import Foundation
import XCTest

@testable import KevCADWire

/// Die Testdateien in `mirror-fixtures/` (erzeugt von kernel/tools/make_mirror_fixtures.py): lesen, mit
/// `fixtures.json` vergleichen und mit dem Swift-Kodierer wieder schreiben; das Ergebnis muss inhaltlich gleich sein.
final class MirrorFixtureTests: XCTestCase {
    var expected: JSONValue!

    override func setUpWithError() throws {
        expected = try WireFiles.expected()
    }

    func values(_ file: String) -> JSONValue { expected["files"]?[file] ?? .null }

    /// Kopf als JSONValue (zum inhaltlichen Vergleich).
    func json(_ data: Data) throws -> JSONValue { try JSONDecoder().decode(JSONValue.self, from: data) }

    /// Nachricht lesen, mit dem Swift-Kodierer neu schreiben und mit der Datei vergleichen.
    func roundTrip<M: MirrorOutgoing>(_ file: String, _ message: M, payload: Data = Data()) throws {
        let original = try WireFiles.fixture(file)
        let seq = values(file)["seq"]?.intValue ?? 0
        let again = try message.frame(seq: seq, payload: payload)
        XCTAssertEqual(try json(again.header), try json(original.header), "\(file): Swift schreibt anders als die Referenz")
        XCTAssertEqual(again.payload, original.payload, file)
    }

    func testAllFilesDecodeAndMatchExpectations() throws {
        guard case .object(let files) = expected["files"] ?? .null else { return XCTFail("fixtures.json ohne files") }
        XCTAssertGreaterThanOrEqual(files.count, 13)
        for (file, v) in files {
            let f = try WireFiles.fixture(file)
            XCTAssertLessThanOrEqual(f.header.count, MirrorProtocol.maxHeaderBytes, file)
            XCTAssertLessThanOrEqual(f.payload.count, MirrorProtocol.maxPayloadBytes, file)
            let info = try MirrorEnvelopeInfo.peek(f.header)
            XCTAssertEqual(info.type, v["type"]?.stringValue, file)
            XCTAssertEqual(info.prio?.rawValue, v["prio"]?.stringValue, file)
            XCTAssertEqual(info.seq, v["seq"]?.intValue, file)
            let m = try MirrorMessage.decode(f)
            if case .unknown = m { XCTFail("\(file): Typ unbekannt") }
            XCTAssertEqual(m.typeName, v["type"]?.stringValue, file)
        }
    }

    func testHandshakeAndAgents() throws {
        guard case .hello(let vb) = try MirrorMessage.decode(WireFiles.fixture("hello_vb.bin")) else { return XCTFail() }
        XCTAssertFalse(vb.isServerHello)
        XCTAssertEqual(vb.protocolName, "kevcad-mirror")
        try roundTrip("hello_vb.bin", vb)

        guard case .hello(let kc) = try MirrorMessage.decode(WireFiles.fixture("hello_kc.bin")) else { return XCTFail() }
        XCTAssertTrue(kc.isServerHello)
        XCTAssertEqual(kc.epoche, "0123456789abcdef")
        XCTAssertEqual(kc.project?.name, "gestell")
        XCTAssertEqual(kc.agents?.filter(\.aktiv).map(\.sessionID), [values("hello_kc.bin")["aktiv"]?.stringValue ?? ""])
        XCTAssertEqual(kc.agents?.first?.zuletzt, "2026-10-21T22:05:12Z")
        try roundTrip("hello_kc.bin", kc)

        guard case .agents(let a) = try MirrorMessage.decode(WireFiles.fixture("agents.bin")) else { return XCTFail() }
        XCTAssertEqual(a.agents.count, 2)
        try roundTrip("agents.bin", a)

        guard case .watch(let w) = try MirrorMessage.decode(WireFiles.fixture("watch.bin")) else { return XCTFail() }
        XCTAssertEqual(w.dauerS, 300)
        try roundTrip("watch.bin", w)
        try roundTrip("unwatch.bin", MirrorUnwatch())
    }

    func testSceneAndPartAndMeshOverTwoBlocks() throws {
        guard case .scene(let s) = try MirrorMessage.decode(WireFiles.fixture("scene.bin")) else { return XCTFail() }
        XCTAssertEqual(s.parts.count, values("scene.bin")["parts"]?.intValue)
        XCTAssertNil(s.project?.path)
        XCTAssertEqual(s.parts.reduce(0) { $0 + $1.counts.tri }, values("scene.bin")["triangles"]?.intValue)
        try roundTrip("scene.bin", s)

        guard case .part(let p) = try MirrorMessage.decode(WireFiles.fixture("part_upsert.bin")) else { return XCTFail() }
        let part = try XCTUnwrap(p.part)
        XCTAssertEqual(part.name, "Drehknopf")
        try roundTrip("part_upsert.bin", p)
        guard case .part(let r) = try MirrorMessage.decode(WireFiles.fixture("part_remove.bin")) else { return XCTFail() }
        XCTAssertEqual(r.op, .remove)
        XCTAssertEqual(r.name, "Deckel")
        try roundTrip("part_remove.bin", r)

        guard case .meshRequest(let req) = try MirrorMessage.decode(WireFiles.fixture("mesh_req.bin")) else {
            return XCTFail()
        }
        XCTAssertEqual(req.hashes.first, part.hash)
        try roundTrip("mesh_req.bin", req)

        // Netz: Blöcke in beliebiger Reihenfolge, Hash geprüft, Geometrie mit den Anzahlen aus PART
        var assembler = MeshAssembler()
        var done: (hash: String, raw: Data)?
        for file in ["mesh_block_last.bin", "mesh_block_1.bin"] {
            let f = try WireFiles.fixture(file)
            guard case .mesh(let header, let payload) = try MirrorMessage.decode(f) else { return XCTFail(file) }
            XCTAssertEqual(header.hash, part.hash)
            XCTAssertEqual(header.blocks, 2)
            try roundTrip(file, header, payload: payload)
            done = try assembler.add(header, payload: payload) ?? done
        }
        let mesh = try XCTUnwrap(done)
        XCTAssertEqual(mesh.hash, part.hash)
        XCTAssertEqual(mesh.raw.count, part.counts.rawBytes)
        let g = try KcadMesh.geometry(raw: mesh.raw, counts: part.counts)
        XCTAssertEqual(g.triangleCount, part.counts.tri)
        XCTAssertEqual(g.edgeCount, part.counts.edge)
        // Swift packt dasselbe Netz mit gleichem Hash (der gepackte Strom darf sich unterscheiden)
        let repacked = try PackedMesh(geometry: g)
        XCTAssertEqual(repacked.hash, part.hash)
        XCTAssertEqual(try KcadMesh.decompress(repacked.packed, rawSize: repacked.rawBytes), mesh.raw)
        let bodies = PartBodies(name: part.name, geometry: g).bodies(color: part.colorVector)
        XCTAssertEqual(bodies.reduce(0) { $0 + $1.indices.count / 3 }, part.counts.tri)
    }

    func testStateDeltasCamera() throws {
        guard case .state(let s) = try MirrorMessage.decode(WireFiles.fixture("state.bin")) else { return XCTFail() }
        XCTAssertEqual(s.rev, 17)
        XCTAssertEqual(s.state.auswahl.refs.last, "Deckel#f3")
        XCTAssertNil(s.state.isoliert)
        XCTAssertEqual(s.state.schnitt?.axis, "z")
        XCTAssertEqual(s.state.hervorgehoben.first?.color, [1.0, 0.6, 0.0, 1.0])
        XCTAssertEqual(s.state.masse.first?.points.count, 2)
        XCTAssertEqual(s.state.lauf, MirrorRunState(run: 3, laeuft: false))
        try roundTrip("state.bin", s)

        for file in ["state_delta_auswahl.bin", "state_delta_sichtbarkeit.bin", "state_delta_alle_zeigen.bin"] {
            guard case .stateDelta(let d) = try MirrorMessage.decode(WireFiles.fixture(file)) else { return XCTFail(file) }
            XCTAssertEqual(d.change.fieldNames, values(file)["fields"]?.stringList, file)
            XCTAssertEqual(d.quelle.rawValue, values(file)["quelle"]?.stringValue, file)
            try roundTrip(file, d)
        }
        guard case .stateDelta(let all) = try MirrorMessage.decode(WireFiles.fixture("state_delta_alle_zeigen.bin")) else {
            return XCTFail()
        }
        XCTAssertEqual(all.change.isoliert, .some(nil), "isoliert: null ist ausdrücklich gesetzt")

        guard case .camera(let c) = try MirrorMessage.decode(WireFiles.fixture("camera.bin")) else { return XCTFail() }
        XCTAssertEqual(c.kamera.distance, 1800)
        try roundTrip("camera.bin", c)
        // Kamera über den Viewport-Typ hin und zurück
        for (a, b) in zip(MirrorCamera(c.kamera.cameraState).rotation, c.kamera.rotation) {
            XCTAssertEqual(a, b, accuracy: 1e-5)
        }
    }

    func testCommandsAndResults() throws {
        guard case .command(let k) = try MirrorMessage.decode(WireFiles.fixture("cmd_kamera.bin")) else { return XCTFail() }
        XCTAssertEqual(k.knownOp, .kamera)
        XCTAssertEqual(k.prio, .kamera)
        XCTAssertNotNil(k.camera)
        try roundTrip("cmd_kamera.bin", MirrorCommand.kamera(id: k.id, k.camera!))

        guard case .command(let a) = try MirrorMessage.decode(WireFiles.fixture("cmd_auswahl.bin")) else { return XCTFail() }
        XCTAssertEqual(a.refs, values("cmd_auswahl.bin")["refs"]?.stringList)
        XCTAssertEqual(a.args["modus"]?.stringValue, "setzen")
        try roundTrip("cmd_auswahl.bin", MirrorCommand.auswahl(id: a.id, refs: a.refs, run: 3, modus: "setzen"))

        guard case .command(let s) = try MirrorMessage.decode(WireFiles.fixture("cmd_sichtbarkeit.bin")) else {
            return XCTFail()
        }
        try roundTrip("cmd_sichtbarkeit.bin", MirrorCommand.sichtbarkeit(id: s.id, mode: "isolate", refs: s.refs))

        for file in ["cmd_res.bin", "cmd_res_fehler.bin"] {
            guard case .commandResult(let r) = try MirrorMessage.decode(WireFiles.fixture(file)) else { return XCTFail() }
            XCTAssertEqual(r.ok, values(file)["ok"]?.boolValue)
            try roundTrip(file, r)
        }
    }

    func testReceiverWithFixtures() throws {
        var r = MirrorReceiver()
        for file in ["hello_kc.bin", "scene.bin", "state.bin", "part_upsert.bin", "state_delta_sichtbarkeit.bin",
                     "camera.bin"]
        {
            _ = try r.apply(frame: WireFiles.fixture(file))
        }
        XCTAssertEqual(r.epoche, "0123456789abcdef")
        XCTAssertEqual(r.parts.count, 18)
        XCTAssertEqual(r.state?.isoliert?.count, values("state_delta_sichtbarkeit.bin")["isoliert"]?.arrayValue?.count)
        XCTAssertEqual(r.state?.kamera.distance, 1800)
        // Alter Stand wird verworfen
        let stale = try r.apply(frame: WireFiles.fixture("state_delta_auswahl.bin"))
        XCTAssertEqual(r.state?.auswahl.refs, ["Gestell/Bein vorn links", "Deckel#f3"])
        if case .ignored = stale.first {} else { XCTFail("rev 18 nach rev 19 muss verworfen werden") }
        let req = try XCTUnwrap(r.takeMeshRequest())
        let distinct = try XCTUnwrap(values("scene.bin")["hashes"]?.intValue)
        XCTAssertEqual(req.hashes.count, distinct + 1, "alle Netze des Gestells und der Drehknopf")
        XCTAssertNil(r.takeMeshRequest(), "nichts doppelt anfordern")
        for file in ["mesh_block_1.bin", "mesh_block_last.bin"] { _ = try r.apply(frame: WireFiles.fixture(file)) }
        XCTAssertNotNil(try r.geometry(of: XCTUnwrap(r.part("Drehknopf"))))
    }
}
