import Foundation

// Freigabe direkt im Projektfenster (Strang „Feinschliff 2“, PROTOCOL.md Abschnitt „Freigabe im Projektfenster“).
// Vorschläge von Claude gibt nur Kevin frei. Bisher ging das nur im Lagerkatalog; jetzt zeigt das Projektfenster ein
// Band „3 Vorschläge warten auf Freigabe“ und den Dialog „Vorschläge freigeben“ (Vorschau der Daten, Link, Freigeben je
// Eintrag und für alle). `freigabe_anfragen` öffnet denselben Dialog über FREIGABE_ANFRAGE; geschlossen meldet die App
// FREIGABE_GESCHLOSSEN. Freigegeben wird wie im Lagerkatalog mit CATALOG_SAVE und `status: "frei"`, einer nach dem
// anderen; Fehler bleiben stehen, bis Kevin sie wegklickt oder neu freigibt.

/// Ein Eintrag der Anfrage: id und Art (`teil` oder `material`).
public struct FreigabeEintrag: Identifiable, Equatable, Hashable, Sendable {
    public var id: String
    public var kind: String
    public var name: String
    /// Vermerk `freigegeben_von` im Katalogeintrag (nur bei der Freigabe vom iPhone: „Kevin (iPhone)“), sonst nil.
    public var von: String?

    public init(id: String, kind: String, name: String? = nil, von: String? = nil) {
        self.id = id
        self.kind = kind
        self.name = name ?? id
        self.von = von
    }
}

/// FREIGABE_ANFRAGE (Kernel → App): Claude bittet Kevin, diese Vorschläge freizugeben.
public struct FreigabeAnfrage: Equatable, Sendable {
    /// `id` der Nachricht (Antwort ACK mit `reply_to`).
    public var requestID: String
    /// Kennung der Anfrage („F-0001“), kommt mit FREIGABE_GESCHLOSSEN zurück.
    public var anfrage: String
    public var eintraege: [FreigabeEintrag]
    /// Wofür Claude die Teile braucht (eine Zeile), oder nil.
    public var grund: String?

    public init(requestID: String, anfrage: String, eintraege: [FreigabeEintrag], grund: String? = nil) {
        self.requestID = requestID
        self.anfrage = anfrage
        self.eintraege = eintraege
        self.grund = grund
    }

    public static func decode(_ header: Data) throws -> FreigabeAnfrage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        let eintraege: [FreigabeEintrag] = (json["eintraege"]?.arrayValue ?? []).compactMap { e in
            guard let id = e["id"]?.lenientString else { return nil }
            let kind = e["kind"]?.stringValue == "material" ? "material" : "teil"
            return FreigabeEintrag(id: id, kind: kind, name: e["name"]?.lenientString)
        }
        let grund = json["grund"]?.lenientString?.trimmingCharacters(in: .whitespacesAndNewlines)
        return FreigabeAnfrage(
            requestID: json["id"]?.lenientString ?? "", anfrage: json["anfrage"]?.lenientString ?? "",
            eintraege: eintraege, grund: grund?.isEmpty == false ? grund : nil)
    }
}

/// FREIGABE_GESCHLOSSEN (App → Kernel): Kevin hat den Dialog geschlossen.
public struct FreigabeGeschlossenMessage: OutgoingMessage {
    public static let type = "FREIGABE_GESCHLOSSEN"
    public var seq = 0
    public var anfrage: String
    public var freigegeben: [String]
    public var abgelehnt: [String]
    public var offen: [String]

    public init(anfrage: String, freigegeben: [String], abgelehnt: [String] = [], offen: [String]) {
        self.anfrage = anfrage
        self.freigegeben = freigegeben
        self.abgelehnt = abgelehnt
        self.offen = offen
    }

    enum CodingKeys: String, CodingKey { case type, seq, anfrage, freigegeben, abgelehnt, offen }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(anfrage, forKey: .anfrage)
        try c.encode(freigegeben, forKey: .freigegeben)
        try c.encode(abgelehnt, forKey: .abgelehnt)
        try c.encode(offen, forKey: .offen)
    }
}

/// Zustand der Freigabe im Projektfenster (AppModel.freigabe, gesetzt nur vom App-Kern).
public struct FreigabeZustand: Equatable, Sendable {
    /// Offene Anfrage von Claude (Dialog geöffnet), sonst nil.
    public var anfrage: FreigabeAnfrage?
    /// Eintrag, dessen Freigabe gerade läuft (CATALOG_SAVE bis zur Bestätigung im neu geladenen Katalog).
    public var laeuft: String?
    /// Danach freizugebende Einträge („Alle freigeben“), der Reihe nach.
    public var warteschlange: [FreigabeEintrag] = []
    /// In diesem Dialog freigegeben (für die Anzeige und FREIGABE_GESCHLOSSEN).
    public var freigegeben: [String] = []
    /// Letzter Fehler; bleibt stehen, bis Kevin ihn wegklickt oder neu freigibt.
    public var fehler: String?

    public init() {}

    /// Läuft gerade eine Freigabe oder wartet eine?
    public var beschaeftigt: Bool { laeuft != nil || !warteschlange.isEmpty }

    /// Wartet dieser Eintrag auf seine Freigabe (läuft oder in der Warteschlange)?
    public func wartet(_ id: String) -> Bool { laeuft == id || warteschlange.contains { $0.id == id } }
}

/// Aktionen der Oberfläche für die Freigabe (implementiert vom App-Kern).
@MainActor
public protocol FreigabeActions: AnyObject {
    /// Einträge freigeben (CATALOG_SAVE mit `status: "frei"`), einer nach dem anderen; nur Kevins Klick.
    func freigeben(_ eintraege: [FreigabeEintrag])
    /// Dialog geschlossen: FREIGABE_GESCHLOSSEN an den Kernel, falls Claude gefragt hatte.
    func freigabeSchliessen()
    /// Fehlermeldung wegklicken.
    func freigabeFehlerVerwerfen()
}

/// Ein Vorschlag zur Anzeige im Dialog: Daten zur Vorschau und Link.
public struct FreigabeVorschlag: Identifiable, Equatable, Sendable {
    public struct Zeile: Equatable, Sendable {
        public var titel: String
        public var wert: String
    }

    public var id: String
    public var kind: String
    public var name: String
    /// „Rohr“, „Zukaufteil“, „Material“ …
    public var artTitel: String
    public var art: String
    public var ebene: CatalogLevel
    /// Claude hat ausdrücklich nach diesem Eintrag gefragt (oben, hervorgehoben).
    public var angefragt: Bool
    public var zeilen: [Zeile]
    public var link: URL?
    /// „vorgeschlagen am 22.10.2026“ (Datum aus `vorgeschlagen_am`).
    public var vorgeschlagenAm: String?

    public var eintrag: FreigabeEintrag { FreigabeEintrag(id: id, kind: kind, name: name) }
}

public enum FreigabeListe {
    /// Alle Vorschläge des Katalogs (Teile und Materialien), die angefragten zuerst in der Reihenfolge der Anfrage.
    public static func vorschlaege(_ catalog: Catalog?, angefragt: [String] = []) -> [FreigabeVorschlag] {
        guard let catalog else { return [] }
        var out: [FreigabeVorschlag] = []
        for item in catalog.items where item.vorgeschlagen {
            out.append(vorschlag(item, catalog: catalog, angefragt: angefragt.contains(item.id)))
        }
        for m in catalog.materials where m.vorgeschlagen {
            out.append(vorschlag(m, angefragt: angefragt.contains(m.id)))
        }
        return out.sorted { a, b in
            let ia = angefragt.firstIndex(of: a.id) ?? Int.max
            let ib = angefragt.firstIndex(of: b.id) ?? Int.max
            if ia != ib { return ia < ib }
            if a.kind != b.kind { return a.kind == "teil" }
            return a.name.localizedStandardCompare(b.name) == .orderedAscending
        }
    }

    /// „3 Vorschläge warten auf Freigabe“.
    public static func bandText(_ anzahl: Int) -> String {
        anzahl == 1 ? "1 Vorschlag wartet auf Freigabe" : "\(anzahl) Vorschläge warten auf Freigabe"
    }

    static func vorschlag(_ item: CatalogItem, catalog: Catalog, angefragt: Bool) -> FreigabeVorschlag {
        let e = item.entry
        var z: [FreigabeVorschlag.Zeile] = []
        func add(_ t: String, _ w: String?) {
            if let w, !w.isEmpty { z.append(.init(titel: t, wert: w)) }
        }
        add("Hersteller", [e["hersteller"]?.lenientString, e["modell"]?.lenientString].compactMap { $0 }
            .joined(separator: " "))
        add("Nummer", e["mpn"]?.lenientString ?? e["shop_nr"]?.lenientString)
        add("EAN", e["gtin"]?.lenientString)
        add("Norm", item.norm)
        add("Maße", masseText(e["masse"]))
        if !item.material.isEmpty {
            add("Material", catalog.material(item.material).map { "\($0.name) (\(item.material))" } ?? item.material)
        }
        add("Stangenlänge", e["stangenlaenge"]?.doubleValue.map { KevFormat.length($0) })
        if let p = e["platte"]?.doubles, p.count >= 2 { add("Plattenformat", BestandText.format(p[0], p[1])) }
        add("Gewicht", e["gewicht"]?.doubleValue.map { KevFormat.mass(grams: $0) })
        add("Preis", preisText(e["preis"]))
        add("Tags", item.tags.isEmpty ? nil : item.tags.joined(separator: ", "))
        let link = url(e["bezugsquelle"]?["url"]) ?? url(e["url"])
        return FreigabeVorschlag(
            id: item.id, kind: "teil", name: item.name, artTitel: CatalogSchema.art(item.art).title, art: item.art,
            ebene: item.ebene, angefragt: angefragt, zeilen: z, link: link,
            vorgeschlagenAm: e["vorgeschlagen_am"]?.lenientString.map { ZukaufDate.display($0) ?? $0 })
    }

    static func vorschlag(_ m: CatalogMaterial, angefragt: Bool) -> FreigabeVorschlag {
        let e = m.entry
        var z: [FreigabeVorschlag.Zeile] = []
        func add(_ t: String, _ w: String?) {
            if let w, !w.isEmpty { z.append(.init(titel: t, wert: w)) }
        }
        add("Gruppe", m.gruppe)
        add("Dichte", KevFormat.number(m.dichte, digits: 2) + " g/cm³")
        add("3D-Druck", m.druckbar ? "druckbar (Filament)" : nil)
        if let p = m.preisJeKg {
            let quelle = [e["preis_quelle"]?.lenientString, e["preis_stand"]?.lenientString].compactMap { $0 }
            add("Preis", KevFormat.euro(p) + "/kg" + (quelle.isEmpty ? "" : " (\(quelle.joined(separator: ", ")))"))
        }
        add("Farbe", m.farbe)
        add("Aliase", e["aliase"]?.stringList?.joined(separator: ", "))
        return FreigabeVorschlag(
            id: m.id, kind: "material", name: m.name, artTitel: "Material", art: "material", ebene: m.ebene,
            angefragt: angefragt, zeilen: z, link: url(e["bezugsquelle"]?["url"]),
            vorgeschlagenAm: e["vorgeschlagen_am"]?.lenientString.map { ZukaufDate.display($0) ?? $0 })
    }

    /// Maße als Text: „d 33,7 · s 2,6 mm“; Textfelder (Typ, Norm, Größe) wie angegeben.
    static func masseText(_ masse: JSONValue?) -> String? {
        guard let obj = masse?.objectValue, !obj.isEmpty else { return nil }
        var zahlen: [String] = []
        var texte: [String] = []
        for key in obj.keys.sorted() {
            guard let v = obj[key] else { continue }
            if let d = v.doubleValue, v.stringValue == nil {
                zahlen.append("\(key) \(KevFormat.compact(d, maxDigits: 2))")
            } else if let s = v.lenientString {
                texte.append(s)
            }
        }
        let z = zahlen.isEmpty ? nil : zahlen.joined(separator: " · ") + " mm"
        return ([z] + texte.map { Optional($0) }).compactMap { $0 }.joined(separator: " · ")
    }

    /// „14,50 €/m (Kevin, 2026-10)“.
    static func preisText(_ preis: JSONValue?) -> String? {
        guard let preis, let basis = Catalog.priceText(preis) else { return nil }
        let quelle = [preis["quelle"]?.lenientString, preis["stand"]?.lenientString].compactMap { $0 }
        let brutto = preis["brutto"]?.boolValue == true ? ", brutto" : ""
        return basis + (quelle.isEmpty && brutto.isEmpty ? "" : " (\(quelle.joined(separator: ", "))\(brutto))")
    }

    static func url(_ v: JSONValue?) -> URL? {
        guard let t = v?.stringValue?.trimmingCharacters(in: .whitespaces), !t.isEmpty, let u = URL(string: t),
            let scheme = u.scheme?.lowercased(), ["http", "https"].contains(scheme), u.host != nil
        else { return nil }
        return u
    }
}
