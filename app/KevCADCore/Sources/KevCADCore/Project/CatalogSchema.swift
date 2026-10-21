import Foundation

/// Aufbau der Katalogeinträge nach KATALOG.md für Anzeige und Formular: Arten mit ihren Maßfeldern, deutsche
/// Bezeichnungen, Namens- und ID-Vorschläge. Ohne Oberfläche, damit testbar.
public enum CatalogSchema {
    public enum FieldKind: Equatable, Sendable {
        case number
        case text
    }

    /// Ein Feld in `masse`.
    public struct MeasureField: Identifiable, Equatable, Sendable {
        public var key: String
        public var label: String
        public var required: Bool
        public var kind: FieldKind
        /// Vorschläge für das Formular (Raster, Nut, bd_warehouse-Klassen …).
        public var suggestions: [String]
        public var hint: String?

        public var id: String { key }
        public var unit: String? { kind == .number && !["raster", "nut"].contains(key) ? "mm" : nil }

        init(
            _ key: String, _ label: String, required: Bool = true, kind: FieldKind = .number,
            suggestions: [String] = [], hint: String? = nil
        ) {
            self.key = key
            self.label = label
            self.required = required
            self.kind = kind
            self.suggestions = suggestions
            self.hint = hint
        }
    }

    /// Lieferform: Stangenware (Preis je m, Zuschnitt), Platte (Preis je m², Format), Stückware (Preis je Stück).
    public enum Supply: Equatable, Sendable {
        case bar, sheet, piece
    }

    public enum PriceUnit: String, CaseIterable, Identifiable, Sendable {
        case jeM = "je_m"
        case jeM2 = "je_m2"
        case jeStueck = "je_stueck"

        public var id: String { rawValue }

        public var title: String {
            switch self {
            case .jeM: return "€/m"
            case .jeM2: return "€/m²"
            case .jeStueck: return "€/Stück"
            }
        }
    }

    public struct Art: Identifiable, Equatable, Sendable {
        public var id: String
        /// Einzahl („Vierkantrohr“) und Mehrzahl („Vierkantrohre“) für Listen.
        public var title: String
        public var plural: String
        /// SF Symbol für Listen und Teilebaum.
        public var symbol: String
        public var fields: [MeasureField]
        public var supply: Supply
        /// Querschnitt laut KATALOG.md, für die Hilfe im Formular.
        public var profile: String

        public var priceUnit: PriceUnit {
            switch supply {
            case .bar: return .jeM
            case .sheet: return .jeM2
            case .piece: return .jeStueck
            }
        }

        public var isKnown: Bool { CatalogSchema.arten.contains { $0.id == id } }
    }

    static let screwTypes = [
        "SocketHeadCapScrew", "ButtonHeadScrew", "CounterSunkScrew", "HexHeadScrew", "PanHeadScrew", "SetScrew",
    ]
    static let nutTypes = ["HexNut", "DomedCapNut", "SquareNut", "HeatSetNut"]
    static let washerTypes = ["PlainWasher", "ChamferedWasher", "CheeseHeadWasher"]

    /// Alle Arten aus KATALOG.md in fester Reihenfolge.
    public static let arten: [Art] = [
        Art(
            id: "rohr", title: "Rohr", plural: "Rohre", symbol: "circle.circle",
            fields: [MeasureField("d", "Außendurchmesser"), MeasureField("s", "Wandstärke")], supply: .bar,
            profile: "Kreisring"),
        Art(
            id: "vierkantrohr", title: "Vierkantrohr", plural: "Vierkantrohre", symbol: "square.inset.filled",
            fields: [
                MeasureField("a", "Kantenlänge"), MeasureField("s", "Wandstärke"),
                MeasureField("r", "Außenradius", required: false, hint: "Standard 2 · s (bis s = 6), sonst 2,5 · s"),
            ], supply: .bar, profile: "Quadrat mit Eckenradius, hohl"),
        Art(
            id: "rechteckrohr", title: "Rechteckrohr", plural: "Rechteckrohre", symbol: "rectangle.inset.filled",
            fields: [
                MeasureField("b", "Breite"), MeasureField("h", "Höhe"), MeasureField("s", "Wandstärke"),
                MeasureField("r", "Außenradius", required: false, hint: "Standard 2 · s (bis s = 6), sonst 2,5 · s"),
            ], supply: .bar, profile: "Rechteck, hohl"),
        Art(
            id: "flach", title: "Flachstahl", plural: "Flachstahl", symbol: "rectangle.fill",
            fields: [MeasureField("b", "Breite"), MeasureField("s", "Dicke")], supply: .bar, profile: "Rechteck"),
        Art(
            id: "rund", title: "Rundstahl", plural: "Rundstahl", symbol: "circle.fill",
            fields: [MeasureField("d", "Durchmesser")], supply: .bar, profile: "Kreis"),
        Art(
            id: "vierkant", title: "Vierkantstahl", plural: "Vierkantstahl", symbol: "square.fill",
            fields: [MeasureField("a", "Kantenlänge")], supply: .bar, profile: "Quadrat"),
        Art(
            id: "winkel", title: "Winkel", plural: "Winkel", symbol: "angle",
            fields: [
                MeasureField("a", "Schenkel a"), MeasureField("b", "Schenkel b"), MeasureField("s", "Dicke"),
                MeasureField("r", "Innenradius", required: false),
            ], supply: .bar, profile: "L-Profil"),
        Art(
            id: "u_profil", title: "U-Profil", plural: "U-Profile", symbol: "u.square",
            fields: [
                MeasureField("h", "Höhe"), MeasureField("b", "Breite"), MeasureField("s", "Stegdicke"),
                MeasureField("t", "Flanschdicke"),
            ], supply: .bar, profile: "U-Profil, vereinfacht ohne Neigung"),
        Art(
            id: "nutprofil", title: "Nutprofil", plural: "Nutprofile", symbol: "plus.square",
            fields: [
                MeasureField("raster", "Raster", suggestions: ["20", "30", "40", "45"]),
                MeasureField("nut", "Nut", suggestions: ["5", "6", "8", "10"]),
                MeasureField("variante", "Variante", kind: .text, suggestions: ["leicht", "schwer"]),
                MeasureField("a", "Breite", required: false, hint: "nur bei Mehrfachprofilen, z. B. 40 × 80"),
                MeasureField("b", "Höhe", required: false, hint: "nur bei Mehrfachprofilen"),
            ], supply: .bar, profile: "vereinfachte Kontur mit T-Nuten und Kernbohrung"),
        Art(
            id: "holz", title: "Kantholz", plural: "Holz", symbol: "leaf",
            fields: [MeasureField("b", "Breite"), MeasureField("h", "Höhe")], supply: .bar,
            profile: "Rechteck (Kantholz, Latte, Brett)"),
        Art(
            id: "platte", title: "Platte", plural: "Platten und Bleche", symbol: "rectangle",
            fields: [MeasureField("s", "Dicke")], supply: .sheet, profile: "Zuschnitt aus der Fläche"),
        Art(
            id: "schraube", title: "Schraube", plural: "Schrauben", symbol: "screwdriver",
            fields: [
                MeasureField("typ", "Typ", kind: .text, suggestions: screwTypes, hint: "Klasse aus bd_warehouse"),
                MeasureField("norm", "Norm", kind: .text, suggestions: ["iso4762", "iso7380", "iso10642", "iso4017"]),
                MeasureField("groesse", "Größe", kind: .text, suggestions: ["M4-0.7", "M5-0.8", "M6-1", "M8-1.25", "M10-1.5"]),
            ], supply: .piece, profile: "aus bd_warehouse, Länge beim Verbauen"),
        Art(
            id: "mutter", title: "Mutter", plural: "Muttern", symbol: "hexagon",
            fields: [
                MeasureField("typ", "Typ", kind: .text, suggestions: nutTypes, hint: "Klasse aus bd_warehouse"),
                MeasureField("norm", "Norm", kind: .text, suggestions: ["iso4032", "iso4035"]),
                MeasureField("groesse", "Größe", kind: .text, suggestions: ["M4-0.7", "M5-0.8", "M6-1", "M8-1.25", "M10-1.5"]),
            ], supply: .piece, profile: "aus bd_warehouse"),
        Art(
            id: "scheibe", title: "Scheibe", plural: "Scheiben", symbol: "circle.dashed",
            fields: [
                MeasureField("typ", "Typ", kind: .text, suggestions: washerTypes, hint: "Klasse aus bd_warehouse"),
                MeasureField("norm", "Norm", kind: .text, suggestions: ["iso7089", "iso7090", "iso7092"]),
                MeasureField("groesse", "Größe", kind: .text, suggestions: ["M4", "M5", "M6", "M8", "M10"]),
            ], supply: .piece, profile: "aus bd_warehouse"),
    ]

    /// Art nach `id`; unbekannte Arten (neuer Kernel) bekommen eine allgemeine Beschreibung.
    public static func art(_ id: String) -> Art {
        if let known = arten.first(where: { $0.id == id }) { return known }
        if id == "eigenteil" {
            return Art(id: id, title: "Eigenteil", plural: "Eigenteile", symbol: "hammer", fields: [], supply: .piece,
                       profile: "frei modelliert")
        }
        if id == "druckteil" {
            return Art(id: id, title: "3D-Druckteil", plural: "3D-Druckteile", symbol: "printer.fill", fields: [],
                       supply: .piece, profile: "aus druckbarem Material, Kosten aus dem Filamentpreis")
        }
        let title = id.replacingOccurrences(of: "_", with: " ").capitalized
        return Art(id: id, title: title, plural: title, symbol: "shippingbox", fields: [], supply: .bar, profile: "")
    }

    /// Sortierschlüssel der Arten (bekannte in KATALOG.md-Reihenfolge, unbekannte dahinter).
    public static func order(of art: String) -> Int {
        arten.firstIndex { $0.id == art } ?? arten.count
    }

    /// Bezeichnung eines Maßes für die Anzeige, z. B. "Außendurchmesser d".
    public static func measureLabel(_ key: String, art: String) -> String {
        if let field = self.art(art).fields.first(where: { $0.key == key }) {
            if field.kind == .text || key.count > 1 || field.label.hasSuffix(" \(key)") { return field.label }
            return "\(field.label) \(key)"
        }
        let generic = [
            "d": "Durchmesser", "s": "Dicke", "a": "Kantenlänge", "b": "Breite", "h": "Höhe", "r": "Radius",
            "t": "Flanschdicke", "l": "Länge",
        ]
        return generic[key].map { "\($0) \(key)" } ?? key
    }

    /// Maßwert für die Anzeige: Zahlen mit Einheit, Texte unverändert.
    public static func measureValue(_ value: JSONValue, key: String, art: String) -> String {
        if let s = value.stringValue { return s }
        guard let d = value.doubleValue else { return "–" }
        let unit = self.art(art).fields.first { $0.key == key }?.unit ?? (["raster", "nut"].contains(key) ? nil : "mm")
        return unit.map { "\(KevFormat.compact(d)) \($0)" } ?? KevFormat.compact(d)
    }

    // MARK: Vorschläge

    /// Deutscher Name einer bd_warehouse-Klasse.
    public static func hardwareName(_ typ: String) -> String? {
        [
            "SocketHeadCapScrew": "Zylinderschraube", "ButtonHeadScrew": "Linsenkopfschraube",
            "CounterSunkScrew": "Senkschraube", "HexHeadScrew": "Sechskantschraube", "PanHeadScrew": "Flachkopfschraube",
            "SetScrew": "Gewindestift", "HexNut": "Sechskantmutter", "DomedCapNut": "Hutmutter",
            "SquareNut": "Vierkantmutter", "HeatSetNut": "Gewindeeinsatz", "PlainWasher": "Unterlegscheibe",
            "ChamferedWasher": "Scheibe mit Fase", "CheeseHeadWasher": "Scheibe",
        ][typ]
    }

    /// "iso4762" → "ISO 4762", "din125" → "DIN 125".
    public static func normTitle(_ norm: String) -> String {
        let t = norm.trimmingCharacters(in: .whitespaces)
        guard let firstDigit = t.firstIndex(where: \.isNumber), firstDigit != t.startIndex else { return t.uppercased() }
        let letters = t[..<firstDigit].trimmingCharacters(in: .whitespaces).uppercased()
        return "\(letters) \(t[firstDigit...])"
    }

    /// Namensvorschlag nach KATALOG.md: deutsches Komma und „×“, z. B. "Vierkantrohr 40 × 40 × 3".
    /// `masse` enthält Zahlen oder Texte; `materialName`/`materialGroup` verfeinern den Namen (Platte, Edelstahl).
    public static func suggestedName(
        art: String, masse: [String: JSONValue], materialName: String? = nil, materialGroup: String? = nil
    ) -> String {
        func n(_ key: String) -> String? { masse[key]?.doubleValue.map { KevFormat.compact($0) } }
        func text(_ key: String) -> String? { masse[key]?.lenientString }
        func join(_ keys: [String]) -> String? {
            let values = keys.map(n)
            guard values.allSatisfy({ $0 != nil }) else { return nil }
            return values.compactMap { $0 }.joined(separator: " × ")
        }
        let def = self.art(art)
        let metal = ["stahl", "edelstahl"].contains(materialGroup?.lowercased() ?? "stahl")
        let stainless = materialGroup?.lowercased() == "edelstahl"
        switch art {
        case "rohr":
            return [stainless ? "Edelstahlrohr" : "Rohr", join(["d", "s"])].compactMap { $0 }.joined(separator: " ")
        case "vierkantrohr":
            let a = n("a"), s = n("s")
            return ["Vierkantrohr", a.flatMap { a in s.map { "\(a) × \(a) × \($0)" } }].compactMap { $0 }
                .joined(separator: " ")
        case "rechteckrohr":
            return ["Rechteckrohr", join(["b", "h", "s"])].compactMap { $0 }.joined(separator: " ")
        case "flach":
            return [metal ? "Flachstahl" : "Flachprofil", join(["b", "s"])].compactMap { $0 }.joined(separator: " ")
        case "rund":
            return [metal ? "Rundstahl" : "Rundstange", n("d").map { "Ø \($0)" }].compactMap { $0 }
                .joined(separator: " ")
        case "vierkant":
            return [metal ? "Vierkantstahl" : "Vierkantstange", n("a")].compactMap { $0 }.joined(separator: " ")
        case "winkel":
            return ["Winkel", join(["a", "b", "s"])].compactMap { $0 }.joined(separator: " ")
        case "u_profil":
            return ["U-Profil", join(["h", "b", "s"])].compactMap { $0 }.joined(separator: " ")
        case "nutprofil":
            let size = join(["a", "b"]) ?? n("raster").map { "\($0) × \($0)" }
            return ["Nutprofil", size, n("nut").map { "Nut \($0)" }, text("variante")].compactMap { $0 }
                .joined(separator: " ")
        case "holz":
            return ["Kantholz", join(["b", "h"])].compactMap { $0 }.joined(separator: " ")
        case "platte":
            return [materialName ?? "Platte", n("s").map { "\($0) mm" }].compactMap { $0 }.joined(separator: " ")
        case "schraube", "mutter", "scheibe":
            let base = text("typ").flatMap(hardwareName) ?? def.title
            let size = text("groesse").map { String($0.split(separator: "-").first ?? Substring($0)) }
            return [base, text("norm").map(normTitle), size].compactMap { $0 }.joined(separator: " ")
        default:
            let values = def.fields.compactMap { n($0.key) }
            return ([def.title] + (values.isEmpty ? [] : [values.joined(separator: " × ")])).joined(separator: " ")
        }
    }

    /// ID-Vorschlag: Kleinbuchstaben, Bindestriche, Punkt als Dezimaltrenner, z. B. "rohr-33.7x2".
    public static func suggestedID(art: String, masse: [String: JSONValue], material: String? = nil) -> String {
        func n(_ key: String) -> String? {
            masse[key]?.doubleValue.map { KevFormat.compact($0).replacingOccurrences(of: ".", with: "")
                .replacingOccurrences(of: ",", with: ".") }
        }
        let def = self.art(art)
        var parts = [art.replacingOccurrences(of: "_", with: "-")]
        switch art {
        case "platte":
            if let material { parts.append(material) }
            if let s = n("s") { parts.append(s) }
        case "schraube", "mutter", "scheibe":
            if let norm = masse["norm"]?.lenientString { parts.append(norm) }
            if let g = masse["groesse"]?.lenientString { parts.append(String(g.split(separator: "-").first ?? "")) }
        case "vierkantrohr":
            if let a = n("a"), let s = n("s") { parts.append("\(a)x\(a)x\(s)") }
        case "nutprofil":
            let size = [n("a"), n("b")].compactMap { $0 }
            if size.count == 2 {
                parts.append(size.joined(separator: "x"))
            } else if let r = n("raster") {
                parts.append("\(r)x\(r)")
            }
            if let nut = n("nut") { parts.append("n\(nut)") }
            if let v = masse["variante"]?.lenientString { parts.append(v) }
        default:
            let values = def.fields.filter { $0.kind == .number && $0.required }.compactMap { n($0.key) }
            if !values.isEmpty { parts.append(values.joined(separator: "x")) }
            if let material, material.contains("edelstahl") || material.contains("alu") {
                parts.insert(material.contains("edelstahl") ? "edelstahl" : "alu", at: 1)
            }
        }
        return slug(parts.joined(separator: "-"))
    }

    /// Text als ID: klein, Umlaute umschrieben, nur a–z, 0–9, Punkt und Bindestrich.
    public static func slug(_ text: String) -> String {
        var t = text.lowercased()
        for (a, b) in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("×", "x"), (",", "."), ("ø", "")] {
            t = t.replacingOccurrences(of: a, with: b)
        }
        var out = ""
        var lastDash = false
        for ch in t {
            if ch.isASCII && (ch.isLetter || ch.isNumber || ch == ".") {
                out.append(ch)
                lastDash = false
            } else if !lastDash && !out.isEmpty {
                out.append("-")
                lastDash = true
            }
        }
        while out.hasSuffix("-") || out.hasSuffix(".") { out.removeLast() }
        return out
    }

    /// Gültige ID laut KATALOG.md (klein, Bindestriche; Punkt für Dezimalmaße wie "42.4").
    public static func isValidID(_ id: String) -> Bool {
        guard let first = id.first, first.isASCII, first.isLetter || first.isNumber else { return false }
        return id.allSatisfy { $0.isASCII && ($0.isLowercase || $0.isNumber || "-._".contains($0)) }
    }

    /// Materialgruppen laut KATALOG.md (Vorschläge im Formular).
    public static let materialGroups = [
        "Stahl", "Edelstahl", "Aluminium", "Buntmetall", "Holz", "Holzwerkstoff", "Kunststoff",
    ]

    /// Aktueller Monat für `stand`, z. B. "2026-10".
    public static func currentMonth(_ date: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM"
        return f.string(from: date)
    }

    static func isMonth(_ text: String) -> Bool {
        let parts = text.split(separator: "-")
        guard parts.count == 2, parts[0].count == 4, parts[1].count == 2, let m = Int(parts[1]), Int(parts[0]) != nil
        else { return false }
        return (1...12).contains(m)
    }
}

/// Fehler im Formular: Feld (z. B. "masse.d", "preis") und Meldung.
public struct CatalogIssue: Equatable, Sendable, Identifiable {
    public var field: String
    public var message: String
    public var id: String { field + message }

    public init(_ field: String, _ message: String) {
        self.field = field
        self.message = message
    }
}

// MARK: - Formular Lagerteil

/// Eingaben des Formulars „Lagerteil“ als Text (so, wie getippt). Aus einem vorhandenen Eintrag erzeugt, bleiben
/// unbekannte Felder in `extra` und `extraMasse` erhalten und gehen beim Speichern mit.
public struct CatalogItemDraft: Equatable, Sendable {
    public var art: String
    public var masse: [String: String] = [:]
    public var name = ""
    public var id = ""
    public var norm = ""
    public var material = ""
    public var kgJeM = ""
    public var stangenlaenge = ""
    public var formatB = ""
    public var formatH = ""
    public var preis = ""
    public var preisEinheit: CatalogSchema.PriceUnit
    public var preisQuelle = "eigene Angabe"
    public var preisStand = CatalogSchema.currentMonth()
    public var tags = ""
    public var extra: [String: JSONValue] = [:]
    public var extraMasse: [String: JSONValue] = [:]

    static let knownKeys: Set<String> = [
        "id", "art", "name", "norm", "masse", "material", "kg_je_m", "stangenlaenge", "platte", "preis", "tags", "ebene",
        "status",
    ]

    public init(art: String = "vierkantrohr") {
        self.art = art
        preisEinheit = CatalogSchema.art(art).priceUnit
        if CatalogSchema.art(art).supply == .bar { stangenlaenge = "6000" }
    }

    /// Aus einem Katalogeintrag (KATALOG.md) zum Bearbeiten oder Kopieren.
    public init(entry: JSONValue) {
        let art = entry["art"]?.lenientString ?? "vierkantrohr"
        self.init(art: art)
        stangenlaenge = ""
        id = entry["id"]?.lenientString ?? ""
        name = entry["name"]?.lenientString ?? ""
        norm = entry["norm"]?.lenientString ?? ""
        material = entry["material"]?.lenientString ?? ""
        kgJeM = entry["kg_je_m"]?.doubleValue.map(KevFormat.input) ?? ""
        stangenlaenge = entry["stangenlaenge"]?.doubleValue.map(KevFormat.input) ?? ""
        let fieldKeys = Set(CatalogSchema.art(art).fields.map(\.key))
        for (key, value) in entry["masse"]?.objectValue ?? [:] {
            if fieldKeys.contains(key) {
                masse[key] = value.stringValue ?? value.doubleValue.map(KevFormat.input) ?? ""
            } else if key == "platte" {
                continue
            } else {
                extraMasse[key] = value
            }
        }
        if let format = (entry["platte"] ?? entry["masse"]?["platte"])?.doubles, format.count == 2 {
            formatB = KevFormat.input(format[0])
            formatH = KevFormat.input(format[1])
        }
        if let p = entry["preis"] {
            for unit in CatalogSchema.PriceUnit.allCases {
                if let v = p[unit.rawValue]?.doubleValue {
                    preis = KevFormat.input(v)
                    preisEinheit = unit
                    break
                }
            }
            preisQuelle = p["quelle"]?.lenientString ?? (preis.isEmpty ? preisQuelle : "")
            preisStand = p["stand"]?.lenientString ?? (preis.isEmpty ? preisStand : "")
        }
        tags = (entry["tags"]?.stringList ?? []).joined(separator: ", ")
        for (key, value) in entry.objectValue ?? [:] where !Self.knownKeys.contains(key) { extra[key] = value }
    }

    public var schema: CatalogSchema.Art { CatalogSchema.art(art) }

    /// Maße als JSON-Werte (Zahlen geparst, Texte getrimmt), nur gültige.
    public var masseValues: [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        for field in schema.fields {
            let text = (masse[field.key] ?? "").trimmingCharacters(in: .whitespaces)
            guard !text.isEmpty else { continue }
            switch field.kind {
            case .number: if let d = KevFormat.parseNumber(text) { out[field.key] = .number(d) }
            case .text: out[field.key] = .string(text)
            }
        }
        return out
    }

    /// Pflichtfelder und Zahlen prüfen. `materials`: bekannte Material-IDs (leer = nicht prüfen).
    public func validate(materials: Set<String> = []) -> [CatalogIssue] {
        var issues: [CatalogIssue] = []
        let idText = id.trimmingCharacters(in: .whitespaces)
        if idText.isEmpty {
            issues.append(CatalogIssue("id", "ID fehlt"))
        } else if !CatalogSchema.isValidID(idText) {
            issues.append(CatalogIssue("id", "ID nur aus Kleinbuchstaben, Ziffern, Punkt und Bindestrich"))
        }
        if name.trimmingCharacters(in: .whitespaces).isEmpty { issues.append(CatalogIssue("name", "Name fehlt")) }
        if art.trimmingCharacters(in: .whitespaces).isEmpty { issues.append(CatalogIssue("art", "Art fehlt")) }
        for field in schema.fields {
            let text = (masse[field.key] ?? "").trimmingCharacters(in: .whitespaces)
            if text.isEmpty {
                if field.required { issues.append(CatalogIssue("masse.\(field.key)", "\(field.label) fehlt")) }
                continue
            }
            if field.kind == .number {
                guard let d = KevFormat.parseNumber(text) else {
                    issues.append(CatalogIssue("masse.\(field.key)", "\(field.label): keine Zahl"))
                    continue
                }
                if d <= 0 { issues.append(CatalogIssue("masse.\(field.key)", "\(field.label) muss größer als 0 sein")) }
            }
        }
        if let s = masseValues["s"]?.doubleValue {
            if art == "rohr", let d = masseValues["d"]?.doubleValue, s * 2 >= d {
                issues.append(CatalogIssue("masse.s", "Wandstärke zu groß für den Durchmesser"))
            }
            if art == "vierkantrohr", let a = masseValues["a"]?.doubleValue, s * 2 >= a {
                issues.append(CatalogIssue("masse.s", "Wandstärke zu groß für die Kantenlänge"))
            }
        }
        let mat = material.trimmingCharacters(in: .whitespaces)
        if mat.isEmpty {
            issues.append(CatalogIssue("material", "Material fehlt"))
        } else if !materials.isEmpty && !materials.contains(mat) {
            issues.append(CatalogIssue("material", "Material „\(mat)“ gibt es im Katalog nicht"))
        }
        func positive(_ text: String, _ field: String, _ label: String) {
            let t = text.trimmingCharacters(in: .whitespaces)
            guard !t.isEmpty else { return }
            if let d = KevFormat.parseNumber(t) {
                if d <= 0 { issues.append(CatalogIssue(field, "\(label) muss größer als 0 sein")) }
            } else {
                issues.append(CatalogIssue(field, "\(label): keine Zahl"))
            }
        }
        positive(kgJeM, "kg_je_m", "Gewicht je Meter")
        if schema.supply == .bar { positive(stangenlaenge, "stangenlaenge", "Stangenlänge") }
        if schema.supply == .sheet {
            positive(formatB, "platte", "Format Breite")
            positive(formatH, "platte", "Format Höhe")
            if formatB.trimmingCharacters(in: .whitespaces).isEmpty != formatH.trimmingCharacters(in: .whitespaces).isEmpty {
                issues.append(CatalogIssue("platte", "Format braucht Breite und Höhe"))
            }
        }
        let priceText = preis.trimmingCharacters(in: .whitespaces)
        if !priceText.isEmpty {
            if let d = KevFormat.parseNumber(priceText) {
                if d < 0 { issues.append(CatalogIssue("preis", "Preis darf nicht negativ sein")) }
            } else {
                issues.append(CatalogIssue("preis", "Preis: keine Zahl"))
            }
            if preisQuelle.trimmingCharacters(in: .whitespaces).isEmpty {
                issues.append(CatalogIssue("preis_quelle", "Quelle des Preises fehlt"))
            }
            let stand = preisStand.trimmingCharacters(in: .whitespaces)
            if stand.isEmpty {
                issues.append(CatalogIssue("preis_stand", "Stand des Preises fehlt"))
            } else if !CatalogSchema.isMonth(stand) {
                issues.append(CatalogIssue("preis_stand", "Stand als Jahr-Monat, z. B. \(CatalogSchema.currentMonth())"))
            }
        }
        return issues
    }

    /// Der Eintrag laut KATALOG.md (ohne `ebene`). Was Kevin in der App anlegt oder ändert, ist immer freigegeben
    /// (`status: "frei"`), auch wenn es ein Vorschlag von Claude war.
    public func entry() -> JSONValue {
        var o = extra
        o["status"] = "frei"
        o["id"] = .string(id.trimmingCharacters(in: .whitespaces))
        o["art"] = .string(art)
        o["name"] = .string(name.trimmingCharacters(in: .whitespaces))
        let normText = norm.trimmingCharacters(in: .whitespaces)
        if !normText.isEmpty { o["norm"] = .string(normText) }
        var m = masseValues
        let fieldKeys = Set(schema.fields.map(\.key))
        for (key, value) in extraMasse where !fieldKeys.contains(key) { m[key] = value }
        o["masse"] = .object(m)
        o["material"] = .string(material.trimmingCharacters(in: .whitespaces))
        if let kg = KevFormat.parseNumber(kgJeM) { o["kg_je_m"] = .number(kg) }
        if schema.supply == .bar, let l = KevFormat.parseNumber(stangenlaenge) { o["stangenlaenge"] = .number(l) }
        if schema.supply == .sheet, let b = KevFormat.parseNumber(formatB), let h = KevFormat.parseNumber(formatH) {
            o["platte"] = .array([.number(b), .number(h)])
        }
        if let p = KevFormat.parseNumber(preis) {
            o["preis"] = .object([
                preisEinheit.rawValue: .number(p), "quelle": .string(preisQuelle.trimmingCharacters(in: .whitespaces)),
                "stand": .string(preisStand.trimmingCharacters(in: .whitespaces)),
            ])
        }
        let tagList = tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            .filter { !$0.isEmpty }
        if !tagList.isEmpty { o["tags"] = .array(tagList.map { .string($0) }) }
        return .object(o)
    }

    public func json() -> Data { CatalogDraftEncoding.encode(entry()) }

    /// Vorschläge für Name und ID aus Art, Maßen und Material.
    public func suggestedName(materialName: String?, materialGroup: String?) -> String {
        CatalogSchema.suggestedName(art: art, masse: masseValues, materialName: materialName, materialGroup: materialGroup)
    }

    public func suggestedID() -> String {
        CatalogSchema.suggestedID(art: art, masse: masseValues, material: material.isEmpty ? nil : material)
    }
}

// MARK: - Formular Material

public struct CatalogMaterialDraft: Equatable, Sendable {
    public var id = ""
    public var name = ""
    public var gruppe = "Stahl"
    public var dichte = ""
    public var farbe = "#8A9099"
    public var metallisch = ""
    public var rauheit = ""
    public var preisJeKg = ""
    public var preisQuelle = "eigene Angabe"
    public var preisStand = CatalogSchema.currentMonth()
    public var aliase = ""
    /// Filament für 3D-Druckteile.
    public var druckbar = false
    public var extra: [String: JSONValue] = [:]

    static let knownKeys: Set<String> = [
        "id", "name", "gruppe", "dichte", "farbe", "metallisch", "rauheit", "preis_je_kg", "preis_quelle",
        "preis_stand", "aliase", "ebene", "status", "druckbar",
    ]

    public init() {}

    public init(entry: JSONValue) {
        id = entry["id"]?.lenientString ?? ""
        name = entry["name"]?.lenientString ?? ""
        gruppe = entry["gruppe"]?.lenientString ?? ""
        dichte = entry["dichte"]?.doubleValue.map(KevFormat.input) ?? ""
        farbe = entry["farbe"]?.lenientString ?? "#8A9099"
        metallisch = entry["metallisch"]?.doubleValue.map(KevFormat.input) ?? ""
        rauheit = entry["rauheit"]?.doubleValue.map(KevFormat.input) ?? ""
        preisJeKg = entry["preis_je_kg"]?.doubleValue.map(KevFormat.input) ?? ""
        if !preisJeKg.isEmpty {
            preisQuelle = entry["preis_quelle"]?.lenientString ?? ""
            preisStand = entry["preis_stand"]?.lenientString ?? ""
        }
        aliase = (entry["aliase"]?.stringList ?? []).joined(separator: ", ")
        druckbar = entry["druckbar"]?.boolValue ?? false
        for (key, value) in entry.objectValue ?? [:] where !Self.knownKeys.contains(key) { extra[key] = value }
    }

    /// "#8A9099" (auch ohne #, drei- oder sechsstellig) → normiertes "#8A9099", sonst nil.
    public static func normalizedHex(_ text: String) -> String? {
        var t = text.trimmingCharacters(in: .whitespaces).uppercased()
        if t.hasPrefix("#") { t.removeFirst() }
        guard t.allSatisfy({ $0.isHexDigit }) else { return nil }
        if t.count == 3 { t = t.map { "\($0)\($0)" }.joined() }
        return t.count == 6 ? "#" + t : nil
    }

    public func validate() -> [CatalogIssue] {
        var issues: [CatalogIssue] = []
        let idText = id.trimmingCharacters(in: .whitespaces)
        if idText.isEmpty {
            issues.append(CatalogIssue("id", "ID fehlt"))
        } else if !CatalogSchema.isValidID(idText) {
            issues.append(CatalogIssue("id", "ID nur aus Kleinbuchstaben, Ziffern, Punkt und Bindestrich"))
        }
        if name.trimmingCharacters(in: .whitespaces).isEmpty { issues.append(CatalogIssue("name", "Name fehlt")) }
        if gruppe.trimmingCharacters(in: .whitespaces).isEmpty { issues.append(CatalogIssue("gruppe", "Gruppe fehlt")) }
        if let d = KevFormat.parseNumber(dichte) {
            if d <= 0 || d > 25 { issues.append(CatalogIssue("dichte", "Dichte in g/cm³, zwischen 0 und 25")) }
        } else {
            issues.append(CatalogIssue("dichte", dichte.trimmingCharacters(in: .whitespaces).isEmpty
                ? "Dichte fehlt" : "Dichte: keine Zahl"))
        }
        if Self.normalizedHex(farbe) == nil { issues.append(CatalogIssue("farbe", "Farbe als Hexwert, z. B. #8A9099")) }
        for (text, field, label) in [(metallisch, "metallisch", "Metallisch"), (rauheit, "rauheit", "Rauheit")] {
            let t = text.trimmingCharacters(in: .whitespaces)
            guard !t.isEmpty else { continue }
            if let d = KevFormat.parseNumber(t), (0...1).contains(d) { continue }
            issues.append(CatalogIssue(field, "\(label) zwischen 0 und 1"))
        }
        if !preisJeKg.trimmingCharacters(in: .whitespaces).isEmpty {
            if let d = KevFormat.parseNumber(preisJeKg) {
                if d < 0 { issues.append(CatalogIssue("preis_je_kg", "Preis darf nicht negativ sein")) }
            } else {
                issues.append(CatalogIssue("preis_je_kg", "Preis: keine Zahl"))
            }
            if preisQuelle.trimmingCharacters(in: .whitespaces).isEmpty {
                issues.append(CatalogIssue("preis_quelle", "Quelle des Preises fehlt"))
            }
            let stand = preisStand.trimmingCharacters(in: .whitespaces)
            if !CatalogSchema.isMonth(stand) {
                issues.append(CatalogIssue("preis_stand", stand.isEmpty
                    ? "Stand des Preises fehlt" : "Stand als Jahr-Monat, z. B. \(CatalogSchema.currentMonth())"))
            }
        }
        return issues
    }

    public func entry() -> JSONValue {
        var o = extra
        o["status"] = "frei"
        o["id"] = .string(id.trimmingCharacters(in: .whitespaces))
        o["name"] = .string(name.trimmingCharacters(in: .whitespaces))
        o["gruppe"] = .string(gruppe.trimmingCharacters(in: .whitespaces))
        if druckbar { o["druckbar"] = true }
        if let d = KevFormat.parseNumber(dichte) { o["dichte"] = .number(d) }
        o["farbe"] = .string(Self.normalizedHex(farbe) ?? farbe)
        if let v = KevFormat.parseNumber(metallisch) { o["metallisch"] = .number(v) }
        if let v = KevFormat.parseNumber(rauheit) { o["rauheit"] = .number(v) }
        if let p = KevFormat.parseNumber(preisJeKg) {
            o["preis_je_kg"] = .number(p)
            o["preis_quelle"] = .string(preisQuelle.trimmingCharacters(in: .whitespaces))
            o["preis_stand"] = .string(preisStand.trimmingCharacters(in: .whitespaces))
        }
        let list = aliase.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            .filter { !$0.isEmpty }
        if !list.isEmpty { o["aliase"] = .array(list.map { .string($0) }) }
        return .object(o)
    }

    public func json() -> Data { CatalogDraftEncoding.encode(entry()) }

    public func suggestedID() -> String { CatalogSchema.slug(name) }
}

enum CatalogDraftEncoding {
    static func encode(_ value: JSONValue) -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return (try? enc.encode(value)) ?? Data("{}".utf8)
    }
}

// MARK: - Suche

/// Suche im Katalog ohne Kernel: jedes Wort muss irgendwo vorkommen (Name, ID, Norm, Art, Material, Tags, Maße).
/// „40x40“ findet „40 × 40“, „33,7“ und „33.7“ sind gleich, Umlaute egal.
public enum CatalogSearch {
    public static func normalize(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: KevFormat.locale)
            .replacingOccurrences(of: " × ", with: "x").replacingOccurrences(of: "×", with: "x")
            .replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: "ø", with: "")
    }

    public static func tokens(_ query: String) -> [String] {
        normalize(query).split(whereSeparator: \.isWhitespace).map(String.init)
    }

    public static func haystack(_ item: CatalogItem, material: CatalogMaterial?) -> String {
        let art = CatalogSchema.art(item.art)
        var fields = [item.name, item.id, item.norm ?? "", item.art, art.title, art.plural, item.material]
        fields += item.tags
        if let material { fields += [material.name, material.gruppe] }
        for (key, value) in item.entry["masse"]?.objectValue ?? [:] {
            fields.append(value.stringValue ?? value.doubleValue.map { "\(key)\(KevFormat.compact($0))" } ?? "")
        }
        return normalize(fields.joined(separator: " "))
    }

    public static func matches(_ item: CatalogItem, tokens: [String], material: CatalogMaterial?) -> Bool {
        guard !tokens.isEmpty else { return true }
        let hay = haystack(item, material: material)
        return tokens.allSatisfy { hay.contains($0) }
    }

    public static func matches(_ material: CatalogMaterial, tokens: [String]) -> Bool {
        guard !tokens.isEmpty else { return true }
        var fields = [material.name, material.id, material.gruppe]
        fields += material.entry["aliase"]?.stringList ?? []
        let hay = normalize(fields.joined(separator: " "))
        return tokens.allSatisfy { hay.contains($0) }
    }

    /// Sortierung: Art (KATALOG.md-Reihenfolge), dann Maße der Art der Reihe nach, dann Name.
    public static func sorted(_ items: [CatalogItem]) -> [CatalogItem] {
        items.sorted { a, b in
            let oa = CatalogSchema.order(of: a.art), ob = CatalogSchema.order(of: b.art)
            if oa != ob { return oa < ob }
            if a.art != b.art { return a.art < b.art }
            for field in CatalogSchema.art(a.art).fields where field.kind == .number {
                let va = a.masse[field.key] ?? 0, vb = b.masse[field.key] ?? 0
                if va != vb { return va < vb }
            }
            return a.name.localizedStandardCompare(b.name) == .orderedAscending
        }
    }
}
