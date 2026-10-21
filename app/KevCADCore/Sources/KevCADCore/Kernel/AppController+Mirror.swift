import Foundation

// Spiegel aufs iPhone (MIRROR.md): der Dienst lauscht auf `<Datenordner>/mirror.sock`, VoiceBridge verbindet sich.

extension AppController {
    /// Socket-Pfad des Spiegels: `KEVCAD_MIRROR_SOCKET`, sonst `mirror.sock` im Datenordner der App. In Tests ohne
    /// gebaute App (und mit `KEVCAD_MIRROR=0`) kein Spiegel.
    nonisolated static var mirrorSocketPath: String? {
        let env = ProcessInfo.processInfo.environment
        if env["KEVCAD_MIRROR"] == "0" { return nil }
        if let path = env["KEVCAD_MIRROR_SOCKET"], !path.isEmpty { return path }
        guard Bundle.main.bundleURL.pathExtension == "app" else { return nil }
        return AppInfo.supportDirectory.appendingPathComponent(MirrorProtocol.socketName).path
    }

    /// Spiegel-Dienst einmal starten (bei einem Neustart des Kernels läuft er weiter).
    func startMirror(path: String? = AppController.mirrorSocketPath) {
        guard mirror == nil, let path else { return }
        let service = MirrorService(controller: self, path: path)
        do {
            try service.start()
            mirror = service
        } catch {
            log(.error, "Spiegel nicht gestartet: \(error)")
        }
    }
}
