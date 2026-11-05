import Foundation
import simd

/// V2-5: Was die App für das Live-Protokoll führt (PROTOCOL.md, „V2-5 Live“). Alles gilt für eine Verbindung.
@MainActor
final class LiveZustand {
    /// Ein Delta-Lauf dunkelt seine offenen Teile erst nach dieser Zeit ab: Ein unveränderter Lauf bleibt ganz ruhig.
    static let abdunkelnNachS: TimeInterval = 2.0

    /// Fähigkeiten des Kernels aus HELLO.
    var kernelFaehigkeiten: Set<String> = []
    /// Inhalte je Teil (der Kernel führt dieselbe Liste).
    var inhalte = TeilInhalte()
    /// Laufender Lauf mit `delta: true`.
    var deltaLauf: Int?
    /// Teile, die beim Stapelende mit PARTS_REQ nachgefragt werden, und schon nachgefragte.
    var nachzufragen: [String] = []
    var nachgefragt: Set<String> = []
    /// Bestätigte Teile haben das Bild geändert (einmal je Stapel weitergeben) bzw. stehen noch nicht in `model.parts`.
    var bildGeaendert = false
    var teileGeaendert = false

    /// Beide Seiten können `delta-1`.
    var deltaAktiv: Bool {
        kernelFaehigkeiten.contains(LiveFaehigkeit.delta) && LiveFaehigkeit.app.contains(LiveFaehigkeit.delta)
    }

    func teilWeg(_ name: String) {
        inhalte.vergessen(name)
        nachgefragt.remove(name)
    }

    func projektGewechselt(_ statik: StatikStore) { statik.feldVorrat = [:] }
}

extension AppController {
    // MARK: Verbindung

    /// HELLO: Eine neue Verbindung beginnt leer (Basen für WIE_ZUVOR leert die Verbindung selbst).
    func neueVerbindung(_ h: HelloMessage) {
        live.kernelFaehigkeiten = Set(h.faehigkeiten ?? [])
        live.inhalte.leeren()
        live.deltaLauf = nil
        live.nachzufragen = []
        live.nachgefragt = []
        model.statik.feldVorrat = [:]
    }

    /// WIE_ZUVOR ohne passende Basis: verwerfen, die Nachricht vollständig neu anfordern.
    func basisFehlt(art: String, grund: String) {
        log(.warning, "\(grund), fordere neu an")
        guard LiveGrenzen.wieZuvorArten.contains(art) else { return }
        send(NochmalMessage(art: art))
    }

    // MARK: Teile

    /// PART_UPSERT: Inhalt merken; eine Nachfrage nach diesem Teil ist erledigt.
    func teilGekommen(_ record: PartRecord) {
        live.inhalte.merken(record)
        live.nachgefragt.remove(record.name)
        scene.setStale(record.name, false)
    }

    /// PART_SAME (PROTOCOL.md, „Delta“). Fehlt der Inhalt, bleibt das alte Teil dunkel stehen, bis der Kernel es neu
    /// geschickt hat: lieber kurz dunkel als ein falsches Teil.
    func applyPartSame(_ m: PartSameMessage) {
        guard var gespeichert = live.inhalte.zeigen(m.name, m.inhalt) else {
            log(.warning, "Inhalt \(m.inhalt) von \(m.name) fehlt, fordere das Teil neu an")
            nachfragen(m.name)
            scene.setStale(m.name, true)
            return
        }
        if scene.record(m.name)?.header.inhalt == m.inhalt {
            if scene.confirm(m.name, run: m.run) { live.bildGeaendert = true }
            live.teileGeaendert = true
        } else {
            gespeichert.header.run = m.run  // ein früherer Inhalt: Kopf und Netz tauschen, nichts wird übertragen
            handlePart(gespeichert)
        }
    }

    private func nachfragen(_ name: String) {
        guard live.nachgefragt.insert(name).inserted else { return }
        live.nachzufragen.append(name)
    }

    /// RUN_END.teile: Jedes Teil, das nicht in der Liste steht, geht; fehlt der App ein genanntes, fragt sie es nach.
    func teileNachLauf(_ teile: [String]) {
        let bleiben = Set(teile)
        for n in scene.order where !bleiben.contains(n) {
            live.teilWeg(n)
            scene.remove(n)
        }
        for n in teile where scene.record(n) == nil { nachfragen(n) }
    }

    /// Ende eines Stapels: Bestätigtes einmal anzeigen, Fehlendes in einer Anfrage nachfragen.
    func liveStapelEnde() {
        if live.bildGeaendert {
            live.bildGeaendert = false
            scene.publishChanges()
        }
        if live.teileGeaendert {
            live.teileGeaendert = false
            updateParts()
            refreshOverlay()
        }
        if !live.nachzufragen.isEmpty {
            let namen = live.nachzufragen
            live.nachzufragen = []
            send(PartsRequestMessage(teile: namen))
        }
    }

    // MARK: Lauf

    /// RUN_START mit `delta: true`: Teile, Auswahl und Hervorhebung bleiben stehen; offene Teile dunkeln erst ab, wenn
    /// der Lauf länger dauert.
    func deltaLaufBeginn(_ run: Int) {
        live.deltaLauf = run
        scene.beginDeltaRun(run)
        measurePending = []
        updateMeasureHint()
        DispatchQueue.main.asyncAfter(deadline: .now() + LiveZustand.abdunkelnNachS) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.live.deltaLauf == run else { return }
                self.scene.dimOpenParts(run: run)
            }
        }
    }

    /// RUN_END und RUN_ERROR: Die Auswahl gilt für den neuen Lauf; der Kernel bekommt sie mit der neuen Laufnummer.
    func deltaLaufEnde() {
        guard live.deltaLauf != nil else { return }
        live.deltaLauf = nil
        guard !scene.selection.isEmpty || !model.selection.isEmpty else { return }
        model.selection = scene.selection.compactMap { r in scene.record(r.part)?.selectionItem(for: r) }
        send(SelectionMessage(run: scene.latestRun, refs: scene.selection.map(\.string)))
    }

    /// Im Delta-Lauf bleibt die Auswahl stehen. Flächen und Kanten eines geänderten Teils können aber etwas anderes
    /// meinen: nur das ganze Teil bleibt.
    func elementeVerwerfen(_ name: String) {
        guard scene.selection.contains(where: { $0.part == name && $0.kind != .part }) else { return }
        applySelection(scene.selection.filter { !($0.part == name && $0.kind != .part) }, notifyKernel: false)
    }

    // MARK: Versionsbild

    /// VERSION_BILD_REQ: Köpfe mit `aus_szene` bekommen ihr Netz aus den Inhalten, so wie sie beim Empfang stehen.
    func versionsbildTeile(_ b: VersionBildAnfrage) -> [VersionBildAnfrage.Teil] {
        b.teile.compactMap { t in
            guard let inhalt = t.ausSzene else { return t }
            guard let r = live.inhalte.inhalt(t.teil, inhalt) else {
                log(.warning, "Vorschaubild V\(b.nr): Inhalt \(inhalt) von \(t.teil) fehlt, Teil fehlt im Bild")
                return nil
            }
            var neu = t
            let g = r.geometry
            neu.netz = VergleichsNetz(
                teil: t.teil, art: "alt", positions: g.positions, normals: g.normals, triangles: g.triangles,
                edgePoints: g.edgePoints, edgeOffsets: g.edgeOffsets)
            return neu
        }
    }
}
