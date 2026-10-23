import Foundation
import simd

// Dateien eines Scans nach SCAN.md (Version 1). Feldnamen sind Teil des Vertrags und deshalb deutsch.

/// Rundet auf sechs Nachkommastellen, damit die JSON-Dateien lesbar bleiben.
func r6(_ value: Double) -> Double { (value * 1_000_000).rounded() / 1_000_000 }
func r6(_ value: Float) -> Double { r6(Double(value)) }

/// Lage Kamera -> Welt als Translation (Meter) und Quaternion (x, y, z, w) mit w >= 0.
struct Pose: Codable, Equatable {
    var t: [Double]
    var q: [Double]

    init(_ m: simd_float4x4) {
        let rotation = Pose.quaternion(m)
        t = [r6(m.columns.3.x), r6(m.columns.3.y), r6(m.columns.3.z)]
        q = [r6(rotation.imag.x), r6(rotation.imag.y), r6(rotation.imag.z), r6(rotation.real)]
    }

    static func quaternion(_ m: simd_float4x4) -> simd_quatf {
        var rotation = simd_normalize(simd_quatf(m))
        if rotation.real < 0 {
            rotation = simd_quatf(ix: -rotation.imag.x, iy: -rotation.imag.y, iz: -rotation.imag.z, r: -rotation.real)
        }
        return rotation
    }
}

struct ScanMeta: Codable {
    struct Video: Codable {
        var breite: Int
        var hoehe: Int
        var bilder: Int
        var codec: String
    }

    struct Depth: Codable {
        var breite: Int
        var hoehe: Int
        var einheit: String
        var quelle: String
    }

    struct Photos: Codable {
        var anzahl: Int
        var breite: Int
        var hoehe: Int
    }

    /// Zusatz zu Version 1: das Videoformat der ARKit-Sitzung.
    struct VideoFormat: Codable {
        var breite: Int
        var hoehe: Int
        var fps: Int
        var kamera: String
        var hochaufloesend_empfohlen: Bool
        var hdr: Bool
    }

    /// Zusatz zu Version 1: Einstellungen der automatischen Fotos.
    struct AutoPhoto: Codable {
        var aktiv: Bool
        var winkel_grad: Double
        var abstand_m: Double
    }

    var format: String
    var version: Int
    var id: String
    var name: String
    var erstellt: String
    var geraet: String
    var ios: String
    var app: String
    var hz: Int
    var video: Video
    var tiefe: Depth
    var fotos: Photos
    var notiz: String
    var objekt: Bool
    var dauer_s: Double
    var zeit_bezug: String
    var videoformat: VideoFormat?
    var auto_foto: AutoPhoto
    /// Zusatz zu Version 1: Hinweise beim Speichern (verworfene Fotos, nicht geschriebene Dateien); fehlt ohne Hinweise.
    var warnungen: [String]?
}

/// Nur zum Lesen in der Liste: alles optional, damit auch fremde oder unvollständige Scans erscheinen.
struct ScanMetaLite: Decodable {
    struct Video: Decodable { var bilder: Int? }
    struct Photos: Decodable { var anzahl: Int? }
    var id: String?
    var name: String?
    var erstellt: String?
    var video: Video?
    var fotos: Photos?
    var objekt: Bool?
    var dauer_s: Double?
}

struct PhotoEntry: Codable {
    var datei: String
    var zeit: Double
    var breite: Int
    var hoehe: Int
    var k: [[Double]]
    var lage: Pose
    var tiefe: String?
    var konfidenz: String?
    var belichtung_s: Double?
    var iso: Double?
    var tracking: String
    /// Zusatz: "foto" (Tiefe gehört zum Foto selbst) oder "videobild" (Tiefe des letzten Videobilds).
    var tiefe_quelle: String?
    /// Zusatz: "hand" oder "auto".
    var ausloeser: String
}

struct PhotosFile: Codable {
    var fotos: [PhotoEntry]
}

struct ObjectFile: Codable {
    struct Box: Codable {
        var mitte: [Double]
        var groesse: [Double]
        var drehung_y_grad: Double
    }

    struct Floor: Codable {
        var punkt: [Double]
        var normale: [Double]
    }

    var box: Box
    var boden: Floor

    init(_ b: ObjectBox) {
        let c = b.center
        box = Box(mitte: [r6(c.x), r6(c.y), r6(c.z)],
                  groesse: [r6(b.size.x), r6(b.size.y), r6(b.size.z)],
                  drehung_y_grad: r6(Double(b.yaw) * 180 / .pi))
        let n = simd_normalize(b.floorNormal)
        boden = Floor(punkt: [r6(b.floorPoint.x), r6(b.floorPoint.y), r6(b.floorPoint.z)],
                      normale: [r6(n.x), r6(n.y), r6(n.z)])
    }
}

/// Box um das Objekt in Weltkoordinaten (Meter). Die Grundfläche liegt auf dem Boden.
struct ObjectBox: Equatable {
    /// Mitte der Grundfläche.
    var floorPoint: SIMD3<Float>
    var floorNormal: SIMD3<Float>
    /// Breite (lokales x), Höhe (y), Tiefe (lokales z).
    var size: SIMD3<Float>
    /// Drehung um +y im Bogenmaß (rechtshändig, von oben gesehen gegen den Uhrzeigersinn).
    var yaw: Float

    var center: SIMD3<Float> { floorPoint + SIMD3<Float>(0, size.y / 2, 0) }
}

enum JSONFiles {
    static func write<T: Encodable>(_ value: T, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(value).write(to: url, options: .atomic)
    }

    static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = .current
        return f
    }()
}
