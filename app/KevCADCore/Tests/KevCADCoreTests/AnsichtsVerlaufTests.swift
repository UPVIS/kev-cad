import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// I-3b (PLAN-IPAD.md 4.2): Rückgängig und Wiederholen für Ansicht, Auswahl und Sichtbarkeit, und das Kontextmenü am Teil
/// aus einer Quelle für Mac und iPad. Läuft auf beiden Plattformen.
@MainActor
final class AnsichtsVerlaufTests: XCTestCase {
    func testVerlaufSchritteZurueckUndVor() {
        var v = Verlauf<Int>(gleich: ==)
        XCTAssertFalse(v.merke(1), "der erste Stand ist der Anfang, kein Schritt")
        XCTAssertFalse(v.merke(1), "derselbe Stand zählt nicht")
        XCTAssertTrue(v.merke(2))
        XCTAssertTrue(v.merke(3))
        XCTAssertEqual(v.rueckgaengig(), 2)
        XCTAssertEqual(v.rueckgaengig(), 1)
        XCTAssertNil(v.rueckgaengig(), "vor dem Anfang ist nichts mehr")
        XCTAssertEqual(v.aktuell, 1)
        XCTAssertEqual(v.wiederholen(), 2)
        XCTAssertTrue(v.kannWiederholen)
        XCTAssertTrue(v.merke(5), "eine neue Änderung …")
        XCTAssertFalse(v.kannWiederholen, "… nimmt das Wiederholen weg")
        XCTAssertEqual(v.rueckgaengig(), 2)
        v.leeren(ab: 9)
        XCTAssertFalse(v.kannRueckgaengig)
        XCTAssertEqual(v.aktuell, 9)
    }

    func testVerlaufHatEineGrenze() {
        var v = Verlauf<Int>(gleich: ==)
        v.grenze = 3
        for i in 0...10 { v.merke(i) }
        XCTAssertEqual(v.zurueck, [7, 8, 9])
    }

    func testKameraGleichMitToleranz() {
        let a = StandardView.isometricFrontRight.cameraState(distance: 400)
        var b = a
        b.distance += 0.00001
        XCTAssertTrue(AnsichtsStand.kameraGleich(a, b), "eine Fahrt endet nicht immer bitgleich")
        b.distance += 5
        XCTAssertFalse(AnsichtsStand.kameraGleich(a, b))
        var c = a
        c.rotation = simd_quatf(vector: -a.rotation.vector)
        XCTAssertTrue(AnsichtsStand.kameraGleich(a, c), "q und -q sind dieselbe Drehung")
    }

    /// Lauf mit zwei Teilen aus stream.bin (wie ControllerTests).
    private func controller() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        c.verlaufFestschreiben()  // Anfang: der geladene Stand
        return c
    }

    func testAuswahlSichtbarkeitUndKamera() throws {
        let c = try controller()
        XCTAssertNil(c.verlaufTitel(.rueckgaengig), "noch nichts geändert")

        c.select(["Grundplatte"])
        XCTAssertEqual(c.verlaufTitel(.rueckgaengig), "Rückgängig: Auswahl",
                       "eine Änderung in der Ruhezeit zählt schon, wenn das Menü fragt")
        c.setVisibility(["Halter/Bolzen"], visible: false)
        c.verlaufFestschreiben()
        let vorher = c.viewport.kameraZiel
        var neu = vorher
        neu.distance *= 2
        c.viewport.setCamera(neu)
        c.verlaufFestschreiben()
        XCTAssertEqual(c.model.viewer.rueckgaengigTitel, "Rückgängig: Ansicht")

        c.ausfuehren(.rueckgaengig)
        XCTAssertTrue(AnsichtsStand.kameraGleich(c.viewport.kameraZiel, vorher), "Kamera wie vorher")
        XCTAssertEqual(c.model.viewer.meldung?.text, "Rückgängig: Ansicht")
        c.ausfuehren(.rueckgaengig)
        XCTAssertFalse(c.scene.hidden.contains("Halter/Bolzen"), "Bolzen wieder sichtbar")
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte"], "die Auswahl bleibt dabei")
        c.ausfuehren(.rueckgaengig)
        XCTAssertTrue(c.model.selection.isEmpty, "Auswahl zurück")
        c.ausfuehren(.rueckgaengig)
        XCTAssertEqual(c.model.viewer.meldung?.text, "Nichts mehr rückgängig zu machen")

        c.ausfuehren(.wiederholen)
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte"])
        c.ausfuehren(.wiederholen)
        XCTAssertTrue(c.scene.hidden.contains("Halter/Bolzen"))
        XCTAssertEqual(c.model.viewer.wiederholenTitel, "Wiederholen: Ansicht")
        c.verlaufFestschreiben()
        XCTAssertNotNil(c.model.viewer.wiederholenTitel, "Wiederholen anwenden ist keine neue Änderung")

        c.select([])
        c.verlaufFestschreiben()
        XCTAssertNil(c.model.viewer.wiederholenTitel, "eine neue Änderung nimmt das Wiederholen weg")
    }

    func testLokaleAnsichtZurueck() throws {
        let c = try controller()
        c.select(["Grundplatte"])
        c.verlaufFestschreiben()
        c.ausfuehren(.isolieren)
        c.verlaufFestschreiben()
        XCTAssertTrue(c.model.viewer.lokaleAnsicht)
        c.ausfuehren(.rueckgaengig)
        XCTAssertFalse(c.model.viewer.lokaleAnsicht, "Rückgängig verlässt die lokale Ansicht")
        XCTAssertTrue(c.scene.hauchTeile.isEmpty)
        XCTAssertTrue(c.scene.hidden.isEmpty)
        c.ausfuehren(.wiederholen)
        XCTAssertTrue(c.model.viewer.lokaleAnsicht, "Wiederholen geht wieder hinein")
        c.ausfuehren(.isolieren)
        XCTAssertFalse(c.model.viewer.lokaleAnsicht, "/ führt danach wie gewohnt hinaus")
    }

    func testKontextmenueEineQuelle() throws {
        let c = try controller()
        let ohne = c.kontextEintraege(treffer: nil)
        XCTAssertEqual(ohne.count, 3)
        XCTAssertEqual(ohne.flatMap { $0 }.map(\.befehl),
                       [.auswahlEinrahmen, .allesEinrahmen, .ausblenden, .andereAusblenden, .allesEinblenden, .isolieren,
                        .messen, .masseUmschalten, .masseLoeschen, .elementModus])
        XCTAssertEqual(ohne[1][0].aktiv, false, "ohne Auswahl nichts auszublenden")
        XCTAssertNotNil(ohne[1][0].taste, "Tasten kommen aus der Belegung")

        // iPad: langes Drücken auf ein Teil wählt es aus, das Menü gilt dann ihm
        let bolzen = SceneStore.bodyID(part: "Halter/Bolzen", chunk: 0)
        let treffer = PickResult(rawValue: 0 | (3 << 16), indexMap: [0: bolzen])
        let mit = c.kontextEintraege(treffer: treffer)
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen"])
        XCTAssertEqual(mit[1][0].aktiv, true)
        XCTAssertEqual(mit[0][0].titel, "Auswahl zentrieren")
        c.ausfuehren(mit[1][0].befehl)
        XCTAssertTrue(c.scene.hidden.contains("Halter/Bolzen"), "Ausblenden wirkt auf das gedrückte Teil")

        // Ein Teil, das schon zur Auswahl gehört, lässt die Auswahl stehen
        c.ausfuehren(.allesEinblenden)
        c.select(["Grundplatte", "Halter/Bolzen"])
        _ = c.kontextEintraege(treffer: treffer)
        XCTAssertEqual(c.model.selection.count, 2)
    }
}

/// I-3b: Auswahl erweitern ohne Tastatur („Mehrfach“) und Schwung nach schnellem Loslassen.
@MainActor
final class BeruehrungTests: XCTestCase {
    func testMehrfachNimmtDazuWieUmschalt() throws {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        let platte = SceneStore.bodyID(part: "Grundplatte", chunk: 0)
        let bolzen = SceneStore.bodyID(part: "Halter/Bolzen", chunk: 0)
        func pick(_ o: UInt32) -> PickResult? {
            PickResult(rawValue: o | (3 << 16), indexMap: [0: platte, 1: bolzen])
        }
        c.handleClick(pick(0), modifiers: [])
        c.handleClick(pick(1), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen"], "ohne Mehrfach ersetzt der Tipp")
        c.setzeMehrfach(true)
        XCTAssertTrue(c.model.viewer.mehrfach)
        c.handleClick(pick(0), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen", "Grundplatte"], "Mehrfach nimmt dazu")
        c.handleClick(pick(1), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte"], "… und wieder heraus")
        c.setzeMehrfach(false)
        c.handleClick(pick(1), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen"])
    }

    func testSchwungKlingtAb() {
        XCTAssertNil(Schwung(geschwindigkeit: CGVector(dx: 100, dy: 0)), "langsam losgelassen: kein Schwung")
        guard var s = Schwung(geschwindigkeit: CGVector(dx: 1000, dy: -500)) else { return XCTFail("schnell: Schwung") }
        var weg = CGVector.zero
        var bilder = 0
        while let d = s.schritt(1.0 / 120) {
            weg.dx += d.dx
            weg.dy += d.dy
            bilder += 1
            XCTAssertLessThan(bilder, 240, "nach zwei Sekunden ist Ruhe")
        }
        XCTAssertGreaterThan(bilder, 40, "läuft spürbar nach (über 0,3 s)")
        // Gesamtweg ≈ v · τ (Integral der abklingenden Geschwindigkeit), Richtung bleibt
        XCTAssertEqual(weg.dx, 1000 * CGFloat(Schwung.zeitkonstante), accuracy: 15)
        XCTAssertEqual(weg.dy / weg.dx, -0.5, accuracy: 0.001)
        var t = Schwung(geschwindigkeit: CGVector(dx: 1000, dy: 0))!
        let lang = t.schritt(1.0)!
        XCTAssertLessThanOrEqual(lang.dx, 1000 * 0.05 + 0.001, "ein Hänger von 1 s zählt höchstens 0,05 s")
    }

    func testSchwungAmIPadVorgabeAn() {
        UserDefaults.standard.removeObject(forKey: ViewerStore.schwungKey)
        #if os(iOS)
        XCTAssertTrue(ViewerStore().schwung)
        #else
        XCTAssertFalse(ViewerStore().schwung, "am Mac bleibt es wie in Blender")
        #endif
        XCTAssertNotNil(Tastenbelegung.kranz(.mehr).first { $0.aktion == .schwung }, "abschaltbar im Kranz")
    }
}
