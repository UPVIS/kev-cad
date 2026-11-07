import KevCADCore
import SwiftUI

// I-6 Live-Kopplung (PLAN-IPAD.md, Abschnitt 5): Gemeinsame oder Eigene Ansicht wählen und sehen, welches Gerät führt.
// Am Mac als Kapsel in der Kopfleiste und im Menü Ablage, am iPad am Kopplungs-Chip oben (KopplungsAnsicht.swift).
// Zustand: `AppModel.kopplung` (`modus`, `liveGeraete`), Aktion: `KopplungsActions.ansichtModus`.

/// Einträge für die Menüs: die beiden Arten mit Haken, darunter der Stand in Worten.
struct AnsichtTeilenEintraege: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?

    var body: some View {
        Button {
            aktionen?.ansichtModus(.gemeinsam)
        } label: {
            if kopplung.modus == .gemeinsam {
                Label("Gemeinsame Ansicht", systemImage: "checkmark")
            } else {
                Text("Gemeinsame Ansicht")
            }
        }
        Button {
            aktionen?.ansichtModus(.eigen)
        } label: {
            if kopplung.modus == .eigen {
                Label("Eigene Ansicht", systemImage: "checkmark")
            } else {
                Text("Eigene Ansicht")
            }
        }
        if let text = kopplung.ansichtText {
            Divider()
            Text(text)
        }
    }
}

extension KopplungsStore {
    /// Ganz kurz für Kapsel und Chip: „Gemeinsam · iPad führt“, „Gemeinsam · du führst“, „Eigene Ansicht“.
    var kurzText: String {
        if modus == .eigen { return "Eigene Ansicht" }
        if fuehrtSelbst { return "Gemeinsam · du führst" }
        if let f = fuehrendesAnderes { return "Gemeinsam · \(f.anzeigeName) führt" }
        return "Gemeinsame Ansicht"
    }

    /// Punkt vor dem Text: grün, wenn die Ansicht geteilt wird; Agentenfarbe, wenn ein anderes Gerät führt.
    var ansichtPunkt: Color {
        guard teiltMitAnderen else { return GF.rauch }
        return fuehrendesAnderes != nil ? GF.agent : Color.green
    }
}

#if os(macOS)
/// Kapsel in der Kopfleiste, sobald ein anderes Gerät verbunden ist (iPad: der Kopplungs-Chip oben übernimmt das).
struct AnsichtTeilenKapsel: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?

    var body: some View {
        if !kopplung.andere.isEmpty {
            Menu {
                AnsichtTeilenEintraege(kopplung: kopplung, aktionen: aktionen)
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "ipad.landscape").font(GS.klein).foregroundStyle(GF.asche)
                    Circle().fill(kopplung.ansichtPunkt).frame(width: 6, height: 6)
                    Text(kopplung.kurzText).font(GS.klein).foregroundStyle(GF.asche).lineLimit(1)
                }
                .padding(.horizontal, 8)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help(kopplung.ansichtText ?? "Ansicht mit dem anderen Gerät teilen")
            .accessibilityLabel(kopplung.ansichtText ?? kopplung.kurzText)
        }
    }
}

/// Menü Ablage › Ansicht mit dem iPad: dieselben Einträge (beobachtet den Zustand, damit der Haken stimmt).
struct AnsichtTeilenMenue: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?

    var body: some View {
        Menu("Ansicht mit dem iPad") {
            AnsichtTeilenEintraege(kopplung: kopplung, aktionen: aktionen)
        }
        .disabled(aktionen == nil)
    }
}
#endif
