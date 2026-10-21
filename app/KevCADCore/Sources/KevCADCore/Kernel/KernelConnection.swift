import Darwin
import Foundation

/// Was die Verbindung an den Hauptthread liefert.
public enum IncomingEvent: Sendable {
    case connected
    case disconnected(String)
    case message(KernelMessage)
    /// PART_UPSERT, schon auf dem Lesethread zu Körper-Stücken vorbereitet
    case part(PartRecord)
    /// Rahmen, der sich nicht lesen ließ (Typ, Grund)
    case invalid(String, String)
}

/// Unix-Socket-Client zum Kernel (POSIX + Dispatch). Verbindet sich wiederholt, bis der Kernel lauscht, und nach
/// einem Abbruch erneut. Lesen, Dekodieren und das Vorbereiten der Geometrie laufen auf einer eigenen Warteschlange;
/// die Ereignisse kommen gebündelt und in Reihenfolge auf dem Hauptthread an.
public final class KernelConnection: @unchecked Sendable {
    private let queue = DispatchQueue(label: "de.upvis.kevcad.kernel-socket", qos: .userInitiated)
    private var fd: Int32 = -1
    private var readSource: DispatchSourceRead?
    private var retryTimer: DispatchSourceTimer?
    private var reader = FrameReader()
    private var path = ""
    private var wanted = false
    private var readBuffer = [UInt8](repeating: 0, count: 256 * 1024)

    /// Ereignisse auf dem Hauptthread.
    public var onEvents: (@MainActor ([IncomingEvent]) -> Void)?
    /// Abstand zwischen Verbindungsversuchen.
    public var retryInterval: TimeInterval = 0.2

    public init() {}

    deinit {
        if fd >= 0 { Darwin.close(fd) }
    }

    /// Verbindung aufbauen und halten (bis `close()`).
    public func open(path: String) {
        queue.async {
            self.path = path
            self.wanted = true
            if self.fd < 0 { self.tryConnect() }
        }
    }

    /// Verbindung trennen und keine neuen Versuche mehr.
    public func close() {
        queue.async {
            self.wanted = false
            self.retryTimer?.cancel()
            self.retryTimer = nil
            self.teardown(reason: nil)
        }
    }

    /// Bytes senden (in Reihenfolge, auch große Nutzlasten).
    public func send(_ data: Data) {
        queue.async { self.writeAll(data) }
    }

    /// Für Tests: wartet, bis alles bisher Eingereihte verarbeitet ist.
    public func sync() { queue.sync {} }

    // MARK: Verbinden

    private func tryConnect() {
        guard wanted, fd < 0 else { return }
        let s = socket(AF_UNIX, SOCK_STREAM, 0)
        guard s >= 0 else {
            scheduleRetry()
            return
        }
        var on: Int32 = 1
        setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(path.utf8)
        let cap = MemoryLayout.size(ofValue: addr.sun_path)
        guard bytes.count < cap else {
            Darwin.close(s)
            deliver([.disconnected("Socket-Pfad zu lang (\(bytes.count) Byte): \(path)")])
            return
        }
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(s, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard rc == 0 else {
            Darwin.close(s)
            scheduleRetry()
            return
        }
        let flags = fcntl(s, F_GETFL)
        _ = fcntl(s, F_SETFL, flags | O_NONBLOCK)
        fd = s
        reader = FrameReader()
        let src = DispatchSource.makeReadSource(fileDescriptor: s, queue: queue)
        src.setEventHandler { [weak self] in self?.readAvailable() }
        readSource = src
        src.resume()
        deliver([.connected])
    }

    private func scheduleRetry() {
        guard wanted else { return }
        retryTimer?.cancel()
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + retryInterval)
        t.setEventHandler { [weak self] in
            self?.retryTimer = nil
            self?.tryConnect()
        }
        retryTimer = t
        t.resume()
    }

    private func teardown(reason: String?) {
        guard fd >= 0 else { return }
        readSource?.cancel()
        readSource = nil
        Darwin.close(fd)
        fd = -1
        reader.reset()
        if let reason { deliver([.disconnected(reason)]) }
        if wanted { scheduleRetry() }
    }

    // MARK: Lesen

    private func readAvailable() {
        guard fd >= 0 else { return }
        var events: [IncomingEvent] = []
        var closedReason: String?
        while true {
            let n = readBuffer.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
            if n > 0 {
                do {
                    let frames = try readBuffer.withUnsafeBytes { try reader.feed(UnsafeRawBufferPointer(rebasing: $0[0..<n])) }
                    for f in frames { events.append(Self.decode(f)) }
                } catch {
                    closedReason = "Datenstrom ungültig: \(error)"
                    break
                }
                if n < readBuffer.count { break }
            } else if n == 0 {
                closedReason = "Kernel hat die Verbindung beendet"
                break
            } else {
                let e = errno
                if e == EAGAIN || e == EWOULDBLOCK { break }
                if e == EINTR { continue }
                closedReason = "Lesefehler: \(String(cString: strerror(e)))"
                break
            }
        }
        if !events.isEmpty { deliver(events) }
        if let closedReason { teardown(reason: closedReason) }
    }

    /// Dekodiert einen Rahmen; Geometrie wird gleich zu Körper-Stücken vorbereitet.
    static func decode(_ frame: Frame) -> IncomingEvent {
        do {
            let msg = try KernelMessage.decode(frame)
            if case .partUpsert(let head, let geo) = msg { return .part(PartRecord(header: head, geometry: geo)) }
            return .message(msg)
        } catch {
            let type = (try? JSONDecoder().decode(MessageEnvelope.self, from: frame.header).type) ?? "?"
            return .invalid(type, "\(error)")
        }
    }

    private func deliver(_ events: [IncomingEvent]) {
        guard let handler = onEvents else { return }
        DispatchQueue.main.async { MainActor.assumeIsolated { handler(events) } }
    }

    // MARK: Schreiben

    private func writeAll(_ data: Data) {
        guard fd >= 0 else { return }
        var failed: String?
        data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var off = 0
            while off < raw.count {
                let n = Darwin.write(fd, raw.baseAddress! + off, raw.count - off)
                if n > 0 {
                    off += n
                } else if n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) {
                    var p = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                    if poll(&p, 1, 5000) <= 0 {
                        failed = "Schreiben blockiert"
                        return
                    }
                } else if n < 0 && errno == EINTR {
                    continue
                } else {
                    failed = "Schreibfehler: \(String(cString: strerror(errno)))"
                    return
                }
            }
        }
        if let failed { teardown(reason: failed) }
    }
}
