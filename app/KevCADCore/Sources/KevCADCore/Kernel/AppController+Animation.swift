import AppKit
import Foundation
import OCCTSwiftViewport
import simd

/// Zustand der Animation im App-Kern (eine gespeicherte Eigenschaft in AppController: `animationRuntime`).
@MainActor
final class AnimationRuntime {
    let player: AnimationPlayer
    let exporter = AnimationVideoExporter()
    var lastVideoNote: String?
    var lastVideoCamera: String?
    /// Benannte Kameras (Strang KAM): "Kamera/<name>" und Zeit → Kamera; nil = keine benannten Kameras.
    var cameraResolver: ((String, Double) -> CameraState?)?

    init(player: AnimationPlayer) {
        self.player = player
    }
}

/// Phase 5 (Strang ANI): Animation im App-Kern. Nachrichten des Kernels, Zeitleiste (AnimationActions), Lage der Teile
/// über SceneStore (nur Matrizen), Kamerafahrt, Kollisionen und Video.
extension AppController: AnimationActions {
    var animationPlayer: AnimationPlayer { animationRuntime.player }
    private var videoExporter: AnimationVideoExporter { animationRuntime.exporter }

    /// Für den Strang KAM: Kamera je Name und Zeit für `animation_video(kamera=…)`.
    public func setAnimationCameraResolver(_ resolver: ((String, Double) -> CameraState?)?) {
        animationRuntime.cameraResolver = resolver
    }

    /// Baut den Spieler (aus AppController.animationPlayer, einmal).
    func makeAnimationPlayer() -> AnimationPlayer {
        let player = AnimationPlayer(model: model.animation)
        player.onPose = { [weak self] transforms, hidden, collision, camera in
            guard let self else { return }
            self.scene.setAnimationPose(transforms, hidden: hidden, collision: collision)
            if let camera { self.applyAnimationCamera(camera) }
            self.refreshOverlay()
        }
        player.onStateChange = { [weak self] in self?.sendAnimationState() }
        player.pivotOf = { [weak self] name in
            guard let self, let rec = self.scene.record(name) else { return nil }
            return SceneStore.transformBox(rec.localMin, rec.localMax, rec.header.transformMatrix).center
        }
        return player
    }

    /// Benannte Kameras (Strang KAM): liefert für "Kamera/<name>" die Kamera zur Zeit t. Solange niemand sie setzt,
    /// nimmt die Videoausgabe die Viewer-Kamera bzw. die Kamerafahrt.
    func animationCamera(named name: String, at t: Double) -> CameraState? {
        animationRuntime.cameraResolver?(name, t)
    }

    // MARK: Nachrichten

    func handleAnimation(_ m: AnimationMessage) {
        switch m {
        case .definition(let clip):
            animationPlayer.define(clip)
            log(.info, "Animation \(clip.name): \(KevFormatNumbers.seconds(clip.duration)), \(clip.frameCount) Bilder, "
                + "\(clip.parts.count) bewegte Teile" + (clip.hasCamera ? ", Kamerafahrt" : ""))
            for w in clip.warnings { log(.warning, "Animation \(clip.name): \(w)") }
        case .remove(let name):
            animationPlayer.remove(name)
        case .collisions(let c):
            animationPlayer.setCollisions(c)
            if c.collisions.isEmpty {
                log(.info, "Animation \(c.name): keine Kollision (\(c.checkedFrames) Bilder geprüft)")
            } else {
                for k in c.collisions {
                    log(.warning, "Kollision \(c.name) bei \(KevFormatNumbers.seconds(k.time)): "
                        + "\(k.parts.joined(separator: " ↔ ")), Eindringtiefe \(KevFormatNumbers.mm(k.depth))")
                }
            }
        case .play(let p):
            let (ok, message) = performAnimationPlay(p)
            send(AckOutMessage(replyTo: p.id, ok: ok, message: message))
        case .seek(let s):
            let (ok, message) = performAnimationSeek(s)
            send(AckOutMessage(replyTo: s.id, ok: ok, message: message))
        case .video(let v):
            startVideo(v)
        }
    }

    private func clipNamed(_ name: String?) -> (AnimationClip?, String?) {
        if let name {
            guard let clip = animationPlayer.clips[name] else {
                let known = animationPlayer.order.map { "„\($0)“" }.joined(separator: ", ")
                return (nil, "Animation „\(name)“ ist in der App nicht geladen" + (known.isEmpty ? "" : " (da: \(known))"))
            }
            return (clip, nil)
        }
        guard let clip = animationPlayer.current else { return (nil, "Keine Animation geladen") }
        return (clip, nil)
    }

    private func performAnimationPlay(_ p: AnimationPlayCommand) -> (Bool, String?) {
        let (clip, err) = clipNamed(p.name)
        guard let clip else { return (false, err) }
        if model.animation.selected != clip.name { animationPlayer.select(clip.name) }
        model.animation.loop = p.loop
        animationPlayer.setSpeed(p.speed)
        if p.on {
            animationPlayer.play(fromStart: p.fromStart)
            return (true, "spielt \(clip.name)")
        }
        animationPlayer.pause()
        return (true, "angehalten bei \(KevFormatNumbers.seconds(model.animation.time))")
    }

    private func performAnimationSeek(_ s: AnimationSeekCommand) -> (Bool, String?) {
        let (clip, err) = clipNamed(s.name)
        guard let clip else { return (false, err) }
        if model.animation.selected != clip.name { animationPlayer.select(clip.name) }
        animationPlayer.seek(to: s.time)
        return (true, "Bild \(model.animation.frame)")
    }

    func sendAnimationState() {
        let a = model.animation
        send(AnimationStateMessage(
            name: a.selected, time: a.time, frame: a.frame, playing: a.playing, loop: a.loop, speed: a.speed))
    }

    private func applyAnimationCamera(_ key: AnimationCameraKey) {
        let cam = AnimationVideoExporter.camera(from: key, base: viewport.camera)
        viewport.controller.animateTo(cam, duration: 0)
    }

    // MARK: AnimationActions

    public func selectAnimation(_ name: String) { animationPlayer.select(name) }
    public func togglePlayback() { animationPlayer.toggle() }
    public func setPlaying(_ on: Bool) { if on { animationPlayer.play() } else { animationPlayer.pause() } }
    public func seekAnimation(to time: Double) { animationPlayer.seek(to: time) }
    public func stepAnimation(frames: Int) { animationPlayer.step(frames: frames) }
    public func jumpToAnimationStart() { animationPlayer.jumpToStart() }
    public func jumpToAnimationEnd() { animationPlayer.jumpToEnd() }
    public func setAnimationLoop(_ on: Bool) { animationPlayer.setLoop(on) }
    public func setAnimationSpeed(_ speed: Double) { animationPlayer.setSpeed(speed) }
    public func setFollowsAnimationCamera(_ on: Bool) { animationPlayer.setFollowsCamera(on) }
    public func resetAnimationPose() { animationPlayer.resetPose() }

    public func checkAnimationCollisions() {
        guard let clip = animationPlayer.current else { return }
        animationPlayer.setCollisionCheckRunning()
        request(AnimationCollisionsRequestMessage(id: nextRequestID(), name: clip.name), timeout: 180) {
            [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.animation(.collisions(let c))):  // Antworten mit reply_to kommen nur hier an
                self.handleAnimation(.collisions(c))
            case .success(let m):
                self.animationPlayer.setCollisionCheckFailed("unerwartete Antwort \(m.typeName)")
                self.log(.warning, "Kollisionsprüfung: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.animationPlayer.setCollisionCheckFailed(e.message)
                self.log(.error, "Kollisionsprüfung fehlgeschlagen: \(e.message)")
            }
        }
    }

    public func exportAnimationVideo(width: Int, format: String) {
        guard let clip = animationPlayer.current, let project = model.project else { return }
        let ext = format == "prores" ? "mov" : "mp4"
        let url = project.path.appendingPathComponent("output/animationen", isDirectory: true)
            .appendingPathComponent("\(Self.safeFileName(clip.name)).\(ext)")
        let height = Int((Double(width) * 9 / 16).rounded()) / 2 * 2
        renderVideo(clip: clip, width: width, height: height, fps: clip.fps, format: format, camera: nil, output: url) {
            [weak self] result in
            guard let self else { return }
            if case .success(let out) = result { self.revealFiles([URL(fileURLWithPath: out.path)]) }
        }
    }

    static func safeFileName(_ name: String) -> String {
        let bad = CharacterSet(charactersIn: "/\\:*?\"<>|").union(.newlines)
        let s = name.components(separatedBy: bad).joined(separator: "_").trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? "Animation" : s
    }

    // MARK: Video

    private func startVideo(_ v: AnimationVideoCommand) {
        let (clip, err) = clipNamed(v.name)
        guard let clip else {
            send(AnimationVideoResponseMessage(replyTo: v.id, ok: false, path: nil, frames: 0, milliseconds: 0, message: err))
            return
        }
        guard !v.path.isEmpty else {
            send(AnimationVideoResponseMessage(
                replyTo: v.id, ok: false, path: nil, frames: 0, milliseconds: 0, message: "Kein Zielpfad"))
            return
        }
        renderVideo(
            clip: clip, width: v.width, height: v.height, fps: v.fps ?? clip.fps, format: v.format, camera: v.camera,
            output: URL(fileURLWithPath: v.path)
        ) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let out):
                self.send(AnimationVideoResponseMessage(
                    replyTo: v.id, ok: true, path: out.path, frames: out.frames, milliseconds: out.milliseconds,
                    message: self.animationRuntime.lastVideoNote, camera: self.animationRuntime.lastVideoCamera))
            case .failure(let e):
                self.send(AnimationVideoResponseMessage(
                    replyTo: v.id, ok: false, path: nil, frames: 0, milliseconds: 0, message: e.message))
            }
        }
    }

    /// Rendert Bild für Bild aus der Viewer-Sicht (bzw. der Kamerafahrt oder einer benannten Kamera) und setzt danach
    /// Lage und Zeit wie vorher.
    func renderVideo(
        clip: AnimationClip, width: Int, height: Int, fps: Double, format: String, camera: String?, output: URL,
        completion: @escaping (Result<AnimationVideoExporter.Output, AnimationVideoExporter.ExportError>) -> Void
    ) {
        let player = animationPlayer
        let anim = model.animation
        if player.model.playing { player.pause() }
        let wasPosed = anim.posed, oldTime = anim.time
        let baseCamera = viewport.camera
        var note: String?
        var cameraLabel = clip.hasCamera && anim.followsCamera ? "Kamerafahrt" : "Viewer"
        if let camera, !camera.isEmpty {
            if animationCamera(named: camera, at: 0) != nil {
                cameraLabel = camera
            } else {
                note = "Kamera „\(camera)“ gibt es noch nicht als Objekt; Video aus der \(cameraLabel == "Viewer" ? "Viewer-Kamera" : "Kamerafahrt")"
            }
        }
        animationRuntime.lastVideoNote = note
        animationRuntime.lastVideoCamera = cameraLabel
        let named = cameraLabel != "Viewer" && cameraLabel != "Kamerafahrt" ? camera : nil
        let useTrack = cameraLabel == "Kamerafahrt"
        player.suspended = true
        anim.video = .rendering(frame: 0, of: Int((clip.duration * fps).rounded()) + 1)
        log(.info, "Video \(clip.name): \(width) × \(height), \(KevFormatNumbers.number(fps)) fps → \(output.path)")
        let job = AnimationVideoExporter.Job(
            clip: clip, width: width, height: height, fps: fps, format: format, output: output,
            camera: { [weak self] t in
                guard let self else { return baseCamera }
                if let named, let cam = self.animationCamera(named: named, at: t) { return cam }
                if useTrack, let key = clip.cameraKey(at: t) {
                    return AnimationVideoExporter.camera(from: key, base: baseCamera)
                }
                return baseCamera
            },
            bodies: { [weak self] t in
                guard let self else { return [] }
                self.scene.setAnimationPose(
                    clip.pose(at: t, pivots: player.pivotsFor(clip)), hidden: clip.hiddenParts(at: t), collision: [])
                return self.scene.snapshotBodies()
            },
            displayMode: scene.viewportDisplayMode, lighting: viewport.controller.lightingConfiguration)
        videoExporter.export(job, progress: { done, total in
            anim.video = done >= total ? .encoding : .rendering(frame: done, of: total)
        }) { [weak self] result in
            guard let self else { return }
            player.suspended = false
            anim.posed = wasPosed
            player.seek(to: oldTime)
            if !wasPosed { player.resetPose() }
            switch result {
            case .success(let out):
                anim.video = .finished(path: out.path)
                self.log(.info, "Video fertig: \(out.path) (\(out.frames) Bilder, \(out.milliseconds) ms)")
                DispatchQueue.main.asyncAfter(deadline: .now() + 10) {  // Hinweis nach einer Weile ausblenden
                    MainActor.assumeIsolated { if anim.video == .finished(path: out.path) { anim.video = .idle } }
                }
            case .failure(let e):
                anim.video = .failed(e.message)
                self.log(.error, "Video nicht erstellt: \(e.message)")
            }
            completion(result)
        }
    }
}

/// Zahlen für Protokollzeilen (deutsch).
enum KevFormatNumbers {
    static func number(_ x: Double, digits: Int = 2) -> String {
        var s = String(format: "%.\(digits)f", x)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s.replacingOccurrences(of: ".", with: ",")
    }

    static func seconds(_ x: Double) -> String { "\(number(x)) s" }
    static func mm(_ x: Double) -> String { "\(number(x)) mm" }
}
