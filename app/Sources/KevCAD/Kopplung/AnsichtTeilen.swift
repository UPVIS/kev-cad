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
        if kopplung.modus == .eigen && !kopplung.andere.isEmpty {
            Button {
                aktionen?.blickZeigen(!kopplung.blickZeigen)
            } label: {
                if kopplung.blickZeigen {
                    Label(kopplung.blickTitel, systemImage: "checkmark")
                } else {
                    Text(kopplung.blickTitel)
                }
            }
        }
        if let text = kopplung.ansichtText {
            Divider()
            Text(text)
        }
    }
}

/// Eigene Ansicht mit eingeschaltetem Blick: Kapsel unten im Viewer mit Aus-Knopf (Kevins Regel „ruhiger Viewer“: was
/// stehen bleibt, braucht einen sichtbaren Knopf zum Ausblenden; am iPad der einzige Weg ohne Menü).
struct BlickKapsel: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?
    var kompakt = false

    var body: some View {
        if kopplung.blickSichtbar {
            Pill(symbol: "viewfinder", tint: .orange) {
                Text(kompakt ? "Blick" : "Blick: \(kopplung.blickVon.joined(separator: ", "))")
            } trailing: {
                Button {
                    aktionen?.blickZeigen(false)
                } label: {
                    Image(systemName: "xmark")
                        .frame(minWidth: Self.ziel, minHeight: Self.ziel)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Rahmen ausblenden")
                .accessibilityLabel("Rahmen ausblenden")
            }
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    #if os(iOS)
    static let ziel: CGFloat = 34  // für den Finger
    #else
    static let ziel: CGFloat = 20
    #endif
}

/// Beim Sprechen an einem anderen Gerät: was dort gerade gesagt wird, live. Geht mit dem Ende der Sitzung von selbst.
struct FremderTextKapsel: View {
    @ObservedObject var kopplung: KopplungsStore

    var body: some View {
        ForEach(kopplung.fremdeTexte) { t in
            Pill(symbol: "waveform", tint: .accentColor) {
                Text("\(t.geraet): „\(Self.ende(t.text))“")
                    .lineLimit(2)
                    .truncationMode(.head)
            } trailing: {
                EmptyView()
            }
            .frame(maxWidth: 520)
            .transition(.opacity)
        }
    }

    /// Die letzten Wörter zählen: lange Texte vorn kürzen.
    static func ende(_ text: String, hoechstens: Int = 160) -> String {
        text.count <= hoechstens ? text : "…" + String(text.suffix(hoechstens))
    }
}

extension KopplungsStore {
    /// Menüeintrag für den Rahmen: „Zeigen, wohin iPad von Kevin schaut“.
    var blickTitel: String {
        let namen = andere.map(\.anzeigeName)
        return namen.count == 1 ? "Zeigen, wohin \(namen[0]) schaut" : "Zeigen, wohin die anderen Geräte schauen"
    }

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

#endif

/// Menü Ablage › Ansicht mit dem iPad (am iPad: mit dem Mac): dieselben Einträge (beobachtet den Zustand, damit der Haken
/// stimmt). Gemeinsame Menüs für Mac und iPad (Menues/).
struct AnsichtTeilenMenue: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?

    var body: some View {
        Menu(KevCADCommands.ipad ? "Ansicht mit dem Mac" : "Ansicht mit dem iPad") {
            AnsichtTeilenEintraege(kopplung: kopplung, aktionen: aktionen)
        }
        .disabled(aktionen == nil)
    }
}
