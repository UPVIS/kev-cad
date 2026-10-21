import Foundation
import simd

/// Binäre PLY-Punktwolke (x, y, z als float, Farbe als uchar).
public enum PLYWriter {
    public static func write(points: [SIMD3<Float>], colors: [SIMD4<UInt8>], to url: URL) throws {
        var header = "ply\nformat binary_little_endian 1.0\ncomment kevcad-capture\n"
        header += "element vertex \(points.count)\nproperty float x\nproperty float y\nproperty float z\n"
        let hasColor = colors.count == points.count
        if hasColor { header += "property uchar red\nproperty uchar green\nproperty uchar blue\n" }
        header += "end_header\n"
        var data = Data(header.utf8)
        data.reserveCapacity(data.count + points.count * (hasColor ? 15 : 12))
        for i in points.indices {
            var p = points[i]
            withUnsafeBytes(of: &p.x) { data.append(contentsOf: $0) }
            withUnsafeBytes(of: &p.y) { data.append(contentsOf: $0) }
            withUnsafeBytes(of: &p.z) { data.append(contentsOf: $0) }
            if hasColor {
                let c = colors[i]
                data.append(contentsOf: [c.x, c.y, c.z])
            }
        }
        try data.write(to: url)
    }
}

/// Bildinformationen für poses.json (aus bilder.json oder dem Bildordner).
public struct ImageInfo {
    public var width: Int
    public var height: Int
    public var time: Double?
    public var frameIndex: Int?
    public var sharpness: Double?
}

/// poses.json: Kameras je Bild in zwei Formen (Object-Capture-Welt und OpenCV-Konvention),
/// nach der Nachbearbeitung zusätzlich im ausgerichteten mm-System (Z oben, Boden z = 0).
public enum PosesWriter {
    /// RealityKit-Kamera (X rechts, Y oben, Blick −Z) → OpenCV-Kamera (X rechts, Y unten, Blick +Z)
    static let flip = simd_float3x3(diagonal: SIMD3<Float>(1, -1, -1))

    public static func cameraJSON(_ c2w: simd_float4x4, intrinsics: simd_float3x3?, info: ImageInfo?) -> [String: Any] {
        let r = simd_float3x3(columns: (c2w.columns.0.xyz, c2w.columns.1.xyz, c2w.columns.2.xyz))
        let pos = c2w.columns.3.xyz
        // Welt → Kamera (OpenCV): R_cv = F · Rᵀ, t_cv = −R_cv · C
        let rcv = flip * r.transpose
        let tcv = -(rcv * pos)
        var d: [String: Any] = [
            "camera_to_world": rows4(c2w),
            "position": arr(pos),
            "view_dir": arr(-c2w.columns.2.xyz),
            "up": arr(c2w.columns.1.xyz),
            "opencv": ["R": rows3(rcv), "t": arr(tcv)],
        ]
        if let k = intrinsics {
            d["K"] = rows3(k) // simd ist spaltenweise (Spalte 2 = cx, cy, 1); Ausgabe zeilenweise
            let fx = g(k.columns.0.x), fy = g(k.columns.1.y)
            d["fx"] = fx
            d["fy"] = fy
            d["cx"] = g(k.columns.2.x)
            d["cy"] = g(k.columns.2.y)
            if let i = info {
                let w = Double(i.width), h = Double(i.height)
                let diag: Double = (w * w + h * h).squareRoot()
                let f35: Double = (fx + fy) / 2 * 43.2666 / diag
                let hfov: Double = 2 * atan(w / 2 / fx) * 180 / Double.pi
                d["focal_35mm"] = (f35 * 10).rounded() / 10
                d["hfov_deg"] = (hfov * 100).rounded() / 100
            }
        }
        return d
    }

    public static func write(poses: [CameraPose], images: [String: ImageInfo], imageDir: URL,
                             meta: [String: Any], aligned: (matrix: simd_double4x4, scaleMM: Double?)?,
                             to url: URL) throws {
        var cams: [[String: Any]] = []
        for p in poses {
            let info = images[p.image]
            var c: [String: Any] = ["image": p.image, "path": imageDir.appendingPathComponent(p.image).path,
                                    "sample": p.sample]
            if let i = info {
                c["width"] = i.width
                c["height"] = i.height
                if let t = i.time { c["time_s"] = (t * 1000).rounded() / 1000 }
                if let f = i.frameIndex { c["video_frame"] = f }
            }
            c["raw"] = cameraJSON(p.cameraToWorld, intrinsics: p.intrinsics, info: info)
            if let (m, _) = aligned {
                let mf = float4x4(m)
                // Ausrichtung = Drehung · Maßstab; die Kamera behält ihre Achsen (Spalten normieren)
                var c2w = mf * p.cameraToWorld
                for k in 0..<3 {
                    let v = simd_normalize(c2w[k].xyz)
                    c2w[k] = SIMD4<Float>(v, 0)
                }
                c["aligned"] = cameraJSON(c2w, intrinsics: p.intrinsics, info: info)
            }
            if let dc = p.distortionCenter, let tab = p.distortionTable {
                c["lens_distortion"] = ["center": [g(dc.x), g(dc.y)], "radial_lookup": tab.map { g($0) }]
            }
            cams.append(c)
        }
        // Verzeichnung ist bei Videobildern für alle Kameras gleich: dann nur einmal oben ablegen
        var sharedDistortion: Any? = nil
        let tables = poses.compactMap { $0.distortionTable }
        if tables.count == poses.count, let first = tables.first, tables.allSatisfy({ $0 == first }),
           Set(poses.compactMap { $0.distortionCenter.map { "\($0)" } }).count == 1 {
            sharedDistortion = cams.first?["lens_distortion"]
            for i in cams.indices { cams[i]["lens_distortion"] = nil }
        }
        var root: [String: Any] = meta
        root["format"] = "kevcad-capture/poses"
        root["version"] = 1
        root["count"] = cams.count
        root["cameras"] = cams
        if let d = sharedDistortion { root["lens_distortion"] = d }
        root["conventions"] = [
            "raw": "Weltsystem von Object Capture (Y oben, Einheit beliebig, ohne Maßstab)",
            "aligned": "Kev-CAD-System nach der Nachbearbeitung: mm, Z oben, Boden z = 0, Objektmitte x = y = 0",
            "camera_to_world": "4×4 zeilenweise; Spalten 0–2 = Kameraachsen X rechts, Y oben, Z nach hinten (RealityKit, Blick entlang −Z), Spalte 3 = Kameraposition",
            "opencv": "R, t: Welt → Kamera in OpenCV-Konvention (X rechts, Y unten, Z Blickrichtung); Pixel u, v = K · (R·X + t), Ursprung links oben",
            "K": "Kameramatrix in Pixeln der gespeicherten Bilder (width × height), zeilenweise",
            "lens_distortion": "Apple-Format wie AVCameraCalibrationData.lensDistortionLookupTable: Mitte in Pixeln, Tabelle = relative Vergrößerung über dem Radius (0 … Abstand zur entferntesten Bildecke); bei allen Kameras gleich, dann nur einmal oben",
            "scene": "Posen beziehen sich auf die starre Szene, die Object Capture rekonstruiert hat. Wurde der Gegenstand während der Aufnahme bewegt oder umgedreht, passen Bilder vor der Bewegung nicht zum Netz",
            "check": "Geprüft am Rollwagen-Video: Netz mit K und opencv-R/t in die Bilder projiziert, deckt sich mit dem Gegenstand",
        ]
        if let (m, s) = aligned {
            root["aligned_from_raw"] = rows4(float4x4(m))
            if let s { root["scale_mm_per_raw_unit"] = s }
        }
        let data = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try data.write(to: url, options: .atomic)
    }

    static func arr(_ v: SIMD3<Float>) -> [Double] { [g(v.x), g(v.y), g(v.z)] }
    static func rows3(_ m: simd_float3x3) -> [[Double]] {
        (0..<3).map { r in (0..<3).map { c in g(m[c][r]) } }
    }
    static func rows4(_ m: simd_float4x4) -> [[Double]] {
        (0..<4).map { r in (0..<4).map { c in g(m[c][r]) } }
    }
    /// Float → Double mit 7 gültigen Stellen (statt Binärrest wie 0.06934981793165207)
    static func g(_ x: Float) -> Double { Double(String(format: "%.7g", Double(x))) ?? Double(x) }
}

extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
}

/// simd_double4x4 → simd_float4x4
func float4x4(_ m: simd_double4x4) -> simd_float4x4 {
    simd_float4x4(columns: (SIMD4<Float>(m.columns.0), SIMD4<Float>(m.columns.1),
                            SIMD4<Float>(m.columns.2), SIMD4<Float>(m.columns.3)))
}
