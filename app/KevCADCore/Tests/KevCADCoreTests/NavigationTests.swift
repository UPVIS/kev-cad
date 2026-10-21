import OCCTSwiftViewport
import XCTest
import simd
@testable import KevCADCore

/// Blender-Steuerung: Richtungen und Verhalten der Kamera (ohne Fenster).
@MainActor
final class NavigationTests: XCTestCase {
    private func frontCoordinator() -> ViewportCoordinator {
        let c = ViewportCoordinator()
        c.viewSize = CGSize(width: 1000, height: 800)
        var cam = StandardView.front.cameraState(pivot: .zero, distance: 500)
        cam.isOrthographic = false
        c.setCamera(cam)
        return c
    }

    func testOrbitRightMovesCameraToTheLeftAroundZ() {
        let c = frontCoordinator()
        XCTAssertLessThan(c.camera.position.y, 0, "Vorderansicht schaut von -Y")
        c.navOrbit(dx: 50, dy: 0)
        // Maus nach rechts: das Modell folgt der Maus, die Kamera wandert nach links (-X)
        XCTAssertLessThan(c.camera.position.x, -1)
        XCTAssertEqual(c.camera.upVector.z, 1, accuracy: 1e-3, "Turntable: Z bleibt oben")
    }

    func testOrbitMouseDownLooksFromAbove() {
        let c = frontCoordinator()
        c.navOrbit(dx: 0, dy: -50)
        XCTAssertGreaterThan(c.camera.position.z, 1, "Maus nach unten: Blick mehr von oben")
    }

    func testOrbitSensitivityMatchesBlender() {
        let c = frontCoordinator()
        c.navOrbit(dx: 225, dy: 0)  // 225 Punkte × 0,4° = 90°
        let p = simd_normalize(c.camera.position)
        XCTAssertEqual(p.x, -1, accuracy: 1e-3)
    }

    func testPanModelFollowsMouse() {
        let c = frontCoordinator()
        c.navPan(dx: 100, dy: 0)
        XCTAssertLessThan(c.camera.pivot.x, 0, "Maus nach rechts: Ansicht wandert nach links, Modell folgt der Maus")
        c.navPan(dx: 0, dy: 100)
        XCTAssertLessThan(c.camera.pivot.z, 0)
    }

    func testZoomKeepsPivotAndChangesDistance() {
        let c = frontCoordinator()
        c.navZoom(factor: 0.5)
        XCTAssertEqual(c.camera.distance, 250, accuracy: 1e-3)
        XCTAssertEqual(c.camera.pivot, .zero)
    }

    func testAxisViewIsOrthoAndOrbitReturnsToPerspective() {
        let c = frontCoordinator()
        c.navAxisView(.top)
        XCTAssertTrue(c.autoOrtho)
        c.controller.cameraController.cancelAnimation()
        c.setCamera({ var s = c.camera; s.rotation = StandardView.top.rotation; s.isOrthographic = true; return s }())
        c.navOrbit(dx: 10, dy: 0)
        XCTAssertFalse(c.camera.isOrthographic, "Auto Perspective: Drehen verlässt die Parallelprojektion")
        XCTAssertFalse(c.autoOrtho)
    }

    func testNoSnapAfterSmallOrbit() {
        let c = frontCoordinator()
        c.navOrbit(dx: 2, dy: 0)
        let after = c.camera.rotation
        XCTAssertGreaterThan(abs(simd_dot(after.vector, StandardView.front.rotation.vector)), 0.99)
        XCTAssertNotEqual(after, StandardView.front.rotation, "kleine Drehung bleibt erhalten, kein Einrasten")
    }
}
