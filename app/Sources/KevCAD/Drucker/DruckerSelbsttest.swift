import AppKit
import KevCADCore
import SwiftUI

/// Selbsttest „Drucken“ (Phase 8) in der Testvariante (`KEVCAD_SELFTEST=drucker`), nur gegen die Drucker-Attrappe
/// (`kernel/tools/drucker_attrappe.py --druckt`, Werte aus `KEVCAD_SELFTEST_ATTRAPPE` = Pfad zu `attrappe.json`):
///
/// 1. öffnet `KEVCAD_SELFTEST_PROJEKT` und wartet auf den Lauf; ohne Druckvorschau vom Kernel Beispieldaten aus dem Modell,
/// 2. sichert einen Drucker `selbsttest` auf 127.0.0.1 mit „Status lesen“; Seriennummer und Zugangscode der Attrappe
///    (Testwerte) gehen in den echten Schlüsselbund, der Kernel liest sie über `/usr/bin/security`,
/// 3. wartet auf „verbunden“ und den laufenden Druck der Attrappe, prüft, dass Steuern gesperrt ist,
/// 4. öffnet „Drucken …“, wartet auf das Vorbereiten (Bambu Studio slict), bestätigt Weg A (der Kernel öffnet Bambu
///    Studio mit `KEVCAD_DRUCKER_NICHT_OEFFNEN=1` nicht wirklich) und prüft die Datei im Projektordner,
/// 5. zeigt die Einstellungen, löscht danach die Zugangsdaten wieder.
///
/// Bilder und Ergebnis in `KEVCAD_SELFTEST_AUSGABE` (`selftest-drucker.txt`), ohne Maus- und Tastatureingaben.
@MainActor
enum DruckerSelbsttest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "drucker"
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-drucker", isDirectory: true)
    }

    static func projektOeffnen(_ session: AppSession) {
        guard gewuenscht, session.demo == nil,
              let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty
        else { return }
        Task { @MainActor in
            let ende = Date().addingTimeInterval(240)
            while Date() < ende, session.model.kernelState != .ready {
                try? await Task.sleep(for: .milliseconds(200))
            }
            if session.model.project == nil {
                session.model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
            }
        }
    }

    static func runIfRequested(_ session: AppSession) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session) }
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var passed = true
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Drucker: \(line)"))
        }
        func info(_ text: String) { lines.append("      \(text)") }
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func foto(_ w: NSWindow?, _ name: String) {
            guard let v = w?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        let drucker = model.drucker
        guard let actions = model.druckerActions else {
            check(false, "keine Drucker-Aktionen")
            return fertig(lines, passed, model)
        }
        // Attrappe
        guard let pfad = env["KEVCAD_SELFTEST_ATTRAPPE"],
              let d = try? Data(contentsOf: URL(fileURLWithPath: pfad)),
              let a = try? JSONDecoder().decode(JSONValue.self, from: d),
              let mqtt = a["mqtt_port"]?.intValue, let ftps = a["ftps_port"]?.intValue,
              let sn = a["seriennummer"]?.stringValue, let code = a["zugangscode"]?.stringValue
        else {
            check(false, "KEVCAD_SELFTEST_ATTRAPPE fehlt oder ist unlesbar (attrappe.json)")
            return fertig(lines, passed, model)
        }

        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        check(await wait(400) { model.project != nil && !model.isRunning && !model.parts.isEmpty }, "Projekt offen, Lauf fertig")
        check(await wait(15) { drucker.status != nil }, "PRINTER_STATUS vom Kernel")

        // Druckvorschau: vom Kernel oder Beispieldaten aus dem Modell (wie der Selbsttest der Druckvorschau)
        if !(await wait(8) { model.druck.vorschau != nil }) {
            session.controller?.druckSelbsttestEinspeisen(.vorschau(DruckBeispiel.ausModell(model, run: 901,
                                                                                             stand: .schaetzung),
                                                                    replyTo: nil))
            info("Kernel ohne Druckvorschau: Beispieldaten aus dem Modell")
        }
        let fenster = DruckTestFenster.zeige(model: model)

        // 2. Einstellungen sichern (Schlüsselbund)
        var e = DruckerEintrag(id: "selbsttest", name: "P1P Attrappe", ip: "127.0.0.1", weg: .a, statusLesen: true)
        e.portMqtt = mqtt
        e.portFtps = ftps
        do {
            try actions.druckerSpeichern(e, seriennummer: sn, zugangscode: code)
            check(drucker.zugangGespeichert, "Zugangsdaten im Schlüsselbund (Konto selbsttest)")
        } catch {
            check(false, "Sichern: \(error.localizedDescription)")
        }
        let datei = (try? String(contentsOf: drucker.dateiURL, encoding: .utf8)) ?? ""
        check(!datei.contains(code) && !datei.contains(sn), "drucker.json ohne Seriennummer und Zugangscode")

        // 3. Status lesend
        let verbunden = await wait(30) { drucker.status?.verbindung == .verbunden }
        check(verbunden, "verbunden (Kernel liest den Schlüsselbund über security): \(drucker.status?.meldung ?? "")")
        let druckt = await wait(20) { drucker.status?.druck?.zustand == .druckt }
        check(druckt, "Live-Status: \(drucker.status?.druck?.zustand.titel ?? "?"), "
            + "\(Int(((drucker.status?.druck?.fortschritt ?? 0) * 100).rounded())) %, Schicht "
            + "\(drucker.status?.druck?.schicht ?? 0)/\(drucker.status?.druck?.schichten ?? 0)")
        check(drucker.status?.steuern == false && drucker.status?.wegB.moeglich == false,
              "Steuern gesperrt, Weg B ausgegraut: \(drucker.status?.wegB.grund ?? "?")")
        check(drucker.status?.kamera == false, "keine Kamera")
        await pause(1)
        foto(fenster, "01-leiste-druckt")
        actions.druckerSteuern(.pause)
        check(drucker.fehler?.contains("Weg B") == true, "Pause in der App gesperrt")

        // 4. Drucken … (Weg A)
        actions.druckDialogOeffnen(platten: [])
        check(drucker.dialog != nil, "Dialog „Drucken …“ offen")
        let bereit = await wait(240) { drucker.dialog?.bestaetigbar == true || isFehler(drucker.dialog?.phase) }
        if case .bereit(let r) = drucker.dialog?.phase {
            check(bereit, "vorbereitet: \(r.gesliced.count) Platte(n), \(DruckFormat.zeit(r.zeitS)), "
                + DruckFormat.gramm(r.gramm))
        } else {
            check(false, "vorbereiten: \(String(describing: drucker.dialog?.phase))")
        }
        await pause(1)
        if let w = session.projectWindow, let s = w.attachedSheet { foto(s, "02-dialog-bereit") }
        actions.druckBestaetigen()
        let fertigOK = await wait(120) {
            if case .fertig = drucker.dialog?.phase { return true }
            return isFehler(drucker.dialog?.phase)
        }
        if case .fertig(let r) = drucker.dialog?.phase, let f = r.datei {
            check(fertigOK && r.schritt == "geoeffnet", "Weg A: \(f.lastPathComponent) (würde in Bambu Studio öffnen)")
            check(FileManager.default.fileExists(atPath: f.path)
                  && f.path.hasPrefix(model.project?.path.path ?? "/nirgends"), "Datei im Projektordner output/")
        } else {
            check(false, "bestätigen: \(String(describing: drucker.dialog?.phase))")
        }
        await pause(1)
        if let w = session.projectWindow, let s = w.attachedSheet { foto(s, "03-dialog-geoeffnet") }
        actions.druckDialogSchliessen()
        await pause(0.5)

        // 5. Einstellungen zeigen, Zugangsdaten löschen
        DruckerUI.shared.einstellungenOffen = true
        await pause(1.5)
        if let w = session.projectWindow, let s = w.attachedSheet { foto(s, "04-einstellungen") }
        DruckerUI.shared.einstellungenOffen = false
        await pause(0.5)
        do {
            try actions.druckerZugangLoeschen(id: "selbsttest")
            check(!drucker.zugangGespeichert, "Zugangsdaten gelöscht")
        } catch {
            check(false, "Löschen: \(error.localizedDescription)")
        }
        check(await wait(15) { drucker.status?.verbindung == .aus }, "Verbindung getrennt nach dem Löschen")
        fertig(lines, passed, model)
        if env["KEVCAD_SELFTEST_QUIT"] == "1" { NSApp.terminate(nil) }
    }

    private static func isFehler(_ p: DruckDialogZustand.Phase?) -> Bool {
        if case .fehler = p { return true }
        return false
    }

    private static func fertig(_ lines: [String], _ passed: Bool, _ model: AppModel) {
        let log = model.log.suffix(300).map { "\($0.level.rawValue): \($0.text)" }.joined(separator: "\n")
        try? log.write(to: ausgabe.appendingPathComponent("protokoll.txt"), atomically: true, encoding: .utf8)
        var text = lines.joined(separator: "\n")
        text += "\n\n" + (passed ? "Selbsttest Drucker bestanden" : "Selbsttest Drucker FEHLGESCHLAGEN") + "\n"
        try? text.write(to: ausgabe.appendingPathComponent("selftest-drucker.txt"), atomically: true, encoding: .utf8)
    }
}
