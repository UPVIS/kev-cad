import AppKit
import KevCADCore
import PDFKit

/// Selbsttest „Bauplan und Export“ in der Testvariante (`KEVCAD_SELFTEST=bauplan-export`, Strang P6-A2): öffnet
/// `KEVCAD_SELFTEST_PROJEKT`, holt den Bauplan im Bereich Dokumente, zeigt Überblick und einzelne Schritte (hell und
/// dunkel), spielt einige Montageschritte im 3D-Bereich durch, setzt die Berichte, öffnet den Export-Dialog und
/// exportiert alle Bausteine als PDF. Bilder, PDF und Messwerte landen in `KEVCAD_SELFTEST_AUSGABE` (sonst im
/// Datenordner), Ergebnis in `selftest-dokumente.txt`. Ohne Maus- und Tastatureingaben; Fensterbilder über
/// `cacheDisplay` oder mit `KEVCAD_SELFTEST_FOTO_AUSSEN=1` von außen, das 3D-Bild über den Offscreen-Renderer.
/// `KEVCAD_SELFTEST_HALTEN=<s>` hält jeden Durchspielschritt so lange.
@MainActor
enum BauplanExportSelfTest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "bauplan-export"
    }

    /// Aus dem Willkommensfenster: das Projekt öffnen, sobald der Kernel bereit ist; das Projektfenster startet den Test.
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

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState, zustand: DokumenteZustand) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session, state, zustand) }
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-dokumente", isDirectory: true)
    }

    private static func run(_ session: AppSession, _ state: ProjectWindowState, _ zustand: DokumenteZustand) async {
        let model = session.model
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var messwerte: [String: Any] = [:]
        var passed = true
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Dokumente: \(line)"))
        }
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func foto(_ w: NSWindow?, _ name: String) async {
            // KEVCAD_SELFTEST_FOTO_AUSSEN=1: ein Werkzeug außerhalb fotografiert das echte Fenster (screencapture -l);
            // der Test schreibt den Auftrag und wartet auf das Bild (cacheDisplay zeigt Materialien und Steuerelemente
            // nicht vollständig)
            if env["KEVCAD_SELFTEST_FOTO_AUSSEN"] == "1", let w {
                let auftrag = ausgabe.appendingPathComponent("foto-auftrag.txt")
                let zeile = "\(w.windowNumber) \(name)\n"
                if let h = try? FileHandle(forWritingTo: auftrag) {
                    h.seekToEndOfFile()
                    h.write(zeile.data(using: .utf8)!)
                    try? h.close()
                } else {
                    try? zeile.write(to: auftrag, atomically: true, encoding: .utf8)
                }
                let ziel = ausgabe.appendingPathComponent(name + ".png")
                _ = await wait(8) { FileManager.default.fileExists(atPath: ziel.path) }
                return
            }
            guard let v = w?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else {
                check(false, "Bild \(name): kein Fenster")
                return
            }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        func bild3D(_ name: String) {
            guard let img = session.controller?.bauplanAnsichtsBild(hoehe: 900),
                  let d = ScreenshotRenderer.pngData(img)
            else { return }
            try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
        }

        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        check(await wait(400) { model.project != nil && !model.isRunning && model.bom != nil }, "Projekt offen, Lauf fertig")
        await pause(2)
        // Bauplan
        let t0 = Date()
        state.bereich = .dokumente
        zustand.waehle(.bauplan)
        model.bauplanActions?.bauplanAnfordern()
        check(await wait(400) { model.bauplan.plan != nil }, "Bauplan geladen")
        messwerte["bauplan_ms"] = Int(Date().timeIntervalSince(t0) * 1000)
        guard let plan = model.bauplan.plan else {
            lines.append("      Meldung: \(model.bauplan.meldung?.text ?? "keine")")
            return fertig(lines, messwerte, passed, model)
        }
        check(plan.alleSchritte.count > 0, "\(plan.alleSchritte.count) Schritte, \(model.bauplan.bilder.count) Bilder")
        messwerte["schritte"] = plan.alleSchritte.count
        await pause(1.5)
        let fenster = session.projectWindow
        await foto(fenster, "01-bauplan-ueberblick")
        // je Abschnitt ein Schritt, dazu der erste mit Problem
        var gezeigt: [String] = []
        for a in plan.abschnitte where !a.schritte.isEmpty {
            gezeigt.append(a.art == .montage ? (a.schritte.dropFirst().first ?? a.schritte[0]).id : a.schritte[0].id)
        }
        if let p = plan.alleSchritte.first(where: { !$0.probleme.isEmpty }) { gezeigt.append(p.id) }
        if let gross = plan.montage?.schritte.max(by: { $0.neu.count < $1.neu.count }) { gezeigt.append(gross.id) }
        for (i, id) in gezeigt.enumerated() {
            BauplanUI.shared.auswahl = id
            await pause(1.2)
            await foto(fenster, String(format: "02-schritt-%02d-%@", i + 1, plan.abschnitt(von: id)?.art.raw ?? "x"))
        }
        // dunkel
        fenster?.appearance = NSAppearance(named: .darkAqua)
        await pause(1.2)
        await foto(fenster, "03-schritt-dunkel")
        BauplanUI.shared.auswahl = nil
        await pause(1)
        await foto(fenster, "03-ueberblick-dunkel")
        fenster?.appearance = nil
        // Durchspielen (holt selbst den 3D-Bereich nach vorn)
        let halten = Double(env["KEVCAD_SELFTEST_HALTEN"] ?? "") ?? 0
        if let m = plan.montage, !m.schritte.isEmpty {
            model.bauplanActions?.durchspielenStarten(ab: nil)
            check(await wait(5) { model.bauplan.durchspielen != nil }, "Durchspielen gestartet")
            for k in 0..<min(4, m.schritte.count) {
                if k > 0 { model.bauplanActions?.durchspielenSchritt(1) }
                await pause(0.6)
                bild3D(String(format: "04-durchspielen-%02d-a-einfahren", k + 1))
                check(await wait(6) { (model.bauplan.durchspielen?.fortschritt ?? 0) >= 1 }, "Schritt \(k + 1) eingefahren")
                await pause(0.4)
                bild3D(String(format: "04-durchspielen-%02d-b-eingebaut", k + 1))
                if k == 1 {
                    check(state.bereich == .modell, "3D-Bereich vorn beim Durchspielen")
                    await foto(session.projectWindow, "04-durchspielen-fenster")
                }
                if let d = model.bauplan.durchspielen, let id = d.schritt,
                   let pose = BauplanAblauf.pose(plan, schritt: id, fortschritt: 1)
                {
                    let alle = Set(model.parts.map(\.id))
                    let sichtbar = alle.intersection(pose.sichtbar).count
                    lines.append("      Schritt \(id): \(sichtbar) von \(alle.count) Teilen sichtbar, \(pose.neu.count) neu")
                }
                if halten > 0 { await pause(halten) }
            }
            model.bauplanActions?.durchspielenBeenden()
            check(await wait(3) { model.bauplan.durchspielen == nil }, "Durchspielen beendet")
        }
        // Bearbeiten über BAUPLAN_EDIT (Projektkopie): Text, fest, verschieben, Reihenfolge, zusammenfassen
        if env["KEVCAD_SELFTEST_BEARBEITEN"] == "1", let a = model.bauplanActions, let m = plan.montage,
           m.schritte.count > 3, let mat = plan.abschnitte.first(where: { $0.art == .material }), mat.schritte.count > 2
        {
            func plan2() -> Bauplan? { model.bauplan.plan }
            let s1 = mat.schritte[0].id
            BauplanUI.shared.auswahl = s1
            let t = Date()
            a.bauplanBearbeiten([BauplanOp.text(schritt: s1, titel: "Einkaufsliste prüfen", text: "Selbsttest: Text von Kevin.")],
                                titel: "Text")
            check(await wait(60) { plan2()?.schritt(s1)?.quelle == "kevin" && plan2()?.schritt(s1)?.titel == "Einkaufsliste prüfen" },
                  "Text gesetzt (\(Int(Date().timeIntervalSince(t) * 1000)) ms bis zum neuen BAUPLAN)")
            check(BauplanUI.shared.auswahl == s1, "Auswahl bleibt nach neuem BAUPLAN")
            a.bauplanBearbeiten([BauplanOp.fest(schritt: s1, true)], titel: "fest")
            check(await wait(60) { plan2()?.schritt(s1)?.fest == true }, "Schritt fest")
            let ms = m.schritte.map(\.id)
            a.bauplanBearbeiten([BauplanOp.verschieben(schritt: ms[3], nach: ms[1])], titel: "verschieben")
            check(await wait(90) { (plan2()?.montage?.schritte.map(\.id).firstIndex(of: ms[3]) ?? -1) == 2 },
                  "Montageschritt verschoben: \(plan2()?.montage?.schritte.prefix(4).map(\.id) ?? [])")
            let regeln = plan2()?.vorher.count ?? 0
            a.bauplanBearbeiten([BauplanOp.vorher(a: ms[0], b: ms[3], grund: "Selbsttest")], titel: "Reihenfolge")
            check(await wait(90) { (plan2()?.vorher.count ?? 0) > regeln }, "Reihenfolge eingetragen")
            if let r = plan2()?.vorher.first(where: { $0.grund == "Selbsttest" }) {
                a.bauplanBearbeiten([BauplanOp.vorherLoeschen(index: r.index)], titel: "Reihenfolge löschen")
                check(await wait(60) { !(plan2()?.vorher.contains { $0.grund == "Selbsttest" } ?? true) }, "Reihenfolge gelöscht")
            }
            let anzahl = plan2()?.alleSchritte.count ?? 0
            a.bauplanBearbeiten([BauplanOp.zusammenfassen([mat.schritte[1].id, mat.schritte[2].id])], titel: "zusammenfassen")
            check(await wait(60) { (plan2()?.alleSchritte.count ?? 0) == anzahl - 1 }, "Zwei Schritte zusammengefasst")
            await pause(1)
            await foto(fenster, "07-nach-bearbeiten")
        }
        // Berichte
        state.bereich = .dokumente
        zustand.waehle(.berichte)
        await pause(6)
        await foto(fenster, "05-berichte-stueckliste")
        // Export-Dialog
        ExportDialogFenster.zeige(session: session, model: model)
        await pause(6)
        await foto(ExportDialogFenster.fenster, "06-export-dialog")
        if let w = ExportDialogFenster.fenster { w.sheetParent?.endSheet(w) ?? w.close() }
        // Export aller Bausteine, zweimal: erster Lauf mit Bildern, zweiter aus dem Zwischenspeicher
        let ziel = ausgabe.appendingPathComponent("\(model.project?.name ?? "Projekt") – alle Bausteine.pdf")
        for runde in 1...2 {
            let t = Date()
            do {
                let e = try await model.exportActions?.exportPDF(.standard, nach: ziel)
                let ms = Int(Date().timeIntervalSince(t) * 1000)
                check(e != nil, "Export \(runde): \(e?.seiten ?? 0) Seiten in \(ms) ms")
                messwerte["export_\(runde)_ms"] = ms
                messwerte["seiten"] = e?.seiten
                messwerte["formate"] = e?.formate
                messwerte["bausteine"] = e?.bausteine.map { "\($0.art.rawValue): \($0.seiten)" }
                messwerte["hinweise"] = e?.hinweise
            } catch {
                check(false, "Export \(runde): \(error)")
            }
        }
        if let pdf = PDFDocument(url: ziel) {
            check(pdf.pageCount > 5, "PDF lesbar, \(pdf.pageCount) Seiten, Gliederung \(pdf.outlineRoot?.numberOfChildren ?? 0)")
            messwerte["pdf_bytes"] = (try? FileManager.default.attributesOfItem(atPath: ziel.path)[.size]) as? Int
        }
        fertig(lines, messwerte, passed, model)
        if env["KEVCAD_SELFTEST_BLEIBEN"] != "1" {
            try? await Task.sleep(for: .seconds(1))
            NSApp.terminate(nil)
        }
    }

    private static func fertig(_ lines: [String], _ messwerte: [String: Any], _ passed: Bool, _ model: AppModel) {
        // Protokoll der App für die Fehlersuche
        let log = model.log.suffix(400).map { "\($0.level.rawValue): \($0.text)" }.joined(separator: "\n")
        try? log.write(to: ausgabe.appendingPathComponent("protokoll.txt"), atomically: true, encoding: .utf8)
        var text = lines.joined(separator: "\n")
        text += "\n\n" + (passed ? "Selbsttest Dokumente bestanden" : "Selbsttest Dokumente FEHLGESCHLAGEN") + "\n"
        try? text.write(to: ausgabe.appendingPathComponent("selftest-dokumente.txt"), atomically: true, encoding: .utf8)
        if let d = try? JSONSerialization.data(withJSONObject: messwerte, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: ausgabe.appendingPathComponent("messwerte.json"))
        }
    }
}
