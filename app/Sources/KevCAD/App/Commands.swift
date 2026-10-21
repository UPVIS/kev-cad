import KevCADCore
import SwiftUI

/// Menüs und Tastenkürzel. Einbuchstabige Kürzel wirken nur, wenn das Projektfenster vorne ist, und nicht, solange ein
/// Textfeld den Fokus hat (siehe `KeyboardGuard`).
struct KevCADCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var recents: RecentProjects
    /// Gesetzt, solange das Projektfenster das Hauptfenster ist.
    @FocusedObject private var window: ProjectWindowState?

    private var hasProject: Bool { model.project != nil }
    private var inProject: Bool { window != nil && hasProject }
    private var hasSelection: Bool { !model.selection.isEmpty }
    /// Blender-Befehle des App-Kerns (im Demomodus nicht vorhanden).
    private var nav: NavigationActions? { model.actions as? NavigationActions }

    private func axisView(_ view: StandardViewName) {
        if let nav { nav.axisView(view) } else { model.actions?.setStandardView(view) }
    }

    private func viewSelected() {
        if let nav { nav.viewSelected() } else { model.fitSelection() }
    }

    private func viewAll() {
        if let nav { nav.viewAll() } else { model.actions?.focus(on: model.parts.filter(\.visible).map(\.id)) }
    }

    var body: some Commands {
        // Ablage
        CommandGroup(replacing: .newItem) {
            Button("Neues Projekt …") { session.requestNewProject() }
                .keyboardShortcut("n")
            Button("Öffnen …") { session.presentOpenPanel() }
                .keyboardShortcut("o")
            Menu("Zuletzt geöffnet") {
                ForEach(recents.items) { item in
                    Button(item.isMissing ? "\(item.name) (fehlt)" : item.name) { session.openRecent(item) }
                }
                if recents.items.isEmpty {
                    Text("Keine Projekte")
                }
                Divider()
                Button("Fehlende entfernen") { recents.removeMissing() }
                    .disabled(!recents.items.contains(where: \.isMissing))
                Button("Liste leeren") { recents.clear() }
                    .disabled(recents.items.isEmpty)
            }
        }
        CommandGroup(replacing: .saveItem) {
            Button("model.py im Editor öffnen") { session.openModelInEditor() }
                .keyboardShortcut("o", modifiers: [.command, .option])
                .disabled(!hasProject)
            Button("Projektordner im Finder zeigen") { session.revealProjectInFinder() }
                .disabled(!hasProject)
        }
        CommandGroup(replacing: .importExport) {
            Menu("Exportieren") {
                Button("STEP, STL und 3MF") { model.actions?.export(formats: ExportFormat.standard.map(\.rawValue)) }
                    .keyboardShortcut("e", modifiers: [.command, .shift])
                Divider()
                ForEach(ExportFormat.allCases) { format in
                    Button("Nur \(format.title)") { model.actions?.export(formats: [format.rawValue]) }
                }
            }
            .disabled(!hasProject || model.parts.isEmpty)
            Button("Bild speichern") { model.actions?.saveScreenshot() }
                .keyboardShortcut("s", modifiers: [.command, .option])
                .disabled(!hasProject)
        }

        // Darstellung
        CommandGroup(before: .toolbar) {
            Group {
                // Ansicht wie in Blender (Ziffernblock oder Zahlenreihe)
                ForEach(StandardViewName.menuOrder.filter { $0.blenderKey != nil }, id: \.self) { view in
                    Button(view.title) { axisView(view) }
                        .keyboardShortcut(view.blenderKey!.key, modifiers: view.blenderKey!.modifiers)
                }
                Button("Gegenseite") { nav?.viewOpposite() }
                    .keyboardShortcut("9", modifiers: [])
                Button(model.orthographic ? "Perspektive" : "Parallelprojektion") { nav?.toggleProjection() }
                    .keyboardShortcut("5", modifiers: [])
                Menu("Isometrisch") {
                    ForEach([StandardViewName.iso] + StandardViewName.extraIsoOrder, id: \.self) { view in
                        Button(view.title) { model.actions?.setStandardView(view) }
                    }
                }
                Menu("Drehen, Schwenken, Zoomen") {
                    Button("Nach links drehen") { nav?.orbitStep(yaw: -15, pitch: 0) }
                        .keyboardShortcut("4", modifiers: [])
                    Button("Nach rechts drehen") { nav?.orbitStep(yaw: 15, pitch: 0) }
                        .keyboardShortcut("6", modifiers: [])
                    Button("Nach oben drehen") { nav?.orbitStep(yaw: 0, pitch: -15) }
                        .keyboardShortcut("8", modifiers: [])
                    Button("Nach unten drehen") { nav?.orbitStep(yaw: 0, pitch: 15) }
                        .keyboardShortcut("2", modifiers: [])
                    Divider()
                    Button("Nach links schwenken") { nav?.panStep(x: -0.1, y: 0) }
                        .keyboardShortcut("4", modifiers: .control)
                    Button("Nach rechts schwenken") { nav?.panStep(x: 0.1, y: 0) }
                        .keyboardShortcut("6", modifiers: .control)
                    Button("Nach oben schwenken") { nav?.panStep(x: 0, y: 0.1) }
                        .keyboardShortcut("8", modifiers: .control)
                    Button("Nach unten schwenken") { nav?.panStep(x: 0, y: -0.1) }
                        .keyboardShortcut("2", modifiers: .control)
                    Divider()
                    Button("Heranzoomen") { nav?.zoomStep(1) }
                        .keyboardShortcut("+", modifiers: [])
                    Button("Herauszoomen") { nav?.zoomStep(-1) }
                        .keyboardShortcut("-", modifiers: [])
                    Divider()
                    Button("Auswahl zentrieren (Punkt)") { viewSelected() }
                        .keyboardShortcut(".", modifiers: [])
                    Button("Auswahl zentrieren (F)") { viewSelected() }
                        .keyboardShortcut("f", modifiers: [])
                    Button("Alles zeigen (Umschalt-C)") { viewAll() }
                        .keyboardShortcut("c", modifiers: .shift)
                }
                Divider()
                Button(hasSelection ? "Auswahl zentrieren" : "Alles zentrieren") { viewSelected() }
                    .keyboardShortcut(",", modifiers: [])
                Button("Alles zeigen") { viewAll() }
                    .keyboardShortcut(.home, modifiers: [])
                Divider()
                Button("Alles auswählen") { nav?.selectAll() }
                    .keyboardShortcut("a", modifiers: [])
                Button("Auswahl aufheben") { model.clearSelection() }
                    .keyboardShortcut("a", modifiers: .option)
                    .disabled(!inProject || !hasSelection)
                Button("Auswahl umkehren") { nav?.invertSelection() }
                    .keyboardShortcut("i", modifiers: .control)
                Toggle("Flächen und Kanten auswählen", isOn: Binding(
                    get: { model.selectionMode == .elements },
                    set: { nav?.setSelectionMode($0 ? .elements : .parts) }
                ))
                .keyboardShortcut(.tab, modifiers: [])
                Button("Abbrechen") {
                    if model.measureMode { model.actions?.setMeasureMode(false) } else { model.clearSelection() }
                }
                .keyboardShortcut(.escape, modifiers: [])
                Divider()
                Button("Ausblenden") { model.hideSelection() }
                    .keyboardShortcut("h", modifiers: [])
                    .disabled(!inProject || !hasSelection)
                Button("Andere ausblenden") { nav?.hideUnselected() }
                    .keyboardShortcut("h", modifiers: .shift)
                    .disabled(!inProject || !hasSelection)
                Button("Alles einblenden") { model.actions?.showAll() }
                    .keyboardShortcut("h", modifiers: .option)
                Button("Lokale Ansicht") { nav?.toggleLocalView() }
                    .keyboardShortcut("/", modifiers: [])
                Divider()
                Picker("Darstellung", selection: Binding(
                    get: { model.displayStyle }, set: { model.actions?.setDisplayStyle($0) }
                )) {
                    ForEach(DisplayStyle.allCases, id: \.self) { style in Text(style.title).tag(style) }
                }
                Toggle("Messen", isOn: Binding(get: { model.measureMode }, set: { model.actions?.setMeasureMode($0) }))
                    .keyboardShortcut("m", modifiers: [])
                Toggle("Schnitt", isOn: Binding(
                    get: { model.sectionEnabled }, set: { _ in window?.toggleSection(model) }
                ))
                .keyboardShortcut("s", modifiers: [])
                Toggle("Explosion", isOn: Binding(
                    get: { model.explodeFactor > 0 }, set: { _ in window?.toggleExplode(model) }
                ))
                .keyboardShortcut("e", modifiers: [])
            }
            .disabled(!inProject)
            Divider()
        }

        // Modell
        CommandMenu("Modell") {
            Button("Neu rechnen") { model.actions?.runModel() }
                .keyboardShortcut("r")
                .disabled(!hasProject)
            Toggle("Auto-Lauf beim Speichern", isOn: Binding(
                get: { model.autoRun }, set: { model.actions?.setAutoRun($0) }
            ))
            .disabled(!hasProject)
            Toggle("Zeitlupe", isOn: Binding(get: { model.slowMotion }, set: { model.actions?.setSlowMotion($0) }))
                .disabled(!hasProject)
            Divider()
            Button("Kernel neu starten") { model.actions?.restartKernel() }
                .keyboardShortcut("k", modifiers: [.command, .option])
        }

        // Hilfe
        CommandGroup(replacing: .help) {
            Button("Befehl für Claude Code kopieren") { session.copyClaudeCommand() }
            Button("Protokoll zeigen") { session.showLog() }
        }
    }
}

/// Zusatzmenü im Demomodus: Zustände von Hand auslösen.
struct DemoCommands: Commands {
    @ObservedObject var session: AppSession

    var body: some Commands {
        if let demo = session.demo {
            CommandMenu("Demo") {
                Button("Lauf starten") { demo.runModel() }
                Button("Fehler im Lauf auslösen") { demo.triggerError() }
                    .keyboardShortcut("f", modifiers: [.command, .option, .control])
                Button("Agent verbinden oder trennen") { demo.toggleAgent() }
                Button("Kernel-Absturz simulieren") { demo.simulateKernelCrash() }
                Divider()
                Button("Projekt schließen (zum Willkommensfenster)") { demo.closeProject() }
            }
        }
    }
}
