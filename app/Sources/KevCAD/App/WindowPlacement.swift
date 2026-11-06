import AppKit
import KevCADCore
import SwiftUI

/// Wo ein Fenster der Testvariante auf dem zweiten Monitor liegt.
enum TestPlacement {
    /// großes Fenster oben links (Hauptfenster)
    case large
    /// in der Mitte, Größe aus dem Inhalt (Dialog Zukaufteil)
    case centered
    /// rechts neben dem Hauptfenster (Protokoll, Lagerkatalog)
    case trailing(width: CGFloat, height: CGFloat)
}

/// Meldet das NSWindow einer Szene an die Sitzung und legt Fenster der Testvariante auf den zweiten Monitor,
/// damit Tests den Hauptbildschirm nicht stören (CLAUDE.md, Tests mit Oberfläche).
struct WindowHook: NSViewRepresentable {
    var placement: TestPlacement
    var onWindow: (NSWindow) -> Void = { _ in }

    func makeNSView(context: Context) -> HookView {
        let view = HookView()
        view.placement = placement
        view.onWindow = onWindow
        return view
    }

    func updateNSView(_ nsView: HookView, context: Context) {}

    final class HookView: NSView {
        var placement: TestPlacement = .large
        var onWindow: (NSWindow) -> Void = { _ in }
        private weak var placedWindow: NSWindow?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            guard let window, window !== placedWindow else { return }
            placedWindow = window
            WindowHook.verstecken(window)
            onWindow(window)
            // SwiftUI setzt die Startgröße erst nach dem ersten Layout; danach verschieben.
            DispatchQueue.main.async { [placement] in
                WindowHook.place(window, placement)
            }
        }
    }

    /// `KEVCAD_TEST_VERSTECKT=1` (nur Testvariante, Tests ohne zweiten Monitor): Das Fenster liegt hinter dem
    /// Schreibtischbild. Niemand sieht es, Klicks gehen daran vorbei, und es zeichnet weiter (Vorbild Sichtung).
    static var versteckt: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_TEST_VERSTECKT"] == "1"
    }

    static func verstecken(_ window: NSWindow) {
        guard versteckt else { return }
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopWindow)) - 1)
        window.ignoresMouseEvents = true
        window.collectionBehavior.insert([.transient, .ignoresCycle, .stationary])
    }

    static func place(_ window: NSWindow, _ placement: TestPlacement) {
        guard AppInfo.isTestVariant, !versteckt else { return }
        let screens = NSScreen.screens
        guard screens.count > 1 else { return }
        let frame = screens[1].visibleFrame
        var target: NSRect
        switch placement {
        case .large:
            let size = NSSize(width: min(1400, frame.width - 80), height: min(900, frame.height - 80))
            target = NSRect(x: frame.minX + 40, y: frame.maxY - size.height - 40, width: size.width, height: size.height)
        case .centered:
            let size = window.frame.size
            target = NSRect(
                x: frame.midX - size.width / 2, y: frame.midY - size.height / 2, width: size.width, height: size.height)
        case .trailing(let width, let height):
            let size = NSSize(width: min(width, frame.width - 80), height: min(height, frame.height - 80))
            let x = min(frame.minX + 40 + 1400 + 24, frame.maxX - size.width - 40)
            target = NSRect(x: x, y: frame.maxY - size.height - 40, width: size.width, height: size.height)
        }
        window.setFrame(target, display: true)
    }
}
