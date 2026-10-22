import KevCADCore
import SwiftUI

/// Menüs des Strangs „Material“:
/// - Darstellung (oben): Bereich wechseln ⌘1 3D-Modell, ⌘2 Dokumente, ⌘3 Material; Schnellansichten unter dem Viewport
///   einzeln auf- und zuklappen (⌃⌘1 Stückliste, ⌃⌘2 Zuschnitt, ⌃⌘3 Druck), alle aufklappen (⌃⌘9), alle einklappen
///   (⌃⌘0), Schnellansichten umschalten (⇧⌘B: alles zu bzw. das zuletzt Offene wieder auf).
/// - Material: die Abschnitte des Bereichs, Bestand erfassen, Gebaut …, Einkaufsliste, Zukaufteil, Bericht, Katalog.
struct MaterialCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?
    /// Bereich „Material“ des Fensters, bewusst nicht beobachtet: Auswahl und Abschnitt sollen nicht die Menüs neu bauen.
    private var material: MaterialZustand? { window?.materialZustand }

    private var bereit: Bool { window != nil && model.project != nil }

    var body: some Commands {
        // Einmal je Auswertung der Menüs (sie laufen bei jeder Änderung am Modell)
        let d = model.materialDaten
        let sichtbar = SchnellansichtenBereich.sichtbar(d)
        CommandGroup(before: .sidebar) {
            ForEach(ProjektBereich.allCases, id: \.self) { b in
                Button(b.titel) { window?.zeige(b) }
                    .keyboardShortcut(b.kuerzel, modifiers: .command)
                    .disabled(!bereit)
            }
            Divider()
            Menu("Schnellansichten") {
                ForEach(Schnellansicht.allCases) { a in
                    Toggle(a.titel, isOn: Binding(
                        get: { window?.schnell.istOffen(a) ?? false },
                        set: { _ in withAnimation(.snappy(duration: 0.22)) { window?.schnell.umschalten(a) } }))
                        .keyboardShortcut(Self.kuerzel(a), modifiers: [.command, .control])
                        .disabled(!bereit || !sichtbar.contains(a))
                }
                Divider()
                Button("Alle aufklappen") {
                    withAnimation(.snappy(duration: 0.22)) { window?.schnell.alleAuf(sichtbar) }
                }
                .keyboardShortcut("9", modifiers: [.command, .control])
                .disabled(!bereit)
                Button("Alle einklappen") {
                    withAnimation(.snappy(duration: 0.22)) { window?.schnell.alleZu() }
                }
                .keyboardShortcut("0", modifiers: [.command, .control])
                .disabled(!bereit)
            }
            Button(!(window?.schnell.offene(sichtbar).isEmpty ?? true)
                   ? "Schnellansichten einklappen" : "Schnellansichten aufklappen") {
                withAnimation(.snappy(duration: 0.22)) { window?.schnell.allesUmschalten(sichtbar) }
            }
            .keyboardShortcut("b", modifiers: [.command, .shift])
            .disabled(!bereit)
            Divider()
        }
        CommandMenu("Material") {
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
