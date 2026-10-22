import Foundation

// Nachrichten des Spiegel-Protokolls (MIRROR.md, Version 1). Rahmen wie im Kernel-Protokoll (Frame, FrameReader);
// jeder Kopf hat `type`, `seq` (je Absender und Verbindung ab 1) und `prio`.

/// Eine Nachricht, die auf den Spiegel-Socket geht. `frame(seq:)` ergänzt `type`, `seq` und `prio`.
public protocol MirrorOutgoing: Encodable, Sendable {
    static var type: String { get }
    var prio: MirrorPriority { get }
}

public enum MirrorFrameError: Error, Equatable, CustomStringConvertible {
    case headerTooLarge(type: String, bytes: Int)
    case payloadTooLarge(type: String, bytes: Int)

    public var description: String {
        switch self {
        case .headerTooLarge(let t, let n): return "\(t): Kopf hat \(n) Byte, erlaubt sind \(MirrorProtocol.maxHeaderBytes)"
        case .payloadTooLarge(let t, let n):
            return "\(t): Nutzlast hat \(n) Byte, erlaubt sind \(MirrorProtocol.maxPayloadBytes)"
        }
    }
}

private struct MirrorEnvelope<M: MirrorOutgoing>: Encodable {
    var message: M
    var seq: Int

    enum Keys: String, CodingKey { case type, seq, prio }

    func encode(to encoder: Encoder) throws {
        try message.encode(to: encoder)
        var c = encoder.container(keyedBy: Keys.self)
        try c.encode(M.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(message.prio, forKey: .prio)
    }
}

extension MirrorOutgoing {
    /// Kopf als JSON (mit `type`, `seq`, `prio`).
    public func headerData(seq: Int) throws -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.withoutEscapingSlashes]
        return try enc.encode(MirrorEnvelope(message: self, seq: seq))
    }

    /// Rahmen für die Leitung; prüft die Obergrenzen aus MIRROR.md (Kopf 16 KB, Nutzlast 64 KB).
    public func frame(seq: Int, payload: Data = Data()) throws -> Frame {
        let header = try headerData(seq: seq)
        if header.count > MirrorProtocol.maxHeaderBytes {
            throw MirrorFrameError.headerTooLarge(type: Self.type, bytes: header.count)
        }
        if payload.count > MirrorProtocol.maxPayloadBytes {
            throw MirrorFrameError.payloadTooLarge(type: Self.type, bytes: payload.count)
        }
        return Frame(header: header, payload: payload)
    }
}

// MARK: - Handschlag

/// HELLO in beiden Richtungen. VoiceBridge → Kev CAD: `protocol`, `version`, `client`, `features`. Kev CAD →
/// VoiceBridge: `version`, `epoche`, `app_build`, `bundle_id`, `features`, `project` (oder null), `agents`.
public struct MirrorHello: MirrorOutgoing, Decodable, Equatable {
    public static let type = "HELLO"
    public var prio: MirrorPriority { .zustand }

    public var protocolName: String?
    public var version: Int
    public var client: String?
    public var features: [String]
    public var epoche: String?
    public var appBuild: Int?
    public var bundleID: String?
    /// Nur von Kev CAD: das offene Projekt (`nil` = kein Projekt, geht als null auf die Leitung).
    public var project: MirrorProject?
    public var agents: [MirrorAgent]?

    /// HELLO der Gegenstelle (VoiceBridge-Mac-App, Simulator-Client, Tests).
    public static func client(_ client: String = "voicebridge-mac", features: [String] = MirrorProtocol.features)
        -> MirrorHello
    {
        MirrorHello(protocolName: MirrorProtocol.name, version: MirrorProtocol.version, client: client, features: features)
    }

    /// HELLO von Kev CAD.
    public static func server(
        epoche: String, appBuild: Int, bundleID: String, project: MirrorProject?, agents: [MirrorAgent],
        features: [String] = MirrorProtocol.features
    ) -> MirrorHello {
        MirrorHello(
            version: MirrorProtocol.version, features: features, epoche: epoche, appBuild: appBuild, bundleID: bundleID,
            project: project, agents: agents)
    }

    public init(
        protocolName: String? = nil, version: Int = MirrorProtocol.version, client: String? = nil,
        features: [String] = [], epoche: String? = nil, appBuild: Int? = nil, bundleID: String? = nil,
        project: MirrorProject? = nil, agents: [MirrorAgent]? = nil
    ) {
        self.protocolName = protocolName
        self.version = version
        self.client = client
        self.features = features
        self.epoche = epoche
        self.appBuild = appBuild
        self.bundleID = bundleID
        self.project = project
        self.agents = agents
    }

    /// Kommt von Kev CAD (trägt eine Epoche).
    public var isServerHello: Bool { epoche != nil }

    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol"
        case version, client, features, epoche, project, agents
        case appBuild = "app_build"
        case bundleID = "bundle_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        protocolName = try? c.decodeIfPresent(String.self, forKey: .protocolName)
        version = (try? c.decodeIfPresent(Int.self, forKey: .version)) ?? 0
        client = try? c.decodeIfPresent(String.self, forKey: .client)
        features = (try? c.decodeIfPresent([String].self, forKey: .features)) ?? []
        epoche = try? c.decodeIfPresent(String.self, forKey: .epoche)
        appBuild = try? c.decodeIfPresent(Int.self, forKey: .appBuild)
        bundleID = try? c.decodeIfPresent(String.self, forKey: .bundleID)
        project = try? c.decodeIfPresent(MirrorProject.self, forKey: .project)
        agents = try? c.decodeIfPresent([MirrorAgent].self, forKey: .agents)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(protocolName, forKey: .protocolName)
        try c.encode(version, forKey: .version)
        try c.encodeIfPresent(client, forKey: .client)
        try c.encode(features, forKey: .features)
        if let epoche {
            // Kev CAD: alle Felder, `project` ausdrücklich null ohne Projekt
            try c.encode(epoche, forKey: .epoche)
            try c.encodeIfPresent(appBuild, forKey: .appBuild)
            try c.encodeIfPresent(bundleID, forKey: .bundleID)
            try c.encode(project, forKey: .project)
            try c.encode(agents ?? [], forKey: .agents)
        }
    }
}

/// Sitzungen, die Kev CAD bedienen; bei jeder Änderung, auch ohne Miete.
public struct MirrorAgentsMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "AGENTS"
    public var prio: MirrorPriority { .zustand }
    public var epoche: String
    public var agents: [MirrorAgent]

    public init(epoche: String, agents: [MirrorAgent]) {
        self.epoche = epoche
        self.agents = agents
    }

    enum CodingKeys: String, CodingKey { case epoche, agents }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        agents = (try? c.decodeIfPresent([MirrorAgent].self, forKey: .agents)) ?? []
    }
}

/// Hinsehen: Miete für den vollen Stand und alle Änderungen danach (gilt nur für diese Verbindung).
public struct MirrorWatch: MirrorOutgoing, Decodable, Equatable {
    public static let type = "WATCH"
    public var prio: MirrorPriority { .zustand }
    public var dauerS: Double
    public var geraet: String?

    public init(dauerS: Double = MirrorProtocol.defaultLeaseSeconds, geraet: String? = nil) {
        self.dauerS = dauerS
        self.geraet = geraet
    }

    enum CodingKeys: String, CodingKey {
        case dauerS = "dauer_s"
        case geraet
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dauerS = (try? c.decodeIfPresent(Double.self, forKey: .dauerS)) ?? MirrorProtocol.defaultLeaseSeconds
        geraet = try? c.decodeIfPresent(String.self, forKey: .geraet)
    }
}

/// Hinsehen beenden.
public struct MirrorUnwatch: MirrorOutgoing, Decodable, Equatable {
    public static let type = "UNWATCH"
    public var prio: MirrorPriority { .zustand }
    public init() {}
    public func encode(to encoder: Encoder) throws {
        _ = encoder.container(keyedBy: MirrorEmptyKeys.self)
    }
}

enum MirrorEmptyKeys: CodingKey {}

// MARK: - Szene

/// Eine Seite der Teileliste (jede höchstens 16 KB Kopf). Der Empfänger ersetzt seine Liste erst, wenn alle Seiten
/// `0 … seiten − 1` da sind; `run`, `bbox` und `epoche` stehen in jeder Seite gleich.
public struct MirrorScenePage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "SCENE"
    public var prio: MirrorPriority { .szene }
    public var epoche: String
    /// Nur `name` (nie der Pfad); nil = kein Projekt.
    public var project: MirrorProject?
    public var run: Int
    public var bbox: BBox?
    public var seite: Int
    public var seiten: Int
    public var parts: [MirrorPart]

    public init(
        epoche: String, project: MirrorProject?, run: Int, bbox: BBox?, seite: Int, seiten: Int, parts: [MirrorPart]
    ) {
        self.epoche = epoche
        self.project = project?.withoutPath
        self.run = run
        self.bbox = bbox
        self.seite = seite
        self.seiten = seiten
        self.parts = parts
    }

    enum CodingKeys: String, CodingKey { case epoche, project, run, bbox, seite, seiten, parts }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        project = try? c.decodeIfPresent(MirrorProject.self, forKey: .project)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        bbox = try? c.decodeIfPresent(BBox.self, forKey: .bbox)
        seite = (try? c.decodeIfPresent(Int.self, forKey: .seite)) ?? 0
        seiten = (try? c.decodeIfPresent(Int.self, forKey: .seiten)) ?? 1
        parts = (try? c.decodeIfPresent([MirrorPart].self, forKey: .parts)) ?? []
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(project?.withoutPath, forKey: .project)
        try c.encode(run, forKey: .run)
        try c.encode(bbox, forKey: .bbox)
        try c.encode(seite, forKey: .seite)
        try c.encode(seiten, forKey: .seiten)
        try c.encode(parts, forKey: .parts)
    }

    /// Teileliste in Seiten so aufteilen, dass jeder Kopf unter 16 KB bleibt (mit Reserve für die übrigen Felder).
    public static func pages(
        epoche: String, project: MirrorProject?, run: Int, bbox: BBox?, parts: [MirrorPart],
        limit: Int = MirrorProtocol.maxHeaderBytes - 1024
    ) -> [MirrorScenePage] {
        let enc = JSONEncoder()
        var groups: [[MirrorPart]] = [[]]
        var size = 0
        for p in parts {
            let n = ((try? enc.encode(p))?.count ?? 512) + 1
            if !groups[groups.count - 1].isEmpty && size + n > limit {
                groups.append([])
                size = 0
            }
            groups[groups.count - 1].append(p)
            size += n
        }
        return groups.enumerated().map { i, g in
            MirrorScenePage(
                epoche: epoche, project: project, run: run, bbox: bbox, seite: i, seiten: groups.count, parts: g)
        }
    }
}

/// Ein Teil dazu (`upsert`, mit allen Feldern des Teils) oder weg (`remove`, nur `name`).
public struct MirrorPartMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "PART"
    public var prio: MirrorPriority { .szene }

    public enum Op: String, Codable, Sendable { case upsert, remove }

    public var epoche: String
    public var op: Op
    public var run: Int
    /// Bei `upsert` das Teil.
    public var part: MirrorPart?
    /// Name des Teils (bei `upsert` gleich `part.name`).
    public var name: String

    public static func upsert(epoche: String, run: Int, part: MirrorPart) -> MirrorPartMessage {
        MirrorPartMessage(epoche: epoche, op: .upsert, run: run, part: part, name: part.name)
    }

    public static func remove(epoche: String, run: Int, name: String) -> MirrorPartMessage {
        MirrorPartMessage(epoche: epoche, op: .remove, run: run, part: nil, name: name)
    }

    public init(epoche: String, op: Op, run: Int, part: MirrorPart?, name: String) {
        self.epoche = epoche
        self.op = op
        self.run = run
        self.part = part
        self.name = name
    }

    enum CodingKeys: String, CodingKey { case epoche, op, run, name }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        op = (try? c.decodeIfPresent(Op.self, forKey: .op)) ?? .upsert
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        part = op == .upsert ? try MirrorPart(from: decoder) : nil
    }

    public func encode(to encoder: Encoder) throws {
        if op == .upsert, let part { try part.encode(to: encoder) }
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(op, forKey: .op)
        try c.encode(run, forKey: .run)
        if op == .remove { try c.encode(name, forKey: .name) }
    }
}

/// Netze anfordern, die dem Empfänger fehlen.
public struct MirrorMeshRequest: MirrorOutgoing, Decodable, Equatable {
    public static let type = "MESH_REQ"
    public var prio: MirrorPriority { .zustand }
    public var hashes: [String]

    public init(hashes: [String]) { self.hashes = hashes }

    enum CodingKeys: String, CodingKey { case hashes }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hashes = (try? c.decodeIfPresent([String].self, forKey: .hashes)) ?? []
    }
}

/// Kopf eines Netzblocks; die Nutzlast ist der Block (höchstens 64 KB des gepackten Stroms).
public struct MirrorMeshBlock: MirrorOutgoing, Decodable, Equatable, Hashable {
    public static let type = "MESH"
    public var prio: MirrorPriority { .netz }
    public var hash: String
    public var format: String
    public var block: Int
    public var blocks: Int
    /// Länge des ganzen gepackten Stroms.
    public var bytes: Int
    /// Länge ungepackt.
    public var rohBytes: Int

    public init(hash: String, format: String = KcadMesh.format, block: Int, blocks: Int, bytes: Int, rohBytes: Int) {
        self.hash = hash
        self.format = format
        self.block = block
        self.blocks = blocks
        self.bytes = bytes
        self.rohBytes = rohBytes
    }

    enum CodingKeys: String, CodingKey {
        case hash, format, block, blocks, bytes
        case rohBytes = "roh_bytes"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hash = (try? c.decodeIfPresent(String.self, forKey: .hash)) ?? ""
        format = (try? c.decodeIfPresent(String.self, forKey: .format)) ?? KcadMesh.format
        block = (try? c.decodeIfPresent(Int.self, forKey: .block)) ?? 0
        blocks = (try? c.decodeIfPresent(Int.self, forKey: .blocks)) ?? 1
        bytes = (try? c.decodeIfPresent(Int.self, forKey: .bytes)) ?? 0
        rohBytes = (try? c.decodeIfPresent(Int.self, forKey: .rohBytes)) ?? 0
    }
}

// MARK: - Zustand

/// Voller Zustand nach WATCH (und nach einem Epochenwechsel).
public struct MirrorStateMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "STATE"
    public var prio: MirrorPriority { .zustand }
    public var epoche: String
    public var rev: Int
    public var state: MirrorViewState

    public init(epoche: String, rev: Int, state: MirrorViewState) {
        self.epoche = epoche
        self.rev = rev
        self.state = state
    }

    enum CodingKeys: String, CodingKey { case epoche, rev }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        rev = (try? c.decodeIfPresent(Int.self, forKey: .rev)) ?? 0
        state = MirrorViewState(full: try MirrorStateChange(from: decoder))
    }

    public func encode(to encoder: Encoder) throws {
        try MirrorStateChange(full: state).encode(to: encoder)
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(rev, forKey: .rev)
    }
}

/// Nur geänderte Felder des Zustands.
public struct MirrorStateDeltaMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "STATE_DELTA"
    public var prio: MirrorPriority { .zustand }
    public var epoche: String
    public var rev: Int
    public var quelle: MirrorSource
    public var change: MirrorStateChange

    public init(epoche: String, rev: Int, quelle: MirrorSource, change: MirrorStateChange) {
        self.epoche = epoche
        self.rev = rev
        self.quelle = quelle
        self.change = change
    }

    enum CodingKeys: String, CodingKey { case epoche, rev, quelle }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        rev = (try? c.decodeIfPresent(Int.self, forKey: .rev)) ?? 0
        quelle = (try? c.decodeIfPresent(MirrorSource.self, forKey: .quelle)) ?? .mac
        change = try MirrorStateChange(from: decoder)
    }

    public func encode(to encoder: Encoder) throws {
        try change.encode(to: encoder)
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(rev, forKey: .rev)
        try c.encode(quelle, forKey: .quelle)
    }
}

/// Kamerastand (latest-only, höchstens 40 je Sekunde).
public struct MirrorCameraMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "CAMERA"
    public var prio: MirrorPriority { .kamera }
    public var epoche: String
    public var rev: Int
    public var kamera: MirrorCamera
    public var quelle: MirrorSource

    public init(epoche: String, rev: Int, kamera: MirrorCamera, quelle: MirrorSource) {
        self.epoche = epoche
        self.rev = rev
        self.kamera = kamera
        self.quelle = quelle
    }

    enum CodingKeys: String, CodingKey { case epoche, rev, kamera, quelle }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        rev = (try? c.decodeIfPresent(Int.self, forKey: .rev)) ?? 0
        kamera = (try? c.decodeIfPresent(MirrorCamera.self, forKey: .kamera)) ?? MirrorCamera()
        quelle = (try? c.decodeIfPresent(MirrorSource.self, forKey: .quelle)) ?? .mac
    }
}

// MARK: - Befehle

/// Befehl vom iPhone. Alle außer `kamera` bekommen ein CMD_RES.
public struct MirrorCommand: MirrorOutgoing, Decodable, Equatable {
    public static let type = "CMD"
    public var prio: MirrorPriority { op == Op.kamera.rawValue ? .kamera : .zustand }

    public enum Op: String, Sendable, CaseIterable {
        case kamera, auswahl, sichtbarkeit, fokus, ansicht, darstellung, einpassen
        /// Version 1.1: Kevins Entscheidung zu einem Vorschlag (MirrorFreigabe.swift)
        case freigabe
    }

    public var id: String
    public var op: String
    public var args: JSONValue

    public init(id: String, op: String, args: JSONValue = .object([:])) {
        self.id = id
        self.op = op
        self.args = args
    }

    public var knownOp: Op? { Op(rawValue: op) }

    /// Kamera am Mac setzen (nur im Modus „Mitfolgen“); latest-only, ohne Antwort.
    public static func kamera(id: String, _ kamera: MirrorCamera) -> MirrorCommand {
        MirrorCommand(id: id, op: Op.kamera.rawValue, args: .object(["kamera": JSONValue.encoded(kamera)]))
    }

    /// Auswahl wie ein Klick im Viewer; `modus` `setzen`, `dazu` oder `weg`.
    public static func auswahl(id: String, refs: [String], run: Int, modus: String = "setzen") -> MirrorCommand {
        MirrorCommand(
            id: id, op: Op.auswahl.rawValue,
            args: .object(["refs": .array(refs.map(JSONValue.string)), "run": .number(Double(run)), "modus": .string(modus)]))
    }

    /// `mode` `show`, `hide`, `isolate` oder `show_all`.
    public static func sichtbarkeit(id: String, mode: String, refs: [String] = []) -> MirrorCommand {
        MirrorCommand(
            id: id, op: Op.sichtbarkeit.rawValue,
            args: .object(["mode": .string(mode), "refs": .array(refs.map(JSONValue.string))]))
    }

    public static func fokus(id: String, refs: [String]) -> MirrorCommand {
        MirrorCommand(id: id, op: Op.fokus.rawValue, args: .object(["refs": .array(refs.map(JSONValue.string))]))
    }

    /// `standard` wie im Kernel-Protokoll (`top`, `front`, `iso`, …), `projection` `perspective` oder `orthographic`.
    public static func ansicht(id: String, standard: String?, projection: String? = nil) -> MirrorCommand {
        MirrorCommand(
            id: id, op: Op.ansicht.rawValue,
            args: .object(["standard": standard.map(JSONValue.string) ?? .null,
                           "projection": projection.map(JSONValue.string) ?? .null]))
    }

    public static func darstellung(id: String, display: String) -> MirrorCommand {
        MirrorCommand(id: id, op: Op.darstellung.rawValue, args: .object(["display": .string(display)]))
    }

    /// Kev CAD passt die Kamera selbst ein (wie Pos1 bzw. „.“ am Mac); ohne `refs` auf alles.
    public static func einpassen(id: String, refs: [String]? = nil) -> MirrorCommand {
        MirrorCommand(
            id: id, op: Op.einpassen.rawValue,
            args: .object(refs.map { ["refs": .array($0.map(JSONValue.string))] } ?? [:]))
    }

    // Lesen der Argumente
    public var refs: [String] { args["refs"]?.stringList ?? args["refs"]?.stringValue.map { [$0] } ?? [] }
    public var camera: MirrorCamera? { args["kamera"].flatMap { try? $0.decoded(MirrorCamera.self) } }

    enum CodingKeys: String, CodingKey { case id, op, args }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        op = (try? c.decodeIfPresent(String.self, forKey: .op)) ?? ""
        args = (try? c.decodeIfPresent(JSONValue.self, forKey: .args)) ?? .object([:])
    }
}

/// Antwort auf einen Befehl.
public struct MirrorCommandResult: MirrorOutgoing, Decodable, Equatable {
    public static let type = "CMD_RES"
    public var prio: MirrorPriority { .zustand }
    public var replyTo: String
    public var ok: Bool
    public var fehler: String?
    /// Version 1.1, nur bei CMD `freigabe`: Ergebnis als Wert (MirrorFreigabeStatus); sonst nil und weggelassen.
    public var status: String?

    public init(replyTo: String, ok: Bool, fehler: String? = nil, status: String? = nil) {
        self.replyTo = replyTo
        self.ok = ok
        self.fehler = fehler
        self.status = status
    }

    enum CodingKeys: String, CodingKey {
        case replyTo = "reply_to"
        case ok, fehler, status
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        replyTo = (try? c.decodeIfPresent(String.self, forKey: .replyTo)) ?? ""
        ok = (try? c.decodeIfPresent(Bool.self, forKey: .ok)) ?? false
        fehler = try? c.decodeIfPresent(String.self, forKey: .fehler)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(fehler, forKey: .fehler)
        try c.encodeIfPresent(status, forKey: .status)
    }
}

// MARK: - Lesen

/// Gemeinsame Felder jedes Spiegel-Kopfes, ohne den Rest zu dekodieren (zum Weiterreichen nach Vorrang).
public struct MirrorEnvelopeInfo: Decodable, Sendable, Equatable {
    public var type: String
    public var seq: Int?
    public var prio: MirrorPriority?

    enum CodingKeys: String, CodingKey { case type, seq, prio }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decode(String.self, forKey: .type)
        seq = try? c.decodeIfPresent(Int.self, forKey: .seq)
        prio = try? c.decodeIfPresent(MirrorPriority.self, forKey: .prio)
    }

    public static func peek(_ header: Data) throws -> MirrorEnvelopeInfo {
        try JSONDecoder().decode(MirrorEnvelopeInfo.self, from: header)
    }
}

/// Gelesene Spiegel-Nachricht.
public enum MirrorMessage: Sendable, Equatable {
    case hello(MirrorHello)
    case agents(MirrorAgentsMessage)
    case watch(MirrorWatch)
    case unwatch
    case scene(MirrorScenePage)
    case part(MirrorPartMessage)
    case meshRequest(MirrorMeshRequest)
    /// Netzblock mit seiner Nutzlast.
    case mesh(MirrorMeshBlock, Data)
    case state(MirrorStateMessage)
    case stateDelta(MirrorStateDeltaMessage)
    case camera(MirrorCameraMessage)
    case command(MirrorCommand)
    case commandResult(MirrorCommandResult)
    /// Version 1.1: offene Freigabe-Anfrage (Kev CAD → VoiceBridge).
    case freigabe(MirrorFreigabeMessage)
    /// Version 1.1: Eintrag oder Anfrage erledigt (Kev CAD → VoiceBridge).
    case freigabeEnde(MirrorFreigabeEndeMessage)
    /// Typ, den diese Version nicht kennt: verwerfen und protokollieren, nicht beantworten.
    case unknown(type: String)

    public var typeName: String {
        switch self {
        case .hello: return MirrorHello.type
        case .agents: return MirrorAgentsMessage.type
        case .watch: return MirrorWatch.type
        case .unwatch: return MirrorUnwatch.type
        case .scene: return MirrorScenePage.type
        case .part: return MirrorPartMessage.type
        case .meshRequest: return MirrorMeshRequest.type
        case .mesh: return MirrorMeshBlock.type
        case .state: return MirrorStateMessage.type
        case .stateDelta: return MirrorStateDeltaMessage.type
        case .camera: return MirrorCameraMessage.type
        case .command: return MirrorCommand.type
        case .commandResult: return MirrorCommandResult.type
        case .freigabe: return MirrorFreigabeMessage.type
        case .freigabeEnde: return MirrorFreigabeEndeMessage.type
        case .unknown(let t): return t
        }
    }

    public static func decode(_ frame: Frame) throws -> MirrorMessage {
        let dec = JSONDecoder()
        let h = frame.header
        let env = try dec.decode(MirrorEnvelopeInfo.self, from: h)
        switch env.type {
        case MirrorHello.type: return .hello(try dec.decode(MirrorHello.self, from: h))
        case MirrorAgentsMessage.type: return .agents(try dec.decode(MirrorAgentsMessage.self, from: h))
        case MirrorWatch.type: return .watch(try dec.decode(MirrorWatch.self, from: h))
        case MirrorUnwatch.type: return .unwatch
        case MirrorScenePage.type: return .scene(try dec.decode(MirrorScenePage.self, from: h))
        case MirrorPartMessage.type: return .part(try dec.decode(MirrorPartMessage.self, from: h))
        case MirrorMeshRequest.type: return .meshRequest(try dec.decode(MirrorMeshRequest.self, from: h))
        case MirrorMeshBlock.type: return .mesh(try dec.decode(MirrorMeshBlock.self, from: h), frame.payload)
        case MirrorStateMessage.type: return .state(try dec.decode(MirrorStateMessage.self, from: h))
        case MirrorStateDeltaMessage.type: return .stateDelta(try dec.decode(MirrorStateDeltaMessage.self, from: h))
        case MirrorCameraMessage.type: return .camera(try dec.decode(MirrorCameraMessage.self, from: h))
        case MirrorCommand.type: return .command(try dec.decode(MirrorCommand.self, from: h))
        case MirrorCommandResult.type: return .commandResult(try dec.decode(MirrorCommandResult.self, from: h))
        case MirrorFreigabeMessage.type: return .freigabe(try dec.decode(MirrorFreigabeMessage.self, from: h))
        case MirrorFreigabeEndeMessage.type:
            return .freigabeEnde(try dec.decode(MirrorFreigabeEndeMessage.self, from: h))
        default: return .unknown(type: env.type)
        }
    }
}

// MARK: - JSONValue und Codable

extension JSONValue {
    /// Einen Codable-Wert als JSONValue (z. B. die Kamera in `CMD.args`).
    public static func encoded<T: Encodable>(_ value: T) -> JSONValue {
        guard let data = try? JSONEncoder().encode(value),
            let v = try? JSONDecoder().decode(JSONValue.self, from: data)
        else { return .null }
        return v
    }

    /// Den Wert als Codable-Typ lesen.
    public func decoded<T: Decodable>(_ type: T.Type) throws -> T {
        try JSONDecoder().decode(T.self, from: JSONEncoder().encode(self))
    }
}
