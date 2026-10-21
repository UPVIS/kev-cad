import Foundation
import QuartzCore
import simd

/// Spielt Animationen ab: hält die Clips aus ANIM_DEF, die Zeit, Schleife und Geschwindigkeit und rechnet zu jeder Zeit
/// die Lage aller bewegten Teile. Ohne Viewport testbar: Was gezeigt wird, geht über `onPose` an den App-Kern
/// (SceneStore und Kamera), Zustandswechsel für den Kernel über `onStateChange`.
@MainActor
public final class AnimationPlayer {
    public let model: AnimationModel
    public private(set) var clips: [String: AnimationClip] = [:]
    public private(set) var order: [String] = []
    private var collisionsByName: [String: [AnimationCollision]] = [:]
    private var collisionMeta: [String: (frames: Int, ms: Double)] = [:]

    /// Lage, ausgeblendete Teile, Kollisionspaar und Kamera der Kamerafahrt (nil = Kamera nicht anfassen).
    public var onPose: ((_ transforms: [String: simd_float4x4], _ hidden: Set<String>, _ collision: Set<String>,
        _ camera: AnimationCameraKey?) -> Void)?
    /// Abspielen, Anhalten, Springen (für ANIM_STATE an den Kernel).
    public var onStateChange: (() -> Void)?
    /// Uhr (in Tests ersetzbar).
    public var now: () -> CFTimeInterval = { CACurrentMediaTime() }
    /// Mitte eines Teils in Ruhelage (für das Überblenden zwischen zwei Bildern), vom App-Kern aus der Szene.
    public var pivotOf: ((String) -> SIMD3<Float>?)?
    private var pivots: [String: [String: SIMD3<Float>]] = [:]

    private var timer: Timer?
    private var wallStart: CFTimeInterval = 0
    private var timeStart: Double = 0
    /// Während der Videoausgabe steuert der Exporter die Lage selbst.
    public var suspended = false

    public init(model: AnimationModel) {
        self.model = model
    }

    public var current: AnimationClip? { model.selected.flatMap { clips[$0] } }

    // MARK: Clips

    public func define(_ clip: AnimationClip) {
        let isNew = clips[clip.name] == nil
        clips[clip.name] = clip
        if isNew { order.append(clip.name) }
        pivots[clip.name] = nil
        collisionsByName[clip.name] = nil  // neue Bewegung: alte Kollisionen gelten nicht mehr (der Kernel schickt sie neu)
        collisionMeta[clip.name] = nil
        if model.selected == nil || clips[model.selected!] == nil || (isNew && clip.isDefault && order.count == 1) {
            model.selected = clip.name
            model.time = 0
            model.followsCamera = true
        }
        refreshEntries()
        if model.selected == clip.name {
            model.time = min(model.time, clip.duration)
            model.frame = clip.frame(at: model.time)
            syncCollisions()
            model.posed = true
            applyPose()
        }
    }

    public func remove(_ name: String) {
        guard clips.removeValue(forKey: name) != nil else { return }
        order.removeAll { $0 == name }
        collisionsByName[name] = nil
        if model.selected == name {
            stopTimer()
            model.playing = false
            model.selected = order.first
            model.time = 0
            model.frame = 0
            syncCollisions()
            if current != nil { applyPose() } else { clearPose() }
        }
        refreshEntries()
    }

    public func removeAll() {
        stopTimer()
        clips = [:]
        order = []
        collisionsByName = [:]
        collisionMeta = [:]
        model.selected = nil
        model.playing = false
        model.time = 0
        model.frame = 0
        model.collisions = []
        model.activeCollisions = []
        model.collisionState = .unchecked
        model.posed = false
        refreshEntries()
        clearPose()
    }

    public func setCollisions(_ m: AnimationCollisionsMessage) {
        guard clips[m.name] != nil else { return }
        collisionsByName[m.name] = m.collisions
        collisionMeta[m.name] = (m.checkedFrames, m.milliseconds)
        if model.selected == m.name {
            syncCollisions()
            applyPose()
        }
    }

    public func setCollisionCheckRunning() { model.collisionState = .checking }

    public func setCollisionCheckFailed(_ message: String) { model.collisionState = .failed(message) }

    private func syncCollisions() {
        guard let name = model.selected else {
            model.collisions = []
            model.collisionState = .unchecked
            return
        }
        model.collisions = collisionsByName[name] ?? []
        if let meta = collisionMeta[name] {
            model.collisionState = .checked(frames: meta.frames, milliseconds: meta.ms)
        } else if model.collisionState != .checking {
            model.collisionState = .unchecked
        }
    }

    private func refreshEntries() {
        model.entries = order.compactMap { clips[$0] }.map {
            AnimationModel.Entry(
                name: $0.name, duration: $0.duration, fps: $0.fps, frameCount: $0.frameCount,
                movingParts: $0.parts.count, hasCamera: $0.hasCamera, warnings: $0.warnings)
        }
    }

    public func select(_ name: String) {
        guard clips[name] != nil, model.selected != name else { return }
        let wasPlaying = model.playing
        stopTimer()
        model.selected = name
        model.time = 0
        model.frame = 0
        syncCollisions()
        model.posed = true
        applyPose()
        if wasPlaying { play() } else { onStateChange?() }
    }

    // MARK: Abspielen

    public func play(fromStart: Bool = false) {
        guard let clip = current else { return }
        if fromStart || model.time >= clip.duration - 1e-6 { model.time = 0 }
        model.playing = true
        model.posed = true
        wallStart = now()
        timeStart = model.time
        applyPose()
        startTimer()
        onStateChange?()
    }

    public func pause() {
        guard model.playing else { return }
        tick()
        model.playing = false
        stopTimer()
        onStateChange?()
    }

    public func toggle() { if model.playing { pause() } else { play() } }

    public func setLoop(_ on: Bool) {
        model.loop = on
        onStateChange?()
    }

    public func setSpeed(_ speed: Double) {
        let s = min(max(speed, 0.05), 8)
        if model.playing {  // ohne Sprung weiterlaufen
            timeStart = model.time
            wallStart = now()
        }
        model.speed = s
        onStateChange?()
    }

    public func setFollowsCamera(_ on: Bool) {
        model.followsCamera = on
        applyPose()
    }

    /// Zur Zeit springen (hält an).
    public func seek(to t: Double) {
        guard let clip = current else { return }
        if model.playing {
            model.playing = false
            stopTimer()
        }
        model.time = min(max(t, 0), clip.duration)
        model.frame = clip.frame(at: model.time)
        model.posed = true
        applyPose()
        onStateChange?()
    }

    /// Bild für Bild (Pfeiltasten).
    public func step(frames n: Int) {
        guard let clip = current else { return }
        let k = min(max(clip.frame(at: model.time) + n, 0), clip.lastFrame)
        seek(to: clip.time(ofFrame: k))
    }

    public func jumpToStart() { seek(to: 0) }

    public func jumpToEnd() { seek(to: current?.duration ?? 0) }

    /// Ruhelage aus model.py (die Animation bleibt geladen).
    public func resetPose() {
        if model.playing {
            model.playing = false
            stopTimer()
        }
        model.time = 0
        model.frame = 0
        model.posed = false
        model.activeCollisions = []
        clearPose()
        onStateChange?()
    }

    /// Ein Schritt der Uhr: Zeit fortschreiben und Lage zeigen.
    public func tick() {
        guard model.playing, let clip = current, !suspended else { return }
        var t = timeStart + (now() - wallStart) * model.speed
        var ended = false
        if t >= clip.duration {
            if model.loop, clip.duration > 0 {
                t = t.truncatingRemainder(dividingBy: clip.duration)
                timeStart = t
                wallStart = now()
            } else {
                t = clip.duration
                model.playing = false
                stopTimer()
                ended = true
            }
        }
        model.time = t
        let k = clip.frame(at: t)
        if k != model.frame { model.frame = k }
        applyPose()
        if ended { onStateChange?() }  // erst jetzt: der gemeldete Stand trägt das letzte Bild, nicht das davor
    }

    // MARK: Lage

    /// Teile zur aktuellen Zeit zeigen.
    public func applyPose() {
        guard !suspended else { return }
        guard let clip = current, model.posed else {
            clearPose()
            return
        }
        let t = model.time
        let active = model.collisions.filter { $0.covers(time: t, fps: clip.fps) }
        if active != model.activeCollisions { model.activeCollisions = active }
        let camera = model.followsCamera ? clip.cameraKey(at: t) : nil
        onPose?(clip.pose(at: t, pivots: pivotsFor(clip)), clip.hiddenParts(at: t), Set(active.flatMap(\.parts)), camera)
    }

    /// Mitten der bewegten Teile (einmal je Clip, sobald die Szene sie kennt).
    public func pivotsFor(_ clip: AnimationClip) -> [String: SIMD3<Float>] {
        if let p = pivots[clip.name], p.count == clip.parts.count { return p }
        var p: [String: SIMD3<Float>] = [:]
        for name in clip.parts { if let c = pivotOf?(name) { p[name] = c } }
        pivots[clip.name] = p
        return p
    }

    private func clearPose() {
        if !model.activeCollisions.isEmpty { model.activeCollisions = [] }
        onPose?([:], [], [], nil)
    }

    private func startTimer() {
        guard timer == nil else { return }
        let t = Timer(timeInterval: 1.0 / 120.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        RunLoop.main.add(t, forMode: .common)  // läuft auch, während der Schieber gezogen wird
        timer = t
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }
}
