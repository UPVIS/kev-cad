import SwiftUI

#if os(macOS)
#if os(macOS)
import AppKit
#else
import UIKit
#endif
#else
import UIKit
#endif

// Weichen der Oberfläche für Mac und iPad (Paket I-3a, PLAN-IPAD.md I2 und I4).
//
// Stile, die SwiftUI nur am Mac kennt (Haken, Optionsfelder, Verweis, randloses Menü, Zeilen im Wechsel), bekommen auf dem
// iPad ein Gegenstück unter demselben Namen. So schreibt die gemeinsame Oberfläche sie einmal, und am Mac gilt unverändert
// der Stil von SwiftUI. Vorbild ist `option` für die Wahltaste im Kern (KevCADCore/Plattform).
//
// Das geht nur für Stile, die SwiftUI auf dem iPad als nicht verfügbar führt (der Übersetzer nimmt dann das Gegenstück).
// Kennt SwiftUI den Stil dort nur als veraltet (`.borderlessButton`), wird der Aufruf mehrdeutig: dafür kein Gegenstück.

#if os(iOS)
/// Haken statt Schalter, wie die Checkbox am Mac (`.toggleStyle(.checkbox)`).
struct HakenStil: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(spacing: 6) {
                Image(systemName: configuration.isOn ? "checkmark.square.fill" : "square")
                    .foregroundStyle(configuration.isOn ? Color.accentColor : Color.secondary)
                configuration.label
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

extension ToggleStyle where Self == HakenStil {
    /// Haken (am Mac die Checkbox von SwiftUI).
    static var checkbox: HakenStil { HakenStil() }
}

extension PickerStyle where Self == MenuPickerStyle {
    /// Auswahl als Menü (am Mac Optionsfelder untereinander).
    static var radioGroup: MenuPickerStyle { .menu }
}

extension PrimitiveButtonStyle where Self == BorderlessButtonStyle {
    /// Knopf wie ein Verweis (am Mac `.link`).
    static var link: BorderlessButtonStyle { .borderless }
}

extension MenuStyle where Self == ButtonMenuStyle {
    /// Menü als Knopf mit Rand (am Mac `.borderedButton`). `.borderlessButton` kennt SwiftUI auf dem iPad selbst.
    static var borderedButton: ButtonMenuStyle { .button }
}

extension ListStyle where Self == InsetListStyle {
    /// Liste mit Rahmen (am Mac `.bordered`); auf dem iPad eingerückt.
    static var bordered: InsetListStyle { .inset }
}

extension View {
    /// Zeilen einer Tabelle im Wechsel hinterlegt: gibt es auf dem iPad nicht, die Tabelle bleibt gleichmäßig.
    func alternatingRowBackgrounds() -> some View { self }
}
#endif

extension Color {
    /// Grund von Textfeldern und Listen mit Text (am Mac `textBackgroundColor`).
    static var textfeldGrund: Color {
        #if os(macOS)
        Color(nsColor: .textBackgroundColor)
        #else
        Color(uiColor: .secondarySystemBackground)
        #endif
    }

    /// Grund hinter Seiten und Blättern (am Mac `underPageBackgroundColor`).
    static var seitenGrund: Color {
        #if os(macOS)
        Color(nsColor: .underPageBackgroundColor)
        #else
        Color(uiColor: .systemGray5)
        #endif
    }

    /// Grund von Bedienflächen und Leisten (am Mac `controlBackgroundColor`).
    static var bedienGrund: Color {
        #if os(macOS)
        Color(nsColor: .controlBackgroundColor)
        #else
        Color(uiColor: .secondarySystemBackground)
        #endif
    }

    /// Grund eines Fensters (am Mac `windowBackgroundColor`).
    static var fensterGrund: Color {
        #if os(macOS)
        Color(nsColor: .windowBackgroundColor)
        #else
        Color(uiColor: .systemBackground)
        #endif
    }
}

/// Kurzes Fehlersignal, wenn eine Eingabe nicht geht: am Mac der Systemton, auf dem iPad eine Rückmeldung zum Fühlen.
@MainActor
func fehlerSignal() {
    #if os(macOS)
    NSSound.beep()
    #else
    UINotificationFeedbackGenerator().notificationOccurred(.error)
    #endif
}

/// Sind gerade Umschalt- oder Befehlstaste gedrückt (Auswahl erweitern)? Am Mac aus `NSEvent`; auf dem iPad folgt die
/// Tastatur in I-3b, bis dahin nein.
@MainActor
var auswahlErweitern: Bool {
    #if os(macOS)
    let flags = NSEvent.modifierFlags
    return flags.contains(.shift) || flags.contains(.command)
    #else
    return false
    #endif
}
