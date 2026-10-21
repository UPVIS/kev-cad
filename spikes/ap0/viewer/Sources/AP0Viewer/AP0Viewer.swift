// AP0 Viewer-Test für Kev CAD.
//
// Aufruf: AP0Viewer <datei.kcad> [--chunk 16000] [--repeat N] [--seconds 6] [--out ergebnis.json] [--png bild.png]
//
// Ablauf: Teile laden, Fenster auf dem zweiten Monitor öffnen (ohne die App nach vorn zu holen), Modell
// einpassen, einige Sekunden automatisch drehen und dabei die tatsächlich angezeigten Bilder zählen, dann ein
// Raster von Klickpunkten über die GPU-Pick-Funktion abfragen und mit einer eigenen Strahlberechnung auf der CPU
// vergleichen, zum Schluss ein Offscreen-Bild rendern. Ergebnis als JSON, danach beendet sich die App.

import AppKit
import MetalKit
import OCCTSwiftViewport
import SwiftUI
import simd

func log(_ s: String) {
    FileHandle.standardError.write("[\(String(format: "%.2f", CACurrentMediaTime()))] \(s)\n".data(using: .utf8)!)
}

// MARK: - Argumente

struct Options {
    var file = ""
    var chunk: Int? = nil
    var repeatCount = 1
    var seconds = 6.0
    var out = "ergebnis.json"
    var png = "bild.png"
    var only: String? = nil
    var noCPU = false

    static func parse() -> Options {
        var o = Options()
        var args = Array(CommandLine.arguments.dropFirst())
        while !args.isEmpty {
            let a = args.removeFirst()
            switch a {
            case "--chunk": o.chunk = Int(args.removeFirst())
            case "--repeat": o.repeatCount = Int(args.removeFirst()) ?? 1
            case "--seconds": o.seconds = Double(args.removeFirst()) ?? 6
            case "--out": o.out = args.removeFirst()
            case "--png": o.png = args.removeFirst()
            case "--only": o.only = args.removeFirst()
            case "--nocpu": o.noCPU = true
            default: o.file = a
            }
        }
        return o
    }
}

// MARK: - .kcad lesen

struct KPart: Decodable {
    let name: String
    let color: [Float]
    let n_vert, n_tri, n_face, n_edge, n_epts: Int
    let off_pos, off_nrm, off_tri, off_tface, off_epts, off_eoff: Int
}

struct KHead: Decodable { let parts: [KPart] }

func readArray<T>(_ data: Data, _ base: Int, _ offset: Int, _ count: Int, as: T.Type) -> [T] {
    var out = [T](unsafeUninitializedCapacity: count) { _, n in n = count }
    out.withUnsafeMutableBytes { dst in
        data.withUnsafeBytes { src in
            dst.copyMemory(from: UnsafeRawBufferPointer(rebasing: src[(base + offset)..<(base + offset + count * MemoryLayout<T>.stride)]))
        }
    }
    return out
}

/// Ein Teil in CPU-Form, für den Aufbau der Körper und die Kontrollrechnung beim Picking.
struct PartMesh {
    let name: String
    let color: SIMD4<Float>
    let positions: [Float]
    let normals: [Float]
    let triangles: [UInt32]
    let triFace: [Int32]
    let edgePoints: [Float]
    let edgeOffsets: [UInt32]
}

func loadKCAD(_ path: String) throws -> [PartMesh] {
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    let headLen = Int(data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 8, as: UInt32.self) })
    let head = try JSONDecoder().decode(KHead.self, from: data[12..<(12 + headLen)])
    let base = 12 + headLen + ((4 - (12 + headLen) % 4) % 4)
    return head.parts.map { p in
        PartMesh(
            name: p.name,
            color: SIMD4(p.color[0], p.color[1], p.color[2], p.color.count > 3 ? p.color[3] : 1),
            positions: readArray(data, base, p.off_pos, p.n_vert * 3, as: Float.self),
            normals: readArray(data, base, p.off_nrm, p.n_vert * 3, as: Float.self),
            triangles: readArray(data, base, p.off_tri, p.n_tri * 3, as: UInt32.self),
            triFace: readArray(data, base, p.off_tface, p.n_tri, as: Int32.self),
            edgePoints: readArray(data, base, p.off_epts, p.n_epts * 3, as: Float.self),
            edgeOffsets: readArray(data, base, p.off_eoff, p.n_edge + 1, as: UInt32.self))
    }
}

// MARK: - Körper bauen

/// Was ein Körper im Viewport über seine Herkunft weiß: Teil, Fläche je Dreieck, Kante je Segment.
struct BodyInfo {
    let part: Int
    let triFace: [Int32]
    let segEdge: [Int32]
    let positions: [Float]
    let triangles: [UInt32]
    let transform: simd_float4x4
}

/// Baut aus einem Teil einen oder mehrere Körper. Mit `limit` wird das Teil so aufgeteilt, dass kein Körper
/// mehr als `limit` Dreiecke oder Kantensegmente hat (die Pick-ID hat nur 14 Bit für die Primitivnummer).
func makeBodies(_ m: PartMesh, part: Int, limit: Int?, transform: simd_float4x4, idPrefix: String)
    -> [(ViewportBody, BodyInfo)]
{
    let triCount = m.triangles.count / 3
    let edgeCount = m.edgeOffsets.count - 1
    let lim = limit ?? Int.max

    // Kantenzüge in Gruppen aufteilen, jede höchstens `lim` Segmente
    var edgeGroups: [[Int]] = [[]]
    var segInGroup = 0
    for e in 0..<edgeCount {
        let segs = Int(m.edgeOffsets[e + 1] - m.edgeOffsets[e]) - 1
        if segs <= 0 { continue }
        if segInGroup + segs > lim && !edgeGroups[edgeGroups.count - 1].isEmpty {
            edgeGroups.append([])
            segInGroup = 0
        }
        edgeGroups[edgeGroups.count - 1].append(e)
        segInGroup += segs
    }
    let triChunks = limit == nil ? 1 : max(1, (triCount + lim - 1) / max(lim, 1))
    let chunkCount = max(triChunks, edgeGroups.count)

    var result: [(ViewportBody, BodyInfo)] = []
    for c in 0..<chunkCount {
        let t0 = limit == nil ? 0 : min(c * lim, triCount)
        let t1 = limit == nil ? triCount : min(t0 + lim, triCount)
        // Punkte umnummerieren, damit jeder Teilkörper nur seine eigenen Punkte trägt
        var remap = [Int32](repeating: -1, count: m.positions.count / 3)
        var pos: [Float] = []
        var nrm: [Float] = []
        var idx: [UInt32] = []
        idx.reserveCapacity((t1 - t0) * 3)
        for t in t0..<t1 {
            for k in 0..<3 {
                let v = Int(m.triangles[t * 3 + k])
                if remap[v] < 0 {
                    remap[v] = Int32(pos.count / 3)
                    pos.append(contentsOf: m.positions[(v * 3)..<(v * 3 + 3)])
                    nrm.append(contentsOf: m.normals[(v * 3)..<(v * 3 + 3)])
                }
                idx.append(UInt32(remap[v]))
            }
        }
        let triFace = Array(m.triFace[t0..<t1])

        var edges: [[SIMD3<Float>]] = []
        var segEdge: [Int32] = []
        if c < edgeGroups.count {
            for e in edgeGroups[c] {
                let a = Int(m.edgeOffsets[e]), b = Int(m.edgeOffsets[e + 1])
                var poly: [SIMD3<Float>] = []
                poly.reserveCapacity(b - a)
                for p in a..<b {
                    poly.append(SIMD3(m.edgePoints[p * 3], m.edgePoints[p * 3 + 1], m.edgePoints[p * 3 + 2]))
                }
                edges.append(poly)
                segEdge.append(contentsOf: repeatElement(Int32(e), count: poly.count - 1))
            }
        }
        var verts: [SIMD3<Float>] = []
        verts.reserveCapacity(pos.count / 3)
        var i = 0
        while i + 2 < pos.count {
            verts.append(SIMD3(pos[i], pos[i + 1], pos[i + 2]))
            i += 3
        }
        if verts.isEmpty, let first = edges.first?.first { verts = [first] }

        let body = ViewportBody(
            id: "\(idPrefix)\(part):\(m.name)#\(c)",
            vertexData: [],
            indices: idx,
            edges: edges,
            faceIndices: triFace,
            edgeIndices: segEdge,
            vertices: verts,
            color: m.color,
            transform: transform,
            meshPositions: pos,
            meshNormals: nrm)
        result.append(
            (body, BodyInfo(part: part, triFace: triFace, segEdge: segEdge, positions: pos, triangles: idx, transform: transform)))
    }
    return result
}

// MARK: - Bildzähler

/// Sitzt zwischen MTKView und dem Renderer von OCCTSwiftViewport und zählt angezeigte Bilder.
final class FrameProbe: NSObject, MTKViewDelegate {
    let inner: MTKViewDelegate
    private let lock = NSLock()
    private var presented: [CFTimeInterval] = []
    private(set) var cpuDraw: [Double] = []
    var recording = false
    var firstPresent: CFTimeInterval = 0

    init(inner: MTKViewDelegate) { self.inner = inner }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        inner.mtkView(view, drawableSizeWillChange: size)
    }

    func draw(in view: MTKView) {
        let rec = recording
        if let d = view.currentDrawable {
            d.addPresentedHandler { [weak self] drawable in
                guard let self, drawable.presentedTime > 0 else { return }
                self.lock.lock()
                if self.firstPresent == 0 { self.firstPresent = drawable.presentedTime }
                if rec { self.presented.append(drawable.presentedTime) }
                self.lock.unlock()
            }
        }
        let t = CACurrentMediaTime()
        inner.draw(in: view)
        if rec { cpuDraw.append((CACurrentMediaTime() - t) * 1000) }
    }

    func takePresented() -> [CFTimeInterval] {
        lock.lock()
        defer { lock.unlock() }
        return presented
    }
}

// MARK: - Strahltest auf der CPU

func rayFromPixel(_ px: SIMD2<Float>, size: SIMD2<Float>, camera: CameraState) -> (SIMD3<Float>, SIMD3<Float>) {
    let aspect = size.x / size.y
    let proj = camera.projectionMatrix(aspectRatio: aspect, near: 1, far: 1_000_000)
    let inv = simd_inverse(proj * camera.viewMatrix)
    let ndc = SIMD2<Float>((px.x + 0.5) / size.x * 2 - 1, 1 - (px.y + 0.5) / size.y * 2)
    func unproject(_ z: Float) -> SIMD3<Float> {
        let p = inv * SIMD4<Float>(ndc.x, ndc.y, z, 1)
        return SIMD3(p.x, p.y, p.z) / p.w
    }
    let a = unproject(0.1), b = unproject(0.9)
    return (a, simd_normalize(b - a))
}

/// Nächster getroffener Körper und Dreieck (Möller-Trumbore), nur sichtbare Körper.
func cpuPick(origin: SIMD3<Float>, dir: SIMD3<Float>, infos: [BodyInfo]) -> (body: Int, tri: Int)? {
    var best: (Int, Int)? = nil
    var bestT = Float.greatestFiniteMagnitude
    for (b, info) in infos.enumerated() {
        let m = info.transform
        let p = info.positions
        let ts = info.triangles
        func v(_ i: UInt32) -> SIMD3<Float> {
            let k = Int(i) * 3
            let w = m * SIMD4<Float>(p[k], p[k + 1], p[k + 2], 1)
            return SIMD3(w.x, w.y, w.z)
        }
        var t = 0
        while t < ts.count {
            let v0 = v(ts[t]), v1 = v(ts[t + 1]), v2 = v(ts[t + 2])
            let e1 = v1 - v0, e2 = v2 - v0
            let h = simd_cross(dir, e2)
            let a = simd_dot(e1, h)
            if abs(a) > 1e-9 {
                let f = 1 / a
                let s = origin - v0
                let u = f * simd_dot(s, h)
                if u >= 0 && u <= 1 {
                    let q = simd_cross(s, e1)
                    let vv = f * simd_dot(dir, q)
                    if vv >= 0 && u + vv <= 1 {
                        let dist = f * simd_dot(e2, q)
                        if dist > 0 && dist < bestT {
                            bestT = dist
                            best = (b, t / 3)
                        }
                    }
                }
            }
            t += 3
        }
    }
    return best
}

// MARK: - App

@MainActor
final class Bench: ObservableObject {
    let opts = Options.parse()
    let controller: ViewportController = {
        var cfg = ViewportConfiguration.cad
        cfg.pickingConfiguration = PickingConfiguration(isEnabled: true)
        return ViewportController(configuration: cfg)
    }()
    @Published var bodies: [ViewportBody] = []
    var infos: [BodyInfo] = []
    var parts: [PartMesh] = []
    var result: [String: Any] = [:]
    var probe: FrameProbe?
    let t0 = CACurrentMediaTime()

    init() {
        let tl = CACurrentMediaTime()
        do { parts = try loadKCAD(opts.file) } catch {
            print("Datei nicht lesbar: \(error)")
            exit(1)
        }
        let loadMs = (CACurrentMediaTime() - tl) * 1000

        let tb = CACurrentMediaTime()
        // Breite des Modells für das Nebeneinanderlegen beim Belastungstest
        var minX = Float.greatestFiniteMagnitude, maxX = -Float.greatestFiniteMagnitude
        for p in parts {
            var i = 0
            while i < p.positions.count {
                minX = min(minX, p.positions[i])
                maxX = max(maxX, p.positions[i])
                i += 3
            }
        }
        let step = (maxX - minX) * 1.15
        var all: [(ViewportBody, BodyInfo)] = []
        for r in 0..<opts.repeatCount {
            var tr = matrix_identity_float4x4
            tr.columns.3 = SIMD4(Float(r) * step, 0, 0, 1)
            for (i, p) in parts.enumerated() where opts.only == nil || p.name.contains(opts.only!) {
                all += makeBodies(p, part: i, limit: opts.chunk, transform: tr, idPrefix: "r\(r)/")
            }
        }
        bodies = all.map { $0.0 }
        infos = all.map { $0.1 }
        let buildMs = (CACurrentMediaTime() - tb) * 1000

        controller.displayMode = .shadedWithEdges
        result["file"] = opts.file
        result["chunk"] = opts.chunk ?? 0
        result["repeat"] = opts.repeatCount
        result["parts"] = parts.count * opts.repeatCount
        result["bodies"] = bodies.count
        result["triangles"] = infos.reduce(0) { $0 + $1.triangles.count / 3 }
        result["edge_segments"] = infos.reduce(0) { $0 + $1.segEdge.count }
        result["max_triangles_per_body"] = infos.map { $0.triangles.count / 3 }.max() ?? 0
        result["load_ms"] = round(loadMs)
        result["build_bodies_ms"] = round(buildMs)
        log("geladen: \(parts.count) Teile, \(bodies.count) Körper, \(Int(loadMs)) ms Lesen, \(Int(buildMs)) ms Aufbau")
    }

    func findMTKView(_ v: NSView) -> MTKView? {
        if let m = v as? MTKView { return m }
        for s in v.subviews { if let m = findMTKView(s) { return m } }
        return nil
    }

    @MainActor
    func start(window: NSWindow) {
        log("Fenster da")
        // Auf den zweiten Monitor, falls vorhanden; nicht aktivieren, damit der Hauptbildschirm ungestört bleibt
        let screens = NSScreen.screens
        let screen = screens.count > 1 ? screens[1] : screens[0]
        let f = screen.visibleFrame
        let size = NSSize(width: min(1600, f.width - 80), height: min(1000, f.height - 80))
        window.setFrame(NSRect(x: f.minX + 40, y: f.maxY - size.height - 40, width: size.width, height: size.height), display: true)
        window.title = "Kev CAD · AP0 Viewer-Test"
        window.orderFrontRegardless()
        result["screen"] = screen.localizedName
        result["screen_max_fps"] = screen.maximumFramesPerSecond

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [self] in
            guard let mtk = findMTKView(window.contentView!), let inner = mtk.delegate else {
                print("MTKView nicht gefunden")
                NSApp.terminate(nil)
                return
            }
            log("MTKView gefunden, Zeichengröße \(mtk.drawableSize)")
            let p = FrameProbe(inner: inner)
            probe = p
            mtk.delegate = p
            result["preferred_fps"] = mtk.preferredFramesPerSecond
            // Isometrisch einpassen
            let aspect = Float(mtk.drawableSize.width / mtk.drawableSize.height)
            let iso = StandardView.isometricFrontRight.cameraState()
            if let fitted = iso.fit(to: bodies, aspectRatio: aspect, padding: 0.7) {
                controller.animateTo(fitted, duration: 0)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [self] in
                if p.firstPresent > 0 { result["first_frame_after_start_ms"] = round((p.firstPresent - t0) * 1000) }
                orbit(mtk: mtk, probe: p)
            }
        }
    }

    @MainActor
    func orbit(mtk: MTKView, probe: FrameProbe) {
        log("Drehen startet, erstes Bild: \(probe.firstPresent > 0)")
        probe.recording = true
        let started = CACurrentMediaTime()
        let timer = Timer(timeInterval: 1.0 / 120.0, repeats: true) { [self] t in
            controller.handleOrbit(translation: CGSize(width: 3, height: 0))
            if CACurrentMediaTime() - started > opts.seconds {
                t.invalidate()
                probe.recording = false
                let pres = probe.takePresented()
                let dur = (pres.last ?? 0) - (pres.first ?? 0)
                var intervals: [Double] = []
                for i in 1..<max(pres.count, 1) where pres.count > 1 { intervals.append((pres[i] - pres[i - 1]) * 1000) }
                intervals.sort()
                let cpu = probe.cpuDraw.sorted()
                func pct(_ a: [Double], _ q: Double) -> Double { a.isEmpty ? 0 : a[min(a.count - 1, Int(Double(a.count) * q))] }
                result["orbit_frames"] = pres.count
                result["orbit_fps"] = dur > 0 ? round(Double(pres.count - 1) / dur * 10) / 10 : 0
                result["frame_interval_ms_p50"] = round(pct(intervals, 0.5) * 100) / 100
                result["frame_interval_ms_p95"] = round(pct(intervals, 0.95) * 100) / 100
                result["frame_interval_ms_max"] = round((intervals.last ?? 0) * 100) / 100
                result["cpu_draw_ms_p50"] = round(pct(cpu, 0.5) * 100) / 100
                result["cpu_draw_ms_p95"] = round(pct(cpu, 0.95) * 100) / 100
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.picks(mtk: mtk) }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
    }

    @MainActor
    func picks(mtk: MTKView) {
        log("Picking startet")
        guard let renderer = (probe?.inner) as? ViewportRenderer else {
            result["pick_error"] = "Renderer nicht erreichbar"
            offscreen()
            return
        }
        let size = SIMD2<Float>(Float(mtk.drawableSize.width), Float(mtk.drawableSize.height))
        let cam = controller.cameraState
        var points: [SIMD2<Int>] = []
        let n = 11
        for iy in 1...n { for ix in 1...n {
            points.append(SIMD2(Int(size.x * Float(ix) / Float(n + 1)), Int(size.y * Float(iy) / Float(n + 1))))
        } }
        if opts.only != nil {
            // Gezielt: Schwerpunkte von Dreiecken über den ganzen Indexbereich des Teils
            points = []
            let proj = cam.projectionMatrix(aspectRatio: size.x / size.y, near: 1, far: 1_000_000)
            let vp = proj * cam.viewMatrix
            for info in infos {
                let triCount = info.triangles.count / 3
                let samples = 40
                for k in 0..<samples {
                    let t = k * triCount / samples
                    var c = SIMD3<Float>(0, 0, 0)
                    for j in 0..<3 {
                        let v = Int(info.triangles[t * 3 + j]) * 3
                        c += SIMD3(info.positions[v], info.positions[v + 1], info.positions[v + 2])
                    }
                    c /= 3
                    let w4 = info.transform * SIMD4<Float>(c.x, c.y, c.z, 1)
                    let clip = vp * w4
                    let ndc = SIMD2<Float>(clip.x / clip.w, clip.y / clip.w)
                    let px = SIMD2<Int>(Int((ndc.x + 1) / 2 * size.x), Int((1 - ndc.y) / 2 * size.y))
                    if px.x > 0 && px.y > 0 && px.x < Int(size.x) && px.y < Int(size.y) { points.append(px) }
                }
            }
        }
        let indexOfBody = Dictionary(uniqueKeysWithValues: bodies.enumerated().map { ($0.element.id, $0.offset) })
        var latencies: [Double] = []
        var stats = (gpuHit: 0, cpuHit: 0, bothMiss: 0, sameBody: 0, sameFace: 0, faceCompared: 0, edgeHits: 0, mismatch: [String]())

        func next(_ i: Int) {
            if i == points.count {
                latencies.sort()
                result["picks"] = points.count
                result["pick_gpu_hits"] = stats.gpuHit
                result["pick_cpu_hits"] = stats.cpuHit
                result["pick_both_miss"] = stats.bothMiss
                result["pick_edge_hits"] = stats.edgeHits
                result["pick_same_body"] = stats.sameBody
                result["pick_same_face"] = "\(stats.sameFace)/\(stats.faceCompared)"
                result["pick_mismatch_examples"] = Array(stats.mismatch.prefix(6))
                result["pick_latency_ms_p50"] = latencies.isEmpty ? 0 : round(latencies[latencies.count / 2] * 100) / 100
                result["pick_latency_ms_max"] = round((latencies.last ?? 0) * 100) / 100
                offscreen()
                return
            }
            let px = points[i]
            let tp = CACurrentMediaTime()
            renderer.performPick(at: px) { pick in
                let lat = (CACurrentMediaTime() - tp) * 1000
                DispatchQueue.main.async { [self] in
                    latencies.append(lat)
                    let (o, d) = rayFromPixel(SIMD2(Float(px.x), Float(px.y)), size: size, camera: cam)
                    let cpu = opts.noCPU ? nil : cpuPick(origin: o, dir: d, infos: infos)
                    if cpu != nil { stats.cpuHit += 1 }
                    if let pick, let b = indexOfBody[pick.bodyID] {
                        stats.gpuHit += 1
                        if pick.kind == .edge { stats.edgeHits += 1 }
                        if let cpu {
                            let gpuPart = infos[b].part, cpuPart = infos[cpu.body].part
                            if gpuPart == cpuPart && pick.bodyID.prefix(while: { $0 != "/" }) == bodies[cpu.body].id.prefix(while: { $0 != "/" }) {
                                stats.sameBody += 1
                            }
                            if pick.kind == .face && b == cpu.body {
                                stats.faceCompared += 1
                                let tri = pick.triangleIndex
                                let gpuFace = tri < infos[b].triFace.count ? infos[b].triFace[tri] : -1
                                let cpuFace = infos[cpu.body].triFace[cpu.tri]
                                if gpuFace == cpuFace {
                                    stats.sameFace += 1
                                } else {
                                    stats.mismatch.append("\(bodies[b].id): GPU Fläche \(gpuFace) (Dreieck \(tri)), CPU Fläche \(cpuFace) (Dreieck \(cpu.tri))")
                                }
                            } else if pick.kind == .face {
                                stats.mismatch.append("Körper GPU \(pick.bodyID) / CPU \(bodies[cpu.body].id)")
                            }
                        }
                    } else if cpu == nil {
                        stats.bothMiss += 1
                    }
                    next(i + 1)
                }
            }
        }
        next(0)
    }

    @MainActor
    func offscreen() {
        log("Offscreen startet")
        guard let off = OffscreenRenderer() else {
            result["offscreen_error"] = "OffscreenRenderer nicht verfügbar"
            finish()
            return
        }
        let w = 1600, h = 1000
        let iso = StandardView.isometricFrontRight.cameraState()
        let cam = iso.fit(to: bodies, aspectRatio: Float(w) / Float(h), padding: 0.62) ?? controller.cameraState
        let opts = OffscreenRenderOptions(width: w, height: h, cameraState: cam, displayMode: .shadedWithEdges)
        var times: [Double] = []
        for _ in 0..<5 {
            let t = CACurrentMediaTime()
            _ = off.render(bodies: bodies, options: opts)
            times.append((CACurrentMediaTime() - t) * 1000)
        }
        result["offscreen_first_ms"] = round(times[0])
        result["offscreen_ms_avg_warm"] = round(times.dropFirst().reduce(0, +) / Double(times.count - 1))
        do {
            _ = try off.renderToPNG(bodies: bodies, url: URL(fileURLWithPath: self.opts.png), options: opts)
            result["png"] = self.opts.png
        } catch {
            result["offscreen_error"] = "\(error)"
        }
        finish()
    }

    func finish() {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count) }
        }
        if kr == KERN_SUCCESS { result["resident_mb"] = Int(info.resident_size / 1_000_000) }
        if let d = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
            try? d.write(to: URL(fileURLWithPath: opts.out))
            print(String(decoding: d, as: UTF8.self))
        }
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var bench: Bench?

    @MainActor
    func applicationDidFinishLaunching(_ notification: Notification) {
        let b = Bench()
        bench = b
        let w = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1600, height: 1000),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered, defer: false)
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: BenchView(bench: b))
        window = w
        b.start(window: w)
    }
}

struct BenchView: View {
    @ObservedObject var bench: Bench
    var body: some View {
        MetalViewportView(controller: bench.controller, bodies: $bench.bodies)
    }
}

@main
struct Main {
    static func main() {
        let app = NSApplication.shared
        // Kein Dock-Symbol, kein Fokuswechsel: der Hauptbildschirm bleibt ungestört
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
