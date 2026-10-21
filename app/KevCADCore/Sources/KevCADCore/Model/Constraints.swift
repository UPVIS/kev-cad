import Foundation
import simd

// Zwangsbedingungen (PLAN-BEDINGUNGEN.md, PROTOCOL.md Abschnitt „Zwangsbedingungen“): der Bericht des Kernels nach
// jedem Lauf. Die Oberfläche liest ihn aus AppModel.constraints; Symbole am Teil zeichnet der App-Kern in die
// Überlagerung des Viewports (ausblendbar über ConstraintActions).

/// Stand einer Bedingung.
public enum ConstraintState: String, Sendable, Equatable {
    case erfuellt, verletzt, ungeprueft
}

/// Schwere eines Befunds (gemeinsames Befundformat der Prüfungen).
public enum FindingSeverity: String, Sendable, Equatable, Comparable {
    case fehler, warnung, hinweis

    private var rank: Int {
        switch self {
        case .fehler: return 0
        case .warnung: return 1
        case .hinweis: return 2
        }
    }

    public static func < (a: FindingSeverity, b: FindingSeverity) -> Bool { a.rank < b.rank }
}

/// Eine Bedingung (Montage, Gelenk, Maß, Befestigung) mit Stand und Anzeigepunkten.
public struct ConstraintItem: Identifiable, Equatable, Sendable {
    public var id: String
    /// `auf`, `konzentrisch`, `drehgelenk`, `verbinde`, `param` …
    public var art: String
    /// `montage` | `gelenk` | `mass` | `befestigung`
    public var gruppe: String
    public var symbol: String
    public var text: String
    public var teile: [String]
    public var stand: ConstraintState
    public var schwere: FindingSeverity?
    public var soll: String
    public var ist: String
    public var abweichung: Double?
    public var einheit: String
    /// Anzeigepunkte (Welt, mm): der erste am Teil, das sich anpasst, der zweite am Gegenstück.
    public var punkte: [SIMD3<Float>]
    public var zeile: Int?
    public var datei: String?
    public var loesung: String?
    public var hinweis: String?
    /// Gelenke: Achse in der gezeigten Lage, Wert und Bereich.
    public var achse: (punkt: SIMD3<Float>, richtung: SIMD3<Float>)?
    public var wert: Double?
    public var wertEinheit: String?
    public var bereich: [Double]?

    public init(
        id: String, art: String, gruppe: String = "montage", symbol: String? = nil, text: String,
        teile: [String] = [], stand: ConstraintState, schwere: FindingSeverity? = nil, soll: String = "",
        ist: String = "", abweichung: Double? = nil, einheit: String = "mm", punkte: [SIMD3<Float>] = [],
        zeile: Int? = nil, datei: String? = nil, loesung: String? = nil, hinweis: String? = nil
    ) {
        self.id = id
        self.art = art
        self.gruppe = gruppe
        self.symbol = symbol ?? art
        self.text = text
        self.teile = teile
        self.stand = stand
        self.schwere = schwere
        self.soll = soll
        self.ist = ist
        self.abweichung = abweichung
        self.einheit = einheit
        self.punkte = punkte
        self.zeile = zeile
        self.datei = datei
        self.loesung = loesung
        self.hinweis = hinweis
    }

    public static func == (a: ConstraintItem, b: ConstraintItem) -> Bool {
        a.id == b.id && a.art == b.art && a.text == b.text && a.teile == b.teile && a.stand == b.stand
            && a.schwere == b.schwere && a.soll == b.soll && a.ist == b.ist && a.punkte == b.punkte
            && a.zeile == b.zeile && a.loesung == b.loesung && a.wert == b.wert && a.bereich == b.bereich
    }

    /// Verletzt mit Schwere „fehler“ (sperrt den Export).
    public var isError: Bool { stand == .verletzt && (schwere ?? .fehler) == .fehler }
}

/// Eine freie Bewegung eines Teils (Freiheitsgrad).
public struct ConstraintFreedom: Equatable, Sendable {
    public var art: String  // drehung | verschiebung
    public var text: String
    public var gelenk: Bool
    public var unkritisch: Bool

    public init(art: String, text: String, gelenk: Bool = false, unkritisch: Bool = false) {
        self.art = art
        self.text = text
        self.gelenk = gelenk
        self.unkritisch = unkritisch
    }
}

/// Ein Teil mit Bedingungen: Freiheitsgrade und Befestigung.
public struct ConstraintPart: Identifiable, Equatable, Sendable {
    public var name: String
    public var platziert: Bool
    /// Freie Freiheitsgrade ohne Gelenke und ohne unkritische Drehung runder Verbindungen.
    public var frei: Int
    /// `bestimmt` | `unterbestimmt` | `widerspruch` | `bezug`
    public var stand: String
    public var bedingungen: [String]
    public var freiheitsgrade: [ConstraintFreedom]
    public var gelenke: [String]
    public var befestigt: Bool?
    public var amBoden: Bool?
    public var verbindungen: [String]
    public var verletzt: Int

    public var id: String { name }

    public init(
        name: String, platziert: Bool = false, frei: Int = 0, stand: String = "bezug", bedingungen: [String] = [],
        freiheitsgrade: [ConstraintFreedom] = [], gelenke: [String] = [], befestigt: Bool? = nil,
        amBoden: Bool? = nil, verbindungen: [String] = [], verletzt: Int = 0
    ) {
        self.name = name
        self.platziert = platziert
        self.frei = frei
        self.stand = stand
        self.bedingungen = bedingungen
        self.freiheitsgrade = freiheitsgrade
        self.gelenke = gelenke
        self.befestigt = befestigt
        self.amBoden = amBoden
        self.verbindungen = verbindungen
        self.verletzt = verletzt
    }
}

/// Ein Befund im gemeinsamen Format der Prüfungen (`art: "bedingung"`).
public struct ConstraintFinding: Identifiable, Equatable, Sendable {
    public var id: Int
    /// `bedingung` | `parameter` | `widerspruch` | `freiheitsgrade` | `bewegungsraum` | `befestigung`
    public var pruefung: String
    public var teile: [String]
    public var schwere: FindingSeverity
    public var text: String
    public var soll: String
    public var ist: String
    public var ort: SIMD3<Float>?
    public var loesung: String?
    public var bedingung: String?
    public var zeile: Int?

    public init(
        id: Int, pruefung: String, teile: [String] = [], schwere: FindingSeverity, text: String, soll: String = "",
        ist: String = "", ort: SIMD3<Float>? = nil, loesung: String? = nil, bedingung: String? = nil, zeile: Int? = nil
    ) {
        self.id = id
        self.pruefung = pruefung
        self.teile = teile
        self.schwere = schwere
        self.text = text
        self.soll = soll
        self.ist = ist
        self.ort = ort
        self.loesung = loesung
        self.bedingung = bedingung
        self.zeile = zeile
    }
}

/// Bewegungsraum eines Gelenks (B8): freier Bereich und blockierende Teile.
public struct MotionRange: Identifiable, Equatable, Sendable {
    public var name: String
    public var art: String  // drehen | schieben
    public var teile: [String]
    public var von: Double
    public var bis: Double
    public var frei: [[Double]]
    public var blockiertDurch: [String]
    public var teilweise: Bool

    public var id: String { name }

    public init(
        name: String, art: String, teile: [String] = [], von: Double, bis: Double, frei: [[Double]] = [],
        blockiertDurch: [String] = [], teilweise: Bool = false
    ) {
        self.name = name
        self.art = art
        self.teile = teile
        self.von = von
        self.bis = bis
        self.frei = frei
        self.blockiertDurch = blockiertDurch
        self.teilweise = teilweise
    }
}

public struct ConstraintSummary: Equatable, Sendable {
    public var gesamt: Int
    public var erfuellt: Int
    public var verletzt: Int
    public var ungeprueft: Int
    public var fehler: Int
    public var warnungen: Int
    public var hinweise: Int

    public init(
        gesamt: Int = 0, erfuellt: Int = 0, verletzt: Int = 0, ungeprueft: Int = 0, fehler: Int = 0,
        warnungen: Int = 0, hinweise: Int = 0
    ) {
        self.gesamt = gesamt
        self.erfuellt = erfuellt
        self.verletzt = verletzt
        self.ungeprueft = ungeprueft
        self.fehler = fehler
        self.warnungen = warnungen
        self.hinweise = hinweise
    }
}

/// Bericht der Bedingungen eines Laufs (Nachricht CONSTRAINTS).
public struct ConstraintReport: Equatable, Sendable {
    public var run: Int
    public var items: [ConstraintItem]
    public var parts: [ConstraintPart]
    public var findings: [ConstraintFinding]
    public var motions: [MotionRange]
    public var summary: ConstraintSummary
    public var pruefMs: Double?
    public var loeseMs: Double?

    public init(
        run: Int, items: [ConstraintItem] = [], parts: [ConstraintPart] = [], findings: [ConstraintFinding] = [],
        motions: [MotionRange] = [], summary: ConstraintSummary = ConstraintSummary(), pruefMs: Double? = nil,
        loeseMs: Double? = nil
    ) {
        self.run = run
        self.items = items
        self.parts = parts
        self.findings = findings
        self.motions = motions
        self.summary = summary
        self.pruefMs = pruefMs
        self.loeseMs = loeseMs
    }

    /// Bedingungen, an denen ein Teil (oder eine Baugruppe mit diesem Präfix) beteiligt ist.
    public func items(for partID: String) -> [ConstraintItem] {
        items.filter { $0.teile.contains { $0 == partID || $0.hasPrefix(partID + "/") } }
    }

    public func part(_ name: String) -> ConstraintPart? { parts.first { $0.name == name } }

    /// Teile mit verletzten Bedingungen oder Fehler-Befunden (für Markierungen im Teilebaum).
    public var partsWithErrors: Set<String> {
        var out = Set(items.filter { $0.stand == .verletzt }.flatMap(\.teile))
        for f in findings where f.schwere == .fehler { out.formUnion(f.teile) }
        return out
    }

    public var hasErrors: Bool { summary.fehler > 0 || findings.contains { $0.schwere == .fehler } }
}
