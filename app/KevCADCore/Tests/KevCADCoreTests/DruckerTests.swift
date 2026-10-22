import Foundation
import XCTest

@testable import KevCADCore

/// Drucken (Phase 8) gegen die Testdateien des Kernels (kernel/tools/make_drucker_fixtures.py, Abschnitt `drucker` in
/// fixtures.json): Decoder, Encoder, Einstellungen, Schlüsselbund-Ersatz und der Ablauf im App-Kern.
final class DruckerFixtureTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try XCTUnwrap(try Fixtures.expected()["drucker"])
    }

    private func status(_ name: String) throws -> (DruckerStatus, String?) {
        guard case .drucker(.status(let s, let r)) = try Fixtures.message(name) else {
            throw NSError(domain: "Drucker", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(name) ist kein PRINTER_STATUS"])
        }
        return (s, r)
    }

    private func ohneSeq(_ data: Data) throws -> JSONValue {
        var j = try JSONDecoder().decode(JSONValue.self, from: data)
        if case .object(var o) = j { o["seq"] = nil; j = .object(o) }
        return j
    }

    func testAlleRahmenLesbar() throws {
        let frames = try XCTUnwrap(try erwartet()["frames"]?.arrayValue)
        XCTAssertGreaterThanOrEqual(frames.count, 18)
        for f in frames {
            let name = try XCTUnwrap(f["file"]?.stringValue)
            let typ = try XCTUnwrap(f["type"]?.stringValue)
            let m = try Fixtures.message(name)
            if DruckerNachricht.types.contains(typ) || typ == "ACK" {
                XCTAssertEqual(m.typeName, typ, name)
            }
            // Keine Geheimnisse in den Testdateien
            let text = String(decoding: try Fixtures.data(name), as: UTF8.self)
            XCTAssertFalse(text.contains("zugangscode"), name)
            XCTAssertFalse(text.contains("seriennummer"), name)
        }
    }

    func testPrinterStatusDruckt() throws {
        let e = try erwartet()
        let (s, reply) = try status("printer_status.frame")
        XCTAssertNil(reply)
        XCTAssertTrue(s.konfiguriert)
        XCTAssertEqual(s.verbindung, .verbunden)
        XCTAssertEqual(s.weg, .a)
        XCTAssertFalse(s.steuern)
        XCTAssertFalse(s.kamera)
        let d = try XCTUnwrap(s.drucker)
        XCTAssertEqual(d.name, e["drucker"]?["name"]?.stringValue)
        XCTAssertEqual(d.modell, "P1P")
        XCTAssertEqual(d.firmware, "01.10.00.00")
        XCTAssertEqual(d.modus, "cloud")
        XCTAssertEqual(d.modusTitel, "Cloud-Modus")
        XCTAssertEqual(d.entwicklermodus, false)
        let p = try XCTUnwrap(s.druck)
        XCTAssertEqual(p.zustand, .druckt)
        XCTAssertTrue(p.zustand.aktiv)
        XCTAssertEqual(p.fortschritt, e["druck"]?["fortschritt"]?.doubleValue)
        XCTAssertEqual(p.schicht, 41)
        XCTAssertEqual(p.schichten, 98)
        XCTAssertEqual(p.restzeitS, 3720)
        XCTAssertEqual(p.aufgabe, "Kugelschieber-platten")
        XCTAssertEqual(p.geschwindigkeit, "standard")
        let t = try XCTUnwrap(s.temperaturen)
        XCTAssertEqual(t.duese, 219.5)
        XCTAssertEqual(t.dueseZiel, 220)
        XCTAssertEqual(t.bett, 55)
        XCTAssertEqual(s.fehler.map(\.code), ["0300-0100-0003-0007"])
        XCTAssertFalse(s.fehler[0].istFehler)
        XCTAssertTrue(s.wegA.moeglich)
        XCTAssertFalse(s.wegB.moeglich)
        XCTAssertEqual(s.wegB.grund, e["wege"]?["b_grund"]?.stringValue)
        XCTAssertEqual(s.wegB.anleitung.count, e["wege"]?["anleitung"]?.intValue)
        XCTAssertEqual(s.gefunden.map(\.ip), ["192.168.178.40"])
        XCTAssertEqual(s.gefunden.first?.kennung, "3fa2c1d09e7b")
        let a = try XCTUnwrap(s.auftrag)
        XCTAssertEqual(a.auftrag, "j-3")
        XCTAssertEqual(a.zustand, .geoeffnet)
        XCTAssertEqual(a.platten, [1, 2])
        XCTAssertEqual(a.von, "kevin")
        XCTAssertNotNil(s.aktualisiert)
    }

    func testPrinterStatusBereitOhneUndAntwort() throws {
        let (b, _) = try status("printer_status_bereit.frame")
        XCTAssertEqual(b.druck?.zustand, .bereit)
        XCTAssertFalse(b.druck?.zustand.aktiv ?? true)
        XCTAssertEqual(b.auftrag?.zustand, .slict)
        XCTAssertTrue(b.auftrag?.zustand.laeuft ?? false)
        XCTAssertEqual(b.auftrag?.von, "agent")
        let (o, _) = try status("printer_status_ohne.frame")
        XCTAssertFalse(o.konfiguriert)
        XCTAssertEqual(o.verbindung, .aus)
        XCTAssertNil(o.drucker)
        XCTAssertNil(o.druck)
        XCTAssertNil(o.temperaturen)
        XCTAssertTrue(o.wegA.moeglich)
        let (_, r) = try status("printer_status_antwort.frame")
        XCTAssertEqual(r, "a-41")
    }

    func testAuftragErgebnisUndFrage() throws {
        guard case .drucker(.auftragErgebnis(let e)) = try Fixtures.message("print_job_res.frame") else {
            return XCTFail("kein PRINT_JOB_RES")
        }
        XCTAssertTrue(e.ok)
        XCTAssertEqual(e.replyTo, "a-43")
        XCTAssertEqual(e.schritt, "geoeffnet")
        XCTAssertEqual(e.auftrag, "j-3")
        XCTAssertEqual(e.platten, [1, 2])
        XCTAssertEqual(e.datei?.lastPathComponent, "Kugelschieber-platten.gcode.3mf")
        XCTAssertEqual(e.gesliced.map(\.nr), [1, 2])
        XCTAssertEqual(e.gesliced.map(\.material), ["PETG", "PLA"])
        XCTAssertEqual(e.zeitS, 22100 + 5480)
        XCTAssertEqual(e.gramm, 301.2 + 24.6, accuracy: 0.001)
        XCTAssertEqual(e.hinweise.count, 1)
        guard case .drucker(.auftragErgebnis(let f)) = try Fixtures.message("print_job_res_fehler.frame") else {
            return XCTFail("kein PRINT_JOB_RES")
        }
        XCTAssertFalse(f.ok)
        XCTAssertNil(f.schritt)
        XCTAssertEqual(f.weg, .b)
        XCTAssertTrue(f.fehler?.contains("Weg A") ?? false)
        guard case .drucker(.frage(let q)) = try Fixtures.message("print_job_ask.frame") else {
            return XCTFail("kein PRINT_JOB_ASK")
        }
        XCTAssertEqual(q.id, "k-9")
        XCTAssertEqual(q.auftrag, "j-6")
        XCTAssertEqual(q.platten, [1])
        XCTAssertEqual(q.weg, .a)
        XCTAssertEqual(q.grund, "Kevin möchte die Halter jetzt drucken.")
    }

    func testEncoderWieTestdateien() throws {
        let cfg = try JSONDecoder().decode(DruckerEintrag.self, from: JSONEncoder().encode(try XCTUnwrap(try erwartet()["config"])))
        XCTAssertEqual(cfg.ip, "192.168.178.40")
        XCTAssertTrue(cfg.statusLesen)
        XCTAssertEqual(try ohneSeq(DruckerKonfigNachricht(id: "a-40", drucker: cfg).encodedHeader()),
                       try ohneSeq(Fixtures.frame("printer_config.frame").header))
        XCTAssertEqual(try ohneSeq(DruckerKonfigNachricht(id: "a-46", drucker: nil).encodedHeader()),
                       try ohneSeq(Fixtures.frame("printer_config_leer.frame").header))
        XCTAssertEqual(try ohneSeq(DruckerStatusAnfrage(id: "a-41").encodedHeader()),
                       try ohneSeq(Fixtures.frame("printer_status_req.frame").header))
        XCTAssertEqual(try ohneSeq(DruckAuftragNachricht(id: "a-42", platten: [], weg: .a, bestaetigt: false).encodedHeader()),
                       try ohneSeq(Fixtures.frame("print_job_req.frame").header))
        XCTAssertEqual(try ohneSeq(DruckAuftragNachricht(id: "a-43", platten: [1, 2], weg: .a, bestaetigt: true,
                                                         auftrag: "j-3").encodedHeader()),
                       try ohneSeq(Fixtures.frame("print_job_req_bestaetigt.frame").header))
        XCTAssertEqual(try ohneSeq(DruckAuftragNachricht(id: "a-44", platten: [1], weg: .b, bestaetigt: true,
                                                         optionen: DruckOptionen()).encodedHeader()),
                       try ohneSeq(Fixtures.frame("print_job_req_b.frame").header))
        XCTAssertEqual(try ohneSeq(DruckerSteuerNachricht(id: "a-45", aktion: .pause).encodedHeader()),
                       try ohneSeq(Fixtures.frame("print_control.frame").header))
        XCTAssertEqual(try ohneSeq(DruckerSteuerNachricht(id: "a-47", aktion: .verwerfen, auftrag: "j-6").encodedHeader()),
                       try ohneSeq(Fixtures.frame("print_control_verwerfen.frame").header))
    }
}

@MainActor
final class DruckerEinstellungenTests: XCTestCase {
    func testDateiRundlaufUndPruefungen() throws {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-drucker-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let url = ordner.appendingPathComponent("drucker.json")
        XCTAssertNil(DruckerEinstellungenDatei.laden(von: url).aktiver)
        var d = DruckerEinstellungenDatei()
        var e = DruckerEintrag(id: "p1p", name: "P1P Werkstatt", ip: "192.168.178.40", weg: .a)
        XCTAssertFalse(e.statusLesen, "Status lesen ist anfangs aus")
        e.kennung = DruckerEintrag.kennung(seriennummer: "01P00ATESTSN001")
        d.setze(e)
        try d.speichern(nach: url)
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("\"status_lesen\" : false"))
        XCTAssertTrue(text.contains("\"dienst\" : \"de.upvis.kevcad.drucker\""))
        XCTAssertFalse(text.contains("01P00ATESTSN001"))
        let neu = DruckerEinstellungenDatei.laden(von: url)
        XCTAssertEqual(neu, d)
        XCTAssertEqual(neu.aktiver?.kennung, "969456eeaca4", "gleiche Kennung wie im Kernel (ssdp.kennung)")
        XCTAssertTrue(DruckerEintrag.gueltigeID("p1p"))
        XCTAssertTrue(DruckerEintrag.gueltigeID("werkstatt-2"))
        for falsch in ["P1P", "-s", "", String(repeating: "a", count: 33), "p1p; rm"] {
            XCTAssertFalse(DruckerEintrag.gueltigeID(falsch), falsch)
        }
        XCTAssertTrue(DruckerEintrag.gueltigeIP("192.168.178.40"))
        XCTAssertFalse(DruckerEintrag.gueltigeIP("http://x y"))
    }

    private func connected(_ speicher: DruckerZugangsSpeicher, _ url: URL) throws -> AppController {
        let model = AppModel()
        model.drucker.speicher = speicher
        model.drucker.dateiURL = url
        let c = AppController(model: model)
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        return c
    }

    private func msg(_ json: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(json.utf8))))
    }

    func testSpeichernNurInDenSchluesselbund() throws {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-drucker-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let speicher = DruckerZugangImSpeicher()
        let c = try connected(speicher, ordner.appendingPathComponent("drucker.json"))
        let m = c.model
        XCTAssertNil(m.drucker.aktiver)
        var e = DruckerEintrag(id: "p1p", name: "P1P", ip: "192.168.178.40")
        e.statusLesen = true
        XCTAssertThrowsError(try c.druckerSpeichern(e, seriennummer: "01P00ATESTSN001", zugangscode: ""))
        XCTAssertThrowsError(try c.druckerSpeichern(DruckerEintrag(id: "p1p", ip: "nicht gültig"), seriennummer: nil,
                                                    zugangscode: nil))
        try c.druckerSpeichern(e, seriennummer: "01P00ATESTSN001", zugangscode: "12345678")
        XCTAssertTrue(m.drucker.zugangGespeichert)
        XCTAssertEqual(speicher.eintraege["p1p"]?.0, "01P00ATESTSN001")
        XCTAssertEqual(m.drucker.aktiver?.kennung, "969456eeaca4")
        let datei = try String(contentsOf: ordner.appendingPathComponent("drucker.json"), encoding: .utf8)
        XCTAssertFalse(datei.contains("12345678"))
        XCTAssertFalse(datei.contains("01P00ATESTSN001"))
        // Gefundener Drucker wird über die Kennung erkannt
        c.handle([try msg(#"{"type":"PRINTER_STATUS","konfiguriert":true,"verbindung":"aus","meldung":null,"drucker":null,"weg":"a","wege":{"a":{"moeglich":true,"grund":null},"b":{"moeglich":false,"grund":"x","anleitung":[]}},"steuern":false,"druck":null,"temperaturen":null,"fehler":[],"kamera":false,"gefunden":[{"name":"P1P","modell":"P1P","ip":"10.0.0.9","verbindung":"cloud","kennung":"969456eeaca4"}],"auftrag":null,"aktualisiert":1}"#)])
        XCTAssertTrue(m.drucker.istEingetragen(try XCTUnwrap(m.drucker.status?.gefunden.first)))
        // Löschen
        try c.druckerZugangLoeschen(id: "p1p")
        XCTAssertFalse(m.drucker.zugangGespeichert)
        XCTAssertNil(speicher.eintraege["p1p"])
        XCTAssertEqual(m.drucker.aktiver?.statusLesen, false)
        XCTAssertNil(m.drucker.aktiver?.kennung)
    }

    func testDialogVorbereitenBestaetigenUndFrageDesAgenten() throws {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-drucker-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let c = try connected(DruckerZugangImSpeicher(), ordner.appendingPathComponent("drucker.json"))
        let m = c.model
        c.druckDialogOeffnen(platten: [])  // a-1: vorbereiten
        var d = try XCTUnwrap(m.drucker.dialog)
        XCTAssertEqual(d.phase, .bereitet)
        XCTAssertEqual(d.weg, .a)
        XCTAssertFalse(d.bestaetigbar)
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-1","ok":true,"message":"Wird vorbereitet"}"#)])
        c.handle([try msg(#"{"type":"PRINT_JOB_RES","reply_to":"a-1","ok":true,"auftrag":"j-1","weg":"a","schritt":"vorbereitet","datei":"/tmp/x.gcode.3mf","platten":[],"fehler":null,"hinweise":[],"ms":900,"ergebnis":{"platten":[{"nr":1,"zeit_s":3600,"g":40.5,"m":13.2,"material":"PETG"}]}}"#)])
        d = try XCTUnwrap(m.drucker.dialog)
        XCTAssertTrue(d.bestaetigbar)
        XCTAssertEqual(d.auftrag, "j-1")
        c.druckBestaetigen()  // a-2
        XCTAssertEqual(m.drucker.dialog?.phase, .laeuft)
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-2","ok":true,"message":"Wird in Bambu Studio geöffnet"}"#)])
        c.handle([try msg(#"{"type":"PRINT_JOB_RES","reply_to":"a-2","ok":true,"auftrag":"j-1","weg":"a","schritt":"geoeffnet","datei":"/tmp/P/output/P-platten.gcode.3mf","platten":[],"fehler":null,"hinweise":[],"ms":30}"#)])
        guard case .fertig(let e) = m.drucker.dialog?.phase else { return XCTFail("nicht fertig") }
        XCTAssertEqual(e.schritt, "geoeffnet")
        XCTAssertTrue(m.log.contains { $0.text.contains("In Bambu Studio geöffnet: P-platten.gcode.3mf") })
        c.druckDialogSchliessen()  // schon bestätigt: nichts verwerfen
        XCTAssertNil(m.drucker.dialog)

        // Frage des Agenten: ACK sofort, Dialog offen, vorbereiten (a-3); Schließen verwirft (a-4)
        c.handle([try msg(#"{"type":"PRINT_JOB_ASK","id":"k-9","auftrag":"j-6","platten":[1],"weg":"b","von":"agent","grund":"Kevin will die Halter"}"#)])
        d = try XCTUnwrap(m.drucker.dialog)
        XCTAssertEqual(d.frage?.grund, "Kevin will die Halter")
        XCTAssertEqual(d.auftrag, "j-6")
        XCTAssertEqual(d.platten, [1])
        XCTAssertEqual(d.weg, .a, "Weg B ist nicht möglich: Dialog nimmt Weg A")
        c.handle([try msg(#"{"type":"PRINT_JOB_RES","reply_to":"a-3","ok":false,"auftrag":"j-6","weg":"a","schritt":null,"datei":null,"platten":[1],"fehler":"Keine Druckteile","hinweise":[],"ms":2}"#)])
        XCTAssertEqual(m.drucker.dialog?.phase, .fehler("Keine Druckteile"))
        c.druckDialogSchliessen()
        XCTAssertNil(m.drucker.dialog)
        XCTAssertTrue(m.log.contains { $0.text.contains("verworfen") })
    }

    func testEinMaterialJeAuftragUndNaechstesMaterial() throws {
        guard case .druck(.vorschau(let v, _)) = try Fixtures.message("print_preview.frame") else {
            return XCTFail("kein PRINT_PREVIEW")
        }
        // Testdatei: Platte 1 PETG, Platte 2 PLA
        XCTAssertEqual(DruckDialogZustand.material(1, v), "petg")
        XCTAssertEqual(DruckDialogZustand.auswahl([], vorschau: v), [1])
        XCTAssertEqual(DruckDialogZustand.auswahl([2], vorschau: v), [2])
        XCTAssertEqual(DruckDialogZustand.auswahl([2, 1], vorschau: v), [2])
        XCTAssertEqual(DruckDialogZustand.auswahl([7], vorschau: v), [1])
        XCTAssertEqual(DruckDialogZustand.naechste(nach: [1], vorschau: v), [2])
        XCTAssertNil(DruckDialogZustand.naechste(nach: [2], vorschau: v))
        var eins = v
        eins.platten = [v.platten[0]]
        XCTAssertEqual(DruckDialogZustand.auswahl([], vorschau: eins), [], "ein Material: leer = alle")
        XCTAssertEqual(DruckDialogZustand.auswahl([5], vorschau: nil), [5])

        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-drucker-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let c = try connected(DruckerZugangImSpeicher(), ordner.appendingPathComponent("drucker.json"))
        c.handle([.message(.druck(.vorschau(v, replyTo: nil)))])
        c.druckDialogOeffnen(platten: [])  // a-1
        XCTAssertEqual(c.model.drucker.dialog?.platten, [1])
        c.handle([try msg(#"{"type":"PRINT_JOB_RES","reply_to":"a-1","ok":true,"auftrag":"j-1","weg":"a","schritt":"vorbereitet","datei":"/tmp/x.gcode.3mf","platten":[1],"fehler":null,"hinweise":[],"ms":9}"#)])
        c.druckBestaetigen()  // a-2
        c.handle([try msg(#"{"type":"PRINT_JOB_RES","reply_to":"a-2","ok":true,"auftrag":"j-1","weg":"a","schritt":"geoeffnet","datei":"/tmp/x.gcode.3mf","platten":[1],"fehler":null,"hinweise":[],"ms":9}"#)])
        c.druckDialogAendern(platten: [2], weg: .a)  // a-3: nächstes Material, neuer Auftrag
        let d = try XCTUnwrap(c.model.drucker.dialog)
        XCTAssertEqual(d.platten, [2])
        XCTAssertNil(d.auftrag)
        XCTAssertEqual(d.phase, .bereitet)
    }

    func testSteuernNurMitFreigabe() throws {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-drucker-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let c = try connected(DruckerZugangImSpeicher(), ordner.appendingPathComponent("drucker.json"))
        c.handle([.message(try Fixtures.message("printer_status.frame"))])
        c.druckerSteuern(.pause)
        XCTAssertEqual(c.model.drucker.fehler, "Steuern geht nur über Weg B (LAN-only und Developer Mode).")
        c.druckerSteuern(.aktualisieren)  // a-1: Lesen geht immer
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-1","ok":false,"message":"Vollständiger Bericht erst wieder in 280 s"}"#)])
        XCTAssertEqual(c.model.drucker.fehler, "Vollständiger Bericht erst wieder in 280 s")
    }
}
