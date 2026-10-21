import Foundation
import XCTest

@testable import KevCADCore

/// Beispielnachrichten laut BESTAND.md (bis die Testdateien von S-K da sind).
enum BestandBeispiel {
    static let bestand = #"""
        {"type":"BESTAND","seq":9,"stand":"2026-10-21T22:14:03",
         "bestand":{"version":1,"einstellungen":{"mindestrest_mm":100,"saegeblatt_mm":3},
          "posten":{
           "rohr-alfer-12x1":{"ganze":{"anzahl":2,"laenge":1000},
             "reste":[{"kennung":"R-0007","laenge":430,"ort":"Regal 2","seit":"2026-10-21"},
                      {"kennung":"R-0008","laenge":610,"ort":null,"seit":"2026-10-21"}],
             "mindestrest_mm":80,"zukunft":"bleibt"},
           "platte-multiplex-birke-18":{"ganze":{"anzahl":1,"b":2500,"h":1250},
             "reste":[{"kennung":"P-0003","b":600,"h":400,"ort":null,"seit":"2026-10-20"}]},
           "schraube-iso7380-m6":{"stueck":[{"laenge":16,"anzahl":40},{"laenge":20,"anzahl":12}]},
           "mutter-din315-m4":{"stueck":[{"anzahl":30}]}}},
         "buchungen":[
          {"id":"B-0003","zeit":"2026-10-21T22:14:03","art":"gebaut","projekt":"Kugelschieber","aenderungen":[{},{}],
           "von":"kevin","grund":"Gebaut","zusammenfassung":"2 Posten weg, 1 Rest neu (R-0012, 144 mm)",
           "rueckgaengig_durch":null},
          {"id":"B-0002","zeit":"2026-10-21T21:00:00","art":"eintrag","projekt":"Kugelschieber","aenderungen":[{}],
           "von":"agent","grund":"Kevin: 2 Stangen","zusammenfassung":null,"rueckgaengig_durch":"B-0004"}]}
        """#

    static let bom = #"""
        {"type":"BOM","run":7,"lines":[
          {"pos":1,"art":"rohr","stock_id":"rohr-alfer-12x1","benennung":"ALFER-Rundrohr 12 × 1","laenge":425,
           "anzahl":3,"teile":["A","B","C"]},
          {"pos":2,"art":"rohr","stock_id":"rohr-alfer-12x1","benennung":"ALFER-Rundrohr 12 × 1","laenge":175,
           "anzahl":1,"teile":["D"]},
          {"pos":3,"art":"rohr","stock_id":"rohr-alfer-12x1","benennung":"ALFER-Rundrohr 12 × 1","laenge":300,
           "anzahl":1,"teile":["E"]},
          {"pos":4,"art":"platte","stock_id":"platte-multiplex-birke-18","benennung":"Multiplex Birke 18",
           "masse_text":"800 × 600 mm","anzahl":1,"teile":["Boden"]},
          {"pos":5,"art":"mutter","stock_id":"mutter-din315-m4","benennung":"Flügelmutter DIN 315 M4",
           "masse_text":"M4","anzahl":34,"teile":["M1"]},
          {"pos":6,"art":"schraube","stock_id":"schraube-iso7380-m6","benennung":"Linsenkopfschraube M6",
           "masse_text":"M6 × 16","anzahl":8,"teile":["S1"]}],
         "cuts":[
          {"stock_id":"rohr-alfer-12x1","benennung":"ALFER-Rundrohr 12 × 1","stangenlaenge":1000,"saegeschnitt":3,
           "stangen":[[425,175],[425,425],[300]],"verschnitt_prozent":12.0,
           "quellen":[
            {"art":"rest","kennung":"R-0008","laenge":610,"stuecke":[425,175],"rest_neu":4,"verschnitt":true},
            {"art":"bestand","kennung":null,"laenge":1000,"stuecke":[425,425],"rest_neu":144},
            {"art":"kaufen","kennung":null,"laenge":1000,"stuecke":[300],"rest_neu":697}],
           "neue_reste":[144,697],"aus_bestand":{"reste":1,"ganze":1},"kaufen":1},
          {"stock_id":"platte-multiplex-birke-18","art":"platte","benennung":"Multiplex Birke 18",
           "platte":{"b":2500,"h":1250},"saegeschnitt":3,
           "quellen":[
            {"art":"bestand","kennung":null,"b":2500,"h":1250,
             "stuecke":[{"b":800,"h":600,"x":0,"y":0,"gedreht":false}],
             "rest_neu":[{"b":1697,"h":1250,"x":803,"y":0},{"b":800,"h":647,"x":0,"y":603}]}],
           "neue_reste":[{"b":1697,"h":1250,"x":803,"y":0},{"b":800,"h":647,"x":0,"y":603}],
           "aus_bestand":{"reste":0,"ganze":1},"kaufen":0},
          {"stock_id":"vierkant-alt","benennung":"Ohne Quellen","stangenlaenge":6000,"saegeschnitt":3,
           "stangen":[[500]],"verschnitt_prozent":91.6}],
         "totals":{"kg":1.2,"preis":20.5,"positionen":6,"teile":48},
         "einkaufsliste":[
          {"id":"rohr-alfer-12x1","benennung":"ALFER-Rundrohr 12 × 1","menge":1,"einheit":"Stange 1000 mm",
           "preis_je":3.9,"preis":3.9,"link":"https://www.example.com/alfer","hinweis":null,"preis_stand":"2026-10"},
          {"id":"mutter-din315-m4","benennung":"Flügelmutter DIN 315 M4","menge":4,"einheit":"Stück",
           "preis_je":0.12,"preis":0.48,"link":{"url":"https://www.example.com/m4","name":"Schraubenhandel"},
           "hinweis":"Bestand im Projekt: 30, gebraucht: 34"},
          {"id":"ohne-preis","benennung":"Ohne Preis; mit \"Zeichen\"","menge":2,"einheit":"Stück","link":"ftp://nein"}],
         "bestand_stand":"2026-10-21T22:14:03","fehlt":true}
        """#

    static func frame(_ json: String) -> Frame { Frame(header: Data(json.utf8)) }

    static func bestandMessage() throws -> BestandMessage {
        guard case .bestand(let m) = try KernelMessage.decode(frame(bestand)) else { throw XCTSkip("kein BESTAND") }
        return m
    }

    static func bomMessage() throws -> BOMMessage {
        guard case .bom(let m) = try KernelMessage.decode(frame(bom)) else { throw XCTSkip("kein BOM") }
        return m
    }
}

final class BestandProtocolTests: XCTestCase {
    func testDecodeBestand() throws {
        let m = try BestandBeispiel.bestandMessage()
        XCTAssertNil(m.replyTo)
        XCTAssertEqual(m.stand, "2026-10-21T22:14:03")
        let b = try XCTUnwrap(m.bestand)
        XCTAssertEqual(b.einstellungen, BestandEinstellungen(mindestrestMM: 100, saegeblattMM: 3))
        XCTAssertEqual(b.posten.map(\.id), [
            "mutter-din315-m4", "platte-multiplex-birke-18", "rohr-alfer-12x1", "schraube-iso7380-m6",
        ])
        let rohr = try XCTUnwrap(b.posten("rohr-alfer-12x1"))
        XCTAssertEqual(rohr.form, .stange)
        XCTAssertEqual(rohr.ganzeAnzahl, 2)
        XCTAssertEqual(rohr.ganzeLaenge, 1000)
        XCTAssertEqual(rohr.reste.map(\.kennung), ["R-0007", "R-0008"])
        XCTAssertEqual(rohr.reste[0].ort, "Regal 2")
        XCTAssertNil(rohr.reste[1].ort)
        XCTAssertEqual(rohr.mindestrestMM, 80)
        XCTAssertEqual(b.mindestrest("rohr-alfer-12x1"), 80)
        XCTAssertEqual(b.mindestrest("platte-multiplex-birke-18"), 100)
        XCTAssertEqual(rohr.zusammenfassung, "2 Stangen à 1.000 mm · 2 Reste")
        XCTAssertEqual(rohr.resteSortiert.map(\.kennung), ["R-0008", "R-0007"])

        let platte = try XCTUnwrap(b.posten("platte-multiplex-birke-18"))
        XCTAssertEqual(platte.form, .platte)
        XCTAssertEqual(platte.ganzeMasseText, "2.500 × 1.250 mm")
        XCTAssertEqual(platte.reste.first?.masseText, "600 × 400 mm")
        XCTAssertEqual(platte.zusammenfassung, "1 Platte à 2.500 × 1.250 mm · 1 Rest")

        let schraube = try XCTUnwrap(b.posten("schraube-iso7380-m6"))
        XCTAssertEqual(schraube.form, .stueckgut)
        XCTAssertEqual(schraube.stueckGesamt, 52)
        XCTAssertEqual(schraube.zusammenfassung, "52 Stück (16 mm: 40, 20 mm: 12)")
        XCTAssertEqual(b.posten("mutter-din315-m4")?.zusammenfassung, "30 Stück")

        XCTAssertEqual(b.naechsteKennung(.stange), "R-0009")
        XCTAssertEqual(b.naechsteKennung(.platte), "P-0004")
        XCTAssertEqual(b.naechsteKennungen(.stange, anzahl: 3), ["R-0009", "R-0010", "R-0011"])
        XCTAssertEqual(Bestand.leer.naechsteKennung(.stange), "R-0001")

        XCTAssertEqual(m.buchungen.map(\.id), ["B-0003", "B-0002"])
        let g = m.buchungen[0]
        XCTAssertEqual(g.art, "gebaut")
        XCTAssertEqual(g.artTitel, "Gebaut")
        XCTAssertEqual(g.aenderungen, 2)
        XCTAssertEqual(g.text, "2 Posten weg, 1 Rest neu (R-0012, 144 mm)")
        XCTAssertFalse(g.schonRueckgaengig)
        XCTAssertNotNil(g.zeit)
        XCTAssertEqual(m.buchungen[1].vonTitel, "Claude")
        XCTAssertEqual(m.buchungen[1].text, "Kevin: 2 Stangen", "ohne Zusammenfassung gilt der Grund")
        XCTAssertTrue(m.buchungen[1].schonRueckgaengig)
    }

    func testDecodeBestandTolerant() throws {
        // ohne Projekt: bestand null
        guard case .bestand(let leer) = try KernelMessage.decode(BestandBeispiel.frame(
            #"{"type":"BESTAND","reply_to":"a-4","bestand":null,"buchungen":[{"ohne":"id"}]}"#))
        else { return XCTFail() }
        XCTAssertEqual(leer.replyTo, "a-4")
        XCTAssertNil(leer.bestand)
        XCTAssertTrue(leer.buchungen.isEmpty)
        // Kaputte Posten werden übersprungen, fehlende Einstellungen haben Vorgaben
        let b = Bestand(json: try JSONDecoder().decode(JSONValue.self, from: Data(
            #"{"posten":{"a":5,"b":{"ganze":{"anzahl":"3"}},"c":{}}}"#.utf8)))
        XCTAssertEqual(b.posten.map(\.id), ["b", "c"])
        XCTAssertEqual(b.einstellungen, .standard)
        XCTAssertEqual(b.posten("b")?.ganzeAnzahl, 3)
        XCTAssertTrue(b.posten("c")?.leer ?? false)
        // Typname und reply_to
        XCTAssertEqual(KernelMessage.bestand(leer).typeName, "BESTAND")
        XCTAssertEqual(KernelMessage.bestand(leer).replyTo, "a-4")
    }

    func testDecodeBOMBestand() throws {
        let m = try BestandBeispiel.bomMessage()
        XCTAssertEqual(m.bom.cuts.count, 3, "bisheriger Zuschnitt bleibt lesbar")
        let z = try XCTUnwrap(m.bestand)
        XCTAssertEqual(z.run, 7)
        XCTAssertEqual(z.zuschnitte.map(\.stockID), ["rohr-alfer-12x1", "platte-multiplex-birke-18"])
        XCTAssertTrue(z.fehlt)
        XCTAssertEqual(z.bestandStand, "2026-10-21T22:14:03")

        let rohr = try XCTUnwrap(z.zuschnitt("rohr-alfer-12x1"))
        XCTAssertFalse(rohr.istPlatte)
        XCTAssertEqual(rohr.quellen.map(\.art), [.rest, .bestand, .kaufen])
        XCTAssertEqual(rohr.quellen[0].kennung, "R-0008")
        XCTAssertEqual(rohr.quellen[0].stuecke, [425, 175])
        XCTAssertEqual(rohr.quellen[0].restNeu, 4)
        XCTAssertTrue(rohr.quellen[0].verschnitt)
        XCTAssertEqual(rohr.neueReste, [144, 697])
        XCTAssertEqual(rohr.ausBestandReste, 1)
        XCTAssertEqual(rohr.ausBestandGanze, 1)
        XCTAssertEqual(rohr.kaufen, 1)
        XCTAssertEqual(rohr.herkunftText, "aus Bestand: 1 Rest, 1 Stange · kaufen: 1 Stange")
        XCTAssertEqual(rohr.neueResteText, "144 mm, 697 mm")
        XCTAssertEqual(rohr.quellen[0].titel, "R-0008 · 610 mm")

        let platte = try XCTUnwrap(z.zuschnitt("platte-multiplex-birke-18"))
        XCTAssertTrue(platte.istPlatte)
        XCTAssertEqual(platte.platteB, 2500)
        XCTAssertEqual(platte.platteH, 1250)
        XCTAssertEqual(platte.quellen[0].flaechen, [ZuschnittFlaeche(b: 800, h: 600)])
        XCTAssertEqual(platte.quellen[0].resteNeu.count, 2)
        XCTAssertEqual(platte.neueResteFlaechen.map(\.masseText), ["1.697 × 1.250 mm", "800 × 647 mm"])
        XCTAssertEqual(platte.quellen[0].titel, "Bestand · 2.500 × 1.250 mm")

        XCTAssertEqual(z.einkaufsliste.map(\.id), ["rohr-alfer-12x1", "mutter-din315-m4", "ohne-preis"])
        let e0 = z.einkaufsliste[0]
        XCTAssertEqual(e0.link?.absoluteString, "https://www.example.com/alfer")
        XCTAssertEqual(e0.linkTitel, "example.com")
        XCTAssertEqual(e0.stand, "2026-10")
        let e1 = z.einkaufsliste[1]
        XCTAssertEqual(e1.linkTitel, "Schraubenhandel")
        XCTAssertEqual(e1.mengeText, "4")
        XCTAssertNil(z.einkaufsliste[2].link, "nur http(s)")
        XCTAssertNil(z.einkaufsliste[2].preis)
        XCTAssertEqual(z.summe ?? 0, 4.38, accuracy: 1e-9)
        XCTAssertEqual(z.ohnePreis, 1)
        XCTAssertTrue(z.hatBuchbares)
    }

    func testBOMOhneBestand() throws {
        // Älterer Kernel: keine Bestandsfelder, dann gibt es keinen Bestandsteil
        guard case .bom(let m) = try Fixtures.message("bom.frame") else { return XCTFail() }
        XCTAssertNil(m.bestand)
        // Ein Zuschnitt ohne Quellen wird zum Kaufen-Zuschnitt
        let z = BestandZuschnitt(cut: m.bom.cuts[0])
        XCTAssertEqual(z.quellen.map(\.art), [.kaufen])
        XCTAssertEqual(z.kaufen, 1)
        XCTAssertEqual(z.quellen[0].laenge, 6000)
        // Ohne neue_reste: Reste der Quellen, die kein Verschnitt sind
        let ohne = try XCTUnwrap(BestandZuschnitt(json: try JSONDecoder().decode(JSONValue.self, from: Data(#"""
            {"stock_id":"x","quellen":[{"art":"rest","laenge":500,"stuecke":[200],"rest_neu":297},
             {"art":"bestand","laenge":1000,"stuecke":[990],"rest_neu":7,"verschnitt":true}]}
            """#.utf8))))
        XCTAssertEqual(ohne.neueReste, [297])
        XCTAssertEqual(ohne.ausBestandReste, 1)
        XCTAssertEqual(ohne.ausBestandGanze, 1)
        XCTAssertEqual(ohne.kaufen, 0)
    }

    func testAckMitBuchung() throws {
        guard case .ack(let a) = try KernelMessage.decode(BestandBeispiel.frame(
            #"{"type":"ACK","reply_to":"a-9","ok":true,"buchung":"B-0005","message":"2 Posten weg"}"#))
        else { return XCTFail() }
        XCTAssertEqual(a.buchung, "B-0005")
        XCTAssertEqual(a.message, "2 Posten weg")
    }

    func testOutgoingMessages() throws {
        func head<M: OutgoingMessage>(_ m: M) throws -> [String: Any] {
            var m = m
            m.seq = 4
            return try XCTUnwrap(JSONSerialization.jsonObject(with: m.encodedHeader()) as? [String: Any])
        }
        let req = try head(BestandRequestMessage(id: "a-1"))
        XCTAssertEqual(req["type"] as? String, "BESTAND_REQ")
        XCTAssertEqual(req["id"] as? String, "a-1")
        XCTAssertEqual(req["seq"] as? Int, 4)

        let posten: JSONValue = ["ganze": ["anzahl": 3, "laenge": 1000]]
        let save = try head(BestandSaveMessage(id: "a-2", postenID: "rohr", posten: posten, grund: "+1 Stange"))
        XCTAssertEqual(save["type"] as? String, "BESTAND_SAVE")
        XCTAssertEqual(save["posten_id"] as? String, "rohr")
        XCTAssertEqual((save["posten"] as? [String: Any])?["ganze"] as? [String: Double], ["anzahl": 3, "laenge": 1000])
        XCTAssertEqual(save["grund"] as? String, "+1 Stange")
        XCTAssertNil(save["einstellungen"])

        let weg = try head(BestandSaveMessage(id: "a-3", postenID: "rohr", posten: nil, grund: "entfernt"))
        XCTAssertTrue(weg["posten"] is NSNull, "null entfernt den Posten")

        let ein = try head(BestandSaveMessage(
            id: "a-4", einstellungen: BestandEinstellungen(mindestrestMM: 120, saegeblattMM: 4), grund: "x"))
        XCTAssertEqual(ein["einstellungen"] as? [String: Double], ["mindestrest_mm": 120, "saegeblatt_mm": 4])
        XCTAssertNil(ein["posten_id"])
        XCTAssertNil(ein["posten"])

        let gebaut = try head(GebautRequestMessage(id: "a-5", run: 7))
        XCTAssertEqual(gebaut["type"] as? String, "GEBAUT_REQ")
        XCTAssertEqual(gebaut["run"] as? Int, 7)

        let rueck = try head(BuchungRueckgaengigMessage(id: "a-6", buchung: "B-0003"))
        XCTAssertEqual(rueck["type"] as? String, "BUCHUNG_RUECKGAENGIG")
        XCTAssertEqual(rueck["buchung"] as? String, "B-0003")
    }
}

final class BestandModelTests: XCTestCase {
    private func rohr() throws -> BestandPosten {
        try XCTUnwrap(try BestandBeispiel.bestandMessage().bestand?.posten("rohr-alfer-12x1"))
    }

    func testBearbeitenGanzeUndReste() throws {
        let p = try rohr()
        // +1 behält Länge und unbekannte Felder
        let plus = BestandBearbeitung.ganze(p.json, delta: 1, laenge: 6000)
        XCTAssertEqual(plus["ganze"]?["anzahl"]?.intValue, 3)
        XCTAssertEqual(plus["ganze"]?["laenge"]?.doubleValue, 1000, "vorhandene Länge bleibt")
        XCTAssertEqual(plus["zukunft"]?.stringValue, "bleibt")
        XCTAssertEqual(BestandBearbeitung.ganze(p.json, delta: -5)["ganze"]?["anzahl"]?.intValue, 0, "nie unter 0")
        // neuer Posten bekommt die Vorgabe
        let neu = BestandBearbeitung.ganze(BestandBearbeitung.neuerPosten(form: .stange), delta: 1, laenge: 6000)
        XCTAssertEqual(BestandPosten(id: "n", json: neu).ganzeLaenge, 6000)
        XCTAssertEqual(BestandPosten(id: "n", json: neu).form, .stange)
        let platte = BestandBearbeitung.neuerPosten(form: .platte, b: 2500, h: 1250)
        XCTAssertEqual(BestandPosten(id: "p", json: platte).form, .platte)
        XCTAssertEqual(BestandPosten(id: "s", json: BestandBearbeitung.neuerPosten(form: .stueckgut)).form, .stueckgut)
        XCTAssertEqual(BestandPosten(id: "s", json: [:], formHint: .platte).form, .platte)

        // Rest hinzufügen, ändern, entfernen
        var j = BestandBearbeitung.restHinzu(p.json, kennung: "R-0009", laenge: 180, ort: "  ", seit: "2026-10-22")
        var q = BestandPosten(id: p.id, json: j)
        XCTAssertEqual(q.reste.map(\.kennung), ["R-0007", "R-0008", "R-0009"])
        XCTAssertEqual(q.reste[2].laenge, 180)
        XCTAssertNil(q.reste[2].ort, "leerer Ort wird null")
        XCTAssertEqual(q.reste[2].seit, "2026-10-22")
        j = BestandBearbeitung.restAendern(j, rest: "R-0009", laenge: 175, ort: "Regal 1")
        q = BestandPosten(id: p.id, json: j)
        XCTAssertEqual(q.reste[2].laenge, 175)
        XCTAssertEqual(q.reste[2].ort, "Regal 1")
        j = BestandBearbeitung.restEntfernen(j, rest: "R-0007")
        XCTAssertEqual(BestandPosten(id: p.id, json: j).reste.map(\.kennung), ["R-0008", "R-0009"])

        // Plattenrest
        let pj = BestandBearbeitung.restHinzu(platte, kennung: "P-0004", b: 600, h: 400)
        XCTAssertEqual(BestandPosten(id: "p", json: pj).reste.first?.masseText, "600 × 400 mm")

        // Mindestrest
        XCTAssertNil(BestandBearbeitung.mindestrest(p.json, nil)["mindestrest_mm"])
        XCTAssertEqual(BestandBearbeitung.mindestrest(p.json, 150)["mindestrest_mm"]?.doubleValue, 150)
    }

    func testBearbeitenStueck() throws {
        let b = try XCTUnwrap(try BestandBeispiel.bestandMessage().bestand)
        let s = try XCTUnwrap(b.posten("schraube-iso7380-m6"))
        var j = BestandBearbeitung.stueck(s.json, laenge: 16, delta: -4)
        XCTAssertEqual(BestandPosten(id: s.id, json: j).stueck.map(\.anzahl), [36, 12])
        j = BestandBearbeitung.stueck(j, laenge: 25, delta: 10)
        XCTAssertEqual(BestandPosten(id: s.id, json: j).stueck.map(\.laenge), [16, 20, 25], "Längen aufsteigend")
        j = BestandBearbeitung.setzeStueck(j, laenge: 20, anzahl: 0)
        XCTAssertEqual(BestandPosten(id: s.id, json: j).stueck.map(\.laenge), [16, 25], "0 Stück entfernt die Länge")
        let m = try XCTUnwrap(b.posten("mutter-din315-m4"))
        XCTAssertEqual(BestandPosten(id: m.id, json: BestandBearbeitung.stueck(m.json, laenge: nil, delta: 5)).stueckGesamt, 35)
    }

    func testErfassung() throws {
        let b = try XCTUnwrap(try BestandBeispiel.bestandMessage().bestand)
        let p = try rohr()
        // Kevins Beispiel: 2 ganze Stangen, Reste 430, 610 und 180 mm
        let laengen = try XCTUnwrap(BestandText.laengen("430, 610 und 180"))
        XCTAssertEqual(laengen, [430, 610, 180])
        var e = BestandErfassung(form: .stange, ganze: 2, laenge: 1000, resteLaengen: laengen, ort: "Regal 2")
        XCTAssertFalse(e.leer)
        let j = e.posten(vorher: p.json, bestand: b)
        let q = BestandPosten(id: p.id, json: j)
        XCTAssertEqual(q.ganzeAnzahl, 4)
        // Kennungen der neuen Reste vergibt der Kernel
        XCTAssertEqual(q.reste.map(\.kennung), ["R-0007", "R-0008", nil, nil, nil])
        XCTAssertEqual(q.reste.map(\.id), ["R-0007", "R-0008", "#2", "#3", "#4"])
        XCTAssertEqual(q.reste.last?.ort, "Regal 2")
        XCTAssertEqual(e.grund(name: "ALFER-Rohr"), "Erfasst ALFER-Rohr: 2 Stangen à 1.000 mm, 3 Reste (430, 610, 180 mm)")
        // Neuer Posten ohne Bestand
        let neu = BestandPosten(id: "x", json: e.posten(vorher: nil, bestand: nil))
        XCTAssertEqual(neu.ganzeAnzahl, 2)
        XCTAssertEqual(neu.ganzeLaenge, 1000)
        XCTAssertNil(neu.reste.first?.kennung)
        // Ohne Kernel vergibt die App sie selbst (fortlaufend ab der höchsten)
        e.kennungenVergeben = true
        XCTAssertEqual(BestandPosten(id: p.id, json: e.posten(vorher: p.json, bestand: b)).reste.compactMap(\.kennung),
                       ["R-0007", "R-0008", "R-0009", "R-0010", "R-0011"])
        XCTAssertEqual(BestandPosten(id: "x", json: e.posten(vorher: nil, bestand: nil)).reste.first?.kennung, "R-0001")
        // Platten und Stückgut
        let r = try XCTUnwrap(BestandText.rechtecke("600 × 400, 300 x 200"))
        e = BestandErfassung(form: .platte, ganze: 1, b: 2500, h: 1250, resteFlaechen: r.map { ZuschnittFlaeche(b: $0.b, h: $0.h) })
        let pl = BestandPosten(id: "p", json: e.posten(vorher: nil, bestand: b))
        XCTAssertEqual(pl.reste.count, 2)
        XCTAssertEqual(pl.reste.first?.masseText, "600 × 400 mm")
        XCTAssertEqual(pl.ganzeMasseText, "2.500 × 1.250 mm")
        XCTAssertEqual(e.grund(name: "Birke"), "Erfasst Birke: 1 Platte à 2.500 × 1.250 mm, 2 Reste (600 × 400 mm, 300 × 200 mm)")
        e = BestandErfassung(form: .stueckgut, stueck: 20, stueckLaenge: 16)
        XCTAssertEqual(BestandPosten(id: "s", json: e.posten(vorher: nil, bestand: nil)).stueck, [BestandStueck(laenge: 16, anzahl: 20)])
        XCTAssertTrue(BestandErfassung(form: .stange).leer)
    }

    func testEingabenLesen() {
        XCTAssertEqual(BestandText.laengen("430 610 180 mm"), [430, 610, 180])
        XCTAssertEqual(BestandText.laengen("430,610"), [430, 610])
        XCTAssertEqual(BestandText.laengen("12,5"), [12.5])
        XCTAssertEqual(BestandText.laengen("1250; 300"), [1250, 300])
        XCTAssertEqual(BestandText.datum("2026-10-21T20:14:03Z"), BestandText.datum("2026-10-21T22:14:03+02:00"))
        XCTAssertNil(BestandText.laengen("430, abc"))
        XCTAssertNil(BestandText.laengen(""))
        XCTAssertNil(BestandText.laengen("-5"))
        XCTAssertEqual(BestandText.rechtecke("600,5 × 400")?.first?.b, 600.5)
        XCTAssertEqual(BestandText.rechtecke("600x400\n300*200\n")?.count, 2)
        XCTAssertNil(BestandText.rechtecke("600"))
        XCTAssertEqual(BestandText.anzeige("2026-10-21T22:14:03"), "21.10.2026, 22:14")
        XCTAssertEqual(BestandText.anzeige("2026-10-21"), "21.10.2026")
        XCTAssertEqual(BestandText.anzeige("unbekannt"), "unbekannt")
        XCTAssertEqual(BestandForm(art: "rohr"), .stange)
        XCTAssertEqual(BestandForm(art: "platte"), .platte)
        XCTAssertEqual(BestandForm(art: "schraube"), .stueckgut)
    }

    func testKatalogVorgaben() throws {
        let item = CatalogItem(
            id: "rohr", art: "rohr", name: "Rohr", material: "stahl", ebene: .mitgeliefert,
            json: Data(#"{"id":"rohr","stangenlaenge":6000}"#.utf8))
        XCTAssertEqual(item.stangenlaenge, 6000)
        XCTAssertEqual(item.bestandForm, .stange)
        let platte = CatalogItem(
            id: "p", art: "platte", name: "P", material: "holz", ebene: .eigen,
            json: Data(#"{"id":"p","platte":[2500,1250]}"#.utf8))
        XCTAssertEqual(platte.plattenformat?.b, 2500)
        XCTAssertEqual(platte.plattenformat?.h, 1250)
        XCTAssertEqual(platte.bestandForm, .platte)
    }
}

final class BestandAnsichtTests: XCTestCase {
    func testSegmenteUndMassstab() throws {
        let z = try XCTUnwrap(try BestandBeispiel.bomMessage().bestand?.zuschnitt("rohr-alfer-12x1"))
        // Rest R-0008: 425 | Schnitt | 175 | Schnitt | Verschnitt 4
        let seg = z.quellen[0].segmente(saegeschnitt: 3, mindestrest: 80)
        XCTAssertEqual(seg.map(\.art), [.stueck, .schnitt, .stueck, .schnitt, .verschnitt])
        XCTAssertEqual(seg.map(\.start), [0, 425, 428, 603, 606])
        XCTAssertEqual(seg.last?.laenge, 4)
        // Stange aus dem Bestand: neuer Rest 144
        let seg2 = z.quellen[1].segmente(saegeschnitt: 3, mindestrest: 80)
        XCTAssertEqual(seg2.last?.art, .restNeu)
        XCTAssertEqual(seg2.last?.laenge, 144)
        XCTAssertEqual(seg2.last?.farbe, .restNeu)
        // Ohne Angabe des Kernels entscheidet der Mindestrest
        let q = ZuschnittQuelle(index: 0, art: .bestand, laenge: 1000, stuecke: [900])
        XCTAssertEqual(q.restLaenge(saegeschnitt: 3), 97)
        XCTAssertEqual(q.segmente(saegeschnitt: 3, mindestrest: 100).last?.art, .verschnitt)
        XCTAssertEqual(q.segmente(saegeschnitt: 3, mindestrest: 80).last?.art, .restNeu)
        // Ganz aufgebraucht: kein Restsegment
        XCTAssertEqual(ZuschnittQuelle(index: 0, art: .rest, laenge: 403, stuecke: [400]).segmente(saegeschnitt: 3, mindestrest: 100)
            .map(\.art), [.stueck, .schnitt])

        // Maßstab: alle Leisten im selben Maßstab, die längste füllt die Breite
        let skala = ZuschnittMassstab.skala(breite: 500, laengen: z.quellen.compactMap(\.laenge))
        XCTAssertEqual(skala, 0.5)
        XCTAssertEqual(610 * skala, 305, "der Rest ist maßstäblich kürzer als die Stange")
        XCTAssertEqual(ZuschnittMassstab.skala(breite: 500, laengen: []), 0)
        XCTAssertEqual(ZuschnittMassstab.skala2D(breite: 260, hoehe: 130, platten: [(2500, 1250), (600, 400)]), 0.104, accuracy: 1e-9)
        XCTAssertEqual(ZuschnittMassstab.skala2D(breite: 260, hoehe: 50, platten: [(2500, 1250)]), 0.04, accuracy: 1e-9)
    }

    func testFarben() {
        // Jede Quelle hat ihre eigene Farbe, Verschnitt ist grau
        let farben = ZuschnittQuelleArt.allCases.map { $0.farbe.rgb }
        for i in farben.indices {
            for j in farben.indices where i < j {
                XCTAssertFalse(farben[i] == farben[j], "Quellen \(i) und \(j) gleich gefärbt")
            }
        }
        let grau = ZuschnittFarbe.verschnitt.rgb
        XCTAssertEqual(grau.r, grau.g, accuracy: 0.05)
        XCTAssertEqual(grau.g, grau.b, accuracy: 0.05)
        XCTAssertEqual(ZuschnittQuelleArt.rest.farbe, .rest)
        XCTAssertEqual(ZuschnittQuelleArt.kaufen.titel, "kaufen")
        XCTAssertGreaterThan(ZuschnittFarbe.kaufen.rgb.r, ZuschnittFarbe.kaufen.rgb.b, "kaufen ist orange")
        XCTAssertGreaterThan(ZuschnittFarbe.bestand.rgb.b, ZuschnittFarbe.bestand.rgb.r, "Bestand ist blau")
    }

    func testPlattenLayout() {
        // Ohne Lage vom Kernel: zeilenweise auf der Platte verteilt
        let q = ZuschnittQuelle(
            index: 0, art: .bestand, b: 1000, h: 1000,
            flaechen: [ZuschnittFlaeche(b: 600, h: 300), ZuschnittFlaeche(b: 500, h: 400), ZuschnittFlaeche(b: 300, h: 200)])
        let l = q.flaechenLayout(saegeschnitt: 3)
        XCTAssertEqual(l.map(\.x), [0, 0, 603], "höchste zuerst, 600 passt nicht mehr daneben")
        XCTAssertEqual(l.map(\.y), [0, 403, 403])
        // Mit Lage bleibt sie
        let fest = ZuschnittQuelle(index: 0, art: .rest, b: 600, h: 400, flaechen: [ZuschnittFlaeche(b: 500, h: 300, x: 0, y: 97)])
        XCTAssertEqual(fest.flaechenLayout(), fest.flaechen)
    }

    func testGebautVorschau() throws {
        let b = try XCTUnwrap(try BestandBeispiel.bestandMessage().bestand)
        let bom = try BestandBeispiel.bomMessage()
        let v = GebautVorschau.berechnen(
            zuschnitt: try XCTUnwrap(bom.bestand), bestand: b, lines: bom.bom.lines,
            name: { $0 == "rohr-alfer-12x1" ? "ALFER-Rohr" : nil })
        XCTAssertEqual(v.weg.map(\.text), [
            "Rest R-0008 · 610 mm", "1 ganze Stange · 1.000 mm", "1 ganze Platte · 2.500 × 1.250 mm", "30 Stück",
            "8 Stück · 16 mm",
        ])
        XCTAssertEqual(v.weg[0].teil, "ALFER-Rohr")
        XCTAssertEqual(v.weg[3].hinweis, "34 gebraucht, 30 im Bestand")
        XCTAssertEqual(v.neu.map(\.text), ["Rest 144 mm", "Rest 697 mm", "Rest 1.697 × 1.250 mm", "Rest 800 × 647 mm"])
        XCTAssertEqual(v.kaufen.map(\.text), ["1 Stange · 1.000 mm"])
        XCTAssertEqual(v.verschnitt.map(\.text), ["4 mm"])
        XCTAssertEqual(v.verschnitt.first?.hinweis, "unter 80 mm, kommt nicht in den Bestand")
        XCTAssertFalse(v.leer)
        XCTAssertEqual(v.kurz, "5 Posten weg, 4 Reste neu")
        // Nur Kaufen, keine neuen Reste: nichts zu buchen
        let nurKaufen = BOMBestand(
            run: 1, zuschnitte: [BestandZuschnitt(stockID: "x", benennung: "X", quellen: [
                ZuschnittQuelle(index: 0, art: .kaufen, laenge: 1000, stuecke: [999], restNeu: 0, verschnitt: true),
            ])], einkaufsliste: [])
        XCTAssertTrue(GebautVorschau.berechnen(zuschnitt: nurKaufen, bestand: nil, lines: []).leer)
        XCTAssertFalse(nurKaufen.hatBuchbares)
        XCTAssertEqual(GebautVorschau.schraubenLaenge(bom.bom.lines[5]), 16)
        XCTAssertNil(GebautVorschau.schraubenLaenge(bom.bom.lines[4]))
    }

    func testEinkaufslisteExport() throws {
        let z = try XCTUnwrap(try BestandBeispiel.bomMessage().bestand)
        let csv = EinkaufslisteFormat.csv(z.einkaufsliste, summe: z.summe)
        XCTAssertTrue(csv.hasPrefix("\u{FEFF}Menge;Einheit;Benennung;Lagerteil;Preis je (EUR);Preis (EUR)"))
        let zeilen = csv.dropFirst().split(separator: "\r\n").map(String.init)
        XCTAssertEqual(zeilen.count, 5)
        XCTAssertEqual(zeilen[1], "1;Stange 1000 mm;ALFER-Rundrohr 12 × 1;rohr-alfer-12x1;3,90;3,90;2026-10;;https://www.example.com/alfer;")
        XCTAssertEqual(zeilen[2], "4;Stück;Flügelmutter DIN 315 M4;mutter-din315-m4;0,12;0,48;;Schraubenhandel;https://www.example.com/m4;Bestand im Projekt: 30, gebraucht: 34")
        XCTAssertEqual(zeilen[3], "2;Stück;\"Ohne Preis; mit \"\"Zeichen\"\"\";ohne-preis;;;;;;", "Feld mit Semikolon in Anführungszeichen")
        XCTAssertEqual(zeilen[4], ";;Summe;;;4,38;;;;")

        let text = EinkaufslisteFormat.text(z.einkaufsliste, summe: z.summe, projekt: "Kugelschieber", stand: "21.10.2026")
        XCTAssertEqual(text, """
            Einkaufsliste Kugelschieber (Stand 21.10.2026)
            - 1 × Stange 1000 mm: ALFER-Rundrohr 12 × 1, 3,90 € (https://www.example.com/alfer)
            - 4 × Stück: Flügelmutter DIN 315 M4, 0,48 € (https://www.example.com/m4)
              Bestand im Projekt: 30, gebraucht: 34
            - 2 × Stück: Ohne Preis; mit "Zeichen"
            Summe: 4,38 €
            """)
        XCTAssertEqual(EinkaufslisteFormat.text([], summe: nil, projekt: nil), "Einkaufsliste\nNichts zu kaufen, alles ist im Bestand.")
        XCTAssertEqual(EinkaufslisteFormat.dateiname(projekt: "Kugel/schieber"), "Kugel-schieber-einkaufsliste.csv")
    }
}

/// Controller: BESTAND übernehmen, speichern, „Gebaut“ mit Hinweis und Rückgängig, CSV.
@MainActor
final class BestandControllerTests: XCTestCase {
    private func connected() throws -> AppController {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        return c
    }

    private func msg(_ json: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(json.utf8))))
    }

    func testBestandUndBuchungen() throws {
        let c = try connected()
        let m = c.model
        XCTAssertFalse(m.bestandZustand.empfangen)
        c.handle([.message(.bestand(try BestandBeispiel.bestandMessage()))])
        XCTAssertTrue(m.bestandZustand.empfangen)
        XCTAssertEqual(m.bestandZustand.bestand?.posten.count, 4)
        XCTAssertEqual(m.bestandZustand.buchungen.count, 2)
        XCTAssertEqual(m.bestandZustand.stand, "2026-10-21T22:14:03")

        // BOM mit Bestand
        c.handle([.message(.bom(try BestandBeispiel.bomMessage()))])
        XCTAssertEqual(m.bom?.run, 7)
        XCTAssertEqual(m.bestandZustand.zuschnitt?.zuschnitte.count, 2)
        XCTAssertTrue(m.log.contains { $0.text.contains("Einkaufsliste: 3 Positionen") })

        // Speichern (a-1 ist das stille Nachladen des Katalogs nach der BOM): ACK ok → idle; abgelehnt → Fehler
        c.saveBestandPosten(id: "rohr-alfer-12x1", posten: ["ganze": ["anzahl": 3]], grund: "+1 Stange")  // a-2
        XCTAssertEqual(m.bestandZustand.aktivitaet, .saving)
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-2","ok":true}"#)])
        XCTAssertEqual(m.bestandZustand.aktivitaet, .idle)
        XCTAssertTrue(m.log.contains { $0.text == "Bestand: +1 Stange" })
        c.saveBestandEinstellungen(BestandEinstellungen(mindestrestMM: 50, saegeblattMM: 2), grund: "x")  // a-3
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-3","ok":false,"message":"Sägeblatt zu dünn"}"#)])
        XCTAssertEqual(m.bestandZustand.aktivitaet, .failed("Sägeblatt zu dünn"))

        // Gebaut: ACK mit Buchung → Hinweis mit Rückgängig
        c.bucheGebaut()  // a-4
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-4","ok":true,"buchung":"B-0005","message":"5 Posten weg, 4 Reste neu"}"#)])
        XCTAssertEqual(m.bestandZustand.aktivitaet, .idle)
        XCTAssertEqual(m.bestandZustand.hinweis?.buchung, "B-0005")
        XCTAssertEqual(m.bestandZustand.hinweis?.text, "5 Posten weg, 4 Reste neu")

        // BESTAND als Antwort auf BESTAND_REQ pflegt das Modell
        c.requestBestand()  // a-5
        c.handle([try msg(#"{"type":"BESTAND","reply_to":"a-5","bestand":null,"buchungen":[]}"#)])
        XCTAssertNil(m.bestandZustand.bestand)

        // Rückgängig: Hinweis ohne Buchung
        c.buchungRueckgaengig("B-0005")  // a-6
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-6","ok":true}"#)])
        XCTAssertNil(m.bestandZustand.hinweis?.buchung)
        XCTAssertEqual(m.bestandZustand.hinweis?.text, "Buchung B-0005 rückgängig gemacht.")
        c.verwerfeBuchungsHinweis()
        XCTAssertNil(m.bestandZustand.hinweis)

        // Projektwechsel: Zuschnitt und Hinweis gehören zum alten Projekt
        c.bucheGebaut()  // a-7
        c.handle([try msg(#"{"type":"ACK","reply_to":"a-7","ok":true,"buchung":"B-0007"}"#)])
        XCTAssertEqual(m.bestandZustand.hinweis?.text, "Als gebaut gebucht.")
        c.handle([try msg(#"{"type":"PROJECT","path":"/tmp/kevcad-bestand-anderes","name":"anderes"}"#)])
        XCTAssertNil(m.bestandZustand.zuschnitt)
        XCTAssertNil(m.bestandZustand.hinweis)
    }

    func testOhneVerbindungUndOhneStueckliste() throws {
        let c = AppController(model: AppModel())
        c.saveBestandPosten(id: "x", posten: nil, grund: "weg")
        XCTAssertEqual(c.model.bestandZustand.aktivitaet, .failed("Der Kernel ist nicht verbunden, der Bestand wurde nicht geändert."))
        c.bucheGebaut()
        XCTAssertEqual(c.model.bestandZustand.aktivitaet, .failed("Es gibt noch keine Stückliste, nach der gebucht werden könnte."))
    }

    func testEinkaufslisteAlsCSV() throws {
        let c = try connected()
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-bestand-csv-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        c.handle([try msg(#"{"type":"PROJECT","path":"\#(ordner.path)","name":"Kugelschieber"}"#)])
        c.handle([.message(.bom(try BestandBeispiel.bomMessage()))])  // a-1: Katalog still nachladen
        var gezeigt: [URL] = []
        c.revealFiles = { gezeigt = $0 }
        // Über den Kernel (EXPORT_REQ einkaufsliste_csv): seine Datei wird gezeigt
        c.exportEinkaufsliste()  // a-2
        c.handle([try msg(#"{"type":"EXPORT_RES","reply_to":"a-2","files":["/p/output/Kugelschieber-einkaufsliste.csv"]}"#)])
        XCTAssertEqual(gezeigt.map(\.path), ["/p/output/Kugelschieber-einkaufsliste.csv"])
        // Älterer Kernel ohne das Format: die App schreibt die CSV selbst
        c.exportEinkaufsliste()  // a-3
        c.handle([try msg(#"{"type":"ERROR","reply_to":"a-3","message":"Unbekanntes Format einkaufsliste_csv"}"#)])
        let datei = ordner.appendingPathComponent("output/Kugelschieber-einkaufsliste.csv")
        XCTAssertEqual(gezeigt.map(\.path), [datei.path])
        let text = try String(contentsOf: datei, encoding: .utf8)
        XCTAssertTrue(text.contains("ALFER-Rundrohr 12 × 1"))
        XCTAssertTrue(text.contains(";;Summe;;;4,38;;;;"))
    }
}
