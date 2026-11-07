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
/// - Darstellung (oben): Objekte links ⌘1, Eigenschaften rechts ⌘2, Kacheln nebeneinander bzw. nur das Modell ⌘3
///   (V2-9 statt Fokus und Werkstatt), schmal an den rechten bzw. linken Rand ⌃⌥→ / ⌃⌥←, letzte Projekte ⇧⌘O.
/// - Kacheln: Kachel zeigen (⌃⌘1 bis ⌃⌘0), Kachel 1 bis 4 groß (⌥⌘1 bis ⌥⌘4), alle einordnen, aktive schließen ⇧⌘W.
/// - Agent: Sprechen V (nicht in Textfeldern, nicht im Zeichnungsblatt; dort ist V das Auswahlwerkzeug), Fertig, Verwerfen.
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
    private var imBlatt: Bool { window?.bereich == .dokumente && oberflaeche.aktiv != .bauplan }

    private var sprechTitel: String {
        if oberflaeche.spricht { return "Sprechen anhalten" }
        return oberflaeche.sitzungOffen ? "Weitersprechen" : "Sprechen"
    }

    /// Die ersten zehn haben ⌃⌘1 bis ⌃⌘0.
    static let kachelReihe: [KachelArt] = [
        .stueckliste, .zuschnitt, .zeichnung, .ansicht, .material, .simulation, .versionen, .details, .druck, .animation,
        .bauplan, .render,
    ]

    var body: some Commands {
        CommandGroup(before: .sidebar) {
            Button(oberflaeche.leisteLinks ? "Objekte ausblenden" : "Objekte einblenden") {
                a?.setzeLeisteLinks(!oberflaeche.leisteLinks)
            }
            .keyboardShortcut("1", modifiers: .command)
            .disabled(!vorne)
            Button(oberflaeche.leisteRechts ? "Eigenschaften ausblenden" : "Eigenschaften einblenden") {
                a?.setzeLeisteRechts(!oberflaeche.leisteRechts)
            }
            .keyboardShortcut("2", modifiers: .command)
            .disabled(!vorne)
            Button(oberflaeche.kachelflaeche ? "Nur das Modell" : "Kacheln nebeneinander") {
                a?.vergroessereKachel(oberflaeche.kachelflaeche ? .modell : nil)
            }
            .keyboardShortcut("3", modifiers: .command)
            .disabled(!vorne || !oberflaeche.kacheln.contains { $0 != .modell })
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
                    .keyboardShortcut(i < 10 ? KeyboardShortcut(KeyEquivalent(Character(String((i + 1) % 10))),
                                                                modifiers: [.command, .control]) : nil)
                    .disabled(!vorne || model.project == nil)
            }
            Button("Modell") { a?.zeigeKachel(.modell) }
                .disabled(!vorne)
            Divider()
            Button(oberflaeche.zeitleiste ? "Zeitleiste im Viewer ausblenden" : "Zeitleiste im Viewer zeigen") {
                a?.oberflaeche(.zeitleiste(!oberflaeche.zeitleiste))
            }
            .keyboardShortcut("t", modifiers: [.command, .control])
            .disabled(!vorne || !model.animation.hasAnimation)
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
            .disabled(oberflaeche.aktiv == nil || !oberflaeche.kachelflaeche)
        }

        CommandMenu("Agent") {
            Button(sprechTitel) { a?.setzeSprechen(!oberflaeche.spricht) }
                .keyboardShortcut(imBlatt ? nil : KeyboardShortcut("v", modifiers: []))
                .disabled(!vorne || imBlatt)
            // ↩ und esc wirken im Fenster (SprachSteuerung, Abbrechen): als Menükürzel nähme ↩ Dialogen ihren Standardknopf
            Button("Fertig, an den Agenten schicken") { a?.sprechenFertig() }
                .disabled(!oberflaeche.sitzungOffen)
            Button("Sitzung verwerfen") { a?.sprechenVerwerfen() }
                .disabled(!oberflaeche.sitzungOffen)
            Divider()
            Button("Befehl für Claude Code kopieren") { session.copyClaudeCommand() }
        }
    }
}
