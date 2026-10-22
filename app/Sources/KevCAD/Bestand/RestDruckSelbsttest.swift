import AppKit
import KevCADCore
import SwiftUI

/// Selbsttest des Strangs „Rest Druck“ (`KEVCAD_SELFTEST=restdruck`), nur Testvariante, gegen den echten Kernel und das
/// Projekt `KEVCAD_SELFTEST_PROJEKT` (Druckteile in Gelb und Schwarz, einer mit M3-Einsatz, Rohre mit Resten im
/// Bestand, Spulen PETG gelb 50 g und schwarz 500 g). Der Kernel soll Bambu Studio nicht öffnen
/// (`KEVCAD_DRUCKER_NICHT_OEFFNEN=1`) und eigene Zwischenspeicher, Abgleich und Filamentliste nutzen.
///
/// 1. Druckvorschau: Platten je Farbe (Klassen „petg/gelb“, „petg/schwarz“), Summe je Farbe, Modifier am Halter.
/// 2. Dialog „Gebaut“: Zusammenfassung oben, Abschnitte zum Ein- und Ausklappen (Fotos).
/// 3. Dialog „Drucken …“: ohne Wahl gesperrt, Filament wählen, Preset sichtbar, vorbereiten, Weg A bestätigen, Datei im
///    Projekt; beim nächsten Öffnen ist das zuletzt gewählte vorbelegt.
/// 4. „Gedruckt“: Blatt für eine gelbe Platte, buchen (gelbe Spule zuerst, Rest gekauft in Gelb), Stand, Rückgängig.
///
/// Ohne Maus und Tastatur; Fensterbilder (`cacheDisplay`) und `selftest-restdruck.txt` nach `KEVCAD_SELFTEST_AUSGABE`.
@MainActor
enum RestDruckSelbsttest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "restdruck"
    }

    private static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-restdruck", isDirectory: true)
    }

    /// Beim Start (Begrüßungsfenster): das Projekt aus `KEVCAD_SELFTEST_PROJEKT` öffnen, sobald der Kernel bereit ist;
    /// der Test selbst läuft im Projektfenster.
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

    private static func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return condition()
    }

    private static func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }

    private static func foto(_ w: NSWindow?, _ name: String) {
        guard let v = w?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
        v.cacheDisplay(in: v.bounds, to: rep)
        if let d = rep.representation(using: .png, properties: [:]) {
            try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
        }
    }

    private static func run(_ session: AppSession, _ state: ProjectWindowState, _ material: MaterialZustand) async {
        let model = session.model
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var passed = true
        let aktivitaet = ProcessInfo.processInfo.beginActivity(options: [.userInitiated], reason: "Selbsttest Rest Druck")
        defer { ProcessInfo.processInfo.endActivity(aktivitaet) }
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Rest Druck: \(line)"))
        }
        func info(_ text: String) { lines.append("      \(text)") }
        func blatt() -> NSWindow? { session.projectWindow?.attachedSheet }

        // 0. Projekt öffnen und rechnen lassen
        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        if let p = env["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty, model.project == nil {
            model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
        }
        check(await wait(600) { model.project != nil && !model.isRunning && !model.parts.isEmpty },
              "Projekt offen, Lauf fertig (\(model.parts.count) Teile)")
        check(await wait(120) { (model.druck.vorschau?.platten.count ?? 0) >= 2 }, "Druckvorschau mit Platten")
        guard let bestandActions = model.bestandActions, let druckerActions = model.druckerActions,
              let v = model.druck.vorschau
        else {
            check(false, "Aktionen oder Druckvorschau fehlen")
            return fertig(lines, passed, model)
        }

        // 1. Farben und Modifier in der Druckvorschau
        let klassen = v.klassen(platten: [])
        check(klassen.contains("petg/gelb") && klassen.contains("petg/schwarz"),
              "Platten je Farbe: " + v.platten.map { "Platte \($0.nr) \($0.klasse)" }.joined(separator: ", "))
        let petg = v.summe.material.first { $0.material == "petg" }
        check((petg?.farben.count ?? 0) >= 2, "Summe je Farbe: "
            + (petg?.farben.map { "\($0.farbe ?? "ohne") \(DruckFormat.gramm($0.g))" }.joined(separator: ", ") ?? "–"))
        check(v.teile.contains { $0.farbe == "gelb" } && v.teile.contains { $0.farbe == nil },
              "Gruppen mit und ohne Farbe: " + v.teile.map { "\($0.kurzname) \($0.farbe ?? "–")" }.joined(separator: ", "))
        let mitModifier = v.teile.filter { $0.modifier > 0 }
        check(!mitModifier.isEmpty, "Modifier um den Einsatz: " + mitModifier.map { "\($0.kurzname) × \($0.modifier)" }
            .joined(separator: ", "))
        if let g = mitModifier.first, let b = g.begruendung.first(where: { $0.contains("Modifier") }) { info(b) }
        check(model.materialDaten.filament.contains { $0.werkstoff.hasSuffix("gelb") },
              "Einkaufsliste je Farbe: " + model.materialDaten.filament.map(\.werkstoff).joined(separator: ", "))

        // Druckvorschau im Testfenster (Platten mit Farbe und Knopf „Gedruckt“)
        let fenster = DruckTestFenster.zeige(model: model)
        DruckUI.shared.nebeneinander = true
        await pause(2)
        foto(fenster, "01-druckvorschau-farben")

        // 2. Dialog „Gebaut“
        check(await wait(60) { model.bestandZustand.zuschnitt != nil && model.bestandZustand.gebautFilamentAktuell != nil },
              "Zuschnitt mit Bestand und Filament für „Gebaut“")
        BestandUI.shared.gebautDialog = true
        await pause(1.5)
        foto(blatt(), "02-gebaut-dialog")
        if let z = model.bestandZustand.zuschnitt {
            let gv = GebautVorschau.berechnen(zuschnitt: z, bestand: model.bestandZustand.bestand,
                                              lines: model.bom?.lines ?? [], name: { model.catalog?.item($0)?.name },
                                              filament: model.bestandZustand.gebautFilamentAktuell)
            check(!gv.platten.isEmpty && gv.weg.count > GebautDialog.Abschnitt.offenBis,
                  "Gebaut: \(gv.weg.count) Posten weg, \(gv.platten.count) Druckplatten (oben zusammengefasst)")
        }
        BestandUI.shared.gebautDialog = false
        await pause(0.8)

        // 3. Drucken … mit Filamentwahl (Weg A)
        let gelb = v.platten.filter { $0.klasse == "petg/gelb" }.map(\.nr)
        druckerActions.druckDialogOeffnen(platten: gelb)
        check(await wait(5) { model.drucker.dialog != nil }, "Dialog „Drucken …“ für Platte "
            + gelb.map(String.init).joined(separator: ", "))
        let d0 = model.drucker.dialog
        check(d0?.fehlendesFilament(model.druck.vorschau) == ["petg/gelb"],
              "ohne Wahl gesperrt (noch kein Filament für PETG gelb gewählt)")
        await pause(1.5)
        foto(blatt(), "03-drucken-ohne-wahl")
        let liste = model.druck.vorschau?.filamente(fuerKlasse: "petg/gelb") ?? []
        check(liste.first?.farbeSchluessel == "gelb", "Filamente für PETG gelb, passende Farbe zuerst: "
            + liste.map(\.name).joined(separator: ", "))
        if let f = liste.first {
            druckerActions.druckDialogFilament(klasse: "petg/gelb", filament: f.id)
        }
        let bereit = await wait(400) {
            if case .bereit = model.drucker.dialog?.phase { return true }
            if case .fehler = model.drucker.dialog?.phase { return true }
            return false
        }
        if case .bereit(let r) = model.drucker.dialog?.phase {
            check(bereit, "vorbereitet: \(r.gesliced.count) Platte(n), \(DruckFormat.zeit(r.zeitS)), "
                + DruckFormat.gramm(r.gramm))
            let preset = r.hinweise.first { $0.contains("Preset") }
            check(preset != nil, "Preset im Ergebnis: \(preset ?? "–")")
            let modifier = r.hinweise.first { $0.contains("Modifier") }
            check(modifier != nil, "Modifier im Bambu-Projekt: \(modifier ?? "–")")
        } else {
            check(false, "vorbereiten: \(String(describing: model.drucker.dialog?.phase))")
        }
        check(model.drucker.dialog?.fehlendesFilament(model.druck.vorschau).isEmpty == true, "Filament gewählt")
        await pause(1.5)
        foto(blatt(), "04-drucken-bereit")
        druckerActions.druckBestaetigen()
        let geoeffnet = await wait(180) {
            if case .fertig = model.drucker.dialog?.phase { return true }
            if case .fehler = model.drucker.dialog?.phase { return true }
            return false
        }
        if case .fertig(let r) = model.drucker.dialog?.phase, let datei = r.datei {
            check(geoeffnet && r.schritt == "geoeffnet", "Weg A: \(datei.lastPathComponent) (Bambu Studio würde öffnen)")
            check(FileManager.default.fileExists(atPath: datei.path), "Datei im Projektordner output/")
        } else {
            check(false, "bestätigen: \(String(describing: model.drucker.dialog?.phase))")
        }
        await pause(1)
        foto(blatt(), "05-drucken-geoeffnet")
        druckerActions.druckDialogSchliessen()
        await pause(0.8)
        // zuletzt gewählt: beim nächsten Öffnen vorbelegt
        check(await wait(90) { model.druck.vorschau?.filamentZuletzt["petg/gelb"] != nil },
              "zuletzt gewählt gemerkt: \(model.druck.vorschau?.filamentZuletzt["petg/gelb"] ?? "–")")
        druckerActions.druckDialogOeffnen(platten: gelb)
        check(await wait(5) { model.drucker.dialog?.filament["petg/gelb"] == liste.first?.id },
              "vorbelegt mit dem zuletzt gewählten: \(model.drucker.dialog?.filament["petg/gelb"] ?? "–")")
        await pause(1.5)
        foto(blatt(), "06-drucken-vorbelegt")
        druckerActions.druckDialogSchliessen()
        await pause(0.8)

        // 4. „Gedruckt“ für eine gelbe Platte
        func spulen() -> [BestandSpule] { model.bestandZustand.bestand?.spulen ?? [] }
        let vorher = spulen()
        guard let nr = gelb.first else { return fertig(lines, passed, model) }
        BestandUI.shared.gedruckt = GedrucktAnfrage(platten: [nr])
        await pause(1.5)
        foto(blatt(), "07-gedruckt-blatt")
        BestandUI.shared.gedrucktBuchen += 1
        check(await wait(15) { model.bestandZustand.hinweis?.buchung != nil && model.bestandZustand.aktivitaet == .idle },
              "Gedruckt gebucht: \(model.bestandZustand.hinweis?.text ?? "?")")
        check(await wait(10) { spulen() != vorher }, "Spulen danach: "
            + spulen().map { "\($0.kennung) \($0.farbe ?? "–") \($0.mengeText)" }.joined(separator: ", "))
        let schwarz = { (s: [BestandSpule]) in s.filter { $0.farbe == "schwarz" }.map(\.gramm) }
        check(schwarz(spulen()) == schwarz(vorher), "die schwarze Spule bleibt (Gelb zuerst aus Gelb)")
        check(await wait(10) {
            model.bestandZustand.gebautFilament?.platten.first { $0.nr == nr }?.gebucht != nil
        }, "Platte \(nr) in der Druckvorschau als gedruckt gebucht")
        await pause(1.5)
        foto(blatt(), "08-gedruckt-ergebnis")
        BestandUI.shared.gedruckt = nil
        await pause(0.8)
        foto(fenster, "09-druckvorschau-gedruckt")
        if let id = model.bestandZustand.hinweis?.buchung {
            bestandActions.buchungRueckgaengig(id)
            check(await wait(10) { spulen().map(\.kennung) == vorher.map(\.kennung) && spulen().map(\.gramm) == vorher.map(\.gramm) },
                  "Rückgängig: Spulen wie vorher")
        }
        fenster.close()
        fertig(lines, passed, model)
    }

    private static func fertig(_ lines: [String], _ passed: Bool, _ model: AppModel) {
        let log = model.log.suffix(300).map { "\($0.level.rawValue): \($0.text)" }.joined(separator: "\n")
        try? log.write(to: ausgabe.appendingPathComponent("protokoll.txt"), atomically: true, encoding: .utf8)
        let text = ([passed ? "Selbsttest Rest Druck bestanden" : "Selbsttest Rest Druck FEHLGESCHLAGEN"] + lines)
            .joined(separator: "\n") + "\n"
        try? text.write(to: ausgabe.appendingPathComponent("selftest-restdruck.txt"), atomically: true, encoding: .utf8)
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_QUIT"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
        }
    }
}
