import KevCADCore
import SwiftUI

extension AppModel {
    var pruefActions: PruefActions? { actions as? PruefActions }
}

/// Band über dem Viewport, solange die Prüfung offene Befunde hat („2 Durchdringungen“), mit aufklappbarer Liste.
/// Klick auf einen Befund wählt die Teile aus und fährt auf den Ort; die roten Schnittkörper lassen sich ausblenden.
struct PruefBanner: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    var dismiss: () -> Void

    var body: some View {
        let p = model.pruefung
        let befunde = (p?.befunde ?? []).filter { $0.schwere != .hinweis }
        let fehler = befunde.contains { $0.schwere == .fehler }
        let farbe: Color = fehler ? .red : .orange
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.title3)
                    .foregroundStyle(farbe)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Prüfung: " + (p?.bandText ?? ""))
                        .font(.headline)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Text(untertitel(fehler: fehler, laeuft: p?.laeuft ?? false))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                if !(p?.geometrie.isEmpty ?? true) {
                    Toggle("Schnittkörper", isOn: Binding(
                        get: { model.schnittkoerperSichtbar },
                        set: { model.pruefActions?.setSchnittkoerperSichtbar($0) }))
                        .toggleStyle(.checkbox)
                        .help("Rote Schnittvolumen im Viewer zeigen")
                }
                Button(state.pruefListeOffen ? "Liste ausblenden" : "Befunde (\(befunde.count))") {
                    withAnimation(.snappy(duration: 0.2)) { state.pruefListeOffen.toggle() }
                }
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Band ausblenden, bis sich die Befunde ändern")
            }
            if state.pruefListeOffen {
                ScrollView {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(befunde) { b in
                            BefundZeile(befund: b) { model.pruefActions?.zeigeBefund(b) }
                        }
                    }
                }
                .frame(maxHeight: 260)
            }
        }
        .padding(14)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(farbe.opacity(0.05)))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(farbe.opacity(0.4), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
        }
    }

    private func untertitel(fehler: Bool, laeuft: Bool) -> String {
        var t = fehler
            ? "Betroffene Teile sind rot markiert, Export ist gesperrt. Claude behebt die Befunde in model.py."
            : "Hinweise der Prüfung; betroffene Teile sind markiert."
        if laeuft { t += " Neue Prüfung läuft …" }
        return t
    }
}

private struct BefundZeile: View {
    var befund: PruefBefund
    var zeigen: () -> Void

    var body: some View {
        Button(action: zeigen) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: befund.schwere == .fehler ? "xmark.octagon.fill" : "exclamationmark.circle.fill")
                    .foregroundStyle(befund.schwere == .fehler ? Color.red : Color.orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text(befund.text)
                        .font(.callout)
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    if !befund.loesung.isEmpty {
                        Text(befund.loesung)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: "scope")
                    .foregroundStyle(.secondary)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Teile auswählen und hinzoomen")
    }
}
