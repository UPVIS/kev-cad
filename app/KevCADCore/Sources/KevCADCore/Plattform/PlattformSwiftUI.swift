import SwiftUI

// SwiftUI-Weichen des Kerns (Paket I-1): Modifikatoren, die es nur am Mac gibt, unter einem Namen für beide Seiten.

extension View {
    /// Esc schließt: am Mac `onExitCommand`. iPad: Esc einer Hardware-Tastatur folgt in I-3; bis dahin schließen die
    /// Ansichten dort über Berührung (Tippen daneben, Knopf).
    func beiEsc(_ aktion: @escaping () -> Void) -> some View {
        #if os(macOS)
        onExitCommand(perform: aktion)
        #else
        self
        #endif
    }
}
