import KevCADCore
import SwiftUI

/// Was im Fokus über dem Viewer steht (V5, Zustände a und c im Entwurf): links die Gliederung, in der Mitte die
/// Startzeile des leeren Projekts, unten Kevins Live-Text, rechts unten die Agentenspur. Keine Tafeln, nur Text im
/// Bild. Im schmalen Fenster stehen Agent und Sprechknopf unten untereinander.
struct FokusEbenen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var spur: AgentenSpur
    /// Fläche des Viewers im Fenster
    let viewer: CGRect
    let schmal: Bool

    /// Platz unten für Hinweisleiste und Zeitleiste des Viewers.
    private var untenFrei: CGFloat {
        (model.viewer.hinweisleiste ? 38 : 0) + (model.animation.hasAnimation ? 40 : 0) + GA.l
    }

    private var leer: Bool {
        if model.isRunning || !model.parts.isEmpty { return false }
        if case .failed = model.run { return false }
        return true
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            if !schmal && !model.parts.isEmpty {
                Gliederung(model: model, imBild: true, maxHoehe: max(120, viewer.height * 0.6))
                    .frame(width: GA.gliederung)
                    .padding(.leading, GA.xl)
                    .padding(.top, GA.xl)
                    .frame(width: viewer.width, height: viewer.height, alignment: .topLeading)
            }
            if leer {
                StartZeile(model: model, schmal: schmal)
                    .frame(width: viewer.width, height: viewer.height * 0.62)
            }
            // Text im Bild bleibt über hellen Teilen lesbar: weicher Verlauf statt Tafel
            if oberflaeche.sitzungOffen || !spur.eintraege.isEmpty {
                LinearGradient(colors: [.clear, .black.opacity(0.55)], startPoint: .top, endPoint: .bottom)
                    .frame(height: 170)
                    .padding(.bottom, untenFrei - GA.l)  // endet über Hinweisleiste und Zeitleiste
                    .frame(width: viewer.width, height: viewer.height, alignment: .bottom)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
            unten
                .frame(width: viewer.width, height: viewer.height, alignment: .bottom)
        }
        .frame(width: viewer.width, height: viewer.height, alignment: .topLeading)
        .offset(x: viewer.minX, y: viewer.minY)
    }

    @ViewBuilder
    private var unten: some View {
        if schmal {
            VStack(alignment: .leading, spacing: 10) {
                if oberflaeche.sitzungOffen || oberflaeche.sprechText != nil {
                    LiveText(oberflaeche: oberflaeche, sprache: model.sprache, actions: model.oberflaechenActions,
                             schmal: true)
                }
                AgentZeile(model: model, spur: spur)
                HStack {
                    SprechKnopf(spricht: oberflaeche.spricht) {
                        model.oberflaechenActions?.setzeSprechen(!oberflaeche.spricht)
                    }
                    Spacer()
                    if !model.viewer.hinweisleiste { TastenHinweis(tasten: ["?"], text: "Tasten") }
                }
            }
            .padding(.horizontal, GA.l)
            .padding(.bottom, untenFrei)
        } else {
            ZStack(alignment: .bottomTrailing) {
                if oberflaeche.sitzungOffen || oberflaeche.sprechText != nil {
                    LiveText(oberflaeche: oberflaeche, sprache: model.sprache, actions: model.oberflaechenActions,
                             schmal: false)
                        .frame(maxWidth: max(320, min(860, viewer.width - 680)))
                        .frame(maxWidth: .infinity)
                        .padding(.bottom, untenFrei)
                }
                SpurAnsicht(model: model, spur: spur)
                    .frame(width: 310, alignment: .leading)
                    .padding(.trailing, 26)
                    .padding(.bottom, untenFrei)
            }
            .frame(maxWidth: .infinity, alignment: .bottomTrailing)
        }
    }
}

/// „Was soll entstehen?“ im leeren Projekt.
private struct StartZeile: View {
    @ObservedObject var model: AppModel
    let schmal: Bool

    var body: some View {
        VStack(spacing: 12) {
            Text("Was soll entstehen?")
                .font(schmal ? GS.startSchmal : GS.start)
                .foregroundStyle(GF.kreide.opacity(0.94))
            HStack(spacing: 4) {
                Text("Drück")
                Tastenkappe(text: "V")
                Text("und sag es, oder schreib es im Chat.")
            }
            .font(GS.startZeile)
            .foregroundStyle(GF.asche)
            if !schmal {
                Text("Der Agent baut hier Schritt für Schritt mit.")
                    .font(GS.startZeile)
                    .foregroundStyle(GF.asche)
            }
            if model.kernelState == .starting || model.kernelState == .stopped {
                Text("Kernel startet …")
                    .font(GS.klein)
                    .foregroundStyle(GF.rauch)
                    .padding(.top, 6)
            }
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, GA.l)
        .textImBild()
        .accessibilityElement(children: .combine)
    }
}

/// Zone für Kevins Live-Text: Pegel und Stand, der Text groß wie ein Untertitel, darunter die Tasten. Sie beobachtet
/// `SprachStore`, damit nicht jedes Wort das Hauptfenster neu auswertet.
struct LiveText: View {
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var sprache: SprachStore
    let actions: OberflaechenActions?
    let schmal: Bool

    private var titel: String {
        if sprache.schickt { return "Geht an den Agenten" }
        if oberflaeche.spricht { return "Du sprichst" }
        return oberflaeche.sitzungOffen ? "Angehalten" : "Gesagt"
    }

    private var text: String? { sprache.text ?? oberflaeche.sprechText }

    var body: some View {
        VStack(spacing: schmal ? 8 : 12) {
            HStack(spacing: 10) {
                Pegel(an: oberflaeche.spricht, wert: sprache.pegel)
                Text(titel)
                    .font(GS.text)
                    .foregroundStyle(GF.kevin)
            }
            if let t = text, !t.isEmpty {
                Text(t)
                    .font(schmal ? GS.liveTextSchmal : GS.liveText)
                    .foregroundStyle(GF.kreide)
                    .multilineTextAlignment(.center)
                    .lineLimit(schmal ? 4 : 3)
                    .truncationMode(.head)
            } else if oberflaeche.spricht {
                Text("Sprich einfach, der Text erscheint hier.")
                    .font(schmal ? GS.liveTextSchmal : GS.liveText)
                    .foregroundStyle(GF.rauch)
                    .multilineTextAlignment(.center)
            }
            if oberflaeche.sitzungOffen && !sprache.schickt {
                HStack(spacing: schmal ? 14 : 22) {
                    Button {
                        actions?.sprechenFertig()
                    } label: {
                        TastenHinweis(tasten: ["↩"], text: "fertig")
                    }
                    .buttonStyle(.plain)
                    .help("Text, Zeiger und Striche gehen an den Agenten")
                    Button {
                        actions?.setzeSprechen(!oberflaeche.spricht)
                    } label: {
                        TastenHinweis(tasten: ["V"], text: oberflaeche.spricht ? "aufhören" : "weiter")
                    }
                    .buttonStyle(.plain)
                    Button {
                        actions?.sprechenVerwerfen()
                    } label: {
                        TastenHinweis(tasten: ["esc"], text: "verwerfen")
                    }
                    .buttonStyle(.plain)
                }
                .padding(.top, schmal ? 0 : 4)
            }
        }
        .textImBild()
        .accessibilityElement(children: .contain)
        .accessibilityLabel(titel)
        .accessibilityValue(text ?? "")
    }
}

/// Pegel in Lichtblau: folgt der Lautstärke, solange Kevin spricht.
private struct Pegel: View {
    let an: Bool
    let wert: Float
    private let staerken: [CGFloat] = [0.45, 0.8, 1, 0.6, 0.35]

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<5, id: \.self) { i in
                Capsule()
                    .fill(GF.kevin)
                    .frame(width: 3, height: 16)
                    .scaleEffect(y: an ? max(0.2, staerken[i] * (0.3 + CGFloat(wert) * 1.1)) : 0.2, anchor: .center)
            }
        }
        .frame(height: 16)
        .animation(.easeOut(duration: 0.1), value: wert)
        .accessibilityHidden(true)
    }
}

/// Agentenspur: was der Agent getan hat und gerade tut (bis V2-5 aus der Tätigkeitszeile).
private struct SpurAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var spur: AgentenSpur

    var body: some View {
        if !spur.eintraege.isEmpty || model.agentConnected {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Text("Agent")
                        .font(GS.abschnitt)
                        .foregroundStyle(GF.agent)
                    if !model.agentConnected {
                        Text("nicht verbunden")
                            .font(GS.klein)
                            .foregroundStyle(GF.rauch)
                    }
                }
                ForEach(Array(spur.eintraege.enumerated()), id: \.element.id) { i, e in
                    SpurZeile(eintrag: e, alt: i < spur.eintraege.count - 4 && e.art == .fertig)
                }
            }
            .textImBild()
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Agentenspur")
        }
    }
}

private struct SpurZeile: View {
    let eintrag: SpurEintrag
    let alt: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            zeichen
                .frame(width: 12)
            Text(eintrag.text)
                .font(GS.text)
                .foregroundStyle(farbe)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .opacity(alt ? 0.5 : 1)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var zeichen: some View {
        switch eintrag.art {
        case .fertig:
            Image(systemName: "checkmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(GF.agent.opacity(0.9))
        case .jetzt:
            AtmenderPunkt(farbe: GF.agent)
        case .befund:
            Circle().fill(GF.befund).frame(width: 7, height: 7)
        case .info:
            Circle().fill(GF.rauch).frame(width: 5, height: 5)
        }
    }

    private var farbe: Color {
        switch eintrag.art {
        case .fertig, .info: return GF.asche
        case .jetzt: return GF.agent
        case .befund: return GF.kreide
        }
    }
}

/// Eine Zeile Agent für das schmale Fenster: was er gerade tut, sonst das Letzte.
private struct AgentZeile: View {
    @ObservedObject var model: AppModel
    @ObservedObject var spur: AgentenSpur

    var body: some View {
        if let e = spur.jetzt ?? spur.eintraege.last {
            HStack(spacing: 8) {
                if e.art == .jetzt { AtmenderPunkt(farbe: GF.agent) } else { Circle().fill(GF.rauch).frame(width: 6, height: 6) }
                Text(e.text)
                    .font(GS.text)
                    .foregroundStyle(e.art == .jetzt ? GF.agent : GF.asche)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 4)
                if case .running(let run, _, let schritt) = model.run {
                    Text("Lauf \(run) · Schritt \(schritt)")
                        .font(GS.klein)
                        .foregroundStyle(GF.rauch)
                }
            }
            .textImBild()
            .accessibilityElement(children: .combine)
        }
    }
}
