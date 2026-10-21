import Foundation
import XCTest

@testable import KevCADCore

/// Phase 3: Dekodieren von ZUKAUF_STATUS, PART_UPSERT.zukauf, BOM und CATALOG mit Zukaufteilen gegen die Testdateien des
/// Kernels (Abschnitt `phase3` in fixtures.json, erzeugt von kernel/tools/make_fixtures.py), Nachrichten der App gegen
/// dieselben Testdateien. Daneben Toleranz gegenüber fehlenden oder falsch getypten Feldern.
final class Phase3ProtocolTests: XCTestCase {
    private func decode(_ json: String, payload: Data = Data()) throws -> KernelMessage {
        try KernelMessage.decode(Frame(header: Data(json.utf8), payload: payload))
    }

    private func phase3() throws -> JSONValue {
        try XCTUnwrap(Fixtures.expected()["phase3"])
    }

    /// Kopf einer Testdatei als JSON (für Vergleiche mit dem, was die App schickt).
    private func header(_ file: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame(file).header)
    }

    /// Was die App für eine Nachricht schicken würde, als JSON.
    private func sent(_ m: some OutgoingMessage) throws -> JSONValue {
        let back = try FrameReader().feed(m.frame().encoded)
        XCTAssertEqual(back.count, 1)
        return try JSONDecoder().decode(JSONValue.self, from: back[0].header)
    }

    /// Jede Testdatei aus `phase3.frames`: ein Rahmen mit Typ und Nutzlastgröße; Kernel-Nachrichten dekodiert die App.
    func testEveryPhase3FixtureDecodes() throws {
        let frames = try XCTUnwrap(phase3()["frames"]?.arrayValue)
        XCTAssertEqual(frames.compactMap { $0["file"]?.stringValue }, [
            "part_zukauf.frame", "zukauf_status_wartet.frame", "zukauf_status_importiert.frame", "bom_zukauf.frame",
            "catalog_zukauf.frame", "zukauf_neu.frame", "download_seen.frame", "zukauf_cad.frame",
        ])
        for f in frames {
            let file = try XCTUnwrap(f["file"]?.stringValue)
            let type = try XCTUnwrap(f["type"]?.stringValue)
            let frame = try Fixtures.frame(file)
            XCTAssertEqual(frame.payload.count, f["payload_bytes"]?.intValue, file)
            XCTAssertEqual(try JSONDecoder().decode(MessageEnvelope.self, from: frame.header).type, type, file)
            guard f["richtung"]?.stringValue == "kernel" else { continue }
            let msg = try KernelMessage.decode(frame)
            XCTAssertEqual(msg.typeName, type, file)
            if case .unknown = msg { XCTFail("\(file) als unbekannt gelesen") }
        }
    }

    func testPartZukaufFixture() throws {
        let (h, g) = try Fixtures.part("part_zukauf.frame")
        let exp = try XCTUnwrap(phase3()["parts"]?["part_zukauf.frame"])
        // Ersatzkörper: der Kernel hängt „(vereinfacht)“ an den Namen (KATALOG.md, Zukaufteil)
        XCTAssertEqual(h.name, "Rollwagen (vereinfacht)")
        XCTAssertEqual(h.name, exp["name"]?.stringValue)
        XCTAssertEqual(h.counts.tri, exp["counts"]?["tri"]?.intValue)
        XCTAssertEqual(h.counts.payloadBytes, exp["payload_bytes"]?.intValue)
        XCTAssertEqual(g.triangleCount, 12)
        XCTAssertEqual(h.bbox?.min, exp["bbox"]?["min"]?.doubles)
        XCTAssertEqual(h.bbox?.max, [305, 205, 128])
        XCTAssertEqual(h.inventar, "ok")
        XCTAssertNil(h.stock, "Zukaufteile haben kein stock")
        let z = try XCTUnwrap(h.zukauf)
        XCTAssertEqual(z, ZukaufPartInfo(json: try XCTUnwrap(exp["zukauf"])))
        XCTAssertEqual(z.id, "alutec-05200")
        XCTAssertEqual(z.hersteller, "ALUTEC")
        XCTAssertEqual(z.mpn, "05200")
        XCTAssertEqual(z.cad, .vereinfacht)
        XCTAssertTrue(z.isSimplified)
        XCTAssertEqual(z.preis, 24.99)
        XCTAssertEqual(z.url?.absoluteString, "https://www.beispiel-shop.de/p/alutec-05200")
        XCTAssertEqual(z.title, "ALUTEC 05200")
        XCTAssertNil(try Fixtures.part("part_box.frame").0.zukauf, "MVP-Teile ohne zukauf")

        // Werte für cad laut PROTOCOL.md und tolerantes Lesen
        let part = #"{"type":"PART_UPSERT","run":1,"name":"Rollwagen","counts":{"vert":0,"tri":0,"face":0,"edge":0,"epts":0,"vtx":0},"#
        let cases: [(String, String?, ZukaufCADSource?)] = [
            (#""zukauf":{"id":"blum-560h","cad":"hersteller"}"#, "blum-560h", .hersteller),
            (#""zukauf":{"id":"fx6","cad":"skript"}"#, "fx6", .skript),
            (#""zukauf":{"mpn":"123","cad":"vereinfacht"}"#, "123", .vereinfacht),
            (#""zukauf":{"hersteller":"nur"}"#, nil, nil),
            (#""zukauf":"kaputt""#, nil, nil),
            (#""zukauf":null"#, nil, nil),
        ]
        for (field, id, cad) in cases {
            let frame = Frame(header: Data((part + field + "}").utf8), payload: Data(repeating: 0, count: 4))
            guard case .partUpsert(let h, _) = try KernelMessage.decode(frame) else { return XCTFail(field) }
            XCTAssertEqual(h.zukauf?.id, id, field)
            XCTAssertEqual(h.zukauf?.cad, cad, field)
        }
    }

    func testZukaufStatusFixtures() throws {
        guard case .zukaufStatus(let s) = try Fixtures.message("zukauf_status_wartet.frame") else {
            return XCTFail("kein ZUKAUF_STATUS")
        }
        let raw = try header("zukauf_status_wartet.frame")
        XCTAssertEqual(s.id, "alutec-05200")
        XCTAssertEqual(s.zustand, .wartetAufCAD)
        XCTAssertEqual(s.text, raw["text"]?.stringValue)
        XCTAssertEqual(s.erwartet, ["step", "stp", "zip"])
        XCTAssertEqual(s.name, "ALUTEC Transportroller 05200", "name ist laut Festlegungen optional erlaubt")
        XCTAssertEqual(s.cadLinks.map(\.titel), ["Produktseite (CAD-Download oft dort)", "TraceParts: ALUTEC 05200"])
        XCTAssertEqual(s.cadLinks.map(\.url.absoluteString),
                       raw["cad_links"]?.arrayValue?.compactMap { $0["url"]?.stringValue })
        XCTAssertNil(KernelMessage.zukaufStatus(s).replyTo, "ZUKAUF_STATUS kommt immer als Ereignis")
        XCTAssertEqual(KernelMessage.zukaufStatus(s).typeName, "ZUKAUF_STATUS")

        guard case .zukaufStatus(let i) = try Fixtures.message("zukauf_status_importiert.frame") else {
            return XCTFail("kein ZUKAUF_STATUS")
        }
        XCTAssertEqual(i.id, "alutec-05200")
        XCTAssertEqual(i.zustand, .importiert)
        XCTAssertEqual(i.text, "CAD für ALUTEC Transportroller 05200 übernommen: 05200.stp, 5 Körper")
        XCTAssertTrue(i.cadLinks.isEmpty)
        XCTAssertTrue(i.erwartet.isEmpty)
        XCTAssertEqual(i.name, "ALUTEC Transportroller 05200")

        // Alle Zustände laut Vertrag, unbekannte bleiben lesbar
        for (text, zustand) in [("angelegt", ZukaufZustand.angelegt), ("wartet_auf_cad", .wartetAufCAD),
                                ("importiert", .importiert), ("fehler", .fehler), ("unbekannt", .other("unbekannt"))] {
            guard case .zukaufStatus(let m) = try decode(#"{"type":"ZUKAUF_STATUS","id":"x","zustand":"\#(text)"}"#)
            else { return XCTFail(text) }
            XCTAssertEqual(m.zustand, zustand)
            XCTAssertEqual(m.zustand.rawValue, text)
            XCTAssertTrue(m.cadLinks.isEmpty)
            XCTAssertTrue(m.erwartet.isEmpty)
            XCTAssertNil(m.name)
        }
        // Tolerant: Links als Text, unsichere Schemata, Endungen mit Punkt, falsche Typen
        guard case .zukaufStatus(let l) = try decode(#"""
            {"type":"ZUKAUF_STATUS","id":"alutec-05200","zustand":"wartet_auf_cad","erwartet":["STEP",".stp","zip"],
             "cad_links":["https://www.alutec.de/cad/05200",{"titel":"kaputt","url":"javascript:alert(1)"},{"titel":"ohne"}]}
            """#) else { return XCTFail() }
        XCTAssertEqual(l.erwartet, ["step", "stp", "zip"])
        XCTAssertEqual(l.cadLinks.map(\.titel), ["www.alutec.de"])
        guard case .zukaufStatus(let t) = try decode(
            #"{"type":"ZUKAUF_STATUS","id":5200,"zustand":null,"cad_links":"x","erwartet":7,"name":"Rollwagen"}"#)
        else { return XCTFail() }
        XCTAssertEqual(t.id, "5200")
        XCTAssertEqual(t.zustand, .other(""))
        XCTAssertEqual(t.name, "Rollwagen")
    }

    func testBOMZukaufFixture() throws {
        guard case .bom(let m) = try Fixtures.message("bom_zukauf.frame") else { return XCTFail("kein BOM") }
        XCTAssertEqual(m.bom.run, 4)
        XCTAssertEqual(m.bom.lines.count, 1)
        let line = m.bom.lines[0]
        XCTAssertEqual(line.art, "zukaufteil")
        XCTAssertEqual(line.stockID, "alutec-05200", "stock_id ist bei Zukaufteilen die Zukaufteil-id")
        XCTAssertEqual(line.benennung, "ALUTEC Transportroller 05200")
        XCTAssertNil(line.material)
        XCTAssertEqual(line.masseText, "610 × 410 × 128 mm")
        XCTAssertEqual(line.anzahl, 1)
        XCTAssertEqual(line.kgJe, 1.8)
        XCTAssertEqual(line.preisJe, 24.99)
        XCTAssertEqual(line.preis, 24.99)
        XCTAssertEqual(line.teile, ["Rollwagen (vereinfacht)"])
        XCTAssertFalse(line.eigenteil)
        let z = try XCTUnwrap(line.zukauf)
        XCTAssertEqual(z.hersteller, "ALUTEC")
        XCTAssertEqual(z.mpn, "05200")
        XCTAssertEqual(z.gtin, "4005187052008")
        XCTAssertEqual(z.url?.absoluteString, "https://www.beispiel-shop.de/p/alutec-05200")
        XCTAssertEqual(z.bild?.lastPathComponent, "05200.jpg")
        XCTAssertEqual(z.preisStand, "2026-10-21")
        XCTAssertEqual(z.preisBrutto, true)
        XCTAssertEqual(z.cadQuelle, "keins")
        XCTAssertTrue(z.vereinfacht)
        XCTAssertEqual(z.cadTitle, "vereinfacht (Ersatzkörper)")
        XCTAssertEqual(z.title, "ALUTEC · 05200")
        XCTAssertTrue(m.bom.cuts.isEmpty)
        XCTAssertEqual(m.bom.totals.preis, 24.99)
        XCTAssertEqual(m.bom.totals.preisHinweis, "Richtpreise, Stand 2026-10; Zukaufteile zum Shoppreis brutto")

        // Tolerant: Zeile ohne stock_id, nur http(s), CAD-Quelle ohne vereinfacht
        guard case .bom(let t) = try decode(#"""
            {"type":"BOM","run":2,"lines":[
             {"pos":1,"art":"zukaufteil","benennung":"Blum Tandembox","anzahl":2,"teile":["A","B"],"mpn":"560H",
              "cad_quelle":"traceparts","url":"ftp://nein"},
             {"pos":2,"art":"rund","stock_id":"rund-10","benennung":"Rundstahl","anzahl":1,"teile":["C"]}]}
            """#) else { return XCTFail("kein BOM") }
        let tandem = try XCTUnwrap(t.bom.lines[0].zukauf)
        XCTAssertFalse(t.bom.lines[0].eigenteil, "Zukaufteil ohne stock_id ist kein Eigenteil")
        XCTAssertFalse(tandem.vereinfacht)
        XCTAssertNil(tandem.url, "nur http(s)")
        XCTAssertNil(tandem.preisBrutto)
        XCTAssertEqual(tandem.cadTitle, "Hersteller-CAD (TraceParts)")
        XCTAssertNil(t.bom.lines[1].zukauf)
        XCTAssertEqual(ZukaufDate.display("2026-10-21"), "21.10.2026")
        XCTAssertEqual(ZukaufDate.display("2026-10"), "10/2026")
        XCTAssertNil(ZukaufDate.display(""))
    }

    func testCatalogZukaufFixture() throws {
        guard case .catalog(let msg) = try Fixtures.message("catalog_zukauf.frame") else { return XCTFail("kein CATALOG") }
        XCTAssertEqual(msg.replyTo, "a-10")
        let cat = msg.catalog
        XCTAssertTrue(cat.arten.contains("zukaufteil"), "CATALOG.arten enthält zukaufteil")
        XCTAssertEqual(CatalogSchema.art("zukaufteil").plural, "Zukaufteile")
        let item = try XCTUnwrap(cat.item("alutec-05200"))
        XCTAssertTrue(item.isZukauf)
        XCTAssertEqual(item.ebene, .projekt)
        XCTAssertNil(item.entry["ebene"])
        XCTAssertEqual(item.preisText, "24,99 €/Stück")
        let info = try XCTUnwrap(item.zukaufInfo)
        XCTAssertTrue(info.isSimplified)
        XCTAssertEqual(info.cadTitle, "keins, Ersatzkörper aus den Maßen")
        XCTAssertEqual(info.preisText, "24,99 € brutto")
        XCTAssertEqual(info.masseText, "610 × 410 × 128 mm")
        XCTAssertEqual(info.gewicht, 1800)
        XCTAssertEqual(item.entry["bezugspunkte"]?["oben"]?["pos"]?.doubles, [0, 0, 128])
        XCTAssertEqual(cat.zukauf(matching: .gtin("4005187052008"))?.id, "alutec-05200")
        XCTAssertEqual(cat.zukauf(matching: .link(URL(string: "https://beispiel-shop.de/p/alutec-05200/")!))?.id,
                       "alutec-05200")

        // Katalogeintrag → Dialog → ZUKAUF_NEU.felder: genau der Eintrag aus der Testdatei des Kernels
        let draft = ZukaufDraft(entry: item.entry)
        XCTAssertTrue(draft.validate().isEmpty, "\(draft.validate())")
        XCTAssertEqual(draft.entry(), try header("zukauf_neu.frame")["felder"])

        // Kugel (masse nur mit d): wie im Kernel „Ø 70 mm“
        XCTAssertEqual(ZukaufEntryInfo(entry: ["art": "zukaufteil", "masse": ["d": 70]]).masseText, "Ø 70 mm")
    }

    /// Was die App schickt, gleicht den Testdateien des Kernels (ZUKAUF_NEU, DOWNLOAD_SEEN, ZUKAUF_CAD).
    func testOutgoingMatchesFixtures() throws {
        let neuFixture = try header("zukauf_neu.frame")
        let felder = try XCTUnwrap(neuFixture["felder"])
        var neu = ZukaufNewMessage(id: "a-11", eingabe: "https://www.beispiel-shop.de/p/alutec-05200",
                                   felder: ZukaufDraft(entry: felder).entry(), ebene: .projekt)
        neu.seq = 5
        XCTAssertEqual(try sent(neu), neuFixture)

        // Ein frischer Dialog (Link einfügen, Felder tippen) ergibt dieselben Kernfelder
        var d = ZukaufDraft(input: "https://www.beispiel-shop.de/p/alutec-05200")
        d.hersteller = "ALUTEC"
        d.mpn = "05200"
        d.gtin = "4005187052008"
        d.name = "ALUTEC Transportroller 05200"
        d.id = d.suggestedID()
        d.masse = ["l": "610", "b": "410", "h": "128"]
        d.preis = "24,99"
        d.preisStand = "2026-10-21"
        d.gewicht = "1800"
        XCTAssertTrue(d.validate().isEmpty, "\(d.validate())")
        let typed = d.entry()
        for key in ["id", "art", "name", "hersteller", "mpn", "gtin", "url", "preis", "masse", "gewicht", "ersatz",
                    "status"] {
            XCTAssertEqual(typed[key], felder[key], key)
        }

        let seenFixture = try header("download_seen.frame")
        let zeitText = try XCTUnwrap(seenFixture["zeit"]?.stringValue)
        let zeit = try XCTUnwrap(ISO8601DateFormatter().date(from: zeitText))
        var seen = DownloadSeenMessage(pfad: "/Users/test/Downloads/ALUTEC_05200_CAD.zip", groesse: 24641, zeit: zeit)
        seen.seq = 6
        let seenJSON = try sent(seen)
        XCTAssertEqual(seenJSON.objectValue?.keys.sorted(), seenFixture.objectValue?.keys.sorted())
        for key in ["type", "seq", "pfad", "groesse"] { XCTAssertEqual(seenJSON[key], seenFixture[key], key) }
        XCTAssertNil(seenJSON["id"], "DOWNLOAD_SEEN ist keine Anfrage")
        // zeit: ISO 8601 mit Zeitzone, in Berlin genau wie in der Testdatei
        XCTAssertEqual(DownloadSeenMessage.isoString(zeit, timeZone: TimeZone(identifier: "Europe/Berlin")!), zeitText)
        XCTAssertEqual(ISO8601DateFormatter().date(from: try XCTUnwrap(seenJSON["zeit"]?.stringValue)), zeit)

        var cad = ZukaufCADMessage(id: "a-12", teil: "alutec-05200", pfad: "/Users/test/Downloads/ALUTEC_05200_CAD.zip")
        cad.seq = 7
        XCTAssertEqual(try sent(cad), try header("zukauf_cad.frame"))
    }
}

/// Dialog-Modell: Eingabe erkennen, Felder prüfen, Eintrag laut KATALOG.md.
final class ZukaufDraftTests: XCTestCase {
    func testClassifyInput() {
        XCTAssertEqual(ZukaufInput.classify("  "), .empty)
        guard case .link(let url) = ZukaufInput.classify(" https://www.obi.de/p/123?x=1 ") else { return XCTFail() }
        XCTAssertEqual(url.host, "www.obi.de")
        XCTAssertEqual(ZukaufInput.shopName(url), "obi.de")
        XCTAssertEqual(ZukaufInput.classify("https://www.obi.de/p/123").title, "Shop-Link · obi.de")
        guard case .link(let www) = ZukaufInput.classify("www.igus.de/product/1") else { return XCTFail() }
        XCTAssertEqual(www.scheme, "https")
        XCTAssertEqual(ZukaufInput.classify("4005187052008"), .gtin("4005187052008"))
        XCTAssertEqual(ZukaufInput.classify("4005 1870 5200 8"), .gtin("4005187052008"))
        XCTAssertEqual(ZukaufInput.classify("4005187052009"), .mpn("4005187052009"), "falsche Prüfziffer: Nummer")
        XCTAssertEqual(ZukaufInput.classify("05200"), .mpn("05200"))
        XCTAssertEqual(ZukaufInput.classify("560H5000B"), .mpn("560H5000B"))
        XCTAssertTrue(GTIN.isValid("96385074"), "EAN-8")
        XCTAssertTrue(GTIN.isValid("036000291452"), "UPC-A")
        XCTAssertTrue(GTIN.isValid("10012345678902"), "GTIN-14")
        XCTAssertFalse(GTIN.isValid("12345"))
        XCTAssertFalse(GTIN.isValid("40051870520a9"))
    }

    func testDraftValidateAndEntry() throws {
        var d = ZukaufDraft(input: "4005187052008")
        XCTAssertEqual(d.gtin, "4005187052008")
        XCTAssertEqual(d.eingabe, "4005187052008")
        let fields = Set(d.validate().map(\.field))
        XCTAssertEqual(fields, ["id", "name", "hersteller", "mpn", "masse.l", "masse.b", "masse.h"])

        d.hersteller = "ALUTEC"
        d.mpn = "05200"
        XCTAssertEqual(d.suggestedID(), "alutec-05200")
        XCTAssertEqual(d.suggestedName(), "ALUTEC 05200")
        d.id = d.suggestedID()
        d.name = "ALUTEC Transportroller 05200"
        d.masse = ["l": "610", "b": "410", "h": "128,5", "d": "99"]
        d.preis = "24,99"
        d.preisStand = "2026-10-21"
        d.brutto = true
        d.url = "https://www.beispiel-shop.de/p/alutec-05200"
        d.bild = "ftp://bild"
        d.gewicht = "1800"
        d.material = "polypropylen"
        XCTAssertEqual(d.validate().map(\.field), ["bild"])
        d.bild = "https://www.beispiel-shop.de/b.jpg"
        d.gtin = "4005187052009"
        XCTAssertEqual(d.validate().map(\.message), ["Prüfziffer der EAN stimmt nicht"])
        d.gtin = "4005187052008"
        d.preisStand = "21.10.2026"
        XCTAssertEqual(d.validate().map(\.field), ["preis_stand"])
        d.preisStand = "2026-10-21"
        XCTAssertTrue(d.validate().isEmpty)

        let e = d.entry()
        XCTAssertEqual(e["art"]?.stringValue, "zukaufteil")
        XCTAssertEqual(e["status"]?.stringValue, "frei")
        XCTAssertEqual(e["masse"]?.objectValue?.keys.sorted(), ["b", "h", "l"], "nur Maße der Form")
        XCTAssertEqual(e["masse"]?["h"]?.doubleValue, 128.5)
        XCTAssertEqual(e["ersatz"]?["form"]?.stringValue, "quader")
        XCTAssertEqual(e["ersatz"]?["masse"]?["l"]?.doubleValue, 610)
        XCTAssertEqual(e["preis"]?["je_stueck"]?.doubleValue, 24.99)
        XCTAssertEqual(e["preis"]?["brutto"]?.boolValue, true)
        XCTAssertEqual(e["preis"]?["waehrung"]?.stringValue, "EUR")
        XCTAssertEqual(e["preis"]?["stand"]?.stringValue, "2026-10-21")
        XCTAssertEqual(e["preis"]?["quelle"]?.stringValue, d.url, "Quelle ist der Link, wenn leer")
        XCTAssertEqual(e["gewicht"]?.doubleValue, 1800)
        XCTAssertNil(e["shop_nr"])

        // Shop-Artikel ohne Hersteller und MPN, Zylinder
        var s = ZukaufDraft()
        s.shopNr = "OBI-123"
        s.name = "Rolle"
        s.id = s.suggestedID()
        s.form = .zylinder
        s.masse = ["d": "75", "l": "30"]
        XCTAssertEqual(s.id, "obi-123")
        XCTAssertTrue(s.validate().isEmpty, "\(s.validate())")
        XCTAssertEqual(ZukaufEntryInfo(entry: s.entry()).masseText, "Ø 75 × 30 mm")
    }

    func testDraftRoundTripKeepsUnknownFields() throws {
        let entry: JSONValue = [
            "id": "alutec-05200", "art": "zukaufteil", "name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC",
            "mpn": "05200", "gtin": "4005187052008", "url": "https://shop.de/p", "bild": "https://shop.de/b.jpg",
            "preis": ["je_stueck": 24.99, "waehrung": "EUR", "brutto": false, "stand": "2026-10-20", "quelle": "Angebot"],
            "masse": ["l": 610, "b": 410, "h": 128], "gewicht": 1800, "material": "polypropylen",
            "cad": ["quelle": "download", "datei": "zukauf/alutec-05200/05200.step"],
            "ersatz": ["form": "quader", "masse": ["l": 610, "b": 410, "h": 128], "farbe": "#888888"],
            "einbaupunkt": ["pos": [0, 0, 0]], "status": "vorgeschlagen", "vorgeschlagen_von": "agent",
        ]
        let d = ZukaufDraft(entry: entry)
        XCTAssertEqual(d.preis, "24,99")
        XCTAssertFalse(d.brutto)
        XCTAssertEqual(d.preisQuelle, "Angebot")
        XCTAssertEqual(d.masse["h"], "128")
        XCTAssertTrue(d.validate().isEmpty, "\(d.validate())")
        let back = d.entry()
        XCTAssertEqual(back["status"]?.stringValue, "frei", "bestätigt ist freigegeben")
        XCTAssertNil(back["vorgeschlagen_von"])
        XCTAssertEqual(back["cad"]?["datei"]?.stringValue, "zukauf/alutec-05200/05200.step")
        XCTAssertEqual(back["einbaupunkt"]?["pos"]?.doubles, [0, 0, 0])
        XCTAssertEqual(back["ersatz"]?["farbe"]?.stringValue, "#888888")
        XCTAssertEqual(back["preis"]?["quelle"]?.stringValue, "Angebot")

        let info = ZukaufEntryInfo(entry: entry)
        XCTAssertFalse(info.isSimplified)
        XCTAssertEqual(info.cadTitle, "Hersteller-CAD (Download)")
        XCTAssertEqual(info.preisText, "24,99 € netto")
        XCTAssertEqual(info.masseText, "610 × 410 × 128 mm")
        XCTAssertTrue(ZukaufEntryInfo(entry: ["art": "zukaufteil"]).isSimplified)

        // Katalog: Zukaufteil wiederfinden
        let cat = Catalog(json: ["items": [entry.merging(["ebene": "projekt"]), ["id": "rohr", "art": "rohr", "name": "Rohr"]]])
        XCTAssertEqual(cat.item("alutec-05200")?.isZukauf, true)
        XCTAssertEqual(cat.item("alutec-05200")?.preisText, "24,99 €/Stück")
        XCTAssertEqual(cat.zukauf(matching: .link(URL(string: "http://shop.de/p/?ref=x")!))?.id, "alutec-05200")
        XCTAssertEqual(cat.zukauf(matching: .gtin("4005187052008"))?.id, "alutec-05200")
        XCTAssertEqual(cat.zukauf(matching: .mpn("05-200"))?.id, "alutec-05200")
        XCTAssertNil(cat.zukauf(matching: .mpn("05201")))
        XCTAssertEqual(CatalogSchema.art("zukaufteil").plural, "Zukaufteile")
    }
}

extension JSONValue {
    fileprivate func merging(_ other: [String: JSONValue]) -> JSONValue {
        guard var o = objectValue else { return self }
        for (k, v) in other { o[k] = v }
        return .object(o)
    }
}

/// Downloads-Beobachtung in einem Temp-Ordner (nie im echten ~/Downloads).
final class DownloadScannerTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-dl-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    private func write(_ name: String, bytes: Int) throws -> URL {
        let url = dir.appendingPathComponent(name)
        try Data(repeating: 7, count: bytes).write(to: url)
        return url
    }

    func testScannerReportsStableNewFilesOnce() throws {
        let old = try write("alt.step", bytes: 10)
        var scanner = DownloadScanner(directory: dir, extensions: ["STEP", ".stp", "zip"], since: Date().addingTimeInterval(1))
        XCTAssertEqual(scanner.extensions, ["step", "stp", "zip"])
        let t0 = Date().addingTimeInterval(2)
        // Erst in den Zukunftszeitpunkt schieben, damit „alt.step“ vor `since` liegt
        try FileManager.default.setAttributes([.modificationDate: Date().addingTimeInterval(-600)], ofItemAtPath: old.path)
        scanner.since = Date().addingTimeInterval(0.5)
        Thread.sleep(forTimeInterval: 0.6)
        _ = try write("05200.step", bytes: 1000)
        _ = try write("05200.step.crdownload", bytes: 500)
        _ = try write("leer.stp", bytes: 0)
        _ = try write("bild.jpg", bytes: 100)
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("ordner.zip"), withIntermediateDirectories: true)
        XCTAssertTrue(scanner.scan(now: t0).isEmpty, "erst gesehen, noch nicht stabil")
        XCTAssertEqual(scanner.pendingCount, 1)
        var found = scanner.scan(now: t0.addingTimeInterval(1))
        XCTAssertEqual(found.map(\.url.lastPathComponent), ["05200.step"])
        XCTAssertEqual(found.first?.size, 1000)
        XCTAssertTrue(scanner.scan(now: t0.addingTimeInterval(2)).isEmpty, "nur einmal")

        // Wächst noch: erst melden, wenn die Größe steht
        let big = try write("gross.zip", bytes: 100)
        XCTAssertTrue(scanner.scan(now: t0.addingTimeInterval(3)).isEmpty)
        try Data(repeating: 1, count: 5000).write(to: big)
        XCTAssertTrue(scanner.scan(now: t0.addingTimeInterval(4)).isEmpty, "Größe hat sich geändert")
        found = scanner.scan(now: t0.addingTimeInterval(5))
        XCTAssertEqual(found.map(\.url.lastPathComponent), ["gross.zip"])

        // Dieselbe Datei neu heruntergeladen (andere Größe): wieder neu
        _ = try write("05200.step", bytes: 2000)
        XCTAssertTrue(scanner.scan(now: t0.addingTimeInterval(6)).isEmpty)
        XCTAssertEqual(scanner.scan(now: t0.addingTimeInterval(7)).map(\.size), [2000])
    }

    @MainActor
    func testWatcherSeesNewFile() throws {
        let watcher = DownloadWatcher(directory: dir, extensions: ["step"], lookback: 0)
        var seen: [DownloadCandidate] = []
        watcher.onFile = { seen.append($0) }
        watcher.start()
        defer { watcher.stop() }
        XCTAssertTrue(watcher.isRunning)
        _ = try write("Vollauszug.STEP", bytes: 4096)
        let end = Date().addingTimeInterval(5)
        while seen.isEmpty && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
        XCTAssertEqual(seen.map(\.url.lastPathComponent), ["Vollauszug.STEP"])
        watcher.stop()
        XCTAssertFalse(watcher.isRunning)
    }
}

/// App-Kern: ZUKAUF_STATUS, Downloads-Rückfrage, ZUKAUF_NEU und ZUKAUF_CAD, Ersatzkörper im Viewer.
@MainActor
final class Phase3ControllerTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-dl-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    private func connectedController() throws -> AppController {
        let c = AppController(model: AppModel())
        c.zukaufState.recordSent = true
        c.zukaufState.directoryOverride = dir
        c.zukaufState.lookback = 0
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        return c
    }

    private func message(_ json: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(json.utf8))))
    }

    private func lastSent(_ c: AppController, _ type: String) -> JSONValue? {
        c.zukaufState.sent.last { $0.type == type }?.header
    }

    private func wait(_ seconds: Double, _ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while !condition() && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
        return condition()
    }

    /// Ablauf mit den Testdateien des Kernels: wartet_auf_cad → neue Datei → Rückfrage → ZUKAUF_CAD → importiert.
    func testWaitingDownloadOfferAndImport() throws {
        let c = try connectedController()
        let m = c.model
        XCTAssertNil(m.watchedDownloads)
        c.handle([.message(try Fixtures.message("zukauf_status_wartet.frame"))])
        XCTAssertEqual(m.waitingForCAD.map(\.id), ["alutec-05200"])
        XCTAssertEqual(m.zukaufStatus.first?.name, "ALUTEC Transportroller 05200")
        XCTAssertEqual(m.zukaufStatus.first?.cadLinks.map(\.titel),
                       ["Produktseite (CAD-Download oft dort)", "TraceParts: ALUTEC 05200"])
        XCTAssertEqual(m.zukaufStatus.first?.erwartet, ["step", "stp", "zip"])
        XCTAssertEqual(m.watchedDownloads, dir, "Beobachtung läuft nur im Temp-Ordner")
        XCTAssertEqual(c.zukaufState.watcher?.extensions, ["step", "stp", "zip"])
        XCTAssertTrue(m.log.contains { $0.text.contains("wartet auf CAD") })

        // Falsche Endung: keine Rückfrage
        try Data(repeating: 1, count: 200).write(to: dir.appendingPathComponent("anleitung.pdf"))
        // Passende Datei: DOWNLOAD_SEEN und Rückfrage
        let file = dir.appendingPathComponent("ALUTEC_05200_CAD.zip")
        try Data(repeating: 1, count: 24641).write(to: file)
        XCTAssertTrue(wait(5) { m.downloadOffer != nil }, "Rückfrage erwartet")
        let offer = try XCTUnwrap(m.downloadOffer)
        XCTAssertEqual(offer.fileName, "ALUTEC_05200_CAD.zip")
        XCTAssertEqual(offer.size, 24641)
        XCTAssertEqual(offer.candidates, ["alutec-05200"])
        let seen = try XCTUnwrap(lastSent(c, "DOWNLOAD_SEEN"))
        let seenFixture = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("download_seen.frame").header)
        XCTAssertEqual(seen.objectValue?.keys.sorted(), seenFixture.objectValue?.keys.sorted())
        XCTAssertEqual(seen["pfad"]?.stringValue, file.path)
        XCTAssertEqual(seen["groesse"], seenFixture["groesse"])
        XCTAssertEqual(c.zukaufState.sent.filter { $0.type == "DOWNLOAD_SEEN" }.count, 1)

        // Ja: ZUKAUF_CAD wie in der Testdatei, Rückfrage weg, Zustand zeigt die Übergabe
        c.acceptDownload(for: "alutec-05200")
        XCTAssertNil(m.downloadOffer)
        let cad = try XCTUnwrap(lastSent(c, "ZUKAUF_CAD"))
        let cadFixture = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("zukauf_cad.frame").header)
        XCTAssertEqual(cad.objectValue?.keys.sorted(), cadFixture.objectValue?.keys.sorted())
        XCTAssertEqual(cad["teil"], cadFixture["teil"])
        XCTAssertEqual(cad["pfad"]?.stringValue, file.path)
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.uebergabe, "ALUTEC_05200_CAD.zip")
        let id = try XCTUnwrap(cad["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id)","ok":true,"message":"CAD wird übernommen"}"#)])
        // Dieselbe Datei kommt nicht noch einmal
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        XCTAssertNil(m.downloadOffer)

        // Importiert: Beobachtung aus, Meldung verschwindet nach kurzer Zeit
        c.zukaufState.importedDisplay = 0.2
        c.handle([.message(try Fixtures.message("zukauf_status_importiert.frame"))])
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.zustand, .importiert)
        XCTAssertNil(m.zukaufStatus(for: "alutec-05200")?.uebergabe)
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.text,
                       "CAD für ALUTEC Transportroller 05200 übernommen: 05200.stp, 5 Körper")
        XCTAssertNil(m.watchedDownloads)
        XCTAssertNil(c.zukaufState.watcher)
        XCTAssertTrue(wait(2) { m.zukaufStatus.isEmpty })
    }

    /// Der Kernel lehnt eine Datei ab (falsche Maße): ACK ok, dann ZUKAUF_STATUS `fehler` und wieder `wartet_auf_cad`.
    /// Die App beobachtet weiter, die abgelehnte Datei kommt nicht noch einmal, die nächste schon.
    func testRejectedFileKeepsWatching() throws {
        let c = try connectedController()
        let m = c.model
        c.handle([.message(try Fixtures.message("zukauf_status_wartet.frame"))])
        let falsch = dir.appendingPathComponent("falsch.step")
        try Data(repeating: 1, count: 500).write(to: falsch)
        XCTAssertTrue(wait(5) { m.downloadOffer != nil })
        c.acceptDownload(for: "alutec-05200")
        let id = try XCTUnwrap(lastSent(c, "ZUKAUF_CAD")?["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id)","ok":true,"message":"CAD wird übernommen"}"#)])
        c.handle([try message(#"""
            {"type":"ZUKAUF_STATUS","id":"alutec-05200","zustand":"fehler","text":"Hüllmaß passt nicht",
             "cad_links":[],"erwartet":[],"name":"ALUTEC Transportroller 05200"}
            """#)])
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.zustand, .fehler)
        XCTAssertTrue(m.log.contains { $0.text.contains("Hüllmaß passt nicht") })
        var again = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("zukauf_status_wartet.frame").header)
        if case .object(var o) = again {
            o["text"] = "falsch.step abgelehnt: Hüllmaß passt nicht"
            again = .object(o)
        }
        c.handle([.message(.zukaufStatus(ZukaufStatusMessage(json: again)))])
        XCTAssertEqual(m.waitingForCAD.map(\.id), ["alutec-05200"])
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.text, "falsch.step abgelehnt: Hüllmaß passt nicht")
        XCTAssertNotNil(c.zukaufState.watcher)
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        XCTAssertNil(m.downloadOffer, "abgelehnte Datei nicht noch einmal")
        try Data(repeating: 1, count: 900).write(to: dir.appendingPathComponent("richtig.stp"))
        XCTAssertTrue(wait(5) { m.downloadOffer?.fileName == "richtig.stp" })

        // ACK ok:false (Teil unbekannt) zeigt den Text, das Teil wartet weiter
        c.acceptDownload(for: "alutec-05200")
        let id2 = try XCTUnwrap(lastSent(c, "ZUKAUF_CAD")?["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id2)","ok":false,"message":"Zukaufteil 'x' gibt es nicht"}"#)])
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.zustand, .wartetAufCAD)
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.text, "Zukaufteil 'x' gibt es nicht")
    }

    func testDeclineQueueAndRejectedCAD() throws {
        let c = try connectedController()
        let m = c.model
        c.handle([try message(#"{"type":"ZUKAUF_STATUS","id":"a","zustand":"wartet_auf_cad","erwartet":["step"]}"#)])
        c.handle([try message(#"{"type":"ZUKAUF_STATUS","id":"b","zustand":"wartet_auf_cad","erwartet":["zip"]}"#)])
        XCTAssertEqual(m.waitingForCAD.map(\.id), ["a", "b"])
        try Data(repeating: 1, count: 10).write(to: dir.appendingPathComponent("erste.step"))
        XCTAssertTrue(wait(5) { m.downloadOffer != nil })
        try Data(repeating: 1, count: 10).write(to: dir.appendingPathComponent("zweite.zip"))
        XCTAssertTrue(wait(5) { c.zukaufState.queuedOffers.count == 1 })
        XCTAssertEqual(m.downloadOffer?.fileName, "erste.step")
        XCTAssertEqual(m.downloadOffer?.candidates, ["a"], "nur Teile, deren Endung passt")

        // Nein: nächste Rückfrage
        c.declineDownload()
        XCTAssertEqual(m.downloadOffer?.fileName, "zweite.zip")
        XCTAssertEqual(m.downloadOffer?.candidates, ["b"])
        XCTAssertTrue(m.log.contains { $0.text.contains("erste.step nicht als CAD übernommen") })

        // Kernel lehnt die Datei ab: Teil wartet weiter, Fehler im Text
        c.acceptDownload(for: "b")
        let id = try XCTUnwrap(lastSent(c, "ZUKAUF_CAD")?["id"]?.stringValue)
        c.handle([try message(#"{"type":"ERROR","reply_to":"\#(id)","message":"ZIP enthält keine STEP-Datei"}"#)])
        XCTAssertEqual(m.zukaufStatus(for: "b")?.zustand, .wartetAufCAD)
        XCTAssertEqual(m.zukaufStatus(for: "b")?.text, "ZIP enthält keine STEP-Datei")
        XCTAssertNil(m.zukaufStatus(for: "b")?.uebergabe)

        // Teil a ausblenden: Beobachtung läuft für b weiter; b fertig: Beobachtung aus
        c.dismissZukaufStatus("a")
        XCTAssertEqual(m.waitingForCAD.map(\.id), ["b"])
        XCTAssertEqual(c.zukaufState.watcher?.extensions, ["zip"])
        c.handle([try message(#"{"type":"ZUKAUF_STATUS","id":"b","zustand":"fehler","text":"Import fehlgeschlagen"}"#)])
        XCTAssertNil(c.zukaufState.watcher)
        XCTAssertEqual(m.zukaufStatus(for: "b")?.zustand, .fehler)

        // Datei selbst wählen für ein Teil ohne Zustand
        let own = dir.appendingPathComponent("eigen.step")
        c.assignCAD(file: own, to: "rolle-75")
        XCTAssertEqual(lastSent(c, "ZUKAUF_CAD")?["teil"]?.stringValue, "rolle-75")
        XCTAssertEqual(m.zukaufStatus(for: "rolle-75")?.uebergabe, "eigen.step")

        // Projektwechsel vergisst alles
        c.handle([try message(#"{"type":"PROJECT","path":"/tmp/kevcad-zukauf-anderes","name":"anderes"}"#)])
        XCTAssertTrue(m.zukaufStatus.isEmpty)
        XCTAssertNil(m.downloadOffer)
    }

    func testAddZukauf() throws {
        var draft = ZukaufDraft(input: "4005187052008")
        draft.hersteller = "ALUTEC"
        draft.mpn = "05200"
        draft.name = "ALUTEC Transportroller 05200"
        draft.id = draft.suggestedID()
        draft.masse = ["l": "610", "b": "410", "h": "128"]

        let off = AppController(model: AppModel())
        off.addZukauf(eingabe: draft.eingabe, felder: draft.json(), ebene: .projekt)
        if case .failed(let text) = off.model.zukaufActivity {
            XCTAssertTrue(text.contains("nicht verbunden"), text)
        } else {
            XCTFail("ohne Kernel: \(off.model.zukaufActivity)")
        }

        let c = try connectedController()
        let m = c.model
        c.addZukauf(eingabe: draft.eingabe, felder: draft.json(), ebene: .mitgeliefert)
        if case .failed = m.zukaufActivity {} else { XCTFail("mitgeliefert geht nicht") }
        c.addZukauf(eingabe: draft.eingabe, felder: Data("[]".utf8), ebene: .projekt)
        if case .failed = m.zukaufActivity {} else { XCTFail("kein Objekt") }

        c.addZukauf(eingabe: draft.eingabe, felder: draft.json(), ebene: .projekt)
        XCTAssertEqual(m.zukaufActivity, .sending)
        let neu = try XCTUnwrap(lastSent(c, "ZUKAUF_NEU"))
        XCTAssertEqual(neu["eingabe"]?.stringValue, "4005187052008")
        XCTAssertEqual(neu["ebene"]?.stringValue, "projekt")
        XCTAssertEqual(neu["felder"]?["gtin"]?.stringValue, "4005187052008")
        let id = try XCTUnwrap(neu["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id)","ok":true,"message":"katalog.json im Projekt"}"#)])
        XCTAssertEqual(m.zukaufActivity, .accepted(id: "alutec-05200", message: "katalog.json im Projekt"))
        // Der Name aus dem Dialog trägt ZUKAUF_STATUS ohne name
        c.handle([try message(#"{"type":"ZUKAUF_STATUS","id":"alutec-05200","zustand":"angelegt"}"#)])
        XCTAssertEqual(m.zukaufStatus(for: "alutec-05200")?.name, "ALUTEC Transportroller 05200")
        XCTAssertNil(m.watchedDownloads, "angelegt allein beobachtet nichts")

        c.addZukauf(eingabe: draft.eingabe, felder: draft.json(), ebene: .eigen)
        let id2 = try XCTUnwrap(lastSent(c, "ZUKAUF_NEU")?["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id2)","ok":false,"message":"MPN fehlt"}"#)])
        XCTAssertEqual(m.zukaufActivity, .failed("MPN fehlt"))
    }

    func testSimplifiedPartIsTransparent() throws {
        let c = try connectedController()
        let m = c.model
        /// part_zukauf.frame aus dem Kernel, `zukauf.cad` wahlweise ersetzt bzw. entfernt.
        func part(_ cad: String?) throws -> IncomingEvent {
            var frame = try Fixtures.frame("part_zukauf.frame")
            guard case .object(var head) = try JSONDecoder().decode(JSONValue.self, from: frame.header),
                  case .object(var zukauf)? = head["zukauf"]
            else { throw NSError(domain: "t", code: 1) }
            if let cad {
                zukauf["cad"] = .string(cad)
                head["zukauf"] = .object(zukauf)
            } else {
                head["zukauf"] = nil
            }
            frame.header = try JSONEncoder().encode(JSONValue.object(head))
            return KernelConnection.decode(frame)
        }
        c.handle([.message(try Fixtures.message("part_zukauf.frame"))])
        let node = try XCTUnwrap(m.parts.first)
        XCTAssertEqual(node.id, "Rollwagen (vereinfacht)")
        XCTAssertEqual(node.zukauf?.id, "alutec-05200")
        XCTAssertEqual(node.zukauf?.isSimplified, true)
        XCTAssertFalse(node.inventarFehlt)
        XCTAssertEqual(c.scene.simplifiedParts, [node.id])
        let body = try XCTUnwrap(c.scene.bodies.first { c.scene.owner(ofBody: $0.id)?.part == node.id })
        XCTAssertLessThan(body.color.w, 0.5, "halbtransparent")
        XCTAssertGreaterThan(c.scene.renderBodies.count, c.scene.bodies.count + 1, "Kanten des Ersatzkörpers extra")

        // Stückliste aus dem Kernel: Zeile mit Hersteller, Nummer, Preis, Link
        c.handle([.message(try Fixtures.message("bom_zukauf.frame"))])
        let line = try XCTUnwrap(m.bom?.lines.first)
        XCTAssertEqual(line.zukauf?.title, "ALUTEC · 05200")
        XCTAssertEqual(line.teile, [node.id], "Stücklistenzeile verweist auf das Teil im Baum")

        // Hersteller-CAD: wieder deckend
        c.handle([try part("hersteller")])
        XCTAssertEqual(m.parts.first?.zukauf?.cad, .hersteller)
        XCTAssertTrue(c.scene.simplifiedParts.isEmpty)
        let solid = try XCTUnwrap(c.scene.bodies.first { c.scene.owner(ofBody: $0.id)?.part == node.id })
        XCTAssertEqual(solid.color.w, 1)
        c.handle([try part(nil)])
        XCTAssertNil(m.parts.first?.zukauf)
    }
}
