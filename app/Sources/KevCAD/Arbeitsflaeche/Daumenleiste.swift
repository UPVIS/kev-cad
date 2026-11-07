#if os(iOS)
import KevCADCore
import SwiftUI

/// Daumenleiste am iPad (PLAN-IPAD.md 4.5 und 4.6): links unten im Griff des Daumens, der Stift bleibt in der rechten
/// Hand. Sprechen beginnt, hält an und geht weiter (am Mac V), Senden schickt Text, Zeiger und Striche an den Agenten (am
/// Mac ↩). Verwerfen steht in der Zeile mit dem Gesagten. Rückgängig, Wiederholen, Zeichnen mit dem Finger und der
/// Werkzeugkranz kommen mit I-3b und I-4 dazu.
struct Daumenleiste: View {
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var sprache: SprachStore
    let actions: OberflaechenActions?

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
        }
        .animation(GB.standard, value: offen)
        .animation(GB.kurz, value: oberflaeche.spricht)
    }

    private var sprechTitel: String {
        if oberflaeche.spricht { return "Pause" }
        return oberflaeche.sitzungOffen ? "Weiter" : "Sprechen"
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
