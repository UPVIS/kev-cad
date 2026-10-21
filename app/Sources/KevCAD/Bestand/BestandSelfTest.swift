import AppKit
import KevCADCore

/// Live-Selbsttest des Bestands gegen den (Ersatz-)Kernel, nur Testvariante:
///
/// - `KEVCAD_SELFTEST=bestand`: Bestand und Stückliste mit Zuschnitt abwarten, erfassen (ganze Stangen, Reste,
///   Stückgut), Einstellungen ändern, „Gebaut“ buchen und rückgängig machen, Einkaufsliste als CSV schreiben. Alles über
///   die Aktionen der Oberfläche, ohne Maus und Tastatur. Ergebnis im Protokoll und in
///   `<Datenordner>/selftest-bestand.txt`.
/// - `KEVCAD_SELFTEST=bestand-dialog`: nur den Dialog „Gebaut …“ öffnen (für Fensterbilder).
@MainActor
enum BestandSelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession) {
        let mode = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"]
        guard !started, session.demo == nil, AppInfo.isTestVariant, mode == "bestand" || mode == "bestand-dialog"
        else { return }
        started = true
        Task { await mode == "bestand" ? run(session) : dialog(session) }
    }

    private static func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return condition()
    }

    private static func dialog(_ session: AppSession) async {
        let model = session.model
        _ = await wait(30) { model.bestandZustand.zuschnitt != nil && model.bestandZustand.bestand != nil }
        try? await Task.sleep(for: .milliseconds(800))
        BestandUI.shared.bereich = .stueckliste
        BestandUI.shared.gebautDialog = true
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        var lines: [String] = []
        var passed = true
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Bestand: \(line)"))
        }
        func idle() async -> Bool {
            await wait(8) { model.bestandZustand.aktivitaet != .saving }
        }
        guard let actions = model.bestandActions else {
            check(false, "keine BestandActions")
            return finish(lines, passed)
        }

        // 1. Bestand und Stückliste mit Zuschnitt
        check(await wait(30) { model.bestandZustand.bestand != nil }, "BESTAND angekommen")
        check(await wait(30) { model.bestandZustand.zuschnitt != nil && !model.laufAktiv }, "BOM mit Bestand angekommen")
        guard let start = model.bestandZustand.bestand, let z = model.bestandZustand.zuschnitt else {
            return finish(lines, passed)
        }
        check(start.posten.count >= 4, "Posten im Bestand: \(start.posten.map(\.id).joined(separator: ", "))")
        let rohrID = "rohr-alfer-12x1"
        if let rohr = z.zuschnitt(rohrID) {
            check(rohr.quellen.map(\.art.rawValue) == ["rest", "rest", "bestand", "kaufen"],
                  "Zuschnitt Rohr: " + rohr.quellen.map(\.titel).joined(separator: " | "))
            check(rohr.neueReste == [269, 697], "neue Reste: \(rohr.neueResteText)")
        } else {
            check(false, "Zuschnitt Rohr fehlt")
        }
        check(z.zuschnitte.contains { $0.istPlatte }, "Plattenzuschnitt vorhanden")
        check(z.fehlt && z.einkaufsliste.count == 3, "Einkaufsliste: \(z.einkaufsliste.map(\.benennung).joined(separator: ", "))"
            + (z.summe.map { ", Summe \(KevFormat.euro($0))" } ?? ""))

        // 2. Erfassen: 2 ganze Stangen und 2 Reste dazu
        if let rohr = start.posten(rohrID) {
            let e = BestandErfassung(form: .stange, ganze: 2, laenge: 1000, resteLaengen: [250, 330], ort: "Regal 3")
            actions.saveBestandPosten(id: rohrID, posten: e.posten(vorher: rohr.json, bestand: start), grund: e.grund(name: "Rohr"))
            check(await idle(), "Erfassen gebucht")
            check(await wait(5) {
                let p = model.bestandZustand.bestand?.posten(rohrID)
                return p?.ganzeAnzahl == rohr.ganzeAnzahl + 2 && p?.reste.count == rohr.reste.count + 2
            }, "Bestand nach Erfassen: \(model.bestandZustand.bestand?.posten(rohrID)?.zusammenfassung ?? "?")")
            let neu = model.bestandZustand.bestand?.posten(rohrID)?.reste.compactMap(\.kennung) ?? []
            check(Set(neu).count == neu.count, "Kennungen eindeutig: \(neu.joined(separator: ", "))")
        }

        // 3. Schnell: −1 Stange, Rest entfernen, Stückgut +10
        if let p = model.bestandZustand.bestand?.posten(rohrID) {
            PostenAenderung(model: model, posten: p).ganze(-1)
            _ = await idle()
            check(await wait(5) { model.bestandZustand.bestand?.posten(rohrID)?.ganzeAnzahl == p.ganzeAnzahl - 1 }, "−1 Stange")
        }
        if let p = model.bestandZustand.bestand?.posten(rohrID), let rest = p.reste.last {
            PostenAenderung(model: model, posten: p).restEntfernen(rest)
            _ = await idle()
            check(await wait(5) { model.bestandZustand.bestand?.posten(rohrID)?.reste.count == p.reste.count - 1 },
                  "Rest \(rest.kennung ?? "?") entfernt")
        }
        if let p = model.bestandZustand.bestand?.posten("mutter-din315-m4") {
            PostenAenderung(model: model, posten: p).stueck(laenge: nil, delta: 10)
            _ = await idle()
            check(await wait(5) { model.bestandZustand.bestand?.posten("mutter-din315-m4")?.stueckGesamt == p.stueckGesamt + 10 },
                  "Muttern +10")
            check(await wait(5) { !(model.bestandZustand.zuschnitt?.einkaufsliste.contains { $0.id == "mutter-din315-m4" } ?? true) },
                  "Muttern nicht mehr auf der Einkaufsliste")
        }

        // 4. Einstellungen
        let e0 = model.bestandZustand.bestand?.einstellungen ?? .standard
        actions.saveBestandEinstellungen(BestandEinstellungen(mindestrestMM: 120, saegeblattMM: 4), grund: "Selbsttest")
        _ = await idle()
        check(await wait(5) { model.bestandZustand.bestand?.einstellungen.saegeblattMM == 4 }, "Sägeblatt 4 mm gespeichert")
        actions.saveBestandEinstellungen(e0, grund: "Selbsttest zurück")
        _ = await idle()

        // 5. Gebaut: Vorschau, Dialog, buchen
        guard let vorGebaut = model.bestandZustand.bestand, let zuschnitt = model.bestandZustand.zuschnitt else {
            return finish(lines, passed)
        }
        let vorschau = GebautVorschau.berechnen(
            zuschnitt: zuschnitt, bestand: vorGebaut, lines: model.bom?.lines ?? [], name: { model.catalog?.item($0)?.name })
        check(!vorschau.leer, "Vorschau: \(vorschau.kurz); weg: " + vorschau.weg.map(\.text).joined(separator: ", "))
        BestandUI.shared.bereich = .stueckliste
        BestandUI.shared.gebautDialog = true
        try? await Task.sleep(for: .seconds(1.5))
        actions.bucheGebaut()
        BestandUI.shared.gebautDialog = false
        check(await wait(8) { model.bestandZustand.hinweis?.buchung != nil }, "Gebaut gebucht: \(model.bestandZustand.hinweis?.text ?? "?")")
        let buchung = model.bestandZustand.hinweis?.buchung
        check(await wait(5) { model.bestandZustand.bestand != vorGebaut }, "Bestand nach Gebaut geändert")
        check(model.bestandZustand.buchungen.first?.art == "gebaut", "Buchungsprotokoll: \(model.bestandZustand.buchungen.count) Buchungen")

        // 6. Rückgängig
        if let buchung {
            actions.buchungRueckgaengig(buchung)
            check(await wait(8) { model.bestandZustand.bestand?.posten == vorGebaut.posten }, "Rückgängig: Bestand wie vor Gebaut")
            check(await wait(3) { model.bestandZustand.buchungen.first { $0.id == buchung }?.schonRueckgaengig == true },
                  "Buchung \(buchung) als zurückgenommen markiert")
        }

        // 7. Einkaufsliste als CSV
        if let project = model.project {
            let datei = project.path.appendingPathComponent("output")
                .appendingPathComponent(EinkaufslisteFormat.dateiname(projekt: project.name))
            try? FileManager.default.removeItem(at: datei)
            actions.exportEinkaufsliste()
            let text = (try? String(contentsOf: datei, encoding: .utf8)) ?? ""
            check(text.contains("Summe"), "CSV geschrieben: \(datei.lastPathComponent)")
        }
        finish(lines, passed)
    }

    private static func finish(_ lines: [String], _ passed: Bool) {
        let summary = passed ? "Selbsttest Bestand bestanden" : "Selbsttest Bestand FEHLGESCHLAGEN"
        let text = ([summary] + lines).joined(separator: "\n") + "\n"
        try? text.write(
            to: AppInfo.supportDirectory.appendingPathComponent("selftest-bestand.txt"), atomically: true, encoding: .utf8)
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_QUIT"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
        }
    }
}
