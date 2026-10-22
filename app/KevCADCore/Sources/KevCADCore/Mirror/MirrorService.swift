import Combine
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// Spiegel-Dienst der App (MIRROR.md, Version 1): bietet Szene und Zustand über einen Unix-Socket an, über den die
/// VoiceBridge-Mac-App sie live aufs iPhone holt, und nimmt Befehle vom iPhone an.
///
/// - Ohne Miete gehen nur HELLO und AGENTS raus. Nach WATCH folgen SCENE (in Seiten) und STATE, danach nur Änderungen:
///   PART in Kernel-Reihenfolge, STATE_DELTA mit den geänderten Feldern, CAMERA (höchstens 40 je Sekunde).
/// - Netze werden erst gepackt, wenn jemand hinsieht, und zwar im Hintergrund; der Zwischenspeicher hält sie nach
///   Inhalt (Prüfsumme des Teils) und Hash. MESH nur auf MESH_REQ.
/// - CMD wirkt über `AppActions` wie ein Klick am Mac; die Wirkung geht als STATE_DELTA bzw. CAMERA mit
///   `quelle: "iphone"` an alle zurück, dazu CMD_RES (außer bei `kamera`).
/// - Version 1.1: Freigabe vom iPhone (FreigabeVomIPhone.swift) nur für Gegenstellen, die die Prüfung in
///   MirrorGegenstelle.swift bestehen (VoiceBridge-App, Testmodus nur in Testvarianten).
@MainActor
public final class MirrorService {
    /// Zufällige Kennung je Programmstart.
    public let epoche: String
    public let server: MirrorSocketServer
    public var path: String { server.path }

    /// Hauptthread-Zeit des Dienstes (Abgleich, Kamera, Befehle), für Messungen.
    public private(set) var mainThreadSeconds: Double = 0
    public private(set) var syncCount = 0
    public private(set) var cameraFrames = 0

    unowned let controller: AppController
    private var connections: [Int: Peer] = [:]
    private var rev = 0
    private var sentState: MirrorViewState?
    private var sentCamera: MirrorCamera?
    private var baseline: [String: PartKey]?
    private var baselineProject: String?
    private var ops: [PartOp] = []
    private var meshByDigest: [Int: PackedMesh] = [:]
    private var meshByHash: [String: PackedMesh] = [:]
    private var packing = Set<Int>()
    private var agents: [MirrorAgent] = []
    private var pendingSource: MirrorSource?
    private var cameraSource: (source: MirrorSource, until: CFTimeInterval)?
    private var syncScheduled = false
    private var cameraScheduled = false
    private var lastCameraFlush: CFTimeInterval = 0
    private var cancellables = Set<AnyCancellable>()
    private var unknownTypes = Set<String>()
    private var aspectTimer: Timer?
    private let packQueue = DispatchQueue(label: "de.upvis.kevcad.mirror.netze", qos: .utility)
    private static let cacheLimitBytes = 96 << 20

    private struct Peer {
        /// Prüfung der Gegenstelle beim Verbinden (Freigabe, MIRROR.md 1.1); nil, solange sie läuft.
        var urteil: MirrorGegenstelle.Urteil?
        var hello = false
        var leaseUntil: Date?
        var fullSent = false
        var awaitingFull = false
        var client: String?
    }

    private struct PartKey: Equatable {
        var digest: Int
        var run: Int
    }

    private enum PartOp {
        case upsert(record: PartRecord)
        case remove(name: String, run: Int)
        /// Projektwechsel: Teileliste für alle neu
        case scene
    }

    /// Freigabe vom iPhone (MIRROR.md 1.1).
    private(set) lazy var freigabe = FreigabeVomIPhone(service: self)
    /// Testmodus der Freigabe (nur Testvariante mit KEVCAD_FREIGABE_TESTMODUS=1).
    public let freigabeTestmodus: Bool

    public init(controller: AppController, path: String, freigabeTestmodus: Bool = MirrorGegenstelle.testmodus()) {
        self.controller = controller
        self.epoche = String(format: "%016llx", UInt64.random(in: 0...UInt64.max))
        self.server = MirrorSocketServer(path: path)
        self.freigabeTestmodus = freigabeTestmodus
        server.peerVerifier = MirrorGegenstelle.standardPruefer(testmodus: freigabeTestmodus)
        server.onEvent = { [weak self] event in self?.handle(event) }
        controller.model.objectWillChange
            .sink { [weak self] _ in MainActor.assumeIsolated { self?.scheduleSync() } }
            .store(in: &cancellables)
        controller.viewport.objectWillChange
            .sink { [weak self] _ in MainActor.assumeIsolated { self?.scheduleSync() } }
            .store(in: &cancellables)
        controller.viewport.controller.$cameraState
            .sink { [weak self] _ in MainActor.assumeIsolated { self?.scheduleCamera() } }
            .store(in: &cancellables)
    }

    public func start() throws {
        try server.start()
        controller.log(.info, "Spiegel lauscht auf \(server.path) (Epoche \(epoche))")
        if freigabeTestmodus {
            controller.log(.warning, "Spiegel: Testmodus der Freigabe, jede Gegenstelle darf freigeben (nur Testvariante)")
        }
        // Seitenverhältnis der Ansicht (kamera.aspect) ändert sich mit der Fenstergröße, ohne dass die Kamera sich rührt
        aspectTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, !self.connections.isEmpty else { return }
                self.flushCamera()
            }
        }
    }

    public func stop() {
        aspectTimer?.invalidate()
        aspectTimer = nil
        server.stop()
        connections = [:]
    }

    /// Kamerastand mit dem Seitenverhältnis der Ansicht am Mac.
    private var currentCamera: MirrorCamera {
        MirrorCamera(controller.viewport.camera, aspect: controller.viewport.aspectRatio)
    }

    // MARK: Hooks aus dem AppController

    /// Sitzungen aus dem Kernel-Rahmen AGENT.
    public func updateAgents(_ sessions: [MirrorAgent]) {
        guard sessions != agents else { return }
        agents = sessions
        let ids = connections.filter { $0.value.hello }.map(\.key)
        server.send(MirrorAgentsMessage(epoche: epoche, agents: agents), to: ids)
    }

    /// Ein Ansichtsbefehl des Agenten (VIEW_CMD) wird gleich ausgeführt: Änderungen und Kamerafahrt gehören ihm.
    public func noteAgentCommand() {
        pendingSource = .agent
        cameraSource = (.agent, CACurrentMediaTime() + 1.0)
        scheduleSync()
    }

    // MARK: Verbindungen

    private var watcherIDs: [Int] {
        let now = Date()
        var ids: [Int] = []
        for (id, p) in connections where p.fullSent {
            if let until = p.leaseUntil, until > now {
                ids.append(id)
            } else {
                connections[id]?.fullSent = false
                connections[id]?.leaseUntil = nil
            }
        }
        return ids.sorted()
    }

    private var anyoneWaiting: Bool { connections.values.contains { $0.awaitingFull } }

    /// Gegenstellen, die FREIGABE und FREIGABE_ENDE bekommen: Prüfung bestanden und HELLO geschickt (ohne Miete).
    var freigabeEmpfaenger: [Int] {
        connections.filter { $0.value.hello && $0.value.urteil?.erlaubt == true }.map(\.key).sorted()
    }

    private func handle(_ event: MirrorSocketServer.Event) {
        let t0 = CACurrentMediaTime()
        defer { mainThreadSeconds += CACurrentMediaTime() - t0 }
        switch event {
        case .connected(let id):
            connections[id] = Peer()
        case .geprueft(let id, let urteil):
            guard connections[id] != nil else { return }
            connections[id]?.urteil = urteil
            if urteil.erlaubt {
                controller.log(.info, "Spiegel: Verbindung \(id) darf freigeben (\(urteil.grund), PID \(urteil.pid))")
                // Schon begrüßt: offene Anfragen jetzt hinterher
                if connections[id]?.hello == true { freigabe.nachHello(id) }
            }
        case .disconnected(let id, let reason):
            connections[id] = nil
            controller.log(.info, "Spiegel: Verbindung \(id) getrennt (\(reason))")
        case .invalid(let id, let reason):
            controller.log(.warning, "Spiegel: Rahmen von Verbindung \(id) nicht lesbar: \(reason)")
        case .message(let id, let message):
            handle(message, from: id)
        }
    }

    private func handle(_ message: MirrorMessage, from id: Int) {
        guard connections[id] != nil else { return }
        switch message {
        case .hello(let h):
            if h.version != MirrorProtocol.version || (h.protocolName ?? MirrorProtocol.name) != MirrorProtocol.name {
                controller.log(.warning, "Spiegel: Gegenstelle spricht \(h.protocolName ?? "?") Version \(h.version)")
            }
            connections[id]?.hello = true
            connections[id]?.client = h.client
            server.send(helloMessage(), to: [id])
            if connections[id]?.urteil?.erlaubt == true { freigabe.nachHello(id) }  // offene Anfragen gleich hinterher
            controller.log(.info, "Spiegel: \(h.client ?? "Gegenstelle") verbunden (Verbindung \(id))")
        case .watch(let w):
            if connections[id]?.hello != true {
                connections[id]?.hello = true
                server.send(helloMessage(), to: [id])
                if connections[id]?.urteil?.erlaubt == true { freigabe.nachHello(id) }
            }
            connections[id]?.leaseUntil = Date().addingTimeInterval(max(1, w.dauerS))
            let active = connections[id]?.fullSent == true && watcherIDs.contains(id)
            if !active {
                connections[id]?.awaitingFull = true
                ensureMeshes(for: controller.scene.order)
                processPending()
            }
        case .unwatch:
            connections[id]?.leaseUntil = nil
            connections[id]?.fullSent = false
            connections[id]?.awaitingFull = false
        case .meshRequest(let req):
            var unknown: [String] = []
            for hash in req.hashes {
                if let mesh = meshByHash[hash] { server.sendMesh(mesh, to: id) } else { unknown.append(hash) }
            }
            if !unknown.isEmpty { controller.log(.warning, "Spiegel: Netze unbekannt: \(unknown.joined(separator: ", "))") }
        case .command(let cmd):
            perform(cmd, from: id)
        case .unknown(let type):
            if unknownTypes.insert(type).inserted { controller.log(.info, "Spiegel: unbekannter Typ \(type) verworfen") }
        default:
            if unknownTypes.insert(message.typeName).inserted {
                controller.log(.info, "Spiegel: \(message.typeName) von der Gegenstelle verworfen")
            }
        }
    }

    private func helloMessage() -> MirrorHello {
        let build = (Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String).flatMap { Int($0) } ?? 0
        let project = controller.model.project.map { MirrorProject(path: $0.path.path, name: $0.name) }
        return .server(epoche: epoche, appBuild: build, bundleID: AppInfo.bundleID, project: project, agents: agents)
    }

    // MARK: Abgleich

    private func scheduleSync() {
        guard !syncScheduled, !connections.isEmpty else { return }
        syncScheduled = true
        DispatchQueue.main.async { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.syncScheduled = false
                self.sync()
            }
        }
    }

    /// Szene und Zustand mit dem zuletzt Gesendeten vergleichen und Änderungen verschicken.
    func sync() {
        let t0 = CACurrentMediaTime()
        defer {
            mainThreadSeconds += CACurrentMediaTime() - t0
            syncCount += 1
        }
        let watchers = watcherIDs
        guard !watchers.isEmpty || anyoneWaiting else {
            baseline = nil
            sentState = nil
            pendingSource = nil
            return
        }
        if baseline != nil { diffParts() }
        processPending()
        guard !watchers.isEmpty, let old = sentState else { return }
        let now = snapshot()
        let change = MirrorStateChange.between(old, now)
        sentState = now
        guard !change.isEmpty else {
            pendingSource = nil
            return
        }
        var source = pendingSource ?? .mac
        if pendingSource == nil, change.fieldNames.allSatisfy({ ["lauf", "auswahl"].contains($0) }),
            controller.model.agentConnected
        {
            source = .agent
        }
        pendingSource = nil
        rev += 1
        server.send(MirrorStateDeltaMessage(epoche: epoche, rev: rev, quelle: source, change: change), to: watchers)
    }

    /// Teile mit der Grundlage vergleichen: neue oder neu gelieferte Teile (andere Prüfsumme oder anderer Lauf) als
    /// PART upsert in Szenen-Reihenfolge, verschwundene als PART remove.
    private func diffParts() {
        guard var base = baseline else { return }
        let scene = controller.scene
        let project = controller.model.project?.path.path
        if project != baselineProject {
            baselineProject = project
            ops.append(.scene)
            base = [:]
            for name in scene.order {
                if let r = scene.record(name) { base[name] = PartKey(digest: r.digest, run: r.run) }
            }
            ensureMeshes(for: scene.order)
            baseline = base
            return
        }
        var seen = Set<String>()
        var fresh: [PartRecord] = []
        for name in scene.order {
            guard let r = scene.record(name) else { continue }
            seen.insert(name)
            let key = PartKey(digest: r.digest, run: r.run)
            if base[name] != key {
                base[name] = key
                fresh.append(r)
            }
        }
        for name in base.keys where !seen.contains(name) {
            base[name] = nil
            ops.append(.remove(name: name, run: scene.latestRun))
        }
        for r in fresh {
            ops.append(.upsert(record: r))
            ensureMesh(r)
        }
        baseline = base
    }

    /// Ausstehende PART-Nachrichten in Reihenfolge und volle Stände schicken, sobald die Netze gepackt sind.
    private func processPending() {
        let watchers = watcherIDs
        while let op = ops.first {
            switch op {
            case .upsert(let r):
                guard let mesh = meshByDigest[r.digest] else { return }
                server.send(
                    MirrorPartMessage.upsert(epoche: epoche, run: r.run, part: mirrorPart(r, hash: mesh.hash)),
                    to: watchers)
            case .remove(let name, let run):
                server.send(MirrorPartMessage.remove(epoche: epoche, run: run, name: name), to: watchers)
            case .scene:
                guard let pages = scenePages() else { return }
                for page in pages { server.send(page, to: watchers) }
            }
            ops.removeFirst()
        }
        let waiting = connections.filter { $0.value.awaitingFull }.map(\.key).sorted()
        guard !waiting.isEmpty, let pages = scenePages() else { return }
        let state = snapshot()
        if baseline == nil || watchers.isEmpty {
            baseline = Dictionary(
                uniqueKeysWithValues: controller.scene.order.compactMap { n in
                    controller.scene.record(n).map { (n, PartKey(digest: $0.digest, run: $0.run)) }
                })
            baselineProject = controller.model.project?.path.path
            ops = []
        }
        if watchers.isEmpty { sentState = state } else if sentState == nil { sentState = state }
        // Ein neuer Zuschauer bekommt den Stand, auf den sich alle folgenden Änderungen beziehen
        let full = sentState ?? state
        let cam = currentCamera
        for id in waiting {
            for page in pages { server.send(page, to: [id]) }
            var s = full
            s.kamera = cam
            server.send(MirrorStateMessage(epoche: epoche, rev: rev, state: s), to: [id])
            connections[id]?.awaitingFull = false
            connections[id]?.fullSent = true
        }
        sentCamera = sentCamera ?? cam
        trimCache()
    }

    private func mirrorPart(_ r: PartRecord, hash: String) -> MirrorPart {
        MirrorPart(
            name: r.name, hash: hash, color: r.header.color ?? [0.72, 0.75, 0.79, 1], material: r.header.material,
            bbox: r.header.bbox, counts: MeshCounts(r.header.counts))
    }

    /// Teileliste der aktuellen Szene in Seiten, oder nil, solange noch Netze gepackt werden.
    private func scenePages() -> [MirrorScenePage]? {
        let scene = controller.scene
        var parts: [MirrorPart] = []
        var lo = SIMD3<Double>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Double>(repeating: -.greatestFiniteMagnitude)
        for name in scene.order {
            guard let r = scene.record(name) else { continue }
            guard let mesh = meshByDigest[r.digest] else {
                ensureMesh(r)
                return nil
            }
            let p = mirrorPart(r, hash: mesh.hash)
            if let b = p.bbox, b.min.count >= 3, b.max.count >= 3 {
                lo = simd_min(lo, SIMD3(b.min[0], b.min[1], b.min[2]))
                hi = simd_max(hi, SIMD3(b.max[0], b.max[1], b.max[2]))
            }
            parts.append(p)
        }
        let bbox = parts.isEmpty || lo.x > hi.x ? nil : BBox(min: [lo.x, lo.y, lo.z], max: [hi.x, hi.y, hi.z])
        let project = controller.model.project.map { MirrorProject(name: $0.name) }
        return MirrorScenePage.pages(epoche: epoche, project: project, run: scene.latestRun, bbox: bbox, parts: parts)
    }

    // MARK: Netze

    private func ensureMeshes(for names: [String]) {
        for n in names { if let r = controller.scene.record(n) { ensureMesh(r) } }
    }

    /// Netz im Hintergrund packen (einmal je Prüfsumme); danach geht es mit den ausstehenden Nachrichten weiter.
    private func ensureMesh(_ r: PartRecord) {
        let digest = r.digest
        guard meshByDigest[digest] == nil, !packing.contains(digest) else { return }
        packing.insert(digest)
        let geometry = r.geometry
        packQueue.async { [weak self] in
            let mesh = try? PackedMesh(geometry: geometry)
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.packing.remove(digest)
                    if let mesh {
                        self.meshByDigest[digest] = mesh
                        self.meshByHash[mesh.hash] = mesh
                    }
                    let t0 = CACurrentMediaTime()
                    self.processPending()
                    self.mainThreadSeconds += CACurrentMediaTime() - t0
                }
            }
        }
    }

    /// Netze von Teilen, die es nicht mehr gibt, verwerfen, sobald der Speicher über der Grenze liegt.
    private func trimCache() {
        let total = meshByDigest.values.reduce(0) { $0 + $1.packed.count }
        guard total > Self.cacheLimitBytes else { return }
        let current = Set(controller.scene.order.compactMap { controller.scene.record($0)?.digest })
        for d in meshByDigest.keys where !current.contains(d) { meshByDigest[d] = nil }
        let hashes = Set(meshByDigest.values.map(\.hash))
        for h in meshByHash.keys where !hashes.contains(h) { meshByHash[h] = nil }
    }

    // MARK: Kamera

    private func scheduleCamera() {
        guard !cameraScheduled, !connections.isEmpty else { return }
        cameraScheduled = true
        let wait = max(0, lastCameraFlush + 1 / MirrorProtocol.cameraRate - CACurrentMediaTime())
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.cameraScheduled = false
                self.flushCamera()
            }
        }
    }

    private func flushCamera() {
        let t0 = CACurrentMediaTime()
        defer { mainThreadSeconds += CACurrentMediaTime() - t0 }
        lastCameraFlush = t0
        let watchers = watcherIDs
        guard !watchers.isEmpty else { return }
        let cam = currentCamera
        guard cam != sentCamera else { return }
        sentCamera = cam
        var source = MirrorSource.mac
        if let s = cameraSource, s.until > t0 { source = s.source }
        rev += 1
        cameraFrames += 1
        server.send(MirrorCameraMessage(epoche: epoche, rev: rev, kamera: cam, quelle: source), to: watchers)
    }

    // MARK: Zustand

    /// Voller Zustand aus Szene, Modell und Viewport.
    func snapshot() -> MirrorViewState {
        let c = controller
        let scene = c.scene
        var s = MirrorViewState()
        s.kamera = currentCamera
        s.auswahl = MirrorSelection(run: scene.latestRun, refs: scene.selection.map(\.string))
        s.verborgen = scene.order.filter { !scene.isVisible($0) }
        s.isoliert = scene.isolated
        s.hervorgehoben = scene.highlights.map { h in
            let rgb = h.overlayColor  // sRGB wie bei den Teilen (MIRROR.md)
            return MirrorHighlight(
                refs: h.refs.map(\.string), color: [rgb.x, rgb.y, rgb.z, rgb.w].map(Self.round4), label: h.label)
        }
        s.darstellung = Self.protocolName(c.model.displayStyle)
        s.schnitt = scene.section.map { plane in
            let n = -plane.normal
            return MirrorSection(
                axis: Self.axisName(n), normal: [n.x, n.y, n.z].map { Self.round3(Double($0)) },
                offset: Self.round3(Double(plane.distance)))
        }
        var masse = c.model.measurements.map { m in
            MirrorMeasure(id: m.id.uuidString, kind: m.kind, points: m.points.map(Self.point), text: m.text)
        }
        let labels = Set(c.highlightLabels.values)
        for (id, item) in c.annotations where !labels.contains(id) {
            switch item {
            case .dimension(let a, let b, let text, _):
                masse.append(MirrorMeasure(id: id, kind: "dimension", points: [Self.point(a), Self.point(b)], text: text))
            case .arrow(let a, let b, let text, _):
                masse.append(MirrorMeasure(id: id, kind: "arrow", points: [Self.point(a), Self.point(b)], text: text ?? ""))
            case .label(let p, let text, _):
                masse.append(MirrorMeasure(id: id, kind: "label", points: [Self.point(p)], text: text))
            case .polyline, .dot, .badge:  // Symbole der Bedingungen kommen nicht aus annotate
                break
            }
        }
        s.masse = masse
        s.befunde = (c.model.pruefung?.befunde ?? []).map { b in
            MirrorFinding(
                art: b.art, teile: b.teile, schwere: b.schwere.rawValue,
                ort: b.ort.map { JSONValue.array(Self.point($0).map(JSONValue.number)) }, text: b.text)
        }
        switch c.model.run {
        case .idle: s.lauf = MirrorRunState(run: scene.latestRun, laeuft: false)
        case .running(let run, let step, _): s.lauf = MirrorRunState(run: run, laeuft: true, schritt: step)
        case .finished(let run, _, _, _): s.lauf = MirrorRunState(run: run, laeuft: false)
        case .failed(let run, let message, _, _): s.lauf = MirrorRunState(run: run, laeuft: false, fehler: message)
        }
        return s
    }

    static func protocolName(_ d: DisplayStyle) -> String {
        switch d {
        case .shadedEdges: return MirrorDisplay.shadedEdges.rawValue
        case .shaded: return MirrorDisplay.shaded.rawValue
        case .wireframe: return MirrorDisplay.wireframe.rawValue
        case .xray: return MirrorDisplay.xray.rawValue
        }
    }

    static func axisName(_ n: SIMD3<Float>) -> String? {
        let axes: [(SIMD3<Float>, String)] = [
            (SIMD3(1, 0, 0), "x"), (SIMD3(0, 1, 0), "y"), (SIMD3(0, 0, 1), "z"),
            (SIMD3(-1, 0, 0), "-x"), (SIMD3(0, -1, 0), "-y"), (SIMD3(0, 0, -1), "-z"),
        ]
        return axes.first { simd_distance($0.0, simd_normalize(n)) < 1e-5 }?.1
    }

    static func point(_ p: SIMD3<Float>) -> [Double] { [p.x, p.y, p.z].map { round3(Double($0)) } }
    static func round3(_ v: Double) -> Double { (v * 1000).rounded() / 1000 }
    static func round4(_ v: Float) -> Float { (v * 10000).rounded() / 10000 }

    // MARK: Befehle vom iPhone

    private func perform(_ cmd: MirrorCommand, from id: Int) {
        let c = controller
        let scene = c.scene
        var ok = true
        var fehler: String?
        func reply() { server.send(MirrorCommandResult(replyTo: cmd.id, ok: ok, fehler: fehler), to: [id]) }
        switch cmd.knownOp {
        case .kamera?:
            guard let cam = cmd.camera else { return }
            cameraSource = (.iphone, CACurrentMediaTime() + 0.5)
            c.viewport.setCamera(cam.cameraState)
            return  // latest-only, ohne Antwort

        case .auswahl?:
            let modus = cmd.args["modus"]?.stringValue ?? "setzen"
            guard ["setzen", "dazu", "weg"].contains(modus) else {
                ok = false
                fehler = "Unbekannter Modus \(modus)"
                return reply()
            }
            let run = cmd.args["run"]?.intValue
            var valid: [ElementRef] = []
            var problems: [String] = []
            for text in cmd.refs {
                guard let r = ElementRef(text) else { continue }
                if r.kind != .part, let run, run != scene.latestRun {
                    problems.append("gilt nicht mehr (Lauf \(run), aktuell \(scene.latestRun)): \(text)")
                } else if scene.isValid(r) {
                    valid.append(r)
                } else {
                    problems.append("nicht gefunden: \(text)")
                }
            }
            var refs = scene.selection
            switch modus {
            case "dazu": for r in valid where !refs.contains(r) { refs.append(r) }
            case "weg": refs.removeAll { valid.contains($0) }
            default: refs = valid
            }
            pendingSource = .iphone
            c.select(refs.map(\.string))
            ok = !valid.isEmpty || cmd.refs.isEmpty
            fehler = problems.isEmpty ? nil : problems.joined(separator: "; ")

        case .sichtbarkeit?:
            let mode = cmd.args["mode"]?.stringValue ?? ""
            let (hits, missing) = scene.expand(cmd.refs.compactMap(ElementRef.init).map(\.partRef))
            let names = hits.map(\.part)
            pendingSource = .iphone
            switch mode {
            case "show_all": c.showAll()
            case "show", "hide", "isolate":
                guard !names.isEmpty else {
                    ok = false
                    fehler = "Unbekannte Teile: \(missing.isEmpty ? "(keine)" : missing.joined(separator: ", "))"
                    break
                }
                if mode == "isolate" { c.isolate(names) } else { c.setVisibility(names, visible: mode == "show") }
                if !missing.isEmpty { fehler = "Nicht gefunden: \(missing.joined(separator: ", "))" }
            default:
                ok = false
                fehler = "Unbekannter Modus \(mode)"
            }

        case .fokus?:
            let (known, missing) = scene.expand(cmd.refs.compactMap(ElementRef.init))
            if known.isEmpty {
                ok = false
                fehler = "Unbekannte Referenz: \(missing.joined(separator: ", "))"
            } else {
                cameraSource = (.iphone, CACurrentMediaTime() + 1.0)
                c.focus(on: known.map(\.string))
                if !missing.isEmpty { fehler = "Nicht gefunden: \(missing.joined(separator: ", "))" }
            }

        case .ansicht?:
            var rotation: simd_quatf?
            if let name = cmd.args["standard"]?.stringValue {
                guard let sv = ViewportCoordinator.standardView(protocolName: name) else {
                    ok = false
                    fehler = "Unbekannte Ansicht \(name)"
                    return reply()
                }
                rotation = sv.rotation
            }
            var ortho: Bool?
            switch cmd.args["projection"]?.stringValue {
            case "orthographic"?: ortho = true
            case "perspective"?: ortho = false
            case nil: break
            case let p?:
                ok = false
                fehler = "Unbekannte Projektion \(p)"
                return reply()
            }
            cameraSource = (.iphone, CACurrentMediaTime() + 1.0)
            c.viewport.apply(rotation: rotation, orthographic: ortho, fitTo: scene.visibleBounds(), animated: true)

        case .darstellung?:
            let name = cmd.args["display"]?.stringValue ?? ""
            guard let style = AppController.displayStyle(protocolName: name) else {
                ok = false
                fehler = "Unbekannte Darstellung \(name)"
                return reply()
            }
            pendingSource = .iphone
            c.setDisplayStyle(style)

        case .freigabe?:
            // Vor jeder Freigabe die Gegenstelle noch einmal prüfen (Audit-Token vom Verbinden); Antwort kommt erst nach
            // der Bestätigung im Katalog. Die Prüfung läuft neben dem Hauptthread (sie liest die App auf der Platte).
            server.pruefeGegenstelle(id) { [weak self] urteil in
                guard let self, self.connections[id] != nil else { return }
                self.freigabe.befehl(cmd, von: id, urteil: urteil)
            }
            return

        case .einpassen?:
            // Wie Pos1 (alles) bzw. „.“ (die genannten Teile), mit den Rändern und der Projektion des Macs
            cameraSource = (.iphone, CACurrentMediaTime() + 1.0)
            if cmd.args["refs"]?.arrayValue == nil {
                c.viewAll()
            } else {
                let (known, missing) = scene.expand(cmd.refs.compactMap(ElementRef.init))
                if let b = scene.worldBounds(of: known), !known.isEmpty {
                    c.viewport.fit(b, animated: true)
                    if !missing.isEmpty { fehler = "Nicht gefunden: \(missing.joined(separator: ", "))" }
                } else if cmd.refs.isEmpty {
                    c.viewAll()
                } else {
                    ok = false
                    fehler = "Unbekannte Referenz: \(missing.joined(separator: ", "))"
                }
            }

        case nil:
            ok = false
            fehler = "Unbekannter Befehl \(cmd.op)"
        }
        reply()
        scheduleSync()
    }
}
