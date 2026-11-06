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
    /// Hinweis zum aktuellen Schritt (z. B. „Messen: zweites Element anklicken (Teil#f3)“); die Oberfläche kann ihn zeigen.
    @Published public var hint: String?

    /// Ein Klick ohne Ziehen (linke Maustaste): Treffer (oder nil) und die Sondertasten.
    public var onClick: ((PickResult?, NSEvent.ModifierFlags) -> Void)?
    /// Wird vor `onClick` gefragt, mit dem Weltpunkt unter der Maus auf dem getroffenen Dreieck (Phase 4: Werkzeug
    /// „Maßstab setzen“); true = der Klick ist verbraucht, `onClick` kommt dann nicht.
    public var onClickPunkt: ((PickResult?, SIMD3<Float>?, NSEvent.ModifierFlags) -> Bool)?
    /// Rahmenauswahl (linke Maustaste ziehen): alle Treffer im Rahmen und die Sondertasten.
    public var onBoxSelect: (([PickResult], NSEvent.ModifierFlags) -> Void)?
    /// Kontextmenü (rechte Maustaste).
    public var onContextMenu: (() -> NSMenu?)?
    /// Taste des Ziffernblocks im Viewport (Tastencode, Sondertasten); true = verarbeitet.
    public var onNumpadKey: ((UInt16, NSEvent.ModifierFlags) -> Bool)?
    /// Griff im Viewer (Simulation: Pfeil-Griff einer Kraft): Maustaste gedrückt an diesem Punkt (Eingabeebene,
    /// Ursprung unten links); true = Griff getroffen, dann folgen `onGriffZiehen` und `onGriffEnde` statt Auswahl
    /// und Drehen.
    public var onGriffBeginnt: ((CGPoint) -> Bool)?
    public var onGriffZiehen: ((CGPoint) -> Void)?
    public var onGriffEnde: ((CGPoint) -> Void)?
    /// Sondertasten beim Anfassen und Ziehen des Griffs (additiv; Simulation: ⌘ schaltet das Einrasten ab).
    public var griffModifiers: NSEvent.ModifierFlags = []

    public private(set) weak var mtkView: MTKView?
    private var cancellables = Set<AnyCancellable>()

    // MARK: V2: Eingabe, Kamerafahrten, Mauspunkt

    /// Was Maus und Tastatur gerade tun (Hinweisleiste).
    public let eingabe = ViewerEingabe()
    /// Taste im Viewport, die einem Befehl der Belegung entspricht (Ziffernblock, ^, ? …); true = ausgeführt.
    public var onBefehl: ((ViewerBefehl) -> Bool)?
    /// Element unter der Maus hat sich geändert (Treffer, Weltpunkt auf der Fläche, Mausposition oben links); nil-Treffer
    /// = nichts unter der Maus oder Maus außerhalb.
    public var onHover: ((PickResult?, SIMD3<Float>?, CGPoint?) -> Void)?
    /// V2-6: Kevin spricht: Ziehen mit der linken Maustaste zeichnet statt einen Rahmen aufzuziehen.
    public var zeichnen = false
    /// V2-6: Strich im Viewer (Beginn, je Treffer ein Punkt, Ende).
    public var onStrich: ((StrichEreignis) -> Void)?
    /// Eine Kamerafahrt ist am Ziel angekommen.
    public var onFahrtEnde: (() -> Void)?
    /// Jedes Bild der Navigation (Mitschnitt): Kamera nach der Änderung.
    public var onKameraGesetzt: ((CameraState) -> Void)?
    /// Laufende weiche Fahrt (Kamerafahrt.swift).
    var fahrt: Kamerafahrt?
    var fahrtLink: CADisplayLink?
    var fahrtTakt: FahrtTakt?
    /// Letzter Treffer unter der Maus: Weltpunkt und Mausposition (Eingabeebene, Ursprung unten links), Zeitpunkt.
    var mausPunkt: (welt: SIMD3<Float>, maus: CGPoint, zeit: CFTimeInterval)?
    /// Drehpunkt der laufenden Drehung (Punkt unter der Maus beim Beginn); nil = Ansichtsmittelpunkt.
    var drehZentrum: SIMD3<Float>?
    /// Die Eingabeebene über dem MTKView (für einen neuen Treffertest nach einer Kamerafahrt).
    weak var eingabeView: NavigationInputView?
    /// Letzte Mausposition über dem Viewport (Eingabeebene, Ursprung unten links); nil = Maus außerhalb.
    public internal(set) var letzteMaus: CGPoint?

    /// Treffertest unter der Maus neu anstoßen (die Szene hat sich unter dem Mauszeiger bewegt).
    public func hoverAuffrischen() { eingabeView?.hoverTest() }

    /// Größe des Viewports in Punkten (von der Eingabeebene gemeldet), für Schwenken und Strahlen.
    var viewSize: CGSize = CGSize(width: 1200, height: 800) {
        didSet { if aufAbruf && viewSize != oldValue { neuZeichnen() } }
    }
    /// V2-10: nur zeichnen, wenn sich etwas ändert (zweiter Viewer, ZweiterViewer.swift); der Hauptviewer zeichnet
    /// laufend mit 120 Bildern je Sekunde.
    public var aufAbruf = false
    /// V2-10: Maus und Tasten annehmen. Der zweite Viewer bleibt eingehängt, wenn seine Kachel verborgen ist; dann nimmt er
    /// nichts an (sonst meldete sein Verfolgungsbereich Bewegungen über dem Hauptviewer, der darunter liegt).
    public var eingabeAktiv = true {
        didSet { if eingabeAktiv != oldValue { eingabeView?.aktivGeaendert() } }
    }
    /// Die aktuelle Parallelprojektion stammt von einer Achsansicht und endet beim Drehen (Blender „Auto Perspective“).
    var autoOrtho = false

    public init() {
        var cfg = ViewportConfiguration.cad
        cfg.pickingConfiguration = PickingConfiguration(isEnabled: true, pickRadius: 3)
        cfg.displayMode = .shadedWithEdges
        // Raster und Achsen des Pakets liegen in der XZ-Ebene (Y oben) und passen nicht zu Z oben
        cfg.showGrid = false
        cfg.showAxes = false
        // Statt Würfel und Gnomon des Pakets zeichnet die App Blenders Achsen-Gizmo (BlenderNavigation.swift)
        cfg.showViewCube = false
        cfg.showOrientationGnomon = false
        cfg.showScaleBar = true
        cfg.scaleBarUnitLabel = "mm"
        cfg.minDistance = 0.01
        cfg.maxDistance = 1_000_000
        cfg.initialCameraState = StandardView.isometricFrontRight.cameraState(distance: 400)
        cfg.lightingConfiguration = Self.zUpLighting
        controller = ViewportController(configuration: cfg)
    }

    /// Dreipunktlicht des Pakets, umgestellt auf Z oben: Hauptlicht von vorn rechts oben, Fülllicht von links,
    /// Gegenlicht von hinten. Das Umgebungslicht des Pakets unterscheidet oben/unten über Y, deshalb hier gleichmäßig.
    /// Schatten aus: Sie helfen beim Lesen von CAD-Teilen wenig und kosten Schärfe.
    public static var zUpLighting: LightingConfiguration {
        var l = LightingConfiguration.threePoint
        l.keyLight.direction = simd_normalize(SIMD3<Float>(-0.35, 0.55, -0.75))
        l.fillLight.direction = simd_normalize(SIMD3<Float>(0.65, 0.35, -0.45))
        l.backLight.direction = simd_normalize(SIMD3<Float>(0.1, -0.75, 0.45))
        let mid = (l.ambientSkyColor + l.ambientGroundColor) * 0.5
        l.ambientSkyColor = mid
        l.ambientGroundColor = mid
        l.shadowsEnabled = false
        // Der Viewport kodiert sein Ergebnis nicht nach sRGB; mit linearen Farben wirkt alles dunkler als in model.py.
        // Etwas mehr Belichtung gleicht das für typische Grau- und Pastelltöne aus.
        l.exposure = 1.35
        return l
    }

    // MARK: Anbindung an das MTKView

    /// Vom Suchhelfer in der Ansicht aufgerufen, sobald das MTKView des Pakets existiert. Maus und Trackpad nimmt die
    /// Eingabeebene darüber entgegen (BlenderNavigation.swift); das MTKView zeichnet nur.
    func attach(_ view: MTKView) {
        // Auflage aus AP0: das Paket stellt fest 60 Bilder/s ein; für ProMotion 120
        view.preferredFramesPerSecond = 120
        if aufAbruf {
            view.isPaused = true
            view.enableSetNeedsDisplay = true
            view.needsDisplay = true
        }
        mtkView = view
    }

    /// Ein neues Bild anfordern (nur mit `aufAbruf`; sonst zeichnet das MTKView ohnehin laufend).
    func neuZeichnen() {
        guard aufAbruf, let v = mtkView else { return }
        v.needsDisplay = true
    }

    // MARK: Überlagerung

    public func setOverlay(_ items: [OverlayPrimitive]) { overlayItems = items }

    // MARK: Kamera

    public var aspectRatio: Float {
        let a = controller.lastAspectRatio
        return a > 0.01 && a.isFinite ? a : 1.6
    }

    public var camera: CameraState { controller.cameraState }

    /// Kamera so einpassen, dass `bounds` aus der aktuellen Richtung ganz zu sehen ist (weich, rund 0,2 s).
    public func fit(_ bounds: BoundingBox?, animated: Bool, padding: Float = 1.12) {
        guard let bounds else { return }
        let target = Self.fitted(fahrt?.ziel ?? controller.cameraState, to: bounds, aspect: aspectRatio, padding: padding)
        fahre(zu: target, dauer: animated ? ViewerStil.kamerafahrt * 1.25 : 0)
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
        var cam = fahrt?.ziel ?? controller.cameraState
        if let rotation { cam.rotation = rotation }
        if let orthographic { cam = Self.withProjection(cam, orthographic: orthographic) }
        if let bounds { cam = Self.fitted(cam, to: bounds, aspect: aspectRatio) }
        fahre(zu: cam, dauer: animated ? ViewerStil.kamerafahrt * 1.25 : 0)
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
