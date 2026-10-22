import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Feinschliff 2“, Punkt 6: `druckvorschauEinrechnen` nimmt nur die Vorschau desselben Laufs, wie Filament und
/// Einkaufsliste; direkt nach einem neuen Lauf zeigten Übersicht und Einkaufsliste sonst kurz verschiedene Werte.
final class KleinkramFeinschliff2Tests: XCTestCase {
    func testDruckvorschauNurDesselbenLaufs() throws {
        let line = BOMLine(pos: 1, art: "druckteil", stockID: nil, benennung: "Halter (Druck)", material: "PETG",
                           masseText: "", anzahl: 2, kg: 0.1, preis: 1.7, teile: ["Halter 1", "Halter 2"])
        let bom = BillOfMaterials(run: 7, lines: [line], cuts: [],
                                  totals: BOMTotals(kg: 0.1, preis: 1.7, positionen: 1, teile: 2))
        let alt = Druckvorschau(json: try JSONDecoder().decode(JSONValue.self, from: Data(#"""
            {"run": 6, "stand": "slicer", "summe": {"platten": 2, "zeit_s": 3600, "zeit_mit_wechsel_s": 3720,
             "kosten": 9.99, "material": [{"material": "petg", "name": "PETG", "g": 333.0, "kosten": 5.0}]},
             "teile": [{"gruppe": "g1", "name": "Halter (Druck)", "teile": ["Halter 1", "Halter 2"], "anzahl": 2,
                        "material": "petg", "g": 333.0, "stand": "slicer"}], "platten": []}
            """#.utf8)))
        var d = MaterialDaten(bom: bom, druckvorschau: alt)
        let vorher = d.kennzahlen
        d.druckvorschauEinrechnen(alt)
        XCTAssertEqual(d.kennzahlen, vorher, "Vorschau von Lauf 6 zählt nicht für Lauf 7")
        XCTAssertNil(d.kennzahlen.druckZeitS)
        XCTAssertEqual(d.kennzahlen.druckGramm, 100, accuracy: 1e-9)
        XCTAssertEqual(d.filament.first?.gramm ?? 0, 100, accuracy: 1e-9, "Einkaufsliste: ebenfalls Stückliste")
        var neu = alt
        neu.run = 7
        var d2 = MaterialDaten(bom: bom, druckvorschau: neu)
        d2.druckvorschauEinrechnen(neu)
        XCTAssertEqual(d2.kennzahlen.druckGramm, 333, accuracy: 1e-9)
        XCTAssertEqual(d2.kennzahlen.druckPlatten, 2)
        XCTAssertEqual(d2.filament.first?.gramm ?? 0, 333, accuracy: 1e-9)
    }
}
