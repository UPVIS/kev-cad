import AppKit
import KevCADCore
import SwiftUI

/// Testfenster der Druckvorschau: Schnellansicht oben, volle Ansicht darunter, so wie der Material-Strang beide einbaut.
/// Nur für den Selbsttest (die Testvariante legt es auf den zweiten Monitor).
@MainActor
enum DruckTestFenster {
    private(set) static var fenster: NSWindow?

    static func zeige(model: AppModel, groesse: NSSize = NSSize(width: 1320, height: 760)) -> NSWindow {
        if let w = fenster {
            w.setContentSize(groesse)
            w.orderFrontRegardless()
            return w
        }
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: groesse),
                         styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        w.title = "Druckvorschau (Test)"
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: VStack(spacing: 0) {
            DruckKompakt(model: model)
                .background(.bar)
            Divider()
            DruckAnsicht(model: model)
        })
        fenster = w
        platzieren(w)
        w.orderFrontRegardless()
        return w
    }

    /// Auf den zweiten Monitor, oben rechts (das Projektfenster liegt oben links).
    static func platzieren(_ w: NSWindow) {
        let screens = NSScreen.screens
        guard AppInfo.isTestVariant, screens.count > 1 else {
            w.center()
            return
        }
        let f = screens[1].visibleFrame
        let size = NSSize(width: min(w.frame.width, f.width - 60), height: min(w.frame.height, f.height - 60))
        w.setFrame(NSRect(x: f.maxX - size.width - 30, y: f.maxY - size.height - 30, width: size.width,
                          height: size.height), display: true)
    }
}

/// Selbsttest der Druckvorschau in der Testvariante (`KEVCAD_SELFTEST=druck`): öffnet `KEVCAD_SELFTEST_PROJEKT`,
/// wartet auf den Lauf und auf PRINT_PREVIEW vom Kernel. Rechnet der Kernel die Vorschau noch nicht, nimmt er die
/// Beispieldaten aus `KEVCAD_SELFTEST_DRUCK_DATEI` (z. B. `protocol.druckvorschau_beispiel()`) oder baut eine
/// Vorschau aus den Druckteilen des Modells (gleiche Teilenamen, damit die Auswahl in beide Richtungen prüfbar ist).
/// Prüft dann Auswahl Panel ↔ 3D, Blättern, Wechsel Schätzung → Bambu Studio mit Hinweis, Einstellungen, 3MF-Export,
/// Bericht-Baustein und hell/dunkel. Bilder und Messwerte in `KEVCAD_SELFTEST_AUSGABE`, Ergebnis in
/// `selftest-druck.txt`. Ohne Maus- und Tastatureingaben; Fensterbilder mit `KEVCAD_SELFTEST_FOTO_AUSSEN=1` von außen.
@MainActor
enum DruckSelfTest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "druck"
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-druck", isDirectory: true)
    }

    /// Aus dem Willkommensfenster: das Projekt öffnen, sobald der Kernel bereit ist.
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

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState? = nil) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session, state) }
    }

    private static func run(_ session: AppSession, _ state: ProjectWindowState?) async {
        let model = session.model
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var messwerte: [String: Any] = [:]
        var passed = true
        // Hintergrund (open -g): ohne Aktivität drosselt App Nap die Zeitgeber
        let aktivitaet = ProcessInfo.processInfo.beginActivity(options: [.userInitiated], reason: "Selbsttest Druck")
        defer { ProcessInfo.processInfo.endActivity(aktivitaet) }
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: ausgabe.appendingPathComponent("foto-auftrag.txt"))
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Druck: \(line)"))
        }
        func info(_ text: String) {
            lines.append("      \(text)")
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
            guard let v = w?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        let ui = DruckUI.shared
        let druck = model.druck
        let controller = session.controller
        let projektFenster = { session.projectWindow }

        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        let tLauf = Date()
        check(await wait(600) { model.project != nil && !model.isRunning && !model.parts.isEmpty }, "Projekt offen, Lauf fertig")
        info("\(model.parts.count) Teile im Modell")

        // 1. Vorschau vom Kernel (nach dem Lauf von selbst), sonst Beispieldaten
        let vomKernel = await wait(Double(env["KEVCAD_SELFTEST_DRUCK_WARTEN"] ?? "") ?? 60) { druck.vorschau != nil }
        messwerte["vorschau_vom_kernel"] = vomKernel
        if vomKernel, let v = druck.vorschau {
            messwerte["vorschau_nach_lauf_ms"] = Int(Date().timeIntervalSince(tLauf) * 1000)
            if let ms = v.ms { messwerte["schaetzung_kernel_ms"] = ms }
            info("PRINT_PREVIEW vom Kernel: \(v.stand.titel), Slicer \(v.slicer.zustand.rawValue)"
                 + (v.slicer.meldung.map { " (\($0))" } ?? ""))
        } else {
            let beispiel: Druckvorschau
            if let pfad = env["KEVCAD_SELFTEST_DRUCK_DATEI"], let d = try? Data(contentsOf: URL(fileURLWithPath: pfad)),
               let j = try? JSONDecoder().decode(JSONValue.self, from: d)
            {
                beispiel = Druckvorschau(json: j)
                info("Kernel ohne Druckvorschau: Beispieldaten aus \(URL(fileURLWithPath: pfad).lastPathComponent)")
            } else {
                beispiel = DruckBeispiel.ausModell(model, run: 900, stand: .schaetzung)
                info("Kernel ohne Druckvorschau: Vorschau aus den Druckteilen des Modells")
            }
            controller?.druckSelbsttestEinspeisen(.vorschau(beispiel, replyTo: nil))
        }
        guard let v0 = druck.vorschau, !v0.istLeer else {
            check(false, "keine Vorschau mit Druckteilen: \(druck.vorschau?.slicer.meldung ?? "–")")
            return fertig(lines, messwerte, passed, model)
        }
        let ersteSchaetzung = v0.stand != .slicer
        check(true, "Vorschau: \(v0.summe.platten) Platten, \(v0.teile.count) Gruppen, \(v0.stueck) Stück, "
            + "\(DruckFormat.zeit(v0.summe.zeitMitWechselS)), \(DruckFormat.gramm(v0.summe.gramm)), "
            + (v0.summe.kosten.map(DruckFormat.euro) ?? "–") + ", \(v0.stand.titel)")
        for p in v0.platten {
            let raus = DruckPlattenGeometrie.ausserhalb(p, bett: v0.bett)
            check(raus.isEmpty, "Platte \(p.nr) (\(p.material.first?.material.uppercased() ?? "?")): "
                + "\(KevFormat.count(p.teile.count, one: "Teil", many: "Teile")), alles auf der Platte und außerhalb der Sperrzone"
                + (raus.isEmpty ? "" : " (\(raus.joined(separator: ", ")))"))
        }
        let bekannte = Set(model.parts.map(\.id))
        let namen = Set(v0.platten.flatMap(\.teile).map(\.name))
        check(!vomKernel || namen.isSubset(of: bekannte),
              "Teilenamen der Platten im Modell: \(namen.intersection(bekannte).count) von \(namen.count)")

        // 2. Testfenster: Schnellansicht und volle Ansicht mit Druckerleiste
        let fenster = DruckTestFenster.zeige(model: model)
        ui.auswahl = nil
        ui.nebeneinander = false
        ui.platte = v0.platten.first?.nr ?? 1
        model.actions?.select([])
        await pause(2)
        if druck.vorschau?.slicer.laeuft == true { await foto(fenster, "01-ansicht-slicer-rechnet") }

        // 3. Auswahl Panel → 3D und 3D → Panel
        if let g = v0.teile.filter({ !Set($0.teile).isDisjoint(with: bekannte) }).max(by: { $0.anzahl < $1.anzahl }) {
            ui.waehle(g, vorschau: v0, model: model)
            await pause(0.6)
            check(Set(model.selectedPartIDs) == Set(g.teile).intersection(bekannte),
                  "Gruppe „\(g.kurzname)“ gewählt: \(model.selectedPartIDs.count) Teile im 3D ausgewählt")
        }
        if let t = v0.platten.reversed().flatMap(\.teile).first(where: { bekannte.contains($0.name) && $0.gruppe != ui.auswahl }) {
            model.actions?.select([t.name])
            let g = v0.gruppe(vonTeil: t.name)
            check(await wait(3) { ui.auswahl == g?.gruppe }, "Auswahl im 3D (\(DruckFormat.teilname(t.name))) wählt die Gruppe \(g?.kurzname ?? "?")")
            let p = v0.platte(vonTeil: t.name)?.nr
            check(await wait(3) { ui.platte == p }, "und blättert zu Platte \(p ?? 0)")
        }

        // 4. Bambu Studio rechnet nach (echter Kernel): Wechsel Schätzung → Slicer mit Hinweis
        if vomKernel {
            let tSlicer = Date()
            let fertigGerechnet = await wait(Double(env["KEVCAD_SELFTEST_SLICER_WARTEN"] ?? "") ?? 900) {
                druck.vorschau?.stand == .slicer && druck.vorschau?.slicer.laeuft == false
            }
            let v = druck.vorschau
            check(fertigGerechnet, "Bambu Studio: \(v?.stand.titel ?? "?"), \(v?.slicer.meldung ?? v?.slicer.zustand.rawValue ?? "–")"
                  + " nach \(Int(Date().timeIntervalSince(tSlicer))) s")
            messwerte["slicer_s"] = Int(Date().timeIntervalSince(tSlicer))
            if let a = druck.aenderung {
                check(true, "Hinweis nach Bambu Studio: \(a.kurz)")
                info(a.werte.map(\.zeile).joined(separator: " · "))
            } else {
                info(ersteSchaetzung ? "kein Hinweis (keine Änderung?)" : "erste Vorschau kam schon aus dem Zwischenspeicher des Slicers")
            }
            for g in v?.teile ?? [] {
                info("\(g.kurzname) × \(g.anzahl): \(DruckFormat.zeit(g.zeitS)), \(DruckFormat.gramm(g.g)), \(g.stand.titel)"
                     + (g.abweichung.map { ", Schätzung \(DruckFormat.aenderung(-$0 / (1 + $0)))" } ?? "")
                     + " · \(DruckFormat.kurz(g.einstellungen)) · \(g.profilProzess ?? "–") · \(g.profilFilament ?? "–")")
            }
        } else if let v = druck.vorschau {
            var halb = DruckBeispiel.slicerVersion(v, faktorZeit: 1.06, faktorGramm: 1.01, fertig: false)
            halb.stand = .gemischt
            controller?.druckSelbsttestEinspeisen(.vorschau(halb, replyTo: nil))
            controller?.druckSelbsttestEinspeisen(.vorschau(
                DruckBeispiel.slicerVersion(v, faktorZeit: 1.12, faktorGramm: 0.97, fertig: true), replyTo: nil))
            check(druck.aenderung != nil, "Hinweis nach Bambu Studio (Beispieldaten): \(druck.aenderung?.kurz ?? "fehlt")")
        }
        await pause(1)
        if let g = druck.vorschau?.teile.first { ui.waehle(g, vorschau: druck.vorschau, model: model) }
        await pause(1.2)
        await foto(fenster, "02-ansicht-bambu-studio")

        // 5. PRINT_SETTINGS: Wände der ersten Gruppe +1 (fest „von Kevin“), dann zurücksetzen
        if vomKernel, let g = druck.vorschau?.teile.first {
            let ziel = DruckZiel.gruppe(g.gruppe)
            let w0 = g.einstellungen.waende ?? 3
            var t = Date()
            model.druckActions?.druckEinstellen(ziel, einstellungen: ["waende": .number(Double(w0 + 1))], zweck: nil)
            let gesetzt = await wait(60) {
                druck.vorschau?.gruppe(g.gruppe)?.einstellungen.waende == w0 + 1 && !druck.wartet(ziel)
            }
            messwerte["einstellen_ms"] = Int(Date().timeIntervalSince(t) * 1000)
            let g2 = druck.vorschau?.gruppe(g.gruppe)
            check(gesetzt && druck.fehler == nil, "PRINT_SETTINGS Wände \(w0) → \(w0 + 1): neue Vorschau nach "
                  + "\(messwerte["einstellen_ms"] ?? 0) ms" + (druck.fehler.map { " (\($0))" } ?? ""))
            check(g2?.quelle("waende") == .kevin, "fest_von: Wände \(g2?.quelle("waende")?.titel ?? "ohne Quelle")")
            await pause(1)
            await foto(fenster, "03-vorgabe-von-kevin")
            // Bambu Studio rechnet die geänderte Gruppe nach
            let nach = await wait(300) { druck.vorschau?.gruppe(g.gruppe)?.stand == .slicer && druck.vorschau?.slicer.laeuft == false }
            info("geänderte Gruppe nachgerechnet: \(nach ? "ja" : "nein"), \(druck.vorschau.map { DruckFormat.zeit($0.summe.zeitMitWechselS) } ?? "–")")
            t = Date()
            model.druckActions?.druckZuruecksetzen(ziel, schluessel: ["waende"])
            let zurueck = await wait(60) {
                druck.vorschau?.gruppe(g.gruppe)?.quelle("waende") == nil && !druck.wartet(ziel)
            }
            check(zurueck && druck.vorschau?.gruppe(g.gruppe)?.einstellungen.waende == w0,
                  "Zurücksetzen: Wände wieder \(druck.vorschau?.gruppe(g.gruppe)?.einstellungen.waende ?? -1), ohne Vorgabe "
                  + "(\(Int(Date().timeIntervalSince(t) * 1000)) ms)")
            _ = await wait(300) { druck.vorschau?.slicer.laeuft == false }
        }

        // 6. Als 3MF sichern (je Material eine Datei)
        let ziel = (model.project?.path ?? ausgabe).appendingPathComponent("output/selbsttest-druck.3mf")
        let tExport = Date()
        model.druckActions?.druckExportieren(platten: [], nach: ziel)
        let exportFertig = await wait(Double(env["KEVCAD_SELFTEST_EXPORT_WARTEN"] ?? "") ?? 420) { !druck.export.laeuftGerade }
        messwerte["export_ms"] = Int(Date().timeIntervalSince(tExport) * 1000)
        if case .fertig(let e) = druck.export {
            let da = e.dateien.filter { FileManager.default.fileExists(atPath: $0.pfad.path) }
            check(exportFertig && da.count == e.dateien.count && !da.isEmpty,
                  "3MF: \(KevFormat.count(e.dateien.count, one: "Datei", many: "Dateien")) in \(messwerte["export_ms"] ?? 0) ms, "
                  + (e.geprueft == true ? "in Bambu Studio geprüft" : "ungeprüft"))
            for d in e.dateien {
                let bytes = (try? FileManager.default.attributesOfItem(atPath: d.pfad.path)[.size] as? Int) ?? 0
                info("\(d.pfad.lastPathComponent): \(d.material ?? "?"), Platten \(d.platten), \(d.filament ?? "–"), \(bytes / 1024) KB")
            }
            messwerte["export_dateien"] = e.dateien.map(\.pfad.lastPathComponent)
        } else if vomKernel {
            check(false, "3MF-Export: \(druck.export)")
        } else {
            info("3MF-Export über den Kernel: \(druck.export)")
            controller?.druckSelbsttestEinspeisen(.exportErgebnis(DruckExportErgebnis(
                ok: true, pfad: ziel, platten: druck.vorschau?.platten.map(\.nr) ?? [])))
        }
        await pause(1)
        await foto(fenster, "04-als-3mf-gesichert")
        druck.exportHinweisVerwerfen()
        druck.aenderungVerwerfen()

        // 7. „Drucken …“ der Druckerleiste öffnet den Dialog von Phase 8 (am Projektfenster), getrennt vom 3MF-Sichern
        if let d = model.druckerActions {
            d.druckDialogOeffnen(platten: [])
            let offen = await wait(10) { model.drucker.dialog != nil }
            check(offen, "„Drucken …“ öffnet den Dialog von Phase 8")
            await pause(2)
            await foto(projektFenster(), "05-drucken-dialog")
            d.druckDialogSchliessen()
            _ = await wait(10) { model.drucker.dialog == nil }
        }

        // 8. Bereich Material: Abschnitt „Druckteile“ und Schnellansicht „Druck“, hell und dunkel
        DruckTestFenster.fenster?.orderOut(nil)
        if let state, let w = projektFenster() {
            state.materialZustand.zeige(.druck)
            state.zeige(.material)
            await pause(2.5)
            await foto(w, "06-material-druckteile-hell")
            w.appearance = NSAppearance(named: .darkAqua)
            await pause(1.5)
            await foto(w, "07-material-druckteile-dunkel")
            w.appearance = nil
            state.zeige(.modell)
            var s = state.schnell
            s.offen = [.druck]
            state.schnell = s
            await pause(2)
            await foto(w, "08-schnellansicht-druck-hell")
            w.appearance = NSAppearance(named: .darkAqua)
            await pause(1.5)
            await foto(w, "09-schnellansicht-druck-dunkel")
            w.appearance = nil
            s.offen = []
            state.schnell = s
            await pause(1.5)
            await foto(w, "10-schnellansicht-eingeklappt")
            check(true, "Bereich Material und Schnellansicht gezeigt")
        } else {
            info("kein Projektfenster: Bereich Material nicht geprüft")
        }

        // 9. Bericht-Baustein
        if let actions = model.exportActions {
            let vorlage = ExportVorlage(name: "Druck", bausteine: [ExportBausteinWahl(art: .druck)])
            let pdf = ausgabe.appendingPathComponent("druck-bericht.pdf")
            do {
                let t = Date()
                let e = try await actions.exportPDF(vorlage, nach: pdf)
                let seiten = e.bausteine.first { $0.art == .druck }?.seiten ?? 0
                check(seiten > 0, "Bericht 3D-Druck: \(seiten) Seiten in \(Int(Date().timeIntervalSince(t) * 1000)) ms")
                let doc = await actions.exportDokument(vorlage)
                if let img = doc.bild(min(1, doc.seiten.count - 1), pixelJeMM: 4), let d = ScreenshotRenderer.pngData(img) {
                    try? d.write(to: ausgabe.appendingPathComponent("20-bericht.png"))
                }
            } catch {
                check(false, "Bericht: \(error)")
            }
        }
        messwerte["platten"] = druck.vorschau?.summe.platten
        messwerte["gruppen"] = druck.vorschau?.teile.count
        messwerte["stand"] = druck.vorschau?.stand.rawValue
        fertig(lines, messwerte, passed, model)
        if env["KEVCAD_SELFTEST_BLEIBEN"] != "1" {
            try? await Task.sleep(for: .seconds(1))
            NSApp.terminate(nil)
        }
    }

    private static func fertig(_ lines: [String], _ messwerte: [String: Any], _ passed: Bool, _ model: AppModel) {
        let log = model.log.suffix(300).map { "\($0.level.rawValue): \($0.text)" }.joined(separator: "\n")
        try? log.write(to: ausgabe.appendingPathComponent("protokoll.txt"), atomically: true, encoding: .utf8)
        var text = lines.joined(separator: "\n")
        text += "\n\n" + (passed ? "Selbsttest Druck bestanden" : "Selbsttest Druck FEHLGESCHLAGEN") + "\n"
        try? text.write(to: ausgabe.appendingPathComponent("selftest-druck.txt"), atomically: true, encoding: .utf8)
        if let d = try? JSONSerialization.data(withJSONObject: messwerte, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: ausgabe.appendingPathComponent("messwerte.json"))
        }
    }
}

/// Beispieldaten des Selbsttests nach dem Vertrag, aus den Druckteilen des offenen Modells: gleiche Teile (Material und
/// Maße) bilden eine Gruppe, die Grundfläche ist das Hüllrechteck auf der größten Seite, angeordnet in Reihen je
/// Material mit 6 mm Abstand, vorn links frei. Zeit und Filament grob (PETG 1,27 g/cm³, 25 g/h, 17 €/kg).
enum DruckBeispiel {
    static let dichte: [String: Double] = ["petg": 1.27, "pla": 1.24, "asa": 1.07, "abs": 1.04, "tpu-95a": 1.21]

    @MainActor
    static func ausModell(_ model: AppModel, run: Int, stand: DruckStand) -> Druckvorschau {
        let druckteile = model.parts.filter { p in
            p.stock == nil && p.zukauf == nil && (p.name.contains("(Druck)") || dichte[p.material ?? ""] != nil)
        }
        struct Teil { var name: String; var material: String; var masse: [Double]; var g: Double }
        let teile: [Teil] = druckteile.map { p in
            let s = p.bboxMax - p.bboxMin
            let m = [Double(s.x), Double(s.y), Double(s.z)].sorted(by: >)
            let mat = (p.material ?? "petg").lowercased()
            let voll = p.mass ?? (p.volume ?? m[0] * m[1] * m[2] * 0.3) * (dichte[mat] ?? 1.27) / 1000
            return Teil(name: p.id, material: mat, masse: m, g: voll * 0.45)
        }
        // Gruppen nach Material und Maßen (auf 0,5 mm)
        var gruppen: [(key: String, teile: [Teil])] = []
        for t in teile {
            let key = t.material + "|" + t.masse.map { String(format: "%.1f", ($0 * 2).rounded() / 2) }.joined(separator: "x")
            if let i = gruppen.firstIndex(where: { $0.key == key }) { gruppen[i].teile.append(t) } else { gruppen.append((key, [t])) }
        }
        let jeGramm = 3600.0 / 28
        var vorschauTeile: [DruckGruppe] = []
        var gruppeVon: [String: String] = [:]
        for (i, g) in gruppen.enumerated() {
            let id = "g\(i + 1)"
            let name = g.teile[0].name.split(separator: "/").last.map(String.init) ?? g.teile[0].name
            let kurz = name.replacingOccurrences(of: #" (vorn|hinten|links|rechts|oben|unten|\d+)"#, with: "",
                                                options: .regularExpression)
            let gramm = g.teile.reduce(0) { $0 + $1.g }
            let lower = kurz.lowercased()
            let zweck = lower.contains("halter") || lower.contains("träger") ? "tragend"
                : lower.contains("rolle") || lower.contains("schlitten") ? "bewegt" : "funktion"
            let e: DruckEinstellungen
            switch zweck {
            case "tragend": e = DruckEinstellungen(schichtMM: 0.2, waende: 4, decken: 5, boeden: 4, fuellung: 0.25, muster: "gyroid",
                                                  stuetzen: "keine", brim: false, ausrichtung: "größte Fläche unten")
            case "bewegt": e = DruckEinstellungen(schichtMM: 0.16, waende: 4, decken: 6, boeden: 4, fuellung: 0.3, muster: "gyroid",
                                                 stuetzen: "baum", brim: false, ausrichtung: "Lauffläche senkrecht")
            default: e = DruckEinstellungen(schichtMM: 0.2, waende: 3, decken: 5, boeden: 3, fuellung: 0.2, muster: "grid",
                                           stuetzen: "keine", brim: g.teile[0].masse[2] > 2.5 * g.teile[0].masse[1],
                                           ausrichtung: "größte Fläche unten")
            }
            var hinweise: [DruckpraxisHinweis] = []
            if g.teile[0].material == "petg" {
                hinweise.append(DruckpraxisHinweis(schwere: .hinweis, text: "PETG vorher trocknen (65 °C, 12 h).", art: "trocknen"))
            }
            if e.stuetzen == "baum" {
                hinweise.append(DruckpraxisHinweis(schwere: .warnung, text: "Braucht Stützen unter der Lauffläche: Nacharbeit einplanen.",
                                                   art: "stuetzen"))
            }
            if e.brim == true {
                hinweise.append(DruckpraxisHinweis(schwere: .hinweis, text: "Brim 5 mm: kleine Auflage bei großer Höhe.", art: "brim"))
            }
            let begruendung = [
                "\(zweck): \(DruckFormat.waende(e.waende ?? 3)), \(DruckFormat.prozent(e.fuellung ?? 0.2)) \(DruckFormat.muster(e.muster))",
                zweck == "tragend" ? "Last längs der Schichten: liegend drucken" : "Standardwerte für \(DruckFormat.zweck(zweck))",
            ]
            var gr = DruckGruppe(
                gruppe: id, name: kurz + (kurz.contains("(Druck)") ? "" : " (Druck)"), teile: g.teile.map(\.name),
                anzahl: g.teile.count, material: g.teile[0].material, zweck: zweck, zweckGeschaetzt: zweck == "funktion",
                g: gramm, m: gramm / (dichte[g.teile[0].material] ?? 1.27) / 2.405, zeitS: gramm * jeGramm,
                kosten: gramm * 0.017, stand: stand, einstellungen: e, begruendung: begruendung, hinweise: hinweise)
            gr.jeStueck = DruckJeStueck(g: gramm / Double(g.teile.count), zeitS: gramm * jeGramm / Double(g.teile.count))
            gr.risiko = zweck == "bewegt" ? 0.12 : 0.04
            vorschauTeile.append(gr)
            for t in g.teile { gruppeVon[t.name] = id }
        }
        // Anordnen: je Material Reihen auf 256 × 256, 6 mm Abstand, vorn links 18 × 28 frei
        var platten: [DruckPlatte] = []
        let abstand = 6.0, bett = 256.0
        for mat in Array(Set(teile.map(\.material))).sorted() {
            let liste = teile.filter { $0.material == mat }.sorted { $0.masse[1] > $1.masse[1] }
            var x = 18 + abstand, y = abstand, reihe = 0.0
            var aktuell: [DruckPlattenTeil] = []
            func neuePlatte() {
                if !aktuell.isEmpty { platten.append(DruckPlatte(nr: platten.count + 1, teile: aktuell)) }
                aktuell = []
                x = 18 + abstand
                y = abstand
                reihe = 0
            }
            for t in liste {
                let b = min(t.masse[0], bett - 2 * abstand), d = min(t.masse[1], bett - 2 * abstand)
                if x + b > bett - abstand {
                    x = abstand
                    y += reihe + abstand
                    reihe = 0
                }
                if y + d > bett - abstand { neuePlatte() }
                let u = [SIMD2(x, y), SIMD2(x + b, y), SIMD2(x + b, y + d), SIMD2(x, y + d)]
                aktuell.append(DruckPlattenTeil(name: t.name, gruppe: gruppeVon[t.name], x: x + b / 2, y: y + d / 2, umriss: u,
                                                index: aktuell.count))
                x += b + abstand
                reihe = max(reihe, d)
            }
            neuePlatte()
        }
        for i in platten.indices {
            let gramm = platten[i].teile.reduce(0.0) { s, t in s + (teile.first { $0.name == t.name }?.g ?? 0) }
            let mat = teile.first { $0.name == platten[i].teile.first?.name }?.material ?? "petg"
            platten[i].zeitS = gramm * jeGramm + 300
            platten[i].material = [DruckMaterialSumme(material: mat, g: gramm, m: gramm / (dichte[mat] ?? 1.27) / 2.405,
                                                      kosten: gramm * 0.017)]
            platten[i].stand = stand
            platten[i].anordnung = "schnell"
            platten[i].hoeheMM = platten[i].teile.compactMap { t in teile.first { $0.name == t.name }?.masse[2] }.max()
        }
        var material: [DruckMaterialSumme] = []
        for mat in Array(Set(teile.map(\.material))).sorted() {
            let g = teile.filter { $0.material == mat }.reduce(0) { $0 + $1.g }
            material.append(DruckMaterialSumme(material: mat, name: mat.uppercased(), g: g, m: g / (dichte[mat] ?? 1.27) / 2.405,
                                               kosten: g * 0.017, preisKg: 17, preisStand: "2026-10", stand: stand,
                                               filament: mat == "petg" ? "Bambu PETG Basic" : nil))
        }
        let zeit = platten.reduce(0) { $0 + $1.zeitS }
        let filament = material.compactMap(\.kosten).reduce(0, +)
        let strom = zeit / 3600 * 0.15 * 0.32
        let summe = DruckSumme(platten: platten.count, zeitS: zeit, zeitMitWechselS: zeit + Double(max(0, platten.count - 1)) * 120,
                               kosten: ((filament + strom) * 1.05 * 100).rounded() / 100, kostenFilament: filament,
                               kostenStrom: strom, kostenRisiko: (filament + strom) * 0.05, material: material)
        var hinweise: [DruckpraxisHinweis] = []
        if material.count > 1 {
            hinweise.append(DruckpraxisHinweis(schwere: .hinweis, text: "Mehrere Materialien: je Material eigene Platten, ohne AMS die Spule wechseln.",
                                               art: "ams"))
        }
        return Druckvorschau(run: run, stand: stand, summe: summe, platten: platten, teile: vorschauTeile, hinweise: hinweise,
                             slicer: DruckSlicer(zustand: .rechnet, fertig: 0, gesamt: vorschauTeile.count,
                                                 meldung: "Bambu Studio rechnet im Hintergrund"))
    }

    /// Dieselbe Vorschau, wie sie Bambu Studio liefern könnte (andere Zeiten und Gramm).
    static func slicerVersion(_ v: Druckvorschau, faktorZeit: Double, faktorGramm: Double, fertig: Bool) -> Druckvorschau {
        var n = v
        n.stand = fertig ? .slicer : .gemischt
        let halb = fertig ? n.teile.count : max(1, n.teile.count / 2)
        for i in n.teile.indices where i < halb {
            let alt = n.teile[i].zeitS
            n.teile[i].zeitS *= faktorZeit * (1 + 0.04 * Double(i % 3))
            n.teile[i].g *= faktorGramm
            n.teile[i].stand = .slicer
            n.teile[i].abweichung = alt > 0 ? (alt - n.teile[i].zeitS) / n.teile[i].zeitS : nil
        }
        for i in n.platten.indices {
            n.platten[i].zeitS *= faktorZeit
            n.platten[i].stand = n.stand
            n.platten[i].anordnung = fertig ? "slicer" : "schnell"
            for k in n.platten[i].material.indices { n.platten[i].material[k].g *= faktorGramm }
        }
        n.summe.zeitS *= faktorZeit
        n.summe.zeitMitWechselS = n.summe.zeitS + Double(max(0, n.summe.platten - 1)) * 120
        for k in n.summe.material.indices {
            n.summe.material[k].g *= faktorGramm
            n.summe.material[k].kosten = n.summe.material[k].kosten.map { $0 * faktorGramm }
            n.summe.material[k].stand = n.stand
        }
        n.summe.kosten = n.summe.kosten.map { ($0 * faktorGramm * 100).rounded() / 100 }
        n.slicer = DruckSlicer(zustand: fertig ? .fertig : .rechnet, fertig: halb, gesamt: n.teile.count,
                               meldung: fertig ? "Bambu Studio 02.07.01.62: alle Gruppen gerechnet"
                                   : "Bambu Studio 02.07.01.62: \(halb) von \(n.teile.count) Gruppen gerechnet")
        n.slicer.version = "02.07.01.62"
        return n
    }
}
