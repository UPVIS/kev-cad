import Accelerate
import Foundation

/// Schärfemaß: Varianz des Laplace-Operators (3×3) über ein Graubild. Große Werte = scharf,
/// Bewegungsunschärfe senkt den Wert stark. Vergleichbar nur zwischen Bildern derselben Größe und Szene.
public enum Sharpness {
    /// - Parameters:
    ///   - base: Zeiger auf das erste Byte der Graustufenebene (Planar8, z. B. Y-Ebene von 420f)
    ///   - rowBytes: Bytes je Zeile (kann größer als `width` sein)
    ///   - scratch: wiederverwendbarer Zwischenspeicher (wird bei Bedarf vergrößert)
    public static func laplacianVariance(
        base: UnsafeRawPointer, width: Int, height: Int, rowBytes: Int, scratch: inout [Float]
    ) -> Double {
        let n = width * height
        if scratch.count < 2 * n { scratch = [Float](repeating: 0, count: 2 * n) }
        var result = 0.0
        scratch.withUnsafeMutableBufferPointer { buf in
            let f = buf.baseAddress!
            let l = f + n
            var src = vImage_Buffer(
                data: UnsafeMutableRawPointer(mutating: base), height: vImagePixelCount(height),
                width: vImagePixelCount(width), rowBytes: rowBytes)
            var flt = vImage_Buffer(
                data: f, height: vImagePixelCount(height), width: vImagePixelCount(width),
                rowBytes: width * MemoryLayout<Float>.size)
            var lap = vImage_Buffer(
                data: l, height: vImagePixelCount(height), width: vImagePixelCount(width),
                rowBytes: width * MemoryLayout<Float>.size)
            vImageConvert_Planar8toPlanarF(&src, &flt, 1.0, 0.0, vImage_Flags(kvImageNoFlags))
            let kernel: [Float] = [0, 1, 0, 1, -4, 1, 0, 1, 0]
            vImageConvolve_PlanarF(&flt, &lap, nil, 0, 0, kernel, 3, 3, 0, vImage_Flags(kvImageEdgeExtend))
            var mean: Float = 0
            var sd: Float = 0
            vDSP_normalize(l, 1, nil, 1, &mean, &sd, vDSP_Length(n))
            // Werte 0…255 → Varianz in Grauwert² (wie OpenCV cv2.Laplacian(...).var())
            result = Double(sd) * Double(sd) * 255.0 * 255.0
        }
        return result
    }

    /// Bequeme Variante für Tests: Graubild als Bytefeld.
    public static func laplacianVariance(gray: [UInt8], width: Int, height: Int) -> Double {
        var scratch: [Float] = []
        return gray.withUnsafeBytes { raw in
            laplacianVariance(
                base: raw.baseAddress!, width: width, height: height, rowBytes: width, scratch: &scratch)
        }
    }
}

/// Zeitlich gleichmäßige Vorauswahl: das Video wird in `count` gleich lange Fenster geteilt,
/// je Fenster gewinnt das schärfste Bild.
public struct WindowSelector {
    public let count: Int
    public let duration: Double

    public init(count: Int, duration: Double) {
        self.count = max(1, count)
        self.duration = max(duration, 1e-6)
    }

    /// Fensternummer eines Bildes zur Zeit `t` (Sekunden ab Videobeginn).
    public func window(at t: Double) -> Int {
        min(count - 1, max(0, Int((t / duration) * Double(count))))
    }

    /// Auswahl ohne Streaming (für Tests und Bildordner): Indizes der Gewinner, zeitlich sortiert.
    public func select(times: [Double], scores: [Double]) -> [Int] {
        var best: [Int: Int] = [:]
        for i in times.indices {
            let w = window(at: times[i])
            if let b = best[w] {
                if scores[i] > scores[b] { best[w] = i }
            } else {
                best[w] = i
            }
        }
        return best.keys.sorted().map { best[$0]! }
    }
}
