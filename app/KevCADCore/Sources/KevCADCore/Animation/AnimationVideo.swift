import CoreGraphics
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// Video aus einer Animation (Entscheidung A4): je Bild ein Offscreen-Bild (OffscreenRenderer wie beim
/// ScreenshotRenderer), roh an ffmpeg gefüttert, H.264 MP4 oder ProRes 422 (.mov).
///
/// Gerendert wird Bild für Bild auf dem Hauptthread, jeweils in einem eigenen Durchlauf der Ereignisschleife, damit die
/// App bedienbar bleibt und den Fortschritt zeigt; das Schreiben an ffmpeg läuft in einer eigenen Warteschlange.
@MainActor
public final class AnimationVideoExporter {
    public struct Job {
        public var clip: AnimationClip
        public var width: Int
        public var height: Int
        public var fps: Double
        public var format: String  // mp4 | prores
        public var output: URL
        /// Kamera je Zeit (Viewer-Kamera, Kamerafahrt oder später eine benannte Kamera).
        public var camera: (Double) -> CameraState
        /// Körper für die Zeit `t` (setzt vorher die Lage in der Szene).
        public var bodies: (Double) -> [ViewportBody]
        public var displayMode: DisplayMode
        public var lighting: LightingConfiguration
        public var background = SIMD4<Float>(0.95, 0.95, 0.95, 1)
    }

    public struct Output: Sendable {
        public var path: String
        public var frames: Int
        public var milliseconds: Int
    }

    public struct ExportError: Error, CustomStringConvertible {
        public var message: String
        public var description: String { message }
    }

    private var renderer: OffscreenRenderer?
    public private(set) var running = false
    private var cancelled = false

    public init() {}

    /// Ort von ffmpeg: `KEVCAD_FFMPEG`, sonst die üblichen Orte (Apps aus dem Dock haben einen kurzen PATH).
    public static func ffmpegPath() -> String? {
        let env = ProcessInfo.processInfo.environment
        var candidates: [String] = []
        if let p = env["KEVCAD_FFMPEG"], !p.isEmpty { candidates.append(p) }
        candidates += ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]
        for dir in (env["PATH"] ?? "").split(separator: ":") { candidates.append("\(dir)/ffmpeg") }
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    /// Argumente für ffmpeg: Rohbilder RGBA von stdin.
    public static func ffmpegArguments(width: Int, height: Int, fps: Double, format: String, output: String) -> [String] {
        var args = [
            "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "\(width)x\(height)",
            "-r", String(format: "%.6g", fps), "-i", "-",
        ]
        if format == "prores" {
            args += ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
        } else {
            args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        }
        return args + [output]
    }

    public func cancel() { cancelled = true }

    public func export(
        _ job: Job, progress: @escaping (Int, Int) -> Void,
        completion: @escaping (Result<Output, ExportError>) -> Void
    ) {
        guard !running else {
            completion(.failure(ExportError(message: "Es läuft schon eine Videoausgabe")))
            return
        }
        guard let ffmpeg = Self.ffmpegPath() else {
            completion(.failure(ExportError(message: "ffmpeg nicht gefunden (KEVCAD_FFMPEG setzen oder ffmpeg installieren)")))
            return
        }
        let w = max(16, job.width / 2 * 2), h = max(16, job.height / 2 * 2)
        let frames = Int((job.clip.duration * job.fps).rounded()) + 1
        do {
            try FileManager.default.createDirectory(
                at: job.output.deletingLastPathComponent(), withIntermediateDirectories: true)
        } catch {
            completion(.failure(ExportError(message: "Ordner nicht anlegbar: \(error.localizedDescription)")))
            return
        }
        let target = job.output
        let tmp = job.output.deletingLastPathComponent()
            .appendingPathComponent(".\(job.output.deletingPathExtension().lastPathComponent)-entsteht.\(job.output.pathExtension)")
        try? FileManager.default.removeItem(at: tmp)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: ffmpeg)
        process.arguments = Self.ffmpegArguments(width: w, height: h, fps: job.fps, format: job.format, output: tmp.path)
        let stdin = Pipe(), stderr = Pipe()
        process.standardInput = stdin
        process.standardError = stderr
        process.standardOutput = FileHandle.nullDevice
        let errorText = LockedText()
        stderr.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty { errorText.append(String(decoding: data, as: UTF8.self)) }
        }
        do {
            try process.run()
        } catch {
            completion(.failure(ExportError(message: "ffmpeg startet nicht: \(error.localizedDescription)")))
            return
        }
        running = true
        cancelled = false
        let started = CACurrentMediaTime()
        let writer = DispatchQueue(label: "de.upvis.kevcad.video")
        let pipeHandle = stdin.fileHandleForWriting
        let pipeBroken = LockedFlag()
        signal(SIGPIPE, SIG_IGN)  // ffmpeg kann vorzeitig enden; dann soll nur das Schreiben scheitern

        func finish(_ result: Result<Output, ExportError>) {
            running = false
            completion(result)
        }

        func close() {
            writer.async {
                try? pipeHandle.close()
                process.waitUntilExit()
                stderr.fileHandleForReading.readabilityHandler = nil
                let status = process.terminationStatus
                DispatchQueue.main.async {
                    MainActor.assumeIsolated {
                        if self.cancelled {
                            try? FileManager.default.removeItem(at: tmp)
                            finish(.failure(ExportError(message: "Videoausgabe abgebrochen")))
                            return
                        }
                        guard status == 0, FileManager.default.fileExists(atPath: tmp.path) else {
                            let tail = errorText.value.split(separator: "\n").suffix(4).joined(separator: " · ")
                            finish(.failure(ExportError(message: "ffmpeg meldet Fehler \(status)" + (tail.isEmpty ? "" : ": \(tail)"))))
                            return
                        }
                        do {
                            try? FileManager.default.removeItem(at: target)
                            try FileManager.default.moveItem(at: tmp, to: target)
                        } catch {
                            finish(.failure(ExportError(message: "Video nicht gespeichert: \(error.localizedDescription)")))
                            return
                        }
                        let ms = Int((CACurrentMediaTime() - started) * 1000)
                        finish(.success(Output(path: target.path, frames: frames, milliseconds: ms)))
                    }
                }
            }
        }

        func render(_ k: Int) {
            if cancelled || pipeBroken.value {
                close()
                return
            }
            if k >= frames {
                close()
                return
            }
            let t = min(Double(k) / job.fps, job.clip.duration)
            let bodies = job.bodies(t)
            guard let image = renderFrame(bodies: bodies, camera: job.camera(t), width: w, height: h, job: job),
                let rgba = Self.rgbaBytes(image, width: w, height: h)
            else {
                errorText.append("Bild \(k) ließ sich nicht rendern")
                pipeBroken.set()
                writer.async { process.terminate() }
                close()
                return
            }
            writer.async {
                do {
                    try pipeHandle.write(contentsOf: rgba)
                } catch {
                    pipeBroken.set()
                }
            }
            progress(k + 1, frames)
            DispatchQueue.main.async { MainActor.assumeIsolated { render(k + 1) } }
        }
        render(0)
    }

    private func renderFrame(bodies: [ViewportBody], camera: CameraState, width: Int, height: Int, job: Job) -> CGImage? {
        if renderer == nil { renderer = OffscreenRenderer() }
        guard let renderer else { return nil }
        let options = OffscreenRenderOptions(
            width: width, height: height, cameraState: camera, displayMode: job.displayMode,
            lightingConfiguration: job.lighting, backgroundColor: job.background, showGrid: false, showAxes: false,
            msaaSampleCount: 4)
        return renderer.render(bodies: bodies, options: options)
    }

    /// Bild als RGBA (8 Bit, sRGB, deckend) für ffmpeg.
    nonisolated static func rgbaBytes(_ image: CGImage, width: Int, height: Int) -> Data? {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        var data = Data(count: width * height * 4)
        let ok = data.withUnsafeMutableBytes { buf -> Bool in
            guard let ctx = CGContext(
                data: buf.baseAddress, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return false }
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        return ok ? data : nil
    }

    /// Kamera einer Kamerafahrt (Lage, Ziel, Bildwinkel) als Viewport-Kamera, Z oben.
    public static func camera(from key: AnimationCameraKey, base: CameraState) -> CameraState {
        var dir = key.target - key.position
        if simd_length(dir) < 1e-4 { dir = SIMD3(0, 1, 0) }
        var up = SIMD3<Float>(0, 0, 1)
        if abs(simd_dot(simd_normalize(dir), up)) > 0.999 { up = SIMD3(0, 1, 0) }
        var cam = CameraState.lookAt(target: key.target, from: key.position, up: up)
        cam.fieldOfView = key.fieldOfView ?? base.fieldOfView
        cam.isOrthographic = false
        cam.orthographicScale = base.orthographicScale
        return cam
    }
}

/// Kleine threadsichere Hilfen für die Schreibwarteschlange.
final class LockedText: @unchecked Sendable {
    private let lock = NSLock()
    private var text = ""
    func append(_ s: String) {
        lock.lock()
        text += s
        if text.count > 4000 { text = String(text.suffix(4000)) }
        lock.unlock()
    }
    var value: String {
        lock.lock()
        defer { lock.unlock() }
        return text
    }
}

final class LockedFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var flag = false
    func set() {
        lock.lock()
        flag = true
        lock.unlock()
    }
    var value: Bool {
        lock.lock()
        defer { lock.unlock() }
        return flag
    }
}
