import Foundation

// Bestand (BESTAND.md, Abschnitt „Protokoll“): BESTAND vom Kernel, Anfragen der App. Gelesen wird tolerant wie bei allen
// Nachrichten: fehlende oder falsch getypte Felder werden zu nil bzw. Vorgaben.

/// BESTAND (Kernel → App): nach dem Verbinden, nach jedem Projektwechsel, nach jeder Buchung und auf BESTAND_REQ.
public struct BestandMessage: Sendable {
    public var replyTo: String?
    /// Inhalt der Projektdatei; nil ohne offenes Projekt.
    public var bestand: Bestand?
    /// Die letzten Buchungen, neueste zuerst.
    public var buchungen: [BestandBuchung]
    public var stand: String?
    /// Pfad der Projektdatei (oder nil) und Fehlertext, wenn bestand.json kaputt ist (BESTAND.md Anhang S-K).
    public var datei: String?
    public var fehler: String?

    public init(
        replyTo: String? = nil, bestand: Bestand?, buchungen: [BestandBuchung] = [], stand: String? = nil,
        datei: String? = nil, fehler: String? = nil
    ) {
        self.replyTo = replyTo
        self.bestand = bestand
        self.buchungen = buchungen
        self.stand = stand
        self.datei = datei
        self.fehler = fehler
    }

    public static func decode(_ header: Data) throws -> BestandMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        let roh = json["bestand"]
        return BestandMessage(
            replyTo: json["reply_to"]?.stringValue,
            bestand: roh.flatMap { $0.objectValue == nil ? nil : Bestand(json: $0) },
            buchungen: (json["buchungen"]?.arrayValue ?? []).compactMap(BestandBuchung.init(json:)),
            stand: json["stand"]?.lenientString, datei: json["datei"]?.lenientString,
            fehler: json["fehler"]?.lenientString)
    }
}

// MARK: - Senden (App → Kernel)

public struct BestandRequestMessage: OutgoingRequest {
    public static let type = "BESTAND_REQ"
    public var seq = 0
    public var id: String

    public init(id: String) { self.id = id }

    enum CodingKeys: String, CodingKey { case type, seq, id }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
    }
}

/// BESTAND_SAVE: entweder ein ganzer Posten (`posten` null entfernt ihn) oder die Einstellungen.
public struct BestandSaveMessage: OutgoingRequest {
    public static let type = "BESTAND_SAVE"
    public var seq = 0
    public var id: String
    public var postenID: String?
    public var posten: JSONValue?
    public var einstellungen: BestandEinstellungen?
    public var grund: String

    public init(id: String, postenID: String, posten: JSONValue?, grund: String) {
        self.id = id
        self.postenID = postenID
        self.posten = posten
        self.grund = grund
    }

    public init(id: String, einstellungen: BestandEinstellungen, grund: String) {
        self.id = id
        self.einstellungen = einstellungen
        self.grund = grund
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, posten, einstellungen, grund
        case postenID = "posten_id"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        if let einstellungen {
            try c.encode(einstellungen.json, forKey: .einstellungen)
        } else {
            try c.encode(postenID, forKey: .postenID)
            try c.encode(posten ?? .null, forKey: .posten)  // null = Posten entfernen
        }
        try c.encode(grund, forKey: .grund)
    }
}

public struct GebautRequestMessage: OutgoingRequest {
    public static let type = "GEBAUT_REQ"
    public var seq = 0
    public var id: String
    public var run: Int

    public init(id: String, run: Int) {
        self.id = id
        self.run = run
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, run }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(run, forKey: .run)
    }
}

public struct BuchungRueckgaengigMessage: OutgoingRequest {
    public static let type = "BUCHUNG_RUECKGAENGIG"
    public var seq = 0
    public var id: String
    public var buchung: String

    public init(id: String, buchung: String) {
        self.id = id
        self.buchung = buchung
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, buchung }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(buchung, forKey: .buchung)
    }
}
