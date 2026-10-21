import Foundation
import XCTest
import simd

@testable import KevCADCore

/// Prüfung: CHECK dekodieren (Testdateien aus kernel/tools/make_pruef_fixtures.py), Band, rote Teile, Schnittkörper.
@MainActor
final class PruefungTests: XCTestCase {
    func testCheckFixture() throws {
        guard case .check(let msg) = try Fixtures.message("check_done.frame") else { return XCTFail("kein CHECK") }
        let exp = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("check.json"))
        let e = msg.ergebnis
        XCTAssertEqual(e.run, exp["run"]?.intValue)
        XCTAssertEqual(e.zustand, .done)
        XCTAssertEqual(e.zusammenfassung, "1 Durchdringung")
        XCTAssertEqual(e.bandText, "1 Durchdringung")
        XCTAssertEqual(e.fehler, 1)
        XCTAssertEqual(e.dauerMs, 12.5)
        let b = try XCTUnwrap(e.befunde.first)
        XCTAssertEqual(b.id, "du1")
        XCTAssertEqual(b.art, "durchdringung")
        XCTAssertEqual(b.teile, ["Halter/Block A", "Halter/Block B"])
        XCTAssertEqual(b.schwere, .fehler)
        XCTAssertEqual(b.geometrie, 0)
        XCTAssertEqual(b.werte["volumen"], exp["volumen"]?.doubleValue)
        XCTAssertEqual(b.ort, SIMD3<Float>(4, 0, 0))
        XCTAssertFalse(b.text.isEmpty)
        XCTAssertFalse(b.loesung.isEmpty)
        XCTAssertEqual(e.offen.map(\.id), ["du1"])
        XCTAssertEqual(e.betroffeneTeile, ["Halter/Block A", "Halter/Block B"])
        let g = try XCTUnwrap(e.geometrie.first)
        XCTAssertEqual(g.befund, "du1")
        XCTAssertEqual(g.vertexCount, exp["geometrie"]?.arrayValue?.first?["vert"]?.intValue)
        XCTAssertEqual(g.triangleCount, exp["geometrie"]?.arrayValue?.first?["tri"]?.intValue)
        XCTAssertEqual(g.normals.count, g.positions.count)
        XCTAssertEqual(Array(g.positions.prefix(3)), exp["erste_position"]?.doubles?.map(Float.init))
        XCTAssertTrue(g.triangles.allSatisfy { Int($0) < g.vertexCount })

        guard case .check(let laeuft) = try Fixtures.message("check_running.frame") else { return XCTFail() }
        XCTAssertEqual(laeuft.ergebnis.zustand, .running)
        XCTAssertEqual(laeuft.ergebnis.run, 4)
        XCTAssertTrue(laeuft.ergebnis.befunde.isEmpty)
        XCTAssertEqual(laeuft.ergebnis.bandText, "")
        XCTAssertEqual(KernelMessage.check(laeuft).typeName, "CHECK")
    }

    func testKaputteNutzlastWirdAbgelehnt() throws {
        let frame = try Fixtures.frame("check_done.frame")
        XCTAssertThrowsError(try CheckMessage.decode(frame.header, payload: frame.payload.dropLast(4)))
        XCTAssertThrowsError(try CheckMessage.decode(frame.header, payload: frame.payload + Data([0, 0, 0, 0])))
    }

    private func check(_ run: Int, _ state: String, befunde: [JSONValue], geo: [(Int, Int)] = [], payload: Data = Data())
        throws -> KernelMessage
    {
        let header: JSONValue = [
            "type": "CHECK", "run": .number(Double(run)), "state": .string(state), "zusammenfassung": "",
            "befunde": .array(befunde),
            "geometrie": .array(geo.map { ["befund": "du1", "vert": .number(Double($0.0)), "tri": .number(Double($0.1))] }),
        ]
        return try KernelMessage.decode(Frame(header: JSONEncoder().encode(header), payload: payload))
    }

    /// Ein Dreieck als Nutzlast: 3 Punkte, 3 Normalen, 1 Dreieck.
    private var dreieck: Data {
        var d = Data()
        for f: Float in [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1] {
            withUnsafeBytes(of: f.bitPattern.littleEndian) { d.append(contentsOf: $0) }
        }
        for i: UInt32 in [0, 1, 2] { withUnsafeBytes(of: i.littleEndian) { d.append(contentsOf: $0) } }
        return d
    }

    func testControllerMarkiertTeileUndZeigtSchnittkoerper() throws {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))  // HELLO … beide Teile, RUN_END
        XCTAssertNotNil(c.scene.record("Grundplatte"))
        let befund: JSONValue = [
            "id": "du1", "art": "durchdringung", "teile": ["Grundplatte", "Halter/Bolzen"], "schwere": "fehler",
            "wert": ["volumen": 12.5, "tiefe": 0.5], "ort": [5, 0, 0], "text": "Grundplatte und Halter/Bolzen …",
            "loesung": "verschieben", "geometrie": 0,
        ]
        c.handle([.message(try check(1, "done", befunde: [befund], geo: [(3, 1)], payload: dreieck))])
        let p = try XCTUnwrap(c.model.pruefung)
        XCTAssertEqual(p.bandText, "1 Befund")  // ohne Zusammenfassung aus den Befunden gezählt
        XCTAssertEqual(c.scene.inventoryWarnings, ["Grundplatte", "Halter/Bolzen"])
        XCTAssertEqual(c.scene.ghostBodies.count, 1)
        XCTAssertFalse(c.scene.ghostBodies[0].isPickable)
        XCTAssertTrue(c.scene.renderBodies.contains { $0.id == c.scene.ghostBodies[0].id })
        XCTAssertTrue(c.scene.snapshotBodies().contains { $0.id == c.scene.ghostBodies[0].id })
        // Ausblenden und wieder an
        c.setSchnittkoerperSichtbar(false)
        XCTAssertTrue(c.scene.ghostBodies.isEmpty)
        c.setSchnittkoerperSichtbar(true)
        XCTAssertEqual(c.scene.ghostBodies.count, 1)
        // Befund anklicken: Teile ausgewählt
        c.zeigeBefund(p.befunde[0])
        XCTAssertEqual(Set(c.model.selection.map(\.ref)), ["Grundplatte", "Halter/Bolzen"])
        // neuer Lauf: Befunde bleiben stehen, bis das Ergebnis da ist
        c.handle([.message(try check(2, "running", befunde: []))])
        XCTAssertEqual(c.model.pruefung?.laeuft, true)
        XCTAssertEqual(c.model.pruefung?.befunde.count, 1)
        // behoben: nichts mehr rot, keine Schnittkörper
        c.handle([.message(try check(2, "done", befunde: []))])
        XCTAssertEqual(c.model.pruefung?.laeuft, false)
        XCTAssertTrue(c.scene.inventoryWarnings.isEmpty)
        XCTAssertTrue(c.scene.ghostBodies.isEmpty)
    }
}
