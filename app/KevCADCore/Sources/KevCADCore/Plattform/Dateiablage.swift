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

    /// Teilen-Blatt des Systems für lokale Dateien (auf dem iPad mit Drucken, Dateien, AirDrop), am Mac der Teilen-Dienst.
    /// `rahmen`: Stelle des Knopfs im Fenster (SwiftUI global), leer = Fenstermitte.
    public static func teilen(_ urls: [URL], von rahmen: CGRect = .zero) {
        guard !urls.isEmpty else { return }
        #if os(macOS)
        guard let fenster = NSApp.keyWindow ?? NSApp.mainWindow, let inhalt = fenster.contentView else { return }
        // SwiftUI misst global von oben links, AppKit von unten links
        let stelle = rahmen.isEmpty
            ? NSRect(x: inhalt.bounds.midX, y: inhalt.bounds.midY, width: 1, height: 1)
            : NSRect(x: rahmen.minX, y: inhalt.bounds.height - rahmen.maxY, width: rahmen.width, height: rahmen.height)
        NSSharingServicePicker(items: urls).show(relativeTo: stelle, of: inhalt, preferredEdge: .minY)
        #else
        let szenen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let szene = szenen.first(where: { $0.activationState == .foregroundActive }) ?? szenen.first,
              let fenster = szene.keyWindow ?? szene.windows.first, var oben = fenster.rootViewController
        else { return }
        while let weiter = oben.presentedViewController { oben = weiter }
        let blatt = UIActivityViewController(activityItems: urls, applicationActivities: nil)
        if let pop = blatt.popoverPresentationController {
            pop.sourceView = fenster
            pop.sourceRect = rahmen.isEmpty
                ? CGRect(x: fenster.bounds.midX, y: fenster.bounds.midY, width: 1, height: 1) : rahmen
        }
        oben.present(blatt, animated: true)
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
