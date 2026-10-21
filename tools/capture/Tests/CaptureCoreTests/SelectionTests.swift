import XCTest
@testable import CaptureCore

final class SelectionTests: XCTestCase {
    func testWindowSelectionPicksSharpestPerWindow() {
        // 10 s, 30 fps, 5 Fenster à 2 s; im Fenster gewinnt der größte Wert
        let times = (0..<300).map { Double($0) / 30 }
        var scores = times.map { _ in 1.0 }
        let expected = [17, 75, 130, 200, 299]
        for e in expected { scores[e] = 5 }
        let sel = WindowSelector(count: 5, duration: 10).select(times: times, scores: scores)
        XCTAssertEqual(sel, expected)
    }

    func testWindowCountClampsToLastWindow() {
        let s = WindowSelector(count: 4, duration: 8)
        XCTAssertEqual(s.window(at: 0), 0)
        XCTAssertEqual(s.window(at: 7.99), 3)
        XCTAssertEqual(s.window(at: 9), 3)
    }

    func testLaplacianVarianceSeparatesSharpFromBlurred() {
        let w = 64, h = 64
        var sharp = [UInt8](repeating: 0, count: w * h)
        var blurred = [UInt8](repeating: 0, count: w * h)
        for y in 0..<h {
            for x in 0..<w {
                sharp[y * w + x] = ((x / 4 + y / 4) % 2 == 0) ? 230 : 20
                // weicher Verlauf statt harter Kanten
                let v = 125 + 100 * sin(Double(x) / 6) * sin(Double(y) / 6)
                blurred[y * w + x] = UInt8(max(0, min(255, v)))
            }
        }
        let a = Sharpness.laplacianVariance(gray: sharp, width: w, height: h)
        let b = Sharpness.laplacianVariance(gray: blurred, width: w, height: h)
        XCTAssertGreaterThan(a, 20 * b)
        let flat = [UInt8](repeating: 128, count: w * h)
        XCTAssertEqual(Sharpness.laplacianVariance(gray: flat, width: w, height: h), 0, accuracy: 1e-6)
    }
}
