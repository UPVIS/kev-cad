import KevCADCore
import SwiftUI

// Abschnitt „Druckteile“ im Bereich „Material“: dünne Hülle um die Druckvorschau (app/Sources/KevCAD/Druck/,
// DRUCKVORSCHAU.md). Vertrag mit dem Material-Strang: `struct DruckAbschnitt: View { init(model: AppModel) }`, volle
// Fläche ohne Rand. Kopf wie die übrigen Abschnitte, darunter `DruckAnsicht` ohne eigenen Titel.

struct DruckAbschnitt: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var druck: DruckStore

    init(model: AppModel) {
        self.model = model
        _druck = ObservedObject(wrappedValue: model.druck)
    }

    var body: some View {
        VStack(spacing: 0) {
            MaterialAbschnittKopf(titel: MaterialAbschnitt.druck.titel, symbol: MaterialAbschnitt.druck.symbol,
                                  zeile: kennzeile) {
                EmptyView()
            }
            Divider()
            DruckAnsicht(model: model, eingebettet: true)
        }
    }

    /// „15 Teile in 5 Gruppen · Bambu Lab P1P 0.4 · Textured PEI Plate“; ohne Vorschau die Zahlen der Stückliste.
    private var kennzeile: String {
        if let v = druck.vorschau, !v.istLeer {
            return [KevFormat.count(v.stueck, one: "Teil", many: "Teile") + " in "
                        + KevFormat.count(v.teile.count, one: "Gruppe", many: "Gruppen"),
                    v.drucker, v.projekt?.platte].compactMap { $0 }.joined(separator: " · ")
        }
        let k = model.materialDaten.kennzahlen
        guard k.druckteile > 0 else { return "3D-Druckteile aus druckbarem Material" }
        return [KevFormat.count(k.druckteile, one: "Teil", many: "Teile"), KevFormat.mass(grams: k.druckGramm) + " Filament",
                k.druckPreis.map { "≈ " + KevFormat.euro($0) }].compactMap { $0 }.joined(separator: " · ")
    }
}
