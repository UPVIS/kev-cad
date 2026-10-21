import KevCADCore
import SwiftUI

/// Statusleiste unter dem Viewport: Kernel, Lauf, Agent, Teile und Dreiecke.
struct StatusBar: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @State private var showWarnings = false

    var body: some View {
        HStack(spacing: 0) {
            kernel
            separator
            run
            Spacer(minLength: 16)
            agent
            separator
            counts
        }
        .font(.subheadline)
        .lineLimit(1)
        .padding(.horizontal, 12)
        .frame(height: 28)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    private var separator: some View {
        Divider().frame(height: 14).padding(.horizontal, 10)
    }

    // MARK: Kernel

    private var kernel: some View {
        Button {
            session.showLog()
        } label: {
            HStack(spacing: 6) {
                StatusDot(color: model.kernelState.color, pulsing: model.kernelState == .starting
                    || model.kernelState == .busy)
                Text(model.kernelState.title)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(model.kernelState.detail.map { "Kernel-Fehler: \($0) · Klick öffnet das Protokoll" }
            ?? "Klick öffnet das Protokoll")
        .contextMenu {
            Button("Protokoll zeigen") { session.showLog() }
            Button("Kernel neu starten") { model.actions?.restartKernel() }
        }
    }

    // MARK: Lauf

    @ViewBuilder
    private var run: some View {
        switch model.run {
        case .idle:
            Text(model.project == nil ? "Kein Projekt" : "Noch nicht gerechnet")
                .foregroundStyle(.secondary)
        case .running(_, let step, let index):
            HStack(spacing: 6) {
                ProgressView().controlSize(.mini)
                Text(Self.stepText(step: step, index: index))
            }
        case .finished(_, let duration, let parts, let warnings):
            HStack(spacing: 6) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text("fertig in \(KevFormat.duration(ms: duration)) · \(KevFormat.count(parts, one: "Teil", many: "Teile"))")
                if !warnings.isEmpty {
                    Button {
                        showWarnings.toggle()
                    } label: {
                        Label(
                            KevFormat.count(warnings.count, one: "Warnung", many: "Warnungen"),
                            systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                    }
                    .buttonStyle(.plain)
                    .popover(isPresented: $showWarnings, arrowEdge: .top) {
                        WarningsPopover(warnings: warnings)
                    }
                }
            }
        case .failed(_, _, let line, _):
            HStack(spacing: 6) {
                Image(systemName: "xmark.octagon.fill").foregroundStyle(.red)
                Text(line.map { "Fehler in Zeile \($0)" } ?? "Fehler im Lauf")
                    .foregroundStyle(.red)
            }
        }
    }

    /// "Schritt 3 · Bohrungen" bzw. "Rechnet …" ohne Schritt.
    static func stepText(step: String?, index: Int) -> String {
        switch (step, index) {
        case (let step?, let index) where index > 0: return "Schritt \(index) · \(step)"
        case (let step?, _): return step
        case (nil, let index) where index > 0: return "Schritt \(index)"
        default: return "Rechnet …"
        }
    }

    // MARK: Agent

    @ViewBuilder
    private var agent: some View {
        if model.agentConnected {
            HStack(spacing: 6) {
                Image(systemName: "sparkle")
                    .foregroundStyle(.tint)
                Text("Agent verbunden")
                if let activity = model.agentActivity {
                    Text("· \(activity)")
                        .foregroundStyle(.secondary)
                        .truncationMode(.tail)
                }
            }
            .help(model.agentActivity.map { "Agent: \($0)" } ?? "Ein Agent ist über MCP verbunden")
        } else {
            HStack(spacing: 6) {
                Image(systemName: "sparkle").foregroundStyle(.tertiary)
                Text("Kein Agent").foregroundStyle(.secondary)
            }
            .help("Claude verbindet sich über MCP (Port \(AppInfo.mcpPort))")
        }
    }

    // MARK: Zahlen

    private var counts: some View {
        let hidden = model.parts.filter { !$0.visible }.count
        var text = KevFormat.count(model.parts.count, one: "Teil", many: "Teile")
        if hidden > 0 { text += " (\(hidden) ausgeblendet)" }
        let triangles = model.triangleCount > 0 ? model.triangleCount : model.parts.reduce(0) { $0 + $1.triangles }
        return Text("\(text) · \(KevFormat.count(triangles, one: "Dreieck", many: "Dreiecke"))")
            .monospacedDigit()
            .foregroundStyle(.secondary)
    }
}

/// Farbiger Zustandspunkt, auf Wunsch pulsierend.
struct StatusDot: View {
    var color: Color
    var pulsing = false
    @State private var dim = false

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 8, height: 8)
            .opacity(pulsing && dim ? 0.35 : 1)
            .overlay(Circle().strokeBorder(.black.opacity(0.12), lineWidth: 0.5))
            .onAppear { animate() }
            .onChange(of: pulsing) { animate() }
    }

    private func animate() {
        guard pulsing else {
            dim = false
            return
        }
        withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { dim = true }
    }
}

private struct WarningsPopover: View {
    var warnings: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(KevFormat.count(warnings.count, one: "Warnung", many: "Warnungen") + " im letzten Lauf")
                .font(.headline)
            ForEach(Array(warnings.enumerated()), id: \.offset) { _, warning in
                Label(warning, systemImage: "exclamationmark.triangle.fill")
                    .symbolRenderingMode(.multicolor)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(width: 360, alignment: .leading)
    }
}
