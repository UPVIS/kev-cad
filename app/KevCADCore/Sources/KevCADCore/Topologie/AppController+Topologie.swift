import Foundation
import OCCTSwiftViewport
import simd

/// Topologieoptimierung (PROTOCOL.md „Topologie“): TOPO und TOPO_FIELD übernehmen und im Viewer zeigen. Während der
/// Rechnung liegt die Dichte der letzten Iteration halbdurchsichtig über dem blass gezeigten Teil; fertig zeigt „Vorher“
/// bzw. „Nachher“ die Spannungsfarben (Bänder der Ausnutzung wie beim Festkörper) am Ausgangsteil bzw. am Ergebnis.
extension AppController: TopologieActions {
    static let topologiePraefix = "\u{1F}topologie\u{1F}"
    static let dichteFarbe = SIMD4<Float>(0.98, 0.52, 0.12, 0.62)
    static let schutzFarbe = SIMD4<Float>(0.15, 0.72, 0.38, 0.55)
    static let koerperFarbe = SIMD4<Float>(0.55, 0.64, 0.80, 1.0)

    func applyTopologie(_ s: TopologieStand) {
        let t = model.topologie
        let neu = t.stand?.auftrag != s.auftrag
        if neu { t.felder = [:] }
        let warLaufend = t.stand?.laeuft ?? false
        t.stand = s
        if s.laeuft && (neu || t.ansicht == .aus) { t.ansicht = .live }
        if s.fertig && (warLaufend || neu) { t.ansicht = .nachher }
        if s.stand == "failed", let m = s.meldung { log(.warning, "Topologie: \(m)") }
        updateTopologieAnzeige()
    }

    func applyTopologieFeld(_ f: TopologieFeld) {
        let t = model.topologie
        if let s = t.stand, f.auftrag != 0, f.auftrag != s.auftrag { return }
        t.felder[f.art] = f
        updateTopologieAnzeige()
    }

    /// Körper der Topologie in die Szene (oder entfernen).
    func updateTopologieAnzeige() {
        let t = model.topologie
        guard let s = t.stand else {
            scene.setTopologie(bodies: [], verdeckt: [], blass: [])
            return
        }
        var koerper: [ViewportBody] = []
        var verdeckt: Set<String> = []
        var blass: Set<String> = []
        let teil = s.teil
        switch t.ansicht {
        case .aus:
            break
        case .live:
            if let d = t.feld(.dichte) ?? (s.fertig ? t.feld(.koerper) : nil) {
                koerper += Self.netzKoerper(d, id: "d", farbe: Self.dichteFarbe)
                if scene.record(teil) != nil { blass.insert(teil) }
            }
        case .vorher:
            if let f = t.feld(.vorher)?.feld {
                koerper += StatikFeldGeometrie.farbverlauf(f, id: "topo-v")
                if scene.record(teil) != nil { verdeckt.insert(teil) }
            }
        case .nachher:
            if let f = t.feld(.nachher)?.feld {
                koerper += StatikFeldGeometrie.farbverlauf(f, id: "topo-n")
                if scene.record(teil) != nil { verdeckt.insert(teil) }
            } else if let k = t.feld(.koerper) {
                koerper += Self.netzKoerper(k, id: "k", farbe: Self.koerperFarbe)
                if scene.record(teil) != nil { verdeckt.insert(teil) }
            }
        }
        if t.schutzZeigen, let z = t.feld(.schutz) {
            koerper += Self.netzKoerper(z, id: "s", farbe: Self.schutzFarbe)
        }
        scene.setTopologie(bodies: koerper, verdeckt: verdeckt, blass: blass)
    }

    /// Netz als Körper in einer Farbe (linear), flach schattiert, in Stücken bis 16 000 Dreiecke.
    static func netzKoerper(_ f: TopologieFeld, id: String, farbe: SIMD4<Float>) -> [ViewportBody] {
        var vd: [Float] = []
        vd.reserveCapacity(f.dreiecke.count * 6)
        let p = f.punkte
        for k in 0..<(f.dreiecke.count / 3) {
            let a = p[Int(f.dreiecke[3 * k])], b = p[Int(f.dreiecke[3 * k + 1])], c = p[Int(f.dreiecke[3 * k + 2])]
            var n = simd_cross(b - a, c - a)
            let l = simd_length(n)
            if l < 1e-12 { continue }
            n /= l
            for q in [a, b, c] { vd += [q.x, q.y, q.z, n.x, n.y, n.z] }
        }
        return StatikFeldGeometrie.zerlege(vd, id: "\(topologiePraefix)\(id)", farbe: PartBodies.linear(farbe))
    }

    // MARK: TopologieActions

    public func starteTopologie(teil: String) {
        let t = model.topologie
        let msg = TopologieStartMessage(
            teil: teil, szenario: t.szenario, behalten: t.behalten, ueberhang: t.ueberhang, fein: t.fein,
            lager: t.schraubenHalten ? "bohrungen" : nil)
        if !send(msg) { log(.warning, "Topologie: keine Verbindung zum Kernel") }
    }

    public func brecheTopologieAb() {
        if !send(TopologieAbbrechenMessage()) { log(.warning, "Topologie: keine Verbindung zum Kernel") }
    }

    public func uebernehmeTopologie() {
        if !send(TopologieUebernehmenMessage()) { log(.warning, "Topologie: keine Verbindung zum Kernel") }
    }

    public func setTopologieAnsicht(_ ansicht: TopologieStore.Ansicht) {
        model.topologie.ansicht = ansicht
        updateTopologieAnzeige()
    }

    public func setTopologieSchutz(_ an: Bool) {
        model.topologie.schutzZeigen = an
        updateTopologieAnzeige()
    }
}
