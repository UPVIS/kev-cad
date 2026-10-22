import KevCADCore
import SwiftUI

/// Berichte im Bereich Dokumente. Platzhalter von P6-A1; Stückliste, Zuschnitt, Einkauf und Druckteile als Tabellen
/// baut P6-A2 hier hinein.
struct BerichteBereich: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        ContentUnavailableView {
            Label("Berichte", systemImage: "tablecells")
        } description: {
            Text("Stückliste, Teileliste, Einkaufsliste, Zuschnitt, Druckteile, Gewicht und Kosten.")
        }
    }
}
