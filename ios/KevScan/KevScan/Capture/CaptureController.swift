import ARKit
import Combine
import RealityKit
import UIKit

/// Steuert die ARKit-Sitzung der Aufnahme: Anzeige, Objekt-Box, Aufnahme mit 10 Hz und Fotos.
/// Der Delegate läuft auf dem Hauptthread (Vorgabe von ARSession ohne eigene Warteschlange).
final class CaptureController: NSObject, ObservableObject, ARSessionDelegate {
    // Anzeige
    @Published private(set) var trackingText = "Startet …"
    /// 0 = nicht verfügbar, 1 = eingeschränkt, 2 = gut
    @Published private(set) var trackingLevel = 0
    @Published private(set) var distanceText: String?
    @Published private(set) var warnings: [String] = []
    @Published private(set) var isRecording = false
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var photoCount = 0
    @Published private(set) var frameCount = 0
    @Published private(set) var freeBytes: Int64 = 0
    @Published private(set) var photoFlash = false
    @Published private(set) var finishing = false
    @Published private(set) var finished = false
    @Published var errorText: String?

    // Objekt-Box
    @Published var boxMode = false
    @Published var box: ObjectBox? {
        didSet { updateBoxEntity() }
    }

    let lidarAvailable = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)

    private weak var arView: ARView?
    private var boxAnchor: AnchorEntity?
    private var store: ScanStore?
    private var scanName = "Scan"
    private var recorder: ScanRecorder?
    private(set) var videoFormat: ARConfiguration.VideoFormat?
    private var lastRecorded: TimeInterval = 0
    private var lastUIUpdate: TimeInterval = 0
    private var lastFreeCheck: TimeInterval = -10
    private var lastPhotoTransform: simd_float4x4?
    private var lastPhotoTime: TimeInterval = 0
    private var photoInFlight = false
    private var stopRequested = false
    private var gestureStartBox: ObjectBox?
    private var highResReported = false

    func configure(store: ScanStore, name: String) {
        self.store = store
        self.scanName = name
    }

    // MARK: Sitzung

    func attach(_ view: ARView) {
        arView = view
        view.session.delegate = self
        let anchor = AnchorEntity(world: .zero)
        view.scene.addAnchor(anchor)
        boxAnchor = anchor
        setMeshVisible(UserDefaults.standard.bool(forKey: AppSettings.showMesh))
        runSession()
    }

    func detach() {
        if isRecording { cancelRecording() }
        arView?.session.pause()
    }

    func setMeshVisible(_ visible: Bool) {
        guard let view = arView else { return }
        if visible {
            view.debugOptions.insert(.showSceneUnderstanding)
        } else {
            view.debugOptions.remove(.showSceneUnderstanding)
        }
    }

    private func runSession() {
        guard let view = arView else { return }
        let config = ARWorldTrackingConfiguration()
        if let format = Self.bestVideoFormat() {
            config.videoFormat = format
        }
        videoFormat = config.videoFormat
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
            config.sceneReconstruction = .mesh
        }
        config.planeDetection = [.horizontal]
        config.environmentTexturing = .none
        config.isAutoFocusEnabled = true
        config.videoHDRAllowed = false
        view.session.run(config)
    }

    /// Videoformat mit Unterstützung für `captureHighResolutionFrame`, bevorzugt 1920 × 1440 ohne HDR mit der höchsten
    /// Bildrate. Auf dem iPhone 15 Pro Max (iOS 27) gibt es 1920 × 1440 bei 60 fps zweimal, mit und ohne HDR-Fähigkeit;
    /// für Scans ist das Format ohne HDR besser (gleichmäßige Farben, 8-bit-Bilder für den Videoschreiber).
    static func bestVideoFormat() -> ARConfiguration.VideoFormat? {
        let formats = ARWorldTrackingConfiguration.supportedVideoFormats.filter {
            $0.captureDevicePosition == .back && $0.isRecommendedForHighResolutionFrameCapturing
        }
        let sensorSized = formats.filter {
            Int($0.imageResolution.width) == 1920 && Int($0.imageResolution.height) == 1440
        }
        func rank(_ f: ARConfiguration.VideoFormat) -> Int { (f.isVideoHDRSupported ? 0 : 1000) + f.framesPerSecond }
        let preferred = sensorSized.max { rank($0) < rank($1) }
        return preferred
            ?? ARWorldTrackingConfiguration.recommendedVideoFormatForHighResolutionFrameCapturing
            ?? formats.max { rank($0) < rank($1) }
    }

    // MARK: ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let now = frame.timestamp
        if isRecording, let rec = recorder {
            if now - lastRecorded >= 0.095, rec.appendFrame(frame) {
                lastRecorded = now
            }
            if let failure = rec.failure, errorText == nil {
                errorText = "Aufnahme gestört: \(failure)"
            }
            checkAutoPhoto(frame)
        }
        if now - lastUIUpdate >= 0.2 {
            lastUIUpdate = now
            updateDisplay(frame)
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        errorText = "ARKit: \(error.localizedDescription)"
    }

    func sessionWasInterrupted(_ session: ARSession) {
        trackingText = "Unterbrochen"
        trackingLevel = 0
    }

    // MARK: Anzeige

    private func updateDisplay(_ frame: ARFrame) {
        var newWarnings: [String] = []
        if !lidarAvailable {
            newWarnings.append("Dieses Gerät hat kein LiDAR, eine Aufnahme ist nicht möglich.")
        }

        switch frame.camera.trackingState {
        case .normal:
            setTracking("Tracking gut", level: 2)
        case .notAvailable:
            setTracking("Kein Tracking", level: 0)
            newWarnings.append("Tracking nicht verfügbar")
        case .limited(let reason):
            let text: String
            switch reason {
            case .initializing: text = "Tracking startet …"
            case .excessiveMotion: text = "Zu schnell, langsamer bewegen"
            case .insufficientFeatures: text = "Zu wenig Struktur im Bild"
            case .relocalizing: text = "Ortet sich neu …"
            @unknown default: text = "Tracking eingeschränkt"
            }
            setTracking(text, level: 1)
            if case .initializing = reason {} else { newWarnings.append(text) }
        }

        if let depth = frame.sceneDepth?.depthMap, let meters = PixelPacking.centerDepth(depth) {
            let text = String(format: "%.2f m", meters).replacingOccurrences(of: ".", with: ",")
            if distanceText != text { distanceText = text }
            if meters < 0.25 {
                newWarnings.append("Zu nah: etwas zurückgehen (LiDAR misst ab etwa 25 cm)")
            } else if meters > 3.0 {
                newWarnings.append("Zu weit weg: näher heran (LiDAR misst bis etwa 3 m)")
            }
        } else if distanceText != nil {
            distanceText = nil
        }

        if frame.timestamp - lastFreeCheck > 2 {
            lastFreeCheck = frame.timestamp
            freeBytes = Self.freeSpace()
        }
        if freeBytes > 0 && freeBytes < 2_000_000_000 {
            newWarnings.append("Wenig Speicher frei")
        }

        if newWarnings != warnings { warnings = newWarnings }
        if let rec = recorder {
            if let start = rec.startTimestamp { duration = frame.timestamp - start }
            if frameCount != rec.frameCount { frameCount = rec.frameCount }
        }
    }

    private func setTracking(_ text: String, level: Int) {
        if trackingText != text { trackingText = text }
        if trackingLevel != level { trackingLevel = level }
    }

    static func freeSpace() -> Int64 {
        let url = URL(fileURLWithPath: NSHomeDirectory())
        let values = try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage ?? 0
    }

    // MARK: Aufnahme

    func startRecording() {
        guard !isRecording, !finishing, let store else { return }
        guard lidarAvailable else {
            errorText = "Ohne LiDAR keine Aufnahme."
            return
        }
        do {
            let folder = try store.makeScanFolder(named: scanName)
            recorder = try ScanRecorder(folder: folder, name: scanName)
        } catch {
            errorText = "Ordner ließ sich nicht anlegen: \(error.localizedDescription)"
            return
        }
        lastRecorded = 0
        lastPhotoTransform = nil
        lastPhotoTime = 0
        photoCount = 0
        frameCount = 0
        duration = 0
        boxMode = false
        isRecording = true
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }

    func stopRecording() {
        guard isRecording, let rec = recorder else { return }
        if photoInFlight {
            stopRequested = true
            return
        }
        isRecording = false
        finishing = true
        recorder = nil
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        let defaults = UserDefaults.standard
        let info = ScanRecorder.FinishInfo(
            objekt: box.map { ObjectFile($0) },
            videoFormat: videoFormat,
            autoPhoto: ScanMeta.AutoPhoto(aktiv: defaults.bool(forKey: AppSettings.autoPhoto),
                                          winkel_grad: defaults.double(forKey: AppSettings.autoAngle),
                                          abstand_m: defaults.double(forKey: AppSettings.autoDistance)),
            notiz: "")
        rec.finish(info) { [weak self] error in
            guard let self else { return }
            self.finishing = false
            if let error {
                self.errorText = "Speichern gescheitert: \(error.localizedDescription)"
            } else if !rec.warnings.isEmpty {
                self.errorText = "Gespeichert, mit Hinweis: " + rec.warnings.prefix(2).joined(separator: "; ")
            }
            self.finished = true
        }
    }

    func cancelRecording() {
        guard isRecording, let rec = recorder else { return }
        isRecording = false
        recorder = nil
        rec.cancel()
    }

    // MARK: Fotos

    func takePhoto(trigger: String = "hand") {
        guard isRecording, !photoInFlight, let session = arView?.session else { return }
        photoInFlight = true
        if let current = session.currentFrame {
            lastPhotoTransform = current.camera.transform
            lastPhotoTime = current.timestamp
        }
        session.captureHighResolutionFrame { [weak self] frame, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.photoInFlight = false
                if let frame, let rec = self.recorder {
                    rec.addPhoto(frame, latest: self.arView?.session.currentFrame, trigger: trigger)
                    self.photoCount = rec.photoCount
                    self.flash()
                    if !self.highResReported {
                        self.highResReported = true
                        DeviceProbe.noteHighResolution(width: CVPixelBufferGetWidth(frame.capturedImage),
                                                       height: CVPixelBufferGetHeight(frame.capturedImage),
                                                       hasDepth: frame.sceneDepth != nil)
                    }
                } else if let error {
                    self.errorText = "Foto gescheitert: \(error.localizedDescription)"
                }
                if self.stopRequested {
                    self.stopRequested = false
                    self.stopRecording()
                }
            }
        }
    }

    private func flash() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        photoFlash = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in self?.photoFlash = false }
    }

    static let autoPhotoMinInterval: TimeInterval = 1.5

    /// Automatisches Foto, sobald sich die Kamera seit dem letzten Foto genug gedreht oder bewegt hat. Höchstens eins je
    /// 1,5 s und nur, wenn die vorigen Fotos fast geschrieben sind und das iPhone nicht heiß läuft: Ein 12-MP-Foto
    /// hält einen Bildpuffer von ARKit fest, bis es als JPEG auf der Platte liegt; zu viele davon bremsen Tracking und
    /// Videoaufnahme (Scan am Rollwagen, 23.10.2026: 77 Fotos in 93 s, das iPhone war überlastet).
    private func checkAutoPhoto(_ frame: ARFrame) {
        let defaults = UserDefaults.standard
        guard defaults.bool(forKey: AppSettings.autoPhoto), !photoInFlight, !stopRequested else { return }
        guard case .normal = frame.camera.trackingState else { return }
        guard frame.timestamp - lastPhotoTime > Self.autoPhotoMinInterval else { return }
        guard (recorder?.photoBacklog ?? 0) < 2 else { return }
        let thermal = ProcessInfo.processInfo.thermalState
        guard thermal != .serious, thermal != .critical else { return }
        let current = frame.camera.transform
        guard let last = lastPhotoTransform else {
            takePhoto(trigger: "auto")
            return
        }
        let angleLimit = max(1, defaults.double(forKey: AppSettings.autoAngle)) * .pi / 180
        let distanceLimit = max(0.02, defaults.double(forKey: AppSettings.autoDistance))
        let dot = abs(simd_dot(Pose.quaternion(last).vector, Pose.quaternion(current).vector))
        let angle = 2 * acos(min(1, Double(dot)))
        let p1 = SIMD3<Float>(last.columns.3.x, last.columns.3.y, last.columns.3.z)
        let p2 = SIMD3<Float>(current.columns.3.x, current.columns.3.y, current.columns.3.z)
        let distance = Double(simd_distance(p1, p2))
        if angle >= angleLimit || distance >= distanceLimit {
            takePhoto(trigger: "auto")
        }
    }

    // MARK: Objekt-Box

    func handleTap(at point: CGPoint) {
        guard boxMode, let hit = raycastFloor(point) else { return }
        if var current = box {
            current.floorPoint = hit.position
            box = current
        } else {
            box = ObjectBox(floorPoint: hit.position, floorNormal: hit.normal,
                            size: SIMD3<Float>(0.3, 0.3, 0.3), yaw: cameraYaw())
        }
    }

    func handlePan(_ state: UIGestureRecognizer.State, at point: CGPoint) {
        guard boxMode, box != nil, state == .changed || state == .began, let hit = raycastFloor(point) else { return }
        box?.floorPoint = hit.position
    }

    func handlePinch(_ state: UIGestureRecognizer.State, scale: CGFloat) {
        guard boxMode, let current = box else { return }
        switch state {
        case .began:
            gestureStartBox = current
        case .changed:
            guard let start = gestureStartBox else { return }
            let s = Float(scale)
            var next = current
            next.size.x = min(3, max(0.03, start.size.x * s))
            next.size.z = min(3, max(0.03, start.size.z * s))
            box = next
        default:
            gestureStartBox = nil
        }
    }

    func handleRotation(_ state: UIGestureRecognizer.State, rotation: CGFloat) {
        guard boxMode, let current = box else { return }
        switch state {
        case .began:
            if gestureStartBox == nil { gestureStartBox = current }
        case .changed:
            guard let start = gestureStartBox else { return }
            var next = current
            next.yaw = start.yaw - Float(rotation)
            box = next
        default:
            gestureStartBox = nil
        }
    }

    func updateBox(_ change: (inout ObjectBox) -> Void) {
        guard var current = box else { return }
        change(&current)
        current.size = simd_clamp(current.size, SIMD3<Float>(repeating: 0.03), SIMD3<Float>(repeating: 3))
        box = current
    }

    private func raycastFloor(_ point: CGPoint) -> (position: SIMD3<Float>, normal: SIMD3<Float>)? {
        guard let view = arView else { return nil }
        let result = view.raycast(from: point, allowing: .existingPlaneGeometry, alignment: .horizontal).first
            ?? view.raycast(from: point, allowing: .estimatedPlane, alignment: .horizontal).first
        guard let hit = result else { return nil }
        let t = hit.worldTransform
        let normal = simd_normalize(SIMD3<Float>(t.columns.1.x, t.columns.1.y, t.columns.1.z))
        return (SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z), normal)
    }

    /// Drehung um y, bei der die lokale +z-Achse der Box zur Kamera zeigt.
    private func cameraYaw() -> Float {
        guard let transform = arView?.session.currentFrame?.camera.transform else { return 0 }
        let back = transform.columns.2
        return atan2(back.x, back.z)
    }

    private func updateBoxEntity() {
        guard let anchor = boxAnchor else { return }
        anchor.children.removeAll()
        if let box { anchor.addChild(BoxEntity.make(box)) }
    }
}

/// Darstellung der Objekt-Box: halbdurchsichtige Flächen und Kanten.
enum BoxEntity {
    static func make(_ box: ObjectBox) -> Entity {
        let root = Entity()
        root.position = box.floorPoint
        root.orientation = simd_quatf(angle: box.yaw, axis: SIMD3<Float>(0, 1, 0))
        let w = box.size.x, h = box.size.y, d = box.size.z
        let color = UIColor(red: 0.15, green: 0.76, blue: 0.85, alpha: 1)

        var faceMaterial = UnlitMaterial(color: color)
        faceMaterial.blending = .transparent(opacity: 0.16)
        let faces = ModelEntity(mesh: .generateBox(size: SIMD3<Float>(w, h, d)), materials: [faceMaterial])
        faces.position = SIMD3<Float>(0, h / 2, 0)
        root.addChild(faces)

        let edgeMaterial = UnlitMaterial(color: color)
        let t: Float = 0.004
        func edge(_ size: SIMD3<Float>, _ position: SIMD3<Float>) {
            let e = ModelEntity(mesh: .generateBox(size: size), materials: [edgeMaterial])
            e.position = position
            root.addChild(e)
        }
        for sx: Float in [-1, 1] {
            for sz: Float in [-1, 1] {
                edge(SIMD3<Float>(t, h, t), SIMD3<Float>(sx * w / 2, h / 2, sz * d / 2))
            }
        }
        for y: Float in [0, h] {
            for s: Float in [-1, 1] {
                edge(SIMD3<Float>(w, t, t), SIMD3<Float>(0, y, s * d / 2))
                edge(SIMD3<Float>(t, t, d), SIMD3<Float>(s * w / 2, y, 0))
            }
        }
        return root
    }
}
