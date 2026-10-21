import Foundation
import simd

/// Was ein Pick-Punkt (Punktsprite im Pick-Durchgang) bedeutet.
public enum PointTarget: Equatable, Sendable {
    /// B-Rep-Punkt mit Index in `part.vertices()`
    case vertex(Int)
    /// Hilfspunkt für den Hüllquader eines Körpers ohne Dreiecke; zählt als Treffer auf diese Kante
    case edge(Int)
}

/// Ein Stück eines Teils, das als ein `ViewportBody` in den Viewport geht.
///
/// Auflage aus AP0: Die Pick-ID hat nur 14 Bit für die Dreiecks-, Segment- oder Punktnummer. Teile mit mehr als
/// `ChunkBuilder.limit` Dreiecken, Kantensegmenten oder Punkten werden deshalb auf mehrere Körper verteilt; die
/// Zuordnungstabellen rechnen einen Treffer auf Fläche, Kante und Punkt des Teils zurück.
public struct PartChunk: Sendable {
    public var index: Int
    /// Verschachtelt `[px, py, pz, nx, ny, nz, …]` (der normale Pfad des Viewports; Hervorhebung und Umriss lesen
    /// nur dieses Format).
    public var vertexData: [Float]
    /// Dreiecke mit Indizes in `vertexData`.
    public var indices: [UInt32]
    /// Fläche des Teils je Dreieck dieses Stücks.
    public var triFace: [Int32]
    /// Erstes Dreieck dieses Stücks in der Nummerierung des Teils.
    public var firstTriangle: Int
    /// Kantenzüge in Teilkoordinaten.
    public var edges: [[SIMD3<Float>]]
    /// Kante des Teils je Liniensegment (in der Reihenfolge der Züge).
    public var segEdge: [Int32]
    /// Pick-Punkte (B-Rep-Punkte, bei Körpern ohne Dreiecke zusätzlich Hilfspunkte für den Hüllquader).
    public var points: [SIMD3<Float>]
    public var pointTargets: [PointTarget]

    public var triangleCount: Int { indices.count / 3 }
    public var segmentCount: Int { segEdge.count }
    public var vertexCount: Int { vertexData.count / 6 }

    public func face(ofTriangle t: Int) -> Int? {
        guard t >= 0, t < triFace.count else { return nil }
        let f = Int(triFace[t])
        return f >= 0 ? f : nil
    }

    public func edge(ofSegment s: Int) -> Int? {
        guard s >= 0, s < segEdge.count else { return nil }
        let e = Int(segEdge[s])
        return e >= 0 ? e : nil
    }

    public func target(ofPoint p: Int) -> PointTarget? {
        guard p >= 0, p < pointTargets.count else { return nil }
        return pointTargets[p]
    }
}

public enum ChunkBuilder {
    /// Höchstens so viele Dreiecke, Segmente oder Punkte je Körper (14 Bit = 16.384, mit Reserve).
    public static let limit = 16_000

    /// Teilt die Geometrie eines Teils in Körper-Stücke auf.
    public static func build(_ g: PartGeometry, limit: Int = ChunkBuilder.limit) -> [PartChunk] {
        let lim = max(limit, 1)
        let triCount = g.triangleCount
        let edgeCount = g.edgeCount
        let vtxCount = g.brepVertexCount

        // Kantenzüge in Gruppen zu höchstens `lim` Segmenten; ein überlanger Zug wird in Stücke geteilt
        struct Piece {
            var edge: Int
            var from: Int  // erster Punktindex
            var to: Int  // letzter Punktindex (einschließlich)
        }
        var edgeGroups: [[Piece]] = [[]]
        var segInGroup = 0
        for e in 0..<edgeCount {
            let a = Int(g.edgeOffsets[e]), b = Int(g.edgeOffsets[e + 1])
            var p0 = a
            while b - p0 >= 2 {
                let segsLeft = b - 1 - p0
                if segInGroup >= lim {
                    edgeGroups.append([])
                    segInGroup = 0
                }
                let room = lim - segInGroup
                // Ganzen Zug in eine neue Gruppe legen, statt ihn unnötig zu teilen
                if segsLeft > room && segsLeft <= lim && segInGroup > 0 {
                    edgeGroups.append([])
                    segInGroup = 0
                    continue
                }
                let take = min(segsLeft, room)
                edgeGroups[edgeGroups.count - 1].append(Piece(edge: e, from: p0, to: p0 + take))
                segInGroup += take
                p0 += take
            }
        }
        if edgeGroups.last?.isEmpty == true && edgeGroups.count > 1 { edgeGroups.removeLast() }

        let triChunks = triCount == 0 ? 0 : (triCount + lim - 1) / lim
        let vtxChunks = vtxCount == 0 ? 0 : (vtxCount + lim - 7) / (lim - 6)
        let edgeChunks = edgeGroups.first?.isEmpty == true ? 0 : edgeGroups.count
        let chunkCount = max(1, triChunks, edgeChunks, vtxChunks)
        let vtxPer = max(1, (vtxCount + chunkCount - 1) / chunkCount)

        var result: [PartChunk] = []
        result.reserveCapacity(chunkCount)
        var remap = chunkCount > 1 ? [Int32](repeating: -1, count: g.vertexCount) : []

        for c in 0..<chunkCount {
            let t0 = min(c * lim, triCount)
            let t1 = min(t0 + lim, triCount)
            var vertexData: [Float]
            var indices: [UInt32]
            if chunkCount == 1 {
                vertexData = interleave(g.positions, g.normals)
                indices = g.triangles
            } else if t1 > t0 {
                for i in 0..<remap.count { remap[i] = -1 }
                vertexData = []
                vertexData.reserveCapacity((t1 - t0) * 9)
                indices = []
                indices.reserveCapacity((t1 - t0) * 3)
                var next: Int32 = 0
                for t in t0..<t1 {
                    for k in 0..<3 {
                        let v = Int(g.triangles[t * 3 + k])
                        if remap[v] < 0 {
                            remap[v] = next
                            next += 1
                            vertexData.append(contentsOf: g.positions[(v * 3)..<(v * 3 + 3)])
                            vertexData.append(contentsOf: g.normals[(v * 3)..<(v * 3 + 3)])
                        }
                        indices.append(UInt32(remap[v]))
                    }
                }
            } else {
                vertexData = []
                indices = []
            }
            let triFace = t1 > t0 ? Array(g.triFace[t0..<t1]) : []

            var edges: [[SIMD3<Float>]] = []
            var segEdge: [Int32] = []
            if c < edgeChunks {
                for piece in edgeGroups[c] {
                    let poly = (piece.from...piece.to).map(g.edgePoint)
                    edges.append(poly)
                    segEdge.append(contentsOf: repeatElement(Int32(piece.edge), count: poly.count - 1))
                }
            }

            var points: [SIMD3<Float>] = []
            var targets: [PointTarget] = []
            let v0 = min(c * vtxPer, vtxCount), v1 = min(v0 + vtxPer, vtxCount)
            for v in v0..<v1 {
                points.append(g.brepVertex(v))
                targets.append(.vertex(v))
            }
            // Ohne Dreiecke bestimmt der Viewport den Hüllquader aus den Pick-Punkten: Extrempunkte der Kanten dazu
            if indices.isEmpty && !edges.isEmpty {
                var extreme: [(SIMD3<Float>, Int)] = []
                for axis in 0..<3 {
                    var lo: (SIMD3<Float>, Int)? = nil
                    var hi: (SIMD3<Float>, Int)? = nil
                    var s = 0
                    for poly in edges {
                        let e = Int(segEdge[min(s, segEdge.count - 1)])
                        for p in poly {
                            if lo == nil || p[axis] < lo!.0[axis] { lo = (p, e) }
                            if hi == nil || p[axis] > hi!.0[axis] { hi = (p, e) }
                        }
                        s += poly.count - 1
                    }
                    if let lo { extreme.append(lo) }
                    if let hi { extreme.append(hi) }
                }
                for (p, e) in extreme {
                    points.append(p)
                    targets.append(.edge(e))
                }
            }

            result.append(
                PartChunk(
                    index: c, vertexData: vertexData, indices: indices, triFace: triFace, firstTriangle: t0,
                    edges: edges, segEdge: segEdge, points: points, pointTargets: targets))
        }
        return result
    }

    /// Punkte und Normalen zu `[px, py, pz, nx, ny, nz, …]`.
    public static func interleave(_ positions: [Float], _ normals: [Float]) -> [Float] {
        let n = positions.count / 3
        let hasNormals = normals.count == positions.count
        return [Float](unsafeUninitializedCapacity: n * 6) { buf, count in
            positions.withUnsafeBufferPointer { p in
                normals.withUnsafeBufferPointer { nr in
                    for i in 0..<n {
                        buf[i * 6] = p[i * 3]
                        buf[i * 6 + 1] = p[i * 3 + 1]
                        buf[i * 6 + 2] = p[i * 3 + 2]
                        buf[i * 6 + 3] = hasNormals ? nr[i * 3] : 0
                        buf[i * 6 + 4] = hasNormals ? nr[i * 3 + 1] : 0
                        buf[i * 6 + 5] = hasNormals ? nr[i * 3 + 2] : 1
                    }
                }
            }
            count = n * 6
        }
    }
}
