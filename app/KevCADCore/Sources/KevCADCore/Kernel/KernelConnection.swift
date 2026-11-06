import Darwin
import Foundation
import Network

/// Was die Verbindung an den Hauptthread liefert.
public enum IncomingEvent: Sendable {
    case connected
    case disconnected(String)
    case message(KernelMessage)
    /// PART_UPSERT, schon auf dem Lesethread zu Körper-Stücken vorbereitet
    case part(PartRecord)
    /// Rahmen, der sich nicht lesen ließ (Typ, Grund)
    case invalid(String, String)
    /// V2-5: WIE_ZUVOR ohne passende Basis (Art, Grund); die App fordert die Nachricht mit NOCHMAL neu an
    case basisFehlt(String, String)
}

/// I-2b (PLAN-IPAD.md): Ziel übers Netz, das iPad verbindet sich über die Mac-App mit dem Kernel. Die Wege werden der
/// Reihe nach versucht (Bonjour im WLAN, dann Adressen aus der Kopplung, etwa Tailscale), mit Schlüssel und Kennung
/// der Kopplung (`NetzKanal`).
public struct NetzZiel: Sendable {
    public var wege: [NWEndpoint]
    public var schluessel: Data
    public var kennung: String

    public init(wege: [NWEndpoint], schluessel: Data, kennung: String) {
        self.wege = wege
        self.schluessel = schluessel
        self.kennung = kennung
    }

    /// Aus einem Kopplungscode: zuerst der Bonjour-Dienst des Mac, dann jede Adresse aus dem Code.
    public init(code: KopplungsCode) {
        var wege: [NWEndpoint] = [.service(name: code.name, type: NetzKanal.dienstTyp, domain: "local.", interface: nil)]
        if let port = NWEndpoint.Port(rawValue: code.port) {
            wege += code.wege.map { NWEndpoint.hostPort(host: NWEndpoint.Host($0), port: port) }
        }
        self.init(wege: wege, schluessel: code.schluessel, kennung: code.kennung)
    }
}

/// Client zum Kernel. Am Mac über den Unix-Socket (POSIX + Dispatch), auf dem iPad übers Netz (`open(netz:)`, I-2b).
/// Verbindet sich wiederholt, bis der Kernel lauscht, und nach einem Abbruch erneut. Lesen, Dekodieren und das
/// Vorbereiten der Geometrie laufen auf einer eigenen Warteschlange; die Ereignisse kommen gebündelt und in Reihenfolge
/// auf dem Hauptthread an.
public final class KernelConnection: @unchecked Sendable {
    private let queue = DispatchQueue(label: "de.upvis.kevcad.kernel-socket", qos: .userInitiated)
    private var fd: Int32 = -1
    private var readSource: DispatchSourceRead?
    private var retryTimer: DispatchSourceTimer?
    private var reader = FrameReader()
    private var path = ""
    /// I-2b: Ziel übers Netz statt Unix-Socket; `wegIndex` zeigt auf den Weg des nächsten Versuchs.
    private var netzZiel: NetzZiel?
    private var netz: NWConnection?
    private var wegIndex = 0
    private var wanted = false
    private var readBuffer = [UInt8](repeating: 0, count: 256 * 1024)
    /// V2-5: Basen für WIE_ZUVOR, je Verbindung, nur auf dem Lesefaden.
    private let wieZuvor = WieZuvorSpeicher()

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
            self.netzZiel = nil
            self.wanted = true
            if self.fd < 0 { self.tryConnect() }
        }
    }

    /// I-2b: Verbindung übers Netz aufbauen und halten (iPad → Mac-App → Kernel). Ersetzt ein früheres Ziel.
    public func open(netz ziel: NetzZiel) {
        queue.async {
            self.netzZiel = ziel
            self.wegIndex = 0
            self.wanted = true
            if self.netz != nil {
                self.teardown(reason: "Neues Ziel")  // verbindet danach mit dem neuen Ziel
            } else if self.fd < 0 {
                self.tryConnect()
            }
        }
    }

    /// Verbunden übers Netz (sonst Unix-Socket oder getrennt).
    public var istNetz: Bool { queue.sync { netz != nil } }

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
        guard wanted, fd < 0, netz == nil else { return }
        if let ziel = netzZiel {
            netzVerbinden(ziel)
            return
        }
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
        wieZuvor.leeren()  // eine neue Verbindung beginnt leer
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
        // Übers Netz nicht im Takt des lokalen Sockets hämmern: höchstens jede Sekunde ein Weg
        t.schedule(deadline: .now() + (netzZiel != nil ? max(retryInterval, 1.0) : retryInterval))
        t.setEventHandler { [weak self] in
            self?.retryTimer = nil
            self?.tryConnect()
        }
        retryTimer = t
        t.resume()
    }

    private func teardown(reason: String?) {
        if let n = netz {
            netz = nil
            n.stateUpdateHandler = nil
            n.cancel()
            reader.reset()
            if let reason { deliver([.disconnected(reason)]) }
            if wanted { scheduleRetry() }
            return
        }
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
                    for f in frames { events.append(annehmen(f)) }
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
            return decode(frame, envelope: try JSONDecoder().decode(MessageEnvelope.self, from: frame.header))
        } catch {
            return .invalid("?", "\(error)")
        }
    }

    private static func decode(_ frame: Frame, envelope env: MessageEnvelope) -> IncomingEvent {
        do {
            let msg = try KernelMessage.decode(frame, envelope: env)
            if case .partUpsert(let head, let geo) = msg { return .part(PartRecord(header: head, geometry: geo)) }
            return .message(msg)
        } catch {
            return .invalid(env.type, "\(error)")
        }
    }

    /// Rahmen vom Kernel: WIE_ZUVOR wieder aufbauen, dekodieren.
    private func annehmen(_ frame: Frame) -> IncomingEvent {
        guard let env = try? JSONDecoder().decode(MessageEnvelope.self, from: frame.header) else {
            return Self.decode(frame)
        }
        switch wieZuvor.empfangen(frame, envelope: env) {
        case .rahmen(let f, let e):
            return Self.decode(f, envelope: e)
        case .fehlt(let art, let grund):
            return .basisFehlt(art, grund)
        }
    }

    private func deliver(_ events: [IncomingEvent]) {
        guard let handler = onEvents else { return }
        DispatchQueue.main.async { MainActor.assumeIsolated { handler(events) } }
    }

    // MARK: Schreiben

    private func writeAll(_ data: Data) {
        if let n = netz {
            n.send(content: data, completion: .contentProcessed { [weak self, weak n] fehler in
                guard let self, let n, let fehler, self.netz === n else { return }
                self.teardown(reason: "Senden gescheitert: \(fehler)")
            })
            return
        }
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

    // MARK: Netz (I-2b, iPad)

    private func netzVerbinden(_ ziel: NetzZiel) {
        guard !ziel.wege.isEmpty else {
            deliver([.disconnected("Kein Weg zum Mac bekannt")])
            return
        }
        let weg = ziel.wege[wegIndex % ziel.wege.count]
        wegIndex += 1
        let c = NWConnection(to: weg, using: NetzKanal.parameter(schluessel: ziel.schluessel, kennung: ziel.kennung))
        netz = c
        c.stateUpdateHandler = { [weak self, weak c] zustand in
            guard let self, let c, self.netz === c else { return }
            switch zustand {
            case .ready:
                self.wegIndex -= 1  // dieser Weg ging: beim nächsten Abbruch zuerst wieder ihn versuchen
                self.reader = FrameReader()
                self.wieZuvor.leeren()  // eine neue Verbindung beginnt leer
                self.deliver([.connected])
                self.netzLesen(c)
            case .waiting(let fehler):
                // Kein Weg (Netz weg, Mac nicht erreichbar): nächsten Weg versuchen statt hier zu warten
                self.teardown(reason: NetzKanal.schluesselPasstNicht(fehler) ? "Schlüssel passt nicht" : nil)
            case .failed(let fehler):
                self.teardown(reason: NetzKanal.schluesselPasstNicht(fehler) ? "Schlüssel passt nicht" : "\(fehler)")
            default:
                break
            }
        }
        c.start(queue: queue)
    }

    private func netzLesen(_ c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self, weak c] daten, _, fertig, fehler in
            guard let self, let c, self.netz === c else { return }
            if let daten, !daten.isEmpty {
                do {
                    let frames = try self.reader.feed(daten)
                    if !frames.isEmpty { self.deliver(frames.map { self.annehmen($0) }) }
                } catch {
                    return self.teardown(reason: "Datenstrom ungültig: \(error)")
                }
            }
            if let fehler { return self.teardown(reason: "\(fehler)") }
            if fertig { return self.teardown(reason: "Mac hat die Verbindung beendet") }
            self.netzLesen(c)
        }
    }
}
