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

// MARK: - Gegenrichtung: Datei vom Gerät an den Mac (DATEI_HOCH, Fähigkeit datei-hoch-1)

extension DateiAnsGeraet {
    public static let faehigkeitHoch = "datei-hoch-1"
}

/// DATEI_HOCH: ein Stück einer Datei vom Gerät; die Bytes gehen als Nutzlast mit. Den Ort am Mac bestimmt der Kernel.
public struct DateiHochMessage: OutgoingRequest {
    public static let type = "DATEI_HOCH"
    public var seq = 0
    public var id: String
    public var sitzung: String
    public var name: String
    public var groesse: Int
    public var ab: Int

    public init(id: String, sitzung: String, name: String, groesse: Int, ab: Int) {
        self.id = id
        self.sitzung = sitzung
        self.name = name
        self.groesse = groesse
        self.ab = ab
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, sitzung, name, groesse, ab }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(sitzung, forKey: .sitzung)
        try c.encode(name, forKey: .name)
        try c.encode(groesse, forKey: .groesse)
        try c.encode(ab, forKey: .ab)
    }
}

/// DATEI_HOCH_STAND: wie viel angekommen ist; nach dem letzten Stück der Pfad am Mac.
public struct DateiHochStandMessage: Decodable, Sendable, Equatable {
    public var replyTo: String?
    public var sitzung: String
    public var name: String
    public var groesse: Int
    public var empfangen: Int
    public var pfad: String?

    public init(replyTo: String?, sitzung: String, name: String, groesse: Int, empfangen: Int, pfad: String?) {
        self.replyTo = replyTo
        self.sitzung = sitzung
        self.name = name
        self.groesse = groesse
        self.empfangen = empfangen
        self.pfad = pfad
    }

    enum CodingKeys: String, CodingKey {
        case replyTo = "reply_to", sitzung, name, groesse, empfangen, pfad
    }
}
