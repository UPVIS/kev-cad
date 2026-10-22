import KevCADCore
import SwiftUI

// Platzhalter für die Druck-Schnellansicht (PLAN-DRUCKVORSCHAU.md), die ein anderer Strang baut: Er ersetzt nur diese
// Datei und DruckAbschnitt.swift. Vertrag: `struct DruckSchnellansicht: View { init(model: AppModel) }`.
//
// So hängt sie unter dem Viewport: Die Schnellansicht „Druck“ erscheint, sobald das Modell Druckteile hat. Ihre
// Kopfzeile (Titel, Kennzahlen „6 Teile · 120 g“, Pfeil, „In Material öffnen“) zeichnet der Behälter; diese Ansicht
// füllt nur den Inhalt darunter, in voller Breite und in der Höhe, die Kevin zieht (mindestens 72 Punkte).

/// Inhalt der Schnellansicht „Druck“. Heute ein ruhiger leerer Zustand.
struct DruckSchnellansicht: View {
    @ObservedObject var model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "printer.dotmatrix")
                .font(.title3)
                .foregroundStyle(.tertiary)
            VStack(alignment: .leading, spacing: 2) {
                Text("Druckvorschau folgt").font(.callout.weight(.medium)).foregroundStyle(.secondary)
                Text("Filament, Druckzeit und Platten je Lauf erscheinen hier.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
