import Foundation

// STUB aus der Vertragsphase. Zuständig: App-Kern. Die öffentliche Oberfläche (init, start, AppActions,
// KevViewport) bleibt stabil; der Inhalt wird vollständig ersetzt.

/// Verbindet AppModel mit dem Kernel (Prozess, Socket, Protokoll) und dem Viewport.
@MainActor
public final class AppController: AppActions {
    public let model: AppModel

    public init(model: AppModel) {
        self.model = model
        model.actions = self
    }

    /// Startet den Kernel-Server und verbindet sich mit ihm.
    public func start() {
        model.kernelState = .stopped
        model.append(LogLine(level: .warning, text: "AppController ist noch ein Platzhalter"))
    }

    public func stop() {}

    public func openProject(at url: URL) {
        model.project = ProjectInfo(path: url, name: url.lastPathComponent, modelFile: url.appendingPathComponent("model.py"))
    }

    public func newProject(at url: URL, template: String) { openProject(at: url) }
    public func runModel() {}
    public func setVisibility(_ partIDs: [String], visible: Bool) {}
    public func isolate(_ partIDs: [String]) {}
    public func showAll() {}
    public func focus(on refs: [String]) {}
    public func select(_ refs: [String]) {}
    public func setStandardView(_ view: StandardViewName) {}
    public func setDisplayStyle(_ style: DisplayStyle) { model.displayStyle = style }
    public func setSection(enabled: Bool, axis: String, offset: Double) { model.sectionEnabled = enabled }
    public func setExplode(_ factor: Double) { model.explodeFactor = factor }
    public func setMeasureMode(_ on: Bool) { model.measureMode = on }
    public func clearMeasurements() { model.measurements = [] }
    public func setAutoRun(_ on: Bool) { model.autoRun = on }
    public func setSlowMotion(_ on: Bool) { model.slowMotion = on }
    public func export(formats: [String]) {}
    public func saveScreenshot() {}
    public func restartKernel() { start() }
}
