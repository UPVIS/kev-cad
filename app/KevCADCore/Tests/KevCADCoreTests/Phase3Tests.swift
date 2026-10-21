import Foundation
import XCTest

@testable import KevCADCore

/// Phase 3 (Z-A): Dekodieren von ZUKAUF_STATUS, PART_UPSERT.zukauf und Stücklistenzeilen `art: "zukaufteil"`,
/// Nachrichten der App, Dialog-Modell und Downloads-Beobachtung (nur in Temp-Ordnern).
final class Phase3ProtocolTests: XCTestCase {
    private func decode(_ json: String, payload: Data = Data()) throws -> KernelMessage {
        try KernelMessage.decode(Frame(header: Data(json.utf8), payload: payload))
    }

    func testZukaufStatus() throws {
        guard case .zukaufStatus(let s) = try decode(#"""
            {"type":"ZUKAUF_STATUS","seq":4,"id":"alutec-05200","zustand":"wartet_auf_cad",
             "text":"Kein Modell bei TraceParts","erwartet":["STEP",".stp","zip"],
             "cad_links":[{"titel":"PARTcommunity","url":"https://alutec.partcommunity.com/?mpn=05200"},
                          "https://www.alutec.de/cad/05200",{"titel":"kaputt","url":"javascript:alert(1)"},{"titel":"ohne"}]}
            """#) else { return XCTFail("kein ZUKAUF_STATUS") }
        XCTAssertEqual(s.id, "alutec-05200")
        XCTAssertEqual(s.zustand, .wartetAufCAD)
        XCTAssertEqual(s.text, "Kein Modell bei TraceParts")
        XCTAssertEqual(s.erwartet, ["step", "stp", "zip"])
        XCTAssertEqual(s.cadLinks.map(\.titel), ["PARTcommunity", "www.alutec.de"])
        XCTAssertEqual(s.cadLinks[0].url.absoluteString, "https://alutec.partcommunity.com/?mpn=05200")
        XCTAssertNil(s.name)
        XCTAssertNil(KernelMessage.zukaufStatus(s).replyTo, "ZUKAUF_STATUS kommt immer als Ereignis")
        XCTAssertEqual(KernelMessage.zukaufStatus(s).typeName, "ZUKAUF_STATUS")

        for (text, zustand) in [("angelegt", ZukaufZustand.angelegt), ("importiert", .importiert), ("fehler", .fehler),
                                ("unbekannt", .other("unbekannt"))] {
            guard case .zukaufStatus(let m) = try decode(#"{"type":"ZUKAUF_STATUS","id":"x","zustand":"\#(text)"}"#)
            else { return XCTFail(text) }
            XCTAssertEqual(m.zustand, zustand)
            XCTAssertEqual(m.zustand.rawValue, text)
            XCTAssertTrue(m.cadLinks.isEmpty)
            XCTAssertTrue(m.erwartet.isEmpty)
        }
        // Tolerant: falsche Typen, optionaler Name
        guard case .zukaufStatus(let t) = try decode(
            #"{"type":"ZUKAUF_STATUS","id":5200,"zustand":null,"cad_links":"x","erwartet":7,"name":"Rollwagen"}"#)
        else { return XCTFail() }
        XCTAssertEqual(t.id, "5200")
        XCTAssertEqual(t.zustand, .other(""))
        XCTAssertEqual(t.name, "Rollwagen")
    }

    func testPartUpsertZukauf() throws {
        let part = #"{"type":"PART_UPSERT","run":1,"name":"Rollwagen","counts":{"vert":0,"tri":0,"face":0,"edge":0,"epts":0,"vtx":0},"#
        let cases: [(String, String?, ZukaufCADSource?)] = [
            (#""zukauf":{"id":"alutec-05200","hersteller":"ALUTEC","mpn":"05200","cad":"vereinfacht","preis":24.99,"url":"https://shop.de/p"}"#,
             "alutec-05200", .vereinfacht),
            (#""zukauf":{"id":"blum-560h","cad":"hersteller"}"#, "blum-560h", .hersteller),
            (#""zukauf":{"mpn":"123","cad":"skript"}"#, "123", .skript),
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
        let frame = Frame(header: Data((part + cases[0].0 + "}").utf8), payload: Data(repeating: 0, count: 4))
        guard case .partUpsert(let h, _) = try KernelMessage.decode(frame), let z = h.zukauf else { return XCTFail() }
        XCTAssertTrue(z.isSimplified)
        XCTAssertEqual(z.hersteller, "ALUTEC")
        XCTAssertEqual(z.mpn, "05200")
        XCTAssertEqual(z.preis, 24.99)
        XCTAssertEqual(z.url?.host, "shop.de")
        XCTAssertEqual(z.title, "ALUTEC 05200")
        XCTAssertNil(try Fixtures.part("part_box.frame").0.zukauf, "MVP-Teile ohne zukauf")
    }

    func testBOMZukaufLine() throws {
        guard case .bom(let m) = try decode(#"""
            {"type":"BOM","run":2,"lines":[
             {"pos":1,"art":"zukaufteil","stock_id":"alutec-05200","benennung":"ALUTEC Transportroller 05200",
              "material":"Polypropylen","masse_text":"610 × 410 × 128 mm","anzahl":1,"preis_je":24.99,"preis":24.99,
              "teile":["Rollwagen"],"hersteller":"ALUTEC","mpn":"05200","gtin":"4005187052008",
              "url":"https://www.beispiel-shop.de/p/alutec-05200","bild":"https://www.beispiel-shop.de/b.jpg",
              "preis_stand":"2026-10-21","preis_brutto":true,"cad_quelle":"keins","vereinfacht":true},
             {"pos":2,"art":"zukaufteil","benennung":"Blum Tandembox","anzahl":2,"teile":["A","B"],"mpn":"560H",
              "cad_quelle":"traceparts","url":"ftp://nein"},
             {"pos":3,"art":"rund","stock_id":"rund-10","benennung":"Rundstahl","anzahl":1,"teile":["C"]}]}
            """#) else { return XCTFail("kein BOM") }
        let lines = m.bom.lines
        let z = try XCTUnwrap(lines[0].zukauf)
        XCTAssertEqual(lines[0].art, "zukaufteil")
        XCTAssertFalse(lines[0].eigenteil)
        XCTAssertEqual(lines[0].stockID, "alutec-05200")
        XCTAssertEqual(z.hersteller, "ALUTEC")
        XCTAssertEqual(z.mpn, "05200")
        XCTAssertEqual(z.gtin, "4005187052008")
        XCTAssertEqual(z.url?.absoluteString, "https://www.beispiel-shop.de/p/alutec-05200")
        XCTAssertEqual(z.bild?.lastPathComponent, "b.jpg")
        XCTAssertEqual(z.preisStand, "2026-10-21")
        XCTAssertEqual(z.preisBrutto, true)
        XCTAssertTrue(z.vereinfacht)
        XCTAssertEqual(z.cadTitle, "vereinfacht (Ersatzkörper)")
        XCTAssertEqual(z.title, "ALUTEC · 05200")

        let tandem = try XCTUnwrap(lines[1].zukauf)
        XCTAssertFalse(lines[1].eigenteil, "Zukaufteil ohne stock_id ist kein Eigenteil")
        XCTAssertFalse(tandem.vereinfacht)
        XCTAssertNil(tandem.url, "nur http(s)")
        XCTAssertNil(tandem.preisBrutto)
        XCTAssertEqual(tandem.cadTitle, "Hersteller-CAD (TraceParts)")
        XCTAssertNil(lines[2].zukauf)
        XCTAssertEqual(ZukaufDate.display("2026-10-21"), "21.10.2026")
        XCTAssertEqual(ZukaufDate.display("2026-10"), "10/2026")
        XCTAssertNil(ZukaufDate.display(""))
    }

    func testOutgoingPhase3Messages() throws {
        func json(_ m: some OutgoingMessage) throws -> [String: Any] {
            let back = try FrameReader().feed(m.frame().encoded)
            return try XCTUnwrap(JSONSerialization.jsonObject(with: back[0].header) as? [String: Any])
        }
        var draft = ZukaufDraft(input: "https://www.beispiel-shop.de/p/alutec-05200")
        draft.hersteller = "ALUTEC"
        draft.mpn = "05200"
        draft.name = "ALUTEC Transportroller 05200"
        draft.id = draft.suggestedID()
        draft.masse = ["l": "610", "b": "410", "h": "128"]
        let neu = try json(ZukaufNewMessage(id: "a-1", eingabe: draft.eingabe, felder: draft.entry(), ebene: .projekt))
        XCTAssertEqual(neu["type"] as? String, "ZUKAUF_NEU")
        XCTAssertEqual(neu["id"] as? String, "a-1")
        XCTAssertEqual(neu["eingabe"] as? String, "https://www.beispiel-shop.de/p/alutec-05200")
        XCTAssertEqual(neu["ebene"] as? String, "projekt")
        let felder = try XCTUnwrap(neu["felder"] as? [String: Any])
        XCTAssertEqual(felder["id"] as? String, "alutec-05200")
        XCTAssertEqual(felder["art"] as? String, "zukaufteil")
        XCTAssertEqual(felder["status"] as? String, "frei")
        XCTAssertEqual((felder["masse"] as? [String: Any])?["l"] as? Double, 610)

        let date = Date(timeIntervalSince1970: 1_792_610_043)  // 2026-10-21 19:14:03 UTC
        let seen = try json(DownloadSeenMessage(pfad: "/tmp/dl/05200.step", groesse: 2_400_000, zeit: date))
        XCTAssertEqual(seen["type"] as? String, "DOWNLOAD_SEEN")
        XCTAssertNil(seen["id"], "DOWNLOAD_SEEN ist keine Anfrage")
        XCTAssertEqual(seen["pfad"] as? String, "/tmp/dl/05200.step")
        XCTAssertEqual(seen["groesse"] as? Int, 2_400_000)
        XCTAssertEqual(DownloadSeenMessage.isoString(date, timeZone: TimeZone(identifier: "Europe/Berlin")!),
                       "2026-10-21T21:14:03+02:00")
        XCTAssertNotNil(ISO8601DateFormatter().date(from: try XCTUnwrap(seen["zeit"] as? String)))

        let cad = try json(ZukaufCADMessage(id: "a-2", teil: "alutec-05200", pfad: "/tmp/dl/05200.step"))
        XCTAssertEqual(cad["type"] as? String, "ZUKAUF_CAD")
        XCTAssertEqual(cad["id"] as? String, "a-2")
        XCTAssertEqual(cad["teil"] as? String, "alutec-05200")
        XCTAssertEqual(cad["pfad"] as? String, "/tmp/dl/05200.step")
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

    func testWaitingDownloadOfferAndImport() throws {
        let c = try connectedController()
        let m = c.model
        XCTAssertNil(m.watchedDownloads)
        c.handle([try message(#"""
            {"type":"ZUKAUF_STATUS","id":"blum-560h","zustand":"wartet_auf_cad","text":"Bitte herunterladen",
             "cad_links":[{"titel":"Blum CAD","url":"https://www.blum.com/cad/560H"}],"erwartet":["step","stp"],
             "name":"Blum Tandembox 560H"}
            """#)])
        XCTAssertEqual(m.waitingForCAD.map(\.id), ["blum-560h"])
        XCTAssertEqual(m.zukaufStatus.first?.name, "Blum Tandembox 560H")
        XCTAssertEqual(m.zukaufStatus.first?.cadLinks.first?.titel, "Blum CAD")
        XCTAssertEqual(m.watchedDownloads, dir, "Beobachtung läuft nur im Temp-Ordner")
        XCTAssertTrue(m.log.contains { $0.text.contains("wartet auf CAD") })

        // Falsche Endung: keine Rückfrage
        try Data(repeating: 1, count: 200).write(to: dir.appendingPathComponent("anleitung.pdf"))
        // Passende Datei: DOWNLOAD_SEEN und Rückfrage
        let file = dir.appendingPathComponent("560H5000B.stp")
        try Data(repeating: 1, count: 3000).write(to: file)
        XCTAssertTrue(wait(5) { m.downloadOffer != nil }, "Rückfrage erwartet")
        let offer = try XCTUnwrap(m.downloadOffer)
        XCTAssertEqual(offer.fileName, "560H5000B.stp")
        XCTAssertEqual(offer.size, 3000)
        XCTAssertEqual(offer.candidates, ["blum-560h"])
        let seen = try XCTUnwrap(lastSent(c, "DOWNLOAD_SEEN"))
        XCTAssertEqual(seen["pfad"]?.stringValue, file.path)
        XCTAssertEqual(seen["groesse"]?.intValue, 3000)
        XCTAssertEqual(c.zukaufState.sent.filter { $0.type == "DOWNLOAD_SEEN" }.count, 1)

        // Ja: ZUKAUF_CAD, Rückfrage weg, Zustand zeigt die Übergabe
        c.acceptDownload(for: "blum-560h")
        XCTAssertNil(m.downloadOffer)
        let cad = try XCTUnwrap(lastSent(c, "ZUKAUF_CAD"))
        XCTAssertEqual(cad["teil"]?.stringValue, "blum-560h")
        XCTAssertEqual(cad["pfad"]?.stringValue, file.path)
        XCTAssertEqual(m.zukaufStatus(for: "blum-560h")?.uebergabe, "560H5000B.stp")
        let id = try XCTUnwrap(cad["id"]?.stringValue)
        c.handle([try message(#"{"type":"ACK","reply_to":"\#(id)","ok":true,"message":"wird importiert"}"#)])
        // Dieselbe Datei kommt nicht noch einmal
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        XCTAssertNil(m.downloadOffer)

        // Importiert: Beobachtung aus, Meldung verschwindet nach kurzer Zeit
        c.zukaufState.importedDisplay = 0.2
        c.handle([try message(#"{"type":"ZUKAUF_STATUS","id":"blum-560h","zustand":"importiert","text":"STEP geprüft"}"#)])
        XCTAssertEqual(m.zukaufStatus(for: "blum-560h")?.zustand, .importiert)
        XCTAssertNil(m.zukaufStatus(for: "blum-560h")?.uebergabe)
        XCTAssertEqual(m.zukaufStatus(for: "blum-560h")?.name, "Blum Tandembox 560H", "Name bleibt")
        XCTAssertNil(m.watchedDownloads)
        XCTAssertNil(c.zukaufState.watcher)
        XCTAssertTrue(wait(2) { m.zukaufStatus.isEmpty })
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
        func part(_ cad: String?) throws -> IncomingEvent {
            var frame = try Fixtures.frame("part_box.frame")
            guard case .object(var head) = try JSONDecoder().decode(JSONValue.self, from: frame.header) else {
                throw NSError(domain: "t", code: 1)
            }
            if let cad {
                head["zukauf"] = ["id": "alutec-05200", "hersteller": "ALUTEC", "mpn": "05200", "cad": .string(cad),
                                  "preis": 24.99, "url": "https://shop.de/p"]
            }
            frame.header = try JSONEncoder().encode(JSONValue.object(head))
            return KernelConnection.decode(frame)
        }
        c.handle([try part("vereinfacht")])
        let node = try XCTUnwrap(m.parts.first)
        XCTAssertEqual(node.zukauf?.id, "alutec-05200")
        XCTAssertEqual(node.zukauf?.isSimplified, true)
        XCTAssertEqual(c.scene.simplifiedParts, [node.id])
        let body = try XCTUnwrap(c.scene.bodies.first { c.scene.owner(ofBody: $0.id)?.part == node.id })
        XCTAssertLessThan(body.color.w, 0.5, "halbtransparent")
        XCTAssertGreaterThan(c.scene.renderBodies.count, c.scene.bodies.count + 1, "Kanten des Ersatzkörpers extra")

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
