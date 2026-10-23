import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Topologie (PROTOCOL.md „Topologie“): TOPO und TOPO_FIELD aus den Testdateien (kernel/tools/make_topologie_fixtures.py),
/// Anfragen der App, Körper im Viewer (Dichte halbdurchsichtig, Teil blass; nachher Spannungsfarben, Teil verdeckt).
final class TopologieTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("topo.json"))
        return try XCTUnwrap(j[name])
    }

    func testStandAusTestdatei() throws {
        guard case .topologie(let s) = try Fixtures.message("topo.frame") else { return XCTFail() }
        let soll = try erwartet("topo")
        XCTAssertEqual(s.run, soll["run"]?.intValue)
        XCTAssertTrue(s.fertig)
        XCTAssertEqual(s.teil, soll["teil"]?.stringValue)
        XCTAssertEqual(s.auftrag, soll["auftrag"]?.intValue)
        XCTAssertEqual(s.behalten, soll["behalten"]?.doubleValue ?? 0, accuracy: 1e-9)
        XCTAssertEqual(s.ersparnisProzent ?? 0, soll["ersparnis"]?.doubleValue ?? -1, accuracy: 1e-9)
        XCTAssertEqual(s.nachher.sicherheit ?? 0, soll["sicherheit_nachher"]?.doubleValue ?? -1, accuracy: 1e-9)
        XCTAssertEqual(s.nachher.ampel.rawValue, soll["ampel_nachher"]?.stringValue)
        XCTAssertEqual(s.datei, soll["datei"]?.stringValue)
        XCTAssertEqual(s.zonen.count, soll["zonen"]?.intValue)
        XCTAssertEqual(s.verlauf.count, soll["verlauf"]?.intValue)
        XCTAssertEqual(s.verlauf.first?.c ?? 0, 1, accuracy: 1e-9)  // relativ zur ersten Iteration
        XCTAssertFalse(s.imModell)

        guard case .topologie(let l) = try Fixtures.message("topo_laeuft.frame") else { return XCTFail() }
        XCTAssertTrue(l.laeuft)
        XCTAssertEqual(l.fortschritt, try erwartet("topo_laeuft")["fortschritt"]?.doubleValue ?? 0, accuracy: 1e-9)
        XCTAssertEqual(l.iteration, 12)
        XCTAssertNil(l.nachher.sicherheit)
    }

    func testFelderAusTestdatei() throws {
        guard case .topologieFeld(let n) = try Fixtures.message("topo_feld_nachher.frame") else { return XCTFail() }
        let soll = try erwartet("topo_feld_nachher")
        XCTAssertEqual(n.art, .nachher)
        XCTAssertEqual(n.punkte.count, soll["punkte"]?.intValue)
        XCTAssertEqual(n.dreiecke.count, 3 * (soll["dreiecke"]?.intValue ?? 0))
        let f = try XCTUnwrap(n.feld)
        XCTAssertEqual(f.ausnutzung.count, n.punkte.count)
        XCTAssertEqual(f.verschiebung.count, n.punkte.count)
        guard case .topologieFeld(let d) = try Fixtures.message("topo_feld_dichte.frame") else { return XCTFail() }
        XCTAssertEqual(d.art, .dichte)
        XCTAssertEqual(d.iteration, 12)
        XCTAssertNil(d.feld)
        XCTAssertEqual(d.punkte.count, try erwartet("topo_feld_dichte")["punkte"]?.intValue)
        // kaputte Nutzlast
        let frame = try Fixtures.frame("topo_feld_dichte.frame")
        XCTAssertThrowsError(try TopologieFeld.decode(header: frame.header, payload: frame.payload.dropLast(4)))
    }

    func testAnfragenDerApp() throws {
        let start = TopologieStartMessage(teil: "Halter", szenario: nil, behalten: 0.42, ueberhang: true, fein: false)
        let j = try JSONDecoder().decode(JSONValue.self, from: try start.frame().header)
        XCTAssertEqual(j["type"]?.stringValue, "TOPO_START")
        XCTAssertEqual(j["teil"]?.stringValue, "Halter")
        XCTAssertEqual(j["behalten"]?.doubleValue ?? 0, 0.42, accuracy: 1e-12)
        XCTAssertEqual(j["ueberhang"]?.boolValue, true)
        XCTAssertNil(j["szenario"])
        XCTAssertNil(j["lager"])
        let mitLager = TopologieStartMessage(teil: "Halter", szenario: nil, behalten: 0.4, ueberhang: false,
                                             fein: false, lager: "bohrungen")
        let jl = try JSONDecoder().decode(JSONValue.self, from: try mitLager.frame().header)
        XCTAssertEqual(jl["lager"]?.stringValue, "bohrungen")
        let ab = try JSONDecoder().decode(JSONValue.self, from: try TopologieAbbrechenMessage().frame().header)
        XCTAssertEqual(ab["type"]?.stringValue, "TOPO_CANCEL")
        let ue = try JSONDecoder().decode(JSONValue.self, from: try TopologieUebernehmenMessage().frame().header)
        XCTAssertEqual(ue["type"]?.stringValue, "TOPO_APPLY")
    }

    /// Netzkörper: eine Farbe, je Dreieck drei Punkte mit Normale, nicht anklickbar.
    @MainActor
    func testNetzKoerper() throws {
        guard case .topologieFeld(let d) = try Fixtures.message("topo_feld_dichte.frame") else { return XCTFail() }
        let k = AppController.netzKoerper(d, id: "d", farbe: AppController.dichteFarbe)
        XCTAssertEqual(k.count, 1)
        let b = try XCTUnwrap(k.first)
        XCTAssertEqual(b.vertexData.count, d.dreiecke.count * 6)
        XCTAssertFalse(b.isPickable)
        XCTAssertLessThan(b.color.w, 1)  // halbdurchsichtig
    }

    /// Szene: Teil blass (Dichte läuft) bzw. verdeckt (nachher), Körper obenauf, nicht in der Animation.
    @MainActor
    func testSzeneVerdecktUndBlass() throws {
        let scene = SceneStore()
        guard case .topologieFeld(let d) = try Fixtures.message("topo_feld_dichte.frame") else { return XCTFail() }
        let k = AppController.netzKoerper(d, id: "d", farbe: AppController.dichteFarbe)
        scene.setTopologie(bodies: k, verdeckt: [], blass: ["Halter"])
        XCTAssertEqual(scene.topologieBodies.count, 1)
        XCTAssertTrue(scene.renderBodies.contains { $0.id == k[0].id })
        scene.setTopologie(bodies: [], verdeckt: ["Halter"], blass: [])
        XCTAssertTrue(scene.istTopologieVerdeckt("Halter"))
        scene.setTopologie(bodies: [], verdeckt: [], blass: [])
        XCTAssertTrue(scene.topologieBodies.isEmpty)
        XCTAssertFalse(scene.istTopologieVerdeckt("Halter"))
    }
}
