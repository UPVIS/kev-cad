import KevCADCore
import SwiftUI

/// Menüeintrag „Rendern …“ (⌥⌘R) unter „Ablage“ neben „Bild speichern“: öffnet die Kachel.
struct RenderCommands: Commands {
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Button("Rendern …") { model.oberflaechenActions?.zeigeKachel(.render) }
                .keyboardShortcut("r", modifiers: [.command, .option])
                .disabled(model.project == nil || model.parts.isEmpty)
        }
    }
}
