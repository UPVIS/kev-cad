import Foundation

// Rahmen nach PROTOCOL.md: u32 LE Kopflänge · JSON · u32 LE Nutzlastlänge · Nutzlast.

/// Ein vollständiger Rahmen: JSON-Kopf (roh) und Nutzlast.
public struct Frame: Sendable {
    public var header: Data
    public var payload: Data

    public init(header: Data, payload: Data = Data()) {
        self.header = header
        self.payload = payload
    }

    /// Bytes für die Leitung.
    public var encoded: Data { FrameCodec.encode(header: header, payload: payload) }
}

public enum FrameError: Error, Equatable, CustomStringConvertible {
    case headerTooLarge(Int)
    case payloadTooLarge(Int)

    public var description: String {
        switch self {
        case .headerTooLarge(let n): return "Rahmen-Kopf zu groß (\(n) Byte), Datenstrom ist kaputt"
        case .payloadTooLarge(let n): return "Nutzlast zu groß (\(n) Byte), Datenstrom ist kaputt"
        }
    }
}

public enum FrameCodec {
    /// Obergrenzen gegen kaputte Datenströme (ein Kopf ist selten größer als einige 100 kB).
    public static let maxHeaderBytes = 64 << 20
    public static let maxPayloadBytes = 1 << 30

    public static func encode(header: Data, payload: Data = Data()) -> Data {
        var out = Data(capacity: 8 + header.count + payload.count)
        appendU32(&out, UInt32(header.count))
        out.append(header)
        appendU32(&out, UInt32(payload.count))
        out.append(payload)
        return out
    }

    static func appendU32(_ data: inout Data, _ v: UInt32) {
        var le = v.littleEndian
        withUnsafeBytes(of: &le) { data.append(contentsOf: $0) }
    }
}

/// Setzt Rahmen aus einem Bytestrom zusammen. `feed(_:)` nimmt beliebig zerstückelte Daten an
/// (auch Byte für Byte) und liefert alle Rahmen, die damit vollständig geworden sind.
public final class FrameReader {
    private var buffer: [UInt8] = []
    private var start = 0

    public init() {}

    /// Noch nicht verarbeitete Bytes.
    public var pendingBytes: Int { buffer.count - start }

    public func feed(_ data: Data) throws -> [Frame] {
        if !data.isEmpty { buffer.append(contentsOf: data) }
        return try drain()
    }

    public func feed(_ bytes: UnsafeRawBufferPointer) throws -> [Frame] {
        if !bytes.isEmpty { buffer.append(contentsOf: bytes) }
        return try drain()
    }

    public func reset() {
        buffer.removeAll(keepingCapacity: false)
        start = 0
    }

    private func readU32(at offset: Int) -> Int {
        Int(buffer[offset]) | Int(buffer[offset + 1]) << 8 | Int(buffer[offset + 2]) << 16
            | Int(buffer[offset + 3]) << 24
    }

    private func drain() throws -> [Frame] {
        var frames: [Frame] = []
        while true {
            let available = buffer.count - start
            if available < 4 { break }
            let hlen = readU32(at: start)
            if hlen > FrameCodec.maxHeaderBytes { throw FrameError.headerTooLarge(hlen) }
            if available < 8 + hlen { break }
            let plen = readU32(at: start + 4 + hlen)
            if plen > FrameCodec.maxPayloadBytes { throw FrameError.payloadTooLarge(plen) }
            let end = 8 + hlen + plen
            if available < end { break }
            let header = Data(buffer[(start + 4)..<(start + 4 + hlen)])
            let payload = plen > 0 ? Data(buffer[(start + 8 + hlen)..<(start + end)]) : Data()
            frames.append(Frame(header: header, payload: payload))
            start += end
        }
        // Verbrauchte Bytes gelegentlich abschneiden statt bei jedem Rahmen (sonst quadratischer Aufwand)
        if start > 0 && (start == buffer.count || start > 1 << 20) {
            buffer.removeFirst(start)
            start = 0
        }
        return frames
    }
}
