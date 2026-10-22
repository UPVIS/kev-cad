import Foundation

// Phase 3 (PROTOCOL.md Abschnitt „Phase 3“, KATALOG.md Abschnitt „Zukaufteil“): Zukaufteil an PART_UPSERT und in den
// Stücklistenzeilen, ZUKAUF_STATUS vom Kernel, ZUKAUF_NEU, DOWNLOAD_SEEN und ZUKAUF_CAD von der App. Gelesen wird so
// tolerant wie bei Phase 2: fehlende oder falsch getypte Felder werden zu nil bzw. Vorgaben.

// MARK: - Lesen

/// Woher die Geometrie eines verbauten Zukaufteils stammt (`PART_UPSERT.zukauf.cad`).
public enum ZukaufCADSource: Equatable, Sendable {
    /// eingebettetes Hersteller-Modell
    case hersteller
    /// Ersatzkörper aus den Shop-Maßen (halbtransparent im Viewer)
    case vereinfacht
    /// Geometrie aus einer Funktion (`cad.quelle: "skript"`)
    case skript
    case other(String)

    public init(_ text: String?) {
        switch text?.lowercased() {
        case nil, "": self = .other("")
        case "hersteller", "traceparts", "download", "bd_warehouse": self = .hersteller
        case "vereinfacht", "ersatz", "keins": self = .vereinfacht
        case "skript": self = .skript
        case let t?: self = .other(t)
        }
    }

    /// Anzeige: „Hersteller-CAD“, „vereinfacht“, „Skript“.
    public var title: String {
        switch self {
        case .hersteller: return "Hersteller-CAD"
        case .vereinfacht: return "vereinfacht"
        case .skript: return "Skript"
        case .other(let t): return t.isEmpty ? "unbekannt" : t
        }
    }
}

/// `PART_UPSERT.zukauf`: das Teil stammt aus `lager.zukauf(...).verbauen(...)`.
public struct ZukaufPartInfo: Equatable, Sendable {
    public var id: String
    public var hersteller: String?
    public var mpn: String?
    public var cad: ZukaufCADSource
    public var preis: Double?
    public var url: URL?

    public init(
        id: String, hersteller: String? = nil, mpn: String? = nil, cad: ZukaufCADSource = .hersteller,
        preis: Double? = nil, url: URL? = nil
    ) {
        self.id = id
        self.hersteller = hersteller
        self.mpn = mpn
        self.cad = cad
        self.preis = preis
        self.url = url
    }

    /// nil, wenn das Feld fehlt oder weder `id` noch `mpn` hat.
    public init?(json: JSONValue) {
        guard json.objectValue != nil else { return nil }
        let id = json["id"]?.lenientString
        let mpn = json["mpn"]?.lenientString
        guard id != nil || mpn != nil else { return nil }
        self.init(
            id: id ?? mpn ?? "", hersteller: json["hersteller"]?.lenientString, mpn: mpn,
            cad: ZukaufCADSource(json["cad"]?.lenientString ?? json["cad"]?["quelle"]?.lenientString),
            preis: json["preis"]?.doubleValue ?? json["preis"]?["je_stueck"]?.doubleValue,
            url: ZukaufLink.url(json["url"]?.lenientString))
    }

    /// Ersatzkörper statt Hersteller-Modell.
    public var isSimplified: Bool { cad == .vereinfacht }

    /// "ALUTEC 05200"
    public var title: String { [hersteller, mpn].compactMap { $0 }.joined(separator: " ") }
}

/// Zusatzfelder einer Stücklistenzeile `art: "zukaufteil"`.
public struct ZukaufBOMInfo: Equatable, Sendable {
    public var hersteller: String?
    public var mpn: String?
    public var gtin: String?
    public var url: URL?
    public var bild: URL?
    /// Datum des Preises, wie vom Kernel geliefert (meist "2026-10-21").
    public var preisStand: String?
    /// Preis wie im Shop angegeben: brutto (true), netto (false) oder unbekannt.
    public var preisBrutto: Bool?
    public var cadQuelle: String?
    public var vereinfacht: Bool

    public init(
        hersteller: String? = nil, mpn: String? = nil, gtin: String? = nil, url: URL? = nil, bild: URL? = nil,
        preisStand: String? = nil, preisBrutto: Bool? = nil, cadQuelle: String? = nil, vereinfacht: Bool = false
    ) {
        self.hersteller = hersteller
        self.mpn = mpn
        self.gtin = gtin
        self.url = url
        self.bild = bild
        self.preisStand = preisStand
        self.preisBrutto = preisBrutto
        self.cadQuelle = cadQuelle
        self.vereinfacht = vereinfacht
    }

    /// Aus einer Zeile von `BOM.lines`; nil, wenn sie kein Zukaufteil ist.
    public init?(json: JSONValue) {
        guard json.objectValue != nil else { return nil }
        let art = json["art"]?.lenientString
        let hersteller = json["hersteller"]?.lenientString
        let mpn = json["mpn"]?.lenientString
        guard art == "zukaufteil" || (art == nil && (hersteller != nil || mpn != nil)) else { return nil }
        let cad = json["cad_quelle"]?.lenientString
        self.init(
            hersteller: hersteller, mpn: mpn, gtin: json["gtin"]?.lenientString,
            url: ZukaufLink.url(json["url"]?.lenientString), bild: ZukaufLink.url(json["bild"]?.lenientString),
            preisStand: json["preis_stand"]?.lenientString, preisBrutto: json["preis_brutto"]?.boolValue,
            cadQuelle: cad,
            vereinfacht: json["vereinfacht"]?.boolValue ?? (ZukaufCADSource(cad) == .vereinfacht))
    }

    /// "ALUTEC · 05200"
    public var title: String { [hersteller, mpn].compactMap { $0 }.joined(separator: " · ") }

    /// CAD-Quelle für die Anzeige.
    public var cadTitle: String {
        if vereinfacht { return "vereinfacht (Ersatzkörper)" }
        switch cadQuelle?.lowercased() {
        // "traceparts" nur bei älteren Einträgen (TraceParts ist seit dem 22.10.2026 stillgelegt)
        case "hersteller", "download", "traceparts": return "Hersteller-CAD"
        case "bd_warehouse": return "Normteil (bd_warehouse)"
        case "skript": return "Skript"
        case nil, "": return "–"
        case let q?: return q
        }
    }
}

/// Links aus dem Protokoll: nur http(s) und Dateien, alles andere wird verworfen.
public enum ZukaufLink {
    public static func url(_ text: String?) -> URL? {
        guard let t = text?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty,
              let url = URL(string: t), let scheme = url.scheme?.lowercased(),
              ["http", "https", "file"].contains(scheme)
        else { return nil }
        return url
    }
}

/// Zustand eines Zukaufteils laut `ZUKAUF_STATUS.zustand`.
public enum ZukaufZustand: Equatable, Sendable {
    case angelegt
    case wartetAufCAD
    case importiert
    case fehler
    case other(String)

    public init(_ text: String?) {
        switch text?.lowercased() {
        case "angelegt": self = .angelegt
        case "wartet_auf_cad": self = .wartetAufCAD
        case "importiert": self = .importiert
        case "fehler": self = .fehler
        case let t?: self = .other(t)
        case nil: self = .other("")
        }
    }

    public var rawValue: String {
        switch self {
        case .angelegt: return "angelegt"
        case .wartetAufCAD: return "wartet_auf_cad"
        case .importiert: return "importiert"
        case .fehler: return "fehler"
        case .other(let t): return t
        }
    }

    /// Anzeige: „angelegt“, „wartet auf CAD“, „CAD übernommen“, „Fehler“.
    public var title: String {
        switch self {
        case .angelegt: return "angelegt"
        case .wartetAufCAD: return "wartet auf CAD"
        case .importiert: return "CAD übernommen"
        case .fehler: return "Fehler"
        case .other(let t): return t
        }
    }
}

/// Ein Link zum Öffnen im Browser (`ZUKAUF_STATUS.cad_links`).
public struct CADLink: Identifiable, Equatable, Sendable {
    public var titel: String
    public var url: URL

    public var id: String { url.absoluteString }

    public init(titel: String, url: URL) {
        self.titel = titel
        self.url = url
    }
}

/// ZUKAUF_STATUS (Kernel → App): Teil angelegt, wartet auf Download, importiert oder Fehler.
public struct ZukaufStatusMessage: Equatable, Sendable {
    /// Zukaufteil-id
    public var id: String
    public var zustand: ZukaufZustand
    public var text: String?
    public var cadLinks: [CADLink]
    /// Dateiendungen ohne Punkt, klein, z. B. ["step", "stp", "zip"].
    public var erwartet: [String]
    /// Optional laut Festlegungen in PROTOCOL.md: Anzeigename des Teils.
    public var name: String?

    public static let defaultExtensions = ["step", "stp", "zip"]

    public init(
        id: String, zustand: ZukaufZustand, text: String? = nil, cadLinks: [CADLink] = [], erwartet: [String] = [],
        name: String? = nil
    ) {
        self.id = id
        self.zustand = zustand
        self.text = text
        self.cadLinks = cadLinks
        self.erwartet = erwartet
        self.name = name
    }

    public init(json: JSONValue) {
        let links: [CADLink] = (json["cad_links"]?.arrayValue ?? []).compactMap { link in
            if let s = link.stringValue, let url = ZukaufLink.url(s) { return CADLink(titel: url.host ?? s, url: url) }
            guard let url = ZukaufLink.url(link["url"]?.lenientString) else { return nil }
            return CADLink(titel: link["titel"]?.lenientString ?? link["title"]?.lenientString ?? url.host ?? "CAD", url: url)
        }
        let ext = (json["erwartet"]?.stringList ?? []).map(Self.normalizedExtension).filter { !$0.isEmpty }
        self.init(
            id: json["id"]?.lenientString ?? json["teil"]?.lenientString ?? "",
            zustand: ZukaufZustand(json["zustand"]?.lenientString), text: json["text"]?.lenientString,
            cadLinks: links, erwartet: ext, name: json["name"]?.lenientString)
    }

    public static func decode(_ header: Data) throws -> ZukaufStatusMessage {
        ZukaufStatusMessage(json: try JSONDecoder().decode(JSONValue.self, from: header))
    }

    /// ".STEP" → "step"
    public static func normalizedExtension(_ text: String) -> String {
        var t = text.trimmingCharacters(in: .whitespaces).lowercased()
        while t.hasPrefix(".") || t.hasPrefix("*") { t.removeFirst() }
        return t
    }
}

// MARK: - Senden (App → Kernel)

/// ZUKAUF_NEU: Kevin hat im Dialog „Zukaufteil hinzufügen …“ die Felder bestätigt.
public struct ZukaufNewMessage: OutgoingRequest {
    public static let type = "ZUKAUF_NEU"
    public var seq = 0
    public var id: String
    /// Link, MPN oder GTIN, so wie Kevin sie eingefügt hat.
    public var eingabe: String
    /// Eintrag laut KATALOG.md (Abschnitt Zukaufteil).
    public var felder: JSONValue
    /// `projekt` oder `eigen`
    public var ebene: CatalogLevel

    public init(id: String, eingabe: String, felder: JSONValue, ebene: CatalogLevel) {
        self.id = id
        self.eingabe = eingabe
        self.felder = felder
        self.ebene = ebene
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, eingabe, felder, ebene }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(eingabe, forKey: .eingabe)
        try c.encode(felder, forKey: .felder)
        try c.encode(ebene.rawValue, forKey: .ebene)
    }
}

/// DOWNLOAD_SEEN: neue CAD-Datei im Downloads-Ordner, solange ein Zukaufteil auf CAD wartet. Ohne Antwort.
public struct DownloadSeenMessage: OutgoingMessage {
    public static let type = "DOWNLOAD_SEEN"
    public var seq = 0
    /// absoluter Pfad
    public var pfad: String
    /// Größe in Byte
    public var groesse: Int64
    /// Zeitpunkt der Datei (hinzugefügt bzw. geändert)
    public var zeit: Date

    public init(pfad: String, groesse: Int64, zeit: Date) {
        self.pfad = pfad
        self.groesse = groesse
        self.zeit = zeit
    }

    enum CodingKeys: String, CodingKey { case type, seq, pfad, groesse, zeit }

    /// ISO 8601 mit Zeitzone, z. B. "2026-10-21T21:14:03+02:00" (Python: datetime.fromisoformat).
    public static func isoString(_ date: Date, timeZone: TimeZone = .current) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = timeZone
        return f.string(from: date)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(pfad, forKey: .pfad)
        try c.encode(groesse, forKey: .groesse)
        try c.encode(Self.isoString(zeit), forKey: .zeit)
    }
}

/// ZUKAUF_CAD: Kevin hat bestätigt, dass diese Datei das CAD des Zukaufteils ist.
public struct ZukaufCADMessage: OutgoingRequest {
    public static let type = "ZUKAUF_CAD"
    public var seq = 0
    public var id: String
    /// Zukaufteil-id
    public var teil: String
    public var pfad: String

    public init(id: String, teil: String, pfad: String) {
        self.id = id
        self.teil = teil
        self.pfad = pfad
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, teil, pfad }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(teil, forKey: .teil)
        try c.encode(pfad, forKey: .pfad)
    }
}
