#if os(macOS)
import AppKit
#else
import UIKit
import UIKit.UIGestureRecognizerSubclass
#endif

// I-6 (PLAN-IPAD.md, Abschnitt 5): Wer bedient gerade? Die Live-Kopplung muss wissen, wann Kevin an diesem Gerät die
// Ansicht anfasst (Führung, Griff, AKTIV), ohne in die Gesten selbst einzugreifen. Am Mac schaut ein lokaler
// Ereignismonitor auf Maus, Trackpad und Tasten über der Eingabeebene, am iPad ein stiller Gestenerkenner auf der
// Eingabeebene, der nie erkennt und keine Berührung abfängt.

extension ViewportCoordinator {
    /// Beobachter für `onEingabe` anbringen (nach dem Setzen von `onEingabe` und bei jeder neuen Eingabeebene).
    func eingabeBeobachterAnbringen() {
        guard onEingabe != nil else { return }
        #if os(macOS)
        guard eingabeMonitor == nil else { return }
        let arten: NSEvent.EventTypeMask = [
            .leftMouseDown, .leftMouseDragged, .rightMouseDown, .rightMouseDragged, .otherMouseDown, .otherMouseDragged,
            .scrollWheel, .magnify, .keyDown,
        ]
        eingabeMonitor = NSEvent.addLocalMonitorForEvents(matching: arten) { [weak self] e in
            nonisolated(unsafe) let e = e
            MainActor.assumeIsolated { self?.eingabeEreignis(e) }
            return e
        }
        #else
        guard let v = eingabeView else { return }
        if let alt = eingabeBeobachter as? EingabeBeobachter, alt.view === v { return }
        let b = EingabeBeobachter { [weak self] in self?.onEingabe?() }
        v.addGestureRecognizer(b)
        eingabeBeobachter = b
        #endif
    }

    // Mac: Ereignisse des Monitors prüfen. iPad: der stille Gestenerkenner unten meldet selbst.
    #if os(macOS)
    private func eingabeEreignis(_ e: NSEvent) {
        guard let v = eingabeView, let w = v.window, e.window === w, eingabeAktiv else { return }
        if e.type == .keyDown {
            if w.firstResponder === v { onEingabe?() }
            return
        }
        let p = v.convert(e.locationInWindow, from: nil)
        if v.bounds.contains(p) || e.type.istZiehen { onEingabe?() }
    }
    #endif
}

#if os(macOS)
private extension NSEvent.EventType {
    /// Ziehen, das im Viewer begann, darf ihn verlassen und bleibt Bedienung.
    var istZiehen: Bool { self == .leftMouseDragged || self == .rightMouseDragged || self == .otherMouseDragged }
}
#else
/// Stiller Erkenner: meldet jede Berührung (Finger, Stift, Trackpad) und lässt sie unverändert durch.
final class EingabeBeobachter: UIGestureRecognizer {
    private let melden: @MainActor () -> Void

    init(_ melden: @escaping @MainActor () -> Void) {
        self.melden = melden
        super.init(target: nil, action: nil)
        cancelsTouchesInView = false
        delaysTouchesBegan = false
        delaysTouchesEnded = false
    }

    override func canPrevent(_ preventedGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func canBePrevented(by preventingGestureRecognizer: UIGestureRecognizer) -> Bool { false }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) { melden() }
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent) { melden() }
    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent) {
        if numberOfTouches <= touches.count { state = .failed }
    }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent) { state = .failed }

    override func shouldRequireFailure(of otherGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func shouldBeRequiredToFail(by otherGestureRecognizer: UIGestureRecognizer) -> Bool { false }
}
#endif
