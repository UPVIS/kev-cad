import Foundation

/// Fortschritt als JSON-Zeilen auf stdout (eine Zeile je Ereignis), menschenlesbare Hinweise auf stderr.
/// Kev CAD liest stdout zeilenweise; jedes Objekt hat `event` und `t` (Sekunden seit Start).
public final class ProgressLog: @unchecked Sendable {
    public static let shared = ProgressLog()

    private let lock = NSLock()
    private let start = Date()
    public var quiet = false
    private var lastProgress: [String: (Double, Date)] = [:]

    public var elapsed: Double { Date().timeIntervalSince(start) }

    /// Schreibt ein Ereignis. Werte müssen JSON-tauglich sein (String, Zahl, Bool, Array, Dictionary, NSNull).
    public func emit(_ event: String, _ fields: [String: Any] = [:]) {
        var obj = fields
        obj["event"] = event
        obj["t"] = (elapsed * 1000).rounded() / 1000
        guard let data = try? JSONSerialization.data(withJSONObject: sanitize(obj), options: [.sortedKeys, .withoutEscapingSlashes]),
              var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"
        lock.lock()
        FileHandle.standardOutput.write(line.data(using: .utf8)!)
        lock.unlock()
    }

    /// Fortschritt einer Phase (0…1). Gedrosselt: höchstens alle 0,5 s oder bei +1 % je Phase.
    public func progress(_ phase: String, _ fraction: Double, _ extra: [String: Any] = [:]) {
        let now = Date()
        lock.lock()
        if let (last, when) = lastProgress[phase], fraction < 1, fraction - last < 0.01,
           now.timeIntervalSince(when) < 0.5 {
            lock.unlock()
            return
        }
        lastProgress[phase] = (fraction, now)
        lock.unlock()
        var f = extra
        f["phase"] = phase
        f["fraction"] = (min(max(fraction, 0), 1) * 1000).rounded() / 1000
        emit("progress", f)
    }

    public func info(_ text: String) {
        if quiet { return }
        let line = "[kevcad-capture \(String(format: "%6.1f", elapsed)) s] \(text)\n"
        lock.lock()
        FileHandle.standardError.write(line.data(using: .utf8)!)
        lock.unlock()
    }

    public func warn(_ text: String) {
        emit("warning", ["message": text])
        info("Warnung: \(text)")
    }

    private func sanitize(_ v: Any) -> Any {
        switch v {
        case let d as [String: Any]: return d.mapValues { sanitize($0) }
        case let a as [Any]: return a.map { sanitize($0) }
        case let x as Double: return x.isFinite ? x : NSNull()
        case let x as Float: return x.isFinite ? Double(x) : NSNull()
        case let u as URL: return u.path
        default: return v
        }
    }
}
