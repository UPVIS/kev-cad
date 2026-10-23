import CoreGraphics
import Foundation
import simd

/// Pfeil-Griff einer Kraft im Viewer (PLAN-SIMULATION.md, simulation2): die Kraft frei im Raum drehen. Reine
/// Mathematik ohne Viewport, damit sie sich mit Zahlen prüfen lässt.
///
/// - **Kugel** am Pfeilende: Virtueller Trackball um den Angriffspunkt (Shoemake). Gerechnet wird schrittweise von
///   einem Mauspunkt zum nächsten: Der angefasste Punkt folgt der Maus, und zieht man über den Rand der Kugel hinaus,
///   dreht sie weiter (Winkel linear im Abstand), so dass das Pfeilende auch hinter die Kugel kommt.
/// - **Ringe** durch das Pfeilende: Breitenkreis (nur der Azimut ändert sich, die Höhe bleibt) und Meridian (nur die
///   Höhe ändert sich). Der Ring bleibt während des Ziehens liegen; die neue Lage ist der Punkt des Rings, der dem
///   Blickstrahl am nächsten liegt (bei mehreren gleich nahen der nächste zur bisherigen Lage, also stetig auch bei
///   Blick genau von der Seite).
/// - **Einrasten** auf ±X, ±Y, ±Z und ± Flächennormale unter `einrastGrad`.
///
/// Richtung `d` ist immer die Kraftrichtung (vom Pfeilende zum Angriffspunkt P); das Pfeilende liegt bei P − d·L.
public enum SimGriff {
    /// Einrasten unter diesem Winkel (Grad).
    public static let einrastGrad: Float = 6

    /// Wohin eingerastet ist.
    public enum Ziel: Equatable, Sendable {
        /// Weltachse "+x" … "-z"
        case achse(String)
        /// Flächennormale: in die Fläche hinein (`umgekehrt` false) bzw. heraus (true)
        case normale(umgekehrt: Bool)

        public var titel: String {
            switch self {
            case .achse(let a): return a.replacingOccurrences(of: "-", with: "−").uppercased()
            case .normale(let u): return u ? "Normale (zieht)" : "Normale"
            }
        }
    }

    // MARK: Kugel

    /// Bildschirmpunkt → Punkt auf der virtuellen Kugel im Kamerasystem (x rechts, y oben, z zum Betrachter), normiert.
    /// Innen die Kugel (der angefasste Punkt bleibt unter der Maus); außerhalb des Kreises läuft der Winkel zur
    /// Blickachse linear weiter (Abstand 1 = 90°, 2 = 180°), so dass Ziehen über den Rand auf die Rückseite dreht.
    public static func kugelpunkt(_ p: CGPoint, mitte: CGPoint, radius: CGFloat) -> SIMD3<Float> {
        let r = max(radius, 1)
        let x = Float((p.x - mitte.x) / r), y = Float((p.y - mitte.y) / r)
        let q = x * x + y * y
        if q <= 1 { return SIMD3(x, y, (1 - q).squareRoot()) }
        let rho = q.squareRoot()
        let w = Float.pi / 2 * rho
        return SIMD3(x / rho * sin(w), y / rho * sin(w), cos(w))
    }

    /// Kürzeste Drehung von a nach b.
    public static func drehung(von a: SIMD3<Float>, nach b: SIMD3<Float>) -> simd_quatf {
        let u = simd_normalize(a), v = simd_normalize(b)
        let c = simd_dot(u, v)
        if c > 1 - 1e-7 { return simd_quatf(angle: 0, axis: SIMD3(0, 0, 1)) }
        if c < -1 + 1e-7 {
            var achse = simd_cross(u, SIMD3(1, 0, 0))
            if simd_length(achse) < 1e-4 { achse = simd_cross(u, SIMD3(0, 1, 0)) }
            return simd_quatf(angle: .pi, axis: simd_normalize(achse))
        }
        return simd_quatf(angle: acos(c), axis: simd_normalize(simd_cross(u, v)))
    }

    /// Ein Schritt des Trackballs: Kraftrichtung `d` nach der Mausbewegung `von` → `nach` (Bildschirm, Ursprung unten
    /// links), Kugel mit Mitte `mitte` (Angriffspunkt auf dem Bildschirm) und Radius `radius` (Pfeillänge in Punkten),
    /// Kamerabasis `rechts`, `oben` und Blickrichtung `blick` (Welt).
    public static func trackball(_ d: SIMD3<Float>, von: CGPoint, nach: CGPoint, mitte: CGPoint, radius: CGFloat,
                                 rechts: SIMD3<Float>, oben: SIMD3<Float>, blick: SIMD3<Float>) -> SIMD3<Float> {
        func welt(_ v: SIMD3<Float>) -> SIMD3<Float> { rechts * v.x + oben * v.y - blick * v.z }
        let a = welt(kugelpunkt(von, mitte: mitte, radius: radius))
        let b = welt(kugelpunkt(nach, mitte: mitte, radius: radius))
        return simd_normalize(drehung(von: a, nach: b).act(d))
    }

    // MARK: Ringe

    /// Höhe (Grad) und Azimut (Grad) einer Richtung, wie `SimKraft.winkel`.
    static func pfeilende(_ p: SIMD3<Float>, _ d: SIMD3<Float>, _ l: Float) -> SIMD3<Float> { p - simd_normalize(d) * l }

    /// Breitenkreis durch das Pfeilende (waagrecht, in dessen Höhe). Liegt die Kraft fast senkrecht, wäre er winzig:
    /// dann mit mindestens einem Viertel der Pfeillänge.
    public static func breitenkreis(punkt p: SIMD3<Float>, richtung d: SIMD3<Float>, laenge l: Float, n: Int = 72)
        -> [SIMD3<Float>]
    {
        let e = pfeilende(p, d, l)
        let r = max(hypot(e.x - p.x, e.y - p.y), 0.25 * l)
        let mitte = SIMD3(p.x, p.y, e.z)
        return (0..<n).map { k in
            let w = Float(k) / Float(n) * 2 * .pi
            return mitte + SIMD3(cos(w), sin(w), 0) * r
        }
    }

    /// Waagrechte Einheitsrichtung vom Angriffspunkt zum Pfeilende (bei senkrechter Kraft +X).
    static func waagrecht(_ d: SIMD3<Float>) -> SIMD3<Float> {
        let h = SIMD3(-d.x, -d.y, 0)
        return simd_length(h) > 1e-4 ? simd_normalize(h) : SIMD3(1, 0, 0)
    }

    /// Meridian durch das Pfeilende: senkrechter Großkreis um den Angriffspunkt in der Ebene aus Z und der
    /// waagrechten Richtung zum Pfeilende.
    public static func meridian(punkt p: SIMD3<Float>, richtung d: SIMD3<Float>, laenge l: Float, n: Int = 72)
        -> [SIMD3<Float>]
    {
        let h = waagrecht(d)
        return (0..<n).map { k in
            let w = Float(k) / Float(n) * 2 * .pi
            return p + (h * cos(w) + SIMD3(0, 0, 1) * sin(w)) * l
        }
    }

    /// Abstand eines Punkts vom Strahl (o, r normiert).
    static func abstand(_ q: SIMD3<Float>, strahl o: SIMD3<Float>, _ r: SIMD3<Float>) -> Float {
        let v = q - o
        return simd_length(v - r * simd_dot(v, r))
    }

    /// Punkt eines Rings (Linienzug), der dem Blickstrahl am nächsten liegt; unter gleich nahen (bis `toleranz`) der
    /// nächste zu `nahAn`.
    public static func naechster(_ ring: [SIMD3<Float>], strahl o: SIMD3<Float>, _ r: SIMD3<Float>,
                                 nahAn: SIMD3<Float>, toleranz: Float) -> SIMD3<Float>? {
        guard !ring.isEmpty else { return nil }
        // fein abtasten: zwischen den Stützpunkten je 8 Zwischenpunkte
        var punkte: [SIMD3<Float>] = []
        for (i, a) in ring.enumerated() {
            let b = ring[(i + 1) % ring.count]
            for k in 0..<8 { punkte.append(a + (b - a) * (Float(k) / 8)) }
        }
        let d = punkte.map { abstand($0, strahl: o, r) }
        guard let dmin = d.min() else { return nil }
        // örtliche Minima entlang des Rings (je Stelle, an der der Strahl den Ring kreuzt oder streift), davon die fast
        // so nahen wie das beste; unter ihnen das zur bisherigen Lage nächste
        let n = punkte.count
        let minima = punkte.indices.filter { i in
            d[i] <= dmin + toleranz && d[i] <= d[(i + n - 1) % n] && d[i] <= d[(i + 1) % n]
        }
        return minima.map { punkte[$0] }.min { simd_length($0 - nahAn) < simd_length($1 - nahAn) }
    }

    /// Breitenkreis ziehen: Azimut aus dem Ringpunkt am Blickstrahl, die Höhe von `d0` bleibt.
    public static func azimutZiehen(d0: SIMD3<Float>, punkt p: SIMD3<Float>, laenge l: Float, strahl o: SIMD3<Float>,
                                    _ r: SIMD3<Float>, bisher: SIMD3<Float>) -> SIMD3<Float>? {
        let ring = breitenkreis(punkt: p, richtung: d0, laenge: l, n: 180)
        guard let q = naechster(ring, strahl: o, r, nahAn: pfeilende(p, bisher, l), toleranz: 0.02 * l) else {
            return nil
        }
        let ende = SIMD2(q.x - p.x, q.y - p.y)
        guard simd_length(ende) > 1e-6 else { return nil }
        // Pfeilende bei Azimut φ_e: die Kraft zeigt waagrecht in Gegenrichtung, die Höhe von d0 bleibt
        let h0 = simd_normalize(d0)
        let waag = hypot(h0.x, h0.y)
        let u = -simd_normalize(ende)
        return simd_normalize(SIMD3(u.x * waag, u.y * waag, h0.z))
    }

    /// Meridian ziehen: Pfeilende auf dem (beim Anfassen festgelegten) Großkreis, neue Richtung zum Angriffspunkt.
    public static func hoeheZiehen(d0: SIMD3<Float>, punkt p: SIMD3<Float>, laenge l: Float, strahl o: SIMD3<Float>,
                                   _ r: SIMD3<Float>, bisher: SIMD3<Float>) -> SIMD3<Float>? {
        let ring = meridian(punkt: p, richtung: d0, laenge: l, n: 180)
        guard let q = naechster(ring, strahl: o, r, nahAn: pfeilende(p, bisher, l), toleranz: 0.02 * l),
              simd_length(p - q) > 1e-6
        else { return nil }
        return simd_normalize(p - q)
    }

    /// Abstand eines Bildschirmpunkts zu einem Linienzug auf dem Bildschirm (geschlossen).
    public static func abstand(_ p: CGPoint, linie: [CGPoint]) -> CGFloat {
        guard linie.count >= 2 else { return linie.first.map { hypot($0.x - p.x, $0.y - p.y) } ?? .infinity }
        var best = CGFloat.infinity
        for (i, a) in linie.enumerated() {
            let b = linie[(i + 1) % linie.count]
            let ab = CGPoint(x: b.x - a.x, y: b.y - a.y)
            let l2 = ab.x * ab.x + ab.y * ab.y
            var t: CGFloat = 0
            if l2 > 1e-9 { t = max(0, min(1, ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / l2)) }
            let q = CGPoint(x: a.x + ab.x * t, y: a.y + ab.y * t)
            best = min(best, hypot(p.x - q.x, p.y - q.y))
        }
        return best
    }

    // MARK: Einrasten

    /// Nächste Achse oder Flächennormale unter `grad`; die Normale zuerst (ist sie zugleich eine Achse, gewinnt sie).
    public static func einrasten(_ d: SIMD3<Float>, normale: SIMD3<Float>?, grad: Float = einrastGrad)
        -> (richtung: SIMD3<Float>, ziel: Ziel)?
    {
        let v = simd_normalize(d)
        let grenze = cos(grad * .pi / 180)
        var kandidaten: [(SIMD3<Float>, Ziel)] = []
        if let n = normale, simd_length(n) > 1e-9 {
            let m = simd_normalize(n)
            kandidaten += [(-m, .normale(umgekehrt: false)), (m, .normale(umgekehrt: true))]
        }
        kandidaten += SimKraft.achsen.map { ($0.1, .achse($0.0)) }
        guard let best = kandidaten.max(by: { simd_dot($0.0, v) < simd_dot($1.0, v) }),
              simd_dot(best.0, v) >= grenze
        else { return nil }
        return (best.0, best.1)
    }

    /// Richtung der Kraft nach dem Ziehen: eingerastet als Achse bzw. Normale, sonst frei (Winkel auf 0,1° gerundet).
    public static func richtung(_ d: SIMD3<Float>, ziel: Ziel?, alt: SimRichtung) -> SimRichtung {
        switch ziel {
        case .achse(let a)?:
            return SimRichtung(art: .achse, achse: a, azimut: alt.azimut, hoehe: alt.hoehe)
        case .normale(let u)?:
            return SimRichtung(art: .normale, achse: alt.achse, azimut: alt.azimut, hoehe: alt.hoehe, umkehren: u)
        case nil:
            let w = SimKraft.winkel(d)
            return SimRichtung(art: .frei, achse: alt.achse, azimut: (w.azimut * 10).rounded() / 10,
                               hoehe: (w.hoehe * 10).rounded() / 10)
        }
    }
}
