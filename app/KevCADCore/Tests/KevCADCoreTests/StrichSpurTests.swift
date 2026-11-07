import CoreGraphics
import XCTest

@testable import KevCADCore

/// I-4 (PLAN-IPAD.md 4.3): Spur eines Stiftstrichs mit zusammengefassten und vorhergesagten Punkten. Die Messung der
/// Verzögerung am Gerät folgt in I-10; hier nur die Logik.
final class StrichSpurTests: XCTestCase {
    func testZusammengefassteSindAlleDrinDieVorhersageNicht() {
        let s = StrichSpur()
        s.beginnen(CGPoint(x: 0, y: 0))
        let n = s.anfuegen([CGPoint(x: 1, y: 0), CGPoint(x: 2, y: 0), CGPoint(x: 3, y: 0)],
                           vorhersage: [CGPoint(x: 4, y: 0), CGPoint(x: 5, y: 0)])
        XCTAssertEqual(n, 3)
        XCTAssertEqual(s.punkte.count, 4)
        XCTAssertEqual(s.vorhersage.count, 2)
        XCTAssertNotNil(s.vorhersagePfad())
        XCTAssertEqual(s.pfad.currentPoint, CGPoint(x: 3, y: 0), "die Vorhersage geht nicht in die Linie")
        // Das nächste Ereignis ersetzt die Vorhersage
        s.anfuegen([CGPoint(x: 3.8, y: 0)], vorhersage: [])
        XCTAssertNil(s.vorhersagePfad())
        XCTAssertEqual(s.punkte.last, CGPoint(x: 3.8, y: 0))
    }

    func testDichtePunkteZeichnenNichtsNeues() {
        let s = StrichSpur()
        s.beginnen(CGPoint(x: 10, y: 10))
        XCTAssertEqual(s.anfuegen([CGPoint(x: 10.2, y: 10.1), CGPoint(x: 10.3, y: 10)], vorhersage: []), 0)
        XCTAssertEqual(s.anfuegen([CGPoint(x: 11, y: 10)], vorhersage: []), 1)
    }

    func testAbhebenVerwirftDieVorhersage() {
        let s = StrichSpur()
        s.beginnen(.zero)
        s.anfuegen([CGPoint(x: 5, y: 5)], vorhersage: [CGPoint(x: 9, y: 9)])
        s.beenden()
        XCTAssertNil(s.vorhersagePfad())
        XCTAssertEqual(s.punkte.count, 2)
    }

    func testLatenzAnteil() {
        let s = StrichSpur()
        s.beginnen(.zero)
        XCTAssertNil(s.latenzAnteil(0.95))
        for ms in [8.0, 9, 10, 11, 30] { s.latenz(beruehrung: 100, jetzt: 100 + ms / 1000) }
        s.latenz(beruehrung: 0, jetzt: 5)  // ohne Zeitstempel zählt nicht
        XCTAssertEqual(s.latenzenMs.count, 5)
        XCTAssertEqual(s.latenzAnteil(0.5) ?? 0, 10, accuracy: 1e-6)
        XCTAssertEqual(s.latenzAnteil(0.95) ?? 0, 30, accuracy: 1e-6)
        s.beginnen(.zero)
        XCTAssertTrue(s.latenzenMs.isEmpty, "je Strich neu")
    }
}
