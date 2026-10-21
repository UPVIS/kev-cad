import AppKit
import KevCADCore
import SwiftUI

// Gerüst aus AP1. Zuständig für alles in app/Sources/KevCAD: Oberfläche (siehe CLAUDE.md).

@main
struct KevCADApp: App {
    @StateObject private var model: AppModel
    private let controller: AppController

    init() {
        let model = AppModel()
        _model = StateObject(wrappedValue: model)
        controller = AppController(model: model)
        controller.start()
    }

    var body: some Scene {
        WindowGroup("Kev CAD") {
            ProjectWindowView(controller: controller)
                .environmentObject(model)
                .frame(minWidth: 900, minHeight: 600)
                .background(WindowPlacement())
        }
    }
}

/// Platzhalter-Fenster: Viewport und Statusleiste.
struct ProjectWindowView: View {
    let controller: AppController
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            KevViewport(controller: controller)
            Divider()
            HStack(spacing: 12) {
                Label(kernelText, systemImage: "circle")
                    .foregroundStyle(.secondary)
                Spacer()
                Text(AppInfo.isTestVariant ? "Testvariante" : "")
                    .foregroundStyle(.orange)
            }
            .font(.callout)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }

    private var kernelText: String {
        switch model.kernelState {
        case .stopped: return "Kernel: aus"
        case .starting: return "Kernel: startet"
        case .ready: return "Kernel: bereit"
        case .busy: return "Kernel: rechnet"
        case .failed(let m): return "Kernel: Fehler (\(m))"
        }
    }
}

/// Legt das Fenster der Testvariante auf den zweiten Monitor, damit Tests den Hauptbildschirm nicht stören.
struct WindowPlacement: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard AppInfo.isTestVariant, let window = view.window else { return }
            let screens = NSScreen.screens
            guard screens.count > 1 else { return }
            let frame = screens[1].visibleFrame
            let size = NSSize(width: min(1400, frame.width - 80), height: min(900, frame.height - 80))
            window.setFrame(
                NSRect(x: frame.minX + 40, y: frame.maxY - size.height - 40, width: size.width, height: size.height),
                display: true)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
