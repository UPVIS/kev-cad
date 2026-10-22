import KevCADCore
import SwiftUI

/// Bauplan im Bereich Dokumente. Platzhalter von P6-A1; die Ansicht mit Schritten, Strichbildern und Durchspielen baut
/// P6-A2 hier hinein.
struct BauplanBereich: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        ContentUnavailableView {
            Label("Bauplan", systemImage: "hammer")
        } description: {
            Text("Schritt für Schritt: Material, Zuschnitt, Bearbeiten, Drucken, Montage.")
        }
    }
}
