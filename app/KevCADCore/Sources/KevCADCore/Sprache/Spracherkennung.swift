import Foundation

// V2-6: Naht für die Spracherkennung. Heute Apples Erkennung auf dem Gerät (`AppleErkennung`), im Test ein Skript
// (`TestErkennung`). Wortlaut (Parakeet, Kevins XPC-Dienst) lässt sich hier einstecken, sobald Kev CAD mit seinem Team
// signiert ist. Alle Zeiten sind `ProcessInfo.systemUptime`, wie im Sichtung-Vorbild; die Sitzung rechnet sie auf ihre
// Uhr um.

/// Stand der Erkennung, für die Oberfläche.
public enum SprachZustand: Equatable, Sendable {
    case aus
    case startet
    case hoert
    /// Vorübergehend nicht (das Sprachpaket lädt).
    case laedt(String)
    /// Ohne Zutun beendet (kein Zugriff, keine Sprache, kein Mikrofon). Der Satz ist für die Oberfläche.
    case fehler(String)
}

/// Ein erkanntes Wort mit Zeiten aus dem Ton.
public struct SprachWort: Equatable, Sendable {
    public var text: String
    public var von: Double
    public var bis: Double

    public init(text: String, von: Double, bis: Double) {
        self.text = text
        self.von = von
        self.bis = bis
    }
}

public enum SprachEreignis: Sendable {
    /// Lautstärke 0…1, etwa zehnmal je Sekunde.
    case pegel(Float)
    /// Flüchtiger Text des laufenden Satzes.
    case zwischenstand(String)
    /// Endgültig: Text, Wörter mit Zeiten (leer, wenn die Quelle keine kennt), Anfang und Ende des Sprechens.
    case satz(text: String, worte: [SprachWort], von: Double?, bis: Double?)
    case zustand(SprachZustand)
}

/// Eine Quelle für gesprochenen Text. Sie meldet alles auf dem Hauptfaden.
@MainActor
public protocol Spracherkennung: AnyObject {
    /// Fürs Paket: `apple-dictation`, `apple-speech`, `test`, später `wortlaut-parakeet`.
    var kennung: String { get }
    var beiEreignis: ((SprachEreignis) -> Void)? { get set }
    /// Hört zu, bis `anhalten` kommt. Darf nach `anhalten` wieder gerufen werden (nächster Abschnitt).
    func starten()
    /// Hört auf und meldet die letzten Wörter; endet, wenn nichts mehr kommt.
    func anhalten() async
}

/// Für Selbsttests und den Demomodus: kein Mikrofon, keine Rechteabfrage. Sätze kommen über `sagen`.
@MainActor
public final class TestErkennung: Spracherkennung {
    public let kennung = "test"
    public var beiEreignis: ((SprachEreignis) -> Void)?

    public init() {}

    public func starten() { beiEreignis?(.zustand(.hoert)) }

    public func anhalten() async { beiEreignis?(.zustand(.aus)) }

    /// Spricht `text` über `dauer` Sekunden: Zwischenstände Wort für Wort, dann der Satz mit gleichmäßigen Zeiten.
    public func sagen(_ text: String, dauer: Double) async {
        let teile = text.split(separator: " ").map(String.init)
        let beginn = ProcessInfo.processInfo.systemUptime
        let schritt = dauer / Double(max(1, teile.count))
        var worte: [SprachWort] = []
        for (i, t) in teile.enumerated() {
            try? await Task.sleep(for: .seconds(schritt))
            worte.append(.init(text: t, von: beginn + Double(i) * schritt, bis: beginn + Double(i + 1) * schritt))
            beiEreignis?(.pegel(0.6))
            beiEreignis?(.zwischenstand(teile[0...i].joined(separator: " ")))
        }
        beiEreignis?(.satz(text: text, worte: worte, von: beginn, bis: beginn + dauer))
    }
}

/// Auf einem System ohne Spracherkennung (vor macOS 26): Die Sitzung läuft ohne Text, Zeigen und Zeichnen bleiben.
@MainActor
final class KeineErkennung: Spracherkennung {
    let kennung = "keine"
    var beiEreignis: ((SprachEreignis) -> Void)?

    func starten() { beiEreignis?(.zustand(.fehler("Die Spracherkennung braucht macOS 26."))) }

    func anhalten() async {}
}
