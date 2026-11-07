import KevCADCore
import SwiftUI

/// Untermenü „Bauplan“ im Menü „Modell“: Durchspielen (⌥⌘← ⌥⌘→ ⌥⌘.) und der Sprung zu Bauplan und Berichten.
struct BauplanMenue: View {
    @ObservedObject var model: AppModel
    @ObservedObject var bauplan: BauplanStore
    @FocusedObject private var window: ProjectWindowState?

    var body: some View {
        Group {
            Button("Bauplan zeigen") { zeige(.bauplan) }
                .disabled(window == nil || model.project == nil)
            Button("Berichte zeigen") { zeige(.berichte) }
                .disabled(window == nil || model.project == nil)
            Divider()
            Button(bauplan.durchspielen == nil ? "Durchspielen" : "Durchspielen neu beginnen") {
                model.bauplanActions?.durchspielenStarten(ab: nil)
            }
            .disabled(model.project == nil || model.bauplanActions == nil)
            Group {
                Button(bauplan.durchspielen?.spielt == true ? "Anhalten" : "Abspielen") {
                    model.bauplanActions?.durchspielenAbspielen(!(bauplan.durchspielen?.spielt ?? false))
                }
                Button("Nächster Schritt") { model.bauplanActions?.durchspielenSchritt(1) }
                    .keyboardShortcut(.rightArrow, modifiers: [.command, .option])
                Button("Voriger Schritt") { model.bauplanActions?.durchspielenSchritt(-1) }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                Button("Durchspielen beenden") { model.bauplanActions?.durchspielenBeenden() }
                    .keyboardShortcut(".", modifiers: [.command, .option])
            }
            .disabled(bauplan.durchspielen == nil)
        }
    }

    private func zeige(_ a: DokumentAuswahl) {
        if a == .bauplan {  // eigene Kachel
            model.oberflaechenActions?.zeigeKachel(.bauplan)
            return
        }
        withAnimation(.snappy(duration: 0.2)) { window?.bereich = .dokumente }
        window?.dokumenteZustand?.waehle(a)
    }
}
