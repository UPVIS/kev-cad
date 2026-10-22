import KevCADCore
import SwiftUI

/// Bauplan im Bereich Dokumente (Seitenleiste „Fertigung“): Schritte mit Strichbildern, Bearbeiten und Durchspielen
/// (BauplanAnsicht, Strang P6-A2). Der Name ist die Schnittstelle zum Bereich Dokumente von P6-A1.
struct BauplanBereich: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        BauplanAnsicht(model: model)
    }
}
