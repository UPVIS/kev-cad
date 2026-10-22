import KevCADCore
import SwiftUI

// Schnellansicht „Druck“ unter dem Viewport: dünne Hülle um die Druckvorschau (app/Sources/KevCAD/Druck/,
// DRUCKVORSCHAU.md). Vertrag mit dem Material-Strang: `struct DruckSchnellansicht: View { init(model: AppModel) }`.
// Die Kopfzeile (Titel, Gramm, Kosten, Zeit, Platten, „In Material öffnen“) zeichnet der Behälter; hier der Inhalt in
// voller Breite: das Band der Druckvorschau und, wenn Kevin die Ansicht höher zieht, die Platten als kleine Draufsichten.

struct DruckSchnellansicht: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                DruckKompakt(model: model)
                    .frame(height: 32)
                if geo.size.height >= 110 {
                    Divider()
                    DruckPlattenStreifen(model: model)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .top)
        }
    }
}
