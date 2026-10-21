import KevCADCore
import SwiftUI

/// Menüpunkte zum Bestand (eigene Datei, damit die gemeinsamen Menüs klein bleiben): Darstellung > Bestand zeigen (⌥⌘B),
/// Ablage > Einkaufsliste als CSV exportieren, Ablage > Gebaut … (Vorschau der Buchung mit Bestätigung).
struct BestandCommands: Commands {
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?

    private var bereit: Bool { window != nil && model.project != nil }

    var body: some Commands {
        CommandGroup(after: .sidebar) {
            Button("Bestand zeigen") { BestandUI.shared.zeige(.bestand, in: window) }
                .keyboardShortcut("b", modifiers: [.command, .option])
                .disabled(!bereit)
        }
        CommandGroup(after: .importExport) {
            Button("Einkaufsliste als CSV exportieren") { model.bestandActions?.exportEinkaufsliste() }
                .disabled(model.project == nil || model.bestandZustand.zuschnitt == nil || model.bestandActions == nil)
            Divider()
            Button("Gebaut …") { BestandUI.shared.zeigeGebaut(in: window) }
                .disabled(!bereit || model.bestandZustand.zuschnitt == nil || model.bestandActions == nil)
        }
    }
}
