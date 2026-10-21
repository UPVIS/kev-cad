import AppKit
import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

@MainActor
final class ControllerTests: XCTestCase {
    private func streamEvents() throws -> [IncomingEvent] {
        try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
    }

    private func event(_ type: String, in events: [IncomingEvent]) -> IncomingEvent? {
        events.first { e in
            switch e {
            case .message(let m): return m.typeName == type
            case .part: return type == "PART_UPSERT"
            default: return false
            }
        }
    }

    /// Lädt HELLO, PROJECT, RUN_START, STEP und beide Teile, dann RUN_END.
    private func loadedController() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try streamEvents()
        c.handle(Array(events.prefix(7)))
        return c
    }

    func testKernelLogLevels() {
        XCTAssertEqual(AppController.kernelLogLevel("2026-10-21 20:03:25,706 INFO uvicorn.error: Started"), .info)
        XCTAssertEqual(AppController.kernelLogLevel("2026-10-21 20:03:25,706 WARNING kevcad: langsam"), .warning)
        XCTAssertEqual(AppController.kernelLogLevel("2026-10-21 20:03:25,706 ERROR kevcad: kaputt"), .error)
        XCTAssertEqual(AppController.kernelLogLevel("Traceback (most recent call last):"), .error)
        XCTAssertEqual(AppController.kernelLogLevel("[kernel] Rechenprozess bereit"), .info)
    }

    func testKernelCommandResolution() {
        let none = KernelProcess.command(socket: "/x y/kernel.sock", port: 47824, environment: [:], executable: nil)
        guard case .failure(let e1) = none else { return XCTFail() }
        XCTAssertTrue(e1.description.contains("cd kernel && uv sync"), e1.description)

        let missing = KernelProcess.command(
            socket: "/s", port: 1, environment: [:], executable: URL(fileURLWithPath: "/gibt/es/nicht/kevcad-kernel"))
        guard case .failure(let e2) = missing else { return XCTFail() }
        XCTAssertTrue(e2.description.contains("/gibt/es/nicht/kevcad-kernel"))
        XCTAssertTrue(e2.description.contains("uv sync"))

        let custom = KernelProcess.command(
            socket: "/x y/kernel.sock", port: 47824,
            environment: ["KEVCAD_KERNEL_CMD": "'/a b/python' /t/fake_kernel.py --demo-view"], executable: nil)
        guard case .success(let cmd) = custom else { return XCTFail() }
        XCTAssertEqual(cmd.executable, "/bin/sh")
        XCTAssertEqual(
            cmd.arguments,
            ["-c", "exec '/a b/python' /t/fake_kernel.py --demo-view serve --socket '/x y/kernel.sock' --port 47824"])

        let exe = URL(fileURLWithPath: "/bin/ls")
        guard case .success(let real) = KernelProcess.command(socket: "/s.sock", port: 5, environment: [:], executable: exe)
        else { return XCTFail() }
        XCTAssertEqual(real.executable, "/bin/ls")
        XCTAssertEqual(real.arguments, ["serve", "--socket", "/s.sock", "--port", "5"])
    }

    func testStartWithoutKernelReportsSetupHint() throws {
        let env = ProcessInfo.processInfo.environment
        if env["KEVCAD_KERNEL_CMD"] != nil || env["KEVCAD_DEMO"] == "1" || env["KEVCAD_KERNEL_EXTERNAL"] == "1" {
            throw XCTSkip("Umgebung setzt einen Kernel")
        }
        let c = AppController(model: AppModel())
        c.start()
        guard case .failed(let msg) = c.model.kernelState else { return XCTFail("\(c.model.kernelState)") }
        XCTAssertTrue(msg.contains("uv sync"), msg)
        XCTAssertTrue(c.model.log.contains { $0.level == .error })
        c.stop()
        XCTAssertEqual(c.model.kernelState, .stopped)
    }

    func testFixtureStreamDrivesModel() throws {
        let c = AppController(model: AppModel())
        let m = c.model
        let events = try streamEvents()
        XCTAssertEqual(events.count, 13)

        c.handle([events[0]])  // HELLO
        XCTAssertEqual(m.kernelState, .ready)
        c.handle([events[1]])  // PROJECT
        XCTAssertEqual(m.project?.name, "Wandhalter")
        XCTAssertEqual(m.project?.modelFile.path, "/Users/test/Documents/Kev CAD/Wandhalter/model.py")
        c.handle([events[2]])  // RUN_START
        XCTAssertEqual(m.run, .running(run: 1, step: nil, stepIndex: 0))
        XCTAssertEqual(m.kernelState, .busy)
        c.handle([events[3]])  // STEP
        XCTAssertEqual(m.run, .running(run: 1, step: "Grundplatte", stepIndex: 1))
        c.handle([events[4], events[5]])  // Teile
        XCTAssertEqual(m.parts.map(\.id), ["Grundplatte", "Halter/Bolzen"])
        XCTAssertEqual(m.parts[1].path, ["Halter", "Bolzen"])
        XCTAssertEqual(m.parts[0].triangles, 12)
        XCTAssertEqual(m.parts[0].faces, 6)
        XCTAssertEqual(m.parts[0].volume, 6000)
        XCTAssertEqual(m.parts[1].bboxMin, SIMD3(25, -5, -10))
        XCTAssertEqual(m.triangleCount, 260)
        XCTAssertEqual(c.viewport.bodies.filter { $0.id != SceneStore.depthHelperID }.count, 2)
        // Hilfskörper für den Tiefenbereich: unsichtbar, nicht anklickbar, größer als die Szene
        let helper = try XCTUnwrap(c.viewport.bodies.first { $0.id == SceneStore.depthHelperID })
        XCTAssertFalse(helper.isPickable)
        XCTAssertTrue(helper.indices.isEmpty && helper.edges.isEmpty)
        XCTAssertLessThan(try XCTUnwrap(helper.boundingBox).min.x, -5)
        c.handle([events[6]])  // RUN_END
        XCTAssertEqual(m.run, .finished(run: 1, durationMs: 412, parts: 2, warnings: []))
        XCTAssertEqual(m.kernelState, .ready)
        c.handle([events[7]])  // RUN_ERROR
        XCTAssertEqual(
            m.run,
            .failed(
                run: 2, message: "NameError: name 'Boxx' is not defined", line: 7,
                excerpt: "6 | step('Grundplatte')\n7 | platte = Boxx(10, 20, 30)"))
        XCTAssertEqual(m.parts.count, 2, "die letzte gute Geometrie bleibt stehen")
        c.handle([events[8]])  // AGENT
        XCTAssertTrue(m.agentConnected)
        XCTAssertEqual(m.agentActivity, "misst Abstand Lasche ↔ Grundplatte")
        c.handle([events[9], events[10]])  // VIEW_CMD focus, SCREENSHOT_REQ (ohne Verbindung wird nur gerendert)
        c.handle([events[11]])  // MEASURE_RES ohne offene Anfrage
        XCTAssertEqual(m.measurements.count, 1)
        XCTAssertEqual(m.measurements[0].text, "Abstand 20,000 mm (dx 20,000)")
        XCTAssertEqual(m.measurements[0].values["distance"], 20)
        XCTAssertEqual(m.measurements[0].points.count, 2)
        XCTAssertTrue(c.viewport.overlayItems.contains { if case .dimension = $0 { return true } else { return false } })
        c.handle([events[12]])  // PART_REMOVE
        XCTAssertEqual(m.parts.map(\.id), ["Grundplatte"])
        XCTAssertEqual(c.viewport.bodies.filter { $0.id != SceneStore.depthHelperID }.count, 1)

        // Neues HELLO (Wiederverbindung): Szene leeren, der Kernel schickt alles neu
        c.handle([events[0]])
        XCTAssertTrue(m.parts.isEmpty)
        XCTAssertEqual(c.scene.latestRun, 0)
        // Kommt danach kein PROJECT (Kernel neu gestartet), öffnet die App das Projekt wieder
        RunLoop.main.run(until: Date().addingTimeInterval(1.3))
        XCTAssertTrue(m.log.contains { $0.text.contains("wird wieder geöffnet") })
        XCTAssertEqual(AppController.exitText(-9), "Signal 9")
        XCTAssertEqual(AppController.exitText(1), "Code 1")
    }

    func testViewCommands() throws {
        let c = try loadedController()
        let m = c.model
        func run(_ cmd: String, _ args: JSONValue) -> (Bool, String?) {
            c.performViewCommand(ViewCommandMessage(id: "k", cmd: cmd, args: args))
        }
        XCTAssertTrue(run("focus", ["refs": ["Halter/Bolzen#f1"], "animate": false]).0)
        XCTAssertFalse(run("focus", ["refs": ["Gibt/Es/Nicht"]]).0)

        XCTAssertTrue(run("visibility", ["mode": "hide", "refs": ["Grundplatte"]]).0)
        XCTAssertEqual(m.parts.first { $0.id == "Grundplatte" }?.visible, false)
        XCTAssertTrue(run("visibility", ["mode": "isolate", "refs": ["Grundplatte#f2"]]).0)
        XCTAssertEqual(m.parts.filter(\.visible).map(\.id), ["Grundplatte"])
        XCTAssertTrue(run("visibility", ["mode": "show_all", "refs": nil]).0)
        XCTAssertEqual(m.parts.filter(\.visible).count, 2)
        // Baugruppe „Halter“ steht für alle Teile darunter (wie beim Kernel)
        XCTAssertTrue(run("visibility", ["mode": "hide", "refs": ["Halter"]]).0)
        XCTAssertEqual(m.parts.filter(\.visible).map(\.id), ["Grundplatte"])
        let partly = run("visibility", ["mode": "show", "refs": ["Halter", "Fehlt"]])
        XCTAssertTrue(partly.0)
        XCTAssertEqual(partly.1, "Nicht gefunden: Fehlt")
        XCTAssertEqual(m.parts.filter(\.visible).count, 2)
        XCTAssertTrue(run("focus", ["refs": ["Halter"], "animate": false]).0)

        let hl = run("highlight", ["refs": ["Grundplatte#f5", "Halter/Bolzen#e0"], "color": [0, 0.8, 0, 1], "label": "Hier", "clear": true])
        XCTAssertTrue(hl.0)
        XCTAssertTrue(c.viewport.overlayItems.contains { if case .label(_, let t, _) = $0 { return t == "Hier" } else { return false } })
        XCTAssertTrue(c.viewport.overlayItems.contains { if case .polyline = $0 { return true } else { return false } })
        XCTAssertFalse(run("highlight", ["refs": ["Fehlt#f1"]]).0)
        XCTAssertTrue(run("highlight", ["refs": [], "clear": true]).0)
        XCTAssertFalse(c.viewport.overlayItems.contains { if case .label = $0 { return true } else { return false } })

        XCTAssertTrue(run("section", ["enabled": true, "axis": "z", "offset": 2.5]).0)
        XCTAssertTrue(m.sectionEnabled)
        XCTAssertEqual(c.viewport.controller.clipPlanes.count, 1)
        XCTAssertEqual(c.viewport.controller.clipPlanes[0].normal, SIMD3(0, 0, -1))
        XCTAssertEqual(c.viewport.controller.clipPlanes[0].distance, 2.5)
        XCTAssertTrue(run("section", ["enabled": false]).0)
        XCTAssertFalse(m.sectionEnabled)
        XCTAssertTrue(c.viewport.controller.clipPlanes.isEmpty)
        XCTAssertFalse(run("section", ["enabled": true, "axis": "q"]).0)

        XCTAssertTrue(run("explode", ["factor": 0.5]).0)
        XCTAssertEqual(m.explodeFactor, 0.5)
        XCTAssertTrue(run("explode", ["factor": 0]).0)

        let an = run("annotate", ["kind": "dimension", "points": [[0, 0, 0], [10, 0, 0]], "text": nil, "id": "m1"])
        XCTAssertTrue(an.0)
        XCTAssertTrue(
            c.viewport.overlayItems.contains { if case .dimension(_, _, let t, _) = $0 { return t == "10,000 mm" } else { return false } })
        XCTAssertTrue(run("annotate", ["kind": "arrow", "points": [[0, 0, 0], [0, 0, 10]], "text": "hier", "id": "p1"]).0)
        XCTAssertFalse(run("annotate", ["kind": "label", "points": []]).0)
        XCTAssertTrue(run("clear_annotations", ["ids": ["m1"]]).0)
        XCTAssertFalse(c.viewport.overlayItems.contains { if case .dimension = $0 { return true } else { return false } })
        XCTAssertTrue(run("clear_annotations", ["ids": nil]).0)
        XCTAssertFalse(c.viewport.overlayItems.contains { if case .arrow = $0 { return true } else { return false } })

        XCTAssertTrue(run("view", ["standard": "top", "projection": "orthographic", "display": "wireframe", "fit": true]).0)
        XCTAssertEqual(m.displayStyle, .wireframe)
        XCTAssertEqual(c.viewport.controller.displayMode, .wireframe)
        RunLoop.main.run(until: Date().addingTimeInterval(0.7))
        let cam = c.viewport.camera
        XCTAssertTrue(cam.isOrthographic)
        XCTAssertEqual(ViewportCoordinator.nearestStandardName(cam), "top")
        XCTAssertFalse(run("view", ["standard": "schräg"]).0)
        XCTAssertTrue(run("view", ["display": "xray"]).0)
        XCTAssertEqual(m.displayStyle, .xray)
        XCTAssertLessThan(c.viewport.bodies[0].color.w, 0.5)
        XCTAssertFalse(run("gibt_es_nicht", [:]).0)
    }

    func testClickSelectionAndMeasureMode() throws {
        let c = try loadedController()
        let m = c.model
        let box = SceneStore.bodyID(part: "Grundplatte", chunk: 0)
        let cyl = SceneStore.bodyID(part: "Halter/Bolzen", chunk: 0)
        let map = [0: box, 1: cyl]
        func pick(_ object: UInt32, _ prim: UInt32, _ kind: UInt32) -> PickResult? {
            PickResult(rawValue: object | (prim << 16) | (kind << 30), indexMap: map)
        }
        // Blender-Objektmodus (Standard): ein Klick wählt das ganze Teil
        XCTAssertEqual(m.selectionMode, .parts)
        c.handleClick(pick(0, 11, 0), modifiers: [])
        XCTAssertEqual(m.selection.map(\.ref), ["Grundplatte"])
        // Tab: Flächen, Kanten und Punkte
        c.setSelectionMode(.elements)
        c.handleClick(pick(0, 11, 0), modifiers: [])
        XCTAssertEqual(m.selection.map(\.ref), ["Grundplatte#f5"])
        XCTAssertEqual(m.selection.first?.summary, "Fläche 5 · Ebene · 200,0 mm²")
        c.handleClick(pick(1, 0, 1), modifiers: .shift)
        XCTAssertEqual(m.selection.map(\.ref), ["Grundplatte#f5", "Halter/Bolzen#e0"])
        c.handleClick(pick(1, 0, 1), modifiers: .shift)
        XCTAssertEqual(m.selection.map(\.ref), ["Grundplatte#f5"])
        c.setSelectionMode(.parts)
        c.handleClick(pick(1, 3, 0), modifiers: [])
        XCTAssertEqual(m.selection.map(\.ref), ["Halter/Bolzen"])
        XCTAssertEqual(c.viewport.controller.selectedBodyIDs, [cyl])
        c.handleClick(nil, modifiers: [])
        XCTAssertTrue(m.selection.isEmpty)
        XCTAssertTrue(c.viewport.controller.selectedBodyIDs.isEmpty)

        c.select(["Grundplatte#v3", "Unsinn#f1"])
        XCTAssertEqual(m.selection.map(\.ref), ["Grundplatte#v3"])

        c.setMeasureMode(true)
        XCTAssertEqual(c.viewport.hint, "Messen: erstes Element anklicken")
        c.handleClick(pick(0, 11, 0), modifiers: [])
        XCTAssertTrue(c.viewport.hint?.contains("zweites") ?? false)
        c.handleClick(pick(1, 0, 0), modifiers: [])
        // ohne Kernel schlägt die Anfrage fehl, der Messmodus bleibt bereit
        XCTAssertTrue(m.log.contains { $0.text.contains("Messen fehlgeschlagen") })
        XCTAssertEqual(c.viewport.hint, "Messen: erstes Element anklicken")
        c.setMeasureMode(false)
        XCTAssertNil(c.viewport.hint)

        // Neuer Lauf: Referenzen gelten nicht mehr, Auswahl wird geleert
        c.select(["Grundplatte#f1"])
        let events = try streamEvents()
        c.handle([events[2]])
        XCTAssertTrue(m.selection.isEmpty)
    }

    func testActionsWithoutConnection() throws {
        let c = try loadedController()
        c.setVisibility(["Halter/Bolzen"], visible: false)
        XCTAssertEqual(c.model.parts.last?.visible, false)
        c.showAll()
        c.isolate(["Halter/Bolzen"])
        XCTAssertEqual(c.model.parts.first?.visible, false)
        c.showAll()
        c.setDisplayStyle(.shaded)
        XCTAssertEqual(c.viewport.controller.displayMode, .shaded)
        c.setSection(enabled: true, axis: "x", offset: 1)
        XCTAssertTrue(c.model.sectionEnabled)
        c.setSection(enabled: false, axis: "x", offset: 1)
        c.setExplode(0.3)
        XCTAssertEqual(c.model.explodeFactor, 0.3, accuracy: 1e-6)
        c.setAutoRun(false)
        XCTAssertFalse(c.model.autoRun)
        c.setSlowMotion(true)
        XCTAssertTrue(c.model.slowMotion)
        c.setStandardView(.isoBackLeft)
        c.focus(on: ["Halter/Bolzen"])
        c.runModel()
        XCTAssertTrue(c.model.log.contains { $0.text.contains("Lauf nicht gestartet") })
        c.export(formats: ["step"])
        XCTAssertTrue(c.model.log.contains { $0.text.contains("Export fehlgeschlagen") })
        c.handle([.message(try Fixtures.message("measure_res.frame"))])
        XCTAssertEqual(c.model.measurements.count, 1)
        let remover = try XCTUnwrap(c.model.actions as? MeasurementRemoving)
        remover.removeMeasurement(id: c.model.measurements[0].id)
        XCTAssertTrue(c.model.measurements.isEmpty)
        XCTAssertFalse(c.viewport.overlayItems.contains { if case .dimension = $0 { return true } else { return false } })
        c.clearMeasurements()
        XCTAssertTrue(c.model.measurements.isEmpty)
        // Projekt öffnen vor dem HELLO wird nachgeholt
        let fresh = AppController(model: AppModel())
        fresh.openProject(at: URL(fileURLWithPath: "/tmp/Projekt"))
        XCTAssertNotNil(fresh.queuedProjectRequest)
    }

    func testDemoGeometry() throws {
        let parts = DemoScene.parts()
        XCTAssertEqual(parts.map(\.header.name), ["Grundplatte", "Halter/Lasche", "Halter/Bolzen"])
        XCTAssertEqual(try XCTUnwrap(parts[0].header.volume), 48_000, accuracy: 1)
        XCTAssertEqual(parts[0].header.faces.count, 6)
        XCTAssertEqual(parts[2].header.faces.map(\.t), ["cylinder", "plane", "plane"])
        XCTAssertEqual(try XCTUnwrap(parts[2].header.volume), Double.pi * 36 * 40, accuracy: 30)
        for p in parts {
            XCTAssertNoThrow(try p.geometry.validate(faceCount: p.header.counts.face))
            let back = try PartGeometry.decode(payload: p.geometry.encodedPayload(), counts: p.header.counts)
            XCTAssertEqual(back, p.geometry)
        }
        let scene = SceneStore()
        for p in parts { scene.upsert(PartRecord(header: p.header, geometry: p.geometry), flash: false) }
        let r = DemoScene.measure([.face("Grundplatte", 5), .face("Halter/Bolzen", 2)], in: scene)
        XCTAssertEqual(r.kind, "distance")
        XCTAssertEqual(r.pointVectors.count, 2)
    }
    /// Maße des Agenten (measure mit show=True) kommen als Messung und als Anmerkung; Löschen muss beides entfernen.
    func testAgentMeasurementDisappearsWhenDeleted() throws {
        let c = try loadedController()
        let pts: JSONValue = .array([.array([.number(0), .number(0), .number(0)]), .array([.number(20), .number(0), .number(0)])])
        // Reihenfolge 1: erst Anmerkung, dann Messung
        _ = c.performViewCommand(ViewCommandMessage(id: "k1", cmd: "annotate", args: .object([
            "kind": .string("dimension"), "points": pts, "text": .string("Abstand 20,000 mm"), "id": .string("m-1")])))
        c.addMeasurement(MeasureResult(refs: ["A", "B"], run: 1, kind: "distance", values: .object([:]),
                                       points: [[0, 0, 0], [20, 0, 0]], text: "Abstand 20,000 mm"))
        XCTAssertTrue(c.annotations.isEmpty, "Anmerkung wird durch die Messung ersetzt")
        // Reihenfolge 2: Anmerkung nach der Messung wird nicht doppelt gezeichnet
        _ = c.performViewCommand(ViewCommandMessage(id: "k2", cmd: "annotate", args: .object([
            "kind": .string("dimension"), "points": pts, "id": .string("m-2")])))
        XCTAssertTrue(c.annotations.isEmpty)
        XCTAssertEqual(c.model.measurements.count, 1)
        c.removeMeasurement(id: c.model.measurements[0].id)
        XCTAssertTrue(c.model.measurements.isEmpty)
        XCTAssertTrue(c.viewport.overlayItems.allSatisfy { if case .dimension = $0 { return false } else { return true } })
        // Alle löschen entfernt auch freie Maß-Anmerkungen
        let other: JSONValue = .array([.array([.number(0), .number(0), .number(0)]), .array([.number(0), .number(5), .number(0)])])
        _ = c.performViewCommand(ViewCommandMessage(id: "k3", cmd: "annotate", args: .object([
            "kind": .string("dimension"), "points": other])))
        XCTAssertEqual(c.annotations.count, 1)
        c.clearMeasurements()
        XCTAssertTrue(c.annotations.isEmpty)
    }
}

@MainActor
final class ProcessTests: XCTestCase {
    /// Ein Ersatzbefehl über KEVCAD_KERNEL_CMD: Ausgabe kommt zeilenweise an, das Ende wird gemeldet.
    func testProcessOutputAndExit() throws {
        setenv("KEVCAD_KERNEL_CMD", "/bin/echo hallo", 1)
        defer { unsetenv("KEVCAD_KERNEL_CMD") }
        let p = KernelProcess()
        var lines: [String] = []
        let done = expectation(description: "beendet")
        var exitCode: Int32 = -1
        var expectedExit = true
        p.onOutput = { line, _ in lines.append(line) }
        p.onExit = { code, expected in
            exitCode = code
            expectedExit = expected
            done.fulfill()
        }
        try p.start(socket: "/tmp/kevcad-process-test.sock", port: 4711)
        wait(for: [done], timeout: 5)
        XCTAssertEqual(exitCode, 0)
        XCTAssertFalse(expectedExit)
        XCTAssertTrue(lines.contains("hallo serve --socket /tmp/kevcad-process-test.sock --port 4711"), "\(lines)")
        XCTAssertFalse(p.isRunning)
    }

    func testStopTerminates() throws {
        setenv("KEVCAD_KERNEL_CMD", "/bin/sleep 30 #", 1)
        defer { unsetenv("KEVCAD_KERNEL_CMD") }
        let p = KernelProcess()
        let done = expectation(description: "beendet")
        p.onExit = { _, expected in
            XCTAssertTrue(expected)
            done.fulfill()
        }
        try p.start(socket: "/tmp/kevcad-process-test2.sock", port: 4712)
        XCTAssertTrue(p.isRunning)
        p.stop()
        wait(for: [done], timeout: 5)
    }

    func testLineBuffer() {
        var b = LineBuffer()
        XCTAssertEqual(b.append(Data("ab".utf8)), [])
        XCTAssertEqual(b.append(Data("c\nde\r\nf".utf8)), ["abc", "de"])
        XCTAssertEqual(b.flush(), "f")
    }

}
