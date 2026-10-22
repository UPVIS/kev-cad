import Foundation

// Material (Strang „Material“, 22.10.2026): eine Datenquelle für alles, was Stückliste, Zuschnitt, Bestand,
// Einkaufsliste, Zukauf- und Druckteile zeigt: der Bereich „Material“, die Schnellansichten unter dem Viewport und die
// Berichte in „Dokumente“ lesen dieselben Positionen, Gruppen, Kennzeichen, Summen und Texte. Gebaut aus der Stückliste
// (BOM), ihrem Bestandsteil (BOM.cuts mit Quellen, Einkaufsliste, Stückgut), dem Projektbestand und dem Katalog. Rein
// lesend und ohne SwiftUI, damit die Summen überall gleich sind und sich testen lassen.

// MARK: - Gruppen und Kennzeichen

/// Gruppe einer Position in fester Reihenfolge (Tabellen, Schnellansicht, Bericht).
public enum MaterialGruppe: Int, CaseIterable, Comparable, Identifiable, Sendable {
    case stangen, platten, normteile, zukauf, druckteile, eigenteile, weitere

    public var id: Int { rawValue }

    public static func < (a: Self, b: Self) -> Bool { a.rawValue < b.rawValue }

    /// Gruppe nach der Art der Stücklistenzeile (Katalog-Art, `druckteil`, `zukaufteil`, `eigenteil`).
    public init(art: String) {
        switch art {
        case "schraube", "mutter", "scheibe": self = .normteile
        case "zukaufteil", "kamera", "objektiv", "kamerazubehoer": self = .zukauf
        case "druckteil": self = .druckteile
        case "eigenteil": self = .eigenteile
        default:
            let a = CatalogSchema.art(art)
            guard a.isKnown else {
                self = .weitere
                return
            }
            switch a.supply {
            case .bar: self = .stangen
            case .sheet: self = .platten
            case .piece: self = .normteile
            }
        }
    }

    public var titel: String {
        switch self {
        case .stangen: return "Stangen und Profile"
        case .platten: return "Platten"
        case .normteile: return "Normteile"
        case .zukauf: return "Zukaufteile"
        case .druckteile: return "Druckteile"
        case .eigenteile: return "Eigenteile"
        case .weitere: return "Weitere"
        }
    }

    /// SF-Symbol der Gruppe.
    public var symbol: String {
        switch self {
        case .stangen: return "line.diagonal"
        case .platten: return "square.fill"
        case .normteile: return "screwdriver"
        case .zukauf: return "cart"
        case .druckteile: return "printer.fill"
        case .eigenteile: return "hammer"
        case .weitere: return "shippingbox"
        }
    }
}

/// Kennzeichnung, überall gleich benannt und gefärbt: woher eine Position kommt (Zukauf, Druckteil, Eigenteil) bzw.
/// woher ihr Material kommt (Bestand, Rest, Kaufen), dazu die Zuschnittfarben für neue Reste und Verschnitt.
public enum MaterialKennzeichen: String, CaseIterable, Sendable {
    case kaufen, bestand, rest, zukauf, druckteil, eigenteil, restNeu, verschnitt

    public var titel: String {
        switch self {
        case .kaufen: return "Kaufen"
        case .bestand: return "Bestand"
        case .rest: return "Rest"
        case .zukauf: return "Zukauf"
        case .druckteil: return "Druckteil"
        case .eigenteil: return "Eigenteil"
        case .restNeu: return "Neuer Rest"
        case .verschnitt: return "Verschnitt"
        }
    }

    public var symbol: String {
        switch self {
        case .kaufen: return "cart"
        case .bestand: return "shippingbox"
        case .rest: return "arrow.3.trianglepath"
        case .zukauf: return "bag"
        case .druckteil: return "printer.fill"
        case .eigenteil: return "hammer"
        case .restNeu: return "plus.square.dashed"
        case .verschnitt: return "scissors"
        }
    }

    /// Erklärung für Hilfetexte.
    public var hilfe: String {
        switch self {
        case .kaufen: return "Muss gekauft werden (steht auf der Einkaufsliste)"
        case .bestand: return "Kommt aus dem Bestand des Projekts (ganze Stange, Platte oder Stückgut)"
        case .rest: return "Wird aus einem Rest im Bestand geschnitten"
        case .zukauf: return "Fertig gekauftes Teil mit Hersteller und Nummer"
        case .druckteil: return "3D-Druckteil: Masse aus Volumen × Dichte, Kosten aus dem Filamentpreis"
        case .eigenteil: return "Eigenteil: frei modelliert, Masse aus Volumen × Dichte"
        case .restNeu: return "Neuer Rest ab Mindestrest: kommt nach „Gebaut“ mit Kennung in den Bestand"
        case .verschnitt: return "Verschnitt: Sägeschnitte und Reste unter dem Mindestrest"
        }
    }

    /// sRGB 0…1; Bestand, Rest, Kaufen, neuer Rest und Verschnitt wie im Zuschnitt.
    public var rgb: (r: Double, g: Double, b: Double) {
        switch self {
        case .kaufen: return ZuschnittFarbe.kaufen.rgb
        case .bestand: return ZuschnittFarbe.bestand.rgb
        case .rest: return ZuschnittFarbe.rest.rgb
        case .restNeu: return ZuschnittFarbe.restNeu.rgb
        case .verschnitt: return ZuschnittFarbe.verschnitt.rgb
        case .zukauf: return (0.46, 0.36, 0.86)  // violett
        case .druckteil: return (0.10, 0.60, 0.62)  // petrol
        case .eigenteil: return (0.80, 0.45, 0.12)  // ocker
        }
    }

    public init(_ art: ZuschnittQuelleArt) {
        switch art {
        case .rest: self = .rest
        case .bestand: self = .bestand
        case .kaufen: self = .kaufen
        }
    }
}

// MARK: - Position

/// Eine Position der Stückliste, so wie sie überall erscheint.
public struct MaterialPosition: Identifiable, Equatable, Sendable {
    public var line: BOMLine
    public var gruppe: MaterialGruppe
    /// Zukauf, Druckteil oder Eigenteil (Lagerteile: nil).
    public var herkunft: MaterialKennzeichen?
    /// Woher das Material kommt: Bestand, Rest, Kaufen (leer ohne Bestandsangaben oder bei Zukauf-, Druck-, Eigenteilen).
    public var versorgung: [MaterialKennzeichen]
    /// Werkstoff als Anzeigename (Katalog, sonst Angabe der Stückliste).
    public var werkstoff: String?
    /// Link zur Bezugsquelle: Shop des Zukaufteils bzw. Bezugsquelle aus der Einkaufsliste.
    public var link: URL?

    public var id: Int { line.pos }
    public var pos: Int { line.pos }
    public var anzahl: Int { line.anzahl }
    public var kg: Double? { line.kg }
    public var preis: Double? { line.preis }
    public var teile: [String] { line.teile }
    public var stockID: String? { line.stockID }

    /// Alle Kennzeichen zum Anzeigen: Herkunft, sonst die Versorgung.
    public var kennzeichen: [MaterialKennzeichen] {
        if let herkunft { return [herkunft] }
        return versorgung
    }

    /// Teilpfad der Benennung, nur bei Druck- und Eigenteilen (sie heißen wie ihr Teil im Modell, „Halter/Lasche“);
    /// Katalognamen wie „Senkschraube 3/8"-16 UNC“ bleiben ganz.
    private var pfad: [String] {
        guard herkunft == .druckteil || herkunft == .eigenteil else { return [line.benennung] }
        let p = line.benennung.split(separator: "/").map(String.init)
        return p.isEmpty ? [line.benennung] : p
    }

    /// Name ohne Baugruppe.
    public var name: String { pfad.last ?? line.benennung }

    /// Zweite Zeile: Herstellernummer, Norm oder Baugruppe.
    public var unter: String? {
        if let mpn = line.zukauf?.mpn { return "Nr. \(mpn)" }
        if let norm = line.norm, !line.benennung.contains(norm) { return norm }
        let p = pfad
        return p.count > 1 ? p.dropLast().joined(separator: " / ") : nil
    }

    /// Maße wie auf der Sägeliste: Maßtext, bei Stangenware mit Länge („40 × 40 × 3, L = 882 mm“), ohne Gehrung.
    public var masseText: String { MaterialText.masse(line) }

    /// Gehrung („–“ für gerade Schnitte).
    public var gehrungText: String { KevFormat.gehrung(line.gehrung) }

    /// Herkunft als Text (Lager, Zukauf mit Hersteller, Druckteil, Eigenteil).
    public var herkunftText: String {
        switch herkunft {
        case .zukauf?: return line.zukauf?.hersteller ?? MaterialKennzeichen.zukauf.titel
        case let h?: return h.titel
        case nil: return "Lager"
        }
    }

    /// Kleinbuchstaben aller Texte für die Suche.
    public var suchtext: String {
        ([line.benennung, line.norm, werkstoff, line.material, line.masseText, line.stockID, line.zukauf?.hersteller,
          line.zukauf?.mpn, line.zukauf?.gtin, gruppe.titel, "\(line.pos)"] as [String?])
            .compactMap { $0 }.joined(separator: " ").lowercased() + " " + line.teile.joined(separator: " ").lowercased()
    }

    public func passt(_ suche: String) -> Bool {
        let woerter = suche.lowercased().split(whereSeparator: \.isWhitespace)
        guard !woerter.isEmpty else { return true }
        let text = suchtext
        return woerter.allSatisfy { text.contains($0) }
    }
}

// MARK: - Einkauf

/// Zeile der Einkaufsliste: Lagerware aus dem Abgleich mit dem Bestand (Kernel) oder ein Zukaufteil aus der Stückliste
/// (Zukaufteile führt der Bestand noch nicht, sie stehen immer auf der Liste).
public struct MaterialEinkauf: Identifiable, Equatable, Sendable {
    public enum Art: String, Sendable { case lager, zukauf }

    public var art: Art
    public var position: EinkaufsPosition
    /// Position der Stückliste (Zukaufteile).
    public var pos: Int?

    public var id: String { art.rawValue + ":" + position.id + ":" + position.einheit + (pos.map { ":\($0)" } ?? "") }

    /// Schlüssel zum Abhaken: ändert sich Menge oder Einheit, ist die Zeile wieder offen.
    public var abhakSchluessel: String { "\(art.rawValue)|\(position.id)|\(position.mengeText)|\(position.einheit)" }
}

/// Filament der Druckteile je Werkstoff (nur zur Information, Spulen führt der Bestand noch nicht): aus der
/// Druckvorschau desselben Laufs, sonst aus den Druckteilen der Stückliste (Volumen × Dichte). Der Kernel rechnet es
/// genauso (`kernel/src/kevcad_kernel/bestand/einkauf.py`).
public struct MaterialFilament: Identifiable, Equatable, Sendable {
    public var werkstoff: String
    public var teile: Int
    public var gramm: Double
    public var preis: Double?
    /// Material-id der Druckvorschau (aus der Stückliste: nil).
    public var material: String? = nil
    public var preisStand: String? = nil
    /// Stand der Druckvorschau (Schätzung, Bambu Studio); nil: aus der Stückliste.
    public var stand: DruckStand? = nil

    public var id: String { werkstoff }

    /// „Druckvorschau, Schätzung“ bzw. „Stückliste, Volumen × Dichte“.
    public var quelleText: String {
        stand.map { "Druckvorschau, \($0.titel)" } ?? "Stückliste, Volumen × Dichte"
    }

    /// Filament je Material aus der Druckvorschau, wenn sie zum Lauf der Stückliste gehört; sonst nil.
    public static func ausDruckvorschau(_ v: Druckvorschau?, run: Int) -> [MaterialFilament]? {
        guard let v, v.run == run, !v.summe.material.isEmpty else { return nil }
        return v.summe.material.map { m in
            MaterialFilament(
                werkstoff: m.name, teile: v.teile.filter { $0.material == m.material }.reduce(0) { $0 + $1.anzahl },
                gramm: m.g, preis: m.kosten, material: m.material, preisStand: m.preisStand, stand: m.stand)
        }
    }
}

// MARK: - Kennzahlen

/// Das Wichtigste auf einen Blick (Übersicht, Köpfe der Schnellansichten, Deckblatt, Seitenleisten).
public struct MaterialKennzahlen: Equatable, Sendable {
    public var teile = 0
    public var positionen = 0
    public var kg = 0.0
    /// Materialkosten aller Positionen (Richtpreise).
    public var preis: Double?
    public var preisHinweis: String?
    /// Einkaufsliste: Lagerware nach Abzug des Bestands und Zukaufteile.
    public var einkaufLager = 0
    public var einkaufLagerSumme: Double?
    public var einkaufZukauf = 0
    public var einkaufZukaufSumme: Double?
    public var einkaufOhnePreis = 0
    /// Der Kernel hat den Bestand abgeglichen (sonst ist die Einkaufsliste unbekannt).
    public var mitBestand = false
    /// Bestand des Projekts.
    public var lagerteileImBestand = 0
    public var resteImBestand = 0
    /// Zuschnitt.
    public var stangen = 0
    public var platten = 0
    public var neueReste = 0
    /// Verschnitt in Prozent der verplanten Länge (Stangen) bzw. Fläche (Platten), siehe `MaterialZuschnitt`.
    public var verschnittStangen: Double?
    public var verschnittPlatten: Double?
    /// Druck-, Zukauf- und Eigenteile.
    public var druckteile = 0
    public var druckGramm = 0.0
    public var druckPreis: Double?
    public var zukaufteile = 0
    public var wartetAufCAD = 0
    public var eigenteile = 0
    /// Vorschläge von Claude im Katalog, die auf Kevins Freigabe warten, und Teile außerhalb des Inventars.
    public var freigaben = 0
    public var inventarVerstoesse = 0
    public var hinweise = 0

    public init() {}

    /// Summe von Lagerware und Zukaufteilen (nil, wenn keine Position einen Preis hat).
    public var einkaufSumme: Double? {
        let s = [einkaufLagerSumme, einkaufZukaufSumme].compactMap { $0 }
        return s.isEmpty ? nil : s.reduce(0, +)
    }

    public var einkaufPositionen: Int { einkaufLager + einkaufZukauf }

    /// „≈ 312,40 €“ bzw. „–“.
    public var kostenText: String { preis.map { "≈ " + KevFormat.euro($0) } ?? "–" }

    public var einkaufText: String { einkaufSumme.map { "≈ " + KevFormat.euro($0) } ?? "–" }

    /// Verschnitt als Text: „6,2 %“, mit Stangen und Platten „6,2 % · 14,1 %“, sonst „–“.
    public var verschnittText: String {
        let werte = [verschnittStangen, verschnittPlatten].compactMap { $0 }
        guard !werte.isEmpty else { return "–" }
        return werte.map { KevFormat.number($0, digits: 1) + " %" }.joined(separator: " · ")
    }

    /// „4 Stangen · 1 Platte“ bzw. „kein Zuschnitt“.
    public var zuschnittText: String {
        var t: [String] = []
        if stangen > 0 { t.append(KevFormat.count(stangen, one: "Stange", many: "Stangen")) }
        if platten > 0 { t.append(KevFormat.count(platten, one: "Platte", many: "Platten")) }
        return t.isEmpty ? "kein Zuschnitt" : t.joined(separator: " · ")
    }
}

// MARK: - Zuschnitt

/// Verschnitt einheitlich gerechnet (Schnellansicht, Material, Bericht): was weder Teil noch verwertbarer Rest ist
/// (Sägeschnitte und Reste unter dem Mindestrest), bezogen auf die verplante Länge bzw. Fläche aller Quellen.
public enum MaterialZuschnitt {
    /// Kennung dieser Definition im Protokoll (`BOM.cuts[i].verschnitt_definition`, BESTAND.md): der Kernel rechnet
    /// `verschnitt_prozent` dann genauso (`bom.verschnitt_bilanz`).
    public static let definition = "2"

    public static let hilfe = "Verschnitt: Sägeschnitte und Reste unter dem Mindestrest, bezogen auf die verplante "
        + "Länge bzw. Fläche. Neue Reste zählen nicht dazu, sie kommen in den Bestand."

    /// Mindestrest eines Zuschnitts: Angabe des Kernels, sonst Projektbestand, sonst Standard.
    public static func mindestrest(_ z: BestandZuschnitt, bestand: Bestand?) -> Double {
        z.mindestrest ?? bestand?.mindestrest(z.stockID) ?? BestandEinstellungen.standard.mindestrestMM
    }

    /// Verplante Menge (mm bzw. mm²) und Verschnitt (dieselbe Einheit) eines Zuschnitts.
    public static func bilanz(_ z: BestandZuschnitt, mindestrest: Double) -> (gesamt: Double, verschnitt: Double) {
        var gesamt = 0.0
        var verschnitt = 0.0
        for q in z.quellen {
            if z.istPlatte || q.istPlatte {
                let b = q.b ?? z.platteB ?? 0, h = q.h ?? z.platteH ?? 0
                let a = b * h
                guard a > 0 else { continue }
                let stuecke = q.flaechen.reduce(0) { $0 + $1.b * $1.h }
                let reste = q.resteNeu.reduce(0) { $0 + $1.b * $1.h }
                gesamt += a
                verschnitt += max(0, a - stuecke - reste)
            } else {
                guard let l = q.laenge, l > 0 else { continue }
                let rest = q.restLaenge(saegeschnitt: z.saegeschnitt)
                let verwertbar = q.restIstVerschnitt(saegeschnitt: z.saegeschnitt, mindestrest: mindestrest) ? 0 : rest
                gesamt += l
                verschnitt += max(0, l - q.stuecke.reduce(0, +) - verwertbar)
            }
        }
        return (gesamt, verschnitt)
    }

    /// Verschnitt eines Zuschnitts in Prozent (nil ohne Quellen).
    public static func prozent(_ z: BestandZuschnitt, mindestrest: Double) -> Double? {
        let b = bilanz(z, mindestrest: mindestrest)
        guard b.gesamt > 0 else { return nil }
        return b.verschnitt / b.gesamt * 100
    }

    /// Zuschnitte mit Quellen und, falls der Kernel für ein Lagerteil keine Quellen schickt, der bisherige Zuschnitt
    /// der Stückliste (alle Stangen neu).
    public static func liste(bom: BillOfMaterials?, bestand: BOMBestand?) -> [BestandZuschnitt] {
        var out = bestand?.zuschnitte ?? []
        // Platten kommen nur aus dem Bestandsabgleich; ein Eintrag ohne Stangen ist dort kein Zuschnitt
        for cut in bom?.cuts ?? [] where !cut.stangen.isEmpty && !out.contains(where: { $0.stockID == cut.stockID }) {
            out.append(BestandZuschnitt(cut: cut))
        }
        return out
    }
}

// MARK: - Datenquelle

public struct MaterialDaten: Equatable, Sendable {
    /// Lauf der Stückliste (0 ohne Stückliste).
    public var run: Int
    public var positionen: [MaterialPosition]
    public var zuschnitte: [BestandZuschnitt]
    /// Mindestrest je Lagerteil (für Leisten und Verschnitt).
    public var mindestreste: [String: Double]
    public var stueckgut: [StueckgutBedarf]
    public var einkauf: [MaterialEinkauf]
    public var filament: [MaterialFilament]
    public var kennzahlen: MaterialKennzahlen
    public var warnungen: [String]
    /// Stand der Bestandsdatei, nach der Zuschnitt und Einkaufsliste gerechnet sind.
    public var bestandStand: String?
    /// Hinweis des Kernels zu den Preisen der Einkaufsliste.
    public var einkaufHinweis: String?
    /// Die Stückliste ist da (auch leer); ohne sie zeigt alles „Noch keine Stückliste“.
    public var hatStueckliste: Bool

    public static let leer = MaterialDaten(bom: nil)

    public init(
        bom: BillOfMaterials?, bestand: BOMBestand? = nil, projektBestand: Bestand? = nil, katalog: Catalog? = nil,
        wartetAufCAD: Int = 0, inventarVerstoesse: Int = 0, druckvorschau: Druckvorschau? = nil
    ) {
        run = bom?.run ?? 0
        hatStueckliste = bom != nil
        warnungen = bom?.warnings ?? []
        bestandStand = bestand?.bestandStand
        einkaufHinweis = bestand?.einkaufHinweis
        stueckgut = bestand?.stueckgut ?? []
        zuschnitte = MaterialZuschnitt.liste(bom: bom, bestand: bestand)
        var mindest: [String: Double] = [:]
        for z in zuschnitte { mindest[z.stockID] = MaterialZuschnitt.mindestrest(z, bestand: projektBestand) }
        mindestreste = mindest

        let lines = bom?.lines ?? []
        positionen = lines.map { line in
            Self.position(line, zuschnitt: bestand, stueckgut: bestand?.stueckgut ?? [], katalog: katalog)
        }

        // Einkauf: Lagerware aus dem Bestandsabgleich, dann Zukaufteile der Stückliste
        var einkauf = (bestand?.einkaufsliste ?? []).map { MaterialEinkauf(art: .lager, position: $0, pos: nil) }
        for p in positionen where p.herkunft == .zukauf {
            let z = p.line.zukauf
            let hinweis = [z?.title.isEmpty == false ? z?.title : nil, z?.gtin.map { "EAN \($0)" }]
                .compactMap { $0 }.joined(separator: " · ")
            einkauf.append(MaterialEinkauf(
                art: .zukauf,
                position: EinkaufsPosition(
                    id: p.stockID ?? "pos-\(p.pos)", benennung: p.line.benennung, menge: Double(p.anzahl),
                    einheit: "Stück", preisJe: p.line.preisJe, preis: p.line.preis, link: z?.url,
                    linkName: z?.url?.host?.replacingOccurrences(of: "www.", with: ""),
                    hinweis: hinweis.isEmpty ? nil : hinweis, stand: z?.preisStand),
                pos: p.pos))
        }
        self.einkauf = einkauf

        // Filament je Werkstoff: aus der Druckvorschau desselben Laufs, sonst aus den Druckteilen der Stückliste
        var filament: [String: MaterialFilament] = [:]
        var reihenfolge: [String] = []
        for p in positionen where p.herkunft == .druckteil {
            let w = p.werkstoff ?? "Filament"
            if filament[w] == nil {
                filament[w] = MaterialFilament(werkstoff: w, teile: 0, gramm: 0, preis: nil)
                reihenfolge.append(w)
            }
            filament[w]!.teile += p.anzahl
            filament[w]!.gramm += (p.kg ?? 0) * 1000
            if let preis = p.preis { filament[w]!.preis = (filament[w]!.preis ?? 0) + preis }
        }
        self.filament = MaterialFilament.ausDruckvorschau(druckvorschau, run: run) ?? reihenfolge.compactMap { filament[$0] }

        // Kennzahlen
        var k = MaterialKennzahlen()
        if let bom {
            k.teile = bom.totals.teile
            k.positionen = bom.totals.positionen
            k.kg = bom.totals.kg
            k.preis = bom.totals.preis
            k.preisHinweis = bom.totals.preisHinweis
        }
        k.mitBestand = bestand != nil
        let lager = einkauf.filter { $0.art == .lager }.map(\.position)
        let zukauf = einkauf.filter { $0.art == .zukauf }.map(\.position)
        k.einkaufLager = lager.count
        k.einkaufLagerSumme = bestand?.summe ?? Self.summe(lager)
        k.einkaufZukauf = zukauf.count
        k.einkaufZukaufSumme = Self.summe(zukauf)
        k.einkaufOhnePreis = einkauf.filter { $0.position.preis == nil }.count
        k.lagerteileImBestand = projektBestand?.posten.filter { !$0.leer }.count ?? 0
        k.resteImBestand = projektBestand?.posten.reduce(0) { $0 + $1.reste.count } ?? 0
        var stangenGesamt = 0.0, stangenVerschnitt = 0.0, plattenGesamt = 0.0, plattenVerschnitt = 0.0
        for z in zuschnitte {
            let b = MaterialZuschnitt.bilanz(z, mindestrest: mindest[z.stockID] ?? 100)
            if z.istPlatte {
                k.platten += z.quellen.count
                k.neueReste += z.neueResteFlaechen.count
                plattenGesamt += b.gesamt
                plattenVerschnitt += b.verschnitt
            } else {
                k.stangen += z.quellen.count
                k.neueReste += z.neueReste.count
                stangenGesamt += b.gesamt
                stangenVerschnitt += b.verschnitt
            }
        }
        k.verschnittStangen = stangenGesamt > 0 ? stangenVerschnitt / stangenGesamt * 100 : nil
        k.verschnittPlatten = plattenGesamt > 0 ? plattenVerschnitt / plattenGesamt * 100 : nil
        let druck = positionen.filter { $0.herkunft == .druckteil }
        k.druckteile = druck.reduce(0) { $0 + $1.anzahl }
        k.druckGramm = druck.compactMap(\.kg).reduce(0, +) * 1000
        k.druckPreis = Self.summe(druck.map(\.preis))
        k.zukaufteile = positionen.filter { $0.herkunft == .zukauf }.reduce(0) { $0 + $1.anzahl }
        k.eigenteile = positionen.filter { $0.herkunft == .eigenteil }.reduce(0) { $0 + $1.anzahl }
        k.wartetAufCAD = wartetAufCAD
        k.freigaben = katalog?.suggestionCount ?? 0
        k.inventarVerstoesse = inventarVerstoesse
        k.hinweise = warnungen.count
        kennzahlen = k
    }

    static func summe(_ liste: [EinkaufsPosition]) -> Double? { summe(liste.map(\.preis)) }

    static func summe(_ werte: [Double?]) -> Double? {
        let w = werte.compactMap { $0 }
        return w.isEmpty ? nil : w.reduce(0, +)
    }

    static func position(
        _ line: BOMLine, zuschnitt: BOMBestand?, stueckgut: [StueckgutBedarf], katalog: Catalog?
    ) -> MaterialPosition {
        let gruppe = MaterialGruppe(art: line.eigenteil ? "eigenteil" : line.art)
        var herkunft: MaterialKennzeichen?
        if line.eigenteil {
            herkunft = .eigenteil
        } else if line.druckteil {
            herkunft = .druckteil
        } else if line.zukauf != nil || gruppe == .zukauf {
            herkunft = .zukauf
        }
        var versorgung: [MaterialKennzeichen] = []
        if herkunft == nil, let z = zuschnitt, let sid = line.stockID {
            versorgung = Self.versorgung(line, stockID: sid, zuschnitt: z, stueckgut: stueckgut)
        }
        let werkstoff = line.material.map { m in katalog?.material(m)?.name ?? m }
        var link = line.zukauf?.url
        if link == nil, let sid = line.stockID {
            link = zuschnitt?.einkaufsliste.first { $0.id == sid && $0.link != nil }?.link
        }
        return MaterialPosition(
            line: line, gruppe: gruppe, herkunft: herkunft, versorgung: versorgung, werkstoff: werkstoff, link: link)
    }

    /// Woher das Material einer Lagerteil-Zeile kommt, in fester Reihenfolge Rest, Bestand, Kaufen.
    static func versorgung(
        _ line: BOMLine, stockID: String, zuschnitt: BOMBestand, stueckgut: [StueckgutBedarf]
    ) -> [MaterialKennzeichen] {
        var arten = Set<MaterialKennzeichen>()
        if let z = zuschnitt.zuschnitt(stockID) {
            if z.istPlatte {
                // Stücke dieser Zeile an ihren Maßen erkennen, sonst alle Quellen der Platte
                let treffer = z.quellen.filter { q in q.flaechen.contains { MaterialText.gleichesPlattenmass($0, line) } }
                for q in treffer.isEmpty ? z.quellen : treffer { arten.insert(MaterialKennzeichen(q.art)) }
            } else if let l = line.laenge {
                for q in z.quellen where q.stuecke.contains(where: { abs($0 - l) < 0.5 }) {
                    arten.insert(MaterialKennzeichen(q.art))
                }
                if arten.isEmpty { for q in z.quellen { arten.insert(MaterialKennzeichen(q.art)) } }
            }
            // Länger als die Stange: steht als Sonderlänge auf der Einkaufsliste
            if zuschnitt.einkaufsliste.contains(where: { $0.id == stockID && $0.einheit.hasPrefix("Sonderlänge") }) {
                arten.insert(.kaufen)
            }
        } else {
            let laenge = GebautVorschau.schraubenLaenge(line)
            let eigene = stueckgut.filter { $0.stockID == stockID }
            let passend = eigene.filter { BestandBearbeitung.gleicheLaenge($0.laenge, laenge) }
            for s in passend.isEmpty ? eigene : passend {
                if s.ausBestand > 0 { arten.insert(.bestand) }
                if s.kaufen > 0 { arten.insert(.kaufen) }
            }
            if eigene.isEmpty, zuschnitt.einkaufsliste.contains(where: { $0.id == stockID }) { arten.insert(.kaufen) }
        }
        return [MaterialKennzeichen.rest, .bestand, .kaufen].filter(arten.contains)
    }

    // MARK: Abfragen

    public func position(_ pos: Int) -> MaterialPosition? { positionen.first { $0.pos == pos } }

    /// Position, in der ein Teil steckt.
    public func position(enthaelt teil: String) -> MaterialPosition? { positionen.first { $0.teile.contains(teil) } }

    /// Positionen, in denen eines der Teile steckt.
    public func positionen(mit teile: Set<String>) -> Set<Int> {
        guard !teile.isEmpty else { return [] }
        return Set(positionen.filter { !teile.isDisjoint(with: $0.teile) }.map(\.pos))
    }

    public func positionen(in gruppe: MaterialGruppe) -> [MaterialPosition] { positionen.filter { $0.gruppe == gruppe } }

    /// Nach Gruppen in fester Reihenfolge, innen nach Position (oder wie `sortierung` vorgibt).
    public static func gruppiert(
        _ positionen: [MaterialPosition], sortierung: ((MaterialPosition, MaterialPosition) -> Bool)? = nil
    ) -> [(gruppe: MaterialGruppe, positionen: [MaterialPosition])] {
        let g = Dictionary(grouping: positionen, by: \.gruppe)
        return g.keys.sorted().map { key in
            (key, g[key]!.sorted(by: sortierung ?? { $0.pos < $1.pos }))
        }
    }

    public var gruppen: [(gruppe: MaterialGruppe, positionen: [MaterialPosition])] { Self.gruppiert(positionen) }

    /// Summen einer Auswahl von Positionen (Gruppenkopf, Fuß einer gefilterten Tabelle).
    public static func summen(_ liste: [MaterialPosition]) -> (teile: Int, kg: Double, preis: Double?) {
        (liste.reduce(0) { $0 + $1.anzahl }, liste.compactMap(\.kg).reduce(0, +), summe(liste.map(\.preis)))
    }

    public var lagerEinkauf: [MaterialEinkauf] { einkauf.filter { $0.art == .lager } }
    public var zukaufEinkauf: [MaterialEinkauf] { einkauf.filter { $0.art == .zukauf } }

    public func zuschnitt(_ stockID: String) -> BestandZuschnitt? { zuschnitte.first { $0.stockID == stockID } }

    public func mindestrest(_ stockID: String) -> Double {
        mindestreste[stockID] ?? BestandEinstellungen.standard.mindestrestMM
    }

    /// Verschnitt eines Zuschnitts in Prozent, einheitlich gerechnet.
    public func verschnitt(_ z: BestandZuschnitt) -> Double? {
        MaterialZuschnitt.prozent(z, mindestrest: mindestrest(z.stockID))
    }

    /// Stücklistenzeilen eines Lagerteils (für Zuschnitt und Bestand).
    public func lines(_ stockID: String) -> [BOMLine] { positionen.filter { $0.stockID == stockID }.map(\.line) }

    /// Herkunft eines Teils für die Teileliste: Lagerteil mit Länge, Zukauf, Druck- oder Eigenteil, außerhalb des
    /// Inventars. Druck- und Eigenteile erkennt die Stückliste (ohne sie gilt ein freies Teil als Druckteil).
    public func herkunft(_ p: PartNode) -> (titel: String, unter: String?) {
        if let s = p.stock {
            return (s.name, s.laenge.map { "L = " + KevFormat.length($0) })
        }
        if let z = p.zukauf { return ("Zukauf" + (z.hersteller.map { " · \($0)" } ?? ""), z.mpn) }
        if p.inventarFehlt { return ("nicht im Inventar", nil) }
        if let pos = position(enthaelt: p.id), pos.herkunft == .eigenteil {
            return (MaterialKennzeichen.eigenteil.titel, p.material)
        }
        return (MaterialKennzeichen.druckteil.titel, p.material)
    }
}

// MARK: - Texte

/// Gemeinsame Texte der Material-Ansichten und Berichte.
public enum MaterialText {
    /// Spaltentitel, überall gleich (Bildschirm und Druck).
    public enum Spalte {
        public static let pos = "Pos."
        public static let bild = "Bild"
        public static let benennung = "Benennung"
        public static let norm = "Norm"
        public static let werkstoff = "Werkstoff"
        public static let masse = "Maße"
        public static let gehrung = "Gehrung"
        public static let anzahl = "Anzahl"
        public static let gewicht = "Gewicht"
        public static let preisJe = "Preis je"
        public static let preis = "Preis"
        public static let herkunft = "Herkunft"
        public static let kennzeichen = "Quelle"
        public static let menge = "Menge"
        public static let einheit = "Einheit"
        public static let bezugsquelle = "Bezugsquelle"
        public static let hinweis = "Hinweis"
        public static let stand = "Stand"
        public static let lagerteil = "Lagerteil"
    }

    /// Maße einer Zeile wie auf der Sägeliste, ohne Gehrung.
    public static func masse(_ line: BOMLine) -> String {
        var t = line.masseText
        if let l = line.laenge {
            // Stangenware: der Maßtext ist meist schon die Länge
            let laenge = KevFormat.length(l)
            let zahl = KevFormat.compact(l, maxDigits: 1)
            if t.isEmpty {
                t = laenge
            } else if !t.contains(laenge) && !t.hasSuffix(" " + zahl) && !t.contains("× " + zahl) && t != zahl {
                t += ", L = " + laenge
            }
        }
        return t
    }

    /// Maße mit Gehrung (Druck, Text zum Kopieren).
    public static func masseMitGehrung(_ line: BOMLine) -> String {
        let g = KevFormat.gehrung(line.gehrung)
        return masse(line) + (g == "–" ? "" : ", Gehrung " + g)
    }

    /// Preisstand: „21.10.2026“ bzw. „10/2026“.
    public static func stand(_ text: String?) -> String? { ZukaufDate.display(text) }

    /// Preisstand aus dem Hinweis der Stückliste („Richtpreise, Stand 2026-10; Zukaufteile …“ → „10/2026“).
    public static func standAusHinweis(_ hinweis: String?) -> String? {
        guard let hinweis, let r = hinweis.range(of: "Stand ") else { return nil }
        let rest = hinweis[r.upperBound...]
        let ende = rest.firstIndex { ";, ".contains($0) } ?? rest.endIndex
        let roh = String(rest[..<ende])
        return roh.isEmpty ? nil : stand(roh)
    }

    /// Ein Plattenstück passt zu einer Zeile (gleiche Maße, auch gedreht).
    static func gleichesPlattenmass(_ f: ZuschnittFlaeche, _ line: BOMLine) -> Bool {
        let a = BestandText.format(f.b, f.h), b = BestandText.format(f.h, f.b)
        return line.masseText == a || line.masseText == b
            || line.masseText.replacingOccurrences(of: " mm", with: "") == a.replacingOccurrences(of: " mm", with: "")
            || line.masseText.replacingOccurrences(of: " mm", with: "") == b.replacingOccurrences(of: " mm", with: "")
    }

    /// Zeile der Stückliste als Text mit Tabulatoren (Numbers, Excel); Zukaufteile mit Hersteller, Nummer und Link.
    public static func zeile(_ p: MaterialPosition) -> String {
        var cells = [
            "\(p.pos)", p.line.benennung, p.masseText, p.gehrungText, p.werkstoff ?? "", "\(p.anzahl)",
            p.kg.map(KevFormat.kg) ?? "", p.preis.map(KevFormat.euro) ?? "",
        ]
        if let z = p.line.zukauf {
            cells += [z.hersteller ?? "", z.mpn ?? "", z.preisStand ?? "", z.url?.absoluteString ?? ""]
        }
        return cells.joined(separator: "\t")
    }

    /// Gruppen der Einkaufsliste in Text und CSV (gleich im Kernel, `bestand/einkauf.py`).
    public enum EinkaufGruppe {
        public static let lager = "Lagerware"
        public static let zukauf = "Zukaufteile"
        public static let normteile = "Normteile abzählen"
        public static let filament = "Filament für Druckteile"
    }

    /// Normteil zum Abzählen: Benennung, bei Schrauben ohne Länge im Namen dazu das Maß (wie „Normteile · abzählen“).
    public static func normteilName(_ s: StueckgutBedarf) -> String {
        s.benennung + (s.laenge != nil && !s.benennung.contains("Länge") ? " · \(s.masseText)" : "")
    }

    /// „16 gebraucht, 12 aus Bestand, 4 kaufen“.
    public static func normteilMengen(_ s: StueckgutBedarf) -> String {
        "\(KevFormat.integer(s.anzahl)) gebraucht, \(KevFormat.integer(s.ausBestand)) aus Bestand"
            + (s.kaufen > 0 ? ", \(KevFormat.integer(s.kaufen)) kaufen" : "")
    }

    /// Die ganze Einkaufsliste als Text (Lagerware, Zukaufteile, Summe, Normteile zum Abzählen, Filament): so teilt
    /// die App sie, und genau so liefert sie der Kernel über MCP `einkaufsliste()`.
    public static func einkaufText(
        _ d: MaterialDaten, projekt: String?, stand: String? = nil, abgehakt: Set<String> = []
    ) -> String {
        einkaufText(d.einkauf, projekt: projekt, stand: stand, abgehakt: abgehakt, normteile: d.stueckgut,
                    filament: d.filament)
    }

    /// Einkaufsliste als Text zum Weiterleiten: Lagerware und Zukaufteile mit Summe, abgehakte Zeilen als „erledigt“,
    /// darunter (falls übergeben) Normteile zum Abzählen und Filament; beides zählt nicht zur Summe.
    public static func einkaufText(
        _ zeilen: [MaterialEinkauf], projekt: String?, stand: String? = nil, abgehakt: Set<String> = [],
        normteile: [StueckgutBedarf] = [], filament: [MaterialFilament] = []
    ) -> String {
        var out = ["Einkaufsliste" + (projekt.map { " \($0)" } ?? "") + (stand.map { " (Stand \($0))" } ?? "")]
        if zeilen.isEmpty { out.append("Nichts zu kaufen, alles ist im Bestand.") }
        for (art, titel) in [(MaterialEinkauf.Art.lager, EinkaufGruppe.lager), (.zukauf, EinkaufGruppe.zukauf)] {
            let teil = zeilen.filter { $0.art == art }
            guard !teil.isEmpty else { continue }
            out.append("")
            out.append(titel)
            for z in teil {
                let p = z.position
                var zeile = (abgehakt.contains(z.abhakSchluessel) ? "- [x] " : "- [ ] ") + "\(p.mengeText) × \(p.einheit): \(p.benennung)"
                if let preis = p.preis { zeile += ", \(KevFormat.euro(preis))" }
                if let link = p.link { zeile += " (\(link.absoluteString))" }
                out.append(zeile)
                if let h = p.hinweis { out.append("  \(h)") }
            }
        }
        if let summe = MaterialDaten.summe(zeilen.map(\.position)) { out.append(""); out.append("Summe: ≈ \(KevFormat.euro(summe))") }
        if !normteile.isEmpty {
            out.append("")
            out.append(EinkaufGruppe.normteile)
            for s in normteile { out.append("- \(normteilName(s)): \(normteilMengen(s))") }
        }
        if !filament.isEmpty {
            out.append("")
            out.append(EinkaufGruppe.filament)
            for f in filament {
                var zeile = "- \(f.werkstoff): \(KevFormat.mass(grams: f.gramm)) für "
                    + KevFormat.count(f.teile, one: "Teil", many: "Teile")
                if let preis = f.preis { zeile += ", \(KevFormat.euro(preis))" }
                out.append(zeile + " (\(f.quelleText))")
            }
        }
        return out.joined(separator: "\n")
    }

    /// Die ganze Einkaufsliste als CSV (siehe `einkaufCSV(_:normteile:filament:)`), wie Kernel-Export und MCP.
    public static func einkaufCSV(_ d: MaterialDaten) -> String {
        einkaufCSV(d.einkauf, normteile: d.stueckgut, filament: d.filament)
    }

    /// Einkaufsliste als CSV, byteweise wie der Export des Kernels (EXPORT_REQ `einkaufsliste_csv`, MCP
    /// `einkaufsliste()`): Semikolon, deutsche Zahlen, CRLF, UTF-8 mit BOM. Spalte „Gruppe“ zuerst; nach Lagerware und
    /// Zukaufteilen die Summe, darunter Normteile zum Abzählen und Filament ohne Preis (sie zählen nicht zur Summe).
    public static func einkaufCSV(
        _ zeilen: [MaterialEinkauf], normteile: [StueckgutBedarf] = [], filament: [MaterialFilament] = []
    ) -> String {
        typealias F = EinkaufslisteFormat
        var out = ["Gruppe;Menge;Einheit;Benennung;Lagerteil;Preis je (EUR);Preis (EUR);Preisstand;Bezugsquelle;Link;Hinweis"]
        for z in zeilen {
            let p = z.position
            out.append([
                z.art == .lager ? EinkaufGruppe.lager : EinkaufGruppe.zukauf,
                KevFormat.compact(p.menge, maxDigits: 2).replacingOccurrences(of: ".", with: ""), p.einheit,
                p.benennung, p.id, F.zahl(p.preisJe), F.zahl(p.preis), p.stand ?? "", p.linkName ?? "",
                p.link?.absoluteString ?? "", p.hinweis ?? "",
            ].map(F.feld).joined(separator: ";"))
        }
        out.append(";;;Summe;;;\(F.zahl(MaterialDaten.summe(zeilen.map(\.position))));;;;")
        for s in normteile {
            out.append([
                EinkaufGruppe.normteile, KevFormat.integer(s.anzahl).replacingOccurrences(of: ".", with: ""), "Stück",
                normteilName(s), s.stockID, "", "", "", "", "", normteilMengen(s),
            ].map(F.feld).joined(separator: ";"))
        }
        for f in filament {
            let hinweis = KevFormat.count(f.teile, one: "Teil", many: "Teile") + (f.preis.map { ", " + KevFormat.euro($0) } ?? "")
            out.append([
                EinkaufGruppe.filament, KevFormat.compact(f.gramm, maxDigits: 1).replacingOccurrences(of: ".", with: ""),
                "g", f.werkstoff, f.material ?? "", "", "", f.preisStand ?? "", "", "", "\(hinweis) (\(f.quelleText))",
            ].map(F.feld).joined(separator: ";"))
        }
        return "\u{FEFF}" + out.joined(separator: "\r\n") + "\r\n"
    }
}

// MARK: - Abhaken

/// Abgehakte Zeilen der Einkaufsliste je Projekt (Oberflächenzustand, in den Einstellungen der App gemerkt).
public struct EinkaufAbgehakt: Equatable, Sendable {
    public var schluessel: Set<String>

    public init(_ schluessel: Set<String> = []) { self.schluessel = schluessel }

    public func abgehakt(_ z: MaterialEinkauf) -> Bool { schluessel.contains(z.abhakSchluessel) }

    public mutating func umschalten(_ z: MaterialEinkauf) {
        if schluessel.contains(z.abhakSchluessel) { schluessel.remove(z.abhakSchluessel) } else { schluessel.insert(z.abhakSchluessel) }
    }

    public mutating func setze(_ zeilen: [MaterialEinkauf], _ an: Bool) {
        for z in zeilen {
            if an { schluessel.insert(z.abhakSchluessel) } else { schluessel.remove(z.abhakSchluessel) }
        }
    }

    /// Nur Schlüssel behalten, die es in der Liste noch gibt (geänderte Mengen sind wieder offen).
    public func bereinigt(_ zeilen: [MaterialEinkauf]) -> EinkaufAbgehakt {
        EinkaufAbgehakt(schluessel.intersection(zeilen.map(\.abhakSchluessel)))
    }

    public func offen(_ zeilen: [MaterialEinkauf]) -> [MaterialEinkauf] { zeilen.filter { !abgehakt($0) } }

    /// Schlüssel in den Einstellungen der App.
    public static func defaultsKey(_ projekt: URL) -> String { "einkaufAbgehakt." + projekt.standardizedFileURL.path }
}

// MARK: - App-Modell

extension AppModel {
    /// Die gemeinsame Datenquelle aus dem aktuellen Stand (Stückliste, Bestand, Katalog, Zukauf, Inventar,
    /// Druckvorschau für das Filament).
    public var materialDaten: MaterialDaten {
        MaterialDaten(
            bom: bom, bestand: bestandZustand.zuschnitt, projektBestand: bestandZustand.bestand, katalog: catalog,
            wartetAufCAD: waitingForCAD.count, inventarVerstoesse: inventarVerstoesse.count,
            druckvorschau: druck.vorschau)
    }
}
