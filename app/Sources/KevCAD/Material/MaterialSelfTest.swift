import AppKit
import KevCADCore

/// Selbsttest „Material“ in der Testvariante (`KEVCAD_SELFTEST=material`): Schnellansichten auf- und zuklappen, Höhe
/// ziehen, gemerkten Zustand prüfen, „In Material öffnen“, alle Abschnitte des Bereichs „Material“ zeigen (hell und
/// dunkel), Auswahl in beide Richtungen mit dem 3D-Bereich, Abhaken und Teilen der Einkaufsliste, CSV, Dialoge
/// „Gebaut …“ und „Erfassen“, Sprung zum Bericht und zurück, gleiche Summen in Bereich und Bericht. Ohne Maus- und
/// Tastatureingaben; Fensterbilder mit `KEVCAD_SELFTEST_FOTO_AUSSEN=1` von außen (`screencapture -l`, Auftrag in
/// `foto-auftrag.txt`), sonst über `cacheDisplay`. `KEVCAD_SELFTEST_PROJEKT` öffnet ein Projekt, Ausgabe in
/// `KEVCAD_SELFTEST_AUSGABE` (sonst im Datenordner), Ergebnis in `selftest-material.txt`.
@MainActor
enum MaterialSelfTest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "material"
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

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState, material: MaterialZustand) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session, state, material) }
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-material", isDirectory: true)
    }

    private static func run(_ session: AppSession, _ state: ProjectWindowState, _ material: MaterialZustand) async {
        let model = session.model
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var messwerte: [String: Any] = [:]
        var passed = true
        // Die Testvariante läuft im Hintergrund (open -g): ohne Aktivität drosselt App Nap die Zeitgeber und verfälscht
        // die Messwerte des Umschaltens
        let aktivitaet = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .latencyCritical],
                                                               reason: "Selbsttest Material")
        defer { ProcessInfo.processInfo.endActivity(aktivitaet) }
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: ausgabe.appendingPathComponent("foto-auftrag.txt"))
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Material: \(line)"))
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
        func foto(_ name: String) async {
            let w = session.projectWindow
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

        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        check(await wait(400) { model.project != nil && !model.isRunning && model.bom != nil }, "Projekt offen, Stückliste da")
        _ = await wait(30) { model.bestandZustand.zuschnitt != nil }
        await pause(1.5)

        // 1. Datenquelle: dieselben Summen in Stückliste, Material und Bericht
        let t0 = Date()
        let daten = model.materialDaten
        messwerte["material_daten_ms"] = Date().timeIntervalSince(t0) * 1000
        messwerte["positionen"] = daten.positionen.count
        messwerte["teile"] = daten.kennzahlen.teile
        let bom = model.bom
        check(daten.kennzahlen.teile == bom?.totals.teile && daten.kennzahlen.preis == bom?.totals.preis,
              "Summen wie die Stückliste: \(daten.kennzahlen.teile) Teile, \(daten.kennzahlen.kostenText)")
        if let b = model.bestandZustand.zuschnitt {
            check(daten.kennzahlen.einkaufLagerSumme == b.summe && daten.lagerEinkauf.count == b.einkaufsliste.count,
                  "Einkaufsliste wie der Kernel: \(b.einkaufsliste.count) Positionen Lagerware")
        }
        let quellen = ExportQuellen(kopf: ExportKopf(projekt: model.project?.name ?? ""), bom: bom,
                                    bestand: model.bestandZustand.zuschnitt, teile: model.parts)
        check(quellen.material.kennzahlen.einkaufSumme == daten.kennzahlen.einkaufSumme
              && quellen.material.zuschnitte.count == daten.zuschnitte.count,
              "Bericht liest dieselben Daten: Einkauf \(daten.kennzahlen.einkaufText), \(daten.zuschnitte.count) Zuschnitte")

        // 2. Schnellansichten
        state.zeige(.modell)
        state.schnell.alleZu()
        await pause(1)
        let sichtbar = SchnellansichtenBereich.sichtbar(daten)
        check(state.schnell.offene(sichtbar).isEmpty, "Alle eingeklappt: \(sichtbar.map(\.titel).joined(separator: ", "))")
        await foto("01-schnell-alle-zu")
        state.schnell.oeffne(.stueckliste)
        await pause(1)
        check(state.schnell.offene(sichtbar) == [.stueckliste], "Stückliste allein offen")
        await foto("02-schnell-stueckliste")
        if sichtbar.contains(.zuschnitt) {
            state.schnell.oeffne(.zuschnitt)
            await pause(1)
            check(state.schnell.offene(sichtbar) == [.stueckliste, .zuschnitt], "Stückliste und Zuschnitt zusammen offen")
            await foto("03-schnell-beide")
            state.schnell.schliesse(.stueckliste)
            await pause(1)
            check(state.schnell.offene(sichtbar) == [.zuschnitt], "Zuschnitt allein offen")
            await foto("04-schnell-zuschnitt")
            state.schnell.oeffne(.stueckliste)
        }
        state.schnell.setzeHoehe(.stueckliste, Schnellansicht.stueckliste.standardHoehe)
        state.schnell.setzeHoehe(.zuschnitt, Schnellansicht.zuschnitt.standardHoehe)
        let vorher = state.schnell.hoehe(.stueckliste)
        let start = state.schnell.verteilt(sichtbar, platz: 900)
        state.schnell.ziehe(.stueckliste, dy: -60, start: start, sichtbar: sichtbar, platz: 900)
        check(abs(state.schnell.hoehe(.stueckliste) - vorher) > 1,
              "Höhe gezogen: \(Int(vorher)) → \(Int(state.schnell.hoehe(.stueckliste))) pt")
        let gemerkt = SchnellansichtenZustand.aus(UserDefaults.standard.data(forKey: ProjectWindowState.schnellSchluessel))
        check(gemerkt == state.schnell, "Zustand gemerkt (Einstellungen)")
        let offenVorher = state.schnell.offen
        state.schnell.allesUmschalten(sichtbar)
        check(state.schnell.offene(sichtbar).isEmpty, "Umschalten: alles zu")
        state.schnell.allesUmschalten(sichtbar)
        check(state.schnell.offen == offenVorher, "Umschalten: wieder wie vorher")
        await pause(1)
        await foto("05-schnell-gezogen")

        // 3. Auswahl im 3D → Zeile; „In Material öffnen“ an dieselbe Stelle
        // Nur Positionen, deren Teile im Modell stehen (der Ersatz-Kernel schickt eine Stückliste ohne passende Teile)
        let imModell = Set(model.parts.map(\.id))
        let mitTeilen = daten.positionen.filter { !$0.teile.isEmpty && Set($0.teile).isSubset(of: imModell) }
        let p = mitTeilen.first { $0.stockID != nil && $0.herkunft == nil } ?? mitTeilen.first
        if p == nil {
            check(true, "Auswahl übersprungen: keine Position mit Teilen im Modell (Ersatz-Kernel)")
            material.zeige(.stueckliste)
            state.zeige(.material)
            await pause(1.5)
            await foto("10-material-stueckliste")
        }
        if let p {
            model.catalogActions?.showBOMLine(p.line)
            check(await wait(5) { Set(model.selectedPartIDs) == Set(p.teile) }, "Zeile \(p.pos) im 3D gewählt")
            material.zeige(.stueckliste, position: p.pos)
            state.zeige(.material)
            await pause(1.5)
            check(state.bereich == .material && material.abschnitt == .stueckliste && material.auswahl == [p.pos],
                  "In Material geöffnet: Stückliste, Pos. \(p.pos) gewählt")
            await foto("10-material-stueckliste")
            // Auswahl aus dem 3D-Bereich (Teilebaum) erreicht die Tabelle
            if let q = mitTeilen.first(where: { $0.pos != p.pos }), let teil = q.teile.first {
                model.actions?.select([teil])
                check(await wait(5) { material.auswahl == [q.pos] }, "Auswahl im 3D (\(teil)) markiert Pos. \(q.pos)")
                // und zurück: Auswahl in der Tabelle wählt die Teile im 3D
                material.auswahl = [p.pos]
                check(await wait(5) { Set(model.selectedPartIDs) == Set(p.teile) }, "Auswahl in Material wählt Teile im 3D")
            }
        }

        // Nur zum Messen (KEVCAD_SELFTEST_PROFIL=<s>): so lange die Abschnitte im Kreis umschalten, dann beenden
        if let s = env["KEVCAD_SELFTEST_PROFIL"].flatMap(Double.init) {
            try? "profil\n".write(to: ausgabe.appendingPathComponent("profil-start.txt"), atomically: true, encoding: .utf8)
            let ende = Date().addingTimeInterval(s)
            var i = 0
            while Date() < ende {
                material.abschnitt = MaterialAbschnitt.allCases[i % MaterialAbschnitt.allCases.count]
                i += 1
                await pause(0.3)
            }
            messwerte["profil_umschaltungen"] = i
            return fertig(lines, messwerte, passed)
        }

        // 4. Alle Abschnitte, hell und dunkel (die Systemlast gehört zu den Messwerten: bei hoher Last sagen sie wenig)
        var last = [Double](repeating: 0, count: 3)
        if getloadavg(&last, 3) == 3 { messwerte["systemlast_1min"] = last[0] }
        for (i, a) in MaterialAbschnitt.allCases.enumerated() {
            // Zeit bis zum nächsten Durchlauf der Hauptschleife nach dem Umschalten (Aufbau der Ansicht)
            let tA = Date()
            material.abschnitt = a
            await Task.yield()
            try? await Task.sleep(for: .milliseconds(1))
            messwerte["umschalten_\(a.rawValue)_ms"] = Date().timeIntervalSince(tA) * 1000
            await pause(a == .uebersicht ? 2.0 : 1.2)
            await foto(String(format: "%02d-material-%@", 20 + i, a.rawValue))
        }
        check(material.bilder.bilder.count > 0 || model.materialBildActions == nil || mitTeilen.isEmpty,
              "Vorschaubilder: \(material.bilder.bilder.count)")
        // Umschalten ein zweites Mal, ohne Bilder: so schnell wechselt Kevin, wenn alles schon einmal gezeigt war
        var warm: [Double] = []
        for a in MaterialAbschnitt.allCases {
            let tA = Date()
            material.abschnitt = a
            await Task.yield()
            try? await Task.sleep(for: .milliseconds(1))
            let ms = Date().timeIntervalSince(tA) * 1000
            warm.append(ms)
            messwerte["umschalten_warm_\(a.rawValue)_ms"] = ms
            await pause(0.4)
        }
        messwerte["umschalten_warm_max_ms"] = warm.max() ?? 0
        session.projectWindow?.appearance = NSAppearance(named: .darkAqua)
        for a in [MaterialAbschnitt.uebersicht, .stueckliste, .zuschnitt, .einkauf] {
            material.abschnitt = a
            await pause(1.2)
            await foto("30-dunkel-\(a.rawValue)")
        }
        state.zeige(.modell)
        await pause(1)
        await foto("31-dunkel-schnell")
        session.projectWindow?.appearance = nil
        state.zeige(.material)

        // 5. Einkaufsliste: abhaken, teilen, CSV
        material.abschnitt = .einkauf
        material.ladeAbgehakt(model.project?.path)
        if let z = model.materialDaten.einkauf.first {
            let war = material.abgehakt.abgehakt(z)
            material.umschalten(z)
            check(material.abgehakt.abgehakt(z) != war, "Abhaken: \(z.position.benennung)")
            let gespeichert = UserDefaults.standard.stringArray(forKey: EinkaufAbgehakt.defaultsKey(model.project!.path)) ?? []
            check(gespeichert.contains(z.abhakSchluessel) != war, "Abhaken je Projekt gemerkt")
            let text = MaterialText.einkaufText(model.materialDaten, projekt: model.project?.name,
                                                abgehakt: material.abgehakt.schluessel)
            check(text.contains("[x]") != war, "Text zum Teilen kennzeichnet abgehakte Zeilen")
            await pause(1)
            await foto("40-einkauf-abgehakt")
            material.umschalten(z)
        } else {
            check(true, "Einkaufsliste leer, nichts abzuhaken")
        }
        if let datei = EinkaufExport.sichern(model, zeigen: false) {
            // Byte für Byte wie die Liste am Bildschirm (mit BOM für Excel): Kopfzeile, je Position eine Zeile, Summe,
            // dann Normteile zum Abzählen und Filament
            let roh = (try? Data(contentsOf: datei)) ?? Data()
            let d = model.materialDaten
            let einkauf = d.einkauf
            let zeilen = (String(data: roh, encoding: .utf8) ?? "").split(separator: "\r\n").count
            check(roh == Data(MaterialText.einkaufCSV(d).utf8)
                  && zeilen == einkauf.count + 2 + d.stueckgut.count + d.filament.count,
                  "CSV gesichert wie am Bildschirm: \(einkauf.count) Positionen, davon "
                  + "\(model.materialDaten.zukaufEinkauf.count) Zukaufteile (\(datei.lastPathComponent))")
        }

        // 6. Dialoge
        material.abschnitt = .bestand
        await pause(1)
        await foto("41-bestand")
        if model.bestandActions != nil, model.bestandZustand.bestand != nil {
            BestandUI.shared.erfassen = ErfassenAnfrage(stockID: nil)
            await pause(1.2)
            check(BestandUI.shared.erfassen != nil, "Blatt „Erfassen“ offen")
            await foto("42-erfassen")
            BestandUI.shared.erfassen = nil
            await pause(0.8)
        }
        if model.bestandZustand.zuschnitt != nil, model.bestandActions != nil {
            BestandUI.shared.gebautDialog = true
            await pause(1.5)
            await foto("43-gebaut")
            BestandUI.shared.gebautDialog = false
            await pause(0.8)
        }

        // 7. Bericht und zurück
        BerichteUI.shared.bericht = MaterialAbschnitt.zuschnitt.bericht
        state.dokumenteZustand?.waehle(.berichte)
        state.zeige(.dokumente)
        await pause(3)
        check(state.bereich == .dokumente && BerichteUI.shared.bericht == .zuschnitt, "Als Bericht drucken: Zuschnitt in Dokumente")
        await foto("50-bericht-zuschnitt")
        material.zeige(MaterialAbschnitt(bericht: .einkaufsliste))
        state.zeige(.material)
        await pause(1)
        check(state.bereich == .material && material.abschnitt == .einkauf, "Aus dem Bericht zurück in Material › Einkaufsliste")

        // 8. 3D-Bereich mit offenen Schnellansichten zum Schluss
        state.zeige(.modell)
        state.schnell.alleAuf(sichtbar)
        await pause(1.5)
        await foto("60-schnell-alle-auf")
        fertig(lines, messwerte, passed)
    }

    private static func fertig(_ lines: [String], _ messwerte: [String: Any], _ passed: Bool) {
        let summary = passed ? "Selbsttest Material bestanden" : "Selbsttest Material FEHLGESCHLAGEN"
        let text = ([summary] + lines).joined(separator: "\n") + "\n"
        try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-material.txt"), atomically: true,
                        encoding: .utf8)
        try? text.write(to: ausgabe.appendingPathComponent("selftest-material.txt"), atomically: true, encoding: .utf8)
        if let d = try? JSONSerialization.data(withJSONObject: messwerte, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: ausgabe.appendingPathComponent("messwerte.json"))
        }
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_QUIT"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
        }
    }
}
