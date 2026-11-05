import AppKit
import KevCADCore
import SwiftUI

extension KachelArt {
    var titel: String {
        switch self {
        case .modell: return "Modell"
        case .zeichnung: return "Zeichnung"
        case .stueckliste: return "Stückliste"
        case .zuschnitt: return "Zuschnitt"
        case .ansicht: return "Zweite Ansicht"
        case .material: return "Material"
        case .simulation: return "Simulation"
        case .versionen: return "Versionen"
        case .details: return "Details"
        }
    }

    var symbol: String {
        switch self {
        case .modell: return "cube"
        case .zeichnung: return "doc.text"
        case .stueckliste: return "list.bullet.rectangle"
        case .zuschnitt: return "ruler"
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
        case .zeichnung: return .dokumente
        case .material, .stueckliste, .zuschnitt: return .material
        case .simulation: return .simulation
        default: return .modell
        }
    }

    /// Tastenkürzel ⌃⌘ plus Ziffer im Menü „Kacheln“.
    var kuerzel: KeyEquivalent? {
        switch self {
        case .zeichnung: return "d"
        case .stueckliste: return "b"
        case .zuschnitt: return "u"
        case .ansicht: return "a"
        case .material: return "m"
        case .simulation: return "i"
        case .versionen: return "v"
        case .details: return "e"
        case .modell: return nil
        }
    }
}

/// Anordnung der Kacheln wie in einem Fenstermanager: eine füllt alles, zwei nebeneinander (im Hochformat
/// übereinander), drei mit der ersten groß links und zwei rechts übereinander, vier im Raster. Eine große Kachel füllt
/// die Fläche allein.
enum KachelAnordnung {
    static func rahmen(_ kacheln: [KachelArt], gross: KachelArt?, in f: CGRect, abstand a: CGFloat = GA.rand)
        -> [KachelArt: CGRect]
    {
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
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var state: ProjectWindowState
    @ObservedObject var versionen: VersionenZustand
    @ObservedObject var dokumente: DokumenteZustand
    let rahmen: [KachelArt: CGRect]
    let navigation: MaterialNavigation
    let zeigeIm3D: ([String]) -> Void

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(oberflaeche.kacheln) { art in
                if let r = rahmen[art] {
                    kachel(art, breite: r.width)
                        .frame(width: r.width, height: r.height)
                        .position(x: r.midX, y: r.midY)
                        .transition(.opacity)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func kachel(_ art: KachelArt, breite: CGFloat) -> some View {
        let nummer = oberflaeche.nummer(art) ?? 0
        let gross = oberflaeche.gross == art
        return KachelRahmen(
            nummer: nummer, titel: art.titel, untertitel: untertitel(art), aktiv: oberflaeche.aktiv == art,
            gross: gross, durchsichtig: art == .modell,
            vergroessern: { model.oberflaechenActions?.vergroessereKachel(gross ? nil : art) },
            schliessen: { model.oberflaechenActions?.schliesseKachel(art) },
            antippen: { if oberflaeche.aktiv != art { model.oberflaechenActions?.oberflaeche(.kachelAktiv(art)) } },
            zusatz: { zusatz(art) },
            inhalt: { KachelInhalt(art: art, breit: breite >= 880 || gross, model: model, state: state,
                                   versionen: versionen, dokumente: dokumente, navigation: navigation,
                                   zeigeIm3D: zeigeIm3D) })
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
            Menu {
                ForEach(u.blaetter) { b in
                    Button(b.titel) { dokumente.waehle(.blatt(b.id)) }
                }
                Divider()
                Button("Bauplan") { dokumente.waehle(.bauplan) }
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
}

/// Inhalt einer Kachel: die vorhandenen Ansichten der Bereiche, eingebettet statt neu geschrieben.
private struct KachelInhalt: View {
    let art: KachelArt
    let breit: Bool
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    @ObservedObject var versionen: VersionenZustand
    @ObservedObject var dokumente: DokumenteZustand
    let navigation: MaterialNavigation
    let zeigeIm3D: ([String]) -> Void

    var body: some View {
        switch art {
        case .modell:
            Color.clear
        case .zeichnung:
            HStack(spacing: 0) {
                if breit {
                    DokumenteSeitenleiste(model: model, store: model.dokumente, zustand: dokumente)
                        .frame(width: 230)
                    Divider()
                }
                DokumenteBereich(model: model, store: model.dokumente, zustand: dokumente)
                if breit {
                    Divider()
                    dokumenteInspektor
                        .frame(width: 280)
                }
            }
        case .stueckliste:
            if breit {
                MaterialStuecklisteAnsicht(model: model, material: state.materialZustand, daten: model.materialDaten,
                                           navigation: navigation, zeigeIm3D: zeigeIm3D)
            } else {
                StuecklisteKompaktTabelle(model: model, daten: model.materialDaten, navigation: navigation)
            }
        case .zuschnitt:
            MaterialZuschnittAnsicht(model: model, material: state.materialZustand, daten: model.materialDaten,
                                     navigation: navigation)
        case .ansicht:
            ZweiteAnsichtKachel(model: model)
        case .material:
            HStack(spacing: 0) {
                if breit {
                    MaterialSeitenleiste(model: model, material: state.materialZustand, navigation: navigation)
                        .frame(width: 220)
                    Divider()
                }
                MaterialBereich(model: model, material: state.materialZustand, navigation: navigation,
                                zeigeIm3D: zeigeIm3D)
                if breit {
                    Divider()
                    MaterialInspektor(model: model, material: state.materialZustand, navigation: navigation,
                                      zeigeIm3D: zeigeIm3D)
                        .frame(width: 280)
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

/// Kachel „zweite Ansicht“: eine Standardansicht des Modells als Bild, nach jedem Lauf neu gerechnet. Platzhalter,
/// bis V2-4 eine zweite, lebende Ansicht liefert.
private struct ZweiteAnsichtKachel: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @AppStorage("kachel.ansicht") private var ansicht = StandardViewName.top.rawValue
    @State private var bild: CGImage?
    @State private var groesse: CGSize = .zero

    private static let wahl: [(StandardViewName, String)] = [
        (.top, "Oben"), (.front, "Vorn"), (.right, "Rechts"), (.left, "Links"), (.back, "Hinten"), (.iso, "Iso"),
    ]

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topTrailing) {
                if let bild {
                    Image(decorative: bild, scale: 2)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: geo.size.width, height: geo.size.height)
                } else {
                    Text(model.parts.isEmpty ? "Noch keine Teile" : "Ansicht wird gerechnet …")
                        .font(GS.text)
                        .foregroundStyle(GF.rauch)
                        .frame(width: geo.size.width, height: geo.size.height)
                }
                ModusUmschalter(
                    optionen: Self.wahl.map { ModusUmschalter<String>.Option(wert: $0.0.rawValue, titel: $0.1) }, auswahl: ansicht,
                    beschriftung: "Blickrichtung"
                ) { ansicht = $0 }
                .padding(10)
            }
            .onAppear { groesse = geo.size; rechnen() }
            .onChange(of: geo.size) { _, s in
                groesse = s
                rechnen()
            }
        }
        .onChange(of: ansicht) { _, _ in rechnen() }
        .onChange(of: model.run) { _, r in if case .finished = r { rechnen() } }
        .onChange(of: model.parts.count) { _, _ in rechnen() }
    }

    private func rechnen() {
        guard let c = session.controller, groesse.width > 20, groesse.height > 20,
              let v = StandardViewName(rawValue: ansicht)
        else { return }
        bild = c.zweiteAnsicht(v, breite: Int(groesse.width * 2), hoehe: Int(groesse.height * 2))
    }
}
