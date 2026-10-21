import AppKit
import MetalKit
import OCCTSwiftViewport
import SwiftUI

/// Der 3D-Bereich des Projektfensters: Viewport von OCCTSwiftViewport mit Picking, darüber Maße, Anmerkungen und
/// hervorgehobene Kanten. Kamera, Körper und Klicks verwaltet `AppController.viewport`.
public struct KevViewport: View {
    @ObservedObject private var coordinator: ViewportCoordinator
    @ObservedObject private var model: AppModel

    public init(controller: AppController) {
        self._coordinator = ObservedObject(wrappedValue: controller.viewport)
        self._model = ObservedObject(wrappedValue: controller.model)
    }

    public var body: some View {
        ZStack(alignment: .top) {
            MetalViewportView(controller: coordinator.controller, bodies: $coordinator.bodies)
                .background(MTKViewProbe { [weak c = coordinator] view in c?.attach(view) })
            OverlayCanvas(coordinator: coordinator, viewport: coordinator.controller)
                .allowsHitTesting(false)
            if let hint = coordinator.hint {
                Text(hint)
                    .font(.callout)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(.regularMaterial, in: Capsule())
                    .padding(.top, 10)
                    .allowsHitTesting(false)
            }
        }
    }
}

/// Zeichnet die Überlagerung; folgt jeder Kamerabewegung, weil sie den ViewportController beobachtet.
private struct OverlayCanvas: View {
    @ObservedObject var coordinator: ViewportCoordinator
    @ObservedObject var viewport: ViewportController

    var body: some View {
        Canvas { ctx, size in
            let items = coordinator.overlayItems
            guard !items.isEmpty, size.width > 0, size.height > 0 else { return }
            let projector = OverlayProjector(camera: viewport.cameraState, size: size)
            ctx.withCGContext { cg in OverlayPainter.draw(items, in: cg, projector: projector) }
        }
    }
}

/// Unsichtbarer Helfer: findet das MTKView, das MetalViewportView anlegt (wie im AP0-Test), damit die App die
/// Bildrate setzen und Klicks von Ziehbewegungen unterscheiden kann.
struct MTKViewProbe: NSViewRepresentable {
    let onFound: (MTKView) -> Void

    func makeNSView(context: Context) -> ProbeView {
        let v = ProbeView()
        v.onFound = onFound
        return v
    }

    func updateNSView(_ nsView: ProbeView, context: Context) {
        nsView.onFound = onFound
    }

    final class ProbeView: NSView {
        var onFound: ((MTKView) -> Void)?
        private var attempts = 0
        private weak var found: MTKView?

        override func hitTest(_ point: NSPoint) -> NSView? { nil }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            attempts = 0
            schedule()
        }

        private func schedule() {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in self?.search() }
        }

        private func search() {
            guard let window else { return }
            if let f = found, f.window === window {
                onFound?(f)
                return
            }
            let myFrame = convert(bounds, to: nil)
            var best: (MTKView, CGFloat)?
            var ancestor = superview
            while let a = ancestor, best == nil {
                for m in Self.collect(in: a) {
                    let f = m.convert(m.bounds, to: nil)
                    let d = hypot(f.midX - myFrame.midX, f.midY - myFrame.midY)
                    if best == nil || d < best!.1 { best = (m, d) }
                }
                ancestor = a.superview
            }
            if let (m, _) = best {
                found = m
                onFound?(m)
            } else {
                attempts += 1
                if attempts < 100 { schedule() }
            }
        }

        static func collect(in view: NSView) -> [MTKView] {
            var out: [MTKView] = []
            if let m = view as? MTKView { out.append(m) }
            for s in view.subviews { out.append(contentsOf: collect(in: s)) }
            return out
        }
    }
}
