import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Phase 5, Zusammenspiel der Stränge KAM und ANI: Kameras fahren mit dem Teil, dem sie folgen (Pyramide, Blick durch
/// die Kamera, Kamera für das Video), und Vorschläge aus der Ansicht kommen in der Ruhelage zurück.
@MainActor
final class CameraAnimationTests: XCTestCase {
    private func fixtureCamera() throws -> CameraInfo {
        guard case .camera(.upsert(let c)) = try Fixtures.message("camera_upsert.frame") else {
            throw XCTSkip("camera_upsert.frame ist kein CAMERA_UPSERT")
        }
        return c
    }

    private func close(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ tol: Float = 1e-3, file: StaticString = #filePath,
                       line: UInt = #line) {
        XCTAssertLessThan(simd_distance(a, b), tol, "\(a) ≠ \(b)", file: file, line: line)
    }

    func testFolgtFromFixtureAndFallbackToTeil() throws {
        let c = try fixtureCamera()
        XCTAssertEqual(c.folgt, "Wagen")
        guard case .camera(.upsert(let b)) = try Fixtures.message("camera_upsert_b.frame") else { return XCTFail() }
        XCTAssertNil(b.folgt)  // frei gesetzt, ohne Körper: steht fest
        // älterer Kernel ohne `folgt`: es gilt `teil`
        let json = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"name": "Kamera/A", "teil": "Wagen/Deckel"}"#.utf8))
        XCTAssertEqual(CameraInfo(json: json)?.folgt, "Wagen/Deckel")
    }

    func testTransformMovesCameraRigidly() throws {
        let c = try fixtureCamera()  // Sensor (250, 0, 235), Blick +X, oben +Z
        var m = simd_float4x4(simd_quatf(angle: .pi / 2, axis: SIMD3(0, 0, 1)))
        m.columns.3 = SIMD4(100, 0, 0, 1)
        let t = c.transformed(by: m)
        close(t.sensorPos, SIMD3(100, 250, 235))
        close(t.auge, SIMD3(100, 285, 235))
        close(t.blick, SIMD3(0, 1, 0), 1e-5)
        close(t.oben, SIMD3(0, 0, 1), 1e-5)
        close(t.rechts, simd_cross(t.blick, t.oben), 1e-5)
        XCTAssertEqual(t.bildwinkelV, c.bildwinkelV)
    }

    func testCameraRidesAlongWithAnimatedPart() throws {
        let c = AppController(model: AppModel())
        c.handle([.part(try Fixtures.record("part_box.frame"))])  // "Grundplatte"
        var cam = try fixtureCamera()
        cam.teil = "Grundplatte"
        cam.folgt = "Grundplatte"
        cam.ausblenden = []
        c.applyCamera(.upsert(cam))
        let clip = AnimationClip(
            name: "Fahrt", duration: 1, fps: 2, frameCount: 3, parts: ["Grundplatte"],
            matrices: [matrix_identity_float4x4, simd_float4x4(translationX: 50), simd_float4x4(translationX: 100)]
                .flatMap(AnimationTests.pack), isDefault: true)
        c.handleAnimation(.definition(clip))

        // Pyramide fährt mit (Beschriftung über der Oberkante, also mit dem Augpunkt verschoben)
        func labelPoint() -> SIMD3<Float>? {
            for item in c.viewport.overlayItems {
                if case .label(let p, let text, _) = item, text == "FX6 · 35 mm" { return p }
            }
            return nil
        }
        let restLabel = try XCTUnwrap(labelPoint())
        c.seekAnimation(to: 0.5)
        close(c.posedCamera(cam).sensorPos, cam.sensorPos + SIMD3(50, 0, 0))
        close(try XCTUnwrap(labelPoint()), restLabel + SIMD3(50, 0, 0))

        // Blick durch die Kamera (Taste 0) folgt beim Springen und Abspielen, die Ansicht bleibt aktiv
        c.viewport.viewSize = CGSize(width: 1600, height: 1000)
        c.lookThrough("FX6")
        RunLoop.main.run(until: Date().addingTimeInterval(0.6))
        close(c.viewport.camera.position, cam.auge + SIMD3(50, 0, 0), 0.5)
        c.jumpToAnimationEnd()
        close(c.viewport.camera.position, cam.auge + SIMD3(100, 0, 0), 0.5)
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        XCTAssertEqual(c.model.cameras.activeView, "Kamera/FX6")

        // Kamera für das Video über den Resolver des Strangs ANI: Lage des aktuellen Bildes, Bildwinkel der Kamera
        let state = try XCTUnwrap(c.animationCamera(named: "Kamera/FX6", at: 1))
        close(state.position, cam.auge + SIMD3(100, 0, 0), 0.5)
        XCTAssertEqual(state.fieldOfView, Float(cam.bildwinkelV), accuracy: 0.01)
        XCTAssertNil(c.animationCamera(named: "Kamera/Gibtsnicht", at: 0))

        // Vorschlag aus der Ansicht (Strg+Alt+0) zurück in die Ruhelage gerechnet
        let msg = c.restSuggestion(from: c.viewport.camera, for: cam)
        close(msg.auge, cam.auge, 0.5)
        close(msg.blick, cam.blick, 1e-3)

        // Zurücksetzen: Kamera wieder in der Ruhelage
        c.resetAnimationPose()
        close(c.viewport.camera.position, cam.auge, 0.5)
        c.lookThrough(nil)
    }

    func testCameraWithoutPartStays() throws {
        let c = AppController(model: AppModel())
        c.handle([.part(try Fixtures.record("part_box.frame"))])
        var fest = try fixtureCamera()
        fest.teil = nil
        fest.folgt = nil
        let clip = AnimationClip(
            name: "Fahrt", duration: 1, fps: 2, frameCount: 3, parts: ["Grundplatte"],
            matrices: [matrix_identity_float4x4, simd_float4x4(translationX: 50), simd_float4x4(translationX: 100)]
                .flatMap(AnimationTests.pack), isDefault: true)
        c.applyCamera(.upsert(fest))
        c.handleAnimation(.definition(clip))
        c.jumpToAnimationEnd()
        close(c.posedCamera(fest).sensorPos, fest.sensorPos)
        // folgt einem Teil, das es (noch) nicht gibt: steht ebenfalls
        fest.folgt = "Gibtsnicht"
        close(c.posedCamera(fest).sensorPos, fest.sensorPos)
    }
}
