import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Feinschliff 2“, Punkt 4: Gewicht und Kosten der Druckteile aus dem Filament der Druckvorschau desselben
/// Laufs, gleich benannt („Filament 39,1 g (gedruckt, Bambu Studio) · Vollkörper 104,7 g“), Vollkörper bleibt sichtbar.
final class FilamentTests: XCTestCase {
    private func json(_ text: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(text.utf8))
    }

    private func daten(vorschauRun: Int) throws -> MaterialDaten {
        let zeilen = try json(#"""
            [{"pos": 1, "art": "druckteil", "benennung": "Lenksperre (Druck)", "material": "PETG", "anzahl": 2,
              "kg_je": 0.1047, "kg": 0.2094, "preis_je": 1.78, "preis": 3.56, "teile": ["R/Lenksperre 1", "R/Lenksperre 2"]},
             {"pos": 2, "art": "rohr", "stock_id": "rohr-alfer-12x1", "benennung": "ALFER-Rundrohr 12 × 1", "anzahl": 1,
              "kg": 0.1, "preis": 3.9, "teile": ["Rohr"]}]
            """#)
        let lines = (zeilen.arrayValue ?? []).enumerated().compactMap { BOMLine(json: $1, index: $0) }
        let bom = BillOfMaterials(
            run: 5, lines: lines, cuts: [], totals: BOMTotals(kg: 0.3094, preis: 7.46, positionen: 2, teile: 3))
        let v = Druckvorschau(json: try json("""
            {"run": \(vorschauRun), "stand": "slicer", "summe": {"platten": 1, "material": []},
             "teile": [{"gruppe": "g1", "name": "Lenksperre (Druck)", "teile": ["R/Lenksperre 1", "R/Lenksperre 2",
                        "R/Lenksperre 3", "R/Lenksperre 4"], "anzahl": 4, "material": "petg", "g": 156.4, "kosten": 2.66,
                        "stand": "slicer", "je_stueck": {"g": 39.1, "zeit_s": 5605}}],
             "platten": []}
            """))
        var d = MaterialDaten(bom: bom, druckvorschau: v)
        d.druckvorschauEinrechnen(v)
        return d
    }

    func testFilamentStattVollkoerper() throws {
        let d = try daten(vorschauRun: 5)
        let p = try XCTUnwrap(d.position(1))
        XCTAssertEqual(p.filament?.gramm ?? 0, 78.2, accuracy: 1e-9)
        XCTAssertEqual(p.filament?.kosten ?? 0, 1.33, accuracy: 1e-9)
        XCTAssertEqual(p.filament?.stand, .slicer)
        XCTAssertEqual(p.kg ?? 0, 0.0782, accuracy: 1e-9)
        XCTAssertEqual(p.preis ?? 0, 1.33, accuracy: 1e-9)
        XCTAssertEqual(p.vollkoerperKg ?? 0, 0.2094, accuracy: 1e-9)
        XCTAssertEqual(p.gewichtText, "Filament \(KevFormat.mass(grams: 78.2)) (gedruckt, Bambu Studio) · Vollkörper "
            + KevFormat.kg(0.2094))
        XCTAssertNil(d.position(2)?.filament, "Lagerteile bleiben")
        // Summen wie in der Stückliste: Gewicht und Kosten mit dem Filament
        XCTAssertEqual(d.kennzahlen.kg, 0.3094 - 0.2094 + 0.0782, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.preis ?? 0, 7.46 - 3.56 + 1.33, accuracy: 1e-9)
    }

    func testVorschauEinesAnderenLaufsZaehltNicht() throws {
        let d = try daten(vorschauRun: 4)
        XCTAssertNil(d.position(1)?.filament)
        XCTAssertEqual(d.position(1)?.kg ?? 0, 0.2094, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.kg, 0.3094, accuracy: 1e-9)
    }
}
