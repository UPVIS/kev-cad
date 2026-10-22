import KevCADCore
import SwiftUI

/// Inspektor im Bereich Dokumente, solange die Berichte vorne sind: Einstellungen des gewählten Berichts (Papier,
/// Spalten in der Reihenfolge des Berichts). Sie gelten für die Vorschau, „Drucken“ und „Als PDF sichern“; die
/// Vorlagen des Export-Dialogs haben ihre eigenen Spalten.
struct BerichteInspektor: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var ui = BerichteUI.shared

    var body: some View {
        let art = ui.bericht
        let wirksam = Set(ui.wahl.wirksameSpalten.map(\.id))
        Form {
            Section {
                HStack(spacing: 10) {
                    Image(systemName: art.symbol)
                        .font(.title2)
                        .foregroundStyle(Color.kevAkzent)
                        .frame(width: 30)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(art.titel).font(.headline)
                        Text(art.beschreibung).font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if let n = ui.seiten {
                    LabeledContent("Seiten") { Text("\(n)").monospacedDigit() }
                }
            }
            Section("Papier") {
                Picker("Format", selection: $ui.format.papier) {
                    ForEach(ExportPapier.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                Picker("Ausrichtung", selection: $ui.format.ausrichtung) {
                    Text(ExportAusrichtung.hoch.titel).tag(ExportAusrichtung.hoch)
                    Text(ExportAusrichtung.quer.titel).tag(ExportAusrichtung.quer)
                }
            }
            if !art.spalten.isEmpty {
                Section {
                    ForEach(art.spalten) { s in
                        Toggle(isOn: Binding(get: { wirksam.contains(s.id) }, set: { ui.setze(s.id, an: $0) })) {
                            HStack {
                                Text(spaltenName(s))
                                if s.standard {
                                    Spacer()
                                    Text("Vorgabe").font(.caption).foregroundStyle(.tertiary)
                                }
                            }
                        }
                        .disabled(wirksam == [s.id])
                    }
                } header: {
                    HStack {
                        Text("Spalten")
                        Spacer()
                        Button("Vorgabe") { ui.spalten[art.rawValue] = nil }
                            .buttonStyle(.borderless)
                            .controlSize(.small)
                            .disabled(ui.spalten[art.rawValue] == nil)
                    }
                } footer: {
                    Text("Gilt für Vorschau, Drucken und „Als PDF sichern“. Im Export-Dialog hat jede Vorlage ihre "
                         + "eigenen Spalten.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
    }

    private func spaltenName(_ s: ExportSpalte) -> String {
        switch s.id {
        case "abhaken": return "Kästchen zum Abhaken"
        case "pos": return "Position"
        case "nr": return "Nummer"
        case "anzahl": return "Anzahl"
        default: return s.titel.isEmpty ? s.id : s.titel
        }
    }
}
