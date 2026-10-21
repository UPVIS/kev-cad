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
                ForEach(StandardViewName.menuOrder, id: \.self) { view in
                    Button(view.title) { model.actions?.setStandardView(view) }
                        .keyboardShortcut(view.key, modifiers: [])
                }
                Menu("Weitere Isometrien") {
                    ForEach(StandardViewName.extraIsoOrder, id: \.self) { view in
                        Button(view.title) { model.actions?.setStandardView(view) }
                            .keyboardShortcut(view.key, modifiers: [])
                    }
                }
                Divider()
                Button(hasSelection ? "Auswahl einpassen" : "Alles einpassen") { model.fitSelection() }
                    .keyboardShortcut("f", modifiers: [])
                Button("Auswahl aufheben") { model.clearSelection() }
                    .keyboardShortcut(.escape, modifiers: [])
                    .disabled(!inProject || !hasSelection)
                Divider()
                Button("Ausblenden") { model.hideSelection() }
                    .keyboardShortcut("h", modifiers: [])
                    .disabled(!inProject || !hasSelection)
                Button("Isolieren") { model.isolateSelection() }
                    .keyboardShortcut("i", modifiers: [])
                    .disabled(!inProject || !hasSelection)
                Button("Alles einblenden") { model.actions?.showAll() }
                    .keyboardShortcut("h", modifiers: [.shift])
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
