import KevCADCore
import SwiftUI

extension AppModel {
    var pruefActions: PruefActions? { actions as? PruefActions }
}

/// Band über dem Viewport, solange die Prüfung offene Befunde hat („2 Durchdringungen · 1 Teil nicht einbaubar“), oder
/// wenn Kevin die Montagereihenfolge geöffnet hat. Reiter „Befunde“ (Klick: Teile auswählen und hinzoomen) und
/// „Montage“ (Reihenfolge mit Einführrichtung, Schritt für Schritt einblenden).
struct PruefBanner: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    var dismiss: () -> Void

    var body: some View {
        let p = model.pruefung
        let befunde = (p?.befunde ?? []).filter { $0.schwere != .hinweis }
        let fehler = befunde.contains { $0.schwere == .fehler }
        let farbe: Color = fehler ? .red : befunde.isEmpty ? .green : .orange
        let offen = p?.kommtNoch == true  // Bewegungsraum oder Statik rechnen noch: nicht „in Ordnung“ melden
        let kopf = befunde.isEmpty ? (offen ? "bisher in Ordnung" : "in Ordnung") : (p?.bandText ?? "")
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 10) {
                Image(systemName: befunde.isEmpty ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .font(.title3)
                    .foregroundStyle(farbe)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Prüfung: " + kopf)
                        .font(.headline)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Text(untertitel(fehler: fehler, leer: befunde.isEmpty, laeuft: p?.laeuft ?? false,
                                    hintergrund: p?.hintergrundText ?? ""))
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
                Button(state.pruefListeOffen ? "Zuklappen" : "Details") {
                    withAnimation(.snappy(duration: 0.2)) { state.pruefListeOffen.toggle() }
                }
                Button {
                    if state.montageSchritt != nil {
                        state.montageSchritt = nil
                        model.pruefActions?.zeigeMontageSchritt(nil)
                    }
                    state.pruefListeOffen = false
                    dismiss()
                } label: {
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
                Picker("", selection: $state.pruefTab) {
                    Text("Befunde (\(befunde.count))").tag("befunde")
                    Text("Montage (\(p?.montageSchritte.count ?? 0) Schritte)").tag("montage")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 360)
                if state.pruefTab == "montage" {
                    MontageListe(model: model, state: state)
                } else if befunde.isEmpty {
                    Text("Keine offenen Befunde.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
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

    private func untertitel(fehler: Bool, leer: Bool, laeuft: Bool, hintergrund: String = "") -> String {
        if leer, !hintergrund.isEmpty { return hintergrund }  // noch nicht „in Ordnung“: Bewegungsraum oder Statik fehlt
        var t =
            leer
            ? "Keine Durchdringung, nichts schwebt, alles lässt sich einbauen."
            : fehler
                ? "Betroffene Teile sind rot markiert, Export ist gesperrt. Claude behebt die Befunde in model.py."
                : "Hinweise der Prüfung; betroffene Teile sind markiert."
        if laeuft { t += " Neue Prüfung läuft …" }
        if !hintergrund.isEmpty { t += " " + hintergrund }
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

/// Montagereihenfolge mit Schritt-für-Schritt-Ansicht: blendet die Teile der Schritte 1 … k ein.
private struct MontageListe: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState

    var body: some View {
        let schritte = model.pruefung?.montageSchritte ?? []
        let offen = model.pruefung?.montageOffen ?? []
        VStack(alignment: .leading, spacing: 6) {
            if schritte.isEmpty {
                Text("Noch keine Montagereihenfolge.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                HStack(spacing: 8) {
                    Button {
                        gehe((state.montageSchritt ?? schritte.count + 1) - 1, anzahl: schritte.count)
                    } label: { Image(systemName: "chevron.left") }
                        .disabled((state.montageSchritt ?? 2) <= 1)
                    Text(state.montageSchritt.map { "Schritt \($0) von \(schritte.count)" } ?? "Alle Teile")
                        .font(.callout.monospacedDigit())
                        .frame(minWidth: 130)
                    Button {
                        gehe((state.montageSchritt ?? 0) + 1, anzahl: schritte.count)
                    } label: { Image(systemName: "chevron.right") }
                        .disabled((state.montageSchritt ?? 0) >= schritte.count)
                    Button("Alles zeigen") { gehe(nil, anzahl: schritte.count) }
                        .disabled(state.montageSchritt == nil)
                    Spacer(minLength: 0)
                }
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 3) {
                            ForEach(schritte) { s in
                                Button { gehe(s.nr, anzahl: schritte.count) } label: {
                                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                                        Text("\(s.nr).")
                                            .font(.callout.monospacedDigit())
                                            .frame(width: 32, alignment: .trailing)
                                        Text(s.name)
                                            .font(.callout)
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                        Spacer(minLength: 6)
                                        Text(s.richtungText + (s.werkzeug.map { " · \($0)" } ?? ""))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    .padding(.vertical, 3)
                                    .padding(.horizontal, 6)
                                    .background(
                                        RoundedRectangle(cornerRadius: 6)
                                            .fill(state.montageSchritt == s.nr ? Color.accentColor.opacity(0.18) : .clear))
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .id(s.nr)
                            }
                        }
                    }
                    .frame(maxHeight: 240)
                    .onChange(of: state.montageSchritt) { _, k in
                        if let k { withAnimation { proxy.scrollTo(k, anchor: .center) } }
                    }
                }
            }
            if !offen.isEmpty {
                Text("Nicht einbaubar: " + offen.map { $0.split(separator: "/").last.map(String.init) ?? $0 }
                    .joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private func gehe(_ k: Int?, anzahl: Int) {
        let ziel = k.map { max(1, min($0, anzahl)) }
        state.montageSchritt = ziel
        model.pruefActions?.zeigeMontageSchritt(ziel)
    }
}
