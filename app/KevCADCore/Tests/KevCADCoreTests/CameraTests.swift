import AppKit
import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Phase 5, Strang KAM: Kamera-Nachrichten, Bildwinkel der Kameraansicht, Kamerabild, Ausblenden, Vorschlag.
@MainActor
final class CameraTests: XCTestCase {
    private func cameraFixtures() throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("camera_fixtures.json"))
    }

    private func camera(_ file: String) throws -> CameraInfo {
        guard case .camera(.upsert(let c)) = try Fixtures.message(file) else {
            throw NSError(domain: "Fixtures", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(file) kein CAMERA_UPSERT"])
        }
        return c
    }

    // MARK: Decoder

    func testDecodeCameraMessages() throws {
        let exp = try cameraFixtures()
        let c = try camera("camera_upsert.frame")
        let e = try XCTUnwrap(exp["camera_upsert"])
        XCTAssertEqual(c.name, "Kamera/FX6")
        XCTAssertEqual(c.displayName, "FX6")
        XCTAssertEqual(c.kameraID, "sony-fx6")
        XCTAssertEqual(c.objektivID, "sigma-ff-hs-35-t1.5-e")
        XCTAssertEqual(c.formatID, "ff-uhd")
        XCTAssertEqual(c.aufloesung, SIMD2(3840, 2160))
        XCTAssertEqual(c.sensorMM.x, 35.7, accuracy: 1e-9)
        XCTAssertEqual(c.bildwinkelH, try XCTUnwrap(e["bildwinkel_h"]?.doubleValue), accuracy: 1e-9)
        XCTAssertEqual(c.bildwinkelV, try XCTUnwrap(e["bildwinkel_v"]?.doubleValue), accuracy: 1e-9)
        XCTAssertEqual(c.sensorPos, SIMD3(250, 0, 235))
        XCTAssertEqual(c.auge, SIMD3(285, 0, 235))
        XCTAssertEqual(c.blick, SIMD3(1, 0, 0))
        XCTAssertEqual(c.blendenart, "t")
        XCTAssertEqual(c.blendeText, "T2,8")
        XCTAssertEqual(c.fokus, 1500)
        XCTAssertEqual(c.teil, "Wagen")
        XCTAssertEqual(c.ausblenden, ["Kamera FX6/Objektiv"])
        XCTAssertEqual(c.objektivVorne, 139, accuracy: 1e-9)
        XCTAssertEqual(c.schaerfeText, "1,38 m – 1,65 m")
        XCTAssertFalse(c.vignettierung)

        let b = try camera("camera_upsert_b.frame")
        XCTAssertEqual(b.formatID, "ff-dci")
        XCTAssertNil(b.fokus)  // unendlich
        XCTAssertEqual(b.fokusText, "∞")
        XCTAssertEqual(b.seitenverhaeltnis, 4096.0 / 2160.0, accuracy: 1e-4)
        XCTAssertEqual(simd_length(b.blick), 1, accuracy: 1e-5)
        XCTAssertEqual(simd_dot(b.blick, b.oben), 0, accuracy: 1e-5)

        guard case .camera(.remove(let name)) = try Fixtures.message("camera_remove.frame") else { return XCTFail() }
        XCTAssertEqual(name, "Kamera/B")
        XCTAssertEqual(try Fixtures.message("camera_remove.frame").typeName, "CAMERA_REMOVE")

        guard case .viewCommand(let v) = try Fixtures.message("view_cmd_camera.frame") else { return XCTFail() }
        XCTAssertEqual(v.cmd, "camera_view")
        XCTAssertEqual(v.args["name"]?.stringValue, "Kamera/FX6")
        guard case .screenshotRequest(let s) = try Fixtures.message("screenshot_req_camera.frame") else { return XCTFail() }
        XCTAssertEqual(s.source, "camera")
        XCTAssertEqual(s.camera, "Kamera/FX6")
        XCTAssertEqual(s.width, 1920)
        XCTAssertEqual(s.height, 1080)
        XCTAssertTrue(s.hideOverlays)
        // ältere Anfragen ohne Kamera
        guard case .screenshotRequest(let old) = try Fixtures.message("screenshot_req.frame") else { return XCTFail() }
        XCTAssertNil(old.camera)
    }

    func testSuggestMessageEncodes() throws {
        let m = CameraSuggestMessage(
            name: "Kamera/FX6", sensorPos: SIMD3(1, 2, 3), auge: SIMD3(36, 2, 3), blick: SIMD3(1, 0, 0),
            oben: SIMD3(0, 0, 1), rechts: SIMD3(0, -1, 0), roll: 5)
        let json = try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        XCTAssertEqual(json["type"]?.stringValue, "CAMERA_SUGGEST")
        XCTAssertEqual(json["sensor_pos"]?.doubles, [1, 2, 3])
        XCTAssertEqual(json["roll"]?.doubleValue, 5)
    }

    // MARK: Bildwinkel

    /// Die Bildfeld-Ecken der Kamera (in beliebigem Abstand) landen genau auf den Ecken des Formatrahmens, für breite,
    /// quadratische und hohe Viewports: Der Öffnungswinkel des Viewports stimmt also exakt mit der Kamera.
    func testViewportAngleMatchesCamera() throws {
        for file in ["camera_upsert.frame", "camera_upsert_b.frame"] {
            let c = try camera(file)
            for size in [CGSize(width: 1600, height: 1000), CGSize(width: 1000, height: 1000), CGSize(width: 800, height: 1400),
                         CGSize(width: 2400, height: 700)] {
                let state = CameraViewMath.viewportState(for: c, viewSize: size)
                let frame = CameraViewMath.frameRect(viewSize: size, aspect: c.seitenverhaeltnis)
                XCTAssertEqual(Double(frame.width / frame.height), c.seitenverhaeltnis, accuracy: 1e-6)
                XCTAssertFalse(state.isOrthographic)
                XCTAssertLessThan(simd_distance(state.position, c.auge), 0.01)
                XCTAssertGreaterThan(simd_dot(state.viewDirection, c.blick), 0.99999)
                XCTAssertGreaterThan(simd_dot(state.upVector, c.oben), 0.9999)
                let projector = OverlayProjector(camera: state, size: size)
                let k = CameraViewMath.corners(c, length: 2500)
                let expected = [CGPoint(x: frame.minX, y: frame.minY), CGPoint(x: frame.maxX, y: frame.minY),
                                CGPoint(x: frame.maxX, y: frame.maxY), CGPoint(x: frame.minX, y: frame.maxY)]
                for (p, e) in zip(k, expected) {
                    let q = try XCTUnwrap(projector.project(p))
                    XCTAssertEqual(q.x, e.x, accuracy: 0.1, "\(file) \(size)")
                    XCTAssertEqual(q.y, e.y, accuracy: 0.1, "\(file) \(size)")
                }
            }
        }
    }

    /// Fürs Kamerabild ist der vertikale Öffnungswinkel genau der der Kamera; die Ecken liegen auf den Bildecken.
    func testRenderStateUsesCameraAngle() throws {
        let c = try camera("camera_upsert.frame")
        let s = CameraViewMath.state(for: c)
        XCTAssertEqual(Double(s.fieldOfView), c.bildwinkelV, accuracy: 1e-4)
        let size = CGSize(width: 3840, height: 2160)
        let projector = OverlayProjector(camera: s, size: size)
        let k = CameraViewMath.corners(c, length: 1000)
        let tl = try XCTUnwrap(projector.project(k[0])), br = try XCTUnwrap(projector.project(k[2]))
        XCTAssertEqual(tl.x, 0, accuracy: 0.1)
        XCTAssertEqual(tl.y, 0, accuracy: 0.1)
        XCTAssertEqual(br.x, 3840, accuracy: 0.1)
        XCTAssertEqual(br.y, 2160, accuracy: 0.1)
        // Drehpunkt in der Fokusebene (Fokus 1500 ab Sensor, Augpunkt 35 davor)
        XCTAssertEqual(s.distance, 1465, accuracy: 0.01)
    }

    func testFrameAndSafeAreas() {
        let r = CameraViewMath.frameRect(viewSize: CGSize(width: 1000, height: 1000), aspect: 16.0 / 9.0)
        XCTAssertEqual(r.width, 900, accuracy: 1e-9)
        XCTAssertEqual(r.height, 506.25, accuracy: 1e-9)
        let safe = CameraViewMath.safeAreas(in: r)
        XCTAssertEqual(safe.action.width, 900 * 0.93, accuracy: 1e-9)
        XCTAssertEqual(safe.title.height, 506.25 * 0.90, accuracy: 1e-9)
        XCTAssertEqual(safe.title.midX, r.midX, accuracy: 1e-9)
        // Rahmen füllt die Höhe: Öffnungswinkel des Viewports wird um den Rand größer
        let fov = CameraViewMath.viewportFieldOfView(
            cameraVertical: 32, viewSize: CGSize(width: 2000, height: 1000), frame: CGRect(x: 0, y: 50, width: 1600, height: 900))
        XCTAssertEqual(Double(fov), 2 * atan(tan(16 * Double.pi / 180) / 0.9) * 180 / .pi, accuracy: 1e-4)
    }

    // MARK: Ausblenden und Vorschlag

    func testHiddenPartsAlongLens() throws {
        let c = try camera("camera_upsert.frame")  // Auge (285, 0, 235), Frontlinse 139 vor dem Sensor (x = 389)
        let lens = BoundingBox(min: SIMD3(268, -47, 188), max: SIMD3(389, 47, 282))
        let ball = BoundingBox(min: SIMD3(1100, -108, 0), max: SIMD3(1316, 108, 216))
        let handle = BoundingBox(min: SIMD3(100, -12, 300), max: SIMD3(280, 12, 330))
        let hidden = CameraViewMath.hiddenParts(for: c, bounds: [("Platzhalter-Linse", lens), ("Ball", ball), ("Griff", handle)])
        XCTAssertEqual(hidden, ["Kamera FX6/Objektiv", "Platzhalter-Linse"])
        let bodies = [
            ViewportBody(id: "Ball\u{1F}0", vertexData: [], indices: [], edges: [], color: .one),
            ViewportBody(id: "snap\u{1F}Platzhalter-Linse\u{1F}0\u{1F}-", vertexData: [], indices: [], edges: [], color: .one),
            ViewportBody(id: "Kamera FX6/Objektiv\u{1F}0", vertexData: [], indices: [], edges: [], color: .one),
            ViewportBody(id: "kevcad.depth", vertexData: [], indices: [], edges: [], color: .one),
        ]
        XCTAssertEqual(CameraViewMath.filter(bodies, hiding: hidden).map(\.id), ["Ball\u{1F}0", "kevcad.depth"])
    }

    func testSuggestionFromViewKeepsRoll() throws {
        let c = try camera("camera_upsert.frame")
        // Blick nach +Y, um 10° gerollt (im Uhrzeigersinn von hinten: oben kippt nach rechts)
        let blick = SIMD3<Float>(0, 1, 0)
        let r0 = simd_normalize(simd_cross(blick, SIMD3(0, 0, 1)))  // (1, 0, 0)
        let a: Float = 10 * .pi / 180
        let oben = SIMD3<Float>(0, 0, 1) * cos(a) + r0 * sin(a)
        let s = CameraState.lookAt(target: SIMD3(0, 1000, 500), from: SIMD3(0, 0, 500), up: oben)
        let m = CameraViewMath.suggestion(from: s, for: c)
        XCTAssertEqual(m.roll, 10, accuracy: 0.01)
        XCTAssertLessThan(simd_distance(m.auge, SIMD3(0, 0, 500)), 0.01)
        XCTAssertLessThan(simd_distance(m.sensorPos, SIMD3(0, -35, 500)), 0.01)
        XCTAssertGreaterThan(simd_dot(m.blick, blick), 0.99999)
    }

    // MARK: App-Kern

    func testControllerCameraLifecycle() throws {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        let upsert = try KernelConnection.decode(Fixtures.frame("camera_upsert.frame"))
        let upsertB = try KernelConnection.decode(Fixtures.frame("camera_upsert_b.frame"))
        c.handle([upsert, upsertB])
        XCTAssertEqual(c.model.cameras.cameras.map(\.name), ["Kamera/FX6", "Kamera/B"])
        // Pyramiden im Viewport (je Kamera mit Beschriftung)
        let labels = c.viewport.overlayItems.compactMap { item -> String? in
            if case .label(_, let t, _) = item { return t } else { return nil }
        }
        XCTAssertTrue(labels.contains("FX6 · 35 mm"))
        XCTAssertTrue(labels.contains("B · 50 mm"))

        // Durch die Kamera schauen (VIEW_CMD wie vom Kernel), exakter Öffnungswinkel
        c.viewport.viewSize = CGSize(width: 1600, height: 1000)
        let before = c.viewport.camera
        let r = c.performViewCommand(ViewCommandMessage(id: "k", cmd: "camera_view", args: ["name": "Kamera/FX6"]))
        XCTAssertTrue(r.0)
        XCTAssertEqual(c.model.cameras.activeView, "Kamera/FX6")
        RunLoop.main.run(until: Date().addingTimeInterval(0.8))
        let cam = try XCTUnwrap(c.model.cameras.camera("FX6"))
        let expected = CameraViewMath.viewportState(for: cam, viewSize: CGSize(width: 1600, height: 1000))
        XCTAssertEqual(c.viewport.camera.fieldOfView, expected.fieldOfView, accuracy: 0.01)
        XCTAssertLessThan(simd_distance(c.viewport.camera.position, cam.auge), 0.5)
        // Die Pyramide der aktiven Kamera wird nicht gezeichnet
        XCTAssertFalse(c.viewport.overlayItems.contains { if case .label(_, let t, _) = $0 { return t == "FX6 · 35 mm" } else { return false } })
        // Taste 0 noch einmal: zurück zur Ansicht davor
        c.toggleCameraView()
        XCTAssertNil(c.model.cameras.activeView)
        RunLoop.main.run(until: Date().addingTimeInterval(0.8))
        XCTAssertEqual(c.viewport.camera.fieldOfView, before.fieldOfView, accuracy: 0.01)

        // Unbekannte Kamera, freie Ansicht
        XCTAssertFalse(c.performViewCommand(ViewCommandMessage(id: "k", cmd: "camera_view", args: ["name": "X"])).0)
        XCTAssertTrue(c.performViewCommand(ViewCommandMessage(id: "k", cmd: "camera_view", args: ["name": .null])).0)

        // Strg+Alt+0: Kamera auf die Ansicht (Vorschlag), danach Blick durch sie
        c.selectCamera("B")
        c.setActiveCameraToView()
        let b = try XCTUnwrap(c.model.cameras.camera("Kamera/B"))
        XCTAssertTrue(b.vorschlag)
        XCTAssertEqual(c.model.cameras.activeView, "Kamera/B")
        c.lookThrough(nil)

        // Entfernen
        c.handle([try KernelConnection.decode(Fixtures.frame("camera_remove.frame"))])
        XCTAssertEqual(c.model.cameras.cameras.map(\.name), ["Kamera/FX6"])
        XCTAssertEqual(
            AppController.cameraFileName(cam, width: 3840, height: 2160, date: Date(timeIntervalSince1970: 0)).prefix(19),
            "FX6_35mm_3840x2160_")
    }
}
