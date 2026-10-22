import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Bestand Stufe 2“, App: Spulen im Bestand, BESTAND_SAVE mit Spulen, Filament in der Vorschau „Gebaut“ und
/// `hatBuchbares` mit Filament. Erwartungen aus den Testdateien des Kernels (kernel/tools/make_bestand_fixtures.py,
/// Abschnitt `bestand.filament` in fixtures.json): PETG 120 g (reicht nicht, der Rest einer gekauften Spule wird
/// S-0004), PLA mit zwei Spulen (angebrochen und voll), Platte 2 schon als gedruckt gebucht.
final class FilamentBestandTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try XCTUnwrap(try Fixtures.expected()["bestand"]?["filament"])
    }

    private func bestand() throws -> BestandMessage {
        guard case .bestand(let m) = try Fixtures.message("bestand_filament.frame") else {
            throw NSError(domain: "Filament", code: 1, userInfo: [NSLocalizedDescriptionKey: "kein BESTAND"])
        }
        return m
    }

    func testSpulenAusDerTestdatei() throws {
        let e = try erwartet()
        let b = try XCTUnwrap(try bestand().bestand)
        XCTAssertTrue(b.fuehrtFilament)
        XCTAssertEqual(b.spulen.map(\.kennung), try XCTUnwrap(e["spulen"]?.arrayValue).compactMap(\.stringValue))
        XCTAssertEqual(b.spulen.filter { $0.zustand == .voll }.map(\.kennung),
                       try XCTUnwrap(e["voll"]?.arrayValue).compactMap(\.stringValue))
        let petg = try XCTUnwrap(b.spulen.first { $0.kennung == "S-0001" })
        XCTAssertEqual(petg.bezeichnung, "Bambu PETG Basic schwarz")
        XCTAssertEqual(petg.mengeText, "120 g von 1.000 g")
        XCTAssertEqual(petg.anteil ?? 0, 0.12, accuracy: 1e-9)
        XCTAssertEqual([petg.hersteller, petg.farbe, petg.ort], ["Bambu Lab", "schwarz", "Regal 3"])
        // Ab zwei Spulen: angebrochene zuerst (wie der Kernel abbucht), dann volle
        let pla = b.spulen(material: "pla")
        XCTAssertEqual(pla.map(\.kennung), ["S-0002", "S-0003"])
        XCTAssertEqual(pla.map(\.zustand), [.angebrochen, .voll])
        XCTAssertEqual(pla[1].bezeichnung, "Amazon Basics weiß")  // ohne Name: Hersteller und Farbe
        XCTAssertEqual(b.filamentMaterialien, ["petg", "pla"])
        // Lagerteile bleiben, wie sie sind; ein Bestand ohne Liste führt kein Filament
        XCTAssertEqual(b.posten.count, 4)
        XCTAssertFalse(Bestand.leer.fuehrtFilament)
        XCTAssertTrue(Bestand.leer.spulen.isEmpty)
    }

    func testGebautFilamentAusDerTestdatei() throws {
        let e = try XCTUnwrap(try erwartet()["gebaut"])
        let g = try XCTUnwrap(try bestand().gebautFilament)
        XCTAssertEqual(g.run, e["run"]?.intValue)
        let platten = try XCTUnwrap(e["platten"]?.arrayValue)
        XCTAssertEqual(g.platten.map(\.nr), platten.compactMap { $0.arrayValue?[0].intValue })
        XCTAssertEqual(g.platten.map(\.gebucht), platten.map { $0.arrayValue?[1].stringValue })
        XCTAssertEqual(g.platten.map(\.buchen), platten.compactMap { $0.arrayValue?[2].boolValue })
        let spulen = try XCTUnwrap(e["spulen"]?.arrayValue)
        XCTAssertEqual(g.spulen.map(\.kennung), spulen.compactMap { $0.arrayValue?[0].stringValue })
        XCTAssertEqual(g.spulen.map(\.gramm), spulen.compactMap { $0.arrayValue?[1].doubleValue })
        XCTAssertEqual(g.spulen.map(\.nachher), spulen.compactMap { $0.arrayValue?[3].doubleValue })
        XCTAssertEqual(g.spulen.map(\.leer), spulen.compactMap { $0.arrayValue?[4].boolValue })
        XCTAssertEqual(g.neueSpulen.map(\.kennung), try XCTUnwrap(e["neue_spulen"]?.arrayValue).compactMap {
            $0.arrayValue?[0].stringValue })
        XCTAssertEqual(g.gekauft.map(\.material), try XCTUnwrap(e["gekauft"]?.arrayValue).compactMap {
            $0.arrayValue?[0].stringValue })
        XCTAssertEqual(g.name("petg"), "PETG")
        XCTAssertTrue(g.hatBuchbares)
        XCTAssertEqual(g.plattenText(g.platten[0]), "PETG 188,8 g")
    }

    /// Dialog „Gebaut“: welche Spule wie viel Gramm verliert, neue Spule, Gekauftes, Platten mit ihrem Stand.
    func testGebautVorschauMitFilament() throws {
        let g = try XCTUnwrap(try bestand().gebautFilament)
        let nichts = BOMBestand(run: 5, zuschnitte: [], einkaufsliste: [])
        let v = GebautVorschau.berechnen(zuschnitt: nichts, bestand: try bestand().bestand, lines: [], filament: g)
        XCTAssertFalse(v.leer, "nur Filament zu buchen: die Vorschau ist nicht leer")
        let weg = try XCTUnwrap(v.weg.first { $0.art == .filamentWeg })
        XCTAssertEqual(weg.text, "120,0 g von Spule S-0001")
        XCTAssertEqual(weg.teil, "Filament PETG · Bambu PETG Basic schwarz")
        XCTAssertEqual(weg.hinweis, "danach leer, wird aus dem Bestand entfernt")
        XCTAssertEqual(v.neu.map(\.text), ["Spule S-0004 · 931,2 g"])
        XCTAssertEqual(v.kaufen.map(\.text), ["68,8 g von gekauften Spulen"])
        XCTAssertEqual(v.platten.map(\.text), ["Platte 1", "Platte 2"])
        XCTAssertEqual(v.platten.map(\.gebucht), [false, true])
        XCTAssertEqual(v.platten[1].hinweis, "schon als gedruckt gebucht (B-0005)")
        XCTAssertEqual(v.platten[0].hinweis, "wird jetzt abgebucht")
        // Ohne Filament wie bisher
        XCTAssertTrue(GebautVorschau.berechnen(zuschnitt: nichts, bestand: nil, lines: []).platten.isEmpty)
    }

    /// „Gebaut“ ist nicht gesperrt, wenn nur Filament zu buchen ist; die Rechnung muss zur Stückliste gehören.
    func testHatBuchbaresMitFilament() throws {
        let g = try XCTUnwrap(try bestand().gebautFilament)
        let nurKaufen = BOMBestand(
            run: 5, zuschnitte: [BestandZuschnitt(stockID: "rohr", benennung: "Rohr", stangenlaenge: 1000, saegeschnitt: 3,
                                                  quellen: [ZuschnittQuelle(index: 0, art: .kaufen, laenge: 1000,
                                                                            stuecke: [990])], kaufen: 1)],
            einkaufsliste: [])
        XCTAssertFalse(nurKaufen.hatBuchbares)
        var z = BestandZustand(zuschnitt: nurKaufen)
        XCTAssertFalse(z.hatBuchbares)
        z.gebautFilament = g
        XCTAssertTrue(z.hatBuchbares)
        XCTAssertNotNil(z.gebautFilamentAktuell)
        // Rechnung zu einem anderen Lauf: zählt nicht
        z.zuschnitt?.run = 6
        XCTAssertNil(z.gebautFilamentAktuell)
        XCTAssertFalse(z.hatBuchbares)
        // Filament geführt, aber nichts abzubuchen
        z.zuschnitt?.run = 5
        z.gebautFilament = GebautFilament(run: 5, hinweis: "Filament aller Platten schon gebucht")
        XCTAssertFalse(z.hatBuchbares)
    }

    @MainActor
    func testControllerUebernimmtGebautFilament() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("bestand_filament.frame"))])
        XCTAssertEqual(c.model.bestandZustand.gebautFilament?.spulen.map(\.kennung), ["S-0001"])
        XCTAssertEqual(c.model.bestandZustand.bestand?.spulen.count, 3)
        // Ein BESTAND ohne gebaut_filament (Projekt führt kein Filament) setzt es zurück
        c.handle([.message(try Fixtures.message("bestand.frame"))])
        XCTAssertNil(c.model.bestandZustand.gebautFilament)
    }

    /// Die Anfragen der App mit Spulen entsprechen den Testdateien des Kernels.
    func testSpulenAnfragenWieTestdateien() throws {
        func kopf(_ name: String) throws -> [String: JSONValue] {
            try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame(name).header).objectValue)
        }
        func meins(_ m: BestandSaveMessage, seq: Int) throws -> [String: JSONValue] {
            var m = m
            m.seq = seq
            return try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()).objectValue)
        }
        let neu = SpulenEingabe(material: "petg", gramm: 1000, grammVoll: 1000, name: "Bambu PETG Basic schwarz",
                                hersteller: "Bambu Lab", farbe: "schwarz", ort: "Regal 3")
        XCTAssertNil(neu.fehler)
        var k = try kopf("bestand_save_spule.frame")
        XCTAssertEqual(try meins(BestandSaveMessage(id: "a-25", spuleKennung: nil, spule: neu.json, anzahl: 2,
                                                    grund: "Filament: 2 Spulen PETG"), seq: k["seq"]?.intValue ?? 0), k)
        var aendern = neu
        aendern.gramm = 310
        aendern.ort = ""
        k = try kopf("bestand_save_spule_aendern.frame")
        XCTAssertEqual(try meins(BestandSaveMessage(id: "a-26", spuleKennung: "S-0001", spule: aendern.json, anzahl: 5,
                                                    grund: "Spule S-0001 geändert"), seq: k["seq"]?.intValue ?? 0), k,
                       "beim Ändern geht keine Anzahl mit")
        k = try kopf("bestand_save_spule_entfernen.frame")
        XCTAssertEqual(try meins(BestandSaveMessage(id: "a-27", spuleKennung: "S-0003", spule: nil,
                                                    grund: "Spule S-0003 entfernt"), seq: k["seq"]?.intValue ?? 0), k)
        k = try kopf("bestand_save_filament_fuehren.frame")
        XCTAssertEqual(try meins(BestandSaveMessage(id: "a-28", filamentFuehren: true, grund: "Filament führen"),
                                 seq: k["seq"]?.intValue ?? 0), k)
    }

    func testSpulenEingabePrueft() {
        XCTAssertEqual(SpulenEingabe(material: "").fehler, "Material wählen")
        XCTAssertNotNil(SpulenEingabe(material: "petg", gramm: -1).fehler)
        XCTAssertNotNil(SpulenEingabe(material: "petg", grammVoll: 0).fehler)
        XCTAssertNotNil(SpulenEingabe(material: "petg", gramm: 2000, grammVoll: 1000).fehler)
        XCTAssertNil(SpulenEingabe(material: "petg", gramm: nil, grammVoll: 1000).fehler)
        // Vorbelegt mit einer Spule: leere Felder werden zu leeren Texten (der Kernel löscht sie)
        let s = try? XCTUnwrap(BestandSpule(json: .object(["kennung": "S-0009", "material": "pla", "gramm": 5])))
        XCTAssertEqual(s?.zustand, .angebrochen, "ohne volle Menge gilt sie als angebrochen")
        XCTAssertEqual(SpulenEingabe(s!).json["ort"], .string(""))
        XCTAssertNil(BestandSpule(json: .object(["material": "pla"])), "ohne Kennung keine Spule")
    }
}
