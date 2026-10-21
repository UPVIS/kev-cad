import KevCADCore
import SwiftUI

/// Menü „Animation“ mit den Tasten wie in Blender: Leertaste abspielen/anhalten, ← und → ein Bild, Umschalt+← und
/// Umschalt+→ an Anfang und Ende. Die Tasten wirken nur im Projektfenster mit Animation; in Textfeldern und Listen
/// gehen sie dorthin (KeyboardGuard).
struct AnimationCommands: Commands {
    @ObservedObject var model: AppModel
    @ObservedObject var animation: AnimationModel
    @FocusedObject private var window: ProjectWindowState?

    private var actions: AnimationActions? { model.actions as? AnimationActions }
    private var enabled: Bool { window != nil && animation.hasAnimation && actions != nil }

    var body: some Commands {
        CommandMenu("Animation") {
            Group {
                Button(animation.playing ? "Anhalten" : "Abspielen") { actions?.togglePlayback() }
                    .keyboardShortcut(.space, modifiers: [])
                Button("Ein Bild zurück") { actions?.stepAnimation(frames: -1) }
                    .keyboardShortcut(.leftArrow, modifiers: [])
                Button("Ein Bild vor") { actions?.stepAnimation(frames: 1) }
                    .keyboardShortcut(.rightArrow, modifiers: [])
                Button("Zum Anfang") { actions?.jumpToAnimationStart() }
                    .keyboardShortcut(.leftArrow, modifiers: .shift)
                Button("Zum Ende") { actions?.jumpToAnimationEnd() }
                    .keyboardShortcut(.rightArrow, modifiers: .shift)
                Divider()
                Toggle("Schleife", isOn: Binding(get: { animation.loop }, set: { actions?.setAnimationLoop($0) }))
                Menu("Geschwindigkeit") {
                    ForEach([0.25, 0.5, 1.0, 2.0, 4.0], id: \.self) { s in
                        Button(AnimationTimeline.speedText(s)) { actions?.setAnimationSpeed(s) }
                    }
                }
                if animation.entries.count > 1 {
                    Menu("Animation wählen") {
                        ForEach(animation.entries) { e in
                            Button(e.name) { actions?.selectAnimation(e.name) }
                        }
                    }
                }
                Divider()
                Button("Kollisionen prüfen") { actions?.checkAnimationCollisions() }
                Button("Video (MP4, 1920 × 1080)") { actions?.exportAnimationVideo(width: 1920, format: "mp4") }
                Button("Video (ProRes 422, 1920 × 1080)") { actions?.exportAnimationVideo(width: 1920, format: "prores") }
                Divider()
                Button("Bewegung zurücksetzen") { actions?.resetAnimationPose() }
                    .disabled(!animation.posed)
            }
            .disabled(!enabled)
        }
    }
}
