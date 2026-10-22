import KevCADCore
import SwiftUI

/// Menüpunkte für Phase 2 (eigene Datei, damit Commands.swift unberührt bleibt): Vorschläge von Claude prüfen und
/// Ablage > Stückliste als CSV exportieren. Die Stückliste unter dem Viewport schalten die Schnellansichten
/// (MaterialCommands, ⇧⌘B). Das Fenster Lagerkatalog (⇧⌘K) steht als eigene Szene im Fenstermenü.
struct StockCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?

    var body: some Commands {
        CommandGroup(after: .sidebar) {
            if let count = model.catalog?.suggestionCount, count > 0 {
                Button("Vorschläge von Claude prüfen (\(count)) …") { session.showCatalog(section: .suggestions) }
            }
            Divider()
        }
        CommandGroup(after: .importExport) {
            Button("Stückliste als CSV exportieren") { model.actions?.export(formats: ["bom_csv"]) }
                .disabled(model.project == nil || (model.bom?.lines.isEmpty ?? true))
        }
    }
}
