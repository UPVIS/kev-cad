import Foundation
import simd

// Phase 5 (Strang ANI): Nachrichten der Animation, PROTOCOL.md Abschnitt „Phase 5: Animation“. Alles kommt gebündelt als
// `KernelMessage.animation(AnimationMessage)`, damit Messages.swift und AppController nur eine Stelle dafür brauchen.

/// Sichtbarkeit von Teilen über die Zeit (`sichtbar` in ANIM_DEF).
public struct AnimationVisibility: Equatable, Sendable {
    public var parts: [String]
    /// (Zeit, an), nach Zeit sortiert.
    public var events: [(time: Double, on: Bool)]

    public init(parts: [String], events: [(time: Double, on: Bool)]) {
        self.parts = parts
        self.events = events.sorted { $0.time < $1.time }
    }

    /// Zur Zeit `t`: letzter Eintrag mit Zeit ≤ t; davor das Gegenteil des ersten.
    public func isVisible(at t: Double) -> Bool {
        guard let first = events.first else { return true }
        var state = !first.on
        for e in events where t + 1e-9 >= e.time { state = e.on }
        return state
    }

    public static func == (a: Self, b: Self) -> Bool {
        a.parts == b.parts && a.events.count == b.events.count
            && zip(a.events, b.events).allSatisfy { $0.time == $1.time && $0.on == $1.on }
    }
}

/// Eine Kamerastellung der Kamerafahrt.
public struct AnimationCameraKey: Equatable, Sendable {
    public var position: SIMD3<Float>
    public var target: SIMD3<Float>
    /// Vertikaler Bildwinkel in Grad, nil = unverändert.
    public var fieldOfView: Float?
}

/// Eine Animation aus ANIM_DEF: Lagen je Bild und Teil, Kamerafahrt, Sichtbarkeiten.
public struct AnimationClip: Sendable {
    public var name: String
    public var run: Int
    public var duration: Double
    public var fps: Double
    public var frameCount: Int
    public var parts: [String]
    /// N × P × 12 Werte (obere drei Zeilen jeder Matrix spaltenweise), wie in der Nutzlast.
    public var matrices: [Float]
    /// N × 7 Werte (Lage, Ziel, Bildwinkel oder 0) oder leer.
    public var camera: [Float]
    public var visibility: [AnimationVisibility]
    public var isDefault: Bool
    public var warnings: [String]
    public var trackCount: Int

    public init(
        name: String, run: Int = 0, duration: Double, fps: Double, frameCount: Int, parts: [String],
        matrices: [Float], camera: [Float] = [], visibility: [AnimationVisibility] = [], isDefault: Bool = false,
        warnings: [String] = [], trackCount: Int = 0
    ) {
        self.name = name
        self.run = run
        self.duration = duration
        self.fps = fps
        self.frameCount = frameCount
        self.parts = parts
        self.matrices = matrices
        self.camera = camera
        self.visibility = visibility
        self.isDefault = isDefault
        self.warnings = warnings
        self.trackCount = trackCount
    }

    public var hasCamera: Bool { camera.count >= frameCount * 7 && frameCount > 0 }
    public var lastFrame: Int { max(0, frameCount - 1) }

    /// Zeit des Bildes `k`.
    public func time(ofFrame k: Int) -> Double { min(Double(max(0, k)) / fps, duration) }

    /// Nächstes Bild zur Zeit `t`.
    public func frame(at t: Double) -> Int { min(lastFrame, max(0, Int((t * fps).rounded()))) }

    /// Lage des Teils `j` im Bild `k`.
    public func matrix(frame k: Int, part j: Int) -> simd_float4x4 {
        let o = (min(max(k, 0), lastFrame) * parts.count + j) * 12
        guard o + 12 <= matrices.count else { return matrix_identity_float4x4 }
        let m = matrices
        return simd_float4x4(
            SIMD4(m[o], m[o + 1], m[o + 2], 0), SIMD4(m[o + 3], m[o + 4], m[o + 5], 0),
            SIMD4(m[o + 6], m[o + 7], m[o + 8], 0), SIMD4(m[o + 9], m[o + 10], m[o + 11], 1))
    }

    /// Lage aller bewegten Teile zur Zeit `t`, zwischen zwei Bildern weich übergeblendet, damit das Abspielen auch bei
    /// 120 Hz flüssig ist: Drehung über Quaternionen, dazu fährt die Mitte des Teils (`pivots`, Ruhelage) gerade von
    /// Bild zu Bild. Ohne Mitte wird die Verschiebung linear gemischt (richtig nur für Drehungen um den Ursprung).
    public func pose(at t: Double, pivots: [String: SIMD3<Float>] = [:]) -> [String: simd_float4x4] {
        var out: [String: simd_float4x4] = [:]
        out.reserveCapacity(parts.count)
        guard frameCount > 0 else { return out }
        let x = min(max(t, 0), duration) * fps
        let k0 = min(lastFrame, Int(x.rounded(.down)))
        let k1 = min(lastFrame, k0 + 1)
        let u = Float(min(1, max(0, x - Double(k0))))
        for (j, name) in parts.enumerated() {
            let a = matrix(frame: k0, part: j)
            if k1 == k0 || u < 1e-4 {
                out[name] = a
            } else {
                out[name] = Self.blend(a, matrix(frame: k1, part: j), u, pivot: pivots[name])
            }
        }
        return out
    }

    static func blend(_ a: simd_float4x4, _ b: simd_float4x4, _ u: Float, pivot: SIMD3<Float>? = nil) -> simd_float4x4 {
        func rot(_ m: simd_float4x4) -> simd_float3x3 {
            simd_float3x3(
                SIMD3(m.columns.0.x, m.columns.0.y, m.columns.0.z), SIMD3(m.columns.1.x, m.columns.1.y, m.columns.1.z),
                SIMD3(m.columns.2.x, m.columns.2.y, m.columns.2.z))
        }
        let qa = simd_quatf(rot(a)), qb = simd_quatf(rot(b))
        let q = simd_slerp(qa, qb, u)
        let r = simd_float3x3(q)
        let ta = SIMD3(a.columns.3.x, a.columns.3.y, a.columns.3.z)
        let tb = SIMD3(b.columns.3.x, b.columns.3.y, b.columns.3.z)
        var tr = ta + (tb - ta) * u
        if let p = pivot {  // Mitte des Teils gerade führen, Drehung um die Mitte
            let pa = rot(a) * p + ta, pb = rot(b) * p + tb
            tr = pa + (pb - pa) * u - r * p
        }
        return simd_float4x4(SIMD4(r.columns.0, 0), SIMD4(r.columns.1, 0), SIMD4(r.columns.2, 0), SIMD4(tr, 1))
    }

    /// Kamera der Kamerafahrt zur Zeit `t` (nil ohne Kamerafahrt).
    public func cameraKey(at t: Double) -> AnimationCameraKey? {
        guard hasCamera else { return nil }
        let x = min(max(t, 0), duration) * fps
        let k0 = min(lastFrame, Int(x.rounded(.down)))
        let k1 = min(lastFrame, k0 + 1)
        let u = Float(min(1, max(0, x - Double(k0))))
        func row(_ k: Int) -> [Float] { Array(camera[(k * 7)..<(k * 7 + 7)]) }
        let a = row(k0), b = row(k1)
        let v = zip(a, b).map { $0 + ($1 - $0) * u }
        return AnimationCameraKey(
            position: SIMD3(v[0], v[1], v[2]), target: SIMD3(v[3], v[4], v[5]), fieldOfView: v[6] > 0 ? v[6] : nil)
    }

    /// Teile, die zur Zeit `t` ausgeblendet sind.
    public func hiddenParts(at t: Double) -> Set<String> {
        var out = Set<String>()
        for v in visibility where !v.isVisible(at: t) { out.formUnion(v.parts) }
        return out
    }

    /// Liest ANIM_DEF (Kopf und Nutzlast).
    public static func decode(header: Data, payload: Data) throws -> AnimationClip {
        let raw = try JSONDecoder().decode(JSONValue.self, from: header)
        guard case .object(let o) = raw, case .string(let name)? = o["name"] else {
            throw AnimationDecodeError(message: "ANIM_DEF ohne Namen")
        }
        let parts = o["teile"]?.arrayValue?.compactMap(\.stringValue) ?? []
        let frames = o["bilder"]?.intValue ?? 0
        let hasCamera = o["kamera"]?.boolValue ?? false
        let need = frames * parts.count * 12 + (hasCamera ? frames * 7 : 0)
        let floats = payload.count / 4
        guard floats >= need, frames >= 0 else {
            throw AnimationDecodeError(
                message: "ANIM_DEF \(name): Nutzlast hat \(payload.count) Byte, erwartet \(need * 4)")
        }
        var values = [Float](repeating: 0, count: floats)
        values.withUnsafeMutableBytes { dst in
            payload.withUnsafeBytes { src in dst.copyMemory(from: UnsafeRawBufferPointer(rebasing: src[0..<(floats * 4)])) }
        }
        // little-endian auf dem Draht; Apple-Rechner sind little-endian
        let nm = frames * parts.count * 12
        var vis: [AnimationVisibility] = []
        for entry in o["sichtbar"]?.arrayValue ?? [] {
            guard case .object(let e) = entry else { continue }
            let ps = e["teile"]?.arrayValue?.compactMap(\.stringValue) ?? []
            let ev: [(time: Double, on: Bool)] = (e["zeiten"]?.arrayValue ?? []).compactMap { item in
                guard let pair = item.arrayValue, pair.count >= 2, let t = pair[0].doubleValue,
                    let on = pair[1].boolValue
                else { return nil }
                return (t, on)
            }
            vis.append(AnimationVisibility(parts: ps, events: ev))
        }
        return AnimationClip(
            name: name, run: o["run"]?.intValue ?? 0, duration: o["dauer"]?.doubleValue ?? 0,
            fps: max(1, o["fps"]?.doubleValue ?? 30), frameCount: frames, parts: parts,
            matrices: Array(values[0..<nm]), camera: hasCamera ? Array(values[nm..<(nm + frames * 7)]) : [],
            visibility: vis, isDefault: o["standard"]?.boolValue ?? false,
            warnings: o["warnungen"]?.arrayValue?.compactMap(\.stringValue) ?? [],
            trackCount: o["spuren"]?.intValue ?? 0)
    }
}

public struct AnimationDecodeError: Error, CustomStringConvertible {
    public var message: String
    public var description: String { message }
}

/// Eine gemeldete Kollision (Zeitspanne eines Teilpaars).
public struct AnimationCollision: Identifiable, Equatable, Sendable {
    public var parts: [String]
    public var from: Double
    public var to: Double
    /// Zeit und Bild der stärksten Durchdringung.
    public var time: Double
    public var frame: Int
    public var depth: Double
    public var volume: Double
    public var location: SIMD3<Float>?
    public var frames: [Int]

    public var id: String { parts.joined(separator: "\u{1F}") + "@\(from)" }

    public init(
        parts: [String], from: Double, to: Double, time: Double, frame: Int, depth: Double, volume: Double,
        location: SIMD3<Float>? = nil, frames: [Int] = []
    ) {
        self.parts = parts
        self.from = from
        self.to = to
        self.time = time
        self.frame = frame
        self.depth = depth
        self.volume = volume
        self.location = location
        self.frames = frames
    }

    /// Gilt die Kollision im Bild `k`? (zwischen den geprüften Bildern der Spanne)
    public func covers(time t: Double, fps: Double) -> Bool {
        let half = 0.5 / max(fps, 1)
        return t >= from - half && t <= to + half
    }
}

public struct AnimationCollisionsMessage: Sendable {
    public var name: String
    public var run: Int
    public var collisions: [AnimationCollision]
    public var checkedFrames: Int
    public var step: Int
    public var milliseconds: Double
    public var replyTo: String?

    static func decode(_ o: [String: JSONValue]) -> AnimationCollisionsMessage {
        var list: [AnimationCollision] = []
        for item in o["kollisionen"]?.arrayValue ?? [] {
            guard case .object(let c) = item else { continue }
            let loc = c["ort"]?.arrayValue?.compactMap(\.doubleValue)
            list.append(
                AnimationCollision(
                    parts: c["teile"]?.arrayValue?.compactMap(\.stringValue) ?? [],
                    from: c["von"]?.doubleValue ?? 0, to: c["bis"]?.doubleValue ?? 0, time: c["zeit"]?.doubleValue ?? 0,
                    frame: c["bild"]?.intValue ?? 0, depth: c["tiefe"]?.doubleValue ?? 0,
                    volume: c["volumen"]?.doubleValue ?? 0,
                    location: loc.flatMap { $0.count >= 3 ? SIMD3(Float($0[0]), Float($0[1]), Float($0[2])) : nil },
                    frames: c["bilder"]?.arrayValue?.compactMap { $0.intValue } ?? []))
        }
        let g = o["geprueft"]?.objectValue ?? [:]
        return AnimationCollisionsMessage(
            name: o["name"]?.stringValue ?? "", run: o["run"]?.intValue ?? 0, collisions: list,
            checkedFrames: g["geprueft_bilder"]?.intValue ?? 0,
            step: g["schritt"]?.intValue ?? 0, milliseconds: g["ms"]?.doubleValue ?? 0,
            replyTo: o["reply_to"]?.stringValue)
    }
}

/// ANIM_PLAY
public struct AnimationPlayCommand: Sendable {
    public var id: String
    public var name: String?
    public var on: Bool
    public var loop: Bool
    public var speed: Double
    public var fromStart: Bool
}

/// ANIM_SEEK
public struct AnimationSeekCommand: Sendable {
    public var id: String
    public var name: String?
    public var time: Double
}

/// ANIM_VIDEO_REQ
public struct AnimationVideoCommand: Sendable {
    public var id: String
    public var name: String?
    public var width: Int
    public var height: Int
    public var fps: Double?
    public var camera: String?
    public var format: String
    public var path: String
}

/// Alle Animationsnachrichten des Kernels.
public enum AnimationMessage: Sendable {
    case definition(AnimationClip)
    case remove(String)
    case collisions(AnimationCollisionsMessage)
    case play(AnimationPlayCommand)
    case seek(AnimationSeekCommand)
    case video(AnimationVideoCommand)

    public static let types: Set<String> = [
        "ANIM_DEF", "ANIM_REMOVE", "ANIM_COLLISIONS", "ANIM_PLAY", "ANIM_SEEK", "ANIM_VIDEO_REQ",
    ]

    public var typeName: String {
        switch self {
        case .definition: return "ANIM_DEF"
        case .remove: return "ANIM_REMOVE"
        case .collisions: return "ANIM_COLLISIONS"
        case .play: return "ANIM_PLAY"
        case .seek: return "ANIM_SEEK"
        case .video: return "ANIM_VIDEO_REQ"
        }
    }

    public var replyTo: String? {
        if case .collisions(let c) = self { return c.replyTo }
        return nil
    }

    public static func decode(type: String, frame: Frame) throws -> AnimationMessage {
        if type == "ANIM_DEF" { return .definition(try AnimationClip.decode(header: frame.header, payload: frame.payload)) }
        let raw = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        guard case .object(let o) = raw else { throw AnimationDecodeError(message: "\(type): Kopf ist kein Objekt") }
        let id = o["id"]?.stringValue ?? ""
        switch type {
        case "ANIM_REMOVE":
            return .remove(o["name"]?.stringValue ?? "")
        case "ANIM_COLLISIONS":
            return .collisions(AnimationCollisionsMessage.decode(o))
        case "ANIM_PLAY":
            return .play(
                AnimationPlayCommand(
                    id: id, name: o["name"]?.stringValue, on: o["an"]?.boolValue ?? true,
                    loop: o["schleife"]?.boolValue ?? false, speed: o["geschwindigkeit"]?.doubleValue ?? 1,
                    fromStart: o["von_vorn"]?.boolValue ?? false))
        case "ANIM_SEEK":
            return .seek(AnimationSeekCommand(id: id, name: o["name"]?.stringValue, time: o["zeit"]?.doubleValue ?? 0))
        case "ANIM_VIDEO_REQ":
            return .video(
                AnimationVideoCommand(
                    id: id, name: o["name"]?.stringValue, width: o["width"]?.intValue ?? 1920,
                    height: o["height"]?.intValue ?? 1080, fps: o["fps"]?.doubleValue,
                    camera: o["kamera"]?.stringValue, format: o["format"]?.stringValue ?? "mp4",
                    path: o["path"]?.stringValue ?? ""))
        default:
            throw AnimationDecodeError(message: "Unbekannte Animationsnachricht \(type)")
        }
    }
}

// MARK: - App → Kernel

/// ANIM_STATE: Abspielstand für MCP (`animation_liste`), bei Abspielen, Anhalten und Springen.
public struct AnimationStateMessage: OutgoingMessage {
    public static let type = "ANIM_STATE"
    public var seq = 0
    public var name: String?
    public var time: Double
    public var frame: Int
    public var playing: Bool
    public var loop: Bool
    public var speed: Double

    public init(name: String?, time: Double, frame: Int, playing: Bool, loop: Bool, speed: Double) {
        self.name = name
        self.time = time
        self.frame = frame
        self.playing = playing
        self.loop = loop
        self.speed = speed
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, name
        case time = "zeit", frame = "bild", playing = "spielt", loop = "schleife", speed = "geschwindigkeit"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(name, forKey: .name)
        try c.encode(time, forKey: .time)
        try c.encode(frame, forKey: .frame)
        try c.encode(playing, forKey: .playing)
        try c.encode(loop, forKey: .loop)
        try c.encode(speed, forKey: .speed)
    }
}

/// ANIM_COLLISIONS_REQ: Kollisionsprüfung aus der App (Knopf in der Zeitleiste).
public struct AnimationCollisionsRequestMessage: OutgoingRequest {
    public static let type = "ANIM_COLLISIONS_REQ"
    public var seq = 0
    public var id: String
    public var name: String
    public var step: Int

    public init(id: String, name: String, step: Int = 3) {
        self.id = id
        self.name = name
        self.step = step
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, name
        case step = "schritt"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(name, forKey: .name)
        try c.encode(step, forKey: .step)
    }
}

/// ANIM_VIDEO_RES: Antwort auf ANIM_VIDEO_REQ.
public struct AnimationVideoResponseMessage: OutgoingMessage {
    public static let type = "ANIM_VIDEO_RES"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var path: String?
    public var frames: Int
    public var milliseconds: Int
    public var message: String?
    public var camera: String?

    public init(
        replyTo: String, ok: Bool, path: String?, frames: Int, milliseconds: Int, message: String? = nil,
        camera: String? = nil
    ) {
        self.replyTo = replyTo
        self.ok = ok
        self.path = path
        self.frames = frames
        self.milliseconds = milliseconds
        self.message = message
        self.camera = camera
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, path, frames, message
        case replyTo = "reply_to", milliseconds = "ms", camera = "kamera"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(path, forKey: .path)
        try c.encode(frames, forKey: .frames)
        try c.encode(milliseconds, forKey: .milliseconds)
        try c.encode(message, forKey: .message)
        try c.encode(camera, forKey: .camera)
    }
}
