import KevCADCore
import SwiftUI

/// Berichte im Bereich Dokumente (Seitenleiste „Fertigung“): Stückliste, Teileliste, Einkaufsliste und Zuschnitt als
/// druckfertige Seiten (BerichteAnsicht, Strang P6-A2). Der Name ist die Schnittstelle zum Bereich Dokumente von P6-A1.
struct BerichteBereich: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        BerichteAnsicht(model: model)
    }
}
