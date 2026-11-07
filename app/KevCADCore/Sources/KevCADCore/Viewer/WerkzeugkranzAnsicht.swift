#if os(macOS)
import AppKit
#endif
import SwiftUI

/// I-4 (PLAN-IPAD.md 4.4): Der Werkzeugkranz im Viewport. Eine milchige Scheibe; innen die Strichfarben um die aktuelle
/// Farbe, außen acht Felder; ein Feld mit Unterpunkten öffnet einen zweiten Ring, ein Regler wird zum Ziffernblatt.
///
/// Bedienung auf beiden Geräten gleich: Tippen auf ein Feld oder in seine Richtung wischen; Abheben übernimmt, Wischen in
/// die Mitte oder ein Tipp daneben bricht ab. Beim Wischen öffnet ein Feld mit Unterpunkten seinen Ring sofort (wie ein
/// Markierungsmenü), Schweben (Stift, Maus) hebt hervor und nennt den Namen. Am Ziffernblatt ändert Kreisen den Wert, am
/// Mac auch das Mausrad. Logik und Maße: Werkzeugkranz.swift, Felder: `Tastenbelegung.kranz`.
struct WerkzeugkranzOverlay: View {
    @ObservedObject var viewer: ViewerStore
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var render: RenderStore
    let groesse: CGSize
    let actions: ViewerActions?

    #if os(macOS)  // nur am Mac: Mausrad am Drehregler; iPad: Kreisen mit Stift oder Finger (gleicher Code)
    @StateObject private var rad = KranzMausrad()
    #endif
    @State private var gezogen = false

    var body: some View {
        if let k = viewer.kranz {
            ZStack(alignment: .topLeading) {
                // Fängt alles: Tipp daneben schließt, Wischen wählt in der Richtung
                Color.black.opacity(0.001)
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture(minimumDistance: 0, coordinateSpace: .local)
                            .onChanged { g in
                                let weit = abs(g.translation.width) > 8 || abs(g.translation.height) > 8
                                if weit { gezogen = true }
                                zeigen(g.location, gezogen: gezogen, beginn: g.startLocation)
                            }
                            .onEnded { g in
                                loslassen(g.location, gezogen: gezogen)
                                gezogen = false
                            })
                    .onContinuousHover(coordinateSpace: .local) { phase in
                        switch phase {
                        case .active(let p): zeigen(p, gezogen: false, beginn: nil)
                        case .ended: hoverEnde()
                        }
                    }
                KranzScheibe(zustand: k, farbe: viewer.strichfarbe, stiftSprechen: viewer.stiftSprechen,
                             schwung: viewer.schwung, sitzungOffen: oberflaeche.sitzungOffen, spricht: oberflaeche.spricht,
                             ausfuehren: ausfuehren, farbeWaehlen: farbeWaehlen)
                    .position(k.mitte)
                    .allowsHitTesting(false)
                // Seitenblatt mit Reglern neben dem zweiten Ring (nimmt selbst Eingaben an, der Kranz bleibt offen)
                if case .feld(let f) = k.ebene, let blatt = Tastenbelegung.kranzBlatt(f) {
                    KranzSeitenblatt(blatt: blatt, viewer: viewer, render: render, actions: actions)
                        .position(x: KranzGeometrie.blattMitteX(mitte: k.mitte, in: groesse),
                                  y: min(max(k.mitte.y, KranzSeitenblatt.hoehe / 2 + 8),
                                         max(KranzSeitenblatt.hoehe / 2 + 8, groesse.height - KranzSeitenblatt.hoehe / 2 - 8)))
                        .transition(.opacity.combined(with: .scale(scale: 0.95)))
                }
            }
            .frame(width: groesse.width, height: groesse.height)
            .transition(.opacity.combined(with: .scale(scale: 0.92)))
            // Haptik je Teilstrich und je Feld: am Pencil Pro im Stift, am iPad und am Trackpad des Mac im Gerät
            .sensoryFeedback(.alignment, trigger: k.wert)
            .sensoryFeedback(.selection, trigger: k.markiert)
            .beiEsc { schliessen(zuruecksetzen: true) }
            #if os(macOS)  // nur am Mac: Mausrad, iPad: Kreisen
            .onAppear { rad.an { [self] s in drehenRad(s) } }
            .onDisappear { rad.aus() }
            #endif
        }
    }

    // MARK: Zeigen und Wählen

    private func versatz(_ p: CGPoint, _ k: KranzZustand) -> CGPoint { CGPoint(x: p.x - k.mitte.x, y: p.y - k.mitte.y) }

    private func unter(_ e: KranzEbene) -> [KranzEintrag] {
        if case .feld(let f) = e { return Tastenbelegung.kranz(f) }
        return []
    }

    /// Schweben und Ziehen: hervorheben; beim Ziehen und Schweben öffnet ein Feld mit Unterpunkten seinen Ring.
    private func zeigen(_ p: CGPoint, gezogen: Bool, beginn: CGPoint?) {
        guard var k = viewer.kranz else { return }
        let v = versatz(p, k)
        if case .regler = k.ebene {
            drehen(v, &k)
        } else {
            let z = KranzGeometrie.ziel(v, ebene: k.ebene, unterAnzahl: unter(k.ebene).count, gezogen: gezogen)
            if case .feld(let i) = z {
                let f = KranzFeld.allCases[i]
                if !Tastenbelegung.kranz(f).isEmpty, k.ebene != .feld(f) { k.ebene = .feld(f) }
            }
            k.markiert = z
        }
        if k != viewer.kranz { viewer.kranz = k }
    }

    private func hoverEnde() {
        guard var k = viewer.kranz else { return }
        k.markiert = nil
        k.letzterWinkel = nil
        if k != viewer.kranz { viewer.kranz = k }
    }

    /// Abheben bzw. Klick.
    private func loslassen(_ p: CGPoint, gezogen: Bool) {
        guard var k = viewer.kranz else { return }
        let v = versatz(p, k)
        if case .regler = k.ebene {
            // Der Wert steht schon (live); Abheben übernimmt. Ein Tipp in die Mitte oder daneben schließt ebenso.
            if gezogen {
                k.letzterWinkel = nil
                viewer.kranz = k
            } else {
                schliessen(zuruecksetzen: false)
            }
            return
        }
        let eintraege = unter(k.ebene)
        switch KranzGeometrie.ziel(v, ebene: k.ebene, unterAnzahl: eintraege.count, gezogen: gezogen) {
        case .mitte:
            if !gezogen, case .feld = k.ebene {  // Tipp in die Mitte: zurück zur Scheibe
                k.ebene = .haupt
                k.markiert = nil
                viewer.kranz = k
            } else {
                schliessen(zuruecksetzen: false)
            }
        case .daneben:
            schliessen(zuruecksetzen: false)
        case .pille(let i):
            farbeWaehlen(Strichfarbe.allCases[i])
        case .feld(let i):
            let f = KranzFeld.allCases[i]
            if let a = Tastenbelegung.kranzDirekt(f) {
                ausfuehren(a)
            } else if k.ebene != .feld(f) || !gezogen {
                k.ebene = .feld(f)  // Tipp: Ring öffnen; gezogen ist er schon offen und wartet
                k.markiert = nil
                viewer.kranz = k
            }
        case .unter(let j):
            ausfuehren(eintraege[j].aktion)
        }
    }

    private func ausfuehren(_ a: KranzAktion) {
        if let actions {
            actions.kranzAusfuehren(a)
        } else if case .regler = a {
            return
        } else {
            viewer.kranz = nil
        }
    }

    private func farbeWaehlen(_ f: Strichfarbe) {
        if let actions {
            actions.setStrichfarbe(f)
        } else {
            viewer.strichfarbe = f
            viewer.kranz = nil
        }
    }

    private func schliessen(zuruecksetzen: Bool) {
        if zuruecksetzen, let actions {
            actions.ausfuehren(.abbrechen)  // schließt den Kranz und stellt einen Regler zurück
        } else {
            viewer.kranz = nil
        }
    }

    // MARK: Drehregler

    /// Kreisen um die Mitte: eine Umdrehung durchläuft den ganzen Bereich.
    private func drehen(_ v: CGPoint, _ k: inout KranzZustand) {
        guard case .regler(let r) = k.ebene else { return }
        let d = (v.x * v.x + v.y * v.y).squareRoot()
        guard d >= KranzGeometrie.mitteRadius else {
            k.letzterWinkel = nil
            return
        }
        let w = KranzGeometrie.winkel(v.x, v.y)
        if let alt = k.letzterWinkel {
            k.roh = KranzGeometrie.reglerWert(k.roh, grad: KranzGeometrie.winkelSchritt(von: alt, nach: w),
                                              bereich: k.bereich)
            wertSetzen(&k, r)
        }
        k.letzterWinkel = w
    }

    private func wertSetzen(_ k: inout KranzZustand, _ r: KranzRegler) {
        let neu = k.bereich.klemmen(k.roh)
        guard neu != k.wert else { return }
        k.wert = neu
        actions?.kranzRegler(r, wert: neu)
    }

    /// Mausrad am Mac: je Raste ein Teilstrich.
    private func drehenRad(_ schritte: Double) -> Bool {
        guard var k = viewer.kranz, case .regler(let r) = k.ebene else { return false }
        k.roh = KranzGeometrie.reglerWert(k.roh, schritte: schritte, regler: r, bereich: k.bereich)
        wertSetzen(&k, r)
        viewer.kranz = k
        return true
    }
}

#if os(macOS)  // nur am Mac: Mausrad; iPad: Kreisen mit Stift oder Finger
/// Mausrad, solange der Kranz offen ist: Am Ziffernblatt dreht es den Wert, sonst zoomt es nicht hinter dem Kranz.
@MainActor
final class KranzMausrad: ObservableObject {
    private var monitor: Any?

    func an(_ wirkung: @escaping @MainActor (Double) -> Bool) {
        aus()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { e in
            nonisolated(unsafe) let e = e
            // Trackpad liefert feine Schritte, das Rad ganze Rasten
            let schritte = e.hasPreciseScrollingDeltas ? Double(e.scrollingDeltaY) / 12 : Double(e.scrollingDeltaY)
            let verbraucht = MainActor.assumeIsolated { wirkung(schritte) }
            return verbraucht ? nil : e
        }
    }

    func aus() {
        if let m = monitor { NSEvent.removeMonitor(m) }
        monitor = nil
    }
}
#endif

// MARK: Seitenblatt

/// Schmales Blatt mit Reglern neben der Scheibe (PLAN-IPAD.md 4.4, wie Feathers „Adjust“): Schalter der Darstellung und
/// das Licht beim Rendern. Wirkt sofort; der Kranz bleibt offen, bis Kevin daneben tippt oder etwas wählt.
struct KranzSeitenblatt: View {
    static let hoehe: CGFloat = 340
    let blatt: KranzBlatt
    @ObservedObject var viewer: ViewerStore
    @ObservedObject var render: RenderStore
    let actions: ViewerActions?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            switch blatt {
            case .darstellung:
                titel("Darstellung")
                ForEach(ShadingOption.allCases, id: \.self) { o in
                    Toggle(isOn: Binding(
                        get: { o.istAn(viewer.optionen) },
                        set: { an in
                            if let actions { actions.setShadingOption(o, an) } else { o.setzen(&viewer.optionen, an) }
                        })) {
                        Text(o.titel).lineLimit(1).minimumScaleFactor(0.75)
                    }
                }
                titel("Licht beim Rendern")
                    .padding(.top, 4)
                ForEach(RenderStore.szenen, id: \.id) { s in
                    Button {
                        render.szene = s.id
                    } label: {
                        HStack {
                            Text(s.titel)
                            Spacer(minLength: 4)
                            if render.szene == s.id {
                                Image(systemName: "checkmark").foregroundStyle(ViewerStil.akzent)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(render.szene == s.id ? .isSelected : [])
                }
            }
        }
        .toggleStyle(.switch)
        .controlSize(.small)
        .tint(ViewerStil.akzent)
        .font(ViewerStil.schrift)
        .foregroundStyle(ViewerStil.text)
        .padding(14)
        .frame(width: KranzGeometrie.blattBreite, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(.ultraThinMaterial))
        .background(RoundedRectangle(cornerRadius: 16).fill(ViewerStil.kranzGrund))
        .shadow(color: .black.opacity(0.35), radius: 14, y: 6)
        .environment(\.colorScheme, .dark)
    }

    private func titel(_ t: String) -> some View {
        Text(t)
            .font(ViewerStil.schriftFett)
            .foregroundStyle(ViewerStil.textLeise)
    }
}

// MARK: Zeichnung

/// Die Scheibe mit Pillen, Feldern, zweitem Ring und Ziffernblatt. Nimmt selbst keine Eingaben an (das tut die Fläche
/// darunter), bietet VoiceOver aber jedes Feld als Knopf an.
private struct KranzScheibe: View {
    let zustand: KranzZustand
    let farbe: Strichfarbe
    let stiftSprechen: Bool
    let schwung: Bool
    let sitzungOffen: Bool
    let spricht: Bool
    let ausfuehren: (KranzAktion) -> Void
    let farbeWaehlen: (Strichfarbe) -> Void

    private typealias G = KranzGeometrie
    private var regler: KranzRegler? {
        if case .regler(let r) = zustand.ebene { return r }
        return nil
    }
    private var offenesFeld: KranzFeld? {
        if case .feld(let f) = zustand.ebene { return f }
        return nil
    }

    var body: some View {
        ZStack {
            // Zweiter Ring außen um die Scheibe
            if let f = offenesFeld {
                zweiterRing(Tastenbelegung.kranz(f))
                    .transition(.scale(scale: 0.7).combined(with: .opacity))
            }
            scheibe
            if let r = regler {
                Ziffernblatt(regler: r, zustand: zustand)
                    .transition(.scale(scale: 1.08).combined(with: .opacity))
            } else {
                pillen
                    .transition(.scale(scale: 0.6).combined(with: .opacity))
                felder
                    .transition(.scale(scale: 0.85).combined(with: .opacity))
                mitte
            }
            name
        }
        .frame(width: G.platz * 2, height: G.platz * 2)
        .animation(.spring(response: 0.3, dampingFraction: 0.82), value: zustand.ebene)
        .animation(.snappy(duration: 0.12), value: zustand.markiert)
    }

    // Milchig durchscheinend in den Graphit-Farben, weicher Schatten, kein Rahmen
    private var scheibe: some View {
        Circle()
            .fill(.ultraThinMaterial)
            .overlay(Circle().fill(ViewerStil.kranzGrund))
            .overlay(Circle().strokeBorder(Color.white.opacity(0.07), lineWidth: 0.5))
            .frame(width: G.durchmesser, height: G.durchmesser)
            .shadow(color: .black.opacity(0.4), radius: 18, y: 8)
            .environment(\.colorScheme, .dark)
    }

    private var pillen: some View {
        ZStack {
            ForEach(Array(Strichfarbe.allCases.enumerated()), id: \.offset) { i, f in
                let lage = G.lage(index: i, anzahl: Strichfarbe.allCases.count, radius: G.pillenRadius)
                let an = zustand.markiert == .pille(i)
                Capsule()
                    .fill(Color(.sRGB, red: Double(f.rgba.x), green: Double(f.rgba.y), blue: Double(f.rgba.z)))
                    .frame(width: f == farbe ? 22 : 18, height: f == farbe ? 13 : 10)
                    .overlay(Capsule().strokeBorder(Color.white.opacity(f == farbe ? 0.9 : 0), lineWidth: 1.5))
                    .rotationEffect(.degrees(Double(i) * 72 + 90))
                    .scaleEffect(an ? 1.3 : 1)
                    .shadow(color: .black.opacity(0.35), radius: 2, y: 1)
                    .offset(x: lage.x, y: lage.y)
                    .accessibilityElement()
                    .accessibilityLabel("Strichfarbe \(f.name)")
                    .accessibilityAddTraits(f == farbe ? [.isButton, .isSelected] : .isButton)
                    .accessibilityAction { farbeWaehlen(f) }
            }
        }
    }

    private var felder: some View {
        ZStack {
            Circle()
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
                .frame(width: G.pillenGrenze * 2, height: G.pillenGrenze * 2)
            ForEach(Array(KranzFeld.allCases.enumerated()), id: \.offset) { i, f in
                let lage = G.lage(index: i, anzahl: KranzFeld.allCases.count, radius: G.feldRadius)
                let an = zustand.markiert == .feld(i) || offenesFeld == f
                KranzSymbol(symbol: symbol(f), an: an, groesse: 34, farbe: f == .sprechen && spricht
                            ? ViewerStil.aufnahme : nil)
                    .offset(x: lage.x, y: lage.y)
                    .accessibilityElement()
                    .accessibilityLabel(f.name)
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction {
                        if let a = Tastenbelegung.kranzDirekt(f) { ausfuehren(a) }
                    }
            }
        }
    }

    /// Oben: ohne Sitzung Sprechen, in der Sitzung Senden.
    private func symbol(_ f: KranzFeld) -> String {
        f == .sprechen && sitzungOffen ? "paperplane.fill" : f.symbol
    }

    private var mitte: some View {
        ZStack {
            if let f = offenesFeld {
                Image(systemName: f.symbol)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(ViewerStil.text)
            } else {
                Circle()
                    .fill(Color(.sRGB, red: Double(farbe.rgba.x), green: Double(farbe.rgba.y), blue: Double(farbe.rgba.z)))
                    .frame(width: 12, height: 12)
                    .overlay(Circle().strokeBorder(Color.black.opacity(0.25), lineWidth: 0.5))
            }
        }
        .frame(width: G.mitteRadius * 2, height: G.mitteRadius * 2)
        .background(Circle().fill(Color.white.opacity(zustand.markiert == .mitte ? 0.14 : 0.05)))
    }

    private func zweiterRing(_ eintraege: [KranzEintrag]) -> some View {
        ZStack {
            ForEach(Array(eintraege.enumerated()), id: \.offset) { j, e in
                let lage = G.lage(index: j, anzahl: eintraege.count, radius: G.unterRadius)
                let an = zustand.markiert == .unter(j)
                KranzSymbol(symbol: e.aktion == .stiftSprechen && !stiftSprechen ? "pencil.slash"
                                : e.aktion == .schwung && !schwung ? "pause" : e.symbol, an: an,
                            groesse: 36, farbe: nil)
                    .background(Circle().fill(.ultraThinMaterial).environment(\.colorScheme, .dark))
                    .background(Circle().fill(ViewerStil.kranzGrund))
                    .clipShape(Circle())
                    .shadow(color: .black.opacity(0.35), radius: 6, y: 3)
                    .scaleEffect(an ? 1.12 : 1)
                    .offset(x: lage.x, y: lage.y)
                    .accessibilityElement()
                    .accessibilityLabel(e.name)
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction { ausfuehren(e.aktion) }
            }
        }
    }

    /// Kurzer Name beim Darüberfahren, unter dem Kranz.
    @ViewBuilder private var name: some View {
        if let text = nameText {
            Text(text)
                .font(ViewerStil.schriftFett)
                .foregroundStyle(ViewerStil.text)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .frame(height: 24)
                .background(Capsule().fill(ViewerStil.kranzWert))
                .offset(y: (offenesFeld == nil ? G.radius : G.unterRadius + 18) + 18)
                .transition(.opacity)
                .id(text)
        }
    }

    private var nameText: String? {
        if let r = regler { return r.name }
        switch zustand.markiert {
        case .pille(let i): return Strichfarbe.allCases[i].name
        case .feld(let i):
            let f = KranzFeld.allCases[i]
            return f == .sprechen && sitzungOffen ? "Senden" : f.name
        case .unter(let j):
            let e = offenesFeld.map { Tastenbelegung.kranz($0) } ?? []
            guard j < e.count else { return nil }
            if e[j].aktion == .stiftSprechen { return "Stift beginnt Sprechen: " + (stiftSprechen ? "an" : "aus") }
            if e[j].aktion == .schwung { return "Schwung: " + (schwung ? "an" : "aus") }
            return e[j].name
        default: return nil
        }
    }
}

/// Ein Symbol im Kranz; hervorgehoben mit hellem Grund und Akzent.
private struct KranzSymbol: View {
    let symbol: String
    let an: Bool
    let groesse: CGFloat
    let farbe: Color?

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: groesse * 0.42, weight: .medium))
            .foregroundStyle(farbe ?? (an ? ViewerStil.akzent : ViewerStil.text))
            .frame(width: groesse, height: groesse)
            .background(Circle().fill(Color.white.opacity(an ? 0.16 : 0)))
    }
}

/// Ziffernblatt eines Drehreglers: Teilstriche rund herum, die bis zum Wert hell; die Mitte zeigt den Wert dunkel
/// hinterlegt.
private struct Ziffernblatt: View {
    let regler: KranzRegler
    let zustand: KranzZustand

    private typealias G = KranzGeometrie

    var body: some View {
        let n = regler.teilstriche
        let anteil = zustand.bereich.anteil(zustand.wert)
        ZStack {
            ForEach(0..<n, id: \.self) { i in
                let hell = Double(i) / Double(n) < anteil + 1e-9
                Capsule()
                    .fill(hell ? ViewerStil.akzent : Color.white.opacity(0.28))
                    .frame(width: 2.5, height: i % 5 == 0 ? 13 : 8)
                    .offset(y: -(G.radius - 14))
                    .rotationEffect(.degrees(Double(i) * 360 / Double(n)))
            }
            // Zeiger am Rand: wo der Wert steht
            Circle()
                .fill(ViewerStil.text)
                .frame(width: 10, height: 10)
                .shadow(color: .black.opacity(0.4), radius: 2)
                .offset(y: -(G.radius - 30))
                .rotationEffect(.degrees(anteil * 360))
            VStack(spacing: 2) {
                Text(regler.text(zustand.wert))
                    .font(.system(size: 17, weight: .semibold, design: .rounded).monospacedDigit())
                    .foregroundStyle(ViewerStil.text)
                    .contentTransition(.numericText())
                Image(systemName: regler.symbol)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(ViewerStil.textLeise)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Capsule().fill(ViewerStil.kranzWert))
        }
        .frame(width: G.durchmesser, height: G.durchmesser)
        .animation(.snappy(duration: 0.1), value: zustand.wert)
        .accessibilityElement()
        .accessibilityLabel(regler.name)
        .accessibilityValue(regler.text(zustand.wert))
    }
}
