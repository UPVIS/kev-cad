import AppKit
import KevCADCore
import SwiftUI

extension KachelArt {
    var symbol: String {
        switch self {
        case .modell: return "cube"
        case .zeichnung: return "doc.text"
        case .bauplan: return "list.number"
        case .stueckliste: return "list.bullet.rectangle"
        case .zuschnitt: return "ruler"
        case .druck: return "printer"
        case .animation: return "film"
        case .render: return "camera.aperture"
        case .ansicht: return "square.split.2x1"
        case .material: return "shippingbox"
        case .simulation: return "gauge.with.needle"
        case .versionen: return "clock.arrow.circlepath"
        case .details: return "info.circle"
        }
    }

    /// Bereich der bisherigen Oberfläche, der zu dieser Kachel gehört (für Menübefehle und Selbsttests).
    var bereich: ProjektBereich {
        switch self {
        case .zeichnung, .bauplan: return .dokumente
        case .material: return .material
        case .simulation: return .simulation
        default: return .modell
        }
    }
}

/// Anordnung der Kacheln wie in einem Fenstermanager: eine füllt alles, zwei nebeneinander (im Hochformat
/// übereinander), drei mit der ersten groß links und zwei rechts übereinander, vier im Raster. Eine große Kachel füllt
/// die Fläche allein. Die Animation ist eine Zeitleiste: ein Streifen unten über die ganze Breite, darüber der Rest; groß
/// bleibt sie mit dem Modell zusammen, weil man die Bewegung dort sieht.
enum KachelAnordnung {
    /// Höhe des Streifens: Unter dieser Breite steht die Zeitleiste zweizeilig.
    static let zeitleisteEinzeiligAb: CGFloat = 760

    static func zeitleisteHoehe(breite: CGFloat) -> CGFloat {
        GA.kachelKopf + (breite >= zeitleisteEinzeiligAb ? 60 : 100)
    }

    static func rahmen(_ kacheln: [KachelArt], gross: KachelArt?, in f: CGRect, abstand a: CGFloat = GA.rand)
        -> [KachelArt: CGRect]
    {
        if kacheln.contains(.animation), gross == nil || gross == .animation || gross == .modell {
            let rest = kacheln.filter { $0 != .animation && (gross == nil || $0 == .modell) }
            if rest.isEmpty { return [.animation: f] }
            let h = zeitleisteHoehe(breite: f.width)
            let oben = CGRect(x: f.minX, y: f.minY, width: f.width, height: max(1, f.height - h - a))
            var r = rahmen(rest, gross: nil, in: oben, abstand: a)
            r[.animation] = CGRect(x: f.minX, y: f.maxY - h, width: f.width, height: h)
            return r
        }
        if let g = gross, kacheln.contains(g) { return [g: f] }
        var r: [KachelArt: CGRect] = [:]
        let quer = f.width >= f.height * 1.1
        switch kacheln.count {
        case 0:
            break
        case 1:
            r[kacheln[0]] = f
        case 2:
            if quer {
                let w = (f.width - a) / 2
                r[kacheln[0]] = CGRect(x: f.minX, y: f.minY, width: w, height: f.height)
                r[kacheln[1]] = CGRect(x: f.minX + w + a, y: f.minY, width: w, height: f.height)
            } else {
                let h = (f.height - a) / 2
                r[kacheln[0]] = CGRect(x: f.minX, y: f.minY, width: f.width, height: h)
                r[kacheln[1]] = CGRect(x: f.minX, y: f.minY + h + a, width: f.width, height: h)
            }
        case 3:
            if quer {
                let w1 = ((f.width - a) * 0.56).rounded()
                let w2 = f.width - a - w1
                let h = (f.height - a) / 2
                r[kacheln[0]] = CGRect(x: f.minX, y: f.minY, width: w1, height: f.height)
                r[kacheln[1]] = CGRect(x: f.minX + w1 + a, y: f.minY, width: w2, height: h)
                r[kacheln[2]] = CGRect(x: f.minX + w1 + a, y: f.minY + h + a, width: w2, height: h)
            } else {
                let h1 = ((f.height - a) * 0.56).rounded()
                let h2 = f.height - a - h1
                let w = (f.width - a) / 2
                r[kacheln[0]] = CGRect(x: f.minX, y: f.minY, width: f.width, height: h1)
                r[kacheln[1]] = CGRect(x: f.minX, y: f.minY + h1 + a, width: w, height: h2)
                r[kacheln[2]] = CGRect(x: f.minX + w + a, y: f.minY + h1 + a, width: w, height: h2)
            }
        default:
            let w = (f.width - a) / 2, h = (f.height - a) / 2
            for (i, k) in kacheln.prefix(4).enumerated() {
                let x = f.minX + CGFloat(i % 2) * (w + a), y = f.minY + CGFloat(i / 2) * (h + a)
                r[k] = CGRect(x: x, y: y, width: w, height: h)
            }
        }
        return r
    }
}

/// Kachelfläche der Werkstatt. Die Kachel „Modell“ ist durchsichtig: Der Viewer liegt darunter (er wird nie neu
/// angelegt, nur verschoben). Alle anderen Kacheln betten die vorhandenen Ansichten ein.
struct KachelFlaeche: View {
    // Beobachtet nur die Oberfläche: Eine Änderung am Modell soll die schweren Ansichten nicht neu vermessen. Was im
    // Kopf einer Kachel vom Modell abhängt, steht in `KachelKopfZusatz`.
    let model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    let state: ProjectWindowState
    let versionen: VersionenZustand
    let dokumente: DokumenteZustand
    let rahmen: [KachelArt: CGRect]
    let navigation: MaterialNavigation
    let zeigeIm3D: ([String]) -> Void

    /// Letzter Rahmen je Kachel: Während eine andere groß ist, bleiben die übrigen in dieser Größe eingehängt und nur
    /// ausgeblendet, damit „alle einordnen“ nichts neu aufbaut.
    @State private var zuletzt: [KachelArt: CGRect] = [:]

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(oberflaeche.kacheln) { art in
                if let r = rahmen[art] ?? zuletzt[art] {
                    let sichtbar = rahmen[art] != nil
                    kachel(art, breite: r.width)
                        .frame(width: r.width, height: r.height)
                        .position(x: r.midX, y: r.midY)
                        .opacity(sichtbar ? 1 : 0)
                        .allowsHitTesting(sichtbar)
                        .accessibilityHidden(!sichtbar)
                        .transition(.opacity)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .onAppear { zuletzt = rahmen }
        .onChange(of: rahmen) { _, neu in zuletzt.merge(neu) { _, n in n } }
    }

    private func kachel(_ art: KachelArt, breite: CGFloat) -> some View {
        let nummer = oberflaeche.nummer(art) ?? 0
        let gross = oberflaeche.gross == art
        return KachelRahmen(
            nummer: nummer, titel: art.titel, aktiv: oberflaeche.aktiv == art,
            gross: gross, durchsichtig: art == .modell,
            vergroessern: { model.oberflaechenActions?.vergroessereKachel(gross ? nil : art) },
            schliessen: { model.oberflaechenActions?.schliesseKachel(art) },
            antippen: { if oberflaeche.aktiv != art { model.oberflaechenActions?.oberflaeche(.kachelAktiv(art)) } },
            zusatz: { KachelKopfZusatz(art: art, model: model, oberflaeche: oberflaeche, dokumente: dokumente) },
            inhalt: { KachelInhalt(art: art, breit: breite >= 880 || gross, model: model, state: state,
                                   versionen: versionen, dokumente: dokumente, navigation: navigation,
                                   zeigeIm3D: zeigeIm3D)
                .equatable() })
    }

}

/// Rechts neben dem Titel einer Kachel: Untertitel (gewähltes Teil, Blatt 1 von 2 …) und Blattmenü.
private struct KachelKopfZusatz: View {
    let art: KachelArt
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var dokumente: DokumenteZustand

    var body: some View {
        if let t = untertitel(art) {
            Text(t)
                .font(GS.klein)
                .foregroundStyle(GF.rauch)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        zusatz(art)
    }

    private func untertitel(_ art: KachelArt) -> String? {
        switch art {
        case .modell:
            let ids = model.selectedPartIDs
            if let erst = ids.first {
                let name = erst.split(separator: "/").last.map(String.init) ?? erst
                return ids.count == 1 ? "\(name) gewählt" : "\(KevFormat.integer(ids.count)) Teile gewählt"
            }
            return model.parts.isEmpty ? nil : KevFormat.count(model.parts.count, one: "Teil", many: "Teile")
        case .zeichnung:
            guard let u = model.dokumente.uebersicht, !u.blaetter.isEmpty else { return nil }
            if let id = dokumente.blattID, let i = u.blaetter.firstIndex(where: { $0.id == id }) {
                return "Blatt \(i + 1) von \(u.blaetter.count)"
            }
            return KevFormat.count(u.blaetter.count, one: "Blatt", many: "Blätter")
        case .bauplan:
            guard let n = model.dokumente.uebersicht?.bauplan?.schritte, n > 0 else { return nil }
            return KevFormat.count(n, one: "Schritt", many: "Schritte")
        case .stueckliste:
            guard let bom = model.bom else { return nil }
            return KevFormat.count(bom.totals.positionen, one: "Position", many: "Positionen")
        default:
            return nil
        }
    }

    @ViewBuilder
    private func zusatz(_ art: KachelArt) -> some View {
        if art == .zeichnung, let u = model.dokumente.uebersicht, !u.blaetter.isEmpty {
            // V2-10: Das Blatt folgt Auswahl, Agent und Zeigen beim Sprechen; die Nadel hält es fest
            let fest = !oberflaeche.blattFolgt
            Button {
                model.oberflaechenActions?.oberflaeche(.blattFolgt(fest))
            } label: {
                Image(systemName: fest ? "pin.fill" : "pin")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(fest ? GF.kreide : GF.asche)
                    .frame(width: 18, height: 18)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(fest ? "Blatt ist festgehalten. Klicken: Blatt folgt wieder dem, wovon die Rede ist"
                       : "Blatt folgt Auswahl, Agent und Zeigen. Klicken: dieses Blatt festhalten")
            .accessibilityLabel(fest ? "Blatt festgehalten" : "Blatt folgt dem Zusammenhang")
            if u.blaetter.count > 1 {
                BlattSchritt(symbol: "chevron.left", hilfe: "Voriges Blatt") { blattWechseln(u, um: -1) }
                BlattSchritt(symbol: "chevron.right", hilfe: "Nächstes Blatt") { blattWechseln(u, um: 1) }
            }
            Menu {
                ForEach(u.blaetter) { b in
                    Button(b.titel) { dokumente.waehle(.blatt(b.id)) }
                }
                Divider()
                Button("Bauplan") { model.oberflaechenActions?.zeigeKachel(.bauplan) }
                Button("Berichte") { dokumente.waehle(.berichte) }
            } label: {
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(GF.asche)
                    .frame(width: 18, height: 18)
                    .contentShape(Rectangle())
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Blatt wählen")
        }
    }

    private func blattWechseln(_ u: DocsUebersicht, um schritt: Int) {
        let i = dokumente.blattID.flatMap { id in u.blaetter.firstIndex { $0.id == id } } ?? -schritt
        let neu = (i + schritt + u.blaetter.count) % u.blaetter.count
        dokumente.waehle(.blatt(u.blaetter[neu].id))
    }
}

/// Voriges oder nächstes Blatt im Kopf der Kachel.
private struct BlattSchritt: View {
    let symbol: String
    let hilfe: String
    let aktion: () -> Void

    var body: some View {
        Button(action: aktion) {
            Image(systemName: symbol)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(GF.asche)
                .frame(width: 18, height: 18)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(hilfe)
        .accessibilityLabel(hilfe)
    }
}

/// Inhalt einer Kachel: die vorhandenen Ansichten der Bereiche, eingebettet statt neu geschrieben.
///
/// Gleich, solange Art und Breite gleich sind: Die Closures von außen sind bei jeder Auswertung neu, und SwiftUI baute
/// sonst bei jeder Änderung an Kacheln oder Fenstergröße alle Tabellen neu auf (gemessen bis 7 s Pause). Was sich im
/// Inhalt ändert, beobachten die Ansichten selbst.
private struct KachelInhalt: View, Equatable {
    static func == (a: KachelInhalt, b: KachelInhalt) -> Bool { a.art == b.art && a.breit == b.breit }

    let art: KachelArt
    let breit: Bool
    let model: AppModel
    let state: ProjectWindowState
    let versionen: VersionenZustand
    @ObservedObject var dokumente: DokumenteZustand
    let navigation: MaterialNavigation
    let zeigeIm3D: ([String]) -> Void

    var body: some View {
        switch art {
        case .modell:
            Color.clear
        case .zeichnung:
            HStack(spacing: 0) {
                NebenSpalte(an: breit || dokumente.auswahl == nil, breite: 230, kante: .trailing) {
                    DokumenteSeitenleiste(model: model, store: model.dokumente, zustand: dokumente)
                }
                DokumenteBereich(model: model, store: model.dokumente, zustand: dokumente)
                NebenSpalte(an: breit, breite: 280, kante: .leading) { dokumenteInspektor }
            }
        case .bauplan:
            HStack(spacing: 0) {
                BauplanBereich(model: model)
                NebenSpalte(an: breit, breite: 280, kante: .leading) { BauplanInspektor(model: model) }
            }
        case .stueckliste:
            MaterialDatenKachel(model: model) { daten in
                if breit {
                    MaterialStuecklisteAnsicht(model: model, material: state.materialZustand, daten: daten,
                                               navigation: navigation, zeigeIm3D: zeigeIm3D)
                } else {
                    StuecklisteKompaktTabelle(model: model, daten: daten, navigation: navigation)
                }
            }
        case .zuschnitt:
            MaterialDatenKachel(model: model) { daten in
                MaterialZuschnittAnsicht(model: model, material: state.materialZustand, daten: daten,
                                         navigation: navigation)
            }
        case .druck:
            DruckAnsicht(model: model, eingebettet: true)
        case .animation:
            AnimationTimeline(model: model, animation: model.animation)
                .padding(EdgeInsets(top: 4, leading: GA.m, bottom: GA.s, trailing: GA.m))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        case .render:
            RenderDialog(model: model, store: model.render)
        case .ansicht:
            ZweiteAnsichtKachel(actions: model.oberflaechenActions, oberflaeche: model.oberflaeche)
        case .material:
            HStack(spacing: 0) {
                NebenSpalte(an: breit, breite: 220, kante: .trailing) {
                    MaterialSeitenleiste(model: model, material: state.materialZustand, navigation: navigation)
                }
                MaterialBereich(model: model, material: state.materialZustand, navigation: navigation,
                                zeigeIm3D: zeigeIm3D)
                NebenSpalte(an: breit, breite: 280, kante: .leading) {
                    MaterialInspektor(model: model, material: state.materialZustand, navigation: navigation,
                                      zeigeIm3D: zeigeIm3D)
                }
            }
        case .simulation:
            HStack(spacing: 0) {
                SimulationSeitenleiste(model: model, store: model.simulation, zustand: state.simulationZustand)
                    .frame(width: breit ? 240 : 200)
                Divider()
                if breit {
                    SimulationErgebnisAnsicht(model: model, store: model.simulation, statik: model.statik,
                                              zustand: state.simulationZustand)
                    Divider()
                }
                SimulationInspektor(model: model, store: model.simulation, zustand: state.simulationZustand)
                    .frame(maxWidth: breit ? 300 : .infinity)
            }
        case .versionen:
            VersionenLeiste(model: model, store: model.versionen, zustand: versionen)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        case .details:
            InspectorView(model: model, state: state)
        }
    }

    @ViewBuilder
    private var dokumenteInspektor: some View {
        switch dokumente.auswahl {
        case .bauplan: BauplanInspektor(model: model)
        case .berichte: BerichteInspektor(model: model)
        default: BlattInspektor(model: model, store: model.dokumente, zustand: dokumente)
        }
    }
}

/// Seitenleiste oder Inspektor einer breiten Kachel. Sie baut sich kurz nach dem Öffnen unsichtbar auf und behält ihre
/// Breite: „Kachel groß“ gibt ihr nur noch Platz, statt Listen neu aufzubauen (gemessen 118 bis 142 ms, Grenze 100 ms).
private struct NebenSpalte<Inhalt: View>: View {
    let an: Bool
    let breite: CGFloat
    let kante: HorizontalEdge
    @ViewBuilder let inhalt: () -> Inhalt
    @State private var vorgebaut = false

    var body: some View {
        HStack(spacing: 0) {
            if an || vorgebaut {
                if kante == .leading { Divider() }
                inhalt().frame(width: breite)
                if kante == .trailing { Divider() }
            }
        }
        .frame(width: an ? breite + 1 : 0, alignment: kante == .leading ? .leading : .trailing)
        .clipped()
        .opacity(an ? 1 : 0)
        .allowsHitTesting(an)
        .accessibilityHidden(!an)
        .task {
            try? await Task.sleep(for: .seconds(1))
            vorgebaut = true
        }
    }
}

/// Stückliste und Zuschnitt: `materialDaten` nur neu, wenn sich Stückliste, Bestand oder Katalog ändern, nicht bei jeder
/// Änderung am Modell. `@Published` meldet vor dem Setzen, deshalb liest die Kachel erst im nächsten Takt.
private struct MaterialDatenKachel<Inhalt: View>: View {
    let model: AppModel
    @ViewBuilder let inhalt: (MaterialDaten) -> Inhalt
    @State private var daten: MaterialDaten?

    var body: some View {
        Group {
            if let daten { inhalt(daten) } else { Color.clear }
        }
        .onAppear { daten = model.materialDaten }
        .onReceive(model.$bom.dropFirst()) { _ in neu() }
        .onReceive(model.$bestandZustand.dropFirst()) { _ in neu() }
        .onReceive(model.$catalog.dropFirst()) { _ in neu() }
    }

    private func neu() {
        DispatchQueue.main.async { daten = model.materialDaten }
    }
}

/// Kachel „zweite Ansicht“ (V2-10): ein zweiter Viewer mit eigener Kamera und denselben Griffen wie der Hauptviewer
/// (Drehen, Verschieben, Zoomen, Auswählen, Messen, Zeichnen beim Sprechen, Ziffernblock). Der Umschalter stellt eine
/// Standardrichtung ein und passt ein; danach navigiert Kevin frei. Der Agent stellt die Richtung mit
/// `view(zweite_ansicht=…)`.
private struct ZweiteAnsichtKachel: View {
    @EnvironmentObject private var session: AppSession
    let actions: OberflaechenActions?
    @ObservedObject var oberflaeche: OberflaechenStore

    private static let wahl: [(String, String)] = [
        ("top", "Oben"), ("front", "Vorn"), ("right", "Rechts"), ("left", "Links"), ("back", "Hinten"), ("iso", "Iso"),
    ]

    var body: some View {
        ZStack(alignment: .topLeading) {
            if let controller = session.controller {
                ZweiterViewerAnsicht(controller: controller)
            } else {
                Text("Die zweite Ansicht braucht den App-Kern")
                    .font(GS.text)
                    .foregroundStyle(GF.rauch)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            ModusUmschalter(
                optionen: Self.wahl.map { ModusUmschalter<String>.Option(wert: $0.0, titel: $0.1) },
                auswahl: oberflaeche.zweiteAnsicht, beschriftung: "Blickrichtung"
            ) { actions?.oberflaeche(.zweiteAnsicht($0)) }
            .padding(10)
        }
    }
}
