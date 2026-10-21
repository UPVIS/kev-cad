import Foundation
import ImageIO
import simd

/// Ablauf eines Laufs und Ordnerstruktur:
///
///     <aus>/bilder/bild_0001.jpg …   ausgewählte Einzelbilder
///     <aus>/bilder.json              Auswahl (Bildnummer, Zeit, Schärfe)
///     <aus>/poses.json               Kameras je Bild (roh und ausgerichtet)
///     <aus>/roh/obj/ roh/modell.usdz roh/punktwolke.ply   Ausgabe von Object Capture (ohne Maßstab)
///     <aus>/netz_mm.obj (+ .mtl, Textur), netz_mm.usdz, punktwolke_mm.ply   ausgerichtet, mm, Z oben
///     <aus>/bericht.json, bericht.md
public struct Layout {
    public let root: URL
    public init(_ root: URL) { self.root = root }
    public var images: URL { root.appendingPathComponent("bilder", isDirectory: true) }
    public var imagesJSON: URL { root.appendingPathComponent("bilder.json") }
    public var poses: URL { root.appendingPathComponent("poses.json") }
    public var raw: URL { root.appendingPathComponent("roh", isDirectory: true) }
    public var rawOBJDir: URL { raw.appendingPathComponent("obj", isDirectory: true) }
    public var rawUSDZ: URL { raw.appendingPathComponent("modell.usdz") }
    public var rawPLY: URL { raw.appendingPathComponent("punktwolke.ply") }
    public var checkpoint: URL { root.appendingPathComponent("checkpoint", isDirectory: true) }
    public var reconstructionJSON: URL { raw.appendingPathComponent("rekonstruktion.json") }
    /// Posen wie von Object Capture geliefert; wird nur von der Rekonstruktion geschrieben (Quelle der Nachbearbeitung)
    public var rawPoses: URL { raw.appendingPathComponent("posen_roh.json") }
    public var meshMM: URL { root.appendingPathComponent("netz_mm.obj") }
    public var usdzMM: URL { root.appendingPathComponent("netz_mm.usdz") }
    public var plyMM: URL { root.appendingPathComponent("punktwolke_mm.ply") }
    public var reportJSON: URL { root.appendingPathComponent("bericht.json") }
    public var reportMD: URL { root.appendingPathComponent("bericht.md") }
}

public enum Files {
    /// Kopiert eine Datei oder einen Ordner und ersetzt ein vorhandenes Ziel.
    public static func copyReplacing(_ src: URL, to dst: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fm.fileExists(atPath: dst.path) { try fm.removeItem(at: dst) }
        try fm.copyItem(at: src, to: dst)
    }

    public static func directorySize(_ url: URL) -> Int64 {
        guard let e = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey]) else { return 0 }
        var total: Int64 = 0
        for case let f as URL in e {
            total += Int64((try? f.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return total
    }

    /// Bildinfos aus bilder.json, sonst aus den Dateien selbst.
    public static func imageInfos(layout: Layout) -> [String: ImageInfo] {
        var out: [String: ImageInfo] = [:]
        if let data = try? Data(contentsOf: layout.imagesJSON),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let frames = obj["frames"] as? [[String: Any]] {
            for f in frames {
                guard let name = f["file"] as? String else { continue }
                out[name] = ImageInfo(width: f["width"] as? Int ?? 0, height: f["height"] as? Int ?? 0,
                                      time: f["time"] as? Double, frameIndex: f["frame_index"] as? Int,
                                      sharpness: f["sharpness"] as? Double)
            }
        }
        if let files = try? FileManager.default.contentsOfDirectory(at: layout.images, includingPropertiesForKeys: nil) {
            for f in files where out[f.lastPathComponent] == nil || out[f.lastPathComponent]!.width == 0 {
                guard let src = CGImageSourceCreateWithURL(f as CFURL, nil),
                      let p = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
                      let w = p[kCGImagePropertyPixelWidth] as? Int, let h = p[kCGImagePropertyPixelHeight] as? Int
                else { continue }
                var info = out[f.lastPathComponent] ?? ImageInfo(width: w, height: h)
                info.width = w
                info.height = h
                out[f.lastPathComponent] = info
            }
        }
        return out
    }
}
