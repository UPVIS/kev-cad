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
            check(found, "Menü: \(befehl.rawValue) auf \(zeichen == "\u{1B}" ? "Esc" : zeichen.uppercased()) \(modifiers.rawValue)")
        }

        demo.showAll()
        demo.setStandardView(.iso)
        window.makeFirstResponder(nil)
        finish(lines, passed: passed)
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
