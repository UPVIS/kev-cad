import Foundation
import XCTest

@testable import KevCADCore

/// Freigabe im Projektfenster (Strang „Feinschliff 2“, Punkt 2): Anfrage von Claude lesen, Vorschau der Vorschläge,
/// „Alle freigeben“ der Reihe nach über die Freigabe des Lagerkatalogs, Fehler bleiben stehen, Meldung beim Schließen.
@MainActor
final class FreigabeTests: XCTestCase {
    private func connectedController() throws -> AppController {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        return c
    }

    private func message(_ json: String) throws -> IncomingEvent {
        .message(try KernelMessage.decode(Frame(header: Data(json.utf8))))
    }

    private let eintraege: [JSONValue] = [
        ["id": "rohr-alfer-16x1", "art": "rohr", "name": "ALFER-Rundrohr 16 × 1", "norm": "ALFER 01024",
         "masse": ["d": 16, "s": 1], "material": "aluminium-6060", "stangenlaenge": 1000,
         "preis": ["je_m": 4.2, "quelle": "Baumarkt", "stand": "2026-10"],
         "bezugsquelle": ["url": "https://www.alfer.com/", "name": "ALFER"], "status": "vorgeschlagen",
         "vorgeschlagen_am": "2026-10-22", "ebene": "eigen"],
        ["id": "alutec-05200", "art": "zukaufteil", "name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC",
         "mpn": "05200", "gtin": "4005187052008", "url": "https://www.beispiel-shop.de/p/alutec-05200",
         "masse": ["l": 610, "b": 410, "h": 128], "preis": ["je_stueck": 24.99, "brutto": true, "stand": "2026-10-21"],
         "status": "vorgeschlagen", "ebene": "projekt"],
        ["id": "rohr-alfer-12x1", "art": "rohr", "name": "ALFER-Rundrohr 12 × 1", "masse": ["d": 12, "s": 1],
         "material": "aluminium-6060", "ebene": "mitgeliefert"],
    ]

    private func catalog(_ replyTo: String, frei: Set<String> = []) throws -> IncomingEvent {
        let items: [JSONValue] = eintraege.map { e in
            guard case .object(var o) = e, let id = o["id"]?.stringValue else { return e }
            if frei.contains(id) { o["status"] = "frei" }
            return .object(o)
        }
        let mats: [JSONValue] = [
            ["id": "aluminium-6060", "name": "Aluminium 6060", "gruppe": "Aluminium", "dichte": 2.7, "farbe": "#C0C4C8"],
            ["id": "petg-cf", "name": "PETG-CF", "gruppe": "Kunststoff", "dichte": 1.3, "farbe": "#222222",
             "druckbar": true, "preis_je_kg": 29.0, "preis_quelle": "Bambu", "preis_stand": "2026-10",
             "status": frei.contains("petg-cf") ? "frei" : "vorgeschlagen", "ebene": "eigen"],
        ]
        let head: JSONValue = ["type": "CATALOG", "reply_to": .string(replyTo), "materials": .array(mats),
                               "items": .array(items)]
        return .message(try KernelMessage.decode(Frame(header: try JSONEncoder().encode(head))))
    }

    func testAnfrageUndMeldungWieDieTestdatei() throws {
        guard case .freigabe(let a) = try Fixtures.message("freigabe_anfrage.frame") else {
            return XCTFail("keine FREIGABE_ANFRAGE")
        }
        XCTAssertEqual(a.requestID, "k-7")
        XCTAssertEqual(a.anfrage, "F-0001")
        XCTAssertEqual(a.grund, "Für die Lenksperren am Kugelschieber")
        XCTAssertEqual(a.eintraege.map(\.id), ["rohr-alfer-16x1", "petg-cf"])
        XCTAssertEqual(a.eintraege.map(\.kind), ["teil", "material"])
        XCTAssertEqual(a.eintraege.first?.name, "ALFER-Rundrohr 16 × 1")
        let soll = try XCTUnwrap(try Fixtures.expected()["freigabe"]?["geschlossen"]?.objectValue)
        let m = FreigabeGeschlossenMessage(
            anfrage: "F-0001", freigegeben: ["rohr-alfer-16x1"], abgelehnt: [], offen: ["petg-cf"])
        var ist = try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()).objectValue)
        ist.removeValue(forKey: "seq")
        XCTAssertEqual(JSONValue.object(ist), JSONValue.object(soll))
    }

    func testVorschauDerVorschlaege() throws {
        let c = try connectedController()
        c.handle([try catalog("x")])
        let liste = FreigabeListe.vorschlaege(c.model.catalog, angefragt: ["petg-cf", "alutec-05200"])
        XCTAssertEqual(liste.map(\.id), ["petg-cf", "alutec-05200", "rohr-alfer-16x1"], "angefragte zuerst")
        XCTAssertEqual(liste.map(\.angefragt), [true, true, false])
        XCTAssertEqual(FreigabeListe.bandText(liste.count), "3 Vorschläge warten auf Freigabe")
        XCTAssertEqual(FreigabeListe.bandText(1), "1 Vorschlag wartet auf Freigabe")
        let rohr = try XCTUnwrap(liste.last)
        let werte = Dictionary(uniqueKeysWithValues: rohr.zeilen.map { ($0.titel, $0.wert) })
        XCTAssertEqual(werte["Maße"], "d 16 · s 1 mm")
        XCTAssertEqual(werte["Material"], "Aluminium 6060 (aluminium-6060)")
        XCTAssertEqual(werte["Preis"], "4,20 €/m (Baumarkt, 2026-10)")
        XCTAssertEqual(rohr.link?.absoluteString, "https://www.alfer.com/")
        XCTAssertEqual(rohr.vorgeschlagenAm, "22.10.2026")
        let roller = liste[1]
        let r = Dictionary(uniqueKeysWithValues: roller.zeilen.map { ($0.titel, $0.wert) })
        XCTAssertEqual(r["Hersteller"], "ALUTEC")
        XCTAssertEqual(r["Nummer"], "05200")
        XCTAssertEqual(r["EAN"], "4005187052008")
        XCTAssertEqual(r["Preis"], "24,99 €/Stück (2026-10-21, brutto)")
        XCTAssertEqual(roller.link?.host, "www.beispiel-shop.de")
        XCTAssertEqual(roller.artTitel, "Zukaufteil")
        let petg = liste[0]
        XCTAssertEqual(petg.kind, "material")
        XCTAssertTrue(petg.zeilen.contains { $0.titel == "3D-Druck" })
    }

    /// „Alle freigeben“: der Reihe nach, jede Freigabe erst nach der Bestätigung im neu geladenen Katalog; ein Fehler
    /// hält an und bleibt stehen.
    func testAlleFreigebenDerReiheNachUndFehlerBleiben() throws {
        let c = try connectedController()
        let m = c.model
        c.handle([try message(#"{"type":"FREIGABE_ANFRAGE","id":"k-3","anfrage":"F-0002","grund":"Für den Wagen","eintraege":[{"id":"rohr-alfer-16x1","kind":"teil"},{"id":"petg-cf","kind":"material"}]}"#)])
        XCTAssertEqual(m.freigabe.anfrage?.anfrage, "F-0002")
        c.handle([try catalog("a-1")])  // die App lädt nach dem Öffnen den Katalog (a-1)
        let alle = FreigabeListe.vorschlaege(m.catalog, angefragt: ["rohr-alfer-16x1", "petg-cf"]).map(\.eintrag)
        XCTAssertEqual(alle.count, 3)
        c.freigeben(alle)
        XCTAssertEqual(m.freigabe.laeuft, "rohr-alfer-16x1")
        XCTAssertEqual(m.freigabe.warteschlange.map(\.id), ["petg-cf", "alutec-05200"])
        // Rohr: gespeichert (a-2), nachgeladen (a-3) und frei → Material startet (a-4)
        c.handle([try message(#"{"type":"ACK","reply_to":"a-2","ok":true}"#)])
        c.handle([try catalog("a-3", frei: ["rohr-alfer-16x1"])])
        XCTAssertEqual(m.freigabe.freigegeben, ["rohr-alfer-16x1"])
        XCTAssertEqual(m.freigabe.laeuft, "petg-cf")
        // Material abgelehnt: anhalten, Fehler bleibt (auch nach stillem Nachladen)
        c.handle([try message(#"{"type":"ACK","reply_to":"a-4","ok":false,"message":"preis_stand fehlt"}"#)])
        XCTAssertNil(m.freigabe.laeuft)
        XCTAssertTrue(m.freigabe.warteschlange.isEmpty)
        XCTAssertEqual(m.freigabe.fehler, "„petg-cf“ nicht freigegeben: preis_stand fehlt")
        c.handle([try catalog("a-90", frei: ["rohr-alfer-16x1"])])
        XCTAssertNotNil(m.freigabe.fehler)
        // Erneut: der Fehler verschwindet, schon Freies wird übersprungen
        c.freigeben([FreigabeEintrag(id: "rohr-alfer-16x1", kind: "teil"), FreigabeEintrag(id: "alutec-05200", kind: "teil")])
        XCTAssertNil(m.freigabe.fehler)
        XCTAssertEqual(m.freigabe.laeuft, "alutec-05200")
        c.handle([try message(#"{"type":"ACK","reply_to":"a-5","ok":true}"#)])
        c.handle([try catalog("a-6", frei: ["rohr-alfer-16x1", "alutec-05200"])])
        XCTAssertNil(m.freigabe.laeuft)
        XCTAssertEqual(m.freigabe.freigegeben, ["rohr-alfer-16x1", "alutec-05200"])
        // Schließen: Anfrage erledigt
        c.freigabeSchliessen()
        XCTAssertNil(m.freigabe.anfrage)
        XCTAssertEqual(m.freigabe.freigegeben, [])
        // Ohne Kernel: sofort eine Meldung
        c.handle([.disconnected("weg")])
        c.freigeben([FreigabeEintrag(id: "petg-cf", kind: "material")])
        XCTAssertNotNil(m.freigabe.fehler)
        XCTAssertNil(m.freigabe.laeuft)
    }
}
