import KevCADCore
import SwiftUI

/// Menü „Dokumente“ und Drucken: Bereich wechseln (⌘1 3D-Modell, ⌘2 Dokumente), Zoom (⌘9 einpassen, ⌘0 1:1, ⌘+ ⌘−),
/// Werkzeuge (V, D, N, nur im Bereich Dokumente), Als PDF sichern (⌥⌘P), Drucken (⌘P).
struct DokumenteCommands: Commands {
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?
    @FocusedObject private var zustand: DokumenteZustand?

    private var imBereich: Bool { window?.bereich == .dokumente && model.project != nil }
    private var mitBlatt: Bool { imBereich && zustand?.blattID != nil }

    var body: some Commands {
        CommandMenu("Dokumente") {
            Button("3D-Modell") { setze(.modell) }
                .keyboardShortcut("1", modifiers: .command)
                .disabled(window == nil || model.project == nil)
            Button("Dokumente") { setze(.dokumente) }
                .keyboardShortcut("2", modifiers: .command)
                .disabled(window == nil || model.project == nil)
            Divider()
            Group {
                Button("Blatt einpassen") { zustand?.ausfuehren(.einpassen) }
                    .keyboardShortcut("9", modifiers: .command)
                Button("Originalgröße (1:1 auf dem Bildschirm)") { zustand?.ausfuehren(.originalgroesse) }
                    .keyboardShortcut("0", modifiers: .command)
                Button("Vergrößern") { zustand?.ausfuehren(.vergroessern) }
                    .keyboardShortcut("+", modifiers: .command)
                Button("Verkleinern") { zustand?.ausfuehren(.verkleinern) }
                    .keyboardShortcut("-", modifiers: .command)
                Divider()
                Button("Auswählen") { zustand?.setzeWerkzeug(.auswahl) }
                    .keyboardShortcut("v", modifiers: [])
                Button("Maß hinzufügen") { zustand?.setzeWerkzeug(.mass) }
                    .keyboardShortcut("d", modifiers: [])
                Button("Notiz hinzufügen") { zustand?.setzeWerkzeug(.notiz) }
                    .keyboardShortcut("n", modifiers: [])
                Menu("Ansicht hinzufügen") {
                    ForEach(["vorn", "oben", "links", "rechts", "hinten", "unten", "iso"], id: \.self) { art in
                        Button(ZeichnungText.ansichtArt(art)) { zustand?.setzeWerkzeug(.ansicht(art)) }
                    }
                }
            }
            .disabled(!mitBlatt)
            Divider()
            Button("Zeichnungen erzeugen") {
                model.dokumenteActions?.zeichnungenErzeugen(teile: nil, art: "teil", format: nil)
            }
            .disabled(!imBereich || model.parts.isEmpty || model.dokumente.erzeugt)
            Button("Blätter neu rechnen") { model.dokumenteActions?.dokumenteAnfordern() }
                .disabled(!imBereich)
            Divider()
            Button("Als PDF sichern …") { zustand?.pdfSichern?() }
                .keyboardShortcut("p", modifiers: [.command, .option])
                .disabled(!mitBlatt)
        }
        CommandGroup(replacing: .printItem) {
            Button("Drucken …") { zustand?.drucken?() }
                .keyboardShortcut("p", modifiers: .command)
                .disabled(!mitBlatt)
        }
    }

    private func setze(_ b: ProjektBereich) {
        withAnimation(.snappy(duration: 0.2)) { window?.bereich = b }
    }
}
