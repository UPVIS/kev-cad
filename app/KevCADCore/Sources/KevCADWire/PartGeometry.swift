import Foundation
import simd

/// Anzahlen aus dem Kopf von PART_UPSERT (bestimmen die Längen der Arrays in der Nutzlast).
public struct PartCounts: Codable, Equatable, Sendable {
    public var vert: Int
    public var tri: Int
    public var face: Int
    public var edge: Int
    public var epts: Int
    public var vtx: Int

    public init(vert: Int = 0, tri: Int = 0, face: Int = 0, edge: Int = 0, epts: Int = 0, vtx: Int = 0) {
        self.vert = vert
        self.tri = tri
        self.face = face
        self.edge = edge
        self.epts = epts
        self.vtx = vtx
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        vert = try c.decodeIfPresent(Int.self, forKey: .vert) ?? 0
        tri = try c.decodeIfPresent(Int.self, forKey: .tri) ?? 0
        face = try c.decodeIfPresent(Int.self, forKey: .face) ?? 0
        edge = try c.decodeIfPresent(Int.self, forKey: .edge) ?? 0
        epts = try c.decodeIfPresent(Int.self, forKey: .epts) ?? 0
        vtx = try c.decodeIfPresent(Int.self, forKey: .vtx) ?? 0
    }

    /// Erwartete Größe der Nutzlast in Byte.
    public var payloadBytes: Int {
        4 * (vert * 3 + vert * 3 + tri * 3 + tri + epts * 3 + (edge + 1) + vtx * 3)
    }
}

public enum PartGeometryError: Error, Equatable, CustomStringConvertible {
    case payloadSize(expected: Int, actual: Int)
    case invalidIndex(String)

    public var description: String {
        switch self {
        case .payloadSize(let e, let a): return "Nutzlast hat \(a) Byte, erwartet \(e)"
        case .invalidIndex(let s): return "Ungültige Geometrie: \(s)"
        }
    }
}

/// Geometrie eines Teils, wie sie in der Nutzlast von PART_UPSERT reist (Reihenfolge siehe PROTOCOL.md).
/// Alle Arrays flach: Punkte als `[x, y, z, x, y, z, …]`.
public struct PartGeometry: Sendable, Equatable {
    public var positions: [Float]
    public var normals: [Float]
    public var triangles: [UInt32]
    public var triFace: [Int32]
    public var edgePoints: [Float]
    public var edgeOffsets: [UInt32]
    public var vertices: [Float]

    public init(
        positions: [Float] = [], normals: [Float] = [], triangles: [UInt32] = [], triFace: [Int32] = [],
        edgePoints: [Float] = [], edgeOffsets: [UInt32] = [0], vertices: [Float] = []
    ) {
        self.positions = positions
        self.normals = normals
        self.triangles = triangles
        self.triFace = triFace
        self.edgePoints = edgePoints
        self.edgeOffsets = edgeOffsets
        self.vertices = vertices
    }

    public var vertexCount: Int { positions.count / 3 }
    public var triangleCount: Int { triangles.count / 3 }
    public var edgeCount: Int { max(edgeOffsets.count - 1, 0) }
    public var brepVertexCount: Int { vertices.count / 3 }

    public var counts: PartCounts {
        PartCounts(
            vert: vertexCount, tri: triangleCount, face: Int((triFace.max() ?? -1) + 1), edge: edgeCount,
            epts: edgePoints.count / 3, vtx: brepVertexCount)
    }

    public func position(_ i: Int) -> SIMD3<Float> {
        SIMD3(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
    }

    public func edgePoint(_ i: Int) -> SIMD3<Float> {
        SIMD3(edgePoints[i * 3], edgePoints[i * 3 + 1], edgePoints[i * 3 + 2])
    }

    public func brepVertex(_ i: Int) -> SIMD3<Float> {
        SIMD3(vertices[i * 3], vertices[i * 3 + 1], vertices[i * 3 + 2])
    }

    /// Punktfolge der Kante `k` (ein Polygonzug).
    public func edgePolyline(_ k: Int) -> [SIMD3<Float>] {
        guard k >= 0, k < edgeCount else { return [] }
        let a = Int(edgeOffsets[k]), b = Int(edgeOffsets[k + 1])
        guard a < b else { return [] }
        return (a..<b).map(edgePoint)
    }

    /// Hüllquader der Dreieckspunkte (sonst der Kanten- und B-Rep-Punkte).
    public var bounds: (min: SIMD3<Float>, max: SIMD3<Float>)? {
        func scan(_ a: [Float]) -> (SIMD3<Float>, SIMD3<Float>)? {
            guard a.count >= 3 else { return nil }
            var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
            var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
            var i = 0
            while i + 2 < a.count {
                let p = SIMD3(a[i], a[i + 1], a[i + 2])
                lo = simd_min(lo, p)
                hi = simd_max(hi, p)
                i += 3
            }
            return (lo, hi)
        }
        if let b = scan(positions) { return b }
        if let b = scan(edgePoints) { return b }
        return scan(vertices)
    }

    /// Liest die Nutzlast. Jedes Array wird mit einer einzigen Speicherkopie übernommen (kein Umweg über einzelne Werte).
    public static func decode(payload: Data, counts: PartCounts, validate: Bool = true) throws -> PartGeometry {
        let expected = counts.payloadBytes
        guard payload.count == expected else {
            throw PartGeometryError.payloadSize(expected: expected, actual: payload.count)
        }
        var g = PartGeometry()
        payload.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var offset = 0
            func take<T>(_ count: Int, _: T.Type) -> [T] {
                let bytes = count * MemoryLayout<T>.stride
                let out = [T](unsafeUninitializedCapacity: count) { buf, n in
                    if count > 0 {
                        UnsafeMutableRawBufferPointer(buf).copyMemory(
                            from: UnsafeRawBufferPointer(rebasing: raw[offset..<(offset + bytes)]))
                    }
                    n = count
                }
                offset += bytes
                return out
            }
            g.positions = take(counts.vert * 3, Float.self)
            g.normals = take(counts.vert * 3, Float.self)
            g.triangles = take(counts.tri * 3, UInt32.self)
            g.triFace = take(counts.tri, Int32.self)
            g.edgePoints = take(counts.epts * 3, Float.self)
            g.edgeOffsets = take(counts.edge + 1, UInt32.self)
            g.vertices = take(counts.vtx * 3, Float.self)
        }
        #if _endian(big)
            g.byteSwapAll()
        #endif
        if validate { try g.validate(faceCount: counts.face) }
        return g
    }

    /// Prüft Indizes, damit kaputte Daten nicht im Renderer landen.
    public func validate(faceCount: Int? = nil) throws {
        let nv = UInt32(vertexCount)
        for i in triangles where i >= nv {
            throw PartGeometryError.invalidIndex("Dreiecksindex \(i) bei \(nv) Punkten")
        }
        if let fc = faceCount, fc > 0 {
            for f in triFace where f >= fc {
                throw PartGeometryError.invalidIndex("Flächenindex \(f) bei \(fc) Flächen")
            }
        }
        var last: UInt32 = 0
        let np = UInt32(edgePoints.count / 3)
        for o in edgeOffsets {
            if o < last || o > np {
                throw PartGeometryError.invalidIndex("Kantenversatz \(o) (Punkte \(np))")
            }
            last = o
        }
    }

    /// Nutzlast in Protokollform (für Tests und den Demomodus).
    public func encodedPayload() -> Data {
        var d = Data(capacity: counts.payloadBytes)
        func put<T>(_ a: [T]) { a.withUnsafeBytes { d.append(contentsOf: $0) } }
        put(positions)
        put(normals)
        put(triangles)
        put(triFace)
        put(edgePoints)
        put(edgeOffsets.isEmpty ? [0] : edgeOffsets)
        put(vertices)
        return d
    }

    #if _endian(big)
        mutating func byteSwapAll() {
            positions = positions.map { Float(bitPattern: $0.bitPattern.byteSwapped) }
            normals = normals.map { Float(bitPattern: $0.bitPattern.byteSwapped) }
            triangles = triangles.map { $0.byteSwapped }
            triFace = triFace.map { $0.byteSwapped }
            edgePoints = edgePoints.map { Float(bitPattern: $0.bitPattern.byteSwapped) }
            edgeOffsets = edgeOffsets.map { $0.byteSwapped }
            vertices = vertices.map { Float(bitPattern: $0.bitPattern.byteSwapped) }
        }
    #endif
}
