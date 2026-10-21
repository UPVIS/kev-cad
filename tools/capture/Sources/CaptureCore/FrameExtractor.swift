import AVFoundation
import CoreImage
import CoreVideo
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Ein ausgewähltes Einzelbild aus dem Video.
public struct SelectedFrame: Codable {
    public var file: String         // Dateiname im Bildordner
    public var frameIndex: Int      // laufende Nummer im Video (ab 0)
    public var time: Double         // Sekunden ab Videobeginn
    public var sharpness: Double    // Laplace-Varianz des Gewinners
    public var windowMedian: Double // Median der Schärfe im Fenster (zur Einordnung)
    public var width: Int
    public var height: Int
}

public struct ExtractionResult: Codable {
    public var video: String
    public var frameCount: Int
    public var duration: Double
    public var fps: Double
    public var decodeWidth: Int
    public var decodeHeight: Int
    public var orientation: Int     // EXIF-Orientierung, die auf die Bilder angewendet wurde
    public var start: Double = 0    // verwendeter Abschnitt (Sekunden)
    public var end: Double = 0
    public var longEdge: Int
    public var frames: [SelectedFrame]
    public var seconds: Double
}

public struct ExtractionOptions: Sendable {
    public var count = 60
    /// Lange Kante der gespeicherten Bilder in Pixeln; 0 = Originalgröße
    public var longEdge = 1920
    public var jpegQuality = 0.92
    /// Optional: 35-mm-äquivalente Brennweite für die EXIF-Daten (nur wenn bekannt)
    public var focal35mm: Double? = nil
    /// Nur diesen Abschnitt des Videos verwenden (Sekunden); nil = bis zum Ende
    public var start: Double = 0
    public var end: Double? = nil
    public init() {}
}

/// Liest das Video einmal von vorn bis hinten (Hardware-Decoder, direkt auf Zielgröße skaliert),
/// bewertet jedes Bild mit der Laplace-Varianz und speichert je Zeitfenster das schärfste als JPEG.
public final class FrameExtractor: @unchecked Sendable {
    let log = ProgressLog.shared
    let ciContext = CIContext(options: [.cacheIntermediates: false])
    let writeQueue = DispatchQueue(label: "kevcad.capture.write", qos: .userInitiated)
    let writeGroup = DispatchGroup()

    public init() {}

    public func extract(video: URL, to dir: URL, options: ExtractionOptions) async throws -> ExtractionResult {
        let t0 = Date()
        let asset = AVURLAsset(url: video)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw CaptureError.message("Keine Videospur in \(video.lastPathComponent)")
        }
        let fullDuration = try await asset.load(.duration).seconds
        let start = max(0, min(options.start, fullDuration))
        let stop = min(options.end ?? fullDuration, fullDuration)
        guard stop > start else { throw CaptureError.message("Leerer Zeitabschnitt \(start)–\(stop) s") }
        let duration = stop - start
        let natural = try await track.load(.naturalSize)
        let transform = try await track.load(.preferredTransform)
        let fps = Double(try await track.load(.nominalFrameRate))
        let orientation = Self.orientation(for: transform)

        let nw = Int(natural.width.rounded()), nh = Int(natural.height.rounded())
        var dw = nw, dh = nh
        if options.longEdge > 0 && options.longEdge < max(nw, nh) {
            let s = Double(options.longEdge) / Double(max(nw, nh))
            dw = Int((Double(nw) * s / 2).rounded()) * 2
            dh = Int((Double(nh) * s / 2).rounded()) * 2
        }
        let estFrames = max(1, Int((duration * fps).rounded()))
        log.info("Video \(nw)×\(nh), \(String(format: "%.1f", fullDuration)) s (Abschnitt \(String(format: "%.1f–%.1f", start, stop)) s), \(fps) fps, ~\(estFrames) Bilder; dekodiere auf \(dw)×\(dh)")
        log.emit("video", ["width": nw, "height": nh, "duration": fullDuration, "start": start, "end": stop, "fps": fps, "frames": estFrames,
                           "decode_width": dw, "decode_height": dh, "orientation": Int(orientation.rawValue)])

        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let reader = try AVAssetReader(asset: asset)
        if start > 0 || stop < fullDuration {
            reader.timeRange = CMTimeRange(start: CMTime(seconds: start, preferredTimescale: 600),
                                           end: CMTime(seconds: stop, preferredTimescale: 600))
        }
        let (frames, decoded, outW, outH) = try decodeAndSelect(
            reader: reader, track: track, natural: (nw, nh), decode: (dw, dh), start: start, duration: duration,
            estFrames: estFrames, orientation: orientation, dir: dir, options: options)

        let result = ExtractionResult(
            video: video.path, frameCount: decoded, duration: duration, fps: fps,
            decodeWidth: dw, decodeHeight: dh, orientation: Int(orientation.rawValue),
            start: start, end: stop, longEdge: max(outW, outH), frames: frames, seconds: Date().timeIntervalSince(t0))
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        enc.keyEncodingStrategy = .convertToSnakeCase
        try enc.encode(result).write(to: dir.deletingLastPathComponent().appendingPathComponent("bilder.json"))
        return result
    }

    /// Ein Durchlauf durch das Video (synchron): Schärfe je Bild, je Fenster das schärfste als JPEG.
    func decodeAndSelect(reader: AVAssetReader, track: AVAssetTrack, natural: (Int, Int), decode: (Int, Int),
                         start: Double, duration: Double, estFrames: Int, orientation: CGImagePropertyOrientation, dir: URL,
                         options: ExtractionOptions) throws -> ([SelectedFrame], Int, Int, Int) {
        let (nw, nh) = natural
        let (dw, dh) = decode
        var settings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any],
        ]
        if dw != nw || dh != nh {
            settings[kCVPixelBufferWidthKey as String] = dw
            settings[kCVPixelBufferHeightKey as String] = dh
        }
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        output.alwaysCopiesSampleData = false
        reader.add(output)
        guard reader.startReading() else {
            throw CaptureError.message("Video lässt sich nicht lesen: \(reader.error?.localizedDescription ?? "?")")
        }

        let selector = WindowSelector(count: options.count, duration: duration)
        var scratch: [Float] = []
        var currentWindow = -1
        var bestBuffer: CVPixelBuffer? = nil
        var bestScore = -1.0, bestTime = 0.0, bestIndex = 0
        var windowScores: [Double] = []
        let box = FrameBox()
        var frameIndex = 0

        func flush() {
            guard let buf = bestBuffer else { return }
            let sorted = windowScores.sorted()
            let median = sorted.isEmpty ? 0 : sorted[sorted.count / 2]
            let slot = box.append(SelectedFrame(file: "", frameIndex: bestIndex, time: bestTime, sharpness: bestScore,
                                                windowMedian: median, width: 0, height: 0))
            let name = String(format: "bild_%04d.jpg", slot + 1)
            box.setName(slot, name)
            let url = dir.appendingPathComponent(name)
            let job = WriteJob(buffer: buf, url: url)
            writeGroup.enter()
            writeQueue.async { [self] in
                defer { writeGroup.leave() }
                do {
                    let (w, h) = try writeJPEG(job.buffer, orientation: orientation, to: job.url, options: options)
                    box.setSize(slot, w, h)
                } catch {
                    log.warn("Bild \(name) nicht geschrieben: \(error.localizedDescription)")
                }
            }
            bestBuffer = nil
            bestScore = -1
            windowScores.removeAll(keepingCapacity: true)
        }

        while let sample = output.copyNextSampleBuffer() {
            guard let pb = CMSampleBufferGetImageBuffer(sample) else { continue }
            let t = CMSampleBufferGetPresentationTimeStamp(sample).seconds
            if t < start - 1e-6 || t > start + duration + 1e-6 { continue }
            let w = selector.window(at: t - start)
            if w != currentWindow {
                flush()
                currentWindow = w
            }
            CVPixelBufferLockBaseAddress(pb, .readOnly)
            let score = Sharpness.laplacianVariance(
                base: CVPixelBufferGetBaseAddressOfPlane(pb, 0)!,
                width: CVPixelBufferGetWidthOfPlane(pb, 0), height: CVPixelBufferGetHeightOfPlane(pb, 0),
                rowBytes: CVPixelBufferGetBytesPerRowOfPlane(pb, 0), scratch: &scratch)
            CVPixelBufferUnlockBaseAddress(pb, .readOnly)
            windowScores.append(score)
            if score > bestScore {
                bestScore = score
                bestTime = t
                bestIndex = frameIndex
                bestBuffer = try Self.copy(pb)
            }
            frameIndex += 1
            log.progress("frames", Double(frameIndex) / Double(estFrames),
                         ["frame": frameIndex, "selected": box.count])
        }
        flush()
        if reader.status == .failed {
            throw CaptureError.message("Fehler beim Dekodieren: \(reader.error?.localizedDescription ?? "?")")
        }
        writeGroup.wait()
        log.progress("frames", 1, ["frame": frameIndex, "selected": box.count])
        let frames = box.frames
        let ow = frames.first?.width ?? dw, oh = frames.first?.height ?? dh
        return (frames, frameIndex, ow, oh)
    }

    /// JPEG mit angewandter Drehung (Hochformat bleibt Hochformat), sRGB.
    func writeJPEG(_ pb: CVPixelBuffer, orientation: CGImagePropertyOrientation, to url: URL,
                   options: ExtractionOptions) throws -> (Int, Int) {
        let image = CIImage(cvPixelBuffer: pb).oriented(orientation)
        let rect = image.extent.integral
        guard let cg = ciContext.createCGImage(image, from: rect, format: .RGBA8,
                                               colorSpace: CGColorSpace(name: CGColorSpace.sRGB)) else {
            throw CaptureError.message("Bild konnte nicht gerendert werden")
        }
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil)
        else { throw CaptureError.message("JPEG-Ziel nicht anlegbar: \(url.path)") }
        var props: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: options.jpegQuality,
            kCGImagePropertyOrientation: 1,
        ]
        if let f = options.focal35mm {
            props[kCGImagePropertyExifDictionary] = [kCGImagePropertyExifFocalLenIn35mmFilm: Int(f.rounded())]
        }
        CGImageDestinationAddImage(dest, cg, props as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { throw CaptureError.message("JPEG nicht geschrieben") }
        return (cg.width, cg.height)
    }

    /// Tiefe Kopie eines (bi-planaren) Pixelpuffers, damit der Decoder-Pool frei bleibt.
    static func copy(_ src: CVPixelBuffer) throws -> CVPixelBuffer {
        var dst: CVPixelBuffer?
        let attrs: [String: Any] = [kCVPixelBufferIOSurfacePropertiesKey as String: [:] as [String: Any]]
        let st = CVPixelBufferCreate(nil, CVPixelBufferGetWidth(src), CVPixelBufferGetHeight(src),
                                     CVPixelBufferGetPixelFormatType(src), attrs as CFDictionary, &dst)
        guard st == kCVReturnSuccess, let d = dst else { throw CaptureError.message("Pixelpuffer: \(st)") }
        CVBufferPropagateAttachments(src, d)
        CVPixelBufferLockBaseAddress(src, .readOnly)
        CVPixelBufferLockBaseAddress(d, [])
        defer {
            CVPixelBufferUnlockBaseAddress(d, [])
            CVPixelBufferUnlockBaseAddress(src, .readOnly)
        }
        for p in 0..<CVPixelBufferGetPlaneCount(src) {
            let h = CVPixelBufferGetHeightOfPlane(src, p)
            let sb = CVPixelBufferGetBytesPerRowOfPlane(src, p)
            let db = CVPixelBufferGetBytesPerRowOfPlane(d, p)
            let s = CVPixelBufferGetBaseAddressOfPlane(src, p)!
            let t = CVPixelBufferGetBaseAddressOfPlane(d, p)!
            if sb == db {
                memcpy(t, s, sb * h)
            } else {
                for y in 0..<h { memcpy(t + y * db, s + y * sb, min(sb, db)) }
            }
        }
        return d
    }

    /// EXIF-Orientierung aus der Spur-Transformation (Hochformat-Videos vom iPhone: 6 = .right).
    static func orientation(for t: CGAffineTransform) -> CGImagePropertyOrientation {
        let a = t.a.rounded(), b = t.b.rounded(), c = t.c.rounded(), d = t.d.rounded()
        switch (a, b, c, d) {
        case (0, 1, -1, 0): return .right
        case (-1, 0, 0, -1): return .down
        case (0, -1, 1, 0): return .left
        default: return .up
        }
    }
}

/// Gemeinsame Liste der Gewinner (Dekodier-Schleife und Schreib-Warteschlange).
final class FrameBox: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [SelectedFrame] = []
    var count: Int { lock.withLock { items.count } }
    var frames: [SelectedFrame] { lock.withLock { items } }
    func append(_ f: SelectedFrame) -> Int { lock.withLock { items.append(f); return items.count - 1 } }
    func setName(_ i: Int, _ n: String) { lock.withLock { items[i].file = n } }
    func setSize(_ i: Int, _ w: Int, _ h: Int) { lock.withLock { items[i].width = w; items[i].height = h } }
}

struct WriteJob: @unchecked Sendable {
    let buffer: CVPixelBuffer
    let url: URL
}

public enum CaptureError: LocalizedError {
    case message(String)
    public var errorDescription: String? {
        switch self { case .message(let m): return m }
    }
}
