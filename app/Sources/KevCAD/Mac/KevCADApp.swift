import AppKit
import KevCADCore
import SwiftUI

// Oberfläche von Kev CAD. Zuständig für alles in app/Sources/KevCAD (siehe CLAUDE.md).
//
// V2-3 (OBERFLAECHE.md): Das Hauptfenster ist die erste Szene und startet sofort mit einem leeren Projekt, darüber die
// Startübersicht der letzten Projekte. Kein Willkommensfenster, kein Dialog. Nebenfenster: Protokoll, Lagerkatalog,
// Zukaufteil.

@main
struct KevCADApp: App {
    @StateObject private var session = AppSession()

    init() {
        Startzeiten.marke("App.init")
        if WindowHook.versteckt { NSApplication.shared.setActivationPolicy(.accessory) }  // kein Symbol im Dock
        // Selbsttest: nur die Begrüßung bei Wortlaut, ohne Mikrofon und ohne Fenster; Ergebnis auf stdout
        if AppInfo.isTestVariant, ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "wortlaut" {
            NSApplication.shared.setActivationPolicy(.prohibited)
            WortlautErkennung.begruessung { text in
                print("Wortlaut: \(text)")
                fflush(stdout)
                exit(text.contains("angenommen") ? 0 : 1)
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 10) {
                print("Wortlaut: keine Antwort nach 10 s")
                fflush(stdout)
                exit(2)
            }
            dispatchMain()
        }
        // Nur eine Instanz je Variante: läuft schon eine (Tools-Stapel, Start durch die Claude-Brücke), diese nach vorn
        // holen und selbst gleich wieder beenden. Zwei Instanzen würden sich Socket und MCP-Port streitig machen.
        let me = NSRunningApplication.current
        if let other = NSRunningApplication.runningApplications(withBundleIdentifier: AppInfo.bundleID)
            .first(where: { $0.processIdentifier != me.processIdentifier && !$0.isTerminated })
        {
            other.activate()
            exit(0)
        }
        // Fenster stellt die App selbst her (aus dem AppModel), nicht die macOS-Fensterwiederherstellung. Ohne diese
        // Vorgabe merkt sich macOS nach einem Start ohne Fenster „keine Fenster“ und öffnet beim nächsten Start nichts,
        // trotz restorationBehavior(.disabled).
        UserDefaults.standard.register(defaults: ["ApplePersistenceIgnoreState": true])
    }

    var body: some Scene {
        Window("Kev CAD", id: WindowID.project) {
            if GestaltungMuster.an {
                GestaltungMuster()  // V2-3: Musterseite der Grundbausteine (KEVCAD_MUSTER=1)
            } else {
                Hauptfenster(model: session.model, oberflaeche: session.model.oberflaeche)
                    .environmentObject(session)
            }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1400, height: 900)
        .defaultLaunchBehavior(.presented)
        .restorationBehavior(.disabled)
        .commands {
            KevCADMenues(session: session)  // Menues/KevCADMenues.swift, dieselben Menüs wie am iPad
        }

        Window("Protokoll", id: WindowID.log) {
            LogWindow(model: session.model)
                .environmentObject(session)
        }
        .defaultSize(width: 860, height: 520)
        .defaultLaunchBehavior(.suppressed)
        .restorationBehavior(.disabled)
        .keyboardShortcut("l", modifiers: [.command, .option])

        // Phase 2: Lagerkatalog (Fenster > Lagerkatalog, ⇧⌘K)
        Window("Lagerkatalog", id: WindowID.catalog) {
            CatalogWindow(model: session.model)
                .environmentObject(session)
        }
        .defaultSize(width: 1140, height: 720)
        .defaultLaunchBehavior(.suppressed)
        .restorationBehavior(.disabled)
        .keyboardShortcut("k", modifiers: [.command, .shift])

        // I-2b (PLAN-IPAD.md): iPad koppeln (Ablage-Menü): QR-Code und gekoppelte iPads
        Window("iPad koppeln", id: WindowID.kopplung) {
            KopplungsFenster(kopplung: session.model.kopplung, aktionen: session.model.actions as? KopplungsActions)
        }
        .windowResizability(.contentSize)
        .defaultLaunchBehavior(.suppressed)
        .restorationBehavior(.disabled)

        // Phase 3: Zukaufteil hinzufügen (Ablage-Menü, Lagerkatalog)
        Window("Zukaufteil hinzufügen", id: WindowID.zukauf) {
            ZukaufDialogWindow(model: session.model)
                .environmentObject(session)
        }
        .windowResizability(.contentSize)
        .defaultLaunchBehavior(.suppressed)
        .restorationBehavior(.disabled)
    }
}
