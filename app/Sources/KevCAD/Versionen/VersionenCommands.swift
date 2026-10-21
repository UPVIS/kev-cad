import KevCADCore
import SwiftUI

/// Menü „Versionen“. Kürzel nach macOS-Art, ohne Konflikt mit den Blender-Tasten (Buchstaben, Ziffern, 0, Leertaste,
/// Pfeile): ⌘S Meilenstein setzen, ⌥⌘V Versionsleiste, ⌥⌘U mit der vorherigen Version vergleichen (Unterschiede),
/// ⇧⌘U Vergleich beenden, ⌥⌘Z vorherige Version wiederherstellen.
struct VersionenCommands: Commands {
    @ObservedObject var model: AppModel
    @ObservedObject var store: VersionenStore
    @FocusedObject private var zustand: VersionenZustand?

    private var actions: VersionenActions? { model.versionenActions }
    private var hatVersionen: Bool { !(store.stand?.versionen.isEmpty ?? true) && zustand != nil }

    /// Die Version vor dem aktuellen Stand (für Vergleich und Zurück).
    private var vorherige: VersionEintrag? {
        guard let s = store.stand, let i = s.versionen.firstIndex(where: \.aktuell) else { return nil }
        return s.versionen.dropFirst(i + 1).first
    }

    var body: some Commands {
        CommandMenu("Versionen") {
            Button("Meilenstein setzen …") { zustand?.meilensteinSetzen() }
                .keyboardShortcut("s", modifiers: .command)
                .disabled(!hatVersionen)
            Toggle("Versionsleiste", isOn: Binding(
                get: { zustand?.zeigeLeiste ?? false },
                set: { on in withAnimation(.snappy(duration: 0.2)) { zustand?.zeigeLeiste = on } }))
                .keyboardShortcut("v", modifiers: [.command, .option])
                .disabled(zustand == nil)
            Divider()
            Button(vorherige.map { "Mit V\($0.nr) vergleichen" } ?? "Mit vorheriger Version vergleichen") {
                if let v = vorherige { actions?.compareVersion(v.nr, with: nil) }
            }
            .keyboardShortcut("u", modifiers: [.command, .option])
            .disabled(vorherige == nil || zustand == nil)
            Button("Vergleich beenden") { actions?.endCompare() }
                .keyboardShortcut("u", modifiers: [.command, .shift])
                .disabled(store.vergleich == nil)
            Button("Vergleich: Details …") { zustand?.zeigeVergleichDetail = true }
                .disabled(store.vergleich == nil || zustand == nil)
            Divider()
            Button(vorherige.map { "V\($0.nr) wiederherstellen" } ?? "Vorherige Version wiederherstellen") {
                if let v = vorherige { actions?.restoreVersion(v.nr) }
            }
            .keyboardShortcut("z", modifiers: [.command, .option])
            .disabled(vorherige == nil || zustand == nil)
            Divider()
            Menu("Variante") {
                ForEach(store.stand?.varianten ?? []) { v in
                    Button(v.aktuell ? "✓ \(v.name)" : v.name) {
                        if !v.aktuell { actions?.switchVariant(v.id) }
                    }
                }
                Divider()
                Button("Neue Variante …") { zustand?.varianteAnlegen() }
                    .disabled(!hatVersionen)
            }
            .disabled(!(store.stand?.verfuegbar ?? false) || zustand == nil)
        }
    }
}
