import Foundation
import simd

/// Ein Teil der Szene: Kopf und Geometrie aus PART_UPSERT, dazu die vorbereiteten Körper-Stücke.
public struct PartRecord: Sendable {
    public var header: PartUpsertHeader
    public var geometry: PartGeometry
    public var chunks: [PartChunk]
    /// Prüfsumme über Kopfwerte und Nutzlast; gleich bedeutet: Körper müssen nicht neu gebaut werden.
    public var digest: Int
    /// Lokaler Hüllquader (vor `transform`).
    public var localMin: SIMD3<Float>
    public var localMax: SIMD3<Float>

    public var name: String { header.name }
    public var run: Int { header.run }

    /// Baut die Stücke (aufwendig, läuft auf dem Lesethread der Verbindung).
    public init(header: PartUpsertHeader, geometry: PartGeometry, digest: Int? = nil) {
        self.header = header
        self.geometry = geometry
        self.chunks = ChunkBuilder.build(geometry)
        self.digest = digest ?? PartRecord.digest(header: header, geometry: geometry)
        // Der Hüllquader aus dem Kernel ist exakt (B-Rep); ohne Lage-Matrix gilt er direkt, sonst aus den Punkten
        if header.transform == nil, let lo = header.bbox?.minVector, let hi = header.bbox?.maxVector {
            localMin = lo
            localMax = hi
        } else if let b = geometry.bounds {
            localMin = b.min
            localMax = b.max
        } else {
            localMin = .zero
            localMax = .zero
        }
    }

    public static func digest(header: PartUpsertHeader, geometry: PartGeometry) -> Int {
        var h = Hasher()
        h.combine(header.name)
        h.combine(header.color ?? [])
        h.combine(header.material)
        h.combine(header.transform ?? [])
        h.combine(geometry.positions.count)
        h.combine(geometry.triangles.count)
        h.combine(geometry.edgePoints.count)
        geometry.positions.withUnsafeBytes { h.combine(bytes: $0) }
        geometry.triangles.withUnsafeBytes { h.combine(bytes: $0) }
        geometry.triFace.withUnsafeBytes { h.combine(bytes: $0) }
        geometry.edgePoints.withUnsafeBytes { h.combine(bytes: $0) }
        geometry.edgeOffsets.withUnsafeBytes { h.combine(bytes: $0) }
        geometry.vertices.withUnsafeBytes { h.combine(bytes: $0) }
        return h.finalize()
    }

    public var faceCount: Int { max(header.faces.count, header.counts.face) }
    public var edgeCount: Int { max(header.edges.count, geometry.edgeCount) }
    public var vertexCount: Int { geometry.brepVertexCount }
    public var triangleCount: Int { geometry.triangleCount }

    /// Gibt es das Element in diesem Teil?
    public func contains(_ ref: ElementRef) -> Bool {
        switch ref.kind {
        case .part: return true
        case .face: return ref.index >= 0 && ref.index < faceCount
        case .edge: return ref.index >= 0 && ref.index < edgeCount
        case .vertex: return ref.index >= 0 && ref.index < vertexCount
        }
    }

    // MARK: Geometrie einzelner Elemente (lokal)

    /// Hüllquader eines Elements in Teilkoordinaten.
    public func localBounds(of ref: ElementRef) -> (min: SIMD3<Float>, max: SIMD3<Float>)? {
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        var any = false
        func add(_ p: SIMD3<Float>) {
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
            any = true
        }
        switch ref.kind {
        case .part:
            return (localMin, localMax)
        case .face:
            let f = Int32(ref.index)
            let g = geometry
            for t in 0..<g.triangleCount where g.triFace[t] == f {
                for k in 0..<3 { add(g.position(Int(g.triangles[t * 3 + k]))) }
            }
        case .edge:
            for p in geometry.edgePolyline(ref.index) { add(p) }
        case .vertex:
            guard ref.index < vertexCount else { return nil }
            add(geometry.brepVertex(ref.index))
        }
        return any ? (lo, hi) : nil
    }

    /// Ein gut sichtbarer Punkt des Elements (für Beschriftungen), in Teilkoordinaten.
    public func anchorPoint(of ref: ElementRef) -> SIMD3<Float>? {
        switch ref.kind {
        case .vertex:
            return ref.index < vertexCount ? geometry.brepVertex(ref.index) : nil
        case .edge:
            let poly = geometry.edgePolyline(ref.index)
            return poly.isEmpty ? nil : poly[poly.count / 2]
        case .face:
            // Mittelpunkt des größten Dreiecks der Fläche liegt sicher auf ihr
            let f = Int32(ref.index)
            let g = geometry
            var best: SIMD3<Float>? = nil
            var bestArea: Float = -1
            for t in 0..<g.triangleCount where g.triFace[t] == f {
                let a = g.position(Int(g.triangles[t * 3])), b = g.position(Int(g.triangles[t * 3 + 1]))
                let c = g.position(Int(g.triangles[t * 3 + 2]))
                let area = simd_length(simd_cross(b - a, c - a))
                if area > bestArea {
                    bestArea = area
                    best = (a + b + c) / 3
                }
            }
            return best
        case .part:
            if let c = header.center { return c }
            return (localMin + localMax) * 0.5
        }
    }

    // MARK: Sofortwerte für den Inspektor

    /// Kurzbeschreibung und Werte ohne Rückfrage beim Kernel (aus den Metadaten von PART_UPSERT).
    public func selectionItem(for ref: ElementRef) -> SelectionItem {
        var values: [String: Double] = [:]
        var text: String
        func vec(_ prefix: String, _ v: [Double]?) {
            guard let v, v.count >= 3 else { return }
            values["\(prefix)_x"] = v[0]
            values["\(prefix)_y"] = v[1]
            values["\(prefix)_z"] = v[2]
        }
        switch ref.kind {
        case .face:
            text = "Fläche \(ref.index)"
            if ref.index < header.faces.count {
                let f = header.faces[ref.index]
                text += " · " + GermanFormat.faceType(f.t)
                if let r = f.r {
                    text += " r " + GermanFormat.mm(r)
                    values["radius"] = r
                }
                if let r2 = f.r2 {
                    text += " / " + GermanFormat.mm(r2)
                    values["radius2"] = r2
                }
                if let ang = f.ang {
                    text += " · Halbwinkel " + GermanFormat.degrees(ang)
                    values["half_angle"] = ang
                }
                if let a = f.a {
                    text += " · " + GermanFormat.mm2(a)
                    values["area"] = a
                }
                vec("normal", f.n)
                vec("center", f.c)
                vec("axis", f.ax)
            }
        case .edge:
            text = "Kante \(ref.index)"
            if ref.index < header.edges.count {
                let e = header.edges[ref.index]
                text += " · " + GermanFormat.edgeType(e.t)
                if let r = e.r {
                    text += " r " + GermanFormat.mm(r)
                    values["radius"] = r
                }
                if let r2 = e.r2 {
                    text += " / " + GermanFormat.mm(r2)
                    values["radius2"] = r2
                }
                if let l = e.l {
                    text += " · " + GermanFormat.mm(l)
                    values["length"] = l
                }
                vec("center", e.c)
                vec("axis", e.ax)
            }
        case .vertex:
            text = "Punkt \(ref.index)"
            if ref.index < vertexCount {
                let p = geometry.brepVertex(ref.index)
                text += " · " + GermanFormat.point(p, decimals: 3)
                values["x"] = Double(p.x)
                values["y"] = Double(p.y)
                values["z"] = Double(p.z)
            }
        case .part:
            let size = localMax - localMin
            text = "\(name) · " + GermanFormat.size(size)
            values["size_x"] = Double(size.x)
            values["size_y"] = Double(size.y)
            values["size_z"] = Double(size.z)
            if let v = header.volume {
                text += " · " + GermanFormat.mm3(v)
                values["volume"] = v
            }
            if let a = header.area { values["area"] = a }
            if let m = header.mass {
                text += " · " + GermanFormat.mass(m)
                values["mass"] = m
            }
            values["faces"] = Double(faceCount)
            values["edges"] = Double(edgeCount)
            values["triangles"] = Double(triangleCount)
        }
        return SelectionItem(ref: ref.string, run: run, summary: text, values: values)
    }
}
