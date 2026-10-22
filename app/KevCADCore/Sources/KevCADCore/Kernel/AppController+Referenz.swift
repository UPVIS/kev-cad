import AppKit
import CoreGraphics
import Foundation
import OCCTSwiftViewport
import simd

// Phase 4: Foto und Video als Referenz im App-Kern (PROTOCOL.md „Phase 4: Referenzen“). Nachrichten REF_*, Netze als
// halbdurchsichtige Körper in der Szene, Fotoansicht (Blick durch die eingepasste Kamera, Foto hinter dem Modell,
// Deckkraft, Differenz rot/blau) und die Aktionen der Oberfläche (Hinzufügen, Vermessen, Maße übernehmen).

/// Zwischenstand der Fotoansicht: Foto, Maske und das gerenderte Modell (Deckung und Farbe) eines Fotos bei einem
/// Stand der Szene. Regler und Modus verrechnen nur neu, ohne neu zu rendern.
final class FotoAbgleichSpeicher {
    var schluessel = ""
    var breite = 0
    var hoehe = 0
    var foto: [UInt8] = []
    var maske: [UInt8]?
    var deckung: [UInt8] = []
    var modell: [UInt8] = []
    var geplant: DispatchWorkItem?
    /// Zählt Änderungen der Szene; gehört zum Schlüssel des gerenderten Modells
    var stand = 0
}

/// Körper der Farbkarte je Feld (Schlüssel, Spanne, Deckkraft), damit nur ein neues Feld oder eine neue Legende neu
/// geschnitten wird; dazu die Körper der Referenznetze je Netz (ein neues REF_UPSERT zählt `netzStand` hoch), damit
/// häufige REF_LIST (Fortschritt) oder ein Regler der Deckkraft nicht jedes Mal das ganze Netz neu aufteilen.
final class AbweichungSpeicher {
    var koerper: [String: [ViewportBody]] = [:]
    var netzStand: [String: Int] = [:]
    var netzKoerper: [String: (stand: Int, koerper: [ViewportBody])] = [:]
}

extension AppController: ReferenzActions {
    var referenzen: ReferenzStore { model.referenzen }

    static let referenzKoerperPrefix = "\u{1F}referenz\u{1F}"
    static let referenzStueck = 16_000

    // MARK: Nachrichten

    func handleReferenz(_ r: ReferenzNachricht) {
        switch r {
        case .liste(let liste):
            let vorher = Dictionary(uniqueKeysWithValues: referenzen.referenzen.map { ($0.name, $0.zustand) })
            referenzen.referenzen = liste
            let namen = Set(liste.map(\.name))
            // Referenzen, die es nicht mehr gibt (anderes Projekt): Netz, Fotos, Ergebnis weg
            for n in Array(referenzen.netze.keys) where !namen.contains(n) { referenzen.netze.removeValue(forKey: n) }
            referenzen.fotos = referenzen.fotos.filter { namen.contains($0.key) }
            referenzen.ergebnisse = referenzen.ergebnisse.filter { namen.contains($0.key) }
            if let a = referenzen.fotoansicht, !namen.contains(a.referenz) { fotoansichtSchliessen() }
            for r in liste where vorher[r.name] == .rechnet && r.zustand != .rechnet {
                log(r.zustand == .fehler ? .warning : .info,
                    "Referenz \(r.name): " + (r.meldung ?? (r.zustand == .fertig ? "fertig" : r.zustand.rawValue)))
            }
            // Felder der Abweichung nur für den aktuellen Stand (Schlüssel in der Kurzfassung) behalten
            let gueltig = Dictionary(uniqueKeysWithValues: liste.map { ($0.name, $0.abweichung?.schluessel ?? []) })
            referenzen.abweichungFelder = referenzen.abweichungFelder.filter { gueltig[$0.value.referenz]?.contains($0.value.feld) == true }
            if let k = referenzen.farbkarte, !namen.contains(k.referenz) { referenzen.farbkarte = nil }
            if let w = referenzen.massstabWerkzeug, !namen.contains(w.referenz) { massstabWerkzeug(nil) }
            referenzKoerperSetzen()
        case .netz(let n):
            referenzen.netze[n.name] = n
            abweichungSpeicher.netzStand[n.name, default: 0] += 1  // Körper des Netzes neu aufteilen
            referenzKoerperSetzen()
            massstabSelbsttestPlanen(n)  // nur Testvariante mit KEVCAD_SELFTEST=massstab
            log(.info, "Referenznetz \(n.name): \(KevFormat.integer(n.triangleCount)) Dreiecke")
        case .entfernen(let name):
            referenzen.netze.removeValue(forKey: name)
            referenzKoerperSetzen()
        case .fotos(let ref, let satz, let fotos):
            var s = referenzen.fotos[ref] ?? [:]
            s[satz] = fotos
            referenzen.fotos[ref] = s
            if let a = referenzen.fotoansicht, a.referenz == ref, a.satz == satz {
                fotoSpeicher.schluessel = ""
                if fotos.isEmpty { fotoansichtSchliessen() } else { fotoNeuRendern(sofort: true) }
            }
        case .ergebnis(let e):
            referenzen.ergebnisse[e.referenz] = e
            log(.info, "Referenz \(e.referenz) vermessen: " + e.masse.map {
                "\($0.name) \(KevFormat.number($0.wert, digits: 1)) ± \(KevFormat.number($0.sigma, digits: 1))"
            }.joined(separator: ", "))
        case .abweichung(let f):
            referenzen.abweichungFelder[f.key] = f
            if referenzen.farbkarte?.referenz == f.referenz { referenzKoerperSetzen() }
        case .scans(let l):
            referenzen.scans = l.scans
            referenzen.scanEmpfaenger = l.empfaengerName
            referenzen.scanEmpfaengerLaeuft = l.empfaengerLaeuft
            referenzen.scanAusgeblendet.formUnion(UserDefaults.standard.stringArray(forKey: Self.scanAusgeblendetKey) ?? [])
            if let u = referenzen.scanUebernahme {
                let laeuft = referenzen.referenzen.contains { $0.istScan && $0.zustand == .rechnet }
                if !(l.scans.first { $0.id == u }?.neu ?? false) || !laeuft { referenzen.scanUebernahme = nil }
            }
            if let neu = l.neu, let s = l.scans.first(where: { $0.id == neu }) {  // gerade per WLAN empfangen
                referenzen.scanAusgeblendet.remove(neu)
                log(.info, "Neuer Scan empfangen: \(s.name) (\(s.fotos) Fotos, \(s.videobilder) Videobilder)")
            }
        }
    }

    static let scanAusgeblendetKey = "KevCAD.scanBandAusgeblendet"

    /// RUN_END: alle param()-Werte merken (für „Vermessen“).
    func referenzParams(_ params: JSONValue?) {
        var p: [String: Double] = [:]
        for (k, v) in params?.objectValue ?? [:] {
            if case .number(let d) = v { p[k] = d }
        }
        referenzen.params = p
    }

    /// Kernel neu verbunden: er schickt die Referenzen neu.
    func referenzenLeeren() {
        referenzen.referenzen = []
        referenzen.netze = [:]
        referenzen.fotos = [:]
        referenzen.ergebnisse = [:]
        referenzen.abweichungFelder = [:]
        referenzen.massstabWerkzeug = nil
        abweichungSpeicher.koerper = [:]
        if referenzen.fotoansicht != nil { fotoansichtSchliessen() }
        referenzKoerperSetzen()
    }

    // MARK: Netze in der Szene

    func referenzKoerperSetzen() {
        var koerper: [ViewportBody] = []
        var verdeckt: Set<String> = []
        var benutzt: Set<String> = []
        let karte = referenzen.farbkarte
        let skala = referenzen.farbkarteSkala ?? 1
        func farbkarte(_ f: ReferenzAbweichungFeld, id: String) -> [ViewportBody] {
            let schl = "\(f.feld)|\(skala)|\(id)"
            benutzt.insert(schl)
            if let k = abweichungSpeicher.koerper[schl] { return k }
            let k = AbweichungGeometrie.koerper(f, skala: skala, id: id)
            abweichungSpeicher.koerper[schl] = k
            return k
        }
        for name in referenzen.netze.keys.sorted() {
            guard let n = referenzen.netze[name], !referenzen.verborgen.contains(name), n.triangleCount > 0 else {
                continue
            }
            if let k = karte, k.referenz == name, k.auf == .referenz, referenzen.massstabWerkzeug == nil,
               let f = referenzen.abweichungFeld(name, .referenz, nil) {
                koerper += farbkarte(f, id: "r\(name)")
                continue
            }
            // Farbkarte auf dem Modell: das halbdurchsichtige Netz derselben Referenz läge über den Farben
            if let k = karte, k.referenz == name, k.auf == .modell, referenzen.massstabWerkzeug?.referenz != name,
               referenzen.referenz(name)?.abweichung != nil {
                continue
            }
            var farbe = SceneStore.linear(n.farbe)
            farbe.w = Float(referenzen.deckkraft(name))
            let stand = abweichungSpeicher.netzStand[name] ?? 0
            var stuecke: [ViewportBody]
            if let c = abweichungSpeicher.netzKoerper[name], c.stand == stand {
                stuecke = c.koerper
            } else {
                stuecke = Self.referenzKoerper(n, farbe: farbe)
                abweichungSpeicher.netzKoerper[name] = (stand, stuecke)
            }
            let anklickbar = referenzen.massstabWerkzeug?.referenz == name
            for i in stuecke.indices {
                stuecke[i].color = farbe
                stuecke[i].isPickable = anklickbar
            }
            koerper += stuecke
        }
        if let k = karte, k.auf == .modell, let kurz = referenzen.referenz(k.referenz)?.abweichung {
            for t in kurz.teile where scene.record(t.teil) != nil && !scene.hidden.contains(t.teil) {
                guard let f = referenzen.abweichungFeld(k.referenz, .modell, t.teil) else { continue }
                koerper += farbkarte(f, id: "m\(t.teil)")
                verdeckt.insert(t.teil)
            }
        }
        abweichungSpeicher.koerper = abweichungSpeicher.koerper.filter { benutzt.contains($0.key) }
        scene.setReferenzBodies(koerper, verdeckt: verdeckt)
    }

    /// Netz als Körper (Stücke bis 16 000 Dreiecke); anklickbar nur für das Werkzeug „Maßstab setzen“.
    nonisolated static func referenzKoerper(_ n: ReferenzNetz, farbe: SIMD4<Float>, anklickbar: Bool = false)
        -> [ViewportBody]
    {
        var out: [ViewportBody] = []
        let nt = n.triangleCount
        var start = 0
        var stueck = 0
        while start < nt {
            let ende = min(nt, start + referenzStueck)
            var karte: [UInt32: UInt32] = [:]
            var vd: [Float] = []
            var idx: [UInt32] = []
            idx.reserveCapacity((ende - start) * 3)
            for t in start..<ende {
                for k in 0..<3 {
                    let v = n.triangles[t * 3 + k]
                    if let neu = karte[v] {
                        idx.append(neu)
                    } else {
                        let neu = UInt32(vd.count / 6)
                        karte[v] = neu
                        let i = Int(v) * 3
                        vd += [n.positions[i], n.positions[i + 1], n.positions[i + 2], n.normals[i], n.normals[i + 1],
                               n.normals[i + 2]]
                        idx.append(neu)
                    }
                }
            }
            out.append(ViewportBody(
                id: referenzKoerperPrefix + n.name + "\u{1F}\(stueck)", vertexData: vd, indices: idx, edges: [],
                color: farbe, roughness: 0.7, isPickable: anklickbar))
            start = ende
            stueck += 1
        }
        return out
    }

    // MARK: ReferenzActions

    public func referenzHinzufuegen(
        _ urls: [URL], name: String?, masz: [String: Double]?, auflage: Bool, von: Double?, bis: Double?,
        einstellung: String
    ) {
        guard !urls.isEmpty else { return }
        let msg = ReferenzHinzufuegenMessage(
            id: nextRequestID(), pfade: urls.map(\.path), name: name?.isEmpty == false ? name : nil,
            masz: masz?.isEmpty == false ? masz : nil, auflage: auflage, von: von, bis: bis, einstellung: einstellung)
        request(msg, timeout: 60) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)):
                self.referenzen.meldung = a.message
                self.log(a.ok ? .info : .warning, "Referenz hinzufügen: \(a.message ?? "")")
            case .success(.error(let e)):
                self.referenzen.meldung = e.message
                self.log(.error, "Referenz hinzufügen: \(e.message)")
            case .success: break
            case .failure(let e):
                self.referenzen.meldung = e.message
                self.log(.error, "Referenz hinzufügen: \(e.message)")
            }
        }
    }

    public func referenzVermessen(_ name: String, frei: [String]?, bekannt: [String: Double], bilder: Int) {
        let msg = ReferenzVermessenMessage(
            id: nextRequestID(), referenz: name, frei: frei?.isEmpty == false ? frei : nil, bekannt: bekannt,
            bilder: bilder)
        request(msg, timeout: 30) { [weak self] result in
            guard let self else { return }
            if case .success(.ack(let a)) = result, !a.ok {
                self.referenzen.meldung = a.message
                self.log(.warning, "Vermessen: \(a.message ?? "abgelehnt")")
            } else if case .failure(let e) = result {
                self.log(.error, "Vermessen: \(e.message)")
            }
        }
        log(.info, "Referenz \(name) wird vermessen" + (frei.map { ": " + $0.joined(separator: ", ") } ?? ""))
    }

    public func referenzMasseUebernehmen(_ name: String, werte: [String: Double]) {
        guard !werte.isEmpty else { return }
        request(ReferenzUebernehmenMessage(id: nextRequestID(), referenz: name, werte: werte), timeout: 30) {
            [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)):
                self.referenzen.meldung = a.message
                self.log(a.ok ? .info : .warning, a.message ?? "Maße übernommen")
            case .success(.error(let e)):
                self.referenzen.meldung = e.message
                self.log(.error, "Maße übernehmen: \(e.message)")
            case .success: break
            case .failure(let e):
                self.referenzen.meldung = e.message
                self.log(.error, "Maße übernehmen: \(e.message)")
            }
        }
    }

    public func referenzNetzZeigen(_ name: String, _ sichtbar: Bool) {
        if sichtbar { referenzen.verborgen.remove(name) } else { referenzen.verborgen.insert(name) }
        referenzKoerperSetzen()
    }

    public func referenzNetzDeckkraft(_ name: String, _ wert: Double) {
        referenzen.deckkraft[name] = min(max(wert, 0.05), 1)
        referenzKoerperSetzen()
    }

    public func referenzImFinder(_ name: String) {
        guard let p = model.project?.path else { return }
        let url = p.appendingPathComponent("referenzen", isDirectory: true).appendingPathComponent(name)
        revealFiles([url])
    }

    // MARK: Abweichung, Maßstab, Scans (Rest von Phase 4)

    public func farbkarteZeigen(_ name: String?, auf: ReferenzAbweichungFeld.Auf) {
        if let name {
            referenzen.farbkarte = FarbkarteAnzeige(referenz: name, auf: auf, skala: referenzen.farbkarte?.skala)
            if auf == .referenz { referenzen.verborgen.remove(name) }
        } else {
            referenzen.farbkarte = nil
        }
        let t0 = CACurrentMediaTime()
        referenzKoerperSetzen()
        referenzSzeneGeaendert()
        log(.info, "Farbkarte " + (name.map { "\($0) auf \(auf == .modell ? "dem Modell" : "dem Netz")" } ?? "aus")
            + " in \(Int((CACurrentMediaTime() - t0) * 1000)) ms")
    }

    public func farbkarteSkala(_ mm: Double?) {
        guard var k = referenzen.farbkarte else { return }
        k.skala = mm.map { max(0.05, $0) }
        referenzen.farbkarte = k
        referenzKoerperSetzen()
    }

    public func massstabWerkzeug(_ name: String?) {
        referenzen.massstabWerkzeug = name.map { MassstabWerkzeug(referenz: $0) }
        if let name { referenzen.verborgen.remove(name) }
        scene.setTeileAnklickbar(name == nil)  // Klicks gehen durch das Modell aufs Netz
        referenzKoerperSetzen()
        refreshOverlay()
    }

    /// Klick im Viewport, solange „Maßstab setzen“ läuft: Punkt am Referenznetz merken (zwei Punkte, ein dritter
    /// beginnt neu). true = verbraucht.
    func massstabKlick(_ pick: PickResult?, _ punkt: SIMD3<Float>?) -> Bool {
        guard var w = referenzen.massstabWerkzeug else { return false }
        guard let pick, pick.bodyID.hasPrefix(Self.referenzKoerperPrefix + w.referenz + "\u{1F}"), let punkt else {
            referenzen.meldung = "Maßstab: bitte einen Punkt am Referenznetz \(w.referenz) anklicken"
            return true
        }
        if w.punkte.count >= 2 { w.punkte = [] }
        w.punkte.append(punkt)
        referenzen.massstabWerkzeug = w
        referenzen.meldung = nil
        refreshOverlay()
        return true
    }

    func massstabOverlay() -> [OverlayPrimitive] {
        guard let w = referenzen.massstabWerkzeug else { return [] }
        let farbe = SIMD4<Float>(0.93, 0.45, 0.05, 1)
        var out: [OverlayPrimitive] = w.punkte.map { .dot(point: $0, color: farbe, radius: 5) }
        if w.punkte.count == 2, let d = w.abstand {
            out.append(.dimension(a: w.punkte[0], b: w.punkte[1], text: KevFormat.number(d, digits: 1) + " mm am Netz",
                                  color: farbe))
        }
        return out
    }

    public func massstabSetzen(_ name: String, mm: Double, punkte: [SIMD3<Float>]?, kante: String?) {
        let msg = ReferenzMassstabMessage(id: nextRequestID(), referenz: name, punkte: punkte, kante: kante, mm: mm)
        request(msg, timeout: 60) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)):
                self.referenzen.meldung = a.message
                self.log(a.ok ? .info : .warning, "Maßstab: \(a.message ?? "")")
                if a.ok { self.massstabWerkzeug(nil) }
            case .success(.error(let e)):
                self.referenzen.meldung = e.message
                self.log(.error, "Maßstab: \(e.message)")
            case .success: break
            case .failure(let e):
                self.referenzen.meldung = e.message
                self.log(.error, "Maßstab: \(e.message)")
            }
        }
    }

    public func scanUebernehmen(_ id: String, schnell: Bool) {
        referenzen.scanUebernahme = id
        request(ScanImportMessage(id: nextRequestID(), scan: id, schnell: schnell), timeout: 60) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)):
                self.referenzen.meldung = a.message
                self.log(a.ok ? .info : .warning, "Scan übernehmen: \(a.message ?? "")")
                if !a.ok { self.referenzen.scanUebernahme = nil }
            case .success(.error(let e)):
                self.referenzen.meldung = e.message
                self.referenzen.scanUebernahme = nil
            case .success: break
            case .failure(let e):
                self.referenzen.meldung = e.message
                self.referenzen.scanUebernahme = nil
            }
        }
    }

    public func scanBandAusblenden(_ id: String) {
        referenzen.scanAusgeblendet.insert(id)
        var alle = UserDefaults.standard.stringArray(forKey: Self.scanAusgeblendetKey) ?? []
        if !alle.contains(id) { alle.append(id) }
        UserDefaults.standard.set(Array(alle.suffix(200)), forKey: Self.scanAusgeblendetKey)
    }

    // MARK: Fotoansicht

    public func fotoansichtOeffnen(_ name: String, satz: String, index: Int) {
        let liste = referenzen.fotoSatz(name, satz)
        guard !liste.isEmpty else {
            log(.info, "Referenz \(name): keine Fotos mit Kamera (erst vermessen)")
            return
        }
        let vorher = referenzen.fotoansicht
        referenzen.fotoansicht = FotoAnsicht(
            referenz: name, satz: satz, index: min(max(index, 0), liste.count - 1),
            deckkraft: vorher?.deckkraft ?? 0.55,
            modus: vorher?.modus ?? (liste.first?.maske != nil ? .ueberlagern : .ueberlagern))
        fotoSpeicher.schluessel = ""
        fotoNeuRendern(sofort: true)
    }

    public func fotoansichtSchliessen() {
        referenzen.fotoansicht = nil
        referenzen.fotoBild = nil
        referenzen.fotoUeberdeckung = nil
        referenzen.fotoMeldung = nil
        fotoSpeicher.geplant?.cancel()
        fotoSpeicher.schluessel = ""
        fotoSpeicher.foto = []
        fotoSpeicher.modell = []
        fotoSpeicher.deckung = []
        fotoSpeicher.maske = nil
    }

    public func fotoWechseln(_ schritt: Int) {
        guard var a = referenzen.fotoansicht else { return }
        let n = referenzen.fotoSatz(a.referenz, a.satz).count
        guard n > 0 else { return }
        a.index = ((a.index + schritt) % n + n) % n
        referenzen.fotoansicht = a
        fotoNeuRendern(sofort: true)
    }

    public func fotoDeckkraft(_ wert: Double) {
        guard var a = referenzen.fotoansicht else { return }
        a.deckkraft = min(max(wert, 0), 1)
        referenzen.fotoansicht = a
        fotoVerrechnen()
    }

    public func fotoModus(_ modus: FotoAnsicht.Modus) {
        guard var a = referenzen.fotoansicht else { return }
        a.modus = modus
        referenzen.fotoansicht = a
        fotoVerrechnen()
    }

    /// Die Szene hat sich geändert (Lauf, Sichtbarkeit): in der Fotoansicht das Modell neu rendern (gebündelt).
    func referenzSzeneGeaendert() {
        guard referenzen.fotoansicht != nil else { return }
        fotoSpeicher.stand += 1
        fotoNeuRendern(sofort: false)
    }

    func fotoNeuRendern(sofort: Bool) {
        fotoSpeicher.geplant?.cancel()
        let arbeit = DispatchWorkItem { [weak self] in
            MainActor.assumeIsolated { self?.fotoRendern() }
        }
        fotoSpeicher.geplant = arbeit
        DispatchQueue.main.asyncAfter(deadline: .now() + (sofort ? 0.01 : 0.25), execute: arbeit)
    }

    /// Foto laden, Modell durch die Kamera rendern (auf Weiß und auf Schwarz), dann verrechnen.
    func fotoRendern() {
        guard let a = referenzen.fotoansicht, let foto = referenzen.aktuellesFoto else { return }
        let t0 = CACurrentMediaTime()
        let k = foto.kamera
        let schluessel = "\(a.referenz)/\(a.satz)/\(foto.name)/\(fotoSpeicher.stand)"
        let w = k.breite, h = k.hoehe
        if fotoSpeicher.schluessel != schluessel || fotoSpeicher.breite != w || fotoSpeicher.hoehe != h {
            guard let bild = FotoAbgleich.laden(foto.bild) else {
                referenzen.fotoMeldung = "Foto nicht lesbar: \(foto.bild.lastPathComponent)"
                referenzen.fotoBild = nil
                return
            }
            let leinwand = FotoAbgleich.leinwand(k)
            let zustand = FotoAbgleich.kameraZustand(k, hoehe: leinwand.hoehe)
            let koerper = scene.snapshotBodies(applySection: false).filter {
                !$0.id.hasPrefix(Self.referenzKoerperPrefix) && !$0.id.hasPrefix("snap\u{1F}" + Self.referenzKoerperPrefix)
            }
            let alteFarbe = screenshots.backgroundColor
            defer { screenshots.backgroundColor = alteFarbe }
            func render(_ grund: SIMD4<Float>) -> [UInt8]? {
                screenshots.backgroundColor = grund
                guard let r = screenshots.render(
                    bodies: koerper, camera: zustand, width: leinwand.breite, height: leinwand.hoehe,
                    displayMode: .shaded, lighting: viewport.controller.lightingConfiguration),
                    let teil = FotoAbgleich.ausschnitt(r.image, leinwand, breite: w, hoehe: h)
                else { return nil }
                return FotoAbgleich.pixel(teil, breite: w, hoehe: h)
            }
            guard let weiss = render(SIMD4(1, 1, 1, 1)), let schwarz = render(SIMD4(0, 0, 0, 1)) else {
                referenzen.fotoMeldung = "Modell ließ sich nicht rendern"
                return
            }
            let t1 = CACurrentMediaTime()
            fotoSpeicher.foto = FotoAbgleich.pixel(bild, breite: w, hoehe: h)
            fotoSpeicher.maske = foto.maske.flatMap(FotoAbgleich.laden).map { FotoAbgleich.grau($0, breite: w, hoehe: h) }
            fotoSpeicher.deckung = FotoAbgleich.deckung(weiss: weiss, schwarz: schwarz)
            fotoSpeicher.modell = schwarz
            fotoSpeicher.breite = w
            fotoSpeicher.hoehe = h
            fotoSpeicher.schluessel = schluessel
            let t2 = CACurrentMediaTime()
            fotoVerrechnen()
            log(.info, "Fotoansicht \(foto.name): Modell gerendert in \(Int((t1 - t0) * 1000)) ms, Foto und Maske "
                + "\(Int((t2 - t1) * 1000)) ms, verrechnet \(Int((CACurrentMediaTime() - t2) * 1000)) ms")
            return
        }
        fotoVerrechnen()
    }

    func fotoVerrechnen() {
        guard let a = referenzen.fotoansicht, !fotoSpeicher.foto.isEmpty else { return }
        let modus: FotoAnsicht.Modus = fotoSpeicher.maske == nil ? .ueberlagern : a.modus
        let e = FotoAbgleich.verrechnen(
            foto: fotoSpeicher.foto, deckung: fotoSpeicher.deckung, modell: fotoSpeicher.modell,
            maske: fotoSpeicher.maske, deckkraft: a.deckkraft, modus: modus)
        referenzen.fotoBild = FotoAbgleich.bild(e.pixel, breite: fotoSpeicher.breite, hoehe: fotoSpeicher.hoehe)
        referenzen.fotoUeberdeckung = e.ueberdeckung
        referenzen.fotoMeldung = a.modus == .differenz && fotoSpeicher.maske == nil
            ? "Für dieses Foto gibt es keine Maske (Object Capture): nur Überlagern" : nil
    }
}


// MARK: - Fotoansicht für den Agenten (VIEW_CMD referenz_foto, SCREENSHOT_REQ source "referenz_foto")

extension AppController {
    /// VIEW_CMD `referenz_foto`: Fotoansicht öffnen (name, satz, index oder foto, modus, deckkraft) oder schließen (aus).
    func performReferenzCommand(_ v: ViewCommandMessage) -> (Bool, String?)? {
        if v.cmd == "referenz_abweichung" {  // Rest von Phase 4: Farbkarte an oder aus (MCP referenz_abweichung)
            let an = v.args["an"]?.boolValue ?? true
            let auf = ReferenzAbweichungFeld.Auf(rawValue: v.args["auf"]?.stringValue ?? "") ?? .modell
            guard an else {
                farbkarteZeigen(nil, auf: auf)
                return (true, "Farbkarte aus")
            }
            guard let name = v.args["name"]?.stringValue ?? referenzen.referenzen.first(where: { $0.abweichung != nil })?.name,
                  referenzen.referenz(name) != nil
            else { return (false, "Keine Referenz mit Abweichung") }
            farbkarteZeigen(name, auf: auf)
            let skala = referenzen.farbkarteSkala.map { KevFormat.number($0, digits: 1) } ?? "?"
            return (true, "Farbkarte \(name) auf \(auf == .modell ? "dem Modell" : "dem Netz"), Legende ±\(skala) mm")
        }
        guard v.cmd == "referenz_foto" else { return nil }
        let a = v.args
        if a["aus"]?.boolValue == true {
            fotoansichtSchliessen()
            return (true, "Fotoansicht geschlossen")
        }
        let erste = referenzen.referenzen.first(where: { !referenzen.fotos($0.name).isEmpty })?.name
        guard let name = a["name"]?.stringValue ?? erste else { return (false, "Keine Referenz mit Fotos") }
        let satz = a["satz"]?.stringValue ?? (referenzen.fotoSatz(name, "messung").isEmpty ? "capture" : "messung")
        let liste = referenzen.fotoSatz(name, satz)
        guard !liste.isEmpty else { return (false, "Referenz \(name) hat keine Fotos im Satz \(satz)") }
        var index = a["index"]?.intValue ?? 0
        if let f = a["foto"]?.stringValue, let i = liste.firstIndex(where: { $0.name == f }) { index = i }
        fotoansichtOeffnen(name, satz: satz, index: index)
        if let m = a["modus"]?.stringValue, let modus = FotoAnsicht.Modus(rawValue: m) { fotoModus(modus) }
        if let d = a["deckkraft"]?.doubleValue { fotoDeckkraft(d) }
        fotoSpeicher.geplant?.cancel()
        fotoRendern()
        guard let ansicht = referenzen.fotoansicht, let foto = referenzen.aktuellesFoto else {
            return (false, "Fotoansicht nicht geöffnet")
        }
        var text = "Fotoansicht \(name): Foto \(ansicht.index + 1) von \(liste.count) (\(foto.name)), "
            + (ansicht.modus == .differenz ? "Differenz" : "Überlagern")
        if let iou = referenzen.fotoUeberdeckung {
            text += ", Überdeckung Modell und Maske \(KevFormat.number(iou * 100, digits: 1)) %"
        }
        if let m = referenzen.fotoMeldung { text += " (\(m))" }
        return (true, text)
    }

    /// SCREENSHOT_REQ mit `source: "referenz_foto"`: das Bild der offenen Fotoansicht (Foto mit Modell bzw. Differenz).
    func answerFotoScreenshot(_ s: ScreenshotRequestMessage) -> Bool {
        guard s.source == "referenz_foto" else { return false }
        if referenzen.fotoansicht != nil, fotoSpeicher.foto.isEmpty { fotoRendern() }
        guard referenzen.fotoansicht != nil, let bild = referenzen.fotoBild else {
            send(ScreenshotResponseMessage(
                replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                message: "Keine Fotoansicht offen (erst referenz_fotoansicht)"))
            return true
        }
        var out = bild
        let w = max(16, min(s.width, bild.width))
        if w < bild.width {
            let h = max(16, Int((Double(bild.height) * Double(w) / Double(bild.width)).rounded()))
            if let space = CGColorSpace(name: CGColorSpace.sRGB),
               let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: space,
                                   bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) {
                ctx.interpolationQuality = .high
                ctx.draw(bild, in: CGRect(x: 0, y: 0, width: w, height: h))
                out = ctx.makeImage() ?? bild
            }
        }
        guard let png = ScreenshotRenderer.pngData(out) else {
            send(ScreenshotResponseMessage(
                replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil, message: "PNG fehlgeschlagen"))
            return true
        }
        var info: [String: JSONValue] = ["foto": .string(referenzen.aktuellesFoto?.name ?? "")]
        if let iou = referenzen.fotoUeberdeckung { info["ueberdeckung"] = .number(iou) }
        send(ScreenshotResponseMessage(
            replyTo: s.id, ok: true, width: out.width, height: out.height, camera: .object(info), mmPerPx: nil),
             payload: png)
        return true
    }
}
