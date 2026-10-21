import AppKit
import Combine
import KevCADCore
import SwiftUI
import simd
import UniformTypeIdentifiers

/// Kennungen der Fenster (SwiftUI-Szenen).
enum WindowID {
    static let welcome = "welcome"
    static let project = "project"
    static let log = "log"
    static let catalog = "catalog"
}

/// Eintrag, den das Fenster Lagerkatalog beim Öffnen auswählen soll.
enum CatalogFocus: Hashable {
    case item(String)
    case material(String)
}

/// Zentrale der Oberfläche: hält AppModel, App-Kern bzw. Demo, „Zuletzt geöffnet“ und steuert, welches Fenster offen ist.
///
/// Vertrag (CLAUDE.md): Die Oberfläche liest `AppModel` und ruft nur `AppActions`. Im Demomodus ist `actions` die
/// eigene `DemoActions`, sonst der `AppController` des App-Kerns.
@MainActor
final class AppSession: ObservableObject {
    let model: AppModel
    /// App-Kern. Im Demomodus nur vorhanden, wenn `KEVCAD_DEMO_VIEWPORT=metal` gesetzt ist (dann nicht gestartet).
    let controller: AppController?
    let demo: DemoActions?
    let recents: RecentProjects
    let keyboard = KeyboardGuard()

    /// Willkommensfenster soll das Formular „Neues Projekt“ zeigen.
    @Published var newProjectRequested = false
    /// Das Fenster Lagerkatalog soll diesen Eintrag bzw. Abschnitt zeigen (wird dort verbraucht).
    @Published var catalogFocus: CatalogFocus?
    @Published var catalogSectionRequest: CatalogSection?
    /// Phase 3: Auftrag für das Fenster „Zukaufteil hinzufügen …“ (wird dort verbraucht), siehe ZukaufSession.swift.
    @Published var zukaufRequest: ZukaufDialogRequest?

    weak var projectWindow: NSWindow? {
        didSet { keyboard.projectWindow = projectWindow }
    }
    weak var welcomeWindow: NSWindow?

    private(set) var openWindowAction: OpenWindowAction?
    private var dismissWindowAction: DismissWindowAction?
    private var cancellables: Set<AnyCancellable> = []

    init() {
        let model = AppModel()
        self.model = model
        if AppInfo.isDemoMode {
            let config = DemoConfiguration.fromEnvironment()
            controller = config.metalViewport ? AppController(model: model) : nil
            let demo = DemoActions(model: model, config: config)
            model.actions = demo
            self.demo = demo
            recents = DemoData.makeRecents()
            demo.start()
        } else {
            let controller = AppController(model: model)
            self.controller = controller
            demo = nil
            recents = RecentProjects()
            controller.start()
        }

        model.$project
            .dropFirst()
            .removeDuplicates { $0?.path == $1?.path }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] project in self?.projectChanged(project) }
            .store(in: &cancellables)
        if let project = model.project { recents.note(project.path, name: project.name) }
        keyboard.install()
        Self.applyAppearanceOverride()
    }

    /// `KEVCAD_APPEARANCE=light` oder `dark` erzwingt das Erscheinungsbild (für Fensterbilder in beiden Varianten).
    private static func applyAppearanceOverride() {
        let value = ProcessInfo.processInfo.environment["KEVCAD_APPEARANCE"]?.lowercased()
        let name: NSAppearance.Name? = value == "light" ? .aqua : (value == "dark" ? .darkAqua : nil)
        guard let name else { return }
        DispatchQueue.main.async { NSApplication.shared.appearance = NSAppearance(named: name) }
    }

    var actions: AppActions? { model.actions }

    private var launched = false

    /// Einmal beim ersten Erscheinen des Willkommensfensters: ist schon ein Projekt offen, gleich zum Projektfenster.
    /// Gibt `true` zurück, wenn das Willkommensfenster unsichtbar bleiben soll.
    func launchFinished() -> Bool {
        guard !launched else { return false }
        launched = true
        if demo?.config.openLog == true { showLog() }
        guard model.project != nil else { return false }
        showProjectWindow()
        if let config = demo?.config, config.start == .catalog {
            // Nach dem Projektfenster öffnen, damit der Lagerkatalog vorne liegt
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                if config.catalogEntry == "vorschlaege" {
                    self?.showCatalog(focus: .item("winkel-alu-30x30x3"), section: .suggestions)
                } else {
                    self?.showCatalog(focus: config.catalogEntry.map { CatalogFocus.item($0) })
                }
            }
        }
        return true
    }

    // MARK: Fenster

    /// Jedes Fenster meldet sich beim Erscheinen, damit die Sitzung später Fenster öffnen und schließen kann.
    func attach(openWindow: OpenWindowAction, dismissWindow: DismissWindowAction) {
        openWindowAction = openWindow
        dismissWindowAction = dismissWindow
    }

    func showWelcome() {
        openWindowAction?(id: WindowID.welcome)
    }

    func showProjectWindow() {
        guard model.project != nil else { return showWelcome() }
        openWindowAction?(id: WindowID.project)
        dismissWindowAction?(id: WindowID.welcome)
    }

    func showLog() {
        openWindowAction?(id: WindowID.log)
    }

    /// Fenster Lagerkatalog öffnen, auf Wunsch mit einem Eintrag ausgewählt oder einem Abschnitt (Vorschläge).
    func showCatalog(focus: CatalogFocus? = nil, section: CatalogSection? = nil) {
        if let focus { catalogFocus = focus }
        if let section { catalogSectionRequest = section }
        openWindowAction?(id: WindowID.catalog)
    }

    private func projectChanged(_ project: ProjectInfo?) {
        if let project {
            recents.note(project.path, name: project.name)
            showProjectWindow()
        } else {
            showWelcome()
            dismissWindowAction?(id: WindowID.project)
        }
    }

    // MARK: Projekte

    /// Formular „Neues Projekt“ zeigen (im Willkommensfenster).
    func requestNewProject() {
        newProjectRequested = true
        showWelcome()
    }

    /// Ordner für ein neues Projekt: unter `AppInfo.projectsDirectory`, ohne Namenskollision.
    func proposedFolder(for name: String) -> URL {
        ProjectLocator.uniqueFolder(named: name, in: AppInfo.projectsDirectory)
    }

    func createProject(named name: String, template: ProjectTemplate) {
        let folder = proposedFolder(for: name)
        try? FileManager.default.createDirectory(at: AppInfo.projectsDirectory, withIntermediateDirectories: true)
        model.append(LogLine(text: "Neues Projekt „\(folder.lastPathComponent)“ (\(template.title)) unter "
            + KevFormat.abbreviatedPath(folder.path)))
        actions?.newProject(at: folder, template: template.rawValue)
    }

    /// Öffnet einen Projektordner nach Prüfung auf `model.py`.
    func openProject(at url: URL) {
        let folder = ProjectLocator.projectFolder(for: url)
        if let current = model.project, RecentProjects.normalizedPath(current.path) == RecentProjects.normalizedPath(folder)
        {
            showProjectWindow()
            return
        }
        if demo == nil, let problem = ProjectLocator.check(folder) {
            presentProblem(problem, folder: folder)
            return
        }
        actions?.openProject(at: folder)
    }

    func openRecent(_ item: RecentProject) {
        if item.isMissing {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "„\(item.name)“ wurde nicht gefunden"
            alert.informativeText = "Der Ordner \(KevFormat.abbreviatedPath(item.path)) existiert nicht mehr. "
                + "Soll der Eintrag aus „Zuletzt geöffnet“ entfernt werden?"
            alert.addButton(withTitle: "Entfernen")
            alert.addButton(withTitle: "Behalten")
            run(alert) { [weak self] response in
                if response == .alertFirstButtonReturn { self?.recents.remove(item.url) }
            }
            return
        }
        openProject(at: item.url)
    }

    func presentOpenPanel() {
        let panel = NSOpenPanel()
        panel.title = "Projekt öffnen"
        panel.message = "Projektordner mit model.py wählen"
        panel.prompt = "Öffnen"
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.pythonScript, .folder]
        panel.directoryURL = FileManager.default.fileExists(atPath: AppInfo.projectsDirectory.path)
            ? AppInfo.projectsDirectory : FileManager.default.homeDirectoryForCurrentUser
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor in self?.openProject(at: url) }
        }
    }

    private func presentProblem(_ problem: ProjectLocator.Problem, folder: URL) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        switch problem {
        case .missingModel: alert.messageText = "Kein Kev-CAD-Projekt"
        case .notFound: alert.messageText = "Ordner nicht gefunden"
        case .notADirectory: alert.messageText = "Kein Ordner"
        }
        alert.informativeText = problem.errorDescription ?? ""
        alert.addButton(withTitle: "OK")
        run(alert) { _ in }
    }

    private func run(_ alert: NSAlert, completion: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window = NSApp.keyWindow ?? welcomeWindow ?? projectWindow {
            alert.beginSheetModal(for: window, completionHandler: completion)
        } else {
            completion(alert.runModal())
        }
    }

    // MARK: Datei und Ausgabe

    func openModelInEditor() {
        guard let file = model.project?.modelFile else { return }
        NSWorkspace.shared.open(file)
    }

    func revealProjectInFinder() {
        guard let project = model.project else { return }
        let output = project.path.appendingPathComponent("output", isDirectory: true)
        if FileManager.default.fileExists(atPath: output.path) {
            NSWorkspace.shared.activateFileViewerSelecting([output])
        } else {
            NSWorkspace.shared.activateFileViewerSelecting([project.path])
        }
    }

    /// Befehl, mit dem Claude Code die Werkzeuge von Kev CAD bekommt (PLAN-MVP.md Abschnitt 11).
    static var claudeCommand: String {
        let bridge = AppInfo.repoDirectory?.appendingPathComponent("kernel/.venv/bin/kevcad-mcp").path
            ?? "<Repo>/kernel/.venv/bin/kevcad-mcp"
        return "claude mcp add --scope user kevcad -- \"\(bridge)\""
    }

    func copyClaudeCommand() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(Self.claudeCommand, forType: .string)
    }

    static var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "Version \(version) (\(build))"
    }
}

/// Vorlage für neue Projekte (Werte laut PROTOCOL.md `PROJECT_NEW.template`).
enum ProjectTemplate: String, CaseIterable, Identifiable {
    case example
    case empty

    var id: String { rawValue }

    var title: String {
        switch self {
        case .example: return "Beispiel"
        case .empty: return "Leer"
        }
    }

    var detail: String {
        switch self {
        case .example: return "Wandhalter mit Grundplatte, Lasche und Bohrungen zum Ausprobieren"
        case .empty: return "Nur das Grundgerüst von model.py"
        }
    }
}

// MARK: Gemeinsame Befehle der Oberfläche (rufen nur AppActions)

extension AppModel {
    /// Teile der aktuellen Auswahl (Referenzen wie "Lasche#f3" zählen als Teil "Lasche").
    var selectedPartIDs: [String] { PartTree.partIDs(fromRefs: selection.map(\.ref)) }

    var hasProject: Bool { project != nil }

    var isRunning: Bool {
        if case .running = run { return true }
        return false
    }

    func hideSelection() {
        let ids = selectedPartIDs
        guard !ids.isEmpty else { return }
        actions?.setVisibility(ids, visible: false)
    }

    func isolateSelection() {
        let ids = selectedPartIDs
        guard !ids.isEmpty else { return }
        actions?.isolate(ids)
    }

    /// F: Auswahl einpassen; ohne Auswahl alle sichtbaren Teile.
    func fitSelection() {
        let refs = selection.isEmpty ? parts.filter(\.visible).map(\.id) : selection.map(\.ref)
        actions?.focus(on: refs)
    }

    func clearSelection() {
        actions?.select([])
    }

    func toggleMeasureMode() {
        actions?.setMeasureMode(!measureMode)
    }

    func removeMeasurement(_ id: UUID) {
        (actions as? MeasurementRemoving)?.removeMeasurement(id: id)
    }

    var canRemoveSingleMeasurement: Bool { actions is MeasurementRemoving }

    /// Hüllquader aller Teile (für Schnitt-Regler und Vorschau).
    var sceneBounds: (min: SIMD3<Float>, max: SIMD3<Float>)? {
        guard let first = parts.first else { return nil }
        var lo = first.bboxMin
        var hi = first.bboxMax
        for part in parts.dropFirst() {
            lo = simd_min(lo, part.bboxMin)
            hi = simd_max(hi, part.bboxMax)
        }
        return (lo, hi)
    }
}
