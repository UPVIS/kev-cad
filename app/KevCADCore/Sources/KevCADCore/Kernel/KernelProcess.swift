import Darwin
import Foundation

/// Startbefehl des Kernels.
public struct KernelCommand: Equatable, Sendable {
    public var executable: String
    public var arguments: [String]
    /// Lesbare Form für das Protokoll.
    public var display: String
}

public enum KernelLaunchError: Error, Equatable, CustomStringConvertible {
    case notFound(String)
    case launchFailed(String)

    public var description: String {
        switch self {
        case .notFound(let s), .launchFailed(let s): return s
        }
    }
}

/// Startet und überwacht den Kernel-Server (`kevcad-kernel serve --socket … --port …`).
///
/// - `KEVCAD_KERNEL_CMD` ersetzt den Befehl (Shell-Syntax, Pfade mit Leerzeichen in Anführungszeichen); angehängt
///   werden `serve --socket <pfad> --port <port>`, z. B. für den Ersatz-Kernel `kernel/tools/fake_kernel.py`.
/// - Ausgaben gehen zeilenweise an `onOutput`, das Ende an `onExit`.
/// - Die PID steht in `kernel.pid` im Datenordner; ein übrig gebliebener Kernel einer abgestürzten App wird vor dem
///   Start beendet.
@MainActor
public final class KernelProcess {
    public var onOutput: ((String, Bool) -> Void)?  // Zeile, ist stderr
    public var onExit: ((Int32, Bool) -> Void)?  // Code, erwartet (von stop())

    private var process: Process?
    private var expectedExit = false
    private var outBuffer = LineBuffer()
    private var errBuffer = LineBuffer()
    public private(set) var startedAt: Date?

    public init() {}

    public var isRunning: Bool { process?.isRunning ?? false }
    public var pid: Int32? { process.map { $0.processIdentifier } }

    // MARK: Befehl

    /// Ermittelt den Startbefehl aus Umgebung und App-Angaben.
    public static func command(
        socket: String, port: Int, environment: [String: String] = ProcessInfo.processInfo.environment,
        executable: URL? = AppInfo.kernelExecutable, fileManager: FileManager = .default
    ) -> Result<KernelCommand, KernelLaunchError> {
        let tail = "serve --socket \(shellQuote(socket)) --port \(port)"
        if let custom = environment["KEVCAD_KERNEL_CMD"]?.trimmingCharacters(in: .whitespacesAndNewlines),
            !custom.isEmpty
        {
            return .success(
                KernelCommand(executable: "/bin/sh", arguments: ["-c", "exec \(custom) \(tail)"], display: "\(custom) \(tail)"))
        }
        guard let exe = executable else {
            return .failure(
                .notFound(
                    "Kernel nicht gefunden: Die App kennt den Repo-Ordner nicht (mit build.sh bauen). Einrichten mit: cd kernel && uv sync"
                ))
        }
        guard fileManager.isExecutableFile(atPath: exe.path) else {
            return .failure(.notFound("Kernel nicht gefunden (\(exe.path)). Einrichten mit: cd kernel && uv sync"))
        }
        return .success(
            KernelCommand(
                executable: exe.path, arguments: ["serve", "--socket", socket, "--port", String(port)],
                display: "\(shellQuote(exe.path)) \(tail)"))
    }

    public static func shellQuote(_ s: String) -> String {
        if !s.isEmpty, s.allSatisfy({ $0.isLetter || $0.isNumber || "/._-+:=@".contains($0) }) { return s }
        return "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    // MARK: Start und Ende

    public func start(socket: String, port: Int) throws {
        if isRunning { return }
        let cmd: KernelCommand
        switch Self.command(socket: socket, port: port) {
        case .success(let c): cmd = c
        case .failure(let e): throw e
        }
        Self.killStaleKernel()
        try? FileManager.default.removeItem(atPath: socket)

        let p = Process()
        p.executableURL = URL(fileURLWithPath: cmd.executable)
        p.arguments = cmd.arguments
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["KEVCAD_APP_BUNDLE_ID"] = AppInfo.bundleID
        env.removeValue(forKey: "KEVCAD_KERNEL_CMD")
        p.environment = env
        if let repo = AppInfo.repoDirectory {
            p.currentDirectoryURL = repo.appendingPathComponent("kernel", isDirectory: true)
        }
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        p.standardInput = FileHandle.nullDevice
        outBuffer = LineBuffer()
        errBuffer = LineBuffer()
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil }
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.consume(d, stderr: false) } }
        }
        err.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil }
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.consume(d, stderr: true) } }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            // Kurz warten, damit die letzten Ausgaben vor der Meldung des Endes ankommen; die Leser beenden sich
            // selbst am Ende des Datenstroms
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                MainActor.assumeIsolated {
                    guard let self, self.process === proc else { return }
                    self.flushBuffers()
                    let expected = self.expectedExit
                    self.process = nil
                    self.removePIDFile()
                    self.onExit?(code, expected)
                }
            }
        }
        expectedExit = false
        do {
            try p.run()
        } catch {
            throw KernelLaunchError.launchFailed("Kernel ließ sich nicht starten: \(error.localizedDescription)")
        }
        process = p
        startedAt = Date()
        writePIDFile(p.processIdentifier)
        onOutput?("Kernel gestartet (PID \(p.processIdentifier)): \(cmd.display)", false)
    }

    /// Beendet den Kernel: SIGTERM, nach `grace` Sekunden SIGKILL.
    public func stop(grace: TimeInterval = 2) {
        guard let p = process, p.isRunning else {
            process = nil
            return
        }
        expectedExit = true
        let pid = p.processIdentifier
        p.terminate()
        DispatchQueue.global().asyncAfter(deadline: .now() + grace) {
            if kill(pid, 0) == 0, p.isRunning { kill(pid, SIGKILL) }
        }
    }

    /// Beim Beenden der App: sofort und blockierend (höchstens `timeout`).
    public func stopNow(timeout: TimeInterval = 1.0) {
        guard let p = process, p.isRunning else { return }
        expectedExit = true
        p.terminate()
        let deadline = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < deadline { usleep(20_000) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
        removePIDFile()
    }

    // MARK: Ausgabe

    private func consume(_ data: Data, stderr: Bool) {
        guard !data.isEmpty else { return }
        let lines = stderr ? errBuffer.append(data) : outBuffer.append(data)
        for l in lines where !l.isEmpty { onOutput?(l, stderr) }
    }

    private func flushBuffers() {
        if let l = outBuffer.flush(), !l.isEmpty { onOutput?(l, false) }
        if let l = errBuffer.flush(), !l.isEmpty { onOutput?(l, true) }
    }

    // MARK: PID-Datei

    static var pidFile: URL { AppInfo.supportDirectory.appendingPathComponent("kernel.pid") }

    private func writePIDFile(_ pid: Int32) {
        try? "\(pid)\n".write(to: Self.pidFile, atomically: true, encoding: .utf8)
    }

    private func removePIDFile() { try? FileManager.default.removeItem(at: Self.pidFile) }

    /// Beendet einen Kernel, der von einer früheren (abgestürzten) App-Sitzung übrig ist.
    static func killStaleKernel() {
        guard let text = try? String(contentsOf: pidFile, encoding: .utf8),
            let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1
        else { return }
        defer { try? FileManager.default.removeItem(at: pidFile) }
        guard kill(pid, 0) == 0 else { return }
        var buf = [CChar](repeating: 0, count: 4096)
        guard proc_pidpath(pid, &buf, UInt32(buf.count)) > 0 else { return }
        let path = String(cString: buf).lowercased()
        guard path.contains("python") || path.contains("kevcad") else { return }
        kill(pid, SIGTERM)
        for _ in 0..<50 where kill(pid, 0) == 0 { usleep(20_000) }
        if kill(pid, 0) == 0 { kill(pid, SIGKILL) }
    }
}

/// Zerlegt einen Bytestrom in Zeilen (UTF-8, Zeilenende \n).
struct LineBuffer {
    private var pending = Data()

    mutating func append(_ data: Data) -> [String] {
        pending.append(data)
        var lines: [String] = []
        while let nl = pending.firstIndex(of: 0x0A) {
            let lineData = pending[pending.startIndex..<nl]
            lines.append(String(decoding: lineData, as: UTF8.self).trimmingCharacters(in: CharacterSet(charactersIn: "\r")))
            pending.removeSubrange(pending.startIndex...nl)
        }
        if pending.count > 64 * 1024 {
            lines.append(String(decoding: pending, as: UTF8.self))
            pending.removeAll()
        }
        return lines
    }

    mutating func flush() -> String? {
        guard !pending.isEmpty else { return nil }
        defer { pending.removeAll() }
        return String(decoding: pending, as: UTF8.self)
    }
}
