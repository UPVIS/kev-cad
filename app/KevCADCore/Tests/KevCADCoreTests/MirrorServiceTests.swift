import Darwin
import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Kleiner Spiegel-Client für die Tests: blockierend lesen auf einem eigenen Faden, alles in einen `MirrorReceiver`.
final class TestMirrorClient: @unchecked Sendable {
    let fd: Int32
    private let lock = NSLock()
    private var _frames: [(t: Double, frame: Frame)] = []
    private var _receiver = MirrorReceiver()
    private var _closed = false
    private var seq = 0
    let t0 = CFAbsoluteTimeGetCurrent()

    init(path: String) throws {
        fd = socket(AF_UNIX, SOCK_STREAM, 0)
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard rc == 0 else { throw NSError(domain: "TestMirrorClient", code: Int(errno)) }
        var on: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        let t = Thread { [weak self] in self?.readLoop() }
        t.start()
    }

    deinit { close() }

    func close() {
        lock.lock()
        let was = _closed
        _closed = true
        lock.unlock()
        if !was {
            shutdown(fd, SHUT_RDWR)
            Darwin.close(fd)
        }
    }

    private func readLoop() {
        let reader = FrameReader()
        var buf = [UInt8](repeating: 0, count: 64 * 1024)
        while true {
            let n = buf.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
            if n <= 0 { break }
            let now = CFAbsoluteTimeGetCurrent() - t0
            guard let frames = try? buf.withUnsafeBytes({ try reader.feed(UnsafeRawBufferPointer(rebasing: $0[0..<n])) })
            else { break }
            lock.lock()
            for f in frames {
                _frames.append((now, f))
                _ = try? _receiver.apply(frame: f)
            }
            lock.unlock()
        }
        lock.lock()
        _closed = true
        lock.unlock()
    }

    func send(_ m: any MirrorOutgoing) throws {
        seq += 1
        let data = try m.frame(seq: seq).encoded
        _ = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }
    }

    var frames: [(t: Double, frame: Frame)] {
        lock.lock()
        defer { lock.unlock() }
        return _frames
    }

    var receiver: MirrorReceiver {
        lock.lock()
        defer { lock.unlock() }
        return _receiver
    }

    var closed: Bool {
        lock.lock()
        defer { lock.unlock() }
        return _closed
    }

    func headers(_ type: String? = nil, from start: Int = 0) -> [JSONValue] {
        frames.dropFirst(start).compactMap { try? JSONDecoder().decode(JSONValue.self, from: $0.frame.header) }
            .filter { type == nil || $0["type"]?.stringValue == type }
    }

    func requestMissing() throws -> Int {
        lock.lock()
        let req = _receiver.takeMeshRequest()
        lock.unlock()
        if let req { try send(req) }
        return req?.hashes.count ?? 0
    }
}

@MainActor
final class MirrorServiceTests: XCTestCase {
    var dir: String!
    var controller: AppController!

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.path.count > 60
            ? "/tmp/kcm-\(UUID().uuidString.prefix(8))" : NSTemporaryDirectory() + "kcm-\(UUID().uuidString.prefix(8))"
        controller = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        controller.handle(Array(events.prefix(7)))  // HELLO, PROJECT, RUN_START, STEP, zwei Teile, RUN_END
    }

    override func tearDown() async throws {
        controller.mirror?.stop()
        try? FileManager.default.removeItem(atPath: dir)
    }

    var socketPath: String { dir + "/m.sock" }

    /// Hauptthread laufen lassen, bis `cond` gilt.
    func waitUntil(_ timeout: TimeInterval = 5, _ cond: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if cond() { return true }
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.005))
        }
        return cond()
    }

    func watchingClient() throws -> TestMirrorClient {
        controller.startMirror(path: socketPath)
        XCTAssertNotNil(controller.mirror)
        let c = try TestMirrorClient(path: socketPath)
        try c.send(MirrorHello.client("test"))
        try c.send(MirrorWatch(dauerS: 60, geraet: "Test"))
        XCTAssertTrue(waitUntil { c.receiver.hasScene && c.receiver.state != nil }, "voller Stand nach WATCH")
        return c
    }

    func testRightsHandshakeFullStateAndMeshes() throws {
        controller.startMirror(path: socketPath)
        var st = stat()
        XCTAssertEqual(stat(socketPath, &st), 0)
        XCTAssertEqual(st.st_mode & 0o777, 0o600)
        XCTAssertEqual(stat(dir, &st), 0)
        XCTAssertEqual(st.st_mode & 0o777, 0o700)

        let c = try TestMirrorClient(path: socketPath)
        try c.send(MirrorHello.client("test"))
        XCTAssertTrue(waitUntil { c.receiver.hello != nil })
        let hello = try XCTUnwrap(c.receiver.hello)
        XCTAssertEqual(hello.epoche, controller.mirror?.epoche)
        XCTAssertEqual(hello.version, 1)
        XCTAssertEqual(hello.project?.name, "Wandhalter")
        XCTAssertNotNil(hello.project?.path)
        // Ohne Miete nur HELLO und AGENTS
        controller.applySelection([.part("Grundplatte")])
        controller.mirror?.updateAgents([MirrorAgent(sessionID: "s-1", aktiv: true, seit: "2026-10-21T21:50:00Z")])
        XCTAssertTrue(waitUntil { !c.headers("AGENTS").isEmpty })
        _ = waitUntil(0.2) { false }
        XCTAssertEqual(Set(c.headers().compactMap { $0["type"]?.stringValue }), ["HELLO", "AGENTS"])

        try c.send(MirrorWatch(dauerS: 60))
        XCTAssertTrue(waitUntil { c.receiver.hasScene && c.receiver.state != nil })
        let r = c.receiver
        XCTAssertEqual(r.parts.map(\.name), controller.scene.order)
        XCTAssertEqual(r.state?.auswahl.refs, ["Grundplatte"])
        XCTAssertEqual(r.state?.kamera.aspect, Float(controller.viewport.aspectRatio))
        let scene = try XCTUnwrap(c.headers("SCENE").first)
        XCTAssertNil(scene["project"]?["path"], "kein Pfad in SCENE")
        XCTAssertGreaterThan(try c.requestMissing(), 0)
        XCTAssertTrue(waitUntil { c.receiver.isComplete }, "alle Netze da")
        for p in c.receiver.parts {
            let g = try XCTUnwrap(try c.receiver.geometry(of: p))
            XCTAssertEqual(g.triangleCount, controller.scene.record(p.name)?.triangleCount)
            XCTAssertEqual(g.positions, controller.scene.record(p.name)?.geometry.positions)
        }
        let seqs = c.headers().compactMap { $0["seq"]?.intValue }
        XCTAssertEqual(seqs, Array(1...seqs.count))
    }

    func testCommandsActLikeTheMacAndEchoWithSource() throws {
        let c = try watchingClient()
        var start = c.frames.count
        try c.send(MirrorCommand.auswahl(id: "i1", refs: ["Halter/Bolzen"], run: controller.scene.latestRun))
        XCTAssertTrue(waitUntil { c.headers("CMD_RES", from: start).contains { $0["reply_to"]?.stringValue == "i1" } })
        XCTAssertEqual(controller.scene.selection.map(\.string), ["Halter/Bolzen"])
        XCTAssertTrue(waitUntil { c.receiver.state?.auswahl.refs == ["Halter/Bolzen"] })
        let delta = try XCTUnwrap(c.headers("STATE_DELTA", from: start).last)
        XCTAssertEqual(delta["quelle"]?.stringValue, "iphone")

        start = c.frames.count
        try c.send(MirrorCommand.sichtbarkeit(id: "i2", mode: "isolate", refs: ["Halter"]))
        XCTAssertTrue(waitUntil { c.receiver.state?.isoliert == ["Halter/Bolzen"] })
        XCTAssertEqual(c.receiver.state?.verborgen, ["Grundplatte"])
        try c.send(MirrorCommand.sichtbarkeit(id: "i3", mode: "show_all"))
        XCTAssertTrue(waitUntil { c.receiver.state?.isoliert == nil && c.receiver.state?.verborgen == [] })

        // Prüfbefunde (Prüfung Stufe 1) gehen als befunde mit
        controller.model.pruefung = PruefErgebnis(
            run: 1, zustand: .done,
            befunde: [PruefBefund(id: "b1", art: "durchdringung", teile: ["Grundplatte", "Halter/Bolzen"],
                                  schwere: .fehler, text: "Bolzen steckt 2 mm in der Grundplatte",
                                  ort: SIMD3(30, 0, 10))])
        XCTAssertTrue(waitUntil { c.receiver.state?.befunde.first?.schwere == "fehler" })
        XCTAssertEqual(c.receiver.state?.befunde.first?.ort, .array([30, 0, 10]))

        try c.send(MirrorCommand.darstellung(id: "i4", display: "xray"))
        XCTAssertTrue(waitUntil { c.receiver.state?.darstellung == "xray" })
        XCTAssertEqual(controller.model.displayStyle, .xray)

        start = c.frames.count
        var cam = MirrorCamera(controller.viewport.camera)
        cam.distance = 777
        try c.send(MirrorCommand.kamera(id: "i5", cam))
        XCTAssertTrue(waitUntil { abs(controller.viewport.camera.distance - 777) < 0.01 })
        XCTAssertTrue(waitUntil { c.receiver.state?.kamera.distance == 777 })
        let camFrame = try XCTUnwrap(c.headers("CAMERA", from: start).last)
        XCTAssertEqual(camFrame["quelle"]?.stringValue, "iphone")
        XCTAssertFalse(c.headers("CMD_RES", from: start).contains { $0["reply_to"]?.stringValue == "i5" })

        start = c.frames.count
        try c.send(MirrorCommand.einpassen(id: "i6", refs: ["Grundplatte"]))
        XCTAssertTrue(waitUntil { c.headers("CMD_RES", from: start).contains { $0["reply_to"]?.stringValue == "i6" } })
        XCTAssertTrue(waitUntil(2) { !c.headers("CAMERA", from: start).isEmpty })

        start = c.frames.count
        for (id, cmd) in [("i7", MirrorCommand(id: "i7", op: "zaubern")),
                          ("i8", MirrorCommand.darstellung(id: "i8", display: "glas")),
                          ("i9", MirrorCommand.fokus(id: "i9", refs: ["Gibtsnicht"]))]
        {
            try c.send(cmd)
            XCTAssertTrue(waitUntil { c.headers("CMD_RES", from: start).contains { $0["reply_to"]?.stringValue == id } })
            let res = c.headers("CMD_RES", from: start).first { $0["reply_to"]?.stringValue == id }
            XCTAssertEqual(res?["ok"]?.boolValue, false, id)
        }
    }

    func testNewRunSendsPartsInOrderAndClearsSelection() throws {
        let c = try watchingClient()
        controller.applySelection([.face("Grundplatte", 0)])
        XCTAssertTrue(waitUntil { c.receiver.state?.auswahl.refs == ["Grundplatte#f0"] })
        let start = c.frames.count
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        // gleiches Modell noch einmal als Lauf 2: RUN_START, STEP, beide Teile, RUN_END
        var again: [IncomingEvent] = []
        for e in events.prefix(7).dropFirst(2) {
            switch e {
            case .message(.runStart(var r)): r.run = 2; again.append(.message(.runStart(r)))
            case .part(var rec): rec.header.run = 2; again.append(.part(rec))
            default: again.append(e)
            }
        }
        controller.handle(again)
        XCTAssertTrue(waitUntil { c.headers("PART", from: start).count == 2 })
        let parts = c.headers("PART", from: start)
        XCTAssertEqual(parts.compactMap { $0["name"]?.stringValue }, ["Grundplatte", "Halter/Bolzen"])
        XCTAssertEqual(parts.compactMap { $0["run"]?.intValue }, [2, 2])
        XCTAssertTrue(waitUntil { c.receiver.state?.auswahl == MirrorSelection(run: 2, refs: []) })
        XCTAssertTrue(waitUntil { c.receiver.state?.lauf.run == 1 || c.receiver.state?.lauf.run == 2 })
    }

    /// Messung: Kugelschieber (112 Teile, 132.000 Dreiecke) über den Socket bis zum vollen Stand; Hauptthread-Zeit des
    /// Dienstes beim Live-Aufbau und bei einer Kamerafahrt. Braucht samples/mirror-recordings/kugelschieber.kcadrec
    /// (nicht im Git) oder KEVCAD_KUGELSCHIEBER.
    func testMeasureKugelschieber() throws {
        let env = ProcessInfo.processInfo.environment["KEVCAD_KUGELSCHIEBER"]
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let url = env.map { URL(fileURLWithPath: $0) }
            ?? repo.appendingPathComponent("samples/mirror-recordings/kugelschieber.kcadrec")
        guard let data = try? Data(contentsOf: url) else { throw XCTSkip("Kugelschieber-Aufzeichnung fehlt: \(url.path)") }
        let events = try FrameReader().feed(data).map(KernelConnection.decode)
        let fresh = AppController(model: AppModel())
        controller = fresh
        fresh.startMirror(path: socketPath)
        let mirror = try XCTUnwrap(fresh.mirror)
        // Erster Lauf ohne Zuschauer (es wird nichts gepackt)
        for e in events { fresh.handle([e]) }
        _ = waitUntil(0.3) { false }
        let parts = fresh.scene.order.count

        // Kalt: erster Zuschauer, alle Netze werden erst jetzt im Hintergrund gepackt
        let t0 = CFAbsoluteTimeGetCurrent()
        let d = try TestMirrorClient(path: socketPath)
        try d.send(MirrorHello.client("messung"))
        try d.send(MirrorWatch(dauerS: 60))
        XCTAssertTrue(waitUntil(10) { d.receiver.hasScene && d.receiver.state != nil })
        let tScene = CFAbsoluteTimeGetCurrent() - t0
        _ = try d.requestMissing()
        XCTAssertTrue(waitUntil(30) { d.receiver.isComplete })
        let tFull = CFAbsoluteTimeGetCurrent() - t0
        let meshBlocks = d.headers("MESH").count
        let bytes = d.frames.reduce(0) { $0 + $1.frame.encoded.count }

        // Warm: zweiter Zuschauer, Netze liegen im Zwischenspeicher
        let t1 = CFAbsoluteTimeGetCurrent()
        let w = try TestMirrorClient(path: socketPath)
        try w.send(MirrorHello.client("messung-2"))
        try w.send(MirrorWatch(dauerS: 60))
        XCTAssertTrue(waitUntil(10) { w.receiver.hasScene && w.receiver.state != nil })
        _ = try w.requestMissing()
        XCTAssertTrue(waitUntil(30) { w.receiver.isComplete })
        let tWarm = CFAbsoluteTimeGetCurrent() - t1
        w.close()

        // Live-Aufbau mit Zuschauer: derselbe Lauf noch einmal als neuer Lauf, Teil für Teil wie vom Kernel
        let base = mirror.mainThreadSeconds
        let tBuild = CFAbsoluteTimeGetCurrent()
        let firstPart = d.headers("PART").count
        for e in events {
            switch e {
            case .message(.runStart(var r)): r.run += 1; fresh.handle([.message(.runStart(r))])
            case .part(var rec): rec.header.run += 1; fresh.handle([.part(rec)])
            case .message(.step), .message(.runEnd): fresh.handle([e])
            default: continue  // HELLO, PROJECT usw. würden die Szene neu aufsetzen
            }
            RunLoop.current.run(mode: .default, before: Date())
        }
        XCTAssertTrue(waitUntil(20) { d.headers("PART").count - firstPart >= parts })
        XCTAssertEqual(d.headers("PART").dropFirst(firstPart).compactMap { $0["name"]?.stringValue },
                       fresh.scene.order, "Kernel-Reihenfolge")
        let buildWall = CFAbsoluteTimeGetCurrent() - tBuild
        let buildMain = mirror.mainThreadSeconds - base

        // Kamerafahrt: 2 s mit 120 Ständen je Sekunde
        let camBase = mirror.mainThreadSeconds
        let camFrames0 = d.headers("CAMERA").count
        let start = CFAbsoluteTimeGetCurrent()
        var cam = fresh.viewport.camera
        var k = 0
        while CFAbsoluteTimeGetCurrent() - start < 2 {
            k += 1
            cam.rotation = simd_quatf(angle: Float(k) * 0.01, axis: SIMD3(0, 0, 1)) * cam.rotation
            fresh.viewport.setCamera(cam)
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(1.0 / 120))
        }
        _ = waitUntil(0.2) { false }
        let camMain = mirror.mainThreadSeconds - camBase
        let camFrames = d.headers("CAMERA").count - camFrames0

        let report = """
            Kugelschieber: \(parts) Teile, \(fresh.scene.triangleCount) Dreiecke
            Voller Stand über den Socket (kalt, Netze werden erst gepackt): Szene und Zustand nach \
            \(Int(tScene * 1000)) ms, alle Netze nach \(Int(tFull * 1000)) ms (\(meshBlocks) Netzblöcke, \(bytes / 1024) KB)
            Voller Stand warm (Netze im Zwischenspeicher): \(Int(tWarm * 1000)) ms
            Live-Aufbau mit Zuschauer: \(Int(buildWall * 1000)) ms gesamt, davon Hauptthread im Spiegel \
            \(String(format: "%.1f", buildMain * 1000)) ms
            Kamerafahrt 2 s mit \(k) Ständen: \(camFrames) CAMERA gesendet, Hauptthread im Spiegel \
            \(String(format: "%.2f", camMain * 1000)) ms (\(String(format: "%.3f", camMain * 1000 / Double(max(k, 1)))) ms je Bild)
            """
        print(report)
        try? report.write(toFile: dir + "/../kevcad-mirror-messung.txt", atomically: true, encoding: .utf8)
        XCTAssertLessThanOrEqual(Double(camFrames), 2.2 * MirrorProtocol.cameraRate)
        d.close()
    }
}
