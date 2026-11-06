import SwiftUI

// SwiftUI-Weichen des Kerns (Paket I-1, öffentlich seit I-3a): Modifikatoren und Bilder, die es nur auf einer Seite gibt,
// unter einem Namen für beide Seiten.

extension View {
    /// Esc schließt: am Mac `onExitCommand`, auf dem iPad die Esc-Taste einer Hardware-Tastatur (wirkt, solange die
    /// Ansicht den Fokus hat, etwa ein Textfeld beim Bearbeiten). Ohne Tastatur schließen die Ansichten dort über Berührung
    /// (Tippen daneben, Knopf).
    public func beiEsc(_ aktion: @escaping () -> Void) -> some View {
        #if os(macOS)
        onExitCommand(perform: aktion)
        #else
        onKeyPress(.escape) {
            aktion()
            return .handled
        }
        #endif
    }
}

extension Image {
    /// Bild aus einem NSImage (Mac) bzw. UIImage (iPad).
    public init(plattformBild bild: PlattformBild) {
        #if os(macOS)
        self.init(nsImage: bild)
        #else
        self.init(uiImage: bild)
        #endif
    }
}
