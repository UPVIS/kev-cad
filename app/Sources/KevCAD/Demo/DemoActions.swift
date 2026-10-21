import Foundation
import KevCADCore
import simd

/// AppActions für den Demomodus (`KEVCAD_DEMO=1`): füllt AppModel mit Beispieldaten und reagiert sichtbar auf alle
/// Aktionen, ganz ohne Kernel. Nur hier setzt die Oberfläche selbst Werte im AppModel (siehe CLAUDE.md, Vertrag).
@MainActor
final class DemoActions: ObservableObject, AppActions, MeasurementRemoving {
    let model: AppModel
    let config: DemoConfiguration

    // Zustand nur für die Demovorschau (den echten Viewport steuert der App-Kern).
    @Published private(set) var standardView: StandardViewName = .iso
    @Published private(set) var focusRefs: [String] = []
    @Published private(set) var sectionAxis = "z"
    @Published private(set) var sectionOffset: Double = 0

    /// Aufgerufene Aktionen in Reihenfolge (für den Selbsttest).
    private(set) var calls: [String] = []

    private var runNumber = 0
    private var runTask: Task<Void, Never>?
    private var agentTask: Task<Void, Never>?
    private var kernelTask: Task<Void, Never>?
    private var pendingMeasureRef: String?
    private var filledExamples = false
    /// Beispielprojekt: Wandhalter (MVP) oder Gestell mit Lagerteilen (Phase 2).
    private(set) var scenario: DemoScenario = .wandhalter
    /// Lagerkatalog der Demo; Speichern und Löschen ändern ihn nur im Speicher.
    private var demoCatalog = Catalog(json: DemoData.catalogJSON)
    /// Inventar-Regel je Beispielprojekt: Gestell an, Wandhalter (Nachbau aus dem MVP) aus.
    private var inventoryRules: [DemoScenario: Bool] = [.gestell: true, .wandhalter: false]

    init(model: AppModel, config: DemoConfiguration) {
        self.model = model
        self.config = config
    }

    // MARK: Start

    func start() {
        log("Demomodus ohne Kernel (KEVCAD_DEMO=1, Zustand \(config.start.rawValue))", .warning)
        model.agentConnected = true
        log("Agent verbunden über MCP (Port \(AppInfo.mcpPort))")

        switch config.start {
        case .welcome:
            bootKernel(delay: 0.8)
            startAgentCycle()
        case .live:
            bootKernel(delay: 0.4)
            startAgentCycle()
            openProject(at: DemoData.projectFolder)
        case .running, .finished, .error, .bom, .catalog, .inventar:
            model.kernelState = .ready
            log("Kernel bereit (build123d 0.13, Demo)")
            model.agentActivity = "misst Abstand Bohrung ↔ Plattenrand"
            loadFrozenProject()
        }
    }

    /// Fester Zustand für Fensterbilder: Projekt mit Lauf 3, dazu Lauf 4 je nach Zustand.
    private func loadFrozenProject() {
        scenario = config.usesGestell ? .gestell : .wandhalter
        model.project = ProjectLocator.projectInfo(for: scenario.folder)
        log("Projekt geöffnet: \(KevFormat.abbreviatedPath(scenario.folder.path))")
        runNumber = 3
        model.inventarRegel = inventoryRules[scenario] ?? true
        model.parts = scenario.specs.map { $0.node(run: 3) }
        if config.start == .inventar { model.parts.append(DemoData.violationSpec.node(run: 3)) }
        updateTriangles()
        if scenario == .gestell {
            model.agentActivity = config.start == .inventar
                ? "schlägt Alu-Winkel 30 × 30 × 3 vor" : "sucht Lagerteile: vierkantrohr 40"
            model.run = .finished(run: 3, durationMs: 1240, parts: model.parts.count, warnings: [])
            log("Lauf 3 fertig in 1,2 s · \(model.parts.count) Teile")
            updateBOM()
            if config.start == .catalog || config.start == .inventar { model.catalog = demoCatalog }
            // Zeile für Fensterbilder auswählen, ohne die Kamera zu bewegen (das ganze Gestell bleibt im Bild)
            if let pos = config.bomLine, let line = model.bom?.lines.first(where: { $0.pos == pos }) {
                select(line.teile)
            }
            return
        }
        fillExamples()
        switch config.start {
        case .running:
            runNumber = 4
            if let index = model.parts.firstIndex(where: { $0.id == "Grundplatte" }) {
                model.parts[index].run = 4
            }
            model.kernelState = .busy
            model.run = .running(run: 4, step: "Bohrungen", stepIndex: 3)
            log("Lauf 4 gestartet")
            for (index, step) in DemoData.steps.prefix(3).enumerated() { log("Schritt \(index + 1) · \(step.title)") }
        case .error:
            model.run = .finished(run: 3, durationMs: 412, parts: 7, warnings: [])
            failRun()
        default:
            model.run = .finished(run: 3, durationMs: 412, parts: 7, warnings: DemoData.warnings)
            log("Lauf 3 fertig in 0,4 s · 7 Teile")
            log("Warnung: \(DemoData.warnings[0])", .warning)
        }
        if config.section, let bounds = model.sceneBounds {
            setSection(enabled: true, axis: "z", offset: Double(bounds.min.z + bounds.max.z) / 2)
        }
        if let explode = config.explode { setExplode(explode) }
        if config.measureMode { setMeasureMode(true) }
    }

    private func bootKernel(delay: Double) {
        model.kernelState = .starting
        log("Kernel startet …")
        kernelTask?.cancel()
        kernelTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, !Task.isCancelled else { return }
            self.model.kernelState = self.model.isRunning ? .busy : .ready
            self.log("Kernel bereit (build123d 0.13, Demo)")
        }
    }

    private func startAgentCycle() {
        agentTask?.cancel()
        agentTask = Task { [weak self] in
            var index = 0
            while !Task.isCancelled {
                guard let self else { return }
                if self.model.agentConnected {
                    let activity = DemoData.agentActivities[index % DemoData.agentActivities.count]
                    self.model.agentActivity = activity
                    if let activity { self.log("Agent \(activity)") }
                }
                index += 1
                try? await Task.sleep(for: .seconds(4.5))
            }
        }
    }

    // MARK: Projekte

    func openProject(at url: URL) {
        calls.append("openProject")
        runTask?.cancel()
        scenario = DemoScenario.forFolder(url)
        model.project = ProjectLocator.projectInfo(for: url)
        model.inventarRegel = inventoryRules[scenario] ?? true
        model.inventarVerstoesse = []
        model.bom = nil
        model.parts = []
        model.selection = []
        model.measurements = []
        model.run = .idle
        model.triangleCount = 0
        filledExamples = false
        log("Projekt geöffnet: \(KevFormat.abbreviatedPath(url.path))")
        runModel()
    }

    func newProject(at url: URL, template: String) {
        calls.append("newProject(\(template))")
        if template == "empty" {
            runTask?.cancel()
            model.project = ProjectLocator.projectInfo(for: url)
            model.parts = []
            model.selection = []
            model.measurements = []
            model.run = .idle
            model.triangleCount = 0
            log("Leeres Projekt angelegt: \(KevFormat.abbreviatedPath(url.path)) (Demo, nichts auf der Platte)")
        } else {
            log("Beispielprojekt angelegt: \(KevFormat.abbreviatedPath(url.path)) (Demo, nichts auf der Platte)")
            openProject(at: url)
        }
    }

    /// Nur Demo: zurück zum Willkommensfenster.
    func closeProject() {
        runTask?.cancel()
        model.project = nil
        model.bom = nil
        model.parts = []
        model.selection = []
        model.measurements = []
        model.run = .idle
        model.triangleCount = 0
        log("Projekt geschlossen")
    }

    // MARK: Lauf

    func runModel() {
        calls.append("runModel")
        guard model.project != nil else { return }
        runTask?.cancel()
        runTask = Task { [weak self] in await self?.performRun() }
    }

    private func performRun() async {
        runNumber += 1
        let run = runNumber
        let started = Date()
        model.kernelState = .busy
        model.run = .running(run: run, step: nil, stepIndex: 0)
        log("Lauf \(run) gestartet\(model.slowMotion ? " (Zeitlupe)" : "")")
        for (index, step) in scenario.steps.enumerated() {
            model.run = .running(run: run, step: step.title, stepIndex: index + 1)
            log("Schritt \(index + 1) · \(step.title)")
            try? await Task.sleep(for: .milliseconds(model.slowMotion ? 1500 : 650))
            if Task.isCancelled { return }
            for spec in step.parts { upsert(spec.node(run: run)) }
            updateTriangles()
        }
        let shown = Set(scenario.specs.map(\.id))
        model.parts.removeAll { !shown.contains($0.id) }
        let duration = Int(Date().timeIntervalSince(started) * 1000)
        model.run = .finished(run: run, durationMs: duration, parts: model.parts.count, warnings: scenario.warnings)
        model.kernelState = .ready
        updateTriangles()
        log("Lauf \(run) fertig in \(KevFormat.duration(ms: duration)) · \(model.parts.count) Teile")
        for warning in scenario.warnings { log("Warnung: \(warning)", .warning) }
        updateBOM()
        if !filledExamples && scenario == .wandhalter { fillExamples() }
    }

    /// Stückliste und Inventar-Prüfung wie vom Kernel nach RUN_END.
    private func updateBOM() {
        updateInventory()
        model.bom = DemoData.bom(
            for: model.parts, run: runNumber, catalog: demoCatalog, inventoryRule: model.inventarRegel)
        if let bom = model.bom {
            log("Stückliste zu Lauf \(bom.run): \(bom.lines.count) Positionen, \(bom.totals.teile) Teile")
        }
    }

    /// Inventar-Regel: Teile ohne Lagerteil, die nicht aus druckbarem Material sind, verletzen sie.
    private func updateInventory() {
        var names: [String] = []
        for i in model.parts.indices {
            let p = model.parts[i]
            let fehlt = model.inventarRegel && p.stock == nil && demoCatalog.material(p.material ?? "")?.druckbar != true
            model.parts[i].inventarFehlt = fehlt
            if fehlt { names.append(p.id) }
        }
        model.inventarVerstoesse = names
        if !names.isEmpty { log("Nicht aus dem Inventar: \(names.joined(separator: ", "))", .warning) }
    }

    private func upsert(_ part: PartNode) {
        if let index = model.parts.firstIndex(where: { $0.id == part.id }) {
            var updated = part
            updated.visible = model.parts[index].visible
            model.parts[index] = updated
        } else {
            model.parts.append(part)
        }
    }

    private func updateTriangles() {
        model.triangleCount = model.parts.reduce(0) { $0 + $1.triangles }
    }

    /// Beispielauswahl und zwei Messungen, damit Inspektor und Viewport etwas zeigen.
    private func fillExamples() {
        filledExamples = true
        model.selection = [DemoData.selection(for: "Grundplatte#f7", parts: model.parts, run: runNumber)]
        model.measurements = DemoData.measurements()
    }

    /// Nur Demo: Fehler im nächsten Lauf (Fehlerband).
    func triggerError() {
        runTask?.cancel()
        failRun()
    }

    private func failRun() {
        runNumber += 1
        model.kernelState = .ready
        model.run = .failed(
            run: runNumber, message: DemoData.errorMessage, line: DemoData.errorLine, excerpt: DemoData.errorExcerpt)
        log("Lauf \(runNumber) gestartet")
        log("Lauf \(runNumber) fehlgeschlagen, Zeile \(DemoData.errorLine): \(DemoData.errorMessage)", .error)
    }

    // MARK: Sichtbarkeit und Auswahl

    func setVisibility(_ partIDs: [String], visible: Bool) {
        calls.append("setVisibility(\(visible))")
        let ids = Set(partIDs)
        for index in model.parts.indices where ids.contains(model.parts[index].id) {
            model.parts[index].visible = visible
        }
        log("\(visible ? "Eingeblendet" : "Ausgeblendet"): \(partIDs.joined(separator: ", "))")
    }

    func isolate(_ partIDs: [String]) {
        calls.append("isolate")
        let ids = Set(partIDs)
        for index in model.parts.indices { model.parts[index].visible = ids.contains(model.parts[index].id) }
        log("Isoliert: \(partIDs.joined(separator: ", "))")
    }

    func showAll() {
        calls.append("showAll")
        for index in model.parts.indices { model.parts[index].visible = true }
        log("Alles eingeblendet")
    }

    func focus(on refs: [String]) {
        calls.append("focus")
        focusRefs = refs.count == model.parts.count ? [] : refs
        log("Kamera auf \(refs.count == 1 ? refs[0] : "\(refs.count) Elemente") ausgerichtet")
    }

    func select(_ refs: [String]) {
        calls.append("select(\(refs.count))")
        model.selection = refs.map { DemoData.selection(for: $0, parts: model.parts, run: runNumber) }
    }

    /// Klick in die Demovorschau: wählt aus oder misst (im Messmodus zwei Teile nacheinander).
    func pick(_ partID: String?) {
        guard let partID else {
            pendingMeasureRef = nil
            select([])
            return
        }
        guard model.measureMode else { return select([partID]) }
        if let first = pendingMeasureRef, first != partID {
            pendingMeasureRef = nil
            addDistance(first, partID)
            select([first, partID])
        } else {
            pendingMeasureRef = partID
            select([partID])
        }
    }

    private func addDistance(_ a: String, _ b: String) {
        guard let pa = model.parts.first(where: { $0.id == a }), let pb = model.parts.first(where: { $0.id == b })
        else { return }
        let ca = (pa.bboxMin + pa.bboxMax) / 2
        let cb = (pb.bboxMin + pb.bboxMax) / 2
        let d = cb - ca
        let distance = Double(simd_length(d))
        model.measurements.append(MeasurementItem(
            refs: [a, b], kind: "distance",
            text: "Mittenabstand \(KevFormat.mm(distance, digits: 3)) (dz \(KevFormat.number(Double(d.z), digits: 3)))",
            points: [ca, cb], values: ["distance": distance, "dx": Double(d.x), "dy": Double(d.y), "dz": Double(d.z)]))
        log("Gemessen: \(a) ↔ \(b)")
    }

    // MARK: Ansicht

    func setStandardView(_ view: StandardViewName) {
        calls.append("setStandardView(\(view.rawValue))")
        standardView = view
        focusRefs = []
    }

    func setDisplayStyle(_ style: DisplayStyle) {
        calls.append("setDisplayStyle")
        model.displayStyle = style
    }

    func setSection(enabled: Bool, axis: String, offset: Double) {
        calls.append("setSection(\(enabled))")
        model.sectionEnabled = enabled
        sectionAxis = axis
        sectionOffset = offset
    }

    func setExplode(_ factor: Double) {
        calls.append("setExplode")
        model.explodeFactor = min(max(factor, 0), 1)
    }

    func setMeasureMode(_ on: Bool) {
        calls.append("setMeasureMode(\(on))")
        model.measureMode = on
        pendingMeasureRef = nil
    }

    func clearMeasurements() {
        calls.append("clearMeasurements")
        model.measurements = []
    }

    func removeMeasurement(id: UUID) {
        calls.append("removeMeasurement")
        model.measurements.removeAll { $0.id == id }
    }

    // MARK: Einstellungen und Ausgabe

    func setAutoRun(_ on: Bool) {
        calls.append("setAutoRun(\(on))")
        model.autoRun = on
        log("Auto-Lauf \(on ? "an" : "aus")")
    }

    func setSlowMotion(_ on: Bool) {
        calls.append("setSlowMotion(\(on))")
        model.slowMotion = on
        log("Zeitlupe \(on ? "an" : "aus")")
    }

    func export(formats: [String]) {
        calls.append("export")
        let name = model.project?.name ?? "Modell"
        let files = formats.map { "output/\(name).\($0)" }
        log("Exportiert (Demo, nichts geschrieben): \(files.joined(separator: ", "))")
    }

    func saveScreenshot() {
        calls.append("saveScreenshot")
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH.mm.ss"
        log("Bild gespeichert (Demo): output/\(model.project?.name ?? "Bild") \(formatter.string(from: Date())).png")
    }

    func restartKernel() {
        calls.append("restartKernel")
        bootKernel(delay: 1.0)
    }

    // MARK: Nur Demo

    func toggleAgent() {
        model.agentConnected.toggle()
        if !model.agentConnected { model.agentActivity = nil }
        log(model.agentConnected ? "Agent verbunden" : "Agent getrennt")
    }

    func simulateKernelCrash() {
        model.kernelState = .failed("Rechenprozess abgestürzt (Signal 11), starte neu")
        log("Kernel abgestürzt: Rechenprozess beendet mit Signal 11", .error)
        kernelTask?.cancel()
        kernelTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard let self, !Task.isCancelled else { return }
            self.bootKernel(delay: 1.0)
        }
    }

    private func log(_ text: String, _ level: LogLine.Level = .info) {
        model.append(LogLine(level: level, text: text))
    }
}

// MARK: - Phase 2: Stückliste und Lagerkatalog

extension DemoActions: CatalogActions {
    func requestBOM() {
        calls.append("requestBOM")
        guard model.project != nil else { return }
        updateBOM()
    }

    func requestCatalog(query: String?, art: String?) {
        calls.append("requestCatalog")
        if model.catalog == nil {
            model.catalogActivity = .loading
            Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(400))
                guard let self else { return }
                self.model.catalog = self.demoCatalog
                self.model.catalogActivity = .idle
                self.log("Lagerkatalog geladen (Demo): \(self.demoCatalog.items.count) Lagerteile, "
                    + "\(self.demoCatalog.materials.count) Materialien")
            }
        } else {
            model.catalog = demoCatalog
        }
    }

    func saveCatalogEntry(kind: String, json: Data, ebene: CatalogLevel) {
        calls.append("saveCatalogEntry(\(kind))")
        guard var entry = try? JSONDecoder().decode(JSONValue.self, from: json), case .object(var object) = entry,
              let id = object["id"]?.stringValue
        else {
            model.catalogActivity = .failed("Der Eintrag ist kein gültiges JSON-Objekt.")
            return
        }
        model.catalogActivity = .saving
        object["ebene"] = .string(ebene.rawValue)
        entry = .object(object)
        // Katalog als JSON neu zusammensetzen: gleicher Weg wie beim Kernel (spätere Ebene ersetzt die frühere)
        var materials = demoCatalog.materials.map(\.entryWithLevel)
        var items = demoCatalog.items.map(\.entryWithLevel)
        if kind == "material" {
            materials.removeAll { $0["id"]?.stringValue == id }
            materials.append(entry)
        } else {
            items.removeAll { $0["id"]?.stringValue == id }
            items.append(entry)
        }
        demoCatalog = Catalog(json: [
            "materials": .array(materials), "items": .array(items), "arten": .array(demoCatalog.arten.map { .string($0) }),
        ])
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(250))
            guard let self else { return }
            self.model.catalog = self.demoCatalog
            self.model.catalogActivity = .saved(id: id, message: "Demo: nur im Speicher")
            self.log("Katalog: \(id) gespeichert (\(ebene.title), Demo)")
        }
    }

    func deleteCatalogEntry(kind: String, id: String, ebene: CatalogLevel) {
        calls.append("deleteCatalogEntry(\(kind))")
        let materials = demoCatalog.materials.filter { !(kind == "material" && $0.id == id) }
        let items = demoCatalog.items.filter { !(kind != "material" && $0.id == id) }
        demoCatalog = Catalog(materials: materials, items: items, arten: demoCatalog.arten)
        model.catalog = demoCatalog
        model.catalogActivity = .deleted(id: id)
        log("Katalog: \(id) gelöscht (\(ebene.title), Demo)")
    }

    func showBOMLine(_ line: BOMLine) {
        calls.append("showBOMLine(\(line.pos))")
        let ids = Set(line.teile)
        for index in model.parts.indices where ids.contains(model.parts[index].id) { model.parts[index].visible = true }
        select(line.teile.filter { id in model.parts.contains { $0.id == id } })
        focus(on: line.teile)
    }

    func relaunchForUpdate() {}
}

extension DemoActions: InventoryActions {
    func setInventarRegel(_ on: Bool) {
        calls.append("setInventarRegel(\(on))")
        inventoryRules[scenario] = on
        model.inventarRegel = on
        log("Inventar-Regel \(on ? "an" : "aus")")
        guard model.project != nil, !model.parts.isEmpty else { return }
        updateBOM()
    }
}

extension CatalogItem {
    /// Roh-JSON mit Ebene (wie es der Kernel schickt), für den Demokatalog.
    var entryWithLevel: JSONValue {
        guard case .object(var o) = entry else { return entry }
        o["ebene"] = .string(ebene.rawValue)
        return .object(o)
    }
}

extension CatalogMaterial {
    var entryWithLevel: JSONValue {
        guard case .object(var o) = entry else { return entry }
        o["ebene"] = .string(ebene.rawValue)
        return .object(o)
    }
}
