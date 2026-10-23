import AppKit
import Foundation
import OCCTSwiftViewport
import simd

/// Bereich „Simulation“ (PROTOCOL.md „Simulation“, PLAN-SIMULATION.md): SIM und SIM_JOB übernehmen, Werkzeuge im Viewer
/// (Kraft, Lager, Schutzfläche per Klick; Pfeil-Griff einer freien Kraft ziehen), Kräfte, Lager und Flächen als
/// Körper in der Szene, Änderungen als SIM_EDIT, Aufträge als SIM_RUN.
extension AppController: SimulationActions {
    static let simulationPraefix = "\u{1F}simulation\u{1F}"
    // Farben (sRGB): Last blau, Kraftpaar violett, Auswahl und Entwurf orange, Lager je Art, Flächen halbdurchsichtig
    static let simLastFarbe = SIMD4<Float>(0.16, 0.42, 0.92, 1)
    static let simPaarFarbe = SIMD4<Float>(0.62, 0.26, 0.86, 1)
    static let simAuswahlFarbe = SIMD4<Float>(0.98, 0.55, 0.08, 1)
    static let simEntwurfFarbe = SIMD4<Float>(0.98, 0.42, 0.05, 1)
    static let simLagerFarben: [SimLager.Art: SIMD4<Float>] = [
        .fest: SIMD4(0.22, 0.27, 0.36, 1), .gelenkig: SIMD4(0.10, 0.55, 0.58, 1), .gleitend: SIMD4(0.85, 0.62, 0.10, 1),
    ]
    static let simLagerflaeche = SIMD4<Float>(0.30, 0.45, 0.70, 0.42)
    static let simSchutzflaeche = SIMD4<Float>(0.15, 0.72, 0.38, 0.55)
    static let simAbgeleitetFarbe = SIMD4<Float>(0.55, 0.55, 0.58, 1)

    // MARK: Nachrichten

    func applySimulation(_ s: SimStand) {
        let st = model.simulation
        st.stand = s
        if let j = s.job {
            st.job = j
            if !j.laeuft, j.was == "grenze" { st.grenze = j }
        }
        // Auswahl gültig halten: sonst der erste Lastfall der App, sonst der, den die Statik anbietet
        if st.auswahl == nil || !s.alleNamen.contains(st.auswahl ?? "") {
            st.auswahl = s.lastfaelle.first?.name ?? model.statik.ergebnis?.aktiv ?? s.alleNamen.first
        }
        if let neu = st.neueLastErwartet, let lf = st.lastfall, let l = lf.lasten.last, !st.alteLasten.contains(l.id) {
            st.lastAuswahl = l.id
            if neu { st.neueLastErwartet = nil }
        }
        if let e = st.entwurf, let b = e.bearbeitet, st.lastfall?.last(b) == nil { st.entwurf = nil }
        if let teil = st.topologieTeil, st.topologieGeladen != teil { ladeTopologieEinstellungen(teil) }
        updateSimulationAnzeige()
    }

    func applySimulationJob(_ j: SimJob) {
        let st = model.simulation
        st.job = j
        if !j.laeuft {
            if j.was == "grenze", j.stand == "done" { st.grenze = j }
            st.meldung = j.stand == "done" ? j.text : (j.stand == "abgebrochen" ? "Abgebrochen" : (j.meldung ?? j.text))
            st.meldungFehler = j.stand == "failed"
            log(j.stand == "failed" ? .warning : .info, "Simulation \(j.titel): \(st.meldung ?? "")")
        }
    }

    /// Statik: vor dem Übernehmen eines neuen STATICS den bisherigen Stand je Lastfall merken (vorher/nachher).
    func simulationVorherMerken(alt: StatikErgebnis?, neu: StatikErgebnis) {
        guard let alt else { return }
        let st = model.simulation
        for a in alt.szenarien {
            guard let n = neu.szenario(a.name) else { continue }
            if n.urteile != a.urteile || n.teile != a.teile { st.vorher[a.name] = a }
        }
    }

    // MARK: Klick im Viewer

    /// Klick mit aktivem Werkzeug: Entwurf aus Teil, Fläche, Punkt und Normale. true = verbraucht.
    func simulationKlick(_ pick: PickResult?, _ punkt: SIMD3<Float>?) -> Bool {
        let st = model.simulation
        guard st.aktiv, st.werkzeug != .keins else { return false }
        guard let pick, let ref = scene.resolve(pick), scene.record(ref.part) != nil else {
            st.meldung = "Kein Teil getroffen"
            st.meldungFehler = true
            return true
        }
        let flaeche = ref.kind == .face ? ref.index : nil
        let normale = viewport.surfaceNormal(of: pick) ?? flaecheNormale(ref.part, flaeche)
        let p = punkt ?? scene.worldAnchor(of: ref) ?? scene.worldBounds(of: ref)?.center
        simulationOrtGewaehlt(teil: ref.part, flaeche: flaeche, punkt: p, normale: normale)
        return true
    }

    /// Ort aus einem Klick (oder aus dem Selbsttest): je Werkzeug Kraft- bzw. Lagerentwurf, Schutzfläche umschalten.
    public func simulationOrtGewaehlt(teil: String, flaeche: Int?, punkt: SIMD3<Float>?, normale: SIMD3<Float>?) {
        let st = model.simulation
        let ort = SimOrt(flaeche: flaeche, punkt: punkt, normale: normale, signatur: flaecheSignatur(teil, flaeche))
        st.meldung = nil
        st.meldungFehler = false
        switch st.werkzeug {
        case .keins:
            return
        case .kraft:
            guard st.lastfall != nil else {
                st.meldung = "Erst einen Lastfall der App wählen oder anlegen (model.py-Lastfälle: „Als Kopie bearbeiten“)"
                st.meldungFehler = true
                return
            }
            var last = st.entwurf?.last ?? SimLast(
                teil: teil, ort: ort, richtung: SimRichtung(art: normale == nil ? .achse : .normale), betrag: 100)
            last.teil = teil
            last.ort = ort
            if last.richtung.art == .normale && normale == nil { last.richtung.art = .achse }
            if let g = last.gegen, g == teil { last.gegen = nil }
            st.entwurf = SimulationStore.KraftEntwurf(last: last, bearbeitet: st.entwurf?.bearbeitet)
        case .lager:
            var auf = st.lagerAuf
            if auf == .flaeche && flaeche == nil { auf = .punkt }
            st.lagerEntwurf = SimLager(
                id: st.lagerEntwurf?.id ?? "", teil: teil, art: st.lagerArt, auf: auf, ort: ort)
        case .schutz:
            guard let f = flaeche else { return }
            if st.topologieTeil != teil { waehleTopologieTeil(teil) }
            schaltSchutzflaeche(f)
            return
        }
        updateSimulationAnzeige()
    }

    /// Klick auf eine Fläche ohne Maus (Selbsttest, Tests): ein Treffer wie aus dem Pick-Puffer auf einem Dreieck der
    /// Fläche, Weltpunkt in dessen Mitte, dann derselbe Weg wie ein echter Klick (`simulationKlick`).
    @discardableResult
    public func simulationKlickAufFlaeche(teil: String, flaeche: Int) -> Bool {
        guard let rec = scene.record(teil) else { return false }
        let M = scene.worldTransform(teil)
        for chunk in rec.chunks {
            guard let t = (0..<min(chunk.triangleCount, chunk.triFace.count)).first(where: {
                Int(chunk.triFace[$0]) == flaeche
            }) else { continue }
            let id = SceneStore.bodyID(part: teil, chunk: chunk.index)
            guard let index = viewport.bodies.firstIndex(where: { $0.id == id }),
                  let pick = PickResult(rawValue: UInt32(index & 0xFFFF) | (UInt32(t & 0x3FFF) << 16),
                                        indexMap: [index: id])
            else { continue }
            var mitte = SIMD3<Float>.zero
            for j in 0..<3 {
                let k = Int(chunk.indices[t * 3 + j])
                let w = M * SIMD4(chunk.vertexData[k * 6], chunk.vertexData[k * 6 + 1], chunk.vertexData[k * 6 + 2], 1)
                mitte += SIMD3(w.x, w.y, w.z) / 3
            }
            return simulationKlick(pick, mitte)
        }
        return false
    }

    /// Signatur der Fläche wie `PART_UPSERT.faces[i]` (für die Zuordnung nach Modelländerungen).
    func flaecheSignatur(_ teil: String, _ flaeche: Int?) -> JSONValue? {
        guard let f = flaeche, let rec = scene.record(teil), f < rec.header.faces.count,
              let d = try? JSONEncoder().encode(rec.header.faces[f])
        else { return nil }
        return try? JSONDecoder().decode(JSONValue.self, from: d)
    }

    func flaecheNormale(_ teil: String, _ flaeche: Int?) -> SIMD3<Float>? {
        guard let f = flaeche, let rec = scene.record(teil), f < rec.header.faces.count,
              let n = rec.header.faces[f].n, n.count >= 3
        else { return nil }
        return SIMD3(Float(n[0]), Float(n[1]), Float(n[2]))
    }

    // MARK: Griff

    func installSimulationGriff() {
        viewport.onGriffBeginnt = { [weak self] p in self?.simulationGriffBeginnt(p) ?? false }
        viewport.onGriffZiehen = { [weak self] p in self?.simulationGriffZiehen(p) }
        viewport.onGriffEnde = { [weak self] _ in self?.model.simulation.griffAktiv = false }
    }

    /// Länge der Pfeile im Viewer (mm): etwa ein Sechstel der Szene, mindestens 30 mm.
    func simPfeilLaenge() -> Float {
        let d = scene.visibleBounds()?.diagonalLength ?? 400
        return max(30, min(400, d * 0.18))
    }

    /// Ende des Pfeils (Griff) einer Kraft am Punkt `p` in Richtung `d`.
    public func simGriffPunkt() -> SIMD3<Float>? {
        guard let e = model.simulation.entwurf, let p = e.last.ort.punkt, let F = e.kraft, simd_length(F) > 0 else {
            return nil
        }
        return p - simd_normalize(F) * simPfeilLaenge()
    }

    public func simulationGriffBeginnt(_ p: CGPoint) -> Bool {
        let st = model.simulation
        guard st.aktiv, st.entwurf != nil, let g = simGriffPunkt(), let s = viewport.bildpunkt(g) else { return false }
        guard hypot(s.x - p.x, s.y - p.y) <= 14 else { return false }
        st.griffAktiv = true
        return true
    }

    public func simulationGriffZiehen(_ p: CGPoint) {
        let st = model.simulation
        guard var e = st.entwurf, let punkt = e.last.ort.punkt, let g = simGriffPunkt(),
              let w = viewport.weltpunkt(p, durch: g)
        else { return }
        let d = punkt - w
        guard simd_length(d) > 1e-3 else { return }
        let wk = SimKraft.winkel(d)
        e.last.richtung = SimRichtung(art: .frei, achse: e.last.richtung.achse, azimut: (wk.azimut * 10).rounded() / 10,
                                      hoehe: (wk.hoehe * 10).rounded() / 10)
        st.entwurf = e
        updateSimulationAnzeige()
    }

    // MARK: Anzeige

    /// Kräfte des gewählten Lastfalls, Entwurf mit Griff, Lager, Lager- und Schutzflächen als Körper in der Szene;
    /// nur solange der Bereich Simulation vorne ist.
    func updateSimulationAnzeige() {
        let st = model.simulation
        guard st.aktiv else {
            scene.setSimulation(bodies: [])
            return
        }
        var out: [ViewportBody] = []
        let L = simPfeilLaenge()
        let lin = { (c: SIMD4<Float>) in PartBodies.linear(c) }
        if let lf = st.lastfall {
            let fMax = max(lf.lasten.compactMap { $0.kraftWirksam.map(simd_length) }.max() ?? 1, 1e-6)
            for (i, last) in lf.lasten.enumerated() where last.zustand != .fehlt && last.id != st.entwurf?.bearbeitet {
                guard let p = last.punkt, let F = last.kraftWirksam ?? (simd_length(last.kraft) > 0 ? last.kraft : nil)
                else { continue }
                let gewaehlt = last.id == st.lastAuswahl
                let farbe = gewaehlt ? Self.simAuswahlFarbe : (last.paar ? Self.simPaarFarbe : Self.simLastFarbe)
                let l = max(0.35 * L, L * simd_length(F) / fMax)
                out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)l\(i)", punkt: p, kraft: F, laenge: l,
                                                 farbe: lin(farbe)))
                if last.paar {
                    out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)l\(i)g", punkt: p, kraft: -F,
                                                     laenge: l, farbe: lin(farbe)))
                }
            }
        }
        if let e = st.entwurf, let p = e.last.ort.punkt, let F = e.kraft {
            out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)e", punkt: p, kraft: F, laenge: L,
                                             farbe: lin(Self.simEntwurfFarbe)))
            if let g = simGriffPunkt() {  // Griff am Ende des Pfeils: ziehen dreht die Kraft frei
                let d = simd_normalize(F)
                let (vd, idx) = StatikGeometrie.rohr([g - d * 4, g + d * 4], radius: max(5, L * 0.035))
                out.append(ViewportBody(id: "\(Self.simulationPraefix)eg", vertexData: vd, indices: idx, edges: [],
                                        color: lin(SIMD4(1, 1, 1, 1)), roughness: 0.4, isPickable: false))
            }
            if let g = e.last.gegen, scene.record(g) != nil, let p2 = e.last.ort.punkt {
                out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)eG", punkt: p2, kraft: -F,
                                                 laenge: L * 0.7, farbe: lin(Self.simPaarFarbe)))
            }
        }
        if let s = st.stand {
            for (i, l) in (s.lager + s.modellLager).enumerated() where l.zustand != .fehlt {
                out += lagerSymbol(l, id: "a\(i)", groesse: L, lin: lin)
                if l.auf == .flaeche, let f = l.ort.flaeche, scene.record(l.teil) != nil {
                    out += flaechenKoerper(l.teil, f, id: "af\(i)", farbe: lin(Self.simLagerflaeche))
                }
            }
            for (i, a) in s.abgeleitet.enumerated() where a.aktiv && a.art == "boden" {
                guard let p = a.punkt else { continue }
                let h = L * 0.07
                let (vd, idx) = StatikGeometrie.kegel(basis: p - SIMD3(0, 0, h), spitze: p, radius: h * 0.55)
                out.append(ViewportBody(id: "\(Self.simulationPraefix)ab\(i)", vertexData: vd, indices: idx,
                                        edges: [], color: lin(Self.simAbgeleitetFarbe), roughness: 0.6,
                                        isPickable: false))
            }
        }
        if let l = st.lagerEntwurf {
            out += lagerSymbol(l, id: "ae", groesse: L, lin: lin, farbe: Self.simEntwurfFarbe)
            if l.auf == .flaeche, let f = l.ort.flaeche {
                out += flaechenKoerper(l.teil, f, id: "aef", farbe: lin(SIMD4(0.98, 0.55, 0.08, 0.45)))
            }
        }
        if let teil = st.topologieTeil, scene.record(teil) != nil {
            for f in st.schutzFlaechen {
                out += flaechenKoerper(teil, f, id: "s\(f)", farbe: lin(Self.simSchutzflaeche))
            }
        }
        scene.setSimulation(bodies: out)
    }

    /// Lagersymbol am Punkt: Kegel mit der Spitze auf der Fläche (außen), fest mit Platte, gleitend mit abgesetzter
    /// Platte (gleitet längs).
    func lagerSymbol(_ l: SimLager, id: String, groesse L: Float, lin: (SIMD4<Float>) -> SIMD4<Float>,
                     farbe: SIMD4<Float>? = nil) -> [ViewportBody] {
        guard let p = l.punkt else { return [] }
        let n = l.normale.map(simd_normalize) ?? SIMD3(0, 0, -1)
        let h = L * 0.12, r = h * 0.55
        let basis = p + n * h
        let c = lin(farbe ?? Self.simLagerFarben[l.art] ?? Self.simAbgeleitetFarbe)
        var out: [ViewportBody] = []
        let (kd, ki) = StatikGeometrie.kegel(basis: basis, spitze: p, radius: r)
        out.append(ViewportBody(id: "\(Self.simulationPraefix)\(id)k", vertexData: kd, indices: ki, edges: [],
                                color: c, roughness: 0.5, isPickable: false))
        switch l.art {
        case .fest:
            let (vd, idx) = StatikGeometrie.rohr([basis, basis + n * h * 0.22], radius: r * 1.5)
            out.append(ViewportBody(id: "\(Self.simulationPraefix)\(id)p", vertexData: vd, indices: idx, edges: [],
                                    color: c, roughness: 0.5, isPickable: false))
        case .gleitend:
            let (vd, idx) = StatikGeometrie.rohr([basis + n * h * 0.3, basis + n * h * 0.45], radius: r * 1.5)
            out.append(ViewportBody(id: "\(Self.simulationPraefix)\(id)p", vertexData: vd, indices: idx, edges: [],
                                    color: c, roughness: 0.5, isPickable: false))
        case .gelenkig:
            break
        }
        return out
    }

    /// Dreiecke einer Fläche eines Teils als halbdurchsichtiger Körper (etwas nach außen versetzt).
    func flaechenKoerper(_ teil: String, _ flaeche: Int, id: String, farbe: SIMD4<Float>) -> [ViewportBody] {
        guard let rec = scene.record(teil) else { return [] }
        let M = scene.worldTransform(teil)
        var vd: [Float] = []
        for chunk in rec.chunks {
            for t in 0..<chunk.triangleCount where t < chunk.triFace.count && Int(chunk.triFace[t]) == flaeche {
                for j in 0..<3 {
                    let k = Int(chunk.indices[t * 3 + j])
                    let lp = SIMD3(chunk.vertexData[k * 6], chunk.vertexData[k * 6 + 1], chunk.vertexData[k * 6 + 2])
                    let ln = SIMD3(chunk.vertexData[k * 6 + 3], chunk.vertexData[k * 6 + 4], chunk.vertexData[k * 6 + 5])
                    let w = M * SIMD4(lp, 1)
                    let wn4 = M * SIMD4(ln, 0)
                    var wn = SIMD3(wn4.x, wn4.y, wn4.z)
                    if simd_length(wn) > 1e-9 { wn = simd_normalize(wn) }
                    let q = SIMD3(w.x, w.y, w.z) + wn * 0.25
                    vd += [q.x, q.y, q.z, wn.x, wn.y, wn.z]
                }
            }
        }
        guard !vd.isEmpty else { return [] }
        return StatikFeldGeometrie.zerlege(vd, id: "\(Self.simulationPraefix)\(id)", farbe: farbe)
    }

    // MARK: Topologie-Einstellungen

    func ladeTopologieEinstellungen(_ teil: String) {
        let st = model.simulation
        guard let e = st.stand?.topologie[teil] else { return }
        st.topologieGeladen = teil
        st.schutzFlaechen = e.schutz.filter { $0.zustand != .fehlt }.map(\.index)
        st.schutzBohrungen = e.bohrungen ?? true
        st.schutzEinsaetze = e.einsaetze ?? true
        st.schutzKontakt = e.kontakt ?? true
        st.schutzBett = e.bett ?? false
        st.steg = e.steg ?? 6
        let t = model.topologie
        if let b = e.behalten { t.behalten = b }
        if let u = e.ueberhang { t.ueberhang = u }
        if let f = e.fein { t.fein = f }
        t.schraubenHalten = e.lager == "bohrungen"
        t.szenario = e.szenario
    }

    func topologieEinstellungenJSON() -> [String: JSONValue] {
        let st = model.simulation, t = model.topologie
        return [
            "szenario": t.szenario.map(JSONValue.string) ?? .null, "behalten": .number(t.behalten),
            "ueberhang": .bool(t.ueberhang), "fein": .bool(t.fein), "steg": .number(st.steg),
            "bohrungen": .bool(st.schutzBohrungen), "einsaetze": .bool(st.schutzEinsaetze),
            "kontakt": .bool(st.schutzKontakt), "bett": .bool(st.schutzBett),
            "lager": .string(t.schraubenHalten ? "bohrungen" : "kontakt"),
            "schutz": .array(st.schutzFlaechen.map { i in
                var o: [String: JSONValue] = ["art": .string("index"), "index": .number(Double(i))]
                if let teil = st.topologieTeil, let s = flaecheSignatur(teil, i) { o["signatur"] = s }
                return .object(o)
            }),
        ]
    }

    // MARK: SimulationActions

    public func simulationAendern(_ ops: [JSONValue], fertig: ((Bool, String) -> Void)? = nil) {
        let st = model.simulation
        let msg = SimEditMessage(id: nextRequestID(), basis: st.stand?.stand, ops: ops)
        request(msg, timeout: 90) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)):
                st.meldung = a.message
                st.meldungFehler = !a.ok
                if !a.ok { self.log(.warning, "Simulation: \(a.message ?? "")") }
                fertig?(a.ok, a.message ?? "")
            case .success(.error(let e)):
                st.meldung = e.message
                st.meldungFehler = true
                fertig?(false, e.message)
            case .success:
                fertig?(true, "")
            case .failure(let e):
                st.meldung = e.message
                st.meldungFehler = true
                self.log(.error, "Simulation: \(e.message)")
                fertig?(false, e.message)
            }
        }
    }

    public func simulationRechnen(was: String, lastfall: String?, teil: String?, fein: Bool, grenze: String?) {
        let st = model.simulation
        let msg = SimRunMessage(id: nextRequestID(), was: was, lastfall: lastfall, teil: teil, fein: fein,
                                grenze: grenze)
        st.meldung = nil
        request(msg, timeout: 30) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where !a.ok:
                st.meldung = a.message
                st.meldungFehler = true
            case .success(.error(let e)):
                st.meldung = e.message
                st.meldungFehler = true
            case .failure(let e):
                st.meldung = e.message
                st.meldungFehler = true
                self.log(.error, "Simulation: \(e.message)")
            default:
                break
            }
        }
    }

    public func simulationAbbrechen() {
        if !send(SimCancelMessage()) { log(.warning, "Simulation: keine Verbindung zum Kernel") }
    }

    public func waehleLastfall(_ name: String?) {
        let st = model.simulation
        if st.auswahl != name {
            st.entwurf = nil
            st.lastAuswahl = nil
        }
        st.auswahl = name
        if let name, model.statik.ergebnis?.szenario(name) != nil { waehleStatikSzenario(name) }
        updateSimulationAnzeige()
    }

    public func setSimulationAktiv(_ an: Bool) {
        let st = model.simulation
        st.aktiv = an
        if !an, st.werkzeug != .keins { setSimulationWerkzeug(.keins) }
        if an, st.stand == nil { simulationLaden() }
        updateSimulationAnzeige()
    }

    public func setSimulationWerkzeug(_ w: SimulationStore.Werkzeug) {
        let st = model.simulation
        st.werkzeug = w
        if w != .keins, model.measureMode { setMeasureMode(false) }
        viewport.hint = w == .keins ? nil : w.hinweis
        updateSimulationAnzeige()
    }

    public func setKraftEntwurf(_ e: SimulationStore.KraftEntwurf?) {
        model.simulation.entwurf = e
        updateSimulationAnzeige()
    }

    public func setLagerEntwurf(_ l: SimLager?) {
        model.simulation.lagerEntwurf = l
        updateSimulationAnzeige()
    }

    public func kraftEntwurfSpeichern() {
        let st = model.simulation
        guard let e = st.entwurf, let lf = st.lastfall else { return }
        var last = e.last
        if let b = e.bearbeitet { last.id = b }
        guard e.kraft != nil else {
            st.meldung = "Kraft unvollständig: Betrag über 0 und eine Richtung (Normale braucht eine Fläche)"
            st.meldungFehler = true
            return
        }
        st.alteLasten = Set(lf.lasten.map(\.id))
        st.neueLastErwartet = e.bearbeitet == nil ? true : nil
        simulationAendern([SimOp.lastSetzen(lf.name, last)]) { [weak self] ok, _ in
            guard let self, ok else { return }
            st.entwurf = nil
            if let b = e.bearbeitet { st.lastAuswahl = b }
            self.updateSimulationAnzeige()
        }
    }

    public func lagerEntwurfSpeichern() {
        let st = model.simulation
        guard let l = st.lagerEntwurf else { return }
        simulationAendern([SimOp.lagerSetzen(l)]) { [weak self] ok, _ in
            guard let self, ok else { return }
            st.lagerEntwurf = nil
            self.updateSimulationAnzeige()
        }
    }

    public func lastBearbeiten(_ id: String) {
        let st = model.simulation
        guard let l = st.lastfall?.last(id) else { return }
        var last = l
        last.ort.punkt = l.punktWirksam ?? l.ort.punkt
        last.ort.normale = l.normaleWirksam ?? l.ort.normale
        last.ort.flaeche = l.flaecheWirksam ?? l.ort.flaeche
        st.lastAuswahl = id
        st.entwurf = SimulationStore.KraftEntwurf(last: last, bearbeitet: id)
        updateSimulationAnzeige()
    }

    public func waehleLast(_ id: String?) {
        let st = model.simulation
        st.lastAuswahl = id
        if let id, let l = st.lastfall?.last(id), scene.record(l.teil) != nil { select([l.teil]) }
        updateSimulationAnzeige()
    }

    public func zeigeErgebnisTeil(_ name: String) {
        guard scene.record(name) != nil else { return }
        select([name])
        focus(on: [name])
        if !model.statik.farbverlauf { setStatikFarbverlauf(true) }
    }

    public func schaltSchutzflaeche(_ index: Int) {
        let st = model.simulation
        guard let teil = st.topologieTeil else { return }
        if let i = st.schutzFlaechen.firstIndex(of: index) {
            st.schutzFlaechen.remove(at: i)
        } else {
            st.schutzFlaechen.append(index)
        }
        st.topologieGeladen = teil
        simulationAendern([SimOp.topologie(teil, topologieEinstellungenJSON())], fertig: nil)
        updateSimulationAnzeige()
    }

    public func starteSimulationsTopologie(teil: String) {
        let st = model.simulation, t = model.topologie
        st.topologieTeil = teil
        st.topologieGeladen = teil
        simulationAendern([SimOp.topologie(teil, topologieEinstellungenJSON())], fertig: nil)
        let basis = TopologieStartMessage(teil: teil, szenario: t.szenario, behalten: t.behalten,
                                          ueberhang: t.ueberhang, fein: t.fein,
                                          lager: t.schraubenHalten ? "bohrungen" : nil)
        let msg = TopologieStartErweitert(basis: basis, bohrungen: st.schutzBohrungen, einsaetze: st.schutzEinsaetze,
                                          kontakt: st.schutzKontakt, bett: st.schutzBett, steg: st.steg,
                                          schutz: st.schutzFlaechen)
        if !send(msg) { log(.warning, "Topologie: keine Verbindung zum Kernel") }
    }

    public func waehleTopologieTeil(_ teil: String?) {
        let st = model.simulation
        st.topologieTeil = teil
        st.schutzFlaechen = []
        st.topologieGeladen = nil
        if let teil {
            ladeTopologieEinstellungen(teil)
            if scene.record(teil) != nil { select([teil]) }
        }
        updateSimulationAnzeige()
    }

    public func simulationLaden() {
        request(SimReqMessage(id: nextRequestID()), timeout: 30) { [weak self] result in
            if case .failure(let e) = result { self?.log(.warning, "Simulation: \(e.message)") }
        }
    }
}
