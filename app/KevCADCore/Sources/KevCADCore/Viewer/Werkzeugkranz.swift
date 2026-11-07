import CoreGraphics
import Foundation

// I-4 (PLAN-IPAD.md 4.4): Werkzeugkranz, ein Kreismenü an der Stiftspitze (iPad, Pencil doppelt tippen) bzw. an der Maus
// (Mac, Q). Vorbild ist Feather 2.0: eine milchige Scheibe, innen die Strichfarben als Pillen um die aktuelle Farbe,
// außen acht Felder; ein Feld mit Unterpunkten öffnet einen zweiten Ring, ein stufenloser Wert wird zum Drehregler.
//
// Hier steht nur Logik ohne Oberfläche (Geometrie, Auswahl nach Richtung, Drehregler), damit sie testbar ist. Was in
// den Feldern liegt, steht in Tastenbelegung.swift (`Tastenbelegung.kranz`); gezeichnet wird in
// WerkzeugkranzAnsicht.swift, ausgeführt in AppController+Kranz.swift.

/// Die acht Felder des Außenrings, im Uhrzeigersinn ab oben (Reihenfolge = Lage).
public enum KranzFeld: String, CaseIterable, Sendable {
    case sprechen, ansichten, darstellung, messen, mehr, sichtbarkeit, kacheln, agent

    /// Kurzer Name beim Darüberfahren.
    public var name: String {
        switch self {
        case .sprechen: return "Sprechen"
        case .ansichten: return "Ansichten"
        case .darstellung: return "Darstellung"
        case .messen: return "Messen"
        case .mehr: return "Mehr"
        case .sichtbarkeit: return "Sichtbarkeit"
        case .kacheln: return "Kacheln"
        case .agent: return "Agent"
        }
    }

    public var symbol: String {
        switch self {
        case .sprechen: return "mic.fill"
        case .ansichten: return "cube"
        case .darstellung: return "circle.lefthalf.filled"
        case .messen: return "ruler"
        case .mehr: return "ellipsis"
        case .sichtbarkeit: return "eye"
        case .kacheln: return "square.grid.2x2"
        case .agent: return "sparkles"
        }
    }
}

/// Stufenlose Werte, die der Kranz als Drehregler stellt.
public enum KranzRegler: String, CaseIterable, Sendable {
    /// Explosion 0…100 %
    case explosion
    /// Schnittebene quer zu Z, in mm innerhalb der sichtbaren Teile
    case schnitt
    /// Breite der Striche beim Sprechen, in Punkten
    case strichbreite

    public var name: String {
        switch self {
        case .explosion: return "Explosion"
        case .schnitt: return "Schnitt"
        case .strichbreite: return "Strichbreite"
        }
    }

    public var symbol: String {
        switch self {
        case .explosion: return "arrow.up.left.and.arrow.down.right"
        case .schnitt: return "square.split.diagonal"
        case .strichbreite: return "lineweight"
        }
    }

    /// Teilstriche rund um das Ziffernblatt (eine volle Umdrehung durchläuft den ganzen Bereich).
    public var teilstriche: Int {
        switch self {
        case .explosion: return 20
        case .schnitt: return 40
        case .strichbreite: return 10
        }
    }

    /// Wert in der Mitte: „40 %“, „120 mm“, „3 pt“.
    public func text(_ wert: Double) -> String {
        switch self {
        case .explosion: return "\(Int((wert * 100).rounded())) %"
        case .schnitt: return "\(Int(wert.rounded())) mm"
        case .strichbreite: return "\(Int(wert.rounded())) pt"
        }
    }
}

/// Bereich und Raster eines Drehreglers zur Laufzeit (die Schnittebene hängt vom Modell ab).
public struct KranzReglerBereich: Equatable, Sendable {
    public var min: Double
    public var max: Double
    /// Raster, auf das der Wert einrastet (0 = stufenlos).
    public var raster: Double

    public init(min: Double, max: Double, raster: Double = 0) {
        self.min = min
        self.max = Swift.max(max, min)
        self.raster = raster
    }

    public var spanne: Double { max - min }

    /// Nur in den Bereich, ohne Raster (der Drehregler sammelt kleine Schritte, bis sie eine Raste erreichen).
    public func begrenzen(_ w: Double) -> Double { Swift.min(Swift.max(w, min), max) }

    /// Wert in den Bereich und aufs Raster.
    public func klemmen(_ w: Double) -> Double {
        var v = Swift.min(Swift.max(w, min), max)
        if raster > 0 { v = min + ((v - min) / raster).rounded() * raster }
        return Swift.min(Swift.max(v, min), max)
    }

    /// Anteil 0…1 für das Ziffernblatt.
    public func anteil(_ w: Double) -> Double { spanne > 0 ? (klemmen(w) - min) / spanne : 0 }
}

/// Was ein Eintrag des Kranzes tut.
public enum KranzAktion: Equatable, Sendable {
    /// Ein Befehl der Belegung (wie die Taste am Mac).
    case befehl(ViewerBefehl)
    /// Ohne Sitzung: Sprechen beginnt; in der Sitzung: abschicken (die Hauptschleife „Doppeltippen, nach oben“).
    case sprechenOderSenden
    /// Darstellung wählen (wie Z am Mac).
    case darstellung(ShadingModus)
    /// Eine Kachel öffnen bzw. nach vorn holen.
    case kachel(KachelArt)
    /// Drehregler öffnen.
    case regler(KranzRegler)
    /// model.py neu rechnen.
    case neuRechnen
    /// Stift startet das Sprechen (an/aus).
    case stiftSprechen
    /// Viewerbild mit den Strichen als Paket an den Agenten, ohne Sprechen.
    case bildAnAgent
}

/// Ein Eintrag im zweiten Ring.
public struct KranzEintrag: Identifiable, Equatable, Sendable {
    public var name: String
    public var symbol: String
    public var aktion: KranzAktion

    public init(_ name: String, _ symbol: String, _ aktion: KranzAktion) {
        self.name = name
        self.symbol = symbol
        self.aktion = aktion
    }

    /// Eintrag für einen Befehl der Belegung; der Name kommt aus `titel`, wenn keiner gegeben ist.
    public static func befehl(_ b: ViewerBefehl, _ symbol: String, _ name: String? = nil) -> KranzEintrag {
        KranzEintrag(name ?? Tastenbelegung.belegung(b)?.titel ?? b.rawValue, symbol, .befehl(b))
    }

    public var id: String { name }
}

/// Wo der Kranz gerade steht.
public enum KranzEbene: Equatable, Sendable {
    /// Scheibe mit Farbpillen und acht Feldern
    case haupt
    /// zweiter Ring mit den Unterpunkten eines Felds
    case feld(KranzFeld)
    /// Ziffernblatt eines Drehreglers
    case regler(KranzRegler)
}

/// Worauf Stift, Finger oder Maus im Kranz zeigen.
public enum KranzZiel: Equatable, Sendable {
    /// in der Mitte: abbrechen bzw. zurück
    case mitte
    /// eine Farbpille (Index in `Strichfarbe.allCases`)
    case pille(Int)
    /// ein Feld des Außenrings (Index in `KranzFeld.allCases`)
    case feld(Int)
    /// ein Eintrag des zweiten Rings
    case unter(Int)
    /// neben dem Kranz
    case daneben
}

/// Zustand eines offenen Kranzes (im `ViewerStore`).
public struct KranzZustand: Equatable, Sendable {
    /// Mitte der Scheibe im Viewport (Punkte, Ursprung oben links), schon so geschoben, dass alles im Bild bleibt.
    public var mitte: CGPoint
    public var ebene: KranzEbene = .haupt
    /// Hervorgehoben (Darüberfahren, Ziehen).
    public var markiert: KranzZiel?
    /// Drehregler: Wert (eingerastet), gesammelter Wert ohne Raster, Wert beim Öffnen (Esc stellt ihn zurück), Bereich und
    /// letzter Winkel des Zeigers.
    public var wert: Double = 0
    public var roh: Double = 0
    public var startWert: Double = 0
    public var bereich = KranzReglerBereich(min: 0, max: 1)
    public var letzterWinkel: Double?

    public init(mitte: CGPoint) { self.mitte = mitte }
}

/// Maße und Rechnungen des Kranzes. Winkel in Grad, 0 = oben, im Uhrzeigersinn; Punkte mit y nach unten (SwiftUI).
public enum KranzGeometrie {
    /// Durchmesser der Scheibe (PLAN-IPAD.md 4.4: rund 170 pt).
    public static let durchmesser: CGFloat = 170
    public static var radius: CGFloat { durchmesser / 2 }
    /// Abstand der Feldsymbole von der Mitte.
    public static let feldRadius: CGFloat = 63
    /// Abstand der Farbpillen von der Mitte.
    public static let pillenRadius: CGFloat = 32
    /// Innerhalb: Mitte (abbrechen, zurück).
    public static let mitteRadius: CGFloat = 16
    /// Grenze zwischen Pillen und Feldern.
    public static var pillenGrenze: CGFloat { (pillenRadius + feldRadius) / 2 }
    /// Abstand der Einträge des zweiten Rings.
    public static let unterRadius: CGFloat = 122
    /// Außerhalb gilt ein Tipp als daneben (Hauptscheibe bzw. zweiter Ring).
    public static var hauptGrenze: CGFloat { radius + 20 }
    public static var unterGrenze: CGFloat { unterRadius + 34 }
    /// Platz, den der Kranz samt zweitem Ring und Namen braucht (für das Schieben ins Bild).
    public static var platz: CGFloat { unterRadius + 30 }

    /// Winkel eines Vektors (0 = oben, im Uhrzeigersinn, 0..<360).
    public static func winkel(_ dx: CGFloat, _ dy: CGFloat) -> Double {
        let w = atan2(Double(dx), Double(-dy)) * 180 / .pi
        return w < 0 ? w + 360 : w
    }

    /// Sektor zu einem Winkel bei `anzahl` gleich großen Sektoren; Sektor 0 liegt mittig oben.
    public static func sektor(winkel: Double, anzahl: Int) -> Int {
        guard anzahl > 0 else { return 0 }
        let breite = 360 / Double(anzahl)
        let w = (winkel + breite / 2).truncatingRemainder(dividingBy: 360)
        return min(Int(w / breite), anzahl - 1)
    }

    /// Lage des Eintrags `index` von `anzahl` auf einem Ring (Versatz von der Mitte, y nach unten).
    public static func lage(index: Int, anzahl: Int, radius: CGFloat) -> CGPoint {
        let w = Double(index) * 360 / Double(max(anzahl, 1)) * .pi / 180
        return CGPoint(x: radius * CGFloat(sin(w)), y: -radius * CGFloat(cos(w)))
    }

    /// Ziel unter einem Punkt (Versatz von der Mitte). `gezogen`: Der Stift wurde gezogen (Wischen in eine Richtung);
    /// dann wählt auch ein Punkt weit außerhalb nach seiner Richtung, ein Tipp dort ist dagegen daneben.
    public static func ziel(_ v: CGPoint, ebene: KranzEbene, unterAnzahl: Int, gezogen: Bool) -> KranzZiel {
        let d = (v.x * v.x + v.y * v.y).squareRoot()
        if d < mitteRadius { return .mitte }
        let w = winkel(v.x, v.y)
        switch ebene {
        case .haupt:
            if d < pillenGrenze { return .pille(sektor(winkel: w, anzahl: Strichfarbe.allCases.count)) }
            if d <= hauptGrenze || gezogen { return .feld(sektor(winkel: w, anzahl: KranzFeld.allCases.count)) }
            return .daneben
        case .feld:
            if d <= radius { return .feld(sektor(winkel: w, anzahl: KranzFeld.allCases.count)) }
            if unterAnzahl > 0, d <= unterGrenze || gezogen { return .unter(sektor(winkel: w, anzahl: unterAnzahl)) }
            return .daneben
        case .regler:
            return d <= hauptGrenze || gezogen ? .feld(0) : .daneben
        }
    }

    /// Mitte so, dass Kranz und zweiter Ring im Viewport bleiben (`rand`: freier Rand).
    public static func mitte(fuer p: CGPoint, in groesse: CGSize, rand: CGFloat = 8) -> CGPoint {
        let r = platz + rand
        func klemmen(_ x: CGFloat, _ laenge: CGFloat) -> CGFloat {
            laenge <= 2 * r ? laenge / 2 : min(max(x, r), laenge - r)
        }
        return CGPoint(x: klemmen(p.x, groesse.width), y: klemmen(p.y, groesse.height))
    }

    /// Kleinster Unterschied zweier Winkel (−180…180), positiv im Uhrzeigersinn.
    public static func winkelSchritt(von a: Double, nach b: Double) -> Double {
        var d = (b - a).truncatingRemainder(dividingBy: 360)
        if d > 180 { d -= 360 }
        if d < -180 { d += 360 }
        return d
    }

    /// Neuer Rohwert eines Drehreglers, wenn der Zeiger um `grad` kreist: Eine volle Umdrehung durchläuft den Bereich.
    /// Ohne Raster, damit kleine Bewegungen sich sammeln; eingerastet wird mit `KranzReglerBereich.klemmen`.
    public static func reglerWert(_ roh: Double, grad: Double, bereich: KranzReglerBereich) -> Double {
        bereich.begrenzen(roh + grad / 360 * bereich.spanne)
    }

    /// Neuer Rohwert für `schritte` Rasten des Mausrads (je Raste ein Teilstrich).
    public static func reglerWert(_ roh: Double, schritte: Double, regler: KranzRegler,
                                  bereich: KranzReglerBereich) -> Double {
        bereich.begrenzen(roh + schritte * bereich.spanne / Double(max(regler.teilstriche, 1)))
    }
}
