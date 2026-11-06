import Foundation

#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// Zwischenablage (NSPasteboard am Mac, UIPasteboard auf dem iPad).
@MainActor
enum Zwischenablage {
    /// Legt Text in die Zwischenablage und ersetzt ihren bisherigen Inhalt.
    static func setzen(_ text: String) {
        #if os(macOS)
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(text, forType: .string)
        #else
        UIPasteboard.general.string = text
        #endif
    }
}
