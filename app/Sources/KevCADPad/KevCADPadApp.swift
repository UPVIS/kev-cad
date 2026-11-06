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
        PadStart.vorgaben()
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
    /// Gekoppelt verbindet sich die App mit dem Mac (I-2b, `AppController.startUeberMac`). Ohne Kopplung zeigt sie das
    /// Beispielmodell: Der Demo-Lauf des App-Kerns baut den Wandhalter mit echter Geometrie im Metal-Viewer auf
    /// (`KEVCAD_DEMO_VIEWPORT=kern`, siehe Demo/DemoData.swift), darüber liegt das Blatt zum Koppeln. Werte von außen
    /// (Xcode, `xcrun simctl launch` mit `SIMCTL_CHILD_…`) gehen vor.
    static func vorgaben() {
        #if DEBUG
        // Tests im Simulator (keine Kamera): Kopplungscode der Mac-Testvariante über `KEVCAD_PAD_KOPPLUNG`
        if let text = ProcessInfo.processInfo.environment["KEVCAD_PAD_KOPPLUNG"], let code = KopplungsCode.lesen(text) {
            try? PadKopplung.speichern(code)
        }
        #endif
        guard PadKopplung.laden() == nil else { return }
        setenv("KEVCAD_DEMO", "1", 0)
        setenv("KEVCAD_DEMO_VIEWPORT", "kern", 0)
        setenv("KEVCAD_DEMO_STATE", "live", 0)
    }

    /// Das Blatt zum Koppeln beim Start zeigen (nicht in Aufnahmen der Oberfläche: `KEVCAD_PAD_OHNE_KOPPLUNGSBLATT=1`).
    static var kopplungsBlattBeimStart: Bool {
        PadKopplung.laden() == nil && ProcessInfo.processInfo.environment["KEVCAD_PAD_OHNE_KOPPLUNGSBLATT"] != "1"
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
    @State private var kopplungZeigen = PadStart.kopplungsBlattBeimStart

    /// Grund unter Statusleiste und Home-Balken: der des Viewers im dunklen Bild (0,12 Grau wie
    /// `AppController.hintergrundDunkel`), so schließt der Viewer ohne Kacheln nahtlos an. iPad: Viewer bis unter die
    /// Statusleiste folgt in I-3b, dann entfällt dieser Streifen.
    private static let randGrund = Color(white: 0.12)

    private var kopplungsAktionen: KopplungsActions? { session.model.actions as? KopplungsActions }

    var body: some View {
        GeometryReader { geo in
            let oben = geo.safeAreaInsets.top
            Hauptfenster(model: session.model, oberflaeche: session.model.oberflaeche)
                .environmentObject(session)
                .overlay(alignment: .top) {
                    // Mit welchem Mac das iPad verbunden ist; ohne Kopplung der Hinweis aufs Beispielmodell
                    PadKopplungsChip(kopplung: session.model.kopplung) { kopplungZeigen = true }
                        .frame(height: max(oben, 20))
                        .offset(y: -oben)
                }
        }
        .background(Self.randGrund.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .sheet(isPresented: $kopplungZeigen) {
            PadKopplungsBlatt(kopplung: session.model.kopplung, aktionen: kopplungsAktionen) { kopplungZeigen = false }
                .presentationDetents([.medium, .large])
                .presentationBackground(GF.tief)
        }
        // Der Mac kennt das iPad nicht mehr (Schlüssel passt nicht): gleich das Blatt zum neu Koppeln
        .onReceive(session.model.kopplung.$meldung.dropFirst()) { meldung in if meldung != nil { kopplungZeigen = true } }
    }
}
