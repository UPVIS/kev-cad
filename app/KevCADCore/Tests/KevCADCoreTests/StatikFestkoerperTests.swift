import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Statik Stufe 3 (PROTOCOL.md „Festkörper (Stufe 3)“): STATICS mit Festkörper und STATICS_FIELD aus den Testdateien
/// (kernel/tools/make_statik_fixtures.py), Farbverlauf als Bänder, verformter Geist, Teil unter dem Feld verdeckt,
/// Abbruch.
final class StatikFestkoerperTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("statics.json"))
        return try XCTUnwrap(j[name])
    }

    func testFestkoerperUndFeldAusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics_festkoerper.frame") else { return XCTFail() }
        let soll = try erwartet("statics_festkoerper")
        XCTAssertEqual(e.run, soll["run"]?.intValue)
        XCTAssertEqual(e.aktiv, "Haken 2 kg")
        let sz = try XCTUnwrap(e.szenario("Haken 2 kg"))
        let fk = try XCTUnwrap(sz.festkoerper)
        XCTAssertEqual(fk.stand, "done")
        let t = try XCTUnwrap(fk.teile.first)
        XCTAssertEqual(t.teil, "Wandhalter (Druck)")
        XCTAssertEqual(t.ampel, .rot)
        XCTAssertEqual(t.sicherheit, 1.87)
        XCTAssertEqual(t.kriterium, "schicht")
        XCTAssertEqual(t.ausrichtungBeste, "-z")
        XCTAssertEqual(t.ausrichtungen.first?.1, 4.82)
        XCTAssertEqual(t.feld, "d0f84561664942f7ae15")
        XCTAssertEqual(sz.urteile.first?.art, "festkoerper")
        let laeuft = try XCTUnwrap(e.szenario("Aufstützen 30 kg")?.festkoerper)
        XCTAssertTrue(laeuft.laeuft)
        XCTAssertEqual(laeuft.fortschritt, 0.45, accuracy: 1e-9)
        XCTAssertNil(e.szenario("Eigengewicht")?.festkoerper)

        guard case .statikFeld(let f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        let sf = try erwartet("statics_feld")
        XCTAssertEqual(f.run, sf["run"]?.intValue)
        XCTAssertEqual(f.teil, sf["teil"]?.stringValue)
        XCTAssertEqual(f.schluessel, sf["feld"]?.stringValue)
        XCTAssertEqual(f.punkte.count, sf["punkte"]?.intValue)
        XCTAssertEqual(f.dreiecke.count, 3 * (sf["dreiecke"]?.intValue ?? 0))
        XCTAssertEqual(Double(f.ueberhoehung), sf["ueberhoehung"]?.doubleValue ?? 0, accuracy: 1e-5)
        XCTAssertEqual(Double(f.ausnutzung.max() ?? 0), sf["ausnutzung_max"]?.doubleValue ?? 0, accuracy: 1e-5)
        let v1 = sf["verschiebung_1"]?.doubles ?? []
        XCTAssertEqual(f.verschiebung[1], SIMD3<Float>(v1.map(Float.init)))
        XCTAssertEqual(f.ampel, .rot)
        // kaputte Nutzlast
        let frame = try Fixtures.frame("statics_feld.frame")
        XCTAssertThrowsError(try StatikFeld.decode(header: frame.header, payload: frame.payload.dropLast(4)))
    }

    /// Die Bänder decken die Oberfläche genau ab (Fläche bleibt), jedes Band hat eine Farbe der Skala; die Höhenlinie
    /// zwischen Wand (2,1) und Spitze (0) teilt die Längsseiten in 21 Abschnitte.
    func testBaenderUndVerformung() throws {
        guard case .statikFeld(let f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        func flaeche(_ vd: [Float]) -> Float {
            var s: Float = 0
            for t in stride(from: 0, to: vd.count, by: 18) {
                let a = SIMD3(vd[t], vd[t + 1], vd[t + 2]), b = SIMD3(vd[t + 6], vd[t + 7], vd[t + 8])
                let c = SIMD3(vd[t + 12], vd[t + 13], vd[t + 14])
                s += simd_length(simd_cross(b - a, c - a)) / 2
            }
            return s
        }
        let baender = StatikFeldGeometrie.farbverlauf(f, id: "0")
        XCTAssertEqual(baender.count, StatikFeldGeometrie.baender)  // 0 … 2,1 überstreicht alle Bänder
        XCTAssertTrue(baender.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        let soll: Float = 2 * (80 * 20 + 80 * 8 + 20 * 8)
        XCTAssertEqual(baender.map { flaeche($0.vertexData) }.reduce(0, +), soll, accuracy: soll * 1e-4)
        XCTAssertEqual(baender.first?.color.x ?? 0, StatikGeometrie.farbe(0.05).x, accuracy: 1e-5)
        XCTAssertEqual(StatikFeldGeometrie.band(0.05), 0)
        XCTAssertEqual(StatikFeldGeometrie.band(1.0), 10)
        XCTAssertEqual(StatikFeldGeometrie.band(7), 19)
        XCTAssertEqual(StatikFeldGeometrie.band(.nan), 19)
        let geist = StatikFeldGeometrie.verformung(f, id: "0")
        XCTAssertEqual(geist.count, 1)
        XCTAssertLessThan(geist[0].color.w, 1)
        let zMin = stride(from: 2, to: geist[0].vertexData.count, by: 6).map { geist[0].vertexData[$0] }.min() ?? 0
        XCTAssertEqual(zMin, 96 - 2.4 * f.ueberhoehung, accuracy: 1e-3)  // Spitze überhöht abgesenkt
    }

    /// Großes Feld: Körper werden ab 16 000 Dreiecken geteilt (AP0).
    func testGrosseFelderWerdenGeteilt() throws {
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        let n = 20_000
        f.punkte = (0..<(3 * n)).map { i in
            SIMD3(Float(i % 3 == 1 ? 1 : 0), Float(i / 3), Float(i % 3 == 2 ? 1 : 0))
        }
        f.dreiecke = (0..<UInt32(3 * n)).map { $0 }
        f.ausnutzung = Array(repeating: 0.5, count: 3 * n)
        f.verschiebung = Array(repeating: .zero, count: 3 * n)
        let b = StatikFeldGeometrie.farbverlauf(f, id: "x")
        XCTAssertEqual(b.count, 2)
        XCTAssertTrue(b.allSatisfy { $0.indices.count / 3 <= 16_000 })
    }

    @MainActor
    func testControllerZeigtFeldStattTeil() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("part_box.frame"))])  // „Grundplatte“ steht in der Szene
        // STATICS mit Festkörper, Teil umbenannt auf das Teil der Szene
        let kopf = try Fixtures.frame("statics_festkoerper.frame").header
        let text = String(decoding: kopf, as: UTF8.self).replacingOccurrences(of: "Wandhalter (Druck)", with: "Grundplatte")
        let e = try StatikErgebnis.decode(Data(text.utf8))
        c.applyStatik(e)
        let s = c.model.statik
        XCTAssertEqual(s.szenario?.name, "Haken 2 kg")
        XCTAssertTrue(s.farbverlauf)  // zeigen: der Agent will es sehen
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        f.teil = "Grundplatte"
        c.applyStatikFeld(f)
        XCTAssertEqual(s.felder(fuer: try XCTUnwrap(s.szenario)).count, 1)
        XCTAssertEqual(c.scene.statikVerdeckt, ["Grundplatte"])
        XCTAssertFalse(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.isEmpty)
        XCTAssertFalse(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.contains { $0.isVisible })
        XCTAssertTrue(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "f") })
        XCTAssertTrue(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "g") })
        XCTAssertNil(c.scene.statikTints["Grundplatte"])
        // Schnappschuss (Bild): Teil fehlt, Feld ist da
        XCTAssertFalse(c.scene.snapshotBodies().contains { $0.id.contains("Grundplatte") })
        // Farbverlauf aus: Teil wieder sichtbar, nur der Geist bleibt
        c.setStatikFarbverlauf(false)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        XCTAssertTrue(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.allSatisfy { $0.isVisible })
        XCTAssertFalse(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "f") })
        // Feld mit anderem Schlüssel (veraltet): nicht gezeigt
        c.setStatikFarbverlauf(true)
        f.schluessel = "alt"
        c.applyStatikFeld(f)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        // neuer Lauf: Felder verfallen
        f.schluessel = "d0f84561664942f7ae15"
        c.applyStatikFeld(f)
        XCTAssertEqual(c.scene.statikVerdeckt, ["Grundplatte"])
        var neu = e
        neu.run = e.run + 1
        c.applyStatik(neu)
        XCTAssertTrue(s.felder.isEmpty)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        // Abbruch ohne Verbindung: nur eine Warnung, kein Absturz
        c.festkoerperAbbrechen()
    }

    func testAbbruchNachricht() throws {
        let frame = try StatikAbbrechenMessage().frame()
        let j = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        XCTAssertEqual(j["type"]?.stringValue, "STATICS_CANCEL")
    }
}
