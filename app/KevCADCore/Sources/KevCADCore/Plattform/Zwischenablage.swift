import Foundation

#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// Zwischenablage (NSPasteboard am Mac, UIPasteboard auf dem iPad). Öffentlich, damit auch die Oberfläche (Mac und iPad)
/// nur diesen Weg nimmt (Paket I-3a).
@MainActor
public enum Zwischenablage {
    /// Legt Text in die Zwischenablage und ersetzt ihren bisherigen Inhalt.
    public static func setzen(_ text: String) {
        #if os(macOS)
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(text, forType: .string)
        #else
        UIPasteboard.general.string = text
        #endif
    }

    /// Text in der Zwischenablage, nil ohne Text.
    public static var text: String? {
        #if os(macOS)
        NSPasteboard.general.string(forType: .string)
        #else
        UIPasteboard.general.string
        #endif
    }
}
