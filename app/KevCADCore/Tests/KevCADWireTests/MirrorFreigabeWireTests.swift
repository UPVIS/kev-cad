import Foundation
import XCTest

@testable import KevCADWire

/// Freigabe vom iPhone (MIRROR.md, Version 1.1): die Testdateien `freigabe*.bin`, `cmd_freigabe*.bin` und
/// `cmd_res_freigabe*.bin` lesen, mit `fixtures.json` vergleichen, mit dem Swift-Kodierer neu schreiben und im
/// Empfänger anwenden.
final class MirrorFreigabeWireTests: XCTestCase {
    var expected: JSONValue!

    override func setUpWithError() throws {
        expected = try WireFiles.expected()
    }

    func values(_ file: String) -> JSONValue { expected["files"]?[file] ?? .null }

    func json(_ data: Data) throws -> JSONValue { try JSONDecoder().decode(JSONValue.self, from: data) }

    func roundTrip<M: MirrorOutgoing>(_ file: String, _ message: M) throws {
        let original = try WireFiles.fixture(file)
        let again = try message.frame(seq: values(file)["seq"]?.intValue ?? 0)
        XCTAssertEqual(try json(again.header), try json(original.header), "\(file): Swift schreibt anders als die Referenz")
    }

    func testFreigabe() throws {
        guard case .freigabe(let f) = try MirrorMessage.decode(WireFiles.fixture("freigabe.bin")) else {
            return XCTFail("FREIGABE erwartet")
        }
        let v = values("freigabe.bin")
        XCTAssertEqual(f.prio, .zustand)
        XCTAssertEqual(f.anfrageID, v["anfrage_id"]?.stringValue)
        XCTAssertEqual(f.nonce, v["nonce"]?.stringValue)
        XCTAssertEqual(f.nonce.count, 2 * MirrorProtocol.freigabeNonceBytes)
        XCTAssertEqual(f.ablauf, "2026-10-23T14:03:12Z")
        XCTAssertEqual(f.ablaufDatum.map(MirrorFreigabeZeit.text), "2026-10-23T14:03:12Z")
        XCTAssertEqual(f.eintraege.map(\.id), v["ids"]?.stringList)
        XCTAssertEqual(f.eintraege.map(\.kind), ["teil", "teil", "material"])
        XCTAssertEqual(f.eintraege[0].kurz, "d 16 · s 1 mm · 4,20 €/m · ALFER")
        XCTAssertEqual(f.eintraege[0].projekt, "kugelschieber")
        XCTAssertEqual(f.eintraege[1].art, "zukaufteil")
        XCTAssertNil(f.eintraege[2].link, "ohne Link fehlt das Feld")
        XCTAssertTrue(f.abgelaufen(now: try XCTUnwrap(f.ablaufDatum)))
        XCTAssertFalse(f.abgelaufen(now: try XCTUnwrap(f.ablaufDatum).addingTimeInterval(-1)))
        try roundTrip("freigabe.bin", f)
        // Datenschutz: kein Pfad, Links nur mit https
        let raw = String(decoding: try WireFiles.fixture("freigabe.bin").header, as: UTF8.self)
        XCTAssertFalse(raw.contains("\"path\""))
        XCTAssertFalse(raw.contains("http:"))
    }

    func testLinksNurMitHttps() throws {
        XCTAssertNil(MirrorFreigabeEintrag(id: "a", kind: "teil", name: "A", art: "rohr", link: "http://x.de/a").link)
        XCTAssertNil(MirrorFreigabeEintrag(id: "a", kind: "teil", name: "A", art: "rohr", link: "file:///etc/a").link)
        XCTAssertNil(MirrorFreigabeEintrag(id: "a", kind: "teil", name: "A", art: "rohr", link: "https://").link)
        XCTAssertEqual(
            MirrorFreigabeEintrag(id: "a", kind: "teil", name: "A", art: "rohr", link: " https://x.de/a ").link,
            "https://x.de/a")
        // Auch beim Lesen fällt ein unsicherer Link weg
        let h = #"{"id":"a","kind":"teil","name":"A","art":"rohr","kurz":"","link":"http://x.de","grund":null,"projekt":null}"#
        XCTAssertNil(try JSONDecoder().decode(MirrorFreigabeEintrag.self, from: Data(h.utf8)).link)
    }

    func testBefehleUndAntworten() throws {
        guard case .command(let c) = try MirrorMessage.decode(WireFiles.fixture("cmd_freigabe.bin")) else {
            return XCTFail("CMD erwartet")
        }
        XCTAssertEqual(c.knownOp, .freigabe)
        XCTAssertEqual(c.prio, .zustand)
        let b = c.freigabeBefehl
        XCTAssertEqual(b.anfrageID, "F-0001-5c1e9a27")
        XCTAssertEqual(b.nonce, values("freigabe.bin")["nonce"]?.stringValue)
        XCTAssertEqual(b.id, "rohr-alfer-16x1")
        XCTAssertEqual(b.entscheidung, .frei)
        try roundTrip(
            "cmd_freigabe.bin",
            MirrorCommand.freigabe(id: c.id, anfrageID: b.anfrageID, nonce: b.nonce, eintrag: b.id, entscheidung: .frei))

        guard case .command(let a) = try MirrorMessage.decode(WireFiles.fixture("cmd_freigabe_ablehnen.bin")) else {
            return XCTFail("CMD erwartet")
        }
        XCTAssertEqual(a.freigabeBefehl.entscheidung, .abgelehnt)
        XCTAssertEqual(a.freigabeBefehl.id, "alutec-05200")

        guard case .commandResult(let ok) = try MirrorMessage.decode(WireFiles.fixture("cmd_res_freigabe.bin")) else {
            return XCTFail("CMD_RES erwartet")
        }
        XCTAssertTrue(ok.ok)
        XCTAssertEqual(ok.freigabeStatus, .frei)
        try roundTrip("cmd_res_freigabe.bin", MirrorCommandResult.freigabe(replyTo: "i-46", status: .frei))

        guard case .commandResult(let nein) = try MirrorMessage.decode(WireFiles.fixture("cmd_res_freigabe_fehler.bin"))
        else { return XCTFail("CMD_RES erwartet") }
        XCTAssertFalse(nein.ok)
        XCTAssertEqual(nein.freigabeStatus, .ungueltig)
        try roundTrip("cmd_res_freigabe_fehler.bin", nein)
        // Ältere Antworten ohne status bleiben ohne status
        guard case .commandResult(let alt) = try MirrorMessage.decode(WireFiles.fixture("cmd_res.bin")) else {
            return XCTFail()
        }
        XCTAssertNil(alt.status)
        // Unbekannte Entscheidung wird nicht geraten
        let x = MirrorCommand(id: "x", op: "freigabe", args: ["anfrage_id": "a", "nonce": "n", "id": "e",
                                                               "entscheidung": "vielleicht"])
        XCTAssertNil(x.freigabeBefehl.entscheidung)
    }

    func testEnde() throws {
        guard case .freigabeEnde(let e) = try MirrorMessage.decode(WireFiles.fixture("freigabe_ende_eintrag.bin")) else {
            return XCTFail("FREIGABE_ENDE erwartet")
        }
        XCTAssertEqual(e.id, "rohr-alfer-16x1")
        XCTAssertEqual(e.grund, .iphone)
        XCTAssertEqual(e.ergebnis, .frei)
        try roundTrip("freigabe_ende_eintrag.bin", e)
        guard case .freigabeEnde(let ganz) = try MirrorMessage.decode(WireFiles.fixture("freigabe_ende.bin")) else {
            return XCTFail("FREIGABE_ENDE erwartet")
        }
        XCTAssertNil(ganz.id)
        XCTAssertNil(ganz.ergebnis)
        XCTAssertEqual(ganz.grund, .abgelaufen)
        try roundTrip("freigabe_ende.bin", ganz)
        // Ohne id kein ergebnis auf der Leitung
        let m = MirrorFreigabeEndeMessage(epoche: "e", anfrageID: "a", grund: .mac, ergebnis: .frei)
        XCTAssertNil(try json(m.headerData(seq: 1))["ergebnis"])
    }

    func testEmpfaengerHaeltOffeneFreigaben() throws {
        var r = MirrorReceiver()
        _ = try r.apply(frame: WireFiles.fixture("hello_kc.bin"))
        let ev = try r.apply(frame: WireFiles.fixture("freigabe.bin"))
        guard case .freigabe = ev.first else { return XCTFail("\(ev)") }
        XCTAssertEqual(r.freigaben.count, 1, "ohne WATCH")
        XCTAssertEqual(r.freigaben.first?.eintraege.count, 3)
        _ = try r.apply(frame: WireFiles.fixture("freigabe_ende_eintrag.bin"))
        XCTAssertEqual(r.freigaben.first?.eintraege.map(\.id), ["alutec-05200", "petg-cf"])
        // Noch nicht abgelaufen am Vortag, abgelaufen danach
        let ablauf = try XCTUnwrap(r.freigaben.first?.ablaufDatum)
        XCTAssertEqual(r.offeneFreigaben(now: ablauf.addingTimeInterval(-60)).count, 1)
        XCTAssertEqual(r.offeneFreigaben(now: ablauf).count, 0)
        _ = try r.apply(frame: WireFiles.fixture("freigabe_ende.bin"))
        XCTAssertTrue(r.freigaben.isEmpty)
        // Neue Epoche: alle Anfragen sind erledigt
        _ = try r.apply(frame: WireFiles.fixture("freigabe.bin"))
        XCTAssertEqual(r.freigaben.count, 1)
        _ = r.apply(.hello(MirrorHello.server(epoche: "fedcba9876543210", appBuild: 1, bundleID: "x", project: nil,
                                             agents: [])))
        XCTAssertTrue(r.freigaben.isEmpty)
        // Fremde Epoche wird verworfen
        let fremd = try r.apply(frame: WireFiles.fixture("freigabe.bin"))
        guard case .ignored = fremd.first else { return XCTFail("\(fremd)") }
    }
}
