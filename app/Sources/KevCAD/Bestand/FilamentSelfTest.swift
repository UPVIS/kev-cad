import AppKit
import KevCADCore

/// Live-Selbsttest Filament im Bestand (Strang „Bestand Stufe 2“), nur Testvariante, mit dem Ersatz-Kernel
/// (`fake_kernel.py --filament`: Spulen, Druckteile, Druckvorschau, Platte 2 schon als gedruckt gebucht) oder dem echten:
///
/// - `KEVCAD_SELFTEST=filament`: Spulen zeigen (Bereich „Material“ › „Bestand“), Spule erfassen, ändern, entfernen und
///   das Entfernen rückgängig machen, Einkaufsliste mit Spulen, „Gebaut“ mit Filament in der Vorschau (Platte 2 als
///   gedruckt markiert, auch wenn nur Filament zu buchen wäre), buchen und rückgängig machen. Alles über Aktionen, ohne
///   Maus und Tastatur. Fensterbilder (`cacheDisplay`) nach `KEVCAD_SELFTEST_AUSGABE` bzw. in den Datenordner,
///   Ergebnis in `selftest-filament.txt`.
@MainActor
enum FilamentSelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState, material: MaterialZustand) {
        guard !started, session.demo == nil, AppInfo.isTestVariant,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "filament"
        else { return }
        started = true
        Task { await run(session, state, material) }
    }

    private static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-filament", isDirectory: true)
    }

    private static func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return condition()
    }

    private static func run(_ session: AppSession, _ state: ProjectWindowState, _ material: MaterialZustand) async {
        let model = session.model
        var lines: [String] = []
        var passed = true
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: ausgabe.appendingPathComponent("foto-auftrag.txt"))
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Filament: \(line)"))
        }
        func idle() async -> Bool { await wait(8) { model.bestandZustand.aktivitaet != .saving } }
        func foto(_ name: String) async {
            try? await Task.sleep(for: .milliseconds(900))
            // Von außen (screencapture -l): Auftrag „<Fensternummer> <Name>“ in foto-auftrag.txt, ein Blatt statt
            // des Fensters, wenn eins offen ist (wie der Selbsttest „Material“)
            if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_FOTO_AUSSEN"] == "1", let w = session.projectWindow {
                let nummer = (w.attachedSheet ?? w).windowNumber
                let auftrag = ausgabe.appendingPathComponent("foto-auftrag.txt")
                let zeile = "\(nummer) \(name)\n"
                if let h = try? FileHandle(forWritingTo: auftrag) {
                    h.seekToEndOfFile()
                    h.write(Data(zeile.utf8))
                    try? h.close()
                } else {
                    try? zeile.write(to: auftrag, atomically: true, encoding: .utf8)
                }
                _ = await wait(10) { FileManager.default.fileExists(atPath: ausgabe.appendingPathComponent(name + ".png").path) }
                return
            }
            guard let v = session.projectWindow?.contentView,
                  let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        func spulen() -> [BestandSpule] { model.bestandZustand.bestand?.spulen ?? [] }
        guard let actions = model.bestandActions else {
            check(false, "keine BestandActions")
            return finish(lines, passed)
        }

        // 1. Bestand mit Spulen, Stückliste, Filament-Rechnung des Kernels zur aktuellen Stückliste
        check(await wait(60) { !spulen().isEmpty }, "Spulen im Bestand: " + spulen().map(\.kennung).joined(separator: ", "))
        check(await wait(60) { model.bestandZustand.gebautFilamentAktuell != nil && !model.laufAktiv },
              "Filament für „Gebaut“ zur Stückliste von Lauf \(model.bom?.run ?? 0)")
        let pla = model.bestandZustand.bestand?.spulen(material: "pla") ?? []
        check(pla.count >= 2 && pla.map(\.zustand).contains(.voll) && pla.map(\.zustand).contains(.angebrochen),
              "PLA: " + pla.map { "\($0.kennung) \($0.zustand.titel)" }.joined(separator: ", "))
        check(model.materialDaten.lagerEinkauf.contains { $0.position.id == "petg" && $0.position.einheit.hasPrefix("Spule") },
              "Einkaufsliste: PETG-Spule unter Lagerware")

        // 2. Bereich „Material“ › „Bestand“ mit Filament
        material.zeige(.bestand)
        state.zeige(.material)
        BestandUI.shared.auswahl = FilamentAuswahl.id("pla")
        await foto("filament-bestand")
        BestandUI.shared.spule = SpulenAnfrage(kennung: pla.first?.kennung)
        await foto("filament-spule-aendern")
        BestandUI.shared.spule = nil
        try? await Task.sleep(for: .milliseconds(500))
        material.zeige(.einkauf)
        await foto("filament-einkauf")
        material.zeige(.bestand)

        // 3. Erfassen, ändern, entfernen, rückgängig
        let vorher = spulen().map(\.kennung)
        actions.saveBestandSpule(
            kennung: nil, spule: SpulenEingabe(material: "petg", gramm: nil, grammVoll: 1000, name: "Selbsttest PETG",
                                               hersteller: "Bambu Lab", farbe: "grau", ort: "Regal 9"),
            anzahl: 1, grund: "Selbsttest: neue Spule")
        _ = await idle()
        check(await wait(8) { spulen().count == vorher.count + 1 }, "Spule erfasst")
        guard let neu = spulen().first(where: { !vorher.contains($0.kennung) }) else { return finish(lines, passed) }
        check(neu.zustand == .voll && neu.gramm == 1000 && neu.ort == "Regal 9",
              "neue Spule \(neu.kennung): \(neu.mengeText), \(neu.zustand.titel), \(neu.ort ?? "–")")
        var e = SpulenEingabe(neu)
        e.gramm = 640
        e.ort = ""
        actions.saveBestandSpule(kennung: neu.kennung, spule: e, anzahl: nil, grund: "Selbsttest: Spule geändert")
        _ = await idle()
        check(await wait(8) {
            let s = spulen().first { $0.kennung == neu.kennung }
            return s?.gramm == 640 && s?.ort == nil && s?.zustand == .angebrochen
        }, "Spule geändert: 640 g, Ort gelöscht, angebrochen")
        BestandUI.shared.auswahl = FilamentAuswahl.id("petg")
        await foto("filament-petg")
        actions.saveBestandSpule(kennung: neu.kennung, spule: nil, anzahl: nil, grund: "Selbsttest: Spule entfernt")
        _ = await idle()
        check(await wait(8) { !spulen().contains { $0.kennung == neu.kennung } }, "Spule entfernt")
        if let b = model.bestandZustand.buchungen.first {
            actions.buchungRueckgaengig(b.id)
            check(await wait(8) { spulen().contains { $0.kennung == neu.kennung } }, "Entfernen rückgängig (\(b.id))")
            actions.saveBestandSpule(kennung: neu.kennung, spule: nil, anzahl: nil, grund: "Selbsttest: wieder weg")
            _ = await idle()
            _ = await wait(8) { !spulen().contains { $0.kennung == neu.kennung } }
        }

        // 4. „Gebaut“: Filament in der Vorschau, Platte 2 schon gedruckt, hatBuchbares mit Filament
        check(await wait(15) { model.bestandZustand.gebautFilamentAktuell != nil }, "Filament-Rechnung wieder aktuell")
        guard let z = model.bestandZustand.zuschnitt, let f = model.bestandZustand.gebautFilamentAktuell else {
            return finish(lines, passed)
        }
        let v = GebautVorschau.berechnen(zuschnitt: z, bestand: model.bestandZustand.bestand,
                                         lines: model.bom?.lines ?? [], name: { model.catalog?.item($0)?.name },
                                         filament: f)
        check(v.weg.contains { $0.art == .filamentWeg },
              "Vorschau: " + v.weg.filter { $0.art == .filamentWeg }.map { "\($0.text) (\($0.hinweis ?? ""))" }
                .joined(separator: ", "))
        check(v.platten.contains { $0.gebucht }, "Platten: " + v.platten.map { "\($0.text) \($0.hinweis ?? "")" }
            .joined(separator: "; "))
        var nurFilament = model.bestandZustand
        nurFilament.zuschnitt = BOMBestand(run: z.run, zuschnitte: [], einkaufsliste: [])
        check(nurFilament.hatBuchbares, "„Gebaut“ nicht gesperrt, wenn nur Filament zu buchen ist")
        state.zeige(.modell)
        BestandUI.shared.gebautDialog = true
        await foto("filament-gebaut-dialog")
        let vorGebaut = spulen()
        actions.bucheGebaut()
        BestandUI.shared.gebautDialog = false
        check(await wait(8) { model.bestandZustand.hinweis?.buchung != nil },
              "Gebaut gebucht: \(model.bestandZustand.hinweis?.text ?? "?")")
        check(await wait(8) { spulen() != vorGebaut }, "Spulen nach Gebaut: "
            + spulen().map { "\($0.kennung) \($0.mengeText)" }.joined(separator: ", "))
        if let buchung = model.bestandZustand.hinweis?.buchung {
            actions.buchungRueckgaengig(buchung)
            check(await wait(8) { spulen().map(\.kennung) == vorGebaut.map(\.kennung)
                && spulen().map(\.gramm) == vorGebaut.map(\.gramm) }, "Gebaut rückgängig: Spulen wie vorher")
        }
        finish(lines, passed)
    }

    private static func finish(_ lines: [String], _ passed: Bool) {
        let summary = passed ? "Selbsttest Filament bestanden" : "Selbsttest Filament FEHLGESCHLAGEN"
        let text = ([summary] + lines).joined(separator: "\n") + "\n"
        try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-filament.txt"), atomically: true,
                        encoding: .utf8)
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_QUIT"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
        }
    }
}
