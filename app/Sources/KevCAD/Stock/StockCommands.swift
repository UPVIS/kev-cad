import KevCADCore
import SwiftUI

/// Menüpunkte für Phase 2 (eigene Datei, damit Commands.swift unberührt bleibt): Darstellung > Stückliste (⇧⌘B) und
/// Ablage > Stückliste als CSV exportieren. Das Fenster Lagerkatalog (⇧⌘K) steht als eigene Szene im Fenstermenü.
struct StockCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?

    var body: some Commands {
        CommandGroup(after: .sidebar) {
            Button(window?.showBOM == true ? "Stückliste ausblenden" : "Stückliste einblenden") {
                guard let window else { return }
                withAnimation(.snappy(duration: 0.2)) { window.showBOM.toggle() }
            }
            .keyboardShortcut("b", modifiers: [.command, .shift])
            .disabled(window == nil || model.project == nil)
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
