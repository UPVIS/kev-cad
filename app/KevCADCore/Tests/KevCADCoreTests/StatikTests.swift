import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Statik (PROTOCOL.md Abschnitt „Statik“): STATICS aus den Testdateien (kernel/tools/make_statik_fixtures.py),
/// Farbverlauf und Verformung im Viewer, Auswahl eines Szenarios.
final class StatikTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("statics.json"))
        return try XCTUnwrap(j[name])
    }

    func testStaticsAusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics.frame") else { return XCTFail("kein STATICS") }
        let soll = try erwartet("statics")
        XCTAssertEqual(e.run, soll["run"]?.intValue)
        XCTAssertEqual(e.aktiv, soll["aktiv"]?.stringValue)
        XCTAssertFalse(e.zeigen)
        XCTAssertEqual(e.szenarien.map(\.name), soll["szenarien"]?.arrayValue?.compactMap { $0["name"]?.stringValue })
        XCTAssertEqual(e.ampel, .rot)
        let sz = try XCTUnwrap(e.szenario("Aufstützen 30 kg"))
        XCTAssertEqual(sz.ampel, .rot)
        XCTAssertEqual(sz.urteile.count, 2)
        XCTAssertEqual(sz.auffaellig.first?.ampel, .rot)
        XCTAssertEqual(sz.kennzahlen.sicherheit, 0.2)
        XCTAssertEqual(sz.staebe.first?.punkte.count, 3)
        XCTAssertEqual(sz.staebe.first?.verschiebung.last, SIMD3<Float>(0, 0, -61))
        XCTAssertEqual(sz.teile.map(\.name), ["Rahmen/Rohr", "Rahmen/Halter (Druck)"])
        let eigen = try XCTUnwrap(e.szenario("Eigengewicht"))
        XCTAssertEqual(eigen.kippen.first?.jeRichtung.first?.kippwinkel, 31)
        XCTAssertEqual(eigen.ueberhoehung, 66.7, accuracy: 1e-4)
        XCTAssertEqual(e.grenzen.count, soll["grenzen"]?.intValue)
        guard case .statik(let antwort) = try Fixtures.message("statics_eigengewicht.frame") else { return XCTFail() }
        XCTAssertTrue(antwort.zeigen)
        XCTAssertEqual(antwort.replyTo, "k-12")
        guard case .statik(let fehl) = try Fixtures.message("statics_failed.frame") else { return XCTFail() }
        XCTAssertEqual(fehl.stand, "failed")
        XCTAssertTrue(fehl.szenarien.isEmpty)
    }

    func testFarbverlaufUndVerformung() throws {
        guard case .statik(let e) = try Fixtures.message("statics.frame") else { return XCTFail() }
        let sz = try XCTUnwrap(e.szenario("Aufstützen 30 kg"))
        let nur = StatikGeometrie.koerper(sz, farbverlauf: true, verformung: false)
        XCTAssertEqual(nur.count, 2)  // drei Stationen: zwei Segmente
        XCTAssertTrue(nur.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        // erstes Segment (Ausnutzung 10 → 5): rot; Farben linear
        XCTAssertEqual(nur[0].color.x, StatikGeometrie.farbe(2).x, accuracy: 1e-5)
        let beide = StatikGeometrie.koerper(sz, farbverlauf: true, verformung: true)
        XCTAssertEqual(beide.count, 3)
        let geist = try XCTUnwrap(beide.last)
        XCTAssertLessThan(geist.color.w, 1)
        // Geist mit Überhöhung 1: Spitze 61 mm unter der Ruhelage
        let zMin = stride(from: 2, to: geist.vertexData.count, by: 6).map { geist.vertexData[$0] }.min() ?? 0
        XCTAssertLessThan(zMin, 30 - 61 + 1)
        // Farbe: grün bei 0, gelb bei 1, rot ab 2
        XCTAssertGreaterThan(StatikGeometrie.farbe(0).y, StatikGeometrie.farbe(0).x)
        XCTAssertEqual(StatikGeometrie.farbe(5), StatikGeometrie.farbe(2))
        let toene = StatikGeometrie.toene(sz, bekannt: { $0 == "Rahmen/Rohr" })
        XCTAssertEqual(Array(toene.keys), ["Rahmen/Rohr"])
        let (vd, idx) = StatikGeometrie.rohr([SIMD3(0, 0, 0), SIMD3(100, 0, 0)], radius: 5)
        XCTAssertEqual(vd.count % 6, 0)
        XCTAssertEqual(idx.count % 3, 0)
        XCTAssertTrue(idx.allSatisfy { Int($0) < vd.count / 6 })
    }

    @MainActor
    func testControllerZeigtGewaehltesSzenario() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("statics.frame"))])
        let s = c.model.statik
        XCTAssertEqual(s.szenario?.name, "Aufstützen 30 kg")
        XCTAssertFalse(s.farbverlauf)
        XCTAssertTrue(c.scene.statikBodies.isEmpty)  // nach einem Lauf nichts einfärben, bis Kevin es will
        c.waehleStatikSzenario("Eigengewicht")
        XCTAssertTrue(s.farbverlauf)
        XCTAssertEqual(c.scene.statikBodies.count, 2)
        c.setStatikVerformung(true)
        XCTAssertEqual(c.scene.statikBodies.count, 3)
        c.setStatikFarbverlauf(false)
        c.setStatikVerformung(false)
        XCTAssertTrue(c.scene.statikBodies.isEmpty)
        // Der Agent will ein Szenario sehen: Farbverlauf und Verformung an
        c.handle([.message(try Fixtures.message("statics_eigengewicht.frame"))])
        XCTAssertEqual(s.szenario?.name, "Eigengewicht")
        XCTAssertTrue(s.farbverlauf && s.verformung)
        XCTAssertEqual(c.scene.statikBodies.count, 3)
    }
}
