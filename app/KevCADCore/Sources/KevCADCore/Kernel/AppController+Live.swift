#if os(macOS)
import AppKit
#endif
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// V2-5: Was die App für das Live-Protokoll führt (PROTOCOL.md, „V2-5 Live“). Alles gilt für eine Verbindung.
@MainActor
final class LiveZustand {
    /// Ein Delta-Lauf dunkelt seine offenen Teile erst nach dieser Zeit ab: Ein unveränderter Lauf bleibt ganz ruhig.
    static let abdunkelnNachS: TimeInterval = 2.0

    /// IN_ARBEIT kommt nach 0,3 s ohne Teil; markiert wird erst nach dieser Zeit mehr: Ein schneller Lauf bleibt ruhig.
    var inArbeitNachS: TimeInterval = 0.4

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

    /// PART_SAME eines anderen Inhalts, der erst zum Laufende angezeigt wird (Teilname → Inhalt mit dem neuen Lauf): Zeigt
    /// model.py ein Teil im Lauf mehrmals (Zwischenstände), wäre sonst jeder Lauf ein Sprung hin und zurück.
    var offeneWechsel: [String: PartRecord] = [:]
    /// Teil aus IN_ARBEIT, dessen Markierung noch aussteht.
    var inArbeitWartet: String?
    /// `stand` der letzten Antwort auf das stille Nachladen des Katalogs.
    var katalogStand: String?
    /// Letzter Treffer unter der Maus (fürs Lagebild); nil, wenn die Maus nicht über einem Teil steht.
    var maus: MausStand?
    /// Maße und Hervorhebungen mit `dauer_s` (Schlüssel: Kennung).
    var anmerkungAblauf: [String: Ablauf] = [:]
    var hervorhebungAblauf: [String: Ablauf] = [:]
    var ablaufTimer: Timer?

    struct MausStand {
        var pick: PickResult
        var welt: SIMD3<Float>?
        /// Bildpunkt, Ursprung oben links
        var bild: CGPoint
    }

    /// Ablauf einer Anzeige; in den letzten `ausblendenS` Sekunden wird sie sanft durchsichtig.
    struct Ablauf {
        static let ausblendenS: CFTimeInterval = 0.5
        var ende: CFTimeInterval

        func deckkraft(_ now: CFTimeInterval) -> Float {
            Float(max(0, min(1, (ende - now) / Self.ausblendenS)))
        }
    }

    /// Nächster Zeitpunkt, zu dem sich an den Anzeigen etwas ändert (im Ausblenden 30-mal je Sekunde).
    func naechsterAblauf(_ now: CFTimeInterval) -> CFTimeInterval? {
        let alle = Array(anmerkungAblauf.values) + Array(hervorhebungAblauf.values)
        return alle.map { a in
            let beginn = a.ende - Ablauf.ausblendenS
            return now < beginn ? beginn : min(a.ende, now + 1.0 / 30)
        }.min()
    }

    /// Beide Seiten können `delta-1`.
    var deltaAktiv: Bool {
        kernelFaehigkeiten.contains(LiveFaehigkeit.delta) && LiveFaehigkeit.app.contains(LiveFaehigkeit.delta)
    }

    func teilWeg(_ name: String) {
        inhalte.vergessen(name)
        nachgefragt.remove(name)
        offeneWechsel[name] = nil
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
        live.offeneWechsel = [:]
        live.katalogStand = nil
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
        live.offeneWechsel[record.name] = nil
        scene.setStale(record.name, false)
        inArbeitEnde(record.name)
    }

    /// PART_SAME (PROTOCOL.md, „Delta“). Fehlt der Inhalt, bleibt das alte Teil dunkel stehen, bis der Kernel es neu
    /// geschickt hat: lieber kurz dunkel als ein falsches Teil.
    func applyPartSame(_ m: PartSameMessage) {
        inArbeitEnde(m.name)
        guard var gespeichert = live.inhalte.zeigen(m.name, m.inhalt) else {
            log(.warning, "Inhalt \(m.inhalt) von \(m.name) fehlt, fordere das Teil neu an")
            nachfragen(m.name)
            scene.setStale(m.name, true)
            return
        }
        if scene.record(m.name)?.header.inhalt == m.inhalt {
            live.offeneWechsel[m.name] = nil
            if scene.confirm(m.name, run: m.run) { live.bildGeaendert = true }
            live.teileGeaendert = true
        } else {
            gespeichert.header.run = m.run  // ein früherer Inhalt: Kopf und Netz tauschen, nichts wird übertragen
            guard scene.record(m.name) != nil else {  // ein Teil, das gerade fehlt, springt nicht
                handlePart(gespeichert)
                return
            }
            live.offeneWechsel[m.name] = gespeichert
        }
    }

    /// Laufende: Offene Wechsel anzeigen, in der Reihenfolge der Szene.
    func inhaltWechseln() {
        guard !live.offeneWechsel.isEmpty else { return }
        let wechsel = live.offeneWechsel
        live.offeneWechsel = [:]
        for n in scene.order { if let r = wechsel[n] { handlePart(r) } }
    }

    /// IN_ARBEIT: Das Teil wird markiert, wenn es nicht gleich kommt.
    func inArbeitMelden(_ teil: String) {
        live.inArbeitWartet = teil
        guard live.inArbeitNachS > 0 else {
            scene.setInArbeit(teil)
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + live.inArbeitNachS) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.live.inArbeitWartet == teil else { return }
                self.scene.setInArbeit(teil)
            }
        }
    }

    /// Markierung beenden: für dieses Teil, das gekommen ist, oder (nil) für alle.
    func inArbeitEnde(_ teil: String?) {
        if teil == nil || live.inArbeitWartet == teil { live.inArbeitWartet = nil }
        if let aktuell = scene.inArbeit, teil == nil || aktuell == teil { scene.setInArbeit(nil) }
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
    // MARK: Lagebild (lage-1)

    /// Letzten Treffer unter der Maus merken: Das Lagebild rendert und pickt nichts.
    func mausMerken(_ pick: PickResult?, _ welt: SIMD3<Float>?, _ bildpunkt: CGPoint?) {
        guard let pick, let bildpunkt else {
            live.maus = nil
            return
        }
        live.maus = LiveZustand.MausStand(pick: pick, welt: welt, bild: bildpunkt)
    }

    /// LAGE_REQ: aus dem, was die App ohnehin weiß, ohne zu rendern.
    func lageBeantworten(_ r: LageRequestMessage) {
        let t0 = CACurrentMediaTime()
        let felder = lagebild()
        send(LageMessage(
            replyTo: r.id, zeit: Date().timeIntervalSince1970, ms: ((CACurrentMediaTime() - t0) * 10000).rounded() / 10,
            felder: felder))
    }

    /// Felder von LAGE ohne `reply_to`, `zeit` und `ms` (PROTOCOL.md, „Lagebild“).
    func lagebild() -> [String: JSONValue] {
        func p(_ v: SIMD3<Float>) -> JSONValue { .array([v.x, v.y, v.z].map { .number(Double($0)) }) }
        func namen(_ n: [String]) -> JSONValue { .array(n.map(JSONValue.string)) }
        let c = viewport.camera
        let groesse = viewport.viewSize
        var felder: [String: JSONValue] = [
            "kamera": .object([
                "position": p(c.position), "ziel": p(c.pivot), "richtung": p(c.viewDirection), "oben": p(c.upVector),
                "abstand": .number(Double(c.distance)), "projektion": .string(c.isOrthographic ? "orthographic" : "perspective"),
                "fov": c.isOrthographic ? .null : .number(Double(c.fieldOfView)),
                "ortho_hoehe": c.isOrthographic ? .number(Double(c.orthographicScale)) : .null,
                "ansicht": ViewportCoordinator.nearestStandardName(c).map(JSONValue.string) ?? .null,
                "durch": cameras.activeView.map { .string($0.hasPrefix("Kamera/") ? $0 : "Kamera/" + $0) } ?? .null,
            ]),
            "viewport": .object(["breite": .number(groesse.width.rounded()), "hoehe": .number(groesse.height.rounded())]),
            "sichtbar": namen(teileImBild()),
            "verborgen": namen(scene.order.filter { !scene.isVisible($0) }),
            "isoliert": scene.isolated.map(namen) ?? .null,
            "auswahl": .object([
                "run": scene.selection.isEmpty ? .null : .number(Double(scene.latestRun)),
                "refs": namen(scene.selection.map(\.string)),
            ]),
            "darstellung": .string(lageDarstellung),
            "explosion": .number(Double(scene.explodeFactor)),
        ]
        felder["maus"] = lageMaus(p) ?? .null
        felder["schnitt"] = scene.section.map { ebene in
            let n = -ebene.normal
            return .object([
                "axis": MirrorService.axisName(n).map(JSONValue.string) ?? .null, "normal": p(n),
                "offset": .number(Double(ebene.distance)),
            ])
        } ?? .null
        let bewegt = model.animation.playing || (model.animation.posed && model.animation.time > 0)  // nur geladen: Ruhelage
        felder["animation"] = model.animation.selected.flatMap { name in
            bewegt ? .object(["name": .string(name), "zeit": .number(model.animation.time), "spielt": .bool(model.animation.playing)]) : nil
        } ?? .null
        felder["flaeche"] = lageFlaeche()  // V2-7
        if AppInfo.isTestVariant {  // Selbsttest (kernel/tools/live_selbsttest.py): was die Szene getan hat
            let z = scene.statistik
            felder["statistik"] = .object([
                "koerper_gebaut": .number(Double(z.koerperGebaut)), "aufleuchten": .number(Double(z.aufleuchten)),
                "weitergaben": .number(Double(z.weitergaben)), "teile": .number(Double(scene.order.count)),
                "spur": .number(Double(model.agentenspur.schritte.count)),
                "marken": .number(Double(befundMarken().count)),
                // V2-7: längste Pause des Hauptfadens seit dem letzten Lagebild, fertige Bilder der zweiten Ansicht
                "pause_ms": .number(hauptfadenPause().rounded()), "zweite_ansicht": .number(Double(zweiterViewer.bilder)),
            ])
        }
        return felder
    }

    /// Name der Darstellung wie in `VIEW_CMD view` (`display`).
    private var lageDarstellung: String {
        switch model.viewer.shading {
        case .material, .technisch: return model.viewer.shading.protokollName
        default: return MirrorService.protocolName(model.displayStyle)
        }
    }

    private func lageMaus(_ p: (SIMD3<Float>) -> JSONValue) -> JSONValue? {
        guard let m = live.maus, let ref = scene.resolve(m.pick) else { return nil }
        return .object([
            "teil": .string(ref.part), "ref": .string(ref.string), "punkt": m.welt.map(p) ?? .null,
            "normale": viewport.surfaceNormal(of: m.pick).map(p) ?? .null,
            "bild": .array([.number(m.bild.x.rounded()), .number(m.bild.y.rounded())]),
        ])
    }

    /// Teile, die gerade im Bild sind: nicht ausgeblendet, Hüllquader im Sichtbereich.
    func teileImBild() -> [String] {
        let c = viewport.camera
        let g = viewport.viewSize
        let seiten = g.height > 0 ? Float(g.width / g.height) : 1
        let vp = c.projectionMatrix(aspectRatio: seiten, near: 0.01, far: 1e7) * c.viewMatrix
        return scene.order.filter { n in
            guard scene.isVisible(n), !scene.animationHidden.contains(n), let b = scene.worldBounds(of: .part(n)) else {
                return false
            }
            return Self.imSichtbereich(b, vp)
        }
    }

    /// Liegt der Quader nicht ganz hinter einer Seite des Sichtbereichs? Prüft in homogenen Koordinaten, damit Ecken
    /// hinter der Kamera nicht täuschen.
    static func imSichtbereich(_ b: BoundingBox, _ vp: simd_float4x4) -> Bool {
        var links = true, rechts = true, unten = true, oben = true, hinten = true
        for i in 0..<8 {
            let q = SIMD3<Float>(i & 1 == 0 ? b.min.x : b.max.x, i & 2 == 0 ? b.min.y : b.max.y, i & 4 == 0 ? b.min.z : b.max.z)
            let k = vp * SIMD4(q, 1)
            if k.x >= -k.w { links = false }
            if k.x <= k.w { rechts = false }
            if k.y >= -k.w { unten = false }
            if k.y <= k.w { oben = false }
            if k.w > 0 { hinten = false }
        }
        return !(links || rechts || unten || oben || hinten)
    }

    // MARK: Live-Maße (live-masse-1)

    /// Farbe nach `annotate.art`: Maß wie eine Messung, geänderter Wert im Akzent, sonst wie bisher.
    static func anmerkungsFarbe(_ art: String?) -> SIMD4<Float> {
        switch art {
        case "mass": return measureColor
        case "param": return ViewerStil.massParameter
        default: return annotationColor
        }
    }

    /// `annotate` mit `dauer_s`: die Anmerkung blendet nach dieser Zeit sanft aus; ohne bleibt sie stehen.
    func anmerkungLaeuftAb(_ id: String, nach dauer: Double?, now: CFTimeInterval = CACurrentMediaTime()) {
        guard let dauer, dauer > 0 else {
            live.anmerkungAblauf[id] = nil
            return
        }
        live.anmerkungAblauf[id] = LiveZustand.Ablauf(ende: now + dauer)
        ablaufPlanen(now)
    }

    /// `highlight` mit `id` und `dauer_s`: nur diese Hervorhebung geht nach Ablauf.
    func hervorhebungLaeuftAb(_ kennung: String, nach dauer: Double, now: CFTimeInterval = CACurrentMediaTime()) {
        live.hervorhebungAblauf[kennung] = LiveZustand.Ablauf(ende: now + dauer)
        ablaufPlanen(now)
    }

    /// Hervorhebung mit ihrer Beschriftung entfernen.
    func hervorhebungEntfernen(_ kennung: String) {
        live.hervorhebungAblauf[kennung] = nil
        for h in scene.highlights where h.kennung == kennung {
            if let a = highlightLabels.removeValue(forKey: h.id) { annotations.removeAll { $0.id == a } }
        }
        scene.removeHighlight(kennung: kennung)
    }

    /// Anmerkungen fürs Bild; die mit Ablauf werden in den letzten Augenblicken durchsichtig.
    func anmerkungenMitAblauf(now: CFTimeInterval = CACurrentMediaTime()) -> [OverlayPrimitive] {
        annotations.filter { anmerkungImBild($0.id) }.map { a in
            guard let ablauf = live.anmerkungAblauf[a.id] else { return a.item }
            return a.item.mitDeckkraft(ablauf.deckkraft(now))
        }
    }

    /// Ausgeblendete Maße (Knopf „Maße“, ⇧M) nehmen die stehenden Einblendungen mit. Kurze mit Ablauf (measure mit
    /// show, view mit dauer_s) und die Beschriftungen von Hervorhebungen bleiben im Bild.
    func anmerkungImBild(_ id: String) -> Bool {
        viewer.masseSichtbar || live.anmerkungAblauf[id] != nil || highlightLabels.values.contains(id)
    }

    /// Stehende Einblendungen des Agenten: ohne Ablauf und keine Beschriftung einer Hervorhebung.
    func stehendeAnmerkungenZaehlen() -> Int {
        let beschriftungen = Set(highlightLabels.values)
        return annotations.filter { live.anmerkungAblauf[$0.id] == nil && !beschriftungen.contains($0.id) }.count
    }

    private func ablaufPlanen(_ now: CFTimeInterval) {
        live.ablaufTimer?.invalidate()
        live.ablaufTimer = nil
        guard let t = live.naechsterAblauf(now) else { return }
        live.ablaufTimer = Timer.scheduledTimer(withTimeInterval: max(0.005, t - now), repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.ablaufSchritt() }
        }
    }

    /// Anzeigen nachführen: Abgelaufene entfernen, Ausblendende neu zeichnen.
    func ablaufSchritt(now: CFTimeInterval = CACurrentMediaTime()) {
        var ueberlagerung = false
        for (id, a) in live.anmerkungAblauf where a.deckkraft(now) < 1 {
            ueberlagerung = true
            if a.ende <= now {
                live.anmerkungAblauf[id] = nil
                annotations.removeAll { $0.id == id }
            }
        }
        for (kennung, a) in live.hervorhebungAblauf where a.deckkraft(now) < 1 {
            ueberlagerung = true
            if a.ende <= now {
                hervorhebungEntfernen(kennung)
            } else {
                scene.setHighlightDeckkraft(kennung, a.deckkraft(now))
            }
        }
        if ueberlagerung { refreshOverlay() }
        ablaufPlanen(now)
    }

    // MARK: Befunde am Teil

    static let maxBefundMarken = 24
    /// Mehr Warnungen zeigen nur noch die ausgewählten Teile: Dutzende Marken wären keine Hilfe, sondern Unruhe.
    static let maxWarnMarken = 6

    /// Befunde der Prüfung als kleine Marke am Teil, Fehler zuerst, je Ort nur eine. Hinweise bleiben in der Liste.
    func befundMarken() -> [OverlayPrimitive] {
        guard model.befundMarkenSichtbar, let p = model.pruefung else { return [] }
        var out: [OverlayPrimitive] = []
        var orte = Set<SIMD3<Int32>>()
        var warnungen = p.befunde.filter { $0.schwere == .warnung }
        if warnungen.count > Self.maxWarnMarken {
            let gewaehlt = Set(scene.selection.map(\.part))
            warnungen = warnungen.filter { !gewaehlt.isDisjoint(with: $0.teile) }
        }
        let befunde = p.befunde.filter { $0.schwere == .fehler } + warnungen
        for b in befunde {
            guard out.count < Self.maxBefundMarken else { break }
            let teile = b.teile.filter { scene.record($0) != nil }
            guard teile.isEmpty || teile.contains(where: scene.isVisible) else { continue }
            guard let ort = b.ort ?? teile.first(where: scene.isVisible).flatMap({ scene.worldAnchor(of: .part($0)) }) else {
                continue
            }
            guard orte.insert(SIMD3<Int32>((ort / 5).rounded(.down))).inserted else { continue }
            out.append(.badge(point: ort, text: "!", color: b.schwere == .fehler ? Self.constraintError : Self.constraintWarning, filled: true))
        }
        return out
    }
}
