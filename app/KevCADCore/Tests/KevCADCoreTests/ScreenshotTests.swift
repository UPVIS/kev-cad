import CoreGraphics
import Foundation
import ImageIO
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

@MainActor
final class ScreenshotTests: XCTestCase {
    private func scene() throws -> SceneStore {
        let s = SceneStore()
        s.upsert(try Fixtures.record("part_box.frame"), flash: false)
        s.upsert(try Fixtures.record("part_cylinder.frame"), flash: false)
        return s
    }

    /// Anteil der Pixel, die sich vom Hintergrund unterscheiden.
    private func coverage(_ image: CGImage, background: SIMD3<Float>) -> Double {
        let w = image.width, h = image.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let ctx = CGContext(
            data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        let bg = background * 255
        var differ = 0
        for i in stride(from: 0, to: px.count, by: 4) {
            let d = abs(Float(px[i]) - bg.x) + abs(Float(px[i + 1]) - bg.y) + abs(Float(px[i + 2]) - bg.z)
            if d > 24 { differ += 1 }
        }
        return Double(differ) / Double(w * h)
    }

    func testOffscreenImageIsNotEmpty() throws {
        let renderer = ScreenshotRenderer()
        let s = try scene()
        let bounds = try XCTUnwrap(s.visibleBounds())
        let cam = ViewportCoordinator.fitted(StandardView.isometricFrontRight.cameraState(), to: bounds, aspect: 1.6)
        guard let r = renderer.render(bodies: s.snapshotBodies(), camera: cam, width: 640, height: 400, displayMode: .shadedWithEdges)
        else { throw XCTSkip("Kein Metal-Gerät für den OffscreenRenderer") }
        XCTAssertGreaterThan(r.png.count, 1000)
        XCTAssertEqual(r.image.width, 640)
        XCTAssertEqual(r.image.height, 400)
        XCTAssertNil(r.mmPerPixel)
        let cov = coverage(r.image, background: SIMD3(0.95, 0.95, 0.95))
        XCTAssertGreaterThan(cov, 0.03, "Teile sind im Bild zu sehen")
        XCTAssertLessThan(cov, 0.9)
        // PNG ist lesbar
        let src = try XCTUnwrap(CGImageSourceCreateWithData(r.png as CFData, nil))
        XCTAssertEqual(CGImageSourceGetCount(src), 1)
    }

    func testOrthographicScaleAndOverlay() throws {
        let renderer = ScreenshotRenderer()
        let s = try scene()
        let bounds = try XCTUnwrap(s.visibleBounds())
        let cam = ViewportCoordinator.fitted(StandardView.top.cameraState(), to: bounds, aspect: 1)
        XCTAssertTrue(cam.isOrthographic)
        guard let plain = renderer.render(bodies: s.snapshotBodies(), camera: cam, width: 400, height: 400, displayMode: .shaded)
        else { throw XCTSkip("Kein Metal-Gerät für den OffscreenRenderer") }
        XCTAssertEqual(try XCTUnwrap(plain.mmPerPixel), Double(cam.orthographicScale) / 400, accuracy: 1e-9)
        let overlay: [OverlayPrimitive] = [
            .dimension(a: SIMD3(-5, 0, 15), b: SIMD3(35, 0, 15), text: "40,000 mm", color: SIMD4(0, 0.55, 0.45, 1))
        ]
        let marked = try XCTUnwrap(
            renderer.render(bodies: s.snapshotBodies(), camera: cam, width: 400, height: 400, displayMode: .shaded, overlay: overlay))
        XCTAssertNotEqual(plain.png, marked.png)
        // Projektion: Bildmitte entspricht der Mitte des Hüllquaders
        let proj = OverlayProjector(camera: cam, size: CGSize(width: 400, height: 400))
        let c = try XCTUnwrap(proj.project(bounds.center))
        XCTAssertEqual(c.x, 200, accuracy: 1)
        XCTAssertEqual(c.y, 200, accuracy: 1)
        // Draufsicht mit Z oben: +X nach rechts, +Y nach oben im Bild
        let px = try XCTUnwrap(proj.project(bounds.center + SIMD3(10, 0, 0)))
        let py = try XCTUnwrap(proj.project(bounds.center + SIMD3(0, 10, 0)))
        XCTAssertGreaterThan(px.x, c.x)
        XCTAssertLessThan(py.y, c.y)
    }

    func testCameraJSON() {
        let cam = StandardView.front.cameraState(distance: 100, orthographicScale: 80)
        let j = ViewportCoordinator.cameraJSON(cam, height: 800)
        XCTAssertEqual(j["projection"]?.stringValue, "orthographic")
        XCTAssertEqual(j["view"]?.stringValue, "front")
        XCTAssertEqual(j["mm_per_px"]?.doubleValue ?? 0, 0.1, accuracy: 1e-9)
        XCTAssertEqual(j["position"]?.doubles?.count, 3)
        let iso = ViewportCoordinator.cameraJSON(StandardView.isometricFrontRight.cameraState(), height: 800)
        XCTAssertEqual(iso["view"]?.stringValue, "iso")
        XCTAssertTrue(iso["ortho_height_mm"]?.isNull ?? false)
        // Vorderansicht schaut entlang +Y (Kamera bei -Y), oben ist +Z
        XCTAssertEqual(cam.viewDirection.y, 1, accuracy: 1e-5)
        XCTAssertEqual(cam.upVector.z, 1, accuracy: 1e-5)
    }
}
