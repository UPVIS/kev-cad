import Foundation

/// Der Projektordner auf dem iPad (PLAN-IPAD.md, I-7): ein Ordner in iCloud Drive, den Kevin einmal in der Dateien-App
/// wählt. Die App merkt sich ein Lesezeichen darauf und öffnet den Zugriff beim Start wieder. Ohne Lesezeichen (oder mit
/// dem Schalter aus) gilt der Dokumente-Ordner der App.
///
/// Warum kein eigener iCloud-Container: Er bräuchte eine Berechtigung im Profil der iPad-App und am Mac ein Profil für die
/// Developer-ID-Signatur; der Spike (Abschnitt 6) zeigt, dass ein gewöhnlicher Ordner in iCloud Drive für den Kernel und
/// das iPad reicht.
public enum PadOrdner {
    public static let lesezeichenKey = "KevCAD.ablage.lesezeichen"

    /// Ist der Schalter „Projekte aus iCloud (Versuch)“ an (Einstellungen des iPad)?
    public static func schalterAn(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: Projektablage.padSchalterKey)
    }

    /// Merkt sich den gewählten Ordner. Die Adresse kommt aus dem Ordner-Dialog und hat den Zugriff schon offen.
    public static func merken(_ url: URL, defaults: UserDefaults = .standard) throws {
        let daten = try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
        defaults.set(daten, forKey: lesezeichenKey)
        aufgeloest = nil
    }

    public static func vergessen(_ defaults: UserDefaults = .standard) {
        if let alt = aufgeloest { alt.stopAccessingSecurityScopedResource() }
        aufgeloest = nil
        defaults.removeObject(forKey: lesezeichenKey)
    }

    nonisolated(unsafe) private static var aufgeloest: URL?

    /// Der gewählte Ordner mit offenem Zugriff, oder nil (kein Lesezeichen, Ordner weg). Ein veraltetes Lesezeichen
    /// (Ordner umbenannt oder verschoben) wird erneuert.
    public static func ordner(_ defaults: UserDefaults = .standard) -> URL? {
        if let u = aufgeloest { return u }
        guard let daten = defaults.data(forKey: lesezeichenKey) else { return nil }
        var veraltet = false
        guard let url = try? URL(resolvingBookmarkData: daten, options: [], relativeTo: nil,
                                 bookmarkDataIsStale: &veraltet)
        else { return nil }
        _ = url.startAccessingSecurityScopedResource()
        if veraltet { try? merken(url, defaults: defaults) }
        aufgeloest = url
        return url
    }

    /// Projektordner der iPad-App: der gewählte iCloud-Ordner, wenn der Schalter an ist; sonst `nil`.
    public static func projektOrdner(_ defaults: UserDefaults = .standard) -> URL? {
        schalterAn(defaults) ? ordner(defaults) : nil
    }
}
