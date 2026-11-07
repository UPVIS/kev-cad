import KevCADCore
import SwiftUI
import UIKit

/// Vom Rand wischen (PLAN-IPAD.md 4.2, I-3b): vom linken Rand öffnet die Gliederung, vom rechten die Eigenschaften, wie
/// ⌘1 und ⌘2 am Mac. Die Gesten hängen am Fenster, nicht am Viewer: So wirken sie auch neben Kacheln, und die Gesten des
/// Viewers warten, bis feststeht, dass es kein Wischen vom Rand ist (das entscheidet sich gleich beim Aufsetzen).
/// Nur iPad: Am Mac gibt es keinen Rand zum Wischen, dort bleiben ⌘1 und ⌘2.
struct RandWischen: UIViewRepresentable {
    @ObservedObject var oberflaeche: OberflaechenStore
    let actions: OberflaechenActions?

    func makeUIView(context: Context) -> RandWischenView {
        let v = RandWischenView()
        v.isUserInteractionEnabled = false
        v.oeffnen = { rand in context.coordinator.oeffnen(rand) }
        return v
    }

    func updateUIView(_ uiView: RandWischenView, context: Context) {
        context.coordinator.oberflaeche = oberflaeche
        context.coordinator.actions = actions
    }

    func makeCoordinator() -> Koordinator { Koordinator(oberflaeche: oberflaeche, actions: actions) }

    @MainActor
    final class Koordinator {
        var oberflaeche: OberflaechenStore
        var actions: OberflaechenActions?

        init(oberflaeche: OberflaechenStore, actions: OberflaechenActions?) {
            self.oberflaeche = oberflaeche
            self.actions = actions
        }

        func oeffnen(_ rand: UIRectEdge) {
            if rand == .left, !oberflaeche.leisteLinks {
                withAnimation(GB.standard) { actions?.setzeLeisteLinks(true) }
                UISelectionFeedbackGenerator().selectionChanged()
            } else if rand == .right, !oberflaeche.leisteRechts {
                withAnimation(GB.standard) { actions?.setzeLeisteRechts(true) }
                UISelectionFeedbackGenerator().selectionChanged()
            }
        }
    }
}

/// Unsichtbar; hängt beim Erscheinen zwei Randgesten ans Fenster.
final class RandWischenView: UIView {
    var oeffnen: ((UIRectEdge) -> Void)?
    private var gesten: [UIScreenEdgePanGestureRecognizer] = []
    private let regeln = RandRegeln()

    override func didMoveToWindow() {
        super.didMoveToWindow()
        for g in gesten { g.view?.removeGestureRecognizer(g) }
        gesten = []
        guard let window else { return }
        for rand in [UIRectEdge.left, .right] {
            let g = UIScreenEdgePanGestureRecognizer(target: self, action: #selector(gewischt(_:)))
            g.edges = rand
            g.delegate = regeln
            g.name = rand == .left ? "rand.links" : "rand.rechts"
            window.addGestureRecognizer(g)
            gesten.append(g)
        }
    }

    @objc private func gewischt(_ g: UIScreenEdgePanGestureRecognizer) {
        guard g.state == .began else { return }
        oeffnen?(g.edges)
    }
}

/// Regeln der Randgesten (eigenes Objekt: UIView hat selbst ein `gestureRecognizerShouldBegin`).
final class RandRegeln: NSObject, UIGestureRecognizerDelegate {
    // Über einem Blatt (Kopplung, Dialoge) gehört der Rand dem Blatt
    func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
        g.view?.window?.rootViewController?.presentedViewController == nil
    }

    // Die übrigen Gesten (Drehen mit einem Finger, Listen) warten, bis feststeht, dass es kein Wischen vom Rand ist
    func gestureRecognizer(_ g: UIGestureRecognizer, shouldBeRequiredToFailBy other: UIGestureRecognizer) -> Bool {
        !(other is UIScreenEdgePanGestureRecognizer) && other.view !== g.view
    }
}
