import XCTest
import simd
@testable import KevCADCore

/// Deutsche Zahlenformate der Oberfläche.
final class FormatTests: XCTestCase {
    func testNumbers() {
        XCTAssertEqual(KevFormat.number(12.5, digits: 1), "12,5")
        XCTAssertEqual(KevFormat.number(1234.5, digits: 1), "1.234,5")
        XCTAssertEqual(KevFormat.number(0.04, digits: 1), "0,0")
        XCTAssertEqual(KevFormat.number(-0.04, digits: 1), "0,0")
        XCTAssertEqual(KevFormat.number(-3.25, digits: 2), "-3,25")
        XCTAssertEqual(KevFormat.number(.nan, digits: 1), "–")
        XCTAssertEqual(KevFormat.integer(134_000), "134.000")
        XCTAssertEqual(KevFormat.integer(999), "999")
        XCTAssertEqual(KevFormat.count(1, one: "Teil", many: "Teile"), "1 Teil")
        XCTAssertEqual(KevFormat.count(12480, one: "Dreieck", many: "Dreiecke"), "12.480 Dreiecke")
    }

    func testLengths() {
        XCTAssertEqual(KevFormat.mm(12.5), "12,5 mm")
        XCTAssertEqual(KevFormat.mm(17, digits: 3), "17,000 mm")
        XCTAssertEqual(KevFormat.mm(1500), "1.500,0 mm")
        XCTAssertEqual(
            KevFormat.dimensions(min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 5)), "120,0 × 80,0 × 5,0 mm")
    }

    func testVolume() {
        XCTAssertEqual(KevFormat.volume(mm3: 850), "850,0 mm³")
        XCTAssertEqual(KevFormat.volume(mm3: 999.9), "999,9 mm³")
        XCTAssertEqual(KevFormat.volume(mm3: 1000), "1,00 cm³")
        XCTAssertEqual(KevFormat.volume(mm3: 4760), "4,76 cm³")
        XCTAssertEqual(KevFormat.volume(mm3: 47_600), "47,6 cm³")
        XCTAssertEqual(KevFormat.volume(mm3: 48_000_000), "48.000 cm³")
    }

    func testArea() {
        XCTAssertEqual(KevFormat.area(mm2: 200), "200,0 mm²")
        XCTAssertEqual(KevFormat.area(mm2: 9600), "9.600,0 mm²")
        XCTAssertEqual(KevFormat.area(mm2: 12_500), "125,0 cm²")
    }

    func testMass() {
        XCTAssertEqual(KevFormat.mass(grams: 7.25), "7,25 g")
        XCTAssertEqual(KevFormat.mass(grams: 128.56), "128,6 g")
        XCTAssertEqual(KevFormat.mass(grams: 1300), "1,30 kg")
        XCTAssertEqual(KevFormat.mass(grams: 24_480), "24,5 kg")
        XCTAssertEqual(KevFormat.mass(grams: 1_250_000), "1.250,0 kg")
    }

    func testDuration() {
        XCTAssertEqual(KevFormat.duration(ms: 85), "85 ms")
        XCTAssertEqual(KevFormat.duration(ms: 412), "0,4 s")
        XCTAssertEqual(KevFormat.duration(ms: 4234), "4,2 s")
        XCTAssertEqual(KevFormat.duration(ms: 12_500), "13 s")
        XCTAssertEqual(KevFormat.duration(ms: 65_000), "1 min 05 s")
        XCTAssertEqual(KevFormat.duration(ms: 59_700), "1 min 00 s")
        XCTAssertEqual(KevFormat.duration(ms: 3_725_000), "62 min 05 s")
    }

    func testAnglePercentPoint() {
        XCTAssertEqual(KevFormat.angle(90), "90,00°")
        XCTAssertEqual(KevFormat.angle(44.999), "45,00°")
        XCTAssertEqual(KevFormat.percent(0.4), "40 %")
        XCTAssertEqual(KevFormat.point(SIMD3(12, 4.5, 0)), "x 12,000 · y 4,500 · z 0,000 mm")
    }

    func testRecentDate() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Berlin")!
        let now = calendar.date(from: DateComponents(year: 2026, month: 10, day: 21, hour: 18, minute: 0))!
        let today = calendar.date(from: DateComponents(year: 2026, month: 10, day: 21, hour: 14, minute: 32))!
        let yesterday = calendar.date(from: DateComponents(year: 2026, month: 10, day: 20, hour: 9, minute: 10))!
        let monday = calendar.date(from: DateComponents(year: 2026, month: 10, day: 19, hour: 10, minute: 0))!
        let old = calendar.date(from: DateComponents(year: 2026, month: 10, day: 12, hour: 8, minute: 0))!
        XCTAssertEqual(KevFormat.recentDate(today, now: now, calendar: calendar), "Heute, 14:32")
        XCTAssertEqual(KevFormat.recentDate(yesterday, now: now, calendar: calendar), "Gestern, 09:10")
        XCTAssertEqual(KevFormat.recentDate(monday, now: now, calendar: calendar), "Montag, 10:00")
        XCTAssertEqual(KevFormat.recentDate(old, now: now, calendar: calendar), "12.10.2026")
    }

    func testAbbreviatedPath() {
        XCTAssertEqual(
            KevFormat.abbreviatedPath("/Users/kevin/Documents/Kev CAD/Wandhalter", home: "/Users/kevin"),
            "~/Documents/Kev CAD/Wandhalter")
        XCTAssertEqual(KevFormat.abbreviatedPath("/Users/kevin", home: "/Users/kevin/"), "~")
        XCTAssertEqual(KevFormat.abbreviatedPath("/Users/kevinx/a", home: "/Users/kevin"), "/Users/kevinx/a")
        XCTAssertEqual(KevFormat.abbreviatedPath("/Volumes/T7/a", home: "/Users/kevin"), "/Volumes/T7/a")
    }

    func testLabeledValuesOrderAndUnits() {
        let values = KevFormat.labeledValues([
            "dz": 12.5, "distance": 12.5, "zeta": 1, "parallel": 1, "area": 100.53, "radius": 3.2,
        ])
        XCTAssertEqual(values.map(\.label), ["Abstand", "Radius", "Fläche", "Δz", "Parallel", "zeta"])
        XCTAssertEqual(values.map(\.value), ["12,500 mm", "3,200 mm", "100,5 mm²", "12,500 mm", "ja", "1,000"])
        XCTAssertEqual(KevFormat.labeledValue(key: "mass", 1300).value, "1,30 kg")
        XCTAssertEqual(KevFormat.labeledValue(key: "angle", 90).value, "90,00°")
    }
}

/// Teilebaum aus den Pfaden der Teile.
final class PartTreeTests: XCTestCase {
    private func part(_ id: String, visible: Bool = true, triangles: Int = 10) -> PartNode {
        PartNode(id: id, color: SIMD4(1, 1, 1, 1), visible: visible, triangles: triangles)
    }

    func testBuildsHierarchyInShowOrder() {
        let tree = PartTree.build([
            part("Grundplatte"), part("Halter/Lasche"), part("Halter/Rohrschelle/Oberteil"),
            part("Halter/Rohrschelle/Unterteil", visible: false), part("Schrauben/M6 links"),
        ])
        XCTAssertEqual(tree.map(\.name), ["Grundplatte", "Halter", "Schrauben"])
        XCTAssertNil(tree[0].children)
        XCTAssertEqual(tree[0].part?.id, "Grundplatte")

        let halter = tree[1]
        XCTAssertTrue(halter.isGroup)
        XCTAssertNil(halter.part)
        XCTAssertEqual(halter.partCount, 3)
        XCTAssertEqual(halter.visibleCount, 2)
        XCTAssertEqual(halter.triangles, 30)
        XCTAssertEqual(halter.children?.map(\.id), ["Halter/Lasche", "Halter/Rohrschelle"])
        XCTAssertEqual(
            halter.partIDs, ["Halter/Lasche", "Halter/Rohrschelle/Oberteil", "Halter/Rohrschelle/Unterteil"])
        XCTAssertFalse(halter.allHidden)
        XCTAssertFalse(halter.allVisible)
    }

    func testNodeCanBePartAndGroup() {
        let tree = PartTree.build([part("Halter"), part("Halter/Lasche")])
        XCTAssertEqual(tree.count, 1)
        XCTAssertEqual(tree[0].part?.id, "Halter")
        XCTAssertEqual(tree[0].partIDs, ["Halter", "Halter/Lasche"])
    }

    func testFilterKeepsParentsOfMatches() {
        let tree = PartTree.build([part("Grundplatte"), part("Halter/Lasche"), part("Halter/Rohrschelle/Oberteil")])
        let filtered = PartTree.filter(tree, query: "ober")
        XCTAssertEqual(filtered.map(\.id), ["Halter"])
        XCTAssertEqual(filtered[0].children?.map(\.id), ["Halter/Rohrschelle"])
        XCTAssertEqual(PartTree.filter(tree, query: "halter").first?.children?.count, 2)
        XCTAssertEqual(PartTree.filter(tree, query: " ").count, 2)
        XCTAssertTrue(PartTree.filter(tree, query: "xyz").isEmpty)
    }

    func testRefsAndExpansion() {
        XCTAssertEqual(PartTree.partID(fromRef: "Halter/Lasche#f12"), "Halter/Lasche")
        XCTAssertEqual(PartTree.partID(fromRef: "Grundplatte"), "Grundplatte")
        XCTAssertEqual(
            PartTree.partIDs(fromRefs: ["A#f1", "A#e2", "B", "A"]), ["A", "B"])
        let tree = PartTree.build([part("A"), part("G/B"), part("G/C")])
        XCTAssertEqual(PartTree.expandToParts(["G", "A", "G/B"], in: tree), ["G/B", "G/C", "A"])
        XCTAssertEqual(PartTree.allIDs(tree), ["A", "G", "G/B", "G/C"])
    }
}
