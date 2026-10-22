import AppKit

/// Sorgt dafür, dass einbuchstabige Tastenkürzel (1 bis 0, F, H, I, M, S, E, Umschalt-H, Esc, Leertaste, Pfeile) nicht
/// feuern, solange ein Textfeld den Fokus hat; die Pfeiltasten der Animation auch nicht in Listen (Teilebaum, Stückliste).
///
/// Menüpunkte mit Tastenkürzel ohne Befehlstaste fangen sonst Tastendrücke ab, bevor sie das Textfeld erreichen
/// (AppKit prüft Tastenkürzel vor der normalen Tastenverarbeitung). Der lokale Ereignismonitor läuft noch davor:
/// Hat ein Textfeld den Fokus, schickt er solche Tasten direkt an das Fenster, also an das Textfeld, und am Menü vorbei.
@MainActor
final class KeyboardGuard {
    /// Tasten, die als einbuchstabige Kürzel belegt sind (ohne Befehls-, Control- und Wahltaste).
    static let plainShortcutKeys: Set<String> = [
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "f", "h", "i", "m", "s", "e",
        " ", arrowLeft, arrowRight,  // Phase 5: Animation (Leertaste, Pfeil links/rechts)
        "v", "d", "n",  // Phase 6: Werkzeuge im Bereich Dokumente (Auswählen, Maß, Notiz)
    ]
    static let arrowLeft = String(UnicodeScalar(UInt16(NSLeftArrowFunctionKey))!)
    static let arrowRight = String(UnicodeScalar(UInt16(NSRightArrowFunctionKey))!)
    static let escapeKeyCode: UInt16 = 53

    weak var projectWindow: NSWindow?
    private var monitor: Any?
    /// Zahl der Tastendrücke, die am Menü vorbei ans Textfeld gingen (für den Selbsttest).
    private(set) var bypassCount = 0

    func install() {
        guard monitor == nil else { return }
        // Lokale Monitore laufen immer auf dem Hauptthread.
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            nonisolated(unsafe) let event = event
            let consumed = MainActor.assumeIsolated { self?.forwardToTextInput(event) ?? false }
            return consumed ? nil : event
        }
    }

    /// Schickt den Tastendruck direkt ans Textfeld, wenn nötig; `true` heißt erledigt.
    private func forwardToTextInput(_ event: NSEvent) -> Bool {
        guard let window = event.window ?? NSApp.keyWindow,
              Self.shouldBypassMenu(event: event, responder: window.firstResponder,
                                    isProjectWindow: window === projectWindow)
        else { return false }
        bypassCount += 1
        window.sendEvent(event)
        return true
    }

    /// Entscheidet, ob ein Tastendruck am Menü vorbei direkt ans Textfeld gehen soll.
    static func shouldBypassMenu(event: NSEvent, responder: NSResponder?, isProjectWindow: Bool) -> Bool {
        guard event.type == .keyDown else { return false }
        if !isTextInput(responder) {
            // Pfeiltasten gehören in Listen und Tabellen der Liste, nicht der Zeitleiste
            guard responder is NSTableView, event.modifierFlags.intersection([.command, .control, .option]).isEmpty,
                  let key = event.charactersIgnoringModifiers, key == arrowLeft || key == arrowRight
            else { return false }
            return true
        }
        if !event.modifierFlags.intersection([.command, .control, .option]).isEmpty { return false }
        if event.keyCode == escapeKeyCode {
            // Esc leert sonst die Auswahl; in Sheets bleibt Esc beim Abbrechen-Knopf.
            return isProjectWindow
        }
        guard let key = event.charactersIgnoringModifiers?.lowercased() else { return false }
        return plainShortcutKeys.contains(key)
    }

    /// Textfeld, Suchfeld oder Texteditor mit Fokus (bei Feldern ist der Fokus der gemeinsame Feld-Editor).
    static func isTextInput(_ responder: NSResponder?) -> Bool {
        if let textView = responder as? NSTextView { return textView.isEditable || textView.isFieldEditor }
        if let field = responder as? NSTextField { return field.isEditable }
        return false
    }
}
