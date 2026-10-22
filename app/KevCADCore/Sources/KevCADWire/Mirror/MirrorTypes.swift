import Foundation

// Werte des Spiegel-Protokolls (MIRROR.md, Version 1.1): Teile der Szene, Kamera, Zustand, Sitzungen.
// Alle Typen lesen tolerant (fehlende Felder werden Vorgaben, unbekannte Felder werden ignoriert) und schreiben genau
// die Felder aus MIRROR.md. Felder, die dort „oder null“ sind, gehen ausdrücklich als null auf die Leitung.

/// Feste Angaben des Spiegels.
public enum MirrorProtocol {
    /// `protocol` im HELLO der Gegenstelle.
    public static let name = "kevcad-mirror"
    public static let version = 1
    /// Obergrenzen je Rahmen auf dem Spiegel-Socket.
    public static let maxHeaderBytes = 16 * 1024
    public static let maxPayloadBytes = 64 * 1024
    /// Dateiname des Sockets im Support-Ordner der App (`~/Library/Application Support/<bundle-id>/mirror.sock`).
    public static let socketName = "mirror.sock"
    /// Bundle-ID der installierten App; nur deren Socket sucht VoiceBridge ohne Debug-Schalter.
    public static let installedBundleID = "de.upvis.kevcad"
    /// Merkmale, die Kev CAD im HELLO anbietet.
    public static let features = [KcadMesh.format, freigabeFeature]
    /// Kamerastände höchstens so oft je Sekunde (latest-only).
    public static let cameraRate = 40.0
    /// Höchstens so viele Netzblöcke gleichzeitig unterwegs.
    public static let meshBlocksInFlight = 2
    /// Vorschlag für die Miete (`WATCH.dauer_s`).
    public static let defaultLeaseSeconds = 300.0
    /// Eine Sitzung gilt als aktiv, wenn ihr letzter verändernder Werkzeugaufruf höchstens so lange her ist.
    public static let activeSessionWindow: TimeInterval = 10 * 60

    #if os(macOS)
        /// Socket-Pfad für eine Bundle-ID (Standard: die installierte App).
        public static func socketPath(bundleID: String = installedBundleID, home: URL? = nil) -> String {
            let base = home ?? FileManager.default.homeDirectoryForCurrentUser
            return base.appendingPathComponent("Library/Application Support/\(bundleID)/\(socketName)").path
        }
    #endif
}

/// Vorrang eines Rahmens; bestimmt die Reihenfolge in jeder Sendewarteschlange.
public enum MirrorPriority: String, Codable, Sendable, CaseIterable, Comparable {
    /// Auswahl, Sichtbarkeit, Isolieren, Hervorhebung, Laufstand, Befehle und Antworten: nie verwerfen, zuerst.
    case zustand
    /// Kamerastand: nur der neueste zählt, höchstens 40 je Sekunde.
    case kamera
    /// Teileliste, Teil dazu oder weg: nie verwerfen, vor Netzen.
    case szene
    /// Netzblöcke: zuletzt, höchstens zwei unterwegs.
    case netz

    var rank: Int {
        switch self {
        case .zustand: return 0
        case .kamera: return 1
        case .szene: return 2
        case .netz: return 3
        }
    }

    public static func < (a: MirrorPriority, b: MirrorPriority) -> Bool { a.rank < b.rank }
}

/// Woher eine Zustandsänderung kommt.
public enum MirrorSource: String, Codable, Sendable {
    case mac, iphone, agent
}

// MARK: - Sitzungen und Projekt

/// Eine Claude-Sitzung, die Kev CAD bedient (`agents` in HELLO und AGENTS, `sessions` im Kernel-Rahmen AGENT).
public struct MirrorAgent: Codable, Equatable, Sendable {
    /// `CLAUDE_CODE_SESSION_ID` aus der Umgebung des MCP-Brückenprozesses.
    public var sessionID: String
    /// Genau eine Sitzung ist aktiv: die mit dem letzten verändernden Werkzeugaufruf der letzten 10 Minuten.
    public var aktiv: Bool
    /// Seit wann die Sitzung Kev CAD bedient (ISO 8601, UTC).
    public var seit: String?
    /// Was die Sitzung gerade bzw. zuletzt getan hat, z. B. „führt model.py aus“.
    public var taetigkeit: String?
    /// Zusatz (optional): Zeitpunkt des letzten verändernden Werkzeugaufrufs (ISO 8601, UTC).
    public var zuletzt: String?

    public init(sessionID: String, aktiv: Bool, seit: String? = nil, taetigkeit: String? = nil, zuletzt: String? = nil) {
        self.sessionID = sessionID
        self.aktiv = aktiv
        self.seit = seit
        self.taetigkeit = taetigkeit
        self.zuletzt = zuletzt
    }

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case aktiv, seit, taetigkeit, zuletzt
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionID = (try? c.decodeIfPresent(String.self, forKey: .sessionID)) ?? ""
        aktiv = (try? c.decodeIfPresent(Bool.self, forKey: .aktiv)) ?? false
        seit = try? c.decodeIfPresent(String.self, forKey: .seit)
        taetigkeit = try? c.decodeIfPresent(String.self, forKey: .taetigkeit)
        zuletzt = try? c.decodeIfPresent(String.self, forKey: .zuletzt)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(sessionID, forKey: .sessionID)
        try c.encode(aktiv, forKey: .aktiv)
        try c.encode(seit, forKey: .seit)
        try c.encode(taetigkeit, forKey: .taetigkeit)
        try c.encodeIfPresent(zuletzt, forKey: .zuletzt)
    }
}

/// Offenes Projekt. `path` steht nur im HELLO von Kev CAD und verlässt den Mac nicht (VoiceBridge reicht nur `name`).
public struct MirrorProject: Codable, Equatable, Sendable {
    public var path: String?
    public var name: String

    public init(path: String? = nil, name: String) {
        self.path = path
        self.name = name
    }

    enum CodingKeys: String, CodingKey { case path, name }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = try? c.decodeIfPresent(String.self, forKey: .path)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(path, forKey: .path)
        try c.encode(name, forKey: .name)
    }

    /// Dasselbe ohne Pfad (für SCENE und alles, was den Mac verlässt).
    public var withoutPath: MirrorProject { MirrorProject(name: name) }
}

// MARK: - Teile

/// Anzahlen eines Netzes im Format `kcad-mesh-1` (wie `counts` in PART_UPSERT, ohne B-Rep-Punkte).
public struct MeshCounts: Codable, Equatable, Hashable, Sendable {
    public var vert: Int
    public var tri: Int
    public var face: Int
    public var edge: Int
    public var epts: Int

    public init(vert: Int = 0, tri: Int = 0, face: Int = 0, edge: Int = 0, epts: Int = 0) {
        self.vert = vert
        self.tri = tri
        self.face = face
        self.edge = edge
        self.epts = epts
    }

    public init(_ counts: PartCounts) {
        self.init(vert: counts.vert, tri: counts.tri, face: counts.face, edge: counts.edge, epts: counts.epts)
    }

    enum CodingKeys: String, CodingKey { case vert, tri, face, edge, epts }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        vert = (try? c.decodeIfPresent(Int.self, forKey: .vert)) ?? 0
        tri = (try? c.decodeIfPresent(Int.self, forKey: .tri)) ?? 0
        face = (try? c.decodeIfPresent(Int.self, forKey: .face)) ?? 0
        edge = (try? c.decodeIfPresent(Int.self, forKey: .edge)) ?? 0
        epts = (try? c.decodeIfPresent(Int.self, forKey: .epts)) ?? 0
    }

    /// Anzahlen für `PartGeometry.decode` (ohne B-Rep-Punkte).
    public var partCounts: PartCounts { PartCounts(vert: vert, tri: tri, face: face, edge: edge, epts: epts, vtx: 0) }

    /// Länge der ungepackten Arrays in Byte (`roh_bytes`).
    public var rawBytes: Int { 4 * (vert * 3 + vert * 3 + tri * 3 + tri + epts * 3 + (edge + 1)) }
}

/// Ein Teil der Szene, wie es in SCENE und PART reist. `color` ist sRGB wie in PART_UPSERT.
public struct MirrorPart: Codable, Equatable, Sendable {
    public var name: String
    /// SHA-256 über das ungepackte Netz (`kcad-mesh-1`), die ersten 16 Hex-Zeichen.
    public var hash: String
    public var color: [Float]
    public var material: String?
    public var bbox: BBox?
    public var counts: MeshCounts

    public init(
        name: String, hash: String, color: [Float], material: String? = nil, bbox: BBox? = nil, counts: MeshCounts
    ) {
        self.name = name
        self.hash = hash
        self.color = color
        self.material = material
        self.bbox = bbox
        self.counts = counts
    }

    enum CodingKeys: String, CodingKey { case name, hash, color, material, bbox, counts }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        hash = (try? c.decodeIfPresent(String.self, forKey: .hash)) ?? ""
        color = (try? c.decodeIfPresent([Float].self, forKey: .color)) ?? [0.72, 0.75, 0.79, 1]
        material = try? c.decodeIfPresent(String.self, forKey: .material)
        bbox = try? c.decodeIfPresent(BBox.self, forKey: .bbox)
        counts = (try? c.decodeIfPresent(MeshCounts.self, forKey: .counts)) ?? MeshCounts()
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        try c.encode(hash, forKey: .hash)
        try c.encode(color, forKey: .color)
        try c.encode(material, forKey: .material)
        try c.encodeIfPresent(bbox, forKey: .bbox)
        try c.encode(counts, forKey: .counts)
    }

    /// sRGB-Farbe als Vektor (Vorgabe hellgrau).
    public var colorVector: SIMD4<Float> {
        guard color.count >= 3 else { return SIMD4(0.72, 0.75, 0.79, 1) }
        return SIMD4(color[0], color[1], color[2], color.count > 3 ? color[3] : 1)
    }

    /// Teil aus dem Kopf eines PART_UPSERT des Kernels (Name, Farbe, Material, Hüllquader, Anzahlen) und dem Hash
    /// seines Netzes.
    public init(partUpsertHeader header: Data, hash: String) throws {
        let h = try JSONDecoder().decode(PartUpsertSummary.self, from: header)
        self.init(
            name: h.name, hash: hash, color: h.color ?? [0.72, 0.75, 0.79, 1], material: h.material, bbox: h.bbox,
            counts: MeshCounts(h.counts))
    }
}

/// Was der Spiegel aus dem Kopf eines PART_UPSERT braucht (der volle Kopf steht in KevCADCore als PartUpsertHeader).
public struct PartUpsertSummary: Decodable, Sendable {
    public var run: Int
    public var name: String
    public var color: [Float]?
    public var material: String?
    public var bbox: BBox?
    public var counts: PartCounts

    enum CodingKeys: String, CodingKey { case run, name, color, material, bbox, counts }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        name = try c.decode(String.self, forKey: .name)
        color = try? c.decodeIfPresent([Float].self, forKey: .color)
        material = try? c.decodeIfPresent(String.self, forKey: .material)
        bbox = try? c.decodeIfPresent(BBox.self, forKey: .bbox)
        counts = try c.decode(PartCounts.self, forKey: .counts)
    }

    /// Kopf und Nutzlast eines PART_UPSERT: Kurzfassung und vollständig geprüfte Geometrie.
    public static func decode(_ frame: Frame) throws -> (summary: PartUpsertSummary, geometry: PartGeometry) {
        let s = try JSONDecoder().decode(PartUpsertSummary.self, from: frame.header)
        let g = try PartGeometry.decode(payload: frame.payload, counts: s.counts)
        return (s, g)
    }
}

// MARK: - Zustand

/// Kamerastand. `rotation` ist ein Quaternion (x, y, z, w) Kamera → Welt, die Kamera blickt entlang ihrer −Z-Achse.
public struct MirrorCamera: Codable, Equatable, Sendable {
    public var rotation: [Float]
    public var pivot: [Float]
    public var distance: Float
    /// Öffnungswinkel in Grad (Perspektive).
    public var fov: Float
    public var ortho: Bool
    /// Sichtbare Höhe in mm bei Parallelprojektion.
    public var orthoScale: Float
    /// Optional: Breite / Höhe der Ansicht am Mac (damit zeigt das iPhone beim Mitfolgen denselben Ausschnitt).
    public var aspect: Float?

    public init(
        rotation: [Float] = [0, 0, 0, 1], pivot: [Float] = [0, 0, 0], distance: Float = 400, fov: Float = 45,
        ortho: Bool = false, orthoScale: Float = 100, aspect: Float? = nil
    ) {
        self.rotation = rotation
        self.pivot = pivot
        self.distance = distance
        self.fov = fov
        self.ortho = ortho
        self.orthoScale = orthoScale
        self.aspect = aspect
    }

    enum CodingKeys: String, CodingKey {
        case rotation, pivot, distance, fov, ortho, aspect
        case orthoScale = "ortho_scale"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let r = (try? c.decodeIfPresent([Float].self, forKey: .rotation)) ?? []
        rotation = r.count == 4 ? r : [0, 0, 0, 1]
        let p = (try? c.decodeIfPresent([Float].self, forKey: .pivot)) ?? []
        pivot = p.count >= 3 ? Array(p.prefix(3)) : [0, 0, 0]
        distance = (try? c.decodeIfPresent(Float.self, forKey: .distance)) ?? 400
        fov = (try? c.decodeIfPresent(Float.self, forKey: .fov)) ?? 45
        ortho = (try? c.decodeIfPresent(Bool.self, forKey: .ortho)) ?? false
        orthoScale = (try? c.decodeIfPresent(Float.self, forKey: .orthoScale)) ?? 100
        aspect = try? c.decodeIfPresent(Float.self, forKey: .aspect)
    }
}

/// Auswahl mit Referenzen wie im Kernel-Protokoll (`Teil`, `Teil#f12`); gültig für den genannten Lauf.
public struct MirrorSelection: Codable, Equatable, Sendable {
    public var run: Int
    public var refs: [String]

    public init(run: Int = 0, refs: [String] = []) {
        self.run = run
        self.refs = refs
    }

    enum CodingKeys: String, CodingKey { case run, refs }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        refs = (try? c.decodeIfPresent([String].self, forKey: .refs)) ?? []
    }
}

/// Hervorhebung (z. B. durch den Agenten). `color` ist sRGB wie bei den Teilen, null = Standardfarbe.
public struct MirrorHighlight: Codable, Equatable, Sendable {
    public var refs: [String]
    public var color: [Float]?
    public var label: String?

    public init(refs: [String], color: [Float]? = nil, label: String? = nil) {
        self.refs = refs
        self.color = color
        self.label = label
    }

    enum CodingKeys: String, CodingKey { case refs, color, label }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        refs = (try? c.decodeIfPresent([String].self, forKey: .refs)) ?? []
        color = try? c.decodeIfPresent([Float].self, forKey: .color)
        label = try? c.decodeIfPresent(String.self, forKey: .label)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(refs, forKey: .refs)
        try c.encode(color, forKey: .color)
        try c.encode(label, forKey: .label)
    }
}

/// Schnittebene: entfernt wird die Seite in Richtung `normal` (bzw. der Achse) ab `offset` mm.
public struct MirrorSection: Codable, Equatable, Sendable {
    /// `x`, `y`, `z` (auch mit Minus), wenn die Ebene achsparallel ist.
    public var axis: String?
    public var normal: [Double]?
    public var offset: Double

    public init(axis: String? = nil, normal: [Double]? = nil, offset: Double = 0) {
        self.axis = axis
        self.normal = normal
        self.offset = offset
    }

    enum CodingKeys: String, CodingKey { case axis, normal, offset }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        axis = try? c.decodeIfPresent(String.self, forKey: .axis)
        normal = try? c.decodeIfPresent([Double].self, forKey: .normal)
        offset = (try? c.decodeIfPresent(Double.self, forKey: .offset)) ?? 0
    }

    /// Normale als Vektor (aus `normal`, sonst aus `axis`).
    public var normalVector: SIMD3<Double>? {
        if let n = normal, n.count >= 3 { return SIMD3(n[0], n[1], n[2]) }
        switch axis?.lowercased() {
        case "x"?: return SIMD3(1, 0, 0)
        case "y"?: return SIMD3(0, 1, 0)
        case "z"?: return SIMD3(0, 0, 1)
        case "-x"?: return SIMD3(-1, 0, 0)
        case "-y"?: return SIMD3(0, -1, 0)
        case "-z"?: return SIMD3(0, 0, -1)
        default: return nil
        }
    }
}

/// Maß oder Anmerkung im Viewer. `points` in Weltkoordinaten (mm).
public struct MirrorMeasure: Codable, Equatable, Sendable {
    public var id: String
    /// Messart (`distance`, `angle`, `face`, …) bzw. Art der Anmerkung (`dimension`, `label`, `arrow`).
    public var kind: String
    public var points: [[Double]]
    public var text: String

    public init(id: String, kind: String, points: [[Double]], text: String) {
        self.id = id
        self.kind = kind
        self.points = points
        self.text = text
    }

    enum CodingKeys: String, CodingKey { case id, kind, points, text }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? ""
        points = (try? c.decodeIfPresent([[Double]].self, forKey: .points)) ?? []
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
    }
}

/// Prüfbefund (kommt mit der Prüfung; bis dahin ist `befunde` leer).
public struct MirrorFinding: Codable, Equatable, Sendable {
    public var art: String
    public var teile: [String]
    public var schwere: String
    /// Ort des Befunds, so wie die Prüfung ihn liefert (Punkt, Hüllquader oder Referenz).
    public var ort: JSONValue?
    public var text: String

    public init(art: String, teile: [String], schwere: String, ort: JSONValue? = nil, text: String) {
        self.art = art
        self.teile = teile
        self.schwere = schwere
        self.ort = ort
        self.text = text
    }

    enum CodingKeys: String, CodingKey { case art, teile, schwere, ort, text }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        art = (try? c.decodeIfPresent(String.self, forKey: .art)) ?? ""
        teile = (try? c.decodeIfPresent([String].self, forKey: .teile)) ?? []
        schwere = (try? c.decodeIfPresent(String.self, forKey: .schwere)) ?? ""
        ort = try? c.decodeIfPresent(JSONValue.self, forKey: .ort)
        text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
    }
}

/// Laufstand.
public struct MirrorRunState: Codable, Equatable, Sendable {
    public var run: Int
    public var laeuft: Bool
    public var schritt: String?
    public var fehler: String?

    public init(run: Int = 0, laeuft: Bool = false, schritt: String? = nil, fehler: String? = nil) {
        self.run = run
        self.laeuft = laeuft
        self.schritt = schritt
        self.fehler = fehler
    }

    enum CodingKeys: String, CodingKey { case run, laeuft, schritt, fehler }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        laeuft = (try? c.decodeIfPresent(Bool.self, forKey: .laeuft)) ?? false
        schritt = try? c.decodeIfPresent(String.self, forKey: .schritt)
        fehler = try? c.decodeIfPresent(String.self, forKey: .fehler)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(run, forKey: .run)
        try c.encode(laeuft, forKey: .laeuft)
        try c.encode(schritt, forKey: .schritt)
        try c.encode(fehler, forKey: .fehler)
    }
}

/// Darstellungsart im Protokoll.
public enum MirrorDisplay: String, Codable, Sendable, CaseIterable {
    case shadedEdges = "shaded_edges"
    case shaded, wireframe, xray
}

/// Voller Zustand der Ansicht (STATE).
public struct MirrorViewState: Equatable, Sendable {
    public var kamera: MirrorCamera
    public var auswahl: MirrorSelection
    public var verborgen: [String]
    public var isoliert: [String]?
    public var hervorgehoben: [MirrorHighlight]
    /// `shaded_edges`, `shaded`, `wireframe` oder `xray` (siehe `MirrorDisplay`).
    public var darstellung: String
    public var schnitt: MirrorSection?
    public var masse: [MirrorMeasure]
    public var befunde: [MirrorFinding]
    public var lauf: MirrorRunState

    public init(
        kamera: MirrorCamera = MirrorCamera(), auswahl: MirrorSelection = MirrorSelection(), verborgen: [String] = [],
        isoliert: [String]? = nil, hervorgehoben: [MirrorHighlight] = [],
        darstellung: String = MirrorDisplay.shadedEdges.rawValue, schnitt: MirrorSection? = nil,
        masse: [MirrorMeasure] = [], befunde: [MirrorFinding] = [], lauf: MirrorRunState = MirrorRunState()
    ) {
        self.kamera = kamera
        self.auswahl = auswahl
        self.verborgen = verborgen
        self.isoliert = isoliert
        self.hervorgehoben = hervorgehoben
        self.darstellung = darstellung
        self.schnitt = schnitt
        self.masse = masse
        self.befunde = befunde
        self.lauf = lauf
    }

    /// Mit einer Änderung (STATE_DELTA) zusammenführen; fehlende Felder bleiben.
    public func applying(_ change: MirrorStateChange) -> MirrorViewState {
        var s = self
        if let v = change.kamera { s.kamera = v }
        if let v = change.auswahl { s.auswahl = v }
        if let v = change.verborgen { s.verborgen = v }
        if let v = change.isoliert { s.isoliert = v }
        if let v = change.hervorgehoben { s.hervorgehoben = v }
        if let v = change.darstellung { s.darstellung = v }
        if let v = change.schnitt { s.schnitt = v }
        if let v = change.masse { s.masse = v }
        if let v = change.befunde { s.befunde = v }
        if let v = change.lauf { s.lauf = v }
        return s
    }
}

/// Felder einer Zustandsänderung (STATE_DELTA); `nil` = unverändert. Bei `isoliert` und `schnitt` heißt `.some(nil)`
/// „ausdrücklich null“ (Isolieren bzw. Schnitt aufgehoben).
public struct MirrorStateChange: Equatable, Sendable {
    public var kamera: MirrorCamera?
    public var auswahl: MirrorSelection?
    public var verborgen: [String]?
    public var isoliert: [String]??
    public var hervorgehoben: [MirrorHighlight]?
    public var darstellung: String?
    public var schnitt: MirrorSection??
    public var masse: [MirrorMeasure]?
    public var befunde: [MirrorFinding]?
    public var lauf: MirrorRunState?

    public init(
        kamera: MirrorCamera? = nil, auswahl: MirrorSelection? = nil, verborgen: [String]? = nil,
        isoliert: [String]?? = nil, hervorgehoben: [MirrorHighlight]? = nil, darstellung: String? = nil,
        schnitt: MirrorSection?? = nil, masse: [MirrorMeasure]? = nil, befunde: [MirrorFinding]? = nil,
        lauf: MirrorRunState? = nil
    ) {
        self.kamera = kamera
        self.auswahl = auswahl
        self.verborgen = verborgen
        self.isoliert = isoliert
        self.hervorgehoben = hervorgehoben
        self.darstellung = darstellung
        self.schnitt = schnitt
        self.masse = masse
        self.befunde = befunde
        self.lauf = lauf
    }

    /// Alle Felder eines vollen Stands.
    public init(full s: MirrorViewState) {
        self.init(
            kamera: s.kamera, auswahl: s.auswahl, verborgen: s.verborgen, isoliert: .some(s.isoliert),
            hervorgehoben: s.hervorgehoben, darstellung: s.darstellung, schnitt: .some(s.schnitt), masse: s.masse,
            befunde: s.befunde, lauf: s.lauf)
    }

    /// Nur die Felder, die sich von `old` zu `new` geändert haben. Die Kamera bleibt außen vor (eigener Rahmen CAMERA).
    public static func between(_ old: MirrorViewState, _ new: MirrorViewState, includeCamera: Bool = false)
        -> MirrorStateChange
    {
        var c = MirrorStateChange()
        if includeCamera && old.kamera != new.kamera { c.kamera = new.kamera }
        if old.auswahl != new.auswahl { c.auswahl = new.auswahl }
        if old.verborgen != new.verborgen { c.verborgen = new.verborgen }
        if old.isoliert != new.isoliert { c.isoliert = .some(new.isoliert) }
        if old.hervorgehoben != new.hervorgehoben { c.hervorgehoben = new.hervorgehoben }
        if old.darstellung != new.darstellung { c.darstellung = new.darstellung }
        if old.schnitt != new.schnitt { c.schnitt = .some(new.schnitt) }
        if old.masse != new.masse { c.masse = new.masse }
        if old.befunde != new.befunde { c.befunde = new.befunde }
        if old.lauf != new.lauf { c.lauf = new.lauf }
        return c
    }

    public var isEmpty: Bool { self == MirrorStateChange() }

    /// Namen der enthaltenen Felder (für Protokoll und Tests).
    public var fieldNames: [String] {
        var out: [String] = []
        if kamera != nil { out.append("kamera") }
        if auswahl != nil { out.append("auswahl") }
        if verborgen != nil { out.append("verborgen") }
        if isoliert != nil { out.append("isoliert") }
        if hervorgehoben != nil { out.append("hervorgehoben") }
        if darstellung != nil { out.append("darstellung") }
        if schnitt != nil { out.append("schnitt") }
        if masse != nil { out.append("masse") }
        if befunde != nil { out.append("befunde") }
        if lauf != nil { out.append("lauf") }
        return out
    }
}

extension MirrorStateChange: Codable {
    enum CodingKeys: String, CodingKey {
        case kamera, auswahl, verborgen, isoliert, hervorgehoben, darstellung, schnitt, masse, befunde, lauf
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kamera = try? c.decodeIfPresent(MirrorCamera.self, forKey: .kamera)
        auswahl = try? c.decodeIfPresent(MirrorSelection.self, forKey: .auswahl)
        verborgen = try? c.decodeIfPresent([String].self, forKey: .verborgen)
        if c.contains(.isoliert) {
            isoliert = (try? c.decodeNil(forKey: .isoliert)) == true ? .some(nil)
                : .some(try? c.decode([String].self, forKey: .isoliert))
        }
        hervorgehoben = try? c.decodeIfPresent([MirrorHighlight].self, forKey: .hervorgehoben)
        darstellung = try? c.decodeIfPresent(String.self, forKey: .darstellung)
        if c.contains(.schnitt) {
            schnitt = (try? c.decodeNil(forKey: .schnitt)) == true ? .some(nil)
                : .some(try? c.decode(MirrorSection.self, forKey: .schnitt))
        }
        masse = try? c.decodeIfPresent([MirrorMeasure].self, forKey: .masse)
        befunde = try? c.decodeIfPresent([MirrorFinding].self, forKey: .befunde)
        lauf = try? c.decodeIfPresent(MirrorRunState.self, forKey: .lauf)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(kamera, forKey: .kamera)
        try c.encodeIfPresent(auswahl, forKey: .auswahl)
        try c.encodeIfPresent(verborgen, forKey: .verborgen)
        if let v = isoliert { try c.encode(v, forKey: .isoliert) }
        try c.encodeIfPresent(hervorgehoben, forKey: .hervorgehoben)
        try c.encodeIfPresent(darstellung, forKey: .darstellung)
        if let v = schnitt { try c.encode(v, forKey: .schnitt) }
        try c.encodeIfPresent(masse, forKey: .masse)
        try c.encodeIfPresent(befunde, forKey: .befunde)
        try c.encodeIfPresent(lauf, forKey: .lauf)
    }
}

extension MirrorViewState {
    /// Voller Stand aus einer Änderung mit allen Feldern (STATE); Fehlendes wird zur Vorgabe.
    public init(full change: MirrorStateChange) {
        self = MirrorViewState().applying(change)
    }
}
