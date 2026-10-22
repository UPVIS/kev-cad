import ARKit
import AVFoundation
import Foundation

/// Hält fest, was ARKit auf diesem Gerät anbietet: `Library/Application Support/geraet.json`.
/// Abholen am Mac mit `tools/kevscan.sh geraet` (devicectl), ohne das iPhone zu bedienen.
enum DeviceProbe {
    private static let queue = DispatchQueue(label: "de.upvis.kevscan.probe", qos: .utility)

    static var fileURL: URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("geraet.json")
    }

    static func write() {
        queue.async {
            var dict = load()
            dict["geraet"] = DeviceInfo.model
            dict["ios"] = DeviceInfo.systemVersion
            dict["app"] = DeviceInfo.appVersion
            dict["stand"] = JSONFiles.isoFormatter.string(from: Date())
            dict["lidar"] = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
            dict["netz"] = ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
            dict["formate"] = ARWorldTrackingConfiguration.supportedVideoFormats.map(describe)
            if let recommended = ARWorldTrackingConfiguration.recommendedVideoFormatForHighResolutionFrameCapturing {
                dict["empfohlen_hochaufloesend"] = describe(recommended)
            }
            if let chosen = CaptureController.bestVideoFormat() {
                dict["gewaehlt"] = describe(chosen)
                dict["avfoundation_foto_max"] = photoDimensions(for: chosen)
            }
            save(dict)
        }
    }

    /// Nach dem ersten echten Foto: die tatsächliche Größe von `captureHighResolutionFrame`.
    static func noteHighResolution(width: Int, height: Int, hasDepth: Bool) {
        queue.async {
            var dict = load()
            dict["hochaufloesend_gemessen"] = ["breite": width, "hoehe": height, "tiefe_im_foto": hasDepth] as [String: Any]
            save(dict)
        }
    }

    private static func describe(_ f: ARConfiguration.VideoFormat) -> [String: Any] {
        [
            "breite": Int(f.imageResolution.width),
            "hoehe": Int(f.imageResolution.height),
            "fps": f.framesPerSecond,
            "kamera": f.captureDeviceType.rawValue,
            "hinten": f.captureDevicePosition == .back,
            "hochaufloesend_empfohlen": f.isRecommendedForHighResolutionFrameCapturing,
            "hdr": f.isVideoHDRSupported,
        ]
    }

    /// Größte Fotogrößen der AVFoundation-Formate mit derselben Videoauflösung (Hinweis auf die Größe der Fotos).
    private static func photoDimensions(for format: ARConfiguration.VideoFormat) -> [String] {
        guard let device = AVCaptureDevice.default(format.captureDeviceType, for: .video, position: .back) else { return [] }
        var result = Set<String>()
        for candidate in device.formats {
            let dims = CMVideoFormatDescriptionGetDimensions(candidate.formatDescription)
            guard Int(dims.width) == Int(format.imageResolution.width), Int(dims.height) == Int(format.imageResolution.height) else {
                continue
            }
            for photo in candidate.supportedMaxPhotoDimensions {
                result.insert("\(photo.width)x\(photo.height)")
            }
        }
        return result.sorted()
    }

    private static func load() -> [String: Any] {
        guard let data = try? Data(contentsOf: fileURL),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return dict
    }

    private static func save(_ dict: [String: Any]) {
        try? FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }
}
