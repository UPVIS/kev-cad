import Foundation
import RealityKit
import simd

public struct ReconstructionOptions {
    public var detail: PhotogrammetrySession.Request.Detail = .reduced
    public var objectMasking = true
    public var highSensitivity = false
    public var sequential = true
    public var writeOBJ = true
    /// Zusätzlich die USDZ von Object Capture (ohne Maßstab). Kostet bei medium ~17 s, bei reduced ~5 s;
    /// die Nachbearbeitung schreibt netz_mm.usdz ohnehin selbst aus dem OBJ.
    public var writeUSDZ = false
    /// Posen in einer eigenen ersten Anfrage: kommen etwa nach der Hälfte der Zeit, der Lauf dauert dafür
    /// rund 40 % länger (Messung Rollwagen, 60 Bilder: Posen 27 s statt 49 s, gesamt 75 s statt 55 s).
    public var posesFirst = false
    public init() {}

    public static func detail(named s: String) -> PhotogrammetrySession.Request.Detail? {
        switch s.lowercased() {
        case "preview", "vorschau": return .preview
        case "reduced", "reduziert": return .reduced
        case "medium", "mittel": return .medium
        case "full", "voll": return .full
        case "raw", "roh": return .raw
        default: return nil
        }
    }

    public static func name(of d: PhotogrammetrySession.Request.Detail) -> String {
        switch d {
        case .preview: return "preview"
        case .reduced: return "reduced"
        case .medium: return "medium"
        case .full: return "full"
        case .raw: return "raw"
        case .custom: return "custom"
        @unknown default: return "unknown"
        }
    }
}

/// Kamerapose eines Eingabebildes, wie Object Capture sie liefert (Weltsystem von Object Capture).
public struct CameraPose {
    public var sample: Int
    public var image: String
    public var cameraToWorld: simd_float4x4
    public var intrinsics: simd_float3x3?
    public var distortionCenter: SIMD2<Float>?
    public var distortionTable: [Float]?
}

public struct ReconstructionResult {
    public var poses: [CameraPose] = []
    public var points: [SIMD3<Float>] = []
    public var colors: [SIMD4<UInt8>] = []
    public var objDir: URL?
    public var usdz: URL?
    public var stageSeconds: [String: Double] = [:]
    public var posesAt: Double?
    public var seconds: Double = 0
    public var skipped: [Int] = []
    public var invalid: [Int: String] = [:]
}

/// Führt die PhotogrammetrySession auf einem Bildordner aus und meldet den Fortschritt als JSON-Zeilen.
/// `onPoses` wird aufgerufen, sobald die Posen fertig sind (lange vor dem Netz).
public final class Reconstructor {
    let log = ProgressLog.shared
    public init() {}

    public func run(images: URL, rawDir: URL, checkpoint: URL?, options: ReconstructionOptions,
                    onPoses: (ReconstructionResult) throws -> Void,
                    onPointCloud: (ReconstructionResult) throws -> Void) async throws -> ReconstructionResult {
        guard PhotogrammetrySession.isSupported else {
            throw CaptureError.message("Object Capture wird auf diesem Mac nicht unterstützt")
        }
        let t0 = Date()
        var config = PhotogrammetrySession.Configuration()
        config.sampleOrdering = options.sequential ? .sequential : .unordered
        config.featureSensitivity = options.highSensitivity ? .high : .normal
        config.isObjectMaskingEnabled = options.objectMasking
        if let cp = checkpoint {
            try FileManager.default.createDirectory(at: cp, withIntermediateDirectories: true)
            config.checkpointDirectory = cp
        }
        try FileManager.default.createDirectory(at: rawDir, withIntermediateDirectories: true)

        let session = try PhotogrammetrySession(input: images, configuration: config)
        // Posen zuerst allein anfordern: sie sind nach der Bildausrichtung fertig, das Netz erst viel später.
        // Die übrigen Anfragen folgen, sobald die Posen da sind (gleiche Sitzung, Ausrichtung wird wiederverwendet).
        var requests: [PhotogrammetrySession.Request] = [.pointCloud]
        let objDir = rawDir.appendingPathComponent("obj", isDirectory: true)
        let usdz = rawDir.appendingPathComponent("modell.usdz")
        if options.writeOBJ {
            try FileManager.default.createDirectory(at: objDir, withIntermediateDirectories: true)
            requests.append(.modelFile(url: objDir, detail: options.detail))
        }
        if options.writeUSDZ {
            requests.append(.modelFile(url: usdz, detail: options.detail))
        }
        let limits = PhotogrammetrySession.limits
        log.info("Object Capture: \(ReconstructionOptions.name(of: options.detail)), Maske \(options.objectMasking ? "an" : "aus"), Grenzen \(limits.maximumNumberOfInputImages) Bilder / \(limits.maximumInputImageDimension) px")
        log.emit("reconstruction_start", [
            "detail": ReconstructionOptions.name(of: options.detail), "object_masking": options.objectMasking,
            "sequential": options.sequential, "high_sensitivity": options.highSensitivity,
            "max_images": limits.maximumNumberOfInputImages, "max_dimension": limits.maximumInputImageDimension,
        ])

        var result = ReconstructionResult()
        var currentStage: String? = nil
        var stageStart = Date()
        var failure: Error? = nil
        var pending = Set((requests + [.poses]).map { requestName($0) })
        var followUp: [PhotogrammetrySession.Request]? = options.posesFirst ? requests : nil
        let modelName = requests.first(where: { if case .modelFile = $0 { return true } else { return false } })
            .map { requestName($0) } ?? "poses"
        var primary = options.posesFirst ? "poses" : modelName
        func sendFollowUp() throws {
            guard let r = followUp else { return }
            followUp = nil
            primary = modelName
            try session.process(requests: r)
        }

        try session.process(requests: options.posesFirst ? [.poses] : [.poses] + requests)
        outer: for try await output in session.outputs {
            switch output {
            case .inputComplete:
                log.emit("input_complete")
            case .requestProgress(let req, let fraction):
                // nur die Leitanfrage (erstes Netz, sonst Posen) melden, damit der Balken nicht springt
                if requestName(req) == primary {
                    log.progress("reconstruction", fraction, ["request": requestName(req), "stage": currentStage ?? NSNull()])
                }
            case .requestProgressInfo(let req, let info):
                if let st = info.processingStage {
                    let name = stageName(st)
                    if name != currentStage {
                        if let c = currentStage { result.stageSeconds[c, default: 0] += Date().timeIntervalSince(stageStart) }
                        currentStage = name
                        stageStart = Date()
                        log.emit("stage", ["stage": name, "request": requestName(req),
                                           "remaining_s": info.estimatedRemainingTime ?? NSNull()])
                        log.info("Stufe: \(name)")
                    }
                }
            case .requestComplete(let req, let res):
                pending.remove(requestName(req))
                switch res {
                case .poses(let poses):
                    result.poses = convert(poses)
                    result.posesAt = Date().timeIntervalSince(t0)
                    log.info("Posen fertig: \(result.poses.count) von \(poses.urlsBySample.count) Bildern nach \(Int(result.posesAt!)) s")
                    try onPoses(result)
                    try sendFollowUp()
                case .pointCloud(let pc):
                    result.points = pc.points.map { $0.position }
                    result.colors = pc.points.map { $0.color }
                    log.info("Punktwolke fertig: \(pc.points.count) Punkte")
                    try onPointCloud(result)
                case .modelFile(let url):
                    if url.pathExtension.lowercased() == "usdz" { result.usdz = url } else { result.objDir = url }
                    log.emit("file", ["kind": url.pathExtension.lowercased() == "usdz" ? "usdz_raw" : "obj_raw", "path": url.path])
                    log.info("Netz geschrieben: \(url.path)")
                default:
                    break
                }
            case .requestError(let req, let err):
                pending.remove(requestName(req))
                if case .poses = req { try sendFollowUp() }
                log.emit("error", ["request": requestName(req), "message": err.localizedDescription])
                log.info("Fehler bei \(requestName(req)): \(err.localizedDescription)")
                if case .modelFile = req { failure = err }
            case .processingComplete:
                if followUp != nil { try sendFollowUp(); continue }
                if !pending.isEmpty && (session.isProcessing || !session.activeRequests.isEmpty) { continue }
                break outer
            case .processingCancelled:
                failure = CaptureError.message("Rekonstruktion abgebrochen")
                break outer
            case .invalidSample(let id, let reason):
                result.invalid[id] = reason
                log.warn("Bild \(id) ungültig: \(reason)")
            case .skippedSample(let id):
                result.skipped.append(id)
                log.emit("skipped_sample", ["sample": id])
            case .automaticDownsampling:
                log.warn("Object Capture verkleinert die Bilder selbst (zu wenig Speicher)")
            case .stitchingIncomplete:
                log.warn("Nicht alle Bilder ließen sich verbinden (stitchingIncomplete) – Lücken in der Aufnahme?")
            @unknown default:
                break
            }
        }
        if let c = currentStage { result.stageSeconds[c, default: 0] += Date().timeIntervalSince(stageStart) }
        result.seconds = Date().timeIntervalSince(t0)
        if let f = failure { throw f }
        if !pending.isEmpty { log.warn("Unvollständig: \(pending.sorted().joined(separator: ", "))") }
        return result
    }

    func convert(_ poses: PhotogrammetrySession.Poses) -> [CameraPose] {
        let urls = poses.urlsBySample
        var out: [CameraPose] = []
        for (id, pose) in poses.posesBySample.sorted(by: { $0.key < $1.key }) {
            var p = CameraPose(sample: id, image: urls[id]?.lastPathComponent ?? "sample_\(id)",
                               cameraToWorld: pose.transform.matrix, intrinsics: nil)
            if #available(macOS 26.0, *) {
                p.intrinsics = pose.intrinsics
                if let ld = pose.lensDistortionData {
                    p.distortionCenter = ld.center
                    p.distortionTable = ld.radialLookupTable
                }
            }
            out.append(p)
        }
        return out.sorted { $0.image < $1.image }
    }

    func requestName(_ r: PhotogrammetrySession.Request) -> String {
        switch r {
        case .poses: return "poses"
        case .pointCloud: return "point_cloud"
        case .bounds: return "bounds"
        case .modelEntity: return "model_entity"
        case .modelFile(let url, _, _): return url.pathExtension.lowercased() == "usdz" ? "usdz" : "obj"
        @unknown default: return "unknown"
        }
    }

    func stageName(_ s: PhotogrammetrySession.Output.ProcessingStage) -> String {
        switch s {
        case .preProcessing: return "pre_processing"
        case .imageAlignment: return "image_alignment"
        case .pointCloudGeneration: return "point_cloud_generation"
        case .meshGeneration: return "mesh_generation"
        case .textureMapping: return "texture_mapping"
        case .optimization: return "optimization"
        @unknown default: return "unknown"
        }
    }
}
