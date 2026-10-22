import CoreImage
import CoreVideo
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Einkanaliges Bild (Tiefe in Millimetern als 16 bit oder Konfidenz als 8 bit), Zeilen ohne Auffüllung.
struct GrayPlane {
    let data: Data
    let width: Int
    let height: Int
    let bits: Int
}

enum PixelPacking {
    /// `ARDepthData.depthMap` (Float32, Meter) -> UInt16 Millimeter, 0 = keine Messung.
    static func depthMillimeters(_ buffer: CVPixelBuffer) -> GrayPlane {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        var out = Data(count: width * height * 2)
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            out.withUnsafeMutableBytes { raw in
                let dst = raw.bindMemory(to: UInt16.self)
                for y in 0..<height {
                    let row = base.advanced(by: y * rowBytes).assumingMemoryBound(to: Float32.self)
                    for x in 0..<width {
                        let meters = row[x]
                        var mm: UInt16 = 0
                        if meters.isFinite && meters > 0 {
                            mm = UInt16(min(Float(65535), (meters * 1000).rounded()))
                        }
                        dst[y * width + x] = mm.littleEndian
                    }
                }
            }
        }
        return GrayPlane(data: out, width: width, height: height, bits: 16)
    }

    /// `ARDepthData.confidenceMap` (UInt8, Werte 0, 1, 2) ohne Zeilenauffüllung.
    static func bytes8(_ buffer: CVPixelBuffer) -> GrayPlane {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        var out = Data(count: width * height)
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            out.withUnsafeMutableBytes { raw in
                guard let dst = raw.baseAddress else { return }
                for y in 0..<height {
                    memcpy(dst.advanced(by: y * width), base.advanced(by: y * rowBytes), width)
                }
            }
        }
        return GrayPlane(data: out, width: width, height: height, bits: 8)
    }

    /// Median der Tiefe (Meter) in einem kleinen Fenster in der Bildmitte, nil ohne gültige Messung.
    static func centerDepth(_ buffer: CVPixelBuffer, radius: Int = 4) -> Float? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        var values: [Float] = []
        values.reserveCapacity((2 * radius + 1) * (2 * radius + 1))
        let cx = width / 2, cy = height / 2
        for y in max(0, cy - radius)...min(height - 1, cy + radius) {
            let row = base.advanced(by: y * rowBytes).assumingMemoryBound(to: Float32.self)
            for x in max(0, cx - radius)...min(width - 1, cx + radius) {
                let v = row[x]
                if v.isFinite && v > 0 { values.append(v) }
            }
        }
        guard !values.isEmpty else { return nil }
        values.sort()
        return values[values.count / 2]
    }
}

enum ImageCoding {
    static let context = CIContext(options: [.cacheIntermediates: false])
    static let sRGB = CGColorSpace(name: CGColorSpace.sRGB)!

    /// PNG in Graustufen, 16 oder 8 bit, Werte unverändert (keine Farbanpassung).
    @discardableResult
    static func writePNG(_ plane: GrayPlane, to url: URL) -> Bool {
        guard let provider = CGDataProvider(data: plane.data as CFData) else { return false }
        var info = CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue)
        if plane.bits == 16 { info.insert(.byteOrder16Little) }
        guard let image = CGImage(width: plane.width, height: plane.height,
                                  bitsPerComponent: plane.bits, bitsPerPixel: plane.bits,
                                  bytesPerRow: plane.width * plane.bits / 8,
                                  space: CGColorSpaceCreateDeviceGray(), bitmapInfo: info,
                                  provider: provider, decode: nil, shouldInterpolate: false,
                                  intent: .defaultIntent) else { return false }
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            return false
        }
        CGImageDestinationAddImage(destination, image, nil)
        return CGImageDestinationFinalize(destination)
    }

    /// JPEG im Querformat des Sensors, ohne Drehung (die Kameramatrix gilt für genau dieses Bild).
    static func writeJPEG(_ image: CIImage, to url: URL, quality: Double) throws {
        let key = CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String)
        try context.writeJPEGRepresentation(of: image, to: url, colorSpace: sRGB, options: [key: quality])
    }

    /// Vorschaubild für Listen: aufrecht (Hochformat), längste Seite `maxSide`.
    static func writePreview(_ image: CIImage, to url: URL, maxSide: CGFloat = 512) {
        let upright = image.oriented(.right)
        let scale = maxSide / max(upright.extent.width, upright.extent.height)
        let scaled = upright.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let moved = scaled.transformed(by: CGAffineTransform(translationX: -scaled.extent.origin.x, y: -scaled.extent.origin.y))
        try? writeJPEG(moved, to: url, quality: 0.8)
    }
}
