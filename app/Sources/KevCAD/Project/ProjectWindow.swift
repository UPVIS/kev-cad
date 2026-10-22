import KevCADCore
import SwiftUI

/// Projektfenster: links Teilebaum, Mitte Viewport mit Statusleiste, rechts Inspektor.
struct ProjectWindow: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @StateObject private var state = ProjectWindowState()
    @StateObject private var versionen = VersionenZustand()
    @StateObject private var dokumente = DokumenteZustand()  // Phase 6: Bereich Dokumente
    @State private var columns = NavigationSplitViewVisibility.all
    /// Breite von Viewport und Stückliste (links der Versionsleiste), für `platzFuerLeiste`.
    @State private var modellBreite: CGFloat = 0
    @State private var modellMitLeiste = false
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        Group {
            if model.project != nil {
                content
            } else {
                NoProjectView()
            }
        }
        .frame(minWidth: 960, minHeight: 600)
        .background(WindowHook(placement: .large) { session.projectWindow = $0 })
        .focusedSceneObject(state)
        .focusedSceneObject(versionen)
        .focusedSceneObject(dokumente)
        .navigationTitle(model.project?.name ?? "Kev CAD")
        .navigationSubtitle(untertitel)
        .onAppear {
            session.attach(openWindow: openWindow, dismissWindow: dismissWindow)
            dokumenteVerbinden()
            DokumenteSelfTest.runIfRequested(session, state: state, zustand: dokumente)
            SelfTest.runIfRequested(session)
            CatalogSelfTest.runIfRequested(session)
            ZukaufSelfTest.runIfRequested(session)
            BauplanExportSelfTest.runIfRequested(session, state: state, zustand: dokumente)  // Phase 6, P6-A2
            if let config = session.demo?.config, config.usesGestell { state.showBOM = true }
        }
        .onChange(of: model.bom?.run) { _, _ in autoShowBOM() }
        // Phase 6, P6-A2: Durchspielen und „Im 3D zeigen“ aus dem Bauplan holen den 3D-Bereich nach vorn
        .onReceive(model.bauplan.$zeige3D.dropFirst()) { _ in
            withAnimation(.snappy(duration: 0.2)) { state.bereich = .modell }
        }
        .onChange(of: model.project?.path) { _, _ in  // Phase 6: anderes Projekt, andere Blätter
            dokumente.bearbeiter.vergessen()
            dokumente.auswahl = nil
            dokumente.markiert = []
            dokumente.element = nil
        }
    }

    /// Verbaut das Modell zum ersten Mal Lagerteile, öffnet sich die Stückliste einmal von selbst.
    private func autoShowBOM() {
        guard !state.showBOM, !state.bomAutoShown, let bom = model.bom,
              bom.lines.contains(where: { !$0.eigenteil })
        else { return }
        state.bomAutoShown = true
        withAnimation(.snappy(duration: 0.25)) { state.showBOM = true }
    }

    /// Untertitel: im 3D-Bereich der Projektordner, im Bereich Dokumente das gezeigte Blatt.
    private var untertitel: String {
        if state.bereich == .dokumente {
            if let id = dokumente.blattID, let e = model.dokumente.uebersicht?.blatt(id) {
                return "Dokumente · \(e.titel)"
            }
            return "Dokumente"
        }
        return model.project.map { KevFormat.abbreviatedPath($0.path.deletingLastPathComponent().path) } ?? ""
    }

    /// Bereich Dokumente: Rückgängig über das Fenster, Teile im 3D-Bereich zeigen.
    private func dokumenteVerbinden() {
        let b = dokumente.bearbeiter
        b.model = model
        b.zeige = { [weak state, weak dokumente] id in
            state?.bereich = .dokumente
            dokumente?.waehle(.blatt(id))
        }
        b.melde = { [weak dokumente] t in dokumente?.melde(t, fehler: true) }
        dokumente.zeigeIm3D = { [weak state, weak model] teile in
            withAnimation(.snappy(duration: 0.2)) { state?.bereich = .modell }
            model?.actions?.select(teile)
            model?.actions?.focus(on: teile)
        }
        state.dokumenteZustand = dokumente
    }

    private var content: some View {
        NavigationSplitView(columnVisibility: $columns) {
            Group {
                if state.bereich == .dokumente {
                    DokumenteSeitenleiste(model: model, store: model.dokumente, zustand: dokumente)
                } else {
                    PartTreeView(model: model, state: state)
                }
            }
            .modifier(SpaltenBreite())
            .navigationSplitViewColumnWidth(min: 210, ideal: 260, max: 400)
        } detail: {
            // Der 3D-Bereich bleibt bestehen (Kamera, Metal-Ansicht), ruht aber, solange die Dokumente vorne sind
            ZStack {
                modellBereich
                    .opacity(state.bereich == .dokumente ? 0 : 1)
                    .allowsHitTesting(state.bereich != .dokumente)
                    .accessibilityHidden(state.bereich == .dokumente)
                if state.bereich == .dokumente {
                    DokumenteBereich(model: model, store: model.dokumente, zustand: dokumente)
                        .transition(.opacity)
                }
            }
            // Die Mitte nimmt genau ihre Spaltenbreite: Ist ein Inhalt (Bauplan, Berichte) im Mindestmaß breiter, drückt
            // er nicht das ganze Fenster über den Rand (Seitenleiste links und Inspektor rechts abgeschnitten)
            .modifier(SpaltenBreite())
            .clipped()
            .onChange(of: state.bereich) { _, b in
                session.controller?.viewport.mtkView?.isPaused = b == .dokumente
                if b == .modell { session.projectWindow?.makeFirstResponder(nil) }
            }
        }
        .inspector(isPresented: $state.showInspector) {
            Group {
                if state.bereich == .dokumente {
                    // kontextbezogen: Blatt, gewählter Bauplanschritt oder Einstellungen des Berichts
                    switch dokumente.auswahl {
                    case .bauplan: BauplanInspektor(model: model)
                    case .berichte: BerichteInspektor(model: model)
                    default: BlattInspektor(model: model, store: model.dokumente, zustand: dokumente)
                    }
                } else {
                    InspectorView(model: model)
                }
            }
            .modifier(SpaltenBreite())
            .inspectorColumnWidth(min: 260, ideal: 300, max: 440)
        }
        .toolbar {
            ToolbarItem(placement: .navigation) { BereichUmschalter(state: state) }  // Phase 6: 3D / Dokumente
            if state.bereich == .dokumente {
                DokumenteToolbar(model: model, store: model.dokumente, zustand: dokumente, state: state)
            } else {
                modellToolbar
            }
        }
    }

    @ToolbarContentBuilder
    private var modellToolbar: some ToolbarContent {
        ProjectToolbar(model: model, state: state, session: session)
        ToolbarItem(placement: .navigation) {  // Versionen: Variantenmenü in der Titelleiste
            VariantenMenu(model: model, store: model.versionen, zustand: versionen)
        }
        ToolbarItem(placement: .primaryAction) {
            Toggle(isOn: Binding(
                get: { versionen.zeigeLeiste },
                set: { on in withAnimation(.snappy(duration: 0.2)) { versionen.zeigeLeiste = on } }
            )) {
                Label("Versionen", systemImage: "clock.arrow.circlepath")
            }
            .help("Versionsleiste ein- oder ausblenden (⌥⌘V)")
        }
    }

    /// 3D-Bereich: Viewport mit Zeitleiste, Stückliste, Statusleiste und Versionsleiste. Die Versionsleiste ist eine
    /// Seitenleiste: Sie nimmt ihre Breite neben dem Viewport ein, Viewport und Stückliste werden schmaler und laufen
    /// nie unter sie (alles links davon auf die verbleibende Breite gezwungen und beschnitten). Wird es zu eng, wächst
    /// das Fenster beim Einblenden (`platzFuerLeiste`).
    private var modellBereich: some View {
            HStack(spacing: 0) {
                GeometryReader { geo in
                    VStack(spacing: 0) {
                        ViewportArea(model: model, state: state)
                            .overlay(alignment: .bottomLeading) {  // Versionen: laufender Vergleich
                                VergleichKarte(model: model, store: model.versionen, zustand: versionen)
                                    .padding(14)
                            }
                            .overlay(alignment: .bottom) { DurchspielenLeiste(model: model) }  // Phase 6, P6-A2
                        AnimationTimeline(model: model, animation: model.animation)  // Phase 5, nur mit Animation
                        if state.showBOM {
                            PanelResizeHandle(height: $state.bomHeight, range: ProjectWindowState.bomHeightRange)
                            ProjectBottomPanel(model: model, state: state)
                                .frame(height: min(state.bomHeight, max(160, geo.size.height - 260)))
                                .transition(.move(edge: .bottom).combined(with: .opacity))
                        }
                        StatusBar(model: model)
                    }
                    .frame(width: geo.size.width, height: geo.size.height)
                    .onAppear { modellGemessen(geo.size.width) }
                    .onChange(of: geo.size.width) { _, w in modellGemessen(w) }
                }
                .frame(minWidth: 0, maxWidth: .infinity)
                .clipped()
                if versionen.zeigeLeiste {  // Versionen: Seitenleiste rechts neben dem Viewport
                    Divider()
                    VersionenLeiste(model: model, store: model.versionen, zustand: versionen)
                        .fixedSize(horizontal: true, vertical: false)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            .onChange(of: versionen.zeigeLeiste) { _, an in
                if an { DispatchQueue.main.async { platzFuerLeiste() } }  // nach dem Layout mit Leiste
            }
            .modifier(VersionenBlaetter(model: model, zustand: versionen))
    }

    private func modellGemessen(_ w: CGFloat) {
        modellBreite = w
        modellMitLeiste = versionen.zeigeLeiste
    }

    /// Mindestbreite von Viewport und Stückliste neben der Versionsleiste.
    static let modellMinBreite: CGFloat = 520

    /// Versionsleiste eingeblendet: Bliebe dem Viewport weniger als `modellMinBreite`, wächst das Fenster um den
    /// Fehlbetrag (so weit der Bildschirm reicht, nach links, wenn rechts kein Platz ist); im Vollbild bleibt es.
    private func platzFuerLeiste() {
        guard let fenster = session.projectWindow, !fenster.styleMask.contains(.fullScreen),
              let schirm = fenster.screen?.visibleFrame
        else { return }
        let rest = modellMitLeiste ? modellBreite : modellBreite - VersionenZustand.breite - 1
        let fehlt = Self.modellMinBreite - rest
        guard fehlt > 1 else { return }
        var f = fenster.frame
        let breite = min(schirm.width, f.width + fehlt)
        let zuwachs = breite - f.width
        guard zuwachs > 1 else { return }
        f.size.width = breite
        if f.maxX > schirm.maxX { f.origin.x = max(schirm.minX, schirm.maxX - breite) }
        fenster.setFrame(f, display: true, animate: true)
    }
}

/// Projektfenster ohne Projekt (z. B. über das Fenstermenü geöffnet).
private struct NoProjectView: View {
    @EnvironmentObject private var session: AppSession

    var body: some View {
        ContentUnavailableView {
            Label("Kein Projekt geöffnet", systemImage: "cube.transparent")
        } description: {
            Text("Lege ein neues Projekt an oder öffne einen Ordner mit model.py.")
        } actions: {
            HStack {
                Button("Neues Projekt …") { session.requestNewProject() }
                Button("Öffnen …") { session.presentOpenPanel() }
            }
        }
    }
}

/// Werkzeugleiste des Projektfensters. Alles ruft AppActions.
struct ProjectToolbar: ToolbarContent {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    let session: AppSession

    private var actions: AppActions? { model.actions }

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .navigation) {
            Button {
                actions?.runModel()
            } label: {
                Label("Neu rechnen", systemImage: "arrow.clockwise")
            }
            .help("model.py neu rechnen (⌘R)")

            Toggle(isOn: Binding(get: { model.autoRun }, set: { actions?.setAutoRun($0) })) {
                Label("Auto-Lauf", systemImage: "bolt.badge.automatic")
            }
            .help(model.autoRun ? "Auto-Lauf an: rechnet nach jedem Speichern von model.py" : "Auto-Lauf aus")

            Toggle(isOn: Binding(get: { model.slowMotion }, set: { actions?.setSlowMotion($0) })) {
                Label("Zeitlupe", systemImage: "tortoise")
            }
            .help("Zeitlupe: Aufbau Teil für Teil verlangsamt zeigen")
        }

        ToolbarItemGroup(placement: .principal) {
            Menu {
                ForEach(StandardViewName.menuOrder, id: \.self) { view in
                    Button(view.title) { actions?.setStandardView(view) }
                }
                Divider()
                ForEach(StandardViewName.extraIsoOrder, id: \.self) { view in
                    Button(view.title) { actions?.setStandardView(view) }
                }
                Divider()
                Button("Alles einpassen") { actions?.focus(on: model.parts.filter(\.visible).map(\.id)) }
            } label: {
                Label("Ansicht", systemImage: "rotate.3d")
            }
            .help("Standardansichten (Tasten 1 bis 7)")

            Picker("Darstellung", selection: Binding(
                get: { model.displayStyle }, set: { actions?.setDisplayStyle($0) }
            )) {
                ForEach(DisplayStyle.allCases, id: \.self) { style in
                    Label(style.title, systemImage: style.symbol).tag(style)
                }
            }
            .pickerStyle(.segmented)
            .labelStyle(.iconOnly)
            .help("Darstellung: \(model.displayStyle.title)")

            Toggle(isOn: Binding(get: { model.sectionEnabled }, set: { _ in state.toggleSection(model) })) {
                Label("Schnitt", systemImage: "square.split.diagonal")
            }
            .help("Schnittebene ein oder aus (S)")

            Toggle(isOn: Binding(get: { model.measureMode }, set: { actions?.setMeasureMode($0) })) {
                Label("Messen", systemImage: "ruler")
            }
            .help("Messen: Elemente anklicken (M)")

            Button {
                state.showExplode.toggle()
            } label: {
                Label("Explosion", systemImage: "arrow.up.left.and.arrow.down.right")
            }
            .help("Explosionsdarstellung (E schaltet um)")
            .popover(isPresented: $state.showExplode, arrowEdge: .bottom) {
                ExplodePopover(model: model, state: state)
            }
        }

        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                actions?.saveScreenshot()
            } label: {
                Label("Bild speichern", systemImage: "camera")
            }
            .help("Bild der aktuellen Ansicht in output/ speichern")

            Menu {
                Button("STEP, STL und 3MF") { actions?.export(formats: ExportFormat.standard.map(\.rawValue)) }
                Divider()
                ForEach(ExportFormat.allCases) { format in
                    Button {
                        actions?.export(formats: [format.rawValue])
                    } label: {
                        Text(format.title)
                        Text(format.detail)
                    }
                }
                Divider()
                Button("Ausgabeordner im Finder zeigen") { session.revealProjectInFinder() }
            } label: {
                Label("Exportieren", systemImage: "square.and.arrow.up")
            } primaryAction: {
                actions?.export(formats: ExportFormat.standard.map(\.rawValue))
            }
            .disabled(model.parts.isEmpty)
            .help("Klick: STEP, STL und 3MF nach output/ (⌥⇧⌘E); Pfeil: einzelnes Format")

            Toggle(isOn: Binding(
                get: { state.showBOM }, set: { on in withAnimation(.snappy(duration: 0.2)) { state.showBOM = on } }
            )) {
                Label("Stückliste", systemImage: "list.bullet.rectangle")
            }
            .help("Stückliste mit Zuschnitt, Gewicht und Kosten ein- oder ausblenden (⇧⌘B)")

            Button {
                state.showInspector.toggle()
            } label: {
                Label("Inspektor", systemImage: "sidebar.trailing")
            }
            .help("Inspektor ein- oder ausblenden")
        }
    }
}

/// Regler für die Explosionsdarstellung.
private struct ExplodePopover: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Explosion").font(.headline)
                Spacer()
                Text(KevFormat.percent(model.explodeFactor))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            Slider(
                value: Binding(get: { model.explodeFactor }, set: { model.actions?.setExplode($0) }), in: 0...1
            ) {
                Text("Explosion")
            } minimumValueLabel: {
                Image(systemName: "square.stack.3d.up.fill").help("zusammengebaut")
            } maximumValueLabel: {
                Image(systemName: "square.stack.3d.forward.dottedline").help("voll auseinander")
            }
            .labelsHidden()
            HStack {
                Button("Zusammenbauen") { model.actions?.setExplode(0) }
                    .disabled(model.explodeFactor == 0)
                Spacer()
                Text("E schaltet um").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(width: 280)
    }
}

/// Inhalt einer Seitenspalte genau so breit wie die Spalte: Ist er im Mindestmaß breiter (lange Zeilen, Knöpfe), kürzt
/// und bricht er um, statt mittig über die Spalte hinauszuragen und links bzw. rechts abgeschnitten zu werden.
struct SpaltenBreite: ViewModifier {
    func body(content: Content) -> some View {
        GeometryReader { geo in
            content.frame(width: geo.size.width, height: geo.size.height)
        }
    }
}
