import Foundation
import simd

// CHECK (Kernel → App, PROTOCOL.md Abschnitt „Prüfung“): Prüfergebnis nach jedem Lauf mit Befunden und Schnittkörpern.

public struct CheckMessage: Sendable {
    public var ergebnis: PruefErgebnis

    public init(ergebnis: PruefErgebnis) { self.ergebnis = ergebnis }

    public enum DecodeError: Error, CustomStringConvertible {
        case payload(String)
        public var description: String {
            switch self {
            case .payload(let s): return "CHECK: \(s)"
            }
        }
    }

    public static func decode(_ header: Data, payload: Data) throws -> CheckMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        let befunde = (json["befunde"]?.arrayValue ?? []).enumerated().compactMap { PruefBefund(json: $1, index: $0) }
        let geo = try geometrie(json["geometrie"]?.arrayValue ?? [], payload: payload)
        let z = json["zaehler"]
        let ergebnis = PruefErgebnis(
            run: json["run"]?.intValue ?? 0,
            zustand: PruefErgebnis.Zustand(rawValue: json["state"]?.stringValue ?? "done") ?? .done,
            dauerMs: json["duration_ms"]?.doubleValue,
            meldung: json["message"]?.stringValue,
            zusammenfassung: json["zusammenfassung"]?.stringValue ?? "",
            fehler: z?["fehler"]?.intValue ?? befunde.filter { $0.schwere == .fehler }.count,
            warnungen: z?["warnung"]?.intValue ?? befunde.filter { $0.schwere == .warnung }.count,
            hinweise: z?["hinweis"]?.intValue ?? befunde.filter { $0.schwere == .hinweis }.count,
            befunde: befunde, geometrie: geo,
            montage: json["montage"].flatMap { $0.isNull ? nil : $0 },
            stand: json["stand"].flatMap { $0.isNull ? nil : $0 },
            imHintergrund: json["im_hintergrund"]?.stringList ?? [])
        return CheckMessage(ergebnis: ergebnis)
    }

    static func geometrie(_ eintraege: [JSONValue], payload: Data) throws -> [PruefGeometrie] {
        var out: [PruefGeometrie] = []
        var offset = 0
        func floats(_ n: Int) throws -> [Float] {
            let bytes = n * 4
            guard offset + bytes <= payload.count else { throw DecodeError.payload("Nutzlast zu kurz") }
            var arr = [Float](repeating: 0, count: n)
            _ = arr.withUnsafeMutableBytes { payload.copyBytes(to: $0, from: offset..<(offset + bytes)) }
            offset += bytes
            return arr.map { Float(bitPattern: UInt32(littleEndian: $0.bitPattern)) }
        }
        func uints(_ n: Int) throws -> [UInt32] {
            let bytes = n * 4
            guard offset + bytes <= payload.count else { throw DecodeError.payload("Nutzlast zu kurz") }
            var arr = [UInt32](repeating: 0, count: n)
            _ = arr.withUnsafeMutableBytes { payload.copyBytes(to: $0, from: offset..<(offset + bytes)) }
            offset += bytes
            return arr.map { UInt32(littleEndian: $0) }
        }
        for e in eintraege {
            let nv = e["vert"]?.intValue ?? 0
            let nt = e["tri"]?.intValue ?? 0
            let pos = try floats(nv * 3)
            let nrm = try floats(nv * 3)
            let tri = try uints(nt * 3)
            if let bad = tri.first(where: { Int($0) >= nv }) {
                throw DecodeError.payload("Dreiecksindex \(bad) außerhalb von \(nv) Punkten")
            }
            out.append(PruefGeometrie(befund: e["befund"]?.stringValue, positions: pos, normals: nrm, triangles: tri))
        }
        guard offset == payload.count else {
            throw DecodeError.payload("Nutzlast hat \(payload.count) Byte, erwartet \(offset)")
        }
        return out
    }
}

extension PruefBefund {
    /// Ein Eintrag aus `CHECK.befunde`; unbekannte Felder werden ignoriert.
    public init?(json: JSONValue, index: Int) {
        guard json.objectValue != nil else { return nil }
        let ort = json["ort"]?.doubles.flatMap { $0.count == 3 ? SIMD3<Float>(Float($0[0]), Float($0[1]), Float($0[2])) : nil }
        self.init(
            id: json["id"]?.stringValue ?? "b\(index + 1)",
            art: json["art"]?.stringValue ?? "befund",
            teile: json["teile"]?.stringList ?? [],
            schwere: PruefSchwere(rawValue: json["schwere"]?.stringValue ?? "fehler") ?? .fehler,
            text: json["text"]?.stringValue ?? "",
            loesung: json["loesung"]?.stringValue ?? "",
            ort: ort,
            geometrie: json["geometrie"]?.intValue,
            werte: json["wert"]?.flattenedNumbers() ?? [:])
    }
}
