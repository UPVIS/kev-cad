import ARKit
import AVFoundation
import CoreImage
import Foundation
import ImageIO

enum RecorderError: LocalizedError {
    case writer(String)

    var errorDescription: String? {
        switch self {
        case .writer(let text): return "Video: \(text)"
        }
    }
}

/// Schreibt einen Scan nach SCAN.md: Video, Tiefe, Konfidenz und Lage mit etwa 10 Hz, dazu hochaufgelöste Fotos.
/// Alle Methoden laufen auf dem Hauptthread (ARSession-Delegate); Bilddateien entstehen auf einer eigenen Warteschlange.
final class ScanRecorder {
    let folder: URL
    let name: String
    let scanID = UUID().uuidString
    let created = Date()

    private let io = DispatchQueue(label: "de.upvis.kevscan.io", qos: .userInitiated)
    private let pending = DispatchGroup()
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var codec = "hevc"
    private var odometry: [String] = []
    private var intrinsics: simd_float3x3?
    private var intrinsicsResolution = CGSize.zero
    private var videoSize = CGSize.zero
    private var depthSize = CGSize(width: 256, height: 192)
    private var lastFrameTime: TimeInterval = 0
    private var photos: [PhotoEntry] = []
    private var previewWritten = false

    private(set) var frameCount = 0
    private(set) var startTimestamp: TimeInterval?
    private(set) var failure: String?

    var photoCount: Int { photos.count }
    var photoSize: (Int, Int)? { photos.first.map { ($0.breite, $0.hoehe) } }

    init(folder: URL, name: String) throws {
        self.folder = folder
        self.name = name
        let fm = FileManager.default
        for sub in ["depth", "confidence", "fotos"] {
            try fm.createDirectory(at: folder.appendingPathComponent(sub, isDirectory: true), withIntermediateDirectories: true)
        }
    }

    // MARK: Videobilder

    /// Nimmt ein ARFrame als Bild k auf (Video, Tiefe, Konfidenz, Lage). false, wenn es übersprungen wurde.
    @discardableResult
    func appendFrame(_ frame: ARFrame) -> Bool {
        guard failure == nil, let depth = frame.sceneDepth else { return false }
        let image = frame.capturedImage
        if writer == nil {
            do {
                try setupWriter(width: CVPixelBufferGetWidth(image), height: CVPixelBufferGetHeight(image))
            } catch {
                failure = error.localizedDescription
                return false
            }
            intrinsics = frame.camera.intrinsics
            intrinsicsResolution = frame.camera.imageResolution
        }
        // Bild 0 hat die Zeit 0,0, auch wenn ein früheres Anhängen gescheitert ist.
        if frameCount == 0 { startTimestamp = frame.timestamp }
        guard let writer, let input, let adaptor, let start = startTimestamp else { return false }
        guard writer.status == .writing else {
            failure = writer.error?.localizedDescription ?? "Der Videoschreiber hat angehalten."
            return false
        }
        guard input.isReadyForMoreMediaData else { return false }
        let t = frame.timestamp - start
        guard adaptor.append(image, withPresentationTime: CMTime(seconds: t, preferredTimescale: 600_000)) else {
            return false
        }

        let index = frameCount
        frameCount += 1
        lastFrameTime = t
        let depthPlane = PixelPacking.depthMillimeters(depth.depthMap)
        let confidencePlane = depth.confidenceMap.map { PixelPacking.bytes8($0) }
        depthSize = CGSize(width: depthPlane.width, height: depthPlane.height)
        odometry.append(Self.odometryRow(time: t, index: index, transform: frame.camera.transform))

        let depthURL = folder.appendingPathComponent(String(format: "depth/%06d.png", index))
        let confidenceURL = folder.appendingPathComponent(String(format: "confidence/%06d.png", index))
        pending.enter()
        io.async { [pending] in
            ImageCoding.writePNG(depthPlane, to: depthURL)
            if let confidencePlane { ImageCoding.writePNG(confidencePlane, to: confidenceURL) }
            pending.leave()
        }

        if !previewWritten && t >= 0.5 {
            previewWritten = true
            let preview = CIImage(cvPixelBuffer: image)
            let previewURL = folder.appendingPathComponent("vorschau.jpg")
            pending.enter()
            io.async { [pending] in
                ImageCoding.writePreview(preview, to: previewURL)
                pending.leave()
            }
        }
        return true
    }

    private func setupWriter(width: Int, height: Int) throws {
        let url = folder.appendingPathComponent("rgb.mp4")
        try? FileManager.default.removeItem(at: url)
        let assetWriter = try AVAssetWriter(outputURL: url, fileType: .mp4)
        var settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.hevc,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: 16_000_000,
                AVVideoMaxKeyFrameIntervalKey: 10,
            ],
        ]
        codec = "hevc"
        if !assetWriter.canApply(outputSettings: settings, forMediaType: .video) {
            settings[AVVideoCodecKey] = AVVideoCodecType.h264
            codec = "h264"
        }
        let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        videoInput.expectsMediaDataInRealTime = true
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
        ]
        let pixelAdaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: videoInput, sourcePixelBufferAttributes: attributes)
        guard assetWriter.canAdd(videoInput) else { throw RecorderError.writer("Eingang wird nicht angenommen.") }
        assetWriter.add(videoInput)
        guard assetWriter.startWriting() else {
            throw RecorderError.writer(assetWriter.error?.localizedDescription ?? "Start gescheitert.")
        }
        assetWriter.startSession(atSourceTime: .zero)
        writer = assetWriter
        input = videoInput
        adaptor = pixelAdaptor
        videoSize = CGSize(width: width, height: height)
    }

    static func odometryRow(time: Double, index: Int, transform m: simd_float4x4) -> String {
        let q = Pose.quaternion(m)
        return String(format: "%.6f, %d, %.6f, %.6f, %.6f, %.6f, %.6f, %.6f, %.6f",
                      time, index,
                      Double(m.columns.3.x), Double(m.columns.3.y), Double(m.columns.3.z),
                      Double(q.imag.x), Double(q.imag.y), Double(q.imag.z), Double(q.real))
    }

    // MARK: Fotos

    /// Legt ein hochaufgelöstes Foto ab. `latest` ist das letzte Videobild, falls das Foto selbst keine Tiefe hat.
    func addPhoto(_ frame: ARFrame, latest: ARFrame?, trigger: String) {
        let index = photos.count
        let base = String(format: "%03d", index)
        let buffer = frame.capturedImage
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)

        // Kameramatrix auf die tatsächliche Bildgröße beziehen.
        let resolution = frame.camera.imageResolution
        let sx = resolution.width > 0 ? Double(width) / Double(resolution.width) : 1
        let sy = resolution.height > 0 ? Double(height) / Double(resolution.height) : 1
        let K = frame.camera.intrinsics
        let k: [[Double]] = [
            [r6(Double(K.columns.0.x) * sx), 0, r6(Double(K.columns.2.x) * sx)],
            [0, r6(Double(K.columns.1.y) * sy), r6(Double(K.columns.2.y) * sy)],
            [0, 0, 1],
        ]

        var depthSource: String?
        var depthData: ARDepthData?
        if let own = frame.sceneDepth {
            depthData = own
            depthSource = "foto"
        } else if let other = latest?.sceneDepth {
            depthData = other
            depthSource = "videobild"
        }
        let depthPlane = depthData.map { PixelPacking.depthMillimeters($0.depthMap) }
        let confidencePlane = depthData?.confidenceMap.map { PixelPacking.bytes8($0) }

        let start = startTimestamp ?? frame.timestamp
        let exposure = Self.exposure(of: frame)
        let entry = PhotoEntry(datei: "\(base).jpg",
                               zeit: r6(frame.timestamp - start),
                               breite: width,
                               hoehe: height,
                               k: k,
                               lage: Pose(frame.camera.transform),
                               tiefe: depthPlane == nil ? nil : "\(base)_depth.png",
                               konfidenz: confidencePlane == nil ? nil : "\(base)_confidence.png",
                               belichtung_s: exposure.duration.map { r6($0) },
                               iso: exposure.iso,
                               tracking: Self.trackingName(frame.camera.trackingState),
                               tiefe_quelle: depthSource,
                               ausloeser: trigger)
        photos.append(entry)

        let fotos = folder.appendingPathComponent("fotos", isDirectory: true)
        let image = CIImage(cvPixelBuffer: buffer)
        pending.enter()
        io.async { [pending] in
            try? ImageCoding.writeJPEG(image, to: fotos.appendingPathComponent("\(base).jpg"), quality: 0.95)
            if let depthPlane { ImageCoding.writePNG(depthPlane, to: fotos.appendingPathComponent("\(base)_depth.png")) }
            if let confidencePlane {
                ImageCoding.writePNG(confidencePlane, to: fotos.appendingPathComponent("\(base)_confidence.png"))
            }
            pending.leave()
        }
    }

    static func exposure(of frame: ARFrame) -> (duration: Double?, iso: Double?) {
        var duration: Double? = frame.camera.exposureDuration > 0 ? frame.camera.exposureDuration : nil
        var iso: Double?
        let exif = frame.exifData
        let dict = (exif[kCGImagePropertyExifDictionary as String] as? [String: Any]) ?? exif
        if let value = dict[kCGImagePropertyExifExposureTime as String] as? NSNumber {
            duration = value.doubleValue
        }
        if let values = dict[kCGImagePropertyExifISOSpeedRatings as String] as? [NSNumber], let first = values.first {
            iso = first.doubleValue
        } else if let value = dict[kCGImagePropertyExifISOSpeedRatings as String] as? NSNumber {
            iso = value.doubleValue
        }
        return (duration, iso)
    }

    static func trackingName(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .normal: return "normal"
        case .notAvailable: return "nicht_verfuegbar"
        case .limited(let reason):
            switch reason {
            case .initializing: return "eingeschraenkt_start"
            case .excessiveMotion: return "eingeschraenkt_bewegung"
            case .insufficientFeatures: return "eingeschraenkt_merkmale"
            case .relocalizing: return "eingeschraenkt_neuortung"
            @unknown default: return "eingeschraenkt"
            }
        }
    }

    // MARK: Abschluss

    struct FinishInfo {
        var objekt: ObjectFile?
        var videoFormat: ARConfiguration.VideoFormat?
        var autoPhoto: ScanMeta.AutoPhoto
        var notiz: String
    }

    /// Schließt das Video ab und schreibt odometry.csv, camera_matrix.csv, fotos.json, objekt.json und zuletzt meta.json.
    func finish(_ info: FinishInfo, completion: @escaping (Error?) -> Void) {
        let meta = makeMeta(info)
        let odometryText = "timestamp, frame, x, y, z, qx, qy, qz, qw\n" + odometry.map { $0 + "\n" }.joined()
        let matrixText = cameraMatrixText()
        let photosFile = PhotosFile(fotos: photos)
        let folder = self.folder

        pending.enter()
        if let writer, let input, writer.status == .writing {
            input.markAsFinished()
            writer.finishWriting { [pending] in pending.leave() }
        } else {
            writer?.cancelWriting()
            pending.leave()
        }

        pending.notify(queue: io) {
            do {
                try odometryText.write(to: folder.appendingPathComponent("odometry.csv"), atomically: true, encoding: .utf8)
                if let matrixText {
                    try matrixText.write(to: folder.appendingPathComponent("camera_matrix.csv"), atomically: true, encoding: .utf8)
                }
                try JSONFiles.write(photosFile, to: folder.appendingPathComponent("fotos.json"))
                if let objekt = info.objekt {
                    try JSONFiles.write(objekt, to: folder.appendingPathComponent("objekt.json"))
                }
                try JSONFiles.write(meta, to: folder.appendingPathComponent("meta.json"))
                DispatchQueue.main.async { completion(nil) }
            } catch {
                DispatchQueue.main.async { completion(error) }
            }
        }
    }

    /// Bricht ab und löscht den Ordner.
    func cancel() {
        if let writer, writer.status == .writing {
            input?.markAsFinished()
            writer.cancelWriting()
        }
        let folder = self.folder
        pending.notify(queue: io) {
            try? FileManager.default.removeItem(at: folder)
        }
    }

    private func cameraMatrixText() -> String? {
        guard let K = intrinsics else { return nil }
        let sx = intrinsicsResolution.width > 0 ? Double(videoSize.width) / Double(intrinsicsResolution.width) : 1
        let sy = intrinsicsResolution.height > 0 ? Double(videoSize.height) / Double(intrinsicsResolution.height) : 1
        let fx = Double(K.columns.0.x) * sx, fy = Double(K.columns.1.y) * sy
        let cx = Double(K.columns.2.x) * sx, cy = Double(K.columns.2.y) * sy
        return String(format: "%.6f,%.6f,%.6f\n%.6f,%.6f,%.6f\n%.6f,%.6f,%.6f\n", fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0)
    }

    private func makeMeta(_ info: FinishInfo) -> ScanMeta {
        let photoDims = photoSize ?? (0, 0)
        var formatInfo: ScanMeta.VideoFormat?
        if let f = info.videoFormat {
            formatInfo = ScanMeta.VideoFormat(breite: Int(f.imageResolution.width),
                                              hoehe: Int(f.imageResolution.height),
                                              fps: f.framesPerSecond,
                                              kamera: f.captureDeviceType.rawValue,
                                              hochaufloesend_empfohlen: f.isRecommendedForHighResolutionFrameCapturing,
                                              hdr: f.isVideoHDRSupported)
        }
        return ScanMeta(format: "kevscan",
                        version: 1,
                        id: scanID,
                        name: name,
                        erstellt: JSONFiles.isoFormatter.string(from: created),
                        geraet: DeviceInfo.model,
                        ios: DeviceInfo.systemVersion,
                        app: DeviceInfo.appVersion,
                        hz: 10,
                        video: .init(breite: Int(videoSize.width), hoehe: Int(videoSize.height), bilder: frameCount, codec: codec),
                        tiefe: .init(breite: Int(depthSize.width), hoehe: Int(depthSize.height), einheit: "mm", quelle: "sceneDepth"),
                        fotos: .init(anzahl: photos.count, breite: photoDims.0, hoehe: photoDims.1),
                        notiz: info.notiz,
                        objekt: info.objekt != nil,
                        dauer_s: r6(lastFrameTime),
                        zeit_bezug: "erstes_videobild",
                        videoformat: formatInfo,
                        auto_foto: info.autoPhoto)
    }
}
