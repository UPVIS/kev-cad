import KevCADCore
import SwiftUI
import simd

/// Platzhalter für den Viewport im Demomodus: zeichnet die Teile aus einfachen Grundformen (Quader, Zylinder) mit
/// Standardansichten, Darstellung, Auswahl, Ausblenden, Explosion, Schnitt und Messungen. Die echte Geometrie und der
/// Metal-Viewport kommen vom App-Kern (KevViewport).
struct DemoViewport: View {
    @ObservedObject var model: AppModel
    @ObservedObject var demo: DemoActions
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { geometry in
            let scene = DemoScene(model: model, demo: demo, size: geometry.size, dark: scheme == .dark)
            Canvas { context, _ in
                scene.draw(in: &context)
            }
            .contentShape(Rectangle())
            .onTapGesture(coordinateSpace: .local) { location in
                demo.pick(scene.hit(location))
            }
        }
        .background(background)
        .overlay(alignment: .topLeading) {
            Text("Demovorschau")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .padding(10)
                .help("Demomodus ohne Kernel: Teile als vereinfachte Formen")
        }
    }

    private var background: some View {
        LinearGradient(
            colors: scheme == .dark
                ? [Color(white: 0.20), Color(white: 0.12)]
                : [Color(red: 0.93, green: 0.94, blue: 0.95), Color(red: 0.79, green: 0.81, blue: 0.84)],
            startPoint: .top, endPoint: .bottom)
    }
}

/// Eine Fläche nach der Projektion.
private struct ProjectedFace {
    var partID: String
    var points: [CGPoint]
    var depth: Float
    var fill: Color?
    var stroke: Color
    var lineWidth: CGFloat
}

/// Projektion und Zeichnen der Demovorschau (orthografisch, Z nach oben).
private struct DemoScene {
    let size: CGSize
    let dark: Bool
    let style: DisplayStyle
    let right: SIMD3<Float>
    let up: SIMD3<Float>
    let toEye: SIMD3<Float>
    let scale: Float
    let offset: SIMD2<Float>
    var faces: [ProjectedFace] = []
    let measurements: [MeasurementItem]
    let section: (axis: Int, offset: Float, bounds: (SIMD3<Float>, SIMD3<Float>))?
    let grid: (min: SIMD3<Float>, max: SIMD3<Float>, step: Float)?

    static let light = simd_normalize(SIMD3<Float>(0.35, -0.55, 0.85))

    @MainActor
    init(model: AppModel, demo: DemoActions, size: CGSize, dark: Bool) {
        self.size = size
        self.dark = dark
        style = model.displayStyle
        measurements = model.measurements

        // Kamera aus der Standardansicht
        let (eye, upHint) = Self.camera(demo.standardView)
        toEye = simd_normalize(eye)
        right = simd_normalize(simd_cross(upHint, toEye))
        up = simd_cross(toEye, right)

        let selected = Set(model.selectedPartIDs)
        var runningRun: Int?
        if case .running(let run, _, _) = model.run { runningRun = run }

        // Szenenmitte für die Explosion
        let all = model.parts
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        for part in all {
            lo = simd_min(lo, part.bboxMin)
            hi = simd_max(hi, part.bboxMax)
        }
        let center = all.isEmpty ? .zero : (lo + hi) / 2

        let axisIndex = ["x": 0, "y": 1, "z": 2][demo.sectionAxis] ?? 2
        let cut: (Int, Float)? = model.sectionEnabled ? (axisIndex, Float(demo.sectionOffset)) : nil
        section = model.sectionEnabled && !all.isEmpty ? (axisIndex, Float(demo.sectionOffset), (lo, hi)) : nil
        grid = all.isEmpty ? nil : (lo, hi, 10)

        // Polygone je Teil in Weltkoordinaten
        struct WorldPart {
            var id: String
            var polygons: [(points: [SIMD3<Float>], normal: SIMD3<Float>, isCap: Bool, smooth: Bool)]
            var color: SIMD4<Float>
            var selected: Bool
            var dimmed: Bool
            var center: SIMD3<Float>
        }
        var world: [WorldPart] = []
        for part in all where part.visible {
            let partCenter = (part.bboxMin + part.bboxMax) / 2
            let shift = (partCenter - center) * Float(model.explodeFactor) * 1.1
            let shape = DemoData.shape(for: part.id) ?? [.box(min: part.bboxMin, max: part.bboxMax)]
            var polygons: [(points: [SIMD3<Float>], normal: SIMD3<Float>, isCap: Bool, smooth: Bool)] = []
            for primitive in shape {
                var solid: [Polygon] = Self.polygons(primitive).map {
                    (points: $0.points.map { $0 + shift }, normal: $0.normal, smooth: $0.smooth)
                }
                if let (axis, value) = cut {
                    solid = Self.clip(solid, axis: axis, value: value)
                    let capped = Self.cap(solid, axis: axis, value: value)
                    polygons += solid.map { (points: $0.points, normal: $0.normal, isCap: false, smooth: $0.smooth) }
                    if let capped {
                        polygons.append((points: capped.points, normal: capped.normal, isCap: true, smooth: false))
                    }
                } else {
                    polygons += solid.map { (points: $0.points, normal: $0.normal, isCap: false, smooth: $0.smooth) }
                }
            }
            if polygons.isEmpty { continue }
            // Inventar-Regel verletzt: rot eingefärbt wie im echten Viewport
            let warn = SIMD4<Float>(0.85, 0.05, 0.03, part.color.w)
            let color = part.inventarFehlt ? part.color + (warn - part.color) * 0.55 : part.color
            world.append(WorldPart(
                id: part.id, polygons: polygons, color: color, selected: selected.contains(part.id),
                dimmed: runningRun.map { part.run < $0 } ?? false, center: partCenter + shift))
        }

        // Einpassen: Fokus oder alles
        let focusIDs = Set(PartTree.partIDs(fromRefs: demo.focusRefs))
        let fitParts = world.filter { focusIDs.isEmpty || focusIDs.contains($0.id) }
        var minX = Float.greatestFiniteMagnitude, maxX = -Float.greatestFiniteMagnitude
        var minY = Float.greatestFiniteMagnitude, maxY = -Float.greatestFiniteMagnitude
        for part in (fitParts.isEmpty ? world : fitParts) {
            for polygon in part.polygons {
                for p in polygon.points {
                    let x = simd_dot(p, right), y = simd_dot(p, up)
                    minX = min(minX, x)
                    maxX = max(maxX, x)
                    minY = min(minY, y)
                    maxY = max(maxY, y)
                }
            }
        }
        if minX > maxX {
            minX = -100
            maxX = 100
            minY = -100
            maxY = 100
        }
        let width = Float(max(size.width, 1)), height = Float(max(size.height, 1))
        let fitScale = min(width * 0.62 / max(maxX - minX, 1), height * 0.62 / max(maxY - minY, 1))
        scale = min(fitScale, 14)
        offset = SIMD2(width / 2 - (minX + maxX) / 2 * scale, height / 2 + (minY + maxY) / 2 * scale)

        // Flächen projizieren, je Teil von hinten nach vorne
        var result: [ProjectedFace] = []
        let toEye = self.toEye
        let sortedParts = world.sorted { simd_dot($0.center, toEye) < simd_dot($1.center, toEye) }
        let accent = Color.accentColor
        let edgeColor = dark ? Color.black.opacity(0.55) : Color.black.opacity(0.45)
        for part in sortedParts {
            var partFaces: [ProjectedFace] = []
            for polygon in part.polygons {
                let facing = simd_dot(polygon.normal, toEye)
                if style != .wireframe && style != .xray && facing <= 0.0001 { continue }
                let depth = polygon.points.reduce(0) { $0 + simd_dot($1, toEye) } / Float(polygon.points.count)
                let points = polygon.points.map(project)
                let shade = 0.5 + 0.5 * max(0, simd_dot(polygon.normal, Self.light))
                var base = SIMD3<Float>(part.color.x, part.color.y, part.color.z) * shade
                if polygon.isCap { base = SIMD3<Float>(0.62, 0.06, 0.05) * (0.8 + 0.2 * shade) }
                var fill: Color? = Color(.sRGBLinear, red: Double(base.x), green: Double(base.y), blue: Double(base.z))
                var stroke = edgeColor
                var lineWidth: CGFloat = style == .shaded ? 0 : 0.9
                switch style {
                case .shadedEdges, .shaded: break
                case .wireframe:
                    fill = nil
                    stroke = Color(.sRGBLinear, red: Double(part.color.x * 0.6), green: Double(part.color.y * 0.6),
                                   blue: Double(part.color.z * 0.6))
                    lineWidth = 1
                case .xray:
                    fill = fill?.opacity(0.22)
                    stroke = edgeColor.opacity(0.5)
                    lineWidth = 0.7
                }
                if part.selected {
                    if let current = fill { fill = current.mix(with: accent, by: 0.45) }
                    stroke = accent
                    lineWidth = 1.6
                }
                if polygon.smooth && style != .wireframe, let current = fill {
                    // Facetten eines Zylindermantels: Naht mit der eigenen Farbe schließen statt Kanten zeichnen.
                    stroke = current
                    lineWidth = 0.6
                } else if polygon.smooth {
                    stroke = stroke.opacity(0.25)
                }
                if part.dimmed {
                    fill = fill?.opacity(0.45)
                    stroke = stroke.opacity(0.45)
                }
                if part.color.w < 0.99 { fill = fill?.opacity(Double(part.color.w)) }
                partFaces.append(ProjectedFace(
                    partID: part.id, points: points, depth: depth, fill: fill, stroke: stroke, lineWidth: lineWidth))
            }
            result += partFaces.sorted { $0.depth < $1.depth }
        }
        faces = result
    }

    func project(_ p: SIMD3<Float>) -> CGPoint {
        CGPoint(
            x: CGFloat(offset.x + simd_dot(p, right) * scale),
            y: CGFloat(offset.y - simd_dot(p, up) * scale))
    }

    /// Richtung zum Auge und Hilfsvektor nach oben je Standardansicht (Z oben, Vorne = Blick in +Y).
    static func camera(_ view: StandardViewName) -> (SIMD3<Float>, SIMD3<Float>) {
        let z = SIMD3<Float>(0, 0, 1)
        switch view {
        case .top: return (SIMD3(0, 0, 1), SIMD3(0, 1, 0))
        case .bottom: return (SIMD3(0, 0, -1), SIMD3(0, -1, 0))
        case .front: return (SIMD3(0, -1, 0), z)
        case .back: return (SIMD3(0, 1, 0), z)
        case .left: return (SIMD3(-1, 0, 0), z)
        case .right: return (SIMD3(1, 0, 0), z)
        case .iso: return (SIMD3(1, -1, 0.9), z)
        case .isoFrontLeft: return (SIMD3(-1, -1, 0.9), z)
        case .isoBackRight: return (SIMD3(1, 1, 0.9), z)
        case .isoBackLeft: return (SIMD3(-1, 1, 0.9), z)
        }
    }

    // MARK: Geometrie

    /// `smooth`: Teil einer gekrümmten Fläche (Zylindermantel), ohne Facettenkanten gezeichnet.
    typealias Polygon = (points: [SIMD3<Float>], normal: SIMD3<Float>, smooth: Bool)

    static func polygons(_ primitive: DemoPrimitive) -> [Polygon] {
        switch primitive {
        case .box(let a, let b):
            let p = [
                SIMD3(a.x, a.y, a.z), SIMD3(b.x, a.y, a.z), SIMD3(b.x, b.y, a.z), SIMD3(a.x, b.y, a.z),
                SIMD3(a.x, a.y, b.z), SIMD3(b.x, a.y, b.z), SIMD3(b.x, b.y, b.z), SIMD3(a.x, b.y, b.z),
            ]
            return [
                ([p[0], p[3], p[2], p[1]], SIMD3(0, 0, -1), false),
                ([p[4], p[5], p[6], p[7]], SIMD3(0, 0, 1), false),
                ([p[0], p[1], p[5], p[4]], SIMD3(0, -1, 0), false),
                ([p[2], p[3], p[7], p[6]], SIMD3(0, 1, 0), false),
                ([p[1], p[2], p[6], p[5]], SIMD3(1, 0, 0), false),
                ([p[3], p[0], p[4], p[7]], SIMD3(-1, 0, 0), false),
            ]
        case .cylinder(let axis, let center, let radius, let from, let to):
            let segments = 28
            let (u, v) = axis == 0 ? (1, 2) : (axis == 1 ? (2, 0) : (0, 1))
            func point(_ angle: Float, _ t: Float) -> SIMD3<Float> {
                var p = center
                p[u] += radius * cos(angle)
                p[v] += radius * sin(angle)
                p[axis] = t
                return p
            }
            var result: [Polygon] = []
            var bottom: [SIMD3<Float>] = []
            var top: [SIMD3<Float>] = []
            for i in 0..<segments {
                let a0 = Float(i) / Float(segments) * 2 * .pi
                let a1 = Float(i + 1) / Float(segments) * 2 * .pi
                var normal = SIMD3<Float>(repeating: 0)
                normal[u] = cos((a0 + a1) / 2)
                normal[v] = sin((a0 + a1) / 2)
                result.append(([point(a0, from), point(a1, from), point(a1, to), point(a0, to)], normal, true))
                bottom.append(point(a0, from))
                top.append(point(a0, to))
            }
            var down = SIMD3<Float>(repeating: 0)
            down[axis] = -1
            result.append((bottom.reversed(), down, false))
            result.append((top, -down, false))
            return result
        }
    }

    /// Schneidet alle Polygone an der Ebene `p[axis] = value` und behält die Seite darunter.
    static func clip(_ polygons: [Polygon], axis: Int, value: Float) -> [Polygon] {
        polygons.compactMap { polygon in
            var output: [SIMD3<Float>] = []
            let points = polygon.points
            for i in points.indices {
                let current = points[i]
                let next = points[(i + 1) % points.count]
                let currentInside = current[axis] <= value
                let nextInside = next[axis] <= value
                if currentInside { output.append(current) }
                if currentInside != nextInside {
                    let t = (value - current[axis]) / (next[axis] - current[axis])
                    output.append(current + (next - current) * t)
                }
            }
            return output.count >= 3 ? (output, polygon.normal, polygon.smooth) : nil
        }
    }

    /// Schnittfläche eines konvexen Körpers in der Ebene (konvexe Hülle der Punkte auf der Ebene).
    static func cap(_ polygons: [Polygon], axis: Int, value: Float) -> Polygon? {
        let (u, v) = axis == 0 ? (1, 2) : (axis == 1 ? (2, 0) : (0, 1))
        var onPlane: [SIMD3<Float>] = []
        for polygon in polygons {
            for p in polygon.points where abs(p[axis] - value) < 0.001 { onPlane.append(p) }
        }
        guard onPlane.count >= 3 else { return nil }
        let sorted = onPlane.sorted { $0[u] == $1[u] ? $0[v] < $1[v] : $0[u] < $1[u] }
        func turn(_ o: SIMD3<Float>, _ a: SIMD3<Float>, _ b: SIMD3<Float>) -> Float {
            (a[u] - o[u]) * (b[v] - o[v]) - (a[v] - o[v]) * (b[u] - o[u])
        }
        var lower: [SIMD3<Float>] = []
        for p in sorted {
            while lower.count >= 2 && turn(lower[lower.count - 2], lower[lower.count - 1], p) <= 0 { lower.removeLast() }
            lower.append(p)
        }
        var upper: [SIMD3<Float>] = []
        for p in sorted.reversed() {
            while upper.count >= 2 && turn(upper[upper.count - 2], upper[upper.count - 1], p) <= 0 { upper.removeLast() }
            upper.append(p)
        }
        let hull = Array(lower.dropLast() + upper.dropLast())
        guard hull.count >= 3 else { return nil }
        var normal = SIMD3<Float>(repeating: 0)
        normal[axis] = 1
        return (hull, normal, false)
    }

    // MARK: Zeichnen

    func draw(in context: inout GraphicsContext) {
        drawGrid(in: &context)
        for face in faces {
            var path = Path()
            path.addLines(face.points)
            path.closeSubpath()
            if let fill = face.fill { context.fill(path, with: .color(fill)) }
            if face.lineWidth > 0 {
                context.stroke(path, with: .color(face.stroke), style: StrokeStyle(lineWidth: face.lineWidth,
                                                                                   lineJoin: .round))
            }
        }
        drawSectionPlane(in: &context)
        drawMeasurements(in: &context)
        drawTriad(in: &context)
    }

    private func drawGrid(in context: inout GraphicsContext) {
        guard let grid, abs(toEye.z) > 0.2 else { return }
        let pad: Float = 30
        let z = grid.min.z
        let x0 = ((grid.min.x - pad) / grid.step).rounded(.down) * grid.step
        let x1 = ((grid.max.x + pad) / grid.step).rounded(.up) * grid.step
        let y0 = ((grid.min.y - pad) / grid.step).rounded(.down) * grid.step
        let y1 = ((grid.max.y + pad) / grid.step).rounded(.up) * grid.step
        var minor = Path()
        var major = Path()
        var x = x0
        while x <= x1 + 0.01 {
            var line = Path()
            line.move(to: project(SIMD3(x, y0, z)))
            line.addLine(to: project(SIMD3(x, y1, z)))
            if abs(x.remainder(dividingBy: 50)) < 0.01 { major.addPath(line) } else { minor.addPath(line) }
            x += grid.step
        }
        var y = y0
        while y <= y1 + 0.01 {
            var line = Path()
            line.move(to: project(SIMD3(x0, y, z)))
            line.addLine(to: project(SIMD3(x1, y, z)))
            if abs(y.remainder(dividingBy: 50)) < 0.01 { major.addPath(line) } else { minor.addPath(line) }
            y += grid.step
        }
        let color = dark ? Color.white : Color.black
        context.stroke(minor, with: .color(color.opacity(0.05)), lineWidth: 0.5)
        context.stroke(major, with: .color(color.opacity(0.11)), lineWidth: 0.7)
    }

    private func drawSectionPlane(in context: inout GraphicsContext) {
        guard let section else { return }
        let (lo, hi) = section.bounds
        let pad = (hi - lo) * 0.12 + 8
        let a = lo - pad, b = hi + pad
        let axis = section.axis
        let (u, v) = axis == 0 ? (1, 2) : (axis == 1 ? (2, 0) : (0, 1))
        var corners: [SIMD3<Float>] = []
        for (cu, cv) in [(a[u], a[v]), (b[u], a[v]), (b[u], b[v]), (a[u], b[v])] {
            var p = SIMD3<Float>(repeating: section.offset)
            p[u] = cu
            p[v] = cv
            p[axis] = section.offset
            corners.append(p)
        }
        var path = Path()
        path.addLines(corners.map(project))
        path.closeSubpath()
        context.fill(path, with: .color(Color.accentColor.opacity(0.07)))
        context.stroke(path, with: .color(Color.accentColor.opacity(0.6)), style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
    }

    private func drawMeasurements(in context: inout GraphicsContext) {
        let color = Color.orange
        for item in measurements where !item.points.isEmpty {
            let points = item.points.map(project)
            var path = Path()
            path.addLines(points)
            context.stroke(path, with: .color(color), lineWidth: 1.6)
            for p in points {
                context.fill(Path(ellipseIn: CGRect(x: p.x - 3.5, y: p.y - 3.5, width: 7, height: 7)), with: .color(color))
            }
            let mid = points.count >= 2
                ? CGPoint(x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2) : points[0]
            let label = context.resolve(
                Text(Self.shortLabel(item)).font(.system(size: 11, weight: .semibold)).foregroundStyle(.white))
            let size = label.measure(in: CGSize(width: 400, height: 40))
            let rect = CGRect(
                x: mid.x - size.width / 2 - 7, y: mid.y - size.height - 14, width: size.width + 14,
                height: size.height + 6)
            context.fill(Path(roundedRect: rect, cornerRadius: 6), with: .color(color))
            context.draw(label, at: CGPoint(x: rect.midX, y: rect.midY))
        }
    }

    /// Kurzer Text am Maß: nur der Hauptwert.
    static func shortLabel(_ item: MeasurementItem) -> String {
        if let angle = item.values["angle"], item.kind == "angle" { return KevFormat.angle(angle) }
        if let distance = item.values["distance"] { return KevFormat.mm(distance, digits: 2) }
        return item.text
    }

    private func drawTriad(in context: inout GraphicsContext) {
        let origin = CGPoint(x: 44, y: size.height - 44)
        let axes: [(SIMD3<Float>, String, Color)] = [
            (SIMD3(1, 0, 0), "X", .red), (SIMD3(0, 1, 0), "Y", .green), (SIMD3(0, 0, 1), "Z", .blue),
        ]
        let sorted = axes.sorted { simd_dot($0.0, toEye) < simd_dot($1.0, toEye) }
        for (axis, name, color) in sorted {
            let dx = CGFloat(simd_dot(axis, right)) * 26
            let dy = -CGFloat(simd_dot(axis, up)) * 26
            var line = Path()
            line.move(to: origin)
            line.addLine(to: CGPoint(x: origin.x + dx, y: origin.y + dy))
            context.stroke(line, with: .color(color.opacity(0.85)), style: StrokeStyle(lineWidth: 2, lineCap: .round))
            if abs(dx) + abs(dy) > 4 {
                let label = context.resolve(Text(name).font(.system(size: 10, weight: .bold)).foregroundStyle(color))
                context.draw(label, at: CGPoint(x: origin.x + dx * 1.35, y: origin.y + dy * 1.35))
            }
        }
    }

    // MARK: Klick

    /// Vorderstes Teil unter dem Punkt.
    func hit(_ location: CGPoint) -> String? {
        for face in faces.reversed() where face.fill != nil || style == .wireframe {
            var path = Path()
            path.addLines(face.points)
            path.closeSubpath()
            if path.contains(location) { return face.partID }
        }
        return nil
    }
}
