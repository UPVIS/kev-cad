import AppKit
import Foundation

// Druckvorschau (DRUCKVORSCHAU.md): PRINT_PREVIEW übernehmen, Einstellungen senden (PRINT_SETTINGS), Platten als 3MF
// exportieren (PRINT_EXPORT_REQ → ACK → PRINT_EXPORT_RES), die Datei in Bambu Studio öffnen und Teile aus dem Panel
// im 3D-Bereich auswählen. Der Kernel schickt PRINT_PREVIEW nach jedem Lauf mit Druckteilen von selbst.

extension AppController: DruckActions {
    /// Zeitlimit für ACK und Vorschau-Anfrage; ältere Kernel antworten gar nicht.
    static var druckTimeout: TimeInterval = 15
    /// Zeitlimit für das Ergebnis des 3MF-Exports nach dem ACK (Anordnen im Slicer kann dauern).
    static var druckExportTimeout: TimeInterval = 300

    func handleDruck(_ n: DruckNachricht) {
        switch n {
        case .vorschau(let v, _):
            let war = model.druck.vorschau
            model.druck.uebernehmen(v)
            if war?.run != v.run || war?.stand != v.stand {
                let platten = KevFormat.count(v.summe.platten, one: "Platte", many: "Platten")
                log(.info, "Druckvorschau (\(v.stand.titel)): \(platten), \(DruckFormat.zeit(v.summe.zeitMitWechselS)), "
                    + DruckFormat.gramm(v.summe.gramm) + (v.summe.kosten.map { ", \(DruckFormat.euro($0))" } ?? ""))
            }
            if let a = model.druck.aenderung, a.run == v.run, war?.stand != .slicer, v.stand == .slicer {
                log(.info, "\(a.titel): \(a.kurz)")
            }
        case .exportErgebnis(let e):
            druckExportFertig(e)
        }
    }

    /// Projektwechsel: die Vorschau gehört zum alten Projekt.
    func resetDruck() {
        model.druck.leeren()
    }

    /// Nach HELLO bzw. PROJECT: die Vorschau des offenen Projekts holen (still, ältere Kernel kennen sie nicht).
    func druckNachVerbinden() {
        guard !AppInfo.isDemoMode, helloReceived, model.project != nil else { return }
        druckvorschauAnfordern()
    }

    // MARK: DruckActions

    public func druckvorschauAnfordern() {
        guard !AppInfo.isDemoMode, helloReceived else { return }
        request(DruckvorschauAnfrage(id: nextRequestID()), timeout: Self.druckTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.druck):
                break  // schon in handle(_:) übernommen
            case .success(let m):
                self.log(.info, "Druckvorschau: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                let lower = e.message.lowercased()
                if lower.contains("keine antwort") || lower.contains("unbekannt") || lower.contains("unknown") {
                    self.model.druck.setzeNichtUnterstuetzt(self.model.druck.vorschau == nil)
                }
                self.log(.info, "Druckvorschau nicht erhalten (\(e.message))")
            }
        }
    }

    public func druckEinstellen(_ ziel: DruckZiel, einstellungen: [String: JSONValue]?, zweck: JSONValue?) {
        guard !AppInfo.isDemoMode else { return }
        guard helloReceived else {
            model.druck.setzeFehler("Der Kernel ist nicht verbunden, die Einstellung wurde nicht gesendet.")
            return
        }
        model.druck.setzeFehler(nil)
        model.druck.markiere(ziel)
        let msg = DruckEinstellenNachricht(id: nextRequestID(), ziel: ziel, einstellungen: einstellungen, zweck: zweck)
        let was = Self.druckBeschreibung(einstellungen: einstellungen, zweck: zweck)
        request(msg, timeout: Self.druckTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                self.log(.info, "Druck: \(was)" + (a.message.map { " (\($0))" } ?? ""))
            case .success(.ack(let a)):
                self.druckEinstellenFehler(ziel, a.message ?? "Der Kernel hat die Einstellung abgelehnt.")
            case .success(.druck):
                break  // Vorschau statt ACK: schon übernommen
            case .success(let m):
                self.druckEinstellenFehler(ziel, "Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.druckEinstellenFehler(ziel, e.message.contains("keine Antwort")
                    ? "Der Kernel antwortet nicht. Ältere Kernel-Versionen kennen die Druckvorschau noch nicht."
                    : e.message)
            }
        }
    }

    private func druckEinstellenFehler(_ ziel: DruckZiel, _ text: String) {
        model.druck.entmarkiere(ziel)
        model.druck.setzeFehler(text)
        log(.warning, "Druck: \(text)")
    }

    /// „Wände 4, Füllung zurückgesetzt“ für das Protokoll.
    static func druckBeschreibung(einstellungen: [String: JSONValue]?, zweck: JSONValue?) -> String {
        var t: [String] = []
        if let zweck {
            t.append(zweck.isNull ? "Zweck zurückgesetzt" : "Zweck \(DruckFormat.zweck(zweck.stringValue))")
        }
        for (k, v) in (einstellungen ?? [:]).sorted(by: { $0.key < $1.key }) {
            let titel = DruckFormat.schluessel(k)
            if v.isNull {
                t.append("\(titel) zurückgesetzt")
            } else if let d = v.doubleValue, k == "fuellung" {
                t.append("\(titel) \(DruckFormat.prozent(d))")
            } else if let s = v.stringValue {
                t.append("\(titel) \(k == "muster" ? DruckFormat.muster(s) : k == "stuetzen" ? DruckFormat.stuetzen(s) : s)")
            } else if let b = v.boolValue, case .bool = v {
                t.append("\(titel) \(b ? "an" : "aus")")
            } else if let d = v.doubleValue {
                t.append("\(titel) \(KevFormat.compact(d, maxDigits: 2))")
            }
        }
        return t.isEmpty ? "Einstellungen gesendet" : t.joined(separator: ", ")
    }

    public func druckExportieren(platten: [Int], nach ziel: URL) {
        guard !AppInfo.isDemoMode else { return }
        if case .laeuft = model.druck.export { return }
        guard helloReceived else {
            model.druck.setzeExport(.fehler("Der Kernel ist nicht verbunden, es wurde nichts exportiert."))
            return
        }
        let id = nextRequestID()
        model.druck.exportID = id
        model.druck.setzeExport(.laeuft(ziel: ziel))
        let msg = DruckExportNachricht(id: id, platten: platten, ziel: ziel.path)
        request(msg, timeout: Self.druckTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                // Ergebnis kommt als PRINT_EXPORT_RES; wartet höchstens druckExportTimeout
                DispatchQueue.main.asyncAfter(deadline: .now() + Self.druckExportTimeout) { [weak self] in
                    MainActor.assumeIsolated {
                        guard let self, self.model.druck.exportID == id, case .laeuft = self.model.druck.export else {
                            return
                        }
                        self.model.druck.exportID = nil
                        self.model.druck.setzeExport(.fehler("Der Kernel hat den Export nicht abgeschlossen."))
                    }
                }
            case .success(.ack(let a)):
                self.druckExportFehler(a.message ?? "Der Kernel hat den Export abgelehnt.")
            case .success(.druck(.exportErgebnis)):
                break  // schon übernommen
            case .success(let m):
                self.druckExportFehler("Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.druckExportFehler(e.message.contains("keine Antwort")
                    ? "Der Kernel antwortet nicht. Ältere Kernel-Versionen kennen den 3MF-Export noch nicht."
                    : e.message)
            }
        }
    }

    private func druckExportFehler(_ text: String) {
        model.druck.exportID = nil
        model.druck.setzeExport(.fehler(text))
        log(.warning, "3MF-Export: \(text)")
    }

    func druckExportFertig(_ e: DruckExportErgebnis) {
        if let id = model.druck.exportID, let r = e.replyTo, r != id { return }  // Antwort auf eine ältere Anfrage
        model.druck.exportID = nil
        guard e.ok, let pfad = e.pfad else {
            druckExportFehler(e.fehler ?? "Export fehlgeschlagen")
            return
        }
        model.druck.setzeExport(.fertig(e))
        let platten = e.platten.isEmpty ? "Platten" : KevFormat.count(e.platten.count, one: "Platte", many: "Platten")
        log(.info, "3MF-Export: \(platten) nach \(pfad.path)")
    }

    public func druckInBambuStudioOeffnen(_ datei: URL) {
        guard let app = DruckStore.bambuStudio else {
            model.druck.setzeFehler("Bambu Studio ist nicht unter /Applications installiert.")
            return
        }
        // nie im Selbsttest und nie in Tests ohne App-Bündel
        guard Bundle.main.bundleURL.pathExtension == "app", ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == nil
        else { return }
        let config = NSWorkspace.OpenConfiguration()
        config.activates = true
        NSWorkspace.shared.open([datei], withApplicationAt: app, configuration: config) { [weak self] _, error in
            guard let error else { return }
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    self?.model.druck.setzeFehler("Bambu Studio ließ sich nicht öffnen: \(error.localizedDescription)")
                }
            }
        }
        log(.info, "In Bambu Studio geöffnet: \(datei.lastPathComponent)")
    }

    public func druckTeileWaehlen(_ teile: [String], einpassen: Bool) {
        let refs = teile.compactMap(ElementRef.init).map(\.partRef)
        let (known, _) = scene.expand(refs)
        measurePending = []
        applySelection(known)
        if einpassen, !known.isEmpty, let b = scene.worldBounds(of: known) { viewport.fit(b, animated: true) }
    }
}
