import AppKit
import Combine
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
    // simulation2: Lager, die im gewählten Lastfall nicht gelten (blass), Last auf der ganzen Fläche, Ringe des Griffs
    static let simLagerBlass = SIMD4<Float>(0.62, 0.62, 0.65, 0.35)
    static let simLagerflaecheBlass = SIMD4<Float>(0.6, 0.6, 0.62, 0.18)
    static let simFlaechenlast = SIMD4<Float>(0.16, 0.42, 0.92, 0.30)
    static let simRingAzimut = SIMD4<Float>(0.22, 0.55, 0.98, 1)
    static let simRingHoehe = SIMD4<Float>(0.25, 0.75, 0.38, 1)
    static let simEingerastet = SIMD4<Float>(0.20, 0.85, 0.35, 1)
    /// Pfeillänge in Bildschirmpunkten, wenn die Pfeile bildschirmfest sind.
    static let simPfeilPunkte: Float = 80

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
        if st.werkzeug == .lager, st.kanteWaehlen {  // Gleitrichtung entlang einer Kante
            if ref.kind == .edge {
                simulationKanteGewaehlt(teil: ref.part, kante: ref.index)
            } else {
                st.meldung = "Eine Kante anklicken (Gleitrichtung), keine Fläche"
                st.meldungFehler = true
            }
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
            if flaeche == nil, last.aufFlaeche {  // ganze Fläche braucht eine Fläche
                last.verteilung = "punkt"
                if last.einheit == SimKraft.druck { last.einheit = "N" }
            }
            st.entwurf = SimulationStore.KraftEntwurf(last: last, bearbeitet: st.entwurf?.bearbeitet)
        case .lager:
            var auf = st.lagerAuf
            if auf == .flaeche && flaeche == nil { auf = .punkt }
            let alt = st.lagerEntwurf
            // Lastfälle und Gleitrichtung: die des Entwurfs, sonst die Einstellung für das nächste Lager
            st.lagerEntwurf = SimLager(
                id: alt?.id ?? "", teil: teil, art: st.lagerArt, auf: auf, ort: ort,
                szenarien: alt != nil ? alt?.szenarien : st.lagerSzenarien,
                gleiten: alt?.gleiten ?? st.lagerGleiten)
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
        viewport.onGriffEnde = { [weak self] _ in self?.simulationGriffEnde() }
        // Pfeile bildschirmfest: bei Kamerabewegung neu bauen (gedrosselt, nur bei merklicher Änderung)
        viewport.controller.$cameraState
            .throttle(for: .milliseconds(50), scheduler: DispatchQueue.main, latest: true)
            .sink { [weak self] _ in MainActor.assumeIsolated { self?.simulationKameraBewegt() } }
            .store(in: &navCancellables)
    }

    /// Länge der Pfeile im Viewer (mm) am Punkt `p`: bildschirmfest (Schalter) etwa 80 Punkte in der Tiefe von `p`,
    /// sonst etwa ein Sechstel der Szene, mindestens 30 mm.
    public func simPfeilLaenge(bei p: SIMD3<Float>? = nil) -> Float {
        if model.simulation.pfeileBildschirmfest, let p, let w = viewport.weltProPunkt(bei: p), w.isFinite, w > 0 {
            return max(0.05, min(1e5, Self.simPfeilPunkte * w))
        }
        let d = scene.visibleBounds()?.diagonalLength ?? 400
        return max(30, min(400, d * 0.18))
    }

    /// Ende des Pfeils (Griff) der Kraft im Entwurf.
    public func simGriffPunkt() -> SIMD3<Float>? {
        guard let e = model.simulation.entwurf, let p = e.last.ort.punkt, let F = e.kraft, simd_length(F) > 0 else {
            return nil
        }
        return p - simd_normalize(F) * simPfeilLaenge(bei: p)
    }

    /// Breitenkreis und Meridian durch das Pfeilende (Welt), beim Ziehen eines Rings fest wie beim Anfassen.
    public func simGriffRinge() -> (azimut: [SIMD3<Float>], hoehe: [SIMD3<Float>])? {
        let st = model.simulation
        guard let e = st.entwurf, let p = e.last.ort.punkt, let F = e.kraft, simd_length(F) > 0 else { return nil }
        let L = simPfeilLaenge(bei: p)
        let jetzt = simd_normalize(F)
        // Breitenkreis hängt nur an der Höhe (bleibt beim Ziehen des Azimuts derselbe); der Meridian bleibt beim
        // Ziehen der Höhe in der Ebene vom Anfassen (auch über den Pol hinweg)
        let dHoehe = st.griffZug.flatMap { $0.art == .ringHoehe ? $0.d0 : nil } ?? jetzt
        return (SimGriff.breitenkreis(punkt: p, richtung: jetzt, laenge: L),
                SimGriff.meridian(punkt: p, richtung: dHoehe, laenge: L))
    }

    /// Maustaste gedrückt: Kugel am Pfeilende (frei drehen) oder einer der Ringe (nur Azimut bzw. nur Höhe).
    public func simulationGriffBeginnt(_ p: CGPoint) -> Bool {
        let st = model.simulation
        guard st.aktiv, let e = st.entwurf, e.last.einheit != SimKraft.druck, e.last.ort.punkt != nil,
              let F = e.kraft, simd_length(F) > 0
        else { return false }
        var art = SimulationStore.GriffArt.keins
        if let g = simGriffPunkt(), let s = viewport.bildpunkt(g), hypot(s.x - p.x, s.y - p.y) <= 14 {
            art = .kugel
        } else if let r = simGriffRinge() {
            let az = SimGriff.abstand(p, linie: r.azimut.compactMap { viewport.bildpunkt($0) })
            let hz = SimGriff.abstand(p, linie: r.hoehe.compactMap { viewport.bildpunkt($0) })
            if min(az, hz) <= 6 { art = az <= hz ? .ringAzimut : .ringHoehe }
        }
        guard art != .keins else { return false }
        let d = simd_normalize(F)
        st.griffZug = SimulationStore.GriffZug(art: art, d0: d, d: d, letzter: p)
        st.griffArt = art
        st.griffAktiv = true
        st.eingerastet = nil
        updateSimulationAnzeige()
        return true
    }

    /// Ziehen: Kugel als Trackball, Ringe über den Blickstrahl; Einrasten auf Achsen und Normale (⌘: aus).
    public func simulationGriffZiehen(_ p: CGPoint) {
        let st = model.simulation
        guard var zug = st.griffZug, var e = st.entwurf, let punkt = e.last.ort.punkt else { return }
        let L = simPfeilLaenge(bei: punkt)
        let cam = viewport.camera
        var neu: SIMD3<Float>?
        switch zug.art {
        case .kugel:
            guard let mitte = viewport.bildpunkt(punkt), let w = viewport.weltProPunkt(bei: punkt), w > 0 else { return }
            neu = SimGriff.trackball(zug.d, von: zug.letzter, nach: p, mitte: mitte, radius: CGFloat(max(L / w, 30)),
                                     rechts: simd_normalize(cam.rightVector), oben: simd_normalize(cam.upVector),
                                     blick: simd_normalize(cam.viewDirection))
        case .ringAzimut:
            guard let s = viewport.blickstrahl(p) else { return }
            neu = SimGriff.azimutZiehen(d0: zug.d0, punkt: punkt, laenge: L, strahl: s.ursprung, s.richtung,
                                        bisher: zug.d)
        case .ringHoehe:
            guard let s = viewport.blickstrahl(p) else { return }
            neu = SimGriff.hoeheZiehen(d0: zug.d0, punkt: punkt, laenge: L, strahl: s.ursprung, s.richtung,
                                       bisher: zug.d)
        case .keins:
            return
        }
        guard let d = neu, d.x.isFinite, d.y.isFinite, d.z.isFinite else { return }
        zug.d = d  // freie Richtung (ohne Einrasten): der Trackball dreht von hier weiter
        zug.letzter = p
        st.griffZug = zug
        let snap = viewport.griffModifiers.contains(.command) ? nil : SimGriff.einrasten(d, normale: e.last.ort.normale)
        e.last.richtung = SimGriff.richtung(snap?.richtung ?? d, ziel: snap?.ziel, alt: e.last.richtung)
        st.eingerastet = snap?.ziel.titel
        st.entwurf = e
        updateSimulationAnzeige()
    }

    public func simulationGriffEnde() {
        let st = model.simulation
        st.griffAktiv = false
        st.griffArt = .keins
        st.griffZug = nil
        st.eingerastet = nil
        updateSimulationAnzeige()
    }

    /// Kamera bewegt: bildschirmfeste Pfeile neu bauen, wenn sich Lage oder Maßstab merklich geändert haben.
    func simulationKameraBewegt() {
        let st = model.simulation
        guard st.aktiv, st.pfeileBildschirmfest else { return }
        let c = viewport.camera
        let q = c.rotation.vector
        let neu: [Float] = [c.distance, c.orthographicScale, q.x, q.y, q.z, q.w, c.pivot.x, c.pivot.y, c.pivot.z,
                            c.panOffset.x, c.panOffset.y, c.isOrthographic ? 1 : 0, c.fieldOfView,
                            Float(viewport.viewSize.width), Float(viewport.viewSize.height)]
        let alt = st.bildschirmSchluessel
        if alt.count == neu.count, zip(alt, neu).allSatisfy({ abs($0 - $1) <= 0.002 * max(1, abs($0)) }) { return }
        st.bildschirmSchluessel = neu
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
        let lin = { (c: SIMD4<Float>) in PartBodies.linear(c) }
        if let lf = st.lastfall {
            let fMax = max(lf.lasten.compactMap { $0.kraftWirksam.map(simd_length) }.max() ?? 1, 1e-6)
            for (i, last) in lf.lasten.enumerated() where last.zustand != .fehlt && last.id != st.entwurf?.bearbeitet {
                guard let p = last.punkt, let F = last.kraftWirksam ?? (simd_length(last.kraft) > 0 ? last.kraft : nil)
                else { continue }
                let L = simPfeilLaenge(bei: p)
                let gewaehlt = last.id == st.lastAuswahl
                let farbe = gewaehlt ? Self.simAuswahlFarbe : (last.paar ? Self.simPaarFarbe : Self.simLastFarbe)
                let l = max(0.35 * L, L * simd_length(F) / fMax)
                out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)l\(i)", punkt: p, kraft: F, laenge: l,
                                                 farbe: lin(farbe)))
                if last.paar {
                    out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)l\(i)g", punkt: p, kraft: -F,
                                                     laenge: l, farbe: lin(farbe)))
                }
                // Last auf der ganzen Fläche: Fläche getönt, kleine Pfeile verteilt
                if last.aufFlaeche, let f = last.flaecheWirksam ?? last.ort.flaeche, scene.record(last.teil) != nil {
                    out += flaechenKoerper(last.teil, f, id: "lf\(i)", farbe: lin(Self.simFlaechenlast))
                    out += flaechenPfeile(last.teil, f, kraft: F, laenge: 0.3 * L, id: "lf\(i)p", farbe: lin(farbe))
                }
            }
        }
        if let e = st.entwurf, let p = e.last.ort.punkt, let F = e.kraft {
            let L = simPfeilLaenge(bei: p)
            out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)e", punkt: p, kraft: F, laenge: L,
                                             farbe: lin(Self.simEntwurfFarbe)))
            if e.last.aufFlaeche, let f = e.last.ort.flaeche, scene.record(e.last.teil) != nil {
                out += flaechenKoerper(e.last.teil, f, id: "ef", farbe: lin(SIMD4(0.98, 0.55, 0.08, 0.30)))
                out += flaechenPfeile(e.last.teil, f, kraft: F, laenge: 0.3 * L, id: "efp",
                                      farbe: lin(Self.simEntwurfFarbe))
            }
            if e.last.einheit != SimKraft.druck {
                out += griffKoerper(kraft: F, laenge: L, lin: lin)
            }
            if let g = e.last.gegen, scene.record(g) != nil, let p2 = e.last.ort.punkt {
                out.append(StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)eG", punkt: p2, kraft: -F,
                                                 laenge: L * 0.7, farbe: lin(Self.simPaarFarbe)))
            }
        }
        if let s = st.stand {
            for (i, l) in (s.lager + s.modellLager).enumerated() where l.zustand != .fehlt {
                // Lager, die im gewählten Lastfall nicht gelten: blass
                let gilt = l.giltFuer(st.auswahl)
                out += lagerSymbol(l, id: "a\(i)", groesse: simPfeilLaenge(bei: l.punkt), lin: lin,
                                   farbe: gilt ? nil : Self.simLagerBlass)
                if l.auf == .flaeche, let f = l.ort.flaeche, scene.record(l.teil) != nil {
                    out += flaechenKoerper(l.teil, f, id: "af\(i)",
                                           farbe: lin(gilt ? Self.simLagerflaeche : Self.simLagerflaecheBlass))
                }
            }
            for (i, a) in s.abgeleitet.enumerated() where a.aktiv && a.art == "boden" {
                guard let p = a.punkt else { continue }
                let h = simPfeilLaenge(bei: p) * 0.07
                let (vd, idx) = StatikGeometrie.kegel(basis: p - SIMD3(0, 0, h), spitze: p, radius: h * 0.55)
                out.append(ViewportBody(id: "\(Self.simulationPraefix)ab\(i)", vertexData: vd, indices: idx,
                                        edges: [], color: lin(Self.simAbgeleitetFarbe), roughness: 0.6,
                                        isPickable: false))
            }
        }
        if let l = st.lagerEntwurf {
            out += lagerSymbol(l, id: "ae", groesse: simPfeilLaenge(bei: l.punkt), lin: lin,
                               farbe: Self.simEntwurfFarbe)
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
            // Schiene: kleiner Doppelpfeil entlang der Gleitrichtung an der abgesetzten Platte
            if let g = l.gleiten?.richtung, simd_length(g) > 1e-6 {
                let d = simd_normalize(g)
                let m = basis + n * h * 0.6
                let a = h * 0.9, s = h * 0.3
                var (vd2, idx2) = StatikGeometrie.rohr([m - d * (a - s), m + d * (a - s)], radius: r * 0.22)
                for (spitze, hals) in [(m + d * a, m + d * (a - s)), (m - d * a, m - d * (a - s))] {
                    let (kd, ki) = StatikGeometrie.kegel(basis: hals, spitze: spitze, radius: r * 0.6)
                    let off = UInt32(vd2.count / 6)
                    vd2 += kd
                    idx2 += ki.map { $0 + off }
                }
                out.append(ViewportBody(id: "\(Self.simulationPraefix)\(id)g", vertexData: vd2, indices: idx2, edges: [],
                                        color: c, roughness: 0.5, isPickable: false))
            }
        case .gelenkig:
            break
        }
        return out
    }

    /// Griff am Pfeilende (Kugel, weiß; eingerastet grün) und die beiden Ringe durch ihn (Breitenkreis blau: nur
    /// Azimut, Meridian grün: nur Höhe); der gezogene Ring dicker.
    func griffKoerper(kraft F: SIMD3<Float>, laenge L: Float, lin: (SIMD4<Float>) -> SIMD4<Float>) -> [ViewportBody] {
        let st = model.simulation
        var out: [ViewportBody] = []
        if let g = simGriffPunkt() {
            let d = simd_normalize(F)
            let (vd, idx) = StatikGeometrie.rohr([g - d * L * 0.04, g + d * L * 0.04], radius: max(L * 0.06, 0.02))
            out.append(ViewportBody(id: "\(Self.simulationPraefix)eg", vertexData: vd, indices: idx, edges: [],
                                    color: lin(st.eingerastet != nil ? Self.simEingerastet : SIMD4(1, 1, 1, 1)),
                                    roughness: 0.4, isPickable: false))
        }
        if let r = simGriffRinge() {
            for (name, ring, farbe, art) in [("era", r.azimut, Self.simRingAzimut, SimulationStore.GriffArt.ringAzimut),
                                            ("erh", r.hoehe, Self.simRingHoehe, SimulationStore.GriffArt.ringHoehe)] {
                guard let erster = ring.first else { continue }
                let dick: Float = st.griffArt == art ? 0.012 : 0.006
                let (vd, idx) = StatikGeometrie.rohr(ring + [erster], radius: max(L * dick, 0.01))
                out.append(ViewportBody(id: "\(Self.simulationPraefix)\(name)", vertexData: vd, indices: idx,
                                        edges: [], color: lin(farbe), roughness: 0.5, isPickable: false))
            }
        }
        return out
    }

    /// Kleine Pfeile verteilt auf einer Fläche (Last auf der ganzen Fläche): höchstens sechs Dreiecksmitten.
    func flaechenPfeile(_ teil: String, _ flaeche: Int, kraft F: SIMD3<Float>, laenge: Float, id: String,
                        farbe: SIMD4<Float>) -> [ViewportBody] {
        guard let rec = scene.record(teil), simd_length(F) > 0 else { return [] }
        let M = scene.worldTransform(teil)
        var mitten: [(SIMD3<Float>, Float)] = []
        for chunk in rec.chunks {
            for t in 0..<chunk.triangleCount where t < chunk.triFace.count && Int(chunk.triFace[t]) == flaeche {
                var q = [SIMD3<Float>]()
                for j in 0..<3 {
                    let k = Int(chunk.indices[t * 3 + j])
                    let w = M * SIMD4(chunk.vertexData[k * 6], chunk.vertexData[k * 6 + 1], chunk.vertexData[k * 6 + 2], 1)
                    q.append(SIMD3(w.x, w.y, w.z))
                }
                mitten.append(((q[0] + q[1] + q[2]) / 3, simd_length(simd_cross(q[1] - q[0], q[2] - q[0])) / 2))
            }
        }
        // die größten Dreiecke, gleichmäßig über die Fläche gestreut (Abstand mindestens ein Pfeil)
        var gewaehlt: [SIMD3<Float>] = []
        for (m, _) in mitten.sorted(by: { $0.1 > $1.1 }) where gewaehlt.allSatisfy({ simd_length($0 - m) > laenge }) {
            gewaehlt.append(m)
            if gewaehlt.count >= 6 { break }
        }
        return gewaehlt.enumerated().map { i, m in
            StatikGeometrie.pfeil(id: "\(Self.simulationPraefix)\(id)\(i)", punkt: m, kraft: F, laenge: laenge,
                                  farbe: farbe)
        }
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
        simRun(SimRunMessage(id: nextRequestID(), was: was, lastfall: lastfall, teil: teil, fein: fein, grenze: grenze))
    }

    public func simulationGrenzeSuchen(lastfall: String?, art: String, verfahren: String) {
        simRun(SimRunMessage(id: nextRequestID(), was: "grenze", lastfall: lastfall, grenze: art,
                             verfahren: verfahren == "fem" && art != "geschwindigkeit" ? "fem" : "s0s1"))
    }

    public func setPfeileBildschirmfest(_ an: Bool) {
        let st = model.simulation
        st.pfeileBildschirmfest = an
        st.bildschirmSchluessel = []
        updateSimulationAnzeige()
    }

    public func simulationKanteGewaehlt(teil: String, kante: Int) {
        let st = model.simulation
        st.kanteWaehlen = false
        guard let rec = scene.record(teil) else { return }
        let M = scene.worldTransform(teil)
        let poly = rec.geometry.edgePolyline(kante).map { p -> SIMD3<Float> in
            let w = M * SIMD4(p, 1)
            return SIMD3(w.x, w.y, w.z)
        }
        guard let a = poly.first, let b = poly.last, simd_length(b - a) > 1e-3 else {
            st.meldung = "Kante \(kante) hat keine Richtung (geschlossen); eine gerade Kante anklicken"
            st.meldungFehler = true
            return
        }
        let g = SimGleiten(art: .richtung, richtung: simd_normalize(b - a), quelle: "kante", kante: kante)
        if var l = st.lagerEntwurf {
            l.art = .gleitend
            l.gleiten = g
            st.lagerEntwurf = l
        } else {
            st.lagerGleiten = g
            st.lagerArt = .gleitend
        }
        st.meldung = "Gleitrichtung \(g.titel)"
        st.meldungFehler = false
        updateSimulationAnzeige()
    }

    private func simRun(_ msg: SimRunMessage) {
        let st = model.simulation
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
        if w != .lager { st.kanteWaehlen = false }
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
