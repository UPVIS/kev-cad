import KevCADCore
import SwiftUI

// Platzhalter für die Druckvorschau (PLAN-DRUCKVORSCHAU.md), die ein anderer Strang baut: Er ersetzt nur diese Datei
// und DruckSchnellansicht.swift. Vertrag: `struct DruckAbschnitt: View { init(model: AppModel) }`. Der Bereich
// „Material“ zeigt die Ansicht im Abschnitt „Druckteile“ ohne eigenen Kopf und ohne Rand (volle Fläche).

/// Abschnitt „Druckteile“ im Bereich „Material“. Heute: die Druckteile aus der Stückliste und ein leerer Zustand
/// „Druckvorschau folgt“.
struct DruckAbschnitt: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        let daten = model.materialDaten
        let druck = daten.positionen(in: .druckteile)
        let k = daten.kennzahlen
        VStack(spacing: 0) {
            MaterialAbschnittKopf(
                titel: MaterialAbschnitt.druck.titel, symbol: MaterialAbschnitt.druck.symbol,
                zeile: druck.isEmpty ? "3D-Druckteile aus druckbarem Material"
                    : [KevFormat.count(druck.count, one: "Position", many: "Positionen"),
                       KevFormat.count(k.druckteile, one: "Teil", many: "Teile"),
                       KevFormat.mass(grams: k.druckGramm) + " Filament",
                       k.druckPreis.map { "≈ " + KevFormat.euro($0) } ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
            ) {
                EmptyView()
            }
            Divider()
            if druck.isEmpty {
                MaterialLeer(titel: "Keine Druckteile", symbol: "printer",
                             text: "Das Modell enthält keine 3D-Druckteile (lager.druckteil(…)).")
            } else {
                Table(druck) {
                    TableColumn(MaterialText.Spalte.pos) { p in
                        Text("\(p.pos)").monospacedDigit().foregroundStyle(.secondary)
                    }
                    .width(40)
                    TableColumn(MaterialText.Spalte.benennung) { p in BenennungZelle(position: p) }
                        .width(min: 180, ideal: 280)
                    TableColumn(MaterialText.Spalte.werkstoff) { p in Text(p.werkstoff ?? "–") }
                        .width(min: 70, ideal: 110)
                    TableColumn(MaterialText.Spalte.anzahl) { p in ZahlZelle(text: KevFormat.integer(p.anzahl), hervor: true) }
                        .width(min: 46, ideal: 56)
                    TableColumn("Filament") { p in ZahlZelle(text: p.kg.map(KevFormat.kg) ?? "–") }
                        .width(min: 64, ideal: 80)
                    TableColumn(MaterialText.Spalte.preis) { p in ZahlZelle(text: p.preis.map(KevFormat.euro) ?? "–") }
                        .width(min: 64, ideal: 80)
                }
                .tableStyle(.inset)
                .alternatingRowBackgrounds()
                .frame(minHeight: 120, idealHeight: CGFloat(druck.count) * 34 + 40, maxHeight: 320)
                Divider()
                ContentUnavailableView {
                    Label("Druckvorschau folgt", systemImage: "printer.dotmatrix")
                } description: {
                    Text("Hier erscheinen bald Filament je Sorte, Druckzeit, Platten mit Anordnung und Empfehlungen je Teil, "
                        + "nach jedem Lauf von selbst gerechnet.")
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}
