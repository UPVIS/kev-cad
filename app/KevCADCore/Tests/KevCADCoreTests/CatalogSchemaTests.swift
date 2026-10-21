import Foundation
import XCTest

@testable import KevCADCore

/// Formular und Suche des Lagerkatalogs, Formate der Stückliste.
final class CatalogSchemaTests: XCTestCase {
    func testFormats() {
        XCTAssertEqual(KevFormat.euro(26.956), "26,96 €")
        XCTAssertEqual(KevFormat.euro(1234.5), "1.234,50 €")
        XCTAssertEqual(KevFormat.kg(2.871), "2,87 kg")
        XCTAssertEqual(KevFormat.kg(0.248), "248,0 g")
        XCTAssertEqual(KevFormat.compact(33.7), "33,7")
        XCTAssertEqual(KevFormat.compact(2), "2")
        XCTAssertEqual(KevFormat.compact(6000), "6.000")
        XCTAssertEqual(KevFormat.compact(1.25), "1,25")
        XCTAssertEqual(KevFormat.length(882), "882 mm")
        XCTAssertEqual(KevFormat.length(33.75), "33,8 mm")
        XCTAssertEqual(KevFormat.gehrung([0, 0]), "–")
        XCTAssertEqual(KevFormat.gehrung([45, 45]), "45° / 45°")
        XCTAssertEqual(KevFormat.gehrung([0, 22.5]), "0° / 22,5°")
        XCTAssertEqual(KevFormat.gehrung([]), "–")
        XCTAssertEqual(KevFormat.input(33.7), "33,7")
        XCTAssertEqual(KevFormat.input(6000), "6000")
        XCTAssertEqual(KevFormat.parseNumber("33,7"), 33.7)
        XCTAssertEqual(KevFormat.parseNumber("33.7"), 33.7)
        XCTAssertEqual(KevFormat.parseNumber("1.234,5"), 1234.5)
        XCTAssertEqual(KevFormat.parseNumber(" 12 mm"), 12)
        XCTAssertEqual(KevFormat.parseNumber("14,50 €/m"), 14.5)
        XCTAssertNil(KevFormat.parseNumber("abc"))
        XCTAssertNil(KevFormat.parseNumber(""))
    }

    func testSchemaNamesAndIDs() {
        XCTAssertEqual(CatalogSchema.arten.count, 14)
        XCTAssertEqual(CatalogSchema.art("vierkantrohr").fields.map(\.key), ["a", "s", "r"])
        XCTAssertEqual(CatalogSchema.art("schraube").fields.map(\.kind), [.text, .text, .text])
        XCTAssertEqual(CatalogSchema.art("platte").priceUnit, .jeM2)
        XCTAssertEqual(CatalogSchema.art("mutter").priceUnit, .jeStueck)
        XCTAssertFalse(CatalogSchema.art("zukunft").isKnown)
        XCTAssertEqual(CatalogSchema.art("zukunft").title, "Zukunft")
        XCTAssertEqual(CatalogSchema.measureLabel("d", art: "rohr"), "Außendurchmesser d")
        XCTAssertEqual(CatalogSchema.measureLabel("raster", art: "nutprofil"), "Raster")
        XCTAssertEqual(CatalogSchema.measureValue(.number(33.7), key: "d", art: "rohr"), "33,7 mm")
        XCTAssertEqual(CatalogSchema.measureValue(.number(8), key: "nut", art: "nutprofil"), "8")
        XCTAssertEqual(CatalogSchema.measureValue(.string("M8-1.25"), key: "groesse", art: "schraube"), "M8-1.25")

        XCTAssertEqual(
            CatalogSchema.suggestedName(art: "vierkantrohr", masse: ["a": 40, "s": 3]), "Vierkantrohr 40 × 40 × 3")
        XCTAssertEqual(
            CatalogSchema.suggestedName(art: "rohr", masse: ["d": 33.7, "s": 2], materialGroup: "Edelstahl"),
            "Edelstahlrohr 33,7 × 2")
        XCTAssertEqual(
            CatalogSchema.suggestedName(art: "platte", masse: ["s": 18], materialName: "Multiplex Birke"),
            "Multiplex Birke 18 mm")
        XCTAssertEqual(
            CatalogSchema.suggestedName(
                art: "schraube", masse: ["typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8-1.25"]),
            "Zylinderschraube ISO 4762 M8")
        XCTAssertEqual(
            CatalogSchema.suggestedName(art: "nutprofil", masse: ["raster": 40, "nut": 8, "variante": "leicht"]),
            "Nutprofil 40 × 40 Nut 8 leicht")
        XCTAssertEqual(CatalogSchema.suggestedName(art: "rund", masse: ["d": 12]), "Rundstahl Ø 12")
        XCTAssertEqual(CatalogSchema.suggestedName(art: "rohr", masse: [:]), "Rohr")

        XCTAssertEqual(CatalogSchema.suggestedID(art: "vierkantrohr", masse: ["a": 40, "s": 3]), "vierkantrohr-40x40x3")
        XCTAssertEqual(
            CatalogSchema.suggestedID(art: "rohr", masse: ["d": 33.7, "s": 2], material: "edelstahl-1.4301"),
            "rohr-edelstahl-33.7x2")
        XCTAssertEqual(
            CatalogSchema.suggestedID(art: "platte", masse: ["s": 18], material: "multiplex-birke"),
            "platte-multiplex-birke-18")
        XCTAssertEqual(
            CatalogSchema.suggestedID(art: "schraube", masse: ["norm": "iso4762", "groesse": "M8-1.25"]),
            "schraube-iso4762-m8")
        XCTAssertEqual(CatalogSchema.suggestedID(art: "u_profil", masse: ["h": 80, "b": 45, "s": 6, "t": 8]),
                       "u-profil-80x45x6x8")
        XCTAssertEqual(CatalogSchema.slug("Eiche Größe 4,5 × 2!"), "eiche-groesse-4.5-x-2")
        XCTAssertTrue(CatalogSchema.isValidID("rohr-en10220-42.4x2.0"))
        XCTAssertFalse(CatalogSchema.isValidID("Rohr 42"))
        XCTAssertFalse(CatalogSchema.isValidID("-rohr"))
        XCTAssertEqual(CatalogSchema.normTitle("iso4762"), "ISO 4762")
        XCTAssertEqual(CatalogSchema.currentMonth(Date(timeIntervalSince1970: 1_792_540_800)), "2026-10")
    }

    func testItemDraftValidationAndJSON() throws {
        var d = CatalogItemDraft(art: "rohr")
        XCTAssertEqual(d.stangenlaenge, "6000")
        XCTAssertEqual(d.preisEinheit, .jeM)
        let empty = Set(d.validate().map(\.field))
        XCTAssertTrue(empty.isSuperset(of: ["id", "name", "masse.d", "masse.s", "material"]), "\(empty)")

        d.masse = ["d": "33,7", "s": "abc"]
        d.id = "Rohr 33"
        d.name = "Edelstahlrohr 33,7 × 2"
        d.material = "edelstahl-1.4301"
        d.preis = "14,50"
        d.preisStand = "Oktober"
        var issues = d.validate(materials: ["stahl-s235"])
        XCTAssertEqual(Set(issues.map(\.field)), ["id", "masse.s", "material", "preis_stand"], "\(issues)")

        d.masse["s"] = "20"
        issues = d.validate()
        XCTAssertTrue(issues.contains { $0.field == "masse.s" && $0.message.contains("zu groß") })

        d.masse["s"] = "2"
        d.id = "rohr-edelstahl-33.7x2"
        d.preisStand = "2026-10"
        d.preisQuelle = "Kevin"
        d.tags = "Rund, Edelstahl, "
        XCTAssertEqual(d.validate(materials: ["edelstahl-1.4301"]), [])
        let entry = d.entry()
        XCTAssertEqual(entry["id"]?.stringValue, "rohr-edelstahl-33.7x2")
        XCTAssertEqual(entry["art"]?.stringValue, "rohr")
        XCTAssertEqual(entry["masse"]?["d"]?.doubleValue, 33.7)
        XCTAssertEqual(entry["masse"]?["s"]?.doubleValue, 2)
        XCTAssertEqual(entry["stangenlaenge"]?.doubleValue, 6000)
        XCTAssertEqual(entry["preis"]?["je_m"]?.doubleValue, 14.5)
        XCTAssertEqual(entry["preis"]?["quelle"]?.stringValue, "Kevin")
        XCTAssertEqual(entry["tags"]?.stringList, ["rund", "edelstahl"])
        XCTAssertNil(entry["norm"], "leere Felder fehlen im JSON")
        XCTAssertNil(entry["kg_je_m"])
        XCTAssertNil(entry["platte"])
        let back = try JSONDecoder().decode(JSONValue.self, from: d.json())
        XCTAssertEqual(back, entry)
        XCTAssertEqual(d.suggestedID(), "rohr-edelstahl-33.7x2")
        XCTAssertEqual(d.suggestedName(materialName: "Edelstahl 1.4301", materialGroup: "Edelstahl"),
                       "Edelstahlrohr 33,7 × 2")
    }

    /// Bearbeiten eines vorhandenen Eintrags verliert keine unbekannten Felder.
    func testItemDraftRoundTripKeepsUnknownFields() throws {
        let original: JSONValue = [
            "id": "platte-multiplex-birke-18", "art": "platte", "name": "Multiplex Birke 18 mm",
            "masse": ["s": 18, "kante": "umleimer"], "material": "multiplex-birke", "platte": [2500, 1250],
            "preis": ["je_m2": 38.5, "quelle": "Holzhandel", "stand": "2026-09"], "lieferant": "Holz Meier",
            "status": "vorgeschlagen",
        ]
        let d = CatalogItemDraft(entry: original)
        XCTAssertEqual(d.masse["s"], "18")
        XCTAssertEqual(d.formatB, "2500")
        XCTAssertEqual(d.preisEinheit, .jeM2)
        XCTAssertEqual(d.preis, "38,5")
        XCTAssertEqual(d.stangenlaenge, "")
        XCTAssertEqual(d.validate(), [])
        // Was Kevin speichert, ist freigegeben; alles andere bleibt wie es war
        guard case .object(var expected) = original else { return XCTFail() }
        expected["status"] = "frei"
        XCTAssertEqual(d.entry(), .object(expected))

        var screw = CatalogItemDraft(entry: [
            "id": "schraube-iso4762-m8", "art": "schraube", "name": "Zylinderschraube ISO 4762 M8",
            "masse": ["typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8-1.25"], "material": "stahl-8.8",
            "preis": ["je_stueck": 0.32, "quelle": "Richtwert", "stand": "2026-10"],
        ])
        XCTAssertEqual(screw.validate(), [])
        XCTAssertEqual(screw.entry()["masse"]?["groesse"]?.stringValue, "M8-1.25")
        XCTAssertNil(screw.entry()["stangenlaenge"])
        screw.masse["groesse"] = " "
        XCTAssertEqual(screw.validate().map(\.field), ["masse.groesse"])

        var sheet = CatalogItemDraft(art: "platte")
        sheet.masse["s"] = "2"
        sheet.formatB = "2000"
        XCTAssertTrue(sheet.validate().contains { $0.field == "platte" })
    }

    func testMaterialDraft() throws {
        var m = CatalogMaterialDraft()
        XCTAssertEqual(Set(m.validate().map(\.field)), ["id", "name", "dichte"])
        m.name = "Eiche massiv"
        m.id = m.suggestedID()
        XCTAssertEqual(m.id, "eiche-massiv")
        m.gruppe = "Holz"
        m.dichte = "0,71"
        m.farbe = "a8743f"
        m.metallisch = "2"
        m.preisJeKg = "6,5"
        XCTAssertEqual(m.validate().map(\.field), ["metallisch"])
        m.metallisch = ""
        m.aliase = "Eiche, oak"
        XCTAssertEqual(m.validate(), [])
        XCTAssertNil(m.entry()["druckbar"])
        m.druckbar = true
        let e = m.entry()
        XCTAssertEqual(e["druckbar"]?.boolValue, true)
        XCTAssertEqual(e["status"]?.stringValue, "frei")
        XCTAssertEqual(e["farbe"]?.stringValue, "#A8743F")
        XCTAssertEqual(e["dichte"]?.doubleValue, 0.71)
        XCTAssertEqual(e["preis_je_kg"]?.doubleValue, 6.5)
        XCTAssertEqual(e["preis_stand"]?.stringValue, CatalogSchema.currentMonth())
        XCTAssertEqual(e["aliase"]?.stringList, ["eiche", "oak"])
        XCTAssertNil(e["metallisch"])
        XCTAssertEqual(CatalogMaterialDraft(entry: e).entry(), e)
        XCTAssertEqual(CatalogMaterialDraft.normalizedHex("#abc"), "#AABBCC")
        XCTAssertNil(CatalogMaterialDraft.normalizedHex("#12345"))
    }

    func testSearchAndSort() throws {
        let json: JSONValue = [
            "items": [
                ["id": "vierkantrohr-50x50x3", "art": "vierkantrohr", "name": "Vierkantrohr 50 × 50 × 3",
                 "masse": ["a": 50, "s": 3], "material": "stahl-s235"],
                ["id": "rohr-edelstahl-33.7x2", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2",
                 "masse": ["d": 33.7, "s": 2], "material": "edelstahl-1.4301", "tags": ["geländer"]],
                ["id": "vierkantrohr-40x40x3", "art": "vierkantrohr", "name": "Vierkantrohr 40 × 40 × 3",
                 "norm": "DIN EN 10219", "masse": ["a": 40, "s": 3], "material": "stahl-s235"],
                ["id": "neu-1", "art": "zukunft", "name": "Etwas Neues", "masse": [:], "material": "stahl-s235"],
            ],
            "materials": [
                ["id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#8A9099",
                 "aliase": ["baustahl"]],
                ["id": "edelstahl-1.4301", "name": "Edelstahl 1.4301", "gruppe": "Edelstahl", "dichte": 7.9,
                 "farbe": "#B4B8BC"],
            ],
        ]
        let cat = Catalog(json: json)
        func find(_ q: String) -> [String] {
            let t = CatalogSearch.tokens(q)
            return CatalogSearch.sorted(cat.items).filter {
                CatalogSearch.matches($0, tokens: t, material: cat.material($0.material))
            }.map(\.id)
        }
        XCTAssertEqual(find(""), ["rohr-edelstahl-33.7x2", "vierkantrohr-40x40x3", "vierkantrohr-50x50x3", "neu-1"])
        XCTAssertEqual(find("vierkantrohr 40"), ["vierkantrohr-40x40x3"])
        XCTAssertEqual(find("40x40"), ["vierkantrohr-40x40x3"])
        XCTAssertEqual(find("33.7"), ["rohr-edelstahl-33.7x2"])
        XCTAssertEqual(find("33,7 edelstahl"), ["rohr-edelstahl-33.7x2"])
        XCTAssertEqual(find("GELANDER"), ["rohr-edelstahl-33.7x2"], "Umlaute und Groß-/Kleinschreibung egal")
        XCTAssertEqual(find("en 10219"), ["vierkantrohr-40x40x3"])
        XCTAssertEqual(find("Vierkantrohre"), ["vierkantrohr-40x40x3", "vierkantrohr-50x50x3"], "Mehrzahl der Art")
        XCTAssertEqual(find("s235"), ["vierkantrohr-40x40x3", "vierkantrohr-50x50x3", "neu-1"])
        XCTAssertEqual(find("a50"), ["vierkantrohr-50x50x3"])
        XCTAssertTrue(CatalogSearch.matches(cat.materials[0], tokens: CatalogSearch.tokens("baustahl")))
        XCTAssertFalse(CatalogSearch.matches(cat.materials[1], tokens: CatalogSearch.tokens("baustahl")))
    }
}
