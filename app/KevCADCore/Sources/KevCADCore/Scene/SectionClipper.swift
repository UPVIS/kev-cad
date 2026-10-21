import Foundation
import OCCTSwiftViewport
import simd

/// Schneidet Dreiecke und Kantenzüge an einer Ebene ab (auf der CPU). Der Viewport schneidet live im Shader; für
/// Bilder über den `OffscreenRenderer`, der keine Schnittebenen kennt, wird die Geometrie hier vorher beschnitten.
/// Es gilt dieselbe Regel wie bei `ClipPlane`: entfernt wird, wo `dot(normal, p) + distance < 0`.
public enum SectionClipper {
    /// Dreiecks-Suppe (verschachtelt, 6 Werte je Punkt, je 3 Punkte ein Dreieck) beschneiden.
    public static func clipTriangles(_ soup: [Float], plane: ClipPlane) -> [Float] {
        let n = plane.normal, d = plane.distance
        var out: [Float] = []
        out.reserveCapacity(soup.count)
        var i = 0
        while i + 17 < soup.count {
            var p = [SIMD3<Float>](), nr = [SIMD3<Float>]()
            for k in 0..<3 {
                let b = i + k * 6
                p.append(SIMD3(soup[b], soup[b + 1], soup[b + 2]))
                nr.append(SIMD3(soup[b + 3], soup[b + 4], soup[b + 5]))
            }
            let s = p.map { simd_dot(n, $0) + d }
            if s[0] >= 0 && s[1] >= 0 && s[2] >= 0 {
                out.append(contentsOf: soup[i..<(i + 18)])
            } else if s[0] < 0 && s[1] < 0 && s[2] < 0 {
                // ganz weg
            } else {
                // Sutherland-Hodgman an einer Ebene
                var poly: [(SIMD3<Float>, SIMD3<Float>)] = []
                for k in 0..<3 {
                    let j = (k + 1) % 3
                    let sk = s[k], sj = s[j]
                    if sk >= 0 { poly.append((p[k], nr[k])) }
                    if (sk >= 0) != (sj >= 0) {
                        let t = sk / (sk - sj)
                        let m = nr[k] + (nr[j] - nr[k]) * t
                        let len = simd_length(m)
                        poly.append((p[k] + (p[j] - p[k]) * t, len > 1e-12 ? m / len : nr[k]))
                    }
                }
                if poly.count >= 3 {
                    for k in 1..<(poly.count - 1) {
                        for v in [poly[0], poly[k], poly[k + 1]] {
                            out.append(contentsOf: [v.0.x, v.0.y, v.0.z, v.1.x, v.1.y, v.1.z])
                        }
                    }
                }
            }
            i += 18
        }
        return out
    }

    /// Kantenzüge beschneiden; ein Zug kann dabei in mehrere zerfallen.
    public static func clipPolylines(_ lines: [[SIMD3<Float>]], plane: ClipPlane) -> [[SIMD3<Float>]] {
        let n = plane.normal, d = plane.distance
        var out: [[SIMD3<Float>]] = []
        for line in lines {
            var current: [SIMD3<Float>] = []
            for k in 0..<line.count {
                let p = line[k]
                let sp = simd_dot(n, p) + d
                if k == 0 {
                    if sp >= 0 { current.append(p) }
                    continue
                }
                let q = line[k - 1]
                let sq = simd_dot(n, q) + d
                if sq >= 0 && sp >= 0 {
                    current.append(p)
                } else if sq >= 0 && sp < 0 {
                    current.append(q + (p - q) * (sq / (sq - sp)))
                    if current.count >= 2 { out.append(current) }
                    current = []
                } else if sq < 0 && sp >= 0 {
                    current = [q + (p - q) * (sq / (sq - sp)), p]
                }
            }
            if current.count >= 2 { out.append(current) }
        }
        return out
    }
}
