import Darwin
import Foundation

/// Unix-Socket des Spiegels (MIRROR.md): lauscht, prüft die Gegenstelle mit `getpeereid` (gleiche UID, sonst sofort
/// trennen) und hält je Verbindung eine Sendewarteschlange mit dem Vorrang aus dem Vertrag:
/// zustand > kamera (nur der neueste, höchstens 40 je Sekunde) > szene > netz. Rahmen werden erst beim Senden kodiert
/// (`seq` in Leitungsreihenfolge) und einzeln nacheinander geschrieben, so kann ein Zustand höchstens hinter dem
/// gerade laufenden Netzblock warten. Lesen, Dekodieren und Schreiben laufen auf einer eigenen Warteschlange; Ereignisse
/// kommen auf dem Hauptthread an.
public final class MirrorSocketServer: @unchecked Sendable {
    public enum Event: Sendable {
        case connected(Int)
        case disconnected(Int, String)
        case message(Int, MirrorMessage)
        /// Rahmen, der sich nicht lesen ließ (Verbindung, Grund)
        case invalid(Int, String)
    }

    public enum ServerError: Error, CustomStringConvertible {
        case pathTooLong(String)
        case socket(String)

        public var description: String {
            switch self {
            case .pathTooLong(let p): return "Socket-Pfad zu lang (höchstens 103 Byte): \(p)"
            case .socket(let s): return "Spiegel-Socket: \(s)"
            }
        }
    }

    public let path: String
    /// Ereignisse auf dem Hauptthread (vor `start()` setzen).
    public var onEvent: (@MainActor (Event) -> Void)?
    /// Mindestabstand zwischen zwei Kamerarahmen je Verbindung.
    public var cameraInterval: TimeInterval = 1 / MirrorProtocol.cameraRate

    let queue = DispatchQueue(label: "de.upvis.kevcad.mirror", qos: .userInitiated)
    private var listenFD: Int32 = -1
    private var acceptSource: DispatchSourceRead?
    private var connections: [Int: MirrorConnection] = [:]
    private var nextID = 0

    public init(path: String) {
        self.path = path
    }

    deinit {
        if listenFD >= 0 { Darwin.close(listenFD) }
    }

    // MARK: Lauschen

    /// Ordner 0700, alten Socket entfernen, binden, Socket 0600, lauschen.
    public func start() throws {
        let bytes = Array(path.utf8)
        var addr = sockaddr_un()
        guard bytes.count < MemoryLayout.size(ofValue: addr.sun_path) else { throw ServerError.pathTooLong(path) }
        let dir = (path as NSString).deletingLastPathComponent
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        chmod(dir, 0o700)
        unlink(path)
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ServerError.socket("socket: \(String(cString: strerror(errno)))") }
        addr.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let old = umask(0o177)
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        umask(old)
        guard rc == 0 else {
            let e = String(cString: strerror(errno))
            Darwin.close(fd)
            throw ServerError.socket("bind \(path): \(e)")
        }
        chmod(path, 0o600)
        guard listen(fd, 8) == 0 else {
            let e = String(cString: strerror(errno))
            Darwin.close(fd)
            throw ServerError.socket("listen: \(e)")
        }
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        queue.sync {
            self.listenFD = fd
            let src = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
            src.setEventHandler { [weak self] in self?.acceptAll() }
            acceptSource = src
            src.resume()
        }
    }

    /// Alle Verbindungen trennen, nicht mehr lauschen, Socket-Datei entfernen.
    public func stop() {
        queue.sync {
            acceptSource?.cancel()
            acceptSource = nil
            if listenFD >= 0 {
                Darwin.close(listenFD)
                listenFD = -1
            }
            for c in connections.values { c.close(reason: nil) }
            connections = [:]
        }
        unlink(path)
    }

    private func acceptAll() {
        while true {
            let fd = accept(listenFD, nil, nil)
            if fd < 0 { return }
            var uid: uid_t = 0
            var gid: gid_t = 0
            guard getpeereid(fd, &uid, &gid) == 0, uid == getuid() else {
                Darwin.close(fd)
                continue
            }
            var on: Int32 = 1
            setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
            _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
            nextID += 1
            let conn = MirrorConnection(id: nextID, fd: fd, server: self)
            connections[nextID] = conn
            conn.start()
            deliver(.connected(nextID))
        }
    }

    func connectionClosed(_ id: Int, reason: String) {
        connections[id] = nil
        deliver(.disconnected(id, reason))
    }

    func deliver(_ event: Event) {
        guard let handler = onEvent else { return }
        DispatchQueue.main.async { MainActor.assumeIsolated { handler(event) } }
    }

    // MARK: Senden

    /// Nachricht einreihen (Vorrang aus `message.prio`); kodiert wird erst beim Senden.
    public func send(_ message: any MirrorOutgoing, payload: Data = Data(), to ids: [Int]) {
        guard !ids.isEmpty else { return }
        queue.async {
            for id in ids { self.connections[id]?.enqueue(message, payload: payload) }
        }
    }

    /// Alle Blöcke eines Netzes einreihen.
    public func sendMesh(_ mesh: PackedMesh, to id: Int) {
        queue.async {
            guard let c = self.connections[id] else { return }
            for i in 0..<mesh.blockCount { c.enqueue(mesh.blockHeader(i), payload: mesh.blockPayload(i)) }
        }
    }

    public func close(_ id: Int, reason: String) {
        queue.async { self.connections[id]?.close(reason: reason) }
    }

    /// Für Tests: wartet, bis alles bisher Eingereihte bearbeitet ist (nicht: bis es geschrieben ist).
    public func sync() { queue.sync {} }

    /// Rahmen, die je Verbindung noch auf das Senden warten.
    public func pendingFrames() -> [Int: Int] {
        queue.sync { connections.mapValues(\.pendingCount) }
    }
}

/// Eine Verbindung; alle Zustände gehören der Warteschlange des Servers.
final class MirrorConnection {
    private struct Outgoing {
        var message: any MirrorOutgoing
        var payload: Data
    }

    let id: Int
    private let fd: Int32
    private unowned let server: MirrorSocketServer
    private var readSource: DispatchSourceRead?
    private var writeSource: DispatchSourceWrite?
    private var writeSuspended = true
    private var reader = FrameReader()
    private var readBuffer = [UInt8](repeating: 0, count: 64 * 1024)
    private var zustand: [Outgoing] = []
    private var szene: [Outgoing] = []
    private var netz: [Outgoing] = []
    private var camera: Outgoing?
    private var lastCamera: CFAbsoluteTime = 0
    private var cameraTimer = false
    private var seq = 0
    private var out = Data()
    private var outOffset = 0
    private var closed = false

    init(id: Int, fd: Int32, server: MirrorSocketServer) {
        self.id = id
        self.fd = fd
        self.server = server
    }

    var pendingCount: Int { zustand.count + szene.count + netz.count + (camera == nil ? 0 : 1) + (out.isEmpty ? 0 : 1) }

    func start() {
        let r = DispatchSource.makeReadSource(fileDescriptor: fd, queue: server.queue)
        r.setEventHandler { [weak self] in self?.readAvailable() }
        readSource = r
        r.resume()
        let w = DispatchSource.makeWriteSource(fileDescriptor: fd, queue: server.queue)
        w.setEventHandler { [weak self] in self?.pump() }
        writeSource = w  // startet angehalten
    }

    func close(reason: String?) {
        guard !closed else { return }
        closed = true
        readSource?.cancel()
        if let w = writeSource {
            if writeSuspended { w.resume() }
            w.cancel()
        }
        readSource = nil
        writeSource = nil
        Darwin.close(fd)
        zustand = []
        szene = []
        netz = []
        camera = nil
        if let reason { server.connectionClosed(id, reason: reason) }
    }

    // MARK: Lesen

    private func readAvailable() {
        guard !closed else { return }
        var reason: String?
        while true {
            let n = readBuffer.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
            if n > 0 {
                do {
                    let frames = try readBuffer.withUnsafeBytes {
                        try reader.feed(UnsafeRawBufferPointer(rebasing: $0[0..<n]))
                    }
                    for f in frames { handle(f) }
                } catch {
                    reason = "Datenstrom ungültig: \(error)"
                    break
                }
            } else if n == 0 {
                reason = "Gegenstelle hat getrennt"
                break
            } else {
                let e = errno
                if e == EAGAIN || e == EWOULDBLOCK { break }
                if e == EINTR { continue }
                reason = "Lesefehler: \(String(cString: strerror(e)))"
                break
            }
        }
        if let reason { close(reason: reason) }
    }

    private func handle(_ frame: Frame) {
        if frame.header.count > MirrorProtocol.maxHeaderBytes || frame.payload.count > MirrorProtocol.maxPayloadBytes {
            server.deliver(.invalid(id, "Rahmen über den Grenzen (\(frame.header.count) / \(frame.payload.count) Byte)"))
            return
        }
        do {
            server.deliver(.message(id, try MirrorMessage.decode(frame)))
        } catch {
            server.deliver(.invalid(id, "\(error)"))
        }
    }

    // MARK: Schreiben

    func enqueue(_ message: any MirrorOutgoing, payload: Data) {
        guard !closed else { return }
        let item = Outgoing(message: message, payload: payload)
        switch message.prio {
        case .zustand: zustand.append(item)
        case .kamera: camera = item  // nur der neueste zählt
        case .szene: szene.append(item)
        case .netz: netz.append(item)
        }
        pump()
    }

    /// Nächster Rahmen nach Vorrang; nil, wenn nichts fällig ist (eine Kamera wartet dann auf ihren Zeitpunkt).
    private func next() -> Outgoing? {
        if !zustand.isEmpty { return zustand.removeFirst() }
        if let cam = camera {
            let due = lastCamera + server.cameraInterval - CFAbsoluteTimeGetCurrent()
            if due <= 0 {
                camera = nil
                lastCamera = CFAbsoluteTimeGetCurrent()
                return cam
            }
            if !cameraTimer {
                cameraTimer = true
                server.queue.asyncAfter(deadline: .now() + due) { [weak self] in
                    self?.cameraTimer = false
                    self?.pump()
                }
            }
        }
        if !szene.isEmpty { return szene.removeFirst() }
        if !netz.isEmpty { return netz.removeFirst() }
        return nil
    }

    private func pump() {
        guard !closed else { return }
        while true {
            if outOffset >= out.count {
                guard let item = next() else {
                    out = Data()
                    outOffset = 0
                    setWriteWanted(false)
                    return
                }
                seq += 1
                do {
                    out = try item.message.frame(seq: seq, payload: item.payload).encoded
                } catch {
                    seq -= 1
                    server.deliver(.invalid(id, "Senden: \(error)"))
                    continue
                }
                outOffset = 0
            }
            let n = out.withUnsafeBytes { raw in
                Darwin.write(fd, raw.baseAddress! + outOffset, raw.count - outOffset)
            }
            if n > 0 {
                outOffset += n
            } else if n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) {
                setWriteWanted(true)
                return
            } else if n < 0 && errno == EINTR {
                continue
            } else {
                close(reason: "Schreibfehler: \(String(cString: strerror(errno)))")
                return
            }
        }
    }

    private func setWriteWanted(_ wanted: Bool) {
        guard let w = writeSource else { return }
        if wanted && writeSuspended {
            writeSuspended = false
            w.resume()
        } else if !wanted && !writeSuspended {
            writeSuspended = true
            w.suspend()
        }
    }
}
