import Foundation

// Drucken (Phase 8, DRUCKVORSCHAU.md „Drucken (Phase 8)“): PRINTER_STATUS, PRINT_JOB_RES und PRINT_JOB_ASK vom Kernel,
// PRINTER_CONFIG, PRINTER_STATUS_REQ, PRINT_JOB_REQ und PRINT_CONTROL von der App. Gelesen wird tolerant wie bei allen
// Nachrichten. Seriennummer und Zugangscode kommen in keiner dieser Nachrichten vor.

/// Weg zum Drucker: A = in Bambu Studio öffnen (Kevins Entscheidung), B = direkt (gesperrt ohne Developer Mode).
public enum DruckWeg: String, Equatable, Sendable, CaseIterable, Codable {
    case a, b

    public var titel: String {
        switch self {
        case .a: return "In Bambu Studio öffnen"
        case .b: return "Direkt drucken (LAN)"
        }
    }

    public var kurz: String { self == .a ? "Weg A" : "Weg B" }
}

/// Nachrichten Kernel → App.
public enum DruckerNachricht: Sendable {
    case status(DruckerStatus, replyTo: String?)
    case auftragErgebnis(DruckAuftragErgebnis)
    case frage(DruckFrage)

    public static let types: Set<String> = ["PRINTER_STATUS", "PRINT_JOB_RES", "PRINT_JOB_ASK"]

    public var typeName: String {
        switch self {
        case .status: return "PRINTER_STATUS"
        case .auftragErgebnis: return "PRINT_JOB_RES"
        case .frage: return "PRINT_JOB_ASK"
        }
    }

    public var replyTo: String? {
        switch self {
        case .status(_, let r): return r
        case .auftragErgebnis(let e): return e.replyTo
        case .frage: return nil
        }
    }

    public static func decode(type: String, header: Data) throws -> DruckerNachricht {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        switch type {
        case "PRINT_JOB_RES": return .auftragErgebnis(DruckAuftragErgebnis(json: j))
        case "PRINT_JOB_ASK": return .frage(DruckFrage(json: j))
        default: return .status(DruckerStatus(json: j), replyTo: j["reply_to"]?.lenientString)
        }
    }
}

// MARK: - PRINTER_STATUS

public enum DruckerVerbindung: String, Equatable, Sendable {
    case aus, verbindet, verbunden, getrennt, fehler

    public var titel: String {
        switch self {
        case .aus: return "Status aus"
        case .verbindet: return "verbindet …"
        case .verbunden: return "verbunden (nur lesend)"
        case .getrennt: return "getrennt"
        case .fehler: return "Fehler"
        }
    }
}

public struct DruckerInfo: Equatable, Sendable {
    public var id: String
    public var name: String
    public var modell: String
    public var ip: String?
    public var firmware: String?
    /// "cloud", "lan" oder "unbekannt"
    public var modus: String
    public var entwicklermodus: Bool?
    public var signal: String?

    public init(id: String, name: String, modell: String = "P1P", ip: String? = nil, firmware: String? = nil,
                modus: String = "unbekannt", entwicklermodus: Bool? = nil, signal: String? = nil)
    {
        self.id = id
        self.name = name
        self.modell = modell
        self.ip = ip
        self.firmware = firmware
        self.modus = modus
        self.entwicklermodus = entwicklermodus
        self.signal = signal
    }

    init?(json: JSONValue?) {
        guard let j = json, j.objectValue != nil else { return nil }
        self.init(id: j["id"]?.lenientString ?? "", name: j["name"]?.lenientString ?? "Drucker",
                  modell: j["modell"]?.lenientString ?? "P1P", ip: j["ip"]?.lenientString,
                  firmware: j["firmware"]?.lenientString, modus: j["modus"]?.lenientString ?? "unbekannt",
                  entwicklermodus: j["entwicklermodus"]?.boolValue, signal: j["signal"]?.lenientString)
    }

    public var modusTitel: String {
        switch modus {
        case "cloud": return "Cloud-Modus"
        case "lan": return "LAN-Modus"
        default: return "Modus unbekannt"
        }
    }
}

public struct DruckWegZustand: Equatable, Sendable {
    public var moeglich: Bool
    public var grund: String?
    public var anleitung: [String]

    public init(moeglich: Bool, grund: String? = nil, anleitung: [String] = []) {
        self.moeglich = moeglich
        self.grund = grund
        self.anleitung = anleitung
    }

    init(json: JSONValue?, standard: Bool) {
        self.init(moeglich: json?["moeglich"]?.boolValue ?? standard, grund: json?["grund"]?.lenientString,
                  anleitung: json?["anleitung"]?.stringList ?? [])
    }
}

public enum DruckLaufZustand: String, Equatable, Sendable {
    case unbekannt, bereit, vorbereiten, druckt, pausiert, fertig, fehlgeschlagen

    public var titel: String {
        switch self {
        case .unbekannt: return "Zustand unbekannt"
        case .bereit: return "bereit"
        case .vorbereiten: return "bereitet vor"
        case .druckt: return "druckt"
        case .pausiert: return "pausiert"
        case .fertig: return "fertig"
        case .fehlgeschlagen: return "abgebrochen"
        }
    }

    /// Läuft ein Druck (Fortschritt und Restzeit zeigen)?
    public var aktiv: Bool { self == .vorbereiten || self == .druckt || self == .pausiert }
}

public struct DruckLauf: Equatable, Sendable {
    public var zustand: DruckLaufZustand
    public var gcodeState: String?
    public var fortschritt: Double?
    public var schicht: Int?
    public var schichten: Int?
    public var restzeitS: Double?
    public var aufgabe: String?
    public var datei: String?
    public var stufe: String?
    public var geschwindigkeit: String?

    public init(zustand: DruckLaufZustand, fortschritt: Double? = nil, schicht: Int? = nil, schichten: Int? = nil,
                restzeitS: Double? = nil, aufgabe: String? = nil)
    {
        self.zustand = zustand
        self.fortschritt = fortschritt
        self.schicht = schicht
        self.schichten = schichten
        self.restzeitS = restzeitS
        self.aufgabe = aufgabe
    }

    init?(json: JSONValue?) {
        guard let j = json, j.objectValue != nil else { return nil }
        self.init(zustand: j["zustand"]?.stringValue.flatMap { DruckLaufZustand(rawValue: $0) } ?? .unbekannt,
                  fortschritt: j["fortschritt"]?.doubleValue, schicht: j["schicht"]?.intValue,
                  schichten: j["schichten"]?.intValue, restzeitS: j["restzeit_s"]?.doubleValue,
                  aufgabe: j["aufgabe"]?.lenientString)
        gcodeState = j["gcode_state"]?.lenientString
        datei = j["datei"]?.lenientString
        stufe = j["stufe"]?.lenientString
        geschwindigkeit = j["geschwindigkeit"]?.lenientString
    }
}

public struct DruckerTemperaturen: Equatable, Sendable {
    public var duese: Double?
    public var dueseZiel: Double?
    public var bett: Double?
    public var bettZiel: Double?

    init?(json: JSONValue?) {
        guard let j = json, j.objectValue != nil else { return nil }
        duese = j["duese"]?.doubleValue
        dueseZiel = j["duese_ziel"]?.doubleValue
        bett = j["bett"]?.doubleValue
        bettZiel = j["bett_ziel"]?.doubleValue
    }

    public init(duese: Double?, dueseZiel: Double?, bett: Double?, bettZiel: Double?) {
        self.duese = duese
        self.dueseZiel = dueseZiel
        self.bett = bett
        self.bettZiel = bettZiel
    }
}

public struct DruckerFehler: Equatable, Sendable, Identifiable {
    public var code: String
    public var text: String
    /// "fehler", "warnung" oder "hinweis"
    public var schwere: String
    public var art: String?

    public var id: String { code + "|" + text }
    public var istFehler: Bool { schwere == "fehler" }

    init?(json: JSONValue) {
        guard let text = json["text"]?.lenientString else { return nil }
        code = json["code"]?.lenientString ?? "?"
        self.text = text
        schwere = json["schwere"]?.lenientString ?? "warnung"
        art = json["art"]?.lenientString
    }
}

public struct GefundenerDrucker: Equatable, Sendable, Identifiable {
    public var name: String
    public var modell: String
    public var ip: String
    public var verbindung: String?
    /// Erste 12 Hex-Zeichen von SHA-256 der Seriennummer (nie die Seriennummer selbst).
    public var kennung: String

    public var id: String { kennung + "|" + ip }

    init?(json: JSONValue) {
        guard let ip = json["ip"]?.lenientString else { return nil }
        name = json["name"]?.lenientString ?? "Bambu-Drucker"
        modell = json["modell"]?.lenientString ?? "?"
        self.ip = ip
        verbindung = json["verbindung"]?.lenientString
        kennung = json["kennung"]?.lenientString ?? ""
    }
}

public enum DruckAuftragZustand: String, Equatable, Sendable {
    case wartet, slict, bereit, oeffnet, geoeffnet, laedtHoch = "laedt_hoch", startet, gestartet, fehler, verworfen

    public var titel: String {
        switch self {
        case .wartet: return "wartet auf Bestätigung"
        case .slict: return "Bambu Studio slict"
        case .bereit: return "gesliced, bereit"
        case .oeffnet: return "Bambu Studio wird geöffnet"
        case .geoeffnet: return "in Bambu Studio geöffnet"
        case .laedtHoch: return "wird hochgeladen"
        case .startet: return "wird gestartet"
        case .gestartet: return "gestartet"
        case .fehler: return "Fehler"
        case .verworfen: return "verworfen"
        }
    }

    /// Arbeitet der Kernel gerade daran?
    public var laeuft: Bool { [.slict, .oeffnet, .laedtHoch, .startet].contains(self) }
}

public struct DruckAuftrag: Equatable, Sendable {
    public var auftrag: String
    public var zustand: DruckAuftragZustand
    public var weg: DruckWeg
    public var platten: [Int]
    public var fortschritt: Double?
    public var meldung: String?
    public var datei: String?
    /// "kevin" oder "agent"
    public var von: String

    init?(json: JSONValue?) {
        guard let j = json, let id = j["auftrag"]?.lenientString else { return nil }
        auftrag = id
        zustand = j["zustand"]?.stringValue.flatMap { DruckAuftragZustand(rawValue: $0) } ?? .fehler
        weg = j["weg"]?.stringValue.flatMap { DruckWeg(rawValue: $0) } ?? .a
        platten = (j["platten"]?.arrayValue ?? []).compactMap(\.intValue)
        fortschritt = j["fortschritt"]?.doubleValue
        meldung = j["meldung"]?.lenientString
        datei = j["datei"]?.lenientString
        von = j["von"]?.lenientString ?? "kevin"
    }
}

/// PRINTER_STATUS: alles, was die Druckerleiste zeigt.
public struct DruckerStatus: Equatable, Sendable {
    public var konfiguriert: Bool
    public var verbindung: DruckerVerbindung
    public var meldung: String?
    public var drucker: DruckerInfo?
    public var weg: DruckWeg
    public var wegA: DruckWegZustand
    public var wegB: DruckWegZustand
    /// Nur true, wenn die Sperre im Kernel Steuerbefehle erlaubt (Weg B nachgewiesen).
    public var steuern: Bool
    public var druck: DruckLauf?
    public var temperaturen: DruckerTemperaturen?
    public var fehler: [DruckerFehler]
    public var kamera: Bool
    public var gefunden: [GefundenerDrucker]
    public var auftrag: DruckAuftrag?
    public var aktualisiert: Date?

    public init(konfiguriert: Bool = false, verbindung: DruckerVerbindung = .aus, meldung: String? = nil) {
        self.konfiguriert = konfiguriert
        self.verbindung = verbindung
        self.meldung = meldung
        drucker = nil
        weg = .a
        wegA = DruckWegZustand(moeglich: true)
        wegB = DruckWegZustand(moeglich: false)
        steuern = false
        druck = nil
        temperaturen = nil
        fehler = []
        kamera = false
        gefunden = []
        auftrag = nil
        aktualisiert = nil
    }

    public init(json j: JSONValue) {
        self.init(konfiguriert: j["konfiguriert"]?.boolValue ?? false,
                  verbindung: j["verbindung"]?.stringValue.flatMap { DruckerVerbindung(rawValue: $0) } ?? .aus,
                  meldung: j["meldung"]?.lenientString)
        drucker = DruckerInfo(json: j["drucker"])
        weg = j["weg"]?.stringValue.flatMap { DruckWeg(rawValue: $0) } ?? .a
        wegA = DruckWegZustand(json: j["wege"]?["a"], standard: true)
        wegB = DruckWegZustand(json: j["wege"]?["b"], standard: false)
        steuern = j["steuern"]?.boolValue ?? false
        druck = DruckLauf(json: j["druck"])
        temperaturen = DruckerTemperaturen(json: j["temperaturen"])
        fehler = (j["fehler"]?.arrayValue ?? []).compactMap(DruckerFehler.init(json:))
        kamera = j["kamera"]?.boolValue ?? false
        gefunden = (j["gefunden"]?.arrayValue ?? []).compactMap(GefundenerDrucker.init(json:))
        auftrag = DruckAuftrag(json: j["auftrag"])
        aktualisiert = j["aktualisiert"]?.doubleValue.map { Date(timeIntervalSince1970: $0) }
    }
}

// MARK: - PRINT_JOB_RES und PRINT_JOB_ASK

public struct DruckAuftragErgebnis: Equatable, Sendable {
    public struct Platte: Equatable, Sendable {
        public var nr: Int
        public var zeitS: Double
        public var g: Double
        public var m: Double?
        public var material: String?
    }

    public var replyTo: String?
    public var ok: Bool
    public var auftrag: String?
    public var weg: DruckWeg
    /// "vorbereitet", "geoeffnet", "gestartet" oder nil (Fehler)
    public var schritt: String?
    public var datei: URL?
    public var platten: [Int]
    public var fehler: String?
    public var hinweise: [String]
    public var ms: Double?
    /// Ergebnis von Bambu Studio je Platte (additiv `ergebnis.platten`).
    public var gesliced: [Platte]
    public var ausZwischenspeicher: Bool

    public init(json j: JSONValue) {
        replyTo = j["reply_to"]?.lenientString
        ok = j["ok"]?.boolValue ?? false
        auftrag = j["auftrag"]?.lenientString
        weg = j["weg"]?.stringValue.flatMap { DruckWeg(rawValue: $0) } ?? .a
        schritt = j["schritt"]?.lenientString
        datei = j["datei"]?.lenientString.map { URL(fileURLWithPath: $0) }
        platten = (j["platten"]?.arrayValue ?? []).compactMap(\.intValue)
        fehler = j["fehler"]?.lenientString
        hinweise = (j["hinweise"]?.arrayValue ?? []).compactMap(\.lenientString)
        ms = j["ms"]?.doubleValue
        gesliced = (j["ergebnis"]?["platten"]?.arrayValue ?? []).compactMap { p in
            guard let nr = p["nr"]?.intValue else { return nil }
            return Platte(nr: nr, zeitS: p["zeit_s"]?.doubleValue ?? 0, g: p["g"]?.doubleValue ?? 0,
                          m: p["m"]?.doubleValue, material: p["material"]?.lenientString)
        }
        ausZwischenspeicher = j["ergebnis"]?["aus_zwischenspeicher"]?.boolValue ?? false
    }

    public var zeitS: Double { gesliced.reduce(0) { $0 + $1.zeitS } }
    public var gramm: Double { gesliced.reduce(0) { $0 + $1.g } }
}

/// PRINT_JOB_ASK: der Agent bittet (über MCP `drucken`), den Dialog zu öffnen. Es geschieht nichts ohne Kevins Klick.
public struct DruckFrage: Equatable, Sendable {
    public var id: String
    public var auftrag: String
    public var platten: [Int]
    public var weg: DruckWeg
    public var von: String
    public var grund: String?

    public init(id: String, auftrag: String, platten: [Int] = [], weg: DruckWeg = .a, von: String = "agent",
                grund: String? = nil)
    {
        self.id = id
        self.auftrag = auftrag
        self.platten = platten
        self.weg = weg
        self.von = von
        self.grund = grund
    }

    public init(json j: JSONValue) {
        self.init(id: j["id"]?.lenientString ?? "", auftrag: j["auftrag"]?.lenientString ?? "",
                  platten: (j["platten"]?.arrayValue ?? []).compactMap(\.intValue),
                  weg: j["weg"]?.stringValue.flatMap { DruckWeg(rawValue: $0) } ?? .a,
                  von: j["von"]?.lenientString ?? "agent", grund: j["grund"]?.lenientString)
    }
}

// MARK: - Senden (App → Kernel)

/// PRINTER_CONFIG: der aktive Drucker aus `drucker.json` (ohne Geheimnisse) oder nil.
public struct DruckerKonfigNachricht: OutgoingRequest {
    public static let type = "PRINTER_CONFIG"
    public var seq = 0
    public var id: String
    public var drucker: DruckerEintrag?

    public init(id: String, drucker: DruckerEintrag?) {
        self.id = id
        self.drucker = drucker
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, drucker }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        if let drucker { try c.encode(drucker, forKey: .drucker) } else { try c.encodeNil(forKey: .drucker) }
    }
}

public struct DruckerStatusAnfrage: OutgoingRequest {
    public static let type = "PRINTER_STATUS_REQ"
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

/// Optionen für Weg B (der P1P hat kein AMS: immer externe Spule).
public struct DruckOptionen: Equatable, Sendable, Codable {
    public var bettNivellieren = true
    public var flussrate = true
    public var zeitraffer = false
    public var spule = "extern"

    public init(bettNivellieren: Bool = true, flussrate: Bool = true, zeitraffer: Bool = false) {
        self.bettNivellieren = bettNivellieren
        self.flussrate = flussrate
        self.zeitraffer = zeitraffer
    }

    enum CodingKeys: String, CodingKey {
        case bettNivellieren = "bett_nivellieren", flussrate, zeitraffer, spule
    }
}

/// PRINT_JOB_REQ: `bestaetigt` false = nur vorbereiten (slicen), true = Kevin hat im Dialog geklickt.
public struct DruckAuftragNachricht: OutgoingRequest {
    public static let type = "PRINT_JOB_REQ"
    public var seq = 0
    public var id: String
    public var platten: [Int]
    public var weg: DruckWeg
    public var bestaetigt: Bool
    public var optionen: DruckOptionen?
    public var auftrag: String?

    public init(id: String, platten: [Int], weg: DruckWeg, bestaetigt: Bool, optionen: DruckOptionen? = nil,
                auftrag: String? = nil)
    {
        self.id = id
        self.platten = platten
        self.weg = weg
        self.bestaetigt = bestaetigt
        self.optionen = optionen
        self.auftrag = auftrag
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, platten, weg, bestaetigt, optionen, auftrag }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(platten, forKey: .platten)
        try c.encode(weg.rawValue, forKey: .weg)
        try c.encode(bestaetigt, forKey: .bestaetigt)
        if let optionen { try c.encode(optionen, forKey: .optionen) }
        if let auftrag { try c.encode(auftrag, forKey: .auftrag) }
    }
}

public enum DruckerAktion: String, Sendable, CaseIterable {
    case aktualisieren, pause, fortsetzen, abbrechen, verwerfen
}

/// PRINT_CONTROL: Pause, Fortsetzen, Abbruch nur bei `steuern` (Weg B); verwerfen nimmt einen Auftrag zurück.
public struct DruckerSteuerNachricht: OutgoingRequest {
    public static let type = "PRINT_CONTROL"
    public var seq = 0
    public var id: String
    public var aktion: DruckerAktion
    public var auftrag: String?

    public init(id: String, aktion: DruckerAktion, auftrag: String? = nil) {
        self.id = id
        self.aktion = aktion
        self.auftrag = auftrag
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, aktion, auftrag }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(aktion.rawValue, forKey: .aktion)
        if let auftrag { try c.encode(auftrag, forKey: .auftrag) }
    }
}
