import Compression
import CryptoKit
import Foundation

/// Netzformat `kcad-mesh-1` (MIRROR.md): die Arrays aus PART_UPSERT ohne die B-Rep-Punkte, little-endian direkt
/// hintereinander (positions, normals, triangles, tri_face, edge_points, edge_offsets), als **ein** LZFSE-Strom gepackt
/// und in Blöcke zu höchstens 64 KB geteilt. Hash: SHA-256 über die ungepackten Arrays, die ersten 16 Hex-Zeichen.
public enum KcadMesh {
    public static let format = "kcad-mesh-1"
    public static let blockSize = MirrorProtocol.maxPayloadBytes

    public enum MeshError: Error, Equatable, CustomStringConvertible {
        case compressionFailed
        case decompressionFailed(expected: Int, actual: Int)
        case rawSize(expected: Int, actual: Int)
        case hashMismatch(expected: String, actual: String)
        case unsupportedFormat(String)
        case blockMismatch(String)

        public var description: String {
            switch self {
            case .compressionFailed: return "LZFSE: Packen fehlgeschlagen"
            case .decompressionFailed(let e, let a): return "LZFSE: \(a) statt \(e) Byte entpackt"
            case .rawSize(let e, let a): return "Netz hat \(a) Byte, erwartet \(e)"
            case .hashMismatch(let e, let a): return "Hash \(a) statt \(e), Netz verworfen"
            case .unsupportedFormat(let f): return "Netzformat \(f) unbekannt"
            case .blockMismatch(let s): return "Netzblöcke passen nicht zusammen: \(s)"
            }
        }
    }

    // MARK: Ungepackt

    /// Ungepackte Arrays einer Geometrie (die B-Rep-Punkte bleiben weg).
    public static func raw(_ g: PartGeometry) -> Data {
        var d = Data(capacity: MeshCounts(g.counts).rawBytes)
        func put<T>(_ a: [T]) { a.withUnsafeBytes { d.append(contentsOf: $0) } }
        put(g.positions)
        put(g.normals)
        put(g.triangles)
        put(g.triFace)
        put(g.edgePoints)
        put(g.edgeOffsets.isEmpty ? [UInt32(0)] : g.edgeOffsets)
        return d
    }

    /// Ungepackte Arrays aus der Nutzlast eines PART_UPSERT (schneidet die B-Rep-Punkte am Ende ab).
    public static func raw(partUpsertPayload payload: Data, counts: PartCounts) throws -> Data {
        guard payload.count == counts.payloadBytes else {
            throw MeshError.rawSize(expected: counts.payloadBytes, actual: payload.count)
        }
        return Data(payload.prefix(MeshCounts(counts).rawBytes))
    }

    /// Geometrie aus den ungepackten Arrays (ohne B-Rep-Punkte), mit Prüfung der Indizes.
    public static func geometry(raw: Data, counts: MeshCounts) throws -> PartGeometry {
        guard raw.count == counts.rawBytes else { throw MeshError.rawSize(expected: counts.rawBytes, actual: raw.count) }
        return try PartGeometry.decode(payload: raw, counts: counts.partCounts)
    }

    /// SHA-256 über die ungepackten Arrays, die ersten 16 Hex-Zeichen.
    public static func hash(raw: Data) -> String {
        let digest = SHA256.hash(data: raw)
        let hex = Array("0123456789abcdef")
        var out = ""
        out.reserveCapacity(16)
        for byte in digest.prefix(8) {
            out.append(hex[Int(byte >> 4)])
            out.append(hex[Int(byte & 0x0f)])
        }
        return out
    }

    // MARK: LZFSE

    /// Packt mit LZFSE (ein Strom, wie `compression_encode_buffer`).
    public static func compress(_ raw: Data) throws -> Data {
        if raw.isEmpty { return Data() }
        let capacity = raw.count + raw.count / 8 + 4096
        var out = Data(count: capacity)
        let n = out.withUnsafeMutableBytes { (dst: UnsafeMutableRawBufferPointer) -> Int in
            raw.withUnsafeBytes { (src: UnsafeRawBufferPointer) -> Int in
                compression_encode_buffer(
                    dst.bindMemory(to: UInt8.self).baseAddress!, capacity,
                    src.bindMemory(to: UInt8.self).baseAddress!, raw.count, nil, COMPRESSION_LZFSE)
            }
        }
        guard n > 0 else { throw MeshError.compressionFailed }
        out.removeSubrange(n..<out.count)
        return out
    }

    /// Entpackt einen LZFSE-Strom in einem Zug in einen Puffer der Größe `rawSize`.
    public static func decompress(_ packed: Data, rawSize: Int) throws -> Data {
        if rawSize == 0 { return Data() }
        // Ein Byte Reserve: so fällt auch ein zu langer Strom auf
        var out = Data(count: rawSize + 1)
        let n = out.withUnsafeMutableBytes { (dst: UnsafeMutableRawBufferPointer) -> Int in
            packed.withUnsafeBytes { (src: UnsafeRawBufferPointer) -> Int in
                guard let s = src.bindMemory(to: UInt8.self).baseAddress else { return 0 }
                return compression_decode_buffer(
                    dst.bindMemory(to: UInt8.self).baseAddress!, rawSize + 1, s, packed.count, nil, COMPRESSION_LZFSE)
            }
        }
        guard n == rawSize else { throw MeshError.decompressionFailed(expected: rawSize, actual: n) }
        out.removeLast()
        return out
    }
}

/// Ein gepacktes Netz, bereit für MESH-Rahmen.
public struct PackedMesh: Sendable, Equatable {
    public var hash: String
    public var counts: MeshCounts
    public var rawBytes: Int
    /// Der ganze LZFSE-Strom.
    public var packed: Data

    public init(hash: String, counts: MeshCounts, rawBytes: Int, packed: Data) {
        self.hash = hash
        self.counts = counts
        self.rawBytes = rawBytes
        self.packed = packed
    }

    /// Aus einer Geometrie: ungepackt, Hash, gepackt.
    public init(geometry: PartGeometry) throws {
        try self.init(raw: KcadMesh.raw(geometry), counts: MeshCounts(geometry.counts))
    }

    /// Aus den ungepackten Arrays.
    public init(raw: Data, counts: MeshCounts) throws {
        self.init(hash: KcadMesh.hash(raw: raw), counts: counts, rawBytes: raw.count, packed: try KcadMesh.compress(raw))
    }

    public var blockCount: Int { max(1, (packed.count + KcadMesh.blockSize - 1) / KcadMesh.blockSize) }

    /// Kopf des Blocks `i`.
    public func blockHeader(_ i: Int) -> MirrorMeshBlock {
        MirrorMeshBlock(hash: hash, block: i, blocks: blockCount, bytes: packed.count, rohBytes: rawBytes)
    }

    /// Nutzlast des Blocks `i` (höchstens 64 KB).
    public func blockPayload(_ i: Int) -> Data {
        let a = i * KcadMesh.blockSize
        let b = min(a + KcadMesh.blockSize, packed.count)
        guard a < b else { return Data() }
        return packed.subdata(in: a..<b)
    }

    /// Alle Rahmen dieses Netzes (für Tests und Werkzeuge).
    public func frames(seq: inout Int) throws -> [Frame] {
        try (0..<blockCount).map { i in
            seq += 1
            return try blockHeader(i).frame(seq: seq, payload: blockPayload(i))
        }
    }
}

/// Setzt Netze aus MESH-Blöcken zusammen: hängt die Blöcke eines Hashs nach `block` aneinander, entpackt in einem Zug
/// auf `roh_bytes`, prüft den Hash und verwirft das Netz bei Abweichung.
public struct MeshAssembler: Sendable {
    private struct Pending: Sendable {
        var header: MirrorMeshBlock
        var blocks: [Int: Data] = [:]
    }

    private var pending: [String: Pending] = [:]

    public init() {}

    /// Hashes, deren Blöcke noch nicht vollständig sind.
    public var incomplete: [String] { Array(pending.keys) }

    /// Fertiges Netz (ungepackt, Hash geprüft) oder nil, solange Blöcke fehlen. Wirft bei falschem Format, Hash oder
    /// unpassenden Blöcken (das Netz ist dann verworfen).
    public mutating func add(_ header: MirrorMeshBlock, payload: Data) throws -> (hash: String, raw: Data)? {
        guard header.format == KcadMesh.format else {
            pending[header.hash] = nil
            throw KcadMesh.MeshError.unsupportedFormat(header.format)
        }
        var p = pending[header.hash] ?? Pending(header: header)
        if p.header.blocks != header.blocks || p.header.bytes != header.bytes || p.header.rohBytes != header.rohBytes {
            // Neuer Anlauf mit anderen Eckdaten: von vorn
            p = Pending(header: header)
        }
        guard header.block >= 0, header.block < header.blocks else {
            pending[header.hash] = nil
            throw KcadMesh.MeshError.blockMismatch("Block \(header.block) von \(header.blocks)")
        }
        p.blocks[header.block] = payload
        guard p.blocks.count == header.blocks else {
            pending[header.hash] = p
            return nil
        }
        pending[header.hash] = nil
        var packed = Data(capacity: header.bytes)
        for i in 0..<header.blocks { packed.append(p.blocks[i]!) }
        guard packed.count == header.bytes else {
            throw KcadMesh.MeshError.blockMismatch("\(packed.count) statt \(header.bytes) Byte gepackt")
        }
        let raw = try KcadMesh.decompress(packed, rawSize: header.rohBytes)
        let actual = KcadMesh.hash(raw: raw)
        guard actual == header.hash else { throw KcadMesh.MeshError.hashMismatch(expected: header.hash, actual: actual) }
        return (header.hash, raw)
    }

    /// Halbfertige Netze verwerfen (z. B. nach einem Epochenwechsel oder Neuverbinden).
    public mutating func reset() { pending = [:] }
}
