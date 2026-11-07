import CoreGraphics
import Foundation

/// Schwung nach schnellem Loslassen (PLAN-IPAD.md 4.2, I-3b): Die Drehung läuft mit der Geschwindigkeit des Fingers weiter
/// und klingt rasch ab. Reine Rechnung, damit iPad (eigener Nachlauf in TouchNavigation.swift) und Tests dieselbe Kurve
/// haben; am Mac liefert das Trackpad seinen Nachlauf selbst (BlenderNavigation.swift, nur wenn der Schalter an ist).
struct Schwung {
    /// Ab dieser Geschwindigkeit beim Loslassen (Punkte je Sekunde) gibt es Schwung; langsames Loslassen bleibt stehen.
    static let abGeschwindigkeit: CGFloat = 280
    /// Darunter endet der Schwung.
    static let bisGeschwindigkeit: CGFloat = 12
    /// Zeitkonstante des Abklingens (Sekunden): nach rund 0,7 s ist die Drehung zur Ruhe gekommen.
    static let zeitkonstante: Double = 0.18

    /// Geschwindigkeit in Punkten je Sekunde, y nach oben (wie die Mausbewegung am Mac).
    private(set) var geschwindigkeit: CGVector

    /// nil, wenn das Loslassen zu langsam war.
    init?(geschwindigkeit v: CGVector) {
        guard hypot(v.dx, v.dy) >= Self.abGeschwindigkeit else { return nil }
        geschwindigkeit = v
    }

    /// Ein Bild weiter: Drehweg in Punkten für `dt` Sekunden; nil = Schwung zu Ende.
    mutating func schritt(_ dt: Double) -> CGVector? {
        let dt = max(0, min(dt, 0.05))  // ein langer Hänger soll keinen Sprung machen
        let f = exp(-dt / Self.zeitkonstante)
        // Weg = Integral der abklingenden Geschwindigkeit über dt
        let weg = CGFloat(Self.zeitkonstante * (1 - f))
        let d = CGVector(dx: geschwindigkeit.dx * weg, dy: geschwindigkeit.dy * weg)
        geschwindigkeit = CGVector(dx: geschwindigkeit.dx * CGFloat(f), dy: geschwindigkeit.dy * CGFloat(f))
        return hypot(geschwindigkeit.dx, geschwindigkeit.dy) < Self.bisGeschwindigkeit ? nil : d
    }
}
