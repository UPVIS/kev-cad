import Foundation

#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// Dateien im Dateimanager zeigen und Adressen öffnen. Öffentlich, damit auch die Oberfläche (Mac und iPad) nur diesen Weg
/// nimmt (Paket I-3a).
@MainActor
public enum Dateiablage {
    /// Gibt es einen Dateimanager, in dem der Kern Dateien markieren kann (Finder)? Auf dem iPad nicht.
    public static var kannImFinderZeigen: Bool {
        #if os(macOS)
        true
        #else
        false
        #endif
    }

    /// Markiert die Dateien im Finder; true, wenn das ging. Auf dem iPad gibt es dafür kein Gegenstück im Kern: Dort gibt
    /// die Oberfläche Dateien über das Teilen-Blatt weiter (`AppSession.dateienTeilen`, `DateiKnopf`, I-8); hier geschieht
    /// dann nichts und die Antwort ist false.
    @discardableResult
    public static func imFinderZeigen(_ urls: [URL]) -> Bool {
        #if os(macOS)
        NSWorkspace.shared.activateFileViewerSelecting(urls)
        return true
        #else
        return false
        #endif
    }

    /// Kann diese Adresse hier geöffnet werden? Webadressen überall; Dateien nur am Mac (mit dem Standardprogramm). Auf dem
    /// iPad gehen Dateien über das Teilen-Blatt (I-8).
    public static func kannOeffnen(_ url: URL) -> Bool {
        #if os(macOS)
        true
        #else
        !url.isFileURL
        #endif
    }

    /// Öffnet die Adresse: am Mac mit dem Standardprogramm (Webseite im Browser, model.py im Editor), auf dem iPad nur
    /// Webadressen (Safari). true, wenn das Öffnen angestoßen wurde.
    @discardableResult
    public static func oeffnen(_ url: URL) -> Bool {
        #if os(macOS)
        return NSWorkspace.shared.open(url)
        #else
        guard kannOeffnen(url) else { return false }
        UIApplication.shared.open(url)
        return true
        #endif
    }
}
