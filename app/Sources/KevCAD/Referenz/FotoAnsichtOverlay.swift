import KevCADCore
import SwiftUI

/// Fotoansicht über dem Viewport (Phase 4): das Foto, gesehen durch die eingepasste Kamera, das Modell davor mit
/// Deckkraft-Regler; im Modus „Differenz“ rot, was nur das Foto zeigt, blau, was nur das Modell zeigt. Das Bild rechnet
/// der App-Kern (AppController+Referenz) nach jedem Lauf neu. Zwei schmale Leisten oben (Foto, Darstellung), damit
/// der Bereich auch neben Versionsleiste und Inspektor passt; unten bleibt Platz für die Bänder des Viewports.
struct FotoAnsichtOverlay: View {
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?

    var body: some View {
        if let a = store.fotoansicht {
            VStack(spacing: 0) {
                kopf(a)
                darstellung(a)
                ZStack {
                    Color.black.opacity(0.92)
                    if let bild = store.fotoBild {
                        Image(decorative: bild, scale: 1)
                            .resizable()
                            .interpolation(.high)
                            .aspectRatio(contentMode: .fit)
                            .padding(10)
                    } else {
                        ProgressView().controlSize(.large)
                    }
                }
                .padding(.bottom, 44)
                .background(Color.black.opacity(0.92))
            }
            .transition(.opacity)
            .onExitCommand { actions?.fotoansichtSchliessen() }
        }
    }

    private func kopf(_ a: FotoAnsicht) -> some View {
        let liste = store.fotoSatz(a.referenz, a.satz)
        let foto = store.aktuellesFoto
        return HStack(spacing: 8) {
            Image(systemName: "camera.viewfinder")
            Text("Fotoansicht").fontWeight(.semibold).fixedSize()
            Button { actions?.fotoWechseln(-1) } label: { Image(systemName: "chevron.left") }
                .keyboardShortcut(.leftArrow, modifiers: [])
                .help("Voriges Foto (←)")
            Text("\(a.index + 1)/\(liste.count)").monospacedDigit().fixedSize()
            Button { actions?.fotoWechseln(1) } label: { Image(systemName: "chevron.right") }
                .keyboardShortcut(.rightArrow, modifiers: [])
                .help("Nächstes Foto (→)")
            if let foto {
                Text(foto.titel + (a.satz == "capture" ? " · Object Capture" : ""))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: 4)
            Button { actions?.fotoansichtSchliessen() } label: { Image(systemName: "xmark") }
                .keyboardShortcut(.escape, modifiers: [])
                .help("Fotoansicht schließen (Esc)")
        }
        .font(.callout)
        .buttonStyle(.borderless)
        .controlSize(.small)
        .padding(.horizontal, 12)
        .padding(.top, 7)
        .padding(.bottom, 4)
        .background(.regularMaterial)
    }

    private func darstellung(_ a: FotoAnsicht) -> some View {
        let maske = store.aktuellesFoto?.maske != nil
        return HStack(spacing: 10) {
            Picker("", selection: Binding(get: { a.modus }, set: { actions?.fotoModus($0) })) {
                Text("Überlagern").tag(FotoAnsicht.Modus.ueberlagern)
                Text("Differenz").tag(FotoAnsicht.Modus.differenz)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .disabled(!maske)
            .help(maske ? "Differenz: rot nur im Foto, blau nur im Modell" : "Für dieses Foto gibt es keine Maske")
            Image(systemName: "cube").foregroundStyle(.secondary).help("Deckkraft des Modells über dem Foto")
            Slider(value: Binding(get: { a.deckkraft }, set: { actions?.fotoDeckkraft($0) }), in: 0...1)
                .frame(minWidth: 70, maxWidth: 150)
            if a.modus == .differenz && maske {
                punkt(Color(red: 0.91, green: 0.17, blue: 0.17), "Foto")
                punkt(Color(red: 0.15, green: 0.44, blue: 0.93), "Modell")
            }
            if let iou = store.fotoUeberdeckung {
                Text("Überdeckung \(KevFormat.number(iou * 100, digits: 1)) %")
                    .monospacedDigit()
                    .lineLimit(1)
                    .fixedSize()
                    .help("Modell gegen die Maske des Fotos (Überschneidung durch Vereinigung)"
                        + (store.aktuellesFoto?.iou.map { "; beim Vermessen \(KevFormat.number($0 * 100, digits: 1)) %" } ?? ""))
            }
            if let m = store.fotoMeldung {
                Text(m).foregroundStyle(.orange).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .font(.caption)
        .controlSize(.small)
        .padding(.horizontal, 12)
        .padding(.bottom, 6)
        .background(.regularMaterial)
    }

    private func punkt(_ farbe: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(farbe).frame(width: 8, height: 8)
            Text("nur \(text)").lineLimit(1).fixedSize()
        }
    }
}
