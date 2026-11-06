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

    func testZwischenstandImLaufFlackertNicht() throws {
        let (c, _) = try verbunden()
        // model.py zeigt A erst als Zwischenstand, dann fertig; beides kennt die App
        c.handle([.part(try teil("A", "zwischen", z: 2)), .part(try teil("A", "fertig", z: 9))])
        let vorher = c.scene.statistik
        c.handle([try laufStart(2), gleich(2, "A", "zwischen"), gleich(2, "A", "fertig"), try laufEnde(2, ["A"])])
        XCTAssertEqual(c.scene.statistik, vorher, "der gezeigte Inhalt kam gleich wieder: nichts passiert")
        XCTAssertEqual(c.scene.record("A")?.header.inhalt, "fertig")
        XCTAssertEqual(c.scene.record("A")?.run, 2)
        XCTAssertEqual(c.live.inhalte.schluessel("A"), ["zwischen", "fertig"], "wie die Liste des Kernels")
        // bleibt der andere Inhalt stehen, kommt er zum Laufende; ein neues Teil geht vor
        c.handle([try laufStart(3), gleich(3, "A", "zwischen")])
        XCTAssertEqual(c.scene.record("A")?.header.inhalt, "fertig", "noch nicht im Lauf")
        c.handle([try laufEnde(3, ["A"])])
        XCTAssertEqual(c.scene.record("A")?.header.inhalt, "zwischen")
        c.handle([try laufStart(4), gleich(4, "A", "fertig"), .part(try teil("A", "neu", run: 4, z: 20)), try laufEnde(4, ["A"])])
        XCTAssertEqual(c.scene.record("A")?.header.inhalt, "neu")
    }

    func testStillesNachladenDesKatalogsBehaeltDenStand() throws {
        let (c, g) = try verbunden()
        c.refreshCatalogQuietly()
        let erste = try XCTUnwrap(try g.koepfe("CATALOG_REQ").last)
        XCTAssertNil(erste["stand"], "ohne Stand kommt der Katalog ganz")
        let id = try XCTUnwrap(erste["id"]?.stringValue)
        c.handle([try nachricht(#"{"type":"CATALOG","reply_to":"\#(id)","stand":"abc","materials":[],"items":[],"arten":[]}"#)])
        let katalog = try XCTUnwrap(c.model.catalog)
        c.lastQuietCatalog = nil
        c.refreshCatalogQuietly()
        let zweite = try XCTUnwrap(try g.koepfe("CATALOG_REQ").last)
        XCTAssertEqual(zweite["stand"]?.stringValue, "abc")
        let id2 = try XCTUnwrap(zweite["id"]?.stringValue)
        c.handle([try nachricht(#"{"type":"CATALOG","reply_to":"\#(id2)","stand":"abc","unveraendert":true}"#)])
        XCTAssertEqual(c.model.catalog?.items.count, katalog.items.count, "der Katalog bleibt stehen")
        XCTAssertEqual(c.live.katalogStand, "abc")
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

// MARK: - Lagebild, In Arbeit, Live-Maße, Agentenspur, Befunde

@MainActor
final class LiveAnzeigeTests: XCTestCase {
    private func nachricht(_ kopf: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(kopf.utf8))))
    }

    private func teil(_ name: String, _ inhalt: String, run: Int = 1, z: Float = 0) throws -> PartRecord {
        var (h, g) = try Fixtures.part("live_part_upsert.frame")
        h.name = name
        h.run = run
        h.inhalt = inhalt
        h.bbox = BBox(min: [0, 0, Double(z)], max: [40, 20, Double(z) + 1])
        for i in stride(from: 2, to: g.positions.count, by: 3) { g.positions[i] += z }
        return PartRecord(header: h, geometry: g)
    }

    private func verbunden() throws -> AppController {
        let c = AppController(model: AppModel())
        c.live.inArbeitNachS = 0
        c.handle([.connected])
        c.handle([try nachricht(#"{"type":"HELLO","seq":1,"protocol":1,"faehigkeiten":["delta-1","in-arbeit-1","spur-1","lage-1","live-masse-1"]}"#)])
        return c
    }

    private func befehl(_ cmd: String, _ args: JSONValue) -> ViewCommandMessage { ViewCommandMessage(id: "k-1", cmd: cmd, args: args) }

    func testLagebildHatGenauDieFelderDerTestdatei() throws {
        let c = try verbunden()
        c.handle([.part(try teil("Halter/Lasche", "a1")), .part(try teil("Deckel", "b1", z: 30))])
        c.setVisibility(["Deckel"], visible: false)
        c.applySelection([.face("Halter/Lasche", 0)])
        c.viewport.viewSize = CGSize(width: 900, height: 600)
        c.viewport.fit(c.scene.visibleBounds(), animated: false)
        var gesendet: [Frame] = []
        c.sendeBeobachter = { gesendet.append($0) }
        c.handle([.message(.lageAnfrage(LageRequestMessage(id: "k-41")))])
        let kopf = try JSONDecoder().decode(JSONValue.self, from: try XCTUnwrap(gesendet.first).header)
        let muster = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("live_lage.frame").header)
        XCTAssertEqual(Set(try XCTUnwrap(kopf.objectValue).keys), Set(try XCTUnwrap(muster.objectValue).keys))
        XCTAssertEqual(Set(try XCTUnwrap(kopf["kamera"]?.objectValue).keys), Set(try XCTUnwrap(muster["kamera"]?.objectValue).keys))
        XCTAssertEqual(kopf["reply_to"]?.stringValue, "k-41")
        XCTAssertEqual(kopf["sichtbar"]?.stringList, ["Halter/Lasche"])
        XCTAssertEqual(kopf["verborgen"]?.stringList, ["Deckel"])
        XCTAssertEqual(kopf["viewport"]?["breite"]?.intValue, 900)
        XCTAssertEqual(kopf["auswahl"]?["refs"]?.stringList, ["Halter/Lasche#f0"])
        XCTAssertEqual(kopf["maus"], .null)
        XCTAssertLessThan(try XCTUnwrap(kopf["ms"]?.doubleValue), 50)
    }

    func testTeilAusserhalbDesBildesIstNichtSichtbar() throws {
        let c = try verbunden()
        c.handle([.part(try teil("Nah", "a1")), .part(try teil("Weit", "b1", z: 100_000))])
        c.viewport.viewSize = CGSize(width: 900, height: 600)
        c.viewport.fit(c.scene.worldBounds(of: .part("Nah")), animated: false)
        XCTAssertEqual(c.teileImBild(), ["Nah"])
    }

    func testInArbeitMarkiertBisDasTeilKommt() throws {
        let c = try verbunden()
        c.handle([.part(try teil("A", "a1")), .part(try teil("B", "b1", z: 3))])
        let vorher = c.scene.displayColor("A", now: 0, includeFlash: false)
        c.handle([try nachricht(#"{"type":"RUN_START","run":2,"delta":true}"#),
                  .message(.inArbeit(InArbeitMessage(run: 2, teil: "A")))])
        XCTAssertEqual(c.scene.inArbeit, "A")
        XCTAssertNotEqual(c.scene.displayColor("A", now: 0, includeFlash: false), vorher)
        c.handle([.message(.partSame(PartSameMessage(run: 2, name: "A", inhalt: "a1")))])
        XCTAssertNil(c.scene.inArbeit, "die Markierung endet mit PART_SAME")
        XCTAssertEqual(c.scene.displayColor("A", now: 0, includeFlash: false), vorher)
        c.handle([.message(.inArbeit(InArbeitMessage(run: 2, teil: "B")))])
        c.handle([.part(try teil("B", "b2", run: 2, z: 8))])
        XCTAssertNil(c.scene.inArbeit, "oder mit PART_UPSERT")
        c.handle([.message(.inArbeit(InArbeitMessage(run: 2, teil: "A")))])
        c.handle([try nachricht(#"{"type":"RUN_ERROR","run":2,"message":"kaputt","excerpt":""}"#)])
        XCTAssertNil(c.scene.inArbeit, "alle enden mit dem Laufende")
    }

    func testMassMitDauerBlendetSanftAus() throws {
        let c = try verbunden()
        c.handle([.part(try teil("A", "a1"))])
        guard case .viewCommand(let v) = try Fixtures.message("live_view_annotate_param.frame") else { return XCTFail() }
        XCTAssertTrue(c.performViewCommand(v).0)
        XCTAssertEqual(c.annotations.map(\.id), ["p-3"])
        let ende = try XCTUnwrap(c.live.anmerkungAblauf["p-3"]?.ende)
        XCTAssertEqual(ende - CACurrentMediaTime(), 4, accuracy: 0.5)
        func deckkraft(_ now: CFTimeInterval) -> Float? {
            guard case .label(_, _, let f)? = c.anmerkungenMitAblauf(now: now).first else { return nil }
            return f.w
        }
        XCTAssertEqual(deckkraft(ende - 1), 1)
        XCTAssertEqual(try XCTUnwrap(deckkraft(ende - 0.25)), 0.5, accuracy: 0.01)
        c.ablaufSchritt(now: ende + 0.01)
        XCTAssertTrue(c.annotations.isEmpty)
        XCTAssertNil(c.live.anmerkungAblauf["p-3"])
    }

    func testHervorhebungMitDauerGehtAlleinUndClearBleibt() throws {
        let c = try verbunden()
        c.handle([.part(try teil("Halter/Lasche", "a1")), .part(try teil("B", "b1", z: 3))])
        XCTAssertTrue(c.performViewCommand(befehl("highlight", ["refs": ["B"], "label": "bleibt"])).0)
        guard case .viewCommand(let v) = try Fixtures.message("live_view_highlight_dauer.frame") else { return XCTFail() }
        XCTAssertTrue(c.performViewCommand(v).0)
        XCTAssertEqual(c.scene.highlights.count, 2)
        let ende = try XCTUnwrap(c.live.hervorhebungAblauf["p-3"]?.ende)
        c.ablaufSchritt(now: ende - 0.25)
        XCTAssertEqual(c.scene.highlights.first { $0.kennung == "p-3" }?.deckkraft ?? 0, 0.5, accuracy: 0.01)
        c.ablaufSchritt(now: ende + 0.01)
        XCTAssertEqual(c.scene.highlights.map(\.label), ["bleibt"], "nur diese Hervorhebung geht")
        XCTAssertEqual(c.annotations.count, 1, "die Beschriftung der anderen bleibt")
        // gleiche Kennung ersetzt; clear entfernt wie bisher alles
        XCTAssertTrue(c.performViewCommand(v).0)
        XCTAssertTrue(c.performViewCommand(v).0)
        XCTAssertEqual(c.scene.highlights.filter { $0.kennung == "p-3" }.count, 1)
        XCTAssertTrue(c.performViewCommand(befehl("highlight", ["clear": true])).0)
        XCTAssertTrue(c.scene.highlights.isEmpty)
        c.ablaufSchritt(now: CACurrentMediaTime() + 10)  // abgelaufene Kennung ohne Hervorhebung stört nicht
    }

    func testAgentenspurHaeltFuenfzigUndErsetztNachID() throws {
        let c = try verbunden()
        c.handle([.message(try Fixtures.message("live_agent_spur.frame"))])
        XCTAssertEqual(c.model.agentenspur.schritte.map(\.id), try XCTUnwrap(try Fixtures.expected()["live"]?["spur_ids"]?.stringList))
        c.handle([.message(try Fixtures.message("live_agent_schritt.frame"))])
        XCTAssertEqual(c.model.agentenspur.schritte.first?.stand, .laeuft, "gleiche id ersetzt den Stand")
        XCTAssertEqual(c.model.agentenspur.laufend?.absicht, "Laufrolle auf 90 mm")
        c.handle([.message(try Fixtures.message("live_agent_schritt_ende.frame"))])
        let fertig = try XCTUnwrap(c.model.agentenspur.schritte.first)
        XCTAssertEqual(fertig.stand, .ok)
        XCTAssertEqual(fertig.dauerMs, 2333)
        XCTAssertEqual(fertig.phasen?["run"]?.intValue, 8)
        XCTAssertNil(c.model.agentenspur.laufend)
        c.handle([.message(try Fixtures.message("live_agent_schritt_fehler.frame"))])
        XCTAssertEqual(c.model.agentenspur.schritte.last?.stand, .fehler)
        for k in 0..<60 {
            c.model.agentenspur.aktualisieren(AgentSchritt(id: "n-\(k)", werkzeug: "run", beginn: Double(k)))
        }
        XCTAssertEqual(c.model.agentenspur.schritte.count, 50)
        XCTAssertEqual(c.model.agentenspur.schritte.first?.id, "n-10")
    }

    func testBefundeSindMarkenAmTeil() throws {
        let c = try verbunden()
        c.handle([.part(try teil("Halter/Lasche", "a1")), .part(try teil("Halter/Grundplatte", "b1", z: 3))])
        c.model.pruefung = PruefErgebnis(
            run: 1, zustand: .done,
            befunde: [
                PruefBefund(id: "1", art: "durchdringung", teile: ["Halter/Lasche"], schwere: .fehler, text: "x", ort: SIMD3(1, 2, 3)),
                PruefBefund(id: "2", art: "kippen", teile: ["Halter/Grundplatte"], schwere: .warnung, text: "y"),
                PruefBefund(id: "3", art: "zart", teile: ["Halter/Grundplatte"], schwere: .hinweis, text: "z"),
                PruefBefund(id: "4", art: "weg", teile: ["Gibt/Es/Nicht"], schwere: .fehler, text: "w"),
            ])
        let marken = c.befundMarken()
        XCTAssertEqual(marken.count, 2, "Hinweise und Befunde ohne Ort stehen nur in der Liste")
        guard case .badge(let p, let text, _, let gefuellt) = marken[0] else { return XCTFail() }
        XCTAssertEqual(p, SIMD3(1, 2, 3))
        XCTAssertEqual(text, "!")
        XCTAssertTrue(gefuellt)
        c.setVisibility(["Halter/Lasche"], visible: false)
        XCTAssertEqual(c.befundMarken().count, 1, "ausgeblendete Teile tragen keine Marke")
        c.setVisibility(["Halter/Lasche"], visible: true)
        // Viele Warnungen: Marken nur an den ausgewählten Teilen, Fehler immer
        c.model.pruefung?.befunde += (0..<7).map {
            PruefBefund(id: "w\($0)", art: "kippen", teile: ["Halter/Grundplatte"], schwere: .warnung, text: "w",
                        ort: SIMD3(100 + Float($0) * 50, 0, 0))
        }
        XCTAssertEqual(c.befundMarken().count, 1, "nur der Fehler")
        c.applySelection([.part("Halter/Grundplatte")])
        XCTAssertEqual(c.befundMarken().count, 9, "Fehler und alle acht Warnungen des ausgewählten Teils")
        c.model.befundMarkenSichtbar = false
        XCTAssertTrue(c.befundMarken().isEmpty)
    }
}
