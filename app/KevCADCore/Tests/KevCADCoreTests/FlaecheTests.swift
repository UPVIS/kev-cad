import XCTest

@testable import KevCADCore

/// V2-7: Zustand der Oberfläche und `VIEW_CMD flaeche` (PROTOCOL.md, „Fläche“).
final class FlaecheTests: XCTestCase {
    private func auftrag(_ a: JSONValue, _ z: OberflaechenZustand = OberflaechenZustand(),
                         blaetter: [(id: String, titel: String)]? = nil) throws -> FlaecheAuftrag {
        try FlaecheAuftrag.aus(a, zustand: z, blaetter: blaetter).get()
    }

    private func args(_ text: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(text.utf8))
    }

    func testKachelImFokusWechseltInDieWerkstatt() {
        var z = OberflaechenZustand()
        z.anwenden(.kachelZeigen(.modell))
        XCTAssertEqual(z.modus, .fokus, "das Modell ist der Fokus selbst")
        z.anwenden(.kachelZeigen(.druck))
        XCTAssertEqual(z.modus, .werkstatt)
        XCTAssertEqual(z.kacheln, [.modell, .druck])
        XCTAssertEqual(z.aktiv, .druck)
        XCTAssertEqual(z.nummer(.druck), 2)
    }

    func testAnimationBringtDasModellMit() {
        var z = OberflaechenZustand(modus: .werkstatt, kacheln: [.stueckliste])
        z.anwenden(.kachelZeigen(.animation))
        XCTAssertEqual(z.kacheln, [.stueckliste, .modell, .animation])
        z.anwenden(.kachelnOrdnen([.animation]))
        XCTAssertEqual(z.kacheln, [.modell, .animation])
    }

    func testFuenfteVerdraengtDieAeltesteAusserModell() throws {
        let z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell, .zeichnung, .stueckliste, .zuschnitt])
        let a = try auftrag(try args(#"{"zeigen": ["druck"]}"#), z)
        XCTAssertEqual(a.stand.kacheln, [.modell, .stueckliste, .zuschnitt, .druck])
        XCTAssertEqual(a.gewichen, [.zeichnung])
        XCTAssertEqual(a.meldung, "Werkstatt: 1 Modell, 2 Stückliste, 3 Zuschnitt, 4 Druck; Zeichnung musste weichen")
    }

    func testAmRandBleibtDieWerkstattNachDemZurueckkommen() {
        var z = OberflaechenZustand()
        z.anwenden(.rand(.rechts))
        XCTAssertEqual(z.modus, .fokus)
        z.anwenden(.kachelZeigen(.druck))
        XCTAssertEqual(z.modus, .werkstatt)
        XCTAssertEqual(z.rand, .rechts, "das Fenster bleibt schmal")
        z.anwenden(.rand(nil))
        XCTAssertEqual(z.modus, .werkstatt, "sonst wären die Kacheln des Agenten weg")
    }

    func testDieTestdateiWirktWieBeschrieben() throws {
        let kopf = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("live_view_flaeche.frame").header)
        var z = OberflaechenZustand(modus: .fokus, kacheln: [.modell])
        z.anwenden(.rand(.links))
        z.anwenden(.uebersicht(true))
        let a = try auftrag(kopf["args"] ?? .null, z, blaetter: [("b-1", "Zusammenbau"), ("b-2", "Rohr")])
        XCTAssertNil(a.stand.rand)
        XCTAssertFalse(a.stand.uebersicht, "die Startübersicht geht aus dem Weg")
        // ordnen [modell, zeichnung], zeigen druck, schließen 2, groß druck, Blatt 2 öffnet die Zeichnung wieder
        XCTAssertEqual(a.stand.kacheln, [.modell, .druck, .ansicht, .zeichnung])
        XCTAssertNil(a.stand.gross, "eine neue Kachel ordnet die große wieder ein")
        XCTAssertEqual(a.stand.modus, .werkstatt)
        XCTAssertEqual(a.stand.zweiteAnsicht, "front")
        XCTAssertEqual(a.stand.blatt, "b-2")
        XCTAssertFalse(a.stand.zeitleiste)
    }

    func testNummernMeinenDieKachelnWieKevinSieSieht() throws {
        let z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell, .zeichnung, .druck])
        var a = try auftrag(try args(#"{"schliessen": [2, 3]}"#), z)
        XCTAssertEqual(a.stand.kacheln, [.modell])
        XCTAssertEqual(a.gewichen, [], "geschlossen ist nicht gewichen")
        a = try auftrag(try args(#"{"gross": 3}"#), z)
        XCTAssertEqual(a.stand.gross, .druck)
        XCTAssertEqual(a.meldung, "Werkstatt: 1 Modell, 2 Zeichnung, 3 Druck (groß)")
        a = try auftrag(try args(#"{"schliessen": "alle", "modus": "fokus"}"#), z)
        XCTAssertEqual(a.stand.kacheln, [])
        XCTAssertEqual(a.stand.modus, .fokus)
        XCTAssertEqual(a.meldung, "Fokus")
    }

    func testFalscheAngabenAendernNichts() throws {
        let z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell])
        for (text, erwartet) in [
            (#"{"zeigen": ["druck", "kaffee"]}"#, "Unbekannte Kachel in zeigen: kaffee"),
            (#"{"gross": 3}"#, "Kachel 3 gibt es nicht"),
            (#"{"schliessen": ["druck"]}"#, "Kachel druck ist nicht offen"),
            (#"{"modus": "ruhe", "zeigen": ["druck"]}"#, "Unbekannter Modus ruhe"),
            (#"{"rand": "oben"}"#, "Unbekannter Rand oben"),
            (#"{"ansicht": "schraeg"}"#, "Unbekannte Ansicht schraeg"),
            (#"{"blatt": 2}"#, "Noch keine Zeichnungsblätter da"),
        ] {
            XCTAssertEqual(FlaecheAuftrag.aus(try args(text), zustand: z, blaetter: nil), .failure(FlaecheFehler(erwartet)))
        }
    }

    func testBlattNachNummerKennungUndTitel() throws {
        let z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell, .zeichnung])
        let blaetter: [(id: String, titel: String)] = [("b-1", "Zusammenbau"), ("b-2", "Rohr 40 × 40")]
        XCTAssertEqual(try auftrag(try args(#"{"blatt": 1}"#), z, blaetter: blaetter).stand.blatt, "b-1")
        XCTAssertEqual(try auftrag(try args(#"{"blatt": "b-2"}"#), z, blaetter: blaetter).stand.blatt, "b-2")
        XCTAssertEqual(try auftrag(try args(#"{"blatt": "rohr"}"#), z, blaetter: blaetter).stand.blatt, "b-2")
        XCTAssertEqual(FlaecheAuftrag.aus(try args(#"{"blatt": 9}"#), zustand: z, blaetter: blaetter),
                       .failure(FlaecheFehler("Blatt 9 gibt es nicht (2 Blätter)")))
    }
}
