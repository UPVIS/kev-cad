import Foundation
import simd

// Gemeinsames App-Modell: Vertrag zwischen App-Kern (Kernel-Verbindung, Szene, Viewport) und Oberfläche
// (Fenster, Leisten, Projekte). Der App-Kern füllt AppModel und setzt AppModel.actions; die Oberfläche liest
// AppModel und ruft nur Methoden aus AppActions auf, ändert also selbst keine der @Published-Werte.
// Änderungen an dieser Datei nur abgestimmt (siehe CLAUDE.md, Abschnitt Zuständigkeiten).

public enum KernelState: Equatable, Sendable {
    case stopped
    case starting
    case ready
    case busy
    case failed(String)
}

public struct ProjectInfo: Equatable, Sendable {
    public var path: URL
    public var name: String
    public var modelFile: URL

    public init(path: URL, name: String, modelFile: URL) {
        self.path = path
        self.name = name
        self.modelFile = modelFile
    }
}

/// Ein Teil aus `show()`. `id` ist der vollständige Name ("Halter/Lasche"), `path` dessen Bestandteile.
public struct PartNode: Identifiable, Equatable, Sendable {
    public var id: String
    public var path: [String]
    public var color: SIMD4<Float>
    public var material: String?
    public var visible: Bool
    public var triangles: Int
    public var faces: Int
    public var edges: Int
    public var bboxMin: SIMD3<Float>
    public var bboxMax: SIMD3<Float>
    public var volume: Double?
    public var mass: Double?
    public var run: Int
    /// Phase 2: gesetzt, wenn das Teil aus `lager.teil(...).verbauen(...)` stammt.
    public var stock: StockInfo?
    /// Phase 2 (A1, additiv): Inventar-Regel verletzt (PART_UPSERT `inventar: "fehlt"` oder in
    /// RUN_END `inventar_verstoesse`): weder verbautes Lagerteil noch gekennzeichnetes 3D-Druckteil.
    public var inventarFehlt: Bool

    public var name: String { path.last ?? id }

    public init(
        id: String, color: SIMD4<Float>, material: String? = nil, visible: Bool = true, triangles: Int = 0,
        faces: Int = 0, edges: Int = 0, bboxMin: SIMD3<Float> = .zero, bboxMax: SIMD3<Float> = .zero,
        volume: Double? = nil, mass: Double? = nil, run: Int = 0, stock: StockInfo? = nil, inventarFehlt: Bool = false
    ) {
        self.id = id
        self.path = id.split(separator: "/").map(String.init)
        self.color = color
        self.material = material
        self.visible = visible
        self.triangles = triangles
        self.faces = faces
        self.edges = edges
        self.bboxMin = bboxMin
        self.bboxMax = bboxMax
        self.volume = volume
        self.mass = mass
        self.run = run
        self.stock = stock
        self.inventarFehlt = inventarFehlt
    }
}

public enum RunState: Equatable, Sendable {
    case idle
    case running(run: Int, step: String?, stepIndex: Int)
    case finished(run: Int, durationMs: Int, parts: Int, warnings: [String])
    case failed(run: Int, message: String, line: Int?, excerpt: String)
}

/// Ein ausgewähltes Element: Teil, Fläche, Kante oder Punkt (Referenz siehe PROTOCOL.md).
public struct SelectionItem: Identifiable, Equatable, Sendable {
    public var ref: String
    public var run: Int
    /// Kurzbeschreibung für den Inspektor, z. B. "Fläche 12 · Ebene · 200,0 mm²".
    public var summary: String
    /// Sofortwerte ohne Rückfrage beim Kernel (Länge, Radius, Fläche, Normale …).
    public var values: [String: Double]

    public var id: String { ref }

    public init(ref: String, run: Int, summary: String, values: [String: Double] = [:]) {
        self.ref = ref
        self.run = run
        self.summary = summary
        self.values = values
    }
}

public struct MeasurementItem: Identifiable, Equatable, Sendable {
    public var id: UUID
    public var refs: [String]
    public var kind: String
    public var text: String
    public var points: [SIMD3<Float>]
    public var values: [String: Double]

    public init(
        id: UUID = UUID(), refs: [String], kind: String, text: String, points: [SIMD3<Float>],
        values: [String: Double] = [:]
    ) {
        self.id = id
        self.refs = refs
        self.kind = kind
        self.text = text
        self.points = points
        self.values = values
    }
}

public enum DisplayStyle: String, CaseIterable, Sendable {
    case shadedEdges, shaded, wireframe, xray
}

public enum StandardViewName: String, CaseIterable, Sendable {
    case top, bottom, front, back, left, right, iso, isoFrontLeft, isoBackRight, isoBackLeft
}

public struct LogLine: Identifiable, Equatable, Sendable {
    public enum Level: String, Sendable { case info, warning, error }
    public var id = UUID()
    public var date: Date
    public var level: Level
    public var text: String

    public init(date: Date = Date(), level: Level = .info, text: String) {
        self.date = date
        self.level = level
        self.text = text
    }
}

@MainActor
public final class AppModel: ObservableObject {
    @Published public var kernelState: KernelState = .stopped
    @Published public var agentConnected = false
    @Published public var agentActivity: String?
    @Published public var project: ProjectInfo?
    @Published public var parts: [PartNode] = []
    @Published public var run: RunState = .idle
    @Published public var selection: [SelectionItem] = []
    @Published public var measurements: [MeasurementItem] = []
    @Published public var displayStyle: DisplayStyle = .shadedEdges
    @Published public var sectionEnabled = false
    @Published public var explodeFactor: Double = 0
    @Published public var measureMode = false
    @Published public var autoRun = true
    @Published public var slowMotion = false
    @Published public var triangleCount = 0
    @Published public var log: [LogLine] = []
    /// Phase 2: Stückliste des letzten Laufs (BOM) und zuletzt geladener Lagerkatalog (CATALOG).
    @Published public var bom: BillOfMaterials?
    @Published public var catalog: Catalog?
    /// Neue Version im Tools-Stapel installiert, die laufende App ist älter: Text für den Hinweis, sonst nil.
    @Published public var updateAvailable: String?
    /// Phase 2 (A1, additiv): Stand der letzten Katalog-Anfrage (Laden, Speichern, Löschen) für die Oberfläche.
    @Published public var catalogActivity: CatalogActivity = .idle
    /// Phase 2 (A1, additiv): Inventar-Regel des offenen Projekts (Standard an; nur Kevin schaltet sie in der App um,
    /// SETTINGS `inventar_regel`) und die Teile, die sie im letzten Lauf verletzen (RUN_END `inventar_verstoesse`).
    @Published public var inventarRegel = true
    @Published public var inventarVerstoesse: [String] = []
    /// Blender-Steuerung: Teile (Objektmodus) oder Flächen/Kanten/Punkte (Tab schaltet um), Projektion für Anzeigen.
    @Published public var selectionMode: SelectionMode = .parts
    @Published public var orthographic = false
    /// Phase 5 (additiv): Animation (Zeitleiste) als eigenes Objekt, damit das Abspielen nicht das ganze Fenster neu
    /// zeichnet; Aktionen über `actions as? AnimationActions`.
    public let animation = AnimationModel()

    /// Vom App-Kern gesetzt; die Oberfläche ruft darüber alle Aktionen auf.
    public weak var actions: AppActions?

    public init() {}

    public func append(_ line: LogLine) {
        log.append(line)
        if log.count > 2000 { log.removeFirst(log.count - 2000) }
    }
}

/// Alles, was die Oberfläche auslösen kann. Implementiert vom App-Kern (AppController).
@MainActor
public protocol AppActions: AnyObject {
    func openProject(at url: URL)
    func newProject(at url: URL, template: String)
    func runModel()
    func setVisibility(_ partIDs: [String], visible: Bool)
    func isolate(_ partIDs: [String])
    func showAll()
    func focus(on refs: [String])
    func select(_ refs: [String])
    func setStandardView(_ view: StandardViewName)
    func setDisplayStyle(_ style: DisplayStyle)
    func setSection(enabled: Bool, axis: String, offset: Double)
    func setExplode(_ factor: Double)
    func setMeasureMode(_ on: Bool)
    func clearMeasurements()
    func setAutoRun(_ on: Bool)
    func setSlowMotion(_ on: Bool)
    func export(formats: [String])
    func saveScreenshot()
    func restartKernel()
}

/// Ergänzung der Oberfläche (AP4), rein additiv: eine einzelne Messung löschen. AppActions kennt nur
/// `clearMeasurements()`. Der App-Kern kann dieses Protokoll übernehmen (oder die Methode in AppActions aufnehmen);
/// bis dahin blendet die Oberfläche den Löschknopf je Messung aus, wenn `AppModel.actions` es nicht anbietet.
@MainActor
public protocol MeasurementRemoving: AnyObject {
    func removeMeasurement(id: UUID)
}

// MARK: - Phase 2: Lagerteile, Stückliste, Katalog (PROTOCOL.md Abschnitt „Phase 2“, KATALOG.md)

public struct StockInfo: Equatable, Sendable {
    public var id: String
    public var name: String
    public var laenge: Double?
    public var gehrung: [Double]
    public var material: String?
    public var kg: Double?
    public var preis: Double?

    public init(
        id: String, name: String, laenge: Double? = nil, gehrung: [Double] = [0, 0], material: String? = nil,
        kg: Double? = nil, preis: Double? = nil
    ) {
        self.id = id
        self.name = name
        self.laenge = laenge
        self.gehrung = gehrung
        self.material = material
        self.kg = kg
        self.preis = preis
    }
}

public struct BOMLine: Identifiable, Equatable, Sendable {
    public var pos: Int
    public var art: String
    public var stockID: String?
    public var benennung: String
    public var norm: String?
    public var material: String?
    public var laenge: Double?
    public var gehrung: [Double]
    public var masseText: String
    public var anzahl: Int
    public var kgJe: Double?
    public var kg: Double?
    public var preisJe: Double?
    public var preis: Double?
    public var teile: [String]
    public var eigenteil: Bool

    public var id: Int { pos }

    public init(
        pos: Int, art: String, stockID: String?, benennung: String, norm: String? = nil, material: String? = nil,
        laenge: Double? = nil, gehrung: [Double] = [0, 0], masseText: String, anzahl: Int, kgJe: Double? = nil,
        kg: Double? = nil, preisJe: Double? = nil, preis: Double? = nil, teile: [String] = [], eigenteil: Bool = false
    ) {
        self.pos = pos
        self.art = art
        self.stockID = stockID
        self.benennung = benennung
        self.norm = norm
        self.material = material
        self.laenge = laenge
        self.gehrung = gehrung
        self.masseText = masseText
        self.anzahl = anzahl
        self.kgJe = kgJe
        self.kg = kg
        self.preisJe = preisJe
        self.preis = preis
        self.teile = teile
        self.eigenteil = eigenteil
    }
}

/// Zuschnitt einer Stangenware: welche Längen auf welche Stange kommen.
public struct CutPlan: Identifiable, Equatable, Sendable {
    public var stockID: String
    public var benennung: String
    public var stangenlaenge: Double
    public var saegeschnitt: Double
    public var stangen: [[Double]]
    public var verschnittProzent: Double

    public var id: String { stockID }

    public init(
        stockID: String, benennung: String, stangenlaenge: Double, saegeschnitt: Double, stangen: [[Double]],
        verschnittProzent: Double
    ) {
        self.stockID = stockID
        self.benennung = benennung
        self.stangenlaenge = stangenlaenge
        self.saegeschnitt = saegeschnitt
        self.stangen = stangen
        self.verschnittProzent = verschnittProzent
    }
}

public struct BOMTotals: Equatable, Sendable {
    public var kg: Double
    public var preis: Double?
    public var positionen: Int
    public var teile: Int
    public var preisHinweis: String?

    public init(kg: Double, preis: Double?, positionen: Int, teile: Int, preisHinweis: String? = nil) {
        self.kg = kg
        self.preis = preis
        self.positionen = positionen
        self.teile = teile
        self.preisHinweis = preisHinweis
    }
}

public struct BillOfMaterials: Equatable, Sendable {
    public var run: Int
    public var lines: [BOMLine]
    public var cuts: [CutPlan]
    public var totals: BOMTotals
    public var warnings: [String]

    public init(run: Int, lines: [BOMLine], cuts: [CutPlan], totals: BOMTotals, warnings: [String] = []) {
        self.run = run
        self.lines = lines
        self.cuts = cuts
        self.totals = totals
        self.warnings = warnings
    }
}

/// Ebene eines Katalogeintrags (KATALOG.md): mitgeliefert, eigener Katalog, Projekt.
public enum CatalogLevel: String, Sendable, CaseIterable {
    case mitgeliefert, eigen, projekt
}

public struct CatalogMaterial: Identifiable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var gruppe: String
    public var dichte: Double
    public var farbe: String
    public var preisJeKg: Double?
    public var ebene: CatalogLevel
    /// Der vollständige Eintrag als JSON (zum Bearbeiten und Zurückschicken mit CATALOG_SAVE).
    public var json: Data
    /// Phase 2 (A1, additiv): `status: "vorgeschlagen"` (von Claude angelegt, wartet auf Freigabe).
    public var vorgeschlagen: Bool
    /// Phase 2 (A1, additiv): Filament für 3D-Druckteile (`druckbar: true`).
    public var druckbar: Bool

    public init(
        id: String, name: String, gruppe: String, dichte: Double, farbe: String, preisJeKg: Double? = nil,
        ebene: CatalogLevel, json: Data = Data(), vorgeschlagen: Bool = false, druckbar: Bool = false
    ) {
        self.id = id
        self.name = name
        self.gruppe = gruppe
        self.dichte = dichte
        self.farbe = farbe
        self.preisJeKg = preisJeKg
        self.ebene = ebene
        self.json = json
        self.vorgeschlagen = vorgeschlagen
        self.druckbar = druckbar
    }
}

public struct CatalogItem: Identifiable, Equatable, Sendable {
    public var id: String
    public var art: String
    public var name: String
    public var norm: String?
    public var masse: [String: Double]
    public var material: String
    public var kgJeM: Double?
    /// Preis als Anzeigetext, z. B. "4,80 €/m" oder "0,32 €/Stück".
    public var preisText: String?
    public var tags: [String]
    public var ebene: CatalogLevel
    public var json: Data
    /// Phase 2 (A1, additiv): `status: "vorgeschlagen"` (von Claude angelegt, wartet auf Freigabe).
    public var vorgeschlagen: Bool

    public init(
        id: String, art: String, name: String, norm: String? = nil, masse: [String: Double] = [:], material: String,
        kgJeM: Double? = nil, preisText: String? = nil, tags: [String] = [], ebene: CatalogLevel, json: Data = Data(),
        vorgeschlagen: Bool = false
    ) {
        self.id = id
        self.art = art
        self.name = name
        self.norm = norm
        self.masse = masse
        self.material = material
        self.kgJeM = kgJeM
        self.preisText = preisText
        self.tags = tags
        self.ebene = ebene
        self.json = json
        self.vorgeschlagen = vorgeschlagen
    }
}

/// Phase 2 (A1, additiv): Was gerade mit dem Katalog passiert. `saved`/`deleted` bleiben stehen, bis die nächste
/// Katalog-Aktion beginnt (die Oberfläche schließt daran z. B. das Formular und wählt den Eintrag aus).
public enum CatalogActivity: Equatable, Sendable {
    case idle
    /// CATALOG_REQ läuft (nur beim ersten Laden; Nachladen nach dem Speichern zeigt keinen Ladezustand).
    case loading
    case saving
    case saved(id: String, message: String?)
    case deleted(id: String)
    /// Laden, Speichern oder Löschen gescheitert (Fehlertext des Kernels oder Zeitüberschreitung).
    case failed(String)
}

public struct Catalog: Equatable, Sendable {
    public var materials: [CatalogMaterial]
    public var items: [CatalogItem]
    public var arten: [String]

    public init(materials: [CatalogMaterial], items: [CatalogItem], arten: [String]) {
        self.materials = materials
        self.items = items
        self.arten = arten
    }
}

/// Phase-2-Aktionen. Standardmäßig ohne Wirkung, damit bestehende Implementierungen weiter kompilieren; der App-Kern
/// (AppController) und der Demomodus (DemoActions) setzen sie um.
@MainActor
public protocol CatalogActions: AnyObject {
    func requestBOM()
    func requestCatalog(query: String?, art: String?)
    /// `json`: Eintrag laut KATALOG.md; `kind`: "teil" oder "material".
    func saveCatalogEntry(kind: String, json: Data, ebene: CatalogLevel)
    func deleteCatalogEntry(kind: String, id: String, ebene: CatalogLevel)
    /// Teile einer Stücklistenzeile im Viewer hervorheben und einpassen.
    func showBOMLine(_ line: BOMLine)
    /// Beendet die App und startet die installierte Version neu.
    func relaunchForUpdate()
}

/// Phase 2 (A1, additiv): Inventar-Regel des Projekts umschalten (nur aus der App, nicht über MCP).
@MainActor
public protocol InventoryActions: AnyObject {
    func setInventarRegel(_ on: Bool)
}

// MARK: - Blender-Steuerung

/// Was ein Klick im Viewport auswählt: ganze Teile (wie Blenders Objektmodus) oder einzelne Elemente.
public enum SelectionMode: String, Sendable, CaseIterable {
    case parts, elements
}

/// Ansicht und Auswahl wie in Blender (Ziffernblock bzw. Zahlenreihe, Komma, Pos1, A, H, /, Tab). Implementiert vom
/// App-Kern; die Oberfläche ruft sie über `model.actions as? NavigationActions` auf.
@MainActor
public protocol NavigationActions: AnyObject {
    /// 1/3/7 (mit Strg die Gegenseite): Blickrichtung wechseln, Drehpunkt und Abstand bleiben, automatisch parallel.
    func axisView(_ view: StandardViewName)
    /// 9: Ansicht von der Gegenseite.
    func viewOpposite()
    /// 5: Perspektive und Parallelprojektion umschalten.
    func toggleProjection()
    /// 4/6/8/2: in 15°-Schritten drehen (Grad um die Z-Achse bzw. nach oben/unten).
    func orbitStep(yaw: Double, pitch: Double)
    /// Strg+4/6/8/2: schwenken, Anteil der Bildhöhe.
    func panStep(x: Double, y: Double)
    /// + und -: zoomen, positive Schritte vergrößern.
    func zoomStep(_ steps: Int)
    /// Komma bzw. Punkt (Ziffernblock): Auswahl zentrieren und einpassen; ohne Auswahl alles.
    func viewSelected()
    /// Pos1: alles einpassen.
    func viewAll()
    /// A: alles auswählen.
    func selectAll()
    /// Strg+I: Auswahl umkehren.
    func invertSelection()
    /// Umschalt+H: alles außer der Auswahl ausblenden.
    func hideUnselected()
    /// /: lokale Ansicht (nur Auswahl zeigen und einpassen) an und aus.
    func toggleLocalView()
    /// Tab: Teile oder Elemente auswählen.
    func setSelectionMode(_ mode: SelectionMode)
}
