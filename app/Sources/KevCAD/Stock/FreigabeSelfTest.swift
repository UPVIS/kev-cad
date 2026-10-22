import AppKit
import KevCADCore

/// Selbsttest „Vorschläge freigeben“ in der Testvariante (`KEVCAD_SELFTEST=freigabe`, startet mit dem Lagerkatalog):
/// gibt alle Vorschläge von Claude über die echte Oberfläche frei, so wie Kevin klickt: über den Knopf „Freigeben“ in
/// der Zeile (Abschnitt Vorschläge), in den Details und bei Zukaufteilen im Dialog („Prüfen …“ → „Freigeben“).
/// Geklickt wird mit Maus-Ereignissen, die nur an das Fenster der Testvariante gehen (Trefferprüfung wie bei einem
/// echten Klick; der Mauszeiger und andere Programme bleiben unberührt). Die Knöpfe findet der Test über ihre
/// Fokusringe in der Ansichtshierarchie. Ergebnis im Protokoll und in `<Datenordner>/selftest-freigabe.txt`.
///
/// Mit eigenem Katalogordner starten (`KEVCAD_CATALOG_DIR`, darin Vorschläge wie von `stock_define`), dann das Fenster
/// Lagerkatalog öffnen. Optional: `KEVCAD_SELFTEST_WEG=zeile|details|dialog` (alle über einen Weg),
/// `KEVCAD_SELFTEST_FEHLER=1` (erst eine Freigabe während eines Kernel-Neustarts: muss mit Hinweisfenster scheitern),
/// `KEVCAD_SELFTEST_PROJEKT=<Ordner>` (mit offenem Projekt und Auto-Lauf).
@MainActor
enum FreigabeSelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession) {
        guard !started, session.demo == nil, AppInfo.isTestVariant,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "freigabe"
        else { return }
        started = true
        Task { await run(session) }
    }

    enum Way: String { case zeile = "Zeile", details = "Details", dialog = "Zukauf-Dialog" }

    private static func run(_ session: AppSession) async {
        let model = session.model
        var lines: [String] = []
        var passed = true
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Freigabe: \(line)"))
        }
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }

        check(await wait(180) { model.catalog != nil }, "Lagerkatalog geladen")
        // Wie bei Kevin: mit offenem Projekt, Auto-Lauf und Läufen, während freigegeben wird
        if let path = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !path.isEmpty {
            model.actions?.openProject(at: URL(fileURLWithPath: path, isDirectory: true))
            check(await wait(240) { model.project != nil && !model.isRunning && model.run != .idle },
                  "Projekt offen, erster Lauf fertig: \(model.run)")
        }
        session.showCatalog(section: .suggestions)
        try? await Task.sleep(for: .seconds(1))
        let all = model.catalog?.items.filter(\.vorgeschlagen) ?? []
        check(!all.isEmpty, "Vorschläge: \(all.map(\.id))")
        // Jede Art über jeden Weg, soweit es Einträge gibt
        var plan: [(CatalogItem, Way)] = []
        let zukauf = all.filter(\.isZukauf), stock = all.filter { !$0.isZukauf }
        // KEVCAD_SELFTEST_WEG=zeile|details|dialog: alle über denselben Weg (dialog nur für Zukaufteile)
        let forced = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_WEG"].flatMap { w in
            w.isEmpty ? nil : [Way.zeile, .details, .dialog].first { $0.rawValue.lowercased().contains(w.lowercased()) }
        }
        for (n, item) in stock.enumerated() {
            plan.append((item, forced.map { $0 == .dialog ? .details : $0 } ?? (n % 2 == 0 ? .zeile : .details)))
        }
        for (n, item) in zukauf.enumerated() { plan.append((item, forced ?? [.zeile, .details, .dialog][n % 3])) }

        // Fehlerfall: Kernel startet gerade neu. Die Freigabe muss mit einem Hinweisfenster scheitern, nicht still.
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_FEHLER"] == "1", let item = plan.first?.0 {
            session.showCatalog(section: .suggestions)
            try? await Task.sleep(for: .milliseconds(600))
            model.actions?.restartKernel()
            check(await wait(10) { model.kernelState != .ready }, "Kernel startet neu: \(model.kernelState)")
            check(clickRowApprove(item, model: model), "\(item.id): „Freigeben“ während des Neustarts geklickt")
            let sheet = await wait(5) { catalogWindow?.attachedSheet != nil }
            let texts = catalogWindow?.attachedSheet.map { views(NSTextField.self, in: $0.contentView ?? NSView()) }?
                .map(\.stringValue).joined(separator: " ") ?? ""
            check(sheet && texts.contains("Freigabe fehlgeschlagen") && texts.contains("nicht verbunden"),
                  "Hinweisfenster: \(texts.replacingOccurrences(of: "\n", with: " "))")
            check(model.catalog?.item(item.id)?.vorgeschlagen == true, "\(item.id) bleibt Vorschlag")
            if let sheet = catalogWindow?.attachedSheet,
               let ok = views(NSButton.self, in: sheet.contentView ?? NSView()).first(where: { $0.title == "OK" }) {
                ok.performClick(nil)
            }
            let ready = await wait(180) { model.kernelState == .ready || model.kernelState == .busy }
            let closed = await wait(10) { catalogWindow?.attachedSheet == nil }
            check(ready && closed, "Kernel wieder bereit (\(model.kernelState)), Hinweis geschlossen")
            try? await Task.sleep(for: .seconds(2))
        }

        for (item, way) in plan {
            let before = model.catalogActivity
            var clicked = false
            switch way {
            case .zeile:
                session.showCatalog(section: .suggestions)
                try? await Task.sleep(for: .milliseconds(600))
                clicked = clickRowApprove(item, model: model)
            case .details:
                session.showCatalog(focus: .item(item.id), section: .suggestions)
                try? await Task.sleep(for: .milliseconds(800))
                clicked = clickDetailBar(fromRight: 0)
            case .dialog:
                session.showCatalog(focus: .item(item.id), section: .suggestions)
                try? await Task.sleep(for: .milliseconds(800))
                clicked = clickDetailBar(fromRight: 1)  // „Prüfen …“ links neben „Freigeben“
                try? await Task.sleep(for: .milliseconds(1200))
                clicked = clicked && clickDialogPrimary()
            }
            check(clicked, "\(item.id) (\(item.art)): „Freigeben“ über \(way.rawValue) geklickt")
            let done = await wait(15) {
                if model.catalog?.item(item.id)?.vorgeschlagen == false { return true }
                // ein neuer Fehler (ein alter bleibt bis zur nächsten Aktion stehen)
                if case .failed = model.catalogActivity, model.catalogActivity != before { return true }
                return false
            }
            var shown = ""
            if case .failed(let text) = model.catalogActivity { shown = ", Meldung: \(text)" }
            check(done && model.catalog?.item(item.id)?.vorgeschlagen == false,
                  "\(item.id) freigegeben über \(way.rawValue) (vorher \(before), danach \(model.catalogActivity)\(shown))")
            if way == .dialog { session.dismissZukaufWindow() }
            try? await Task.sleep(for: .milliseconds(500))
        }
        check(await wait(5) { model.catalog?.suggestionCount == 0 },
              "keine offenen Vorschläge mehr (\(model.catalog?.suggestionCount ?? -1))")
        finish(lines, passed)
    }

    // MARK: Fenster und Knöpfe

    private static var catalogWindow: NSWindow? {
        NSApp.windows.first { $0.title.hasPrefix("Lagerkatalog") && $0.isVisible }
    }

    private static var zukaufWindow: NSWindow? {
        NSApp.windows.first { $0.title == "Zukaufteil hinzufügen" && $0.isVisible }
    }

    /// Flächen der SwiftUI-Knöpfe unter einer Ansicht (ihre Fokusringe), in Fensterkoordinaten.
    private static func buttonFrames(in view: NSView) -> [NSRect] {
        var out: [NSRect] = []
        func walk(_ v: NSView) {
            if !v.isHidden, String(describing: type(of: v)) == "_FocusRingView" {
                out.append(v.convert(v.bounds, to: nil))
            }
            v.subviews.forEach(walk)
        }
        walk(view)
        return out
    }

    private static func views<T: NSView>(_ type: T.Type, in view: NSView) -> [T] {
        var out: [T] = []
        func walk(_ v: NSView) {
            if let t = v as? T { out.append(t) }
            v.subviews.forEach(walk)
        }
        walk(view)
        return out
    }

    /// Spalten des Katalogfensters von links: Seitenleiste, Liste, Details.
    private static func columns(_ window: NSWindow) -> [NSView] {
        guard let root = window.contentView,
              let split = views(NSSplitView.self, in: root).max(by: { $0.subviews.count < $1.subviews.count })
        else { return [] }
        // macOS 26: die Seitenleiste schwebt über der Liste (gleiches minX), deshalb nach minX und Breite ordnen
        return split.subviews.filter { String(describing: type(of: $0)).contains("ItemViewWrapper") }
            .sorted { ($0.frame.minX, $0.frame.width) < ($1.frame.minX, $1.frame.width) }
    }

    /// Knopf „Freigeben“ (der rechte) in der Zeile des Eintrags im Abschnitt Vorschläge.
    private static func clickRowApprove(_ item: CatalogItem, model: AppModel) -> Bool {
        guard let window = catalogWindow, let catalog = model.catalog else { return false }
        let cols = columns(window)
        guard cols.count >= 2, let table = views(NSTableView.self, in: cols[1]).first else { return false }
        // Reihenfolge wie CatalogList: Abschnitt Zukaufteile, dann Lagerteile, je mit Überschrift
        let sorted = CatalogSearch.sorted(catalog.items).filter(\.vorgeschlagen)
        let zukauf = sorted.filter(\.isZukauf), stock = sorted.filter { !$0.isZukauf }
        var rows: [String?] = []
        if !zukauf.isEmpty { rows += [nil] + zukauf.map(\.id) }
        if !stock.isEmpty { rows += [nil] + stock.map(\.id) }
        guard let row = rows.firstIndex(of: item.id), row < table.numberOfRows,
              let rowView = table.rowView(atRow: row, makeIfNecessary: true)
        else { return false }
        guard let target = buttonFrames(in: rowView).max(by: { $0.minX < $1.minX }) else { return false }
        return click(at: NSPoint(x: target.midX, y: target.midY), in: window)
    }

    /// Knopf in der Aktionsleiste unten in den Details, `fromRight` 0 = ganz rechts.
    private static func clickDetailBar(fromRight: Int) -> Bool {
        guard let window = catalogWindow, let detail = columns(window).last else { return false }
        // nur sichtbare Knöpfe (das Formular darüber scrollt, seine Knöpfe können außerhalb liegen)
        let visible = detail.convert(detail.bounds, to: nil)
        let frames = buttonFrames(in: detail).filter { visible.contains(NSPoint(x: $0.midX, y: $0.midY)) }
        guard let bottom = frames.map(\.minY).min() else { return false }
        let bar = frames.filter { abs($0.minY - bottom) < 8 }.sorted { $0.minX > $1.minX }
        guard bar.indices.contains(fromRight) else { return false }
        return click(at: NSPoint(x: bar[fromRight].midX, y: bar[fromRight].midY), in: window)
    }

    /// Hauptknopf unten rechts im Zukauf-Dialog („Freigeben“).
    private static func clickDialogPrimary() -> Bool {
        guard let window = zukaufWindow, let root = window.contentView else { return false }
        let frames = buttonFrames(in: root).filter { root.bounds.contains(NSPoint(x: $0.midX, y: $0.midY)) }
        guard let bottom = frames.map(\.minY).min(),
              let target = frames.filter({ abs($0.minY - bottom) < 8 }).max(by: { $0.minX < $1.minX })
        else { return false }
        return click(at: NSPoint(x: target.midX, y: target.midY), in: window)
    }

    /// Klick als Maus-Ereignisse nur an dieses Fenster (kein echter Mauszeiger, kein anderes Programm betroffen).
    private static func click(at point: NSPoint, in window: NSWindow) -> Bool {
        window.makeKey()
        let hit = window.contentView?.superview?.hitTest(point) ?? window.contentView?.hitTest(point)
        FileHandle.standardError.write(Data(("[selbsttest-freigabe] Klick bei \(Int(point.x)),\(Int(point.y)) in "
            + "\(window.title): \(hit.map { String(describing: type(of: $0)) } ?? "nichts")\n").utf8))
        let time = ProcessInfo.processInfo.systemUptime
        func event(_ type: NSEvent.EventType, _ t: TimeInterval) -> NSEvent? {
            NSEvent.mouseEvent(with: type, location: point, modifierFlags: [], timestamp: t,
                               windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1,
                               pressure: type == .leftMouseDown ? 1 : 0)
        }
        guard let down = event(.leftMouseDown, time), let up = event(.leftMouseUp, time + 0.08) else { return false }
        NSApp.postEvent(down, atStart: false)
        NSApp.postEvent(up, atStart: false)
        return true
    }

    private static func finish(_ lines: [String], _ passed: Bool) {
        let text = (lines + [passed ? "Ergebnis: bestanden" : "Ergebnis: FEHLER"]).joined(separator: "\n") + "\n"
        try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-freigabe.txt"), atomically: true,
                        encoding: .utf8)
        FileHandle.standardError.write(Data("[selbsttest-freigabe]\n\(text)".utf8))
    }
}
