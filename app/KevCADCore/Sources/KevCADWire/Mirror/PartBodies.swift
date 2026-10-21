import Foundation
import OCCTSwiftViewport
import simd

/// Viewport-Körper eines Teils, so wie die Mac-App sie baut: geteilt über 16.000 Dreiecke, Kantensegmente oder Punkte
/// (Grenze der Pick-ID), Körper-ID `"<Teil>\u{1F}<Stück>"`, Farbe sRGB → linear, matt. Netze reisen immer ungeteilt;
/// jede Darstellung teilt selbst (MIRROR.md, „Nicht vorab teilen“).
public struct PartBodies: Sendable {
    public var name: String
    public var chunks: [PartChunk]

    /// Rauheit der Teile im Viewport (wie in der Mac-App).
    public static let roughness: Float = 0.55

    public init(name: String, geometry: PartGeometry, limit: Int = ChunkBuilder.limit) {
        self.name = name
        self.chunks = ChunkBuilder.build(geometry, limit: limit)
    }

    public init(name: String, chunks: [PartChunk]) {
        self.name = name
        self.chunks = chunks
    }

    /// Körper für den Viewport.
    /// - Parameters:
    ///   - color: Teilfarbe in **sRGB** (wie `MirrorPart.color`); wird für den Viewport linear gerechnet.
    ///   - faceStyles: Fläche → lineare Farbe mit Deckkraft für einzelne Flächen (Auswahl, Hervorhebung).
    public func bodies(
        color: SIMD4<Float>, visible: Bool = true, pickable: Bool = true, transform: simd_float4x4 = matrix_identity_float4x4,
        faceStyles: [Int: SIMD4<Float>] = [:]
    ) -> [ViewportBody] {
        let linear = PartBodies.linear(color)
        return chunks.map { chunk in
            let styles: [TriangleStyle] =
                faceStyles.isEmpty || chunk.triangleCount == 0
                ? [] : chunk.triFace.map { f in faceStyles[Int(f)].map { TriangleStyle(color: $0) } ?? .none }
            return ViewportBody(
                id: PartBodies.bodyID(part: name, chunk: chunk.index), vertexData: chunk.vertexData,
                indices: chunk.indices, edges: chunk.edges, faceIndices: chunk.triFace, edgeIndices: chunk.segEdge,
                vertices: chunk.points, triangleStyles: styles, color: linear, roughness: PartBodies.roughness,
                metallic: 0, isVisible: visible, isPickable: pickable, transform: transform)
        }
    }

    public var triangleCount: Int { chunks.reduce(0) { $0 + $1.triangleCount } }

    /// Treffer im Körper `chunk` auf Teil, Fläche, Kante oder Punkt zurückrechnen.
    public func resolve(chunk index: Int, kind: PrimitiveKind, primitive: Int) -> ElementRef {
        guard index >= 0, index < chunks.count else { return .part(name) }
        let chunk = chunks[index]
        switch kind {
        case .face:
            if let f = chunk.face(ofTriangle: primitive) { return .face(name, f) }
        case .edge:
            if let e = chunk.edge(ofSegment: primitive) { return .edge(name, e) }
        case .vertex:
            switch chunk.target(ofPoint: primitive) {
            case .vertex(let v)?: return .vertex(name, v)
            case .edge(let e)?: return .edge(name, e)
            case nil: break
            }
        }
        return .part(name)
    }

    // MARK: Körper-IDs

    /// Trennzeichen zwischen Teilname und Stücknummer in der Körper-ID.
    public static let separator: Character = "\u{1F}"

    public static func bodyID(part: String, chunk: Int) -> String { "\(part)\(separator)\(chunk)" }

    /// Teilname und Stück aus einer Körper-ID.
    public static func owner(ofBody id: String) -> (part: String, chunk: Int)? {
        guard let i = id.lastIndex(of: separator), let chunk = Int(id[id.index(after: i)...]) else { return nil }
        return (String(id[..<i]), chunk)
    }

    /// Treffer des Viewports auf ein Element, wenn `parts` die Körper der Szene kennt.
    public static func resolve(_ pick: PickResult, in parts: [String: PartBodies]) -> ElementRef? {
        guard let owner = owner(ofBody: pick.bodyID), let p = parts[owner.part] else { return nil }
        return p.resolve(chunk: owner.chunk, kind: pick.kind, primitive: pick.triangleIndex)
    }

    // MARK: Farben

    /// sRGB (Protokoll, model.py) → linear (Viewport). Alpha bleibt.
    public static func linear(_ c: SIMD4<Float>) -> SIMD4<Float> {
        func f(_ v: Float) -> Float {
            let x = min(max(v, 0), 1)
            return x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4)
        }
        return SIMD4(f(c.x), f(c.y), f(c.z), c.w)
    }

    /// linear → sRGB. Alpha bleibt.
    public static func srgb(_ c: SIMD4<Float>) -> SIMD4<Float> {
        func f(_ v: Float) -> Float {
            let x = min(max(v, 0), 1)
            return x <= 0.0031308 ? x * 12.92 : 1.055 * pow(x, 1 / 2.4) - 0.055
        }
        return SIMD4(f(c.x), f(c.y), f(c.z), c.w)
    }
}

// MARK: - Kamera

extension MirrorCamera {
    /// Aus dem Kamerastand des Viewports (`panOffset` wirkt dort nicht und bleibt weg).
    public init(_ c: CameraState) {
        let q = c.rotation.vector
        self.init(
            rotation: [q.x, q.y, q.z, q.w], pivot: [c.pivot.x, c.pivot.y, c.pivot.z], distance: c.distance,
            fov: c.fieldOfView, ortho: c.isOrthographic, orthoScale: c.orthographicScale)
    }

    /// Als Kamerastand für den Viewport (gleiche Konvention: Kamera → Welt, Blick entlang −Z der Kamera).
    public var cameraState: CameraState {
        let r = rotation.count == 4 ? rotation : [0, 0, 0, 1]
        let p = pivot.count >= 3 ? SIMD3(pivot[0], pivot[1], pivot[2]) : SIMD3<Float>(0, 0, 0)
        return CameraState(
            rotation: simd_quatf(ix: r[0], iy: r[1], iz: r[2], r: r[3]), distance: distance, pivot: p, fieldOfView: fov,
            orthographicScale: orthoScale, isOrthographic: ortho)
    }
}
