import AppKit
import KevCADCore

/// Live-Selbsttest der Phase 2 gegen den (Ersatz-)Kernel, nur Testvariante (`KEVCAD_SELFTEST=catalog`): Stückliste
/// abwarten, Lagerkatalog öffnen und laden, einen Vorschlag freigeben, einen Eintrag anlegen und löschen, einen
/// fehlerhaften Eintrag ablehnen lassen, die Inventar-Regel aus- und wieder einschalten, eine Zeile zeigen und die
/// Stückliste als CSV exportieren. Alles über die Aktionen der Oberfläche, ohne Maus und Tastatur. Ergebnis im
/// Protokoll und in `<Datenordner>/selftest-catalog.txt`.
@MainActor
enum CatalogSelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession) {
        guard !started, session.demo == nil, AppInfo.isTestVariant,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "catalog"
        else { return }
        started = true
        Task { await run(session) }
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        var lines: [String] = []
        var passed = true
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Katalog: \(line)"))
        }
        /// Wartet, bis `condition` gilt (höchstens `seconds`).
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }
        guard let actions = model.catalogActions else {
            check(false, "keine CatalogActions")
            return finish(lines, passed)
        }

        // 1. Stückliste und Inventar nach dem ersten Lauf
        check(await wait(30) { model.bom != nil && !model.isRunning }, "Stückliste angekommen")
        if let bom = model.bom {
            check(!bom.lines.isEmpty, "Stückliste: \(bom.lines.count) Positionen, \(bom.cuts.count) Zuschnitte, "
                + "\(KevFormat.euro(bom.totals.preis ?? 0))")
            check(bom.lines.contains(where: \.druckteil), "Druckteil in der Stückliste")
        }
        check(model.inventarVerstoesse == ["Grundplatte"], "Inventar-Verstoß gemeldet: \(model.inventarVerstoesse)")
        check(model.parts.first { $0.id == "Grundplatte" }?.inventarFehlt == true, "Grundplatte im Teilebaum markiert")
        if let bein = model.parts.first(where: { $0.stock != nil }) {
            check(bein.stock?.laenge == 882, "Lagerteil am Teil: \(bein.id) · \(bein.stock?.name ?? "?")")
        }

        // 2. Lagerkatalog öffnen und laden
        session.showCatalog()
        check(await wait(10) { model.catalog != nil }, "Lagerkatalog geladen")
        let catalog = model.catalog
        check((catalog?.suggestionCount ?? 0) == 2, "Vorschläge von Claude: \(catalog?.suggestionCount ?? 0)")

        // 3. Vorschlag freigeben
        if let suggestion = catalog?.items.first(where: \.vorgeschlagen) {
            actions.saveCatalogEntry(kind: "teil", json: Catalog.approvedJSON(suggestion.json), ebene: suggestion.ebene)
            check(await wait(5) { if case .saved = model.catalogActivity { return true } else { return false } },
                  "Freigabe gespeichert: \(suggestion.id)")
            check(await wait(5) { model.catalog?.item(suggestion.id)?.vorgeschlagen == false },
                  "nach dem Nachladen freigegeben")
        }

        // 4. Neuer Eintrag über das Formular-Modell, dann löschen
        var draft = CatalogItemDraft(art: "rohr")
        draft.masse = ["d": "26,9", "s": "2,3"]
        draft.material = "stahl-s235"
        draft.name = draft.suggestedName(materialName: "Stahl S235", materialGroup: "Stahl")
        draft.id = "selbsttest-" + draft.suggestedID()
        draft.preis = "3,90"
        check(draft.validate(materials: Set(model.catalog?.materials.map(\.id) ?? [])).isEmpty, "Entwurf gültig")
        actions.saveCatalogEntry(kind: "teil", json: draft.json(), ebene: .eigen)
        check(await wait(5) { model.catalog?.item(draft.id) != nil }, "neuer Eintrag im Katalog: \(draft.id)")
        actions.deleteCatalogEntry(kind: "teil", id: draft.id, ebene: .eigen)
        check(await wait(5) { model.catalog?.item(draft.id) == nil && model.catalogActivity == .deleted(id: draft.id) },
              "Eintrag gelöscht")

        // 5. Fehler des Kernels kommt an
        actions.saveCatalogEntry(kind: "teil", json: Data(#"{"id":"kaputt","art":"rohr"}"#.utf8), ebene: .eigen)
        check(await wait(5) { if case .failed = model.catalogActivity { return true } else { return false } },
              "Ablehnung durch den Kernel: \(model.catalogActivity)")

        // 6. Inventar-Regel aus: die Grundplatte wird Eigenteil, kein Verstoß mehr; danach wieder an
        model.inventoryActions?.setInventarRegel(false)
        check(await wait(15) { model.inventarVerstoesse.isEmpty && model.bom?.lines.contains(where: \.eigenteil) == true },
              "Regel aus: kein Verstoß, Eigenteil in der Stückliste")
        try? await Task.sleep(for: .milliseconds(500))
        model.inventoryActions?.setInventarRegel(true)
        check(await wait(15) { model.inventarVerstoesse == ["Grundplatte"] }, "Regel wieder an: Verstoß zurück")

        // 7. Zeile zeigen, CSV exportieren
        try? await Task.sleep(for: .milliseconds(500))
        if let line = model.bom?.lines.first {
            actions.showBOMLine(line)
            check(Set(model.selectedPartIDs) == Set(line.teile), "Zeile \(line.pos) ausgewählt: \(model.selectedPartIDs)")
        }
        let before = model.log.count
        model.actions?.export(formats: ["bom_csv"])
        check(await wait(5) { model.log.dropFirst(before).contains { $0.text.hasPrefix("Export fertig") } }, "CSV-Export")
        if let entry = model.log.dropFirst(before).first(where: { $0.text.hasPrefix("Export fertig") }),
           let path = entry.text.components(separatedBy: ": ").last?.components(separatedBy: ", ").first {
            check(FileManager.default.fileExists(atPath: path), "CSV-Datei vorhanden: \(path)")
        }
        finish(lines, passed)
    }

    private static func finish(_ lines: [String], _ passed: Bool) {
        let text = (lines + [passed ? "Ergebnis: bestanden" : "Ergebnis: FEHLER"]).joined(separator: "\n") + "\n"
        try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-catalog.txt"), atomically: true,
                        encoding: .utf8)
        FileHandle.standardError.write(Data("[selbsttest-katalog]\n\(text)".utf8))
    }
}
