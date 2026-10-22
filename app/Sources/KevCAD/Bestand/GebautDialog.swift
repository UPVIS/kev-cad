import KevCADCore
import SwiftUI

/// Dialog „Gebaut …“: Vorschau der Buchung (was aus dem Bestand weg geht, welche Reste neu entstehen) und Bestätigung.
/// Gebucht wird erst mit „Gebaut buchen“ (GEBAUT_REQ); danach erscheint ein Hinweis mit „Rückgängig“.
struct GebautDialog: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    private var vorschau: GebautVorschau? {
        guard let z = model.bestandZustand.zuschnitt else { return nil }
        return GebautVorschau.berechnen(
            zuschnitt: z, bestand: model.bestandZustand.bestand, lines: model.bom?.lines ?? [],
            name: { model.catalog?.item($0)?.name }, filament: model.bestandZustand.gebautFilamentAktuell)
    }

    /// Das Projekt führt Filament, die Rechnung des Kernels gehört aber noch nicht zur aktuellen Stückliste.
    private var filamentWartet: Bool {
        model.bestandZustand.bestand?.fuehrtFilament == true && model.bestandZustand.gebautFilamentAktuell == nil
    }

    private var sperre: String? {
        if model.bestandActions == nil { return "Buchen geht nur mit verbundenem Kernel." }
        if model.laufAktiv { return "Das Modell wird gerade neu gerechnet. Warte auf die neue Stückliste." }
        if model.bestandZustand.zuschnitt == nil { return "Der Kernel schickt noch keinen Zuschnitt mit Bestand." }
        if !model.bestandZustand.hatBuchbares && (vorschau?.leer ?? true) {
            return "Der Zuschnitt verplant nichts aus dem Bestand und es ist kein Filament abzubuchen."
        }
        return nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            kopf
                .padding(20)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let v = vorschau {
                        abschnitt("Wird aus dem Bestand abgebucht", symbol: "minus.circle.fill", farbe: .red, zeilen: v.weg,
                                  leer: "Nichts aus dem Bestand verplant.")
                        // Filament: welche Platte jetzt abgebucht wird, welche schon als gedruckt gebucht ist
                        if !v.platten.isEmpty {
                            plattenAbschnitt(v.platten)
                        }
                        abschnitt("Kommt neu in den Bestand", symbol: "plus.circle.fill", farbe: ZuschnittFarbe.restNeu.color,
                                  zeilen: v.neu, leer: "Es entstehen keine Reste ab Mindestrest.")
                        if !v.kaufen.isEmpty {
                            abschnitt("Vorausgesetzt gekauft", symbol: "cart.fill", farbe: ZuschnittFarbe.kaufen.color,
                                      zeilen: v.kaufen, leer: "")
                        }
                        if !v.verschnitt.isEmpty {
                            abschnitt("Verschnitt", symbol: "trash.circle.fill", farbe: ZuschnittFarbe.verschnitt.color,
                                      zeilen: v.verschnitt, leer: "")
                        }
                        if let h = v.filamentHinweis {
                            Label(h, systemImage: "info.circle").foregroundStyle(.secondary)
                        } else if filamentWartet {
                            Label("Filament: Die Druckvorschau zu dieser Stückliste wird noch gerechnet; gebucht wird "
                                  + "trotzdem, was der Kernel beim Buchen findet.", systemImage: "hourglass")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(20)
            }
            .frame(minHeight: 180, idealHeight: 320, maxHeight: 440)
            Divider()
            fuss
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
        }
        .frame(width: 540)
    }

    private var kopf: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "hammer.circle.fill")
                .font(.system(size: 34))
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text("„\(model.project?.name ?? "Projekt")“ als gebaut buchen?")
                    .font(.title3.weight(.semibold))
                Text("Kev CAD bucht ab, was der Zuschnitt aus dem Bestand dieses Projekts verplant, und legt die neuen "
                    + "Reste mit Kennung an."
                    + (model.bestandZustand.bestand?.fuehrtFilament == true
                        ? " Das Filament der noch nicht gedruckt gebuchten Platten geht von den Spulen ab." : "")
                    + (model.bom.map { " Stand: Stückliste von Lauf \($0.run)." } ?? ""))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func abschnitt(
        _ titel: String, symbol: String, farbe: Color, zeilen: [GebautVorschau.Zeile], leer: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label {
                Text(titel).fontWeight(.semibold)
            } icon: {
                Image(systemName: symbol).foregroundStyle(farbe)
            }
            if zeilen.isEmpty {
                Text(leer).foregroundStyle(.secondary).padding(.leading, 26)
            }
            ForEach(zeilen) { z in
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(z.text).monospacedDigit()
                        Text(z.teil).foregroundStyle(.secondary).lineLimit(1)
                    }
                    if let h = z.hinweis {
                        Text(h).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.leading, 26)
            }
        }
    }

    /// Druckplatten: welche jetzt abgebucht wird und welche schon als gedruckt gebucht ist (Filament nicht doppelt).
    private func plattenAbschnitt(_ zeilen: [GebautVorschau.Zeile]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label {
                Text("Druckplatten").fontWeight(.semibold)
            } icon: {
                Image(systemName: "printer.fill").foregroundStyle(MaterialKennzeichen.druckteil.color)
            }
            ForEach(zeilen) { z in
                HStack(spacing: 6) {
                    Image(systemName: z.gebucht ? "checkmark.circle.fill" : "circle.dashed")
                        .foregroundStyle(z.gebucht ? Color.green : Color.secondary)
                    Text(z.text).monospacedDigit()
                    Text(z.teil).foregroundStyle(.secondary).monospacedDigit().lineLimit(1)
                    if let h = z.hinweis {
                        Text("· \(h)").font(.caption).foregroundStyle(z.gebucht ? Color.green : Color.secondary)
                    }
                }
                .padding(.leading, 26)
                .help(z.gebucht ? "Das Filament dieser Platte ist schon gebucht und wird nicht noch einmal abgezogen"
                    : "Das Filament dieser Platte wird mit „Gebaut“ abgebucht")
            }
        }
    }

    private var fuss: some View {
        HStack(spacing: 10) {
            if let s = sperre {
                Label(s, systemImage: "info.circle")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text("Lässt sich danach rückgängig machen.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Button("Abbrechen", role: .cancel) { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button("Gebaut buchen") {
                model.bestandActions?.bucheGebaut()
                dismiss()
            }
            .keyboardShortcut(.defaultAction)
            .disabled(sperre != nil)
        }
    }
}
