import Foundation

// Phase 3: Eingabe und Felder des Dialogs „Zukaufteil hinzufügen …“ (KATALOG.md, Abschnitt Zukaufteil). Ohne
// Oberfläche, damit testbar. Kev CAD lädt keine Shop-Seiten (PLAN-PHASE3-ZUKAUF.md, Z1): aus einem Link wird nur
// abgelesen, was in ihm selbst steht (Shop, Link); alle übrigen Felder kommen von Kevin oder aus Claudes Vorschlag.

/// Was Kevin eingefügt hat.
public enum ZukaufInput: Equatable, Sendable {
    case empty
    case link(URL)
    /// EAN/GTIN mit gültiger Prüfziffer (nur Ziffern)
    case gtin(String)
    /// Herstellernummer (alles andere)
    case mpn(String)

    public static func classify(_ text: String) -> ZukaufInput {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return .empty }
        let lower = t.lowercased()
        if lower.hasPrefix("http://") || lower.hasPrefix("https://") || lower.hasPrefix("www.") {
            let full = lower.hasPrefix("www.") ? "https://" + t : t
            if let url = URL(string: full.replacingOccurrences(of: " ", with: "%20")), url.host != nil {
                return .link(url)
            }
        }
        let digits = t.filter { !" -".contains($0) }
        if digits.allSatisfy(\.isASCII), digits.allSatisfy(\.isNumber), GTIN.isValid(digits) { return .gtin(digits) }
        return .mpn(t)
    }

    /// Anzeige der erkannten Art, z. B. "Shop-Link · obi.de".
    public var title: String {
        switch self {
        case .empty: return ""
        case .link(let url): return "Shop-Link · \(ZukaufInput.shopName(url))"
        case .gtin(let g): return "EAN \(g) · Prüfziffer stimmt"
        case .mpn: return "Herstellernummer (MPN)"
        }
    }

    public var symbol: String {
        switch self {
        case .empty: return "questionmark.circle"
        case .link: return "link"
        case .gtin: return "barcode"
        case .mpn: return "number"
        }
    }

    /// "www.obi.de" → "obi.de"
    public static func shopName(_ url: URL) -> String {
        var host = url.host ?? url.absoluteString
        if host.hasPrefix("www.") { host.removeFirst(4) }
        return host
    }
}

/// Prüfziffer von EAN-8, UPC-A (12), EAN-13 und GTIN-14.
public enum GTIN {
    public static func isValid(_ digits: String) -> Bool {
        guard [8, 12, 13, 14].contains(digits.count), digits.allSatisfy({ $0.isASCII && $0.isNumber }) else { return false }
        let values = digits.compactMap { $0.wholeNumberValue }
        let body = values.dropLast()
        var sum = 0
        for (i, v) in body.reversed().enumerated() { sum += v * (i % 2 == 0 ? 3 : 1) }
        return (10 - sum % 10) % 10 == values.last
    }
}

/// Form des Ersatzkörpers.
public enum ZukaufForm: String, CaseIterable, Identifiable, Sendable {
    case quader, zylinder

    public var id: String { rawValue }
    public var title: String { self == .quader ? "Quader" : "Zylinder" }
    /// Maßfelder in dieser Reihenfolge.
    public var keys: [String] { self == .quader ? ["l", "b", "h"] : ["d", "l"] }

    public static func label(_ key: String) -> String {
        ["l": "Länge", "b": "Breite", "h": "Höhe", "d": "Durchmesser"][key] ?? key
    }
}

/// Eingaben des Dialogs als Text (so, wie getippt). Aus einem vorhandenen Eintrag erzeugt, bleiben unbekannte Felder
/// (`cad`, `einbaupunkt`, `bezugspunkte`, `tags` …) in `extra` erhalten und gehen beim Speichern mit.
public struct ZukaufDraft: Equatable, Sendable {
    public var eingabe = ""
    public var id = ""
    public var name = ""
    public var hersteller = ""
    public var mpn = ""
    public var shopNr = ""
    public var gtin = ""
    public var url = ""
    public var bild = ""
    public var preis = ""
    public var waehrung = "EUR"
    public var brutto = true
    public var preisStand = ZukaufDraft.today()
    public var preisQuelle = ""
    public var form: ZukaufForm = .quader
    public var masse: [String: String] = [:]
    public var gewicht = ""
    public var material = ""
    public var hinweis = ""
    public var extra: [String: JSONValue] = [:]
    /// Maße und Ersatzkörper des Eintrags, wie sie kamen (Vorschlag prüfen, bearbeiten). Solange Form und Maße im Dialog
    /// unverändert bleiben, gehen sie unverändert zurück: Der Dialog kennt nur Quader (l, b, h) und Zylinder (d, l),
    /// ein Vorschlag darf aber auch z. B. `{"d": 19.05, "h": 15.875}` haben.
    public var sourceSize: SourceSize?

    public struct SourceSize: Equatable, Sendable {
        public var masse: JSONValue
        public var ersatz: JSONValue?
        public var form: ZukaufForm
        public var felder: [String: String]
    }

    static let knownKeys: Set<String> = [
        "id", "art", "name", "hersteller", "mpn", "shop_nr", "gtin", "url", "bild", "preis", "masse", "gewicht",
        "material", "ersatz", "hinweis", "status", "ebene", "vorgeschlagen_am", "vorgeschlagen_von",
    ]

    public init() {}

    /// Aus der Eingabe vorbelegen: Link, EAN oder Herstellernummer an die passende Stelle.
    public init(input text: String) {
        self.init()
        eingabe = text.trimmingCharacters(in: .whitespacesAndNewlines)
        apply(ZukaufInput.classify(text))
    }

    public mutating func apply(_ input: ZukaufInput) {
        switch input {
        case .empty: break
        case .link(let u):
            url = u.absoluteString
            if preisQuelle.isEmpty { preisQuelle = u.absoluteString }
        case .gtin(let g): gtin = g
        case .mpn(let m): mpn = m
        }
    }

    /// Aus einem Katalogeintrag (Vorschlag von Claude bestätigen, bearbeiten, kopieren).
    public init(entry: JSONValue) {
        self.init()
        id = entry["id"]?.lenientString ?? ""
        name = entry["name"]?.lenientString ?? ""
        hersteller = entry["hersteller"]?.lenientString ?? ""
        mpn = entry["mpn"]?.lenientString ?? ""
        shopNr = entry["shop_nr"]?.lenientString ?? ""
        gtin = entry["gtin"]?.lenientString ?? ""
        url = entry["url"]?.lenientString ?? ""
        bild = entry["bild"]?.lenientString ?? ""
        if let p = entry["preis"] {
            preis = (p["je_stueck"]?.doubleValue ?? p.doubleValue).map(KevFormat.input) ?? ""
            waehrung = p["waehrung"]?.lenientString ?? "EUR"
            brutto = p["brutto"]?.boolValue ?? true
            preisStand = p["stand"]?.lenientString ?? (preis.isEmpty ? preisStand : "")
            preisQuelle = p["quelle"]?.lenientString ?? ""
        }
        let m = entry["masse"]?.objectValue ?? entry["ersatz"]?["masse"]?.objectValue ?? [:]
        let formText = entry["ersatz"]?["form"]?.lenientString
        form = ZukaufForm(rawValue: formText ?? "") ?? (m["d"] != nil && m["b"] == nil ? .zylinder : .quader)
        func text(_ value: JSONValue) -> String { value.doubleValue.map(KevFormat.input) ?? value.lenientString ?? "" }
        for (key, value) in m { masse[key] = text(value) }
        // Fehlt ein Maß der Form (Kugel nur mit d, Schraube mit d und h), aus dem Ersatzkörper des Kernels ergänzen;
        // sonst ließe sich ein gültiger Vorschlag im Dialog nicht freigeben („Länge fehlt“)
        for key in form.keys where (masse[key] ?? "").isEmpty {
            if let value = entry["ersatz"]?["masse"]?[key] { masse[key] = text(value) }
        }
        if let original = entry["masse"], original.objectValue != nil {
            sourceSize = SourceSize(masse: original, ersatz: entry["ersatz"], form: form, felder: masse)
        }
        gewicht = entry["gewicht"]?.doubleValue.map(KevFormat.input) ?? ""
        material = entry["material"]?.lenientString ?? ""
        hinweis = entry["hinweis"]?.lenientString ?? ""
        for (key, value) in entry.objectValue ?? [:] where !Self.knownKeys.contains(key) { extra[key] = value }
        if let ersatz = entry["ersatz"]?.objectValue {
            // weitere Felder im Ersatzkörper behalten
            for (key, value) in ersatz where !["form", "masse"].contains(key) { extraErsatz[key] = value }
        }
    }

    /// Unbekannte Felder in `ersatz`.
    public var extraErsatz: [String: JSONValue] = [:]

    public static func today(_ date: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }

    /// "2026-10-21" → Datum, sonst nil.
    public static func parseDay(_ text: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        f.isLenient = false
        let t = text.trimmingCharacters(in: .whitespaces)
        guard t.count == 10, let d = f.date(from: t) else { return nil }
        return d
    }

    /// Maße als Zahlen, nur die der gewählten Form und nur gültige.
    public var masseValues: [String: Double] {
        var out: [String: Double] = [:]
        for key in form.keys {
            if let d = KevFormat.parseNumber(masse[key] ?? ""), d > 0 { out[key] = d }
        }
        return out
    }

    // MARK: Vorschläge

    public func suggestedID() -> String {
        let number = mpn.trimmingCharacters(in: .whitespaces).isEmpty ? shopNr : mpn
        let base = [hersteller, number].map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        if base.isEmpty, !gtin.isEmpty { return "ean-\(gtin)" }
        return CatalogSchema.slug(base.joined(separator: "-"))
    }

    public func suggestedName() -> String {
        let number = mpn.trimmingCharacters(in: .whitespaces).isEmpty ? shopNr : mpn
        return [hersteller, number].map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    // MARK: Prüfen

    public func validate() -> [CatalogIssue] {
        var issues: [CatalogIssue] = []
        func trimmed(_ s: String) -> String { s.trimmingCharacters(in: .whitespaces) }
        let idText = trimmed(id)
        if idText.isEmpty {
            issues.append(CatalogIssue("id", "ID fehlt"))
        } else if !CatalogSchema.isValidID(idText) {
            issues.append(CatalogIssue("id", "ID nur aus Kleinbuchstaben, Ziffern, Punkt und Bindestrich"))
        }
        if trimmed(name).isEmpty { issues.append(CatalogIssue("name", "Name fehlt")) }
        if trimmed(shopNr).isEmpty {
            if trimmed(hersteller).isEmpty { issues.append(CatalogIssue("hersteller", "Hersteller fehlt")) }
            if trimmed(mpn).isEmpty {
                issues.append(CatalogIssue("mpn", "Herstellernummer fehlt (bei reinen Shop-Artikeln die Shop-Nummer)"))
            }
        }
        let g = trimmed(gtin).filter { !" -".contains($0) }
        if !g.isEmpty {
            if !(8...14).contains(g.count) || !g.allSatisfy({ $0.isASCII && $0.isNumber }) {
                issues.append(CatalogIssue("gtin", "EAN mit 8 bis 14 Ziffern"))
            } else if [8, 12, 13, 14].contains(g.count), !GTIN.isValid(g) {
                issues.append(CatalogIssue("gtin", "Prüfziffer der EAN stimmt nicht"))
            }
        }
        for (field, text, label) in [("url", url, "Link"), ("bild", bild, "Bild")] {
            let t = trimmed(text)
            if !t.isEmpty, ZukaufLink.url(t) == nil || !(t.lowercased().hasPrefix("http")) {
                issues.append(CatalogIssue(field, "\(label) muss mit http:// oder https:// beginnen"))
            }
        }
        for key in form.keys {
            let t = trimmed(masse[key] ?? "")
            if t.isEmpty {
                issues.append(CatalogIssue("masse.\(key)", "\(ZukaufForm.label(key)) fehlt"))
            } else if let d = KevFormat.parseNumber(t) {
                if d <= 0 { issues.append(CatalogIssue("masse.\(key)", "\(ZukaufForm.label(key)) muss größer als 0 sein")) }
            } else {
                issues.append(CatalogIssue("masse.\(key)", "\(ZukaufForm.label(key)): keine Zahl"))
            }
        }
        let w = trimmed(gewicht)
        if !w.isEmpty {
            if let d = KevFormat.parseNumber(w) {
                if d <= 0 { issues.append(CatalogIssue("gewicht", "Gewicht muss größer als 0 sein")) }
            } else {
                issues.append(CatalogIssue("gewicht", "Gewicht: keine Zahl"))
            }
        }
        let p = trimmed(preis)
        if !p.isEmpty {
            if let d = KevFormat.parseNumber(p) {
                if d < 0 { issues.append(CatalogIssue("preis", "Preis darf nicht negativ sein")) }
            } else {
                issues.append(CatalogIssue("preis", "Preis: keine Zahl"))
            }
            if Self.parseDay(preisStand) == nil {
                issues.append(CatalogIssue("preis_stand", "Stand als Datum, z. B. \(Self.today())"))
            }
        }
        return issues
    }

    // MARK: Eintrag

    /// Der Eintrag laut KATALOG.md. Was Kevin im Dialog bestätigt, ist freigegeben (`status: "frei"`).
    public func entry() -> JSONValue {
        func trimmed(_ s: String) -> String { s.trimmingCharacters(in: .whitespaces) }
        var o = extra
        o["status"] = "frei"
        o["id"] = .string(trimmed(id))
        o["art"] = "zukaufteil"
        o["name"] = .string(trimmed(name))
        for (key, value) in [("hersteller", hersteller), ("mpn", mpn), ("shop_nr", shopNr), ("url", url),
                             ("bild", bild), ("material", material), ("hinweis", hinweis)] {
            let t = trimmed(value)
            if !t.isEmpty { o[key] = .string(t) }
        }
        let g = trimmed(gtin).filter { !" -".contains($0) }
        if !g.isEmpty { o["gtin"] = .string(g) }
        if let p = KevFormat.parseNumber(preis) {
            var price: [String: JSONValue] = [
                "je_stueck": .number(p), "waehrung": .string(trimmed(waehrung).isEmpty ? "EUR" : trimmed(waehrung)),
                "brutto": .bool(brutto), "stand": .string(trimmed(preisStand)),
            ]
            let quelle = trimmed(preisQuelle).isEmpty ? trimmed(url) : trimmed(preisQuelle)
            if !quelle.isEmpty { price["quelle"] = .string(quelle) }
            o["preis"] = .object(price)
        }
        if let source = sourceSize, source.form == form, source.felder == masse {
            // Maße nicht angefasst: so zurück, wie sie kamen
            o["masse"] = source.masse
            if let ersatz = source.ersatz { o["ersatz"] = ersatz }
        } else {
            let m = masseValues.mapValues { JSONValue.number($0) }
            o["masse"] = .object(m)
            var ersatz = extraErsatz
            ersatz["form"] = .string(form.rawValue)
            ersatz["masse"] = .object(m)
            o["ersatz"] = .object(ersatz)
        }
        if let w = KevFormat.parseNumber(gewicht) { o["gewicht"] = .number(w) }
        return .object(o)
    }

    public func json() -> Data { CatalogDraftEncoding.encode(entry()) }
}

/// Lesesicht auf einen Katalogeintrag `art: "zukaufteil"` (für Details, Inspektor und Stückliste).
public struct ZukaufEntryInfo: Equatable, Sendable {
    public var hersteller: String?
    public var mpn: String?
    public var shopNr: String?
    public var gtin: String?
    public var url: URL?
    public var bild: URL?
    public var preis: Double?
    public var waehrung: String
    public var brutto: Bool?
    public var preisStand: String?
    public var preisQuelle: String?
    public var masse: [String: Double]
    public var form: ZukaufForm
    public var gewicht: Double?
    public var cadQuelle: String?
    public var cadDatei: String?
    public var cadStand: String?
    public var cadLizenz: String?
    public var hinweis: String?

    public init(entry: JSONValue) {
        hersteller = entry["hersteller"]?.lenientString
        mpn = entry["mpn"]?.lenientString
        shopNr = entry["shop_nr"]?.lenientString
        gtin = entry["gtin"]?.lenientString
        url = ZukaufLink.url(entry["url"]?.lenientString)
        bild = ZukaufLink.url(entry["bild"]?.lenientString)
        let p = entry["preis"]
        preis = p?["je_stueck"]?.doubleValue ?? (p?.objectValue == nil ? p?.doubleValue : nil)
        waehrung = p?["waehrung"]?.lenientString ?? "EUR"
        brutto = p?["brutto"]?.boolValue
        preisStand = p?["stand"]?.lenientString
        preisQuelle = p?["quelle"]?.lenientString
        var m: [String: Double] = [:]
        for (k, v) in entry["masse"]?.objectValue ?? entry["ersatz"]?["masse"]?.objectValue ?? [:] {
            if let d = v.doubleValue, v.stringValue == nil { m[k] = d }
        }
        masse = m
        form = ZukaufForm(rawValue: entry["ersatz"]?["form"]?.lenientString ?? "")
            ?? (m["d"] != nil && m["b"] == nil ? .zylinder : .quader)
        gewicht = entry["gewicht"]?.doubleValue
        cadQuelle = entry["cad"]?["quelle"]?.lenientString
        cadDatei = entry["cad"]?["datei"]?.lenientString
        cadStand = entry["cad"]?["stand"]?.lenientString
        cadLizenz = entry["cad"]?["lizenz"]?.lenientString
        hinweis = entry["hinweis"]?.lenientString
    }

    /// Ohne CAD-Datei (oder `quelle: "keins"`) steht das Teil als Ersatzkörper im Modell.
    public var isSimplified: Bool {
        guard let q = cadQuelle?.lowercased(), !q.isEmpty else { return true }
        return q == "keins"
    }

    /// "ALUTEC 05200" bzw. die Shop-Nummer.
    public var number: String? { mpn ?? shopNr }

    /// "610 × 410 × 128 mm" bzw. "Ø 40 × 120 mm", bei einer Kugel (nur `d`) "Ø 70 mm" wie im Kernel
    public var masseText: String {
        if form == .zylinder, let d = masse["d"], masse["l"] == nil, masse["h"] == nil {
            return "Ø " + KevFormat.compact(d) + " mm"
        }
        let values = form.keys.compactMap { masse[$0] }
        guard values.count == form.keys.count else { return "–" }
        let text = values.map { KevFormat.compact($0) }.joined(separator: " × ") + " mm"
        return form == .zylinder ? "Ø " + text : text
    }

    /// "24,99 € brutto"
    public var preisText: String? {
        guard let preis else { return nil }
        let currency = waehrung == "EUR" ? "€" : waehrung
        let tax = brutto.map { $0 ? " brutto" : " netto" } ?? ""
        return "\(KevFormat.number(preis, digits: 2)) \(currency)\(tax)"
    }

    /// CAD-Quelle für die Anzeige.
    public var cadTitle: String {
        switch cadQuelle?.lowercased() {
        case "traceparts": return "Hersteller-CAD (TraceParts)"
        case "hersteller": return "Hersteller-CAD"
        case "download": return "Hersteller-CAD (Download)"
        case "bd_warehouse": return "Normteil (bd_warehouse)"
        case "skript": return "Skript"
        case "keins", nil, "": return "keins, Ersatzkörper aus den Maßen"
        case let q?: return q
        }
    }
}

extension CatalogItem {
    /// Zukaufteil (Phase 3).
    public var isZukauf: Bool { art == ZukaufDraft.art }

    public var zukaufInfo: ZukaufEntryInfo? { isZukauf ? ZukaufEntryInfo(entry: entry) : nil }
}

extension ZukaufDraft {
    public static let art = "zukaufteil"
}

/// Datum aus dem Katalog bzw. der Stückliste für die Anzeige: "2026-10-21" → "21.10.2026", "2026-10" → "10/2026".
public enum ZukaufDate {
    public static func display(_ text: String?) -> String? {
        guard let t = text?.trimmingCharacters(in: .whitespaces), !t.isEmpty else { return nil }
        let parts = t.prefix(10).split(separator: "-")
        if parts.count == 3, parts[0].count == 4 { return "\(parts[2]).\(parts[1]).\(parts[0])" }
        if parts.count == 2, parts[0].count == 4 { return "\(parts[1])/\(parts[0])" }
        return t
    }
}

extension Catalog {
    /// Zukaufteil, das zu einer Eingabe passt (gleicher Link, gleiche EAN oder gleiche Herstellernummer).
    public func zukauf(matching input: ZukaufInput) -> CatalogItem? {
        let candidates = items.filter(\.isZukauf)
        switch input {
        case .empty:
            return nil
        case .link(let url):
            let key = Self.linkKey(url.absoluteString)
            return candidates.first { $0.zukaufInfo?.url.map { Self.linkKey($0.absoluteString) } == key }
        case .gtin(let g):
            return candidates.first { $0.zukaufInfo?.gtin == g }
        case .mpn(let m):
            let key = m.lowercased().filter { !" -_./".contains($0) }
            return candidates.first {
                ($0.zukaufInfo?.mpn?.lowercased().filter { !" -_./".contains($0) }) == key
            }
        }
    }

    /// Link ohne Schema, `www.`, Abfrage und Schrägstrich am Ende.
    static func linkKey(_ text: String) -> String {
        var t = text.lowercased()
        for prefix in ["https://", "http://"] where t.hasPrefix(prefix) { t.removeFirst(prefix.count) }
        if t.hasPrefix("www.") { t.removeFirst(4) }
        if let q = t.firstIndex(where: { $0 == "?" || $0 == "#" }) { t = String(t[..<q]) }
        while t.hasSuffix("/") { t.removeLast() }
        return t
    }
}
