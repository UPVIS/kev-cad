import Foundation
import XCTest

@testable import KevCADCore

final class ProtocolTests: XCTestCase {
    /// Jede Testdatei ergibt genau einen Rahmen mit dem erwarteten Typ und der erwarteten Nutzlastgröße.
    func testEveryFixtureFrameDecodes() throws {
        let exp = try Fixtures.expected()
        let frames = try XCTUnwrap(exp["frames"]?.arrayValue)
        XCTAssertEqual(frames.count, 22)  // 16 bis Phase 2, dazu 6 der Animation (Phase 5)
        for f in frames {
            let file = try XCTUnwrap(f["file"]?.stringValue)
            let type = try XCTUnwrap(f["type"]?.stringValue)
            let frame = try Fixtures.frame(file)
            XCTAssertEqual(frame.payload.count, f["payload_bytes"]?.intValue, file)
            let env = try JSONDecoder().decode(MessageEnvelope.self, from: frame.header)
            XCTAssertEqual(env.type, type, file)
            let msg = try KernelMessage.decode(frame)
            XCTAssertEqual(msg.typeName, type, file)
            if case .unknown = msg { XCTFail("\(file) als unbekannt gelesen") }
        }
    }

    /// stream.bin am Stück, Byte für Byte und in zufälligen Stücken: immer dieselben 16 Rahmen in Reihenfolge.
    func testStreamWholeBytewiseAndChunked() throws {
        let stream = try Fixtures.data("stream.bin")
        let expectedTypes = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).compactMap { $0["type"]?.stringValue }
        let expectedSizes = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).compactMap { $0["payload_bytes"]?.intValue }

        func types(_ frames: [Frame]) throws -> [String] {
            try frames.map { try JSONDecoder().decode(MessageEnvelope.self, from: $0.header).type }
        }

        let whole = try FrameReader().feed(stream)
        XCTAssertEqual(try types(whole), expectedTypes)
        XCTAssertEqual(whole.map(\.payload.count), expectedSizes)

        let r = FrameReader()
        var bytewise: [Frame] = []
        for b in stream { bytewise += try r.feed(Data([b])) }
        XCTAssertEqual(try types(bytewise), expectedTypes)
        XCTAssertEqual(bytewise.map(\.payload), whole.map(\.payload))
        XCTAssertEqual(r.pendingBytes, 0)

        var gen = SystemRandomNumberGenerator()
        for _ in 0..<5 {
            let rr = FrameReader()
            var out: [Frame] = []
            var i = 0
            while i < stream.count {
                let n = Int.random(in: 1...700, using: &gen)
                out += try rr.feed(stream.subdata(in: i..<min(i + n, stream.count)))
                i += n
            }
            XCTAssertEqual(try types(out), expectedTypes)
            XCTAssertEqual(out.map(\.header), whole.map(\.header))
        }

        // Dekodieren aller Nachrichten aus dem Strom
        let msgs = try whole.map(KernelMessage.decode)
        XCTAssertEqual(msgs.map(\.typeName), expectedTypes)
    }

    /// Geometrie der Teile gegen fixtures.json.
    func testPartPayloadsMatchExpectations() throws {
        let parts = try XCTUnwrap(Fixtures.expected()["parts"]?.objectValue)
        XCTAssertEqual(parts.count, 3)
        for (file, e) in parts {
            let (h, g) = try Fixtures.part(file)
            XCTAssertEqual(h.name, e["name"]?.stringValue, file)
            let c = try XCTUnwrap(e["counts"])
            XCTAssertEqual(h.counts.vert, c["vert"]?.intValue)
            XCTAssertEqual(h.counts.tri, c["tri"]?.intValue)
            XCTAssertEqual(h.counts.face, c["face"]?.intValue)
            XCTAssertEqual(h.counts.edge, c["edge"]?.intValue)
            XCTAssertEqual(h.counts.epts, c["epts"]?.intValue)
            XCTAssertEqual(h.counts.vtx, c["vtx"]?.intValue)
            XCTAssertEqual(h.counts.payloadBytes, e["payload_bytes"]?.intValue)
            XCTAssertEqual(g.vertexCount, h.counts.vert)
            XCTAssertEqual(g.normals.count, h.counts.vert * 3)
            XCTAssertEqual(g.triangleCount, h.counts.tri)
            XCTAssertEqual(g.triFace.count, h.counts.tri)
            XCTAssertEqual(g.edgeCount, h.counts.edge)
            XCTAssertEqual(g.edgeOffsets.last.map(Int.init), h.counts.epts)
            XCTAssertEqual(g.brepVertexCount, h.counts.vtx)

            let fp = try XCTUnwrap(e["first_position"]?.doubles)
            let p0 = g.position(0)
            XCTAssertEqual(Double(p0.x), fp[0], accuracy: 1e-4)
            XCTAssertEqual(Double(p0.y), fp[1], accuracy: 1e-4)
            XCTAssertEqual(Double(p0.z), fp[2], accuracy: 1e-4)
            XCTAssertEqual(g.triangles.prefix(3).map(Int.init), e["first_triangle"]?.doubles?.map { Int($0) })
            XCTAssertEqual(g.triFace.last.map(Int.init), e["tri_face_last"]?.intValue)
            XCTAssertEqual(h.faces.map(\.t), e["face_types"]?.stringList)
            XCTAssertEqual(h.edges.map(\.t), e["edge_types"]?.stringList)
            XCTAssertEqual(h.bbox?.min, e["bbox"]?["min"]?.doubles)
            XCTAssertEqual(h.bbox?.max, e["bbox"]?["max"]?.doubles)
            XCTAssertEqual(try XCTUnwrap(h.volume), try XCTUnwrap(e["volume"]?.doubleValue), accuracy: 1e-3)

            // Berechneter Hüllquader der Punkte stimmt mit dem Kopf überein
            let b = try XCTUnwrap(g.bounds)
            XCTAssertEqual(Double(b.min.x), h.bbox!.min[0], accuracy: 0.05)
            XCTAssertEqual(Double(b.max.z), h.bbox!.max[2], accuracy: 0.05)
            // Nutzlast lässt sich wieder genauso kodieren
            XCTAssertEqual(g.encodedPayload(), try Fixtures.frame(file).payload)
        }
    }

    func testMessageFields() throws {
        guard case .hello(let h) = try Fixtures.message("hello.frame") else { return XCTFail() }
        XCTAssertEqual(h.protocolVersion, 1)
        XCTAssertEqual(h.kernelVersion, "0.1.0")
        XCTAssertEqual(h.build123d, "0.13.0")
        XCTAssertEqual(h.mcpPort, 47823)

        guard case .project(let p) = try Fixtures.message("project.frame") else { return XCTFail() }
        XCTAssertEqual(p.name, "Wandhalter")
        XCTAssertEqual(p.path, "/Users/test/Documents/Kev CAD/Wandhalter")
        XCTAssertEqual(p.model, "/Users/test/Documents/Kev CAD/Wandhalter/model.py")
        XCTAssertNil(p.replyTo)

        guard case .runStart(let rs) = try Fixtures.message("run_start.frame") else { return XCTFail() }
        XCTAssertEqual(rs.run, 1)
        XCTAssertEqual(rs.fileHash, "abc123")
        XCTAssertEqual(rs.params?["breite"]?.doubleValue, 120)
        XCTAssertEqual(rs.slowMs, 0)

        guard case .step(let st) = try Fixtures.message("step.frame") else { return XCTFail() }
        XCTAssertEqual(st.index, 1)
        XCTAssertEqual(st.text, "Grundplatte")

        guard case .runEnd(let re) = try Fixtures.message("run_end.frame") else { return XCTFail() }
        XCTAssertEqual(re.run, 1)
        XCTAssertEqual(re.durationMs, 412)
        XCTAssertEqual(re.parts, 2)
        XCTAssertEqual(re.warnings, [])
        XCTAssertEqual(re.params?["breite"]?.doubleValue, 120)

        guard case .runError(let er) = try Fixtures.message("run_error.frame") else { return XCTFail() }
        XCTAssertEqual(er.run, 2)
        XCTAssertEqual(er.line, 7)
        XCTAssertTrue(er.message.contains("Boxx"))
        XCTAssertTrue(er.excerpt.contains("7 | platte = Boxx"))
        XCTAssertEqual(er.traceback, "File model.py, line 7")
        XCTAssertNil(er.hint)
        let withHint = Frame(
            header: Data(#"{"type":"RUN_ERROR","run":3,"message":"x","line":null,"excerpt":"","hint":"Klammer fehlt"}"#.utf8))
        guard case .runError(let eh) = try KernelMessage.decode(withHint) else { return XCTFail() }
        XCTAssertEqual(eh.hint, "Klammer fehlt")
        XCTAssertNil(eh.line)

        guard case .agent(let ag) = try Fixtures.message("agent.frame") else { return XCTFail() }
        XCTAssertTrue(ag.connected)
        XCTAssertEqual(ag.activity, "misst Abstand Lasche ↔ Grundplatte")

        guard case .viewCommand(let vc) = try Fixtures.message("view_cmd_focus.frame") else { return XCTFail() }
        XCTAssertEqual(vc.id, "k-1")
        XCTAssertEqual(vc.cmd, "focus")
        XCTAssertEqual(vc.args["refs"]?.stringList, ["Halter/Bolzen"])
        XCTAssertEqual(vc.args["animate"]?.boolValue, true)

        guard case .screenshotRequest(let sr) = try Fixtures.message("screenshot_req.frame") else { return XCTFail() }
        XCTAssertEqual(sr.id, "k-2")
        XCTAssertEqual(sr.width, 1280)
        XCTAssertEqual(sr.height, 800)
        XCTAssertEqual(sr.source, "current")
        XCTAssertNil(sr.view)
        XCTAssertFalse(sr.hideOverlays)

        guard case .measureResponse(let mr) = try Fixtures.message("measure_res.frame") else { return XCTFail() }
        XCTAssertEqual(mr.replyTo, "a-5")
        XCTAssertEqual(mr.result.kind, "distance")
        XCTAssertEqual(mr.result.refs, ["Grundplatte#f0", "Halter/Bolzen#f1"])
        XCTAssertEqual(mr.result.values["distance"]?.doubleValue, 20)
        XCTAssertEqual(mr.result.pointVectors, [SIMD3(5, 0, 15), SIMD3(25, 0, 15)])
        XCTAssertEqual(mr.result.text, "Abstand 20,000 mm (dx 20,000)")
        XCTAssertEqual(mr.result.values.flattenedNumbers()["dx"], 20)

        guard case .partRemove(let pr) = try Fixtures.message("part_remove.frame") else { return XCTFail() }
        XCTAssertEqual(pr.run, 2)
        XCTAssertEqual(pr.name, "Halter/Bolzen")
    }

    /// Unbekannte Typen und Felder dürfen nichts kaputt machen.
    func testUnknownTypesAndFieldsAreTolerated() throws {
        let future = Frame(header: Data(#"{"type":"FUTURE_THING","seq":99,"neu":{"a":[1,2]}}"#.utf8))
        guard case .unknown(let t, let raw) = try KernelMessage.decode(future) else { return XCTFail() }
        XCTAssertEqual(t, "FUTURE_THING")
        XCTAssertEqual(raw["neu"]?["a"]?.doubles, [1, 2])

        let hello = Frame(header: Data(#"{"type":"HELLO","seq":1,"protocol":1,"zusatz":true,"mcp_port":1}"#.utf8))
        guard case .hello(let h) = try KernelMessage.decode(hello) else { return XCTFail() }
        XCTAssertEqual(h.mcpPort, 1)

        let status = Frame(header: Data(#"{"type":"STATUS","seq":2}"#.utf8))
        guard case .status(let s) = try KernelMessage.decode(status) else { return XCTFail() }
        XCTAssertEqual(s.state, "ready")

        // ACK mit fehlendem ok gilt als ok
        let ack = Frame(header: Data(#"{"type":"ACK","reply_to":"a-1"}"#.utf8))
        guard case .ack(let a) = try KernelMessage.decode(ack) else { return XCTFail() }
        XCTAssertTrue(a.ok)
        XCTAssertEqual(KernelMessage.ack(a).replyTo, "a-1")
    }

    func testBrokenPayloadIsRejected() throws {
        var frame = try Fixtures.frame("part_box.frame")
        frame.payload.removeLast(4)
        XCTAssertThrowsError(try KernelMessage.decode(frame))

        // Dreiecksindex außerhalb
        let (h, g) = try Fixtures.part("part_box.frame")
        var bad = g
        bad.triangles[0] = 9999
        XCTAssertThrowsError(try PartGeometry.decode(payload: bad.encodedPayload(), counts: h.counts))
    }

    func testFrameReaderRejectsGarbage() {
        let r = FrameReader()
        XCTAssertThrowsError(try r.feed(Data([0xFF, 0xFF, 0xFF, 0x7F])))
    }

    /// App → Kernel: Felder und Namen wie in PROTOCOL.md.
    func testOutgoingMessagesEncodeAsSpecified() throws {
        func json(_ m: some OutgoingMessage) throws -> [String: Any] {
            let frame = try m.frame()
            let back = try FrameReader().feed(frame.encoded)
            XCTAssertEqual(back.count, 1)
            return try XCTUnwrap(JSONSerialization.jsonObject(with: back[0].header) as? [String: Any])
        }
        var run = RunRequestMessage(id: "a-1", params: nil, slowMs: 350)
        run.seq = 4
        let r = try json(run)
        XCTAssertEqual(r["type"] as? String, "RUN_REQ")
        XCTAssertEqual(r["seq"] as? Int, 4)
        XCTAssertEqual(r["id"] as? String, "a-1")
        XCTAssertTrue(r["params"] is NSNull)
        XCTAssertEqual(r["slow_ms"] as? Int, 350)

        let withParams = try json(RunRequestMessage(id: "a-2", params: ["wand_dicke": 5]))
        XCTAssertEqual((withParams["params"] as? [String: Any])?["wand_dicke"] as? Double, 5)

        let s = try json(SettingsMessage(autoRun: true, slowMs: 0))
        XCTAssertEqual(s["type"] as? String, "SETTINGS")
        XCTAssertEqual(s["auto_run"] as? Bool, true)
        XCTAssertEqual(s["slow_ms"] as? Int, 0)

        let hello = try json(HelloAppMessage(appVersion: "0.1", bundleID: "de.upvis.kevcad.test"))
        XCTAssertEqual(hello["type"] as? String, "HELLO_APP")
        XCTAssertEqual(hello["bundle_id"] as? String, "de.upvis.kevcad.test")
        XCTAssertEqual(hello["app_version"] as? String, "0.1")

        let m = try json(MeasureRequestMessage(id: "a-3", refs: ["A#f1", "B#e2"], run: 3, show: true))
        XCTAssertEqual(m["refs"] as? [String], ["A#f1", "B#e2"])
        XCTAssertEqual(m["run"] as? Int, 3)
        XCTAssertEqual(m["show"] as? Bool, true)

        let sel = try json(SelectionMessage(run: 3, refs: []))
        XCTAssertEqual(sel["type"] as? String, "SELECTION")
        XCTAssertEqual(sel["refs"] as? [String], [])

        let ex = try json(ExportRequestMessage(id: "a-4", formats: ["step", "stl"], parts: nil))
        XCTAssertTrue(ex["parts"] is NSNull)

        let shot = try json(
            ScreenshotResponseMessage(replyTo: "k-2", ok: true, width: 10, height: 20, camera: ["projection": "perspective"], mmPerPx: nil))
        XCTAssertEqual(shot["reply_to"] as? String, "k-2")
        XCTAssertTrue(shot["mm_per_px"] is NSNull)
        XCTAssertEqual((shot["camera"] as? [String: Any])?["projection"] as? String, "perspective")

        let ack = try json(AckOutMessage(replyTo: "k-1", ok: false, message: "nein"))
        XCTAssertEqual(ack["type"] as? String, "ACK")
        XCTAssertEqual(ack["ok"] as? Bool, false)

        let open = try json(ProjectNewMessage(id: "a-5", path: "/tmp/x", template: "example"))
        XCTAssertEqual(open["type"] as? String, "PROJECT_NEW")
        XCTAssertEqual(open["template"] as? String, "example")
    }

    func testPayloadWithFrameIsLittleEndian() throws {
        let payload = Data([1, 2, 3])
        let f = FrameCodec.encode(header: Data("{}".utf8), payload: payload)
        XCTAssertEqual(Array(f.prefix(4)), [2, 0, 0, 0])
        XCTAssertEqual(Array(f[6..<10]), [3, 0, 0, 0])
        XCTAssertEqual(Array(f.suffix(3)), [1, 2, 3])
    }
}
