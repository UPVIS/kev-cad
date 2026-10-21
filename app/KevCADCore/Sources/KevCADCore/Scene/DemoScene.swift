import Foundation
import simd

/// Einfache Teile ohne Kernel (Demomodus `KEVCAD_DEMO=1` für Arbeiten an der Oberfläche, und für Tests).
public enum DemoScene {
    public struct Part {
        public var header: PartUpsertHeader
        public var geometry: PartGeometry
        public var step: String
    }

    /// Wandhalter aus Grundplatte, Lasche und Bolzen.
    public static func parts(run: Int = 1) -> [Part] {
        [
            Part(
                header: header(run: run, name: "Grundplatte", color: [0.72, 0.75, 0.79, 1], material: "aluminium"),
                geometry: box(center: SIMD3(0, 0, 2.5), size: SIMD3(120, 80, 5)), step: "Grundplatte"),
            Part(
                header: header(run: run, name: "Halter/Lasche", color: [0.55, 0.62, 0.75, 1], material: "aluminium"),
                geometry: box(center: SIMD3(-57.5, 0, 35), size: SIMD3(5, 80, 60)), step: "Lasche"),
            Part(
                header: header(run: run, name: "Halter/Bolzen", color: [0.85, 0.55, 0.2, 1], material: "messing"),
                geometry: cylinder(base: SIMD3(20, 0, 5), radius: 6, height: 40), step: "Bolzen"),
        ].map { p in
            var p = p
            p.header = completed(p.header, p.geometry)
            return p
        }
    }

    static func header(run: Int, name: String, color: [Float], material: String?) -> PartUpsertHeader {
        PartUpsertHeader(run: run, name: name, color: color, material: material, counts: PartCounts())
    }

    /// Zählwerte, Hüllquader und Flächen-/Kantenwerte aus der Geometrie ergänzen.
    static func completed(_ h: PartUpsertHeader, _ g: PartGeometry) -> PartUpsertHeader {
        var h = h
        h.counts = PartCounts(
            vert: g.vertexCount, tri: g.triangleCount, face: Int((g.triFace.max() ?? -1) + 1), edge: g.edgeCount,
            epts: g.edgePoints.count / 3, vtx: g.brepVertexCount)
        if let b = g.bounds {
            h.bbox = BBox(min: [Double(b.min.x), Double(b.min.y), Double(b.min.z)], max: [Double(b.max.x), Double(b.max.y), Double(b.max.z)])
        }
        h.faces = (0..<h.counts.face).map { f in faceInfo(g, f) }
        h.edges = (0..<g.edgeCount).map { e in edgeInfo(g, e) }
        var volume = 0.0, area = 0.0
        for t in 0..<g.triangleCount {
            let a = g.position(Int(g.triangles[t * 3])), b = g.position(Int(g.triangles[t * 3 + 1]))
            let c = g.position(Int(g.triangles[t * 3 + 2]))
            volume += Double(simd_dot(a, simd_cross(b, c))) / 6
            area += Double(simd_length(simd_cross(b - a, c - a))) / 2
        }
        var props: [String: JSONValue] = ["volume": .number(abs(volume)), "area": .number(area)]
        if h.material != nil { props["mass"] = .number(abs(volume) * 2.70e-3) }
        if let b = g.bounds { props["center"] = JSONValue.from((b.min + b.max) * 0.5) }
        h.props = .object(props)
        return h
    }

    static func faceInfo(_ g: PartGeometry, _ f: Int) -> FaceInfo {
        var area: Float = 0
        var nsum = SIMD3<Float>(repeating: 0)
        var csum = SIMD3<Float>(repeating: 0)
        var normals: [SIMD3<Float>] = []
        for t in 0..<g.triangleCount where Int(g.triFace[t]) == f {
            let a = g.position(Int(g.triangles[t * 3])), b = g.position(Int(g.triangles[t * 3 + 1]))
            let c = g.position(Int(g.triangles[t * 3 + 2]))
            let cr = simd_cross(b - a, c - a)
            let ar = simd_length(cr) / 2
            area += ar
            if ar > 0 { normals.append(cr / (2 * ar)) }
            nsum += cr
            csum += (a + b + c) / 3 * ar
        }
        let planar = normals.allSatisfy { simd_dot($0, normals.first ?? $0) > 0.9999 }
        let c = area > 0 ? csum / area : .zero
        func d(_ v: SIMD3<Float>) -> [Double] { [Double(v.x), Double(v.y), Double(v.z)].map { ($0 * 1e4).rounded() / 1e4 } }
        if planar, simd_length(nsum) > 0 {
            return FaceInfo(t: "plane", a: Double(area), n: d(simd_normalize(nsum)), c: d(c))
        }
        return FaceInfo(t: "cylinder", a: Double(area), c: d(c))
    }

    static func edgeInfo(_ g: PartGeometry, _ e: Int) -> EdgeInfo {
        let poly = g.edgePolyline(e)
        var len: Float = 0
        for i in 1..<max(poly.count, 1) { len += simd_distance(poly[i], poly[i - 1]) }
        if poly.count > 2 {
            let c = poly.reduce(SIMD3<Float>(repeating: 0), +) / Float(poly.count)
            let r = simd_distance(poly[0], c)
            return EdgeInfo(t: "circle", l: Double(len), r: Double(r), c: [Double(c.x), Double(c.y), Double(c.z)])
        }
        return EdgeInfo(t: "line", l: Double(len))
    }

    // MARK: Geometrie

    public static func box(center c: SIMD3<Float>, size s: SIMD3<Float>) -> PartGeometry {
        let lo = c - s / 2, hi = c + s / 2
        let dx = SIMD3<Float>(s.x, 0, 0), dy = SIMD3<Float>(0, s.y, 0), dz = SIMD3<Float>(0, 0, s.z)
        let quads: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)] = [
            (lo, dz, dy), (SIMD3(hi.x, lo.y, lo.z), dy, dz),
            (lo, dx, dz), (SIMD3(lo.x, hi.y, lo.z), dz, dx),
            (lo, dy, dx), (SIMD3(lo.x, lo.y, hi.z), dx, dy),
        ]
        var g = PartGeometry()
        for (f, q) in quads.enumerated() {
            let (o, u, v) = q
            let n = simd_normalize(simd_cross(u, v))
            let base = UInt32(g.vertexCount)
            for p in [o, o + u, o + u + v, o + v] {
                g.positions += [p.x, p.y, p.z]
                g.normals += [n.x, n.y, n.z]
            }
            g.triangles += [base, base + 1, base + 2, base, base + 2, base + 3]
            g.triFace += [Int32(f), Int32(f)]
        }
        let corners = (0..<8).map { i in
            SIMD3<Float>(i & 1 == 0 ? lo.x : hi.x, i & 2 == 0 ? lo.y : hi.y, i & 4 == 0 ? lo.z : hi.z)
        }
        let pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        g.edgeOffsets = [0]
        for (a, b) in pairs {
            for p in [corners[a], corners[b]] { g.edgePoints += [p.x, p.y, p.z] }
            g.edgeOffsets.append(UInt32(g.edgePoints.count / 3))
        }
        for p in corners { g.vertices += [p.x, p.y, p.z] }
        return g
    }

    /// Zylinder entlang Z: Mantel (Fläche 0), Boden (1), Deckel (2); Kanten unten, Naht, oben.
    public static func cylinder(base b: SIMD3<Float>, radius r: Float, height h: Float, segments n: Int = 48) -> PartGeometry {
        var g = PartGeometry()
        func ring(_ z: Float) -> [SIMD3<Float>] {
            (0...n).map { i in
                let a = Float(i) / Float(n) * 2 * .pi
                return b + SIMD3(r * cos(a), r * sin(a), z)
            }
        }
        let bottom = ring(0), top = ring(h)
        // Mantel
        for i in 0...n {
            for p in [bottom[i], top[i]] {
                let nr = simd_normalize(SIMD3(p.x - b.x, p.y - b.y, 0))
                g.positions += [p.x, p.y, p.z]
                g.normals += [nr.x, nr.y, nr.z]
            }
        }
        for i in 0..<n {
            let a = UInt32(i * 2)
            g.triangles += [a, a + 2, a + 1, a + 1, a + 2, a + 3]
            g.triFace += [0, 0]
        }
        // Boden und Deckel als Fächer
        for (face, pts, z, nz) in [(Int32(1), bottom, Float(0), Float(-1)), (Int32(2), top, h, Float(1))] {
            let center = UInt32(g.vertexCount)
            let cp = b + SIMD3(0, 0, z)
            g.positions += [cp.x, cp.y, cp.z]
            g.normals += [0, 0, nz]
            for p in pts {
                g.positions += [p.x, p.y, p.z]
                g.normals += [0, 0, nz]
            }
            for i in 0..<n {
                let a = center + 1 + UInt32(i)
                g.triangles += nz > 0 ? [center, a, a + 1] : [center, a + 1, a]
                g.triFace.append(face)
            }
        }
        g.edgeOffsets = [0]
        for line in [bottom, [bottom[0], top[0]], top] {
            for p in line { g.edgePoints += [p.x, p.y, p.z] }
            g.edgeOffsets.append(UInt32(g.edgePoints.count / 3))
        }
        for p in [bottom[0], top[0]] { g.vertices += [p.x, p.y, p.z] }
        return g
    }

    // MARK: Messen ohne Kernel

    @MainActor
    public static func measure(_ refs: [ElementRef], in scene: SceneStore) -> MeasureResult {
        let pts = refs.compactMap { scene.worldAnchor(of: $0) }
        if refs.count >= 2, pts.count >= 2, refs[0] != refs[1] {
            let d = pts[1] - pts[0]
            let text = "Abstand \(GermanFormat.mm(Double(simd_length(d)))) (Demo, Mittelpunkte)"
            return MeasureResult(
                refs: refs.map(\.string), run: scene.latestRun, kind: "distance",
                values: .object([
                    "distance": .number(Double(simd_length(d))), "dx": .number(Double(d.x)), "dy": .number(Double(d.y)),
                    "dz": .number(Double(d.z)),
                ]),
                points: pts.map { [Double($0.x), Double($0.y), Double($0.z)] }, text: text)
        }
        let ref = refs.first ?? .part("")
        let item = scene.record(ref.part)?.selectionItem(for: ref)
        return MeasureResult(
            refs: [ref.string], run: scene.latestRun, kind: ref.kind.rawValue,
            values: .object((item?.values ?? [:]).mapValues { .number($0) }),
            points: pts.prefix(1).map { [Double($0.x), Double($0.y), Double($0.z)] }, text: item?.summary ?? ref.string)
    }
}
