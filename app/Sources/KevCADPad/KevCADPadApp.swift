import KevCADCore
import SwiftUI

// iPad-Hülle von Kev CAD (PLAN-IPAD.md, I2): Einstieg, Fenster, Statusleiste und Hinweis auf den Demomodus. Die Oberfläche
// selbst ist dieselbe wie am Mac (app/Sources/KevCAD); was nur am Mac geht, steht dort hinter `#if os(macOS)`, die Hülle des
// Mac (Menüs, Fenster, Tastaturwächter) liegt in app/Sources/KevCAD/Mac/.

/// Einstieg der iPad-App: ein Fenster mit dem Hauptfenster der gemeinsamen Oberfläche, im Graphit-Look wie am Mac.
@main
struct KevCADPadApp: App {
    @StateObject private var session: AppSession

    init() {
        PadStart.demoVorgaben()
        Startzeiten.marke("App.init")
        _session = StateObject(wrappedValue: AppSession())
    }

    var body: some Scene {
        // Eine Szene mit der Kennung des Hauptfensters (wie die Szene „Window“ am Mac): `showProjectWindow()` holt sie nach
        // vorn, statt ein zweites Fenster zu öffnen (Info.plist: UIApplicationSupportsMultipleScenes aus).
        WindowGroup(id: WindowID.project) {
            PadHauptfenster(session: session)
        }
    }
}

/// Vorgaben beim Start der iPad-App.
enum PadStart {
    /// Bis die Verbindung zum Mac steht (I-2b), startet die iPad-App im Demomodus: Der Demo-Lauf des App-Kerns baut den
    /// Wandhalter mit echter Geometrie im Metal-Viewer auf (`KEVCAD_DEMO_VIEWPORT=kern`, siehe Demo/DemoData.swift). Werte
    /// von außen (Xcode, `xcrun simctl launch` mit `SIMCTL_CHILD_…`) gehen vor.
    /// iPad: Verbindung zum Mac und Kopplung folgen in I-2b und I-6; dann entfällt diese Vorgabe.
    static func demoVorgaben() {
        setenv("KEVCAD_DEMO", "1", 0)
        setenv("KEVCAD_DEMO_VIEWPORT", "kern", 0)
        setenv("KEVCAD_DEMO_STATE", "live", 0)
    }
}

/// Hauptfenster auf dem iPad: die gemeinsame Oberfläche zwischen Statusleiste und Home-Balken (am Mac reicht sie bis
/// unter die Titelleiste), die Statusleiste hell darüber. Solange die App ohne Mac läuft, sagt das ein kleiner Hinweis in
/// der Mitte der Statusleiste.
///
/// Darum hält das Hauptfenster auf dem iPad die Ränder des Systems selbst ein (kein `ignoresSafeArea`): Ein Abstand
/// (`padding`) von außen hält ein `ignoresSafeArea` im Inneren nicht auf, es reicht trotzdem bis an den Bildschirmrand, und
/// ein `GeometryReader` mit `ignoresSafeArea` meldet keine Ränder mehr (beides am Simulator gesehen, I-3a).
struct PadHauptfenster: View {
    @ObservedObject var session: AppSession

    /// Grund unter Statusleiste und Home-Balken: der des Viewers im dunklen Bild (0,12 Grau wie
    /// `AppController.hintergrundDunkel`), so schließt der Viewer ohne Kacheln nahtlos an. iPad: Viewer bis unter die
    /// Statusleiste folgt in I-3b, dann entfällt dieser Streifen.
    private static let randGrund = Color(white: 0.12)

    private var imDemomodus: Bool { AppInfo.isDemoMode }

    var body: some View {
        GeometryReader { geo in
            let oben = geo.safeAreaInsets.top
            Hauptfenster(model: session.model, oberflaeche: session.model.oberflaeche)
                .environmentObject(session)
                .overlay(alignment: .top) {
                    if imDemomodus {
                        DemoHinweis()
                            .frame(height: max(oben, 20))
                            .offset(y: -oben)
                    }
                }
        }
        .background(Self.randGrund.ignoresSafeArea())
        .preferredColorScheme(.dark)
    }
}

/// Leiser Hinweis: Die App zeigt ein Beispiel, weil sie (noch) nicht mit dem Mac verbunden ist.
private struct DemoHinweis: View {
    var body: some View {
        Text("Beispielmodell, noch ohne Verbindung zum Mac")
            .font(GS.klein)
            .foregroundStyle(GF.asche)
            .padding(.horizontal, 10)
            .padding(.vertical, 2)
            .background(Capsule().fill(GF.mitte.opacity(0.6)))
            .accessibilityLabel("Kev CAD zeigt ein Beispielmodell, weil es noch nicht mit dem Mac verbunden ist.")
    }
}
