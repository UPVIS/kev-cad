import Foundation

/// Zustand der Animation für die Oberfläche (Zeitleiste, Statusleiste). Eigenes Objekt, damit das Abspielen mit bis zu
/// 120 Bildern je Sekunde nur die Zeitleiste neu zeichnet und nicht das ganze Fenster (AppModel bleibt still).
///
/// Vertrag wie AppModel: Der App-Kern (AppController+Animation) schreibt, die Oberfläche liest und ruft
/// `AnimationActions` (über `model.actions as? AnimationActions`).
@MainActor
public final class AnimationModel: ObservableObject {
    /// Übersicht einer Animation für die Auswahl.
    public struct Entry: Identifiable, Equatable, Sendable {
        public var name: String
        public var duration: Double
        public var fps: Double
        public var frameCount: Int
        public var movingParts: Int
        public var hasCamera: Bool
        public var warnings: [String]
        public var id: String { name }

        public init(
            name: String, duration: Double, fps: Double, frameCount: Int, movingParts: Int, hasCamera: Bool,
            warnings: [String] = []
        ) {
            self.name = name
            self.duration = duration
            self.fps = fps
            self.frameCount = frameCount
            self.movingParts = movingParts
            self.hasCamera = hasCamera
            self.warnings = warnings
        }
    }

    public enum CollisionState: Equatable, Sendable {
        case unchecked
        case checking
        case checked(frames: Int, milliseconds: Double)
        case failed(String)
    }

    public enum VideoState: Equatable, Sendable {
        case idle
        case rendering(frame: Int, of: Int)
        case encoding
        case finished(path: String)
        case failed(String)
    }

    /// Zeit, Bild und Videofortschritt ändern sich bis zu 120-mal je Sekunde: eigenes Objekt, damit nur Schieber und
    /// Zeitanzeige neu zeichnen (Menüs und der Rest der Zeitleiste beobachten AnimationModel).
    public let clock = AnimationClock()

    @Published public internal(set) var entries: [Entry] = []
    @Published public internal(set) var selected: String?
    public internal(set) var time: Double {
        get { clock.time }
        set { clock.time = newValue }
    }
    public internal(set) var frame: Int {
        get { clock.frame }
        set { if clock.frame != newValue { clock.frame = newValue } }
    }
    public internal(set) var video: VideoState {
        get { clock.video }
        set { clock.video = newValue }
    }
    @Published public internal(set) var playing = false
    @Published public internal(set) var loop = false
    @Published public internal(set) var speed: Double = 1
    /// Die Teile stehen in der Lage der Animation (false nach „Bewegung zurücksetzen“: Ruhelage aus model.py).
    @Published public internal(set) var posed = false
    @Published public internal(set) var collisions: [AnimationCollision] = []
    @Published public internal(set) var collisionState: CollisionState = .unchecked
    /// Kollisionen im aktuellen Bild.
    @Published public internal(set) var activeCollisions: [AnimationCollision] = []
    /// Die Viewer-Kamera folgt der Kamerafahrt aus `anim.ansicht` (nur wenn es eine gibt).
    @Published public internal(set) var followsCamera = true

    public init() {}

    public var current: Entry? { entries.first { $0.name == selected } ?? entries.first }
    public var hasAnimation: Bool { !entries.isEmpty }
    public var duration: Double { current?.duration ?? 0 }
    public var lastFrame: Int { max(0, (current?.frameCount ?? 1) - 1) }
}

/// Schnell wechselnder Teil des Animationszustands (siehe `AnimationModel.clock`).
@MainActor
public final class AnimationClock: ObservableObject {
    @Published public internal(set) var time: Double = 0
    @Published public internal(set) var frame: Int = 0
    @Published public internal(set) var video: AnimationModel.VideoState = .idle

    public init() {}
}

/// Aktionen der Zeitleiste. Implementiert vom App-Kern (AppController); die Oberfläche ruft sie über
/// `model.actions as? AnimationActions` auf (wie NavigationActions).
@MainActor
public protocol AnimationActions: AnyObject {
    func selectAnimation(_ name: String)
    func togglePlayback()
    func setPlaying(_ on: Bool)
    /// Springt zur Zeit (s) und hält an.
    func seekAnimation(to time: Double)
    /// Ein Bild vor (+1) oder zurück (-1).
    func stepAnimation(frames: Int)
    func jumpToAnimationStart()
    func jumpToAnimationEnd()
    func setAnimationLoop(_ on: Bool)
    func setAnimationSpeed(_ speed: Double)
    func setFollowsAnimationCamera(_ on: Bool)
    /// Alle Teile in die Ruhelage aus model.py (Animation bleibt geladen).
    func resetAnimationPose()
    func checkAnimationCollisions()
    /// Video nach output/animationen/ (H.264, `prores` = ProRes 422).
    func exportAnimationVideo(width: Int, format: String)
}
