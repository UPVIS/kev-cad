import CoreGraphics
import Foundation

// Export-Dialog (DOKUMENTE.md, Anhang „Export“, Strang P6-A2): Bausteine, Spalten, Papier, Vorlagen in
// <projekt>/dokumente/vorlagen.json. Rein Daten, ohne Oberfläche, mit `swift test` prüfbar.

public enum ExportBausteinArt: String, CaseIterable, Codable, Sendable, Identifiable {
    case deckblatt, stueckliste, teileliste, einkaufsliste, zuschnitt, zeichnungen, bauplan

    public var id: String { rawValue }

    public var titel: String {
        switch self {
        case .deckblatt: return "Deckblatt"
        case .stueckliste: return "Stückliste"
        case .teileliste: return "Teileliste"
        case .einkaufsliste: return "Einkaufsliste"
        case .zuschnitt: return "Zuschnitt"
        case .zeichnungen: return "Zeichnungen"
        case .bauplan: return "Bauplan"
        }
    }

    public var beschreibung: String {
        switch self {
        case .deckblatt: return "Titel, Gesamtansicht, Kennzahlen und Inhalt"
        case .stueckliste: return "Positionen mit Bild, Maßen, Anzahl, Gewicht und Preis"
        case .teileliste: return "Jedes Teil einzeln mit Bild, Herkunft und Abmessungen"
        case .einkaufsliste: return "Was nach Abzug des Bestands zu kaufen ist, zum Abhaken"
        case .zuschnitt: return "Schnittpläne je Stange und Platte mit Resten"
        case .zeichnungen: return "Technische Zeichnungen im eigenen Blattformat"
        case .bauplan: return "Schritt für Schritt: Material, Zuschnitt, Bearbeiten, Drucken, Montage"
        }
    }

    public var symbol: String {
        switch self {
        case .deckblatt: return "doc.richtext"
        case .stueckliste: return "list.number"
        case .teileliste: return "square.grid.3x3"
        case .einkaufsliste: return "cart"
        case .zuschnitt: return "ruler"
        case .zeichnungen: return "pencil.and.ruler"
        case .bauplan: return "hammer"
        }
    }

    /// Spalten, die der Baustein kennt (leer = keine Tabelle mit wählbaren Spalten).
    public var spalten: [ExportSpalte] { ExportSpalte.alle(self) }

    public var standardSpalten: [String] { spalten.filter(\.standard).map(\.id) }
}

/// Eine Tabellenspalte: Kennung (wie in DOC_EXPORT_REQ), Titel, Breitenanteil, Ausrichtung.
public struct ExportSpalte: Identifiable, Equatable, Sendable {
    public enum Ausrichtung: Sendable { case links, rechts, mitte }

    public var id: String
    public var titel: String
    /// Mindestbreite in mm; übrige Breite verteilt sich nach `gewicht`.
    public var mindestbreite: CGFloat
    public var gewicht: CGFloat
    public var ausrichtung: Ausrichtung
    /// In der Vorgabe angekreuzt.
    public var standard: Bool

    public init(_ id: String, _ titel: String, mindest: CGFloat, gewicht: CGFloat = 0, _ a: Ausrichtung = .links,
                standard: Bool = true) {
        self.id = id
        self.titel = titel
        self.mindestbreite = mindest
        self.gewicht = gewicht
        self.ausrichtung = a
        self.standard = standard
    }

    public static func alle(_ art: ExportBausteinArt) -> [ExportSpalte] {
        switch art {
        case .stueckliste:
            return [
                ExportSpalte("pos", "Pos.", mindest: 11, .rechts),
                ExportSpalte("bild", "Bild", mindest: 16, .mitte),
                ExportSpalte("benennung", "Benennung", mindest: 40, gewicht: 3),
                ExportSpalte("norm", "Norm", mindest: 18, gewicht: 0.5, standard: false),
                ExportSpalte("material", "Werkstoff", mindest: 22, gewicht: 1),
                ExportSpalte("masse", "Maße", mindest: 24, gewicht: 1),
                ExportSpalte("anzahl", MaterialText.Spalte.anzahl, mindest: 13, .rechts),
                ExportSpalte("gewicht", "Gewicht", mindest: 16, .rechts),
                ExportSpalte("preis_je", "Preis je", mindest: 15, .rechts, standard: false),
                ExportSpalte("preis", "Preis", mindest: 15, .rechts),
                ExportSpalte("herkunft", "Herkunft", mindest: 18, standard: false),
            ]
        case .teileliste:
            return [
                ExportSpalte("nr", "Nr.", mindest: 11, .rechts),
                ExportSpalte("bild", "Bild", mindest: 16, .mitte),
                ExportSpalte("name", "Teil", mindest: 42, gewicht: 2),
                ExportSpalte("baugruppe", "Baugruppe", mindest: 24, gewicht: 1, standard: false),
                ExportSpalte("herkunft", "Herkunft", mindest: 34, gewicht: 2),
                ExportSpalte("material", "Werkstoff", mindest: 20, gewicht: 1),
                ExportSpalte("abmessungen", "Abmessungen", mindest: 30, gewicht: 1),
                ExportSpalte("gewicht", "Gewicht", mindest: 16, .rechts),
            ]
        case .einkaufsliste:
            return [
                ExportSpalte("abhaken", "", mindest: 7, .mitte),
                ExportSpalte("menge", "Menge", mindest: 15, .rechts),
                ExportSpalte("einheit", "Einheit", mindest: 26, gewicht: 0.6),
                ExportSpalte("benennung", "Benennung", mindest: 50, gewicht: 3),
                ExportSpalte("preis_je", "Preis je", mindest: 16, .rechts),
                ExportSpalte("preis", "Preis", mindest: 16, .rechts),
                ExportSpalte("bezugsquelle", "Bezugsquelle", mindest: 24, gewicht: 0.8),
                ExportSpalte("hinweis", "Hinweis", mindest: 24, gewicht: 1, standard: false),
            ]
        case .zuschnitt:
            return [
                ExportSpalte("stange", "Stange", mindest: 18),
                ExportSpalte("herkunft", "Herkunft", mindest: 32),
                ExportSpalte("stuecke", "Stücke", mindest: 50, gewicht: 3),
                ExportSpalte("rest", "Rest", mindest: 22, .rechts),
                ExportSpalte("verschnitt", "Verschnitt", mindest: 18, .rechts, standard: false),
            ]
        case .deckblatt, .zeichnungen, .bauplan:
            return []
        }
    }
}

public enum ExportPapier: String, CaseIterable, Codable, Sendable {
    case a4 = "A4", a3 = "A3"

    /// Hochformat in mm.
    public var hochMM: CGSize { self == .a4 ? CGSize(width: 210, height: 297) : CGSize(width: 297, height: 420) }
}

public enum ExportAusrichtung: String, CaseIterable, Codable, Sendable {
    case hoch, quer

    public var titel: String { self == .hoch ? "Hochformat" : "Querformat" }
}

/// Seitengröße in mm und als Name („A4 hoch“).
public struct ExportSeitenformat: Equatable, Hashable, Sendable {
    public var papier: ExportPapier
    public var ausrichtung: ExportAusrichtung

    public init(_ papier: ExportPapier = .a4, _ ausrichtung: ExportAusrichtung = .hoch) {
        self.papier = papier
        self.ausrichtung = ausrichtung
    }

    public var mm: CGSize {
        let h = papier.hochMM
        return ausrichtung == .hoch ? h : CGSize(width: h.height, height: h.width)
    }

    /// In Punkten (1/72 Zoll) für die PDF-MediaBox.
    public var punkte: CGSize { CGSize(width: mm.width * Self.ptJeMM, height: mm.height * Self.ptJeMM) }

    public var name: String { "\(papier.rawValue) \(ausrichtung.rawValue)" }

    public static let ptJeMM: CGFloat = 72 / 25.4

    /// Format zu einer Seitengröße in mm (A4/A3, hoch/quer), sonst nil.
    public static func passend(mm s: CGSize) -> ExportSeitenformat? {
        for p in ExportPapier.allCases {
            for a in ExportAusrichtung.allCases {
                let f = ExportSeitenformat(p, a)
                if abs(f.mm.width - s.width) < 1.5 && abs(f.mm.height - s.height) < 1.5 { return f }
            }
        }
        return nil
    }
}

/// Ein Baustein in der Vorlage: an oder aus, gewählte Spalten, Auswahl der Zeichnungen.
public struct ExportBausteinWahl: Codable, Equatable, Identifiable, Sendable {
    public var art: ExportBausteinArt
    public var an: Bool
    /// Spalten in dieser Reihenfolge; nil = Vorgabe.
    public var spalten: [String]?
    /// Nur Zeichnungen: Blatt-ids; nil = alle.
    public var auswahl: [String]?

    public var id: String { art.rawValue }

    public init(art: ExportBausteinArt, an: Bool = true, spalten: [String]? = nil, auswahl: [String]? = nil) {
        self.art = art
        self.an = an
        self.spalten = spalten
        self.auswahl = auswahl
    }

    /// Spalten, die tatsächlich gedruckt werden (unbekannte fallen weg, leer = Vorgabe).
    public var wirksameSpalten: [ExportSpalte] {
        let alle = art.spalten
        guard let s = spalten, !s.isEmpty else { return alle.filter(\.standard) }
        let gefunden = s.compactMap { id in alle.first { $0.id == id } }
        return gefunden.isEmpty ? alle.filter(\.standard) : gefunden
    }
}

public struct ExportVorlage: Codable, Equatable, Identifiable, Sendable {
    public var name: String
    public var format: ExportPapier
    public var ausrichtung: ExportAusrichtung
    public var bausteine: [ExportBausteinWahl]

    public var id: String { name }

    public init(name: String, format: ExportPapier = .a4, ausrichtung: ExportAusrichtung = .hoch,
                bausteine: [ExportBausteinWahl]) {
        self.name = name
        self.format = format
        self.ausrichtung = ausrichtung
        self.bausteine = bausteine
    }

    /// Alles in der Standardreihenfolge.
    public static var standard: ExportVorlage {
        ExportVorlage(name: "Alles", bausteine: ExportBausteinArt.allCases.map { ExportBausteinWahl(art: $0) })
    }

    /// Ergänzt fehlende Bausteine (aus), damit jede Vorlage alle Bausteine kennt.
    public var vollstaendig: ExportVorlage {
        var v = self
        var seen = Set<ExportBausteinArt>()
        v.bausteine = v.bausteine.filter { seen.insert($0.art).inserted }
        for a in ExportBausteinArt.allCases where !seen.contains(a) {
            v.bausteine.append(ExportBausteinWahl(art: a, an: false))
        }
        return v
    }

    public var aktive: [ExportBausteinWahl] { bausteine.filter(\.an) }

    public var seitenformat: ExportSeitenformat { ExportSeitenformat(format, ausrichtung) }

    enum CodingKeys: String, CodingKey { case name, format, ausrichtung, bausteine }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? "Vorlage"
        format = (try? c.decode(ExportPapier.self, forKey: .format)) ?? .a4
        ausrichtung = (try? c.decode(ExportAusrichtung.self, forKey: .ausrichtung)) ?? .hoch
        // unbekannte Bausteinarten (neuere App) überspringen statt die ganze Vorlage zu verwerfen
        let roh = (try? c.decode([JSONValue].self, forKey: .bausteine)) ?? []
        bausteine = roh.compactMap { j in
            guard let art = j["art"]?.stringValue.flatMap(ExportBausteinArt.init(rawValue:)) else { return nil }
            return ExportBausteinWahl(
                art: art, an: j["an"]?.boolValue ?? true, spalten: j["spalten"]?.stringList,
                auswahl: j["auswahl"]?.stringList)
        }
    }
}

/// Inhalt von <projekt>/dokumente/vorlagen.json.
public struct ExportVorlagenDatei: Codable, Equatable, Sendable {
    public var version: Int
    public var zuletzt: String?
    public var vorlagen: [ExportVorlage]

    public init(version: Int = 1, zuletzt: String? = nil, vorlagen: [ExportVorlage] = []) {
        self.version = version
        self.zuletzt = zuletzt
        self.vorlagen = vorlagen
    }

    public static func url(projekt: URL) -> URL {
        projekt.appendingPathComponent("dokumente", isDirectory: true).appendingPathComponent("vorlagen.json")
    }

    /// Liest die Datei; fehlt sie oder ist sie kaputt, gibt es eine leere Liste (und bei kaputter Datei den Fehler).
    public static func laden(projekt: URL) -> (ExportVorlagenDatei, String?) {
        let u = url(projekt: projekt)
        guard let data = try? Data(contentsOf: u) else { return (ExportVorlagenDatei(), nil) }
        do {
            var d = try JSONDecoder().decode(ExportVorlagenDatei.self, from: data)
            d.vorlagen = d.vorlagen.map(\.vollstaendig)
            return (d, nil)
        } catch {
            return (ExportVorlagenDatei(), "vorlagen.json nicht lesbar: \(error.localizedDescription)")
        }
    }

    /// Schreibt atomar (lesbar eingerückt, Schlüssel sortiert, damit Versionen kleine Unterschiede zeigen).
    public func speichern(projekt: URL) throws {
        let u = Self.url(projekt: projekt)
        try FileManager.default.createDirectory(at: u.deletingLastPathComponent(), withIntermediateDirectories: true)
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try enc.encode(self).write(to: u, options: .atomic)
    }

    public func vorlage(_ name: String) -> ExportVorlage? {
        vorlagen.first { $0.name.caseInsensitiveCompare(name) == .orderedSame }
    }

    /// Fügt eine Vorlage hinzu oder ersetzt die gleichnamige und merkt sie als zuletzt benutzt.
    public mutating func setze(_ v: ExportVorlage) {
        if let i = vorlagen.firstIndex(where: { $0.name.caseInsensitiveCompare(v.name) == .orderedSame }) {
            vorlagen[i] = v
        } else {
            vorlagen.append(v)
        }
        zuletzt = v.name
    }

    public mutating func entferne(_ name: String) {
        vorlagen.removeAll { $0.name.caseInsensitiveCompare(name) == .orderedSame }
        if zuletzt?.caseInsensitiveCompare(name) == .orderedSame { zuletzt = nil }
    }
}

// MARK: - Anfrage des Kernels (DOC_EXPORT_REQ) und Antwort

/// DOC_EXPORT_REQ: welche Bausteine wohin (oder drucken).
public struct DokumentExportAnfrage: Sendable {
    public var id: String
    public var bausteine: [ExportBausteinWahl]
    public var ziel: URL?
    public var drucken: Bool
    public var format: ExportPapier?
    public var ausrichtung: ExportAusrichtung?
    public var vorlage: String?

    public static func decode(_ frame: Frame) throws -> DokumentExportAnfrage {
        let j = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        let bausteine: [ExportBausteinWahl] = (j["bausteine"]?.arrayValue ?? []).compactMap { b in
            guard let art = (b["art"]?.stringValue ?? b.stringValue).flatMap(ExportBausteinArt.init(rawValue:))
            else { return nil }
            return ExportBausteinWahl(art: art, an: true, spalten: b["spalten"]?.stringList,
                                      auswahl: b["auswahl"]?.stringList)
        }
        return DokumentExportAnfrage(
            id: j["id"]?.stringValue ?? "", bausteine: bausteine,
            ziel: j["ziel"]?.stringValue.flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) },
            drucken: j["drucken"]?.boolValue ?? false,
            format: j["format"]?.stringValue.flatMap { ExportPapier(rawValue: $0.uppercased()) },
            ausrichtung: j["ausrichtung"]?.stringValue.flatMap { ExportAusrichtung(rawValue: $0.lowercased()) },
            vorlage: j["vorlage"]?.stringValue)
    }

    /// Die Vorlage, nach der gebaut wird: Bausteine der Anfrage, sonst die der genannten Vorlage, sonst alles.
    public func vorlage(aus datei: ExportVorlagenDatei) -> (ExportVorlage, [String]) {
        var hinweise: [String] = []
        var basis = ExportVorlage.standard
        if let name = vorlage {
            if let v = datei.vorlage(name) {
                basis = v
            } else {
                hinweise.append("Vorlage „\(name)“ gibt es nicht, es gilt die Vorgabe")
            }
        }
        if !bausteine.isEmpty {
            // Spalten aus der Vorlage übernehmen, wenn die Anfrage keine nennt
            basis.bausteine = bausteine.map { b in
                var w = b
                if w.spalten == nil { w.spalten = basis.bausteine.first { $0.art == b.art }?.spalten }
                return w
            }
        }
        if let f = format { basis.format = f }
        if let a = ausrichtung { basis.ausrichtung = a }
        return (basis, hinweise)
    }
}

/// Ergebnis eines Exports (für DOC_EXPORT_RES, die Oberfläche und Messungen).
public struct ExportErgebnis: Equatable, Sendable {
    public var pfad: URL?
    public var seiten: Int
    public var bausteine: [(art: ExportBausteinArt, seiten: Int)]
    public var formate: [String: Int]
    public var hinweise: [String]
    public var ms: Int
    public var gedruckt: String?
    /// Dauer je Phase in ms (bauplan_ms, blaetter_ms, bilder_ms, seiten_ms, pdf_ms).
    public var phasen: [String: Int]

    public init(pfad: URL?, seiten: Int, bausteine: [(art: ExportBausteinArt, seiten: Int)], formate: [String: Int],
                hinweise: [String], ms: Int, gedruckt: String? = nil, phasen: [String: Int] = [:]) {
        self.phasen = phasen
        self.pfad = pfad
        self.seiten = seiten
        self.bausteine = bausteine
        self.formate = formate
        self.hinweise = hinweise
        self.ms = ms
        self.gedruckt = gedruckt
    }

    public static func == (a: ExportErgebnis, b: ExportErgebnis) -> Bool {
        a.pfad == b.pfad && a.seiten == b.seiten && a.formate == b.formate && a.hinweise == b.hinweise
            && a.bausteine.map(\.art) == b.bausteine.map(\.art) && a.bausteine.map(\.seiten) == b.bausteine.map(\.seiten)
            && a.ms == b.ms && a.gedruckt == b.gedruckt
    }

    /// Mehr als ein Papierformat: der Druck braucht je Format einen eigenen Auftrag.
    public var gemischteFormate: Bool { formate.count > 1 }
}

public struct DokumentExportAntwortMessage: OutgoingMessage {
    public static let type = "DOC_EXPORT_RES"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var pfad: String?
    public var seiten: Int
    public var fehler: String?
    public var bausteine: [[String: JSONValue]]
    public var formate: [String: Int]
    public var gedruckt: String?
    public var hinweise: [String]
    public var ms: Int
    public var phasen: [String: Int]

    public init(replyTo: String, ergebnis: ExportErgebnis) {
        phasen = ergebnis.phasen
        self.replyTo = replyTo
        ok = true
        pfad = ergebnis.pfad?.path
        seiten = ergebnis.seiten
        fehler = nil
        bausteine = ergebnis.bausteine.map { ["art": .string($0.art.rawValue), "seiten": .number(Double($0.seiten))] }
        formate = ergebnis.formate
        gedruckt = ergebnis.gedruckt
        hinweise = ergebnis.hinweise
        ms = ergebnis.ms
    }

    public init(replyTo: String, fehler: String) {
        self.replyTo = replyTo
        ok = false
        pfad = nil
        seiten = 0
        self.fehler = fehler
        bausteine = []
        formate = [:]
        gedruckt = nil
        hinweise = []
        ms = 0
        phasen = [:]
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, pfad, seiten, fehler, bausteine, formate, gedruckt, hinweise, ms, phasen
        case replyTo = "reply_to"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        if let pfad { try c.encode(pfad, forKey: .pfad) } else { try c.encodeNil(forKey: .pfad) }
        try c.encode(seiten, forKey: .seiten)
        if let fehler { try c.encode(fehler, forKey: .fehler) } else { try c.encodeNil(forKey: .fehler) }
        try c.encode(bausteine, forKey: .bausteine)
        try c.encode(formate, forKey: .formate)
        if let gedruckt { try c.encode(gedruckt, forKey: .gedruckt) } else { try c.encodeNil(forKey: .gedruckt) }
        try c.encode(hinweise, forKey: .hinweise)
        try c.encode(ms, forKey: .ms)
        try c.encode(phasen, forKey: .phasen)
    }
}
