import SwiftUI

@main
struct KevScanApp: App {
    @StateObject private var store = ScanStore()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        AppSettings.registerDefaults()
        ScanStore.cleanTemporaryFiles()
        DeviceProbe.write()
    }

    var body: some Scene {
        WindowGroup {
            ScanListView()
                .environmentObject(store)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { store.reload() }
        }
    }
}

/// Einstellungen der App (UserDefaults, in der Oberfläche über @AppStorage).
enum AppSettings {
    static let autoPhoto = "autoFoto"
    static let autoAngle = "autoWinkelGrad"
    static let autoDistance = "autoAbstandM"
    static let showMesh = "netzZeigen"

    static func registerDefaults() {
        UserDefaults.standard.register(defaults: [
            autoPhoto: true,
            autoAngle: 15.0,
            autoDistance: 0.25,
            showMesh: true,
        ])
    }
}

/// Angaben zum Gerät für meta.json.
enum DeviceInfo {
    /// Modellkennung wie "iPhone16,2".
    static var model: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }

    static var systemVersion: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        if v.patchVersion > 0 { return "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)" }
        return "\(v.majorVersion).\(v.minorVersion)"
    }

    static var appVersion: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }
}
