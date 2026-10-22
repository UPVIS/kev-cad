import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Material im Kernel angleichen“ (22.10.2026): Was Claude über MCP liest, ist genau das, was Kevin in der App
/// sieht. Die App rechnet mit `MaterialDaten` und `MaterialText`, der Kernel mit `bestand/einkauf.py` und
/// `bom.verschnitt_bilanz`; die Erwartungen kommen vom Kernel (kernel/tools/make_bestand_fixtures.py, Abschnitt
/// `material` in fixtures.json). Beispiel: Kugelschieber mit Resten (neue und solche unter dem Mindestrest), Normteilen
/// teils aus dem Bestand, Zukaufteilen mit und ohne Link, Druckteilen und der Druckvorschau desselben Laufs.
final class MaterialKernelGleichTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try XCTUnwrap(try Fixtures.expected()["material"])
    }

    private func bom() throws -> BOMMessage {
        guard case .bom(let m) = try Fixtures.message("bom_material.frame") else {
            throw NSError(domain: "Material", code: 1, userInfo: [NSLocalizedDescriptionKey: "kein BOM"])
        }
        return m
    }

    private func druck() throws -> Druckvorschau {
        guard case .druck(.vorschau(let v, _)) = try Fixtures.message("print_material.frame") else {
            throw NSError(domain: "Material", code: 2, userInfo: [NSLocalizedDescriptionKey: "kein PRINT_PREVIEW"])
        }
        return v
    }

    private func daten(mitDruck: Bool = true) throws -> MaterialDaten {
        let m = try bom()
        return MaterialDaten(bom: m.bom, bestand: m.bestand, druckvorschau: mitDruck ? try druck() : nil)
    }

    /// Zwei Beträge, wie beide Seiten sie zeigen (auf Cent gerundet).
    private func euro(_ v: Double?) -> String? { v.map(KevFormat.euro) }

    func testEinkaufslisteTextUndCSVByteweiseWieDerKernel() throws {
        let e = try erwartet()
        let projekt = e["projekt"]?.stringValue
        let stand = e["stand"]?.stringValue
        let d = try daten()
        XCTAssertEqual(MaterialText.einkaufText(d, projekt: projekt, stand: stand), e["text"]?.stringValue)
        let csv = MaterialText.einkaufCSV(d)
        XCTAssertEqual(Data(csv.utf8), Data(try XCTUnwrap(e["csv"]?.stringValue).utf8), "CSV Byte für Byte")
        XCTAssertTrue(csv.hasPrefix("\u{FEFF}Gruppe;Menge;Einheit;Benennung;Lagerteil;"))
        // Ohne Druckvorschau: Filament aus den Druckteilen der Stückliste, wie im Kernel
        let ohne = try daten(mitDruck: false)
        XCTAssertEqual(MaterialText.einkaufText(ohne, projekt: projekt, stand: stand), e["text_ohne_druck"]?.stringValue)
        XCTAssertEqual(Data(MaterialText.einkaufCSV(ohne).utf8),
                       Data(try XCTUnwrap(e["csv_ohne_druck"]?.stringValue).utf8))
        // Eine Druckvorschau eines anderen Laufs gilt nicht (beide Seiten nehmen dann die Stückliste)
        var alt = try druck()
        alt.run += 1
        let m = try bom()
        XCTAssertEqual(MaterialDaten(bom: m.bom, bestand: m.bestand, druckvorschau: alt).filament, ohne.filament)
        // Abgehakte Zeilen kennt nur die App; ohne Haken ist der Text der des Kernels
        var a = EinkaufAbgehakt()
        a.umschalten(d.einkauf[0])
        let abgehakt = MaterialText.einkaufText(d, projekt: projekt, stand: stand, abgehakt: a.schluessel)
        XCTAssertEqual(abgehakt.replacingOccurrences(of: "- [x] ", with: "- [ ] "), e["text"]?.stringValue)
    }

    func testGleicheGruppenUndSummen() throws {
        let e = try erwartet()
        let d = try daten()
        let k = d.kennzahlen
        XCTAssertEqual(k.einkaufPositionen, e["positionen"]?.intValue)
        XCTAssertEqual(d.lagerEinkauf.count, e["lager"]?.intValue)
        XCTAssertEqual(d.zukaufEinkauf.count, e["zukauf"]?.intValue)
        XCTAssertEqual(euro(k.einkaufSumme), euro(e["summe"]?.doubleValue))
        XCTAssertEqual(euro(k.einkaufLagerSumme), euro(e["summe_lager"]?.doubleValue))
        XCTAssertEqual(euro(k.einkaufZukaufSumme), euro(e["summe_zukauf"]?.doubleValue))
        XCTAssertEqual(k.einkaufSumme ?? 0, e["summe"]?.doubleValue ?? -1, accuracy: 1e-9)
        XCTAssertEqual(k.einkaufOhnePreis, e["ohne_preis"]?.intValue)
        XCTAssertEqual(d.stueckgut.count, e["normteile"]?.intValue)
        // Die Zeile in `run` nennt dieselbe Zahl und Summe wie die Seitenleiste der App
        let zeile = try XCTUnwrap(e["run_zeile"]?.stringValue)
        XCTAssertTrue(zeile.contains(KevFormat.count(k.einkaufPositionen, one: "Position", many: "Positionen")), zeile)
        XCTAssertTrue(zeile.contains(k.einkaufText), zeile)
        // Beispiel deckt alles ab: Reste, Normteile teils aus dem Bestand, Zukauf mit und ohne Link
        XCTAssertTrue(d.stueckgut.contains { $0.ausBestand > 0 && $0.kaufen > 0 })
        XCTAssertTrue(d.zukaufEinkauf.contains { $0.position.link != nil })
        XCTAssertTrue(d.zukaufEinkauf.contains { $0.position.link == nil })
        // Filament: aus der Druckvorschau (mit Ersatzteilen), sonst aus der Stückliste
        func vergleiche(_ liste: [MaterialFilament], _ soll: [JSONValue]) {
            XCTAssertEqual(liste.map(\.werkstoff), soll.compactMap { $0["werkstoff"]?.stringValue })
            XCTAssertEqual(liste.map(\.teile), soll.compactMap { $0["teile"]?.intValue })
            XCTAssertEqual(liste.map { KevFormat.mass(grams: $0.gramm) },
                           soll.compactMap { $0["gramm"]?.doubleValue }.map { KevFormat.mass(grams: $0) })
            XCTAssertEqual(liste.map { euro($0.preis) }, soll.map { euro($0["preis"]?.doubleValue) })
        }
        let soll = try XCTUnwrap(e["filament"]?.arrayValue)
        vergleiche(d.filament, soll)
        XCTAssertEqual(d.filament.map { $0.stand?.rawValue }, soll.map { $0["stand"]?.stringValue })
        vergleiche(try daten(mitDruck: false).filament, try XCTUnwrap(e["filament_ohne_druck"]?.arrayValue))
        XCTAssertTrue(try daten(mitDruck: false).filament.allSatisfy { $0.stand == nil })
    }

    func testGleicherVerschnitt() throws {
        let e = try erwartet()
        let d = try daten()
        let je = try XCTUnwrap(e["verschnitt"])
        XCTAssertEqual(d.zuschnitte.count, je.objectValue?.count)
        for z in d.zuschnitte {
            let kernel = try XCTUnwrap(je[z.stockID]?.doubleValue, z.stockID)
            let app = try XCTUnwrap(d.verschnitt(z), z.stockID)
            XCTAssertEqual(KevFormat.number(app, digits: 1), KevFormat.number(kernel, digits: 1), z.stockID)
            // Das Feld im Protokoll trägt den neuen Wert und sagt, dass er so gerechnet ist
            XCTAssertEqual(z.verschnittProzent, kernel)
            XCTAssertTrue(z.verschnittWieApp, z.stockID)
        }
        let gesamt = try XCTUnwrap(e["verschnitt_gesamt"])
        XCTAssertEqual(gesamt["definition"]?.stringValue, MaterialZuschnitt.definition)
        XCTAssertEqual(d.kennzahlen.verschnittStangen.map { KevFormat.number($0, digits: 1) },
                       gesamt["stangen"]?.doubleValue.map { KevFormat.number($0, digits: 1) })
        XCTAssertEqual(d.kennzahlen.verschnittPlatten.map { KevFormat.number($0, digits: 1) },
                       gesamt["platten"]?.doubleValue.map { KevFormat.number($0, digits: 1) })
        // Neue Reste zählen nicht, Reste unter dem Mindestrest schon
        let rohr = try XCTUnwrap(d.zuschnitt("rohr-alfer-12x1"))
        XCTAssertTrue(rohr.hatNeueReste)
        XCTAssertTrue(rohr.quellen.contains { $0.verschnitt })
        // Ein älterer Kernel ohne Definition: die App rechnet selbst, das Kennzeichen fehlt
        var alt = rohr
        alt.verschnittDefinition = nil
        XCTAssertFalse(alt.verschnittWieApp)
    }
}
