import AppKit
import Combine
import KevCADCore
import SwiftUI

/// Maße der Flächen im Hauptfenster je Modus (reine Rechnung, damit der Viewer immer an derselben Stelle im
/// Ansichtsbaum bleibt und nur seinen Rahmen wechselt).
struct Arbeitsgeometrie: Equatable {
    var groesse: CGSize
    var schmal: Bool
    /// Fläche des Viewers im Fenster (im Fokus alles unter der Kopfleiste, in der Werkstatt die Kachel „Modell“)
    var viewer: CGRect
    var viewerSichtbar: Bool
    /// Untere Ecken des Viewers (in der Werkstatt passend zur Kachel)
    var viewerEcke: CGFloat
    var spalte: CGRect?
    var kacheln: [KachelArt: CGRect]
    var kachelFlaeche: CGRect
    var statuszeile: CGRect?

    init(groesse: CGSize, modus: ArbeitsModus, kacheln liste: [KachelArt], gross: KachelArt?) {
        let w = max(1, groesse.width), h = max(1, groesse.height)
        self.groesse = groesse
        schmal = w < GA.schmalAb
        let oben = GA.kopf + GA.unterKopf
        if modus == .fokus {
            viewer = CGRect(x: 0, y: oben, width: w, height: max(1, h - oben))
            viewerSichtbar = true
            viewerEcke = 0
            spalte = nil
            kacheln = [:]
            kachelFlaeche = viewer
            statuszeile = nil
            return
        }
        let r = GA.rand
        let mitSpalte = w >= 760
        let s = mitSpalte ? CGRect(x: r, y: oben + 2, width: GA.spalte, height: max(1, h - oben - 2 - r)) : nil
        let links = (s?.maxX ?? 0) + r
        let status = CGRect(x: links, y: h - r - GA.statuszeile, width: max(1, w - links - r), height: GA.statuszeile)
        let flaeche = CGRect(x: links, y: oben + 2, width: max(1, w - links - r),
                             height: max(1, status.minY - oben - 2 - 4))
        spalte = s
        statuszeile = status
        kachelFlaeche = flaeche
        let rahmen = KachelAnordnung.rahmen(liste, gross: gross, in: flaeche)
        kacheln = rahmen
        if let m = rahmen[.modell] {
            viewer = CGRect(x: m.minX + 1, y: m.minY + GA.kachelKopf, width: max(1, m.width - 2),
                            height: max(1, m.height - GA.kachelKopf - 1))
            viewerSichtbar = true
        } else {
            viewer = flaeche
            viewerSichtbar = false
        }
        viewerEcke = GR.kachel - 1
    }
}

/// Hauptfenster von Kev CAD V2: startet sofort mit einem leeren Projekt (V3), Fokus und Werkstatt (V5), eigene
/// Oberfläche (V6), Kacheln (V4), Fenster am Rand. Liest AppModel, ruft AppActions und OberflaechenActions.
struct Hauptfenster: View {
    @EnvironmentObject private var session: AppSession
    /// Nicht beobachtet: Jede Änderung am Modell (auch jede Protokollzeile) ließe sonst das ganze Fenster samt
    /// Kacheln neu auswerten. Die Teilansichten beobachten selbst, was sie brauchen.
    let model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @StateObject private var state = ProjectWindowState()
    @StateObject private var versionen = VersionenZustand()
    @StateObject private var dokumente = DokumenteZustand()
    @StateObject private var parameter = ParameterVerlauf()
    @StateObject private var spur = AgentenSpur()
    @State private var suche = ""
    /// Der Viewer kommt erst nach dem ersten Bild dazu: Metal einzurichten soll das Fenster nicht aufhalten.
    @State private var viewerAn = false
    @State private var werkstattAn = false
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    private var material: MaterialZustand { state.materialZustand }

    var body: some View {
        GeometryReader { geo in
            let g = Arbeitsgeometrie(groesse: geo.size, modus: oberflaeche.modus, kacheln: oberflaeche.kacheln,
                                     gross: oberflaeche.gross)
            let imFokus = oberflaeche.modus == .fokus
            // Im Fokus behält die ausgeblendete Werkstatt ihre Maße: Kacheln werden beim Schieben an den Rand nicht
            // neu vermessen
            let w = imFokus ? Arbeitsgeometrie(groesse: session.werkstattGroesse ?? geo.size, modus: .werkstatt,
                                               kacheln: oberflaeche.kacheln, gross: oberflaeche.gross) : g
            ZStack(alignment: .topLeading) {
                GraphitGrund()
                if viewerAn { viewerFlaeche(g) }
                if imFokus {
                    FokusEbenen(model: model, oberflaeche: oberflaeche, spur: spur, viewer: g.viewer, schmal: g.schmal)
                        .transition(.opacity)
                }
                // Einmal geöffnet bleibt die Werkstatt eingehängt: Schwere Kacheln abzubauen und neu aufzubauen kostet
                // bei jedem Umschalten Sekunden, Ausblenden nichts
                if viewerAn && (werkstattAn || !imFokus) {
                    werkstatt(w)
                        .opacity(imFokus ? 0 : 1)
                        .allowsHitTesting(!imFokus)
                        .accessibilityHidden(imFokus)
                }
                if oberflaeche.uebersicht {
                    uebersicht(g)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                Kopfleiste(model: model, oberflaeche: oberflaeche, schmal: g.schmal)
                    .frame(width: geo.size.width, height: GA.kopf)
                    .position(x: geo.size.width / 2, y: GA.ampelMitte)
            }
            // Nur Merkwerte ohne Beobachtung: Eine Größenänderung darf das Fenster nicht neu auswerten
            .onAppear { session.viewerRahmen = g.viewer }
            .onChange(of: g) { _, neu in
                session.viewerRahmen = neu.viewer
                if !imFokus { session.werkstattGroesse = neu.groesse }
            }
            .onChange(of: g.viewerSichtbar) { _, s in session.controller?.viewport.mtkView?.isPaused = !s }
        }
        .ignoresSafeArea()
        .environment(\.colorScheme, .dark)
        .frame(minWidth: 420, minHeight: 480)
        .background(WindowHook(placement: .large) { fenster in
            session.projectWindow = fenster
            session.fensterEinrichten(fenster)
        })
        .focusedSceneObject(state)
        .focusedSceneObject(versionen)
        .focusedSceneObject(dokumente)
        .modifier(DruckerDialoge(model: model))  // Phase 8: „Drucken …“ und Drucker-Einstellungen
        .modifier(RenderDialoge(model: model))  // Phase 7: „Rendern …“
        .modifier(BestandDialoge(model: model))  // Gebaut, Erfassen, Band nach einer Buchung
        .modifier(FreigabeDialogModifier(model: model, state: state))  // Vorschläge freigeben
        .modifier(ReferenzDialoge(model: model, state: state))  // Phase 4: Referenz hinzufügen, Vermessen
        .environment(\.materialNavigation, navigation)
        // Rahmen von Kacheln werden nie animiert: Schwere Tabellen würden in jedem Animationsschritt neu vermessen
        // (gemessen bis 15 s Pause). Der Modus blendet nur.
        .animation(GB.standard, value: oberflaeche.modus)
        .animation(GB.standard, value: oberflaeche.uebersicht)
        .onAppear(perform: erscheinen)
        .onChange(of: oberflaeche.aktiv) { _, a in bereichAngleichen(a) }
        .onChange(of: oberflaeche.modus) { _, m in
            if m == .werkstatt { werkstattAn = true }
            bereichAngleichen(oberflaeche.aktiv)
        }
        .onChange(of: oberflaeche.kacheln.contains(.simulation)) { _, an in
            model.simulationActions?.setSimulationAktiv(an)  // Kräfte und Lager per Klick im Viewer
        }
        .onChange(of: oberflaeche.rand) { _, r in
            session.fensterRand(r)
            guard r != nil else { return }
            // Im schmalen Fenster das Modell neu einpassen, sobald die Bewegung zu Ende ist
            DispatchQueue.main.asyncAfter(deadline: .now() + GB.rand + 0.05) {
                (model.actions as? NavigationActions)?.viewAll()
            }
        }
        .onReceive(model.bauplan.$zeige3D.dropFirst()) { _ in
            model.oberflaechenActions?.oberflaeche(.kachelAktiv(.modell))
        }
        .onReceive(model.$project.map { $0?.path }.removeDuplicates().dropFirst()) { _ in  // andere Blätter
            dokumente.bearbeiter.vergessen()
            dokumente.auswahl = nil
            dokumente.markiert = []
            dokumente.element = nil
        }
    }

    // MARK: Viewer

    /// Der Viewer samt Bändern, Zeitleiste, Vergleich und Durchspielen. Er bleibt an derselben Stelle im Ansichtsbaum
    /// und ändert nur seinen Rahmen, ohne Animation: Die Metal-Ansicht wird so nie neu angelegt.
    private func viewerFlaeche(_ g: Arbeitsgeometrie) -> some View {
        let ecken = UnevenRoundedRectangle(
            cornerRadii: .init(topLeading: 0, bottomLeading: g.viewerEcke, bottomTrailing: g.viewerEcke, topTrailing: 0),
            style: .continuous)
        return VStack(spacing: 0) {
            ViewportArea(model: model, state: state, zeigeAgent: false, zeigeLeer: false)
                .overlay(alignment: .bottomLeading) {  // Versionen: laufender Vergleich
                    VergleichKarte(model: model, store: model.versionen, zustand: versionen)
                        .padding(14)
                }
                .overlay(alignment: .bottom) { DurchspielenLeiste(model: model) }  // Bauplan durchspielen
            AnimationTimeline(model: model, animation: model.animation)  // nur mit Animation
        }
        .modifier(VersionenBlaetter(model: model, zustand: versionen))
        .onAppear {
            Startzeiten.marke("Viewer eingehängt")
            DispatchQueue.main.async { Startzeiten.marke("Viewer steht") }
        }
        .frame(width: g.viewer.width, height: g.viewer.height)
        .clipShape(ecken)
        .overlay { Sprechrahmen(an: oberflaeche.spricht, radius: g.viewerEcke) }
        .position(x: g.viewer.midX, y: g.viewer.midY)
        .opacity(g.viewerSichtbar ? 1 : 0)
        .allowsHitTesting(g.viewerSichtbar)
        .accessibilityHidden(!g.viewerSichtbar)
        .transaction { $0.animation = nil }
    }

    // MARK: Werkstatt

    private func werkstatt(_ g: Arbeitsgeometrie) -> some View {
        ZStack(alignment: .topLeading) {
            if let s = g.spalte {
                WerkstattSpalte(model: model, parameter: parameter, suche: $suche, hoehe: s.height)
                    .frame(width: s.width, height: s.height)
                    .position(x: s.midX, y: s.midY)
            }
            if oberflaeche.kacheln.isEmpty {
                KeineKachel(model: model)
                    .frame(width: g.kachelFlaeche.width, height: g.kachelFlaeche.height)
                    .position(x: g.kachelFlaeche.midX, y: g.kachelFlaeche.midY)
            }
            KachelFlaeche(model: model, oberflaeche: oberflaeche, state: state, versionen: versionen,
                          dokumente: dokumente, rahmen: g.kacheln, navigation: navigation, zeigeIm3D: zeigeIm3D)
            if let z = g.statuszeile {
                WerkstattStatus(model: model, oberflaeche: oberflaeche, spur: spur)
                    .frame(width: z.width, height: z.height)
                .position(x: z.midX, y: z.midY)
            }
        }
    }

    // MARK: Startübersicht

    private func uebersicht(_ g: Arbeitsgeometrie) -> some View {
        let oben = GA.kopf + GA.unterKopf
        return ZStack(alignment: .bottom) {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { model.oberflaechenActions?.zeigeUebersicht(false) }
                .accessibilityHidden(true)
            Startuebersicht(recents: session.recents, breite: g.groesse.width) {
                withAnimation(GB.standard) { model.oberflaechenActions?.zeigeUebersicht(false) }
            }
            .padding(.bottom, GA.xl)
        }
        .frame(width: g.groesse.width, height: max(1, g.groesse.height - oben))
        .position(x: g.groesse.width / 2, y: oben + (g.groesse.height - oben) / 2)
    }

    // MARK: Verbindungen

    private func erscheinen() {
        OberflaechenSelbsttest.fensterErschienen()  // Startzeit messen (nur der Selbsttest liest sie)
        session.attach(openWindow: openWindow, dismissWindow: dismissWindow)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { viewerAn = true }
        session.viewerKlickBeobachten()
        parameter.beobachten(model)
        spur.beobachten(model)
        state.beimBereichswechsel = { [weak model] b in
            guard let model, let a = model.oberflaechenActions else { return }
            if model.oberflaeche.aktiv?.bereich == b { return }  // Kachel und Bereich passen schon
            switch b {
            case .modell: a.oberflaeche(.kachelAktiv(.modell))
            case .dokumente: a.zeigeKachel(.zeichnung)
            case .material: a.zeigeKachel(.material)
            case .simulation: a.zeigeKachel(.simulation)
            }
        }
        BedingungenSchalter.wiederherstellen(model)
        dokumenteVerbinden()
        session.launchFinished()
        // Selbsttests wie im bisherigen Projektfenster (öffnen ihr Projekt selbst)
        BauplanExportSelfTest.projektOeffnen(session)
        DruckSelfTest.projektOeffnen(session)
        DruckerSelbsttest.projektOeffnen(session)
        MaterialSelfTest.projektOeffnen(session)
        RestDruckSelbsttest.projektOeffnen(session)
        SimulationSelfTest.projektOeffnen(session)
        DokumenteSelfTest.runIfRequested(session, state: state, zustand: dokumente)
        SelfTest.runIfRequested(session)
        CatalogSelfTest.runIfRequested(session)
        ZukaufSelfTest.runIfRequested(session)
        BauplanExportSelfTest.runIfRequested(session, state: state, zustand: dokumente)
        DruckSelfTest.runIfRequested(session, state: state)
        DruckerSelbsttest.runIfRequested(session)
        RenderSelbsttest.runIfRequested(session)
        BestandSelfTest.runIfRequested(session)
        FilamentSelfTest.runIfRequested(session, state: state, material: material)
        RestDruckSelbsttest.runIfRequested(session, state: state, material: material)
        MaterialSelfTest.runIfRequested(session, state: state, material: material)
        SimulationSelfTest.runIfRequested(session, state: state)
        OberflaechenSelbsttest.runIfRequested(session)
    }

    /// Bereich der bisherigen Oberfläche passend zur aktiven Kachel (Menübefehle der Bereiche, Tastenkürzel).
    private func bereichAngleichen(_ a: KachelArt?) {
        let b: ProjektBereich = oberflaeche.modus == .fokus ? .modell : (a?.bereich ?? .modell)
        if state.bereich != b { state.bereich = b }
        if b == .modell { session.projectWindow?.makeFirstResponder(nil) }
    }

    /// Sprünge in den Bereich „Material“ und zu den Berichten (Stückliste, Inspektor, Bauplan).
    private var navigation: MaterialNavigation {
        MaterialNavigation(
            zeige: { [weak state, weak material] a, pos, sid in
                material?.zeige(a, position: pos, stockID: sid)
                state?.zeige(.material)
            },
            bericht: { [weak state, weak dokumente] art in
                BerichteUI.shared.bericht = art
                dokumente?.waehle(.berichte)
                state?.zeige(.dokumente)
            })
    }

    /// Aus einer Kachel: Teile wählen und einpassen, das Modell nach vorn.
    private func zeigeIm3D(_ teile: [String]) {
        model.oberflaechenActions?.oberflaeche(.kachelAktiv(.modell))
        model.actions?.select(teile)
        model.actions?.focus(on: teile)
    }

    /// Bereich Dokumente: Rückgängig über das Fenster, Teile im 3D zeigen.
    private func dokumenteVerbinden() {
        let b = dokumente.bearbeiter
        b.model = model
        b.zeige = { [weak state, weak dokumente] id in
            state?.bereich = .dokumente
            dokumente?.waehle(.blatt(id))
        }
        b.melde = { [weak dokumente] t in dokumente?.melde(t, fehler: true) }
        dokumente.zeigeIm3D = { [weak model] teile in
            model?.oberflaechenActions?.oberflaeche(.kachelAktiv(.modell))
            model?.actions?.select(teile)
            model?.actions?.focus(on: teile)
        }
        state.dokumenteZustand = dokumente
    }
}

/// Statuszeile der Werkstatt (eigene Ansicht: nur sie beobachtet Lauf und Kernel).
private struct WerkstattStatus: View {
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    @ObservedObject var spur: AgentenSpur

    var body: some View {
        Statuszeile(
            spricht: oberflaeche.spricht, gesagt: oberflaeche.zuletztGesagt,
            agent: spur.jetzt?.text ?? spur.eintraege.last?.text, stand: standText, standFarbe: standFarbe
        ) {
            model.oberflaechenActions?.setzeSprechen(!oberflaeche.spricht)
        }
    }

    private var standText: String {
        switch model.kernelState {
        case .stopped, .starting: return "Kernel startet"
        case .failed(let m): return "Kernel: \(m)"
        case .ready, .busy: break
        }
        switch model.run {
        case .running(let run, let step, _): return "Lauf \(run)" + (step.map { " · \($0)" } ?? "")
        case .failed(let run, _, let line, _): return "Lauf \(run): Fehler" + (line.map { " in Zeile \($0)" } ?? "")
        case .finished(let run, _, let teile, _): return "Lauf \(run) · \(KevFormat.count(teile, one: "Teil", many: "Teile"))"
        case .idle: return model.project == nil ? "Kein Projekt" : "Bereit"
        }
    }

    private var standFarbe: Color {
        switch model.kernelState {
        case .failed: return GF.befund
        case .stopped, .starting: return GF.rauch
        case .ready, .busy: break
        }
        if case .failed = model.run { return GF.befund }
        if case .running = model.run { return GF.agent }
        return Color(red: 0.42, green: 0.78, blue: 0.5)
    }
}

/// Linke Spalte der Werkstatt: Objekte (mit Suche ab einigen Teilen) und Eigenschaften der Auswahl.
private struct WerkstattSpalte: View {
    @ObservedObject var model: AppModel
    @ObservedObject var parameter: ParameterVerlauf
    @Binding var suche: String
    let hoehe: CGFloat

    private var form: RoundedRectangle { RoundedRectangle(cornerRadius: GR.insel, style: .continuous) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            AbschnittTitel(titel: "Objekte", zusatz: KevFormat.integer(model.parts.count))
            if model.parts.count > 12 {
                SuchFeld(text: $suche)
            }
            if model.parts.isEmpty {
                Text(model.isRunning ? "Teile entstehen …" : "Noch keine Teile.")
                    .font(GS.text)
                    .foregroundStyle(GF.rauch)
            } else {
                Gliederung(model: model, filter: suche)
                    .frame(height: max(120, (hoehe - 90) * 0.44))
            }
            Rectangle().fill(GF.linie).frame(height: 1)
            ScrollView(.vertical) {
                Eigenschaften(model: model, verlauf: parameter)
                    .padding(.bottom, GA.s)
            }
            .scrollIndicators(.automatic)
        }
        .padding(EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16))
        .background(form.fill(GF.insel))
        .overlay(form.strokeBorder(GF.linie, lineWidth: 1))
    }
}

/// Werkstatt ohne Kachel: Hinweis und Knöpfe für die häufigsten Kacheln.
private struct KeineKachel: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 14) {
            Text("Keine Kachel offen")
                .font(GS.karteTitel)
                .foregroundStyle(GF.asche)
            HStack(spacing: 8) {
                ForEach([KachelArt.modell, .zeichnung, .stueckliste, .zuschnitt], id: \.self) { a in
                    Button { model.oberflaechenActions?.zeigeKachel(a) } label: { Label(a.titel, systemImage: a.symbol) }
                        .buttonStyle(KevKnopfStil(form: .text))
                }
            }
        }
    }
}
