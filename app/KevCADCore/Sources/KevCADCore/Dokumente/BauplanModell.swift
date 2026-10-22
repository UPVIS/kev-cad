import CoreGraphics
import Foundation
import simd

// Bauplan (DOKUMENTE.md, Abschnitt „Bauplan“, Strang P6-A2): Inhalt von bauplan.json, wie er mit BAUPLAN ankommt.
// Alles wird nachsichtig gelesen: fehlende Felder haben Vorgaben, unbekannte bleiben in `json` erhalten.

/// Art eines Abschnitts. Unbekannte Arten bleiben als `.andere` mit ihrem Namen.
public enum BauplanAbschnittArt: Equatable, Hashable, Sendable {
    case material, zuschnitt, bearbeiten, drucken, montage
    case andere(String)

    public init(_ raw: String) {
        switch raw {
        case "material": self = .material
        case "zuschnitt": self = .zuschnitt
        case "bearbeiten": self = .bearbeiten
        case "drucken": self = .drucken
        case "montage": self = .montage
        default: self = .andere(raw)
        }
    }

    public var raw: String {
        switch self {
        case .material: return "material"
        case .zuschnitt: return "zuschnitt"
        case .bearbeiten: return "bearbeiten"
        case .drucken: return "drucken"
        case .montage: return "montage"
        case .andere(let s): return s
        }
    }

    /// SF-Symbol für Liste und Seitenkopf.
    public var symbol: String {
        switch self {
        case .material: return "shippingbox"
        case .zuschnitt: return "ruler"
        case .bearbeiten: return "wrench.and.screwdriver"
        case .drucken: return "printer.fill"
        case .montage: return "cube.transparent"
        case .andere: return "list.bullet"
        }
    }
}

public enum BauplanSchwere: String, Sendable, Comparable {
    case fehler, warnung, hinweis

    public init(_ raw: String?) { self = BauplanSchwere(rawValue: raw ?? "") ?? .hinweis }

    var rang: Int { self == .fehler ? 0 : self == .warnung ? 1 : 2 }
    public static func < (a: Self, b: Self) -> Bool { a.rang < b.rang }

    public var titel: String {
        switch self {
        case .fehler: return "Fehler"
        case .warnung: return "Warnung"
        case .hinweis: return "Hinweis"
        }
    }
}

/// Befund der Simulation an einem Schritt (gemeinsames Befundformat der Prüfung).
public struct BauplanBefund: Identifiable, Equatable, Sendable {
    public var id: String
    public var art: String
    public var teile: [String]
    public var schwere: BauplanSchwere
    public var text: String
    public var loesung: String?
    public var schritt: String?
    public var ort: SIMD3<Float>?

    public init(
        id: String, art: String, teile: [String] = [], schwere: BauplanSchwere, text: String, loesung: String? = nil,
        schritt: String? = nil, ort: SIMD3<Float>? = nil
    ) {
        self.id = id
        self.art = art
        self.teile = teile
        self.schwere = schwere
        self.text = text
        self.loesung = loesung
        self.schritt = schritt
        self.ort = ort
    }

    /// Lesbarer Name der Prüfart.
    public var artTitel: String {
        switch art {
        case "einfuehrweg": return "Einführweg"
        case "werkzeugzugang": return "Werkzeugzugang"
        case "standsicherheit": return "Standsicherheit"
        case "reihenfolge": return "Reihenfolge"
        case "verdeckt": return "Teil verdeckt"
        default: return art.prefix(1).uppercased() + art.dropFirst()
        }
    }
}

public struct BauplanVerbindungsmittel: Equatable, Sendable {
    public var id: String
    public var benennung: String
    public var laenge: Double?
    public var anzahl: Int
    /// Aus Kontakt geschätzt (Modell ohne `verbinde`).
    public var geschaetzt: Bool
}

public struct BauplanBohrung: Equatable, Sendable {
    public var teil: String
    public var durchmesser: Double?
    public var tiefe: Double?
    public var lage: [Double]
    public var von: String?
    public var senkung: String?
    public var gewinde: String?
    public var fuer: String?
    public var text: String?
    public var art: String?

    /// Lage als Text, z. B. "45 / 112,5 mm".
    public var lageText: String {
        lage.isEmpty ? "–" : lage.map { KevFormat.compact($0, maxDigits: 1) }.joined(separator: " / ") + " mm"
    }

    /// Bohrer bzw. Merkmal als Text, z. B. "Ø 6,6" oder "M6 (Kernloch Ø 5,0)".
    public var bohrerText: String {
        if let g = gewinde, !g.isEmpty {
            return g + (durchmesser.map { " (Kernloch Ø \(KevFormat.compact($0, maxDigits: 1)))" } ?? "")
        }
        if let d = durchmesser { return "Ø \(KevFormat.compact(d, maxDigits: 2))" }
        return text ?? "–"
    }
}

public struct BauplanZuschnittPosten: Equatable, Sendable {
    public var stockID: String
    public var laenge: Double
    public var gehrung: [Double]
    public var anzahl: Int
}

public struct BauplanDruck: Equatable, Sendable {
    public var teil: String
    public var material: String?
    public var seite: String?
    public var hoeheMM: Double?
    public var masseG: Double?
    public var hinweise: [String]
}

public struct BauplanMaterial: Equatable, Sendable {
    public var benennung: String
    public var menge: Double
    public var einheit: String
    public var preis: Double?
    public var quelle: String?
    public var hinweis: String?
}

/// Wie ein Teil oder eine Einheit eingebaut wird (aus der Montagefolge).
public struct BauplanEinbau: Equatable, Sendable {
    public var name: String
    public var art: String
    public var teile: [String]
    /// Fügerichtung (Welt), nil beim Grundteil.
    public var richtung: SIMD3<Float>?
    public var weg: Double
    public var aufbocken: Double
    public var grundteil: Bool
}

public struct BauplanPfeil: Equatable, Sendable {
    public var teil: String
    public var richtung: SIMD3<Float>
    public var von: SIMD3<Float>?
    public var nach: SIMD3<Float>?
}

/// Bildparameter eines Schritts: Kamera, Explosion, Pfeile, Hervorhebung.
public struct BauplanBildParameter: Equatable, Sendable {
    public var rotation: simd_quatf?
    public var pivot: SIMD3<Float>?
    public var distance: Float?
    public var ortho: Bool
    public var blick: SIMD3<Float>?
    public var oben: SIMD3<Float>?
    /// Versatz je Teil in der Explosion (Welt, mm).
    public var explosion: [String: SIMD3<Float>]
    public var pfeile: [BauplanPfeil]
    public var hervorheben: [String]
    public var kontext: [String]
    public var ausschnittMin: SIMD3<Float>?
    public var ausschnittMax: SIMD3<Float>?
    public var sichtbarkeit: [String: Double]
    public var quelle: String
}

/// Ein Schritt der Bauanleitung.
public struct BauplanSchritt: Identifiable, Equatable, Sendable {
    public var id: String
    public var titel: String
    public var text: String
    public var quelle: String
    public var fest: Bool
    public var verwaist: Bool
    public var teile: [String]
    public var neu: [String]
    public var baugruppe: String?
    /// Wiederholung (gleiche Teile): „4×“.
    public var anzahl: Int
    public var verbindungsmittel: [BauplanVerbindungsmittel]
    public var werkzeug: [String]
    public var bohrbild: [BauplanBohrung]
    public var zuschnitt: [BauplanZuschnittPosten]
    public var druck: BauplanDruck?
    public var material: [BauplanMaterial]
    public var bild: BauplanBildParameter?
    public var pruefung: [BauplanBefund]
    public var hinweise: [String]
    public var einbau: [BauplanEinbau]

    /// Schwerster Befund (nil = keiner).
    public var schwersterBefund: BauplanSchwere? { pruefung.map(\.schwere).min() }
    /// Fehler und Warnungen (ohne Hinweise).
    public var probleme: [BauplanBefund] { pruefung.filter { $0.schwere != .hinweis } }

    /// Hinweise, die der Sicherheit dienen (Schutzbrille, heiß, Klemmstelle …), zuerst gezeigt und gelb markiert.
    public var sicherheitsHinweise: [String] { hinweise.filter(BauplanText.istSicherheit) }
    public var uebrigeHinweise: [String] { hinweise.filter { !BauplanText.istSicherheit($0) } }

    /// Kurzname eines Teils (letzter Teil des Pfads), z. B. „Lenksperre (Druck)“.
    public static func kurzname(_ teil: String) -> String {
        teil.split(separator: "/").last.map(String.init) ?? teil
    }

    /// Neue Teile gruppiert nach Kurzname ohne laufende Nummern: [("Lenksperre (Druck)", 4), …], Verbindungsmittel
    /// ausgenommen (die stehen in `verbindungsmittel`).
    public var neueTeileGruppiert: [(name: String, anzahl: Int)] {
        let vmNamen = Set(einbau.filter { $0.art == "vm" }.flatMap(\.teile))
        var reihenfolge: [String] = []
        var zaehler: [String: Int] = [:]
        for t in neu where !vmNamen.contains(t) {
            let k = BauplanText.ohneNummer(Self.kurzname(t))
            if zaehler[k] == nil { reihenfolge.append(k) }
            zaehler[k, default: 0] += 1
        }
        return reihenfolge.map { ($0, zaehler[$0] ?? 1) }
    }
}

public struct BauplanAbschnitt: Identifiable, Equatable, Sendable {
    public var art: BauplanAbschnittArt
    public var titel: String
    public var schritte: [BauplanSchritt]
    /// Jemand hat Schritte verschoben: die Reihenfolge bleibt bei neuen Läufen.
    public var reihenfolgeFest: Bool

    public var id: String { art.raw }
}

/// Reihenfolge „a vor b“ (Schritt-id oder Teilname).
public struct BauplanReihenfolge: Identifiable, Equatable, Sendable {
    public var index: Int
    public var a: String
    public var b: String
    public var grund: String
    public var quelle: String
    public var id: Int { index }
}

public struct Bauplan: Equatable, Sendable {
    public var version: Int
    public var titel: String
    public var abschnitte: [BauplanAbschnitt]
    public var vorher: [BauplanReihenfolge]
    /// Lauf, aus dem der Plan stammt, und Rechenzeit.
    public var run: Int?
    public var gesamtMS: Double?
    /// Teile, die nicht im Aufbau vorkommen, mit Grund.
    public var nichtImAufbau: [(teil: String, grund: String)]
    /// Modell ohne `verbinde`: Verbindungen sind geschätzt.
    public var ohneVerbinde: Bool

    public static func == (a: Bauplan, b: Bauplan) -> Bool {
        a.version == b.version && a.titel == b.titel && a.abschnitte == b.abschnitte && a.vorher == b.vorher
            && a.run == b.run && a.nichtImAufbau.map(\.teil) == b.nichtImAufbau.map(\.teil)
            && a.ohneVerbinde == b.ohneVerbinde
    }

    public var alleSchritte: [BauplanSchritt] { abschnitte.flatMap(\.schritte) }

    public func schritt(_ id: String) -> BauplanSchritt? { alleSchritte.first { $0.id == id } }

    public func abschnitt(von id: String) -> BauplanAbschnitt? {
        abschnitte.first { $0.schritte.contains { $0.id == id } }
    }

    /// Laufende Nummer über alle Abschnitte (1 …), wie in der Anleitung gedruckt.
    public func nummer(_ id: String) -> Int? {
        alleSchritte.firstIndex { $0.id == id }.map { $0 + 1 }
    }

    public var befunde: [BauplanBefund] { alleSchritte.flatMap(\.pruefung) }
    public var fehlerAnzahl: Int { befunde.filter { $0.schwere == .fehler }.count }
    public var warnungAnzahl: Int { befunde.filter { $0.schwere == .warnung }.count }

    /// Alle Werkzeuge der Anleitung (ohne Doppel, Reihenfolge des ersten Auftretens) für die Werkzeugseite.
    public var alleWerkzeuge: [String] {
        var seen = Set<String>()
        return alleSchritte.flatMap(\.werkzeug).filter { seen.insert($0).inserted }
    }

    public var montage: BauplanAbschnitt? { abschnitte.first { $0.art == .montage } }
}

/// Strichbild eines Schritts im Feld 180 × 120 mm (Blatt-mm, Ursprung links unten, y nach oben).
public struct BauplanStrichbild: Equatable, Sendable {
    public var schritt: String
    public var rahmen: CGRect
    public var massstab: Double?
    /// Linienart → Polylinien (Punkte in Blatt-mm).
    public var linien: [String: [[CGPoint]]]
    public var fehler: String?

    public init(schritt: String, rahmen: CGRect, massstab: Double? = nil, linien: [String: [[CGPoint]]],
                fehler: String? = nil) {
        self.schritt = schritt
        self.rahmen = rahmen
        self.massstab = massstab
        self.linien = linien
        self.fehler = fehler
    }

    public var leer: Bool { linien.values.allSatisfy(\.isEmpty) }

    /// Begrenzung aller Linien (für das Einpassen in einen kleineren Rahmen).
    public var umriss: CGRect? {
        var r: CGRect?
        for pls in linien.values {
            for pl in pls {
                for p in pl {
                    let q = CGRect(x: p.x, y: p.y, width: 0, height: 0)
                    r = r.map { $0.union(q) } ?? q
                }
            }
        }
        return r
    }
}

// MARK: - Texte

public enum BauplanText {
    static let sicherheitsWorte = [
        "schutzbrille", "heiß", "heiss", "klemm", "quetsch", "scharf", "verletz", "handschuh", "gehörschutz",
        "vorsicht", "achtung", "nicht anfassen", "spannen", "zweite person", "zu zweit", "brand", "dämpfe",
    ]

    /// Ein Hinweis, der vor Verletzung oder Schaden warnt.
    public static func istSicherheit(_ text: String) -> Bool {
        let t = text.lowercased()
        return sicherheitsWorte.contains { t.contains($0) }
    }

    /// „Lenkrolle 3“ → „Lenkrolle“, „Schraube M6x16 1 vorn links“ bleibt (Nummer nicht am Ende).
    public static func ohneNummer(_ name: String) -> String {
        var teile = name.split(separator: " ").map(String.init)
        if teile.count > 1, let last = teile.last, Int(last) != nil { teile.removeLast() }
        return teile.joined(separator: " ")
    }

    /// Menge im Stil von LEGO und IKEA: „4×“.
    public static func menge(_ n: Int) -> String { "\(n)×" }
}

/// Werkzeuge mit Symbol (SF Symbols am Bildschirm; im PDF ein eigenes Piktogramm aus derselben Zuordnung).
public enum BauplanWerkzeug {
    public enum Art: String, Sendable, CaseIterable {
        case saege, bohrer, schluessel, innensechskant, schraubendreher, loetkolben, drucker, messen, entgrater,
            koerner, hand, spachtel, kleber, allgemein
    }

    public static func art(_ name: String) -> Art {
        let t = name.lowercased()
        if t.contains("säge") || t.contains("saege") { return .saege }
        if t.contains("bohrer") || t.contains("bohrmaschine") || t.contains("senker") { return .bohrer }
        if t.contains("innensechskant") || t.contains("inbus") || t.contains("torx") { return .innensechskant }
        if t.contains("schlüssel") || t.contains("ratsche") || t.contains("nuss") { return .schluessel }
        if t.contains("schraubendreher") || t.contains("bit") { return .schraubendreher }
        if t.contains("löt") || t.contains("einsatzspitze") { return .loetkolben }
        if t.contains("drucker") || t.contains("bambu") || t.contains("p1p") { return .drucker }
        if t.contains("maß") || t.contains("winkel") || t.contains("anschlag") || t.contains("messschieber") {
            return .messen
        }
        if t.contains("entgrat") || t.contains("feile") { return .entgrater }
        if t.contains("körner") || t.contains("anreiß") { return .koerner }
        if t.contains("hand") { return .hand }
        if t.contains("spachtel") || t.contains("platte") { return .spachtel }
        if t.contains("kleb") || t.contains("loctite") { return .kleber }
        return .allgemein
    }

    public static func symbol(_ name: String) -> String {
        switch art(name) {
        case .saege: return "scissors"
        case .bohrer: return "screwdriver"
        case .schluessel: return "wrench.adjustable"
        case .innensechskant: return "hexagon"
        case .schraubendreher: return "screwdriver.fill"
        case .loetkolben: return "flame"
        case .drucker: return "printer"
        case .messen: return "ruler"
        case .entgrater: return "wand.and.rays"
        case .koerner: return "smallcircle.filled.circle"
        case .hand: return "hand.raised"
        case .spachtel: return "rectangle.portrait"
        case .kleber: return "drop"
        case .allgemein: return "wrench.and.screwdriver"
        }
    }
}
