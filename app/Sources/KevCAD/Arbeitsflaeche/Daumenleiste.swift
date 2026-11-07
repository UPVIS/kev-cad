#if os(iOS)
import KevCADCore
import SwiftUI

/// Daumenleiste am iPad (PLAN-IPAD.md 4.5 und 4.6): links unten im Griff des Daumens, der Stift bleibt in der rechten
/// Hand. Sprechen beginnt, hält an und geht weiter (am Mac V), Senden schickt Text, Zeiger und Striche an den Agenten (am
/// Mac ↩). Verwerfen steht in der Zeile mit dem Gesagten und als X am roten Rahmen. Darunter Rückgängig und Wiederholen
/// für Ansicht, Auswahl und Sichtbarkeit (am Mac ⌘Z und ⇧⌘Z, hier auch 2 und 3 Finger tippen). Zeichnen mit dem Finger
/// und der Werkzeugkranz kommen mit I-4 dazu.
struct Daumenleiste: View {
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var sprache: SprachStore
    @ObservedObject var viewer: ViewerStore
    let actions: OberflaechenActions?
    let viewerActions: ViewerActions?

    private var offen: Bool { oberflaeche.sitzungOffen && !sprache.schickt }

    var body: some View {
        VStack(spacing: GA.m) {
            if offen {
                DaumenKnopf(titel: "Senden", symbol: "paperplane.fill", farbe: GF.kevin, gefuellt: true, groesse: 54) {
                    actions?.sprechenFertig()
                }
                .transition(.scale(scale: 0.6).combined(with: .opacity))
                .accessibilityHint("Text, Zeiger und Striche gehen an den Agenten")
            }
            DaumenKnopf(titel: sprechTitel, symbol: oberflaeche.spricht ? "pause.fill" : "mic.fill",
                        farbe: oberflaeche.spricht ? GF.aufnahme : GF.kevin, gefuellt: false, groesse: 64) {
                actions?.setzeSprechen(!oberflaeche.spricht)
            }
            .accessibilityAddTraits(oberflaeche.spricht ? .isSelected : [])
            HStack(spacing: GA.s) {
                VerlaufKnopf(symbol: "arrow.uturn.backward", titel: "Rückgängig", moeglich: viewer.rueckgaengigTitel) {
                    viewerActions?.ausfuehren(.rueckgaengig)
                }
                VerlaufKnopf(symbol: "arrow.uturn.forward", titel: "Wiederholen", moeglich: viewer.wiederholenTitel) {
                    viewerActions?.ausfuehren(.wiederholen)
                }
            }
        }
        .animation(GB.standard, value: offen)
        .animation(GB.kurz, value: oberflaeche.spricht)
    }

    private var sprechTitel: String {
        if oberflaeche.spricht { return "Pause" }
        return oberflaeche.sitzungOffen ? "Weiter" : "Sprechen"
    }
}

/// Kleiner runder Knopf für Rückgängig und Wiederholen (44 pt, das Mindestmaß für den Finger). Blass, solange nichts da
/// ist; tippen geht trotzdem: Eine Änderung der letzten Augenblicke zählt dann schon mit (AnsichtsVerlauf.swift).
private struct VerlaufKnopf: View {
    let symbol: String
    let titel: String
    let moeglich: String?
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            Image(systemName: symbol)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(GF.kreide.opacity(moeglich == nil ? 0.35 : 0.9))
                .frame(width: 44, height: 44)
                .background(Circle().fill(Color.white.opacity(0.08)))
                .overlay(Circle().strokeBorder(Color.white.opacity(0.12), lineWidth: 1))
                .shadow(color: .black.opacity(0.35), radius: 6, y: 2)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(titel)
        .accessibilityValue(moeglich ?? "")
        .accessibilityIdentifier(titel == "Rückgängig" ? "daumen.rueckgaengig" : "daumen.wiederholen")
    }
}

/// Runder Knopf mit Beschriftung darunter, groß genug für den Daumen.
private struct DaumenKnopf: View {
    let titel: String
    let symbol: String
    let farbe: Color
    let gefuellt: Bool
    let groesse: CGFloat
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            VStack(spacing: 6) {
                Image(systemName: symbol)
                    .font(.system(size: groesse * 0.36, weight: .semibold))
                    .foregroundStyle(gefuellt ? GF.tief : farbe)
                    .frame(width: groesse, height: groesse)
                    .background(Circle().fill(gefuellt ? farbe : farbe.opacity(0.18)))
                    .overlay(Circle().strokeBorder(farbe.opacity(gefuellt ? 0 : 0.45), lineWidth: 1))
                    .shadow(color: .black.opacity(0.35), radius: 8, y: 3)
                Text(titel)
                    .font(GS.klein)
                    .foregroundStyle(GF.kreide)
                    .lineLimit(1)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(titel)
    }
}
#endif
