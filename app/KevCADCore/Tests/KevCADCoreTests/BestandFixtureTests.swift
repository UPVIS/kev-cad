import Foundation
import XCTest

@testable import KevCADCore

/// Bestand gegen die Testdateien des Kernels (kernel/tools/make_bestand_fixtures.py, Abschnitt `bestand` in
/// fixtures.json): Kugelschieber mit Resten, Platten, Stückgut und Einkaufsliste.
final class BestandFixtureTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try XCTUnwrap(try Fixtures.expected()["bestand"])
    }

    func testBestandFrame() throws {
        guard case .bestand(let m) = try Fixtures.message("bestand.frame") else { return XCTFail("kein BESTAND") }
        let exp = try erwartet()["bestand"]
        let b = try XCTUnwrap(m.bestand)
        XCTAssertEqual(b.posten.map(\.id), exp?["posten"]?.stringList)
        let rohr = try XCTUnwrap(b.posten("rohr-alfer-12x1"))
        XCTAssertEqual(rohr.reste.compactMap(\.kennung), exp?["reste_rohr"]?.stringList)
        XCTAssertEqual(rohr.form, .stange)
        XCTAssertEqual(rohr.ganzeAnzahl, 2)
        XCTAssertEqual(rohr.mindestrestMM, 80)
        XCTAssertEqual(b.posten("platte-multiplex-birke-18")?.form, .platte)
        XCTAssertEqual(b.posten("schraube-iso7380-m6")?.form, .stueckgut)
        XCTAssertEqual(b.posten("mutter-din315-m4")?.stueckGesamt, 10)
        XCTAssertEqual(m.buchungen.map(\.id), exp?["buchungen"]?.stringList)
        XCTAssertEqual(m.buchungen.first?.text, exp?["zusammenfassung_erste"]?.stringValue)
        XCTAssertEqual(m.buchungen.first?.artTitel, "Korrektur")
        XCTAssertEqual(m.buchungen.last?.vonTitel, "Claude")
        XCTAssertEqual(m.buchungen.last?.aenderungen, 1)
        XCTAssertEqual(m.stand, exp?["stand"]?.stringValue)
        XCTAssertEqual(m.datei, "/Users/test/Documents/Kev CAD/Kugelschieber/bestand.json")
        XCTAssertNil(m.fehler)

        guard case .bestand(let leer) = try Fixtures.message("bestand_leer.frame") else { return XCTFail() }
        XCTAssertNil(leer.bestand)
        XCTAssertNil(leer.datei)
        XCTAssertTrue(leer.buchungen.isEmpty)
    }

    func testBOMFrame() throws {
        guard case .bom(let m) = try Fixtures.message("bom_bestand.frame") else { return XCTFail("kein BOM") }
        let exp = try XCTUnwrap(try erwartet()["bom"])
        let z = try XCTUnwrap(m.bestand)
        XCTAssertEqual(m.bom.run, exp["run"]?.intValue)
        XCTAssertEqual(z.fehlt, exp["fehlt"]?.boolValue)
        XCTAssertEqual(z.bestandStand, exp["bestand_stand"]?.stringValue)

        // Stange: Quellen, neue Reste, Herkunft, Mindestrest
        let rohr = try XCTUnwrap(z.zuschnitt("rohr-alfer-12x1"))
        let er = try XCTUnwrap(exp["rohr"])
        XCTAssertFalse(rohr.istPlatte)
        let quellen = try XCTUnwrap(er["quellen"]?.arrayValue)
        XCTAssertEqual(rohr.quellen.count, quellen.count)
        for (q, e) in zip(rohr.quellen, quellen) {
            XCTAssertEqual(q.art.rawValue, e["art"]?.stringValue)
            XCTAssertEqual(q.kennung, e["kennung"]?.stringValue)
            XCTAssertEqual(q.laenge, e["laenge"]?.doubleValue)
            XCTAssertEqual(q.stuecke, e["stuecke"]?.doubles)
            XCTAssertEqual(q.restNeu, e["rest_neu"]?.doubleValue)
            XCTAssertEqual(q.verschnitt, e["verschnitt"]?.boolValue)
            XCTAssertTrue(q.verschnittAngegeben)
        }
        XCTAssertEqual(rohr.neueReste, er["neue_reste"]?.doubles)
        XCTAssertEqual(rohr.ausBestandReste, er["aus_bestand"]?["reste"]?.intValue)
        XCTAssertEqual(rohr.ausBestandGanze, er["aus_bestand"]?["ganze"]?.intValue)
        XCTAssertEqual(rohr.kaufen, er["kaufen"]?.intValue)
        XCTAssertEqual(rohr.mindestrest, 80)
        XCTAssertEqual(m.bom.cuts.first { $0.stockID == "rohr-alfer-12x1" }?.stangen, try XCTUnwrap(er["stangen"]?.arrayValue).map { $0.doubles ?? [] })
        XCTAssertEqual(rohr.herkunftText, "aus Bestand: 3 Reste, 2 Stangen · kaufen: 1 Stange")
        // R-0003 (180) mit einem Stück 175: Rest 2 mm ist Verschnitt; Stück so lang wie die Stange: kein Schnitt
        let r3 = try XCTUnwrap(rohr.quellen.first { $0.kennung == "R-0003" })
        XCTAssertEqual(r3.segmente(saegeschnitt: 3, mindestrest: 80).map(\.art), [.stueck, .schnitt, .verschnitt])
        let voll = try XCTUnwrap(rohr.quellen.first { $0.art == .bestand })
        XCTAssertEqual(voll.segmente(saegeschnitt: 3, mindestrest: 80).map(\.art), [.stueck])
        // R-0002 ganz aufgebraucht (rest_neu 0), auch kein Verschnitt
        let r2 = try XCTUnwrap(rohr.quellen.first { $0.kennung == "R-0002" })
        XCTAssertEqual(r2.segmente(saegeschnitt: 3, mindestrest: 80).last?.art, .schnitt)

        // Platte
        let platte = try XCTUnwrap(z.zuschnitt("platte-multiplex-birke-18"))
        let ep = try XCTUnwrap(exp["platte"])
        XCTAssertTrue(platte.istPlatte)
        XCTAssertEqual(platte.platteB, ep["platte"]?["b"]?.doubleValue)
        XCTAssertEqual(platte.platteH, ep["platte"]?["h"]?.doubleValue)
        XCTAssertEqual(platte.quellen.count, ep["quellen"]?.intValue)
        XCTAssertEqual(platte.quellen.reduce(0) { $0 + $1.flaechen.count }, ep["stuecke"]?.intValue)
        let erste = try XCTUnwrap(platte.quellen.first)
        XCTAssertEqual(erste.art.rawValue, ep["erste_quelle"]?["art"]?.stringValue)
        XCTAssertEqual(erste.kennung, ep["erste_quelle"]?["kennung"]?.stringValue)
        XCTAssertEqual(erste.b, ep["erste_quelle"]?["b"]?.doubleValue)
        XCTAssertEqual(erste.h, ep["erste_quelle"]?["h"]?.doubleValue)
        let es = try XCTUnwrap(ep["erstes_stueck"])
        XCTAssertEqual(erste.flaechen.first, ZuschnittFlaeche(
            b: es["b"]?.doubleValue ?? 0, h: es["h"]?.doubleValue ?? 0, x: es["x"]?.doubleValue ?? 0,
            y: es["y"]?.doubleValue ?? 0, gedreht: es["gedreht"]?.boolValue ?? false))
        XCTAssertEqual(platte.neueResteFlaechen.map { [$0.b, $0.h] }, try XCTUnwrap(ep["neue_reste"]?.arrayValue).map {
            [$0["b"]?.doubleValue ?? 0, $0["h"]?.doubleValue ?? 0]
        })
        XCTAssertEqual(platte.kaufen, ep["kaufen"]?.intValue)
        XCTAssertEqual(platte.mindestrest, 100)
        XCTAssertTrue(platte.zuGross.isEmpty)
        // Lage der Restrechtecke der ganzen Platte (für die Zeichnung)
        XCTAssertEqual(platte.quellen[1].resteNeu.first, ZuschnittFlaeche(b: 1697, h: 1250, x: 803, y: 0))

        // Einkaufsliste
        let liste = try XCTUnwrap(exp["einkaufsliste"]?.arrayValue)
        XCTAssertEqual(z.einkaufsliste.count, liste.count)
        for (p, e) in zip(z.einkaufsliste, liste) {
            XCTAssertEqual(p.id, e["id"]?.stringValue)
            XCTAssertEqual(p.menge, e["menge"]?.doubleValue)
            XCTAssertEqual(p.einheit, e["einheit"]?.stringValue)
            XCTAssertEqual(p.preisJe, e["preis_je"]?.doubleValue)
            XCTAssertEqual(p.preis, e["preis"]?.doubleValue)
            XCTAssertEqual(p.link?.absoluteString, e["link"]?.stringValue)
        }
        XCTAssertEqual(z.einkaufsliste[0].linkTitel, "ALFER", "link_text")
        XCTAssertEqual(z.einkaufsliste[0].stand, "2026-10")
        XCTAssertEqual(z.summe, exp["einkauf_summe"]?.doubleValue)
        XCTAssertEqual(z.einkaufHinweis, "Richtpreise, Stand 2026-10")

        // Stückgut
        let sg = try XCTUnwrap(exp["stueckgut"]?.arrayValue)
        XCTAssertEqual(z.stueckgut.count, sg.count)
        for (s, e) in zip(z.stueckgut, sg) {
            XCTAssertEqual(s.stockID, e["stock_id"]?.stringValue)
            XCTAssertEqual(s.laenge, e["laenge"]?.doubleValue)
            XCTAssertEqual(s.anzahl, e["anzahl"]?.intValue)
            XCTAssertEqual(s.ausBestand, e["aus_bestand"]?.intValue)
            XCTAssertEqual(s.kaufen, e["kaufen"]?.intValue)
        }
        XCTAssertTrue(z.hatBuchbares)
    }

    func testGebautVorschauKugelschieber() throws {
        guard case .bestand(let b) = try Fixtures.message("bestand.frame"),
              case .bom(let m) = try Fixtures.message("bom_bestand.frame")
        else { return XCTFail() }
        let v = GebautVorschau.berechnen(zuschnitt: try XCTUnwrap(m.bestand), bestand: b.bestand, lines: m.bom.lines)
        XCTAssertEqual(v.weg.map(\.text), [
            "Rest R-0001 · 430 mm", "Rest R-0002 · 610 mm", "Rest R-0003 · 180 mm", "2 ganze Stangen · 1.000 mm",
            "Rest P-0001 · 600 × 400 mm", "1 ganze Platte · 2.500 × 1.250 mm", "12 Stück · 20 mm", "10 Stück",
        ])
        XCTAssertEqual(v.weg[6].hinweis, "16 gebraucht, 4 kaufen")
        XCTAssertEqual(v.neu.map(\.text), ["Rest 244 mm", "Rest 1.697 × 1.250 mm", "Rest 800 × 264 mm", "Rest 247 × 380 mm"])
        XCTAssertEqual(v.kaufen.map(\.text), ["1 Stange · 1.000 mm"])
        XCTAssertEqual(v.verschnitt.map(\.text), ["2 mm"])
        // Der Kernel meldet nach GEBAUT_REQ: 3 Reste weg, 2 ganze Stangen weg, 1 Rest neu (ack_gebaut.frame)
        guard case .ack(let ack) = try Fixtures.message("ack_gebaut.frame") else { return XCTFail() }
        XCTAssertEqual(ack.buchung, "B-0003")
        XCTAssertTrue(ack.message?.contains("R-0004 244 mm") ?? false)
    }

    /// Die Anfragen der App müssen den Testdateien des Kernels entsprechen (gleiche Felder und Werte).
    func testAnfragenWieTestdateien() throws {
        func kopf(_ name: String) throws -> [String: JSONValue] {
            try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame(name).header).objectValue)
        }
        func meins<M: OutgoingMessage>(_ m: M, seq: Int) throws -> [String: JSONValue] {
            var m = m
            m.seq = seq
            return try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()).objectValue)
        }
        var k = try kopf("bestand_req.frame")
        XCTAssertEqual(try meins(BestandRequestMessage(id: "a-20"), seq: k["seq"]?.intValue ?? 0), k)

        k = try kopf("bestand_save.frame")
        XCTAssertEqual(try meins(
            BestandSaveMessage(id: "a-22", postenID: "rohr-alfer-12x1", posten: k["posten"], grund: "+1 Stange, Rest 250 mm"),
            seq: k["seq"]?.intValue ?? 0), k)

        k = try kopf("bestand_save_einstellungen.frame")
        XCTAssertEqual(try meins(
            BestandSaveMessage(id: "a-23", einstellungen: BestandEinstellungen(mindestrestMM: 80, saegeblattMM: 2.5), grund: ""),
            seq: k["seq"]?.intValue ?? 0), k)

        k = try kopf("gebaut_req.frame")
        XCTAssertEqual(try meins(GebautRequestMessage(id: "a-21", run: 5), seq: k["seq"]?.intValue ?? 0), k)

        k = try kopf("buchung_rueckgaengig.frame")
        XCTAssertEqual(try meins(BuchungRueckgaengigMessage(id: "a-24", buchung: "B-0003"), seq: k["seq"]?.intValue ?? 0), k)

        // Ein neuer Rest aus der App geht ohne Kennung hinaus, wie in bestand_save.frame
        let neu = BestandBearbeitung.restHinzu(.object([:]), laenge: 250)
        XCTAssertNil(neu["reste"]?.arrayValue?.first?["kennung"])
        XCTAssertEqual(neu["reste"]?.arrayValue?.first?["laenge"]?.doubleValue, 250)
        XCTAssertEqual(neu["reste"]?.arrayValue?.first?["ort"], .null)
    }

    @MainActor
    func testControllerMitTestdateien() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("bestand.frame"))])
        let m = c.model
        XCTAssertEqual(m.bestandZustand.datei, "/Users/test/Documents/Kev CAD/Kugelschieber/bestand.json")
        XCTAssertEqual(m.bestandZustand.bestand?.posten.count, 4)
        c.handle([.message(try Fixtures.message("bom_bestand.frame"))])
        XCTAssertEqual(m.bestandZustand.zuschnitt?.zuschnitte.count, 2)
        // Kaputte Datei: Fehler im Zustand, kein Bestand
        c.handle([.message(try KernelMessage.decode(Frame(header: Data(
            #"{"type":"BESTAND","bestand":null,"buchungen":[],"datei":"/p/bestand.json","fehler":"Zeile 3: kein JSON"}"#.utf8))))])
        XCTAssertNil(m.bestandZustand.bestand)
        XCTAssertEqual(m.bestandZustand.fehler, "Zeile 3: kein JSON")
        XCTAssertTrue(m.log.contains { $0.level == .warning && $0.text.contains("kein JSON") })
    }
}
