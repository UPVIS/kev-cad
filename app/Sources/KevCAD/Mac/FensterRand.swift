import AppKit
import KevCADCore
import QuartzCore

/// Fenster schmal an einen Bildschirmrand und zurück (Zustand c im Entwurf): rund 460 pt breit, volle Höhe des
/// sichtbaren Bildschirms (ohne Menüleiste und Dock). Zurück stellt Größe und Lage von vorher wieder her. Die Bewegung
/// läuft über die Fensteranimation von AppKit, der Hauptfaden bleibt frei.
@MainActor
final class FensterRand {
    /// Rahmen vor dem ersten Schritt an den Rand.
    private(set) var gemerkt: NSRect?
    private var schritt = 0

    func anwenden(_ rand: Bildschirmrand?, fenster: NSWindow?, weich: Bool = true) {
        guard let fenster, !fenster.styleMask.contains(.fullScreen) else { return }
        if let rand {
            guard let schirm = (fenster.screen ?? NSScreen.main)?.visibleFrame else { return }
            if gemerkt == nil { gemerkt = fenster.frame }
            let breite = min(GA.schmal, schirm.width)
            let x = rand == .links ? schirm.minX : schirm.maxX - breite
            setze(NSRect(x: x, y: schirm.minY, width: breite, height: schirm.height), fenster, weich)
        } else if let alt = gemerkt {
            gemerkt = nil
            setze(alt, fenster, weich)
        }
    }

    /// Beim Beenden ohne Animation zurück, damit das Fenster beim nächsten Start nicht schmal aufgeht.
    func sofortZurueck(_ fenster: NSWindow?) {
        guard let fenster, let alt = gemerkt else { return }
        gemerkt = nil
        fenster.setFrame(alt, display: false)
    }

    private func setze(_ r: NSRect, _ fenster: NSWindow, _ weich: Bool) {
        schritt += 1
        guard weich else {
            fenster.setFrame(r, display: true)
            return
        }
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = Gestaltung.Bewegung.rand
            ctx.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            ctx.allowsImplicitAnimation = true
            fenster.animator().setFrame(r, display: true)
        }
    }
}
