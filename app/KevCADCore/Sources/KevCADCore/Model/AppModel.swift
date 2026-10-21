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

    public var name: String { path.last ?? id }

    public init(
        id: String, color: SIMD4<Float>, material: String? = nil, visible: Bool = true, triangles: Int = 0,
        faces: Int = 0, edges: Int = 0, bboxMin: SIMD3<Float> = .zero, bboxMax: SIMD3<Float> = .zero,
        volume: Double? = nil, mass: Double? = nil, run: Int = 0
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
    /// Blender-Steuerung: Teile (Objektmodus) oder Flächen/Kanten/Punkte (Tab schaltet um), Projektion für Anzeigen.
    @Published public var selectionMode: SelectionMode = .parts
    @Published public var orthographic = false

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
