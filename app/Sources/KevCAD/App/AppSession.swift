#if os(macOS)
#if os(macOS)
import AppKit
#else
import UIKit
#endif
#else
import UIKit
#endif
import Combine
import KevCADCore
import SwiftUI
import simd
import UniformTypeIdentifiers

/// Kennungen der Fenster (SwiftUI-Szenen).
enum WindowID {
    static let project = "project"
    static let log = "log"
    static let catalog = "catalog"
    /// I-2b: Mac-Fenster „iPad koppeln“ (QR-Code, gekoppelte iPads)
    static let kopplung = "kopplung"
}

/// Eintrag, den das Fenster Lagerkatalog beim Öffnen auswählen soll.
enum CatalogFocus: Hashable {
    case item(String)
    case material(String)
}

/// Zentrale der Oberfläche: hält AppModel, App-Kern bzw. Demo, „Zuletzt geöffnet“, den Entwurf (leeres Projekt ohne
/// Dialog, V2-3) und das Hauptfenster. Gemeinsam für Mac und iPad (PLAN-IPAD.md, I2); was nur am Mac geht (Fenster,
/// Ablagedialoge, Tastaturwächter), steht hinter `#if os(macOS)`.
///
/// Vertrag (CLAUDE.md): Die Oberfläche liest `AppModel` und ruft nur `AppActions`. Im Demomodus ist `actions` die
/// eigene `DemoActions`, sonst (und im Demo-Lauf des App-Kerns, `KEVCAD_DEMO_VIEWPORT=kern`) der `AppController`.
@MainActor
final class AppSession: ObservableObject {
    let model: AppModel
    /// App-Kern. Im Demomodus nur vorhanden, wenn `KEVCAD_DEMO_VIEWPORT=metal` gesetzt ist (dann nicht gestartet) oder
    /// `kern` (dann gestartet: Demo-Lauf des App-Kerns, Vorgabe auf dem iPad bis zur Verbindung mit dem Mac).
    let controller: AppController?
    let demo: DemoActions?
    let recents: RecentProjects
    #if os(macOS)
    let keyboard = KeyboardGuard()
    #endif

    /// Das Fenster Lagerkatalog soll diesen Eintrag bzw. Abschnitt zeigen (wird dort verbraucht).
    @Published var catalogFocus: CatalogFocus?
    @Published var catalogSectionRequest: CatalogSection?
    /// Phase 3: Auftrag für das Fenster „Zukaufteil hinzufügen …“ (wird dort verbraucht), siehe ZukaufSession.swift.
    @Published var zukaufRequest: ZukaufDialogRequest?
    /// iPad: offene Dateiwahl (Dateien-App), gezeigt vom Hauptfenster (`dateienWaehlen`, I-8). Am Mac immer nil.
    @Published var dateiWahl: DateiWahl?
    /// iPad: Protokoll, Lagerkatalog oder Zukaufteil als Blatt über dem Hauptfenster (am Mac eigene Fenster, I-8);
    /// die Projektliste aus der iCloud („Öffnen …“, I-7).
    @Published var padBlatt: PadBlatt?
    /// iPad: Namensabfrage für ein neues Projekt (I-7). Am Mac entsteht ein Entwurf ohne Namen in der Ablage der App; das
    /// iPad kann keinen Entwurf beim Mac ablegen, also fragt es den Namen und der Kernel legt das Projekt gleich an.
    @Published var neuesProjektFragen = false
    /// iPad: Eintrag aus „Zuletzt geöffnet“, dessen Ordner fehlt; das Hauptfenster fragt „Entfernen?“ (am Mac ein NSAlert).
    @Published var fehlendesProjekt: RecentProject?
    /// Die zuletzt gezeigte Dateiwahl, bis ihr Ergebnis da ist (SwiftUI schließt den Dialog teils vor dem Ergebnis).
    private var dateiWahlOffen: DateiWahl?

    /// V2-3: kurze Meldung in der Kopfleiste (Umbenennen ging nicht, Name entsteht im Code …).
    @Published var meldung: Meldung?
    /// V2-3: Menü „Benennen …“ (⇧⌘S) bittet die Kopfleiste, den Projektnamen zu bearbeiten (zählt hoch).
    @Published var umbenennenAnfrage = 0

    struct Meldung: Equatable {
        var text: String
        var fehler: Bool
        var zeit = Date()
    }

    /// V2-3: Ablage der Entwürfe dieser Variante (Application Support, nicht ~/Documents).
    let entwuerfe = EntwurfAblage.standard
    /// Beim Start ein leeres Projekt anlegen (nicht beim Wiederherstellen nach einem Update, nicht im Demomodus und
    /// nicht bei Selbsttests, die ihr eigenes Projekt öffnen).
    var startEntwurfErlaubt = false
    var letztesProjekt: URL?
    #if os(macOS)
    let fensterRandSteuerung = FensterRand()
    #endif
    /// Fläche des Viewers im Fenster (Punkte, oben links), für `viewerKlickBeobachten`.
    var viewerRahmen: CGRect = .zero
    /// Fenstergröße beim letzten Blick auf die Werkstatt; im Fokus behalten die ausgeblendeten Kacheln diese Maße.
    var werkstattGroesse: CGSize?
    var viewerKlickMonitor: Any?
    /// Abos der V2-Oberfläche (Entwurf beim Start, Modus und Kacheln merken).
    var oberflaechenAbos: Set<AnyCancellable> = []

    #if os(macOS)
    weak var projectWindow: NSWindow? {
        didSet { keyboard.projectWindow = projectWindow }
    }
    #endif

    private(set) var openWindowAction: OpenWindowAction?
    private var dismissWindowAction: DismissWindowAction?
    private var cancellables: Set<AnyCancellable> = []

    init() {
        let model = AppModel()
        self.model = model
        // Vor controller.start(): der App-Kern löscht die Marke beim Wiederherstellen nach einem Update
        let wiederherstellen = !AppInfo.isDemoMode && AppController.wiederherstellenAngefordert
        AppSession.oberflaecheVorbelegen(model.oberflaeche)
        let demoConfig = AppInfo.isDemoMode ? DemoConfiguration.fromEnvironment() : nil
        if let config = demoConfig, !config.kernDemo {
            controller = config.metalViewport ? AppController(model: model) : nil
            let demo = DemoActions(model: model, config: config)
            model.actions = demo
            self.demo = demo
            recents = DemoData.makeRecents()
            demo.start()
        } else {
            // Mit Kernel, oder Demo-Lauf des App-Kerns (KEVCAD_DEMO_VIEWPORT=kern): echte Geometrie über den Weg der
            // Kernel-Nachrichten, die Aktionen kommen vom App-Kern. Die Liste „Zuletzt geöffnet“ ist dann die der Demo.
            let controller = AppController(model: model)
            self.controller = controller
            demo = nil
            recents = demoConfig != nil ? DemoData.makeRecents() : RecentProjects(exists: Self.projektordnerVorhanden)
            controller.start()
        }

        #if os(iOS)
        // Kein Finder auf dem iPad: Was der Kern nach einer Aktion im Finder zeigen würde (Export, CSV, Video, Bild,
        // Referenz, 3MF), geht hier über das Teilen-Blatt, vom Mac geholt (I-8)
        controller?.revealFiles = { [weak self] urls in self?.dateienTeilen(urls) }
        #endif
        controller?.projektBenennen = { [weak self] name in
            self?.projektUmziehen(name) ?? .failure(FlaecheFehler("Diese Sitzung ist beendet."))
        }

        model.$project
            .dropFirst()
            .removeDuplicates { $0?.path == $1?.path }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] project in self?.projectChanged(project) }
            .store(in: &cancellables)
        if let project = model.project, !entwuerfe.enthaelt(project.path) {
            recents.note(project.path, name: project.name)
        }
        letztesProjekt = model.project?.path
        #if os(macOS)
        keyboard.install()
        Self.applyAppearanceOverride()
        DokumenteSelfTest.projektOeffnenWennVerlangt(self)  // Phase 6: Selbsttest startet mit offenem Projekt
        #endif
        // iPad: Selbsttests der Oberfläche folgen in I-9
        entwurfVorbereiten(wiederherstellen: wiederherstellen)
        Startzeiten.marke("Sitzung angelegt")
        oberflaecheMerken()
        NotificationCenter.default.addObserver(
            forName: PlattformApp.wirdBeendet, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.beimBeenden() }
        }
    }

    #if os(macOS)
    /// `KEVCAD_APPEARANCE=light` oder `dark` erzwingt das Erscheinungsbild (für Fensterbilder in beiden Varianten).
    private static func applyAppearanceOverride() {
        let value = ProcessInfo.processInfo.environment["KEVCAD_APPEARANCE"]?.lowercased()
        let name: NSAppearance.Name? = value == "light" ? .aqua : (value == "dark" ? .darkAqua : nil)
        guard let name else { return }
        DispatchQueue.main.async { NSApplication.shared.appearance = NSAppearance(named: name) }
    }
    #endif

    var actions: AppActions? { model.actions }

    private var launched = false

    /// Einmal beim ersten Erscheinen des Hauptfensters: Protokoll und Lagerkatalog für den Demomodus.
    @discardableResult
    func launchFinished() -> Bool {
        guard !launched else { return false }
        launched = true
        if demo?.config.openLog == true { showLog() }
        guard model.project != nil else { return false }
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
    #if os(macOS)
    /// I-2b: Fenster „iPad koppeln“ zeigen (neuer QR-Code beim Öffnen).
    func ipadKoppelnZeigen() {
        openWindowAction?(id: WindowID.kopplung)
    }
    #endif

    func attach(openWindow: OpenWindowAction, dismissWindow: DismissWindowAction) {
        openWindowAction = openWindow
        dismissWindowAction = dismissWindow
    }

    func showProjectWindow() {
        openWindowAction?(id: WindowID.project)
    }

    /// Protokoll als eigenes Fenster am Mac; auf dem iPad gibt es nur eine Szene, dort als Blatt (`padBlatt`).
    func showLog() {
        #if os(macOS)
        openWindowAction?(id: WindowID.log)
        #else
        padBlatt = .protokoll
        #endif
    }

    /// Fenster Lagerkatalog öffnen, auf Wunsch mit einem Eintrag ausgewählt oder einem Abschnitt (Vorschläge).
    func showCatalog(focus: CatalogFocus? = nil, section: CatalogSection? = nil) {
        if let focus { catalogFocus = focus }
        if let section { catalogSectionRequest = section }
        #if os(macOS)
        openWindowAction?(id: WindowID.catalog)
        #else
        padBlatt = .lagerkatalog
        #endif
    }

    private func projectChanged(_ project: ProjectInfo?) {
        let vorher = letztesProjekt
        letztesProjekt = project?.path
        if let project {
            if entwuerfe.enthaelt(project.path) {
                entwuerfe.merken(project.path)  // Inhalt beim Anlegen, um später „leer“ zu erkennen
            } else {
                recents.note(project.path, name: project.name)
                model.oberflaechenActions?.zeigeUebersicht(false)
            }
            showProjectWindow()
        }
        // Der Entwurf von eben bleibt leer: weg damit, sobald der Kernel das andere Projekt offen hat
        if let v = vorher, entwuerfe.enthaelt(v),
           project.map({ RecentProjects.normalizedPath($0.path) }) != RecentProjects.normalizedPath(v)
        {
            let ablage = entwuerfe
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { ablage.loeschenWennLeer(v) }
        }
    }

    // MARK: Projekte

    /// Ordner für ein neues Projekt: unter `AppInfo.projectsDirectory`, ohne Namenskollision.
    func proposedFolder(for name: String) -> URL {
        ProjectLocator.uniqueFolder(named: name, in: AppInfo.projectsDirectory)
    }

    /// Öffnet einen Projektordner nach Prüfung auf `model.py`.
    func openProject(at url: URL) {
        let folder = ProjectLocator.projectFolder(for: url)
        if let current = model.project, RecentProjects.normalizedPath(current.path) == RecentProjects.normalizedPath(folder)
        {
            showProjectWindow()
            return
        }
        if !AppInfo.isDemoMode, let problem = Self.pruefen(folder) {
            presentProblem(problem, folder: folder)
            return
        }
        actions?.openProject(at: folder)
    }

    /// Projektordner vor dem Öffnen prüfen. Auf dem iPad nur, was das Gerät sehen kann (`PadOrdner.pruefpfad`); Ordner des
    /// Mac außerhalb der iCloud prüft der Kernel beim Öffnen.
    private static func pruefen(_ folder: URL) -> ProjectLocator.Problem? {
        #if os(macOS)
        ProjectLocator.check(folder)
        #else
        PadOrdner.pruefpfad(folder).flatMap { ProjectLocator.check($0) }
        #endif
    }

    func openRecent(_ item: RecentProject) {
        if item.isMissing {
            #if os(macOS)
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
            #else
            fehlendesProjekt = item  // Rückfrage „Entfernen?“ zeigt das Hauptfenster
            #endif
            return
        }
        openProject(at: item.url)
    }

    /// Kann die App einen Projektordner wählen lassen („Öffnen …“)? Am Mac über den Dateidialog, auf dem iPad über die
    /// Projektliste mit Ordnerwahl in der Dateien-App (I-7).
    static var kannOrdnerWaehlen: Bool { true }

    /// Gibt es den Projektordner noch (für „Zuletzt geöffnet“)? Am Mac der Ordner selbst. Auf dem iPad stehen dort Pfade
    /// des Mac: geprüft wird, was das iPad sehen kann (iCloud über den gewählten Ordner); der Rest gilt als vorhanden, der
    /// Kernel am Mac meldet beim Öffnen, wenn er fehlt.
    nonisolated static func projektordnerVorhanden(_ url: URL) -> Bool {
        #if os(macOS)
        RecentProjects.folderExists(url)
        #else
        PadOrdner.pruefpfad(url).map(RecentProjects.folderExists) ?? true
        #endif
    }

    /// Neues Projekt mit Namen vom iPad: Der Kernel legt es am Mac an, im iCloud-Ordner, wenn der Schalter an ist, sonst
    /// dort, wo es die Mac-App anlegen würde (`Projektablage.kernelPfad`).
    func neuesProjektAnlegen(_ eingabe: String) {
        guard AppInfo.isDemoMode || model.kopplung.verbunden else {
            melde("Neue Projekte legt dein Mac an. Sobald er verbunden ist, geht das.", fehler: true)
            return
        }
        model.oberflaechenActions?.zeigeUebersicht(false)
        padBlatt = nil
        actions?.newProject(at: proposedFolder(for: eingabe), template: ProjectTemplate.empty.rawValue)
    }

    /// Kann die App Dateien des Projekts mit anderen Programmen öffnen oder im Dateimanager zeigen (model.py im Editor,
    /// Projektordner im Finder)? Am Mac ja; auf dem iPad gehen Dateien über das Teilen-Blatt (`dateienTeilen`).
    static var kannDateienOeffnen: Bool { Dateiablage.kannImFinderZeigen }

    /// Dateien dieses Geräts wählen. Am Mac nicht benutzt (dort der Dateidialog von AppKit); auf dem iPad zeigt das
    /// Hauptfenster die Dateien-App. Gewählte Dateien werden in den eigenen Zwischenspeicher kopiert, damit sie ohne
    /// Freigabe lesbar bleiben, bis der App-Kern sie an den Mac geschickt hat.
    func dateienWaehlen(titel: String, typen: [UTType], mehrere: Bool, fertig: @escaping ([URL]) -> Void) {
        dateiWahl = DateiWahl(titel: titel, typen: typen, mehrere: mehrere, fertig: fertig)
    }

    /// Der Dialog ist zu (gewählt oder abgebrochen); das Ergebnis kann danach noch kommen.
    func dateiWahlSchliessen() {
        if let w = dateiWahl { dateiWahlOffen = w }
        dateiWahl = nil
    }

    func dateiWahlBeendet(_ ergebnis: Result<[URL], Error>) {
        guard let wahl = dateiWahl ?? dateiWahlOffen else { return }
        dateiWahl = nil
        dateiWahlOffen = nil
        switch ergebnis {
        case .success(let urls):
            let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("Gewaehlt-\(UUID().uuidString)")
            var kopien: [URL] = []
            for u in urls {
                let frei = u.startAccessingSecurityScopedResource()
                defer { if frei { u.stopAccessingSecurityScopedResource() } }
                do {
                    try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
                    let ziel = ordner.appendingPathComponent(u.lastPathComponent)
                    try FileManager.default.copyItem(at: u, to: ziel)
                    kopien.append(ziel)
                } catch {
                    melde("\(u.lastPathComponent) ließ sich nicht lesen: \(error.localizedDescription)", fehler: true)
                }
            }
            if !kopien.isEmpty { wahl.fertig(kopien) }
        case .failure(let e):
            melde("Dateiwahl: \(e.localizedDescription)", fehler: true)
        }
    }

    /// Dateien des Kernels weitergeben: am Mac im Finder zeigen, auf dem iPad vom Mac holen (I-8, PROTOCOL.md „Datei ans
    /// Gerät“) und das Teilen-Blatt öffnen. Fehler meldet die Kopfleiste.
    func dateienTeilen(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        #if os(macOS)
        Dateiablage.imFinderZeigen(urls)
        #else
        guard let aktionen = model.actions as? DateiActions else { return }
        Task { @MainActor [weak self] in
            var lokal: [URL] = []
            do {
                for u in urls { lokal.append(try await aktionen.dateiFuerGeraet(u)) }
                TeilenBlatt.zeigen(lokal, von: .zero)
            } catch {
                self?.melde("Teilen ging nicht: \(error)", fehler: true)
            }
        }
        #endif
    }

    func presentOpenPanel() {
        #if os(iOS)
        padBlatt = .projekte  // Projektliste mit Ordnerwahl in der Dateien-App (I-7)
        #endif
        #if os(macOS)
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
        #endif
    }

    private func presentProblem(_ problem: ProjectLocator.Problem, folder: URL) {
        #if os(macOS)
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
        #else
        melde(problem.errorDescription ?? "Dieser Ordner ist kein Kev-CAD-Projekt.", fehler: true)
        #endif
    }

    #if os(macOS)
    private func run(_ alert: NSAlert, completion: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window = NSApp.keyWindow ?? projectWindow {
            alert.beginSheetModal(for: window, completionHandler: completion)
        } else {
            completion(alert.runModal())
        }
    }
    #endif

    // MARK: Datei und Ausgabe

    /// model.py im Standard-Editor öffnen; auf dem iPad gibt es keinen Editor dafür, dort geht model.py über das
    /// Teilen-Blatt weiter (vom Mac geholt).
    func openModelInEditor() {
        guard let file = model.project?.modelFile else { return }
        #if os(macOS)
        Dateiablage.oeffnen(file)
        #else
        dateienTeilen([file])
        #endif
    }

    func revealProjectInFinder() {
        guard let project = model.project else { return }
        let output = project.path.appendingPathComponent("output", isDirectory: true)
        if FileManager.default.fileExists(atPath: output.path) {
            Dateiablage.imFinderZeigen([output])
        } else {
            Dateiablage.imFinderZeigen([project.path])
        }
    }

    /// Befehl, mit dem Claude Code die Werkzeuge von Kev CAD bekommt (PLAN-MVP.md Abschnitt 11).
    static var claudeCommand: String {
        let bridge = AppInfo.repoDirectory?.appendingPathComponent("kernel/.venv/bin/kevcad-mcp").path
            ?? "<Repo>/kernel/.venv/bin/kevcad-mcp"
        return "claude mcp add --scope user kevcad -- \"\(bridge)\""
    }

    func copyClaudeCommand() {
        Zwischenablage.setzen(Self.claudeCommand)
    }
}

/// Vorlage für neue Projekte (Werte laut PROTOCOL.md `PROJECT_NEW.template`).
enum ProjectTemplate: String, CaseIterable, Identifiable {
    case example
    case empty

    var id: String { rawValue }
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

/// Offene Dateiwahl auf dem iPad (`AppSession.dateienWaehlen`).
struct DateiWahl: Identifiable {
    let id = UUID()
    var titel: String
    var typen: [UTType]
    var mehrere: Bool
    var fertig: ([URL]) -> Void
}

/// Blätter auf dem iPad, die am Mac eigene Fenster sind.
enum PadBlatt: String, Identifiable {
    case protokoll, lagerkatalog, zukauf, projekte
    var id: String { rawValue }
}
