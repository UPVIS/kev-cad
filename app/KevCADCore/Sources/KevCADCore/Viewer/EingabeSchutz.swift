import CoreGraphics
import Foundation

// Schutz vor Fehleingaben im Viewer (Kevin, 08.11.2026, erster Test am iPad: „wenn wir in dem Erklären- oder in dem
// Zeichen-Modus sind, dass wir da schauen, dass wir vernünftige Palm Rejection haben … eigentlich soll das Teil dann
// insofern gelockt sein, als dass man wirklich nichts verändern kann. Man kann nur drauf schreiben“). PLAN-IPAD.md 4.2,
// 4.3 und 10. Reine Funktionen ohne UIKit und AppKit: Mac (BlenderNavigation.swift) und iPad (TouchNavigation.swift)
// fragen hier, die Tests laufen auf beiden Geräten.

/// Was eine Eingabe im Viewer bewirken würde.
public enum ViewerEingabeArt: String, Sendable, CaseIterable {
    /// Tippen, Klick: Auswahl, Messen, Klick-Werkzeuge (Maßstab, Simulation)
    case auswaehlen
    /// Rahmen aufziehen (Maus mit ⇧, ⌃ oder ⌘)
    case rahmen
    /// Doppeltippen: einrahmen
    case einrahmen
    /// Langes Drücken, Sekundärklick
    case kontextmenue
    /// 2 und 3 Finger tippen: Rückgängig, Wiederholen
    case verlauf
    /// Griff im Viewer ziehen (Simulation: Kraft)
    case griff
    /// Drehen, Verschieben, Zoomen
    case kamera
    /// Schweben, Maus, Finger: „das hier“
    case zeigen
    /// Strich beim Sprechen
    case strich
    /// Stifttipp (Mac: Klick) beim Sprechen: Bezug auf die Stelle, im Paket ein Strich aus einem Punkt
    case nadel
    /// Vom Rand wischen: Leisten (nur iPad)
    case randWischen
}

public enum EingabeSchutz {
    /// Darf die Eingabe wirken? `gesperrt` heißt: Kevin erklärt (Sprechsitzung mit rotem Rahmen, `zeichnen`). Dann ändert
    /// keine Zeiger- oder Berührungseingabe das Modell oder seinen Zustand (Auswahl, Elementmodus, Sichtbarkeit,
    /// Isolieren, Verlauf); Kamera, Zeigen, Striche und die Nadel bleiben. Tastaturkürzel fragen hier nicht: Eine Taste
    /// drückt man bewusst (V, ↩, Esc, Ansichten am Ziffernblock gehören zur Erklärung).
    public static func erlaubt(_ art: ViewerEingabeArt, gesperrt: Bool) -> Bool {
        switch art {
        case .kamera, .zeigen, .randWischen: return true
        case .strich, .nadel: return gesperrt  // ohne Sitzung zeichnet nichts (der Stiftstrich beginnt sie vorher)
        case .auswaehlen, .rahmen, .einrahmen, .kontextmenue, .verlauf, .griff: return !gesperrt
        }
    }

    /// Wirkung einer Geste am iPad (für die Hinweisleiste: was beim Sprechen gesperrt ist, steht dort nicht).
    public static func art(_ g: GestenBelegung.Geste) -> ViewerEingabeArt {
        switch g {
        case .einFinger, .zweiFinger, .spreizen: return .kamera
        case .tippen: return .auswaehlen
        case .doppeltTippen: return .einrahmen
        case .halten: return .kontextmenue
        case .zweiFingerTippen, .dreiFingerTippen: return .verlauf
        case .randWischen: return .randWischen
        case .stift: return .strich
        case .schweben: return .zeigen
        case .stiftDoppelt: return .kamera  // Werkzeugkranz: bewusst ausgelöst, bleibt (Senden liegt oben im Kranz)
        }
    }

    /// Tippen beim Sprechen: mit dem Stift die Nadel, mit dem Finger nur Zeigen (der Finger kann der Handballen sein,
    /// eine Nadel aus Versehen landete im Paket).
    public static func tippenBeimSprechen(stift: Bool) -> ViewerEingabeArt { stift ? .nadel : .zeigen }
}

// MARK: Handballen (iPad, PLAN-IPAD.md 4.3)

/// Wo der Stift zuletzt war (Fensterpunkte, Ursprung oben links). Schweben und Aufliegen frischen `zeit` laufend auf.
public struct StiftLage: Equatable, Sendable {
    public var ort: CGPoint
    /// `ProcessInfo.systemUptime` der letzten Meldung (Berührung oder Schweben)
    public var zeit: TimeInterval
    /// Spitze auf dem Glas (sonst schwebt sie oder ist eben weg)
    public var liegtAuf: Bool
    /// Richtung von der Spitze zur Hand (Azimut des Pencil, Einheitsvektor in Fensterpunkten); nil = unbekannt
    public var zurHand: CGVector?

    public init(ort: CGPoint, zeit: TimeInterval, liegtAuf: Bool, zurHand: CGVector? = nil) {
        self.ort = ort
        self.zeit = zeit
        self.liegtAuf = liegtAuf
        self.zurHand = zurHand
    }
}

/// Eine Fingerberührung, wie UIKit sie meldet (Fensterpunkte, Ursprung oben links).
public struct FingerBeruehrung: Equatable, Sendable {
    public var ort: CGPoint
    /// `UITouch.majorRadius` in Punkten
    public var radius: CGFloat
    public var zeit: TimeInterval

    public init(ort: CGPoint, radius: CGFloat, zeit: TimeInterval) {
        self.ort = ort
        self.radius = radius
        self.zeit = zeit
    }
}

public enum Handballen {
    /// Ab diesem Kontaktradius ist es kein Finger, sondern Ballen oder Handkante (`majorRadius`, Punkte). Eine
    /// Fingerkuppe misst am iPad Pro rund 15 bis 30 pt Radius, ein fest aufgelegter Daumen bis gut 35 pt; ein Handballen
    /// liegt deutlich darüber. Am Gerät zu prüfen (I-10), Kevin meldet, wenn ein Daumen nicht mehr dreht.
    public static let grosseFlaeche: CGFloat = 42
    /// So lange nach dem letzten Lebenszeichen des Stifts (abgehoben oder aus dem Schwebebereich) gilt er noch als da: Die
    /// Hand liegt dann meist noch auf.
    public static let nachlaufS: TimeInterval = 0.5
    /// Ein aufliegender Stift meldet sich nur, wenn er sich bewegt. Kam das Abheben nicht an (Tipp außerhalb des Viewers),
    /// gilt er nach so langer Stille als weg.
    public static let aufliegenOhneMeldungS: TimeInterval = 4
    /// Rund um die Spitze zählt jede Berührung als Hand, gleich in welcher Richtung (der kleine Finger stützt oft neben
    /// der Spitze ab).
    public static let umDieSpitze: CGFloat = 110
    /// Auf der Seite der Schreibhand reicht die Hand so weit (Ballen und Unterarm einer großen Hand auf 12,9″).
    public static let handReichweite: CGFloat = 480
    /// Etwas über die Spitze hinaus nach vorn gehört noch zur Hand (Fingerknöchel).
    public static let vorDerSpitze: CGFloat = 60
    /// Ohne Azimut: rechte Hand, Ballen rechts unterhalb der Spitze (die meisten Schreibhände).
    public static let ohneAzimut = CGVector(dx: 0.45, dy: 0.89)

    /// Gilt der Stift zum Zeitpunkt `jetzt` noch als da (liegt auf, schwebt oder ist kaum weg)?
    public static func stiftDa(_ s: StiftLage?, jetzt: TimeInterval) -> Bool {
        guard let s else { return false }
        let still = jetzt - s.zeit
        return still <= nachlaufS || (s.liegtAuf && still <= aufliegenOhneMeldungS)
    }

    /// Ist die Berührung (wahrscheinlich) Handballen bzw. die Schreibhand statt eines Fingers? Große Kontaktflächen
    /// immer; sonst nur, solange der Stift da ist, und nur in seiner Nähe auf der Seite der Hand. Die andere Hand (zwei
    /// Finger zum Verschieben und Zoomen) bleibt frei.
    public static func istHand(_ b: FingerBeruehrung, stift: StiftLage?) -> Bool {
        if b.radius >= grosseFlaeche { return true }
        guard let s = stift, stiftDa(s, jetzt: b.zeit) else { return false }
        let d = CGVector(dx: b.ort.x - s.ort.x, dy: b.ort.y - s.ort.y)
        let abstand = hypot(d.dx, d.dy)
        if abstand <= umDieSpitze { return true }
        if abstand > handReichweite { return false }
        let r = normiert(s.zurHand) ?? ohneAzimut
        let entlang = d.dx * r.dx + d.dy * r.dy  // wie weit in Richtung der Hand
        return entlang >= -vorDerSpitze
    }

    /// Mehrere Berührungen einer Geste: Eine einzige Hand darunter macht die ganze Geste ungültig (Ballen plus Finger
    /// ist kein 2-Finger-Tippen).
    public static func enthaeltHand(_ b: [FingerBeruehrung], stift: StiftLage?) -> Bool {
        b.contains { istHand($0, stift: stift) }
    }

    static func normiert(_ v: CGVector?) -> CGVector? {
        guard let v else { return nil }
        let l = hypot(v.dx, v.dy)
        return l > 0.01 ? CGVector(dx: v.dx / l, dy: v.dy / l) : nil
    }
}

// MARK: Doppeltippen (PLAN-IPAD.md 4.2)

/// Doppeltippen wählt nicht nebenbei aus: Der erste Tipp wählt sofort (Tippen bleibt so schnell wie bisher), wird er zum
/// Doppeltippen, nimmt das die Auswahl auf den Stand vor dem ersten Tipp zurück und rahmt das getippte Teil ein. Merkt
/// sich je Tippfolge den Stand vor ihrem ersten Tipp.
public struct TippFolge<Stand> {
    /// Länger als UIKits Abstand fürs Doppeltippen (rund 0,35 s), damit der Stand sicher noch da ist.
    public static var fensterS: TimeInterval { 0.6 }

    private var vorher: Stand?
    private var letzterTipp: TimeInterval?

    public init() {}

    /// Ein einzelner Tipp wirkt gleich: `stand` ist der Zustand davor. Nur der erste Tipp einer Folge merkt ihn sich.
    public mutating func tipp(stand: Stand, zeit: TimeInterval) {
        if let l = letzterTipp, zeit - l <= Self.fensterS {
            letzterTipp = zeit
            return
        }
        vorher = stand
        letzterTipp = zeit
    }

    /// Das Doppeltippen ist erkannt: Stand vor dem ersten Tipp, nil = kein Tipp kurz davor (nichts zurückzunehmen).
    public mutating func doppelt(zeit: TimeInterval) -> Stand? {
        defer {
            vorher = nil
            letzterTipp = nil
        }
        guard let l = letzterTipp, zeit - l <= Self.fensterS else { return nil }
        return vorher
    }
}
