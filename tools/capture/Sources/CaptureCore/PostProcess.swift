import Foundation
import simd

public struct KnownMeasure {
    public var name: String
    public var mm: Double
    public init(name: String, mm: Double) { self.name = name; self.mm = mm }
}

public struct PostProcessOptions {
    public var known: KnownMeasure? = nil
    public var checks: [KnownMeasure] = []
    public var cutFloor = true
    public var writeUSDZ = true
    /// Ordner für Kontrollbilder (Blender); nil = keine
    public var previewDir: URL? = nil
    public init() {}
}

public struct PostReport {
    public var summary: [String: Any] = [:]
    public var extraFiles: [String] = []
}

/// Nachbearbeitung des Object-Capture-Netzes:
/// 1. Y oben → Z oben, Bodenebene per RANSAC (Normale nahe der Senkrechten, Kameras liegen darüber)
/// 2. Boden auf z = 0 legen und abschneiden, Objekt = Netzteile am Blickpunkt der Kameras
/// 3. Hauptachsen waagrecht über das kleinste umschließende Rechteck (lange Seite = X)
/// 4. Maßstab über ein bekanntes Maß, Prüfmaße, Hüllmaß, Ebenen oben/unten, Räder (Kreisausgleich)
/// 5. Netz, Punktwolke und Kameras im mm-System schreiben, Bericht als JSON und Markdown
public final class PostProcessor {
    let layout: Layout
    let options: PostProcessOptions
    let log = ProgressLog.shared

    public init(layout: Layout, options: PostProcessOptions) {
        self.layout = layout
        self.options = options
    }

    // Object Capture (Y oben) → Z oben: (x, y, z) ↦ (x, −z, y)
    static let yUpToZUp = simd_double4x4(rows: [
        SIMD4(1, 0, 0, 0), SIMD4(0, 0, -1, 0), SIMD4(0, 1, 0, 0), SIMD4(0, 0, 0, 1),
    ])

    public func run() throws -> PostReport {
        let t0 = Date()
        let fm = FileManager.default
        guard let objName = try fm.contentsOfDirectory(atPath: layout.rawOBJDir.path).first(where: { $0.hasSuffix(".obj") })
        else { throw CaptureError.message("Kein OBJ in \(layout.rawOBJDir.path)") }
        let mesh = try OBJMesh(url: layout.rawOBJDir.appendingPathComponent(objName))
        log.progress("post", 0.1, ["step": "mesh_loaded"])
        let cams = try loadCameras()

        // --- 1. Z oben, Boden finden -------------------------------------------------------------
        let m0 = Self.yUpToZUp
        let pts0 = mesh.positions.map { (m0 * SIMD4($0, 1)).xyz }
        let camPos0 = cams.map { (m0 * SIMD4(SIMD3<Double>($0.cameraToWorld.columns.3.xyz), 1)).xyz }
        let lo = pts0.reduce(SIMD3(repeating: Double.infinity)) { simd_min($0, $1) }
        let hi = pts0.reduce(SIMD3(repeating: -Double.infinity)) { simd_max($0, $1) }
        let diag = simd_length(hi - lo)
        let tol = diag * 0.004
        var floorFound = false
        var floorPlane = Plane(normal: SIMD3(0, 0, 1), d: -lo.z)
        var floorInliers = 0
        var upGuess: SIMD3<Double>? = nil
        var floorNote = ""
        // Kandidaten von oben nach unten: eine waagrechte Ebene ist nur dann Boden, wenn fast nichts darunter liegt
        // (sonst ist es z. B. die Oberseite eines Rahmens, und die Maskierung hat den echten Boden entfernt)
        var searchPts = pts0
        for attempt in 0..<3 {
            guard searchPts.count > 200,
                  let (pl, inl) = Geo.ransacPlane(searchPts, threshold: tol, iterations: 900, seed: 11 + UInt64(attempt),
                                                  allowed: { abs($0.z) > cos(30 * Double.pi / 180) }) else { break }
            // Kameras liegen über dem Boden: danach das Vorzeichen der Normale
            let above = camPos0.filter { pl.distance($0) > 0 }.count
            let plane = above * 2 >= camPos0.count ? pl : Plane(normal: -pl.normal, d: -pl.d)
            if upGuess == nil { upGuess = plane.normal }
            let inlPts = inl.map { searchPts[$0] }
            let ilo = inlPts.reduce(SIMD3(repeating: Double.infinity)) { simd_min($0, $1) }
            let ihi = inlPts.reduce(SIMD3(repeating: -Double.infinity)) { simd_max($0, $1) }
            let spread = simd_length((ihi - ilo) * SIMD3(1, 1, 0)) / max(simd_length((hi - lo) * SIMD3(1, 1, 0)), 1e-9)
            let below = pts0.filter { plane.distance($0) < -2 * tol }
            let belowFrac = Double(below.count) / Double(pts0.count)
            if Double(inl.count) > 0.08 * Double(pts0.count) && spread > 0.5 && belowFrac < 0.05 {
                floorFound = true
                floorPlane = plane
                floorInliers = inl.count
                break
            }
            floorNote += "Ebene \(attempt + 1) verworfen (\(Int(belowFrac * 100)) % der Punkte darunter, \(inl.count) auf der Ebene). "
            searchPts = below
        }
        if !floorFound {
            // kein Boden im Netz (Maskierung hat ihn entfernt): Auflageebene senkrecht zur stärksten waagrechten
            // Ebene (bzw. Y von Object Capture) durch die untersten Punkte
            let n = upGuess ?? SIMD3(0, 0, 1)
            let h = pts0.map { simd_dot(n, $0) }
            floorPlane = Plane(normal: n, d: -Geo.percentile(h, 0.002))
            log.warn("Keine Bodenebene im Netz gefunden – Auflage auf den untersten Punkten angenommen. " + floorNote)
        }
        let rFloor = Self.rotation(from: floorPlane.normal, to: SIMD3(0, 0, 1))
        // Punkt auf der Ebene
        let p0 = -floorPlane.d * floorPlane.normal
        let m1 = Self.translation(SIMD3(0, 0, 0)) * rFloor * Self.translation(-p0)
        var pts1 = pts0.map { (m1 * SIMD4($0, 1)).xyz }
        let camPos1 = camPos0.map { (m1 * SIMD4($0, 1)).xyz }
        let camDir1 = cams.map { c -> SIMD3<Double> in
            let d = -SIMD3<Double>(c.cameraToWorld.columns.2.xyz)
            return simd_normalize(((m1 * m0) * SIMD4(d, 0)).xyz)
        }
        log.progress("post", 0.3, ["step": "floor", "floor_found": floorFound])

        // --- 2. Boden abschneiden, Objekt wählen ----------------------------------------------------
        let cutTol = tol * 1.5
        var keep = [Bool](repeating: true, count: mesh.faces.count)
        if options.cutFloor {
            for (i, f) in mesh.faces.enumerated() {
                let c = (pts1[Int(f.x)].z + pts1[Int(f.y)].z + pts1[Int(f.z)].z) / 3
                if c < cutTol { keep[i] = false }
            }
        }
        let lookAt = Self.lookAtPoint(origins: camPos1, dirs: camDir1)
        let comps = Self.components(faces: mesh.faces, keep: keep, vertexCount: pts1.count)
        var selected = Set<Int>()
        struct CompInfo { var id: Int; var faces: Int; var lo: SIMD3<Double>; var hi: SIMD3<Double> }
        var infos: [CompInfo] = []
        for (id, faceIdx) in comps.enumerated() {
            var clo = SIMD3(repeating: Double.infinity), chi = SIMD3(repeating: -Double.infinity)
            for fi in faceIdx {
                let f = mesh.faces[fi]
                for v in [f.x, f.y, f.z] { clo = simd_min(clo, pts1[Int(v)]); chi = simd_max(chi, pts1[Int(v)]) }
            }
            infos.append(CompInfo(id: id, faces: faceIdx.count, lo: clo, hi: chi))
        }
        let minFaces = max(30, mesh.faces.count / 400)
        let la2 = SIMD2(lookAt.x, lookAt.y)
        func distXY(_ c: CompInfo) -> Double {
            let q = simd_clamp(la2, SIMD2(c.lo.x, c.lo.y), SIMD2(c.hi.x, c.hi.y))
            return simd_length(q - la2)
        }
        let candidates = infos.filter { $0.faces >= minFaces && $0.hi.z - $0.lo.z > cutTol }
        guard let main = candidates.min(by: { a, b in
            // nahe am Blickpunkt, bei Gleichstand das größere
            let da = distXY(a), db = distXY(b)
            if abs(da - db) > diag * 0.02 { return da < db }
            return a.faces > b.faces
        }) else { throw CaptureError.message("Kein Objekt über dem Boden gefunden") }
        selected.insert(main.id)
        if ProcessInfo.processInfo.environment["KEVCAD_CAPTURE_DEBUG"] != nil {
            log.info("Blickpunkt \(lookAt), Haupt-Netzteil \(main.id) mit \(main.faces) Dreiecken, \(main.lo) … \(main.hi)")
            for c in candidates.prefix(12) { log.info("  Teil \(c.id): \(c.faces) Dreiecke, \(c.lo) … \(c.hi), Abstand \(distXY(c))") }
        }
        let grow = (main.hi - main.lo) * 0.08
        // weitere Teile nur, wenn sie überwiegend innerhalb des Hauptteils liegen und es berühren
        // (z. B. abgelöste Räder); frei schwebende Reste der Umgebung bleiben draußen
        let cell = simd_length(main.hi - main.lo) * 0.012
        func key(_ p: SIMD3<Double>) -> SIMD3<Int> {
            SIMD3(Int((p.x / cell).rounded(.down)), Int((p.y / cell).rounded(.down)), Int((p.z / cell).rounded(.down)))
        }
        var mainCells = Set<SIMD3<Int>>()
        for fi in comps[main.id] {
            let f = mesh.faces[fi]
            for v in [f.x, f.y, f.z] { mainCells.insert(key(pts1[Int(v)])) }
        }
        func touchesMain(_ id: Int) -> Bool {
            for fi in comps[id] {
                let f = mesh.faces[fi]
                for v in [f.x, f.y, f.z] {
                    let k = key(pts1[Int(v)])
                    for dx in -1...1 { for dy in -1...1 { for dz in -1...1 where mainCells.contains(k &+ SIMD3(dx, dy, dz)) { return true } } }
                }
            }
            return false
        }
        for c in candidates where c.id != main.id && c.faces <= main.faces {
            let ox = max(0, min(c.hi.x, main.hi.x + grow.x) - max(c.lo.x, main.lo.x - grow.x))
            let oy = max(0, min(c.hi.y, main.hi.y + grow.y) - max(c.lo.y, main.lo.y - grow.y))
            let area = max((c.hi.x - c.lo.x) * (c.hi.y - c.lo.y), 1e-12)
            if ox * oy / area > 0.6 && touchesMain(c.id) { selected.insert(c.id) }
        }
        var objFace = [Bool](repeating: false, count: mesh.faces.count)
        var objVertex = [Bool](repeating: false, count: pts1.count)
        for id in selected { for fi in comps[id] { objFace[fi] = true } }
        for (i, f) in mesh.faces.enumerated() where objFace[i] {
            objVertex[Int(f.x)] = true; objVertex[Int(f.y)] = true; objVertex[Int(f.z)] = true
        }
        let objIdx = objVertex.indices.filter { objVertex[$0] }
        log.progress("post", 0.5, ["step": "object", "components": comps.count, "selected": selected.count])

        // --- 3. Grundkörper und Hauptachsen waagrecht -----------------------------------------------
        // Grundkörper = dichteste waagrechte Schicht (beim Rollwagen der Rahmen); seine Achsen und seine
        // Mitte bestimmen die Ausrichtung, Anbauten wie Räder verfälschen sie so nicht.
        let objPts = objIdx.map { pts1[$0] }
        let rawH0 = Geo.percentile(objPts.map { $0.z }, 0.999)
        let band = Self.densestBand(objPts.map { $0.z }, height: rawH0, floorCut: cutTol)
        let bandPts = objPts.filter { $0.z >= band.lo && $0.z <= band.hi }
        let rect = Geo.minAreaRect((bandPts.count > 50 ? bandPts : objPts).map { SIMD2($0.x, $0.y) })
        let rz = Self.rotationZ(-rect.angle)
        let m2 = rz * Self.translation(SIMD3(-rect.center.x, -rect.center.y, 0))
        pts1 = pts1.map { (m2 * SIMD4($0, 1)).xyz }
        let obj = objIdx.map { pts1[$0] }
        // robuste Ausdehnung (0,1 %/99,9 %) neben der harten Hülle. Waagrecht zählen nur Punkte über dem
        // Bodenrand (6 % der Höhe): dort hängen sonst Reste des Bodens als „Schürze“ am Objekt.
        let zs = obj.map { $0.z }
        let rawH = Geo.percentile(zs, 0.999)
        let fringe = max(cutTol * 3, rawH * 0.06)
        let upper = obj.filter { $0.z > fringe }
        let xs = (upper.count > 50 ? upper : obj).map { $0.x }, ys = (upper.count > 50 ? upper : obj).map { $0.y }
        let rawL = Geo.percentile(xs, 0.999) - Geo.percentile(xs, 0.001)
        let rawB = Geo.percentile(ys, 0.999) - Geo.percentile(ys, 0.001)
        let hullL = (xs.max() ?? 0) - (xs.min() ?? 0), hullB = (ys.max() ?? 0) - (ys.min() ?? 0), hullH = zs.max() ?? 0
        // Grundkörper: Ausdehnung der dichtesten Schicht (0,5–99,5 %), ohne Bodenrand
        let gb = obj.filter { $0.z >= max(band.lo, fringe) && $0.z <= band.hi }
        let gxs = gb.map { $0.x }, gys = gb.map { $0.y }
        let rawGL = gb.count > 50 ? Geo.percentile(gxs, 0.995) - Geo.percentile(gxs, 0.005) : rawL
        let rawGB = gb.count > 50 ? Geo.percentile(gys, 0.995) - Geo.percentile(gys, 0.005) : rawB

        // --- 4. Maßstab ----------------------------------------------------------------------------
        var scale = 1000.0
        var scaleKnown = false
        var scaleNote = "Kein bekanntes Maß angegeben: Einheit von Object Capture × 1000 (ohne LiDAR NICHT maßhaltig)"
        func rawMeasure(_ name: String) -> Double? {
            switch name {
            case "laenge", "länge", "l", "length": return rawL
            case "breite", "b", "width": return rawB
            case "hoehe", "höhe", "h", "height": return rawH
            case "grund_laenge", "grundlaenge", "rahmen_laenge": return rawGL
            case "grund_breite", "grundbreite", "rahmen_breite": return rawGB
            default: return nil
            }
        }
        if let k = options.known {
            if let r = rawMeasure(k.name), r > 0 {
                scale = k.mm / r
                scaleKnown = true
                scaleNote = "Maßstab aus \(k.name) = \(fmt(k.mm)) mm"
            } else {
                log.warn("Unbekanntes Maß \(k.name) – erlaubt: laenge, breite, hoehe, grund_laenge, grund_breite")
            }
        }
        let mScale = simd_double4x4(diagonal: SIMD4(scale, scale, scale, 1))
        let mAll = mScale * m2 * m1 * m0            // roh → mm, Z oben
        let L = rawL * scale, B = rawB * scale, H = rawH * scale
        let GL = rawGL * scale, GB = rawGB * scale
        let bandMM = (band.lo * scale, band.hi * scale)
        let objMM = obj.map { $0 * scale }

        // Ebenen oben/unten, Räder
        let topPlane = Self.horizontalPlaneHeight(objMM, zRange: (H * 0.75, H * 1.05), tol: max(H * 0.012, 0.5))
        let lowPlane = Self.horizontalPlaneHeight(objMM, zRange: (cutTol * scale, H * 0.3), tol: max(H * 0.012, 0.5))
        let wheels = Self.findWheels(objMM, length: L, width: B, height: H, band: bandMM)
        let upsideDown = wheels["gefunden"] as? Bool == true && wheels["seite"] as? String != "unten"

        var checks: [[String: Any]] = []
        for c in options.checks {
            let measured: Double?
            if ["rad", "raddurchmesser", "wheel"].contains(c.name) {
                measured = wheels["mean_diameter_mm"] as? Double
            } else {
                measured = rawMeasure(c.name).map { $0 * scale }
            }
            guard let m = measured else {
                log.warn("Prüfmaß \(c.name) nicht messbar")
                continue
            }
            checks.append(["name": c.name, "soll_mm": c.mm, "ist_mm": r1(m), "abweichung_mm": r1(m - c.mm),
                           "abweichung_prozent": r2((m - c.mm) / c.mm * 100)])
        }
        log.progress("post", 0.7, ["step": "measured"])

        // --- 5. Dateien ----------------------------------------------------------------------------
        var extra: [String] = []
        let mtlSrc = try fm.contentsOfDirectory(atPath: layout.rawOBJDir.path).first { $0.hasSuffix(".mtl") }
        let mtlName = "netz_mm.mtl"
        if let mtl = mtlSrc {
            // Material mit Texturen neben das mm-Netz legen (Texturnamen bleiben)
            let text = try String(contentsOf: layout.rawOBJDir.appendingPathComponent(mtl), encoding: .utf8)
            try text.write(to: layout.root.appendingPathComponent(mtlName), atomically: true, encoding: .utf8)
            for f in try fm.contentsOfDirectory(atPath: layout.rawOBJDir.path) where f.hasSuffix(".png") {
                try Files.copyReplacing(layout.rawOBJDir.appendingPathComponent(f), to: layout.root.appendingPathComponent(f))
                extra.append(f)
            }
        }
        try mesh.write(to: layout.meshMM, transform: mAll, keepFace: objFace, mtlName: mtlSrc == nil ? nil : mtlName)
        log.emit("file", ["kind": "mesh_mm", "path": layout.meshMM.path])

        if options.writeUSDZ {
            var diffuse: String? = nil
            if let mtl = mtlSrc, let text = try? String(contentsOf: layout.rawOBJDir.appendingPathComponent(mtl), encoding: .utf8) {
                diffuse = text.split(separator: "\n").first { $0.hasPrefix("map_Kd ") }
                    .map { String($0.dropFirst(7)).trimmingCharacters(in: .whitespaces) }
            }
            if Self.writeUSDZ(mesh: mesh, transform: mAll, keep: objFace, texture: diffuse, dir: layout.root, to: layout.usdzMM) {
                log.emit("file", ["kind": "usdz_mm", "path": layout.usdzMM.path])
            } else {
                log.warn("netz_mm.usdz nicht geschrieben (usdzip fehlt oder Fehler); netz_mm.obj ist vollständig")
            }
        }

        // Punktwolke im mm-System, nur im Objektbereich
        var cloudCount = 0
        if let (raw, cols) = try? PLYReader.read(layout.rawPLY) {
            let blo = SIMD3(-L / 2, -B / 2, 0) - SIMD3(repeating: 0.05 * L)
            let bhi = SIMD3(L / 2, B / 2, H) + SIMD3(repeating: 0.05 * L)
            var p: [SIMD3<Float>] = [], c: [SIMD4<UInt8>] = []
            for (i, q) in raw.enumerated() {
                let w = (mAll * SIMD4(SIMD3<Double>(q), 1)).xyz
                if w.x >= blo.x && w.y >= blo.y && w.z >= cutTol * scale && w.x <= bhi.x && w.y <= bhi.y && w.z <= bhi.z {
                    p.append(SIMD3<Float>(w))
                    if i < cols.count { c.append(cols[i]) }
                }
            }
            try PLYWriter.write(points: p, colors: c, to: layout.plyMM)
            cloudCount = p.count
            log.emit("file", ["kind": "point_cloud_mm", "path": layout.plyMM.path, "points": p.count])
        }

        // Kameras ausgerichtet in poses.json ergänzen
        try rewritePoses(cams: cams, aligned: mAll, scale: scaleKnown ? scale : nil)

        let reconTimes = (try? JSONSerialization.jsonObject(with: Data(contentsOf: layout.reconstructionJSON))) as? [String: Any]
        let images = (try? JSONSerialization.jsonObject(with: Data(contentsOf: layout.imagesJSON))) as? [String: Any]
        let camHeights = camPos1.map { $0.z * scale }
        var summary: [String: Any] = [
            "einheit": "mm",
            "massstab_bekannt": scaleKnown,
            "massstab_hinweis": scaleNote,
            "mm_je_roh_einheit": r2(scale),
            "huellmass_mm": ["laenge": r1(L), "breite": r1(B), "hoehe": r1(H)],
            "huellmass_hart_mm": ["laenge": r1(hullL * scale), "breite": r1(hullB * scale), "hoehe": r1(hullH * scale)],
            "grundkoerper_mm": ["laenge": r1(GL), "breite": r1(GB), "schicht_von": r1(bandMM.0), "schicht_bis": r1(bandMM.1)],
            "oberkante_mm": topPlane.map { r1($0) } ?? NSNull(),
            // aufrecht: höchster Punkt = H, obere Fläche = oberste waagrechte Ebene. Kopfüber zeigt die obere Fläche
            // zum Boden und ist von keiner Kamera zu sehen: dann nur die Gesamthöhe
            "oberkante_aufrecht_mm": r1(H),
            "obere_flaeche_aufrecht_mm": upsideDown ? NSNull() : (topPlane.map { r1($0) } ?? NSNull()),
            "lage": upsideDown ? "kopfüber (Anbauten wie Räder oben, Maße auf den aufrechten Stand umgerechnet)" : "aufrecht",
            "untere_ebene_mm": lowPlane.map { r1($0) } ?? NSNull(),
            "raeder": wheels,
            "pruefmasse": checks,
            "boden": ["gefunden": floorFound, "punkte_auf_boden": floorInliers, "toleranz_mm": r2(tol * scale),
                      "hinweis": floorFound ? "Bodenebene per RANSAC" : "kein Boden im Netz, Auflage auf den untersten Punkten",
                      "abgeschnitten": options.cutFloor, "schnitthoehe_mm": r2(cutTol * scale)],
            "objekt": ["netzteile": comps.count, "gewaehlt": selected.count,
                       "dreiecke": objFace.filter { $0 }.count, "dreiecke_gesamt": mesh.faces.count,
                       "punkte_wolke": cloudCount],
            "kameras": ["anzahl": cams.count,
                        "hoehe_mm_min": r1(camHeights.min() ?? 0), "hoehe_mm_max": r1(camHeights.max() ?? 0)],
            "transform_roh_zu_mm": PosesWriter.rows4(float4x4(mAll)),
            "nachbearbeitung_s": r2(Date().timeIntervalSince(t0)),
        ]
        if let rt = reconTimes { summary["rekonstruktion"] = rt }
        if let im = images {
            summary["bilder"] = ["anzahl": (im["frames"] as? [Any])?.count ?? 0, "lange_kante": im["long_edge"] ?? 0,
                                 "auswahl_s": im["seconds"] ?? 0, "video": im["video"] ?? ""]
        }
        if let dir = options.previewDir {
            let images = Self.renderPreviews(mesh: layout.meshMM, dir: dir, prefix: layout.root.lastPathComponent)
            if images.isEmpty {
                log.warn("Kontrollbilder nicht erzeugt (Blender oder Skript fehlt)")
            } else {
                summary["kontrollbilder"] = images
                for i in images { log.emit("file", ["kind": "preview", "path": i]) }
            }
        }
        try JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]).write(to: layout.reportJSON)
        try markdown(summary).write(to: layout.reportMD, atomically: true, encoding: .utf8)
        log.emit("file", ["kind": "report", "path": layout.reportJSON.path])
        log.info("Hüllmaß \(fmt(L)) × \(fmt(B)) × \(fmt(H)) mm" + (checks.isEmpty ? "" : ", Prüfmaße: " +
            checks.map { "\($0["name"]!) \($0["ist_mm"]!) statt \($0["soll_mm"]!) mm" }.joined(separator: ", ")))
        log.progress("post", 1, ["step": "done"])
        return PostReport(summary: summary, extraFiles: extra)
    }

    // MARK: Kameras

    func loadCameras() throws -> [CameraPose] {
        let src = FileManager.default.fileExists(atPath: layout.rawPoses.path) ? layout.rawPoses : layout.poses
        let obj = try JSONSerialization.jsonObject(with: Data(contentsOf: src)) as? [String: Any]
        guard let list = obj?["cameras"] as? [[String: Any]] else { throw CaptureError.message("poses.json ohne Kameras") }
        let shared = obj?["lens_distortion"] as? [String: Any]
        return list.compactMap { c in
            guard let raw = c["raw"] as? [String: Any], let rows = raw["camera_to_world"] as? [[Double]] else { return nil }
            var m = simd_float4x4()
            for r in 0..<4 { for k in 0..<4 { m[k][r] = Float(rows[r][k]) } }
            var p = CameraPose(sample: c["sample"] as? Int ?? 0, image: c["image"] as? String ?? "", cameraToWorld: m,
                               intrinsics: nil)
            if let kr = raw["K"] as? [[Double]] {
                var k = simd_float3x3()
                for r in 0..<3 { for j in 0..<3 { k[j][r] = Float(kr[r][j]) } }
                p.intrinsics = k
            }
            if let ld = (c["lens_distortion"] as? [String: Any]) ?? shared, let ce = ld["center"] as? [Double],
               let tab = ld["radial_lookup"] as? [Double] {
                p.distortionCenter = SIMD2(Float(ce[0]), Float(ce[1]))
                p.distortionTable = tab.map { Float($0) }
            }
            return p
        }
    }

    func rewritePoses(cams: [CameraPose], aligned: simd_double4x4, scale: Double?) throws {
        let old = (try JSONSerialization.jsonObject(with: Data(contentsOf: layout.poses)) as? [String: Any]) ?? [:]
        var meta: [String: Any] = [:]
        for k in ["source", "os", "images_dir", "detail", "object_masking", "sequential"] { meta[k] = old[k] }
        try PosesWriter.write(poses: cams, images: Files.imageInfos(layout: layout), imageDir: layout.images,
                              meta: meta, aligned: (aligned, scale), to: layout.poses)
        log.emit("file", ["kind": "poses", "path": layout.poses.path, "aligned": true])
    }

    // MARK: Messhilfen

    /// Höhe der stärksten waagrechten Ebene im Höhenbereich (Median der Inlier) oder nil.
    static func horizontalPlaneHeight(_ pts: [SIMD3<Double>], zRange: (Double, Double), tol: Double) -> Double? {
        let sel = pts.filter { $0.z >= zRange.0 && $0.z <= zRange.1 }
        guard sel.count > 50,
              let (pl, inl) = Geo.ransacPlane(sel, threshold: tol, iterations: 400, seed: 5,
                                              allowed: { abs($0.z) > cos(8 * Double.pi / 180) }),
              Double(inl.count) > 0.12 * Double(sel.count) else { return nil }
        _ = pl
        return Geo.percentile(inl.map { sel[$0].z }, 0.5)
    }

    /// Dichteste waagrechte Schicht (Dicke 12 % der Höhe) über dem Bodenschnitt, auf ±Ränder erweitert,
    /// solange die Punktdichte hoch bleibt.
    static func densestBand(_ zs: [Double], height H: Double, floorCut: Double) -> (lo: Double, hi: Double) {
        guard H > 0, zs.count > 20 else { return (0, H) }
        let bins = 50
        var hist = [Int](repeating: 0, count: bins)
        for z in zs where z >= 0 && z <= H { hist[min(bins - 1, Int(z / H * Double(bins)))] += 1 }
        let w = max(2, bins * 12 / 100)
        let first = min(bins - w, Int(ceil(floorCut * 2 / H * Double(bins))))
        var best = first, bestSum = -1
        for i in first...(bins - w) {
            let sum = hist[i..<(i + w)].reduce(0, +)
            if sum > bestSum { bestSum = sum; best = i }
        }
        var lo = best, hi = best + w - 1
        let peak = hist[lo...hi].max() ?? 0
        while lo > first && Double(hist[lo - 1]) > 0.5 * Double(peak) { lo -= 1 }
        while hi < bins - 1 && Double(hist[hi + 1]) > 0.5 * Double(peak) { hi += 1 }
        return (Double(lo) / Double(bins) * H, Double(hi + 1) / Double(bins) * H)
    }

    /// Räder: liegen auf der Seite des Grundkörpers mit der größeren Resthöhe (über dem Rahmen = kopfüber).
    /// Je Ecke Kreis in der senkrechten Radebene (Hauptachse der Eckpunkte), Ausgleich auf dem Umriss.
    static func findWheels(_ pts: [SIMD3<Double>], length L: Double, width B: Double, height H: Double,
                           band: (Double, Double)) -> [String: Any] {
        guard pts.count > 500, H > 0 else { return ["gefunden": false] }
        let above = H - band.1, below = band.0
        let wheelsDown = below > above
        let margin = H * 0.03
        let zone: (Double, Double) = wheelsDown ? (0, band.0 - margin) : (band.1 + margin, H * 1.01)
        var result: [String: Any] = ["seite": wheelsDown ? "unten" : "oben (Gegenstand liegt kopfüber)",
                                     "zone_mm": [r1(zone.0), r1(zone.1)]]
        guard zone.1 - zone.0 > H * 0.15 else {
            result["gefunden"] = false
            return result
        }
        var diameters: [Double] = []
        var each: [[String: Any]] = []
        for (sx, sy) in [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)] {
            let q = pts.filter { $0.x * sx > L * 0.12 && $0.y * sy > B * 0.08 && $0.z >= zone.0 && $0.z <= zone.1 }
            guard q.count > 60 else { continue }
            let (c, axes, _) = Geo.pca(q.map { SIMD3($0.x, $0.y, 0) })
            let u = axes[0]
            let p2 = q.map { SIMD2(simd_dot($0 - c, u), $0.z) }
            // Umriss: Punkte nahe der konvexen Hülle (die Lauffläche), ohne die Seitenflächen im Inneren
            let hull = Geo.convexHull(p2)
            let band2 = max(H * 0.02, 1.0)
            let rim = p2.filter { p in Self.distanceToPolygon(p, hull) < band2 }
            let endZ = wheelsDown ? zone.0 : (q.map { $0.z }.max() ?? zone.1)
            // nur die Hälfte am Radende: dort ist der Umriss ein Kreisbogen, am anderen Ende sitzt die Gabel
            let half = rim.filter { abs($0.y - endZ) < (zone.1 - zone.0) * 0.6 }
            guard let fit = Geo.fitCircle(half.count > 20 ? half : rim, threshold: max(H * 0.01, 0.6), iterations: 800)
            else { continue }
            let d = 2 * fit.radius
            let touches = wheelsDown ? abs(fit.center.y - fit.radius - endZ) < H * 0.06
                                     : abs(fit.center.y + fit.radius - endZ) < H * 0.06
            let ok = d < H * 1.05 && d > H * 0.15 && touches && fit.inliers >= 15
            each.append(["ecke": [sx, sy], "durchmesser_mm": r1(d), "mitte_hoehe_mm": r1(fit.center.y),
                         "umrisspunkte": half.count, "inlier": fit.inliers, "plausibel": ok])
            if ok { diameters.append(d) }
        }
        result["einzeln"] = each
        result["gefunden"] = !diameters.isEmpty
        if !diameters.isEmpty {
            let sorted = diameters.sorted()
            let mean = diameters.reduce(0, +) / Double(diameters.count)
            result["mean_diameter_mm"] = r1(mean)
            result["median_diameter_mm"] = r1(sorted[sorted.count / 2])
            result["streuung_mm"] = r1((sorted.last! - sorted.first!) / 2)
            result["anzahl"] = diameters.count
        }
        return result
    }

    static func distanceToPolygon(_ p: SIMD2<Double>, _ poly: [SIMD2<Double>]) -> Double {
        guard poly.count >= 2 else { return .infinity }
        var best = Double.infinity
        for i in poly.indices {
            let a = poly[i], b = poly[(i + 1) % poly.count]
            let ab = b - a
            let t = max(0, min(1, simd_dot(p - a, ab) / max(simd_length_squared(ab), 1e-18)))
            best = min(best, simd_length(p - (a + t * ab)))
        }
        return best
    }

    static func lookAtPoint(origins: [SIMD3<Double>], dirs: [SIMD3<Double>]) -> SIMD3<Double> {
        var a = simd_double3x3(0)
        var b = SIMD3<Double>(repeating: 0)
        for (o, d) in zip(origins, dirs) {
            let m = matrix_identity_double3x3 - simd_double3x3(columns: (d * d.x, d * d.y, d * d.z))
            a += m
            b += m * o
        }
        guard abs(a.determinant) > 1e-12 else { return origins.reduce(.zero, +) / Double(max(origins.count, 1)) }
        return a.inverse * b
    }

    /// Zusammenhängende Netzteile (über gemeinsame Ecken) der behaltenen Dreiecke.
    static func components(faces: [SIMD3<Int32>], keep: [Bool], vertexCount: Int) -> [[Int]] {
        var parent = Array(0..<vertexCount)
        func find(_ x: Int) -> Int {
            var x = x
            while parent[x] != x { parent[x] = parent[parent[x]]; x = parent[x] }
            return x
        }
        func unite(_ a: Int, _ b: Int) {
            let ra = find(a), rb = find(b)
            if ra != rb { parent[ra] = rb }
        }
        for (i, f) in faces.enumerated() where keep[i] {
            unite(Int(f.x), Int(f.y)); unite(Int(f.y), Int(f.z))
        }
        var groups: [Int: [Int]] = [:]
        for (i, f) in faces.enumerated() where keep[i] { groups[find(Int(f.x)), default: []].append(i) }
        return groups.values.sorted { $0.count > $1.count }
    }

    // MARK: Matrizen

    static func translation(_ t: SIMD3<Double>) -> simd_double4x4 {
        var m = matrix_identity_double4x4
        m.columns.3 = SIMD4(t, 1)
        return m
    }

    static func rotationZ(_ a: Double) -> simd_double4x4 {
        simd_double4x4(rows: [SIMD4(cos(a), -sin(a), 0, 0), SIMD4(sin(a), cos(a), 0, 0), SIMD4(0, 0, 1, 0), SIMD4(0, 0, 0, 1)])
    }

    /// Kleinste Drehung, die `a` auf `b` abbildet.
    static func rotation(from a: SIMD3<Double>, to b: SIMD3<Double>) -> simd_double4x4 {
        let q = simd_quatd(from: simd_normalize(a), to: simd_normalize(b))
        let r = simd_double3x3(q)
        return simd_double4x4(columns: (SIMD4(r.columns.0, 0), SIMD4(r.columns.1, 0), SIMD4(r.columns.2, 0), SIMD4(0, 0, 0, 1)))
    }

    /// USDZ im mm-System (metersPerUnit 0,001, Z oben) mit Farbtextur: eigenes USDA aus den behaltenen Dreiecken,
    /// mit `usdcat` nach USDC, mit `usdzip` gepackt. false, wenn ein Werkzeug fehlt oder etwas schiefgeht.
    static func writeUSDZ(mesh: OBJMesh, transform m: simd_double4x4, keep: [Bool], texture: String?, dir: URL,
                          to usdz: URL) -> Bool {
        let usdzip = "/usr/bin/usdzip", usdcat = "/usr/bin/usdcat"
        guard FileManager.default.isExecutableFile(atPath: usdzip) else { return false }
        var remap = [Int32](repeating: -1, count: mesh.positions.count)
        var points: [SIMD3<Double>] = []
        var idx: [Int32] = [], st: [SIMD2<Float>] = []
        let hasUV = texture != nil && mesh.faceUVs.count == mesh.faces.count && !mesh.uvs.isEmpty
        for (i, f) in mesh.faces.enumerated() where i < keep.count && keep[i] {
            for (k, v) in [f.x, f.y, f.z].enumerated() {
                if remap[Int(v)] < 0 {
                    remap[Int(v)] = Int32(points.count)
                    points.append((m * SIMD4(mesh.positions[Int(v)], 1)).xyz)
                }
                idx.append(remap[Int(v)])
                if hasUV {
                    let t = mesh.faceUVs[i][k]
                    st.append(t >= 0 && Int(t) < mesh.uvs.count ? mesh.uvs[Int(t)] : .zero)
                }
            }
        }
        guard !points.isEmpty else { return false }
        let lo = points.reduce(SIMD3(repeating: Double.infinity)) { simd_min($0, $1) }
        let hi = points.reduce(SIMD3(repeating: -Double.infinity)) { simd_max($0, $1) }
        var t = "#usda 1.0\n(\n    defaultPrim = \"Referenz\"\n    metersPerUnit = 0.001\n    upAxis = \"Z\"\n"
        t += "    doc = \"kevcad-capture: Referenznetz in mm, Z oben, Boden z = 0\"\n)\n\n"
        t += "def Xform \"Referenz\" (\n    kind = \"component\"\n)\n{\n"
        t += "    def Mesh \"Netz\" (\n        prepend apiSchemas = [\"MaterialBindingAPI\"]\n    )\n    {\n"
        t += String(format: "        float3[] extent = [(%.3f, %.3f, %.3f), (%.3f, %.3f, %.3f)]\n", lo.x, lo.y, lo.z, hi.x, hi.y, hi.z)
        t += "        int[] faceVertexCounts = [" + Array(repeating: "3", count: idx.count / 3).joined(separator: ", ") + "]\n"
        t += "        int[] faceVertexIndices = [" + idx.map { String($0) }.joined(separator: ", ") + "]\n"
        t += "        point3f[] points = [" + points.map { String(format: "(%.3f, %.3f, %.3f)", $0.x, $0.y, $0.z) }.joined(separator: ", ") + "]\n"
        if hasUV {
            t += "        texCoord2f[] primvars:st = [" + st.map { String(format: "(%.5f, %.5f)", $0.x, $0.y) }.joined(separator: ", ") + "] (\n            interpolation = \"faceVarying\"\n        )\n"
        }
        t += "        uniform token subdivisionScheme = \"none\"\n        rel material:binding = </Referenz/Material>\n    }\n\n"
        t += "    def Material \"Material\"\n    {\n        token outputs:surface.connect = </Referenz/Material/Oberflaeche.outputs:surface>\n\n"
        t += "        def Shader \"Oberflaeche\"\n        {\n            uniform token info:id = \"UsdPreviewSurface\"\n"
        if hasUV, let tex = texture {
            t += "            color3f inputs:diffuseColor.connect = </Referenz/Material/Farbe.outputs:rgb>\n"
            t += "            float inputs:roughness = 0.8\n            token outputs:surface\n        }\n\n"
            t += "        def Shader \"Koordinaten\"\n        {\n            uniform token info:id = \"UsdPrimvarReader_float2\"\n            string inputs:varname = \"st\"\n            float2 outputs:result\n        }\n\n"
            t += "        def Shader \"Farbe\"\n        {\n            uniform token info:id = \"UsdUVTexture\"\n            asset inputs:file = @\(tex)@\n"
            t += "            float2 inputs:st.connect = </Referenz/Material/Koordinaten.outputs:result>\n            float3 outputs:rgb\n        }\n"
        } else {
            t += "            color3f inputs:diffuseColor = (0.6, 0.62, 0.66)\n            float inputs:roughness = 0.8\n            token outputs:surface\n        }\n"
        }
        t += "    }\n}\n"
        let usda = dir.appendingPathComponent("netz_mm.usda")
        let usdc = dir.appendingPathComponent("netz_mm.usdc")
        defer {
            try? FileManager.default.removeItem(at: usda)
            try? FileManager.default.removeItem(at: usdc)
        }
        do {
            try t.write(to: usda, atomically: true, encoding: .utf8)
            var root = "netz_mm.usda"
            if FileManager.default.isExecutableFile(atPath: usdcat),
               run(usdcat, ["-o", usdc.path, usda.path], in: dir), FileManager.default.fileExists(atPath: usdc.path) {
                root = "netz_mm.usdc"
            }
            try? FileManager.default.removeItem(at: usdz)
            let ok = run(usdzip, [usdz.lastPathComponent, root] + (hasUV ? [texture!] : []), in: dir)
            return ok && FileManager.default.fileExists(atPath: usdz.path)
        } catch {
            return false
        }
    }

    static func run(_ exe: String, _ args: [String], in dir: URL) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.currentDirectoryURL = dir
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }

    // MARK: Kontrollbilder

    /// Rendert das mm-Netz mit Blender (Hintergrund, kein Fenster) aus vier Richtungen.
    static func renderPreviews(mesh: URL, dir: URL, prefix: String) -> [String] {
        let blender = ProcessInfo.processInfo.environment["KEVCAD_BLENDER"] ?? "/Applications/Blender.app/Contents/MacOS/Blender"
        guard FileManager.default.isExecutableFile(atPath: blender), let script = scriptURL("kontrollbilder.py") else { return [] }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        guard run(blender, ["-b", "--factory-startup", "--python", script.path, "--", mesh.path, dir.path, prefix], in: dir)
        else { return [] }
        return ["vorne", "seite", "oben", "schraeg"].map { dir.appendingPathComponent("\(prefix)_\($0).png").path }
            .filter { FileManager.default.fileExists(atPath: $0) }
    }

    /// Hilfsskripte: $KEVCAD_CAPTURE_SCRIPTS, neben dem Programm, oder in einem `scripts/` darüber (Quellbaum).
    static func scriptURL(_ name: String) -> URL? {
        var dirs: [URL] = []
        if let e = ProcessInfo.processInfo.environment["KEVCAD_CAPTURE_SCRIPTS"] { dirs.append(URL(fileURLWithPath: e)) }
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent()
        dirs.append(exe)
        var up = exe
        for _ in 0..<5 {
            dirs.append(up.appendingPathComponent("scripts"))
            up = up.deletingLastPathComponent()
        }
        for d in dirs {
            let u = d.appendingPathComponent(name)
            if FileManager.default.fileExists(atPath: u.path) { return u }
        }
        return nil
    }

    // MARK: Bericht

    func markdown(_ s: [String: Any]) -> String {
        var t = "# Referenz aus Video · Bericht\n\n"
        t += "Erzeugt von kevcad-capture am \(ISO8601DateFormatter().string(from: Date())).\n\n"
        if let b = s["bilder"] as? [String: Any] {
            t += "- **Video:** \(b["video"] ?? "")\n- **Bilder:** \(b["anzahl"] ?? 0), lange Kante \(b["lange_kante"] ?? 0) px, Auswahl \(fmtAny(b["auswahl_s"])) s\n"
        }
        if let r = s["rekonstruktion"] as? [String: Any] {
            let times = r["times"] as? [String: Any] ?? [:]
            t += "- **Object Capture:** Detail \(r["detail"] ?? "?"), \(r["posed"] ?? 0) von \(r["images"] ?? 0) Bildern ausgerichtet, \(fmtAny(times["reconstruction_s"])) s\n"
        }
        t += "- **Nachbearbeitung:** \(fmtAny(s["nachbearbeitung_s"])) s\n"
        t += "- **Maßstab:** \(s["massstab_hinweis"] ?? "")\n\n"
        t += "## Maße (mm, Z oben, Boden z = 0)\n\n| Größe | Wert |\n|---|---|\n"
        if let h = s["huellmass_mm"] as? [String: Any] {
            t += "| Hüllmaß L × B × H (robust, 0,1–99,9 %) | \(fmtAny(h["laenge"])) × \(fmtAny(h["breite"])) × \(fmtAny(h["hoehe"])) |\n"
        }
        if let h = s["huellmass_hart_mm"] as? [String: Any] {
            t += "| Hüllmaß hart (alle Punkte) | \(fmtAny(h["laenge"])) × \(fmtAny(h["breite"])) × \(fmtAny(h["hoehe"])) |\n"
        }
        t += "| Lage | \(s["lage"] ?? "–") |\n"
        t += "| Höchster Punkt im aufrechten Stand (Gesamthöhe) | \(fmtAny(s["oberkante_aufrecht_mm"])) |\n"
        t += "| Obere Fläche des Grundkörpers im aufrechten Stand | \(s["obere_flaeche_aufrecht_mm"] is NSNull ? "– (liegt kopfüber, Fläche zum Boden hin nicht sichtbar)" : fmtAny(s["obere_flaeche_aufrecht_mm"])) |\n"
        if let g = s["grundkoerper_mm"] as? [String: Any] {
            t += "| Grundkörper L × B (Schicht \(fmtAny(g["schicht_von"]))–\(fmtAny(g["schicht_bis"])) mm) | \(fmtAny(g["laenge"])) × \(fmtAny(g["breite"])) |\n"
        }
        t += "| Obere waagrechte Ebene über Boden | \(fmtAny(s["oberkante_mm"])) |\n"
        t += "| Untere waagrechte Ebene über Boden | \(fmtAny(s["untere_ebene_mm"])) |\n"
        if let w = s["raeder"] as? [String: Any] {
            t += "| Räder | \(w["gefunden"] as? Bool == true ? "Ø \(fmtAny(w["mean_diameter_mm"])) (± \(fmtAny(w["streuung_mm"]))), Seite \(w["seite"] ?? "")" : "nicht gefunden") |\n"
        }
        if let c = s["pruefmasse"] as? [[String: Any]], !c.isEmpty {
            t += "\n## Prüfmaße\n\n| Maß | Soll | Ist | Abweichung |\n|---|---|---|---|\n"
            for x in c {
                t += "| \(x["name"] ?? "") | \(fmtAny(x["soll_mm"])) | \(fmtAny(x["ist_mm"])) | \(fmtAny(x["abweichung_mm"])) mm (\(fmtAny(x["abweichung_prozent"])) %) |\n"
            }
        }
        if let b = s["boden"] as? [String: Any] {
            t += "\n## Boden\n\nGefunden: \(b["gefunden"] as? Bool == true ? "ja" : "nein"), Schnitthöhe \(fmtAny(b["schnitthoehe_mm"])) mm.\n"
        }
        t += "\n## Dateien\n\n- netz_mm.obj (+ netz_mm.mtl, Texturen), netz_mm.usdz, punktwolke_mm.ply\n- poses.json (Abschnitt `aligned` = dieses System)\n- roh/ (Object Capture ohne Maßstab)\n"
        if let k = s["kontrollbilder"] as? [String] {
            t += "\n## Kontrollbilder\n\n" + k.map { "- \($0)" }.joined(separator: "\n") + "\n"
        }
        return t
    }
}

func r1(_ x: Double) -> Double { (x * 10).rounded() / 10 }
func r2(_ x: Double) -> Double { (x * 100).rounded() / 100 }
func fmt(_ x: Double) -> String { String(format: "%.1f", x) }
func fmtAny(_ v: Any?) -> String {
    switch v {
    case let d as Double: return String(format: "%.1f", d)
    case let i as Int: return "\(i)"
    case let n as NSNumber: return String(format: "%.1f", n.doubleValue)
    case nil, is NSNull: return "–"
    default: return "\(v!)"
    }
}
