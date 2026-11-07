import CoreGraphics
import Foundation

/// I-4 (PLAN-IPAD.md 4.3, Budget „Stift bis Strich unter 20 ms“): Spur eines Stiftstrichs auf dem Bildschirm.
///
/// Der Pencil meldet bis zu 240 Punkte je Sekunde, ein Bild zeigt aber nur einen Teil davon: UIKit fasst die
/// Zwischenpunkte zusammen (`coalescedTouches`) und sagt die nächsten voraus (`predictedTouches`). Die Spur nimmt alle
/// zusammengefassten Punkte auf (glatte Linie) und hängt die Vorhersage nur bis zum nächsten Ereignis an (die Linie
/// folgt der Spitze ohne sichtbaren Abstand); die nächsten echten Punkte ersetzen sie. Die Punkte für Treffer und Paket
/// kommen weiter aus der Eingabeebene (einer je Ereignis), die Spur ist nur das, was Kevin sieht.
///
/// Plattformneutral, damit die Logik auch am Mac testbar ist; benutzt wird sie am iPad (TouchNavigation.swift). Am Mac
/// zeichnet die Maus ohne Vorhersage: AppKit fasst Mausereignisse selbst zusammen und kennt keine Vorhersage.
public final class StrichSpur {
    /// Punkte, die näher beieinander liegen, zeichnen nichts Neues (Punkte der Ansicht).
    public static let mindestAbstand: CGFloat = 0.5
    /// Höchstens so viele Messwerte der Verzögerung je Strich.
    public static let latenzenMax = 600

    /// Echte Punkte, Ursprung oben links.
    public private(set) var punkte: [CGPoint] = []
    /// Vorhergesagte Punkte bis zum nächsten Ereignis.
    public private(set) var vorhersage: [CGPoint] = []
    /// Verzögerung je Ereignis in Millisekunden: Zeitstempel der Berührung bis zum Zeichnen.
    public private(set) var latenzenMs: [Double] = []
    /// Linie aus den echten Punkten (wächst mit, statt jedes Mal neu zu entstehen).
    public private(set) var pfad = CGMutablePath()

    public init() {}

    public func beginnen(_ p: CGPoint) {
        punkte = [p]
        vorhersage = []
        latenzenMs = []
        pfad = CGMutablePath()
        pfad.move(to: p)
    }

    /// Neue echte Punkte eines Ereignisses und seine Vorhersage. Rückgabe: wie viele Punkte dazukamen.
    @discardableResult
    public func anfuegen(_ neu: [CGPoint], vorhersage v: [CGPoint]) -> Int {
        var n = 0
        for p in neu {
            if let letzter = punkte.last, Self.abstand(letzter, p) < Self.mindestAbstand { continue }
            if punkte.isEmpty { pfad.move(to: p) } else { pfad.addLine(to: p) }
            punkte.append(p)
            n += 1
        }
        vorhersage = v
        return n
    }

    /// Abheben: Was vorhergesagt war, gilt nicht mehr.
    public func beenden() { vorhersage = [] }

    /// Stück vom letzten echten Punkt durch die Vorhersage; nil ohne Vorhersage.
    public func vorhersagePfad() -> CGPath? {
        guard let start = punkte.last, !vorhersage.isEmpty else { return nil }
        let p = CGMutablePath()
        p.move(to: start)
        for q in vorhersage { p.addLine(to: q) }
        return p
    }

    /// Verzögerung eines Ereignisses merken (`beruehrung` und `jetzt` auf derselben Uhr, in Sekunden).
    public func latenz(beruehrung: TimeInterval, jetzt: TimeInterval) {
        guard beruehrung > 0, latenzenMs.count < Self.latenzenMax else { return }
        latenzenMs.append(max(0, (jetzt - beruehrung) * 1000))
    }

    /// Anteil `q` (0…1) der gemessenen Verzögerungen, etwa 0,95; nil ohne Messung.
    public func latenzAnteil(_ q: Double) -> Double? {
        guard !latenzenMs.isEmpty else { return nil }
        let s = latenzenMs.sorted()
        return s[min(s.count - 1, Int((Double(s.count - 1) * q).rounded()))]
    }

    static func abstand(_ a: CGPoint, _ b: CGPoint) -> CGFloat {
        let dx = a.x - b.x, dy = a.y - b.y
        return (dx * dx + dy * dy).squareRoot()
    }
}
