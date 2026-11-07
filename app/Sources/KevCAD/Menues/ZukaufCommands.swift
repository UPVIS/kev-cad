import KevCADCore
import SwiftUI

/// Menüpunkte für Phase 3 (eigene Datei): Ablage > Zukaufteil hinzufügen … (⌥⇧⌘K) und, solange ein Teil auf CAD
/// wartet, CAD-Datei wählen …
struct ZukaufCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Divider()
            Button("Zukaufteil hinzufügen …") { session.showZukaufDialog() }
                .keyboardShortcut("k", modifiers: [.command, .option, .shift])
            if let first = model.waitingForCAD.first {
                Button("CAD-Datei für „\(session.zukaufName(first.id))“ wählen …") { session.chooseCADFile(for: first.id) }
            }
        }
    }
}
