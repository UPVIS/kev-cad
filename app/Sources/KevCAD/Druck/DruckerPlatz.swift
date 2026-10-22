import KevCADCore
import SwiftUI

/// Platz für die Druckerleiste von Phase 8 oben in `DruckAnsicht`, eine Zeile in voller Breite: Zustand des P1P (nur
/// lesend bei Weg A), Fortschritt und „Drucken …“ (fertig slicen und in Bambu Studio öffnen). Der Knopf „Platten als
/// 3MF …“ der Druckvorschau bleibt der Weg ohne Slicen.
struct DruckerPlatz: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        DruckerLeiste(model: model)
    }
}
