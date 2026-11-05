import Foundation

// V2-6: Quelle für gesprochenen Text. Am Mac zuerst Wortlaut (`WortlautErkennung`); fehlt er, ist er belegt oder weist ab,
// hört Apples Erkennung zu (`AppleErkennung`, `ErkennungMitRueckfall`). Im Test ein Skript (`TestErkennung`). Alle Zeiten
// sind `ProcessInfo.systemUptime`, wie im Vorbild Sichtung; die Sitzung rechnet sie auf ihre Uhr um.

/// Stand der Erkennung, für die Oberfläche.
public enum SprachZustand: Equatable, Sendable {
    case aus
    case startet
    case hoert
    /// Kevin diktiert in Wortlaut; danach geht es weiter.
    case pausiert
    /// Vorübergehend nicht (das Sprachpaket lädt, Wortlaut hat kein Mikrofon). Der Satz ist für die Oberfläche.
    case laedt(String)
    /// Ohne Zutun beendet (Dienst fehlt, belegt, abgewiesen, kein Zugriff). Der Satz ist für die Oberfläche.
    case fehler(String)
    /// Die erste Quelle ist ausgefallen, jetzt hört der Rückfall zu.
    case rueckfall(String)
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
    /// Der angefangene Satz gilt nicht mehr.
    case verworfen
    case zustand(SprachZustand)
}

/// Eine Quelle für gesprochenen Text. Sie meldet alles auf dem Hauptfaden.
@MainActor
public protocol Spracherkennung: AnyObject {
    /// Fürs Paket: `wortlaut-parakeet`, `apple-dictation`, `apple-speech`, `test`.
    var kennung: String { get }
    /// Fürs Paket: `ton` (aus dem Ton gemessen) oder `geschaetzt`.
    var wortzeiten: String { get }
    var beiEreignis: ((SprachEreignis) -> Void)? { get set }
    /// Hört zu, bis `anhalten` kommt. Darf nach `anhalten` wieder gerufen werden (nächster Abschnitt).
    func starten()
    /// Hört auf und meldet die letzten Wörter; endet, wenn nichts mehr kommt, spätestens nach rund `s` Sekunden.
    func anhalten(hoechstens s: Double) async
}

/// Für Selbsttests und den Demomodus: kein Mikrofon, keine Rechteabfrage. Sätze kommen über `sagen`.
@MainActor
public final class TestErkennung: Spracherkennung {
    public let kennung = "test"
    public let wortzeiten = "ton"
    public var beiEreignis: ((SprachEreignis) -> Void)?

    public init() {}

    public func starten() { beiEreignis?(.zustand(.hoert)) }

    public func anhalten(hoechstens s: Double) async { beiEreignis?(.zustand(.aus)) }

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
    let wortzeiten = "ton"
    var beiEreignis: ((SprachEreignis) -> Void)?

    func starten() { beiEreignis?(.zustand(.fehler("Apples Spracherkennung braucht macOS 26."))) }

    func anhalten(hoechstens s: Double) async {}
}

/// Zuerst `erste`; meldet sie einen Fehler, solange zugehört werden soll, übernimmt der Rückfall bis zum Ende der Sitzung.
/// Die nächste Sitzung versucht es wieder zuerst mit `erste`: Belegt ist meist nur für den Moment.
@MainActor
public final class ErkennungMitRueckfall: Spracherkennung {
    private let erste: any Spracherkennung
    private let rueckfall: () -> any Spracherkennung
    private var aktiv: any Spracherkennung
    private var zuhoeren = false

    public var kennung: String { aktiv.kennung }
    public var wortzeiten: String { aktiv.wortzeiten }
    public var beiEreignis: ((SprachEreignis) -> Void)?

    public init(erste: any Spracherkennung, rueckfall: @escaping () -> any Spracherkennung) {
        self.erste = erste
        self.rueckfall = rueckfall
        aktiv = erste
        anbinden(erste)
    }

    public func starten() {
        zuhoeren = true
        aktiv.starten()
    }

    public func anhalten(hoechstens s: Double) async {
        zuhoeren = false
        await aktiv.anhalten(hoechstens: s)
    }

    private func anbinden(_ quelle: any Spracherkennung) {
        quelle.beiEreignis = { [weak self, weak quelle] e in
            guard let self, let quelle, quelle === self.aktiv else { return }
            self.empfangen(e, von: quelle)
        }
    }

    private func empfangen(_ e: SprachEreignis, von quelle: any Spracherkennung) {
        if case .zustand(.fehler(let grund)) = e, quelle === erste, zuhoeren {
            let neu = rueckfall()
            aktiv = neu
            anbinden(neu)
            beiEreignis?(.zustand(.rueckfall(grund)))
            neu.starten()
            return
        }
        beiEreignis?(e)
    }
}
