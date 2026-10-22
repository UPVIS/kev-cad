import Foundation

// Protokoll der Druckvorschau (DRUCKVORSCHAU.md, Abschnitt „Protokoll“, additiv): PRINT_PREVIEW und PRINT_EXPORT_RES
// vom Kernel, PRINT_PREVIEW_REQ, PRINT_SETTINGS und PRINT_EXPORT_REQ von der App.

/// Nachrichten Kernel → App.
public enum DruckNachricht: Sendable {
    /// PRINT_PREVIEW: nach jedem Lauf mit Druckteilen, nach jedem Slicer-Ergebnis, nach PRINT_SETTINGS und auf
    /// PRINT_PREVIEW_REQ (dann mit `reply_to`).
    case vorschau(Druckvorschau, replyTo: String?)
    /// PRINT_EXPORT_RES: Ergebnis von PRINT_EXPORT_REQ (nach dem ACK).
    case exportErgebnis(DruckExportErgebnis)

    public static let types: Set<String> = ["PRINT_PREVIEW", "PRINT_EXPORT_RES"]

    public var typeName: String {
        switch self {
        case .vorschau: return "PRINT_PREVIEW"
        case .exportErgebnis: return "PRINT_EXPORT_RES"
        }
    }

    public var replyTo: String? {
        switch self {
        case .vorschau(_, let r): return r
        case .exportErgebnis(let e): return e.replyTo
        }
    }

    public static func decode(type: String, header: Data) throws -> DruckNachricht {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        switch type {
        case "PRINT_EXPORT_RES": return .exportErgebnis(DruckExportErgebnis(json: j))
        default: return .vorschau(Druckvorschau(json: j), replyTo: j["reply_to"]?.lenientString)
        }
    }
}

/// Ergebnis des 3MF-Exports.
public struct DruckExportErgebnis: Equatable, Sendable {
    public var replyTo: String?
    public var ok: Bool
    public var pfad: URL?
    public var platten: [Int]
    public var fehler: String?
    /// Additiv: Hinweise, Dauer und ob die Datei zur Kontrolle in Bambu Studio geladen wurde.
    public var hinweise: [String] = []
    public var ms: Double?
    public var geprueft: Bool?

    public init(replyTo: String? = nil, ok: Bool, pfad: URL? = nil, platten: [Int] = [], fehler: String? = nil) {
        self.replyTo = replyTo
        self.ok = ok
        self.pfad = pfad
        self.platten = platten
        self.fehler = fehler
    }

    public init(json j: JSONValue) {
        var platten = (j["platten"]?.arrayValue ?? []).compactMap(\.intValue)
        if platten.isEmpty, let n = j["platten"]?.intValue, n > 0 { platten = Array(1...n) }
        self.init(
            replyTo: j["reply_to"]?.lenientString, ok: j["ok"]?.boolValue ?? (j["fehler"]?.lenientString == nil),
            pfad: j["pfad"]?.lenientString.map { URL(fileURLWithPath: $0) }, platten: platten,
            fehler: j["fehler"]?.lenientString)
        hinweise = (j["hinweise"]?.arrayValue ?? []).compactMap { $0.lenientString ?? $0["text"]?.lenientString }
        ms = j["ms"]?.doubleValue
        geprueft = j["geprueft"]?.boolValue
    }
}

// MARK: - Senden (App → Kernel)

/// Wofür eine Einstellung gilt: eine Gruppe gleicher Teile oder ein einzelnes Teil.
public enum DruckZiel: Equatable, Hashable, Sendable {
    case gruppe(String)
    case teil(String)

    public var schluessel: String {
        switch self {
        case .gruppe(let g): return "gruppe:" + g
        case .teil(let t): return "teil:" + t
        }
    }
}

public struct DruckvorschauAnfrage: OutgoingRequest {
    public static let type = "PRINT_PREVIEW_REQ"
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

/// PRINT_SETTINGS: Teilmenge der Einstellungen und bzw. oder der Zweck. Ein Wert `null` nimmt Kevins Vorgabe zurück
/// (der Kernel empfiehlt dann wieder selbst); fehlende Schlüssel bleiben, wie sie sind.
public struct DruckEinstellenNachricht: OutgoingRequest {
    public static let type = "PRINT_SETTINGS"
    public var seq = 0
    public var id: String
    public var ziel: DruckZiel
    /// nil: Einstellungen unverändert; `.null` je Schlüssel: zurücksetzen.
    public var einstellungen: [String: JSONValue]?
    /// nil: Zweck unverändert; `.null`: zurücksetzen; sonst `.string(zweck)`.
    public var zweck: JSONValue?
    /// Alle Vorgaben des Teils bzw. der Gruppe zurücknehmen.
    public var zuruecksetzen: Bool
    /// „kevin“ (Vorgabe aus der App) oder „agent“; nil lässt das Feld weg (der Kernel nimmt dann Kevin an).
    public var von: String?

    public init(id: String, ziel: DruckZiel, einstellungen: [String: JSONValue]? = nil, zweck: JSONValue? = nil,
                zuruecksetzen: Bool = false, von: String? = nil)
    {
        self.id = id
        self.ziel = ziel
        self.einstellungen = einstellungen
        self.zweck = zweck
        self.zuruecksetzen = zuruecksetzen
        self.von = von
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, gruppe, teil, einstellungen, zweck, von, zuruecksetzen }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        switch ziel {
        case .gruppe(let g): try c.encode(g, forKey: .gruppe)
        case .teil(let t): try c.encode(t, forKey: .teil)
        }
        if let einstellungen { try c.encode(einstellungen, forKey: .einstellungen) }
        if let zweck { try c.encode(zweck, forKey: .zweck) }
        if let von { try c.encode(von, forKey: .von) }
        if zuruecksetzen { try c.encode(true, forKey: .zuruecksetzen) }
    }
}

/// PRINT_EXPORT_REQ: die angeordneten Platten als 3MF für Bambu Studio (leere Liste = alle; `ziel` nil =
/// `<projekt>/output/<projekt>-druck.3mf`).
public struct DruckExportNachricht: OutgoingRequest {
    public static let type = "PRINT_EXPORT_REQ"
    public var seq = 0
    public var id: String
    public var platten: [Int]
    public var ziel: String?

    public init(id: String, platten: [Int], ziel: String?) {
        self.id = id
        self.platten = platten
        self.ziel = ziel
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, platten, ziel }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(platten, forKey: .platten)
        if let ziel { try c.encode(ziel, forKey: .ziel) } else { try c.encodeNil(forKey: .ziel) }
    }
}
