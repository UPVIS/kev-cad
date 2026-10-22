import Foundation

/// Zustand von „Drucken“ (Phase 8), gepflegt vom App-Kern (AppController+Drucker); die Oberfläche liest und ruft
/// `DruckerActions`.
@MainActor
public final class DruckerStore: ObservableObject {
    /// Letzter PRINTER_STATUS (nil vor dem ersten, etwa bei älteren Kerneln).
    @Published public internal(set) var status: DruckerStatus?
    /// Inhalt von `drucker.json`.
    @Published public internal(set) var einstellungen = DruckerEinstellungenDatei()
    /// Stehen Zugangsdaten für den aktiven Drucker im Schlüsselbund?
    @Published public internal(set) var zugangGespeichert = false
    /// Offener Dialog „Drucken …“.
    @Published public internal(set) var dialog: DruckDialogZustand?
    /// Letzter Fehler einer Aktion (Einstellungen, Steuern), bis zur nächsten Aktion.
    @Published public internal(set) var fehler: String?
    /// Letzte Rückmeldung einer Steueraktion (Pause gesendet …).
    @Published public internal(set) var meldung: String?

    /// Wo die Zugangsdaten liegen (Tests: im Arbeitsspeicher) und wo `drucker.json` liegt.
    public var speicher: DruckerZugangsSpeicher = DruckerSchluesselbund()
    public var dateiURL: URL = DruckerEinstellungenDatei.standardURL()

    public init() {}

    public var aktiver: DruckerEintrag? { einstellungen.aktiver }

    /// Passt ein gefundener Drucker zum eingetragenen (über die Kennung, sonst die IP)?
    public func istEingetragen(_ g: GefundenerDrucker) -> Bool {
        guard let e = aktiver else { return false }
        if let k = e.kennung, !k.isEmpty { return k == g.kennung }
        return !e.ip.isEmpty && e.ip == g.ip
    }

    func setzeStatus(_ s: DruckerStatus) {
        status = s
        // Fortschritt des laufenden Auftrags in den Dialog spiegeln
        if var d = dialog, let a = s.auftrag, d.auftrag == a.auftrag {
            d.auftragZustand = a.zustand
            d.auftragMeldung = a.meldung
            dialog = d
        }
    }

    func setzeEinstellungen(_ e: DruckerEinstellungenDatei, zugang: Bool) {
        einstellungen = e
        zugangGespeichert = zugang
    }

    func setzeDialog(_ d: DruckDialogZustand?) { dialog = d }
    func setzeFehler(_ t: String?) { fehler = t }
    func setzeMeldung(_ t: String?) { meldung = t }

    func aendereDialog(_ f: (inout DruckDialogZustand) -> Void) {
        guard var d = dialog else { return }
        f(&d)
        dialog = d
    }
}

/// Zustand des Dialogs „Drucken …“.
public struct DruckDialogZustand: Equatable, Sendable, Identifiable {
    public enum Phase: Equatable, Sendable {
        /// Kernel slict (Vorbereiten)
        case bereitet
        /// gesliced, wartet auf Kevins Klick
        case bereit(DruckAuftragErgebnis)
        /// nach dem Klick: öffnet bzw. startet
        case laeuft
        /// geöffnet bzw. gestartet
        case fertig(DruckAuftragErgebnis)
        case fehler(String)
    }

    public var id: String { oeffnungsID }
    /// Je Öffnen neu (für `sheet(item:)`).
    public var oeffnungsID: String
    /// Gewählte Platten der Druckvorschau (leer = alle).
    public var platten: [Int]
    public var weg: DruckWeg
    public var optionen = DruckOptionen()
    /// Frage des Agenten (PRINT_JOB_ASK), sonst nil.
    public var frage: DruckFrage?
    public var auftrag: String?
    public var phase: Phase = .bereitet
    public var auftragZustand: DruckAuftragZustand?
    public var auftragMeldung: String?
    /// ID der letzten Vorbereiten-Anfrage (ältere Antworten verwerfen).
    var vorbereitenID: String?
    var bestaetigenID: String?

    public init(platten: [Int], weg: DruckWeg, frage: DruckFrage? = nil) {
        oeffnungsID = UUID().uuidString
        self.platten = platten
        self.weg = weg
        self.frage = frage
        auftrag = frage?.auftrag
    }

    /// Darf Kevin jetzt bestätigen?
    public var bestaetigbar: Bool {
        if case .bereit = phase { return true }
        return false
    }

    /// Plattenwahl so, dass nur ein Material dabei ist: Der P1P hat kein AMS, und die Druckvorschau liefert je Material
    /// ein Bambu-Projekt. Leer = alle (nur, wenn alle Platten ein Material haben); bei mehreren Materialien die Platten
    /// des ersten gewünschten Materials.
    public static func auswahl(_ gewuenscht: [Int], vorschau: Druckvorschau?) -> [Int] {
        guard let v = vorschau, !v.platten.isEmpty else { return gewuenscht }
        let alle = v.platten.map(\.nr)
        let mats = Set(v.platten.map { material($0.nr, v) })
        var wahl = (gewuenscht.isEmpty ? alle : gewuenscht).filter { alle.contains($0) }
        if wahl.isEmpty { wahl = alle }
        if mats.count > 1, let erstes = wahl.first.map({ material($0, v) }) {
            wahl = wahl.filter { material($0, v) == erstes }
        }
        if mats.count <= 1, Set(wahl) == Set(alle) { return [] }
        return wahl.sorted()
    }

    /// Nach einem Druck: die Platten des nächsten Materials (nil, wenn es keins mehr gibt).
    public static func naechste(nach platten: [Int], vorschau: Druckvorschau?) -> [Int]? {
        guard let v = vorschau, !platten.isEmpty else { return nil }
        var reihe: [String] = []
        for p in v.platten where !reihe.contains(material(p.nr, v)) { reihe.append(material(p.nr, v)) }
        guard let jetzt = reihe.firstIndex(of: material(platten[0], v)), jetzt + 1 < reihe.count else { return nil }
        let neu = reihe[jetzt + 1]
        return v.platten.filter { material($0.nr, v) == neu }.map(\.nr)
    }

    /// Material einer Platte (Kennung wie „petg“).
    public static func material(_ nr: Int, _ v: Druckvorschau) -> String {
        v.platten.first { $0.nr == nr }?.material.first?.material ?? "?"
    }
}

/// Aktionen von „Drucken“, implementiert vom App-Kern; die Oberfläche ruft sie über `model.druckerActions`.
@MainActor
public protocol DruckerActions: AnyObject {
    /// Einstellungen sichern (drucker.json) und an den Kernel geben; Seriennummer und Zugangscode, wenn angegeben, nur
    /// in den Schlüsselbund.
    func druckerSpeichern(_ eintrag: DruckerEintrag, seriennummer: String?, zugangscode: String?) throws
    /// Zugangsdaten des Druckers aus dem Schlüsselbund löschen (Status lesen geht danach nicht mehr).
    func druckerZugangLoeschen(id: String) throws
    func druckerStatusAnfordern()
    /// Dialog „Drucken …“ öffnen und schon vorbereiten (slicen).
    func druckDialogOeffnen(platten: [Int])
    /// Andere Platten oder anderer Weg: neu vorbereiten.
    func druckDialogAendern(platten: [Int], weg: DruckWeg)
    func druckDialogOptionen(_ o: DruckOptionen)
    /// Nach einem Fehler: noch einmal vorbereiten.
    func druckDialogNeuVorbereiten()
    /// Kevins Klick: Weg A öffnen in Bambu Studio, Weg B drucken.
    func druckBestaetigen()
    /// Dialog schließen; ein nicht bestätigter Auftrag wird verworfen.
    func druckDialogSchliessen()
    /// Pause, Fortsetzen, Abbruch (nur bei `status.steuern`) oder Bericht anfordern.
    func druckerSteuern(_ aktion: DruckerAktion)
    /// Datei im Finder zeigen.
    func druckDateiZeigen(_ datei: URL)
}

extension AppModel {
    /// Aktionen von „Drucken“ (nil im Demomodus).
    public var druckerActions: DruckerActions? { actions as? DruckerActions }
}
