import Foundation

/// Feste Angaben zur laufenden App: Variante, Datenordner, Socket, Port, Ort des Kernels.
public enum AppInfo {
    /// Bundle-ID der laufenden App (`de.upvis.kevcad` oder `de.upvis.kevcad.test`).
    public static var bundleID: String { Bundle.main.bundleIdentifier ?? "de.upvis.kevcad.dev" }

    /// Testvariante („Kev CAD Test“, auch mit Zusatz): eigener Datenordner, eigener Port, Fenster auf dem zweiten Monitor.
    public static var isTestVariant: Bool { bundleID.contains(".test") }

    /// Datenordner der App unter Application Support, je Variante getrennt.
    public static var supportDirectory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent(bundleID, isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Unix-Socket zwischen App und Kernel-Server.
    public static var kernelSocket: URL { supportDirectory.appendingPathComponent("kernel.sock") }

    /// Port für MCP über HTTP auf 127.0.0.1 (Info.plist-Schlüssel `KevCADPort`, gesetzt von build.sh).
    public static var mcpPort: Int {
        if let s = Bundle.main.object(forInfoDictionaryKey: "KevCADPort") as? String, let p = Int(s) { return p }
        return isTestVariant ? 47824 : 47823
    }

    /// Demomodus ohne Kernel (Umgebungsvariable `KEVCAD_DEMO=1`), für Arbeiten an der Oberfläche.
    public static var isDemoMode: Bool { ProcessInfo.processInfo.environment["KEVCAD_DEMO"] == "1" }

    /// Repo-Ordner, aus dem die App gebaut wurde (Info.plist-Schlüssel `KevCADRepo`, gesetzt von build.sh).
    public static var repoDirectory: URL? {
        guard let path = Bundle.main.object(forInfoDictionaryKey: "KevCADRepo") as? String, !path.isEmpty,
              !path.hasPrefix("$(")
        else { return nil }
        return URL(fileURLWithPath: path, isDirectory: true)
    }

    /// Startbefehl des Kernels: `<repo>/kernel/.venv/bin/kevcad-kernel`.
    public static var kernelExecutable: URL? {
        repoDirectory?.appendingPathComponent("kernel/.venv/bin/kevcad-kernel")
    }

    /// Standardordner für Projekte. `KEVCAD_PROJECTS_DIR` setzt einen anderen (wie beim MCP-Server; Testvarianten
    /// schreiben so nicht in Kevins ~/Documents/Kev CAD). Sonst entscheidet die Projektablage (I-7, Vorgabe aus): am Mac
    /// `projektablage.json` im Datenordner, auf dem iPad der Schalter in den Einstellungen mit dem gewählten iCloud-Ordner.
    public static var projectsDirectory: URL {
        let umgebung = ProcessInfo.processInfo.environment
        #if os(macOS)
        return Projektablage.ordner(
            umgebung: umgebung, schalter: Projektablage.schalterLesen(in: supportDirectory),
            vorgabe: Projektablage.lokalerOrdner)
        #else
        return Projektablage.ordner(
            umgebung: umgebung, schalter: Projektablage.Schalter(),
            vorgabe: PadOrdner.projektOrdner() ?? PadOrdner.lokalerOrdner)
        #endif
    }
}
