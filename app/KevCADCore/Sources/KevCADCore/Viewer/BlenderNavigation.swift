import AppKit
import OCCTSwiftViewport
import QuartzCore
import SwiftUI
import simd

// Steuerung wie in Blender (Standardbelegung, Z oben, Drehen im Turntable-Stil um den Ansichtsmittelpunkt):
//
// | Eingabe                                   | Wirkung                                          |
// |-------------------------------------------|--------------------------------------------------|
// | Mittlere Maustaste ziehen                 | drehen                                           |
// | Umschalt + mittlere Maustaste             | schwenken                                        |
// | Strg + mittlere Maustaste                 | zoomen (nach oben = näher)                       |
// | Mausrad                                   | zoomen; Strg + Rad schwenkt waagrecht, Umschalt senkrecht |
// | Trackpad mit zwei Fingern                 | drehen; mit Umschalt schwenken, mit Strg zoomen  |
// | Trackpad zusammenziehen/spreizen          | zoomen                                           |
// | Wahltaste + linke Maustaste (3-Tasten-Emulation) | wie mittlere Maustaste                    |
// | Wahltaste + mittlere Maustaste klicken    | Ansicht auf den Punkt unter der Maus zentrieren  |
// | Linke Maustaste klicken                   | auswählen; Umschalt fügt hinzu/entfernt; Klick ins Leere hebt auf |
// | Linke Maustaste ziehen                    | Rahmen aufziehen; Umschalt erweitert, Strg zieht ab |
// | Rechte Maustaste                          | Kontextmenü                                      |
//
// Kein Einrasten auf Standardansichten, kein Nachlaufen. Die Tastatur (Ziffernblock bzw. Zahlenreihe, Komma, Pos1 …)
// belegt die Oberfläche über NavigationActions.

enum BlenderNav {
    /// Blender: 0,4° je Punkt (view_rotate_sensitivity_turntable).
    static let orbitPerPoint: Float = 0.4 * .pi / 180
    /// Mausrad: Faktor je Raste.
    static let wheelStep: Float = 1.2
    /// Ziehen zum Zoomen: Faktor e^(k·Punkte).
    static let zoomPerPoint: Float = 0.01
    /// Ab so vielen Punkten Bewegung ist ein Klick ein Ziehen.
    static let dragThreshold: CGFloat = 3
}

// MARK: - Kamera

extension ViewportCoordinator {
    /// Welt-Millimeter je Bildschirmpunkt in der Ebene des Drehpunkts.
    func worldPerPoint(_ c: CameraState) -> Float {
        let h = Float(max(viewSize.height, 1))
        if c.isOrthographic { return c.orthographicScale / h }
        return 2 * c.distance * tan(c.fieldOfView * .pi / 360) / h
    }

    /// Kamera sofort setzen (laufende Fahrt abbrechen, sonst überschreibt sie die Eingabe).
    func setCamera(_ c: CameraState) {
        controller.cameraController.cancelAnimation()
        controller.animateTo(c, duration: 0)
    }

    /// Kamera mit Blenders „Smooth View“ (0,2 s) setzen.
    func smoothCamera(_ c: CameraState, duration: Float = 0.2) {
        controller.animateTo(c, duration: duration)
    }

    /// Automatische Parallelprojektion einer Achsansicht beim Drehen wieder aufheben (Blender „Auto Perspective“).
    private func leaveAutoOrtho(_ c: inout CameraState) {
        if autoOrtho, c.isOrthographic { c = Self.withProjection(c, orthographic: false) }
        autoOrtho = false
    }

    /// Drehen um den Drehpunkt: waagrecht um die Welt-Z-Achse, senkrecht um die Querachse der Ansicht.
    /// `dx`, `dy` in Punkten, `dy` positiv nach oben (wie Mausbewegung).
    public func navOrbit(dx: Float, dy: Float) {
        var c = controller.cameraState
        leaveAutoOrtho(&c)
        let s = BlenderNav.orbitPerPoint
        let yaw = simd_quatf(angle: -dx * s, axis: SIMD3<Float>(0, 0, 1))
        let pitch = simd_quatf(angle: dy * s, axis: SIMD3<Float>(1, 0, 0))
        c.rotation = simd_normalize(yaw * c.rotation * pitch)
        setCamera(c)
    }

    /// Schwenken: das Modell folgt der Maus.
    public func navPan(dx: Float, dy: Float) {
        var c = controller.cameraState
        let w = worldPerPoint(c)
        c.pivot -= c.rightVector * (dx * w) + c.upVector * (dy * w)
        setCamera(c)
    }

    /// Zoomen um den Drehpunkt; `factor` < 1 = näher heran.
    public func navZoom(factor: Float) {
        guard factor.isFinite, factor > 0 else { return }
        var c = controller.cameraState
        if c.isOrthographic {
            c.orthographicScale = min(max(c.orthographicScale * factor, 0.001), 1e7)
        } else {
            c.distance = min(max(c.distance * factor, 0.01), 1e7)
        }
        setCamera(c)
    }

    /// Ziffernblock 1/3/7 (mit Strg Gegenseite): Blickrichtung, Drehpunkt und Abstand bleiben, automatisch parallel.
    public func navAxisView(_ view: StandardView) {
        var c = controller.cameraState
        c.rotation = view.rotation
        if !c.isOrthographic {
            c = Self.withProjection(c, orthographic: true)
            autoOrtho = true
        }
        smoothCamera(c)
    }

    /// Ziffernblock 5.
    public func navToggleProjection() {
        let c = controller.cameraState
        autoOrtho = false
        smoothCamera(Self.withProjection(c, orthographic: !c.isOrthographic), duration: 0.15)
    }

    /// Ziffernblock 9: Gegenseite. Oben/unten werden getauscht, sonst um 180° um Z gedreht.
    public func navOpposite() {
        var c = controller.cameraState
        let look = c.viewDirection
        if abs(look.z) > 0.999 {
            c.rotation = simd_normalize(c.rotation * simd_quatf(angle: .pi, axis: SIMD3<Float>(0, 1, 0)))
        } else {
            c.rotation = simd_normalize(simd_quatf(angle: .pi, axis: SIMD3<Float>(0, 0, 1)) * c.rotation)
        }
        smoothCamera(c)
    }

    /// Ziffernblock 4/6/8/2: Schritte in Grad.
    public func navOrbitStep(yaw: Float, pitch: Float) {
        var c = controller.cameraState
        leaveAutoOrtho(&c)
        let q = simd_quatf(angle: yaw * .pi / 180, axis: SIMD3<Float>(0, 0, 1))
        let p = simd_quatf(angle: pitch * .pi / 180, axis: SIMD3<Float>(1, 0, 0))
        c.rotation = simd_normalize(q * c.rotation * p)
        smoothCamera(c, duration: 0.12)
    }

    /// Strg + Ziffernblock: schwenken um einen Anteil der Bildhöhe (positiv x = Ansicht nach rechts).
    public func navPanStep(x: Float, y: Float) {
        var c = controller.cameraState
        let h = worldPerPoint(c) * Float(max(viewSize.height, 1))
        c.pivot += c.rightVector * (x * h) + c.upVector * (y * h)
        smoothCamera(c, duration: 0.12)
    }

    /// Kamera auf einen Punkt zentrieren (Blender: Wahltaste + mittlere Maustaste), Richtung und Abstand bleiben.
    public func navCenter(on point: SIMD3<Float>) {
        var c = controller.cameraState
        c.pivot = point
        c.panOffset = .zero
        smoothCamera(c)
    }
}

// MARK: - Picking aus der Eingabeebene

extension ViewportCoordinator {
    var renderer: ViewportRenderer? { mtkView?.delegate as? ViewportRenderer }

    /// Punkt in der Eingabeebene → Pixel im Zeichenpuffer (Ursprung oben links), wie performPick es erwartet.
    func pixel(for point: CGPoint, in view: NSView) -> SIMD2<Int>? {
        guard let mtk = mtkView, mtk.bounds.width > 0, mtk.bounds.height > 0 else { return nil }
        let p = mtk.convert(point, from: view)
        let ds = mtk.drawableSize
        let x = p.x / mtk.bounds.width * ds.width
        let y = (mtk.isFlipped ? p.y : mtk.bounds.height - p.y) / mtk.bounds.height * ds.height
        return SIMD2(Int(x), Int(y))
    }

    func pickPoint(_ point: CGPoint, in view: NSView, completion: @escaping @MainActor (PickResult?) -> Void) {
        guard let r = renderer, let px = pixel(for: point, in: view) else {
            completion(nil)
            return
        }
        r.performPick(at: px) { result in
            Task { @MainActor in completion(result) }
        }
    }

    func pickRect(_ rect: CGRect, in view: NSView, completion: @escaping @MainActor ([PickResult]) -> Void) {
        guard let r = renderer,
            let a = pixel(for: CGPoint(x: rect.minX, y: rect.minY), in: view),
            let b = pixel(for: CGPoint(x: rect.maxX, y: rect.maxY), in: view)
        else {
            completion([])
            return
        }
        let px = CGRect(
            x: min(a.x, b.x), y: min(a.y, b.y), width: abs(a.x - b.x) + 1, height: abs(a.y - b.y) + 1)
        r.performRegionPick(rect: px) { results in
            Task { @MainActor in completion(results) }
        }
    }

    /// Weltpunkt unter der Maus auf dem getroffenen Dreieck (für „Ansicht auf Mauspunkt zentrieren“).
    func surfacePoint(of pick: PickResult, at point: CGPoint, in view: NSView) -> SIMD3<Float>? {
        guard pick.kind == .face, let body = bodies.first(where: { $0.id == pick.bodyID }) else { return nil }
        let t = pick.triangleIndex
        guard t >= 0, (t + 1) * 3 <= body.indices.count else { return nil }
        func vertex(_ i: UInt32) -> SIMD3<Float> {
            let k = Int(i)
            let local: SIMD3<Float>
            if body.usesDirectMesh {
                local = SIMD3(body.meshPositions[k * 3], body.meshPositions[k * 3 + 1], body.meshPositions[k * 3 + 2])
            } else {
                local = SIMD3(body.vertexData[k * 6], body.vertexData[k * 6 + 1], body.vertexData[k * 6 + 2])
            }
            let w = body.transform * SIMD4<Float>(local, 1)
            return SIMD3(w.x, w.y, w.z)
        }
        let v0 = vertex(body.indices[t * 3]), v1 = vertex(body.indices[t * 3 + 1]), v2 = vertex(body.indices[t * 3 + 2])
        // Strahl durch den Mauspunkt
        let c = controller.cameraState
        let size = viewSize
        guard size.width > 0, size.height > 0 else { return (v0 + v1 + v2) / 3 }
        let proj = c.projectionMatrix(aspectRatio: Float(size.width / size.height), near: 0.01, far: 1e7)
        let inv = simd_inverse(proj * c.viewMatrix)
        let ndc = SIMD2<Float>(Float(point.x / size.width) * 2 - 1, Float(point.y / size.height) * 2 - 1)
        func unproject(_ z: Float) -> SIMD3<Float> {
            let p = inv * SIMD4<Float>(ndc.x, ndc.y, z, 1)
            return SIMD3(p.x, p.y, p.z) / p.w
        }
        let o = unproject(0.1)
        let d = simd_normalize(unproject(0.9) - o)
        let e1 = v1 - v0, e2 = v2 - v0
        let h = simd_cross(d, e2)
        let a = simd_dot(e1, h)
        guard abs(a) > 1e-12 else { return (v0 + v1 + v2) / 3 }
        let f = 1 / a
        let s = o - v0
        let q = simd_cross(s, e1)
        let dist = f * simd_dot(e2, q)
        return dist > 0 ? o + d * dist : (v0 + v1 + v2) / 3
    }
}

// MARK: - Eingabeebene

/// Liegt über dem MTKView und nimmt alle Maus- und Trackpad-Eingaben im Viewport entgegen. Das Paket selbst bekommt
/// keine Mausereignisse mehr (dort sitzen Einrasten und Nachlaufen).
final class NavigationInputView: NSView {
    weak var coordinator: ViewportCoordinator?

    private enum Mode {
        case idle
        case pendingSelect(start: CGPoint, modifiers: NSEvent.ModifierFlags)
        case boxSelect(start: CGPoint, modifiers: NSEvent.ModifierFlags)
        case orbit, pan, zoom
        case pendingCenter(start: CGPoint)
    }

    private var mode: Mode = .idle
    private var last = CGPoint.zero
    private let boxLayer = CAShapeLayer()

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        boxLayer.fillColor = NSColor.controlAccentColor.withAlphaComponent(0.08).cgColor
        boxLayer.strokeColor = NSColor.white.withAlphaComponent(0.9).cgColor
        boxLayer.lineWidth = 1
        boxLayer.lineDashPattern = [4, 3]
        boxLayer.isHidden = true
        layer?.addSublayer(boxLayer)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) wird nicht benutzt") }

    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func layout() {
        super.layout()
        coordinator?.viewSize = bounds.size
    }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        coordinator?.viewSize = newSize
    }

    private func point(_ event: NSEvent) -> CGPoint { convert(event.locationInWindow, from: nil) }

    /// Navigationsart aus den Sondertasten (wie mittlere Maustaste in Blender).
    private func navMode(_ flags: NSEvent.ModifierFlags) -> Mode {
        if flags.contains(.shift) { return .pan }
        if flags.contains(.control) || flags.contains(.command) { return .zoom }
        return .orbit
    }

    private func apply(_ dx: CGFloat, _ dy: CGFloat) {
        guard let c = coordinator else { return }
        switch mode {
        case .orbit: c.navOrbit(dx: Float(dx), dy: Float(dy))
        case .pan: c.navPan(dx: Float(dx), dy: Float(dy))
        case .zoom: c.navZoom(factor: exp(-Float(dy) * BlenderNav.zoomPerPoint))
        default: break
        }
    }

    // Linke Maustaste: auswählen, Rahmen; mit Wahltaste wie mittlere Maustaste

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        let p = point(event)
        last = p
        let flags = event.modifierFlags
        if flags.contains(.option) {
            mode = navMode(flags)
        } else {
            mode = .pendingSelect(start: p, modifiers: flags)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        let p = point(event)
        defer { last = p }
        switch mode {
        case .pendingSelect(let start, let flags):
            if hypot(p.x - start.x, p.y - start.y) > BlenderNav.dragThreshold {
                mode = .boxSelect(start: start, modifiers: flags)
                drawBox(from: start, to: p)
            }
        case .boxSelect(let start, _):
            drawBox(from: start, to: p)
        default:
            apply(p.x - last.x, p.y - last.y)
        }
    }

    override func mouseUp(with event: NSEvent) {
        let p = point(event)
        switch mode {
        case .pendingSelect(_, let flags):
            coordinator?.pickPoint(p, in: self) { [weak self] result in
                self?.coordinator?.onClick?(result, flags)
            }
        case .boxSelect(let start, let flags):
            boxLayer.isHidden = true
            let rect = CGRect(
                x: min(start.x, p.x), y: min(start.y, p.y), width: abs(p.x - start.x), height: abs(p.y - start.y))
            coordinator?.pickRect(rect, in: self) { [weak self] results in
                self?.coordinator?.onBoxSelect?(results, flags)
            }
        default:
            break
        }
        mode = .idle
    }

    private func drawBox(from a: CGPoint, to b: CGPoint) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        boxLayer.frame = bounds
        boxLayer.path = CGPath(
            rect: CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y)),
            transform: nil)
        boxLayer.isHidden = false
        CATransaction.commit()
    }

    // Mittlere Maustaste

    override func otherMouseDown(with event: NSEvent) {
        guard event.buttonNumber == 2 else { return }
        window?.makeFirstResponder(self)
        let p = point(event)
        last = p
        mode = event.modifierFlags.contains(.option) ? .pendingCenter(start: p) : navMode(event.modifierFlags)
    }

    override func otherMouseDragged(with event: NSEvent) {
        let p = point(event)
        defer { last = p }
        if case .pendingCenter(let start) = mode {
            // Wahltaste + mittlere Maustaste gezogen: Blender dreht dann normal
            if hypot(p.x - start.x, p.y - start.y) > BlenderNav.dragThreshold { mode = .orbit } else { return }
        }
        apply(p.x - last.x, p.y - last.y)
    }

    override func otherMouseUp(with event: NSEvent) {
        if case .pendingCenter = mode {
            let p = point(event)
            coordinator?.pickPoint(p, in: self) { [weak self] result in
                guard let self, let c = self.coordinator, let result,
                    let world = c.surfacePoint(of: result, at: p, in: self)
                else { return }
                c.navCenter(on: world)
            }
        }
        mode = .idle
    }

    // Rechte Maustaste: Kontextmenü

    override func rightMouseDown(with event: NSEvent) {
        guard let menu = coordinator?.onContextMenu?() else { return }
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }

    override func menu(for event: NSEvent) -> NSMenu? { nil }

    // Mausrad und Trackpad

    override func scrollWheel(with event: NSEvent) {
        guard let c = coordinator else { return }
        // Nachlauf des Trackpads ignorieren: kein Weiterdrehen nach dem Loslassen
        if !event.momentumPhase.isEmpty { return }
        let flags = event.modifierFlags
        if event.hasPreciseScrollingDeltas {
            // Fingerbewegung wie Mausbewegung behandeln, unabhängig von „natürlichem Scrollen“
            let sign: CGFloat = event.isDirectionInvertedFromDevice ? 1 : -1
            let dx = event.scrollingDeltaX * sign
            let dy = -event.scrollingDeltaY * sign
            if flags.contains(.shift) {
                c.navPan(dx: Float(dx), dy: Float(dy))
            } else if flags.contains(.control) || flags.contains(.command) {
                c.navZoom(factor: exp(-Float(dy) * BlenderNav.zoomPerPoint))
            } else {
                c.navOrbit(dx: Float(dx), dy: Float(dy))
            }
            return
        }
        // Mausrad: eine Raste = ein Zoomschritt; Strg schwenkt waagrecht, Umschalt senkrecht
        let raw = event.scrollingDeltaY != 0 ? event.scrollingDeltaY : event.scrollingDeltaX
        let device = event.isDirectionInvertedFromDevice ? -raw : raw
        guard device != 0 else { return }
        let steps = device > 0 ? 1 : -1
        let pagePoints = Float(max(bounds.height, 1)) * 0.06
        if flags.contains(.control) {
            c.navPan(dx: Float(-steps) * pagePoints, dy: 0)
        } else if flags.contains(.shift) {
            c.navPan(dx: 0, dy: Float(steps) * pagePoints)
        } else {
            c.navZoom(factor: steps > 0 ? 1 / BlenderNav.wheelStep : BlenderNav.wheelStep)
        }
    }

    override func magnify(with event: NSEvent) {
        coordinator?.navZoom(factor: 1 / max(0.2, 1 + Float(event.magnification)))
    }

    override func rotate(with event: NSEvent) {}

    // Ziffernblock: falls die Menükürzel eine Taste nicht abfangen (externe Tastatur), hier direkt auswerten

    override func keyDown(with event: NSEvent) {
        if coordinator?.onNumpadKey?(event.keyCode, event.modifierFlags) == true { return }
        super.keyDown(with: event)
    }
}

struct NavigationInputLayer: NSViewRepresentable {
    let coordinator: ViewportCoordinator

    func makeNSView(context: Context) -> NavigationInputView {
        let v = NavigationInputView()
        v.coordinator = coordinator
        return v
    }

    func updateNSView(_ nsView: NavigationInputView, context: Context) {
        nsView.coordinator = coordinator
    }
}

// MARK: - Achsen-Gizmo (wie Blenders Navigationsgizmo oben rechts)

struct AxisGizmo: View {
    @ObservedObject var viewport: ViewportController
    let coordinator: ViewportCoordinator
    @State private var hovering = false
    @State private var lastDrag: CGSize = .zero

    private let size: CGFloat = 92
    private var radius: CGFloat { size / 2 - 13 }

    private struct Ball {
        let axis: SIMD3<Float>
        let label: String?
        let color: Color
        let view: StandardView
        var point: CGPoint = .zero
        var depth: Float = 0
    }

    private static let red = Color(red: 1.0, green: 0.2, blue: 0.32)
    private static let green = Color(red: 0.54, green: 0.86, blue: 0.0)
    private static let blue = Color(red: 0.16, green: 0.56, blue: 1.0)

    private func balls() -> [Ball] {
        let c = viewport.cameraState
        let right = c.rightVector, up = c.upVector, look = c.viewDirection
        var list = [
            Ball(axis: [1, 0, 0], label: "X", color: Self.red, view: .right),
            Ball(axis: [-1, 0, 0], label: nil, color: Self.red, view: .left),
            Ball(axis: [0, 1, 0], label: "Y", color: Self.green, view: .back),
            Ball(axis: [0, -1, 0], label: nil, color: Self.green, view: .front),
            Ball(axis: [0, 0, 1], label: "Z", color: Self.blue, view: .top),
            Ball(axis: [0, 0, -1], label: nil, color: Self.blue, view: .bottom),
        ]
        let center = CGPoint(x: size / 2, y: size / 2)
        for i in list.indices {
            let a = list[i].axis
            list[i].point = CGPoint(
                x: center.x + CGFloat(simd_dot(a, right)) * radius, y: center.y - CGFloat(simd_dot(a, up)) * radius)
            list[i].depth = simd_dot(a, look)  // positiv = vom Betrachter weg
        }
        return list.sorted { $0.depth > $1.depth }
    }

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .fill(Color.white.opacity(hovering ? 0.12 : 0))
                Canvas { ctx, _ in
                    let center = CGPoint(x: size / 2, y: size / 2)
                    for b in balls() {
                        if b.label != nil {
                            var line = Path()
                            line.move(to: center)
                            line.addLine(to: b.point)
                            ctx.stroke(line, with: .color(b.color.opacity(b.depth > 0 ? 0.55 : 1)), lineWidth: 2)
                        }
                        let r: CGFloat = b.label != nil ? 9 : 7.5
                        let rect = CGRect(x: b.point.x - r, y: b.point.y - r, width: 2 * r, height: 2 * r)
                        if b.label != nil {
                            ctx.fill(Path(ellipseIn: rect), with: .color(b.color))
                            ctx.draw(
                                Text(b.label!).font(.system(size: 10, weight: .bold)).foregroundColor(.black),
                                at: b.point)
                        } else {
                            ctx.fill(Path(ellipseIn: rect), with: .color(b.color.opacity(0.35)))
                            ctx.stroke(Path(ellipseIn: rect), with: .color(b.color.opacity(0.85)), lineWidth: 1.2)
                        }
                    }
                }
            }
            .frame(width: size, height: size)
            .contentShape(Circle())
            .onHover { hovering = $0 }
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        let d = CGSize(width: g.translation.width - lastDrag.width,
                                       height: g.translation.height - lastDrag.height)
                        lastDrag = g.translation
                        if hypot(g.translation.width, g.translation.height) > 3 {
                            coordinator.navOrbit(dx: Float(d.width), dy: Float(-d.height))
                        }
                    }
                    .onEnded { g in
                        defer { lastDrag = .zero }
                        guard hypot(g.translation.width, g.translation.height) <= 3 else { return }
                        // Klick: nächste Achse (vorderste zuerst), wie Blender
                        let hit = balls().reversed().first { b in
                            hypot(b.point.x - g.location.x, b.point.y - g.location.y) <= 11
                        }
                        if let hit { coordinator.navAxisView(hit.view) }
                    }
            )
            .help("Ziehen: drehen · Achse anklicken: Ansicht von dieser Seite")

            GizmoButton(symbol: "plus.magnifyingglass", help: "Ziehen: zoomen") { d in
                coordinator.navZoom(factor: exp(Float(d.height) * BlenderNav.zoomPerPoint))
            }
            GizmoButton(symbol: "hand.raised", help: "Ziehen: schwenken") { d in
                coordinator.navPan(dx: Float(d.width), dy: Float(-d.height))
            }
            Button {
                coordinator.navToggleProjection()
            } label: {
                Image(systemName: viewport.cameraState.isOrthographic ? "square.grid.3x3" : "perspective")
                    .font(.system(size: 13, weight: .medium))
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(Color.black.opacity(0.28)))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.white.opacity(0.9))
            .help(viewport.cameraState.isOrthographic
                ? "Parallel (5: Perspektive)" : "Perspektive (5: Parallel)")
        }
    }
}

/// Runder Knopf unter dem Gizmo, der beim Ziehen eine Bewegung meldet (Zoomen, Schwenken).
private struct GizmoButton: View {
    let symbol: String
    let help: String
    let onDrag: (CGSize) -> Void
    @State private var last: CGSize = .zero

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 13, weight: .medium))
            .frame(width: 28, height: 28)
            .background(Circle().fill(Color.black.opacity(0.28)))
            .foregroundStyle(.white.opacity(0.9))
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { g in
                        onDrag(CGSize(width: g.translation.width - last.width, height: g.translation.height - last.height))
                        last = g.translation
                    }
                    .onEnded { _ in last = .zero }
            )
            .help(help)
    }
}
