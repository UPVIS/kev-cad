import AppKit
import Combine
import MetalKit
import OCCTSwiftViewport
import simd

/// Hält den Viewport (OCCTSwiftViewport) unabhängig vom Fenster: Kamera, Körper, Überlagerung, Klicks.
/// Gehört dem `AppController`, damit Befehle des Kernels auch wirken, während die Ansicht neu aufgebaut wird.
@MainActor
public final class ViewportCoordinator: ObservableObject {
    public let controller: ViewportController
    @Published public var bodies: [ViewportBody] = []
    /// Über dem 3D-Bild zu zeichnen (Weltkoordinaten); die Ansicht projiziert bei jeder Kamerabewegung neu.
    @Published public private(set) var overlayItems: [OverlayPrimitive] = []
    /// Hinweiszeile oben im Viewport (z. B. im Messmodus).
    @Published public var hint: String?

    /// Ein Klick ohne Ziehen: Treffer (oder nil) und die Sondertasten beim Drücken.
    public var onClick: ((PickResult?, NSEvent.ModifierFlags) -> Void)?

    public private(set) weak var mtkView: MTKView?
    private var monitor: Any?
    private var cancellables = Set<AnyCancellable>()

    // Klick oder Ziehen?
    private var armed = false
    private var downLocation = CGPoint.zero
    private var downModifiers: NSEvent.ModifierFlags = []
    private var dragged = false
    private var released = false
    private var arrived: PickResult?? = .none

    public init() {
        var cfg = ViewportConfiguration.cad
        cfg.pickingConfiguration = PickingConfiguration(isEnabled: true, pickRadius: 3)
        cfg.displayMode = .shadedWithEdges
        // Raster und Achsen des Pakets liegen in der XZ-Ebene (Y oben) und passen nicht zu Z oben
        cfg.showGrid = false
        cfg.showAxes = false
        cfg.showOrientationGnomon = true
        cfg.showScaleBar = true
        cfg.scaleBarUnitLabel = "mm"
        cfg.minDistance = 0.01
        cfg.maxDistance = 1_000_000
        cfg.initialCameraState = StandardView.isometricFrontRight.cameraState(distance: 400)
        controller = ViewportController(configuration: cfg)
        controller.onPick = { [weak self] result in self?.pickArrived(result) }
    }

    // MARK: Anbindung an das MTKView

    /// Vom Suchhelfer in der Ansicht aufgerufen, sobald das MTKView des Pakets existiert.
    func attach(_ view: MTKView) {
        // Auflage aus AP0: das Paket stellt fest 60 Bilder/s ein; für ProMotion 120
        view.preferredFramesPerSecond = 120
        guard mtkView !== view else { return }
        mtkView = view
        if monitor == nil {
            monitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) {
                [weak self] event in
                MainActor.assumeIsolated { self?.track(event) }
                return event
            }
        }
    }

    private func track(_ event: NSEvent) {
        guard let view = mtkView, let window = view.window, event.window === window else { return }
        switch event.type {
        case .leftMouseDown:
            // Nur, wenn der Klick wirklich im MTKView landet (nicht auf dem Würfel oder anderen Überlagerungen)
            guard let content = window.contentView else { return }
            let point = content.superview?.convert(event.locationInWindow, from: nil) ?? event.locationInWindow
            guard content.hitTest(point) === view else {
                armed = false
                return
            }
            armed = true
            downLocation = event.locationInWindow
            downModifiers = event.modifierFlags
            dragged = false
            released = false
            arrived = .none
        case .leftMouseDragged:
            guard armed else { return }
            let p = event.locationInWindow
            if hypot(p.x - downLocation.x, p.y - downLocation.y) > 4 { dragged = true }
        case .leftMouseUp:
            guard armed else { return }
            released = true
            if dragged {
                armed = false
            } else if case .some(let r) = arrived {
                commit(r)
            }
        default:
            break
        }
    }

    private func pickArrived(_ result: PickResult?) {
        guard armed else { return }
        arrived = .some(result)
        if released && !dragged { commit(result) }
    }

    private func commit(_ result: PickResult?) {
        armed = false
        onClick?(result, downModifiers)
    }

    // MARK: Überlagerung

    public func setOverlay(_ items: [OverlayPrimitive]) { overlayItems = items }

    // MARK: Kamera

    public var aspectRatio: Float {
        let a = controller.lastAspectRatio
        return a > 0.01 && a.isFinite ? a : 1.6
    }

    public var camera: CameraState { controller.cameraState }

    /// Kamera so einpassen, dass `bounds` aus der aktuellen Richtung ganz zu sehen ist.
    public func fit(_ bounds: BoundingBox?, animated: Bool, padding: Float = 1.12) {
        guard let bounds else { return }
        let target = Self.fitted(controller.cameraState, to: bounds, aspect: aspectRatio, padding: padding)
        controller.animateTo(target, duration: animated ? 0.45 : 0)
    }

    /// Wie `CameraState.fit`, mit Mindestgröße (ein Punkt hat keine Ausdehnung) und genug Abstand bei
    /// Parallelprojektion (sonst schneidet die Nahebene).
    public static func fitted(_ cam: CameraState, to bounds: BoundingBox, aspect: Float, padding: Float = 1.12) -> CameraState {
        var b = bounds
        if b.diagonalLength < 2 {
            let c = b.center
            b = BoundingBox(min: c - SIMD3(repeating: 5), max: c + SIMD3(repeating: 5))
        }
        var t = cam.fit(to: b, aspectRatio: aspect, padding: padding)
        if t.isOrthographic {
            t.distance = max(t.distance, b.diagonalLength * 2 + 10)
        }
        return t
    }

    /// Richtung, Projektion und Einpassen in einem Zug.
    public func apply(
        rotation: simd_quatf?, orthographic: Bool?, fitTo bounds: BoundingBox?, animated: Bool
    ) {
        var cam = controller.cameraState
        if let rotation { cam.rotation = rotation }
        if let orthographic { cam = Self.withProjection(cam, orthographic: orthographic) }
        if let bounds { cam = Self.fitted(cam, to: bounds, aspect: aspectRatio) }
        controller.animateTo(cam, duration: animated ? 0.4 : 0)
    }

    /// Projektion wechseln und dabei den sichtbaren Ausschnitt am Drehpunkt erhalten.
    public static func withProjection(_ cam: CameraState, orthographic: Bool) -> CameraState {
        var c = cam
        guard c.isOrthographic != orthographic else { return c }
        let halfFov = c.fieldOfView * .pi / 360
        if orthographic {
            c.orthographicScale = max(2 * c.distance * tan(halfFov), 0.01)
        } else {
            c.distance = max(c.orthographicScale / (2 * tan(halfFov)), 0.05)
        }
        c.isOrthographic = orthographic
        return c
    }

    // MARK: Standardansichten (Z oben)

    public static func standardView(_ name: StandardViewName) -> StandardView {
        switch name {
        case .top: return .top
        case .bottom: return .bottom
        case .front: return .front
        case .back: return .back
        case .left: return .left
        case .right: return .right
        case .iso: return .isometricFrontRight
        case .isoFrontLeft: return .isometricFrontLeft
        case .isoBackRight: return .isometricBackRight
        case .isoBackLeft: return .isometricBackLeft
        }
    }

    /// Name im Protokoll (`top`, `iso`, `iso_front_left`, …) → Ansicht.
    public static func standardView(protocolName: String) -> StandardView? {
        switch protocolName.lowercased() {
        case "top": return .top
        case "bottom": return .bottom
        case "front": return .front
        case "back": return .back
        case "left": return .left
        case "right": return .right
        case "iso", "iso_front_right", "isometric": return .isometricFrontRight
        case "iso_front_left": return .isometricFrontLeft
        case "iso_back_right": return .isometricBackRight
        case "iso_back_left": return .isometricBackLeft
        default: return nil
        }
    }

    static let protocolNames: [(StandardView, String)] = [
        (.top, "top"), (.bottom, "bottom"), (.front, "front"), (.back, "back"), (.left, "left"), (.right, "right"),
        (.isometricFrontRight, "iso"), (.isometricFrontLeft, "iso_front_left"),
        (.isometricBackRight, "iso_back_right"), (.isometricBackLeft, "iso_back_left"),
    ]

    /// Standardansicht, falls die Kamera (bis auf 1°) genau so ausgerichtet ist.
    public static func nearestStandardName(_ cam: CameraState) -> String? {
        for (v, name) in protocolNames {
            let d = abs(simd_dot(cam.rotation.vector, v.rotation.vector))
            if 2 * acos(min(1, d)) < Float.pi / 180 { return name }
        }
        return nil
    }

    /// Kamera als JSON für SCREENSHOT_RES.
    public static func cameraJSON(_ c: CameraState, height: Int) -> JSONValue {
        func v(_ p: SIMD3<Float>) -> JSONValue {
            .array([.number(Double(p.x)), .number(Double(p.y)), .number(Double(p.z))])
        }
        var o: [String: JSONValue] = [
            "projection": .string(c.isOrthographic ? "orthographic" : "perspective"),
            "position": v(c.position), "target": v(c.pivot), "up": v(c.upVector), "direction": v(c.viewDirection),
            "distance": .number(Double(c.distance)), "fov_deg": .number(Double(c.fieldOfView)),
        ]
        o["view"] = nearestStandardName(c).map(JSONValue.string) ?? .null
        o["ortho_height_mm"] = c.isOrthographic ? .number(Double(c.orthographicScale)) : .null
        if c.isOrthographic, height > 0 { o["mm_per_px"] = .number(Double(c.orthographicScale) / Double(height)) }
        return .object(o)
    }
}
