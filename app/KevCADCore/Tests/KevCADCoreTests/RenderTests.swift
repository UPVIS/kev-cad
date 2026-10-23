import CoreGraphics
import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Phase 7: Renderings (PROTOCOL.md „Phase 7: Renderings“) gegen die Testdateien des Kernels
/// (kernel/tools/make_render_fixtures.py, render.json), dazu der RealityKit-Renderer an einer kleinen Szene.
final class RenderTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("render.json"))
        return try XCTUnwrap(j[name])
    }

    private func ohneSeq(_ data: Data) throws -> JSONValue {
        var j = try JSONDecoder().decode(JSONValue.self, from: data)
        if case .object(var o) = j {
            o["seq"] = nil
            j = .object(o)
        }
        return j
    }

    // MARK: Kernel → App

    func testRenderAuftragAusTestdatei() throws {
        guard case .render(.auftrag(let a)) = try Fixtures.message("render_req.frame") else { return XCTFail() }
        XCTAssertEqual(a.id, "k-80")
        XCTAssertEqual(a.auftrag, "R-6")
        XCTAssertEqual(a.szene.name, "studio")
        XCTAssertEqual(a.szene.licht, "studio")
        XCTAssertNil(a.szene.umgebung)
        XCTAssertFalse(a.szene.transparent)
        XCTAssertEqual(a.szene.hintergrundFarbe!, SIMD3<Float>(0xF1, 0xF2, 0xF4) / 255)
        XCTAssertEqual(a.ansicht, "aktuell")
        XCTAssertNil(a.kamera)
        XCTAssertEqual(a.width, 1920)
        XCTAssertEqual(a.height, 1080)
        XCTAssertFalse(a.vorschau)
        XCTAssertEqual(a.teile.map(\.name), ["Rahmen/Rohr", "Rahmen/Halter (Druck)", "Kulisse/Boden"])
        XCTAssertEqual(a.teile.map(\.kulisse), [false, false, true])
        let rohr = a.teile[0]
        XCTAssertEqual(rohr.oberflaeche, "eloxiert")
        XCTAssertEqual(rohr.metallisch, 1)
        XCTAssertEqual(rohr.klarlack, 0.35, accuracy: 1e-6)
        XCTAssertEqual(rohr.material, "alu-6060")
        XCTAssertEqual(a.teile[1].oberflaeche, "schichten")
        XCTAssertEqual(a.teile[1].schichthoehe, 0.2, accuracy: 1e-6)
        XCTAssertEqual(a.teile[1].basisfarbe, SIMD3<Float>(0.85, 0.2, 0.15))
        XCTAssertEqual(a.path, try erwartet("render_req")["path"]?.stringValue)

        guard case .render(.auftrag(let h)) = try Fixtures.message("render_req_hdri.frame") else { return XCTFail() }
        XCTAssertEqual(h.szene.licht, "umgebung")
        XCTAssertEqual(h.szene.hintergrund, "umgebung")
        XCTAssertNil(h.szene.hintergrundFarbe)
        XCTAssertEqual(h.szene.drehung, 30)
        XCTAssertEqual(h.kamera, "Kamera/FX6")
        XCTAssertTrue(h.vorschau)
    }

    func testSzeneAnfrageUndStatus() throws {
        guard case .render(.szeneAnfrage(let s)) = try Fixtures.message("render_scene_req.frame") else {
            return XCTFail()
        }
        XCTAssertEqual(s.id, "k-82")
        XCTAssertEqual(s.ansicht, "iso")
        XCTAssertEqual(s.width, 2400)
        XCTAssertEqual(s.kulisse, ["Kulisse/Boden"])
        guard case .render(.status(let l)) = try Fixtures.message("render_status_laeuft.frame") else { return XCTFail() }
        XCTAssertEqual(l.zustand, .laeuft)
        XCTAssertEqual(l.fortschritt, 0.42, accuracy: 1e-9)
        XCTAssertEqual(l.text, "Probe 54 von 128")
        XCTAssertNil(l.pfad)
        XCTAssertEqual(l.von, "app")
        guard case .render(.status(let f)) = try Fixtures.message("render_status_fertig.frame") else { return XCTFail() }
        XCTAssertEqual(f.zustand, .fertig)
        XCTAssertTrue(f.zustand.istEnde)
        XCTAssertEqual(f.ms, 74210)
        XCTAssertEqual(f.pfad, try erwartet("render_status_fertig")["pfad"]?.stringValue)
        guard case .render(.status(let e)) = try Fixtures.message("render_status_fehler.frame") else { return XCTFail() }
        XCTAssertEqual(e.zustand, .fehler)
        XCTAssertTrue(e.fehler?.contains("Blender fehlt") == true)
        XCTAssertEqual(try Fixtures.message("render_status_fehler.frame").typeName, "RENDER_STATUS")
    }

    func testStoreSammeltAuftraegeUndVorschau() {
        MainActor.assumeIsolated {
            let s = RenderStore()
            s.status(RenderStatus(auftrag: "R-1", zustand: .laeuft, fortschritt: 0.3))
            s.status(RenderStatus(auftrag: "R-1", zustand: .fertig, fortschritt: 1, pfad: "/tmp/a.png"))
            s.status(RenderStatus(auftrag: "R-2", zustand: .laeuft, qualitaet: "foto"))
            XCTAssertEqual(s.auftraege.map(\.auftrag), ["R-2", "R-1"])
            XCTAssertEqual(s.laufende.map(\.auftrag), ["R-2"])
            XCTAssertEqual(s.letztesBild?.path, "/tmp/a.png")
            s.status(RenderStatus(auftrag: "R-3", zustand: .fertig, pfad: "/tmp/v.png", vorschau: true))
            XCTAssertEqual(s.vorschauBild?.path, "/tmp/v.png")
            XCTAssertEqual(s.auftraege.count, 2)
            XCTAssertEqual(s.vorschauStand, 1)
            s.groesse = "4k"
            XCTAssertEqual(s.groesseWerte.breite, 3840)
        }
    }

    // MARK: App → Kernel (gleich den Testdateien)

    func testNachrichtenAnDenKernel() throws {
        let start = RenderStartMessage(id: "a-41", szene: "studio", ansicht: "aktuell", kamera: nil, breite: 1920,
                                       hoehe: 1080, qualitaet: "schnell", hintergrund: nil, ziel: nil, vorschau: false)
        XCTAssertEqual(try ohneSeq(start.encodedHeader()), try ohneSeq(Fixtures.frame("render_start.frame").header))
        let foto = RenderStartMessage(id: "a-42", szene: "draussen", ansicht: "produkt", kamera: "Kamera/FX6",
                                      breite: 3840, hoehe: 2160, qualitaet: "foto", hintergrund: "transparent",
                                      ziel: "titel.png")
        XCTAssertEqual(try ohneSeq(foto.encodedHeader()), try ohneSeq(Fixtures.frame("render_start_foto.frame").header))
        let ab = RenderCancelMessage(id: "a-43", auftrag: "R-7")
        XCTAssertEqual(try ohneSeq(ab.encodedHeader()), try ohneSeq(Fixtures.frame("render_cancel.frame").header))

        let kamera = PBRRenderer.Kamera(position: SIMD3(420, -510, 360), ziel: SIMD3(0, 0, 40), oben: SIMD3(0, 0, 1),
                                        fovGrad: 26)
        var kj = kamera.json
        if case .object(var o) = kj {
            o["name"] = .null
            kj = .object(o)
        }
        let res = RenderResponseMessage(
            replyTo: "k-80", ok: true, path: "/Users/kevin/Documents/Kev CAD/Halter/output/renders/Halter_studio_schnell.png",
            width: 1920, height: 1080, ms: 840, kamera: kj,
            phasen: ["netze_ms": 120, "umgebung_ms": 310, "rendern_ms": 330, "png_ms": 80])
        XCTAssertEqual(try ohneSeq(res.encodedHeader()), try ohneSeq(Fixtures.frame("render_res.frame").header))
        let szene = RenderSceneMessage(
            replyTo: "k-82", ok: true, kamera: kj,
            teile: [("Rahmen/Rohr", nil), ("Rahmen/Halter (Druck)", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 25.5, 1])])
        XCTAssertEqual(try ohneSeq(szene.encodedHeader()), try ohneSeq(Fixtures.frame("render_scene.frame").header))
    }

    // MARK: Rechnen ohne Bild

    func testQuaderUVUndLaengsteAchse() {
        // Seitenfläche (Normale Y): u = x, v = z → Schichtlinien quer zu Z
        XCTAssertEqual(PBRRenderer.quaderUV(SIMD3(10, 5, 3), SIMD3(0, 1, 0), laengs: 0), SIMD2(10, 3))
        // Deckfläche: v = 0 (keine Schichtlinien oben)
        XCTAssertEqual(PBRRenderer.quaderUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), laengs: 0, deckeFlach: true).y, 0)
        XCTAssertEqual(PBRRenderer.quaderUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), laengs: 0).y, 5)  // Holz: Maserung oben
        // Teil längs Y: auf der Deckfläche wird y zu u (Faser längs)
        XCTAssertEqual(PBRRenderer.quaderUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), laengs: 1).x, 5)
        let g = Self.quader(SIMD3(0, 0, 0), SIMD3(20, 200, 10))
        XCTAssertEqual(PBRRenderer.laengsteAchse(g), 1)
        let (lo, hi) = PBRRenderer.grenzen(g, Self.verschoben(SIMD3(0, 0, 5)))
        XCTAssertEqual(lo, SIMD3(0, 0, 5))
        XCTAssertEqual(hi, SIMD3(20, 200, 15))
        XCTAssertLessThan(simd_length(PBRRenderer.rk(SIMD3(1000, 2000, 3000)) - SIMD3(1, 3, -2)), 1e-5)
    }

    func testEingepassteKameraZeigtAlles() {
        let b = BoundingBox(min: SIMD3(-100, -50, 0), max: SIMD3(100, 50, 80))
        let k = AppController.eingepasst(blick: simd_normalize(SIMD3(-1, 1, -0.5)), oben: SIMD3(0, 0, 1), fov: 22,
                                         bounds: b, aspekt: 1.5)
        XCTAssertEqual(k.ziel, b.center)
        let r = b.diagonalLength / 2
        let abstand = simd_length(k.position - k.ziel)
        XCTAssertGreaterThan(abstand * sin(11 * .pi / 180), r)  // Hüllkugel passt in die Höhe
        // Blick genau von oben: Oben-Vektor wird ersetzt
        let o = AppController.eingepasst(blick: SIMD3(0, 0, -1), oben: SIMD3(0, 0, 1), fov: 26, bounds: b, aspekt: 1)
        XCTAssertEqual(o.oben, SIMD3(0, 1, 0))
    }

    /// Schichtlinien nach Druckrichtung: v läuft längs der Aufbaurichtung, Deckflächen quer dazu ohne Linien; mit Z wie
    /// bisher (quaderUV mit deckeFlach).
    func testSchichtUVNachDruckrichtung() {
        let z = PBRRenderer.schichtBasis(SIMD3(0, 0, 1))
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(10, 5, 3), SIMD3(0, 1, 0), basis: z).y, 3)  // Seite: v = z
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), basis: z).y, 0)  // Decke: keine Linien
        // stehend gedruckt in −x (Aufbaurichtung +x): auf der Fläche mit Normale y laufen die Linien quer zu x
        let x = PBRRenderer.schichtBasis(SIMD3(1, 0, 0))
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(10, 5, 3), SIMD3(0, 1, 0), basis: x).y, 10)
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), basis: x).y, 10)  // jetzt auch oben
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(10, 5, 3), SIMD3(1, 0, 0), basis: x).y, 0)  // Bettseite: keine
        // Teile schräg: v ist die Höhe längs der Aufbaurichtung
        let s = PBRRenderer.schichtBasis(simd_normalize(SIMD3(1, 0, 1)))
        XCTAssertEqual(PBRRenderer.schichtUV(SIMD3(1, 0, 1), SIMD3(0, 1, 0), basis: s).y, sqrt(2), accuracy: 1e-5)
        // aus der Nachricht: druck_oben normiert
        let pbr = RenderPBR(json: ["name": "H", "basisfarbe": [0.5, 0.5, 0.5], "oberflaeche": "schichten",
                                   "druck_oben": [0, 0, 2]])
        XCTAssertEqual(pbr.druckOben, SIMD3(0, 0, 1))
        XCTAssertNil(RenderPBR(json: ["name": "H"]).druckOben)
    }

    /// Schatten auf dem Boden (CPU, wie die Flächenlichter im Foto): unter dem Würfel dunkel, am Fuß hart, der
    /// Schlagschatten weg vom Licht, weich mit dem Abstand.
    /// Nur zur Sichtprüfung (KEVCAD_RENDER_AUSGABE): Raster des Bodenschattens der Studio-Szene als Graustufenbild.
    func testBodenSchattenRasterBild() throws {
        guard let ordner = ProcessInfo.processInfo.environment["KEVCAD_RENDER_AUSGABE"] else { return }
        var tri: [SIMD3<Float>] = []
        PBRRenderer.dreieckeInWelt(Self.quader(SIMD3(-60, -40, 0), SIMD3(60, 40, 10)), matrix_identity_float4x4, in: &tri)
        PBRRenderer.dreieckeInWelt(Self.quader(SIMD3(-20, -20, 10), SIMD3(20, 20, 50)), matrix_identity_float4x4, in: &tri)
        let t0 = Date()
        let b = try XCTUnwrap(BodenSchatten.rechne(dreiecke: tri, z0: 0, lichter: BodenSchatten.studioLichter
                                                   + [BodenSchatten.kontakt(groesse: 152)]))
        print("Bodenschatten \(b.nx) × \(b.ny), Zelle \(b.zelle) mm, \(Int(Date().timeIntervalSince(t0) * 1000)) ms")
        var px = [UInt8](repeating: 255, count: b.nx * b.ny * 4)
        for j in 0..<b.ny {
            for i in 0..<b.nx {
                let v = UInt8(max(0, min(255, b.hell[j * b.nx + i] * 255)))
                let k = ((b.ny - 1 - j) * b.nx + i) * 4  // y nach oben
                px[k] = v
                px[k + 1] = v
                px[k + 2] = v
            }
        }
        let img = try XCTUnwrap(PBRRenderer.cgImage(px, b.nx, b.ny))
        try XCTUnwrap(PBRRenderer.pngDaten(img)).write(to: URL(fileURLWithPath: ordner).appendingPathComponent("raster.png"))
        print("Ursprung \(b.ursprung), Platte rechts (65, 0): \(b.wert(65, 0)), vorn (0, -45): \(b.wert(0, -45))")
    }

    func testBodenSchattenKontaktUndSchlagschatten() throws {
        // Würfel 100 mm auf dem Boden, Licht schräg von −x oben (45°)
        var tri: [SIMD3<Float>] = []
        PBRRenderer.dreieckeInWelt(Self.quader(SIMD3(-50, -50, 0), SIMD3(50, 50, 100)), matrix_identity_float4x4,
                                   in: &tri)
        let licht = BodenSchatten.Licht(richtung: SIMD3(-1, 0, 1), winkelGrad: 10, gewicht: 1)
        let b = try XCTUnwrap(BodenSchatten.rechne(dreiecke: tri, z0: 0, lichter: [licht], maxZellen: 400))
        XCTAssertLessThan(b.wert(0, 0), 0.05)  // unter dem Würfel
        XCTAssertLessThan(b.wert(80, 0), 0.2)  // Schlagschatten hinter dem Würfel (+x, weg vom Licht)
        XCTAssertGreaterThan(b.wert(-90, 0), 0.95)  // vor dem Würfel zum Licht hin: hell
        XCTAssertGreaterThan(b.wert(0, 120), 0.95)  // seitlich weit weg: hell
        XCTAssertEqual(b.wert(5000, 0), 1)  // außerhalb des Rasters
        // Halbschatten: am Fuß (Würfelkante x = 50, Weg t klein) schmal, am Ende des Schattens (x ≈ 150) breit
        func breite(_ x0: Float) -> Float {  // Abstand von hell (0,9) bis dunkel (0,1) quer zum Schatten bei x0
            var y = Float(0), dunkel: Float = 0, hell: Float = 0
            while y < 200 {
                let v = b.wert(x0, y)
                if v < 0.1 { dunkel = y }
                if v < 0.9 { hell = y }
                y += 0.5
            }
            return hell - dunkel
        }
        XCTAssertLessThan(breite(60), breite(140))
        // Kontaktschatten: nur Flächen dicht über dem Boden, eng um den Fuß
        let k = try XCTUnwrap(BodenSchatten.rechne(dreiecke: tri, z0: 0, lichter: [BodenSchatten.kontakt(groesse: 170)]))
        XCTAssertLessThan(k.wert(52, 0), k.wert(70, 0))
        XCTAssertGreaterThan(k.wert(150, 0), 0.97)
    }

    /// Strahlen der Kamera: perspektivisch vom Auge, parallel alle in Blickrichtung über die sichtbare Höhe verteilt.
    func testKameraStrahlenPerspektiveUndParallel() {
        let p = PBRRenderer.Kamera(position: SIMD3(0, -500, 0), ziel: .zero, oben: SIMD3(0, 0, 1), fovGrad: 30)
        let (o, d) = p.strahl(50, 50, 101, 101)
        XCTAssertEqual(o, SIMD3(0, -500, 0))
        XCTAssertLessThan(simd_length(d - SIMD3(0, 1, 0)), 1e-5)
        let q = PBRRenderer.Kamera(position: SIMD3(0, -500, 0), ziel: .zero, oben: SIMD3(0, 0, 1), fovGrad: 30,
                                   orthoHoehe: 200)
        let (o1, d1) = q.strahl(0, 0, 100, 100)  // oben links
        XCTAssertLessThan(simd_length(d1 - SIMD3(0, 1, 0)), 1e-5)
        XCTAssertEqual(o1.z, 99, accuracy: 0.01)  // halbe Höhe minus halbes Pixel
        XCTAssertEqual(o1.x, -99, accuracy: 0.01)
        if case .object(let j) = q.json {
            XCTAssertEqual(j["projection"], .string("orthographic"))
            XCTAssertEqual(j["ortho_height_mm"]?.doubleValue, 200)
        } else { XCTFail("kein JSON-Objekt") }
        // Orthografische Kamera für eine parallele Ansicht: Auge hinter der Hüllkugel, Ziel bleibt
        let b = BoundingBox(min: SIMD3(-100, -50, 0), max: SIMD3(100, 50, 80))
        let k = AppController.orthoKamera(blick: SIMD3(0, 1, 0), ziel: b.center, oben: SIMD3(0, 0, 1), hoehe: 150,
                                          fovGrad: 30, bounds: b)
        XCTAssertEqual(k.orthoHoehe, 150)
        XCTAssertLessThan(k.position.y, b.min.y)
    }

    func testZusammensetzen() {
        let w = 40, h = 20
        // Schatten links halb so hell
        let s = (0..<(w * h)).map { i -> Float in i % w < w / 2 ? 0.5 : 1 }
        // C: ein deckendes rotes Pixel in der Mitte, sonst leer
        var c = [Float16](repeating: 0, count: w * h * 4)
        let mitte = 10 * w + 20
        c[mitte * 4] = 1
        c[mitte * 4 + 3] = 1
        let weiss = PBRRenderer.zusammensetzen(c: c, schatten: s, hintergrund: .farbe(SIMD3(1, 1, 1)), w: w, h: h)
        XCTAssertEqual(Array(weiss[(10 * w + w - 2) * 4..<(10 * w + w - 2) * 4 + 4]), [255, 255, 255, 255])
        XCTAssertLessThan(weiss[(10 * w + 2) * 4], 230)  // Schatten dunkelt ab
        XCTAssertEqual(Array(weiss[mitte * 4..<mitte * 4 + 4]), [255, 0, 0, 255])
        let frei = PBRRenderer.zusammensetzen(c: c, schatten: s, hintergrund: .durchsichtig, w: w, h: h)
        XCTAssertEqual(frei[(10 * w + w - 2) * 4 + 3], 0)  // ohne Schatten durchsichtig
        XCTAssertGreaterThan(frei[(10 * w + 2) * 4 + 3], 60)  // Schatten halbdurchsichtig schwarz
        XCTAssertEqual(frei[(10 * w + 2) * 4], 0)
        XCTAssertEqual(frei[mitte * 4 + 3], 255)
    }

    // MARK: RealityKit

    @MainActor
    func testRealityKitRendertStudioUndFreisteller() async throws {
        let r = PBRRenderer()
        let teile = [
            PBRRenderer.Teil(name: "Platte", geometry: Self.quader(SIMD3(-60, -40, 0), SIMD3(60, 40, 10)), digest: 1,
                             transform: matrix_identity_float4x4,
                             pbr: RenderPBR(name: "Platte", basisfarbe: SIMD3(0.85, 0.66, 0.49), rauheit: 0.55,
                                            oberflaeche: "holz")),
            PBRRenderer.Teil(name: "Block", geometry: Self.quader(SIMD3(-20, -20, 10), SIMD3(20, 20, 50)), digest: 2,
                             transform: matrix_identity_float4x4,
                             pbr: RenderPBR(name: "Block", basisfarbe: SIMD3(0.83, 0.84, 0.85), metallisch: 1,
                                            rauheit: 0.42, oberflaeche: "eloxiert", klarlack: 0.35)),
        ]
        let b = BoundingBox(min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 50))
        let k = AppController.eingepasst(blick: simd_normalize(SIMD3(-0.6, 0.8, -0.45)), oben: SIMD3(0, 0, 1), fov: 24,
                                         bounds: b, aspekt: 1.6)
        let t0 = Date()
        let e = try await r.render(teile: teile, kamera: k, szene: RenderSzene(), width: 320, height: 200)
        let ms = Date().timeIntervalSince(t0) * 1000
        XCTAssertEqual(e.bild.width, 320)
        XCTAssertTrue(e.png.starts(with: [0x89, 0x50, 0x4E, 0x47]))
        XCTAssertNotNil(e.phasen["rendern_ms"])
        let px = try Self.pixel(e.bild)
        // Ecke oben links: Hintergrundfarbe #F1F2F4
        XCTAssertEqual(Int(px[0]), 0xF1, accuracy: 3)
        XCTAssertEqual(Int(px[2]), 0xF4, accuracy: 3)
        // Mitte: Teil (nicht Hintergrund)
        let m = (100 * 320 + 160) * 4
        XCTAssertFalse(abs(Int(px[m]) - 0xF1) < 4 && abs(Int(px[m + 2]) - 0xF4) < 4, "Mitte zeigt kein Teil")
        // Freisteller: Ecke durchsichtig, Mitte deckend
        let frei = try await r.render(teile: teile, kamera: k, szene: RenderSzene(
            name: "freigestellt", hintergrund: "transparent", transparent: true), width: 320, height: 200)
        let fp = try Self.pixel(frei.bild)
        XCTAssertEqual(fp[3], 0)
        XCTAssertEqual(fp[m + 3], 255)
        print("RealityKit 320 × 200: \(Int(ms)) ms, Phasen \(e.phasen)")
        print("RealityKit, letztes Bild: \(r.letzterBefund)")
        XCTAssertTrue(r.letzterBefund.contains("GPU fertig ja") || r.letzterBefund.contains("gemeldet ja"))
        // Schatten auf dem Boden: rechts hinter dem Block (weg vom Hauptlicht vorn links) dunkler als die Ecke
        XCTAssertNotNil(e.phasen["schatten_ms"])
        // Zur Sichtprüfung: KEVCAD_RENDER_AUSGABE=/pfad schreibt Studio, Freisteller, Draußen und eine Parallelansicht in
        // 1600 × 1000, dazu die Kamera als JSON (Vergleich mit dem Foto aus Blender)
        if let ordner = ProcessInfo.processInfo.environment["KEVCAD_RENDER_AUSGABE"] {
            let url = URL(fileURLWithPath: ordner)
            let gross = try await r.render(teile: teile, kamera: k, szene: RenderSzene(), width: 1600, height: 1000)
            try gross.png.write(to: url.appendingPathComponent("studio.png"))
            print("RealityKit 1600 × 1000 Phasen \(gross.phasen)")
            let fg = try await r.render(teile: teile, kamera: k, szene: RenderSzene(
                name: "freigestellt", hintergrund: "transparent", transparent: true), width: 1600, height: 1000)
            try fg.png.write(to: url.appendingPathComponent("freigestellt.png"))
            let o = AppController.orthoKamera(blick: simd_normalize(SIMD3(-0.6, 0.8, -0.45)), ziel: SIMD3(0, 0, 25),
                                              oben: SIMD3(0, 0, 1), hoehe: 140, fovGrad: 24,
                                              bounds: BoundingBox(min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 50)))
            let og = try await r.render(teile: teile, kamera: o, szene: RenderSzene(), width: 1600, height: 1000)
            try og.png.write(to: url.appendingPathComponent("parallel.png"))
            // hoher Turm auf dem Boden (Schlagschatten deutlich), gleiche Kamera wie im Foto
            let turm = [PBRRenderer.Teil(name: "Turm", geometry: Self.quader(SIMD3(-20, -20, 0), SIMD3(20, 20, 120)),
                                         digest: 21, transform: matrix_identity_float4x4,
                                         pbr: RenderPBR(name: "Turm", basisfarbe: SIMD3(0.8, 0.8, 0.78), rauheit: 0.5))]
            let kt = AppController.eingepasst(blick: simd_normalize(SIMD3(-0.6, 0.8, -0.45)), oben: SIMD3(0, 0, 1),
                                              fov: 24, bounds: BoundingBox(min: SIMD3(-60, -60, 0),
                                                                           max: SIMD3(60, 60, 120)), aspekt: 1.6)
            let tg = try await r.render(teile: turm, kamera: kt, szene: RenderSzene(), width: 1600, height: 1000)
            try tg.png.write(to: url.appendingPathComponent("turm.png"))
            let kameras: JSONValue = .object(["perspektivisch": k.json, "parallel": o.json, "turm": kt.json])
            try JSONEncoder().encode(kameras).write(to: url.appendingPathComponent("kameras.json"))
            if let hdr = ProcessInfo.processInfo.environment["KEVCAD_RENDER_HDR"] {
                let d = try await r.render(teile: teile, kamera: k, szene: RenderSzene(
                    name: "draussen", licht: "umgebung", umgebung: hdr, hintergrund: "umgebung"), width: 1600, height: 1000)
                try d.png.write(to: url.appendingPathComponent("draussen.png"))
            }
        }
    }

    /// Parallele Ansicht echt orthografisch: zwei gleich große Würfel in verschiedener Tiefe sind im Bild gleich groß,
    /// und die sichtbare Höhe stimmt mit `orthoHoehe` (100 mm Würfel bei 200 mm Bildhöhe = halbe Bildhöhe).
    @MainActor
    func testRealityKitOrthografisch() async throws {
        let r = PBRRenderer()
        let pbr = RenderPBR(name: "W", basisfarbe: SIMD3(0.8, 0.3, 0.2), rauheit: 0.6)
        let teile = [
            PBRRenderer.Teil(name: "vorn", geometry: Self.quader(SIMD3(-150, -50, -50), SIMD3(-50, 50, 50)), digest: 11,
                             transform: matrix_identity_float4x4, pbr: pbr),
            PBRRenderer.Teil(name: "hinten", geometry: Self.quader(SIMD3(50, 450, -50), SIMD3(150, 550, 50)),
                             digest: 12, transform: matrix_identity_float4x4, pbr: pbr),
        ]
        let k = PBRRenderer.Kamera(position: SIMD3(0, -1500, 0), ziel: SIMD3(0, 0, 0), oben: SIMD3(0, 0, 1), fovGrad: 30,
                                   orthoHoehe: 200)
        let szene = RenderSzene(name: "freigestellt", hintergrund: "transparent", transparent: true, boden: false)
        let e = try await r.render(teile: teile, kamera: k, szene: szene, width: 400, height: 200)
        let px = try Self.pixel(e.bild)
        // Spalten mit deckenden Pixeln je Hälfte (links der vordere, rechts der hintere Würfel)
        func spalten(_ von: Int, _ bis: Int) -> (Int, Int, Int) {
            var lo = Int.max, hi = -1, zeilen = Set<Int>()
            for y in 0..<200 {
                for x in von..<bis where px[(y * 400 + x) * 4 + 3] > 128 {
                    lo = min(lo, x)
                    hi = max(hi, x)
                    zeilen.insert(y)
                }
            }
            return (lo, hi, zeilen.count)
        }
        let (l0, l1, lh) = spalten(0, 200), (r0, r1, rh) = spalten(200, 400)
        print("Orthografisch: vorn \(l1 - l0 + 1) × \(lh) px, hinten \(r1 - r0 + 1) × \(rh) px")
        XCTAssertEqual(l1 - l0 + 1, 100, accuracy: 3)  // 100 mm bei 1 px/mm
        XCTAssertEqual(lh, 100, accuracy: 3)
        XCTAssertEqual(r1 - r0 + 1, l1 - l0 + 1, accuracy: 2)  // gleich groß trotz 500 mm Tiefe
        XCTAssertEqual(rh, lh, accuracy: 2)
        XCTAssertEqual(l0, 50, accuracy: 3)  // x = −150 mm liegt bei Pixel 50
    }

    // MARK: Hilfen

    static func quader(_ lo: SIMD3<Float>, _ hi: SIMD3<Float>) -> PartGeometry {
        var p: [Float] = [], n: [Float] = [], t: [UInt32] = []
        let flaechen: [(SIMD3<Float>, Int, Float)] = [
            (SIMD3(1, 0, 0), 0, hi.x), (SIMD3(-1, 0, 0), 0, lo.x), (SIMD3(0, 1, 0), 1, hi.y), (SIMD3(0, -1, 0), 1, lo.y),
            (SIMD3(0, 0, 1), 2, hi.z), (SIMD3(0, 0, -1), 2, lo.z),
        ]
        for (normale, achse, wert) in flaechen {
            let o = [0, 1, 2].filter { $0 != achse }
            let basis = UInt32(p.count / 3)
            var ecken: [SIMD3<Float>] = []
            for (a, b) in [(0, 0), (1, 0), (1, 1), (0, 1)] {
                var q = SIMD3<Float>(0, 0, 0)
                q[achse] = wert
                q[o[0]] = a == 0 ? lo[o[0]] : hi[o[0]]
                q[o[1]] = b == 0 ? lo[o[1]] : hi[o[1]]
                ecken.append(q)
                p += [q.x, q.y, q.z]
                n += [normale.x, normale.y, normale.z]
            }
            let richtig = simd_dot(simd_cross(ecken[1] - ecken[0], ecken[2] - ecken[0]), normale) > 0
            t += richtig ? [basis, basis + 1, basis + 2, basis, basis + 2, basis + 3]
                : [basis, basis + 2, basis + 1, basis, basis + 3, basis + 2]
        }
        return PartGeometry(positions: p, normals: n, triangles: t, triFace: [Int32](repeating: 0, count: t.count / 3))
    }

    static func verschoben(_ t: SIMD3<Float>) -> simd_float4x4 {
        var m = matrix_identity_float4x4
        m.columns.3 = SIMD4(t.x, t.y, t.z, 1)
        return m
    }

    static func pixel(_ img: CGImage) throws -> [UInt8] {
        let w = img.width, h = img.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let space = CGColorSpace(name: CGColorSpace.sRGB)!
        px.withUnsafeMutableBytes { buf in
            let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        }
        return px
    }
}

