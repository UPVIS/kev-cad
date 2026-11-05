import AppKit
import SwiftUI

/// Gestaltungswerte der Oberfläche von Kev CAD V2 (OBERFLAECHE.md, Abschnitt 2).
///
/// Richtung „Graphit“ (Kevins Wahl vom 05.11.2026): Der Viewer ist ein Fotostudio, die Oberfläche tritt zurück, Kevin
/// spricht in Lichtblau, der Agent in Messing. Aus der Richtung „Sucher“ kommen der rote Rahmen, solange Kevin spricht,
/// und die nummerierten Kacheln. Zeichnungsblätter bleiben hell wie im Entwurf „Reißbrett“.
///
/// Alle Bausteine nehmen Farben, Schriften, Abstände, Radien und Bewegungen nur von hier. Eine andere Richtung tauscht
/// diese Datei und die wenigen Bausteine, die eigens für Graphit gezeichnet sind (`GraphitGrund`, `KachelNummer`,
/// `Sprechrahmen`).
enum Gestaltung {
    /// Farben. Sie gelten nur im dunklen Hauptfenster (Graphit hat keine helle Fassung).
    enum Farbe {
        // Licht im Viewer: Mitte, Übergang, Rand
        static let hell = rgb(0x4A4D53)
        static let mitte = rgb(0x2E3034)
        static let tief = rgb(0x191A1D)

        // Text
        /// Haupttext
        static let kreide = rgb(0xEFEDE9)
        /// Nebentext und Beschriftungen
        static let asche = rgb(0xA9A7A2)
        /// leise Angaben: Zahlen, Einheiten, Hinweise
        static let rauch = rgb(0x77756F)

        // Stimmen
        /// Kevin: Live-Text, Auswahl, Zeigen (Lichtblau)
        static let kevin = rgb(0x8FC6FF)
        /// Agent: Spur, Maße, „vorher“ (Messing)
        static let agent = rgb(0xDCB878)
        /// Befunde der Prüfung (Koralle)
        static let befund = rgb(0xFF7B69)
        /// Rahmen um den Viewer, solange Kevin spricht (Rot aus der Richtung „Sucher“)
        static let aufnahme = rgb(0xFF4B3E)

        // Flächen
        /// Spalten und Inseln der Werkstatt
        static let insel = rgb(0x1F2023, 0.74)
        /// Overlay-Karten (über Unschärfe)
        static let karte = rgb(0x1C1D20, 0.80)
        /// Kopf der Kacheln und Statuszeile
        static let leiste = rgb(0x1C1D20, 0.55)
        /// feine Ränder
        static let linie = Color.white.opacity(0.075)
        /// Eingabefelder
        static let feld = Color.white.opacity(0.055)
        static let feldFokus = Color.white.opacity(0.09)
        /// Knöpfe: Ruhe, unter dem Zeiger, gedrückt, eingeschaltet
        static let knopf = Color.white.opacity(0.065)
        static let knopfHover = Color.white.opacity(0.11)
        static let knopfGedrueckt = Color.white.opacity(0.17)
        static let knopfAn = rgb(0x8FC6FF, 0.22)
        /// Umschalter Fokus/Werkstatt
        static let modusGrund = Color.white.opacity(0.06)
        static let modusAn = Color.white.opacity(0.13)
        /// Zeilen der Gliederung
        static let zeileHover = Color.white.opacity(0.045)
        static let zeileGewaehlt = rgb(0x8FC6FF, 0.13)
        /// Tastenkappen
        static let taste = Color.white.opacity(0.08)
        static let tasteRand = Color.white.opacity(0.14)
        /// Schatten für Text, der direkt im Bild steht
        static let textSchatten = Color.black.opacity(0.45)
        /// Zeichnungsblatt (helles Papier wie „Reißbrett“)
        static let papier = rgb(0xF1F0EC)

        /// sRGB aus einer Hexzahl wie 0x4A4D53.
        fileprivate static func rgb(_ hex: UInt32, _ alpha: Double = 1) -> Color {
            Color(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: alpha)
        }
    }

    /// Schriften: SF Pro in den Größen des Entwurfs (1440 × 900 Punkte).
    enum Schrift {
        static let projekt = Font.system(size: 13, weight: .semibold)
        static let projektZusatz = Font.system(size: 12)
        static let modus = Font.system(size: 12)
        static let zeile = Font.system(size: 13)
        static let zeileKind = Font.system(size: 12.5)
        static let zahl = Font.system(size: 12).monospacedDigit()
        static let text = Font.system(size: 12.5)
        static let klein = Font.system(size: 12)
        static let winzig = Font.system(size: 11)
        static let abschnitt = Font.system(size: 12, weight: .semibold)
        static let name = Font.system(size: 17, weight: .semibold)
        static let kachelTitel = Font.system(size: 13, weight: .semibold)
        static let kachelNummer = Font.system(size: 11, weight: .semibold).monospacedDigit()
        static let karteTitel = Font.system(size: 14, weight: .semibold)
        static let karteName = Font.system(size: 13, weight: .semibold)
        static let liveText = Font.system(size: 27)
        static let liveTextSchmal = Font.system(size: 19)
        static let start = Font.system(size: 38, weight: .light)
        static let startSchmal = Font.system(size: 26, weight: .light)
        static let startZeile = Font.system(size: 15)
        static let taste = Font.system(size: 11, weight: .medium)
        static let wert = Font.system(size: 12.5).monospacedDigit()
    }

    /// Abstände und feste Maße.
    enum Abstand {
        static let xs: CGFloat = 4
        static let s: CGFloat = 8
        static let m: CGFloat = 12
        static let l: CGFloat = 16
        static let xl: CGFloat = 22
        /// Abstand der Inseln und Kacheln zum Fensterrand und zueinander
        static let rand: CGFloat = 14
        /// Kopfleiste oben (Ampel, Projekt, Modus, Knöpfe). macOS 26 setzt die Ampel bei versteckter Titelleiste auf
        /// 16 pt Höhe; die Kopfleiste richtet ihre Mitte daran aus (gemessen am Willkommensfenster, 05.11.2026).
        static let kopf: CGFloat = 32
        /// Mitte der Ampel von oben
        static let ampelMitte: CGFloat = 16
        /// Platz für die Ampel (Schließen, Minimieren, Zoomen) links in der Kopfleiste
        static let ampel: CGFloat = 80
        /// Abstand der Arbeitsfläche unter der Kopfleiste
        static let unterKopf: CGFloat = 4
        /// linke Spalte der Werkstatt
        static let spalte: CGFloat = 278
        /// Gliederung im Fokus
        static let gliederung: CGFloat = 232
        static let zeile: CGFloat = 27
        static let zeileKind: CGFloat = 25
        static let einzug: CGFloat = 17
        static let feld: CGFloat = 26
        static let feldTitel: CGFloat = 78
        static let knopf: CGFloat = 30
        static let knopfText: CGFloat = 28
        static let taste: CGFloat = 20
        static let kachelKopf: CGFloat = 40
        static let statuszeile: CGFloat = 50
        /// Breite des Fensters am Bildschirmrand
        static let schmal: CGFloat = 460
        /// unter dieser Breite gilt das Fenster als schmal (Fokus rückt zusammen)
        static let schmalAb: CGFloat = 640
        /// Breite des roten Rahmens beim Sprechen
        static let sprechrahmen: CGFloat = 2
    }

    /// Eckenradien (kontinuierliche Ecken).
    enum Radius {
        static let feld: CGFloat = 7
        static let taste: CGFloat = 6
        static let knopfText: CGFloat = 8
        static let nummer: CGFloat = 5
        static let karte: CGFloat = 14
        static let insel: CGFloat = 18
        static let kachel: CGFloat = 18
        static let overlay: CGFloat = 22
        static let fenster: CGFloat = 12
    }

    /// Bewegungen. Kurz für Rückmeldungen, Standard für Umbau, weich für große Flächen.
    enum Bewegung {
        static let kurz = Animation.snappy(duration: 0.16)
        static let standard = Animation.snappy(duration: 0.24)
        static let weich = Animation.smooth(duration: 0.34)
        /// Fenster an den Rand und zurück (NSAnimationContext)
        static let rand: TimeInterval = 0.3
        /// Punkte, die „atmen“ (der Agent arbeitet gerade)
        static let atmen = Animation.easeInOut(duration: 0.8).repeatForever(autoreverses: true)
    }
}

extension View {
    /// Text, der direkt im Bild über dem Viewer steht: weicher Schatten für die Lesbarkeit über hellen Teilen.
    func textImBild() -> some View {
        shadow(color: Gestaltung.Farbe.textSchatten, radius: 1, x: 0, y: 1)
            .shadow(color: .black.opacity(0.25), radius: 9, x: 0, y: 0)
    }
}
