import Foundation

// Nachrichten App → Kernel (PROTOCOL.md). `seq` setzt die Verbindung beim Senden.

public protocol OutgoingMessage: Encodable, Sendable {
    static var type: String { get }
    var seq: Int { get set }
}

/// Anfrage mit `id`; die Antwort trägt `reply_to`.
public protocol OutgoingRequest: OutgoingMessage {
    var id: String { get }
}

extension OutgoingMessage {
    /// JSON-Kopf als Daten (mit `type` und `seq`).
    public func encodedHeader() throws -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.withoutEscapingSlashes]
        return try enc.encode(self)
    }

    public func frame(payload: Data = Data()) throws -> Frame {
        Frame(header: try encodedHeader(), payload: payload)
    }
}

public struct HelloAppMessage: OutgoingMessage {
    public static let type = "HELLO_APP"
    public var seq = 0
    public var appVersion: String
    public var bundleID: String

    public init(appVersion: String, bundleID: String) {
        self.appVersion = appVersion
        self.bundleID = bundleID
    }

    enum CodingKeys: String, CodingKey {
        case type, seq
        case appVersion = "app_version"
        case bundleID = "bundle_id"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(appVersion, forKey: .appVersion)
        try c.encode(bundleID, forKey: .bundleID)
    }
}

public struct ProjectOpenMessage: OutgoingRequest {
    public static let type = "PROJECT_OPEN"
    public var seq = 0
    public var id: String
    public var path: String

    public init(id: String, path: String) {
        self.id = id
        self.path = path
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, path }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(path, forKey: .path)
    }
}

public struct ProjectNewMessage: OutgoingRequest {
    public static let type = "PROJECT_NEW"
    public var seq = 0
    public var id: String
    public var path: String
    public var template: String

    public init(id: String, path: String, template: String) {
        self.id = id
        self.path = path
        self.template = template
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, path, template }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(path, forKey: .path)
        try c.encode(template, forKey: .template)
    }
}

public struct RunRequestMessage: OutgoingRequest {
    public static let type = "RUN_REQ"
    public var seq = 0
    public var id: String
    public var params: [String: JSONValue]?
    public var slowMs: Int

    public init(id: String, params: [String: JSONValue]? = nil, slowMs: Int = 0) {
        self.id = id
        self.params = params
        self.slowMs = slowMs
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, params
        case slowMs = "slow_ms"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(params, forKey: .params)  // null, wenn keine Vorgaben
        try c.encode(slowMs, forKey: .slowMs)
    }
}

public struct MeasureRequestMessage: OutgoingRequest {
    public static let type = "MEASURE_REQ"
    public var seq = 0
    public var id: String
    public var refs: [String]
    public var run: Int
    public var show: Bool

    public init(id: String, refs: [String], run: Int, show: Bool = false) {
        self.id = id
        self.refs = refs
        self.run = run
        self.show = show
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, refs, run, show }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(refs, forKey: .refs)
        try c.encode(run, forKey: .run)
        try c.encode(show, forKey: .show)
    }
}

public struct SelectionMessage: OutgoingMessage {
    public static let type = "SELECTION"
    public var seq = 0
    public var run: Int
    public var refs: [String]

    public init(run: Int, refs: [String]) {
        self.run = run
        self.refs = refs
    }

    enum CodingKeys: String, CodingKey { case type, seq, run, refs }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(run, forKey: .run)
        try c.encode(refs, forKey: .refs)
    }
}

public struct SettingsMessage: OutgoingMessage {
    public static let type = "SETTINGS"
    public var seq = 0
    public var autoRun: Bool
    public var slowMs: Int
    /// Phase 2: Inventar-Regel des offenen Projekts (nil = nicht mitschicken).
    public var inventarRegel: Bool?

    public init(autoRun: Bool, slowMs: Int, inventarRegel: Bool? = nil) {
        self.autoRun = autoRun
        self.slowMs = slowMs
        self.inventarRegel = inventarRegel
    }

    enum CodingKeys: String, CodingKey {
        case type, seq
        case autoRun = "auto_run"
        case slowMs = "slow_ms"
        case inventarRegel = "inventar_regel"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(autoRun, forKey: .autoRun)
        try c.encode(slowMs, forKey: .slowMs)
        try c.encodeIfPresent(inventarRegel, forKey: .inventarRegel)
    }
}

public struct ExportRequestMessage: OutgoingRequest {
    public static let type = "EXPORT_REQ"
    public var seq = 0
    public var id: String
    public var formats: [String]
    public var parts: [String]?

    public init(id: String, formats: [String], parts: [String]? = nil) {
        self.id = id
        self.formats = formats
        self.parts = parts
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, formats, parts }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(formats, forKey: .formats)
        try c.encode(parts, forKey: .parts)
    }
}

public struct ScreenshotResponseMessage: OutgoingMessage {
    public static let type = "SCREENSHOT_RES"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var width: Int
    public var height: Int
    public var camera: JSONValue
    public var mmPerPx: Double?
    public var message: String?

    public init(
        replyTo: String, ok: Bool, width: Int, height: Int, camera: JSONValue, mmPerPx: Double?,
        message: String? = nil
    ) {
        self.replyTo = replyTo
        self.ok = ok
        self.width = width
        self.height = height
        self.camera = camera
        self.mmPerPx = mmPerPx
        self.message = message
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, width, height, camera, message
        case replyTo = "reply_to"
        case mmPerPx = "mm_per_px"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(width, forKey: .width)
        try c.encode(height, forKey: .height)
        try c.encode(camera, forKey: .camera)
        try c.encode(mmPerPx, forKey: .mmPerPx)  // null bei Perspektive
        try c.encodeIfPresent(message, forKey: .message)
    }
}

public struct AckOutMessage: OutgoingMessage {
    public static let type = "ACK"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var message: String?

    public init(replyTo: String, ok: Bool, message: String? = nil) {
        self.replyTo = replyTo
        self.ok = ok
        self.message = message
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, message
        case replyTo = "reply_to"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(message, forKey: .message)
    }
}

/// Fehlerantwort auf eine Anfrage des Kernels.
public struct ErrorOutMessage: OutgoingMessage {
    public static let type = "ERROR"
    public var seq = 0
    public var replyTo: String
    public var message: String

    public init(replyTo: String, message: String) {
        self.replyTo = replyTo
        self.message = message
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, message
        case replyTo = "reply_to"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(message, forKey: .message)
    }
}
