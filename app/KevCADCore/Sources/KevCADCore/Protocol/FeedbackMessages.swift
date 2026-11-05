import Foundation

// V2-6 Sprach-Feedback (PROTOCOL.md, Abschnitt „V2-6 Sprach-Feedback“): Nachrichten App → Kernel. Testdateien
// `feedback_*.frame` aus kernel/tools/make_feedback_fixtures.py.

/// Stand einer Sitzung, wie ihn der Kernel braucht (Sperre während des Sprechens, `status`).
public enum FeedbackStand: String, Sendable {
    case spricht, pause, aus
}

/// Warum eine Sitzung endet.
public enum FeedbackGrund: String, Sendable {
    case fertig, verworfen
}

/// FEEDBACK_STAND: bei jedem Wechsel, nach einem neuen HELLO noch einmal.
public struct FeedbackStandMessage: OutgoingMessage, Equatable {
    public static let type = "FEEDBACK_STAND"
    public var seq = 0
    public var sitzung: String
    public var stand: String
    public var seit: Double
    public var grund: String?

    public init(sitzung: String, stand: FeedbackStand, seit: Double, grund: FeedbackGrund? = nil) {
        self.sitzung = sitzung
        self.stand = stand.rawValue
        self.seit = seit
        self.grund = grund?.rawValue
    }

    enum CodingKeys: String, CodingKey { case type, seq, sitzung, stand, seit, grund }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(sitzung, forKey: .sitzung)
        try c.encode(stand, forKey: .stand)
        try c.encode(seit, forKey: .seit)
        try c.encode(grund, forKey: .grund)  // null, wenn nicht `aus`
    }
}

/// FEEDBACK_PAKET: Das Paket liegt fertig im Projektordner.
public struct FeedbackPaketMessage: OutgoingMessage, Equatable {
    public static let type = "FEEDBACK_PAKET"
    public var seq = 0
    public var sitzung: String
    public var name: String
    public var datei: String
    public var saetze: Int
    public var striche: Int
    public var dauerS: Double

    public init(sitzung: String, name: String, datei: String, saetze: Int, striche: Int, dauerS: Double) {
        self.sitzung = sitzung
        self.name = name
        self.datei = datei
        self.saetze = saetze
        self.striche = striche
        self.dauerS = dauerS
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, sitzung, name, datei, saetze, striche
        case dauerS = "dauer_s"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(sitzung, forKey: .sitzung)
        try c.encode(name, forKey: .name)
        try c.encode(datei, forKey: .datei)
        try c.encode(saetze, forKey: .saetze)
        try c.encode(striche, forKey: .striche)
        try c.encode(dauerS, forKey: .dauerS)
    }
}
