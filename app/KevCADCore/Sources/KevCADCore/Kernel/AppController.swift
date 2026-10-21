import AppKit
import Combine
import Foundation
import OCCTSwiftViewport
import simd

/// Verbindet AppModel mit dem Kernel (Prozess, Socket, Protokoll), der Szene und dem Viewport.
///
/// Ablauf: `start()` startet den Kernel-Server (`kevcad-kernel serve`, ersetzbar über `KEVCAD_KERNEL_CMD`) und
/// verbindet sich über den Unix-Socket. Nachrichten des Kernels landen auf dem Hauptthread in `handle(_:)` und
/// pflegen AppModel, Szene und Viewport. Die Oberfläche löst über `AppActions` alles Weitere aus.
@MainActor
public final class AppController: AppActions {
    public let model: AppModel
    /// Teile, Auswahl, Hervorhebungen und die daraus gebauten Körper.
    public let scene = SceneStore()
    /// Viewport-Zustand (Kamera, Körper, Überlagerung), unabhängig vom Fenster.
    public let viewport = ViewportCoordinator()

    let process = KernelProcess()
    let connection = KernelConnection()
    let screenshots = ScreenshotRenderer()

    /// Zeitlupe für Läufe aus der App (ms je Schritt).
    public static let slowMotionMs = 350

    // Verbindung und Anfragen
    private(set) var connected = false
    private(set) var helloReceived = false
    private var outSeq = 0
    private var requestCounter = 0
    private var pending: [String: PendingRequest] = [:]
    var queuedProjectRequest: (() -> Void)?
    private var unknownTypesLogged = Set<String>()

    // Prozessüberwachung
    private var running = false
    private var crashTimes: [Date] = []
    private var restartWork: DispatchWorkItem?
    private var connectWatchdog: DispatchWorkItem?
    private var terminationObserver: NSObjectProtocol?

    // Szene
    private var fitOnFirstPart = true
    private var fitAtRunEnd = false
    var measurePending: [ElementRef] = []
    var annotations: [(id: String, item: OverlayPrimitive)] = []
    var highlightLabels: [Int: String] = [:]
    private var animationTimer: Timer?
    var selfTestStarted = false
    private var projectSeenSinceHello = false
    /// Lokale Ansicht (Taste /): vorherige Sichtbarkeit und Kamera, solange sie aktiv ist.
    var localView: (hidden: Set<String>, camera: CameraState)?
    var navCancellables = Set<AnyCancellable>()
    /// Nach einem automatischen Update wiederherzustellen (Projekt, Kamera, Darstellung), bis der erste Lauf fertig ist.
    var pendingRestore: SavedSession?
    /// Spiegel aufs iPhone (MIRROR.md), siehe AppController+Mirror.swift.
    public internal(set) var mirror: MirrorService?

    // Phase 2: Katalog und Stückliste
    /// Suche der letzten Katalog-Anfrage (nach Speichern und Löschen wird damit neu geladen).
    var catalogQuery: (query: String?, art: String?) = (nil, nil)
    /// Der Katalog wurde schon einmal angefordert: nach einem Projektwechsel neu laden (Projekt-Ebene).
    var catalogWanted = false
    /// BOM_REQ ohne Antwort schon gemeldet (ältere Kernel kennen Phase 2 nicht).
    var bomSilenceLogged = false
    /// Stilles Nachladen des Katalogs (Vorschläge von Claude): letzter Zeitpunkt, ausgesetzt nach einer Zeitüberschreitung.
    var lastQuietCatalog: Date?
    var quietCatalogOff = false
    /// Zeigt erzeugte Dateien im Finder (in Tests ersetzt, damit kein Finder aufgeht).
    var revealFiles: ([URL]) -> Void = { urls in
        guard Bundle.main.bundleURL.pathExtension == "app", !urls.isEmpty,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == nil
        else { return }
        NSWorkspace.shared.activateFileViewerSelecting(urls)
    }

    struct PendingRequest {
        var kind: String
        var completion: (Result<KernelMessage, RequestError>) -> Void
        var timer: Timer?
    }

    public struct RequestError: Error, CustomStringConvertible {
        public var message: String
        public var description: String { message }
    }

    public init(model: AppModel) {
        self.model = model
        model.actions = self

        scene.onChange = { [weak self] in
            guard let self else { return }
            self.viewport.bodies = self.scene.renderBodies
        }
        viewport.onClick = { [weak self] pick, modifiers in self?.handleClick(pick, modifiers: modifiers) }
        installNavigation()
        process.onOutput = { [weak self] line, isErr in self?.logKernelOutput(line, stderr: isErr) }
        process.onExit = { [weak self] code, expected in self?.processExited(code: code, expected: expected) }
        connection.onEvents = { [weak self] events in self?.handle(events) }
        terminationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.shutdownForTermination() }
        }
    }

    // MARK: Start und Ende

    /// Startet den Kernel-Server und verbindet sich mit ihm.
    public func start() {
        stopInternal(clearState: false)
        installSignalHandlers()
        startMirror()
        running = true
        if AppInfo.isDemoMode {
            startDemo()
            return
        }
        model.kernelState = .starting
        let socket = AppInfo.kernelSocket.path
        if ProcessInfo.processInfo.environment["KEVCAD_KERNEL_EXTERNAL"] == "1" {
            log(.info, "Kernel wird extern gestartet, verbinde mit \(socket)")
        } else {
            do {
                try process.start(socket: socket, port: AppInfo.mcpPort)
            } catch {
                running = false
                model.kernelState = .failed("\(error)")
                log(.error, "\(error)")
                return
            }
        }
        connection.open(path: socket)
        armWatchdog()
        restoreSessionIfRequested()
    }

    /// Beendet Kernel und Verbindung.
    public func stop() {
        stopInternal(clearState: true)
        model.kernelState = .stopped
    }

    private func stopInternal(clearState: Bool) {
        running = false
        restartWork?.cancel()
        restartWork = nil
        connectWatchdog?.cancel()
        connectWatchdog = nil
        connection.close()
        process.stopNow(timeout: 1.5)
        failAllPending("Verbindung zum Kernel beendet")
        connected = false
        helloReceived = false
        if clearState {
            model.agentConnected = false
            model.agentActivity = nil
        }
    }

    func resetCrashCounter() { crashTimes = [] }

    private static var signalSources: [DispatchSourceSignal] = []

    /// Auch bei SIGTERM/SIGINT/SIGHUP (z. B. `pkill`) den Kernel mitbeenden; nur in der gebauten App, nicht in Tests.
    private func installSignalHandlers() {
        guard Self.signalSources.isEmpty, Bundle.main.bundleURL.pathExtension == "app" else { return }
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { [weak self] in
                MainActor.assumeIsolated { self?.shutdownForTermination() }
                exit(0)
            }
            src.resume()
            Self.signalSources.append(src)
        }
    }

    private func shutdownForTermination() {
        saveSession()
        mirror?.stop()
        running = false
        restartWork?.cancel()
        connection.close()
        process.stopNow()
    }

    private func armWatchdog() {
        connectWatchdog?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.running, !self.helloReceived else { return }
            self.log(.warning, "Kernel meldet sich nach 30 s noch nicht (startet er noch? Protokoll prüfen)")
        }
        connectWatchdog = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 30, execute: work)
    }

    /// Negative Codes stehen für ein Signal (siehe KernelProcess).
    static func exitText(_ code: Int32) -> String { code < 0 ? "Signal \(-code)" : "Code \(code)" }

    private func processExited(code: Int32, expected: Bool) {
        guard !expected, running else { return }
        connected = false
        helloReceived = false
        failAllPending("Kernel beendet")
        let now = Date()
        crashTimes = crashTimes.filter { now.timeIntervalSince($0) < 60 } + [now]
        if crashTimes.count >= 5 {
            running = false
            connection.close()
            model.kernelState = .failed("Kernel stürzt wiederholt ab (\(Self.exitText(code))), Protokoll prüfen")
            log(.error, "Kernel stürzt wiederholt ab, kein weiterer Neustart")
            return
        }
        let delay = min(10, pow(2, Double(crashTimes.count - 1)))
        model.kernelState = .starting
        log(.warning, "Kernel beendet (\(Self.exitText(code))), Neustart in \(Int(delay)) s")
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            do {
                try self.process.start(socket: AppInfo.kernelSocket.path, port: AppInfo.mcpPort)
                self.armWatchdog()
            } catch {
                self.running = false
                self.model.kernelState = .failed("\(error)")
                self.log(.error, "\(error)")
            }
        }
        restartWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    // MARK: Protokoll

    func log(_ level: LogLine.Level, _ text: String) {
        model.append(LogLine(level: level, text: text))
        // Testvariante: zusätzlich auf stderr (mit `open --stderr` für Tests ohne Oberfläche lesbar)
        if AppInfo.isTestVariant { FileHandle.standardError.write(Data("[\(level.rawValue)] \(text)\n".utf8)) }
    }

    private func logKernelOutput(_ line: String, stderr: Bool) {
        log(Self.kernelLogLevel(line), "Kernel: \(line)")
    }

    /// Stufe einer Kernel-Zeile: Python-Logging („… INFO name: …“) zuerst, sonst nach Stichworten.
    static func kernelLogLevel(_ line: String) -> LogLine.Level {
        for (tag, level) in [(" CRITICAL ", LogLine.Level.error), (" ERROR ", .error), (" WARNING ", .warning),
                             (" INFO ", .info), (" DEBUG ", .info)] where line.contains(tag) {
            return level
        }
        let lower = line.lowercased()
        if lower.hasPrefix("traceback") || lower.contains("error:") || lower.contains("exception") || lower.contains("fehler") {
            return .error
        }
        if lower.contains("warn") { return .warning }
        return .info
    }

    /// Sendet eine Nachricht; `false`, wenn keine Verbindung besteht.
    @discardableResult
    func send<M: OutgoingMessage>(_ message: M, payload: Data = Data()) -> Bool {
        guard connected else { return false }
        var m = message
        outSeq += 1
        m.seq = outSeq
        do {
            connection.send(try m.frame(payload: payload).encoded)
            return true
        } catch {
            log(.error, "Nachricht \(M.type) ließ sich nicht kodieren: \(error)")
            return false
        }
    }

    func nextRequestID() -> String {
        requestCounter += 1
        return "a-\(requestCounter)"
    }

    /// Anfrage mit Antwortzuordnung über `id` / `reply_to`.
    func request<M: OutgoingRequest>(
        _ message: M, timeout: TimeInterval = 30,
        completion: @escaping (Result<KernelMessage, RequestError>) -> Void
    ) {
        guard send(message) else {
            completion(.failure(RequestError(message: "Kernel nicht verbunden")))
            return
        }
        let id = message.id
        let timer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, let p = self.pending.removeValue(forKey: id) else { return }
                p.completion(.failure(RequestError(message: "\(p.kind): keine Antwort nach \(Int(timeout)) s")))
            }
        }
        pending[id] = PendingRequest(kind: M.type, completion: completion, timer: timer)
    }

    private func failAllPending(_ reason: String) {
        let all = pending
        pending = [:]
        for (_, p) in all {
            p.timer?.invalidate()
            p.completion(.failure(RequestError(message: reason)))
        }
    }

    /// Antwort einer offenen Anfrage zustellen; `true`, wenn es eine gab.
    private func resolvePending(_ message: KernelMessage) -> Bool {
        guard let id = message.replyTo, let p = pending.removeValue(forKey: id) else { return false }
        p.timer?.invalidate()
        if case .error(let e) = message {
            p.completion(.failure(RequestError(message: e.message)))
        } else {
            p.completion(.success(message))
        }
        return true
    }

    // MARK: Ereignisse

    func handle(_ events: [IncomingEvent]) {
        for e in events {
            switch e {
            case .connected:
                connected = true
                log(.info, "Mit Kernel verbunden")
                send(HelloAppMessage(appVersion: Self.appVersion, bundleID: AppInfo.bundleID))
                sendSettings()
            case .disconnected(let reason):
                let was = connected
                connected = false
                helloReceived = false
                failAllPending(reason)
                if was { log(.warning, "Verbindung zum Kernel getrennt: \(reason)") }
                if running {
                    if case .failed = model.kernelState {} else { model.kernelState = .starting }
                }
                model.agentConnected = false
                model.agentActivity = nil
            case .part(let record):
                handlePart(record)
            case .message(let m):
                handle(m)
            case .invalid(let type, let reason):
                log(.error, "Nachricht \(type) nicht lesbar: \(reason)")
            }
        }
    }

    static var appVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0.1"
    }

    func handle(_ message: KernelMessage) {
        if resolvePending(message) {
            // PROJECT, BOM und CATALOG als Antwort pflegen trotzdem das Modell
            switch message {
            case .project(let p): applyProject(p)
            case .bom(let b): applyBOM(b)
            case .catalog(let c): applyCatalog(c)
            default: break
            }
            return
        }
        switch message {
        case .hello(let h):
            helloReceived = true
            connectWatchdog?.cancel()
            crashTimes = []
            if let v = h.protocolVersion, v != 1 {
                log(.warning, "Kernel spricht Protokoll \(v), die App Protokoll 1")
            }
            model.kernelState = .ready
            log(
                .info,
                "Kernel bereit: Version \(h.kernelVersion ?? "?"), build123d \(h.build123d ?? "?"), MCP-Port \(h.mcpPort.map(String.init) ?? "?")"
            )
            // Der Kernel schickt nach HELLO den vollen Stand (PROJECT, alle Teile). Die Kamera bleibt, wenn schon
            // Teile da waren (Wiederverbinden, Neustart des Kernels).
            let hadParts = !scene.isEmpty
            scene.removeAll()
            fitOnFirstPart = !hadParts
            clearSelectionState()
            updateParts()
            refreshOverlay()
            projectSeenSinceHello = false
            if let q = queuedProjectRequest {
                queuedProjectRequest = nil
                q()
            } else if let open = model.project {
                reopenProjectIfKernelForgotIt(open)
            }
            requestBOMAfterConnect()
            quietCatalogOff = false
        case .status(let s):
            switch s.state {
            case "ready": model.kernelState = .ready
            case "busy": model.kernelState = .busy
            case "error": model.kernelState = .failed(s.message ?? "Kernel meldet einen Fehler")
            default: break
            }
            if let m = s.message, !m.isEmpty { log(s.state == "error" ? .error : .info, "Kernel: \(m)") }
        case .project(let p):
            applyProject(p)
        case .runStart(let r):
            model.run = .running(run: r.run, step: nil, stepIndex: 0)
            if model.kernelState == .ready { model.kernelState = .busy }
            scene.beginRun(r.run)
            fitAtRunEnd = fitOnFirstPart || scene.isEmpty
            clearSelectionState()
            startAnimationTimerIfNeeded()
        case .step(let s):
            model.run = .running(run: s.run, step: s.text, stepIndex: s.index)
        case .partUpsert(let head, let geo):
            handlePart(PartRecord(header: head, geometry: geo))
        case .partRemove(let r):
            scene.remove(r.name)
            updateParts()
            refreshOverlay()
        case .runEnd(let e):
            scene.endRun(e.run)
            model.run = .finished(
                run: e.run, durationMs: e.durationMs, parts: e.parts > 0 ? e.parts : scene.order.count,
                warnings: e.warnings)
            if model.kernelState == .busy { model.kernelState = .ready }
            model.inventarVerstoesse = e.inventarVerstoesse
            updateParts()
            if let restore = pendingRestore {
                applyRestoredView(restore)
                fitAtRunEnd = false
            } else if fitAtRunEnd {
                viewport.fit(scene.visibleBounds(), animated: true)
                fitAtRunEnd = false
            }
            fitOnFirstPart = false
            log(.info, "Lauf \(e.run) fertig: \(scene.order.count) Teile, \(model.triangleCount) Dreiecke, \(e.durationMs) ms")
            scheduleSelfTestIfRequested()
            for w in e.warnings { log(.warning, w) }
            if !e.inventarVerstoesse.isEmpty {
                log(.warning, "Nicht aus dem Inventar: " + e.inventarVerstoesse.joined(separator: ", "))
            }
        case .runError(let e):
            scene.endRun(e.run)
            // Den Reparaturhinweis des Kernels an die Meldung hängen (RunState hat kein eigenes Feld dafür)
            let message = e.hint.map { e.message + "\nHinweis: " + $0 } ?? e.message
            model.run = .failed(run: e.run, message: message, line: e.line, excerpt: e.excerpt)
            if model.kernelState == .busy { model.kernelState = .ready }
            fitAtRunEnd = false
            log(.error, "Lauf \(e.run) fehlgeschlagen" + (e.line.map { " (Zeile \($0))" } ?? "") + ": \(e.message)")
        case .agent(let a):
            model.agentConnected = a.connected
            model.agentActivity = a.connected ? a.activity : nil
            mirror?.updateAgents(a.sessions)
        case .viewCommand(let v):
            mirror?.noteAgentCommand()
            let (ok, message) = performViewCommand(v)
            if !ok { log(.warning, "Ansichtsbefehl \(v.cmd): \(message ?? "fehlgeschlagen")") }
            send(AckOutMessage(replyTo: v.id, ok: ok, message: message))
        case .screenshotRequest(let s):
            answerScreenshot(s)
        case .measureResponse(let m):
            // ohne offene Anfrage: z. B. Messung des Agenten mit show=true
            addMeasurement(m.result)
        case .exportResponse(let e):
            if !e.files.isEmpty { log(.info, "Export: " + e.files.joined(separator: ", ")) }
        case .ack(let a):
            if !a.ok { log(.warning, "Kernel: \(a.message ?? "abgelehnt")") }
        case .error(let e):
            log(.error, "Kernel: \(e.message)")
        case .bom(let b):
            applyBOM(b)
        case .catalog(let c):
            applyCatalog(c)
        case .unknown(let type, _):
            if unknownTypesLogged.insert(type).inserted { log(.info, "Unbekannte Nachricht \(type) wird ignoriert") }
        }
    }

    /// Ein neu gestarteter Kernel kennt das offene Projekt nicht mehr: schickt er kurz nach HELLO kein PROJECT,
    /// öffnet die App es wieder (und rechnet bei Auto-Lauf neu).
    private func reopenProjectIfKernelForgotIt(_ project: ProjectInfo) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.helloReceived, !self.projectSeenSinceHello, self.model.project == project else {
                    return
                }
                self.log(.info, "Kernel kennt das Projekt nicht mehr, es wird wieder geöffnet")
                let msg = ProjectOpenMessage(id: self.nextRequestID(), path: project.path.path)
                self.request(msg, timeout: 60) { result in
                    switch result {
                    case .success(.project):
                        if self.model.autoRun && self.scene.isEmpty { self.runModel() }
                    case .success(let m):
                        self.log(.warning, "Projekt wieder öffnen: unerwartete Antwort \(m.typeName)")
                    case .failure(let e):
                        self.log(.error, "Projekt wieder öffnen fehlgeschlagen: \(e.message)")
                    }
                }
            }
        }
    }

    private func applyProject(_ p: ProjectMessage) {
        projectSeenSinceHello = true
        let url = URL(fileURLWithPath: p.path, isDirectory: true)
        let modelFile = p.model.map { URL(fileURLWithPath: $0) } ?? url.appendingPathComponent("model.py")
        let info = ProjectInfo(path: url, name: p.name ?? url.lastPathComponent, modelFile: modelFile)
        if model.project?.path.standardizedFileURL != url.standardizedFileURL {
            // Anderes Projekt: Szene leeren, beim ersten Lauf alles einpassen
            scene.removeAll()
            fitOnFirstPart = true
            clearSelectionState()
            model.measurements = []
            annotations = []
            highlightLabels = [:]
            updateParts()
            refreshOverlay()
            model.run = .idle
            model.bom = nil
            model.inventarVerstoesse = []
            log(.info, "Projekt \(info.name) geöffnet")
            model.project = info
            adoptInventarRegel(p, project: url)
            // Der Katalog hat eine Projekt-Ebene: war er schon geladen, für das neue Projekt neu holen
            if catalogWanted { reloadCatalog() }
            return
        }
        model.project = info
        if p.inventarRegel != nil { adoptInventarRegel(p, project: url) }
    }

    private func handlePart(_ record: PartRecord) {
        scene.upsert(record)
        updateParts()
        if fitOnFirstPart {
            viewport.fit(scene.visibleBounds(), animated: false)
            fitOnFirstPart = false
            fitAtRunEnd = true
        } else if fitAtRunEnd {
            // Erster Lauf eines Projekts: mit jedem neuen Teil nachführen, damit alles im Bild bleibt
            viewport.fit(scene.visibleBounds(), animated: true)
        }
        refreshOverlay()
        startAnimationTimerIfNeeded()
    }

    /// `model.parts` und `model.triangleCount` aus der Szene.
    func updateParts() {
        model.parts = scene.order.compactMap { name in
            guard let r = scene.record(name) else { return nil }
            let b = SceneStore.transformBox(r.localMin, r.localMax, r.header.transformMatrix)
            return PartNode(
                id: name, color: r.header.colorVector, material: r.header.material, visible: scene.isVisible(name),
                triangles: r.triangleCount, faces: r.faceCount, edges: r.edgeCount, bboxMin: b.min, bboxMax: b.max,
                volume: r.header.volume, mass: r.header.mass, run: r.run, stock: r.header.stock,
                inventarFehlt: r.header.inventarFehlt || model.inventarVerstoesse.contains(name))
        }
        model.triangleCount = scene.triangleCount
        scene.setInventoryWarnings(Set(model.parts.filter(\.inventarFehlt).map(\.id)))
    }

    func sendSettings() {
        send(SettingsMessage(
            autoRun: model.autoRun, slowMs: model.slowMotion ? Self.slowMotionMs : 0, inventarRegel: model.inventarRegel))
    }

    // MARK: Animation

    func startAnimationTimerIfNeeded() {
        guard animationTimer == nil, scene.isAnimating() else { return }
        animationTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] t in
            MainActor.assumeIsolated {
                guard let self else {
                    t.invalidate()
                    return
                }
                self.scene.tick()
                if !self.scene.isAnimating() {
                    t.invalidate()
                    self.animationTimer = nil
                }
            }
        }
    }

    // MARK: Auswahl und Messen

    func handleClick(_ pick: PickResult?, modifiers: NSEvent.ModifierFlags) {
        var ref = pick.flatMap { scene.resolve($0) }
        // Wie Blenders Objektmodus: im Teilemodus wählt ein Klick das ganze Teil; Messen braucht immer Elemente
        if !model.measureMode, model.selectionMode == .parts, let r = ref { ref = r.partRef }
        if model.measureMode {
            guard let ref else { return }
            measurePending.append(ref)
            applySelection(measurePending)
            if measurePending.count >= 2 {
                let refs = measurePending
                measurePending = []
                measure(refs)
            }
            updateMeasureHint()
            return
        }
        var refs = scene.selection
        if modifiers.contains(.shift) || modifiers.contains(.command) {
            if let ref {
                if let i = refs.firstIndex(of: ref) { refs.remove(at: i) } else { refs.append(ref) }
            }
        } else {
            refs = ref.map { [$0] } ?? []
        }
        applySelection(refs)
    }

    /// Auswahl setzen, anzeigen und dem Kernel melden.
    func applySelection(_ refs: [ElementRef], notifyKernel: Bool = true) {
        scene.setSelection(refs)
        model.selection = scene.selection.compactMap { r in scene.record(r.part)?.selectionItem(for: r) }
        viewport.controller.selectedBodyIDs = scene.outlinedBodyIDs
        if notifyKernel { send(SelectionMessage(run: scene.latestRun, refs: scene.selection.map(\.string))) }
        refreshOverlay()
    }

    private func clearSelectionState() {
        measurePending = []
        if !scene.selection.isEmpty || !model.selection.isEmpty {
            scene.setSelection([])
            model.selection = []
            viewport.controller.selectedBodyIDs = []
        }
        updateMeasureHint()
    }

    func updateMeasureHint() {
        guard model.measureMode else {
            viewport.hint = nil
            return
        }
        viewport.hint =
            measurePending.isEmpty
            ? "Messen: erstes Element anklicken" : "Messen: zweites Element anklicken (\(measurePending[0].string))"
    }

    func measure(_ refs: [ElementRef]) {
        if AppInfo.isDemoMode {
            addMeasurement(DemoScene.measure(refs, in: scene))
            return
        }
        var list = refs.map(\.string)
        if list.count == 2 && list[0] == list[1] { list = [list[0]] }
        let msg = MeasureRequestMessage(id: nextRequestID(), refs: list, run: scene.latestRun, show: false)
        request(msg, timeout: 30) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.measureResponse(let m)): self.addMeasurement(m.result)
            case .success(let other): self.log(.warning, "Messen: unerwartete Antwort \(other.typeName)")
            case .failure(let e): self.log(.error, "Messen fehlgeschlagen: \(e.message)")
            }
        }
    }

    func addMeasurement(_ r: MeasureResult) {
        let item = MeasurementItem(
            refs: r.refs, kind: r.kind, text: r.text, points: r.pointVectors, values: r.values.flattenedNumbers())
        model.measurements.append(item)
        // Kam dasselbe Maß schon als Anmerkung (measure mit show=True), die Anmerkung ersetzen
        removeDimensionAnnotations(matching: item.points)
        log(.info, "Messung: \(r.text)")
        refreshOverlay()
    }

    // MARK: Überlagerung

    static let measureColor = SIMD4<Float>(0.0, 0.55, 0.45, 1)
    static let annotationColor = SIMD4<Float>(0.85, 0.2, 0.45, 1)

    /// Alles, was über dem Bild liegt: Auswahl- und Hervorhebungskanten, Messungen, Anmerkungen.
    func overlayItems() -> [OverlayPrimitive] {
        var items = scene.elementOverlay()
        for m in model.measurements {
            if m.points.count >= 2 {
                items.append(.dimension(a: m.points[0], b: m.points[1], text: m.text, color: Self.measureColor))
            } else if let p = m.points.first {
                items.append(.label(point: p, text: m.text, color: Self.measureColor))
            } else if let first = m.refs.first.flatMap(ElementRef.init), let p = scene.worldAnchor(of: first) {
                items.append(.label(point: p, text: m.text, color: Self.measureColor))
            }
        }
        items.append(contentsOf: annotations.map(\.item))
        return items
    }

    func refreshOverlay() { viewport.setOverlay(overlayItems()) }
}
