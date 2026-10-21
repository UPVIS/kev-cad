import Foundation
import XCTest
import simd

@testable import KevCADCore

/// Zwangsbedingungen: Nachricht CONSTRAINTS lesen (Testdatei aus dem Kernel), tolerant lesen, Symbole im Viewport,
/// Ein- und Ausblenden, Bedingung zeigen.
@MainActor
final class ConstraintTests: XCTestCase {
    func testConstraintsFixtureDecodes() throws {
        let msg = try Fixtures.message("constraints.frame")
        XCTAssertEqual(msg.typeName, "CONSTRAINTS")
        guard case .constraints(let r) = msg else { return XCTFail("kein CONSTRAINTS") }
        XCTAssertEqual(r.run, 3)
        XCTAssertEqual(r.items.map(\.id), ["b1", "b2", "b3", "p:wand"])
        let schraube = try XCTUnwrap(r.items.first { $0.id == "b2" })
        XCTAssertEqual(schraube.stand, .verletzt)
        XCTAssertEqual(schraube.schwere, .fehler)
        XCTAssertTrue(schraube.isError)
        XCTAssertEqual(schraube.soll, "Durchgang ≥ Ø 8 mm für M8 (mittel Ø 9 mm)")
        XCTAssertEqual(schraube.ist, "Ø 6 mm")
        XCTAssertEqual(schraube.punkte.count, 2)
        XCTAssertEqual(schraube.punkte[0], SIMD3<Float>(10, 0, 10))
        XCTAssertEqual(schraube.zeile, 61)
        let gelenk = try XCTUnwrap(r.items.first { $0.id == "b3" })
        XCTAssertEqual(gelenk.gruppe, "gelenk")
        XCTAssertEqual(gelenk.bereich, [-60, 90])
        XCTAssertEqual(gelenk.wertEinheit, "°")
        XCTAssertEqual(gelenk.achse?.richtung, SIMD3<Float>(0, -1, 0))
        XCTAssertEqual(r.items.last?.teile, [])
        XCTAssertEqual(r.parts.map(\.name), ["Rollwagen/Rahmen", "Klappe"])
        let klappe = try XCTUnwrap(r.part("Klappe"))
        XCTAssertEqual(klappe.frei, 1)
        XCTAssertEqual(klappe.freiheitsgrade.filter(\.gelenk).count, 1)
        XCTAssertEqual(klappe.amBoden, false)
        XCTAssertEqual(r.motions.first?.frei, [[-10, 40]])
        XCTAssertEqual(r.motions.first?.blockiertDurch, ["Rahmen"])
        XCTAssertEqual(r.findings.map(\.schwere), [.fehler, .fehler, .hinweis])
        XCTAssertEqual(r.findings[1].pruefung, "bewegungsraum")
        XCTAssertNil(r.findings[2].ort)
        XCTAssertEqual(r.summary.fehler, 3)
        XCTAssertTrue(r.hasErrors)
        XCTAssertEqual(r.partsWithErrors, ["Schraube", "Platte", "Klappe", "Rahmen"])
        XCTAssertEqual(r.items(for: "Rollwagen").map(\.id), ["b1"])
        XCTAssertEqual(r.pruefMs, 14.2)
    }

    func testTolerantDecoding() throws {
        let raw = #"{"type":"CONSTRAINTS","items":[{"stand":"komisch","punkte":[[1,2],[1,2,3]]},"kaputt"],"befunde":[{}],"teile":[{"frei":2}]}"#
        let frame = Frame(header: Data(raw.utf8), payload: Data())
        guard case .constraints(let r) = try KernelMessage.decode(frame) else { return XCTFail() }
        XCTAssertEqual(r.items.count, 1)
        XCTAssertEqual(r.items[0].stand, .ungeprueft)
        XCTAssertEqual(r.items[0].id, "b1")
        XCTAssertEqual(r.items[0].punkte, [SIMD3<Float>(1, 2, 3)])
        XCTAssertEqual(r.findings.first?.schwere, .hinweis)
        XCTAssertTrue(r.parts.isEmpty)  // Teil ohne Namen fällt weg
        XCTAssertEqual(r.summary.gesamt, 1)
        XCTAssertEqual(r.summary.ungeprueft, 1)
        XCTAssertFalse(r.hasErrors)
    }

    private func loadedController() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        return c
    }

    private func report() -> ConstraintReport {
        var ok = ConstraintItem(
            id: "b1", art: "auf", text: "Halter/Bolzen.unten auf Grundplatte.oben", teile: ["Halter/Bolzen", "Grundplatte"],
            stand: .erfuellt, punkte: [SIMD3(30, 0, 15), SIMD3(30, 0, 15)])
        ok.zeile = 12
        let falsch = ConstraintItem(
            id: "b2", art: "konzentrisch", text: "Halter/Bolzen.achse konzentrisch zu Grundplatte.bohrung",
            teile: ["Halter/Bolzen", "Grundplatte"], stand: .verletzt, schwere: .fehler, soll: "Achsen deckungsgleich",
            ist: "Versatz 1,5 mm", abweichung: 1.5, punkte: [SIMD3(30, 0, 10), SIMD3(31.5, 0, 10)],
            loesung: "Halter/Bolzen um (1,5; 0; 0) mm verschieben")
        return ConstraintReport(
            run: 1, items: [ok, falsch],
            findings: [ConstraintFinding(id: 0, pruefung: "befestigung", teile: ["Grundplatte"], schwere: .fehler,
                                         text: "Grundplatte ist nicht befestigt", ort: SIMD3(0, 0, 5))],
            summary: ConstraintSummary(gesamt: 2, erfuellt: 1, verletzt: 1, fehler: 2))
    }

    private func badges(_ c: AppController) -> [(String, Bool)] {
        c.viewport.overlayItems.compactMap {
            if case .badge(_, let text, _, let filled) = $0 { return (text, filled) }
            return nil
        }
    }

    func testSymbolsInOverlayAndToggle() throws {
        let c = try loadedController()
        c.handle(.constraints(report()))
        XCTAssertEqual(c.model.constraints?.items.count, 2)
        let b = badges(c)
        XCTAssertEqual(b.count, 3)
        XCTAssertTrue(b.contains { $0 == ("◎", true) })  // verletzt: gefüllt
        XCTAssertTrue(b.contains { $0 == ("⊤", false) })
        XCTAssertTrue(b.contains { $0 == ("!", true) })  // Befund ohne Bedingung (Befestigung)
        // verletzte Bedingung zeigt die Strecke zum Gegenstück
        XCTAssertTrue(c.viewport.overlayItems.contains {
            if case .polyline(let pts, _, _) = $0 { return pts == [SIMD3(30, 0, 10), SIMD3(31.5, 0, 10)] }
            return false
        })
        XCTAssertTrue(c.model.log.contains { $0.text.contains("1 verletzt") })

        c.setConstraintSymbolsVisible(false)
        XCTAssertFalse(c.model.showConstraintSymbols)
        XCTAssertTrue(badges(c).isEmpty)
        c.setConstraintSymbolsVisible(true)
        XCTAssertEqual(badges(c).count, 3)

        // ausgeblendete Teile: keine Symbole
        c.setVisibility(["Halter/Bolzen", "Grundplatte"], visible: false)
        XCTAssertTrue(badges(c).isEmpty)
        // Bedingung zeigen: Teile wieder sichtbar und ausgewählt
        c.showConstraint("b2")
        XCTAssertEqual(Set(c.model.selection.map(\.ref)), ["Halter/Bolzen", "Grundplatte"])
        XCTAssertTrue(c.model.parts.allSatisfy(\.visible))
        XCTAssertEqual(badges(c).count, 3)
        XCTAssertTrue(c.model.actions is ConstraintActions)
    }

    func testOverlayPainterDrawsBadges() throws {
        let ctx = try XCTUnwrap(CGContext(
            data: nil, width: 200, height: 120, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        let box1 = OverlayPainter.drawBadge("◎", at: CGPoint(x: 50, y: 60), color: SIMD4(1, 0, 0, 1), filled: true,
                                            in: ctx, scale: 1)
        let box2 = OverlayPainter.drawBadge("⊤", at: CGPoint(x: 50, y: 60), color: SIMD4(0, 0, 1, 1), filled: false,
                                            in: ctx, scale: 1, avoid: [box1])
        XCTAssertFalse(box1.intersects(box2))  // zwei Symbole am selben Punkt stehen nebeneinander
        XCTAssertEqual(box1.width, 18)
    }
}
