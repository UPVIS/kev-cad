import Foundation
import KevCADCore
import simd

/// Einstellungen des Demomodus aus Umgebungsvariablen.
///
/// - `KEVCAD_DEMO=1` schaltet den Demomodus ein (AppInfo.isDemoMode).
/// - `KEVCAD_DEMO_STATE`: `welcome` (Vorgabe, kein Projekt offen), `live` (Projekt öffnet, Lauf baut sich in einigen
///   Sekunden auf), `running` (Lauf steht bei Schritt 3), `finished` (fertiger Lauf), `error` (Fehlerband).
///   Bei `running`, `finished` und `error` bleibt der Zustand stehen, damit Fensterbilder reproduzierbar sind.
/// - `KEVCAD_DEMO_VIEWPORT=metal` zeigt den echten KevViewport mit einem nicht gestarteten AppController statt der
///   Demovorschau.
/// - `KEVCAD_DEMO_LOG=1` öffnet beim Start auch das Protokoll.
/// - `KEVCAD_SELFTEST=keys` prüft nach dem Start, dass einbuchstabige Kürzel im Suchfeld nicht feuern.
/// - Nur bei festen Zuständen: `KEVCAD_DEMO_SECTION=1` (Schnitt in Z durch die Mitte), `KEVCAD_DEMO_EXPLODE=0.5`,
///   `KEVCAD_DEMO_MEASURE=1` (Messmodus an).
/// - `KEVCAD_APPEARANCE=light` oder `dark` erzwingt das Erscheinungsbild (gilt auch ohne Demomodus).
/// - Phase 2: `KEVCAD_DEMO_STATE=bom` (Gestell mit Stückliste, fester Zustand), `catalog` (dazu das Fenster
///   Lagerkatalog), `inventar` (Gestell mit einem Teil, das nicht aus dem Inventar stammt, und Vorschlägen von Claude).
///   `KEVCAD_DEMO_CATALOG=vorschlaege` zeigt im Lagerkatalog den Abschnitt „Vorschläge von Claude“. `KEVCAD_DEMO_BOM_LINE=2` wählt eine Stücklistenzeile aus, `KEVCAD_DEMO_CATALOG=<id>` einen
///   Katalogeintrag, `KEVCAD_DEMO_FORM=teil|material` öffnet das Formular „Neues Lagerteil“ bzw. „Neues Material“.
struct DemoConfiguration {
    enum Start: String {
        case welcome, live, running, finished, error, bom, catalog, inventar
    }

    var start: Start = .welcome
    var metalViewport = false
    var openLog = false
    var selfTest: String?
    var section = false
    var explode: Double?
    var measureMode = false
    var bomLine: Int?
    var catalogEntry: String?
    var form: String?

    var isFrozen: Bool { [.running, .finished, .error, .bom, .catalog, .inventar].contains(start) }
    /// Feste Zustände mit dem Gestell (Phase 2) statt dem Wandhalter.
    var usesGestell: Bool { start == .bom || start == .catalog || start == .inventar }

    static func fromEnvironment(_ env: [String: String] = ProcessInfo.processInfo.environment) -> DemoConfiguration {
        var config = DemoConfiguration()
        config.start = env["KEVCAD_DEMO_STATE"].flatMap { Start(rawValue: $0.lowercased()) } ?? .welcome
        config.metalViewport = env["KEVCAD_DEMO_VIEWPORT"]?.lowercased() == "metal"
        config.openLog = env["KEVCAD_DEMO_LOG"] == "1"
        config.selfTest = env["KEVCAD_SELFTEST"]
        config.section = env["KEVCAD_DEMO_SECTION"] == "1"
        config.explode = env["KEVCAD_DEMO_EXPLODE"].flatMap(Double.init)
        config.measureMode = env["KEVCAD_DEMO_MEASURE"] == "1"
        config.bomLine = env["KEVCAD_DEMO_BOM_LINE"].flatMap { Int($0) } ?? (config.start == .bom ? 2 : nil)
        config.catalogEntry = env["KEVCAD_DEMO_CATALOG"] ?? (config.start == .catalog ? "rohr-edelstahl-33.7x2" : nil)
        config.form = env["KEVCAD_DEMO_FORM"]?.lowercased()
        return config
    }
}

/// Grundform für die Demovorschau (die echte Geometrie kommt vom Kernel).
enum DemoPrimitive {
    case box(min: SIMD3<Float>, max: SIMD3<Float>)
    /// Zylinder entlang einer Achse (0 = x, 1 = y, 2 = z) von `from` bis `to` um `center`.
    case cylinder(axis: Int, center: SIMD3<Float>, radius: Float, from: Float, to: Float)
}

/// Beispieldaten: Baugruppe „Wandhalter“ mit sieben Teilen, Schritte, Auswahl, Messungen.
enum DemoData {
    static var projectFolder: URL { AppInfo.projectsDirectory.appendingPathComponent("Wandhalter", isDirectory: true) }

    /// sRGB-Hex in lineares RGBA (Farben im Protokoll sind linear).
    static func linear(_ hex: UInt32, alpha: Float = 1) -> SIMD4<Float> {
        func channel(_ shift: UInt32) -> Float {
            let c = Float((hex >> shift) & 0xFF) / 255
            return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return SIMD4(channel(16), channel(8), channel(0), alpha)
    }

    struct Spec {
        var id: String
        var color: UInt32
        var alpha: Float = 1
        var material: String?
        var min: SIMD3<Float>
        var max: SIMD3<Float>
        var volume: Double
        var triangles: Int
        var faces: Int
        var edges: Int
        var shape: [DemoPrimitive]
        /// Phase 2: Lagerteil (Gestell).
        var stock: StockInfo? = nil

        var density: Double { DemoData.density(material) }

        func node(run: Int) -> PartNode {
            PartNode(
                id: id, color: DemoData.linear(color, alpha: alpha), material: material, visible: true,
                triangles: triangles, faces: faces, edges: edges, bboxMin: min, bboxMax: max, volume: volume,
                mass: material == nil ? nil : (volume / 1000 * density * 10).rounded() / 10, run: run, stock: stock)
        }
    }

    static let plateRaw = Spec(
        id: "Grundplatte", color: 0xB8BEC4, material: "aluminium", min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 5),
        volume: 48_000, triangles: 12, faces: 6, edges: 12,
        shape: [.box(min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 5))])

    static let specs: [Spec] = [
        Spec(
            id: "Grundplatte", color: 0xB8BEC4, material: "aluminium", min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 5),
            volume: 47_678, triangles: 412, faces: 14, edges: 36,
            shape: [.box(min: SIMD3(-60, -40, 0), max: SIMD3(60, 40, 5))]),
        Spec(
            id: "Halter/Lasche", color: 0x9EA7B1, material: "aluminium", min: SIMD3(-20, -2.5, 5),
            max: SIMD3(20, 2.5, 64), volume: 11_800, triangles: 96, faces: 10, edges: 24,
            shape: [.box(min: SIMD3(-20, -2.5, 5), max: SIMD3(20, 2.5, 64))]),
        Spec(
            id: "Halter/Rohrschelle/Unterteil", color: 0x6F7A86, material: "stahl", min: SIMD3(-28, -10, 62),
            max: SIMD3(28, 10, 90), volume: 9_870, triangles: 1840, faces: 22, edges: 58,
            shape: [.box(min: SIMD3(-28, -10, 62), max: SIMD3(28, 10, 90))]),
        Spec(
            id: "Halter/Rohrschelle/Oberteil", color: 0x7C8794, material: "stahl", min: SIMD3(-28, -10, 90),
            max: SIMD3(28, 10, 118), volume: 9_870, triangles: 1840, faces: 22, edges: 58,
            shape: [.box(min: SIMD3(-28, -10, 90), max: SIMD3(28, 10, 118))]),
        Spec(
            id: "Schrauben/M6x20 links", color: 0x4D545C, material: "stahl", min: SIMD3(-50, -5, -11),
            max: SIMD3(-40, 5, 9), volume: 766, triangles: 1288, faces: 26, edges: 64,
            shape: [
                .cylinder(axis: 2, center: SIMD3(-45, 0, 0), radius: 3, from: -11, to: 5),
                .cylinder(axis: 2, center: SIMD3(-45, 0, 0), radius: 5, from: 5, to: 9),
            ]),
        Spec(
            id: "Schrauben/M6x20 rechts", color: 0x4D545C, material: "stahl", min: SIMD3(40, -5, -11),
            max: SIMD3(50, 5, 9), volume: 766, triangles: 1288, faces: 26, edges: 64,
            shape: [
                .cylinder(axis: 2, center: SIMD3(45, 0, 0), radius: 3, from: -11, to: 5),
                .cylinder(axis: 2, center: SIMD3(45, 0, 0), radius: 5, from: 5, to: 9),
            ]),
        Spec(
            id: "Rohr Ø42,4", color: 0x5B8DC9, alpha: 0.92, material: "stahl", min: SIMD3(-21.2, -70, 68.8),
            max: SIMD3(21.2, 70, 111.2), volume: 45_514, triangles: 2304, faces: 4, edges: 6,
            shape: [.cylinder(axis: 1, center: SIMD3(0, 0, 90), radius: 21.2, from: -70, to: 70)]),
    ]

    static var partIDs: [String] { specs.map(\.id) }

    static func shape(for id: String) -> [DemoPrimitive]? {
        (specs + gestellSpecs).first { $0.id == id }?.shape
    }

    static func parts(run: Int) -> [PartNode] { specs.map { $0.node(run: run) } }

    struct Step {
        var title: String
        var parts: [Spec]
    }

    /// Schritte eines Laufs wie `step()` im Modellcode; Teile erscheinen am Ende ihres Schritts.
    static let steps: [Step] = [
        Step(title: "Parameter", parts: []),
        Step(title: "Grundplatte", parts: [plateRaw]),
        Step(title: "Bohrungen", parts: [specs[0]]),
        Step(title: "Lasche", parts: [specs[1]]),
        Step(title: "Rohrschelle", parts: [specs[2], specs[3]]),
        Step(title: "Schrauben", parts: [specs[4], specs[5]]),
        Step(title: "Rohr", parts: [specs[6]]),
    ]

    static let warnings = ["Schrauben/M6x20: Gewinde nur kosmetisch dargestellt"]

    // MARK: Auswahl und Messungen

    static func selection(for ref: String, parts: [PartNode], run: Int) -> SelectionItem {
        if ref == "Grundplatte#f7" {
            return SelectionItem(
                ref: ref, run: run, summary: "Fläche 7 · Zylinder · Bohrung Ø6,4 mm",
                values: ["radius": 3.2, "area": 100.531])
        }
        if ref == "Halter/Lasche#e3" {
            return SelectionItem(ref: ref, run: run, summary: "Kante 3 · Gerade", values: ["length": 59])
        }
        if let hash = ref.firstIndex(of: "#") {
            let kind = ref[ref.index(after: hash)...]
            let number = kind.dropFirst()
            switch kind.first {
            case "f": return SelectionItem(ref: ref, run: run, summary: "Fläche \(number)")
            case "e": return SelectionItem(ref: ref, run: run, summary: "Kante \(number)")
            default: return SelectionItem(ref: ref, run: run, summary: "Punkt \(number)")
            }
        }
        let part = parts.first { $0.id == ref }
        var values: [String: Double] = [:]
        if let volume = part?.volume { values["volume"] = volume }
        if let mass = part?.mass { values["mass"] = mass }
        let material = part?.material.map { demoCatalog.material($0)?.name ?? $0.capitalized } ?? "ohne Material"
        return SelectionItem(ref: ref, run: run, summary: "Teil \(part?.name ?? ref) · \(material)", values: values)
    }

    static func measurements() -> [MeasurementItem] {
        [
            MeasurementItem(
                refs: ["Grundplatte#f7", "Grundplatte#f2"], kind: "distance", text: "Abstand 11,800 mm (dx 11,800)",
                points: [SIMD3(-48.2, -40, 5), SIMD3(-60, -40, 5)],
                values: ["distance": 11.8, "dx": 11.8, "dy": 0, "dz": 0]),
            MeasurementItem(
                refs: ["Halter/Lasche#f4", "Grundplatte#f5"], kind: "angle", text: "Winkel 90,00°",
                points: [SIMD3(20, -2.5, 40), SIMD3(40, -2.5, 5)], values: ["angle": 90]),
        ]
    }

    static let agentActivities: [String?] = [
        "liest model.py", "misst Abstand Bohrung ↔ Plattenrand", "macht ein Bild von vorne", nil,
        "prüft die Wandstärke der Rohrschelle", "exportiert STEP und 3MF", nil,
    ]

    static let errorMessage = "NameError: name 'dicke' is not defined"
    static let errorLine = 23
    static let errorExcerpt = """
          21 | platte = Box(breite, 80, 5)
          22 | show(platte, "Grundplatte", material="aluminium")
        > 23 | lasche = Box(40, dicke, 59)
          24 | show(lasche, "Halter/Lasche", material="aluminium")
          25 |
        """

    // MARK: Zuletzt geöffnet

    /// Eigene, beim Start neu gefüllte Liste, damit der Demomodus die echte Liste der Variante nicht verändert.
    @MainActor
    static func makeRecents() -> RecentProjects {
        let suite = "\(AppInfo.bundleID).demo"
        let defaults = UserDefaults(suiteName: suite) ?? .standard
        defaults.removePersistentDomain(forName: suite)
        let base = AppInfo.projectsDirectory
        let missing = base.appendingPathComponent("Alter Entwurf").path
        let recents = RecentProjects(defaults: defaults, exists: { $0.path != missing })
        let now = Date()
        let entries: [(String, TimeInterval)] = [
            ("Alter Entwurf", -86400 * 40),
            ("Gartenbank", -86400 * 9),
            ("Outdoorküche Beelonia", -86400 * 3),
            ("Regalwinkel", -86400 - 3600 * 5),
            ("Wandhalter", -3600 * 2),
            ("Gestell", -60 * 20),
        ]
        for (name, offset) in entries {
            recents.note(base.appendingPathComponent(name, isDirectory: true), date: now.addingTimeInterval(offset))
        }
        return recents
    }
}
