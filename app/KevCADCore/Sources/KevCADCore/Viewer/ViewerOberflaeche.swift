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
            WerkzeugkranzOverlay(viewer: viewer, oberflaeche: model.oberflaeche, groesse: groesse, actions: actions)
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
        .animation(.snappy(duration: 0.18), value: viewer.kranz != nil)
        #if DEBUG
        .task { await kranzVorfuehren() }
        #endif
        .onChange(of: viewer.hinweisleiste, initial: true) { _, an in
            // Der Maßstab steht in der Hinweisleiste; ohne sie zeigt das Paket seinen eigenen
            coordinator.controller.showScaleBar = !an
        }
    }
}

#if DEBUG
extension ViewerOberflaeche {
    /// I-4, nur in Debug-Bauten: `KEVCAD_KRANZ` zeigt den Werkzeugkranz beim Start offen, für Fotos im Simulator und in
    /// der Testvariante. Werte: `haupt`, ein Feld (`ansichten`, `darstellung` …) oder `regler:<name>` (`regler:explosion`).
    @MainActor
    func kranzVorfuehren() async {
        guard let wert = ProcessInfo.processInfo.environment["KEVCAD_KRANZ"], !wert.isEmpty else { return }
        try? await Task.sleep(for: .seconds(2))
        guard let actions, viewer.kranz == nil else { return }
        actions.kranzOeffnen(bei: CGPoint(x: groesse.width * 0.62, y: groesse.height * 0.5))
        if wert.hasPrefix("regler:"), let r = KranzRegler(rawValue: String(wert.dropFirst(7))) {
            actions.kranzAusfuehren(.regler(r))
        } else if let f = KranzFeld(rawValue: wert), var k = viewer.kranz {
            k.ebene = Tastenbelegung.kranz(f).isEmpty ? .haupt : .feld(f)
            k.markiert = Tastenbelegung.kranz(f).isEmpty ? .feld(KranzFeld.allCases.firstIndex(of: f) ?? 0) : .unter(0)
            viewer.kranz = k
        } else if var k = viewer.kranz {
            k.markiert = .feld(1)
            viewer.kranz = k
        }
    }
}
#endif

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
            // Am Mac „Im Finder zeigen“; auf dem iPad liegt die Datei im eigenen Zwischenspeicher, dort „Teilen“
            if let datei = meldung.datei {
                Button(Dateiablage.kannImFinderZeigen ? "Im Finder zeigen" : "Teilen") {
                    if !Dateiablage.imFinderZeigen([datei]) { Dateiablage.teilen([datei]) }
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
