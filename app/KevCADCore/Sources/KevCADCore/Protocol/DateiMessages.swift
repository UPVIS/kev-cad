import Foundation

// I-8 Datei ans Gerät (PROTOCOL.md, Abschnitt „I-8 Datei ans Gerät“): Das iPad holt eine Datei, die der Kernel am Mac
// geschrieben hat, stückweise zum Teilen. Testdateien `datei_*.frame` aus kernel/tools/make_datei_fixtures.py.

/// Fähigkeit des Kernels (HELLO.faehigkeiten) und Stückgrößen wie in `protocol.py`.
public enum DateiAnsGeraet {
    public static let faehigkeit = "datei-1"
    public static let stueckVorgabe = 4 * 1024 * 1024
    public static let stueckMax = 8 * 1024 * 1024
}

/// DATEI_REQ: ein Stück einer Datei ab `ab`, höchstens `max` Byte.
public struct DateiRequestMessage: OutgoingRequest {
    public static let type = "DATEI_REQ"
    public var seq = 0
    public var id: String
    public var pfad: String
    public var ab: Int
    public var max: Int

    public init(id: String, pfad: String, ab: Int = 0, max: Int = DateiAnsGeraet.stueckVorgabe) {
        self.id = id
        self.pfad = pfad
        self.ab = ab
        self.max = max
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, pfad, ab, max }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(pfad, forKey: .pfad)
        try c.encode(ab, forKey: .ab)
        try c.encode(max, forKey: .max)
    }
}

/// DATEI: ein Stück der Datei; die Bytes stehen in `daten` (Nutzlast des Rahmens).
public struct DateiStueckMessage: Sendable, Equatable {
    public var replyTo: String?
    /// Pfad am Mac (aufgelöst) und Dateiname
    public var pfad: String
    public var name: String
    /// Größe der ganzen Datei, Anfang und Länge dieses Stücks in Byte
    public var groesse: Int
    public var ab: Int
    public var laenge: Int
    /// Änderungszeit am Mac (Unix-Zeit), damit ein schon geholtes Stück wiederverwendet werden kann
    public var geaendert: Double
    public var daten: Data

    struct Kopf: Decodable {
        var replyTo: String?
        var pfad: String
        var name: String
        var groesse: Int
        var ab: Int
        var laenge: Int
        var geaendert: Double?

        enum CodingKeys: String, CodingKey {
            case replyTo = "reply_to", pfad, name, groesse, ab, laenge, geaendert
        }
    }

    public enum DecodeError: Error, CustomStringConvertible {
        case nutzlast(String)
        public var description: String {
            switch self {
            case .nutzlast(let s): return "DATEI: \(s)"
            }
        }
    }

    static func decode(_ header: Data, payload: Data) throws -> DateiStueckMessage {
        let k = try JSONDecoder().decode(Kopf.self, from: header)
        guard k.laenge == payload.count else {
            throw DecodeError.nutzlast("laenge \(k.laenge) passt nicht zur Nutzlast (\(payload.count) Byte)")
        }
        return DateiStueckMessage(replyTo: k.replyTo, pfad: k.pfad, name: k.name, groesse: k.groesse, ab: k.ab,
                                  laenge: k.laenge, geaendert: k.geaendert ?? 0, daten: payload)
    }
}
