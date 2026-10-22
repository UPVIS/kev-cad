import CoreGraphics
import Foundation

/// Draufsicht einer Druckplatte im Maßstab: Platten-mm (Ursprung vorn links, y nach hinten) ↔ Ansichtspunkte (Ursprung
/// links oben, y nach unten). Vorn liegt unten, wie in Bambu Studio von oben gesehen. Gemeinsam für Panel und Bericht.
public struct DruckPlattenGeometrie: Equatable, Sendable {
    public var bett: DruckBett
    /// Punkte je mm.
    public var massstab: CGFloat
    /// Die Platte in Ansichtskoordinaten.
    public var platte: CGRect

    /// Größte Platte, die mit `rand` ringsum in `rahmen` passt, mittig.
    public init(bett: DruckBett = .p1p, in rahmen: CGRect, rand: CGFloat = 0) {
        self.bett = bett
        let w = max(1, rahmen.width - 2 * rand), h = max(1, rahmen.height - 2 * rand)
        massstab = min(w / CGFloat(bett.breite), h / CGFloat(bett.tiefe))
        let pw = CGFloat(bett.breite) * massstab, ph = CGFloat(bett.tiefe) * massstab
        platte = CGRect(x: rahmen.midX - pw / 2, y: rahmen.midY - ph / 2, width: pw, height: ph)
    }

    /// Platten-mm → Ansicht.
    public func punkt(_ p: SIMD2<Double>) -> CGPoint {
        CGPoint(x: platte.minX + CGFloat(p.x) * massstab, y: platte.maxY - CGFloat(p.y) * massstab)
    }

    /// Ansicht → Platten-mm.
    public func mm(_ p: CGPoint) -> SIMD2<Double> {
        SIMD2(Double((p.x - platte.minX) / massstab), Double((platte.maxY - p.y) / massstab))
    }

    /// Rechteck in Platten-mm → Ansicht (positive Breite und Höhe).
    public func rechteck(_ r: DruckRechteck) -> CGRect {
        let a = punkt(SIMD2(r.x, r.y)), b = punkt(SIMD2(r.x + r.b, r.y + r.t))
        return CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y))
    }

    public var sperrzonen: [CGRect] { bett.sperrzonen.map(rechteck) }

    /// Pfad eines Umrisses in Ansichtskoordinaten.
    public func pfad(_ umriss: [SIMD2<Double>]) -> CGPath {
        let p = CGMutablePath()
        guard let erster = umriss.first else { return p }
        p.move(to: punkt(erster))
        for q in umriss.dropFirst() { p.addLine(to: punkt(q)) }
        p.closeSubpath()
        return p
    }

    /// Gitterlinien alle `schritt` mm (ohne Rand), x-Werte und y-Werte in Platten-mm.
    public func gitter(schritt: Double) -> (x: [Double], y: [Double]) {
        guard schritt > 0 else { return ([], []) }
        let xs = stride(from: schritt, to: bett.breite, by: schritt).map { $0 }
        let ys = stride(from: schritt, to: bett.tiefe, by: schritt).map { $0 }
        return (xs, ys)
    }

    /// Oberstes Teil unter einem Ansichtspunkt (die Liste wird von hinten durchsucht, weil später Gezeichnetes oben
    /// liegt); knapp daneben (bis `toleranz` Punkte) zählt das nächste Teil.
    public func treffer(_ teile: [DruckPlattenTeil], bei p: CGPoint, toleranz: CGFloat = 4) -> DruckPlattenTeil? {
        let q = mm(p)
        for t in teile.reversed() where Self.enthaelt(t.plattenUmriss, q) { return t }
        let grenze = Double(toleranz / max(massstab, 0.0001))
        var best: (DruckPlattenTeil, Double)?
        for t in teile {
            let d = Self.abstand(t.plattenUmriss, q)
            if d <= grenze && (best == nil || d < best!.1) { best = (t, d) }
        }
        return best?.0
    }

    // MARK: Geometrie in mm

    /// Punkt im Vieleck (gerade-ungerade-Regel).
    public static func enthaelt(_ vieleck: [SIMD2<Double>], _ p: SIMD2<Double>) -> Bool {
        guard vieleck.count >= 3 else { return false }
        var drin = false
        var j = vieleck.count - 1
        for i in vieleck.indices {
            let a = vieleck[i], b = vieleck[j]
            if (a.y > p.y) != (b.y > p.y) {
                let x = (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x
                if p.x < x { drin.toggle() }
            }
            j = i
        }
        return drin
    }

    /// Kleinster Abstand eines Punkts zum Rand eines Vielecks.
    public static func abstand(_ vieleck: [SIMD2<Double>], _ p: SIMD2<Double>) -> Double {
        guard !vieleck.isEmpty else { return .infinity }
        var best = Double.infinity
        for i in vieleck.indices {
            let a = vieleck[i], b = vieleck[(i + 1) % vieleck.count]
            let ab = b - a
            let l2 = ab.x * ab.x + ab.y * ab.y
            let t = l2 > 0 ? max(0, min(1, ((p - a).x * ab.x + (p - a).y * ab.y) / l2)) : 0
            let d = p - (a + ab * t)
            best = min(best, (d.x * d.x + d.y * d.y).squareRoot())
        }
        return best
    }

    /// Fläche eines Vielecks in mm² (Gaußsche Trapezformel, Betrag).
    public static func flaeche(_ vieleck: [SIMD2<Double>]) -> Double {
        guard vieleck.count >= 3 else { return 0 }
        var s = 0.0
        for i in vieleck.indices {
            let a = vieleck[i], b = vieleck[(i + 1) % vieleck.count]
            s += a.x * b.y - b.x * a.y
        }
        return abs(s) / 2
    }

    /// Hüllrechteck eines Vielecks in mm.
    public static func huelle(_ vieleck: [SIMD2<Double>]) -> DruckRechteck? {
        guard let f = vieleck.first else { return nil }
        var lo = f, hi = f
        for p in vieleck {
            lo = SIMD2(min(lo.x, p.x), min(lo.y, p.y))
            hi = SIMD2(max(hi.x, p.x), max(hi.y, p.y))
        }
        return DruckRechteck(x: lo.x, y: lo.y, b: hi.x - lo.x, t: hi.y - lo.y)
    }

    /// Belegung einer Platte 0…1: vom Kernel, sonst Summe der Umrissflächen durch die freie Fläche.
    public static func auslastung(_ platte: DruckPlatte, bett: DruckBett = .p1p) -> Double {
        if let a = platte.auslastung { return max(0, min(1, a)) }
        let frei = bett.breite * bett.tiefe - bett.sperrzonen.reduce(0) { $0 + $1.b * $1.t }
        guard frei > 0 else { return 0 }
        return min(1, platte.teile.reduce(0) { $0 + flaeche($1.plattenUmriss) } / frei)
    }

    /// Teile, die (teilweise) außerhalb der Platte oder in einer Sperrzone liegen (zur Prüfung der Anordnung).
    public static func ausserhalb(_ platte: DruckPlatte, bett: DruckBett = .p1p, toleranz: Double = 0.5) -> [String] {
        platte.teile.filter { t in
            let u = t.plattenUmriss
            let raus = u.contains { $0.x < -toleranz || $0.y < -toleranz || $0.x > bett.breite + toleranz
                || $0.y > bett.tiefe + toleranz }
            let gesperrt = bett.sperrzonen.contains { z in
                let innen = DruckRechteck(x: z.x + toleranz, y: z.y + toleranz, b: z.b - 2 * toleranz,
                                          t: z.t - 2 * toleranz)
                return u.contains { p in p.x > innen.x && p.x < innen.x + innen.b && p.y > innen.y
                    && p.y < innen.y + innen.t }
            }
            return raus || gesperrt
        }.map(\.name)
    }
}
