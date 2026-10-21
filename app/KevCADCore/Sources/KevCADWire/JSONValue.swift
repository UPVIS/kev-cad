import Foundation
import simd

/// Beliebiger JSON-Wert. Für Felder, deren Inhalt das Protokoll offen lässt (`params`, `args`, `values`, `camera`).
/// Unbekannte Felder und Typen werden so ohne Fehler mitgenommen.
public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let b = try? c.decode(Bool.self) {
            self = .bool(b)
        } else if let d = try? c.decode(Double.self) {
            self = .number(d)
        } else if let s = try? c.decode(String.self) {
            self = .string(s)
        } else if let a = try? c.decode([JSONValue].self) {
            self = .array(a)
        } else if let o = try? c.decode([String: JSONValue].self) {
            self = .object(o)
        } else {
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Unbekannter JSON-Wert")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    // MARK: Zugriff

    public subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    public var isNull: Bool { if case .null = self { return true } else { return false } }

    public var doubleValue: Double? {
        switch self {
        case .number(let d): return d
        case .bool(let b): return b ? 1 : 0
        case .string(let s): return Double(s)
        default: return nil
        }
    }

    public var intValue: Int? { doubleValue.map { Int($0) } }

    public var boolValue: Bool? {
        switch self {
        case .bool(let b): return b
        case .number(let d): return d != 0
        default: return nil
        }
    }

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    public var arrayValue: [JSONValue]? {
        if case .array(let a) = self { return a }
        return nil
    }

    public var objectValue: [String: JSONValue]? {
        if case .object(let o) = self { return o }
        return nil
    }

    /// Liste von Zahlen, z. B. `[x, y, z]`.
    public var doubles: [Double]? {
        guard let a = arrayValue else { return nil }
        let d = a.compactMap(\.doubleValue)
        return d.count == a.count ? d : nil
    }

    public var vector3: SIMD3<Float>? {
        guard let d = doubles, d.count >= 3 else { return nil }
        return SIMD3(Float(d[0]), Float(d[1]), Float(d[2]))
    }

    public var vector4: SIMD4<Float>? {
        guard let d = doubles, d.count >= 3 else { return nil }
        return SIMD4(Float(d[0]), Float(d[1]), Float(d[2]), d.count > 3 ? Float(d[3]) : 1)
    }

    public var stringList: [String]? {
        guard let a = arrayValue else { return nil }
        return a.compactMap(\.stringValue)
    }

    /// Alle Zahlen eines Objekts flach als `[Name: Wert]`; verschachtelte Listen und Objekte werden mit `_x`/`_y`/`_z`
    /// bzw. `_<Schlüssel>` angehängt (z. B. `center_x`, `bbox_min_z`). Wahrheitswerte werden 0 oder 1.
    public func flattenedNumbers(prefix: String = "") -> [String: Double] {
        var out: [String: Double] = [:]
        func walk(_ v: JSONValue, _ key: String) {
            switch v {
            case .number(let d): out[key] = d
            case .bool(let b): out[key] = b ? 1 : 0
            case .array(let a):
                let axes = ["x", "y", "z", "w"]
                for (i, e) in a.enumerated() {
                    let suffix = a.count <= 4 ? axes[i] : String(i)
                    walk(e, key.isEmpty ? suffix : "\(key)_\(suffix)")
                }
            case .object(let o):
                for (k, e) in o { walk(e, key.isEmpty ? k : "\(key)_\(k)") }
            case .string, .null: break
            }
        }
        walk(self, prefix)
        return out
    }

    /// Aus einem Swift-Wert (Zahl, Text, Liste, Wörterbuch, SIMD) einen JSON-Wert machen.
    public static func from(_ any: Any?) -> JSONValue {
        guard let any else { return .null }
        switch any {
        case let v as JSONValue: return v
        case let b as Bool: return .bool(b)
        case let i as Int: return .number(Double(i))
        case let d as Double: return .number(d)
        case let f as Float: return .number(Double(f))
        case let s as String: return .string(s)
        case let v as SIMD3<Float>: return .array([.number(Double(v.x)), .number(Double(v.y)), .number(Double(v.z))])
        case let a as [Any?]: return .array(a.map { from($0) })
        case let o as [String: Any?]: return .object(o.mapValues { from($0) })
        default: return .string(String(describing: any))
        }
    }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByFloatLiteral, ExpressibleByIntegerLiteral,
    ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral, ExpressibleByNilLiteral
{
    public init(stringLiteral value: String) { self = .string(value) }
    public init(floatLiteral value: Double) { self = .number(value) }
    public init(integerLiteral value: Int) { self = .number(Double(value)) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) {
        self = .object(Dictionary(elements, uniquingKeysWith: { _, b in b }))
    }
    public init(nilLiteral: ()) { self = .null }
}
