import KevCADCore
import SwiftUI

/// Mitte des Projektfensters: Viewport mit Einblendungen (Fehlerband, Schnittleiste, Laufanzeige, Agent, Messhinweis).
struct ViewportArea: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState

    var body: some View {
        viewport
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .overlay { emptyState }
            .overlay(alignment: .top) { topOverlays }
            .overlay(alignment: .bottom) { bottomOverlays }
            .animation(.snappy(duration: 0.25), value: bannerRun)
            .animation(.snappy(duration: 0.25), value: model.sectionEnabled)
            .animation(.snappy(duration: 0.25), value: model.agentActivity)
            .animation(.snappy(duration: 0.25), value: model.measureMode)
            .animation(.snappy(duration: 0.25), value: model.isRunning)
            .animation(.snappy(duration: 0.25), value: inventoryKey)
            .animation(.snappy(duration: 0.25), value: pruefKey)
    }

    // MARK: Prüfung

    /// Kennung der offenen Befunde (Durchdringungen …); weggeklickt bleibt das Band aus, bis sie sich ändern.
    private var pruefKey: String? {
        guard let p = model.pruefung, !p.bandText.isEmpty else { return nil }
        return p.schluessel
    }

    // MARK: Inventar-Regel

    /// Kennung der aktuellen Verstöße; weggeklickt bleibt das Band aus, bis sie sich ändern.
    private var inventoryKey: String? {
        let names = model.inventoryViolations
        return names.isEmpty ? nil : names.joined(separator: "|")
    }

    @ViewBuilder
    private var viewport: some View {
        if let controller = session.controller {
            KevViewport(controller: controller)
        } else if let demo = session.demo {
            DemoViewport(model: model, demo: demo)
        } else {
            Color(nsColor: .windowBackgroundColor)
        }
    }

    // MARK: Oben: Fehlerband, Schnitt, Lauf

    /// Laufnummer des Fehlers, wenn das Band sichtbar ist.
    private var bannerRun: Int? {
        if case .failed(let run, _, _, _) = model.run, state.dismissedErrorRun != run { return run }
        return nil
    }

    private var topOverlays: some View {
        VStack(spacing: 10) {
            if case .failed(let run, let message, let line, let excerpt) = model.run, state.dismissedErrorRun != run {
                ErrorBanner(
                    run: run, message: message, line: line, excerpt: excerpt,
                    openModel: { session.openModelInEditor() },
                    rerun: { model.actions?.runModel() },
                    dismiss: { state.dismissedErrorRun = run }
                )
                .frame(maxWidth: 760)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
            if let key = inventoryKey, state.dismissedInventory != key {
                InventoryBanner(model: model) { state.dismissedInventory = key }
                    .frame(maxWidth: 820)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            if (pruefKey != nil && state.dismissedPruefung != pruefKey) || (state.pruefListeOffen && model.pruefung != nil) {
                PruefBanner(model: model, state: state) { state.dismissedPruefung = pruefKey }
                    .frame(maxWidth: 820)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            if case .running(let run, let step, let index) = model.run {
                RunPill(run: run, text: StatusBar.stepText(step: step, index: index), slow: model.slowMotion)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            if model.sectionEnabled {
                SectionBar(model: model, state: state)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
    }

    // MARK: Unten: Messen, Agent

    private var bottomOverlays: some View {
        HStack(spacing: 8) {
            if model.measureMode {
                Pill(symbol: "ruler", tint: .orange) {
                    Text("Messen: ein oder zwei Elemente anklicken")
                } trailing: {
                    Button("Fertig") { model.actions?.setMeasureMode(false) }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if pruefKey == nil, !state.pruefListeOffen, let p = model.pruefung, !p.montageSchritte.isEmpty {
                Pill(symbol: "checkmark.seal", tint: .green) {
                    Text("Prüfung in Ordnung")
                } trailing: {
                    Button("Montage") {
                        state.pruefTab = "montage"
                        withAnimation(.snappy(duration: 0.2)) { state.pruefListeOffen = true }
                    }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if model.agentConnected, let activity = model.agentActivity {
                Pill(symbol: "sparkle", tint: .accentColor) {
                    Text("Agent \(activity)")
                } trailing: {
                    EmptyView()
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .padding(.bottom, 14)
        .padding(.horizontal, 16)
    }

    // MARK: Leer

    @ViewBuilder
    private var emptyState: some View {
        if model.parts.isEmpty && !model.isRunning {
            VStack(spacing: 10) {
                Image(systemName: "cube.transparent")
                    .font(.system(size: 44, weight: .light))
                    .foregroundStyle(.tertiary)
                Text("Noch keine Geometrie")
                    .font(.title3.weight(.medium))
                Text("Rechne model.py mit ⌘R oder bitte Claude, etwas zu bauen.")
                    .foregroundStyle(.secondary)
                Button("Neu rechnen") { model.actions?.runModel() }
                    .padding(.top, 4)
            }
            .padding(24)
        }
    }
}

/// Kapsel mit Glas-Hintergrund für kurze Meldungen im Viewport.
struct Pill<Content: View, Trailing: View>: View {
    var symbol: String
    var tint: Color
    @ViewBuilder var content: Content
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
            content
                .lineLimit(1)
                .truncationMode(.tail)
            trailing
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(Capsule().fill(.regularMaterial))
        .overlay(Capsule().strokeBorder(.primary.opacity(0.08), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.14), radius: 8, y: 2)
    }
}

/// Laufender Lauf: "Lauf 4 · Schritt 3 · Bohrungen".
private struct RunPill: View {
    var run: Int
    var text: String
    var slow: Bool

    var body: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Lauf \(run)")
                .foregroundStyle(.secondary)
            Text(text)
                .fontWeight(.medium)
            if slow {
                Image(systemName: "tortoise.fill")
                    .foregroundStyle(.secondary)
                    .help("Zeitlupe")
            }
        }
        .font(.callout)
        .monospacedDigit()
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(Capsule().fill(.regularMaterial))
        .overlay(Capsule().strokeBorder(.primary.opacity(0.08), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.14), radius: 8, y: 2)
    }
}

/// Schnittebene: Achse, Lage, Aus.
private struct SectionBar: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState

    var body: some View {
        let range = state.sectionRange(model)
        HStack(spacing: 12) {
            Label("Schnitt", systemImage: "square.split.diagonal")
                .fontWeight(.medium)
            Picker("Achse", selection: Binding(
                get: { state.sectionAxis }, set: { state.setSectionAxis($0, model) }
            )) {
                ForEach(ProjectWindowState.axes, id: \.self) { Text($0.uppercased()).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 96)
            Slider(
                value: Binding(
                    get: { min(max(state.sectionOffset, range.lowerBound), range.upperBound) },
                    set: {
                        state.sectionOffset = $0
                        state.applySection(model)
                    }),
                in: range
            )
            .controlSize(.small)
            .frame(minWidth: 140, maxWidth: 220)
            Text(KevFormat.mm(state.sectionOffset))
                .monospacedDigit()
                .foregroundStyle(.secondary)
                .frame(width: 74, alignment: .trailing)
            Button {
                state.toggleSection(model)
            } label: {
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 16, height: 16)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Schnitt aus (S)")
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(Capsule().fill(.regularMaterial))
        .overlay(Capsule().strokeBorder(.primary.opacity(0.08), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.14), radius: 8, y: 2)
        .onAppear { state.adoptSectionIfUnknown(model) }
    }
}
