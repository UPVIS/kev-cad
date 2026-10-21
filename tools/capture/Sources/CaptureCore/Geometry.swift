import Foundation
import simd

/// Dreiecksnetz aus einer OBJ-Datei von Object Capture. Hält die Originalzeilen, damit Texturkoordinaten,
/// Normalen und Materialverweise beim Export unverändert bleiben.
public final class OBJMesh {
    public var positions: [SIMD3<Double>] = []
    public var faces: [SIMD3<Int32>] = []          // Ecken (0-basiert), Polygone als Fächer zerlegt
    public var uvs: [SIMD2<Float>] = []
    public var faceUVs: [SIMD3<Int32>] = []        // Texturkoordinaten je Dreiecksecke (−1 = keine)
    var lines: [Substring] = []
    var vertexLine: [Int] = []                      // Zeilennummer je Ecke
    var normalLine: [Int] = []
    public let url: URL

    public init(url: URL) throws {
        self.url = url
        let text = try String(contentsOf: url, encoding: .utf8)
        lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        positions.reserveCapacity(lines.count / 3)
        for (li, line) in lines.enumerated() {
            if line.hasPrefix("v ") {
                let p = line.split(separator: " ")
                guard p.count >= 4, let x = Double(p[1]), let y = Double(p[2]), let z = Double(p[3]) else { continue }
                positions.append(SIMD3(x, y, z))
                vertexLine.append(li)
            } else if line.hasPrefix("vt ") {
                let p = line.split(separator: " ")
                if p.count >= 3, let u = Float(p[1]), let v = Float(p[2]) { uvs.append(SIMD2(u, v)) }
            } else if line.hasPrefix("vn ") {
                normalLine.append(li)
            } else if line.hasPrefix("f ") {
                let p = line.split(separator: " ").dropFirst()
                var idx: [Int32] = []
                var tix: [Int32] = []
                idx.reserveCapacity(4)
                for tok in p {
                    let parts = tok.split(separator: "/", omittingEmptySubsequences: false)
                    if var i = Int32(parts.first ?? tok) {
                        if i < 0 { i = Int32(positions.count) + i + 1 }
                        idx.append(i - 1)
                        var t: Int32 = 0
                        if parts.count > 1, let tv = Int32(parts[1]) { t = tv < 0 ? Int32(uvs.count) + tv + 1 : tv }
                        tix.append(t - 1)
                    }
                }
                if idx.count >= 3 {
                    for k in 1..<(idx.count - 1) {
                        faces.append(SIMD3(idx[0], idx[k], idx[k + 1]))
                        faceUVs.append(SIMD3(tix[0], tix[k], tix[k + 1]))
                    }
                }
            }
        }
    }

    /// Schreibt das Netz mit transformierten Ecken (und Normalen). `keepFace` entscheidet je Dreieck
    /// (Index in `faces`), ob es bleibt; Ecken bleiben alle erhalten (Indizes stabil).
    public func write(to out: URL, transform m: simd_double4x4, keepFace: [Bool]?, mtlName: String?) throws {
        let rot = simd_double3x3(columns: (m.columns.0.xyz, m.columns.1.xyz, m.columns.2.xyz))
        let nrm = rot.inverse.transpose
        var vi = 0, ni = 0, fi = 0
        var outText = ""
        outText.reserveCapacity(lines.count * 40)
        let vset = Dictionary(uniqueKeysWithValues: vertexLine.enumerated().map { ($1, $0) })
        let nset = Set(normalLine)
        for (li, line) in lines.enumerated() {
            if let k = vset[li] {
                let p = m * SIMD4(positions[k], 1)
                let rest = line.split(separator: " ").dropFirst(4) // Farben je Ecke, falls vorhanden
                outText += String(format: "v %.4f %.4f %.4f", p.x, p.y, p.z)
                for r in rest { outText += " " + r }
                outText += "\n"
                vi += 1
            } else if nset.contains(li) {
                let p = line.split(separator: " ")
                if p.count >= 4, let x = Double(p[1]), let y = Double(p[2]), let z = Double(p[3]) {
                    let n = simd_normalize(nrm * SIMD3(x, y, z))
                    outText += String(format: "vn %.5f %.5f %.5f\n", n.x, n.y, n.z)
                } else {
                    outText += line + "\n"
                }
                ni += 1
            } else if line.hasPrefix("f ") {
                let tris = max(1, line.split(separator: " ").count - 3)
                let keep = keepFace.map { fi < $0.count ? $0[fi] : true } ?? true
                fi += tris
                if keep { outText += line + "\n" }
            } else if line.hasPrefix("mtllib "), let mtl = mtlName {
                outText += "mtllib \(mtl)\n"
            } else if line.hasPrefix("#") && li < 3 {
                outText += line + "\n"
                if li == 0 { outText += "# kevcad-capture: ausgerichtet, mm, Z oben, Boden z = 0\n" }
            } else {
                outText += line + "\n"
            }
        }
        if !lines.isEmpty && lines.last == "" { outText.removeLast() }
        try outText.write(to: out, atomically: true, encoding: .utf8)
        _ = (vi, ni)
    }
}

public enum PLYReader {
    /// Liest die binäre PLY, die `PLYWriter` schreibt (float xyz, optional uchar rgb).
    public static func read(_ url: URL) throws -> ([SIMD3<Float>], [SIMD4<UInt8>]) {
        let data = try Data(contentsOf: url)
        guard let end = data.range(of: Data("end_header\n".utf8)) else { throw CaptureError.message("PLY ohne Kopf") }
        let header = String(decoding: data[..<end.lowerBound], as: UTF8.self)
        var count = 0
        for l in header.split(separator: "\n") where l.hasPrefix("element vertex") {
            count = Int(l.split(separator: " ").last ?? "0") ?? 0
        }
        let hasColor = header.contains("property uchar red")
        let stride = hasColor ? 15 : 12
        var pts: [SIMD3<Float>] = []
        var cols: [SIMD4<UInt8>] = []
        pts.reserveCapacity(count)
        data.withUnsafeBytes { raw in
            var o = end.upperBound
            for _ in 0..<count {
                guard o + stride <= raw.count else { break }
                let x = raw.loadUnaligned(fromByteOffset: o, as: Float.self)
                let y = raw.loadUnaligned(fromByteOffset: o + 4, as: Float.self)
                let z = raw.loadUnaligned(fromByteOffset: o + 8, as: Float.self)
                pts.append(SIMD3(x, y, z))
                if hasColor { cols.append(SIMD4(raw[o + 12], raw[o + 13], raw[o + 14], 255)) }
                o += stride
            }
        }
        return (pts, cols)
    }
}

/// Kleiner, reproduzierbarer Zufallsgenerator (für RANSAC).
public struct SplitMix64: RandomNumberGenerator {
    var state: UInt64
    public init(seed: UInt64) { state = seed }
    public mutating func next() -> UInt64 {
        state &+= 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

public struct Plane {
    public var normal: SIMD3<Double>   // Einheitsvektor
    public var d: Double               // n·x + d = 0
    public func distance(_ p: SIMD3<Double>) -> Double { simd_dot(normal, p) + d }
    public init(normal: SIMD3<Double>, d: Double) { self.normal = normal; self.d = d }
    public init(normal: SIMD3<Double>, through p: SIMD3<Double>) {
        self.normal = simd_normalize(normal)
        self.d = -simd_dot(self.normal, p)
    }
}

public enum Geo {
    /// RANSAC-Ebene. `allowed` filtert Normalen (z. B. nur nahe einer Richtung).
    public static func ransacPlane(_ pts: [SIMD3<Double>], threshold: Double, iterations: Int = 600,
                                   seed: UInt64 = 1, allowed: ((SIMD3<Double>) -> Bool)? = nil) -> (Plane, [Int])? {
        guard pts.count >= 3 else { return nil }
        var rng = SplitMix64(seed: seed)
        var best: Plane? = nil
        var bestCount = 0
        // auf höchstens 20 000 Punkte ausdünnen, Endauswertung auf allen
        let sample: [SIMD3<Double>] = pts.count > 20000
            ? (0..<20000).map { _ in pts[Int.random(in: 0..<pts.count, using: &rng)] } : pts
        for _ in 0..<iterations {
            let a = sample[Int.random(in: 0..<sample.count, using: &rng)]
            let b = sample[Int.random(in: 0..<sample.count, using: &rng)]
            let c = sample[Int.random(in: 0..<sample.count, using: &rng)]
            let n = simd_cross(b - a, c - a)
            let len = simd_length(n)
            if len < 1e-12 { continue }
            let pl = Plane(normal: n / len, through: a)
            if let f = allowed, !f(pl.normal) { continue }
            var cnt = 0
            for p in sample where abs(pl.distance(p)) < threshold { cnt += 1 }
            if cnt > bestCount { bestCount = cnt; best = pl }
        }
        guard var pl = best else { return nil }
        // Verfeinern: Ausgleichsebene durch die Inlier (zweimal)
        var inl: [Int] = []
        for _ in 0..<2 {
            inl = pts.indices.filter { abs(pl.distance(pts[$0])) < threshold }
            guard inl.count >= 3, let fit = fitPlane(inl.map { pts[$0] }) else { break }
            pl = simd_dot(fit.normal, pl.normal) < 0 ? Plane(normal: -fit.normal, d: -fit.d) : fit
        }
        inl = pts.indices.filter { abs(pl.distance(pts[$0])) < threshold }
        return (pl, inl)
    }

    /// Ausgleichsebene (kleinster Eigenvektor der Kovarianz).
    public static func fitPlane(_ pts: [SIMD3<Double>]) -> Plane? {
        guard pts.count >= 3 else { return nil }
        let (c, vecs, _) = pca(pts)
        return Plane(normal: vecs[2], through: c)
    }

    /// Hauptachsen: Mittelpunkt, Eigenvektoren (absteigend nach Varianz), Eigenwerte.
    public static func pca(_ pts: [SIMD3<Double>]) -> (SIMD3<Double>, [SIMD3<Double>], [Double]) {
        var c = SIMD3<Double>(repeating: 0)
        for p in pts { c += p }
        c /= Double(max(pts.count, 1))
        var m = simd_double3x3(0)
        for p in pts {
            let q = p - c
            m += simd_double3x3(columns: (q * q.x, q * q.y, q * q.z))
        }
        m = m * (1.0 / Double(max(pts.count, 1)))
        let (vals, vecs) = symmetricEigen(m)
        return (c, vecs, vals)
    }

    /// Jacobi-Verfahren für symmetrische 3×3-Matrizen; Eigenwerte absteigend.
    public static func symmetricEigen(_ m: simd_double3x3) -> ([Double], [SIMD3<Double>]) {
        var a = [[m[0][0], m[1][0], m[2][0]], [m[0][1], m[1][1], m[2][1]], [m[0][2], m[1][2], m[2][2]]]
        var v = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
        for _ in 0..<50 {
            var off = 0.0
            for i in 0..<3 { for j in 0..<3 where i != j { off += a[i][j] * a[i][j] } }
            if off < 1e-22 { break }
            for p in 0..<2 {
                for q in (p + 1)..<3 where abs(a[p][q]) > 1e-30 {
                    let theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                    let t = (theta >= 0 ? 1.0 : -1.0) / (abs(theta) + (theta * theta + 1).squareRoot())
                    let c = 1 / (t * t + 1).squareRoot(), s = t * c
                    for k in 0..<3 {
                        let akp = a[k][p], akq = a[k][q]
                        a[k][p] = c * akp - s * akq
                        a[k][q] = s * akp + c * akq
                    }
                    for k in 0..<3 {
                        let apk = a[p][k], aqk = a[q][k]
                        a[p][k] = c * apk - s * aqk
                        a[q][k] = s * apk + c * aqk
                    }
                    for k in 0..<3 {
                        let vkp = v[k][p], vkq = v[k][q]
                        v[k][p] = c * vkp - s * vkq
                        v[k][q] = s * vkp + c * vkq
                    }
                }
            }
        }
        var pairs = (0..<3).map { (a[$0][$0], SIMD3(v[0][$0], v[1][$0], v[2][$0])) }
        pairs.sort { $0.0 > $1.0 }
        return (pairs.map { $0.0 }, pairs.map { simd_normalize($0.1) })
    }

    public static func percentile(_ xs: [Double], _ q: Double) -> Double {
        guard !xs.isEmpty else { return .nan }
        let s = xs.sorted()
        let pos = min(max(q, 0), 1) * Double(s.count - 1)
        let lo = Int(pos.rounded(.down)), hi = Int(pos.rounded(.up))
        return s[lo] + (s[hi] - s[lo]) * (pos - Double(lo))
    }

    /// Konvexe Hülle in 2D (Andrew), gegen den Uhrzeigersinn.
    public static func convexHull(_ pts: [SIMD2<Double>]) -> [SIMD2<Double>] {
        let p = pts.sorted { $0.x < $1.x || ($0.x == $1.x && $0.y < $1.y) }
        guard p.count > 2 else { return p }
        func cross(_ o: SIMD2<Double>, _ a: SIMD2<Double>, _ b: SIMD2<Double>) -> Double {
            (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
        }
        var lower: [SIMD2<Double>] = [], upper: [SIMD2<Double>] = []
        for q in p {
            while lower.count >= 2 && cross(lower[lower.count - 2], lower[lower.count - 1], q) <= 0 { lower.removeLast() }
            lower.append(q)
        }
        for q in p.reversed() {
            while upper.count >= 2 && cross(upper[upper.count - 2], upper[upper.count - 1], q) <= 0 { upper.removeLast() }
            upper.append(q)
        }
        return Array(lower.dropLast() + upper.dropLast())
    }

    /// Kleinstes umschließendes Rechteck (Drehschieblehre über die Hüllkanten):
    /// Winkel der langen Seite, Länge, Breite, Mittelpunkt.
    public static func minAreaRect(_ pts: [SIMD2<Double>]) -> (angle: Double, length: Double, width: Double, center: SIMD2<Double>) {
        let hull = convexHull(pts)
        guard hull.count >= 3 else { return (0, 0, 0, .zero) }
        var best = (area: Double.infinity, angle: 0.0, l: 0.0, w: 0.0, c: SIMD2<Double>.zero)
        for i in hull.indices {
            let e = hull[(i + 1) % hull.count] - hull[i]
            let ang = atan2(e.y, e.x)
            let u = SIMD2(cos(ang), sin(ang)), v = SIMD2(-sin(ang), cos(ang))
            var minU = Double.infinity, maxU = -Double.infinity, minV = Double.infinity, maxV = -Double.infinity
            for q in hull {
                let a = simd_dot(q, u), b = simd_dot(q, v)
                minU = min(minU, a); maxU = max(maxU, a); minV = min(minV, b); maxV = max(maxV, b)
            }
            let area = (maxU - minU) * (maxV - minV)
            if area < best.area {
                let c = u * (minU + maxU) / 2 + v * (minV + maxV) / 2
                if maxU - minU >= maxV - minV {
                    best = (area, ang, maxU - minU, maxV - minV, c)
                } else {
                    best = (area, ang + .pi / 2, maxV - minV, maxU - minU, c)
                }
            }
        }
        var a = best.angle.truncatingRemainder(dividingBy: .pi)
        if a > .pi / 2 { a -= .pi } else if a < -.pi / 2 { a += .pi }
        return (a, best.l, best.w, best.c)
    }

    /// Kreis durch Punkte (algebraisch nach Kåsa), RANSAC-gestützt.
    public static func fitCircle(_ pts: [SIMD2<Double>], threshold: Double, iterations: Int = 400,
                                 seed: UInt64 = 7) -> (center: SIMD2<Double>, radius: Double, inliers: Int)? {
        guard pts.count >= 8 else { return nil }
        var rng = SplitMix64(seed: seed)
        func circle3(_ a: SIMD2<Double>, _ b: SIMD2<Double>, _ c: SIMD2<Double>) -> (SIMD2<Double>, Double)? {
            let d = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y))
            if abs(d) < 1e-12 { return nil }
            let a2 = simd_length_squared(a), b2 = simd_length_squared(b), c2 = simd_length_squared(c)
            let ux = (a2 * (b.y - c.y) + b2 * (c.y - a.y) + c2 * (a.y - b.y)) / d
            let uy = (a2 * (c.x - b.x) + b2 * (a.x - c.x) + c2 * (b.x - a.x)) / d
            let cc = SIMD2(ux, uy)
            return (cc, simd_length(a - cc))
        }
        var best: (SIMD2<Double>, Double, Int)? = nil
        for _ in 0..<iterations {
            let a = pts[Int.random(in: 0..<pts.count, using: &rng)]
            let b = pts[Int.random(in: 0..<pts.count, using: &rng)]
            let c = pts[Int.random(in: 0..<pts.count, using: &rng)]
            guard let (cc, r) = circle3(a, b, c) else { continue }
            var n = 0
            for p in pts where abs(simd_length(p - cc) - r) < threshold { n += 1 }
            if n > (best?.2 ?? 0) { best = (cc, r, n) }
        }
        guard let (c0, r0, _) = best else { return nil }
        // Kåsa-Ausgleich auf den Inliern
        let inl = pts.filter { abs(simd_length($0 - c0) - r0) < threshold }
        guard inl.count >= 5 else { return (c0, r0, inl.count) }
        var sxx = 0.0, sxy = 0.0, syy = 0.0, sx = 0.0, sy = 0.0, sxz = 0.0, syz = 0.0, sz = 0.0
        for p in inl {
            let z = p.x * p.x + p.y * p.y
            sxx += p.x * p.x; sxy += p.x * p.y; syy += p.y * p.y; sx += p.x; sy += p.y
            sxz += p.x * z; syz += p.y * z; sz += z
        }
        let n = Double(inl.count)
        let m = simd_double3x3(rows: [SIMD3(sxx, sxy, sx), SIMD3(sxy, syy, sy), SIMD3(sx, sy, n)])
        guard abs(m.determinant) > 1e-12 else { return (c0, r0, inl.count) }
        let sol = m.inverse * SIMD3(sxz, syz, sz)
        let cc = SIMD2(sol.x / 2, sol.y / 2)
        let r = (sol.z + simd_length_squared(cc)).squareRoot()
        return (cc, r, inl.count)
    }
}

extension SIMD4 where Scalar == Double {
    var xyz: SIMD3<Double> { SIMD3(x, y, z) }
}
