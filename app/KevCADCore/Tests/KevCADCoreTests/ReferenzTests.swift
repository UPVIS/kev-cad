import CoreGraphics
import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Phase 4: Referenzen. Testdateien aus kernel/tools/make_referenz_fixtures.py, Kamera der Fotoansicht gegen das
/// gerenderte Bild, Verrechnen von Foto und Modell, Netze in der Szene.
@MainActor
final class ReferenzTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("referenz_fixtures.json"))
    }

    private func referenz(_ datei: String) throws -> ReferenzNachricht {
        guard case .referenz(let r) = try Fixtures.message(datei) else {
            throw NSError(domain: "Fixtures", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(datei) keine Referenz"])
        }
        return r
    }

    func testListe() throws {
        guard case .liste(let l) = try referenz("ref_list.frame") else { return XCTFail() }
        XCTAssertEqual(l.count, 2)
        XCTAssertEqual(l[0].name, "IMG_5186")
        XCTAssertEqual(l[0].zustand, .rechnet)
        XCTAssertEqual(l[0].laeuft, "capture")
        XCTAssertEqual(try XCTUnwrap(l[0].fortschritt), 0.42, accuracy: 1e-9)
        XCTAssertEqual(l[0].fotos, 8)
        XCTAssertTrue(l[0].messung)
        XCTAssertFalse(l[0].netz)
        XCTAssertEqual(l[1].art, "fotos")
        XCTAssertEqual(l[1].quelle, "3 Fotos")
        XCTAssertEqual(l[1].zustand, .leer)
        XCTAssertEqual(try Fixtures.message("ref_list.frame").typeName, "REF_LIST")
    }

    func testNetzMitNutzlast() throws {
        guard case .netz(let n) = try referenz("ref_upsert.frame") else { return XCTFail() }
        let exp = try erwartet()
        XCTAssertEqual(n.name, "IMG_5186")
        XCTAssertEqual(n.vertexCount, 5)
        XCTAssertEqual(n.triangleCount, 6)
        let pos = try XCTUnwrap(exp["ref_upsert_nutzlast"]?["positions"]?.arrayValue)
        for (i, p) in pos.enumerated() {
            let d = try XCTUnwrap(p.doubles)
            for k in 0..<3 { XCTAssertEqual(Double(n.positions[i * 3 + k]), d[k], accuracy: 1e-4) }
        }
        let tri = try XCTUnwrap(exp["ref_upsert_nutzlast"]?["triangles"]?.arrayValue).flatMap { $0.doubles ?? [] }
        XCTAssertEqual(n.triangles.map(Double.init), tri)
        XCTAssertEqual(n.farbe.w, 0.45, accuracy: 1e-6)
        XCTAssertEqual(n.bboxMax.z, 47.5, accuracy: 1e-4)
        // Körper für die Szene: nicht anklickbar, Farbe mit Deckkraft
        let k = AppController.referenzKoerper(n, farbe: SIMD4(0.1, 0.2, 0.3, 0.4))
        XCTAssertEqual(k.count, 1)
        XCTAssertFalse(k[0].isPickable)
        XCTAssertEqual(k[0].indices.count, 18)
        XCTAssertTrue(k[0].id.hasPrefix(AppController.referenzKoerperPrefix))
    }

    func testFotosErgebnisEntfernen() throws {
        guard case .fotos(let ref, let satz, let fotos) = try referenz("ref_photos.frame") else { return XCTFail() }
        XCTAssertEqual(ref, "IMG_5186")
        XCTAssertEqual(satz, "messung")
        XCTAssertEqual(fotos.count, 2)
        XCTAssertEqual(fotos[0].kamera.f, 1546.8, accuracy: 1e-9)
        XCTAssertEqual(fotos[0].kamera.breite, 1920)
        XCTAssertNotNil(fotos[0].maske)
        XCTAssertNil(fotos[1].maske)
        XCTAssertEqual(fotos[1].kamera.cx, 951.5, accuracy: 1e-9)
        XCTAssertEqual(fotos[0].titel, "3,7 s")
        // Kamera bei (0, -600, 40) mit Blick +Y (R: x → x, y → −z, z → y)
        let z = fotos[0].kamera.zentrum
        XCTAssertEqual(z.x, 0, accuracy: 1e-9)
        XCTAssertEqual(z.y, -600, accuracy: 1e-9)
        XCTAssertEqual(z.z, 40, accuracy: 1e-9)
        XCTAssertEqual(fotos[0].kamera.blick.y, 1, accuracy: 1e-9)
        XCTAssertEqual(fotos[0].kamera.oben.z, 1, accuracy: 1e-9)

        guard case .ergebnis(let e) = try referenz("ref_result.frame") else { return XCTFail() }
        XCTAssertEqual(e.masse.map(\.name), ["tiefe", "hoehe"])
        XCTAssertEqual(try XCTUnwrap(e.mass("tiefe")?.aenderung), -6.6, accuracy: 1e-9)
        XCTAssertEqual(e.mass("tiefe")?.gerundet, 103.4)
        XCTAssertEqual(e.bekannt["breite"], 180)
        XCTAssertEqual(e.grundkoerperTeil, "Scarlett/Gehaeuse")
        XCTAssertEqual(try XCTUnwrap(e.huelle).y, 118, accuracy: 1e-9)
        XCTAssertEqual(e.empfehlungen.count, 2)
        XCTAssertEqual(e.empfehlungen[0].art, "nachmessen")

        guard case .entfernen(let n) = try referenz("ref_remove.frame") else { return XCTFail() }
        XCTAssertEqual(n, "Fotos Küche")
    }

    /// Ausgehende Nachrichten wie die Testdateien des Kernels (gleiche Felder und Werte).
    func testAusgehendeNachrichten() throws {
        let exp = try erwartet()
        func kopf<M: OutgoingMessage>(_ m: M) throws -> JSONValue {
            try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        }
        var add = ReferenzHinzufuegenMessage(
            id: "a-1", pfade: ["/Users/test/IMG_5186.MOV"], masz: ["laenge": 180], auflage: true)
        add.seq = 1
        XCTAssertEqual(try kopf(add), exp["ref_add"])
        var mess = ReferenzVermessenMessage(id: "a-2", referenz: "IMG_5186", frei: ["tiefe", "hoehe"],
                                            bekannt: ["breite": 180], bilder: 8)
        mess.seq = 2
        XCTAssertEqual(try kopf(mess), exp["ref_measure_req"])
        var apply = ReferenzUebernehmenMessage(id: "a-3", referenz: "IMG_5186", werte: ["tiefe": 103.4, "hoehe": 46.4])
        apply.seq = 3
        XCTAssertEqual(try kopf(apply), exp["ref_apply"])
    }

    func testLeinwandUndVerrechnen() {
        let mitte = ReferenzKamera(R: [SIMD3(1, 0, 0), SIMD3(0, 1, 0), SIMD3(0, 0, 1)], t: .zero, f: 1000, cx: 960,
                                   cy: 540, breite: 1920, hoehe: 1080)
        XCTAssertEqual(FotoAbgleich.leinwand(mitte), FotoAbgleich.Leinwand(breite: 1920, hoehe: 1080, x0: 0, y0: 0))
        var schief = mitte
        schief.cx = 900
        schief.cy = 560
        let l = FotoAbgleich.leinwand(schief)
        XCTAssertEqual(l.breite, 2040)  // 2 · (1920 − 900)
        XCTAssertEqual(l.hoehe, 1120)  // 2 · 560
        XCTAssertEqual(l.x0, 120)  // Hauptpunkt in der Mitte der Leinwand: 1020 − 900
        XCTAssertEqual(l.y0, 0)

        // 4 Pixel: nur Foto, nur Modell, beide, keins
        let foto: [UInt8] = [100, 100, 100, 255, 100, 100, 100, 255, 100, 100, 100, 255, 100, 100, 100, 255]
        let modell: [UInt8] = [0, 0, 0, 255, 200, 0, 0, 255, 200, 0, 0, 255, 0, 0, 0, 255]
        let deckung: [UInt8] = [0, 255, 255, 0]
        let maske: [UInt8] = [255, 0, 255, 0]
        let ueber = FotoAbgleich.verrechnen(foto: foto, deckung: deckung, modell: modell, maske: maske, deckkraft: 1,
                                            modus: .ueberlagern)
        XCTAssertEqual(Array(ueber.pixel[0..<3]), [100, 100, 100])  // ohne Modell bleibt das Foto
        XCTAssertEqual(Array(ueber.pixel[4..<7]), [200, 0, 0])  // Modell deckend
        XCTAssertEqual(try XCTUnwrap(ueber.ueberdeckung), 1.0 / 3.0, accuracy: 1e-9)
        let halb = FotoAbgleich.verrechnen(foto: foto, deckung: deckung, modell: modell, maske: maske, deckkraft: 0.5,
                                           modus: .ueberlagern)
        XCTAssertEqual(Array(halb.pixel[4..<7]), [150, 50, 50])
        let diff = FotoAbgleich.verrechnen(foto: foto, deckung: deckung, modell: modell, maske: maske, deckkraft: 1,
                                           modus: .differenz)
        XCTAssertGreaterThan(diff.pixel[0], diff.pixel[2])  // rot: nur im Foto
        XCTAssertGreaterThan(diff.pixel[6], diff.pixel[4])  // blau: nur im Modell
        XCTAssertEqual(diff.pixel[8], diff.pixel[10])  // beide: grau
        XCTAssertEqual(diff.pixel[12], diff.pixel[14])
    }

    /// Die Kamera der Fotoansicht rendert genau dorthin, wohin die OpenCV-Kamera projiziert (auch mit Hauptpunkt
    /// außerhalb der Mitte): Ecken der Kiste aus part_box gegen die Deckung im gerenderten Bild.
    func testKameraTrifftDasGerenderteBild() throws {
        let s = SceneStore()
        s.upsert(try Fixtures.record("part_box.frame"), flash: false)
        let box = try XCTUnwrap(s.visibleBounds())
        let mitte = (box.min + box.max) / 2
        // Kamera schräg von vorne oben, Blick auf die Mitte
        let c = SIMD3<Double>(Double(mitte.x) + 60, Double(mitte.y) - 220, Double(mitte.z) + 140)
        let vorn = simd_normalize(SIMD3<Double>(Double(mitte.x), Double(mitte.y), Double(mitte.z)) - c)
        let rechts = simd_normalize(simd_cross(vorn, SIMD3(0, 0, 1)))
        let unten = simd_cross(vorn, rechts)
        let R = [rechts, unten, vorn]
        let t = -SIMD3(simd_dot(R[0], c), simd_dot(R[1], c), simd_dot(R[2], c))
        let k = ReferenzKamera(R: R, t: t, f: 700, cx: 300, cy: 230, breite: 640, hoehe: 400)
        let l = FotoAbgleich.leinwand(k)
        let zustand = FotoAbgleich.kameraZustand(k, hoehe: l.hoehe)
        let r = ScreenshotRenderer()
        func pixel(_ grund: SIMD4<Float>) -> [UInt8]? {
            r.backgroundColor = grund
            guard let b = r.render(bodies: s.snapshotBodies(), camera: zustand, width: l.breite, height: l.hoehe,
                                   displayMode: .shaded),
                let teil = FotoAbgleich.ausschnitt(b.image, l, breite: k.breite, hoehe: k.hoehe)
            else { return nil }
            return FotoAbgleich.pixel(teil, breite: k.breite, hoehe: k.hoehe)
        }
        guard let weiss = pixel(SIMD4(1, 1, 1, 1)), let schwarz = pixel(SIMD4(0, 0, 0, 1)) else {
            throw XCTSkip("Kein Metal-Gerät für den OffscreenRenderer")
        }
        let d = FotoAbgleich.deckung(weiss: weiss, schwarz: schwarz)
        var lo = SIMD2<Double>(1e9, 1e9), hi = SIMD2<Double>(-1e9, -1e9)
        for y in 0..<k.hoehe {
            for x in 0..<k.breite where d[y * k.breite + x] >= 128 {
                lo = simd_min(lo, SIMD2(Double(x), Double(y)))
                hi = simd_max(hi, SIMD2(Double(x + 1), Double(y + 1)))
            }
        }
        var plo = SIMD2<Double>(1e9, 1e9), phi = SIMD2<Double>(-1e9, -1e9)
        for i in 0..<8 {
            let p = SIMD3<Double>(Double(i & 1 == 0 ? box.min.x : box.max.x), Double(i & 2 == 0 ? box.min.y : box.max.y),
                                  Double(i & 4 == 0 ? box.min.z : box.max.z))
            let (u, _) = k.projiziere(p)
            plo = simd_min(plo, u)
            phi = simd_max(phi, u)
        }
        XCTAssertGreaterThan(hi.x - lo.x, 30, "Kiste ist im Bild zu sehen")
        for (a, b) in [(lo.x, plo.x), (lo.y, plo.y), (hi.x, phi.x), (hi.y, phi.y)] {
            XCTAssertEqual(a, b, accuracy: 2.5, "Ecke der Kiste: gerendert \(a), projiziert \(b)")
        }
    }

    func testControllerPflegtStoreUndSzene() throws {
        let c = AppController(model: AppModel())
        c.handle(try Fixtures.message("ref_list.frame"))
        c.handle(try Fixtures.message("ref_upsert.frame"))
        XCTAssertEqual(c.model.referenzen.referenzen.count, 2)
        XCTAssertEqual(c.scene.referenzBodies.count, 1)
        XCTAssertTrue(c.scene.renderBodies.contains { $0.id.hasPrefix(AppController.referenzKoerperPrefix) })
        c.referenzNetzZeigen("IMG_5186", false)
        XCTAssertTrue(c.scene.referenzBodies.isEmpty)
        c.referenzNetzZeigen("IMG_5186", true)
        c.referenzNetzDeckkraft("IMG_5186", 0.8)
        XCTAssertEqual(c.scene.referenzBodies[0].color.w, 0.8, accuracy: 1e-6)
        c.handle(try Fixtures.message("ref_photos.frame"))
        c.handle(try Fixtures.message("ref_result.frame"))
        XCTAssertEqual(c.model.referenzen.fotos("IMG_5186").count, 2)
        XCTAssertEqual(c.model.referenzen.ergebnisse["IMG_5186"]?.masse.count, 2)
        c.handle(try Fixtures.message("ref_remove.frame"))  // „Fotos Küche“ hatte kein Netz
        XCTAssertEqual(c.scene.referenzBodies.count, 1)
        // Liste ohne die Referenz: Netz, Fotos und Ergebnis verschwinden
        c.handleReferenz(.liste([]))
        XCTAssertTrue(c.scene.referenzBodies.isEmpty)
        XCTAssertTrue(c.model.referenzen.fotos.isEmpty)
        XCTAssertNil(c.model.referenzen.ergebnisse["IMG_5186"])
    }
}
