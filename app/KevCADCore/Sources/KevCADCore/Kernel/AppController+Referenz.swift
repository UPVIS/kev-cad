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
            referenzKoerperSetzen()
        case .netz(let n):
            referenzen.netze[n.name] = n
            referenzKoerperSetzen()
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
        }
    }

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
        if referenzen.fotoansicht != nil { fotoansichtSchliessen() }
        referenzKoerperSetzen()
    }

    // MARK: Netze in der Szene

    func referenzKoerperSetzen() {
        var koerper: [ViewportBody] = []
        for name in referenzen.netze.keys.sorted() {
            guard let n = referenzen.netze[name], !referenzen.verborgen.contains(name), n.triangleCount > 0 else {
                continue
            }
            var farbe = SceneStore.linear(n.farbe)
            farbe.w = Float(referenzen.deckkraft(name))
            koerper += Self.referenzKoerper(n, farbe: farbe)
        }
        scene.setReferenzBodies(koerper)
    }

    /// Netz als Körper (Stücke bis 16 000 Dreiecke, nicht anklickbar).
    nonisolated static func referenzKoerper(_ n: ReferenzNetz, farbe: SIMD4<Float>) -> [ViewportBody] {
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
                color: farbe, roughness: 0.7, isPickable: false))
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
            fotoSpeicher.foto = FotoAbgleich.pixel(bild, breite: w, hoehe: h)
            fotoSpeicher.maske = foto.maske.flatMap(FotoAbgleich.laden).map { FotoAbgleich.grau($0, breite: w, hoehe: h) }
            fotoSpeicher.deckung = FotoAbgleich.deckung(weiss: weiss, schwarz: schwarz)
            fotoSpeicher.modell = schwarz
            fotoSpeicher.breite = w
            fotoSpeicher.hoehe = h
            fotoSpeicher.schluessel = schluessel
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
