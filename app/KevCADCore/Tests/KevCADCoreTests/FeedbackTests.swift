import XCTest

@testable import KevCADCore

/// V2-6 Sprach-Feedback (PROTOCOL.md, „V2-6 Sprach-Feedback“): Format gegen die Testdateien aus
/// `make_feedback_fixtures.py`, Uhr, Bezüge, atomares Schreiben.
final class FeedbackFormatTests: XCTestCase {
    private func beispiel() throws -> Data { try Fixtures.data("feedback_beispiel.json") }

    func testBeispielpaketGehtVerlustfreiHinUndZurueck() throws {
        let paket = try JSONDecoder().decode(FeedbackPaket.self, from: beispiel())
        XCTAssertEqual(paket.format, FeedbackGrenzen.format)
        XCTAssertEqual(paket.saetze.count, 2)
        XCTAssertEqual(paket.saetze[0].bezuege.first?.wort, "hier")
        XCTAssertEqual(paket.striche[1].punkte[0].ref, nil)
        let zurueck = try JSONDecoder().decode(JSONValue.self, from: paket.json())
        let vorlage = try JSONDecoder().decode(JSONValue.self, from: beispiel())
        XCTAssertEqual(zurueck, vorlage, "Swift schreibt dasselbe wie die Referenz, auch alle null")
    }

    func testNachrichtenGleichDenTestdateien() throws {
        func kopf(_ datei: String) throws -> JSONValue {
            try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame(datei).header)
        }
        var a = FeedbackStandMessage(sitzung: "s-1793480977", stand: .spricht, seit: 1793480977.25)
        a.seq = 9
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: a.encodedHeader()),
                       try kopf("feedback_stand_spricht.frame"))
        var b = FeedbackStandMessage(sitzung: "s-1793480977", stand: .aus, seit: 1793480986.75, grund: .fertig)
        b.seq = 11
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: b.encodedHeader()),
                       try kopf("feedback_stand_aus.frame"))
        var c = FeedbackPaketMessage(
            sitzung: "s-1793480977", name: "fb-20261105-223011",
            datei: "/Users/kevin/Documents/Kev CAD/Halter/feedback/fb-20261105-223011.json", saetze: 2, striche: 2,
            dauerS: 9.5)
        c.seq = 12
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: c.encodedHeader()),
                       try kopf("feedback_paket.frame"))
    }

    func testGrenzenGleichDerReferenz() throws {
        let f = try XCTUnwrap(Fixtures.expected()["feedback"])
        XCTAssertEqual(f["format"]?.stringValue, FeedbackGrenzen.format)
        XCTAssertEqual(Set(f["zeigewoerter"]?.stringList ?? []), FeedbackGrenzen.zeigewoerter)
    }
}

final class FeedbackSitzungTests: XCTestCase {
    private typealias P = FeedbackPaket
    private let kamera = JSONValue.object(["abstand": .number(100)])

    private func sitzung() -> FeedbackSitzung { FeedbackSitzung(id: "s-1", uhrStart: 1000, uhrNull: 50) }

    private func probe(_ t: Double, _ ref: String?) -> P.MausProbe {
        P.MausProbe(t: t, bild: [10, 20], teil: ref?.split(separator: "#").first.map(String.init), ref: ref,
                    run: ref == nil ? nil : 3)
    }

    private func worte(_ w: (String, Double, Double)...) -> [FeedbackSitzung.RohWort] {
        w.map { .init(text: $0.0, von: $0.1, bis: $0.2) }
    }

    func testUhrRechnetUptimeAufDieSitzung() {
        let s = sitzung()
        XCTAssertEqual(s.zeit(uptime: 52.5), 2.5)
        XCTAssertEqual(s.zeit(uptime: 40), 0, "nichts liegt vor dem Beginn")
    }

    func testMausDrosseltAberBehaeltJedenWechsel() {
        var s = sitzung()
        s.maus(probe(0.00, "A#f1"))
        s.maus(probe(0.02, "A#f1"))  // gedrosselt
        s.maus(probe(0.03, "B#f2"))  // Wechsel zählt immer
        s.maus(probe(0.05, "A#f1"))
        s.maus(probe(0.20, "A#f1"))
        XCTAssertEqual(s.mausweg.map(\.t), [0.00, 0.03, 0.05, 0.20])
    }

    func testZeigerNimmtDasTeilUnterDerMausZumZeigewort() {
        // Maus auf A, wandert kurz über B (0,1 s, zählt nur dank Zeigewort), weiter auf C
        var s = sitzung()
        s.maus(probe(0.0, "A#f1"))
        s.maus(probe(1.5, "B#f2"))
        s.maus(probe(1.6, "C#f3"))
        s.maus(probe(3.0, nil))
        s.satz(text: "Mach hier mehr.", von: 1.0, bis: 2.0,
               worte: worte(("Mach", 1.0, 1.3), ("hier", 1.5, 1.6), ("mehr.", 1.65, 2.0)))
        let (saetze, w) = s.saetzeMitBezuegen(run: 3)
        let z = saetze[0].bezuege
        XCTAssertEqual(z.map(\.ref), ["A#f1", "B#f2", "C#f3"])
        XCTAssertEqual(z.map(\.wort), [nil, "hier", nil])
        XCTAssertEqual(z[0].t, 0.5, "Fenster beginnt 0,5 s vor dem Satz")
        XCTAssertEqual(z[2].bis, 2.3, accuracy: 1e-9, "Fenster endet 0,3 s nach dem Satz")
        XCTAssertEqual(w.map(\.satz), [1, 1, 1])
    }

    func testZeigewortSuchtDasNaechsteTeilInDerNaehe() {
        var s = sitzung()
        s.maus(probe(0.0, nil))
        s.maus(probe(1.9, "A#f1"))  // Kevin sagt „da“, ist 0,3 s später auf dem Teil
        s.maus(probe(3.0, nil))
        s.satz(text: "Hier.", von: 1.5, bis: 1.7, worte: worte(("Hier.", 1.5, 1.7)))
        let z = s.saetzeMitBezuegen(run: 3).saetze[0].bezuege
        XCTAssertEqual(z.map(\.ref), ["A#f1"])
        XCTAssertEqual(z[0].wort, "hier")
    }

    func testKurzesUeberstreichenOhneZeigewortZaehltNicht() {
        var s = sitzung()
        s.maus(probe(0.0, nil))
        s.maus(probe(1.0, "A#f1"))
        s.maus(probe(1.1, nil))
        s.satz(text: "Etwas anderes.", von: 0.5, bis: 2.0, worte: worte(("Etwas", 0.5, 1.0), ("anderes.", 1.0, 2.0)))
        XCTAssertTrue(s.saetzeMitBezuegen(run: 3).saetze[0].bezuege.isEmpty)
    }

    func testHoechstensSechsZeigerZeigewortGehtVor() {
        var s = sitzung()
        for i in 0..<9 { s.maus(probe(Double(i) * 0.3, "T\(i)#f1")) }
        s.maus(probe(2.7, nil))
        s.satz(text: "Lang.", von: 0, bis: 3, worte: worte(("Das", 0.1, 0.2), ("Lang.", 2.5, 3)))
        let z = s.saetzeMitBezuegen(run: 3).saetze[0].bezuege
        XCTAssertEqual(z.count, FeedbackGrenzen.zeigerJeSatz)
        XCTAssertEqual(z[0].ref, "T0#f1", "der Zeiger mit Zeigewort bleibt")
        XCTAssertEqual(z.map(\.t), z.map(\.t).sorted())
    }

    func testStrichGehoertZumSatzMitDerLaengstenUeberschneidung() {
        var s = sitzung()
        s.satz(text: "Erst.", von: 0, bis: 2, worte: worte(("Erst.", 0, 2)))
        s.satz(text: "Dann.", von: 2.2, bis: 5, worte: worte(("Dann.", 2.2, 5)))
        s.strichBeginnen(t: 1.5, run: 3, kamera: kamera)
        s.strichPunkt(.init(t: 1.5, bild: [0, 0], welt: [0, 0, 0], ref: "A#f1"), teil: "A")
        s.strichPunkt(.init(t: 3.5, bild: [1, 0], welt: [30, 40, 0], ref: nil), teil: nil)
        s.strichEnden(t: 3.6)
        let saetze = s.saetzeMitBezuegen(run: 3).saetze
        XCTAssertTrue(saetze[0].bezuege.isEmpty)
        XCTAssertEqual(saetze[1].bezuege.map(\.strich), [1])
        XCTAssertEqual(s.striche[0].laengeMm, 50, accuracy: 1e-9)
        XCTAssertEqual(s.striche[0].teile, ["A"])
        XCTAssertEqual(s.striche[0].bis, 3.6)
    }

    func testStrichNachDemLetztenSatzGehtZumNaechsten() {
        var s = sitzung()
        s.satz(text: "Erst.", von: 0, bis: 1, worte: worte(("Erst.", 0, 1)))
        s.satz(text: "Dann.", von: 2, bis: 3, worte: worte(("Dann.", 2, 3)))
        s.strichBeginnen(t: 4, run: 3, kamera: kamera)
        s.strichPunkt(.init(t: 4, bild: [0, 0], welt: [0, 0, 0], ref: nil), teil: nil)
        s.strichEnden(t: 4.5)
        XCTAssertEqual(s.saetzeMitBezuegen(run: 3).saetze[1].bezuege.map(\.strich), [1])
    }

    func testErgebnisMitZweiSaetzenWirdGeteilt() {
        var s = sitzung()
        s.satz(text: "Eins zwei. Drei.", von: 0, bis: 3,
               worte: worte(("Eins", 0, 0.5), ("zwei.", 0.6, 1), ("Drei.", 2, 3)))
        XCTAssertEqual(s.saetze.map(\.text), ["Eins zwei.", "Drei."])
        XCTAssertEqual(s.saetze.map(\.von), [0, 2])
    }

    func testSatzOhneWortzeitenBleibtGanz() {
        var s = sitzung()
        s.satz(text: "Ohne Zeiten. Trotzdem da.", von: 1, bis: 2, worte: [], vorlaeufig: true)
        XCTAssertEqual(s.saetze.count, 1)
        XCTAssertTrue(s.saetze[0].vorlaeufig)
    }

    func testAbschnitteFolgenDemMikrofon() {
        var s = sitzung()
        s.mikrofonAn(t: 0)
        s.mikrofonAn(t: 0.5)  // kein zweiter Beginn
        s.mikrofonAus(t: 2)
        s.mikrofonAus(t: 3)  // kein zweites Ende
        s.mikrofonAn(t: 4)
        let p = s.paket(name: "fb-20261105-223011", erstellt: Date(timeIntervalSince1970: 1000), dauer: 5,
                        spracherkennung: "test", projekt: .init(name: "P", pfad: "/p"), run: 3, ende: .object([:]),
                        bild: nil)
        XCTAssertEqual(p.abschnitte, [.init(von: 0, bis: 2), .init(von: 4, bis: 5)])
    }

    func testSatzBekommtKameraUndAuswahlSeinerZeit() {
        var s = sitzung()
        let k1 = JSONValue.object(["abstand": .number(1)]), k2 = JSONValue.object(["abstand": .number(2)])
        s.kamera(t: 0, k1)
        s.kamera(t: 0.1, k2)  // gedrosselt
        s.kamera(t: 3, k2)
        s.auswahl(t: 0, run: 3, refs: [])
        s.auswahl(t: 2, run: 3, refs: ["A"])
        s.satz(text: "Früh.", von: 1, bis: 1.5, worte: worte(("Früh.", 1, 1.5)))
        s.satz(text: "Spät.", von: 3.5, bis: 4, worte: worte(("Spät.", 3.5, 4)))
        let saetze = s.saetzeMitBezuegen(run: 3).saetze
        XCTAssertEqual(saetze[0].kamera, k1)
        XCTAssertEqual(saetze[1].kamera, k2)
        XCTAssertEqual(saetze[0].auswahl.refs, [])
        XCTAssertEqual(saetze[1].auswahl.refs, ["A"])
    }
}

final class FeedbackAblageTests: XCTestCase {
    private func leererOrdner() throws -> URL {
        let u = FileManager.default.temporaryDirectory.appendingPathComponent("fb-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: u) }
        return u
    }

    private func paket(_ name: String) throws -> FeedbackPaket {
        var p = try JSONDecoder().decode(FeedbackPaket.self, from: Fixtures.data("feedback_beispiel.json"))
        p.name = name
        p.bild = .init(datei: name + ".jpg", breite: 4, hoehe: 2)
        return p
    }

    func testSchreibtBildUndJsonOhneZwischendateien() throws {
        let ordner = try leererOrdner()
        let ziel = try FeedbackAblage.schreiben(paket("fb-20261105-223011"), bild: Data([1, 2, 3]), in: ordner)
        let dateien = try FileManager.default.contentsOfDirectory(atPath: ordner.path).sorted()
        XCTAssertEqual(dateien, ["fb-20261105-223011.jpg", "fb-20261105-223011.json"])
        let gelesen = try JSONDecoder().decode(FeedbackPaket.self, from: Data(contentsOf: ziel))
        XCTAssertEqual(gelesen.name, "fb-20261105-223011")
    }

    func testNameWeichtBeiGleicherSekundeAus() throws {
        let ordner = try leererOrdner()
        let datum = Date(timeIntervalSince1970: 1793480977)
        let n1 = FeedbackAblage.name(in: ordner, datum: datum)
        try FeedbackAblage.schreiben(paket(n1), bild: nil, in: ordner)
        let n2 = FeedbackAblage.name(in: ordner, datum: datum)
        try FeedbackAblage.schreiben(paket(n2), bild: nil, in: ordner)
        XCTAssertEqual(n2, n1 + "-2")
        XCTAssertEqual(FeedbackAblage.name(in: ordner, datum: datum), n1 + "-3")
    }
}
