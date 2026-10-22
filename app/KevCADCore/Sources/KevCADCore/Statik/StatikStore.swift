import Foundation
import OCCTSwiftViewport
import simd

/// Statik im Fenster (additiv zu AppModel): letztes Ergebnis (STATICS), gewähltes Szenario und die Schalter für den
/// Farbverlauf (Ausnutzung grün → gelb → rot an Teilen und Stäben) und die überhöhte Verformung als Geist.
@MainActor
public final class StatikStore: ObservableObject {
    @Published public var ergebnis: StatikErgebnis?
    /// Gewähltes Szenario (Name); nil = das vom Kernel vorgeschlagene (`aktiv`).
    @Published public var auswahl: String?
    @Published public var farbverlauf = false
    @Published public var verformung = false

    public init() {}

    public var szenario: StatikSzenario? {
        guard let e = ergebnis else { return nil }
        return e.szenario(auswahl) ?? e.szenario(e.aktiv) ?? e.szenarien.first
    }
}

/// Aktionen der Statik-Ansicht; die Oberfläche ruft sie über `model.actions as? StatikActions`.
@MainActor
public protocol StatikActions: AnyObject {
    /// Szenario wählen; schaltet den Farbverlauf ein.
    func waehleStatikSzenario(_ name: String)
    func setStatikFarbverlauf(_ an: Bool)
    func setStatikVerformung(_ an: Bool)
    /// Teil des Urteils auswählen und die Kamera auf den Ort fahren.
    func zeigeStatikUrteil(_ urteil: StatikUrteil)
}

/// Körper für den Viewport aus einem Szenario: je Stab Röhrensegmente in der Farbe der Ausnutzung (etwas dicker als der
/// Stab, damit sie ihn überdecken) und die Stabachsen in überhöhter Verformung als durchscheinender Geist. Rein,
/// testbar, ohne Szene.
public enum StatikGeometrie {
    public static let praefix = "\u{1F}statik\u{1F}"
    static let seiten = 14

    /// Farben in sRGB: grün (Ausnutzung 0), gelb (1 = Ziel erreicht), rot (ab 2).
    static let gruen = SIMD3<Float>(0.18, 0.68, 0.30)
    static let gelb = SIMD3<Float>(0.98, 0.80, 0.15)
    static let rot = SIMD3<Float>(0.88, 0.14, 0.11)
    static let geist = SIMD4<Float>(0.40, 0.58, 0.98, 0.42)

    /// Farbe der Ausnutzung (Zielsicherheit / vorhandene Sicherheit), linear für den Viewport.
    public static func farbe(_ ausnutzung: Double) -> SIMD3<Float> {
        let a = Float(max(0, min(2, ausnutzung.isFinite ? ausnutzung : 2)))
        let srgb = a <= 1 ? gruen + (gelb - gruen) * a : gelb + (rot - gelb) * (a - 1)
        let l = PartBodies.linear(SIMD4(srgb, 1))
        return SIMD3(l.x, l.y, l.z)
    }

    public static func ampelFarbe(_ ampel: StatikAmpel) -> SIMD3<Float> {
        switch ampel {
        case .gruen: return farbe(0.3)
        case .gelb: return farbe(1.5)
        case .rot: return farbe(2)
        case .grau: return SIMD3(0.5, 0.5, 0.5)
        }
    }

    /// Färbung der Teile (linear) nach ihrer Ausnutzung; `bekannt` filtert Teile, die es in der Szene gibt.
    public static func toene(_ sz: StatikSzenario, bekannt: (String) -> Bool) -> [String: SIMD3<Float>] {
        var out: [String: SIMD3<Float>] = [:]
        for t in sz.teile where bekannt(t.name) && t.ampel != .grau {
            out[t.name] = farbe(t.ausnutzung)
        }
        return out
    }

    public static func koerper(_ sz: StatikSzenario, farbverlauf: Bool, verformung: Bool) -> [ViewportBody] {
        var out: [ViewportBody] = []
        for (i, s) in sz.staebe.enumerated() where s.punkte.count >= 2 {
            if farbverlauf {
                let r = s.radius * 1.08 + 0.3
                for k in 0..<(s.punkte.count - 1) {
                    let a = (s.ausnutzung[k] + s.ausnutzung[k + 1]) / 2
                    let (vd, idx) = rohr([s.punkte[k], s.punkte[k + 1]], radius: r)
                    out.append(
                        ViewportBody(
                            id: "\(praefix)s\(i)\u{1F}\(k)", vertexData: vd, indices: idx, edges: [],
                            color: SIMD4(farbe(a), 1), roughness: 0.5, isPickable: false))
                }
            }
            if verformung {
                let u = max(sz.ueberhoehung, 1)
                let punkte = zip(s.punkte, s.verschiebung).map { $0 + $1 * u }
                let (vd, idx) = rohr(punkte, radius: max(s.radius * 0.7, 1))
                let g = PartBodies.linear(geist)
                out.append(
                    ViewportBody(
                        id: "\(praefix)v\(i)", vertexData: vd, indices: idx, edges: [], color: g, roughness: 0.6,
                        isPickable: false))
            }
        }
        return out
    }

    /// Röhre entlang eines Linienzugs (Ringe mit parallel mitgeführtem Bezugsvektor, Deckel an den Enden):
    /// verschachtelte Daten [px, py, pz, nx, ny, nz] und Dreiecke.
    public static func rohr(_ punkte: [SIMD3<Float>], radius: Float) -> ([Float], [UInt32]) {
        guard punkte.count >= 2 else { return ([], []) }
        var vd: [Float] = []
        var idx: [UInt32] = []
        let n = seiten
        var tangenten: [SIMD3<Float>] = []
        for i in punkte.indices {
            let a = punkte[max(i - 1, 0)], b = punkte[min(i + 1, punkte.count - 1)]
            var t = b - a
            if simd_length(t) < 1e-6 { t = SIMD3(0, 0, 1) }
            tangenten.append(simd_normalize(t))
        }
        var bezug = abs(tangenten[0].z) < 0.9 ? SIMD3<Float>(0, 0, 1) : SIMD3<Float>(1, 0, 0)
        for (i, p) in punkte.enumerated() {
            let t = tangenten[i]
            var u = bezug - t * simd_dot(bezug, t)
            if simd_length(u) < 1e-6 { u = abs(t.z) < 0.9 ? simd_cross(t, SIMD3(0, 0, 1)) : simd_cross(t, SIMD3(1, 0, 0)) }
            u = simd_normalize(u)
            bezug = u
            let v = simd_cross(t, u)
            for k in 0..<n {
                let w = Float(k) / Float(n) * 2 * .pi
                let d = u * cos(w) + v * sin(w)
                let q = p + d * radius
                vd += [q.x, q.y, q.z, d.x, d.y, d.z]
            }
        }
        for i in 0..<(punkte.count - 1) {
            let a = UInt32(i * n), b = UInt32((i + 1) * n)
            for k in 0..<n {
                let k1 = UInt32((k + 1) % n), k0 = UInt32(k)
                idx += [a + k0, a + k1, b + k1, a + k0, b + k1, b + k0]
            }
        }
        // Deckel
        for (ende, ring) in [(0, 0), (punkte.count - 1, (punkte.count - 1) * n)] {
            let t = tangenten[ende] * (ende == 0 ? -1 : 1)
            let c = UInt32(vd.count / 6)
            let p = punkte[ende]
            vd += [p.x, p.y, p.z, t.x, t.y, t.z]
            for k in 0..<n {
                let i0 = UInt32(ring + k), i1 = UInt32(ring + (k + 1) % n)
                idx += ende == 0 ? [c, i1, i0] : [c, i0, i1]
            }
        }
        return (vd, idx)
    }
}
