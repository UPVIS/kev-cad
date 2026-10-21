import Foundation

// Phase 2 (PROTOCOL.md Abschnitt „Phase 2“, KATALOG.md): Lagerteil an PART_UPSERT, Stückliste (BOM), Lagerkatalog
// (CATALOG) und die Anfragen der App. Gelesen wird über JSONValue und so tolerant wie bei allen Nachrichten: fehlende
// oder falsch getypte Felder werden zu nil bzw. Vorgaben, unbekannte Felder bleiben unbeachtet (im Katalog bleiben sie
// im Roh-JSON des Eintrags erhalten, damit Bearbeiten nichts verliert).

// MARK: - Lesen

extension JSONValue {
    /// Text auch aus einer Zahl ("8" statt 8), leere Texte als nil.
    public var lenientString: String? {
        switch self {
        case .string(let s): return s.isEmpty ? nil : s
        case .number(let d): return d == d.rounded() ? String(Int(d)) : String(d)
        default: return nil
        }
    }

    /// Gehrung als genau zwei Winkel: `[a, b]`, eine Zahl gilt für beide Enden, sonst `[0, 0]`.
    var gehrung: [Double] {
        switch self {
        case .number(let d):
            return [d, d]
        case .array(let a):
            let list = a.compactMap(\.doubleValue)
            switch list.count {
            case 0: return [0, 0]
            case 1: return [list[0], list[0]]
            default: return [list[0], list[1]]
            }
        default:
            return [0, 0]
        }
    }
}

extension StockInfo {
    /// Aus `PART_UPSERT.stock`; nil, wenn das Feld fehlt oder keine `id` und keinen `name` hat.
    public init?(json: JSONValue) {
        guard json.objectValue != nil else { return nil }
        let id = json["id"]?.lenientString ?? json["stock_id"]?.lenientString
        let name = json["name"]?.lenientString ?? json["benennung"]?.lenientString
        guard id != nil || name != nil else { return nil }
        self.init(
            id: id ?? "", name: name ?? id ?? "", laenge: json["laenge"]?.doubleValue,
            gehrung: json["gehrung"]?.gehrung ?? [0, 0], material: json["material"]?.lenientString,
            kg: json["kg"]?.doubleValue, preis: json["preis"]?.doubleValue)
    }
}

extension BOMLine {
    /// Eine Zeile aus `BOM.lines`; `index` (ab 0) ersetzt eine fehlende Positionsnummer.
    public init?(json: JSONValue, index: Int) {
        guard json.objectValue != nil else { return nil }
        let teile = json["teile"]?.stringList ?? []
        let stockID = json["stock_id"]?.lenientString
        let givenArt = json["art"]?.lenientString
        // 3D-Druckteile (Inventar-Regel) haben kein Lagerteil, sind aber keine Eigenteile
        let eigenteil = json["eigenteil"]?.boolValue ?? (stockID == nil && givenArt != "druckteil")
        let laenge = json["laenge"]?.doubleValue
        let benennung = json["benennung"]?.lenientString ?? json["name"]?.lenientString ?? stockID ?? teile.first ?? "Teil"
        let masseText = json["masse_text"]?.lenientString ?? laenge.map { KevFormat.mm($0, digits: 0) } ?? ""
        self.init(
            pos: json["pos"]?.intValue ?? index + 1,
            art: givenArt ?? (eigenteil ? "eigenteil" : ""),
            stockID: stockID, benennung: benennung, norm: json["norm"]?.lenientString,
            material: json["material"]?.lenientString, laenge: laenge, gehrung: json["gehrung"]?.gehrung ?? [0, 0],
            masseText: masseText, anzahl: json["anzahl"]?.intValue ?? max(1, teile.count),
            kgJe: json["kg_je"]?.doubleValue, kg: json["kg"]?.doubleValue, preisJe: json["preis_je"]?.doubleValue,
            preis: json["preis"]?.doubleValue, teile: teile, eigenteil: eigenteil)
    }
}

extension BOMLine {
    /// 3D-Druckteil (Kosten aus dem Filamentpreis).
    public var druckteil: Bool { art == "druckteil" }
}

extension CutPlan {
    public init?(json: JSONValue) {
        guard json.objectValue != nil else { return nil }
        let stangen: [[Double]] = (json["stangen"]?.arrayValue ?? []).map { bar in
            bar.arrayValue?.compactMap(\.doubleValue) ?? []
        }
        let laenge = json["stangenlaenge"]?.doubleValue ?? 6000
        let schnitt = json["saegeschnitt"]?.doubleValue ?? 3
        let stockID = json["stock_id"]?.lenientString ?? json["benennung"]?.lenientString ?? ""
        self.init(
            stockID: stockID, benennung: json["benennung"]?.lenientString ?? stockID, stangenlaenge: laenge,
            saegeschnitt: schnitt, stangen: stangen,
            verschnittProzent: json["verschnitt_prozent"]?.doubleValue
                ?? CutPlan.wastePercent(stangen: stangen, stangenlaenge: laenge))
    }

    /// Anteil der gekauften Stangenlänge, der nicht in Teilen steckt (Sägeschnitte und Reste), in Prozent.
    public static func wastePercent(stangen: [[Double]], stangenlaenge: Double) -> Double {
        let total = Double(stangen.count) * stangenlaenge
        guard total > 0 else { return 0 }
        let used = stangen.joined().reduce(0, +)
        return max(0, (total - used) / total * 100)
    }

    /// Rest einer Stange nach allen Abschnitten und Sägeschnitten (mm, nie negativ).
    public func rest(ofBar index: Int) -> Double {
        guard stangen.indices.contains(index) else { return 0 }
        let pieces = stangen[index]
        return max(0, stangenlaenge - pieces.reduce(0, +) - Double(pieces.count) * saegeschnitt)
    }
}

extension BOMTotals {
    /// Aus `BOM.totals`; fehlende Summen werden aus den Zeilen gebildet.
    public init(json: JSONValue?, lines: [BOMLine]) {
        let kg = json?["kg"]?.doubleValue ?? lines.compactMap(\.kg).reduce(0, +)
        var preis = json?["preis"]?.doubleValue
        if json?["preis"] == nil {
            let prices = lines.compactMap(\.preis)
            preis = prices.isEmpty ? nil : prices.reduce(0, +)
        }
        self.init(
            kg: kg, preis: preis, positionen: json?["positionen"]?.intValue ?? lines.count,
            teile: json?["teile"]?.intValue ?? lines.reduce(0) { $0 + $1.anzahl },
            preisHinweis: json?["preis_hinweis"]?.lenientString)
    }
}

extension BillOfMaterials {
    public init(json: JSONValue) {
        let lines = (json["lines"]?.arrayValue ?? []).enumerated().compactMap { BOMLine(json: $1, index: $0) }
        self.init(
            run: json["run"]?.intValue ?? 0, lines: lines,
            cuts: (json["cuts"]?.arrayValue ?? []).compactMap { CutPlan(json: $0) },
            totals: BOMTotals(json: json["totals"], lines: lines),
            warnings: json["warnings"]?.stringList ?? [])
    }

    /// Zeile, in der ein Teil steckt.
    public func line(containing partID: String) -> BOMLine? {
        lines.first { $0.teile.contains(partID) }
    }
}

extension CatalogLevel {
    /// Anzeige: „mitgeliefert“, „eigener Katalog“, „Projekt“.
    public var title: String {
        switch self {
        case .mitgeliefert: return "Mitgeliefert"
        case .eigen: return "Eigener Katalog"
        case .projekt: return "Projekt"
        }
    }

    /// Nur eigene und Projekt-Einträge lassen sich ändern und löschen.
    public var isEditable: Bool { self != .mitgeliefert }
}

extension Catalog {
    /// Roh-JSON eines Eintrags ohne das Transportfeld `ebene` (stabil sortiert).
    static func entryData(_ entry: JSONValue) -> Data {
        guard var object = entry.objectValue else { return Data() }
        object.removeValue(forKey: "ebene")
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return (try? enc.encode(JSONValue.object(object))) ?? Data()
    }

    public init(json: JSONValue) {
        let materials: [CatalogMaterial] = (json["materials"]?.arrayValue ?? json["materialien"]?.arrayValue ?? [])
            .compactMap { m in
                guard let id = m["id"]?.lenientString else { return nil }
                return CatalogMaterial(
                    id: id, name: m["name"]?.lenientString ?? id, gruppe: m["gruppe"]?.lenientString ?? "",
                    dichte: m["dichte"]?.doubleValue ?? 0, farbe: m["farbe"]?.lenientString ?? "#A0A4A8",
                    preisJeKg: m["preis_je_kg"]?.doubleValue,
                    ebene: m["ebene"]?.stringValue.flatMap(CatalogLevel.init(rawValue:)) ?? .mitgeliefert,
                    json: Self.entryData(m), vorgeschlagen: Self.isSuggested(m), druckbar: m["druckbar"]?.boolValue ?? false)
            }
        let items: [CatalogItem] = (json["items"]?.arrayValue ?? json["teile"]?.arrayValue ?? []).compactMap { t in
            guard let id = t["id"]?.lenientString else { return nil }
            var masse: [String: Double] = [:]
            for (key, value) in t["masse"]?.objectValue ?? [:] {
                if let d = value.doubleValue, value.stringValue == nil { masse[key] = d }
            }
            return CatalogItem(
                id: id, art: t["art"]?.lenientString ?? "", name: t["name"]?.lenientString ?? id,
                norm: t["norm"]?.lenientString, masse: masse, material: t["material"]?.lenientString ?? "",
                kgJeM: t["kg_je_m"]?.doubleValue, preisText: Self.priceText(t["preis"]),
                tags: t["tags"]?.stringList ?? [],
                ebene: t["ebene"]?.stringValue.flatMap(CatalogLevel.init(rawValue:)) ?? .mitgeliefert,
                json: Self.entryData(t), vorgeschlagen: Self.isSuggested(t))
        }
        var arten = json["arten"]?.stringList ?? []
        for item in items where !item.art.isEmpty && !arten.contains(item.art) { arten.append(item.art) }
        self.init(materials: materials, items: items, arten: arten)
    }

    /// `status: "vorgeschlagen"`: von Claude angelegt, noch nicht von Kevin freigegeben.
    static func isSuggested(_ entry: JSONValue) -> Bool {
        entry["status"]?.stringValue?.lowercased() == "vorgeschlagen"
    }

    /// Der Eintrag mit `status: "frei"` als JSON, für die Freigabe eines Vorschlags (CATALOG_SAVE).
    public static func approvedJSON(_ json: Data) -> Data {
        guard var entry = (try? JSONDecoder().decode(JSONValue.self, from: json))?.objectValue else { return json }
        entry["status"] = "frei"
        entry.removeValue(forKey: "ebene")
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return (try? enc.encode(JSONValue.object(entry))) ?? json
    }

    /// Vorschläge von Claude (Teile und Materialien).
    public var suggestionCount: Int {
        items.filter(\.vorgeschlagen).count + materials.filter(\.vorgeschlagen).count
    }

    /// Preis eines Lagerteils als Text: "4,80 €/m", "38,00 €/m²", "0,32 €/Stück".
    public static func priceText(_ preis: JSONValue?) -> String? {
        guard let preis else { return nil }
        if let d = preis.doubleValue, preis.objectValue == nil { return "\(KevFormat.number(d, digits: 2)) €" }
        if let v = preis["je_m"]?.doubleValue { return "\(KevFormat.number(v, digits: 2)) €/m" }
        if let v = preis["je_m2"]?.doubleValue { return "\(KevFormat.number(v, digits: 2)) €/m²" }
        if let v = preis["je_stueck"]?.doubleValue { return "\(KevFormat.number(v, digits: 2)) €/Stück" }
        return nil
    }

    public func material(_ id: String) -> CatalogMaterial? { materials.first { $0.id == id } }
    public func item(_ id: String) -> CatalogItem? { items.first { $0.id == id } }
}

extension CatalogItem {
    /// Der vollständige Eintrag als JSONValue (Roh-JSON aus dem Katalog).
    public var entry: JSONValue { (try? JSONDecoder().decode(JSONValue.self, from: json)) ?? .object([:]) }
}

extension CatalogMaterial {
    public var entry: JSONValue { (try? JSONDecoder().decode(JSONValue.self, from: json)) ?? .object([:]) }
}

/// BOM (Kernel → App): nach jedem RUN_END und als Antwort auf BOM_REQ.
public struct BOMMessage: Sendable {
    public var replyTo: String?
    public var bom: BillOfMaterials
    /// Bestand (BESTAND.md): Zuschnitt mit Quellen, Einkaufsliste; nil, wenn der Kernel nichts dazu schickt.
    public var bestand: BOMBestand?

    public init(replyTo: String? = nil, bom: BillOfMaterials, bestand: BOMBestand? = nil) {
        self.replyTo = replyTo
        self.bom = bom
        self.bestand = bestand
    }

    public static func decode(_ header: Data) throws -> BOMMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        return BOMMessage(
            replyTo: json["reply_to"]?.stringValue, bom: BillOfMaterials(json: json), bestand: BOMBestand(json: json))
    }
}

/// CATALOG (Kernel → App): Antwort auf CATALOG_REQ.
public struct CatalogMessage: Sendable {
    public var replyTo: String?
    public var catalog: Catalog

    public init(replyTo: String? = nil, catalog: Catalog) {
        self.replyTo = replyTo
        self.catalog = catalog
    }

    public static func decode(_ header: Data) throws -> CatalogMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        return CatalogMessage(replyTo: json["reply_to"]?.stringValue, catalog: Catalog(json: json))
    }
}

// MARK: - Senden (App → Kernel)

public struct BOMRequestMessage: OutgoingRequest {
    public static let type = "BOM_REQ"
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

public struct CatalogRequestMessage: OutgoingRequest {
    public static let type = "CATALOG_REQ"
    public var seq = 0
    public var id: String
    public var query: String?
    public var art: String?

    public init(id: String, query: String? = nil, art: String? = nil) {
        self.id = id
        self.query = query
        self.art = art
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, query, art }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(query, forKey: .query)  // null = ohne Suche
        try c.encode(art, forKey: .art)
    }
}

public struct CatalogSaveMessage: OutgoingRequest {
    public static let type = "CATALOG_SAVE"
    public var seq = 0
    public var id: String
    /// `teil` oder `material`
    public var kind: String
    public var entry: JSONValue
    public var ebene: CatalogLevel

    public init(id: String, kind: String, entry: JSONValue, ebene: CatalogLevel) {
        self.id = id
        self.kind = kind
        self.entry = entry
        self.ebene = ebene
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, kind, entry, ebene }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(kind, forKey: .kind)
        try c.encode(entry, forKey: .entry)
        try c.encode(ebene.rawValue, forKey: .ebene)
    }
}

public struct CatalogDeleteMessage: OutgoingRequest {
    public static let type = "CATALOG_DELETE"
    public var seq = 0
    public var id: String
    public var kind: String
    public var entryID: String
    public var ebene: CatalogLevel

    public init(id: String, kind: String, entryID: String, ebene: CatalogLevel) {
        self.id = id
        self.kind = kind
        self.entryID = entryID
        self.ebene = ebene
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, kind, ebene
        case entryID = "entry_id"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(kind, forKey: .kind)
        try c.encode(entryID, forKey: .entryID)
        try c.encode(ebene.rawValue, forKey: .ebene)
    }
}
