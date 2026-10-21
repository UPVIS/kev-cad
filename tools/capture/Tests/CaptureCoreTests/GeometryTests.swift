import simd
import XCTest
@testable import CaptureCore

final class GeometryTests: XCTestCase {
    func testMinAreaRectFindsRotatedRectangle() {
        // Rechteck 610 × 410, um 25° gedreht, Mitte (100, −50)
        let a = 25.0 * Double.pi / 180
        var pts: [SIMD2<Double>] = []
        var rng = SplitMix64(seed: 3)
        for _ in 0..<2000 {
            let u = Double.random(in: -305...305, using: &rng), v = Double.random(in: -205...205, using: &rng)
            pts.append(SIMD2(100 + u * cos(a) - v * sin(a), -50 + u * sin(a) + v * cos(a)))
        }
        let r = Geo.minAreaRect(pts)
        XCTAssertEqual(r.length, 610, accuracy: 3)
        XCTAssertEqual(r.width, 410, accuracy: 3)
        XCTAssertEqual(r.angle, a, accuracy: 0.02)
        XCTAssertEqual(r.center.x, 100, accuracy: 2)
        XCTAssertEqual(r.center.y, -50, accuracy: 2)
    }

    func testRansacPlaneIgnoresObjectAboveFloor() {
        var rng = SplitMix64(seed: 9)
        var pts: [SIMD3<Double>] = []
        for _ in 0..<3000 { // leicht geneigter Boden
            let x = Double.random(in: -1...1, using: &rng), y = Double.random(in: -1...1, using: &rng)
            pts.append(SIMD3(x, y, 0.05 * x + Double.random(in: -0.002...0.002, using: &rng)))
        }
        for _ in 0..<1500 { // Kiste darüber
            pts.append(SIMD3(Double.random(in: -0.3...0.3, using: &rng), Double.random(in: -0.2...0.2, using: &rng),
                             Double.random(in: 0.05...0.4, using: &rng)))
        }
        let (pl, inl) = Geo.ransacPlane(pts, threshold: 0.006, seed: 1, allowed: { abs($0.z) > 0.9 })!
        let n = pl.normal.z < 0 ? -pl.normal : pl.normal
        XCTAssertEqual(n.x, -0.05 / (1 + 0.0025).squareRoot(), accuracy: 0.005)
        XCTAssertGreaterThan(inl.count, 2800)
    }

    func testCircleFitOnUpperArc() {
        var pts: [SIMD2<Double>] = []
        for i in 0..<200 { // obere Hälfte eines Rads Ø 100, Mitte (0, 110)
            let t = Double(i) / 199 * Double.pi
            pts.append(SIMD2(50 * cos(t), 110 + 50 * sin(t)))
        }
        for i in 0..<60 { pts.append(SIMD2(Double(i) - 30, 60 + Double(i % 7))) } // Gabel, Störpunkte
        let fit = Geo.fitCircle(pts, threshold: 1.0)!
        XCTAssertEqual(2 * fit.radius, 100, accuracy: 1)
        XCTAssertEqual(fit.center.y, 110, accuracy: 1)
    }

    func testDensestBandFindsFrameLayer() {
        // Rahmen 30–50 mm dicht, Räder bis 160 mm dünn besetzt
        var zs: [Double] = []
        for i in 0..<4000 { zs.append(30 + Double(i % 200) / 10) }
        for i in 0..<1000 { zs.append(50 + Double(i % 110)) }
        let b = PostProcessor.densestBand(zs, height: 160, floorCut: 4)
        XCTAssertLessThanOrEqual(b.lo, 31)
        XCTAssertGreaterThanOrEqual(b.hi, 49)
        XCTAssertLessThan(b.hi, 60)
    }

    func testYUpToZUpMapping() {
        let p = PostProcessor.yUpToZUp * SIMD4<Double>(1, 2, 3, 1)
        XCTAssertEqual(p, SIMD4(1, -3, 2, 1))
    }
}
