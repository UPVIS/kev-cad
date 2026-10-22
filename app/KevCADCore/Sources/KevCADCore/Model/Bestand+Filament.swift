import Foundation

// Filament im Bestand (Strang „Bestand Stufe 2“, BESTAND.md Abschnitt „Filament“): Spulen je Material und Farbe in
// bestand.json (Liste `filament`), was „Gebaut“ davon abbuchen würde (BESTAND `gebaut_filament`, gerechnet vom Kernel,
// damit Vorschau und Buchung dieselbe Rechnung sind) und das Bearbeiten als ganze Spule für BESTAND_SAVE.

/// Eine Filamentspule mit Kennung `S-0001`.
public struct BestandSpule: Identifiable, Equatable, Sendable {
    public enum Zustand: String, Sendable {
        case voll, angebrochen, leer

        public var titel: String {
            switch self {
            case .voll: return "voll"
            case .angebrochen: return "angebrochen"
            case .leer: return "leer"
            }
        }
    }

    public var kennung: String
    /// Material-id aus dem Katalog („petg“).
    public var material: String
    public var gramm: Double
    /// Netto einer vollen Spule; nil, wenn unbekannt.
    public var grammVoll: Double?
    public var name: String?
    public var hersteller: String?
    public var farbe: String?
    public var ort: String?
    public var seit: String?
    /// Die Spule roh wie in der Datei.
    public var json: JSONValue

    public var id: String { kennung }

    public init?(json: JSONValue) {
        guard json.objectValue != nil, let k = json["kennung"]?.lenientString, let m = json["material"]?.lenientString
        else { return nil }
        kennung = k
        material = m
        gramm = max(0, json["gramm"]?.doubleValue ?? 0)
        grammVoll = json["gramm_voll"]?.doubleValue.flatMap { $0 > 0 ? $0 : nil }
        name = json["name"]?.lenientString
        hersteller = json["hersteller"]?.lenientString
        farbe = json["farbe"]?.lenientString
        ort = json["ort"]?.lenientString
        seit = json["seit"]?.lenientString
        self.json = json
    }

    /// Voll, angebrochen oder leer; ohne bekannte volle Menge gilt sie als angebrochen (wie der Kernel beim Abbuchen).
    public var zustand: Zustand {
        if gramm <= 0.05 { return .leer }
        guard let v = grammVoll else { return .angebrochen }
        return gramm >= v - 0.05 ? .voll : .angebrochen
    }

    /// Anteil übrig (0…1) für den Balken; nil ohne volle Menge.
    public var anteil: Double? { grammVoll.map { min(1, max(0, gramm / $0)) } }

    /// „Bambu PETG Basic schwarz“, sonst „Bambu Lab schwarz“, sonst die Kennung.
    public var bezeichnung: String {
        if let name, !name.isEmpty { return name }
        let t = [hersteller, farbe].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " ")
        return t.isEmpty ? kennung : t
    }

    /// „640 g von 1.000 g“ bzw. „640 g“.
    public var mengeText: String {
        let g = KevFormat.compact(gramm, maxDigits: 1) + " g"
        return grammVoll.map { "\(g) von \(KevFormat.compact($0, maxDigits: 1)) g" } ?? g
    }

    /// Reihenfolge wie beim Abbuchen im Kernel: angebrochene mit wenig Filament zuerst, dann volle, nach Kennung.
    public static func reihenfolge(_ a: BestandSpule, _ b: BestandSpule) -> Bool {
        let va = a.zustand != .voll, vb = b.zustand != .voll
        if va != vb { return va }
        if a.gramm != b.gramm { return a.gramm < b.gramm }
        return a.kennung < b.kennung
    }
}

extension Bestand {
    /// Filamentspulen (Liste `filament` der Datei), nach Kennung.
    public var spulen: [BestandSpule] {
        (json["filament"]?.arrayValue ?? []).compactMap(BestandSpule.init(json:)).sorted { $0.kennung < $1.kennung }
    }

    /// Das Projekt führt Filament (Liste `filament` vorhanden, auch leer): Einkauf und „Gebaut“ rechnen mit Spulen.
    public var fuehrtFilament: Bool { json["filament"]?.arrayValue != nil }

    /// Spulen eines Materials in der Reihenfolge, in der sie verbraucht werden.
    public func spulen(material: String) -> [BestandSpule] {
        spulen.filter { $0.material == material }.sorted(by: BestandSpule.reihenfolge)
    }

    /// Materialien der Spulen in der Reihenfolge ihrer ersten Spule.
    public var filamentMaterialien: [String] {
        var out: [String] = []
        for s in spulen where !out.contains(s.material) { out.append(s.material) }
        return out
    }
}

/// Eine Spule zum Erfassen oder Ändern (BESTAND_SAVE `spule`): dieselben Felder und Regeln wie MCP
/// `bestand_eintragen` mit `material`, `gramm`, `spule` …; prüfen tut der Kernel, hier nur das Offensichtliche.
public struct SpulenEingabe: Equatable, Sendable {
    public var material: String
    public var gramm: Double?
    public var grammVoll: Double?
    public var name: String
    public var hersteller: String
    public var farbe: String
    public var ort: String

    public init(
        material: String, gramm: Double? = nil, grammVoll: Double? = nil, name: String = "", hersteller: String = "",
        farbe: String = "", ort: String = ""
    ) {
        self.material = material
        self.gramm = gramm
        self.grammVoll = grammVoll
        self.name = name
        self.hersteller = hersteller
        self.farbe = farbe
        self.ort = ort
    }

    /// Vorbelegt mit einer vorhandenen Spule (Ändern).
    public init(_ s: BestandSpule) {
        self.init(material: s.material, gramm: s.gramm, grammVoll: s.grammVoll, name: s.name ?? "",
                  hersteller: s.hersteller ?? "", farbe: s.farbe ?? "", ort: s.ort ?? "")
    }

    /// Fehler für die Oberfläche (nil = absendbar).
    public var fehler: String? {
        if material.trimmingCharacters(in: .whitespaces).isEmpty { return "Material wählen" }
        if let g = gramm, g < 0 { return "Gramm übrig darf nicht negativ sein" }
        if let v = grammVoll, v <= 0 { return "Gramm voll muss größer als 0 sein" }
        if let g = gramm, let v = grammVoll, g > 1.5 * v { return "Mehr als anderthalb volle Spulen: Tippfehler?" }
        return nil
    }

    /// Als `spule` für BESTAND_SAVE; leere Texte löschen das Feld (der Kernel macht daraus null).
    public var json: JSONValue {
        var o: [String: JSONValue] = [
            "material": .string(material.trimmingCharacters(in: .whitespaces)),
            "name": .string(name.trimmingCharacters(in: .whitespaces)),
            "hersteller": .string(hersteller.trimmingCharacters(in: .whitespaces)),
            "farbe": .string(farbe.trimmingCharacters(in: .whitespaces)),
            "ort": .string(ort.trimmingCharacters(in: .whitespaces)),
        ]
        if let gramm { o["gramm"] = .number(gramm) }
        if let grammVoll { o["gramm_voll"] = .number(grammVoll) }
        return .object(o)
    }
}

/// Was „Gebaut“ jetzt vom Filament abbuchen würde (BESTAND `gebaut_filament`, BESTAND.md „Filament“). Der Kernel
/// rechnet es mit derselben Funktion wie die Buchung und schickt es neu, sobald eine Druckvorschau oder der Bestand
/// sich ändert.
public struct GebautFilament: Equatable, Sendable {
    public struct Platte: Identifiable, Equatable, Sendable {
        public var nr: Int
        public var material: [(material: String, g: Double)]
        /// Buchung, mit der die Platte schon als gedruckt gebucht ist.
        public var gebucht: String?
        /// „Gebaut“ bucht sie jetzt ab.
        public var buchen: Bool

        public var id: Int { nr }

        public static func == (a: Platte, b: Platte) -> Bool {
            a.nr == b.nr && a.gebucht == b.gebucht && a.buchen == b.buchen
                && a.material.map(\.material) == b.material.map(\.material) && a.material.map(\.g) == b.material.map(\.g)
        }
    }

    public struct Verbrauch: Identifiable, Equatable, Sendable {
        public var kennung: String
        public var material: String
        public var name: String?
        public var farbe: String?
        public var gramm: Double
        public var vorher: Double
        public var nachher: Double
        /// Die Spule ist danach leer und wird entfernt.
        public var leer: Bool

        public var id: String { kennung }
    }

    public struct NeueSpule: Identifiable, Equatable, Sendable {
        public var kennung: String
        public var material: String
        public var gramm: Double
        public var grammVoll: Double?

        public var id: String { kennung }
    }

    /// Lauf der Stückliste, zu dem die Rechnung gehört (nil: noch keine).
    public var run: Int?
    public var platten: [Platte]
    public var ganzGebucht: String?
    public var spulen: [Verbrauch]
    public var neueSpulen: [NeueSpule]
    /// Filament, das als von gekauften Spulen gedruckt vorausgesetzt ist.
    public var gekauft: [(material: String, gramm: Double)]
    public var materialien: [String: String]
    public var hinweis: String?

    public static func == (a: GebautFilament, b: GebautFilament) -> Bool {
        a.run == b.run && a.platten == b.platten && a.ganzGebucht == b.ganzGebucht && a.spulen == b.spulen
            && a.neueSpulen == b.neueSpulen && a.gekauft.map(\.material) == b.gekauft.map(\.material)
            && a.gekauft.map(\.gramm) == b.gekauft.map(\.gramm) && a.materialien == b.materialien
            && a.hinweis == b.hinweis
    }

    public init(
        run: Int?, platten: [Platte] = [], ganzGebucht: String? = nil, spulen: [Verbrauch] = [],
        neueSpulen: [NeueSpule] = [], gekauft: [(material: String, gramm: Double)] = [],
        materialien: [String: String] = [:], hinweis: String? = nil
    ) {
        self.run = run
        self.platten = platten
        self.ganzGebucht = ganzGebucht
        self.spulen = spulen
        self.neueSpulen = neueSpulen
        self.gekauft = gekauft
        self.materialien = materialien
        self.hinweis = hinweis
    }

    public init?(json: JSONValue?) {
        guard let json, json.objectValue != nil else { return nil }
        self.init(
            run: json["run"]?.intValue,
            platten: (json["platten"]?.arrayValue ?? []).compactMap { p in
                guard let nr = p["nr"]?.intValue else { return nil }
                return Platte(
                    nr: nr,
                    material: (p["material"]?.arrayValue ?? []).compactMap { m in
                        m["material"]?.lenientString.map { ($0, m["g"]?.doubleValue ?? 0) }
                    },
                    gebucht: p["gebucht"]?.lenientString, buchen: p["buchen"]?.boolValue ?? false)
            },
            ganzGebucht: json["ganz_gebucht"]?.lenientString,
            spulen: (json["spulen"]?.arrayValue ?? []).compactMap { s in
                guard let k = s["kennung"]?.lenientString else { return nil }
                return Verbrauch(
                    kennung: k, material: s["material"]?.lenientString ?? "", name: s["name"]?.lenientString,
                    farbe: s["farbe"]?.lenientString, gramm: s["gramm"]?.doubleValue ?? 0,
                    vorher: s["vorher"]?.doubleValue ?? 0, nachher: s["nachher"]?.doubleValue ?? 0,
                    leer: s["leer"]?.boolValue ?? false)
            },
            neueSpulen: (json["neue_spulen"]?.arrayValue ?? []).compactMap { s in
                guard let k = s["kennung"]?.lenientString else { return nil }
                return NeueSpule(kennung: k, material: s["material"]?.lenientString ?? "",
                                 gramm: s["gramm"]?.doubleValue ?? 0, grammVoll: s["gramm_voll"]?.doubleValue)
            },
            gekauft: (json["gekauft"]?.arrayValue ?? []).compactMap { g in
                g["material"]?.lenientString.map { ($0, g["gramm"]?.doubleValue ?? 0) }
            },
            materialien: (json["materialien"]?.objectValue ?? [:]).compactMapValues(\.lenientString),
            hinweis: json["hinweis"]?.lenientString)
    }

    /// Es gibt Filament abzubuchen (auch wenn der Zuschnitt nichts aus dem Bestand nimmt).
    public var hatBuchbares: Bool { !spulen.isEmpty || !neueSpulen.isEmpty }

    /// Anzeigename eines Materials („PETG“).
    public func name(_ material: String) -> String { materialien[material] ?? material.uppercased() }

    /// „PETG 188,8 g“ für eine Platte.
    public func plattenText(_ p: Platte) -> String {
        p.material.map { "\(name($0.material)) \(KevFormat.mass(grams: $0.g))" }.joined(separator: ", ")
    }
}

extension BestandZustand {
    /// Die Filament-Rechnung des Kernels, wenn sie zur aktuellen Stückliste gehört.
    public var gebautFilamentAktuell: GebautFilament? {
        guard let f = gebautFilament, let run = f.run, let z = zuschnitt, z.run == run else { return nil }
        return f
    }

    /// „Gebaut“ hat etwas zu buchen: der Zuschnitt nimmt etwas aus dem Bestand bzw. lässt Reste entstehen, oder es ist
    /// Filament abzubuchen (Strang „Bestand Stufe 2“: sonst wäre „Gebaut“ gesperrt, wenn nur Filament zu buchen ist).
    public var hatBuchbares: Bool {
        (zuschnitt?.hatBuchbares ?? false) || (gebautFilamentAktuell?.hatBuchbares ?? false)
    }
}
