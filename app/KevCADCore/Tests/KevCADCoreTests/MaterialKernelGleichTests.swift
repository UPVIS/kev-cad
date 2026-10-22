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
        let v: Druckvorschau? = try mitDruck ? druck() : nil
        return MaterialDaten(bom: m.bom, bestand: m.bestand, druckvorschau: v)
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
        // Zukaufteile im Bestand (Strang „Feinschliff 2“): ganz gedeckt entfällt, teilweise mit Fehlmenge und Hinweis
        XCTAssertEqual(d.zukaufAusBestand.map(\.stockID),
                       try XCTUnwrap(e["zukauf_aus_bestand"]?.arrayValue).compactMap(\.stringValue))
        XCTAssertTrue(d.zukaufAusBestand.contains { $0.kaufen == 0 })
        XCTAssertFalse(d.zukaufEinkauf.contains { $0.position.id == "blackmagic-pocket-6k-pro" })
        XCTAssertTrue(d.zukaufEinkauf.contains { $0.position.hinweis?.hasSuffix("Bestand im Projekt: 1, gebraucht: 2") == true })
        XCTAssertEqual(d.position(enthaelt: "Kamera/Blackmagic Pocket 6K Pro")?.versorgung, [.bestand])
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

    /// Strang „Bestand Stufe 2“: Filament-Spulen nach Abzug des Projektbestands (`BOM.filament_bestand`), auf ganze
    /// Spulen aufgerundet, nur gegen die Druckvorschau desselben Laufs; stehen unter Lagerware hinter der Stückliste und
    /// zählen zur Summe. Beispiel: PETG 120 g im Bestand für 188,8 g (eine Spule kaufen), PLA 310 g für 24,6 g (reicht).
    func testFilamentSpulenWieDerKernel() throws {
        let e = try erwartet()
        let m = try bom()
        let bestand = try XCTUnwrap(m.bestand)
        XCTAssertEqual(bestand.filamentBestand?.map(\.material),
                       try XCTUnwrap(e["filament_bestand"]?.arrayValue).compactMap { $0["material"]?.stringValue })
        let soll = try XCTUnwrap(e["filament_kauf"]?.arrayValue)
        XCTAssertEqual(soll.count, 1)
        let d = try daten()
        let ist = d.lagerEinkauf.suffix(soll.count).map(\.position)
        XCTAssertEqual(ist.map(\.id), soll.compactMap { $0["id"]?.stringValue })
        XCTAssertEqual(ist.map(\.benennung), soll.compactMap { $0["benennung"]?.stringValue })
        XCTAssertEqual(ist.map(\.menge), soll.compactMap { $0["menge"]?.doubleValue })
        XCTAssertEqual(ist.map(\.einheit), soll.compactMap { $0["einheit"]?.stringValue })
        XCTAssertEqual(ist.map(\.preisJe), soll.map { $0["preis_je"]?.doubleValue })
        XCTAssertEqual(ist.map(\.preis), soll.map { $0["preis"]?.doubleValue })
        XCTAssertEqual(ist.map(\.hinweis), soll.map { $0["hinweis"]?.stringValue })
        XCTAssertEqual(ist.map(\.stand), soll.map { $0["preis_stand"]?.stringValue })
        XCTAssertFalse(d.lagerEinkauf.contains { $0.position.id == "pla" }, "PLA reicht aus dem Bestand")
        // Ohne Druckvorschau desselben Laufs keine Spulen, wie im Kernel
        XCTAssertEqual(try daten(mitDruck: false).lagerEinkauf.filter { $0.position.einheit.hasPrefix("Spule ") }
            .map(\.position.id), try XCTUnwrap(e["filament_kauf_ohne_druck"]?.arrayValue).compactMap(\.stringValue))
        // Führt das Projekt kein Filament (älterer Kernel, kein filament_bestand): keine Spulen, Summe wie bisher
        var ohne = bestand
        ohne.filamentBestand = nil
        let alt = MaterialDaten(bom: m.bom, bestand: ohne, druckvorschau: try druck())
        XCTAssertFalse(alt.lagerEinkauf.contains { $0.position.einheit.hasPrefix("Spule ") })
        XCTAssertEqual(alt.kennzahlen.einkaufLagerSumme, bestand.summe)
        XCTAssertEqual(d.kennzahlen.einkaufLagerSumme ?? 0, (bestand.summe ?? 0) + 17, accuracy: 1e-9)
    }

    /// Strang „Rest Druck“: Filament je Material und Farbe (Testdatei `material_farbe`). PETG gelb fehlt ganz (eine
    /// Spule kaufen), PETG schwarz reicht aus der schwarzen Spule, PLA ohne Farbe aus dem PLA-Bestand; Text und CSV
    /// byteweise wie der Kernel.
    func testFarbenWieDerKernel() throws {
        let e = try XCTUnwrap(try Fixtures.expected()["material_farbe"])
        guard case .bom(let m) = try Fixtures.message("bom_material_farbe.frame"),
              case .druck(.vorschau(let v, _)) = try Fixtures.message("print_material_farbe.frame")
        else { return XCTFail("Testdateien material_farbe fehlen") }
        XCTAssertEqual(v.platten.map(\.klasse), ["petg/gelb", "petg/schwarz", "pla"])
        XCTAssertEqual(v.platten.map(\.farbe), ["gelb", "schwarz", nil])
        XCTAssertEqual(v.summe.material.first?.farben.map(\.farbe), ["gelb", "schwarz"])
        let d = MaterialDaten(bom: m.bom, bestand: m.bestand, druckvorschau: v)
        let projekt = e["projekt"]?.stringValue
        let stand = e["stand"]?.stringValue
        XCTAssertEqual(MaterialText.einkaufText(d, projekt: projekt, stand: stand), e["text"]?.stringValue)
        XCTAssertEqual(Data(MaterialText.einkaufCSV(d).utf8), Data(try XCTUnwrap(e["csv"]?.stringValue).utf8))
        XCTAssertEqual(d.filament.map(\.werkstoff),
                       try XCTUnwrap(e["filament"]?.arrayValue).compactMap { $0["werkstoff"]?.stringValue })
        XCTAssertEqual(d.filament.map(\.teile), try XCTUnwrap(e["filament"]?.arrayValue).compactMap { $0["teile"]?.intValue })
        let soll = try XCTUnwrap(e["filament_kauf"]?.arrayValue)
        let ist = d.lagerEinkauf.filter { $0.position.einheit.hasPrefix("Spule ") }.map(\.position)
        XCTAssertEqual(ist.map(\.benennung), soll.compactMap { $0["benennung"]?.stringValue })
        XCTAssertEqual(ist.map(\.hinweis), soll.map { $0["hinweis"]?.stringValue })
        XCTAssertEqual(euro(d.kennzahlen.einkaufSumme), euro(e["summe"]?.doubleValue))
        // Zeilen mit gleicher Material-id und Spulenzahl bleiben unterscheidbar (Abhaken, SwiftUI-Kennung)
        XCTAssertEqual(Set(d.einkauf.map(\.id)).count, d.einkauf.count)
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
