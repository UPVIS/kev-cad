import Foundation
import simd

// Nachrichten Kernel → App (PROTOCOL.md). Alle Felder sind tolerant: fehlende Werte werden zu nil oder Vorgaben,
// unbekannte Felder werden ignoriert, unbekannte Typen kommen als `.unknown` an.

/// Gemeinsame Felder jedes Kopfes.
public struct MessageEnvelope: Decodable, Sendable {
    public var type: String
    public var seq: Int?
    public var id: String?
    public var replyTo: String?

    enum CodingKeys: String, CodingKey {
        case type, seq, id
        case replyTo = "reply_to"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decode(String.self, forKey: .type)
        seq = try? c.decodeIfPresent(Int.self, forKey: .seq)
        id = try? c.decodeIfPresent(String.self, forKey: .id)
        replyTo = try? c.decodeIfPresent(String.self, forKey: .replyTo)
    }
}

public struct HelloMessage: Decodable, Sendable {
    public var protocolVersion: Int?
    public var kernelVersion: String?
    public var build123d: String?
    public var mcpPort: Int?

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "protocol"
        case kernelVersion = "kernel_version"
        case build123d
        case mcpPort = "mcp_port"
    }
}

public struct StatusMessage: Decodable, Sendable {
    public var state: String
    public var message: String?

    enum CodingKeys: String, CodingKey { case state, message }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decodeIfPresent(String.self, forKey: .state)) ?? "ready"
        message = try? c.decodeIfPresent(String.self, forKey: .message)
    }
}

public struct ProjectMessage: Decodable, Sendable {
    public var path: String
    public var name: String?
    public var model: String?
    public var replyTo: String?
    /// Phase 2: Inventar-Regel des Projekts, falls der Kernel sie mitschickt.
    public var inventarRegel: Bool?

    enum CodingKeys: String, CodingKey {
        case path, name, model
        case replyTo = "reply_to"
        case inventarRegel = "inventar_regel"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = try c.decode(String.self, forKey: .path)
        name = try? c.decodeIfPresent(String.self, forKey: .name)
        model = try? c.decodeIfPresent(String.self, forKey: .model)
        replyTo = try? c.decodeIfPresent(String.self, forKey: .replyTo)
        inventarRegel = try? c.decodeIfPresent(Bool.self, forKey: .inventarRegel)
    }
}

public struct RunStartMessage: Decodable, Sendable {
    public var run: Int
    public var fileHash: String?
    public var params: JSONValue?
    public var slowMs: Int?

    enum CodingKeys: String, CodingKey {
        case run, params
        case fileHash = "file_hash"
        case slowMs = "slow_ms"
    }
}

public struct StepMessage: Decodable, Sendable {
    public var run: Int
    public var index: Int
    public var text: String

    enum CodingKeys: String, CodingKey { case run, index, text }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        index = (try? c.decodeIfPresent(Int.self, forKey: .index)) ?? 0
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
    }
}

/// Werte je Fläche (`faces[i]` im Kopf von PART_UPSERT).
public struct FaceInfo: Codable, Equatable, Sendable {
    public var t: String
    public var a: Double?
    public var n: [Double]?
    public var c: [Double]?
    public var ax: [Double]?
    public var r: Double?
    /// Zweiter Radius (Torus: Rohrradius)
    public var r2: Double?
    /// Halbwinkel in Grad (Kegel)
    public var ang: Double?

    public init(
        t: String, a: Double? = nil, n: [Double]? = nil, c: [Double]? = nil, ax: [Double]? = nil, r: Double? = nil,
        r2: Double? = nil, ang: Double? = nil
    ) {
        self.t = t
        self.a = a
        self.n = n
        self.c = c
        self.ax = ax
        self.r = r
        self.r2 = r2
        self.ang = ang
    }

    public init(from decoder: Decoder) throws {
        let k = try decoder.container(keyedBy: CodingKeys.self)
        t = (try? k.decodeIfPresent(String.self, forKey: .t)) ?? "other"
        a = try? k.decodeIfPresent(Double.self, forKey: .a)
        n = try? k.decodeIfPresent([Double].self, forKey: .n)
        c = try? k.decodeIfPresent([Double].self, forKey: .c)
        ax = try? k.decodeIfPresent([Double].self, forKey: .ax)
        r = try? k.decodeIfPresent(Double.self, forKey: .r)
        r2 = try? k.decodeIfPresent(Double.self, forKey: .r2)
        ang = try? k.decodeIfPresent(Double.self, forKey: .ang)
    }
}

/// Werte je Kante (`edges[i]` im Kopf von PART_UPSERT).
public struct EdgeInfo: Codable, Equatable, Sendable {
    public var t: String
    public var l: Double?
    public var r: Double?
    public var c: [Double]?
    public var ax: [Double]?
    /// Zweiter Radius (Ellipse)
    public var r2: Double?

    public init(t: String, l: Double? = nil, r: Double? = nil, c: [Double]? = nil, ax: [Double]? = nil) {
        self.t = t
        self.l = l
        self.r = r
        self.c = c
        self.ax = ax
    }

    public init(from decoder: Decoder) throws {
        let k = try decoder.container(keyedBy: CodingKeys.self)
        t = (try? k.decodeIfPresent(String.self, forKey: .t)) ?? "other"
        l = try? k.decodeIfPresent(Double.self, forKey: .l)
        r = try? k.decodeIfPresent(Double.self, forKey: .r)
        c = try? k.decodeIfPresent([Double].self, forKey: .c)
        ax = try? k.decodeIfPresent([Double].self, forKey: .ax)
        r2 = try? k.decodeIfPresent(Double.self, forKey: .r2)
    }
}

/// Kopf von PART_UPSERT.
public struct PartUpsertHeader: Decodable, Sendable {
    public var run: Int
    public var name: String
    public var color: [Float]?
    public var material: String?
    public var bbox: BBox?
    public var props: JSONValue?
    public var counts: PartCounts
    public var faces: [FaceInfo]
    public var edges: [EdgeInfo]
    public var transform: [Float]?
    /// Phase 2: Lagerteil, wenn das Teil aus `lager.teil(...).verbauen(...)` stammt.
    public var stock: StockInfo?
    /// Phase 2, Inventar-Regel: "ok" oder "fehlt" (Teil ist weder Lagerteil noch gekennzeichnetes Druckteil).
    public var inventar: String?
    /// Phase 3: Zukaufteil, wenn das Teil aus `lager.zukauf(...).verbauen(...)` stammt.
    public var zukauf: ZukaufPartInfo?

    enum CodingKeys: String, CodingKey {
        case run, name, color, material, bbox, props, counts, faces, edges, transform, stock, inventar, zukauf
    }

    /// Inventar-Regel verletzt.
    public var inventarFehlt: Bool { inventar == "fehlt" }

    public init(
        run: Int, name: String, color: [Float]? = nil, material: String? = nil, bbox: BBox? = nil,
        props: JSONValue? = nil, counts: PartCounts, faces: [FaceInfo] = [], edges: [EdgeInfo] = [],
        transform: [Float]? = nil, stock: StockInfo? = nil
    ) {
        self.run = run
        self.name = name
        self.color = color
        self.material = material
        self.bbox = bbox
        self.props = props
        self.counts = counts
        self.faces = faces
        self.edges = edges
        self.transform = transform
        self.stock = stock
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        name = try c.decode(String.self, forKey: .name)
        color = try? c.decodeIfPresent([Float].self, forKey: .color)
        material = try? c.decodeIfPresent(String.self, forKey: .material)
        bbox = try? c.decodeIfPresent(BBox.self, forKey: .bbox)
        props = try? c.decodeIfPresent(JSONValue.self, forKey: .props)
        counts = try c.decode(PartCounts.self, forKey: .counts)
        faces = (try? c.decodeIfPresent([FaceInfo].self, forKey: .faces)) ?? []
        edges = (try? c.decodeIfPresent([EdgeInfo].self, forKey: .edges)) ?? []
        let t = try? c.decodeIfPresent([Float].self, forKey: .transform)
        transform = (t?.count == 16) ? t : nil
        stock = (try? c.decodeIfPresent(JSONValue.self, forKey: .stock)).flatMap { StockInfo(json: $0) }
        inventar = try? c.decodeIfPresent(String.self, forKey: .inventar)
        zukauf = (try? c.decodeIfPresent(JSONValue.self, forKey: .zukauf)).flatMap { ZukaufPartInfo(json: $0) }
    }

    /// Lineares RGBA, Vorgabe hellgrau.
    public var colorVector: SIMD4<Float> {
        guard let c = color, c.count >= 3 else { return SIMD4(0.72, 0.75, 0.79, 1) }
        return SIMD4(c[0], c[1], c[2], c.count > 3 ? c[3] : 1)
    }

    public var volume: Double? { props?["volume"]?.doubleValue }
    public var area: Double? { props?["area"]?.doubleValue }
    public var mass: Double? { props?["mass"]?.doubleValue }
    public var center: SIMD3<Float>? { props?["center"]?.vector3 }

    /// `transform` als Matrix (16 Zahlen spaltenweise), sonst Einheitsmatrix.
    public var transformMatrix: simd_float4x4 {
        guard let t = transform, t.count == 16 else { return matrix_identity_float4x4 }
        return simd_float4x4(
            SIMD4(t[0], t[1], t[2], t[3]), SIMD4(t[4], t[5], t[6], t[7]),
            SIMD4(t[8], t[9], t[10], t[11]), SIMD4(t[12], t[13], t[14], t[15]))
    }
}

public struct PartRemoveMessage: Decodable, Sendable {
    public var run: Int?
    public var name: String
}

public struct RunEndMessage: Decodable, Sendable {
    public var run: Int
    public var durationMs: Int
    public var parts: Int
    public var triangles: Int
    public var warnings: [String]
    public var params: JSONValue?
    /// Phase 2, Inventar-Regel: Teile, die weder Lagerteil noch gekennzeichnetes Druckteil sind.
    public var inventarVerstoesse: [String]

    enum CodingKeys: String, CodingKey {
        case run, parts, triangles, warnings, params
        case durationMs = "duration_ms"
        case inventarVerstoesse = "inventar_verstoesse"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        durationMs = (try? c.decodeIfPresent(Int.self, forKey: .durationMs)) ?? 0
        parts = (try? c.decodeIfPresent(Int.self, forKey: .parts)) ?? 0
        triangles = (try? c.decodeIfPresent(Int.self, forKey: .triangles)) ?? 0
        warnings = (try? c.decodeIfPresent([String].self, forKey: .warnings)) ?? []
        params = try? c.decodeIfPresent(JSONValue.self, forKey: .params)
        inventarVerstoesse = (try? c.decodeIfPresent([String].self, forKey: .inventarVerstoesse)) ?? []
    }
}

public struct RunErrorMessage: Decodable, Sendable {
    public var run: Int
    public var message: String
    public var line: Int?
    public var excerpt: String
    public var traceback: String?
    /// Kurzer Reparaturhinweis des Kernels, falls bekannt
    public var hint: String?

    enum CodingKeys: String, CodingKey { case run, message, line, excerpt, traceback, hint }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        message = (try? c.decodeIfPresent(String.self, forKey: .message)) ?? "Unbekannter Fehler"
        line = try? c.decodeIfPresent(Int.self, forKey: .line)
        excerpt = (try? c.decodeIfPresent(String.self, forKey: .excerpt)) ?? ""
        traceback = try? c.decodeIfPresent(String.self, forKey: .traceback)
        hint = try? c.decodeIfPresent(String.self, forKey: .hint)
    }
}

public struct AgentMessage: Decodable, Sendable {
    public var connected: Bool
    public var activity: String?
    /// Claude-Sitzungen, die Kev CAD bedienen (additiv, für den Spiegel; leer bei älteren Kerneln).
    public var sessions: [MirrorAgent]

    enum CodingKeys: String, CodingKey { case connected, activity, sessions }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        connected = (try? c.decodeIfPresent(Bool.self, forKey: .connected)) ?? false
        activity = try? c.decodeIfPresent(String.self, forKey: .activity)
        sessions = (try? c.decodeIfPresent([MirrorAgent].self, forKey: .sessions)) ?? []
    }
}

public struct ViewCommandMessage: Decodable, Sendable {
    public var id: String
    public var cmd: String
    public var args: JSONValue

    enum CodingKeys: String, CodingKey { case id, cmd, args }

    public init(id: String, cmd: String, args: JSONValue = .object([:])) {
        self.id = id
        self.cmd = cmd
        self.args = args
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        cmd = (try? c.decodeIfPresent(String.self, forKey: .cmd)) ?? ""
        args = (try? c.decodeIfPresent(JSONValue.self, forKey: .args)) ?? .object([:])
    }
}

public struct ScreenshotRequestMessage: Decodable, Sendable {
    public var id: String
    public var width: Int
    public var height: Int
    public var source: String
    public var view: String?
    public var hideOverlays: Bool
    /// Phase 5: Bild durch diese Kamera (`Kamera/<name>`, `source` "camera").
    public var camera: String?
    /// Prüfung/Analyse (additiv): eigene Blickrichtung, Ziel, Darstellung, Hervorhebung, Schnittkörper; siehe
    /// AppController+Ansichten.swift und PROTOCOL.md Abschnitt „Prüfung“.
    public var ansicht: JSONValue? = nil

    enum CodingKeys: String, CodingKey {
        case id, width, height, source, view, camera, ansicht
        case hideOverlays = "hide_overlays"
    }

    public init(
        id: String, width: Int, height: Int, source: String, view: String?, hideOverlays: Bool, camera: String? = nil
    ) {
        self.id = id
        self.width = width
        self.height = height
        self.source = source
        self.view = view
        self.hideOverlays = hideOverlays
        self.camera = camera
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        width = (try? c.decodeIfPresent(Int.self, forKey: .width)) ?? 1280
        height = (try? c.decodeIfPresent(Int.self, forKey: .height)) ?? 800
        source = (try? c.decodeIfPresent(String.self, forKey: .source)) ?? "current"
        view = try? c.decodeIfPresent(String.self, forKey: .view)
        hideOverlays = (try? c.decodeIfPresent(Bool.self, forKey: .hideOverlays)) ?? false
        camera = try? c.decodeIfPresent(String.self, forKey: .camera)
        if let v = try? c.decodeIfPresent(JSONValue.self, forKey: .ansicht), !v.isNull { ansicht = v }
    }
}

/// Ergebnis einer Messung (MEASURE_RES.result).
public struct MeasureResult: Decodable, Sendable {
    public var refs: [String]
    public var run: Int?
    public var kind: String
    public var values: JSONValue
    public var points: [[Double]]
    public var text: String

    enum CodingKeys: String, CodingKey { case refs, run, kind, values, points, text }

    public init(refs: [String], run: Int?, kind: String, values: JSONValue, points: [[Double]], text: String) {
        self.refs = refs
        self.run = run
        self.kind = kind
        self.values = values
        self.points = points
        self.text = text
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        refs = (try? c.decodeIfPresent([String].self, forKey: .refs)) ?? []
        run = try? c.decodeIfPresent(Int.self, forKey: .run)
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "distance"
        values = (try? c.decodeIfPresent(JSONValue.self, forKey: .values)) ?? .object([:])
        points = (try? c.decodeIfPresent([[Double]].self, forKey: .points)) ?? []
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
    }

    public var pointVectors: [SIMD3<Float>] {
        points.compactMap { $0.count >= 3 ? SIMD3(Float($0[0]), Float($0[1]), Float($0[2])) : nil }
    }
}

public struct MeasureResponseMessage: Decodable, Sendable {
    public var replyTo: String?
    public var result: MeasureResult

    enum CodingKeys: String, CodingKey {
        case result
        case replyTo = "reply_to"
    }
}

public struct ExportResponseMessage: Decodable, Sendable {
    public var replyTo: String?
    public var files: [String]

    enum CodingKeys: String, CodingKey {
        case files
        case replyTo = "reply_to"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        replyTo = try? c.decodeIfPresent(String.self, forKey: .replyTo)
        files = (try? c.decodeIfPresent([String].self, forKey: .files)) ?? []
    }
}

public struct AckMessage: Decodable, Sendable {
    public var replyTo: String?
    public var ok: Bool
    public var message: String?
    /// Bestand: id der Buchung (ACK auf GEBAUT_REQ).
    public var buchung: String?

    enum CodingKeys: String, CodingKey {
        case ok, message, buchung
        case replyTo = "reply_to"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        replyTo = try? c.decodeIfPresent(String.self, forKey: .replyTo)
        ok = (try? c.decodeIfPresent(Bool.self, forKey: .ok)) ?? true
        message = try? c.decodeIfPresent(String.self, forKey: .message)
        buchung = try? c.decodeIfPresent(String.self, forKey: .buchung)
    }
}

public struct ErrorMessage: Decodable, Sendable {
    public var replyTo: String?
    public var message: String

    enum CodingKeys: String, CodingKey {
        case message
        case replyTo = "reply_to"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        replyTo = try? c.decodeIfPresent(String.self, forKey: .replyTo)
        message = (try? c.decodeIfPresent(String.self, forKey: .message)) ?? "Unbekannter Fehler"
    }
}

/// Fertig gelesene Nachricht des Kernels.
public enum KernelMessage: Sendable {
    case hello(HelloMessage)
    case status(StatusMessage)
    case project(ProjectMessage)
    case runStart(RunStartMessage)
    case step(StepMessage)
    case partUpsert(PartUpsertHeader, PartGeometry)
    case partRemove(PartRemoveMessage)
    case runEnd(RunEndMessage)
    case runError(RunErrorMessage)
    case agent(AgentMessage)
    case viewCommand(ViewCommandMessage)
    case screenshotRequest(ScreenshotRequestMessage)
    case measureResponse(MeasureResponseMessage)
    case exportResponse(ExportResponseMessage)
    case ack(AckMessage)
    case error(ErrorMessage)
    /// Phase 2: Stückliste nach RUN_END oder auf BOM_REQ.
    case bom(BOMMessage)
    /// Phase 2: Lagerkatalog auf CATALOG_REQ.
    case catalog(CatalogMessage)
    /// Phase 3: Zustand eines Zukaufteils (angelegt, wartet auf CAD, importiert, Fehler).
    case zukaufStatus(ZukaufStatusMessage)
    /// Zwangsbedingungen: Bericht nach RUN_END (PROTOCOL.md Abschnitt „Zwangsbedingungen“).
    case constraints(ConstraintReport)
    /// Phase 5: Animation (ANIM_DEF, ANIM_REMOVE, ANIM_COLLISIONS, ANIM_PLAY, ANIM_SEEK, ANIM_VIDEO_REQ).
    case animation(AnimationMessage)
    /// Phase 5: CAMERA_UPSERT und CAMERA_REMOVE.
    case camera(CameraMessage)
    /// Prüfung: Befunde nach jedem Lauf (zuerst `state: "running"`, dann das Ergebnis).
    case check(CheckMessage)
    /// Versionen (PROTOCOL.md Abschnitt „Versionen“): VERSIONEN, VERSION_VERGLEICH, VERSION_BILD_REQ.
    case versionen(VersionMessage)
    /// Bestand des offenen Projekts mit Buchungen (BESTAND.md).
    case bestand(BestandMessage)
    /// Typ, den diese App-Version nicht kennt (wird ignoriert und protokolliert).
    case unknown(type: String, header: JSONValue)

    public var typeName: String {
        switch self {
        case .hello: return "HELLO"
        case .status: return "STATUS"
        case .project: return "PROJECT"
        case .runStart: return "RUN_START"
        case .step: return "STEP"
        case .partUpsert: return "PART_UPSERT"
        case .partRemove: return "PART_REMOVE"
        case .runEnd: return "RUN_END"
        case .runError: return "RUN_ERROR"
        case .agent: return "AGENT"
        case .viewCommand: return "VIEW_CMD"
        case .screenshotRequest: return "SCREENSHOT_REQ"
        case .measureResponse: return "MEASURE_RES"
        case .exportResponse: return "EXPORT_RES"
        case .ack: return "ACK"
        case .error: return "ERROR"
        case .bom: return "BOM"
        case .catalog: return "CATALOG"
        case .zukaufStatus: return "ZUKAUF_STATUS"
        case .constraints: return "CONSTRAINTS"
        case .animation(let a): return a.typeName
        case .camera(let c): return c.typeName
        case .check: return "CHECK"
        case .versionen(let v): return v.typeName
        case .bestand: return "BESTAND"
        case .unknown(let t, _): return t
        }
    }

    /// `reply_to` der Nachricht, falls sie eine Antwort ist.
    public var replyTo: String? {
        switch self {
        case .project(let m): return m.replyTo
        case .measureResponse(let m): return m.replyTo
        case .exportResponse(let m): return m.replyTo
        case .ack(let m): return m.replyTo
        case .error(let m): return m.replyTo
        case .bom(let m): return m.replyTo
        case .catalog(let m): return m.replyTo
        case .bestand(let m): return m.replyTo
        case .animation(let m): return m.replyTo
        case .versionen(let m): return m.replyTo
        default: return nil
        }
    }

    /// Liest einen Rahmen. Geometrie wird dabei vollständig dekodiert und geprüft.
    public static func decode(_ frame: Frame) throws -> KernelMessage {
        let dec = JSONDecoder()
        let env = try dec.decode(MessageEnvelope.self, from: frame.header)
        let h = frame.header
        switch env.type {
        case "HELLO": return .hello(try dec.decode(HelloMessage.self, from: h))
        case "STATUS": return .status(try dec.decode(StatusMessage.self, from: h))
        case "PROJECT": return .project(try dec.decode(ProjectMessage.self, from: h))
        case "RUN_START": return .runStart(try dec.decode(RunStartMessage.self, from: h))
        case "STEP": return .step(try dec.decode(StepMessage.self, from: h))
        case "PART_UPSERT":
            let head = try dec.decode(PartUpsertHeader.self, from: h)
            let geo = try PartGeometry.decode(payload: frame.payload, counts: head.counts)
            return .partUpsert(head, geo)
        case "PART_REMOVE": return .partRemove(try dec.decode(PartRemoveMessage.self, from: h))
        case "RUN_END": return .runEnd(try dec.decode(RunEndMessage.self, from: h))
        case "RUN_ERROR": return .runError(try dec.decode(RunErrorMessage.self, from: h))
        case "AGENT": return .agent(try dec.decode(AgentMessage.self, from: h))
        case "VIEW_CMD": return .viewCommand(try dec.decode(ViewCommandMessage.self, from: h))
        case "SCREENSHOT_REQ": return .screenshotRequest(try dec.decode(ScreenshotRequestMessage.self, from: h))
        case "MEASURE_RES": return .measureResponse(try dec.decode(MeasureResponseMessage.self, from: h))
        case "EXPORT_RES": return .exportResponse(try dec.decode(ExportResponseMessage.self, from: h))
        case "ACK": return .ack(try dec.decode(AckMessage.self, from: h))
        case "ERROR": return .error(try dec.decode(ErrorMessage.self, from: h))
        case "BOM": return .bom(try BOMMessage.decode(h))
        case "CATALOG": return .catalog(try CatalogMessage.decode(h))
        case "ZUKAUF_STATUS": return .zukaufStatus(try ZukaufStatusMessage.decode(h))
        case "CONSTRAINTS": return .constraints(try ConstraintsMessage.decode(h).report)
        case let t where AnimationMessage.types.contains(t): return .animation(try AnimationMessage.decode(type: t, frame: frame))
        case "CAMERA_UPSERT", "CAMERA_REMOVE": return .camera(try CameraMessage.decode(h, type: env.type))
        case "CHECK": return .check(try CheckMessage.decode(h, payload: frame.payload))
        case "BESTAND": return .bestand(try BestandMessage.decode(h))
        case let t where VersionMessage.types.contains(t): return .versionen(try VersionMessage.decode(type: t, frame: frame))
        default:
            let raw = (try? dec.decode(JSONValue.self, from: h)) ?? .null
            return .unknown(type: env.type, header: raw)
        }
    }
}
