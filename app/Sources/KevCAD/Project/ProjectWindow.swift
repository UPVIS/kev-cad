import KevCADCore
import SwiftUI

/// Projektfenster: links Teilebaum, Mitte Viewport mit Statusleiste, rechts Inspektor.
struct ProjectWindow: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @StateObject private var state = ProjectWindowState()
    @State private var columns = NavigationSplitViewVisibility.all
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
        .navigationTitle(model.project?.name ?? "Kev CAD")
        .navigationSubtitle(model.project.map { KevFormat.abbreviatedPath($0.path.deletingLastPathComponent().path) } ?? "")
        .onAppear {
            session.attach(openWindow: openWindow, dismissWindow: dismissWindow)
            SelfTest.runIfRequested(session)
            CatalogSelfTest.runIfRequested(session)
            if let config = session.demo?.config, config.usesGestell { state.showBOM = true }
        }
        .onChange(of: model.bom?.run) { _, _ in autoShowBOM() }
    }

    /// Verbaut das Modell zum ersten Mal Lagerteile, öffnet sich die Stückliste einmal von selbst.
    private func autoShowBOM() {
        guard !state.showBOM, !state.bomAutoShown, let bom = model.bom,
              bom.lines.contains(where: { !$0.eigenteil })
        else { return }
        state.bomAutoShown = true
        withAnimation(.snappy(duration: 0.25)) { state.showBOM = true }
    }

    private var content: some View {
        NavigationSplitView(columnVisibility: $columns) {
            PartTreeView(model: model, state: state)
                .navigationSplitViewColumnWidth(min: 210, ideal: 260, max: 400)
        } detail: {
            GeometryReader { geo in
                VStack(spacing: 0) {
                    ViewportArea(model: model, state: state)
                    if state.showBOM {
                        PanelResizeHandle(height: $state.bomHeight, range: ProjectWindowState.bomHeightRange)
                        BOMPanel(model: model, state: state)
                            .frame(height: min(state.bomHeight, max(160, geo.size.height - 260)))
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                    StatusBar(model: model)
                }
            }
        }
        .inspector(isPresented: $state.showInspector) {
            InspectorView(model: model)
                .inspectorColumnWidth(min: 260, ideal: 300, max: 440)
        }
        .toolbar {
            ProjectToolbar(model: model, state: state, session: session)
        }
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
            .help("Klick: STEP, STL und 3MF nach output/ (⇧⌘E); Pfeil: einzelnes Format")

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
