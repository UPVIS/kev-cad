#if os(macOS)
import Darwin
import Foundation
import Network

/// I-2b (PLAN-IPAD.md, Entscheidung I8): Eingang der Mac-App für gekoppelte iPads. Lauscht mit TLS (ein Schlüssel je
/// Gerät, `NetzKanal`), meldet sich per Bonjour (`_kevcad._tcp`) und reicht jede Verbindung Byte für Byte an den
/// Kernel-Socket durch. Für den Kernel ist das iPad damit eine weitere App-Verbindung (PROTOCOL.md, „I-2 Mehrere
/// Geräte“); Inhalte sieht der Eingang nicht, nur den ersten Rahmen (HELLO_APP), um das Gerät zu erkennen.
public final class IPadEingang: @unchecked Sendable {
    private let queue = DispatchQueue(label: "de.upvis.kevcad.ipad-eingang", qos: .userInitiated)
    private let wunschPort: UInt16
    private let kernelSocket: String
    private let dienstName: String
    private let macKennung: String
    private var listener: NWListener?
    private var durchreichen: [ObjectIdentifier: Durchreiche] = [:]
    /// Schlüssel für den nächsten Eingang, solange der alte noch schließt (der Port ist erst danach frei).
    private var wartendeSchluessel: [(kennung: String, schluessel: Data)]?
    private var versuche = 0

    /// Zeile fürs Protokoll der App.
    public var onProtokoll: (@MainActor (String) -> Void)?
    /// Ein Gerät hat sich gemeldet: Kennung der Kopplung und Name aus HELLO_APP.geraet.
    public var onGeraet: (@MainActor (String, String?) -> Void)?
    /// Der Eingang lauscht (Port) oder ist zu (nil).
    public var onBereit: (@MainActor (UInt16?) -> Void)?

    /// `port` 0 nimmt einen freien Port (Tests).
    public init(port: UInt16, kernelSocket: String, dienstName: String, macKennung: String) {
        self.wunschPort = port
        self.kernelSocket = kernelSocket
        self.dienstName = dienstName
        self.macKennung = macKennung
    }

    /// Anzahl laufender Verbindungen (Tests, Anzeige).
    public var verbindungen: Int { queue.sync { durchreichen.count } }

    /// Startet den Eingang mit diesen Schlüsseln neu; ohne Schlüssel ist er zu (kein offener Port ohne Kopplung).
    public func starten(schluessel: [(kennung: String, schluessel: Data)]) {
        queue.async { self.neuStarten(schluessel) }
    }

    /// Schließt den Eingang und alle Verbindungen.
    public func stoppen() {
        queue.sync {
            wartendeSchluessel = nil
            listener?.cancel()
            listener = nil
            for d in durchreichen.values { d.schliessen() }
            durchreichen.removeAll()
        }
    }

    private func neuStarten(_ schluessel: [(kennung: String, schluessel: Data)]) {
        // Laufende Verbindungen bleiben (eigene NWConnections); nur der Eingang wird mit den neuen Schlüsseln neu geöffnet.
        // Erst wenn der alte wirklich zu ist, ist sein Port frei (sonst scheitert das Binden, gesehen im Kettentest).
        if let alt = listener {
            listener = nil
            wartendeSchluessel = schluessel
            alt.stateUpdateHandler = { [weak self] zustand in
                guard let self else { return }
                if case .cancelled = zustand, let neu = self.wartendeSchluessel {
                    self.wartendeSchluessel = nil
                    self.oeffnen(neu)
                }
            }
            alt.cancel()
            return
        }
        if wartendeSchluessel != nil {
            wartendeSchluessel = schluessel  // der alte schließt noch: dann gleich mit den neuesten Schlüsseln
            return
        }
        versuche = 0
        oeffnen(schluessel)
    }

    private func oeffnen(_ schluessel: [(kennung: String, schluessel: Data)]) {
        guard !schluessel.isEmpty else {
            melde(bereit: nil)
            return
        }
        let parameter = NetzKanal.parameter(schluessel: schluessel)
        parameter.allowLocalEndpointReuse = true
        let l: NWListener
        do {
            l = try NWListener(using: parameter, on: NWEndpoint.Port(rawValue: wunschPort) ?? .any)
        } catch {
            protokoll("iPad-Eingang ließ sich nicht öffnen: \(error)")
            melde(bereit: nil)
            return
        }
        if !dienstName.isEmpty {
            l.service = NWListener.Service(name: dienstName, type: NetzKanal.dienstTyp, domain: nil,
                                           txtRecord: NWTXTRecord(["v": "\(NetzKanal.fassung)", "mac": macKennung]))
        }
        l.stateUpdateHandler = { [weak self, weak l] zustand in
            guard let self, let l, self.listener === l else { return }
            switch zustand {
            case .ready:
                self.versuche = 0
                self.melde(bereit: l.port?.rawValue)
            case .failed(let fehler):
                self.listener = nil
                l.cancel()
                // Port noch belegt (eben geschlossener Eingang): kurz warten und erneut versuchen
                if self.versuche < 10 {
                    self.versuche += 1
                    self.queue.asyncAfter(deadline: .now() + 0.3) { [weak self] in
                        guard let self, self.listener == nil, self.wartendeSchluessel == nil else { return }
                        self.oeffnen(schluessel)
                    }
                } else {
                    self.protokoll("iPad-Eingang gescheitert: \(fehler)")
                    self.melde(bereit: nil)
                }
            default:
                break
            }
        }
        l.newConnectionHandler = { [weak self] netz in self?.annehmen(netz) }
        listener = l
        l.start(queue: queue)
    }

    private func annehmen(_ netz: NWConnection) {
        let d = Durchreiche(netz: netz, kernelSocket: kernelSocket, queue: queue)
        let schluessel = ObjectIdentifier(d)
        durchreichen[schluessel] = d
        d.onGeraet = { [weak self] kennung, name in
            guard let self else { return }
            self.protokoll("iPad verbunden: \(name ?? kennung)")
            let cb = self.onGeraet
            DispatchQueue.main.async { MainActor.assumeIsolated { cb?(kennung, name) } }
        }
        d.onEnde = { [weak self] grund in
            guard let self else { return }
            self.durchreichen[schluessel] = nil
            if let grund { self.protokoll("iPad getrennt: \(grund)") }
        }
        d.starten()
    }

    private func protokoll(_ zeile: String) {
        let cb = onProtokoll
        DispatchQueue.main.async { MainActor.assumeIsolated { cb?(zeile) } }
    }

    private func melde(bereit port: UInt16?) {
        let cb = onBereit
        DispatchQueue.main.async { MainActor.assumeIsolated { cb?(port) } }
    }
}

/// Eine iPad-Verbindung: TLS-Seite (NWConnection) und Kernel-Seite (Unix-Socket), Bytes in beide Richtungen.
private final class Durchreiche {
    private let netz: NWConnection
    private let kernelSocket: String
    private let queue: DispatchQueue
    private var fd: Int32 = -1
    private var leseQuelle: DispatchSourceRead?
    private var leseQuelleAngehalten = false
    private var unterwegs = 0  // an das iPad geschickte, noch nicht abgenommene Bytes
    private var ersterRahmen: FrameReader? = FrameReader()
    private var beendet = false
    private var puffer = [UInt8](repeating: 0, count: 256 * 1024)

    var onGeraet: ((String, String?) -> Void)?
    var onEnde: ((String?) -> Void)?

    /// Liest der Kernel schneller, als das iPad abnimmt, ruht das Lesen ab hier (und läuft unter der unteren Marke weiter).
    private static let obereMarke = 16 << 20
    private static let untereMarke = 4 << 20

    init(netz: NWConnection, kernelSocket: String, queue: DispatchQueue) {
        self.netz = netz
        self.kernelSocket = kernelSocket
        self.queue = queue
    }

    func starten() {
        netz.stateUpdateHandler = { [weak self] zustand in
            guard let self else { return }
            switch zustand {
            case .ready:
                self.kernelVerbinden()
            case .failed(let fehler):
                self.beenden(NetzKanal.schluesselPasstNicht(fehler) ? "Schlüssel passt nicht (neu koppeln)" : "\(fehler)")
            case .cancelled:
                self.beenden(nil)
            default:
                break
            }
        }
        netz.start(queue: queue)
    }

    func schliessen() { beenden(nil) }

    private func kernelVerbinden() {
        let s = socket(AF_UNIX, SOCK_STREAM, 0)
        guard s >= 0 else { return beenden("kein Socket") }
        var an: Int32 = 1
        setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &an, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(kernelSocket.utf8)
        guard bytes.count < MemoryLayout.size(ofValue: addr.sun_path) else {
            Darwin.close(s)
            return beenden("Socket-Pfad zu lang")
        }
        withUnsafeMutableBytes(of: &addr.sun_path) { roh in
            roh.copyBytes(from: bytes)
            roh[bytes.count] = 0
        }
        addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let rc = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(s, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard rc == 0 else {
            Darwin.close(s)
            return beenden("Kernel nicht erreichbar")
        }
        _ = fcntl(s, F_SETFL, fcntl(s, F_GETFL) | O_NONBLOCK)
        fd = s
        let quelle = DispatchSource.makeReadSource(fileDescriptor: s, queue: queue)
        quelle.setEventHandler { [weak self] in self?.vomKernel() }
        leseQuelle = quelle
        quelle.resume()
        vomIPad()
    }

    // iPad → Kernel: jedes Stück schreiben, dann das nächste annehmen (natürlicher Gegendruck)
    private func vomIPad() {
        netz.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self] daten, _, fertig, fehler in
            guard let self, !self.beendet else { return }
            if let daten, !daten.isEmpty {
                self.erstenRahmenAnsehen(daten)
                if let grund = self.schreibeZumKernel(daten) { return self.beenden(grund) }
            }
            if let fehler { return self.beenden("\(fehler)") }
            if fertig { return self.beenden("iPad hat die Verbindung beendet") }
            self.vomIPad()
        }
    }

    /// HELLO_APP des iPads: Kennung der Kopplung und Name fürs Protokoll und die Geräteliste am Mac.
    private func erstenRahmenAnsehen(_ daten: Data) {
        guard let leser = ersterRahmen else { return }
        guard let rahmen = try? leser.feed(daten), let erster = rahmen.first else {
            if leser.pendingBytes > 1 << 20 { ersterRahmen = nil }  // kein HELLO in den ersten Bytes: nicht weiter suchen
            return
        }
        ersterRahmen = nil
        guard let kopf = try? JSONSerialization.jsonObject(with: erster.header) as? [String: Any],
            kopf["type"] as? String == "HELLO_APP", let geraet = kopf["geraet"] as? [String: Any]
        else { return }
        let kennung = (geraet["kopplung"] as? String) ?? (geraet["id"] as? String) ?? "?"
        onGeraet?(kennung, geraet["name"] as? String)
    }

    private func schreibeZumKernel(_ daten: Data) -> String? {
        guard fd >= 0 else { return "Kernel getrennt" }
        var fehler: String?
        daten.withUnsafeBytes { (roh: UnsafeRawBufferPointer) in
            var off = 0
            while off < roh.count {
                let n = Darwin.write(fd, roh.baseAddress! + off, roh.count - off)
                if n > 0 {
                    off += n
                } else if n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) {
                    var p = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                    if poll(&p, 1, 5000) <= 0 {
                        fehler = "Kernel nimmt nichts an"
                        return
                    }
                } else if n < 0 && errno == EINTR {
                    continue
                } else {
                    fehler = "Schreibfehler zum Kernel"
                    return
                }
            }
        }
        return fehler
    }

    // Kernel → iPad
    private func vomKernel() {
        guard fd >= 0, !beendet else { return }
        while true {
            let n = puffer.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
            if n > 0 {
                let stueck = Data(puffer[0..<n])
                unterwegs += n
                netz.send(content: stueck, completion: .contentProcessed { [weak self] fehler in
                    guard let self else { return }
                    self.unterwegs -= n
                    if let fehler { return self.beenden("\(fehler)") }
                    if self.leseQuelleAngehalten && self.unterwegs < Self.untereMarke {
                        self.leseQuelleAngehalten = false
                        self.leseQuelle?.resume()
                    }
                })
                if unterwegs > Self.obereMarke, !leseQuelleAngehalten {
                    leseQuelleAngehalten = true
                    leseQuelle?.suspend()
                    return
                }
                if n < puffer.count { return }
            } else if n == 0 {
                return beenden("Kernel hat die Verbindung beendet")
            } else {
                let e = errno
                if e == EAGAIN || e == EWOULDBLOCK { return }
                if e == EINTR { continue }
                return beenden("Lesefehler vom Kernel")
            }
        }
    }

    private func beenden(_ grund: String?) {
        guard !beendet else { return }
        beendet = true
        if let q = leseQuelle {
            if leseQuelleAngehalten { q.resume() }  // eine angehaltene Quelle lässt sich nicht freigeben
            q.cancel()
        }
        leseQuelle = nil
        if fd >= 0 {
            Darwin.close(fd)
            fd = -1
        }
        netz.cancel()
        onEnde?(grund)
        onEnde = nil
        onGeraet = nil
    }
}
#endif
