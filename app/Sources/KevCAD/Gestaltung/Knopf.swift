import AppKit
import SwiftUI

// Grundbausteine (1): Knöpfe, Umschalter Fokus/Werkstatt, Tastenkappe. Selbst gezeichnet, aber echte SwiftUI-Knöpfe:
// Tastatursteuerung (Tab, Leertaste), Fokusring des Systems und VoiceOver bleiben erhalten.

typealias GF = Gestaltung.Farbe
typealias GS = Gestaltung.Schrift
typealias GA = Gestaltung.Abstand
typealias GR = Gestaltung.Radius
typealias GB = Gestaltung.Bewegung

/// Form eines Knopfs.
enum KnopfForm {
    /// runder Symbolknopf 34 × 34 (Foto, Video, Messen …)
    case rund
    /// Text mit Symbol, 28 hoch („Ordner öffnen …“)
    case text
    /// Text über die ganze Breite, 28 hoch („Isolieren“, „Zeigen“)
    case breit
    /// ohne Fläche, erst unter dem Zeiger sichtbar (Kopf der Kacheln)
    case leise
}

/// Knopfstil der Oberfläche. `an` markiert eingeschaltete Werkzeuge (Messen an, Isolieren an).
struct KevKnopfStil: ButtonStyle {
    var form: KnopfForm = .text
    var an = false
    /// Farbe des Symbols bzw. Texts; nil = Kreide
    var farbe: Color?

    func makeBody(configuration: Configuration) -> some View {
        KnopfKoerper(label: configuration.label, gedrueckt: configuration.isPressed, form: form, an: an, farbe: farbe)
    }
}

private struct KnopfKoerper<Label: View>: View {
    let label: Label
    let gedrueckt: Bool
    let form: KnopfForm
    let an: Bool
    let farbe: Color?
    @State private var hover = false
    @Environment(\.isEnabled) private var aktiv

    var body: some View {
        inhalt
            .foregroundStyle(farbe ?? GF.kreide)
            .background { flaeche }
            .contentShape(umriss)
            .opacity(aktiv ? 1 : 0.4)
            .onHover { hover = $0 }
            .animation(GB.kurz, value: hover)
            .animation(GB.kurz, value: an)
    }

    @ViewBuilder
    private var inhalt: some View {
        switch form {
        case .rund:
            label.font(.system(size: 14, weight: .medium))
                .frame(width: GA.knopf, height: GA.knopf)
        case .text:
            label.font(GS.text)
                .padding(.horizontal, GA.m)
                .frame(height: GA.knopfText)
        case .breit:
            label.font(GS.klein)
                .frame(maxWidth: .infinity)
                .frame(height: GA.knopfText)
        case .leise:
            label.font(.system(size: 12, weight: .medium))
                .frame(minWidth: 24, minHeight: 24)
                .padding(.horizontal, 2)
        }
    }

    private var grund: Color {
        if gedrueckt { return GF.knopfGedrueckt }
        if an { return GF.knopfAn }
        if hover && aktiv { return form == .leise ? GF.knopf : GF.knopfHover }
        return form == .leise ? .clear : GF.knopf
    }

    private var flaeche: some View { umriss.fill(grund) }

    private var umriss: AnyShape {
        switch form {
        case .rund: return AnyShape(Circle())
        case .text, .breit: return AnyShape(RoundedRectangle(cornerRadius: GR.knopfText, style: .continuous))
        case .leise: return AnyShape(RoundedRectangle(cornerRadius: GR.taste, style: .continuous))
        }
    }
}

/// Runder Symbolknopf mit Hilfe-Text und Beschriftung für VoiceOver.
struct SymbolKnopf: View {
    let symbol: String
    let titel: String
    var taste: String?
    var an = false
    var farbe: Color?
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            Image(systemName: symbol)
        }
        .buttonStyle(KevKnopfStil(form: .rund, an: an, farbe: farbe))
        .help(taste.map { "\(titel) (\($0))" } ?? titel)
        .accessibilityLabel(titel)
        .accessibilityAddTraits(an ? .isSelected : [])
    }
}

/// Knopf „Video aufnehmen“: roter Punkt wie im Entwurf.
struct AufnahmeKnopf: View {
    let laeuft: Bool
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            Group {
                if laeuft {
                    RoundedRectangle(cornerRadius: 2, style: .continuous).frame(width: 10, height: 10)
                } else {
                    Circle().frame(width: 11, height: 11)
                }
            }
            .foregroundStyle(GF.befund)
            .shadow(color: GF.befund.opacity(0.35), radius: 3)
        }
        .buttonStyle(KevKnopfStil(form: .rund, an: laeuft))
        .help(laeuft ? "Video beenden (⌥⌘V)" : "Video aufnehmen (⌥⌘V)")
        .accessibilityLabel(laeuft ? "Video beenden" : "Video aufnehmen")
    }
}

/// Umschalter zwischen zwei oder mehr Werten (Fokus/Werkstatt). Die helle Kapsel gleitet zur Auswahl.
struct ModusUmschalter<Wert: Hashable>: View {
    struct Option: Identifiable {
        let wert: Wert
        let titel: String
        var hilfe: String?
        var id: Wert { wert }
    }

    let optionen: [Option]
    let auswahl: Wert
    var beschriftung = "Modus"
    let waehle: (Wert) -> Void
    @Namespace private var raum

    var body: some View {
        HStack(spacing: 0) {
            ForEach(optionen) { o in
                Button {
                    waehle(o.wert)
                } label: {
                    Text(o.titel)
                        .font(GS.modus)
                        .foregroundStyle(o.wert == auswahl ? GF.kreide : GF.asche)
                        .padding(.horizontal, 11)
                        .padding(.vertical, 4)
                        .background {
                            if o.wert == auswahl {
                                Capsule().fill(GF.modusAn).matchedGeometryEffect(id: "auswahl", in: raum)
                            }
                        }
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .help(o.hilfe ?? o.titel)
                .accessibilityAddTraits(o.wert == auswahl ? .isSelected : [])
            }
        }
        .padding(2)
        .background(Capsule().fill(GF.modusGrund))
        .animation(GB.kurz, value: auswahl)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(beschriftung)
    }
}

/// Tastenkappe für Hinweise („V“, „esc“, „↩“).
struct Tastenkappe: View {
    let text: String

    var body: some View {
        Text(text)
            .font(GS.taste)
            .foregroundStyle(GF.kreide)
            .lineLimit(1)
            .padding(.horizontal, 6)
            .frame(minWidth: GA.taste, minHeight: GA.taste)
            .background(
                RoundedRectangle(cornerRadius: GR.taste, style: .continuous)
                    .fill(GF.taste)
                    .shadow(color: .black.opacity(0.35), radius: 0, x: 0, y: 1))
            .overlay(
                RoundedRectangle(cornerRadius: GR.taste, style: .continuous)
                    .strokeBorder(GF.tasteRand, lineWidth: 0.5))
            .accessibilityLabel(Self.gesprochen(text))
    }

    /// Name der Taste für VoiceOver.
    static func gesprochen(_ t: String) -> String {
        switch t {
        case "↩": return "Zeilenschalter"
        case "esc": return "Escape"
        case "⌘": return "Befehl"
        case "⌥": return "Wahl"
        case "⌃": return "Control"
        case "⇧": return "Umschalt"
        case "→": return "Pfeil rechts"
        case "←": return "Pfeil links"
        default: return t
        }
    }
}

/// Tastenkappen und Erklärung nebeneinander („V drücken und sprechen“).
struct TastenHinweis: View {
    let tasten: [String]
    let text: String

    var body: some View {
        HStack(spacing: 7) {
            HStack(spacing: 3) {
                ForEach(Array(tasten.enumerated()), id: \.offset) { _, t in Tastenkappe(text: t) }
            }
            Text(text)
                .font(GS.klein)
                .foregroundStyle(GF.asche)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
    }
}
