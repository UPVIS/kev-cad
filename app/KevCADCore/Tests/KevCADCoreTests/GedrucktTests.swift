import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Feinschliff 2“, Punkt 7: schon gedruckte Druckteile (`lager.druckteil(…, gedruckt=True)`) tragen das
/// Kennzeichen „gedruckt“, brauchen kein Filament und stehen in der Druckvorschau als „gedruckt, vorhanden“.
final class GedrucktTests: XCTestCase {
    private func json(_ text: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(text.utf8))
    }

    func testStuecklisteUndMaterial() throws {
        let zeilen = try json(#"""
            [{"pos": 1, "art": "druckteil", "benennung": "Fangrolle (Druck)", "material": "PETG", "anzahl": 1,
              "kg": 0.06, "preis": 1.02, "teile": ["Kugelschieber/Fangrolle (Druck)"], "gedruckt": true},
             {"pos": 2, "art": "druckteil", "benennung": "Halter (Druck)", "material": "PETG", "anzahl": 2,
              "kg": 0.02, "preis": 0.34, "teile": ["Halter 1", "Halter 2"]}]
            """#)
        let lines = (zeilen.arrayValue ?? []).enumerated().compactMap { BOMLine(json: $1, index: $0) }
        XCTAssertEqual(lines.map(\.gedruckt), [true, false])
        let bom = BillOfMaterials(run: 3, lines: lines, cuts: [], totals: BOMTotals(kg: 0.1, preis: 1.36, positionen: 2, teile: 3))
        let d = MaterialDaten(bom: bom)
        XCTAssertEqual(d.position(1)?.kennzeichen, [.druckteil, .gedruckt])
        XCTAssertEqual(d.position(2)?.kennzeichen, [.druckteil])
        XCTAssertEqual(d.filament.map(\.teile), [2], "nur zu druckende Teile brauchen Filament")
        XCTAssertEqual(d.filament.first?.gramm ?? 0, 20, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.gedruckt, 1)
        XCTAssertEqual(d.kennzahlen.druckteile, 3)
        XCTAssertEqual(d.kennzahlen.druckGramm, 20, accuracy: 1e-9)
    }

    func testDruckvorschauMitGedrucktenTeilen() throws {
        let v = Druckvorschau(json: try json(#"""
            {"run": 4, "stand": "schaetzung", "teile": [], "platten": [], "summe": {},
             "gedruckt": [{"name": "Kugelschieber/Fangrolle (Druck)", "material": "petg", "form": "geaendert",
                           "unterschiede": ["Volumen +3,0 %"]},
                          {"name": "Kugelschieber/Fängerschlitten links (Druck)", "form": "gleich"}]}
            """#))
        XCTAssertTrue(v.istLeer)
        XCTAssertEqual(v.gedruckt.map(\.form), ["geaendert", "gleich"])
        XCTAssertEqual(v.gedruckt.filter(\.geaendert).first?.unterschiede, ["Volumen +3,0 %"])
        XCTAssertEqual(Druckvorschau(json: try json(#"{"run": 1}"#)).gedruckt, [])
    }
}
