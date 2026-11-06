import Foundation

#if os(macOS)
import AppKit
#endif

/// Dateien im Dateimanager zeigen.
@MainActor
enum Dateiablage {
    /// Gibt es einen Dateimanager, in dem der Kern Dateien markieren kann (Finder)? Auf dem iPad nicht.
    static var kannImFinderZeigen: Bool {
        #if os(macOS)
        true
        #else
        false
        #endif
    }

    /// Markiert die Dateien im Finder; true, wenn das ging. Auf dem iPad gibt es dafür kein Gegenstück im Kern (dort gibt
    /// die Oberfläche Dateien über das Teilen-Blatt weiter; iPad: folgt in I-8), dann geschieht nichts und die Antwort ist
    /// false.
    @discardableResult
    static func imFinderZeigen(_ urls: [URL]) -> Bool {
        #if os(macOS)
        NSWorkspace.shared.activateFileViewerSelecting(urls)
        return true
        #else
        return false
        #endif
    }
}
