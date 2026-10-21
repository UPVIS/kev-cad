import AppKit
import Combine
import Foundation
import OCCTSwiftViewport
import simd

// Phase 5, Strang KAM: Kameras im App-Kern. Nachrichten (CAMERA_UPSERT/REMOVE), Pyramiden im Viewport, Blick durch die
// Kamera (Taste 0) mit exaktem Bildwinkel, Strg+Alt+0 als Vorschlag an Kernel und Agent, Kamerabilder (Oberfläche und
// SCREENSHOT_REQ mit `camera`), VIEW_CMD `camera_view` und `camera_suggest`.
//
// Zusammenspiel mit der Animation: Kameras kommen in der Ruhelage aus model.py. Folgt eine Kamera einem Teil
// (`folgt`, sonst `teil`), bewegt die App sie mit dessen Lage relativ zur Ruhelage (Animation und Explosion):
// `posedCamera`. Pyramide, Blick durch die Kamera, Kamerabild und Video benutzen immer die bewegte Kamera.

extension AppController: CameraActions {
    var cameras: CameraStore { model.cameras }

    // MARK: Nachrichten des Kernels

    func applyCamera(_ m: CameraMessage) {
        switch m {
        case .upsert(let c):
            cameras.upsert(c)
            if cameras.activeView == c.name {
                applyCameraView(posedCamera(c), animated: false)
                viewport.bodies = cameraFilteredBodies(scene.renderBodies)
            }
        case .remove(let name):
            if cameras.activeView == name { endCameraView(restore: true) }
            cameras.remove(name)
        }
        refreshOverlay()
    }

    /// Kernel neu verbunden oder anderes Projekt: alle Kameras verwerfen (der Kernel schickt sie neu).
    func clearCameras() {
        if cameras.activeView != nil { endCameraView(restore: true) }
        cameras.removeAll()
    }

    /// Pyramiden aller Kameras außer der, durch die gerade geschaut wird (in der aktuellen Lage ihres Teils).
    func cameraOverlayItems() -> [OverlayPrimitive] {
        cameras.cameras.filter { $0.name != cameras.activeView }.flatMap {
            CameraViewMath.overlay(posedCamera($0), selected: $0.name == cameras.selected)
        }
    }

    /// Körper für den Viewport: beim Blick durch eine Kamera ohne ihr eigenes Objektiv und ohne Teile vor dem Augpunkt.
    func cameraFilteredBodies(_ bodies: [ViewportBody]) -> [ViewportBody] {
        guard let name = cameras.activeView, let c = cameras.camera(name) else { return bodies }
        return CameraViewMath.filter(bodies, hiding: hiddenForCamera(posedCamera(c)))
    }

    // MARK: Kamera folgt ihrem Teil (Animation, Explosion)

    /// Teil, dem die Kamera folgt, wie es in der Szene steht (bei einer Baugruppe ihr erstes Teil).
    func followedPart(_ c: CameraInfo) -> String? {
        guard let name = c.folgt ?? c.teil, !name.isEmpty else { return nil }
        if scene.record(name) != nil { return name }
        return scene.order.first { $0.hasPrefix(name + "/") }
    }

    /// Bewegung des gefolgten Teils gegenüber seiner Ruhelage (Animation · Explosion); nil = steht in Ruhe.
    func cameraMotion(_ c: CameraInfo) -> simd_float4x4? {
        guard let part = followedPart(c), let rec = scene.record(part) else { return nil }
        let m = scene.worldTransform(part) * rec.header.transformMatrix.inverse
        let d = m - matrix_identity_float4x4
        let columns = [d.columns.0, d.columns.1, d.columns.2, d.columns.3]
        let deviation = columns.map { simd_reduce_max(simd_abs($0)) }.max() ?? 0
        return deviation < 1e-5 ? nil : m
    }

    /// Kamera in der aktuellen Lage ihres Teils.
    func posedCamera(_ c: CameraInfo) -> CameraInfo {
        guard let m = cameraMotion(c) else { return c }
        return c.transformed(by: m)
    }

    /// Lage der Teile hat sich geändert (Bild der Animation, Explosion): Blick durch die Kamera nachführen.
    func cameraPoseChanged() {
        guard let name = cameras.activeView, let c = cameras.camera(name) else { return }
        applyCameraView(posedCamera(c), animated: false)
    }

    /// Kamerazustand für ein Bild der Animation (Video): die benannte Kamera in der Lage, die die Szene gerade hat
    /// (der Videoexport setzt die Lage des Bildes, bevor er nach der Kamera fragt). nil = Kamera unbekannt.
    func animationCameraState(_ name: String) -> CameraState? {
        guard let c = cameras.camera(name) else { return nil }
        return CameraViewMath.state(for: posedCamera(c))
    }

    /// Körper für ein Videobild durch die Kamera: ohne ihr Objektiv und ohne Teile vor dem Augpunkt.
    func animationCameraBodies(_ name: String, _ bodies: [ViewportBody]) -> [ViewportBody] {
        guard let c = cameras.camera(name) else { return bodies }
        return CameraViewMath.filter(bodies, hiding: hiddenForCamera(posedCamera(c)))
    }

    /// Vorschlag aus einer Ansicht, zurückgerechnet in die Ruhelage (model.py kennt nur die), falls die Kamera gerade
    /// mit ihrem Teil bewegt steht.
    func restSuggestion(from s: CameraState, for c: CameraInfo) -> CameraSuggestMessage {
        var auge = s.position, blick = s.viewDirection, oben = s.upVector
        if let inv = cameraMotion(c)?.inverse {
            let a = inv * SIMD4(auge, 1), b = inv * SIMD4(blick, 0), o = inv * SIMD4(oben, 0)
            auge = SIMD3(a.x, a.y, a.z)
            blick = SIMD3(b.x, b.y, b.z)
            oben = SIMD3(o.x, o.y, o.z)
        }
        return CameraViewMath.suggestion(auge: auge, blick: blick, oben: oben, for: c)
    }

    func hiddenForCamera(_ c: CameraInfo) -> Set<String> {
        let bounds = scene.order.compactMap { n in scene.worldBounds(of: [ElementRef.part(n)]).map { (n, $0) } }
        return CameraViewMath.hiddenParts(for: c, bounds: bounds)
    }

    // MARK: Blick durch die Kamera

    public func lookThrough(_ name: String?) {
        guard let name else {
            endCameraView(restore: true)
            return
        }
        guard let c = cameras.camera(name) else {
            log(.warning, "Kamera \(name) gibt es nicht")
            return
        }
        installCameraTracking()
        if cameras.activeView == nil { cameras.savedViewport = viewport.camera }
        cameras.activeView = c.name
        cameras.selected = c.name
        applyCameraView(posedCamera(c), animated: true)
        viewport.bodies = cameraFilteredBodies(scene.renderBodies)
        refreshOverlay()
        log(.info, "Blick durch \(c.displayName): \(c.formatName), \(c.brennweiteText), \(c.blendeText), Fokus \(c.fokusText)")
    }

    func applyCameraView(_ c: CameraInfo, animated: Bool) {
        let state = CameraViewMath.viewportState(for: c, viewSize: viewport.viewSize)
        cameras.lastApplied = state
        cameras.ignoreChangesUntil = Date().addingTimeInterval(animated ? 0.6 : 0.15)
        viewport.autoOrtho = false
        if animated { viewport.smoothCamera(state, duration: 0.3) } else { viewport.setCamera(state) }
    }

    /// Kameraansicht beenden. `restore`: zurück zur Ansicht davor; sonst (Kevin navigiert weg) bleibt die Lage, der
    /// Öffnungswinkel geht zurück.
    func endCameraView(restore: Bool) {
        guard cameras.activeView != nil else { return }
        cameras.activeView = nil
        let saved = cameras.savedViewport
        cameras.savedViewport = nil
        cameras.lastApplied = nil
        viewport.bodies = scene.renderBodies
        refreshOverlay()
        guard let saved else { return }
        if restore {
            viewport.smoothCamera(saved, duration: 0.3)
        } else {
            var c = viewport.camera
            c.fieldOfView = saved.fieldOfView
            viewport.setCamera(c)
        }
    }

    /// Drehen, Schwenken oder Zoomen beendet die Kameraansicht (wie in Blender ohne „Lock Camera to View“).
    func installCameraTracking() {
        guard !cameras.trackingInstalled else { return }
        cameras.trackingInstalled = true
        viewport.controller.$cameraState
            .sink { [weak self] state in
                MainActor.assumeIsolated { self?.cameraStateChanged(state) }
            }
            .store(in: &navCancellables)
    }

    func cameraStateChanged(_ s: CameraState) {
        guard cameras.activeView != nil, let target = cameras.lastApplied, Date() > cameras.ignoreChangesUntil,
            !viewport.controller.isAnimating
        else { return }
        if !CameraViewMath.same(s, target) {
            endCameraView(restore: false)
        }
    }

    /// Der Viewport hat eine neue Größe: Öffnungswinkel und Rahmen neu rechnen.
    public func cameraViewportResized(_ size: CGSize) {
        guard size.width > 1, size.height > 1 else { return }
        viewport.viewSize = size
        guard let name = cameras.activeView, let c = cameras.camera(name) else { return }
        applyCameraView(posedCamera(c), animated: false)
    }

    public func toggleCameraView() {
        if cameras.activeView != nil {
            lookThrough(nil)
            return
        }
        guard let c = cameras.target else {
            log(.info, "Keine Kamera im Modell: in model.py mit lager.kamera(...) anlegen")
            return
        }
        lookThrough(c.name)
    }

    public func setActiveCameraToView() {
        guard let c = cameras.target else {
            log(.info, "Keine Kamera im Modell: in model.py mit lager.kamera(...) anlegen")
            return
        }
        let base = cameras.activeView == nil ? viewport.camera : (cameras.savedViewport ?? viewport.camera)
        let msg = restSuggestion(from: base, for: c)
        send(msg)
        let moved = c.moved(auge: msg.auge, blick: msg.blick, oben: msg.oben)
        cameras.upsert(moved)
        log(.info, "Kamera \(c.displayName) auf die Ansicht gesetzt (Vorschlag an Kernel und Agent, model.py unverändert)")
        lookThrough(moved.name)
    }

    public func selectCamera(_ name: String?) {
        cameras.selected = name.flatMap { cameras.camera($0)?.name }
        refreshOverlay()
    }

    // MARK: Kamerabilder

    func renderThroughCamera(_ camera: CameraInfo, width: Int, height: Int, overlays: Bool) -> ScreenshotRenderer.Result? {
        let c = posedCamera(camera)
        let state = CameraViewMath.state(for: c)
        let bodies = CameraViewMath.filter(scene.snapshotBodies(), hiding: hiddenForCamera(c))
        return screenshots.render(
            bodies: bodies, camera: state, width: width, height: height, displayMode: scene.viewportDisplayMode,
            lighting: viewport.controller.lightingConfiguration, overlay: overlays ? overlayItems() : [])
    }

    static func cameraFileName(_ c: CameraInfo, width: Int, height: Int, date: Date = Date()) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        let safe = c.displayName.map { ch -> Character in
            ch.isLetter || ch.isNumber || ch == "-" || ch == "_" || ch == "." ? ch : "-"
        }
        let mm = c.brennweite == c.brennweite.rounded() ? String(Int(c.brennweite)) : String(format: "%.1f", c.brennweite)
        return "\(String(safe))_\(mm)mm_\(width)x\(height)_\(f.string(from: date)).png"
    }

    public func renderCameraImage(_ name: String) {
        guard let c = cameras.camera(name) else { return }
        let w = max(16, min(c.aufloesung.x, 8192)), h = max(16, min(c.aufloesung.y, 8192))
        guard let r = renderThroughCamera(c, width: w, height: h, overlays: false) else {
            log(.error, "Kamerabild \(c.displayName) ließ sich nicht rendern")
            return
        }
        let base =
            model.project?.path.appendingPathComponent("output", isDirectory: true)
            ?? FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("kameras", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent(Self.cameraFileName(c, width: w, height: h))
        do {
            try r.png.write(to: url)
            cameras.lastImage = url
            log(.info, "Kamerabild gespeichert: \(url.path)")
        } catch {
            log(.error, "Kamerabild nicht gespeichert: \(error.localizedDescription)")
        }
    }

    /// SCREENSHOT_REQ mit `camera`: Bild genau durch diese Kamera. true, wenn die Anfrage damit beantwortet ist.
    func answerCameraScreenshot(_ s: ScreenshotRequestMessage) -> Bool {
        guard let name = s.camera, !name.isEmpty else { return false }
        guard let c = cameras.camera(name) else {
            send(
                ScreenshotResponseMessage(
                    replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Kamera \(name) gibt es in der App nicht"))
            return true
        }
        let w = max(16, min(s.width, 8192)), h = max(16, min(s.height, 8192))
        let started = CACurrentMediaTime()
        guard let r = renderThroughCamera(c, width: w, height: h, overlays: !s.hideOverlays) else {
            send(
                ScreenshotResponseMessage(
                    replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Kamerabild ließ sich nicht rendern"))
            return true
        }
        var json = ViewportCoordinator.cameraJSON(r.camera, height: h)
        if case .object(var o) = json {
            o["name"] = .string(c.name)
            json = .object(o)
        }
        log(.info, "Kamerabild \(c.displayName) für den Kernel: \(w) × \(h) in \(Int((CACurrentMediaTime() - started) * 1000)) ms")
        send(ScreenshotResponseMessage(replyTo: s.id, ok: true, width: w, height: h, camera: json, mmPerPx: nil),
             payload: r.png)
        return true
    }

    func whenCameraIdle(until deadline: CFTimeInterval, _ done: @escaping () -> Void) {
        if !viewport.controller.isAnimating || CACurrentMediaTime() > deadline {
            done()
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) { [weak self] in
            self?.whenCameraIdle(until: deadline, done)
        }
    }

    /// VIEW_CMD für Kameras; nil, wenn der Befehl kein Kamerabefehl ist.
    func performCameraCommand(_ v: ViewCommandMessage) -> (Bool, String?)? {
        switch v.cmd {
        case "camera_view":
            guard let name = v.args["name"]?.stringValue, !name.isEmpty else {
                lookThrough(nil)
                return (true, "freie Ansicht")
            }
            guard let c = cameras.camera(name) else { return (false, "Kamera \(name) gibt es in der App nicht") }
            lookThrough(c.name)
            return (true, "Blick durch \(c.displayName)")
        case "camera_suggest":
            guard let name = v.args["name"]?.stringValue, let c = cameras.camera(name) else {
                return (false, "Kamera unbekannt")
            }
            // Läuft noch eine Kamerafahrt (view, focus direkt davor), erst ihr Ende abwarten (höchstens 1,5 s)
            whenCameraIdle(until: CACurrentMediaTime() + 1.5) { [weak self] in
                guard let self else { return }
                self.send(self.restSuggestion(from: self.viewport.camera, for: c))
            }
            return (true, "Vorschlag aus der aktuellen Ansicht")
        default:
            return nil
        }
    }
}
