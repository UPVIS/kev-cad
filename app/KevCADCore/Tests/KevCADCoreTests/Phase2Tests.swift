import Foundation
import XCTest

@testable import KevCADCore

/// Phase 2: Dekodieren von BOM, CATALOG und PART_UPSERT.stock, Anfragen der App, Controller mit Stückliste und Katalog.
final class Phase2ProtocolTests: XCTestCase {
    func testPartStockFixture() throws {
        let (h, g) = try Fixtures.part("part_stock.frame")
        XCTAssertEqual(h.name, "Gestell/Bein vorn links")
        XCTAssertEqual(g.triangleCount, 32)
        let s = try XCTUnwrap(h.stock)
        XCTAssertEqual(s.id, "vierkantrohr-en10219-40x40x3")
        XCTAssertEqual(s.name, "Vierkantrohr 40 × 40 × 3")
        XCTAssertEqual(s.laenge, 882)
        XCTAssertEqual(s.gehrung, [0, 45])
        XCTAssertEqual(s.material, "stahl-s235")
        XCTAssertEqual(s.kg, 2.98)
        XCTAssertEqual(s.preis, 7.06)
        // Gegen fixtures.json
        let exp = try XCTUnwrap(Fixtures.expected()["parts"]?["part_stock.frame"]?["stock"])
        XCTAssertEqual(StockInfo(json: exp), s)
        // Ohne stock (MVP-Teile) bleibt das Feld leer
        XCTAssertNil(try Fixtures.part("part_box.frame").0.stock)
    }

    func testBOMFixture() throws {
        guard case .bom(let msg) = try Fixtures.message("bom.frame") else { return XCTFail("kein BOM") }
        XCTAssertNil(msg.replyTo)
        let bom = msg.bom
        XCTAssertEqual(bom.run, 3)
        XCTAssertEqual(bom.lines.map(\.pos), [1, 2, 3, 4])
        let rohr = bom.lines[0]
        XCTAssertEqual(rohr.art, "vierkantrohr")
        XCTAssertEqual(rohr.stockID, "vierkantrohr-en10219-40x40x3")
        XCTAssertEqual(rohr.benennung, "Vierkantrohr 40 × 40 × 3")
        XCTAssertEqual(rohr.norm, "DIN EN 10219")
        XCTAssertEqual(rohr.material, "Stahl S235")
        XCTAssertEqual(rohr.laenge, 882)
        XCTAssertEqual(rohr.gehrung, [0, 45])
        XCTAssertEqual(rohr.masseText, "882 mm")
        XCTAssertEqual(rohr.anzahl, 4)
        XCTAssertEqual(rohr.kgJe, 2.98)
        XCTAssertEqual(rohr.kg, 11.92)
        XCTAssertEqual(rohr.preisJe, 7.06)
        XCTAssertEqual(rohr.preis, 28.24)
        XCTAssertEqual(rohr.teile.count, 4)
        XCTAssertFalse(rohr.eigenteil)

        let platte = bom.lines[1]
        XCTAssertNil(platte.laenge)
        XCTAssertNil(platte.norm)
        XCTAssertEqual(platte.masseText, "800 × 600 mm")
        XCTAssertEqual(bom.lines[2].masseText, "M8 × 60")
        XCTAssertEqual(bom.lines[2].teile.last, "Schrauben/M8x60 8")

        let halter = bom.lines[3]
        XCTAssertTrue(halter.eigenteil)
        XCTAssertNil(halter.stockID)
        XCTAssertNil(halter.preis)
        XCTAssertEqual(halter.teile, ["Halter"])

        XCTAssertEqual(bom.cuts.count, 1)
        let cut = bom.cuts[0]
        XCTAssertEqual(cut.stockID, "vierkantrohr-en10219-40x40x3")
        XCTAssertEqual(cut.stangenlaenge, 6000)
        XCTAssertEqual(cut.saegeschnitt, 3)
        XCTAssertEqual(cut.stangen, [[882, 882, 882, 882, 800, 800]])
        XCTAssertEqual(cut.verschnittProzent, 13.6)
        XCTAssertEqual(cut.rest(ofBar: 0), 6000 - 5128 - 18)

        XCTAssertEqual(bom.totals.kg, 18.16)
        XCTAssertEqual(bom.totals.preis, 52.4)
        XCTAssertEqual(bom.totals.positionen, 4)
        XCTAssertEqual(bom.totals.teile, 14)
        XCTAssertEqual(bom.totals.preisHinweis, "Richtpreise, Stand 2026-10")
        XCTAssertEqual(bom.warnings, ["Halter: kein Lagerteil, Masse aus Volumen × Dichte"])
        XCTAssertEqual(bom.line(containing: "Deckel")?.pos, 2)
    }

    func testCatalogFixture() throws {
        guard case .catalog(let msg) = try Fixtures.message("catalog.frame") else { return XCTFail("kein CATALOG") }
        XCTAssertEqual(msg.replyTo, "a-9")
        XCTAssertEqual(KernelMessage.catalog(msg).replyTo, "a-9")
        let cat = msg.catalog
        XCTAssertEqual(cat.arten, ["rohr", "vierkantrohr", "platte"])
        XCTAssertEqual(cat.materials.count, 1)
        let stahl = cat.materials[0]
        XCTAssertEqual(stahl.id, "stahl-s235")
        XCTAssertEqual(stahl.gruppe, "Stahl")
        XCTAssertEqual(stahl.dichte, 7.85)
        XCTAssertEqual(stahl.farbe, "#8A9099")
        XCTAssertEqual(stahl.preisJeKg, 2.4)
        XCTAssertEqual(stahl.ebene, .mitgeliefert)
        // Roh-JSON ohne das Transportfeld ebene, alle anderen Felder erhalten
        XCTAssertNil(stahl.entry["ebene"])
        XCTAssertEqual(stahl.entry["preis_quelle"]?.stringValue, "Richtwert")

        XCTAssertEqual(cat.items.count, 2)
        let vkr = try XCTUnwrap(cat.item("vierkantrohr-en10219-40x40x3"))
        XCTAssertEqual(vkr.art, "vierkantrohr")
        XCTAssertEqual(vkr.masse, ["a": 40, "s": 3])
        XCTAssertEqual(vkr.kgJeM, 3.41)
        XCTAssertEqual(vkr.preisText, "8,00 €/m")
        XCTAssertEqual(vkr.tags, ["quadrat"])
        XCTAssertEqual(vkr.ebene, .mitgeliefert)
        XCTAssertEqual(vkr.entry["stangenlaenge"]?.doubleValue, 6000)
        let eigen = try XCTUnwrap(cat.item("rohr-edelstahl-33.7x2"))
        XCTAssertEqual(eigen.ebene, .eigen)
        XCTAssertNil(eigen.kgJeM)
        XCTAssertEqual(eigen.preisText, "14,50 €/m")
        XCTAssertEqual(eigen.masse["d"], 33.7)
        XCTAssertEqual(cat.material("stahl-s235")?.name, "Stahl S235")
        XCTAssertTrue(CatalogLevel.eigen.isEditable)
        XCTAssertFalse(CatalogLevel.mitgeliefert.isEditable)
    }

    /// Fehlende und falsch getypte Felder dürfen nichts kaputt machen.
    func testTolerantDecoding() throws {
        let bom = Frame(header: Data(#"""
            {"type":"BOM","seq":1,"reply_to":"a-2","lines":[
              {"benennung":"Rohr","laenge":"viel","anzahl":2,"teile":["A","B"],"gehrung":30},
              {"pos":7,"stock_id":"x","teile":["C"],"gehrung":[15],"kg":1.5,"preis":2},
              "Unsinn"],
             "cuts":[{"stock_id":"x","stangen":[[1000,1000],[500]],"stangenlaenge":3000}],
             "neu":{"etwas":1}}
            """#.utf8))
        guard case .bom(let m) = try KernelMessage.decode(bom) else { return XCTFail() }
        XCTAssertEqual(m.replyTo, "a-2")
        XCTAssertEqual(m.bom.run, 0)
        XCTAssertEqual(m.bom.lines.count, 2)
        XCTAssertEqual(m.bom.lines[0].pos, 1)
        XCTAssertNil(m.bom.lines[0].laenge)
        XCTAssertEqual(m.bom.lines[0].gehrung, [30, 30])
        XCTAssertTrue(m.bom.lines[0].eigenteil, "ohne stock_id gilt die Zeile als Eigenteil")
        XCTAssertEqual(m.bom.lines[1].pos, 7)
        XCTAssertEqual(m.bom.lines[1].anzahl, 1)
        XCTAssertEqual(m.bom.lines[1].gehrung, [15, 15])
        XCTAssertFalse(m.bom.lines[1].eigenteil)
        XCTAssertEqual(m.bom.cuts[0].saegeschnitt, 3)
        XCTAssertEqual(m.bom.cuts[0].verschnittProzent, 100 * (6000 - 2500) / 6000, accuracy: 1e-9)
        // Summen aus den Zeilen, wenn totals fehlt
        XCTAssertEqual(m.bom.totals.kg, 1.5)
        XCTAssertEqual(m.bom.totals.preis, 2)
        XCTAssertEqual(m.bom.totals.positionen, 2)
        XCTAssertEqual(m.bom.totals.teile, 3)
        XCTAssertNil(m.bom.totals.preisHinweis)

        let cat = Frame(header: Data(#"""
            {"type":"CATALOG","items":[{"id":"a","art":"schraube","masse":{"typ":"SocketHeadCapScrew","groesse":"M8-1.25"},
              "preis":{"je_stueck":0.32},"ebene":"unbekannt"},{"name":"ohne id"}],"materials":[{"id":"m","dichte":"x"}]}
            """#.utf8))
        guard case .catalog(let c) = try KernelMessage.decode(cat) else { return XCTFail() }
        XCTAssertNil(c.replyTo)
        XCTAssertEqual(c.catalog.items.map(\.id), ["a"])
        XCTAssertEqual(c.catalog.items[0].masse, [:], "Texte stehen nicht in masse, aber im Roh-JSON")
        XCTAssertEqual(c.catalog.items[0].entry["masse"]?["groesse"]?.stringValue, "M8-1.25")
        XCTAssertEqual(c.catalog.items[0].preisText, "0,32 €/Stück")
        XCTAssertEqual(c.catalog.items[0].ebene, .mitgeliefert)
        XCTAssertEqual(c.catalog.arten, ["schraube"], "arten aus den Einträgen, wenn das Feld fehlt")
        XCTAssertEqual(c.catalog.materials[0].dichte, 0)

        // stock mit falschen Typen und null
        let part = #"{"type":"PART_UPSERT","run":1,"name":"P","counts":{"vert":0,"tri":0,"face":0,"edge":0,"epts":0,"vtx":0},"#
        for (stock, expected) in [
            (#""stock":null"#, nil as String?), (#""stock":"rohr""#, nil), (#""stock":{"laenge":5}"#, nil),
            (#""stock":{"id":"r","laenge":"lang","gehrung":"schräg"}"#, "r"),
        ] {
            let frame = Frame(header: Data((part + stock + "}").utf8), payload: Data(repeating: 0, count: 4))
            guard case .partUpsert(let h, _) = try KernelMessage.decode(frame) else { return XCTFail(stock) }
            XCTAssertEqual(h.stock?.id, expected, stock)
            if expected != nil {
                XCTAssertNil(h.stock?.laenge)
                XCTAssertEqual(h.stock?.gehrung, [0, 0])
                XCTAssertEqual(h.stock?.name, "r")
            }
        }
    }

    func testOutgoingPhase2Messages() throws {
        func json(_ m: some OutgoingMessage) throws -> [String: Any] {
            let back = try FrameReader().feed(m.frame().encoded)
            return try XCTUnwrap(JSONSerialization.jsonObject(with: back[0].header) as? [String: Any])
        }
        let bom = try json(BOMRequestMessage(id: "a-1"))
        XCTAssertEqual(bom["type"] as? String, "BOM_REQ")
        XCTAssertEqual(bom["id"] as? String, "a-1")

        let req = try json(CatalogRequestMessage(id: "a-2", query: nil, art: "rohr"))
        XCTAssertEqual(req["type"] as? String, "CATALOG_REQ")
        XCTAssertTrue(req["query"] is NSNull)
        XCTAssertEqual(req["art"] as? String, "rohr")

        let entry: JSONValue = ["id": "rohr-x", "art": "rohr", "masse": ["d": 33.7, "s": 2]]
        let save = try json(CatalogSaveMessage(id: "a-3", kind: "teil", entry: entry, ebene: .eigen))
        XCTAssertEqual(save["type"] as? String, "CATALOG_SAVE")
        XCTAssertEqual(save["kind"] as? String, "teil")
        XCTAssertEqual(save["ebene"] as? String, "eigen")
        XCTAssertEqual(((save["entry"] as? [String: Any])?["masse"] as? [String: Any])?["d"] as? Double, 33.7)

        let del = try json(CatalogDeleteMessage(id: "a-4", kind: "material", entryID: "eiche", ebene: .projekt))
        XCTAssertEqual(del["type"] as? String, "CATALOG_DELETE")
        XCTAssertEqual(del["entry_id"] as? String, "eiche")
        XCTAssertEqual(del["ebene"] as? String, "projekt")
        XCTAssertEqual(del["kind"] as? String, "material")
    }
}

@MainActor
final class Phase2ControllerTests: XCTestCase {
    /// Controller mit „Verbindung“ und HELLO; Anfragen gehen ins Leere, Antworten kommen über handle(_:).
    private func connectedController() throws -> AppController {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        return c
    }

    private func message(_ json: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(json.utf8))))
    }

    func testCatalogRequestSaveDelete() throws {
        let c = try connectedController()
        let m = c.model
        c.requestCatalog(query: nil, art: nil)  // a-1
        XCTAssertEqual(m.catalogActivity, .loading)
        var cat = try Fixtures.frame("catalog.frame")
        var head = try JSONDecoder().decode(JSONValue.self, from: cat.header)
        if case .object(var o) = head { o["reply_to"] = "a-1"; head = .object(o) }
        cat.header = try JSONEncoder().encode(head)
        c.handle([.message(try KernelMessage.decode(cat))])
        XCTAssertEqual(m.catalog?.items.count, 2)
        XCTAssertEqual(m.catalogActivity, .idle)

        // Speichern: ACK ok → saved, danach wird neu geladen (a-3)
        var draft = CatalogItemDraft(art: "rohr")
        draft.masse = ["d": "33,7", "s": "2"]
        draft.id = "rohr-edelstahl-33.7x2"
        draft.name = "Edelstahlrohr 33,7 × 2"
        draft.material = "edelstahl-1.4301"
        c.saveCatalogEntry(kind: "teil", json: draft.json(), ebene: .eigen)  // a-2
        XCTAssertEqual(m.catalogActivity, .saving)
        c.handle([try message(#"{"type":"ACK","reply_to":"a-2","ok":true,"message":"eigene.json"}"#)])
        XCTAssertEqual(m.catalogActivity, .saved(id: "rohr-edelstahl-33.7x2", message: "eigene.json"))
        c.handle([try message(#"{"type":"CATALOG","reply_to":"a-3","items":[],"materials":[]}"#)])
        XCTAssertEqual(m.catalog?.items.count, 0)
        XCTAssertEqual(m.catalogActivity, .saved(id: "rohr-edelstahl-33.7x2", message: "eigene.json"))

        // Abgelehnt: ERROR mit Meldung
        c.saveCatalogEntry(kind: "teil", json: draft.json(), ebene: .eigen)  // a-4
        c.handle([try message(#"{"type":"ERROR","reply_to":"a-4","message":"masse.d fehlt"}"#)])
        XCTAssertEqual(m.catalogActivity, .failed("masse.d fehlt"))
        c.saveCatalogEntry(kind: "teil", json: draft.json(), ebene: .mitgeliefert)
        if case .failed = m.catalogActivity {} else { XCTFail("mitgeliefert darf nicht gespeichert werden") }
        c.saveCatalogEntry(kind: "teil", json: Data("[1]".utf8), ebene: .eigen)
        if case .failed = m.catalogActivity {} else { XCTFail("kein Objekt") }

        // Löschen: ACK ok → deleted
        c.deleteCatalogEntry(kind: "teil", id: "rohr-edelstahl-33.7x2", ebene: .eigen)  // a-5
        c.handle([try message(#"{"type":"ACK","reply_to":"a-5","ok":true}"#)])
        XCTAssertEqual(m.catalogActivity, .deleted(id: "rohr-edelstahl-33.7x2"))
        c.deleteCatalogEntry(kind: "teil", id: "x", ebene: .eigen)  // a-7 (a-6 war das Nachladen)
        c.handle([try message(#"{"type":"ACK","reply_to":"a-7","ok":false,"message":"nicht gefunden"}"#)])
        XCTAssertEqual(m.catalogActivity, .failed("nicht gefunden"))
    }

    func testCatalogWithoutKernelAndTimeout() throws {
        let off = AppController(model: AppModel())
        off.requestCatalog(query: "rohr", art: nil)
        if case .failed(let text) = off.model.catalogActivity {
            XCTAssertTrue(text.contains("nicht verbunden"), text)
        } else {
            XCTFail("ohne Kernel: \(off.model.catalogActivity)")
        }

        let saved = AppController.catalogTimeout
        AppController.catalogTimeout = 0.2
        defer { AppController.catalogTimeout = saved }
        let c = try connectedController()
        c.requestCatalog(query: nil, art: nil)
        RunLoop.main.run(until: Date().addingTimeInterval(0.5))
        if case .failed(let text) = c.model.catalogActivity {
            XCTAssertTrue(text.contains("Ältere Kernel"), text)
        } else {
            XCTFail("Zeitüberschreitung: \(c.model.catalogActivity)")
        }
        XCTAssertNil(c.model.catalog)
        // Stille BOM-Anfrage: Zeitüberschreitung nur als Info
        c.requestBOM(quiet: true)
        RunLoop.main.run(until: Date().addingTimeInterval(0.5))
        XCTAssertTrue(c.model.log.contains { $0.level == .info && $0.text.contains("keine Stückliste") })
    }

    func testBOMReplyShowLineAndExport() throws {
        let c = try connectedController()
        let m = c.model
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events[1...6]))  // PROJECT, Lauf mit Grundplatte und Halter/Bolzen
        c.handle([events[13]])  // Gestell/Bein vorn links

        c.requestBOM()  // a-1
        c.handle([try message(#"""
            {"type":"BOM","reply_to":"a-1","run":3,"lines":[
             {"pos":1,"stock_id":"vkr","benennung":"Vierkantrohr","laenge":882,"anzahl":2,
              "teile":["Gestell/Bein vorn links","Gestell/Bein fehlt"]},
             {"pos":2,"benennung":"Halter","eigenteil":true,"anzahl":1,"teile":["Halter"]},
             {"pos":3,"benennung":"Nichts","anzahl":1,"teile":["Gibt es nicht"]}],
             "totals":{"kg":3,"preis":7,"positionen":3,"teile":4}}
            """#)])
        let bom = try XCTUnwrap(m.bom)
        XCTAssertEqual(bom.lines.count, 3)
        XCTAssertTrue(m.log.contains { $0.text.contains("Stückliste zu Lauf 3") })

        // Zeile zeigen: Teile auswählen, ausgeblendete einblenden; Baugruppe „Halter“ steht für Halter/Bolzen
        c.setVisibility(["Gestell/Bein vorn links"], visible: false)
        c.showBOMLine(bom.lines[0])
        XCTAssertEqual(m.selection.map(\.ref), ["Gestell/Bein vorn links"])
        XCTAssertEqual(m.parts.first { $0.id == "Gestell/Bein vorn links" }?.visible, true)
        c.showBOMLine(bom.lines[1])
        XCTAssertEqual(m.selection.map(\.ref), ["Halter/Bolzen"])
        c.showBOMLine(bom.lines[2])
        XCTAssertEqual(m.selection.map(\.ref), ["Halter/Bolzen"], "unbekannte Teile ändern die Auswahl nicht")
        XCTAssertTrue(m.log.contains { $0.level == .warning && $0.text.contains("Pos. 3") })

        // Nach der Stückliste lädt die App den Katalog still nach (a-2), um Vorschläge von Claude zu finden
        c.handle([try message(#"""

            {"type":"CATALOG","reply_to":"a-2","items":[{"id":"winkel-alu","art":"winkel","name":"Alu-Winkel",
             "masse":{"a":30,"b":30,"s":3},"material":"aluminium-6060","status":"vorgeschlagen","ebene":"eigen"}],
             "materials":[{"id":"pla-grau","name":"PLA grau","gruppe":"Kunststoff","dichte":1.24,"farbe":"#888888",
             "druckbar":true,"status":"vorgeschlagen","ebene":"eigen"}]}
            """#)])
        XCTAssertEqual(m.catalog?.suggestionCount, 2)
        XCTAssertEqual(m.catalog?.materials.first?.druckbar, true)
        XCTAssertEqual(m.catalogActivity, .idle, "stilles Nachladen zeigt keinen Ladezustand")
        // Freigeben: derselbe Eintrag mit status frei, ohne ebene
        let approved = try JSONDecoder().decode(
            JSONValue.self, from: Catalog.approvedJSON(try XCTUnwrap(m.catalog?.items.first?.json)))
        XCTAssertEqual(approved["status"]?.stringValue, "frei")
        XCTAssertEqual(approved["id"]?.stringValue, "winkel-alu")
        XCTAssertNil(approved["ebene"])

        // CSV-Export: die Datei wird im Finder gezeigt (hier abgefangen)
        var revealed: [URL] = []
        c.revealFiles = { revealed = $0 }
        c.export(formats: ["bom_csv"])  // a-3
        c.handle([try message(
            #"{"type":"EXPORT_RES","reply_to":"a-3","files":["/tmp/p/output/Gestell.step","/tmp/p/output/Gestell-stueckliste.csv"]}"#)])
        XCTAssertEqual(revealed.map(\.path), ["/tmp/p/output/Gestell-stueckliste.csv"])
        revealed = []
        c.export(formats: ["step"])  // a-4
        c.handle([try message(#"{"type":"EXPORT_RES","reply_to":"a-4","files":["/tmp/p/output/Gestell.step"]}"#)])
        XCTAssertTrue(revealed.isEmpty, "andere Exporte öffnen keinen Finder")

        // Projektwechsel verwirft die Stückliste
        c.handle([try message(#"{"type":"PROJECT","path":"/tmp/anderes","name":"anderes"}"#)])
        XCTAssertNil(m.bom)
        // Neustart nach Update ist absichtlich ohne Wirkung (macht das Update-Skript)
        c.relaunchForUpdate()
        XCTAssertNil(m.updateAvailable)
    }

    /// Inventar-Regel: PART_UPSERT `inventar`, RUN_END `inventar_verstoesse`, SETTINGS `inventar_regel`.
    func testInventoryRule() throws {
        let c = try connectedController()
        let m = c.model
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle([events[1], events[2]])  // PROJECT, RUN_START
        XCTAssertTrue(m.inventarRegel, "Standard: an")

        // Grundplatte mit inventar "fehlt"
        var frame = try Fixtures.frame("part_box.frame")
        guard case .object(var head) = try JSONDecoder().decode(JSONValue.self, from: frame.header) else { return XCTFail() }
        head["inventar"] = "fehlt"
        frame.header = try JSONEncoder().encode(JSONValue.object(head))
        c.handle([KernelConnection.decode(frame), events[5]])
        XCTAssertEqual(m.parts.filter(\.inventarFehlt).map(\.id), ["Grundplatte"])
        XCTAssertEqual(c.scene.inventoryWarnings, ["Grundplatte"])
        let tinted = try XCTUnwrap(c.scene.bodies.first { c.scene.owner(ofBody: $0.id)?.part == "Grundplatte" })
        XCTAssertGreaterThan(tinted.color.x, tinted.color.z, "rot eingefärbt")

        // RUN_END nennt zusätzlich Halter/Bolzen
        c.handle([try message(#"""
            {"type":"RUN_END","run":1,"duration_ms":5,"parts":2,"triangles":0,"warnings":[],
             "inventar_verstoesse":["Grundplatte","Halter/Bolzen"]}
            """#)])
        XCTAssertEqual(m.inventarVerstoesse, ["Grundplatte", "Halter/Bolzen"])
        XCTAssertEqual(Set(m.parts.filter(\.inventarFehlt).map(\.id)), ["Grundplatte", "Halter/Bolzen"])
        XCTAssertTrue(m.log.contains { $0.text.contains("Nicht aus dem Inventar") })

        // Umschalten: wird je Projekt gemerkt
        let defaults = UserDefaults.standard
        let saved = defaults.dictionary(forKey: AppController.inventarDefaultsKey)
        defer { defaults.set(saved, forKey: AppController.inventarDefaultsKey) }
        c.setInventarRegel(false)
        XCTAssertFalse(m.inventarRegel)
        let project = try XCTUnwrap(m.project?.path)
        XCTAssertEqual(AppController.storedInventarRegel(project), false)
        XCTAssertTrue(m.log.contains { $0.text.contains("Inventar-Regel aus") })

        // Neues Projekt ohne Angabe: Standard an, Verstöße weg; mit Angabe des Kernels gilt diese
        c.handle([try message(#"{"type":"PROJECT","path":"/tmp/kevcad-inventar-test","name":"neu"}"#)])
        XCTAssertTrue(m.inventarRegel)
        XCTAssertEqual(m.inventarVerstoesse, [])
        XCTAssertTrue(c.scene.inventoryWarnings.isEmpty)
        c.handle([try message(#"{"type":"PROJECT","path":"/tmp/kevcad-inventar-2","name":"x","inventar_regel":false}"#)])
        XCTAssertFalse(m.inventarRegel)
        let tolerant = try KernelMessage.decode(
            Frame(header: Data(#"{"type":"PROJECT","path":"/p","inventar_regel":"ja"}"#.utf8)))
        guard case .project(let p) = tolerant else { return XCTFail() }
        XCTAssertNil(p.inventarRegel)
    }

    func testSettingsCarryInventoryRule() throws {
        var s = SettingsMessage(autoRun: true, slowMs: 0, inventarRegel: false)
        s.seq = 2
        let head = try XCTUnwrap(JSONSerialization.jsonObject(with: s.encodedHeader()) as? [String: Any])
        XCTAssertEqual(head["inventar_regel"] as? Bool, false)
        let old = try XCTUnwrap(
            JSONSerialization.jsonObject(with: SettingsMessage(autoRun: true, slowMs: 0).encodedHeader()) as? [String: Any])
        XCTAssertNil(old["inventar_regel"])
    }
}
