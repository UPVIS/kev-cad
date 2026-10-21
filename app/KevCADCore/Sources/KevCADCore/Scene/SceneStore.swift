import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// Hervorhebung durch den Agenten (VIEW_CMD `highlight`). `color` ist linear, so wie der Kernel sie schickt
/// (mcp_tools.parse_color rechnet Hex und Namen von sRGB in linear um).
public struct SceneHighlight: Sendable {
    public var id: Int
    public var refs: [ElementRef]
    public var color: SIMD4<Float>
    public var label: String?

    /// Farbe für die 2D-Überlagerung (CoreGraphics arbeitet in sRGB).
    public var overlayColor: SIMD4<Float> { SceneStore.srgb(color) }
}

/// Die Szene: Teile nach Namen, ihr Zustand (Sichtbarkeit, Auswahl, Hervorhebung, Explosion, Darstellung) und die
/// daraus gebauten `ViewportBody`. Körper werden nur neu gebaut, wenn sich Geometrie oder Flächenfarben ändern;
/// Farbe, Sichtbarkeit und Lage ändert der Viewport ohne neues Hochladen.
@MainActor
public final class SceneStore {
    public static let selectionFaceColor = SIMD4<Float>(0.10, 0.50, 1.00, 0.70)
    public static let selectionLineColor = SIMD4<Float>(0.10, 0.50, 1.00, 1.00)
    public static let defaultHighlightColor = SIMD4<Float>(1.00, 0.45, 0.00, 1.00)
    static let flashColor = SIMD3<Float>(1.00, 0.80, 0.25)
    static let flashDuration: CFTimeInterval = 0.6
    static let pulseDuration: CFTimeInterval = 0.9
    static let xrayAlpha: Float = 0.4
    static let dimFactor: Float = 0.6

    // MARK: Inhalt

    public private(set) var order: [String] = []
    public private(set) var parts: [String: PartRecord] = [:]
    /// Laufnummer des letzten RUN_START bzw. RUN_END.
    public private(set) var latestRun = 0

    // MARK: Zustand

    public private(set) var hidden: Set<String> = []
    public private(set) var displayStyle: DisplayStyle = .shadedEdges
    public private(set) var explodeFactor: Float = 0
    public private(set) var section: ClipPlane?
    public private(set) var selection: [ElementRef] = []
    public private(set) var highlights: [SceneHighlight] = []
    /// Während eines Laufs: Teile mit kleinerer Laufnummer werden abgedunkelt.
    public private(set) var dimBelowRun: Int?
    /// Phase 2: Teile, die die Inventar-Regel verletzen (rot eingefärbt).
    public private(set) var inventoryWarnings: Set<String> = []
    /// Prüfung: rote, durchscheinende Schnittkörper (immer obenauf, nicht anklickbar), siehe AppController+Pruefung.
    public private(set) var ghostBodies: [ViewportBody] = []
    static let inventoryWarningColor = SIMD3<Float>(0.85, 0.05, 0.03)
    /// Phase 5: Lage je Teil aus der Animation (Ruhelage → aktuelles Bild), zusätzlich zur Basislage; leer = Ruhelage.
    public private(set) var animationTransforms: [String: simd_float4x4] = [:]
    /// Phase 5: von der Animation ausgeblendete Teile (`sichtbar`) und Teile einer Kollision im aktuellen Bild (rot).
    public private(set) var animationHidden: Set<String> = []
    public private(set) var collisionParts: Set<String> = []
    static let collisionColor = SIMD3<Float>(0.95, 0.04, 0.04)

    private var flashStart: [String: CFTimeInterval] = [:]
    private var pulseStart: CFTimeInterval = -10
    private var pulseLevel = 0
    private var nextHighlightID = 1
    private var assemblyCenter = SIMD3<Float>(repeating: 0)

    // MARK: Körper

    private var partBodies: [String: [ViewportBody]] = [:]
    /// Reine Kantenkörper je Teil für die Röntgendarstellung (durchsichtige Körper zeichnet der Viewport ohne Kanten).
    private var edgeBodies: [String: [ViewportBody]] = [:]
    private var styleSignature: [String: Int] = [:]
    private var bodyOwner: [String: (part: String, chunk: Int)] = [:]
    public private(set) var bodies: [ViewportBody] = []
    /// `bodies` plus unsichtbarer Hilfskörper für den Tiefenbereich (das geht an den Viewport).
    public private(set) var renderBodies: [ViewportBody] = []
    public static let depthHelperID = "\u{1F}tiefe"

    /// Wird nach jeder Änderung an `bodies` aufgerufen.
    public var onChange: (() -> Void)?

    public init() {}

    // MARK: Teile

    public var isEmpty: Bool { order.isEmpty }
    public var triangleCount: Int { order.reduce(0) { $0 + (parts[$1]?.triangleCount ?? 0) } }

    /// Fügt ein Teil ein oder ersetzt es. Rückgabe: ob sich die Geometrie geändert hat.
    @discardableResult
    public func upsert(_ record: PartRecord, now: CFTimeInterval = CACurrentMediaTime(), flash: Bool = true) -> Bool {
        let name = record.name
        let old = parts[name]
        if old == nil { order.append(name) }
        latestRun = max(latestRun, record.run)
        if let old, old.digest == record.digest, old.chunks.count == record.chunks.count {
            // Gleiche Geometrie: nur Kopfwerte übernehmen, Körper behalten
            var r = old
            r.header = record.header
            parts[name] = r
            updateAssemblyCenter()
            applyProps(name, now: now)
            publish()
            return false
        }
        parts[name] = record
        // Auswahl und Hervorhebung auf Elemente, die es nicht mehr gibt, verwerfen
        selection.removeAll { $0.part == name && !record.contains($0) }
        if flash { flashStart[name] = now }
        updateAssemblyCenter()
        rebuildBodies(name)
        if explodeFactor != 0 { for n in order { applyProps(n, now: now) } } else { applyProps(name, now: now) }
        publish()
        return true
    }

    public func remove(_ name: String) {
        guard parts.removeValue(forKey: name) != nil else { return }
        order.removeAll { $0 == name }
        for b in partBodies[name] ?? [] { bodyOwner.removeValue(forKey: b.id) }
        partBodies.removeValue(forKey: name)
        edgeBodies.removeValue(forKey: name)
        styleSignature.removeValue(forKey: name)
        flashStart.removeValue(forKey: name)
        hidden.remove(name)
        selection.removeAll { $0.part == name }
        for i in highlights.indices { highlights[i].refs.removeAll { $0.part == name } }
        highlights.removeAll { $0.refs.isEmpty }
        updateAssemblyCenter()
        publish()
    }

    public func removeAll() {
        order = []
        parts = [:]
        partBodies = [:]
        edgeBodies = [:]
        styleSignature = [:]
        bodyOwner = [:]
        flashStart = [:]
        hidden = []
        selection = []
        highlights = []
        inventoryWarnings = []
        animationTransforms = [:]
        animationHidden = []
        collisionParts = []
        ghostBodies = []
        dimBelowRun = nil
        assemblyCenter = .zero
        latestRun = 0
        publish()
    }

    public func record(_ name: String) -> PartRecord? { parts[name] }

    /// Prüft eine Referenz gegen die Szene.
    public func isValid(_ ref: ElementRef) -> Bool { parts[ref.part]?.contains(ref) ?? false }

    /// Baugruppen auflösen: ein Teilname ohne eigenes Teil steht für alle Teile darunter („Halter“ → „Halter/…“),
    /// wie beim Kernel. Ergebnis: gültige Referenzen und die Texte, die nichts getroffen haben.
    public func expand(_ refs: [ElementRef]) -> (known: [ElementRef], unknown: [String]) {
        var known: [ElementRef] = []
        var unknown: [String] = []
        var seen = Set<ElementRef>()
        for r in refs {
            var hits: [ElementRef] = []
            if isValid(r) {
                hits = [r]
            } else if r.kind == .part, parts[r.part] == nil {
                let prefix = r.part.hasSuffix("/") ? r.part : r.part + "/"
                hits = order.filter { $0.hasPrefix(prefix) }.map { ElementRef.part($0) }
            }
            if hits.isEmpty { unknown.append(r.string) }
            for h in hits where seen.insert(h).inserted { known.append(h) }
        }
        return (known, unknown)
    }

    // MARK: Lauf

    public func beginRun(_ run: Int, now: CFTimeInterval = CACurrentMediaTime()) {
        latestRun = max(latestRun, run)
        dimBelowRun = run
        for n in order { applyProps(n, now: now) }
        publish()
    }

    public func endRun(_ run: Int?, now: CFTimeInterval = CACurrentMediaTime()) {
        if let run { latestRun = max(latestRun, run) }
        dimBelowRun = nil
        for n in order { applyProps(n, now: now) }
        publish()
    }

    // MARK: Sichtbarkeit und Darstellung

    public func isVisible(_ name: String) -> Bool { !hidden.contains(name) }

    public func setVisible(_ names: [String], _ visible: Bool) {
        for n in names {
            if visible { hidden.remove(n) } else if parts[n] != nil { hidden.insert(n) }
            applyProps(n)
        }
        publish()
    }

    /// Nur diese Teile zeigen.
    public func isolate(_ names: [String]) {
        let keep = Set(names)
        hidden = Set(order.filter { !keep.contains($0) })
        for n in order { applyProps(n) }
        publish()
    }

    public func showAll() {
        hidden = []
        for n in order { applyProps(n) }
        publish()
    }

    public func setDisplayStyle(_ style: DisplayStyle) {
        guard style != displayStyle else { return }
        displayStyle = style
        for n in order { applyProps(n) }
        publish()
    }

    public var viewportDisplayMode: DisplayMode {
        switch displayStyle {
        case .shadedEdges, .xray: return .shadedWithEdges
        case .shaded: return .shaded
        case .wireframe: return .wireframe
        }
    }

    public func setExplode(_ factor: Float) {
        explodeFactor = max(0, min(factor, 3))
        for n in order { applyProps(n) }
        publish()
    }

    /// Schnittebene; entfernt wird die Seite in Richtung `normal` ab `offset` (mm entlang der Normalen).
    public func setSection(normal: SIMD3<Float>?, offset: Float) {
        if let normal, simd_length(normal) > 1e-6 {
            let n = simd_normalize(normal)
            section = ClipPlane(normal: -n, distance: offset)
        } else {
            section = nil
        }
    }

    // MARK: Inventar-Regel

    /// Teile, die weder Lagerteil noch gekennzeichnetes Druckteil sind, rot einfärben (ohne Wirkung, wenn gleich).
    public func setInventoryWarnings(_ names: Set<String>) {
        guard names != inventoryWarnings else { return }
        let touched = names.symmetricDifference(inventoryWarnings)
        inventoryWarnings = names
        for n in touched where parts[n] != nil { applyProps(n) }
        publish()
    }

    // MARK: Animation (Phase 5)

    /// Lage aller bewegten Teile für ein Bild setzen (nur Matrizen, kein Neuvernetzen), dazu ausgeblendete Teile und
    /// das Kollisionspaar. Leere Werte = Ruhelage.
    public func setAnimationPose(
        _ transforms: [String: simd_float4x4], hidden: Set<String> = [], collision: Set<String> = []
    ) {
        var touched = Set(transforms.keys).union(animationTransforms.keys)
        touched.formUnion(hidden.symmetricDifference(animationHidden))
        touched.formUnion(collision.symmetricDifference(collisionParts))
        animationTransforms = transforms
        animationHidden = hidden
        collisionParts = collision
        for n in touched where parts[n] != nil { applyProps(n) }
        publish()
    }

    /// Schnittkörper der Prüfung ersetzen (leer = keine).
    public func setGhostBodies(_ bodies: [ViewportBody]) {
        ghostBodies = bodies
        publish()
    }

    // MARK: Auswahl und Hervorhebung

    public func setSelection(_ refs: [ElementRef]) {
        let old = Set(selection.map(\.part))
        var seen = Set<ElementRef>()
        selection = refs.filter { isValid($0) && seen.insert($0).inserted }
        let touched = old.union(selection.map(\.part))
        for n in touched where parts[n] != nil {
            rebuildBodiesIfStyleChanged(n)
            applyProps(n)
        }
        publish()
    }

    @discardableResult
    public func addHighlight(
        refs: [ElementRef], color: SIMD4<Float>?, label: String?, clear: Bool,
        now: CFTimeInterval = CACurrentMediaTime()
    ) -> SceneHighlight {
        var touched = Set(refs.map(\.part))
        if clear {
            touched.formUnion(highlights.flatMap { $0.refs.map(\.part) })
            highlights = []
        }
        let h = SceneHighlight(
            id: nextHighlightID, refs: refs.filter { isValid($0) }, color: color ?? Self.defaultHighlightColor,
            label: label)
        nextHighlightID += 1
        highlights.append(h)
        pulseStart = now
        pulseLevel = Self.pulseLevel(at: 0)
        for n in touched where parts[n] != nil {
            rebuildBodiesIfStyleChanged(n)
            applyProps(n, now: now)
        }
        publish()
        return h
    }

    public func clearHighlights() {
        let touched = Set(highlights.flatMap { $0.refs.map(\.part) })
        highlights = []
        for n in touched where parts[n] != nil {
            rebuildBodiesIfStyleChanged(n)
            applyProps(n)
        }
        publish()
    }

    /// Körper-IDs der als Ganzes ausgewählten Teile (für den Umriss des Viewports).
    public var outlinedBodyIDs: Set<String> {
        var ids = Set<String>()
        for r in selection where r.kind == .part {
            for b in partBodies[r.part] ?? [] { ids.insert(b.id) }
        }
        return ids
    }

    // MARK: Picking

    /// Rechnet einen GPU-Treffer auf Teil, Fläche, Kante oder Punkt zurück.
    public func resolve(_ pick: PickResult) -> ElementRef? {
        resolve(bodyID: pick.bodyID, kind: pick.kind, primitive: pick.triangleIndex)
    }

    public func resolve(bodyID: String, kind: PrimitiveKind, primitive: Int) -> ElementRef? {
        guard let owner = bodyOwner[bodyID], let rec = parts[owner.part], owner.chunk < rec.chunks.count else {
            return nil
        }
        let chunk = rec.chunks[owner.chunk]
        switch kind {
        case .face:
            if let f = chunk.face(ofTriangle: primitive) { return .face(rec.name, f) }
        case .edge:
            if let e = chunk.edge(ofSegment: primitive) { return .edge(rec.name, e) }
        case .vertex:
            switch chunk.target(ofPoint: primitive) {
            case .vertex(let v)?: return .vertex(rec.name, v)
            case .edge(let e)?: return .edge(rec.name, e)
            case nil: break
            }
        }
        return .part(rec.name)
    }

    /// Teil und Stück eines Körpers.
    public func owner(ofBody id: String) -> (part: String, chunk: Int)? { bodyOwner[id] }

    public static func bodyID(part: String, chunk: Int) -> String { "\(part)\u{1F}\(chunk)" }

    // MARK: Lage und Hüllquader

    /// Lage eines Teils in der Welt (Basislage aus dem Kernel, dazu die Explosion).
    public func worldTransform(_ name: String) -> simd_float4x4 {
        guard let rec = parts[name] else { return matrix_identity_float4x4 }
        var base = rec.header.transformMatrix
        if let anim = animationTransforms[name] { base = anim * base }
        guard explodeFactor != 0 else { return base }
        let c = Self.transformBox(rec.localMin, rec.localMax, base).center
        let offset = (c - assemblyCenter) * explodeFactor
        var t = matrix_identity_float4x4
        t.columns.3 = SIMD4(offset, 1)
        return t * base
    }

    public func worldBounds(of ref: ElementRef) -> BoundingBox? {
        guard let rec = parts[ref.part], let b = rec.localBounds(of: ref) else { return nil }
        return Self.transformBox(b.min, b.max, worldTransform(ref.part))
    }

    public func worldBounds(of refs: [ElementRef]) -> BoundingBox? {
        var u: BoundingBox?
        for r in refs {
            guard let b = worldBounds(of: r) else { continue }
            u = u?.union(b) ?? b
        }
        return u
    }

    /// Alle sichtbaren Teile (ohne sichtbare Teile: alle).
    public func visibleBounds() -> BoundingBox? {
        let vis = order.filter { !hidden.contains($0) }
        return worldBounds(of: (vis.isEmpty ? order : vis).map { ElementRef.part($0) })
    }

    public func worldAnchor(of ref: ElementRef) -> SIMD3<Float>? {
        guard let rec = parts[ref.part], let p = rec.anchorPoint(of: ref) else { return nil }
        let w = worldTransform(ref.part) * SIMD4(p, 1)
        return SIMD3(w.x, w.y, w.z)
    }

    static func transformBox(_ lo: SIMD3<Float>, _ hi: SIMD3<Float>, _ m: simd_float4x4) -> BoundingBox {
        var a = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var b = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        for i in 0..<8 {
            let p = SIMD3<Float>(i & 1 == 0 ? lo.x : hi.x, i & 2 == 0 ? lo.y : hi.y, i & 4 == 0 ? lo.z : hi.z)
            let w = m * SIMD4(p, 1)
            let q = SIMD3(w.x, w.y, w.z)
            a = simd_min(a, q)
            b = simd_max(b, q)
        }
        return BoundingBox(min: a, max: b)
    }

    private func updateAssemblyCenter() {
        var u: BoundingBox?
        for n in order {
            guard let rec = parts[n] else { continue }
            let b = Self.transformBox(rec.localMin, rec.localMax, rec.header.transformMatrix)
            u = u?.union(b) ?? b
        }
        assemblyCenter = u?.center ?? .zero
    }

    // MARK: Überlagerung

    /// Ausgewählte und hervorgehobene Kanten und Punkte, als 2D-Überlagerung zu zeichnen.
    public func elementOverlay() -> [OverlayPrimitive] {
        var out: [OverlayPrimitive] = []
        func add(_ ref: ElementRef, _ color: SIMD4<Float>) {
            guard let rec = parts[ref.part], !hidden.contains(ref.part) else { return }
            let m = worldTransform(ref.part)
            func w(_ p: SIMD3<Float>) -> SIMD3<Float> {
                let v = m * SIMD4(p, 1)
                return SIMD3(v.x, v.y, v.z)
            }
            switch ref.kind {
            case .edge:
                let poly = rec.geometry.edgePolyline(ref.index).map(w)
                let pieces = section.map { SectionClipper.clipPolylines([poly], plane: $0) } ?? [poly]
                for p in pieces where p.count >= 2 { out.append(.polyline(points: p, color: color, width: 3)) }
            case .vertex:
                if ref.index < rec.vertexCount {
                    let p = w(rec.geometry.brepVertex(ref.index))
                    if let s = section, simd_dot(s.normal, p) + s.distance < 0 { break }
                    out.append(.dot(point: p, color: color, radius: 5))
                }
            case .face, .part:
                break
            }
        }
        for h in highlights { for r in h.refs { add(r, h.overlayColor) } }
        for r in selection { add(r, Self.selectionLineColor) }
        return out
    }

    // MARK: Animation (Aufleuchten neuer Teile, Pulsieren von Hervorhebungen)

    public func isAnimating(now: CFTimeInterval = CACurrentMediaTime()) -> Bool {
        !flashStart.isEmpty || now - pulseStart < Self.pulseDuration + 0.05
    }

    /// Einen Animationsschritt rechnen; gibt `true` zurück, wenn sich etwas geändert hat.
    @discardableResult
    public func tick(now: CFTimeInterval = CACurrentMediaTime()) -> Bool {
        var changed = false
        for (name, t0) in flashStart {
            if now - t0 > Self.flashDuration { flashStart.removeValue(forKey: name) }
            applyProps(name, now: now)
            changed = true
        }
        let level = Self.pulseLevel(at: now - pulseStart)
        if level != pulseLevel {
            pulseLevel = level
            let touched = Set(highlights.flatMap { $0.refs.map(\.part) })
            for n in touched where parts[n] != nil {
                rebuildBodiesIfStyleChanged(n)
                applyProps(n, now: now)
            }
            changed = true
        }
        if changed { publish() }
        return changed
    }

    /// Pulsieren in groben Stufen (spart neues Hochladen): an, schwach, an, schwach, an.
    static func pulseLevel(at t: CFTimeInterval) -> Int {
        guard t >= 0, t < pulseDuration else { return 0 }
        return Int(t / 0.18) % 2 == 1 ? 1 : 0
    }

    private var pulseFactor: Float { pulseLevel == 1 ? 0.3 : 1 }

    // MARK: Körper bauen

    private func faceStyles(for name: String) -> [Int: SIMD4<Float>] {
        var map: [Int: SIMD4<Float>] = [:]
        for h in highlights {
            for r in h.refs where r.part == name && r.kind == .face {
                map[r.index] = SIMD4(h.color.x, h.color.y, h.color.z, 0.85 * pulseFactor)
            }
        }
        for r in selection where r.part == name && r.kind == .face { map[r.index] = Self.selectionFaceColor }
        return map
    }

    private static func signature(_ map: [Int: SIMD4<Float>]) -> Int {
        var h = Hasher()
        for k in map.keys.sorted() {
            h.combine(k)
            h.combine(map[k]!)
        }
        return h.finalize()
    }

    private func rebuildBodiesIfStyleChanged(_ name: String) {
        if Self.signature(faceStyles(for: name)) != styleSignature[name] { rebuildBodies(name) }
    }

    private func rebuildBodies(_ name: String) {
        guard let rec = parts[name] else { return }
        for b in partBodies[name] ?? [] { bodyOwner.removeValue(forKey: b.id) }
        let map = faceStyles(for: name)
        styleSignature[name] = Self.signature(map)
        var list: [ViewportBody] = []
        list.reserveCapacity(rec.chunks.count)
        for chunk in rec.chunks {
            let styles: [TriangleStyle] =
                map.isEmpty || chunk.triangleCount == 0
                ? [] : chunk.triFace.map { f in map[Int(f)].map { TriangleStyle(color: $0) } ?? .none }
            let id = Self.bodyID(part: name, chunk: chunk.index)
            bodyOwner[id] = (name, chunk.index)
            list.append(
                ViewportBody(
                    id: id, vertexData: chunk.vertexData, indices: chunk.indices, edges: chunk.edges,
                    faceIndices: chunk.triFace, edgeIndices: chunk.segEdge, vertices: chunk.points,
                    triangleStyles: styles, color: Self.linear(rec.header.colorVector), roughness: 0.55,
                    metallic: Self.metallic(rec.header.material)))
        }
        partBodies[name] = list
        edgeBodies[name] = rec.chunks.filter { !$0.edges.isEmpty }.map { chunk in
            ViewportBody(
                id: Self.bodyID(part: name, chunk: chunk.index) + "\u{1F}k", vertexData: [], indices: [],
                edges: chunk.edges, color: SIMD4(0.2, 0.2, 0.2, 1), isPickable: false)
        }
    }

    /// sRGB (wie in model.py und im Protokoll vom Kernel) → linear für den Viewport. Alpha bleibt.
    nonisolated public static func linear(_ c: SIMD4<Float>) -> SIMD4<Float> {
        func f(_ v: Float) -> Float {
            let x = min(max(v, 0), 1)
            return x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4)
        }
        return SIMD4(f(c.x), f(c.y), f(c.z), c.w)
    }

    /// linear → sRGB (für die Überlagerung). Alpha bleibt.
    nonisolated public static func srgb(_ c: SIMD4<Float>) -> SIMD4<Float> {
        func f(_ v: Float) -> Float {
            let x = min(max(v, 0), 1)
            return x <= 0.0031308 ? x * 12.92 : 1.055 * pow(x, 1 / 2.4) - 0.055
        }
        return SIMD4(f(c.x), f(c.y), f(c.z), c.w)
    }

    /// Kantenfarbe in der Röntgendarstellung: dunklere Teilfarbe, deckend.
    static func xrayEdgeColor(_ c: SIMD4<Float>) -> SIMD4<Float> { SIMD4(c.x * 0.35, c.y * 0.35, c.z * 0.35, 1) }

    /// Ohne Umgebungsbild wirken metallische Flächen im Viewport fast schwarz; Teile bleiben deshalb matt, die
    /// Farbe aus model.py trägt das Material.
    static func metallic(_ material: String?) -> Float { 0 }

    /// Farbe eines Teils mit allen Zuständen (Röntgen, Abdunkeln, Aufleuchten, Hervorhebung, Auswahl).
    func displayColor(_ name: String, now: CFTimeInterval, includeFlash: Bool = true) -> SIMD4<Float> {
        guard let rec = parts[name] else { return .zero }
        var c = Self.linear(rec.header.colorVector)
        var rgb = SIMD3(c.x, c.y, c.z)
        if let dim = dimBelowRun, rec.run < dim { rgb *= Self.dimFactor }
        if inventoryWarnings.contains(name) { rgb = rgb + (Self.inventoryWarningColor - rgb) * 0.55 }
        if collisionParts.contains(name) { rgb = rgb + (Self.collisionColor - rgb) * 0.8 }
        if includeFlash, let t0 = flashStart[name] {
            let k = Float(max(0, 1 - (now - t0) / Self.flashDuration))
            rgb = rgb + (Self.flashColor - rgb) * (0.7 * k)
        }
        for h in highlights where h.refs.contains(where: { $0.part == name && $0.kind == .part }) {
            let hc = SIMD3(h.color.x, h.color.y, h.color.z)
            rgb = rgb + (hc - rgb) * (0.6 * pulseFactor)
        }
        if selection.contains(where: { $0.part == name && $0.kind == .part }) {
            let s = SIMD3(Self.selectionLineColor.x, Self.selectionLineColor.y, Self.selectionLineColor.z)
            rgb = rgb + (s - rgb) * 0.3
        }
        c = SIMD4(rgb, c.w)
        if displayStyle == .xray { c.w = min(c.w, Self.xrayAlpha) }
        return c
    }

    private func applyProps(_ name: String, now: CFTimeInterval = CACurrentMediaTime()) {
        guard var list = partBodies[name] else { return }
        let color = displayColor(name, now: now)
        let visible = !hidden.contains(name) && !animationHidden.contains(name)
        let transform = worldTransform(name)
        for i in list.indices {
            list[i].color = color
            list[i].isVisible = visible
            list[i].transform = transform
        }
        partBodies[name] = list
        if var edges = edgeBodies[name] {
            let ec = Self.xrayEdgeColor(color)
            for i in edges.indices {
                edges[i].color = ec
                edges[i].isVisible = visible
                edges[i].transform = transform
            }
            edgeBodies[name] = edges
        }
    }

    private func publish() {
        var out: [ViewportBody] = []
        out.reserveCapacity(bodies.count + 4)
        for n in order { out.append(contentsOf: partBodies[n] ?? []) }
        bodies = out
        renderBodies = out
        if displayStyle == .xray { for n in order { renderBodies.append(contentsOf: edgeBodies[n] ?? []) } }
        if animationTransforms.isEmpty { renderBodies.append(contentsOf: ghostBodies) }  // Schnittkörper: Ruhelage
        if let helper = depthHelper() { renderBodies.append(helper) }
        onChange?()
    }

    /// Der Viewport legt die Nahebene genau an den Hüllquader der Szene (Abstand zur nächsten Ecke). Flächen, die
    /// dort liegen (Deckfläche in der Draufsicht) oder Ecken schräg am Bildrand werden dadurch abgeschnitten. Ein
    /// unsichtbarer, nicht anklickbarer Körper mit größerem Hüllquader schiebt die Nahebene nach vorn.
    func depthHelper() -> ViewportBody? {
        guard let b = visibleBounds() else { return nil }
        let pad = SIMD3<Float>(repeating: max(b.diagonalLength, 10))
        let lo = b.min - pad, hi = b.max + pad
        let corners = (0..<8).map { i in
            SIMD3<Float>(i & 1 == 0 ? lo.x : hi.x, i & 2 == 0 ? lo.y : hi.y, i & 4 == 0 ? lo.z : hi.z)
        }
        return ViewportBody(
            id: Self.depthHelperID, vertexData: [], indices: [], edges: [], vertices: corners, color: .zero,
            isPickable: false)
    }

    // MARK: Bilder

    /// Körper für ein Bild über den `OffscreenRenderer`: nur sichtbare Teile, Hervorhebungen als eigene Körper
    /// eingefärbt (der Offscreen-Renderer kennt keine Dreiecksstile), Schnitt auf der CPU ausgeführt.
    public func snapshotBodies(applySection: Bool = true) -> [ViewportBody] {
        let clip = applySection ? section : nil
        var out: [ViewportBody] = []
        let now = CACurrentMediaTime()
        for name in order where !hidden.contains(name) && !animationHidden.contains(name) {
            guard let rec = parts[name], let live = partBodies[name] else { continue }
            // Der OffscreenRenderer hat weder Belichtung noch Tonwertkurve; sRGB-Farben sehen dort so aus wie im Viewport
            let colorLinear = displayColor(name, now: now, includeFlash: false)
            let color = Self.srgb(colorLinear)
            let styles = faceStyles(for: name)
            let m = worldTransform(name)
            let xray = displayStyle == .xray
            for (ci, chunk) in rec.chunks.enumerated() {
                if clip == nil && styles.isEmpty, ci < live.count {
                    var b = live[ci]
                    b.color = color
                    b.isVisible = true
                    b.triangleStyles = []
                    out.append(b)
                    if xray, let e = edgeBodies[name]?.first(where: { $0.id.hasPrefix(b.id + "\u{1F}") }) {
                        var edge = e
                        edge.color = Self.srgb(e.color)
                        out.append(edge)
                    }
                    continue
                }
                // Dreiecke nach Farbe gruppieren und in Weltkoordinaten bringen
                var groups: [SIMD4<Float>?: [Float]] = [:]
                let vd = chunk.vertexData
                let nm = simd_float3x3(
                    SIMD3(m.columns.0.x, m.columns.0.y, m.columns.0.z), SIMD3(m.columns.1.x, m.columns.1.y, m.columns.1.z),
                    SIMD3(m.columns.2.x, m.columns.2.y, m.columns.2.z))
                for t in 0..<chunk.triangleCount {
                    let key: SIMD4<Float>? = styles[Int(chunk.triFace[t])]
                    for k in 0..<3 {
                        let v = Int(chunk.indices[t * 3 + k]) * 6
                        let p = m * SIMD4(vd[v], vd[v + 1], vd[v + 2], 1)
                        let n = nm * SIMD3(vd[v + 3], vd[v + 4], vd[v + 5])
                        groups[key, default: []].append(contentsOf: [p.x, p.y, p.z, n.x, n.y, n.z])
                    }
                }
                var edges = chunk.edges.map { line in
                    line.map { p -> SIMD3<Float> in
                        let w = m * SIMD4(p, 1)
                        return SIMD3(w.x, w.y, w.z)
                    }
                }
                if let clip { edges = SectionClipper.clipPolylines(edges, plane: clip) }
                var first = true
                for (key, soup0) in groups.sorted(by: { ($0.key == nil ? 0 : 1) < ($1.key == nil ? 0 : 1) }) {
                    let soup = clip.map { SectionClipper.clipTriangles(soup0, plane: $0) } ?? soup0
                    var c = color
                    if let key {
                        let base = SIMD3(colorLinear.x, colorLinear.y, colorLinear.z)
                        let rgb = base + (SIMD3(key.x, key.y, key.z) - base) * key.w
                        c = Self.srgb(SIMD4(rgb, colorLinear.w))
                    }
                    out.append(
                        ViewportBody(
                            id: "snap\u{1F}\(name)\u{1F}\(ci)\u{1F}\(key.map { "\($0)" } ?? "-")",
                            vertexData: soup, indices: (0..<UInt32(soup.count / 6)).map { $0 },
                            edges: first && !xray ? edges : [], color: c, roughness: 0.55,
                            metallic: Self.metallic(rec.header.material)))
                    first = false
                }
                if (first || xray) && !edges.isEmpty {
                    out.append(
                        ViewportBody(
                            id: "snap\u{1F}\(name)\u{1F}\(ci)\u{1F}e", vertexData: [], indices: [], edges: edges,
                            color: xray ? Self.srgb(Self.xrayEdgeColor(colorLinear)) : SIMD4(0.15, 0.15, 0.15, 1)))
                }
            }
        }
        // Schnittkörper der Prüfung gelten für die Ruhelage, in einem Bild der Animation stehen sie nicht
        for g in ghostBodies where g.isVisible && animationTransforms.isEmpty {  // der Offscreen-Renderer erwartet sRGB
            var b = g
            b.color = Self.srgb(g.color)
            out.append(b)
        }
        if let helper = depthHelper() { out.append(helper) }
        return out
    }
}
