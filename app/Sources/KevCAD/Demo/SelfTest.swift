import AppKit
import KevCADCore

/// Selbsttest im Demomodus (`KEVCAD_SELFTEST=keys`): prüft, dass einbuchstabige Kürzel nicht feuern, solange ein
/// Textfeld den Fokus hat. Die Tastendrücke entstehen nur im eigenen Prozess; die App bleibt im Hintergrund.
///
/// Weil eine Hintergrund-App keine Menükürzel ausführt, prüft der Test den Weg dorthin:
/// - Suchfeld mit Fokus: H, 1, E landen im Feld, keine Aktion, und der `KeyboardGuard` hat alle drei abgefangen.
///   Ein lokaler Monitor, der `nil` zurückgibt, beendet die Verarbeitung, bevor AppKit Menükürzel prüft.
/// - Ohne Textfeld: der `KeyboardGuard` lässt die Tasten durch, und im Menü liegen die Befehle mit genau diesen
///   Tasten ohne Zusatztaste.
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

        guard let field = findSearchField(in: window.contentView?.superview ?? window.contentView) else {
            finish(lines + ["FEHLER Suchfeld im Projektfenster nicht gefunden"], passed: false)
            return
        }
        let guardian = session.keyboard

        // 1. Suchfeld hat den Fokus.
        window.makeFirstResponder(field)
        demo.select(["Grundplatte"])
        var mark = demo.calls.count
        var bypassed = guardian.bypassCount
        send("h", keyCode: 4, to: window)
        send("1", keyCode: 18, to: window)
        send("e", keyCode: 14, to: window)
        let calls = Array(demo.calls[mark...])
        check(field.stringValue == "h1e", "Suchfeld: getippt „\(field.stringValue)“ (erwartet „h1e“)")
        check(calls.isEmpty, "Suchfeld: keine Aktion ausgelöst (\(calls.isEmpty ? "keine" : calls.joined(separator: ", ")))")
        check(guardian.bypassCount - bypassed == 3,
              "Suchfeld: \(guardian.bypassCount - bypassed) von 3 Tasten am Menü vorbei ans Feld geleitet")
        for _ in 0..<3 { send("\u{7F}", keyCode: 51, to: window) }
        check(field.stringValue.isEmpty, "Suchfeld mit Rückschritt geleert")

        // 2. Kein Textfeld im Fokus: Tasten gehen den normalen Weg zu den Menükürzeln.
        window.makeFirstResponder(nil)
        bypassed = guardian.bypassCount
        mark = demo.calls.count
        send("h", keyCode: 4, to: window)
        send("1", keyCode: 18, to: window)
        check(guardian.bypassCount == bypassed, "ohne Textfeld: Tasten nicht abgefangen, sie erreichen das Menü")
        let fired = Array(demo.calls[mark...])
        if !fired.isEmpty { lines.append("       (ausgelöst: \(fired.joined(separator: ", ")))") }

        let expected: [(String, NSEvent.ModifierFlags, String)] = [
            ("1", [], "Oben"), ("2", [], "Vorne"), ("3", [], "Rechts"), ("4", [], "Hinten"), ("5", [], "Links"),
            ("6", [], "Unten"), ("7", [], "Isometrisch"), ("f", [], "einpassen"), ("h", [], "Ausblenden"),
            ("i", [], "Isolieren"), ("h", .shift, "Alles einblenden"), ("m", [], "Messen"), ("s", [], "Schnitt"),
            ("e", [], "Explosion"), ("\u{1B}", [], "Auswahl aufheben"), ("r", .command, "Neu rechnen"),
        ]
        let items = menuItems(NSApp.mainMenu)
        for (key, modifiers, title) in expected {
            let found = items.contains {
                $0.keyEquivalent.lowercased() == key
                    && $0.keyEquivalentModifierMask.intersection([.command, .shift, .option, .control]) == modifiers
                    && $0.title.contains(title)
            }
            let shown = key == "\u{1B}" ? "Esc" : (modifiers.contains(.shift) ? "⇧" : "")
                + (modifiers.contains(.command) ? "⌘" : "") + (key == "\u{1B}" ? "" : key.uppercased())
            check(found, "Menü: „\(title)“ auf \(shown)")
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

    private static func findSearchField(in view: NSView?) -> NSSearchField? {
        guard let view else { return nil }
        if let field = view as? NSSearchField { return field }
        for subview in view.subviews {
            if let found = findSearchField(in: subview) { return found }
        }
        return nil
    }
}
