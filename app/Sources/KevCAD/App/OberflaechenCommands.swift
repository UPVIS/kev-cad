import KevCADCore
import SwiftUI

/// Untermenüs des Menüs „Modell“: Was früher je ein eigenes Menü in der Menüleiste war.
struct ModellUntermenues: View {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel

    var body: some View {
        Menu("Versionen") { VersionenMenue(model: model, store: model.versionen) }
        Menu("Animation") { AnimationMenue(model: model, animation: model.animation) }
        Menu("Simulation") { SimulationMenue(model: model) }
        Menu("Material") { MaterialMenue(session: session, model: model) }
        Menu("Dokumente") { DokumenteMenue(model: model) }
        Menu("Bauplan") { BauplanMenue(model: model, bauplan: model.bauplan) }
    }
}

/// Menüs der V2-Oberfläche (OBERFLAECHE.md, Abschnitt 7):
/// - Darstellung (oben): Fokus ⌘1, Werkstatt ⌘2, schmal an den rechten bzw. linken Rand ⌃⌥→ / ⌃⌥←, letzte Projekte
///   ⇧⌘O.
/// - Kacheln: Kachel zeigen (⌃⌘1 bis ⌃⌘8), Kachel 1 bis 4 groß (⌥⌘1 bis ⌥⌘4), alle einordnen, aktive schließen ⇧⌘W.
/// - Agent: Sprechen V (nicht in Textfeldern, nicht im Zeichnungsblatt; dort ist V das Auswahlwerkzeug).
/// Alles ruft `OberflaechenActions`, wie später Sprache und Agent.
struct OberflaechenCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @FocusedObject private var window: ProjectWindowState?

    private var a: OberflaechenActions? { model.oberflaechenActions }
    /// Hauptfenster vorne
    private var vorne: Bool { window != nil }
    /// Im Zeichnungsblatt gehört V dem Auswahlwerkzeug.
    private var imBlatt: Bool { window?.bereich == .dokumente }

    static let kachelReihe: [KachelArt] = [
        .stueckliste, .zuschnitt, .zeichnung, .ansicht, .material, .simulation, .versionen, .details,
    ]

    var body: some Commands {
        CommandGroup(before: .sidebar) {
            Button("Fokus") { a?.setzeModus(.fokus) }
                .keyboardShortcut("1", modifiers: .command)
                .disabled(!vorne)
            Button("Werkstatt") { a?.setzeModus(.werkstatt) }
                .keyboardShortcut("2", modifiers: .command)
                .disabled(!vorne)
            Divider()
            Button(oberflaeche.rand == .rechts ? "Zurück vom rechten Rand" : "Schmal an den rechten Rand") {
                a?.setzeRand(oberflaeche.rand == .rechts ? nil : .rechts)
            }
            .keyboardShortcut(.rightArrow, modifiers: [.control, .option])
            .disabled(!vorne)
            Button(oberflaeche.rand == .links ? "Zurück vom linken Rand" : "Schmal an den linken Rand") {
                a?.setzeRand(oberflaeche.rand == .links ? nil : .links)
            }
            .keyboardShortcut(.leftArrow, modifiers: [.control, .option])
            .disabled(!vorne)
            Divider()
            Button(oberflaeche.uebersicht ? "Letzte Projekte wegschieben" : "Letzte Projekte zeigen") {
                a?.zeigeUebersicht(!oberflaeche.uebersicht)
            }
            .keyboardShortcut("o", modifiers: [.command, .shift])
            Divider()
        }

        CommandMenu("Kacheln") {
            ForEach(Array(Self.kachelReihe.enumerated()), id: \.element) { i, art in
                Button(art.titel) { a?.zeigeKachel(art) }
                    .keyboardShortcut(KeyEquivalent(Character(String(i + 1))), modifiers: [.command, .control])
                    .disabled(!vorne || model.project == nil)
            }
            Button("Modell") { a?.zeigeKachel(.modell) }
                .disabled(!vorne)
            Divider()
            ForEach(1...4, id: \.self) { n in
                let art = n <= oberflaeche.kacheln.count ? oberflaeche.kacheln[n - 1] : nil
                Button(art.map { oberflaeche.gross == $0 ? "Kachel \(n) einordnen" : "Kachel \(n) groß (\($0.titel))" }
                       ?? "Kachel \(n) groß") {
                    if let art { a?.vergroessereKachel(oberflaeche.gross == art ? nil : art) }
                }
                .keyboardShortcut(KeyEquivalent(Character(String(n))), modifiers: [.command, .option])
                .disabled(art == nil || !vorne)
            }
            Button("Alle einordnen") { a?.vergroessereKachel(nil) }
                .disabled(oberflaeche.gross == nil)
            Divider()
            Button("Aktive Kachel schließen") {
                if let aktiv = oberflaeche.aktiv { a?.schliesseKachel(aktiv) }
            }
            .keyboardShortcut("w", modifiers: [.command, .shift])
            .disabled(oberflaeche.aktiv == nil || oberflaeche.modus != .werkstatt)
        }

        CommandMenu("Agent") {
            Button(oberflaeche.spricht ? "Sprechen beenden" : "Sprechen") { a?.setzeSprechen(!oberflaeche.spricht) }
                .keyboardShortcut(imBlatt ? nil : KeyboardShortcut("v", modifiers: []))
                .disabled(!vorne || imBlatt)
            Divider()
            Button("Befehl für Claude Code kopieren") { session.copyClaudeCommand() }
        }
    }
}
