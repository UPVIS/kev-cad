import AppKit
import Foundation

// Bestand (BESTAND.md): BESTAND übernehmen, Posten und Einstellungen speichern, „Gebaut“ buchen, Buchungen rückgängig
// machen, Einkaufsliste als CSV schreiben. Nach jeder Buchung schickt der Kernel BESTAND und eine neue BOM von selbst.

extension AppController: BestandActions {
    /// Zeitlimit für Bestandsanfragen; ältere Kernel antworten gar nicht.
    static var bestandTimeout: TimeInterval = 15

    func applyBestand(_ message: BestandMessage) {
        var z = model.bestandZustand
        z.empfangen = true
        z.bestand = message.bestand
        z.buchungen = message.buchungen
        z.stand = message.stand
        model.bestandZustand = z
    }

    func applyBOMBestand(_ message: BOMMessage) {
        model.bestandZustand.zuschnitt = message.bestand
        if let b = message.bestand, b.fehlt, !b.einkaufsliste.isEmpty {
            let summe = b.summe.map { ", \(KevFormat.euro($0))" } ?? ""
            log(.info, "Einkaufsliste: \(KevFormat.count(b.einkaufsliste.count, one: "Position", many: "Positionen"))\(summe)")
        }
    }

    /// Neues Projekt: Zuschnitt und Buchungshinweis gehören zum alten (der Bestand folgt mit BESTAND).
    func bestandProjektGewechselt() {
        var z = model.bestandZustand
        z.zuschnitt = nil
        z.hinweis = nil
        z.aktivitaet = .idle
        model.bestandZustand = z
    }

    // MARK: BestandActions

    public func requestBestand() {
        guard !AppInfo.isDemoMode, helloReceived else { return }
        request(BestandRequestMessage(id: nextRequestID()), timeout: Self.bestandTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.bestand):
                break  // schon in handle(_:) übernommen
            case .success(let m):
                self.log(.warning, "Bestand: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.log(.info, "Bestand nicht erhalten (\(e.message))")
            }
        }
    }

    public func saveBestandPosten(id: String, posten: JSONValue?, grund: String) {
        sendBestandSave(BestandSaveMessage(id: nextRequestID(), postenID: id, posten: posten, grund: grund), was: grund)
    }

    public func saveBestandEinstellungen(_ einstellungen: BestandEinstellungen, grund: String) {
        sendBestandSave(BestandSaveMessage(id: nextRequestID(), einstellungen: einstellungen, grund: grund), was: grund)
    }

    private func sendBestandSave(_ msg: BestandSaveMessage, was: String) {
        guard !AppInfo.isDemoMode else { return }
        guard helloReceived else {
            model.bestandZustand.aktivitaet = .failed("Der Kernel ist nicht verbunden, der Bestand wurde nicht geändert.")
            return
        }
        model.bestandZustand.aktivitaet = .saving
        request(msg, timeout: Self.bestandTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                self.model.bestandZustand.aktivitaet = .idle
                self.log(.info, "Bestand: \(was)")
            case .success(.ack(let a)):
                self.bestandFailed(a.message ?? "Der Kernel hat die Änderung abgelehnt.")
            case .success(let m):
                self.bestandFailed("Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.bestandFailed(e.message.contains("keine Antwort")
                    ? "Der Kernel antwortet nicht. Ältere Kernel-Versionen kennen den Bestand noch nicht." : e.message)
            }
        }
    }

    private func bestandFailed(_ text: String) {
        model.bestandZustand.aktivitaet = .failed(text)
        log(.warning, "Bestand: \(text)")
    }

    public func bucheGebaut() {
        guard !AppInfo.isDemoMode else { return }
        guard let run = model.bom?.run else {
            bestandFailed("Es gibt noch keine Stückliste, nach der gebucht werden könnte.")
            return
        }
        guard helloReceived else {
            bestandFailed("Der Kernel ist nicht verbunden, es wurde nichts gebucht.")
            return
        }
        model.bestandZustand.aktivitaet = .saving
        request(GebautRequestMessage(id: nextRequestID(), run: run), timeout: Self.bestandTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                var z = self.model.bestandZustand
                z.aktivitaet = .idle
                z.hinweis = BuchungsHinweis(buchung: a.buchung, text: a.message ?? "Als gebaut gebucht.")
                self.model.bestandZustand = z
                self.log(.info, "Gebaut gebucht" + (a.buchung.map { " (\($0))" } ?? "") + (a.message.map { ": \($0)" } ?? ""))
            case .success(.ack(let a)):
                self.bestandFailed(a.message ?? "Der Kernel hat die Buchung abgelehnt.")
            case .success(let m):
                self.bestandFailed("Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.bestandFailed(e.message)
            }
        }
    }

    public func buchungRueckgaengig(_ id: String) {
        guard !AppInfo.isDemoMode else { return }
        guard helloReceived else {
            bestandFailed("Der Kernel ist nicht verbunden, die Buchung bleibt.")
            return
        }
        model.bestandZustand.aktivitaet = .saving
        request(BuchungRueckgaengigMessage(id: nextRequestID(), buchung: id), timeout: Self.bestandTimeout) {
            [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                var z = self.model.bestandZustand
                z.aktivitaet = .idle
                // Der Hinweis nach „Gebaut“ verschwindet, sobald diese Buchung zurückgenommen ist
                z.hinweis = BuchungsHinweis(buchung: nil, text: a.message ?? "Buchung \(id) rückgängig gemacht.")
                self.model.bestandZustand = z
                self.log(.info, "Buchung \(id) rückgängig gemacht" + (a.message.map { ": \($0)" } ?? ""))
            case .success(.ack(let a)):
                self.bestandFailed(a.message ?? "Der Kernel hat das Rückgängigmachen abgelehnt.")
            case .success(let m):
                self.bestandFailed("Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.bestandFailed(e.message)
            }
        }
    }

    public func verwerfeBuchungsHinweis() {
        var z = model.bestandZustand
        z.hinweis = nil
        if case .failed = z.aktivitaet { z.aktivitaet = .idle }
        model.bestandZustand = z
    }

    public func exportEinkaufsliste() {
        guard let project = model.project, let z = model.bestandZustand.zuschnitt else { return }
        let ordner = project.path.appendingPathComponent("output", isDirectory: true)
        let datei = ordner.appendingPathComponent(EinkaufslisteFormat.dateiname(projekt: project.name))
        do {
            try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
            try Data(EinkaufslisteFormat.csv(z.einkaufsliste, summe: z.summe).utf8).write(to: datei, options: .atomic)
            log(.info, "Einkaufsliste gespeichert: \(datei.path)")
            revealFiles([datei])
        } catch {
            bestandFailed("Einkaufsliste nicht gespeichert: \(error.localizedDescription)")
        }
    }
}
