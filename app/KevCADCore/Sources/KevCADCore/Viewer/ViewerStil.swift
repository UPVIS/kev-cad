import CoreGraphics
import SwiftUI
import simd

/// Gestaltungswerte der Überlagerungen im Viewport (Hinweisleiste, Tastenübersicht, Menüs, Messbeschriftung, Meldungen).
///
/// Bewusst an einer Stelle: Das neue Gestaltungssystem der Fensteroberfläche ersetzt später nur diese Datei. Farben als
/// sRGB 0…1, Größen in Punkten.
public enum ViewerStil {
    // MARK: Farben

    /// Grund der schwebenden Leisten (Hinweisleiste, Meldungen): halbdurchsichtiges Dunkelgrau über dem Modell.
    public static let leisteGrund = Color(.sRGB, red: 0.11, green: 0.115, blue: 0.125, opacity: 0.78)
    /// Rand der Leisten.
    public static let leisteRand = Color.white.opacity(0.08)
    /// Text auf den Leisten.
    public static let text = Color.white.opacity(0.92)
    public static let textLeise = Color.white.opacity(0.58)
    /// Tastensymbole („⇧“, „1“, „Mitte“) auf den Leisten.
    public static let tasteGrund = Color.white.opacity(0.13)
    public static let tasteRand = Color.white.opacity(0.16)
    /// Akzent für aktive Zustände (Messen, Röntgen an, gedrückte Taste).
    public static let akzent = Color(.sRGB, red: 0.33, green: 0.62, blue: 1.0, opacity: 1)
    /// Messungen: Linien, Beschriftung, Fangpunkte (wie bisher das Grün der Messungen).
    public static let mass = SIMD4<Float>(0.0, 0.55, 0.45, 1)
    /// Geänderter Wert am Teil nach `run(params)` (V2-5): der Akzent des Viewers.
    public static let massParameter = SIMD4<Float>(0.33, 0.62, 1.0, 1)
    /// Vorschau beim Darüberfahren im Messmodus.
    public static let massVorschau = SIMD4<Float>(0.95, 0.55, 0.05, 1)
    /// Fangpunkt (Ecke, Kantenmitte, Kreismitte) unter der Maus.
    public static let fangpunkt = SIMD4<Float>(1.0, 0.78, 0.1, 1)
    /// Kevins Striche beim Sprechen (Lichtblau wie sein Text, V2-6).
    public static let strich = SIMD4<Float>(0.56, 0.78, 1.0, 1)

    // MARK: Schrift

    public static let schrift = Font.system(size: 11.5, weight: .regular)
    public static let schriftFett = Font.system(size: 11.5, weight: .semibold)
    public static let schriftTaste = Font.system(size: 10.5, weight: .medium, design: .rounded)
    public static let schriftTitel = Font.system(size: 13, weight: .semibold)
    /// Maßbeschriftung im Bild (CoreText, Punkte vor Skalierung).
    public static let massSchriftgroesse: CGFloat = 12

    // MARK: Maße

    public static let radiusLeiste: CGFloat = 8
    public static let radiusTaste: CGFloat = 4
    public static let radiusKarte: CGFloat = 12
    public static let hoeheLeiste: CGFloat = 26
    public static let abstand: CGFloat = 8
    /// Fangradius für Ecken, Kantenmitten und Kreismitten (Punkte am Bildschirm).
    public static let fangRadius: CGFloat = 12
    /// Dauer weicher Kamerafahrten (Blender „Smooth View“).
    public static let kamerafahrt: Double = 0.2
}
