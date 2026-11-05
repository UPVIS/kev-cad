import KevCADCore
import SwiftUI

/// Untermenü „Material“ im Menü „Modell“: die Abschnitte des Bereichs (als Kachel), Bestand erfassen, Gebaut …, Einkaufsliste, Zukaufteil,
/// Bericht, Katalog. Bereiche und Schnellansichten gibt es seit V2-3 nicht mehr: Fokus und Werkstatt (⌘1, ⌘2) und
/// Kacheln (⌃⌘1 bis ⌃⌘8) stehen in OberflaechenCommands.
struct MaterialMenue: View {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?
    /// Bereich „Material“ des Fensters, bewusst nicht beobachtet: Auswahl und Abschnitt sollen nicht die Menüs neu bauen.
    private var material: MaterialZustand? { window?.materialZustand }

    private var bereit: Bool { window != nil && model.project != nil }

    var body: some View {
        // Einmal je Auswertung der Menüs (sie laufen bei jeder Änderung am Modell)
        let d = model.materialDaten
        Group {
            ForEach(MaterialAbschnitt.allCases) { a in
                Button(a.titel) {
                    material?.zeige(a)
                    window?.zeige(.material)
                }
                .disabled(!bereit)
            }
            Divider()
            Button("Bestand erfassen …") {
                BestandUI.shared.erfassen = ErfassenAnfrage(stockID: nil)
            }
            .disabled(!bereit || model.bestandActions == nil || model.bestandZustand.bestand == nil)
            Button("Gebaut …") { BestandUI.shared.zeigeGebaut() }
                .disabled(!bereit || model.bestandZustand.zuschnitt == nil || model.bestandActions == nil)
            Divider()
            Button("Einkaufsliste kopieren") {
                copyToPasteboard(MaterialText.einkaufText(
                    d, projekt: model.project?.name, stand: BestandText.anzeige(BestandText.heute(), mitZeit: false),
                    abgehakt: material?.abgehakt.schluessel ?? []))
            }
            .disabled(d.einkauf.isEmpty)
            Button("Einkaufsliste als CSV sichern") { EinkaufExport.sichern(model) }
                .disabled(model.project == nil || d.einkauf.isEmpty)
            Button("Zukaufteil hinzufügen …") { session.showZukaufDialog() }
            Divider()
            Button("Als Bericht drucken …") {
                BerichteUI.shared.bericht = (material?.abschnitt ?? .stueckliste).bericht
                window?.dokumenteZustand?.waehle(.berichte)
                window?.zeige(.dokumente)
            }
            .disabled(!bereit)
            Button("Lagerkatalog") { session.showCatalog() }
            if let n = model.catalog?.suggestionCount, n > 0 {
                Button("Vorschläge von Claude prüfen (\(n)) …") { session.showCatalog(section: .suggestions) }
            }
        }
    }

    static func kuerzel(_ a: Schnellansicht) -> KeyEquivalent {
        switch a {
        case .stueckliste: return "1"
        case .zuschnitt: return "2"
        case .druck: return "3"
        }
    }
}
