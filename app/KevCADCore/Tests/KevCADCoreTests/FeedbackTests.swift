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

    /// I-5: Vom iPad kommt das Paket als Nutzlast; Kopf und Nutzlast gleich der Testdatei aus dem Kernel.
    func testPaketAlsNutzlastGleichDerTestdatei() throws {
        let rahmen = try Fixtures.frame("feedback_paket_nutzlast.frame")
        let bild = Data([0xFF, 0xD8, 0xFF, 0xD9])
        let json = rahmen.payload.prefix(rahmen.payload.count - bild.count)
        XCTAssertEqual(rahmen.payload.suffix(bild.count), bild)
        var (m, nutzlast) = FeedbackPaketMessage.mitNutzlast(
            sitzung: "s-1793480977", name: "fb-20261105-223011", json: Data(json), bild: bild, saetze: 2, striche: 2,
            dauerS: 9.5)
        m.seq = 13
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()),
                       try JSONDecoder().decode(JSONValue.self, from: rahmen.header))
        XCTAssertEqual(nutzlast, rahmen.payload)
        XCTAssertNil(m.datei)
        // Das JSON in der Nutzlast ist ein gültiges Paket
        XCTAssertEqual(try JSONDecoder().decode(FeedbackPaket.self, from: Data(json)).name, "fb-20261105-223011")
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

/// Wortlaut ohne Wortlaut: ein Dienst, der antwortet, wie der Vertrag es sagt.
private final class FakeDienst: NSObject, SprachdienstProtocol {
    var hallo: (Int, String?) = (1, nil)
    var start: (Bool, String?) = (true, nil)
    var begruesst: [String] = []
    var optionen: [[String: Any]] = []
    var gestoppt = 0

    func hello(client: String, version: Int, reply: @escaping (Int, String?) -> Void) {
        begruesst.append(client)
        reply(hallo.0, hallo.1)
    }

    func startListening(options: [String: Any], reply: @escaping (Bool, String?) -> Void) {
        optionen.append(options)
        reply(start.0, start.1)
    }

    func stopListening(reply: @escaping () -> Void) {
        gestoppt += 1
        reply()
    }
}

private final class FakeVerbindung: WortlautVerbindung {
    let fake: FakeDienst
    var abgebrochen = false

    init(_ fake: FakeDienst) { self.fake = fake }

    var dienst: (any SprachdienstProtocol)? { fake }

    func schliessenNachStopp() { fake.stopListening {} }

    func abbrechen() { abgebrochen = true }
}

@MainActor
final class WortlautErkennungTests: XCTestCase {
    private var ereignisse: [SprachEreignis] = []
    private let fake = FakeDienst()

    private func erkennung() -> WortlautErkennung {
        let f = fake
        let w = WortlautErkennung(verbinder: { _ in FakeVerbindung(f) })
        w.beiEreignis = { [weak self] in self?.ereignisse.append($0) }
        return w
    }

    /// Antworten laufen über den Hauptfaden.
    private func bis(_ bedingung: () -> Bool, frist: Double = 2) async {
        let ende = Date().addingTimeInterval(frist)
        while !bedingung(), Date() < ende { try? await Task.sleep(for: .milliseconds(5)) }
    }

    private func gestartet() async -> WortlautErkennung {
        let w = erkennung()
        w.starten()
        await bis { !fake.optionen.isEmpty }
        w.empfangen(.gestartet(true, nil, 1), leitung: w.leitung)
        w.empfangen(.zustand("listening", nil), leitung: w.leitung)
        return w
    }

    private var zustaende: [SprachZustand] {
        ereignisse.compactMap { if case .zustand(let z) = $0 { return z } else { return nil } }
    }

    private var saetze: [(String, [SprachWort], Double?, Double?)] {
        ereignisse.compactMap {
            if case .satz(let t, let w, let a, let b) = $0 { return (t, w, a, b) } else { return nil }
        }
    }

    func testBegruesstUndHoertMitPauseUndZwischenstaenden() async {
        _ = await gestartet()
        XCTAssertEqual(fake.begruesst, ["Kev CAD"])
        XCTAssertEqual(fake.optionen.first?["pause"] as? Double, 0.6)
        XCTAssertEqual(fake.optionen.first?["partials"] as? Bool, true)
        XCTAssertTrue(zustaende.contains(.hoert))
    }

    func testAbsageBeimHalloIstEinFehler() async {
        fake.hallo = (1, "Wortlaut spricht Fassung 1.")
        let w = erkennung()
        w.starten()
        await bis { zustaende.contains(.fehler("Wortlaut spricht Fassung 1.")) }
        XCTAssertTrue(zustaende.contains(.fehler("Wortlaut spricht Fassung 1.")))
        XCTAssertTrue(fake.optionen.isEmpty, "ohne Begrüßung geht kein Mikrofon an")
    }

    func testBelegtIstEinFehlerMitDemSatzDesDienstes() async {
        fake.start = (false, "Wortlaut hört gerade für Tessera mit.")
        let w = erkennung()
        w.starten()
        await bis { zustaende.contains(.fehler("Wortlaut hört gerade für Tessera mit.")) }
        XCTAssertTrue(zustaende.contains(.fehler("Wortlaut hört gerade für Tessera mit.")))
    }

    func testDienstOhneAntwortGiltNachDerFristAlsFehler() async {
        let w = WortlautErkennung(verbinder: { _ in
            final class Stumm: WortlautVerbindung {
                var dienst: (any SprachdienstProtocol)? { nil }
                func schliessenNachStopp() {}
                func abbrechen() {}
            }
            return Stumm()
        })
        w.startFristS = 0.02
        w.beiEreignis = { [weak self] in self?.ereignisse.append($0) }
        w.starten()
        await bis { zustaende.contains(.fehler("Wortlaut antwortet nicht.")) }
        XCTAssertTrue(zustaende.contains(.fehler("Wortlaut antwortet nicht.")))
    }

    func testSatzBekommtZeitenAusLatenzUndZwischenstaenden() async {
        let w = await gestartet()
        w.empfangen(.zwischenstand("Mach das", 7), leitung: w.leitung)
        w.empfangen(.zwischenstand("Mach das hier", 7), leitung: w.leitung)
        let vorher = ProcessInfo.processInfo.systemUptime
        w.empfangen(.fertig("Mach das hier höher.", 7, 2.7, 0.5), leitung: w.leitung)
        let s = try! XCTUnwrap(saetze.first)
        XCTAssertEqual(s.0, "Mach das hier höher.")
        XCTAssertEqual(s.3!, vorher - 0.5, accuracy: 0.05, "Ende: jetzt minus Latenz")
        XCTAssertEqual(s.3! - s.2!, 2.0, accuracy: 1e-6, "Länge ohne Vor- und Nachlauf des Tons")
        XCTAssertEqual(s.1.map(\.text), ["Mach", "das", "hier", "höher."])
        XCTAssertEqual(s.1.first?.von, s.2)
        XCTAssertEqual(s.1.last?.bis, s.3)
        for (a, b) in zip(s.1, s.1.dropFirst()) { XCTAssertLessThanOrEqual(a.bis, b.von + 1e-9) }
    }

    func testDiktatVerwirftDenAngefangenenSatz() async {
        let w = await gestartet()
        w.empfangen(.zwischenstand("Mach das", 1), leitung: w.leitung)
        w.empfangen(.zustand("paused", nil), leitung: w.leitung)
        XCTAssertTrue(ereignisse.contains { if case .verworfen = $0 { return true } else { return false } })
        XCTAssertTrue(zustaende.contains(.pausiert))
        w.empfangen(.zustand("listening", nil), leitung: w.leitung)
        XCTAssertEqual(zustaende.last, .hoert)
    }

    func testAnhaltenWartetAufDenOffenenSatz() async {
        let w = await gestartet()
        w.empfangen(.zwischenstand("Mach das", 2), leitung: w.leitung)
        let fertig = Task { await w.anhalten(hoechstens: 1) }
        try? await Task.sleep(for: .milliseconds(40))
        XCTAssertEqual(fake.gestoppt, 0, "der Dienst würde den Satz verwerfen")
        w.empfangen(.fertig("Mach das.", 2, 1.5, 0.1), leitung: w.leitung)
        await fertig.value
        XCTAssertEqual(saetze.count, 1)
        XCTAssertEqual(fake.gestoppt, 1)
        XCTAssertEqual(zustaende.last, .aus)
    }

    func testAnhaltenGibtNachDerFristAuf() async {
        let w = await gestartet()
        w.empfangen(.zwischenstand("Mach das", 2), leitung: w.leitung)
        let t0 = Date()
        await w.anhalten(hoechstens: 0.08)
        XCTAssertLessThan(Date().timeIntervalSince(t0), 0.5)
        XCTAssertEqual(fake.gestoppt, 1)
        XCTAssertTrue(saetze.isEmpty, "den Rest nimmt die Sitzung aus dem Zwischenstand")
    }

    func testAnhaltenOhneSatzStopptSofort() async {
        let w = await gestartet()
        let t0 = Date()
        await w.anhalten(hoechstens: 1)
        XCTAssertLessThan(Date().timeIntervalSince(t0), 0.2)
        XCTAssertEqual(fake.gestoppt, 1)
    }

    func testPegelHaeltDasMikrofonNochKurzOffen() async {
        let w = await gestartet()
        w.empfangen(.pegel(0.5), leitung: w.leitung)  // Kevin sagt etwas, der erste Zwischenstand fehlt noch
        let t0 = Date()
        await w.anhalten(hoechstens: 1)
        XCTAssertGreaterThan(Date().timeIntervalSince(t0), 0.3)
    }

    func testVerbindungRissNachAntwortUndAbweisungVorAntwort() async {
        var w = await gestartet()
        w.empfangen(.ungueltig, leitung: w.leitung)
        XCTAssertEqual(zustaende.last, .fehler("Die Verbindung zu Wortlaut ist abgerissen."))

        // Abgewiesen: Der Dienst antwortet nie, die Verbindung bricht ab
        ereignisse = []
        w = WortlautErkennung(verbinder: { _ in
            final class Stumm: WortlautVerbindung {
                var dienst: (any SprachdienstProtocol)? { nil }
                func schliessenNachStopp() {}
                func abbrechen() {}
            }
            return Stumm()
        })
        w.beiEreignis = { [weak self] in self?.ereignisse.append($0) }
        w.starten()
        w.empfangen(.unterbrochen, leitung: w.leitung)
        XCTAssertEqual(zustaende.last, .fehler("Wortlaut nimmt nur signierte Fassungen von Kev CAD an."))
    }

    func testAlteLeitungZaehltNicht() async {
        let w = await gestartet()
        w.empfangen(.zwischenstand("alt", 1), leitung: w.leitung - 1)
        XCTAssertFalse(ereignisse.contains { if case .zwischenstand = $0 { return true } else { return false } })
    }
}

final class WortzeitenTests: XCTestCase {
    func testOhneStuetzenNachLaenge() {
        let w = Wortzeiten.schaetzen(text: "aa aaaaaa", von: 10, bis: 18, stuetzen: [])
        XCTAssertEqual(w.map(\.text), ["aa", "aaaaaa"])
        XCTAssertEqual(w[0].bis, 12, accuracy: 1e-9)
        XCTAssertEqual(w[1].bis, 18, accuracy: 1e-9)
    }

    func testZwischenstaendeZiehenDieWoerterZuIhrerZeit() {
        // Das erste Wort war schon nach 1 s fertig, der Rest kam spät: mit Stütze statt gleichmäßig
        let s = [Wortzeiten.Stuetze(zeichen: 4, zeit: 11 + Wortzeiten.nachlaufS)]
        let w = Wortzeiten.schaetzen(text: "aaaa bbbb", von: 10, bis: 20, stuetzen: s)
        XCTAssertEqual(w[0].bis, 11, accuracy: 1e-9)
        XCTAssertEqual(w[1].von, 11, accuracy: 1e-9)
        XCTAssertEqual(w[1].bis, 20, accuracy: 1e-9)
    }

    func testStuetzenAusserhalbDesSatzesZaehlenNicht() {
        let s = [Wortzeiten.Stuetze(zeichen: 2, zeit: 5), Wortzeiten.Stuetze(zeichen: 3, zeit: 99),
                 Wortzeiten.Stuetze(zeichen: 50, zeit: 12)]
        let w = Wortzeiten.schaetzen(text: "aa bb", von: 10, bis: 14, stuetzen: s)
        XCTAssertEqual(w[0].bis, 12, accuracy: 1e-9)
    }

    func testLeererText() {
        XCTAssertTrue(Wortzeiten.schaetzen(text: "  ", von: 1, bis: 2, stuetzen: []).isEmpty)
    }

    func testFachwoerterMitTeilenOhneDoppelUndNummern() {
        let k = Fachwoerter.kontext(teile: ["Wagen/Laufrolle 3", "Wagen/Laufrolle 4", "Halter/Klemmbacke"])
        XCTAssertTrue(k.contains("Klemmbacke"))
        XCTAssertEqual(k.filter { $0.lowercased() == "laufrolle" }.count, 1)
        XCTAssertLessThanOrEqual(k.count, Fachwoerter.hoechstens)
    }
}

@MainActor
private final class Attrappe: Spracherkennung {
    let kennung: String
    let wortzeiten = "ton"
    var beiEreignis: ((SprachEreignis) -> Void)?
    var gestartet = 0
    var angehalten = 0

    init(_ kennung: String) { self.kennung = kennung }

    func starten() { gestartet += 1 }

    func anhalten(hoechstens s: Double) async { angehalten += 1 }
}

@MainActor
final class RueckfallTests: XCTestCase {
    func testFehlerDerErstenStartetDenRueckfall() async {
        let erste = Attrappe("wortlaut-parakeet"), zweite = Attrappe("apple-dictation")
        let e = ErkennungMitRueckfall(erste: erste, rueckfall: { zweite })
        var meldungen: [SprachZustand] = []
        e.beiEreignis = { if case .zustand(let z) = $0 { meldungen.append(z) } }
        e.starten()
        XCTAssertEqual(e.kennung, "wortlaut-parakeet")
        erste.beiEreignis?(.zustand(.fehler("Wortlaut hört gerade für Tessera mit.")))
        XCTAssertEqual(e.kennung, "apple-dictation")
        XCTAssertEqual(zweite.gestartet, 1)
        XCTAssertEqual(meldungen, [.rueckfall("Wortlaut hört gerade für Tessera mit.")])
        erste.beiEreignis?(.pegel(1))  // die alte Quelle hat nichts mehr zu sagen
        await e.anhalten(hoechstens: 0)
        XCTAssertEqual(zweite.angehalten, 1)
        e.starten()
        XCTAssertEqual(zweite.gestartet, 2, "in dieser Sitzung bleibt es beim Rückfall")
        XCTAssertEqual(erste.gestartet, 1)
    }

    func testFehlerNachDemAnhaltenStartetNichts() async {
        let erste = Attrappe("a"), zweite = Attrappe("b")
        let e = ErkennungMitRueckfall(erste: erste, rueckfall: { zweite })
        e.starten()
        await e.anhalten(hoechstens: 0)
        erste.beiEreignis?(.zustand(.fehler("zu")))
        XCTAssertEqual(zweite.gestartet, 0)
    }

    func testFehlerDesRueckfallsGehtDurch() {
        let erste = Attrappe("a"), zweite = Attrappe("b")
        let e = ErkennungMitRueckfall(erste: erste, rueckfall: { zweite })
        var meldungen: [SprachZustand] = []
        e.beiEreignis = { if case .zustand(let z) = $0 { meldungen.append(z) } }
        e.starten()
        erste.beiEreignis?(.zustand(.fehler("x")))
        zweite.beiEreignis?(.zustand(.fehler("Kein Mikrofon gefunden.")))
        XCTAssertEqual(meldungen.last, .fehler("Kein Mikrofon gefunden."))
    }
}

/// Die Sitzung am echten App-Kern, ohne Fenster, mit Testerkennung.
@MainActor
final class SprachSitzungTests: XCTestCase {
    private func ordner() throws -> URL {
        let u = FileManager.default.temporaryDirectory.appendingPathComponent("fb-sitzung-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: u) }
        return u
    }

    private func aufbau() throws -> (AppController, TestErkennung, URL, () -> [any OutgoingMessage]) {
        let c = AppController(model: AppModel())
        let projekt = try ordner()
        c.model.project = ProjectInfo(path: projekt, name: "P", modelFile: projekt.appendingPathComponent("model.py"))
        let t = TestErkennung()
        c.sprache.erkennungFabrik = { t }
        var nachrichten: [any OutgoingMessage] = []
        c.sprache.gesendet = { nachrichten.append($0) }
        return (c, t, projekt, { nachrichten })
    }

    private func staende(_ n: [any OutgoingMessage]) -> [String] {
        n.compactMap { ($0 as? FeedbackStandMessage).map { $0.stand + ($0.grund.map { "/" + $0 } ?? "") } }
    }

    private func bis(_ bedingung: () -> Bool) async {
        let ende = Date().addingTimeInterval(3)
        while !bedingung(), Date() < ende { try? await Task.sleep(for: .milliseconds(5)) }
    }

    func testVBeginntHaeltAnUndGehtWeiterMitDerselbenSitzung() async throws {
        let (c, _, _, gesendet) = try aufbau()
        c.oberflaeche(.sprechen(true))
        let id = c.sprache.sitzung?.id
        XCTAssertTrue(c.model.oberflaeche.spricht && c.viewport.zeichnen)
        c.oberflaeche(.sprechen(false))
        XCTAssertFalse(c.model.oberflaeche.spricht)
        XCTAssertTrue(c.model.oberflaeche.sitzungOffen && c.sprache.offen)
        XCTAssertFalse(c.viewport.zeichnen, "in der Pause zieht die Maus wieder den Rahmen auf")
        c.oberflaeche(.sprechen(true))
        XCTAssertEqual(c.sprache.sitzung?.id, id)
        XCTAssertEqual(staende(gesendet()), ["spricht", "pause", "spricht"])
        c.oberflaeche(.sprechenVerwerfen)
    }

    func testFertigSchreibtDasPaketUndMeldetEs() async throws {
        let (c, t, projekt, gesendet) = try aufbau()
        var paket: FeedbackPaket?
        c.sprache.beiPaket = { paket = $1 }
        c.oberflaeche(.sprechen(true))
        await t.sagen("Mach das hier höher.", dauer: 0.05)
        c.sprache.maus(nil, nil, CGPoint(x: 10, y: 20))  // eine Probe mitten in der Sitzung (Zugriff auf die Sitzung)
        c.oberflaeche(.sprechenFertig)
        XCTAssertFalse(c.model.oberflaeche.spricht, "der rote Rahmen geht sofort")
        await bis { paket != nil && !c.sprache.offen }
        let p = try XCTUnwrap(paket)
        XCTAssertEqual(p.saetze.map(\.text), ["Mach das hier höher."])
        XCTAssertEqual(p.spracherkennung, "test")
        XCTAssertEqual(p.projekt.pfad, projekt.path)
        let liste = try FileManager.default.contentsOfDirectory(atPath: projekt.appendingPathComponent("feedback").path)
        XCTAssertEqual(liste, [p.name + ".json"], "ohne Teile gibt es kein Bild")
        XCTAssertEqual(staende(gesendet()), ["spricht", "aus/fertig"])
        XCTAssertEqual(gesendet().compactMap { ($0 as? FeedbackPaketMessage)?.name }, [p.name])
        XCTAssertEqual(c.model.oberflaeche.zuletztGesagt, "Mach das hier höher.")
        XCTAssertFalse(c.model.oberflaeche.sitzungOffen)
    }

    func testNachDemEndeZaehltDieMausNicht() async throws {
        let (c, t, _, _) = try aufbau()
        var paket: FeedbackPaket?
        c.sprache.beiPaket = { paket = $1 }
        c.oberflaeche(.sprechen(true))
        await t.sagen("Fertig.", dauer: 0.02)
        c.oberflaeche(.sprechenFertig)
        c.sprache.maus(nil, nil, CGPoint(x: 1, y: 2))  // Kevin bewegt die Maus weiter, bevor die Datei liegt
        await bis { paket != nil }
        let p = try XCTUnwrap(paket)
        XCTAssertTrue(p.mausweg.isEmpty)
    }

    /// I-5: Über das Netz (iPad) geht das Paket als Nutzlast hinaus; im Projektordner entsteht nichts.
    func testUeberDasNetzGehtDasPaketAlsNutzlast() async throws {
        let (c, t, projekt, _) = try aufbau()
        c.sprache.paketMitschicken = true
        var raus: [(FeedbackPaketMessage, Data)] = []
        c.sprache.versand = { m, n in
            if let p = m as? FeedbackPaketMessage { raus.append((p, n)) }
            return true
        }
        c.oberflaeche(.sprechen(true))
        await t.sagen("Mach das hier höher.", dauer: 0.05)
        c.oberflaeche(.sprechenFertig)
        await bis { !raus.isEmpty && !c.sprache.offen }
        let (m, nutzlast) = try XCTUnwrap(raus.first)
        XCTAssertNil(m.datei)
        let n = try XCTUnwrap(m.nutzlast)
        XCTAssertEqual(nutzlast.count, n.json + n.bild)
        let paket = try JSONDecoder().decode(FeedbackPaket.self, from: Data(nutzlast.prefix(n.json)))
        XCTAssertEqual(paket.saetze.map(\.text), ["Mach das hier höher."])
        XCTAssertEqual(paket.name, m.name)
        XCTAssertEqual(paket.projekt.pfad, projekt.path, "der Kernel am Mac legt es dort ab")
        XCTAssertFalse(FileManager.default.fileExists(atPath: projekt.appendingPathComponent("feedback").path))
    }

    /// I-5: Ist der Mac nicht da, wartet das Paket im Postausgang und geht beim nächsten Verbinden los.
    func testOhneVerbindungWartetDasPaketImPostausgang() async throws {
        let (c, t, _, _) = try aufbau()
        c.sprache.paketMitschicken = true
        let ausgang = try ordner()
        c.sprache.postausgangOrdner = ausgang
        var verbunden = false
        var raus: [FeedbackPaketMessage] = []
        c.sprache.versand = { m, _ in
            guard verbunden else { return false }
            if let p = m as? FeedbackPaketMessage { raus.append(p) }
            return true
        }
        func wartend() -> [String] {
            ((try? FileManager.default.contentsOfDirectory(atPath: ausgang.path)) ?? []).sorted()
        }
        c.oberflaeche(.sprechen(true))
        await t.sagen("Später ankommen.", dauer: 0.05)
        c.oberflaeche(.sprechenFertig)
        await bis { !c.sprache.offen && wartend().count == 2 }
        XCTAssertEqual(wartend().map { ($0 as NSString).pathExtension }, ["kopf", "nutzlast"])
        XCTAssertTrue(raus.isEmpty)
        c.sprache.nachVerbindung()  // noch ohne Mac: bleibt liegen
        XCTAssertEqual(wartend().count, 2)
        verbunden = true
        c.sprache.nachVerbindung()
        XCTAssertEqual(raus.count, 1)
        XCTAssertNotNil(raus.first?.nutzlast)
        XCTAssertEqual(wartend(), [], "was hinausging, verlässt den Postausgang")
    }

    func testVerwerfenSchreibtNichts() async throws {
        let (c, t, projekt, gesendet) = try aufbau()
        c.oberflaeche(.sprechen(true))
        await t.sagen("Das soll weg.", dauer: 0.02)
        c.ausfuehren(.abbrechen)  // esc
        XCTAssertFalse(c.sprache.offen)
        XCTAssertFalse(c.model.oberflaeche.sitzungOffen)
        XCTAssertFalse(FileManager.default.fileExists(atPath: projekt.appendingPathComponent("feedback").path))
        XCTAssertEqual(staende(gesendet()), ["spricht", "aus/verworfen"])
    }

    func testOhneWortUndStrichGehtNichtsRaus() async throws {
        let (c, _, projekt, gesendet) = try aufbau()
        c.oberflaeche(.sprechen(true))
        c.oberflaeche(.sprechenFertig)
        await bis { !c.sprache.offen }
        XCTAssertFalse(FileManager.default.fileExists(atPath: projekt.appendingPathComponent("feedback").path))
        XCTAssertFalse(gesendet().contains { $0 is FeedbackPaketMessage })
    }

    func testVerworfenerSatzVerschwindetAusDemText() async throws {
        let (c, t, _, _) = try aufbau()
        c.oberflaeche(.sprechen(true))
        t.beiEreignis?(.zwischenstand("Mach das"))
        XCTAssertEqual(c.model.sprache.text, "Mach das")
        t.beiEreignis?(.verworfen)
        XCTAssertEqual(c.model.sprache.text, "")
        c.oberflaeche(.sprechenVerwerfen)
    }

    func testRestAusDemZwischenstandZaehltAlsVorlaeufig() async throws {
        let (c, t, _, _) = try aufbau()
        var paket: FeedbackPaket?
        c.sprache.beiPaket = { paket = $1 }
        c.oberflaeche(.sprechen(true))
        t.beiEreignis?(.zwischenstand("Mach das hier"))
        c.oberflaeche(.sprechenFertig)
        await bis { paket != nil }
        let p = try XCTUnwrap(paket)
        XCTAssertEqual(p.saetze.first?.vorlaeufig, true)
        XCTAssertEqual(p.worte.count, 3, "auch der Rest bekommt Wörter, damit Zeigewörter greifen")
    }

    func testEinNeuerKernelErfaehrtVonDerOffenenSitzung() async throws {
        let (c, _, _, gesendet) = try aufbau()
        c.oberflaeche(.sprechen(true))
        c.sprache.nachVerbindung()
        XCTAssertEqual(staende(gesendet()), ["spricht", "spricht"])
        c.oberflaeche(.sprechenVerwerfen)
        c.sprache.nachVerbindung()
        XCTAssertEqual(staende(gesendet()).count, 3, "ohne Sitzung gibt es nichts zu melden")
    }

    func testWaehrendKevinSprichtBleibtDieKamera() throws {
        let c = AppController(model: AppModel())
        c.sprache.erkennungFabrik = { TestErkennung() }
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(2)))  // HELLO, PROJECT
        c.oberflaeche(.sprechen(true))
        XCTAssertTrue(c.sprache.spricht)
        let vorher = c.viewport.camera
        c.handle(Array(events[2..<7]))  // ein Lauf mit Teilen; ohne Sitzung passt die Ansicht sich ein
        XCTAssertFalse(c.scene.isEmpty, "die Teile erscheinen")
        XCTAssertEqual(c.viewport.camera.position, vorher.position)
        XCTAssertEqual(c.viewport.camera.distance, vorher.distance)
        c.oberflaeche(.sprechenVerwerfen)
    }

    func testEingabeTasteGehoertDerOffenenSitzung() async throws {
        let (c, _, _, _) = try aufbau()
        c.oberflaeche(.sprechen(true))
        c.ausfuehren(.messungAbschliessen)
        await bis { !c.sprache.offen }
        XCTAssertFalse(c.sprache.offen)
    }
}

final class SprechenZustandTests: XCTestCase {
    func testPauseLaesstDieSitzungOffen() {
        var z = OberflaechenZustand()
        z.anwenden(.sprechen(true))
        XCTAssertTrue(z.spricht && z.sitzungOffen)
        z.anwenden(.sprechen(false))
        XCTAssertTrue(!z.spricht && z.sitzungOffen)
        z.anwenden(.sprechText("Gesagt"))
        z.anwenden(.sprechenFertig)
        XCTAssertFalse(z.sitzungOffen)
        XCTAssertEqual(z.zuletztGesagt, "Gesagt")
        z.anwenden(.sprechen(true))
        z.anwenden(.sprechText("Weg damit"))
        z.anwenden(.sprechenVerwerfen)
        XCTAssertFalse(z.sitzungOffen)
        XCTAssertEqual(z.zuletztGesagt, "Gesagt", "Verworfenes bleibt nicht stehen")
    }
}
