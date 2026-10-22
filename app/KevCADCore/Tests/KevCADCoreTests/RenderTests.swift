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
        XCTAssertEqual(a.teile.map(\.name), ["Rahmen/Rohr", "Rahmen/Halter (Druck)"])
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
        XCTAssertEqual(PBRRenderer.quaderUV(SIMD3(10, 5, 3), SIMD3(0, 0, 1), laengs: 0).y, 0)
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

    func testSchattenmaskeUndZusammensetzen() {
        let w = 40, h = 20
        // B: heller Boden überall; A: links halb so hell (Schatten)
        var a = [Float16](repeating: 0, count: w * h * 4), b = a
        for i in 0..<(w * h) {
            let x = i % w
            for k in 0..<3 {
                b[i * 4 + k] = 0.8
                a[i * 4 + k] = x < w / 2 ? 0.4 : 0.8
            }
            a[i * 4 + 3] = 1
            b[i * 4 + 3] = 1
        }
        let s = PBRRenderer.schattenmaske(a: a, b: b, w: w, h: h)
        XCTAssertEqual(s[10 * w + 2], 0.5, accuracy: 0.02)
        XCTAssertEqual(s[10 * w + w - 2], 1, accuracy: 0.02)
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
        // Zur Sichtprüfung: KEVCAD_RENDER_AUSGABE=/pfad schreibt Studio und Draußen in 1600 × 1000
        if let ordner = ProcessInfo.processInfo.environment["KEVCAD_RENDER_AUSGABE"] {
            let gross = try await r.render(teile: teile, kamera: k, szene: RenderSzene(), width: 1600, height: 1000)
            try gross.png.write(to: URL(fileURLWithPath: ordner).appendingPathComponent("studio.png"))
            print("RealityKit 1600 × 1000 Phasen \(gross.phasen)")
            if let hdr = ProcessInfo.processInfo.environment["KEVCAD_RENDER_HDR"] {
                let d = try await r.render(teile: teile, kamera: k, szene: RenderSzene(
                    name: "draussen", licht: "umgebung", umgebung: hdr, hintergrund: "umgebung"), width: 1600, height: 1000)
                try d.png.write(to: URL(fileURLWithPath: ordner).appendingPathComponent("draussen.png"))
            }
        }
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

