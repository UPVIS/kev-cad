#if os(macOS)
import AppKit
#endif
import OCCTSwiftViewport
import SwiftUI

/// Alles, was der Viewer selbst über das 3D-Bild legt: Hinweisleiste, Kreismenüs, Tastenübersicht, Meldungen,
/// Aufnahme-Anzeige. Eigenständig in KevCADCore; die Fensteroberfläche muss dafür nichts tun.
struct ViewerOberflaeche: View {
    @ObservedObject var viewer: ViewerStore
    let model: AppModel
    let coordinator: ViewportCoordinator
    let groesse: CGSize

    private var actions: ViewerActions? { model.actions as? ViewerActions }

    var body: some View {
        ZStack {
            VStack(spacing: 8) {
                Spacer(minLength: 0)
                if let m = viewer.meldung {
                    MeldungsLeiste(meldung: m) { viewer.meldung = nil }
                        .id(m.id)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                if viewer.aufnahme.laeuft {
                    AufnahmeLeiste(zustand: viewer.aufnahme) { actions?.navigationAufnehmen() }
                        .transition(.opacity)
                }
                if viewer.hinweisleiste {
                    Hinweisleiste(
                        eingabe: coordinator.eingabe, model: model, viewer: viewer, oberflaeche: model.oberflaeche,
                        viewport: coordinator.controller, groesse: groesse, actions: actions)
                }
            }
            .padding(.horizontal, 10)
            .padding(.bottom, 8)
            ViewerMenueOverlay(
                viewer: viewer, groesse: groesse, actions: actions,
                orthographisch: coordinator.controller.cameraState.isOrthographic)
            if viewer.tastenuebersicht {
                ZStack {
                    Color.black.opacity(0.18)
                        .contentShape(Rectangle())
                        .onTapGesture { viewer.tastenuebersicht = false }
                    Tastenuebersicht(viewer: viewer)
                        .padding(30)
                }
                .transition(.opacity)
            }
        }
        .animation(.snappy(duration: 0.18), value: viewer.meldung)
        .animation(.snappy(duration: 0.18), value: viewer.menue)
        .animation(.snappy(duration: 0.18), value: viewer.tastenuebersicht)
        .onChange(of: viewer.hinweisleiste, initial: true) { _, an in
            // Der Maßstab steht in der Hinweisleiste; ohne sie zeigt das Paket seinen eigenen
            coordinator.controller.showScaleBar = !an
        }
    }
}

/// Meldung mit „Im Finder zeigen“, verschwindet nach einigen Sekunden.
struct MeldungsLeiste: View {
    let meldung: ViewerMeldung
    let schliessen: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: meldung.fehler ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(meldung.fehler ? Color.orange : ViewerStil.akzent)
            Text(meldung.text)
                .foregroundStyle(ViewerStil.text)
                .lineLimit(2)
            // iPad: kein Finder; Dateien teilen (Teilen-Blatt) folgt in I-8
            if let datei = meldung.datei, Dateiablage.kannImFinderZeigen {
                Button("Im Finder zeigen") {
                    Dateiablage.imFinderZeigen([datei])
                }
                .buttonStyle(.plain)
                .foregroundStyle(ViewerStil.akzent)
            }
            Button(action: schliessen) {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(ViewerStil.textLeise)
            }
            .buttonStyle(.plain)
        }
        .font(ViewerStil.schrift)
        .padding(.horizontal, 12)
        .frame(height: 30)
        .background(Capsule().fill(ViewerStil.leisteGrund))
        .overlay(Capsule().strokeBorder(ViewerStil.leisteRand))
        .task(id: meldung.id) {
            try? await Task.sleep(for: .seconds(meldung.datei == nil ? 2.5 : 6))
            schliessen()
        }
    }
}

/// Anzeige während einer Aufnahme: Mitschnitt läuft (mit Stopp) oder Video wird gerechnet.
struct AufnahmeLeiste: View {
    let zustand: AufnahmeZustand
    let stopp: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            switch zustand {
            case .navigation(let beginn):
                Circle().fill(Color.red).frame(width: 8, height: 8)
                TimelineView(.periodic(from: beginn, by: 0.5)) { ctx in
                    Text("Navigation wird aufgenommen · \(Int(ctx.date.timeIntervalSince(beginn))) s")
                        .monospacedDigit()
                        .foregroundStyle(ViewerStil.text)
                }
                Button("Stopp", action: stopp)
                    .buttonStyle(.plain)
                    .foregroundStyle(ViewerStil.akzent)
            case .drehung(let p), .navigationRechnen(let p):
                ProgressView(value: p).progressViewStyle(.linear).frame(width: 120)
                Text(zustand == .drehung(p) ? "Video wird gerechnet" : "Mitschnitt wird gerechnet")
                    .foregroundStyle(ViewerStil.text)
            case .keine:
                EmptyView()
            }
        }
        .font(ViewerStil.schrift)
        .padding(.horizontal, 12)
        .frame(height: 30)
        .background(Capsule().fill(ViewerStil.leisteGrund))
        .overlay(Capsule().strokeBorder(ViewerStil.leisteRand))
    }
}
