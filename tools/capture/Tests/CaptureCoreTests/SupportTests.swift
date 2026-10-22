import simd
import XCTest
@testable import CaptureCore

/// `--auflage`: Gegenstand auf einer Holzscheibe, die auf dem Boden steht (wie die Scarlett im Video IMG_5186).
final class SupportTests: XCTestCase {
    /// Punkte auf den Flächen: Boden (z = 0), Scheibe (Oberseite in `scheibeZ`, um `neigung` Grad um X gekippt,
    /// Radius 170, Mantel), Kasten 180 × 117 × 47,5 mit 2 mm Luft über der Scheibe.
    func szene(boden: Bool = true, scheibe: Bool = true, scheibeZ: Double = 60, neigung: Double = 0,
               seed: UInt64 = 5) -> (pts: [SIMD3<Double>], blick: SIMD3<Double>, kastenUnten: Double) {
        var rng = SplitMix64(seed: seed)
        func r(_ a: Double, _ b: Double) -> Double { Double.random(in: a...b, using: &rng) }
        let w = neigung * Double.pi / 180
        // Oberseite der Scheibe: z = scheibeZ + tan(w) * y
        func oben(_ y: Double) -> Double { scheibe ? scheibeZ + tan(w) * y : 0 }
        var pts: [SIMD3<Double>] = []
        if boden {
            for _ in 0..<3000 { pts.append(SIMD3(r(-600, 600), r(-600, 600), r(-0.3, 0.3))) }
        }
        if scheibe {
            for _ in 0..<2500 {
                let a = r(0, 2 * Double.pi), rad = 170 * r(0, 1).squareRoot()
                let y = rad * sin(a)
                pts.append(SIMD3(rad * cos(a), y, oben(y) + r(-0.4, 0.4)))
            }
            for _ in 0..<1200 { // Mantel
                let a = r(0, 2 * Double.pi), y = 170 * sin(a)
                pts.append(SIMD3(170 * cos(a), y, r(0, oben(y))))
            }
        }
        // Kasten, um 20° gedreht, auf der Scheibe in der Mitte; Unterseite parallel zur Scheibe
        let unten = oben(0) + 2
        let rot = simd_double3x3(rows: [SIMD3(cos(0.35), -sin(0.35), 0), SIMD3(sin(0.35), cos(0.35), 0), SIMD3(0, 0, 1)])
        let kipp = simd_double3x3(rows: [SIMD3(1, 0, 0), SIMD3(0, cos(w), -sin(w)), SIMD3(0, sin(w), cos(w))])
        func kasten(_ p: SIMD3<Double>) -> SIMD3<Double> { kipp * (rot * p) + SIMD3(0, 0, unten) }
        for _ in 0..<1800 { pts.append(kasten(SIMD3(r(-90, 90), r(-58.5, 58.5), 47.5))) }       // Deckel
        for _ in 0..<700 { pts.append(kasten(SIMD3(r(-90, 90), -58.5, r(0, 47.5)))) }         // vorn
        for _ in 0..<700 { pts.append(kasten(SIMD3(r(-90, 90), 58.5, r(0, 47.5)))) }          // hinten
        for _ in 0..<450 { pts.append(kasten(SIMD3(-90, r(-58.5, 58.5), r(0, 47.5)))) }       // links
        for _ in 0..<450 { pts.append(kasten(SIMD3(90, r(-58.5, 58.5), r(0, 47.5)))) }        // rechts
        for _ in 0..<150 { pts.append(kasten(SIMD3(r(-90, 90), -58.5, r(-2, 0)))) }           // „Vorhang“ im Spalt
        return (pts, kasten(SIMD3(0, 0, 24)), unten)
    }

    func testFindetScheibeUnterDemKasten() {
        let s = szene()
        let a = PostProcessor.findSupport(s.pts, lookAt: s.blick, tol: 1.0)!
        XCTAssertEqual(a.plane.normal.z, 1, accuracy: 0.002)
        XCTAssertEqual(-a.plane.d, 60, accuracy: 1.0)         // Scheibe, nicht Boden (0) und nicht Deckel (109,5)
        XCTAssertGreaterThan(a.above, 3000)
    }

    func testGekippteScheibe() {
        let s = szene(neigung: 6)
        let a = PostProcessor.findSupport(s.pts, lookAt: s.blick, tol: 1.0)!
        let n = a.plane.normal
        XCTAssertEqual(acos(n.z) * 180 / Double.pi, 6, accuracy: 0.5)
        XCTAssertEqual(a.plane.distance(SIMD3(0, 0, 60)), 0, accuracy: 1.0)
    }

    func testOhneScheibeIstBodenDieAuflage() {
        let s = szene(scheibe: false)
        let a = PostProcessor.findSupport(s.pts, lookAt: s.blick, tol: 1.0)!
        XCTAssertEqual(-a.plane.d, 0, accuracy: 1.0)
    }

    func testOhneBodenNurScheibe() {
        // Objektmaskierung hat den Boden entfernt (wie im Video): Scheibe bleibt die Auflage
        let s = szene(boden: false)
        let a = PostProcessor.findSupport(s.pts, lookAt: s.blick, tol: 1.0)!
        XCTAssertEqual(-a.plane.d, 60, accuracy: 1.0)
    }

    func testNurKastenOhneUnterlageFindetNichts() {
        // Nur der Gegenstand im Netz: der Deckel trägt nichts, also keine Auflage
        let s = szene(boden: false, scheibe: false)
        XCTAssertNil(PostProcessor.findSupport(s.pts, lookAt: s.blick, tol: 1.0))
    }
}
