import Foundation
import XCTest
import simd

@testable import KevCADCore

/// V2-5 Live (PROTOCOL.md, „V2-5 Live“): Nachrichten gegen die Testdateien aus `make_live_fixtures.py`, Delta,
/// Selbstheilung und was die App je Verbindung führt.
@MainActor
final class LiveTests: XCTestCase {
    private func expected() throws -> JSONValue { try XCTUnwrap(Fixtures.expected()["live"]) }

    private func json(_ data: Data) throws -> JSONValue { try JSONDecoder().decode(JSONValue.self, from: data) }

    /// Ereignis aus einem JSON-Kopf ohne Nutzlast.
    private func nachricht(_ kopf: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(kopf.utf8))))
    }

    /// Teil aus der Testdatei mit eigenem Namen und Inhalt; `z` verschiebt die Punkte (andere Geometrie).
    private func teil(_ name: String, _ inhalt: String?, run: Int = 1, z: Float = 0) throws -> PartRecord {
        var (h, g) = try Fixtures.part("live_part_upsert.frame")
        h.name = name
        h.run = run
        h.inhalt = inhalt
        for i in stride(from: 2, to: g.positions.count, by: 3) { g.positions[i] += z }
        return PartRecord(header: h, geometry: g)
    }

    /// Controller mit bestehender Verbindung; `gesendet` sammelt, was an den Kernel geht.
    private func verbunden(faehigkeiten: [String] = LiveFaehigkeit.app) throws -> (AppController, Gesendet) {
        let c = AppController(model: AppModel())
        let g = Gesendet()
        c.sendeBeobachter = { g.rahmen.append($0) }
        c.handle([.connected])
        let liste = faehigkeiten.map { "\"\($0)\"" }.joined(separator: ",")
        c.handle([try nachricht(#"{"type":"HELLO","seq":1,"protocol":1,"faehigkeiten":[\#(liste)]}"#)])
        g.rahmen = []
        return (c, g)
    }

    private final class Gesendet {
        var rahmen: [Frame] = []
        func koepfe(_ typ: String) throws -> [JSONValue] {
            try rahmen.map { try JSONDecoder().decode(JSONValue.self, from: $0.header) }
                .filter { $0["type"]?.stringValue == typ }
        }
    }

    private func laufStart(_ run: Int, delta: Bool = true) throws -> IncomingEvent {
        try nachricht(#"{"type":"RUN_START","run":\#(run),"delta":\#(delta)}"#)
    }

    private func laufEnde(_ run: Int, _ teile: [String]) throws -> IncomingEvent {
        let liste = teile.map { "\"\($0)\"" }.joined(separator: ",")
        return try nachricht(#"{"type":"RUN_END","run":\#(run),"duration_ms":5,"parts":\#(teile.count),"triangles":1,"warnings":[],"teile":[\#(liste)]}"#)
    }

    private func gleich(_ run: Int, _ name: String, _ inhalt: String) -> IncomingEvent {
        .message(.partSame(PartSameMessage(run: run, name: name, inhalt: inhalt)))
    }

    // MARK: Nachrichten

    func testAlleRahmenSindLesbar() throws {
        for f in try XCTUnwrap(try expected()["frames"]?.arrayValue) {
            let datei = try XCTUnwrap(f["file"]?.stringValue)
            let rahmen = try Fixtures.frame(datei)
            XCTAssertEqual(rahmen.payload.count, f["payload_bytes"]?.intValue, datei)
            guard f["richtung"]?.stringValue == "kernel", f["type"]?.stringValue != "WIE_ZUVOR" else { continue }
            let m = try KernelMessage.decode(rahmen)
            XCTAssertEqual(m.typeName, f["type"]?.stringValue, datei)
            if case .unknown = m { XCTFail("\(datei) nicht erkannt") }
        }
    }

    func testFaehigkeitenUndNeueFelder() throws {
        guard case .hello(let h) = try Fixtures.message("live_hello.frame") else { return XCTFail() }
        XCTAssertEqual(h.faehigkeiten, try expected()["kernel_faehigkeiten"]?.stringList)
        guard case .runStart(let r) = try Fixtures.message("live_run_start.frame") else { return XCTFail() }
        XCTAssertEqual(r.delta, true)
        guard case .runEnd(let e) = try Fixtures.message("live_run_end.frame") else { return XCTFail() }
        XCTAssertEqual(e.teile, ["Halter/Grundplatte", "Halter/Lasche"])
        let (kopf, _) = try Fixtures.part("live_part_upsert.frame")
        XCTAssertEqual(kopf.inhalt, try expected()["part_upsert_inhalt"]?.stringValue)
        guard case .partSame(let s) = try Fixtures.message("live_part_same.frame") else { return XCTFail() }
        XCTAssertEqual(s, PartSameMessage(run: 8, name: "Halter/Grundplatte", inhalt: "9c1d2e3f4a5b6c7d"))
        XCTAssertEqual(LiveGrenzen.teilInhalte, try expected()["teil_inhalte"]?.intValue)
        XCTAssertEqual(LiveGrenzen.wieZuvorBasen, try expected()["wie_zuvor_basen"]?.intValue)
        XCTAssertEqual(LiveGrenzen.wieZuvorArten, Set(try XCTUnwrap(try expected()["wie_zuvor_arten"]?.stringList)))
    }

    func testRahmenDerAppGleichDenTestdateien() throws {
        var hello = HelloAppMessage(appVersion: "2.0", bundleID: "de.upvis.kevcad",
                                    faehigkeiten: try XCTUnwrap(try expected()["kernel_faehigkeiten"]?.stringList))
        hello.seq = 1
        XCTAssertEqual(try json(hello.encodedHeader()), try json(Fixtures.frame("live_hello_app.frame").header))
        var nochmal = NochmalMessage(art: "CHECK")
        nochmal.seq = 4
        XCTAssertEqual(try json(nochmal.encodedHeader()), try json(Fixtures.frame("live_nochmal.frame").header))
        var teile = PartsRequestMessage(teile: ["Halter/Lasche"])
        teile.seq = 5
        XCTAssertEqual(try json(teile.encodedHeader()), try json(Fixtures.frame("live_parts_req.frame").header))
        XCTAssertEqual(try json(PartsRequestMessage(teile: nil).encodedHeader())["teile"], .null)
    }

    // MARK: WIE_ZUVOR

    private func umschlag(_ f: Frame) throws -> MessageEnvelope { try JSONDecoder().decode(MessageEnvelope.self, from: f.header) }

    func testWieZuvorBautDenRahmenAuf() throws {
        let speicher = WieZuvorSpeicher()
        let basis = try Fixtures.frame("live_check_basis.frame")
        guard case .rahmen = speicher.empfangen(basis, envelope: try umschlag(basis)) else { return XCTFail() }
        let wz = try Fixtures.frame("live_wie_zuvor.frame")
        guard case .rahmen(let f, let env) = speicher.empfangen(wz, envelope: try umschlag(wz)) else { return XCTFail() }
        XCTAssertEqual(env.type, "CHECK")
        XCTAssertEqual(env.seq, 41)
        XCTAssertEqual(try json(f.header), try expected()["wie_zuvor"]?["ergebnis"])
        guard case .check(let c) = try KernelMessage.decode(f) else { return XCTFail("kein CHECK") }
        XCTAssertEqual(c.ergebnis.run, 8)
        // Der aufgebaute Rahmen zählt als Basis für später
        let weiter = Frame(header: Data(#"{"type":"WIE_ZUVOR","seq":42,"art":"CHECK","basis":41,"setzen":[[["run"],9],[["neu"],{"a":[1,2]}],[["neu","a",1],5]],"weg":[["zusammenfassung"]]}"#.utf8))
        guard case .rahmen(let f2, _) = speicher.empfangen(weiter, envelope: try umschlag(weiter)) else { return XCTFail() }
        let k = try json(f2.header)
        XCTAssertEqual(k["run"]?.intValue, 9)
        XCTAssertEqual(k["seq"]?.intValue, 42)
        XCTAssertEqual(k["neu"]?["a"], [1, 5])
        XCTAssertNil(k["zusammenfassung"])
        XCTAssertEqual(k["befunde"], try expected()["wie_zuvor"]?["ergebnis"]?["befunde"])
    }

    func testWieZuvorGanzzahlBleibtGanzzahl() throws {
        let speicher = WieZuvorSpeicher()
        let basis = Frame(header: Data(#"{"type":"BOM","seq":3,"run":7,"anteil":1.5,"an":true}"#.utf8), payload: Data([1, 2]))
        _ = speicher.empfangen(basis, envelope: try umschlag(basis))
        let wz = Frame(header: Data(#"{"type":"WIE_ZUVOR","seq":4,"art":"BOM","basis":3,"setzen":[[["run"],8]],"weg":[]}"#.utf8))
        guard case .rahmen(let f, _) = speicher.empfangen(wz, envelope: try umschlag(wz)) else { return XCTFail() }
        let text = try XCTUnwrap(String(data: f.header, encoding: .utf8))
        XCTAssertTrue(text.contains("\"run\":8"), text)
        XCTAssertTrue(text.contains("\"an\":true"), text)
        XCTAssertEqual(f.payload, Data([1, 2]), "Nutzlast der Basis")
    }

    func testWieZuvorBasisFehltOderPasstNicht() throws {
        let speicher = WieZuvorSpeicher()
        let wz = try Fixtures.frame("live_wie_zuvor.frame")
        guard case .fehlt(let art, _) = speicher.empfangen(wz, envelope: try umschlag(wz)) else { return XCTFail() }
        XCTAssertEqual(art, "CHECK")
        let basis = Frame(header: Data(#"{"type":"CHECK","seq":40,"run":1}"#.utf8))
        _ = speicher.empfangen(basis, envelope: try umschlag(basis))
        let falsch = Frame(header: Data(#"{"type":"WIE_ZUVOR","seq":41,"art":"CHECK","basis":40,"setzen":[[["gibt","es","nicht"],1]],"weg":[]}"#.utf8))
        guard case .fehlt = speicher.empfangen(falsch, envelope: try umschlag(falsch)) else { return XCTFail() }
    }

    func testWieZuvorHaeltSechsBasenOhneAntworten() throws {
        let speicher = WieZuvorSpeicher()
        for seq in 1...8 {
            let f = Frame(header: Data(#"{"type":"SIM","seq":\#(seq)}"#.utf8))
            _ = speicher.empfangen(f, envelope: try umschlag(f))
        }
        XCTAssertEqual(speicher.anzahl("SIM"), 6)
        let antwort = Frame(header: Data(#"{"type":"SIM","seq":9,"reply_to":"a-1"}"#.utf8))
        _ = speicher.empfangen(antwort, envelope: try umschlag(antwort))
        XCTAssertEqual(speicher.anzahl("SIM"), 6)
        let alt = Frame(header: Data(#"{"type":"WIE_ZUVOR","seq":10,"art":"SIM","basis":2,"setzen":[],"weg":[]}"#.utf8))
        guard case .fehlt = speicher.empfangen(alt, envelope: try umschlag(alt)) else { return XCTFail("Basis 2 ist verdrängt") }
    }

    func testBasisFehltFordertNeuAn() throws {
        let (c, g) = try verbunden()
        c.handle([.basisFehlt("STATICS", "Basis 3 von STATICS unbekannt")])
        XCTAssertEqual(try g.koepfe("NOCHMAL").compactMap { $0["art"]?.stringValue }, ["STATICS"])
    }

    // MARK: Inhalte je Teil

    func testInhalteHaltenVierJeTeil() throws {
        var s = TeilInhalte()
        for k in 1...5 { s.merken(try teil("A", "i\(k)")) }
        XCTAssertEqual(s.schluessel("A"), ["i2", "i3", "i4", "i5"])
        XCTAssertFalse(s.hat("A", "i1"))
        XCTAssertNotNil(s.zeigen("A", "i2"))
        XCTAssertEqual(s.schluessel("A"), ["i3", "i4", "i5", "i2"], "der gezeigte zuletzt")
        s.merken(try teil("A", "i6"))
        XCTAssertEqual(s.schluessel("A"), ["i4", "i5", "i2", "i6"], "der älteste geht, nicht der vorher gezeigte")
        XCTAssertNil(s.zeigen("A", "i3"))
        s.merken(try teil("A", nil))
        XCTAssertEqual(s.schluessel("A"), [], "ohne Schlüssel bleibt nichts, worauf PART_SAME sich beziehen könnte")
        s.merken(try teil("B", "b"))
        s.vergessen("B")
        XCTAssertFalse(s.hat("B", "b"))
    }

    // MARK: Delta

    func testUnveraenderterLaufLaesstDasBildInRuhe() throws {
        let (c, g) = try verbunden()
        c.handle([try laufStart(1, delta: false), .part(try teil("A", "a1")), .part(try teil("B", "b1", z: 5)),
                  try laufEnde(1, ["A", "B"])])
        c.setVisibility(["B"], visible: false)
        c.applySelection([.face("A", 0)])
        g.rahmen = []
        let vorher = c.scene.statistik
        c.handle([try laufStart(2), gleich(2, "A", "a1"), gleich(2, "B", "b1"), try laufEnde(2, ["A", "B"])])
        XCTAssertEqual(c.scene.statistik, vorher, "nichts neu gebaut, nichts leuchtet auf, nichts an den Viewport")
        XCTAssertEqual(c.scene.record("A")?.run, 2)
        XCTAssertEqual(c.model.parts.map(\.run), [2, 2])
        XCTAssertFalse(c.scene.isVisible("B"), "Sichtbarkeit bleibt")
        XCTAssertEqual(c.scene.selection, [.face("A", 0)], "Auswahl bleibt")
        XCTAssertEqual(try g.koepfe("SELECTION").last?["run"]?.intValue, 2, "der Kernel kennt die Auswahl zum neuen Lauf")
        XCTAssertEqual(try g.koepfe("PARTS_REQ").count, 0)
    }

    func testAbdunkelnErstNachVerzoegerungUndBestaetigtHellt() throws {
        let (c, _) = try verbunden()
        c.handle([.part(try teil("A", "a1")), .part(try teil("B", "b1", z: 5))])
        c.handle([try laufStart(2), gleich(2, "A", "a1")])
        let hell = c.scene.displayColor("B", now: 0, includeFlash: false)
        c.scene.dimOpenParts(run: 2)  // wie nach 2 s
        XCTAssertLessThan(c.scene.displayColor("B", now: 0, includeFlash: false).x, hell.x, "offenes Teil ist dunkel")
        XCTAssertEqual(c.scene.displayColor("A", now: 0, includeFlash: false).x, hell.x, "bestätigtes nicht")
        c.handle([gleich(2, "B", "b1")])
        XCTAssertEqual(c.scene.displayColor("B", now: 0, includeFlash: false).x, hell.x, "abdunkeln endet mit PART_SAME")
    }

    func testFruehererInhaltKommtOhneUebertragungZurueck() throws {
        let (c, g) = try verbunden()
        let alt = try teil("A", "a1"), neu = try teil("A", "a2", run: 2, z: 7)
        c.handle([.part(alt)])
        c.handle([try laufStart(2), .part(neu), try laufEnde(2, ["A"])])
        XCTAssertEqual(c.scene.record("A")?.digest, neu.digest)
        c.handle([try laufStart(3), gleich(3, "A", "a1"), try laufEnde(3, ["A"])])
        XCTAssertEqual(c.scene.record("A")?.digest, alt.digest, "Kopf und Netz aus dem Speicher")
        XCTAssertEqual(c.scene.record("A")?.run, 3)
        XCTAssertEqual(try g.koepfe("PARTS_REQ").count, 0)
        XCTAssertEqual(c.live.inhalte.schluessel("A"), ["a2", "a1"])
    }

    func testFehlenderInhaltHeiltSichUndZeigtNichtsFalsches() throws {
        let (c, g) = try verbunden()
        c.handle([.part(try teil("A", "a1"))])
        c.handle([try laufStart(2), gleich(2, "A", "gibt-es-nicht"), gleich(2, "B", "auch-nicht"), try laufEnde(2, ["A", "B"])])
        XCTAssertEqual(try g.koepfe("PARTS_REQ").flatMap { $0["teile"]?.stringList ?? [] }, ["A", "B"], "einmal je Teil")
        XCTAssertEqual(c.scene.record("A")?.run, 1, "das alte Teil gilt nicht für diesen Lauf")
        XCTAssertTrue(c.scene.veraltet.contains("A"), "und bleibt dunkel, bis der Kernel es schickt")
        let dunkel = c.scene.displayColor("A", now: 0, includeFlash: false)
        c.handle([.part(try teil("A", "a2", run: 2, z: 3)), .part(try teil("B", "b1", run: 2, z: 9))])
        XCTAssertTrue(c.scene.veraltet.isEmpty)
        XCTAssertGreaterThan(c.scene.displayColor("A", now: 0, includeFlash: false).x, dunkel.x)
        XCTAssertEqual(c.scene.order, ["A", "B"])
    }

    func testRunEndEntferntUndPartRemoveVergisst() throws {
        let (c, _) = try verbunden()
        c.handle([.part(try teil("A", "a1")), .part(try teil("B", "b1", z: 1)), .part(try teil("C", "c1", z: 2))])
        c.handle([try laufStart(2), gleich(2, "A", "a1"),
                  try nachricht(#"{"type":"PART_REMOVE","run":2,"name":"B"}"#), try laufEnde(2, ["A"])])
        XCTAssertEqual(c.scene.order, ["A"], "B über PART_REMOVE, C über die Liste")
        XCTAssertFalse(c.live.inhalte.hat("B", "b1"))
        XCTAssertFalse(c.live.inhalte.hat("C", "c1"))
    }

    func testGeaendertesTeilVerliertFlaechenInDerAuswahl() throws {
        let (c, _) = try verbunden()
        c.handle([.part(try teil("A", "a1")), .part(try teil("B", "b1", z: 1))])
        c.applySelection([.face("A", 0), .part("B")])
        c.handle([try laufStart(2), .part(try teil("A", "a2", run: 2, z: 4)), .part(try teil("B", "b2", run: 2, z: 5)),
                  try laufEnde(2, ["A", "B"])])
        XCTAssertEqual(c.scene.selection, [.part("B")])
        XCTAssertEqual(c.model.selection.map(\.ref), ["B"])
    }

    func testNeueVerbindungBeginntLeer() throws {
        let (c, g) = try verbunden()
        c.handle([.part(try teil("A", "a1"))])
        c.handle([.disconnected("weg"), .connected])
        c.handle([try nachricht(#"{"type":"HELLO","seq":1,"protocol":1,"faehigkeiten":["delta-1"]}"#)])
        XCTAssertFalse(c.live.inhalte.hat("A", "a1"))
        g.rahmen = []
        c.handle([gleich(2, "A", "a1")])
        XCTAssertEqual(try g.koepfe("PARTS_REQ").count, 1, "was vor der Verbindung kam, zählt nicht mehr")
    }

    func testInhalteUeberlebenDasLeerenDerSzene() throws {
        let (c, g) = try verbunden()
        c.handle([try nachricht(#"{"type":"PROJECT","path":"/tmp/eins","name":"eins"}"#), .part(try teil("A", "a1"))])
        c.handle([try nachricht(#"{"type":"PROJECT","path":"/tmp/zwei","name":"zwei"}"#)])
        XCTAssertTrue(c.scene.isEmpty)
        c.handle([gleich(2, "A", "a1")])
        XCTAssertEqual(c.scene.order, ["A"], "der Kernel meint, die App habe den Inhalt: hat sie auch")
        XCTAssertEqual(try g.koepfe("PARTS_REQ").count, 0)
    }

    // MARK: Statikfelder und Versionsbild

    func testStatikfelderHaltenVierUndGeltenUeberLaeufe() throws {
        let (c, _) = try verbunden()
        XCTAssertTrue(c.live.deltaAktiv)
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        for k in 1...5 {
            f.schluessel = "s\(k)"
            f.run = k
            c.handle([.message(.statikFeld(f))])
        }
        let liste = try XCTUnwrap(c.model.statik.feldVorrat[f.key])
        XCTAssertEqual(liste.map(\.schluessel), ["s2", "s3", "s4", "s5"])
        c.handle([try nachricht(#"{"type":"PROJECT","path":"/tmp/eins","name":"eins"}"#)])
        c.handle([try nachricht(#"{"type":"PROJECT","path":"/tmp/zwei","name":"zwei"}"#)])
        XCTAssertTrue(c.model.statik.feldVorrat.isEmpty)
    }

    func testVersionsbildNimmtNetzeAusDerSzene() throws {
        guard case .versionen(.bildAnfrage(let b)) = try Fixtures.message("live_version_bild_req.frame") else {
            return XCTFail()
        }
        let e = try XCTUnwrap(try expected()["version_bild"])
        XCTAssertEqual(b.teile.filter { $0.ausSzene != nil }.map(\.teil), e["aus_szene"]?.stringList)
        XCTAssertEqual(b.teile.filter { $0.ausSzene == nil }.map(\.teil), e["mit_netz"]?.stringList)
        let (c, _) = try verbunden()
        let inhalt = try XCTUnwrap(b.teile[0].ausSzene)
        XCTAssertEqual(c.versionsbildTeile(b).count, 1, "fehlt der Inhalt, fehlt das Teil im Bild")
        c.handle([.part(try teil("Halter/Lasche", inhalt))])
        let teile = c.versionsbildTeile(b)
        XCTAssertEqual(teile.map { $0.netz.triangleCount > 0 }, [true, true])
    }
}
