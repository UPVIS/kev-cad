// Selbsttest der Testvariante, bisher nur am Mac (Fenster, Ereignisse, Bildschirmfotos über AppKit).
// iPad: Selbsttests im iPad-Simulator folgen in I-9.
#if os(macOS)
import AppKit
import KevCADCore

/// Selbsttest im Demomodus (`KEVCAD_SELFTEST=keys`): prüft, dass einbuchstabige Kürzel nicht feuern, solange ein
/// Textfeld den Fokus hat, und dass jede Taste der Belegung auf einem Menüpunkt liegt. Die Tastendrücke entstehen nur im
/// eigenen Prozess; die App bleibt im Hintergrund.
///
/// Weil eine Hintergrund-App keine Menükürzel ausführt, prüft der Test den Weg dorthin:
/// - Textfeld mit Fokus: H, 1, E landen im Feld, keine Aktion, und der `KeyboardGuard` hat alle drei abgefangen.
///   Ein lokaler Monitor, der `nil` zurückgibt, beendet die Verarbeitung, bevor AppKit Menükürzel prüft. Das Feld legt der
///   Test selbst an: Das Suchfeld der Werkstatt gibt es erst ab 13 Teilen, und dafür ist es ein Feld wie jedes andere.
/// - Ohne Textfeld: der `KeyboardGuard` lässt die Tasten durch, und im Menü liegen die Befehle mit genau diesen Tasten.
/// Ergebnis im Protokoll und in `<Datenordner>/selftest-keys.txt`.
@MainActor
enum SelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession) {
        guard !started, let demo = session.demo, demo.config.selfTest == "keys" else { return }
        started = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            MainActor.assumeIsolated { keys(session, demo) }
        }
    }

    private static func keys(_ session: AppSession, _ demo: DemoActions) {
        var lines: [String] = []
        var passed = true
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            lines.append("\(ok ? "OK    " : "FEHLER") \(text)")
        }

        guard let window = session.projectWindow else {
            finish(["FEHLER Projektfenster nicht gefunden"], passed: false)
            return
        }
        window.makeKey()
        lines.append("App aktiv: \(NSApp.isActive) (Hintergrundstart, Menükürzel selbst daher nicht auslösbar)")

        guard let inhalt = window.contentView else {
            finish(lines + ["FEHLER Fenster ohne Inhalt"], passed: false)
            return
        }
        let field = NSTextField(frame: NSRect(x: 10, y: 10, width: 200, height: 24))
        inhalt.addSubview(field)
        defer { field.removeFromSuperview() }
        let guardian = session.keyboard

        // 1. Ein Textfeld hat den Fokus.
        window.makeFirstResponder(field)
        demo.select(["Grundplatte"])
        var mark = demo.calls.count
        var bypassed = guardian.bypassCount
        send("h", keyCode: 4, to: window)
        send("1", keyCode: 18, to: window)
        send("e", keyCode: 14, to: window)
        let calls = Array(demo.calls[mark...])
        check(field.stringValue == "h1e", "Textfeld: getippt „\(field.stringValue)“ (erwartet „h1e“)")
        check(calls.isEmpty, "Textfeld: keine Aktion ausgelöst (\(calls.isEmpty ? "keine" : calls.joined(separator: ", ")))")
        check(guardian.bypassCount - bypassed == 3,
              "Textfeld: \(guardian.bypassCount - bypassed) von 3 Tasten am Menü vorbei ans Feld geleitet")
        for _ in 0..<3 { send("\u{7F}", keyCode: 51, to: window) }
        check(field.stringValue.isEmpty, "Textfeld mit Rückschritt geleert")

        // 2. Kein Textfeld im Fokus: Tasten gehen den normalen Weg zu den Menükürzeln.
        window.makeFirstResponder(nil)
        bypassed = guardian.bypassCount
        mark = demo.calls.count
        send("h", keyCode: 4, to: window)
        send("1", keyCode: 18, to: window)
        check(guardian.bypassCount == bypassed, "ohne Textfeld: Tasten nicht abgefangen, sie erreichen das Menü")
        let fired = Array(demo.calls[mark...])
        if !fired.isEmpty { lines.append("       (ausgelöst: \(fired.joined(separator: ", ")))") }

        // 3. Jede Taste der Belegung liegt auf einem Menüpunkt (dieselbe Quelle wie Viewport und Hinweisleiste)
        let items = menuItems(NSApp.mainMenu)
        for befehl in ViewerBefehl.allCases {
            guard let taste = Tastenbelegung.menuTaste(befehl), let key = taste.keyEquivalent else { continue }
            var modifiers: NSEvent.ModifierFlags = []
            if taste.mods.contains(.umschalt) { modifiers.insert(.shift) }
            if taste.mods.contains(.strg) { modifiers.insert(.control) }
            if taste.mods.contains(.wahl) { modifiers.insert(.option) }
            if taste.mods.contains(.befehl) { modifiers.insert(.command) }
            let zeichen = String(key.character).lowercased()
            let found = items.contains {
                $0.keyEquivalent.lowercased() == zeichen
                    && $0.keyEquivalentModifierMask.intersection([.command, .shift, .option, .control]) == modifiers
            }
            // Sonderzeichen wie / übersetzt AppKit je nach Tastatur (deutsch ⇧7); dann zählt, dass der Punkt eine Taste trägt
            let titel = Tastenbelegung.alle.first { $0.befehl == befehl }?.titel ?? ""
            let uebersetzt = !found && !(key.character.isLetter || key.character.isNumber)
                && items.contains { $0.title == titel && !$0.keyEquivalent.isEmpty }
            check(found || uebersetzt, "Menü: \(titel) auf \(zeichen == "\u{1B}" ? "Esc" : zeichen.uppercased())")
        }

        // 4. Die ganze Menüleiste in Reihenfolge (Titel und Kürzel) in eine eigene Datei: Die Menüs sind seit I-9 gemeinsam
        //    mit dem iPad (Menues/), ein Vergleich zweier Stände zeigt, ob sich am Mac etwas verschoben hat.
        let abzug = menueAbzug(NSApp.mainMenu, tiefe: 0)
        let ordner = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"].map { URL(fileURLWithPath: $0) }
            ?? AppInfo.supportDirectory  // kernel/tools/selbsttests.py holt den Ordner der Ausgabe zurück
        let datei = ordner.appendingPathComponent("selftest-keys-menue.txt")
        try? abzug.joined(separator: "\n").write(to: datei, atomically: true, encoding: .utf8)
        lines.append("Menüleiste: \(abzug.count) Einträge in \(datei.lastPathComponent)")

        demo.showAll()
        demo.setStandardView(.iso)
        window.makeFirstResponder(nil)
        finish(lines, passed: passed)
    }

    /// Eine Zeile je Menüeintrag: Einrückung, Titel, Kürzel (⌃⌥⇧⌘ und Taste).
    private static func menueAbzug(_ menu: NSMenu?, tiefe: Int) -> [String] {
        guard let menu else { return [] }
        return menu.items.flatMap { item -> [String] in
            let einzug = String(repeating: "  ", count: tiefe)
            var zeile = einzug + (item.isSeparatorItem ? "---" : item.title)
            if !item.keyEquivalent.isEmpty {
                let m = item.keyEquivalentModifierMask
                let mods = (m.contains(.control) ? "⌃" : "") + (m.contains(.option) ? "⌥" : "")
                    + (m.contains(.shift) ? "⇧" : "") + (m.contains(.command) ? "⌘" : "")
                let taste = item.keyEquivalent.unicodeScalars.map { String(format: "U+%04X", $0.value) }.joined()
                zeile += "  [\(mods)\(taste)]"
            }
            return [zeile] + menueAbzug(item.submenu, tiefe: tiefe + 1)
        }
    }

    private static func finish(_ lines: [String], passed: Bool) {
        let report = (["Selbsttest Tastenkürzel: \(passed ? "bestanden" : "NICHT bestanden")"] + lines)
            .joined(separator: "\n")
        let file = AppInfo.supportDirectory.appendingPathComponent("selftest-keys.txt")
        try? report.write(to: file, atomically: true, encoding: .utf8)
        print(report)
    }

    private static func send(_ characters: String, keyCode: UInt16, to window: NSWindow) {
        for type in [NSEvent.EventType.keyDown, .keyUp] {
            guard let event = NSEvent.keyEvent(
                with: type, location: .zero, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: window.windowNumber, context: nil, characters: characters,
                charactersIgnoringModifiers: characters, isARepeat: false, keyCode: keyCode)
            else { continue }
            NSApp.sendEvent(event)
        }
    }

    private static func menuItems(_ menu: NSMenu?) -> [NSMenuItem] {
        guard let menu else { return [] }
        return menu.items.flatMap { [$0] + menuItems($0.submenu) }
    }
}
#endif
