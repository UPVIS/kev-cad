#if os(macOS)
import AppKit
#else
import UIKit
#endif
import Combine
import KevCADCore
import SwiftUI

/// Maße der Flächen im Hauptfenster (reine Rechnung, damit der Viewer immer an derselben Stelle im Ansichtsbaum bleibt
/// und nur seinen Rahmen wechselt). V2-9: Ohne Kacheln reicht der Viewer bis an die Oberkante, die Kopfleiste liegt
/// ohne eigenen Grund darüber. Links stehen die Objekte (neben Kacheln als Spalte, sonst leise im Viewer), rechts auf
/// Wunsch die Eigenschaften.
struct Arbeitsgeometrie: Equatable {
    var groesse: CGSize
    var schmal: Bool
    /// Kacheln stehen nebeneinander (sonst füllt der Viewer das Fenster)
    var kachelModus: Bool
    /// Fläche des Viewers im Fenster (ohne Kacheln alles bis auf die rechte Spalte, sonst die Kachel „Modell“)
    var viewer: CGRect
    var viewerSichtbar: Bool
    /// Obere Ecken des Viewers (neben Kacheln passend zur Kachel)
    var viewerEcke: CGFloat
    /// Linke Spalte mit den Objekten (nur neben Kacheln)
    var spalte: CGRect?
    /// Rechte Spalte mit Eigenschaften und Maßen des Modells
    var rechts: CGRect?
    var kacheln: [KachelArt: CGRect]
    var kachelFlaeche: CGRect

    init(groesse: CGSize, kachelModus: Bool, links: Bool, rechts mitRechts: Bool, kacheln liste: [KachelArt],
         gross: KachelArt?) {
        let w = max(1, groesse.width), h = max(1, groesse.height)
        self.groesse = groesse
        self.kachelModus = kachelModus
        schmal = w < GA.schmalAb
        let oben = GA.kopf + GA.unterKopf
        let r = GA.rand
        let breit = w >= 760
        let rs = mitRechts && breit
            ? CGRect(x: w - r - GA.spalte, y: oben + 2, width: GA.spalte, height: max(1, h - oben - 2 - r)) : nil
        rechts = rs
        let rechtsKante = rs.map { $0.minX - r } ?? w
        if !kachelModus {
            viewer = CGRect(x: 0, y: 0, width: max(1, rs == nil ? w : rechtsKante + r / 2), height: h)
            viewerSichtbar = true
            viewerEcke = 0
            spalte = nil
            kacheln = [:]
            kachelFlaeche = viewer
            return
        }
        let s = links && breit ? CGRect(x: r, y: oben + 2, width: GA.spalte, height: max(1, h - oben - 2 - r)) : nil
        let linksKante = (s?.maxX ?? 0) + r
        let flaeche = CGRect(x: linksKante, y: oben + 2, width: max(1, rechtsKante - linksKante),
                             height: max(1, h - oben - 2 - r))
        spalte = s
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

/// Hauptfenster von Kev CAD V2: startet sofort mit einem leeren Projekt (V3), linke und rechte Leiste (V5, V2-9), eigene
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
    /// Nicht beobachtet: Das Hauptfenster zeichnet sich nicht bei jedem Schritt neu, nur die Spur selbst.
    @State private var spur = AgentenSpur()
    @State private var suche = ""
    /// Der Viewer kommt erst nach dem ersten Bild dazu: Metal einzurichten soll das Fenster nicht aufhalten.
    @State private var viewerAn = false
    /// Die Kachelfläche wird erst beim ersten Gebrauch eingehängt und bleibt danach (Aufbau schwerer Kacheln kostet).
    @State private var kachelnAn = false
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow
    /// iPad: Statusleiste über dem Fenster; so weit reicht der Viewer nach oben hinaus (am Mac 0).
    @Environment(\.viewerUeberstand) private var ueberstand

    private var material: MaterialZustand { state.materialZustand }

    var body: some View {
        GeometryReader { geo in
            let kachelModus = oberflaeche.kachelflaeche
            let g = Arbeitsgeometrie(groesse: geo.size, kachelModus: kachelModus, links: oberflaeche.leisteLinks,
                                     rechts: oberflaeche.leisteRechts, kacheln: oberflaeche.kacheln,
                                     gross: oberflaeche.gross)
            // Ohne Kacheln behält die ausgeblendete Kachelfläche ihre Maße: Kacheln werden beim Schieben an den Rand
            // und beim Groß des Modells nicht neu vermessen
            let w = kachelModus ? g : Arbeitsgeometrie(groesse: session.werkstattGroesse ?? geo.size, kachelModus: true,
                                                       links: oberflaeche.leisteLinks, rechts: oberflaeche.leisteRechts,
                                                       kacheln: oberflaeche.kacheln, gross: nil)
            ZStack(alignment: .topLeading) {
                // iPad (I-3b): Der Grund reicht bis unter die Statusleiste. Ohne Kacheln liegt dort der Viewer
                // (viewerFlaeche), neben Kacheln der Grund wie um die Kopfleiste; die Kacheln selbst bleiben im sicheren
                // Bereich, ihre Köpfe gehören nicht unter die Uhr.
                GraphitGrund()
                    .padding(.top, -ueberstand)
                if viewerAn { viewerFlaeche(g) }
                // Einmal geöffnet bleibt die Kachelfläche eingehängt: Schwere Kacheln abzubauen und neu aufzubauen
                // kostet bei jedem Umschalten Sekunden, Ausblenden nichts
                if viewerAn && (kachelnAn || kachelModus) {
                    kachelEbene(w)
                        .opacity(kachelModus ? 1 : 0)
                        .allowsHitTesting(kachelModus)
                        .accessibilityHidden(!kachelModus)
                }
                // Live-Text und Agentenspur stehen immer im Bild: über dem Viewer, sonst über den Kacheln
                FokusEbenen(model: model, oberflaeche: oberflaeche, spur: spur, animation: model.animation,
                            viewer: model.viewer, flaeche: g.viewerSichtbar ? g.viewer : g.kachelFlaeche,
                            schmal: (g.viewerSichtbar ? g.viewer : g.kachelFlaeche).width < GA.schmalAb,
                            obenFrei: kachelModus ? 0 : GA.kopf + GA.unterKopf,
                            gliederung: !kachelModus && oberflaeche.leisteLinks, zeitleisteErlaubt: !kachelModus,
                            startZeile: g.viewerSichtbar)
                if let r = g.rechts {
                    RechteSpalte(model: model, parameter: parameter)
                        .zumRandSchliessen(.trailing) { model.oberflaechenActions?.setzeLeisteRechts(false) }
                        .frame(width: r.width, height: r.height)
                        .position(x: r.midX, y: r.midY)
                }
                if oberflaeche.uebersicht {
                    uebersicht(g)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                FensterBaender(model: model, state: state, viewerSichtbar: g.viewerSichtbar)
                    .padding(.top, GA.kopf + GA.unterKopf + GA.s)
                    .padding(.horizontal, GA.m)
                    .frame(width: geo.size.width, alignment: .top)
                #if os(macOS)
                // Der Viewer reicht bis an die Oberkante; leere Stellen der Kopfleiste ziehen trotzdem das Fenster
                FensterZiehen()
                    .frame(width: geo.size.width, height: GA.kopf + GA.unterKopf)
                    .position(x: geo.size.width / 2, y: (GA.kopf + GA.unterKopf) / 2)
                #endif
                Kopfleiste(model: model, oberflaeche: oberflaeche, breite: geo.size.width)
                    .frame(width: geo.size.width, height: GA.kopf)
                    .position(x: geo.size.width / 2, y: GA.ampelMitte)
            }
            // Nur Merkwerte ohne Beobachtung: Eine Größenänderung darf das Fenster nicht neu auswerten
            .onAppear {
                session.viewerRahmen = g.viewer
                model.kopplung.fensterBreite = Double(geo.size.width)  // I-6: schmale Fenster teilen Kacheln anders
                model.viewer.obenFrei = kachelModus ? 0 : GA.kopf + GA.unterKopf
            }
            .onChange(of: g) { _, neu in
                session.viewerRahmen = neu.viewer
                model.kopplung.fensterBreite = Double(neu.groesse.width)
                if neu.kachelModus { session.werkstattGroesse = neu.groesse }
                let frei: CGFloat = neu.kachelModus ? 0 : GA.kopf + GA.unterKopf
                if model.viewer.obenFrei != frei { model.viewer.obenFrei = frei }
            }
            .onChange(of: g.viewerSichtbar) { _, s in session.controller?.viewport.mtkView?.isPaused = !s }
        }
        #if os(macOS)
        .ignoresSafeArea()  // Der Viewer reicht bis unter die (versteckte) Titelleiste
        #endif
        // iPad: Das Hauptfenster bleibt zwischen Statusleiste und Home-Balken (Grund darunter: KevCADPad). Viewer bis unter
        // die Statusleiste, Kopfleiste und Bänder darunter folgen mit I-3b.
        .environment(\.colorScheme, .dark)
        .frame(minWidth: 420, minHeight: 480)
        #if os(macOS)
        .background(WindowHook(placement: .large) { fenster in
            session.projectWindow = fenster
            session.fensterEinrichten(fenster)
        })
        #endif
        #if os(iOS)
        // iPad: Dateien wählen (Referenz, CAD-Datei) über die Dateien-App; der Mac hat dafür den Dialog von AppKit
        .fileImporter(isPresented: Binding(get: { session.dateiWahl != nil },
                                           set: { if !$0 { session.dateiWahlSchliessen() } }),
                      allowedContentTypes: session.dateiWahl?.typen ?? [.item],
                      allowsMultipleSelection: session.dateiWahl?.mehrere ?? false) { ergebnis in
            session.dateiWahlBeendet(ergebnis)
        }
        // iPad: Protokoll, Lagerkatalog, Zukaufteil und Projekte als Blatt (am Mac eigene Fenster bzw. der Dateidialog)
        .sheet(item: $session.padBlatt) { blatt in
            PadBlattAnsicht(blatt: blatt, model: model)
                .environmentObject(session)
        }
        .modifier(PadProjektDialoge(session: session))
        #endif
        .focusedSceneObject(state)
        .focusedSceneObject(versionen)
        .focusedSceneObject(dokumente)
        .modifier(DruckerDialoge(model: model))  // Phase 8: „Drucken …“ und Drucker-Einstellungen
        .modifier(BestandDialoge(model: model))  // Gebaut, Erfassen, Band nach einer Buchung
        .modifier(FreigabeDialogModifier(model: model, state: state))  // Vorschläge freigeben
        .modifier(ReferenzDialoge(model: model, state: state))  // Phase 4: Referenz hinzufügen, Vermessen
        .environment(\.materialNavigation, navigation)
        // Rahmen von Kacheln werden nie animiert: Schwere Tabellen würden in jedem Animationsschritt neu vermessen
        // (gemessen bis 15 s Pause). Der Wechsel zur Kachelfläche blendet nur, die Leisten springen ohne Animation.
        .animation(GB.standard, value: oberflaeche.kachelflaeche)
        .animation(GB.standard, value: oberflaeche.uebersicht)
        .onAppear(perform: erscheinen)
        .onChange(of: oberflaeche.aktiv) { _, a in bereichAngleichen(a) }
        .onChange(of: oberflaeche.kachelflaeche) { _, an in
            if an { kachelnAn = true }
            bereichAngleichen(oberflaeche.aktiv)
        }
        .onChange(of: oberflaeche.blatt) { _, id in  // der Agent wechselt das Blatt
            if let id, dokumente.blattID != id { dokumente.waehle(.blatt(id)) }
        }
        .onChange(of: dokumente.auswahl) { _, a in dokumenteFolgen(a) }
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
            model.oberflaechenActions?.oberflaeche(.blatt(nil))
            dokumente.markiert = []
            dokumente.element = nil
        }
    }

    // MARK: Viewer

    /// Der Viewer samt Bändern, Vergleich und Durchspielen. Er bleibt an derselben Stelle im Ansichtsbaum und ändert nur
    /// seinen Rahmen, ohne Animation: Die Metal-Ansicht wird so nie neu angelegt.
    ///
    /// iPad (I-3b): Liegt der Viewer oben am Fensterrand (ohne Kacheln), reicht er um `ueberstand` bis unter die
    /// Statusleiste; Bänder, Achsen und das X am Sprechrahmen rücken um dasselbe nach unten und bleiben im sicheren Bereich.
    private func viewerFlaeche(_ g: Arbeitsgeometrie) -> some View {
        let ue = g.viewer.minY < 1 ? ueberstand : 0
        let obenFrei = (g.kachelModus ? 0 : GA.kopf + GA.unterKopf) + ue
        return ViewportArea(model: model, state: state, zeigeAgent: false, zeigeLeer: false,
                     obenFrei: obenFrei,
                     linksFrei: !g.kachelModus && oberflaeche.leisteLinks && g.viewer.width >= GA.schmalAb
                        ? GA.xl + GA.gliederung : 0,
                     schmal: g.viewer.width < GA.schmalAb)
            .overlay(alignment: .bottomLeading) {  // Versionen: laufender Vergleich
                VergleichKarte(model: model, store: model.versionen, zustand: versionen)
                    .padding(14)
            }
            .overlay(alignment: .bottom) { DurchspielenLeiste(model: model) }  // Bauplan durchspielen
        .modifier(VersionenBlaetter(model: model, zustand: versionen))
        .onAppear {
            Startzeiten.marke("Viewer eingehängt")
            DispatchQueue.main.async {
                Startzeiten.marke("Viewer steht")
                viewerEcken(g.viewerEcke)
            }
        }
        .onChange(of: g.viewerEcke) { _, r in viewerEcken(r) }
        .frame(width: g.viewer.width, height: g.viewer.height + ue)
        .clipped()
        .overlay { Sprechrahmen(an: oberflaeche.spricht, radius: g.viewerEcke) }
        .overlay(alignment: .top) {  // Verwerfen am Rahmen (PLAN-IPAD.md 4.5; am Mac auch esc)
            if oberflaeche.spricht {
                SprechVerwerfen { model.oberflaechenActions?.sprechenVerwerfen() }
                    .padding(.top, obenFrei + GA.s)
                    .transition(.opacity.combined(with: .scale(scale: 0.9)))
            }
        }
        .animation(GB.kurz, value: oberflaeche.spricht)
        .position(x: g.viewer.midX, y: g.viewer.midY - ue / 2)
        .opacity(g.viewerSichtbar ? 1 : 0)
        .allowsHitTesting(g.viewerSichtbar)
        .accessibilityHidden(!g.viewerSichtbar)
        .transaction { $0.animation = nil }
    }

    /// Obere Ecken des Viewers neben Kacheln, auf der Metal-Ebene selbst: `.clipShape` legte eine Formmaske über den
    /// Viewer, und das Fenstersystem musste jedes Bild erst abseits zusammensetzen.
    private func viewerEcken(_ radius: CGFloat) {
        guard let ebene = session.controller?.viewport.mtkView?.layer else { return }
        ebene.cornerRadius = radius
        ebene.cornerCurve = .continuous
        ebene.maskedCorners = [.layerMinXMinYCorner, .layerMaxXMinYCorner]
        ebene.masksToBounds = radius > 0
    }

    // MARK: Kachelfläche

    private func kachelEbene(_ g: Arbeitsgeometrie) -> some View {
        ZStack(alignment: .topLeading) {
            if let s = g.spalte {
                LinkeSpalte(model: model, suche: $suche, tastenAktiv: oberflaeche.kachelflaeche)
                    .zumRandSchliessen(.leading) { model.oberflaechenActions?.setzeLeisteLinks(false) }
                    .frame(width: s.width, height: s.height)
                    .position(x: s.midX, y: s.midY)
            }
            KachelFlaeche(model: model, oberflaeche: oberflaeche, state: state, versionen: versionen,
                          dokumente: dokumente, rahmen: g.kacheln, navigation: navigation, zeigeIm3D: zeigeIm3D)
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
        #if os(macOS)
        // Selbsttests wie im bisherigen Projektfenster (öffnen ihr Projekt selbst). iPad: folgen in I-9.
        BauplanExportSelfTest.projektOeffnen(session)
        DruckSelfTest.projektOeffnen(session)
        DruckerSelbsttest.projektOeffnen(session)
        MaterialSelfTest.projektOeffnen(session)
        RestDruckSelbsttest.projektOeffnen(session)
        SimulationSelfTest.projektOeffnen(session)
        DokumenteSelfTest.runIfRequested(session, state: state, zustand: dokumente)
        SelfTest.runIfRequested(session)
        CatalogSelfTest.runIfRequested(session)
        FreigabeSelfTest.katalogOeffnen(session)
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
        #else
        PadSelbsttest.runIfRequested(session)  // iPad: Oberfläche ohne Mac-Prozesse (KEVCAD_SELFTEST=pad)
        #endif
    }

    /// Bereich der bisherigen Oberfläche passend zur aktiven Kachel (Menübefehle der Bereiche, Tastenkürzel).
    private func bereichAngleichen(_ a: KachelArt?) {
        let b: ProjektBereich = oberflaeche.kachelflaeche ? (a?.bereich ?? .modell) : .modell
        if state.bereich != b { state.bereich = b }
        #if os(macOS)
        if b == .modell { session.projectWindow?.makeFirstResponder(nil) }
        #endif
    }

    /// Auswahl der Kachel Zeichnung: Der Bauplan hat seine eigene Kachel, die Zeichnung behält dann ihr Blatt. Das gewählte
    /// Blatt steht im Zustand der Oberfläche, damit der Agent es im Lagebild sieht.
    private func dokumenteFolgen(_ a: DokumentAuswahl?) {
        switch a {
        case .bauplan?:
            model.oberflaechenActions?.zeigeKachel(.bauplan)
            dokumente.auswahl = oberflaeche.blatt.map { .blatt($0) }
        case .blatt(let id)?:
            if oberflaeche.blatt != id { model.oberflaechenActions?.oberflaeche(.blatt(id)) }
        default:
            break
        }
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

/// Bänder über allen Flächen: der Hinweis nach „Gebaut“ mit „Rückgängig“ und, solange der Viewer verdeckt ist, die
/// Vorschläge zur Freigabe (sonst zeigt sie der Viewer selbst). Eigene Ansicht: nur sie beobachtet das Modell.
private struct FensterBaender: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    let viewerSichtbar: Bool

    var body: some View {
        VStack(spacing: 8) {
            BuchungsBand(model: model)
            if !viewerSichtbar, let key = model.vorschlagSchluessel, state.dismissedFreigabe != key {
                FreigabeBand(model: model, oeffnen: { state.freigabeOffen = true }) { state.dismissedFreigabe = key }
            }
        }
    }
}

/// Linke Spalte neben Kacheln: die Objekte, ab einigen Teilen mit Suche.
private struct LinkeSpalte: View {
    @ObservedObject var model: AppModel
    @Binding var suche: String
    /// iPad: Pfeiltasten nur in der sichtbaren Gliederung (die Spalte bleibt neben dem Modell eingehängt).
    var tastenAktiv = true

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
                Spacer(minLength: 0)
            } else {
                Gliederung(model: model, filter: suche, tastenAktiv: tastenAktiv)
                    .frame(maxHeight: .infinity, alignment: .top)
            }
        }
        .padding(EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16))
        .background(form.fill(GF.insel))
        .overlay(form.strokeBorder(GF.linie, lineWidth: 1))
    }
}

/// Rechte Leiste (V2-9): Eigenschaften der Auswahl und Maße des Modells.
private struct RechteSpalte: View {
    let model: AppModel
    @ObservedObject var parameter: ParameterVerlauf

    private var form: RoundedRectangle { RoundedRectangle(cornerRadius: GR.insel, style: .continuous) }

    var body: some View {
        ScrollView(.vertical) {
            Eigenschaften(model: model, verlauf: parameter)
                .padding(.bottom, GA.s)
        }
        .scrollIndicators(.automatic)
        .padding(EdgeInsets(top: 14, leading: 16, bottom: 14, trailing: 16))
        .background(form.fill(GF.insel))
        .overlay(form.strokeBorder(GF.linie, lineWidth: 1))
    }
}

#if os(macOS)
/// Fläche hinter der Kopfleiste, die das Fenster zieht (der Viewer darunter würde sonst drehen); ein Doppelklick zoomt.
/// Nur am Mac: Auf dem iPad bewegt das System die Fenster (Stage Manager).
private struct FensterZiehen: NSViewRepresentable {
    final class Flaeche: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 { window?.performZoom(nil) } else { window?.performDrag(with: event) }
        }
    }

    func makeNSView(context: Context) -> NSView { Flaeche() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}
#endif

/// iPad (I-3b): Höhe der Statusleiste über dem Hauptfenster. Der Viewer reicht so weit nach oben hinaus, die Bedienung
/// bleibt im sicheren Bereich. Die iPad-Hülle setzt den Wert (PadHauptfenster), am Mac bleibt er 0.
private struct ViewerUeberstandKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    var viewerUeberstand: CGFloat {
        get { self[ViewerUeberstandKey.self] }
        set { self[ViewerUeberstandKey.self] = newValue }
    }
}

extension View {
    /// iPad (I-3b, PLAN-IPAD.md 4.2): Eine Leiste mit dem Finger zu ihrem Rand hin wischen schließt sie, wie das Wischen
    /// vom Rand sie öffnet (RandWischen.swift). Waagrecht, mindestens 60 pt, deutlich mehr quer als längs: Listen und
    /// Regler darin bleiben bedienbar. Am Mac ohne Wirkung (dort ⌘1, ⌘2 und die Knöpfe der Kopfleiste).
    @ViewBuilder
    func zumRandSchliessen(_ rand: HorizontalEdge, _ schliessen: @escaping () -> Void) -> some View {
        #if os(iOS)
        simultaneousGesture(
            DragGesture(minimumDistance: 24).onEnded { v in
                let dx = v.translation.width
                guard abs(dx) >= 60, abs(dx) > 2 * abs(v.translation.height) else { return }
                if (rand == .leading && dx < 0) || (rand == .trailing && dx > 0) {
                    withAnimation(GB.standard) { schliessen() }
                }
            })
        #else
        self
        #endif
    }
}

#if os(iOS)
/// Inhalt eines Blatts auf dem iPad: dieselben Ansichten wie die Fenster am Mac, mit „Fertig“ oben.
private struct PadBlattAnsicht: View {
    @EnvironmentObject private var session: AppSession
    let blatt: PadBlatt
    @ObservedObject var model: AppModel

    var body: some View {
        NavigationStack {
            inhalt
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    if blatt != .zukauf && blatt != .export {  // beide haben eigene Knöpfe zum Schließen
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Fertig") { session.padBlatt = nil }
                        }
                    }
                }
        }
        .presentationDetents([.large])
        .preferredColorScheme(.dark)
    }

    @ViewBuilder
    private var inhalt: some View {
        switch blatt {
        case .protokoll:
            LogWindow(model: model).navigationTitle("Protokoll")
        case .lagerkatalog:
            CatalogWindow(model: model).navigationTitle("Lagerkatalog")
        case .zukauf:
            ZukaufDialog(model: model, request: session.zukaufRequest ?? .new()) { session.padBlatt = nil }
                .navigationTitle("Zukaufteil hinzufügen")
        case .projekte:
            ProjekteBlatt(model: model).navigationTitle("Projekte")
        case .export:  // Ablage › Dokumente exportieren … (⇧⌘E), am Mac `ExportDialogFenster`
            ExportDialog(model: model, vorauswahl: nil) { session.padBlatt = nil }
                .navigationTitle("Dokumente exportieren")
        }
    }
}

/// iPad: Name für ein neues Projekt und „Entfernen?“ für ein fehlendes Projekt aus „Zuletzt geöffnet“ (I-7). Am Mac
/// entsteht ein neues Projekt als Entwurf ohne Namen, und die Rückfrage ist ein NSAlert (`AppSession.openRecent`).
private struct PadProjektDialoge: ViewModifier {
    @ObservedObject var session: AppSession
    @State private var name = ""

    func body(content: Content) -> some View {
        content
            .alert("Neues Projekt", isPresented: $session.neuesProjektFragen) {
                TextField("Name", text: $name)
                Button("Anlegen") {
                    session.neuesProjektAnlegen(name)
                    name = ""
                }
                Button("Abbrechen", role: .cancel) { name = "" }
            } message: {
                Text("Dein Mac legt das Projekt an, \(Projektablage.inICloud(AppInfo.projectsDirectory) ? "im Ordner „\(AppInfo.projectsDirectory.lastPathComponent)“ in iCloud Drive" : "in seinem Projektordner").")
            }
            .confirmationDialog(
                "„\(session.fehlendesProjekt?.name ?? "")“ wurde nicht gefunden",
                isPresented: Binding(get: { session.fehlendesProjekt != nil },
                                     set: { if !$0 { session.fehlendesProjekt = nil } }),
                titleVisibility: .visible
            ) {
                Button("Entfernen", role: .destructive) {
                    if let p = session.fehlendesProjekt { session.recents.remove(p.url) }
                    session.fehlendesProjekt = nil
                }
                Button("Behalten", role: .cancel) { session.fehlendesProjekt = nil }
            } message: {
                Text("Der Ordner ist nicht mehr da. Soll der Eintrag aus „Zuletzt geöffnet“ entfernt werden?")
            }
    }
}
#endif
