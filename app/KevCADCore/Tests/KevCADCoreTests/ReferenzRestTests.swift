import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Rest von Phase 4: Abweichung als Farbkarte (REF_DEVIATION, Kurzfassung in REF_LIST, Bänder), Maßstab (REF_SCALE,
/// Werkzeug mit zwei Punkten), Scans vom iPhone (SCAN_LIST, SCAN_IMPORT, Band). Testdateien aus
/// kernel/tools/make_referenz_fixtures.py.
@MainActor
final class ReferenzRestTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("referenz_fixtures.json"))
    }

    private func referenz(_ datei: String) throws -> ReferenzNachricht {
        guard case .referenz(let r) = try Fixtures.message(datei) else {
            throw NSError(domain: "Fixtures", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(datei) keine Referenz"])
        }
        return r
    }

    func testFeldMitNutzlast() throws {
        guard case .abweichung(let f) = try referenz("ref_deviation_modell.frame") else { return XCTFail() }
        let exp = try erwartet()
        XCTAssertEqual(f.referenz, "IMG_5186")
        XCTAssertEqual(f.auf, .modell)
        XCTAssertEqual(f.teil, "Kiste/Korpus")
        XCTAssertEqual(f.feld, "a1b2c3d4e5f6a7b8c9d0")
        XCTAssertEqual(f.run, 7)
        XCTAssertEqual(f.punkte.count, 8)
        XCTAssertEqual(f.dreiecke.count, 36)
        let werte = try XCTUnwrap(exp["ref_deviation_modell_nutzlast"]?["werte"]?.arrayValue)
        for (i, w) in werte.enumerated() {
            if let d = w.doubleValue { XCTAssertEqual(Double(f.werte[i]), d, accuracy: 1e-5) } else {
                XCTAssertTrue(f.werte[i].isNaN, "Punkt \(i) ohne Referenz")
            }
        }
        XCTAssertEqual(try XCTUnwrap(f.kennzahlen.max), 2.0, accuracy: 1e-9)
        XCTAssertEqual(f.kennzahlen.abgedeckt, 0.8, accuracy: 1e-9)
        XCTAssertEqual(try Fixtures.message("ref_deviation_modell.frame").typeName, "REF_DEVIATION")
        guard case .abweichung(let r) = try referenz("ref_deviation_referenz.frame") else { return XCTFail() }
        XCTAssertEqual(r.auf, .referenz)
        XCTAssertNil(r.teil)
        XCTAssertEqual(r.punkte.count, 5)
    }

    func testListeMitAbweichungMassstabUndPhase() throws {
        guard case .liste(let l) = try referenz("ref_list_abweichung.frame") else { return XCTFail() }
        let a = try XCTUnwrap(l[0].abweichung)
        XCTAssertEqual(a.stand, "done")
        XCTAssertEqual(a.skala, 2.0)
        XCTAssertTrue(a.angelegt)
        XCTAssertEqual(a.teile.map(\.teil), ["Kiste/Korpus"])
        XCTAssertEqual(a.schluessel, ["a1b2c3d4e5f6a7b8c9d0", "f0e1d2c3b4a596877869"])
        XCTAssertEqual(try XCTUnwrap(a.referenz?.mittel), 0.9, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(l[0].massstab?.faktor), 1.0125, accuracy: 1e-9)
        XCTAssertEqual(l[0].massstab?.quelle, "punkte")
        XCTAssertTrue(l[1].istScan)
        XCTAssertEqual(l[1].phase, "Tiefe (PromptDA)")
        XCTAssertEqual(l[1].laufText, "Scan wird ausgewertet …")
        XCTAssertNil(l[1].abweichung)
    }

    func testBaenderUndFarben() throws {
        guard case .abweichung(let f) = try referenz("ref_deviation_modell.frame") else { return XCTFail() }
        XCTAssertEqual(AbweichungGeometrie.band(0, skala: 2), 5, "null liegt im mittleren, grünen Band")
        XCTAssertEqual(AbweichungGeometrie.band(-5, skala: 2), 0)
        XCTAssertEqual(AbweichungGeometrie.band(5, skala: 2), 10)
        XCTAssertEqual(AbweichungGeometrie.bandMitte(5), 0, accuracy: 1e-12)
        let gruen = AbweichungGeometrie.farbeSRGB(0)
        XCTAssertGreaterThan(gruen.y, gruen.x)
        XCTAssertGreaterThan(AbweichungGeometrie.farbeSRGB(1).x, 0.8, "positiv (Modell zu klein) ist rot")
        XCTAssertGreaterThan(AbweichungGeometrie.farbeSRGB(-1).z, 0.8, "negativ (Modell zu groß) ist blau")
        let k = AbweichungGeometrie.koerper(f, skala: 2, id: "t")
        XCTAssertFalse(k.isEmpty)
        XCTAssertTrue(k.allSatisfy { $0.id.hasPrefix(AbweichungGeometrie.praefix) && !$0.isPickable })
        XCTAssertTrue(k.contains { $0.id.hasSuffix("\u{1F}g\u{1F}0") }, "Dreiecke ohne Referenz grau")
        // Fläche bleibt erhalten: Summe der Bänder = Fläche des Quaders
        var flaeche: Float = 0
        for b in k {
            for t in 0..<(b.vertexData.count / 18) {
                let v = b.vertexData
                let p = (0..<3).map { j in SIMD3(v[t * 18 + j * 6], v[t * 18 + j * 6 + 1], v[t * 18 + j * 6 + 2]) }
                flaeche += simd_length(simd_cross(p[1] - p[0], p[2] - p[0])) / 2
            }
        }
        XCTAssertEqual(flaeche, 2 * (100 * 60 + 100 * 40 + 60 * 40), accuracy: 1)
    }

    /// Feines Netz wie Kevins Scan (rund 225 000 Dreiecke): Bänder in vertretbarer Zeit, Fläche bleibt.
    func testBaenderGrossesNetz() throws {
        let m = 336
        var punkte: [SIMD3<Float>] = []
        var werte: [Float] = []
        for j in 0...m {
            for i in 0...m {
                let x = Float(i), y = Float(j)
                punkte.append(SIMD3(x, y, 0))
                werte.append(i < 20 ? .nan : 6 * sin(x / 25) * cos(y / 30))
            }
        }
        var dreiecke: [UInt32] = []
        for j in 0..<m {
            for i in 0..<m {
                let a = UInt32(j * (m + 1) + i), b = a + 1, c = a + UInt32(m + 1), d = c + 1
                dreiecke += [a, b, d, a, d, c]
            }
        }
        let f = ReferenzAbweichungFeld(
            referenz: "R", run: 1, auf: .referenz, teil: nil, feld: "x", grenze: 10,
            kennzahlen: ReferenzKennzahlen(json: nil), punkte: punkte, dreiecke: dreiecke, werte: werte)
        let t0 = CFAbsoluteTimeGetCurrent()
        let k = AbweichungGeometrie.koerper(f, skala: 5, id: "gross")
        let dauer = CFAbsoluteTimeGetCurrent() - t0
        print("Farbkarte \(dreiecke.count / 3) Dreiecke: \(Int(dauer * 1000)) ms, \(k.count) Körper")
        XCTAssertLessThan(dauer, 8, "Debug-Bau; im Release-Bau deutlich schneller")
        var flaeche: Double = 0
        for b in k {
            let v = b.vertexData
            for t in 0..<(v.count / 18) {
                let p = (0..<3).map { j in SIMD3(v[t * 18 + j * 6], v[t * 18 + j * 6 + 1], v[t * 18 + j * 6 + 2]) }
                flaeche += Double(simd_length(simd_cross(p[1] - p[0], p[2] - p[0])) / 2)
            }
        }
        XCTAssertEqual(flaeche, Double(m * m), accuracy: 1)
    }

    func testControllerFarbkarteAufDemNetz() throws {
        let c = AppController(model: AppModel())
        c.handle(try Fixtures.message("ref_upsert.frame"))
        c.handle(try Fixtures.message("ref_deviation_referenz.frame"))
        c.handle(try Fixtures.message("ref_deviation_modell.frame"))
        c.handle(try Fixtures.message("ref_list_abweichung.frame"))
        let s = c.model.referenzen
        XCTAssertEqual(s.abweichungFelder.count, 2)
        XCTAssertNotNil(s.abweichungFeld("IMG_5186", .referenz, nil))
        XCTAssertEqual(c.scene.referenzBodies.count, 1, "ohne Farbkarte das halbdurchsichtige Netz")
        c.farbkarteZeigen("IMG_5186", auf: .referenz)
        XCTAssertEqual(s.farbkarteSkala, 2.0)
        XCTAssertTrue(c.scene.referenzBodies.allSatisfy { $0.id.hasPrefix(AbweichungGeometrie.praefix) })
        c.farbkarteSkala(5)
        XCTAssertEqual(s.farbkarteSkala, 5.0)
        // Auf dem Modell: das Teil „Kiste/Korpus“ gibt es in der Szene nicht, also nichts verdeckt
        c.farbkarteZeigen("IMG_5186", auf: .modell)
        XCTAssertTrue(c.scene.referenzVerdeckt.isEmpty)
        // VIEW_CMD des Agenten
        var v = ViewCommandMessage(id: "v-1", cmd: "referenz_abweichung",
                                   args: .object(["name": .string("IMG_5186"), "auf": .string("referenz"), "an": .bool(true)]))
        let (ok, text) = try XCTUnwrap(c.performReferenzCommand(v))
        XCTAssertTrue(ok)
        XCTAssertTrue(text?.contains("auf dem Netz") == true)
        v.args = .object(["an": .bool(false)])
        XCTAssertEqual(c.performReferenzCommand(v)?.0, true)
        XCTAssertNil(s.farbkarte)
        // Neuer Stand ohne die Schlüssel: alte Felder fallen weg
        guard case .liste(var l) = try referenz("ref_list_abweichung.frame") else { return XCTFail() }
        l[0].abweichung?.teile = []
        l[0].abweichung?.referenzFeld = "neu"
        c.handleReferenz(.liste(l))
        XCTAssertTrue(s.abweichungFelder.isEmpty)
    }

    func testMassstabWerkzeug() throws {
        let c = AppController(model: AppModel())
        c.handle(try Fixtures.message("ref_list.frame"))
        c.handle(try Fixtures.message("ref_upsert.frame"))
        let s = c.model.referenzen
        XCTAssertFalse(c.massstabKlick(nil, nil), "ohne Werkzeug geht der Klick an die Auswahl")
        c.massstabWerkzeug("IMG_5186")
        XCTAssertTrue(c.scene.referenzBodies.allSatisfy(\.isPickable), "Netz anklickbar, solange das Werkzeug läuft")
        let id = c.scene.referenzBodies[0].id
        XCTAssertTrue(c.massstabKlick(nil, nil))
        XCTAssertNotNil(s.meldung, "Klick daneben: Hinweis")
        let treffer = try XCTUnwrap(PickResult(rawValue: 0, indexMap: [0: id]))
        XCTAssertTrue(c.massstabKlick(treffer, SIMD3(-90, -51, 0)))
        XCTAssertTrue(c.massstabKlick(treffer, SIMD3(90, -51, 0)))
        XCTAssertEqual(try XCTUnwrap(s.massstabWerkzeug?.abstand), 180, accuracy: 1e-4)
        XCTAssertEqual(c.massstabOverlay().count, 3)  // zwei Punkte und die Maßlinie
        XCTAssertTrue(c.massstabKlick(treffer, SIMD3(0, 0, 0)))
        XCTAssertEqual(s.massstabWerkzeug?.punkte.count, 1, "dritter Punkt beginnt neu")
        c.massstabWerkzeug(nil)
        XCTAssertFalse(c.scene.referenzBodies.contains(where: \.isPickable))
    }

    func testScansUndBand() throws {
        UserDefaults.standard.removeObject(forKey: AppController.scanAusgeblendetKey)
        let c = AppController(model: AppModel())
        guard case .scans(let l) = try referenz("scan_list.frame") else { return XCTFail() }
        XCTAssertEqual(l.scans.count, 2)
        XCTAssertTrue(l.scans[0].neu)
        XCTAssertFalse(l.scans[1].neu)
        XCTAssertEqual(l.scans[1].referenzen.first?.name, "Rollwagen")
        XCTAssertEqual(l.scans[0].empfangenKurz, "22.10. 21:40")
        XCTAssertEqual(l.neu, "2026-10-22_213800_Scan 22.10.")
        XCTAssertTrue(l.empfaengerLaeuft)
        c.handle(try Fixtures.message("scan_list.frame"))
        let s = c.model.referenzen
        XCTAssertEqual(s.neuerScan?.name, "Scan 22.10. 21.38")
        c.scanBandAusblenden("2026-10-22_213800_Scan 22.10.")
        XCTAssertNil(s.neuerScan, "weggeklickt, der Scan bleibt in der Liste")
        XCTAssertEqual(s.scans.count, 2)
        XCTAssertEqual(UserDefaults.standard.stringArray(forKey: AppController.scanAusgeblendetKey),
                       ["2026-10-22_213800_Scan 22.10."])
        UserDefaults.standard.removeObject(forKey: AppController.scanAusgeblendetKey)
    }

    /// Ausgehende Nachrichten wie die Testdateien des Kernels (gleiche Felder und Werte).
    func testAusgehendeNachrichten() throws {
        let exp = try erwartet()
        func kopf<M: OutgoingMessage>(_ m: M) throws -> JSONValue {
            try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        }
        var punkte = ReferenzMassstabMessage(
            id: "a-4", referenz: "IMG_5186", punkte: [SIMD3(-88.9, -50.4, 0), SIMD3(88.9, -50.4, 0)], mm: 180)
        punkte.seq = 4
        let k = try kopf(punkte)
        XCTAssertEqual(k["type"], exp["ref_scale_punkte"]?["type"])
        XCTAssertEqual(k["mm"], exp["ref_scale_punkte"]?["mm"])
        XCTAssertEqual(k["kante"], exp["ref_scale_punkte"]?["kante"])
        let a = try XCTUnwrap(k["punkte"]?.arrayValue?.compactMap(\.doubles))
        let b = try XCTUnwrap(exp["ref_scale_punkte"]?["punkte"]?.arrayValue?.compactMap(\.doubles))
        for (p, q) in zip(a, b) { for i in 0..<3 { XCTAssertEqual(p[i], q[i], accuracy: 1e-4) } }  // Float → Double
        var kante = ReferenzMassstabMessage(id: "a-5", referenz: "IMG_5186", kante: "laenge", mm: 180)
        kante.seq = 5
        XCTAssertEqual(try kopf(kante), exp["ref_scale_kante"])
        var imp = ScanImportMessage(id: "a-6", scan: "2026-10-22_213800_Scan 22.10.", schnell: false)
        imp.seq = 6
        XCTAssertEqual(try kopf(imp), exp["scan_import"])
    }
}
