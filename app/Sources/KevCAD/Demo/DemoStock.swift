import Foundation
import KevCADCore
import simd

// Phase 2 im Demomodus: Gestell 800 × 600 × 900 aus Vierkantrohr 40 × 40 × 3 mit Multiplexplatte und M8-Schrauben
// (PLAN-PHASE2.md), seine Stückliste mit Zuschnitt und ein kleiner Lagerkatalog mit allen drei Ebenen.

/// Welches Beispielprojekt der Demomodus zeigt.
enum DemoScenario {
    case wandhalter, gestell

    static func forFolder(_ url: URL) -> DemoScenario {
        url.lastPathComponent.lowercased().hasPrefix("gestell") ? .gestell : .wandhalter
    }

    var folder: URL {
        switch self {
        case .wandhalter: return DemoData.projectFolder
        case .gestell: return DemoData.gestellFolder
        }
    }

    var specs: [DemoData.Spec] { self == .gestell ? DemoData.gestellSpecs : DemoData.specs }
    var steps: [DemoData.Step] { self == .gestell ? DemoData.gestellSteps : DemoData.steps }
    var warnings: [String] { self == .gestell ? [] : DemoData.warnings }
}

extension DemoData {
    static var gestellFolder: URL { AppInfo.projectsDirectory.appendingPathComponent("Gestell", isDirectory: true) }

    static func density(_ material: String?) -> Double {
        switch material {
        case "aluminium": return 2.70
        case "stahl", "stahl-s235", "stahl-8.8-verzinkt": return 7.85
        case "multiplex-birke": return 0.68
        case "petg-schwarz": return 1.27
        default: return 0
        }
    }

    // MARK: Gestell

    static let rohrID = "vierkantrohr-en10219-40x40x3"
    static let rohrName = "Vierkantrohr 40 × 40 × 3"
    static let rohrKgJeM = 3.41
    static let rohrPreisJeM = 8.0

    private static func round(_ v: Double, _ digits: Int) -> Double {
        let f = pow(10, Double(digits))
        return (v * f).rounded() / f
    }

    private static func tube(
        _ id: String, _ lo: SIMD3<Float>, _ hi: SIMD3<Float>, length: Double, miter: [Double] = [0, 0]
    ) -> Spec {
        // Hohlprofil: Außenfläche minus Innenfläche (34 × 34) mal Länge
        let volume = (40.0 * 40 - 34 * 34) * length
        return Spec(
            id: id, color: 0x8A9099, material: "stahl-s235", min: lo, max: hi, volume: volume, triangles: 96,
            faces: 10, edges: 24, shape: [.box(min: lo, max: hi)],
            stock: StockInfo(
                id: rohrID, name: rohrName, laenge: length, gehrung: miter, material: "stahl-s235",
                kg: round(length / 1000 * rohrKgJeM, 3), preis: round(length / 1000 * rohrPreisJeM, 2)))
    }

    /// Teile des Gestells. Unterkante der Fußplatten bei z = 0, Oberkante Deckel bei z = 900.
    static let gestellSpecs: [Spec] = {
        var specs: [Spec] = []
        let legX: [Float] = [-400, 360], legY: [Float] = [-300, 260]
        let legNames = [("vorn links", 0, 0), ("vorn rechts", 1, 0), ("hinten links", 0, 1), ("hinten rechts", 1, 1)]
        for (name, ix, iy) in legNames {
            let x = legX[ix], y = legY[iy]
            specs.append(tube("Gestell/Bein \(name)", SIMD3(x, y, 5), SIMD3(x + 40, y + 40, 842), length: 837))
        }
        specs.append(tube("Gestell/Zarge vorn", SIMD3(-400, -300, 842), SIMD3(400, -260, 882), length: 800,
                          miter: [45, 45]))
        specs.append(tube("Gestell/Zarge hinten", SIMD3(-400, 260, 842), SIMD3(400, 300, 882), length: 800,
                          miter: [45, 45]))
        specs.append(tube("Gestell/Zarge links", SIMD3(-400, -300, 842), SIMD3(-360, 300, 882), length: 600,
                          miter: [45, 45]))
        specs.append(tube("Gestell/Zarge rechts", SIMD3(360, -300, 842), SIMD3(400, 300, 882), length: 600,
                          miter: [45, 45]))
        specs.append(tube("Gestell/Riegel vorn", SIMD3(-360, -300, 150), SIMD3(360, -260, 190), length: 720))
        specs.append(tube("Gestell/Riegel hinten", SIMD3(-360, 260, 150), SIMD3(360, 300, 190), length: 720))
        specs.append(tube("Gestell/Riegel links", SIMD3(-400, -260, 150), SIMD3(-360, 260, 190), length: 520))
        specs.append(tube("Gestell/Riegel rechts", SIMD3(360, -260, 150), SIMD3(400, 260, 190), length: 520))

        // Deckel aus Multiplex Birke 18 mm
        specs.append(Spec(
            id: "Deckel", color: 0xD9B98C, material: "multiplex-birke", min: SIMD3(-400, -300, 882),
            max: SIMD3(400, 300, 900), volume: 800 * 600 * 18, triangles: 12, faces: 6, edges: 12,
            shape: [.box(min: SIMD3(-400, -300, 882), max: SIMD3(400, 300, 900))],
            stock: StockInfo(
                id: "platte-multiplex-birke-18", name: "Multiplex Birke 18 mm", laenge: nil, gehrung: [0, 0],
                material: "multiplex-birke", kg: 5.875, preis: 21.6)))

        // Acht Zylinderschrauben M8 × 60 durch den Deckel in die Zarge
        let screwXY: [(Float, Float)] = [
            (-250, -280), (250, -280), (-250, 280), (250, 280), (-380, -150), (-380, 150), (380, -150), (380, 150),
        ]
        for (i, p) in screwXY.enumerated() {
            let c = SIMD3<Float>(p.0, p.1, 0)
            specs.append(Spec(
                id: "Schrauben/M8x60 \(i + 1)", color: 0xB5BAC0, material: "stahl-8.8-verzinkt",
                min: SIMD3(p.0 - 6.5, p.1 - 6.5, 848), max: SIMD3(p.0 + 6.5, p.1 + 6.5, 908), volume: 3950,
                triangles: 236, faces: 9, edges: 18,
                shape: [
                    .cylinder(axis: 2, center: c, radius: 4, from: 848, to: 900),
                    .cylinder(axis: 2, center: c, radius: 6.5, from: 900, to: 908),
                ],
                stock: StockInfo(
                    id: "schraube-iso4762-m8", name: "Zylinderschraube ISO 4762 M8", laenge: 60, gehrung: [0, 0],
                    material: "stahl-8.8-verzinkt", kg: 0.031, preis: 0.32)))
        }

        // Gleitfüße: 3D-Druckteile aus PETG (Inventar-Regel: gekennzeichnetes Druckteil, Kosten aus dem Filamentpreis)
        for (name, ix, iy) in legNames {
            let x = legX[ix] - 5, y = legY[iy] - 5
            specs.append(Spec(
                id: "Füße/Gleitfuß \(name)", color: 0x34373B, material: "petg-schwarz", min: SIMD3(x, y, 0),
                max: SIMD3(x + 50, y + 50, 5), volume: 50 * 50 * 5 - 34 * 34 * 3, triangles: 220, faces: 14,
                edges: 36, shape: [.box(min: SIMD3(x, y, 0), max: SIMD3(x + 50, y + 50, 5))]))
        }
        return specs
    }()

    /// Frei modelliertes Teil ohne Lagerteil: verletzt die Inventar-Regel (Demozustand `inventar`).
    static let violationSpec = Spec(
        id: "Halter Steckdosenleiste", color: 0xC9CDD2, material: "aluminium-6060", min: SIMD3(400, -110, 690),
        max: SIMD3(404, 110, 842), volume: 4 * 220 * 152, triangles: 12, faces: 6, edges: 12,
        shape: [.box(min: SIMD3(400, -110, 690), max: SIMD3(404, 110, 842))])

    static let gestellSteps: [Step] = {
        let s = gestellSpecs
        func pick(_ prefix: String) -> [Spec] { s.filter { $0.id.hasPrefix(prefix) } }
        return [
            Step(title: "Lagerteile suchen", parts: []),
            Step(title: "Beine", parts: pick("Gestell/Bein")),
            Step(title: "Zarge mit Gehrung", parts: pick("Gestell/Zarge")),
            Step(title: "Riegel unten", parts: pick("Gestell/Riegel")),
            Step(title: "Deckel", parts: pick("Deckel")),
            Step(title: "Schrauben", parts: pick("Schrauben/")),
            Step(title: "Gleitfüße (3D-Druck)", parts: pick("Füße/")),
        ]
    }()

    // MARK: Stückliste

    /// Stückliste wie vom Kernel (P5, P6): gleiche Lagerteile mit gleicher Länge und Gehrung zusammengefasst,
    /// Eigenteile mit Masse aus Volumen × Dichte, Zuschnitt First-Fit-Decreasing mit 3 mm Sägeschnitt.
    static func bom(for parts: [PartNode], run: Int, catalog: Catalog, inventoryRule: Bool = false) -> BillOfMaterials {
        struct Group {
            var key: String
            var parts: [PartNode]
        }
        var groups: [Group] = []
        func add(_ key: String, _ part: PartNode) {
            if let i = groups.firstIndex(where: { $0.key == key }) {
                groups[i].parts.append(part)
            } else {
                groups.append(Group(key: key, parts: [part]))
            }
        }
        var violations: [String] = []
        for part in parts {
            if let s = part.stock {
                add("L|\(s.id)|\(s.laenge ?? -1)|\(s.gehrung)", part)
            } else if inventoryRule && catalog.material(part.material ?? "")?.druckbar != true {
                violations.append(part.id)
            } else if part.material != nil {
                // Eigenteile: gleiche Form (Volumen, Hüllmaße) und gleiche Baugruppe zusammenfassen
                let size = part.bboxMax - part.bboxMin
                let dims = [size.x, size.y, size.z].map { String(Int($0.rounded())) }.joined(separator: "x")
                add("E|\(part.material ?? "")|\(Int(part.volume ?? 0))|\(dims)|\(part.path.dropLast().joined(separator: "/"))",
                    part)
            }
        }
        func materialName(_ id: String?) -> String? {
            guard let id else { return nil }
            return catalog.material(id)?.name ?? (id == "stahl" ? "Stahl" : id.capitalized)
        }
        var stockLines: [(order: (Int, Double), line: BOMLine)] = []
        var ownLines: [BOMLine] = []
        var warnings: [String] = []
        for g in groups {
            let first = g.parts[0]
            let n = g.parts.count
            if let s = first.stock {
                let item = catalog.item(s.id)
                let art = item?.art ?? "rohr"
                var masse = s.laenge.map(KevFormat.length) ?? ""
                if art == "platte" {
                    let size = first.bboxMax - first.bboxMin
                    masse = "\(KevFormat.compact(Double(size.x))) × \(KevFormat.compact(Double(size.y))) mm"
                } else if ["schraube", "mutter", "scheibe"].contains(art) {
                    let size = item?.entry["masse"]?["groesse"]?.stringValue?.split(separator: "-").first.map(String.init)
                    masse = [size, s.laenge.map { KevFormat.compact($0) }].compactMap { $0 }.joined(separator: " × ")
                }
                let line = BOMLine(
                    pos: 0, art: art, stockID: s.id, benennung: item?.name ?? s.name, norm: item?.norm,
                    material: materialName(s.material), laenge: art == "platte" ? nil : s.laenge, gehrung: s.gehrung,
                    masseText: masse, anzahl: n, kgJe: s.kg, kg: s.kg.map { round($0 * Double(n), 3) },
                    preisJe: s.preis, preis: s.preis.map { round($0 * Double(n), 2) }, teile: g.parts.map(\.id))
                stockLines.append(((CatalogSchema.order(of: art), -(s.laenge ?? 0)), line))
            } else {
                let kgJe = (first.mass ?? 0) / 1000
                let printed = catalog.material(first.material ?? "")?.druckbar == true
                let perKg = catalog.material(first.material ?? "")?.preisJeKg
                    ?? (first.material == "aluminium" ? 7.5 : 2.4)
                let size = first.bboxMax - first.bboxMin
                let dims = [size.x, size.y, size.z].map { KevFormat.compact(Double($0)) }.joined(separator: " × ")
                var name = first.name
                if n > 1 {
                    let prefix = g.parts.map(\.name).reduce(first.name) { String($0.commonPrefix(with: $1)) }
                        .trimmingCharacters(in: .whitespaces)
                    let parent: String? = first.path.count > 1 ? first.path[first.path.count - 2] : nil
                    name = prefix.count >= 3 ? prefix : (parent ?? first.name)
                }
                ownLines.append(BOMLine(
                    pos: 0, art: printed ? "druckteil" : "eigenteil", stockID: nil, benennung: name,
                    material: materialName(first.material), masseText: "\(dims) mm", anzahl: n, kgJe: round(kgJe, 3),
                    kg: round(kgJe * Double(n), 3), preisJe: round(kgJe * perKg, 2),
                    preis: round(kgJe * perKg * Double(n), 2), teile: g.parts.map(\.id), eigenteil: !printed))
                if !printed { warnings.append("\(name): kein Lagerteil, Masse aus Volumen × Dichte") }
            }
        }
        for v in violations { warnings.append("\(v): nicht aus dem Inventar, fehlt in der Stückliste") }
        var lines = stockLines.sorted { $0.order < $1.order }.map(\.line) + ownLines
        for i in lines.indices { lines[i].pos = i + 1 }

        // Zuschnitt je Stangenware
        var cuts: [CutPlan] = []
        var barIDs: [String] = []
        for line in lines where line.laenge != nil && ["rohr", "vierkantrohr", "rechteckrohr", "flach", "rund",
                                                          "vierkant", "winkel", "u_profil", "nutprofil", "holz"]
            .contains(line.art) {
            if let id = line.stockID, !barIDs.contains(id) { barIDs.append(id) }
        }
        for id in barIDs {
            let pieces = lines.filter { $0.stockID == id }.flatMap { l in Array(repeating: l.laenge ?? 0, count: l.anzahl) }
            let bar = catalog.item(id)?.entry["stangenlaenge"]?.doubleValue ?? 6000
            let kerf = 3.0
            var bars: [[Double]] = []
            var free: [Double] = []
            for p in pieces.sorted(by: >) {
                if let i = free.firstIndex(where: { $0 >= p }) {
                    bars[i].append(p)
                    free[i] -= p + kerf
                } else {
                    bars.append([p])
                    free.append(bar - p - kerf)
                }
            }
            cuts.append(CutPlan(
                stockID: id, benennung: catalog.item(id)?.name ?? id, stangenlaenge: bar, saegeschnitt: kerf,
                stangen: bars, verschnittProzent: round(CutPlan.wastePercent(stangen: bars, stangenlaenge: bar), 1)))
        }
        let kg = round(lines.compactMap(\.kg).reduce(0, +), 2)
        let preis = round(lines.compactMap(\.preis).reduce(0, +), 2)
        return BillOfMaterials(
            run: run, lines: lines, cuts: cuts,
            totals: BOMTotals(
                kg: kg, preis: preis, positionen: lines.count, teile: lines.reduce(0) { $0 + $1.anzahl },
                preisHinweis: "Richtpreise, Stand 2026-10"),
            warnings: warnings)
    }

    // MARK: Lagerkatalog

    /// Der Katalog der Demo, fertig gelesen (für Anzeigenamen).
    static let demoCatalog = Catalog(json: catalogJSON)

    /// Kleiner Katalog: mehrere Arten, alle drei Ebenen (mitgeliefert, eigener Katalog, Projekt).
    static let catalogJSON: JSONValue = {
        func preis(_ unit: String, _ v: Double, _ quelle: String = "Richtwert Stahlhandel") -> JSONValue {
            [unit: .number(v), "quelle": .string(quelle), "stand": "2026-10"]
        }
        let materials: [JSONValue] = [
            ["id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#8A9099",
             "metallisch": 0.8, "rauheit": 0.45, "preis_je_kg": 2.4, "preis_quelle": "Richtwert Stahlhandel",
             "preis_stand": "2026-10", "aliase": ["stahl", "baustahl", "s235jr", "steel"], "ebene": "mitgeliefert"],
            ["id": "stahl-8.8-verzinkt", "name": "Stahl 8.8 verzinkt", "gruppe": "Stahl", "dichte": 7.85,
             "farbe": "#B5BAC0", "metallisch": 0.9, "rauheit": 0.35, "aliase": ["8.8", "verzinkt"],
             "ebene": "mitgeliefert"],
            ["id": "edelstahl-1.4301", "name": "Edelstahl 1.4301", "gruppe": "Edelstahl", "dichte": 7.9,
             "farbe": "#B4B8BC", "metallisch": 0.9, "rauheit": 0.3, "preis_je_kg": 6.8,
             "preis_quelle": "Richtwert Edelstahlhandel", "preis_stand": "2026-10", "aliase": ["v2a", "a2", "inox"],
             "ebene": "mitgeliefert"],
            ["id": "aluminium-6060", "name": "Aluminium EN AW-6060", "gruppe": "Aluminium", "dichte": 2.7,
             "farbe": "#C9CDD2", "metallisch": 0.85, "rauheit": 0.4, "preis_je_kg": 7.5, "preis_quelle": "Richtwert",
             "preis_stand": "2026-10", "aliase": ["aluminium", "alu"], "ebene": "mitgeliefert"],
            ["id": "multiplex-birke", "name": "Multiplex Birke", "gruppe": "Holzwerkstoff", "dichte": 0.68,
             "farbe": "#D9B98C", "metallisch": 0, "rauheit": 0.7, "preis_je_kg": 3.7, "preis_quelle": "Richtwert Holzhandel",
             "preis_stand": "2026-10", "aliase": ["multiplex", "birke"], "ebene": "mitgeliefert"],
            ["id": "fichte-kvh", "name": "Fichte KVH", "gruppe": "Holz", "dichte": 0.47, "farbe": "#E2C48E",
             "preis_je_kg": 1.3, "preis_quelle": "Richtwert Holzhandel", "preis_stand": "2026-10",
             "aliase": ["fichte", "kvh"], "ebene": "mitgeliefert"],
            ["id": "petg-schwarz", "name": "PETG schwarz", "gruppe": "Kunststoff", "dichte": 1.27, "farbe": "#34373B",
             "rauheit": 0.5, "druckbar": true, "preis_je_kg": 24, "preis_quelle": "Filament, Rolle 1 kg",
             "preis_stand": "2026-10", "aliase": ["petg"], "ebene": "eigen", "status": "frei"],
            ["id": "pla-grau", "name": "PLA grau", "gruppe": "Kunststoff", "dichte": 1.24, "farbe": "#8E9196",
             "druckbar": true, "preis_je_kg": 20, "preis_quelle": "Claude: Richtwert Onlinehandel",
             "preis_stand": "2026-10", "aliase": ["pla"], "ebene": "eigen", "status": "vorgeschlagen"],
            ["id": "eiche-massiv", "name": "Eiche massiv", "gruppe": "Holz", "dichte": 0.71, "farbe": "#A8743F",
             "rauheit": 0.6, "preis_je_kg": 6.5, "preis_quelle": "Kevin, Sägewerk", "preis_stand": "2026-09",
             "aliase": ["eiche", "oak"], "ebene": "eigen"],
        ]
        let steel = "stahl-s235"
        let items: [JSONValue] = [
            ["id": "rohr-en10220-21.3x2.0", "art": "rohr", "name": "Rohr 21,3 × 2,0", "norm": "DIN EN 10220",
             "masse": ["d": 21.3, "s": 2.0], "material": .string(steel), "kg_je_m": 0.952, "stangenlaenge": 6000,
             "preis": preis("je_m", 3.2), "tags": ["rund", "gewinderohr"], "ebene": "mitgeliefert"],
            ["id": "rohr-en10220-33.7x2.6", "art": "rohr", "name": "Rohr 33,7 × 2,6", "norm": "DIN EN 10220",
             "masse": ["d": 33.7, "s": 2.6], "material": .string(steel), "kg_je_m": 1.99, "stangenlaenge": 6000,
             "preis": preis("je_m", 5.4), "tags": ["rund"], "ebene": "mitgeliefert"],
            ["id": "rohr-en10220-42.4x2.0", "art": "rohr", "name": "Rohr 42,4 × 2,0", "norm": "DIN EN 10220",
             "masse": ["d": 42.4, "s": 2.0], "material": .string(steel), "kg_je_m": 1.99, "stangenlaenge": 6000,
             "preis": preis("je_m", 4.8), "tags": ["rund", "gewinderohr"], "ebene": "mitgeliefert"],
            ["id": "rohr-edelstahl-33.7x2", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2", "norm": "ISO 1127",
             "masse": ["d": 33.7, "s": 2.0], "material": "edelstahl-1.4301", "kg_je_m": 1.58, "stangenlaenge": 6000,
             "preis": preis("je_m", 14.5, "Kevin"), "tags": ["geländer", "edelstahl"], "ebene": "eigen"],
            ["id": "vierkantrohr-en10219-30x30x2", "art": "vierkantrohr", "name": "Vierkantrohr 30 × 30 × 2",
             "norm": "DIN EN 10219", "masse": ["a": 30, "s": 2], "material": .string(steel), "kg_je_m": 1.68,
             "stangenlaenge": 6000, "preis": preis("je_m", 4.2), "tags": ["quadrat"], "ebene": "mitgeliefert"],
            ["id": .string(rohrID), "art": "vierkantrohr", "name": .string(rohrName), "norm": "DIN EN 10219",
             "masse": ["a": 40, "s": 3], "material": .string(steel), "kg_je_m": .number(rohrKgJeM),
             "stangenlaenge": 6000, "preis": preis("je_m", rohrPreisJeM), "tags": ["quadrat"], "ebene": "mitgeliefert"],
            ["id": "vierkantrohr-en10219-50x50x3", "art": "vierkantrohr", "name": "Vierkantrohr 50 × 50 × 3",
             "norm": "DIN EN 10219", "masse": ["a": 50, "s": 3], "material": .string(steel), "kg_je_m": 4.35,
             "stangenlaenge": 6000, "preis": preis("je_m", 10.2), "tags": ["quadrat"], "ebene": "mitgeliefert"],
            ["id": "rechteckrohr-en10219-60x40x3", "art": "rechteckrohr", "name": "Rechteckrohr 60 × 40 × 3",
             "norm": "DIN EN 10219", "masse": ["b": 60, "h": 40, "s": 3], "material": .string(steel), "kg_je_m": 4.35,
             "stangenlaenge": 6000, "preis": preis("je_m", 10.4), "ebene": "mitgeliefert"],
            ["id": "flach-en10058-40x5", "art": "flach", "name": "Flachstahl 40 × 5", "norm": "DIN EN 10058",
             "masse": ["b": 40, "s": 5], "material": .string(steel), "kg_je_m": 1.57, "stangenlaenge": 6000,
             "preis": preis("je_m", 2.9), "ebene": "mitgeliefert"],
            ["id": "winkel-alu-30x30x3", "art": "winkel", "name": "Alu-Winkel 30 × 30 × 3", "norm": "EN 755-9",
             "masse": ["a": 30, "b": 30, "s": 3], "material": "aluminium-6060", "kg_je_m": 0.47, "stangenlaenge": 3000,
             "preis": preis("je_m", 6.9, "Claude: Richtwert Onlinehandel"), "tags": ["halter", "alu"],
             "ebene": "eigen", "status": "vorgeschlagen"],
            ["id": "rund-en10060-12", "art": "rund", "name": "Rundstahl Ø 12", "norm": "DIN EN 10060",
             "masse": ["d": 12], "material": .string(steel), "kg_je_m": 0.888, "stangenlaenge": 6000,
             "preis": preis("je_m", 1.9), "ebene": "mitgeliefert"],
            ["id": "winkel-en10056-40x40x4", "art": "winkel", "name": "Winkel 40 × 40 × 4", "norm": "DIN EN 10056",
             "masse": ["a": 40, "b": 40, "s": 4], "material": .string(steel), "kg_je_m": 2.42, "stangenlaenge": 6000,
             "preis": preis("je_m", 4.6), "ebene": "mitgeliefert"],
            ["id": "nutprofil-40x40-n8-leicht", "art": "nutprofil", "name": "Nutprofil 40 × 40 Nut 8 leicht",
             "norm": "Raster 40 Nut 8, item-ähnlich", "masse": ["raster": 40, "nut": 8, "variante": "leicht"],
             "material": "aluminium-6060", "kg_je_m": 1.45, "stangenlaenge": 6000,
             "preis": preis("je_m", 9.9, "Richtwert Profilhandel"), "tags": ["alu", "systemprofil"],
             "ebene": "mitgeliefert"],
            ["id": "holz-kvh-60x80", "art": "holz", "name": "Kantholz 60 × 80", "norm": "KVH Fichte",
             "masse": ["b": 60, "h": 80], "material": "fichte-kvh", "stangenlaenge": 5000,
             "preis": preis("je_m", 3.1, "Richtwert Holzhandel"), "ebene": "mitgeliefert"],
            ["id": "holz-eiche-40x40", "art": "holz", "name": "Eiche Kantel 40 × 40", "masse": ["b": 40, "h": 40],
             "material": "eiche-massiv", "stangenlaenge": 2000, "preis": preis("je_m", 7.8, "Kevin, Sägewerk"),
             "tags": ["möbel"], "ebene": "eigen"],
            ["id": "platte-multiplex-birke-18", "art": "platte", "name": "Multiplex Birke 18 mm", "masse": ["s": 18],
             "material": "multiplex-birke", "platte": [2500, 1250], "preis": preis("je_m2", 45, "Richtwert Holzhandel"),
             "tags": ["holz", "deckel"], "ebene": "mitgeliefert"],
            ["id": "platte-blech-s235-2", "art": "platte", "name": "Stahlblech 2 mm", "norm": "DIN EN 10051",
             "masse": ["s": 2], "material": .string(steel), "platte": [2000, 1000], "preis": preis("je_m2", 22),
             "ebene": "mitgeliefert"],
            ["id": "platte-siebdruck-21", "art": "platte", "name": "Siebdruckplatte 21 mm", "masse": ["s": 21],
             "material": "multiplex-birke", "platte": [2500, 1250], "preis": preis("je_m2", 39, "Angebot Holz Meier"),
             "tags": ["werkbank"], "ebene": "projekt"],
            ["id": "schraube-iso4762-m8", "art": "schraube", "name": "Zylinderschraube ISO 4762 M8", "norm": "ISO 4762",
             "masse": ["typ": "SocketHeadCapScrew", "norm": "iso4762", "groesse": "M8-1.25"],
             "material": "stahl-8.8-verzinkt", "preis": preis("je_stueck", 0.32), "ebene": "mitgeliefert"],
            ["id": "mutter-iso4032-m8", "art": "mutter", "name": "Sechskantmutter ISO 4032 M8", "norm": "ISO 4032",
             "masse": ["typ": "HexNut", "norm": "iso4032", "groesse": "M8-1.25"], "material": "stahl-8.8-verzinkt",
             "preis": preis("je_stueck", 0.06), "ebene": "mitgeliefert"],
            ["id": "scheibe-iso7089-m8", "art": "scheibe", "name": "Unterlegscheibe ISO 7089 M8", "norm": "ISO 7089",
             "masse": ["typ": "PlainWasher", "norm": "iso7089", "groesse": "M8"], "material": "stahl-8.8-verzinkt",
             "preis": preis("je_stueck", 0.03), "ebene": "mitgeliefert"],
        ]
        return [
            "materials": .array(materials), "items": .array(items),
            "arten": ["rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "winkel", "nutprofil", "holz", "platte",
                      "schraube", "mutter", "scheibe"],
        ]
    }()
}
