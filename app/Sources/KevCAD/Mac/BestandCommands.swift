import KevCADCore
import SwiftUI

/// Menüpunkte zum Bestand (eigene Datei, damit die gemeinsamen Menüs klein bleiben): Ablage > Einkaufsliste als CSV
/// exportieren (dieselbe Liste wie im Bereich „Material“, mit Zukaufteilen), Ablage > Gebaut … (Vorschau der Buchung mit
/// Bestätigung). Den Bestand selbst zeigt der Bereich „Material“ (Menü „Material“, ⌘3); das frühere ⌥⌘B gehört wieder
/// allein „Bedingungen am Teil“.
struct BestandCommands: Commands {
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?

    private var bereit: Bool { window != nil && model.project != nil }

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Button("Einkaufsliste als CSV exportieren") { EinkaufExport.sichern(model) }
                .disabled(model.project == nil || model.materialDaten.einkauf.isEmpty)
            Divider()
            Button("Gebaut …") { BestandUI.shared.zeigeGebaut() }
                .disabled(!bereit || model.bestandZustand.zuschnitt == nil || model.bestandActions == nil)
        }
    }
}
