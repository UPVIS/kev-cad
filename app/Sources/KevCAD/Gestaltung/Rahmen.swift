#if os(macOS)
import AppKit
#else
import UIKit
#endif
import SwiftUI

// Grundbausteine (3): Grund des Fensters, Kachelrahmen mit Nummer, Overlay-Karte, Statuszeile, Sprechrahmen, Punkte.

/// Grund des Hauptfensters in Graphit: weiches Licht, in der Mitte heller, zum Rand hin tief.
struct GraphitGrund: View {
    var body: some View {
        EllipticalGradient(
            stops: [
                .init(color: GF.hell, location: 0),
                .init(color: GF.mitte, location: 0.44),
                .init(color: GF.tief, location: 1),
            ],
            center: UnitPoint(x: 0.56, y: 0.40), startRadiusFraction: 0, endRadiusFraction: 1.05)
    }
}

/// Nummer einer Kachel. Mit ihr lässt sich jede Kachel per Sprache eindeutig ansprechen („Kachel 2 groß“).
struct KachelNummer: View {
    let nummer: Int
    var aktiv = false

    var body: some View {
        Text(String(nummer))
            .font(GS.kachelNummer)
            .foregroundStyle(aktiv ? GF.tief : GF.kreide)
            .frame(width: 18, height: 18)
            .background(
                RoundedRectangle(cornerRadius: GR.nummer, style: .continuous)
                    .fill(aktiv ? GF.kreide : Color.white.opacity(0.11)))
            .accessibilityLabel("Kachel \(nummer)")
    }
}

/// Rahmen einer Kachel: Kopf mit Nummer, Titel, Untertitel, eigenen Knöpfen, „groß“ und „schließen“. `durchsichtig`
/// lässt die Fläche frei, damit darunter liegende Inhalte (der Viewer) sichtbar und bedienbar bleiben.
struct KachelRahmen<Zusatz: View, Inhalt: View>: View {
    let nummer: Int
    let titel: String
    var untertitel: String?
    var aktiv = false
    var gross = false
    var durchsichtig = false
    let vergroessern: () -> Void
    var schliessen: (() -> Void)?
    var antippen: () -> Void = {}
    @ViewBuilder var zusatz: () -> Zusatz
    @ViewBuilder var inhalt: () -> Inhalt

    private var form: RoundedRectangle { RoundedRectangle(cornerRadius: GR.kachel, style: .continuous) }

    var body: some View {
        VStack(spacing: 0) {
            kopf
                .contentShape(Rectangle())
                .simultaneousGesture(TapGesture().onEnded { antippen() })
            if durchsichtig {
                Spacer(minLength: 0)
            } else {
                inhalt()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()
                    .simultaneousGesture(TapGesture().onEnded { antippen() })
            }
        }
        // Verlangt ein Inhalt mehr Höhe, als die Kachel hat, läuft er unten über (und wird abgeschnitten); der Kopf bleibt
        // oben, statt mit dem Überlauf mittig verschoben zu werden
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background {
            if !durchsichtig { form.fill(Color.white.opacity(0.03)) }
        }
        .clipShape(form)
        .overlay {
            form.strokeBorder(aktiv ? GF.kevin.opacity(0.45) : GF.linie, lineWidth: aktiv ? 1.5 : 1)
                .allowsHitTesting(false)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Kachel \(nummer), \(titel)")
    }

    private var kopf: some View {
        HStack(spacing: GA.s) {
            KachelNummer(nummer: nummer, aktiv: aktiv)
            Text(titel)
                .font(GS.kachelTitel)
                .foregroundStyle(GF.kreide)
                .lineLimit(1)
                .layoutPriority(2)
            if let untertitel {
                Text(untertitel)
                    .font(GS.klein)
                    .foregroundStyle(GF.rauch)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            zusatz()
            Spacer(minLength: GA.s)
            Button(action: vergroessern) {
                Image(systemName: gross ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right")
            }
            .buttonStyle(KevKnopfStil(form: .leise, farbe: GF.asche))
            .help(gross ? "Kachel \(nummer) wieder einordnen" : "Kachel \(nummer) groß")
            .accessibilityLabel(gross ? "Kachel \(nummer) wieder einordnen" : "Kachel \(nummer) groß")
            if let schliessen {
                Button(action: schliessen) { Image(systemName: "xmark") }
                    .buttonStyle(KevKnopfStil(form: .leise, farbe: GF.asche))
                    .help("Kachel \(nummer) schließen")
                    .accessibilityLabel("Kachel \(nummer) schließen")
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .frame(height: GA.kachelKopf)
        .background(durchsichtig ? GF.leiste : Color.clear)
    }
}

/// Karte, die über allem liegt (Startübersicht „Zuletzt geöffnet“): Titel, Knöpfe rechts, Inhalt, leiser Fuß.
struct OverlayKarte<Kopf: View, Inhalt: View>: View {
    let titel: String
    var fuss: String?
    @ViewBuilder var kopf: () -> Kopf
    @ViewBuilder var inhalt: () -> Inhalt

    private var form: RoundedRectangle { RoundedRectangle(cornerRadius: GR.overlay, style: .continuous) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Text(titel)
                    .font(GS.karteTitel)
                    .foregroundStyle(GF.kreide)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: GA.s)
                kopf()
            }
            inhalt()
            if let fuss {
                Text(fuss)
                    .font(GS.klein)
                    .foregroundStyle(GF.rauch)
                    .frame(maxWidth: .infinity)
            }
        }
        .padding(EdgeInsets(top: 16, leading: 18, bottom: 16, trailing: 18))
        .background {
            form.fill(.ultraThinMaterial)
            form.fill(GF.karte)
        }
        .overlay(form.strokeBorder(GF.linie, lineWidth: 1))
        .shadow(color: .black.opacity(0.45), radius: 35, x: 0, y: 26)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(titel)
    }
}

/// Statuszeile der Werkstatt: Knopf zum Sprechen, das zuletzt Gesagte (Lichtblau), die letzte Meldung des Agenten
/// (Messing) und rechts der Stand von Kernel und Lauf.
struct Statuszeile: View {
    let spricht: Bool
    var gesagt: String?
    var agent: String?
    var stand: String?
    var standFarbe: Color = GF.rauch
    let sprechen: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            SprechKnopf(spricht: spricht, aktion: sprechen)
            if let gesagt, !gesagt.isEmpty {
                Text("„\(gesagt)“")
                    .font(GS.text)
                    .foregroundStyle(GF.kevin)
                    .lineLimit(1)
                    .truncationMode(.head)
            }
            if let agent, !agent.isEmpty {
                Text(agent)
                    .font(GS.text)
                    .foregroundStyle(GF.agent)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: GA.s)
            if let stand {
                HStack(spacing: 6) {
                    Circle().fill(standFarbe).frame(width: 6, height: 6)
                    Text(stand)
                        .font(GS.klein)
                        .foregroundStyle(GF.rauch)
                        .lineLimit(1)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(.horizontal, GA.l)
        .frame(height: GA.statuszeile)
    }
}

/// Knopf „V drücken und sprechen“ mit Mikrofon in Lichtblau (am iPad „Sprechen“, ohne Taste).
struct SprechKnopf: View {
    let spricht: Bool
    var kurz = false
    let aktion: () -> Void

    static func text(spricht: Bool) -> String {
        #if os(iOS)
        return spricht ? "Du sprichst · tippen hält an" : "Sprechen"
        #else
        return spricht ? "Du sprichst · V beendet" : "V drücken und sprechen"
        #endif
    }

    var body: some View {
        Button(action: aktion) {
            HStack(spacing: 9) {
                Image(systemName: spricht ? "waveform" : "mic.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(spricht ? GF.aufnahme : GF.kevin)
                    .frame(width: 26, height: 26)
                    .background(Circle().fill((spricht ? GF.aufnahme : GF.kevin).opacity(0.16)))
                if !kurz {
                    Text(Self.text(spricht: spricht))
                        .font(GS.text)
                        .foregroundStyle(GF.kreide)
                        .lineLimit(1)
                }
            }
            .padding(.leading, 5)
            .padding(.trailing, kurz ? 5 : 14)
            .frame(height: 36)
            .background(Capsule().fill(Color.white.opacity(0.07)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .help(spricht ? "Sprechen beenden (V)" : "Sprechen (V)")
        .accessibilityLabel(spricht ? "Sprechen beenden" : "Sprechen")
        .accessibilityAddTraits(spricht ? .isSelected : [])
    }
}

/// Schmaler roter Rahmen um den Viewer, solange Kevin spricht (aus der Richtung „Sucher“).
struct Sprechrahmen: View {
    let an: Bool
    var radius: CGFloat = 0

    var body: some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous)
            .strokeBorder(GF.aufnahme, lineWidth: GA.sprechrahmen)
            .opacity(an ? 1 : 0)
            .animation(GB.kurz, value: an)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}

/// Kleiner Punkt, der „atmet“, solange etwas läuft (Agent arbeitet, Lauf rechnet).
struct AtmenderPunkt: View {
    let farbe: Color
    var groesse: CGFloat = 7
    @State private var hell = false

    var body: some View {
        Circle()
            .fill(farbe)
            .frame(width: groesse, height: groesse)
            .opacity(hell ? 1 : 0.35)
            .onAppear { withAnimation(GB.atmen) { hell = true } }
            .accessibilityHidden(true)
    }
}
