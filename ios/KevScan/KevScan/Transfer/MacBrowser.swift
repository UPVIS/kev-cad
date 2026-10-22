import Foundation
import Network

/// Ein Mac mit laufendem Kev CAD, gefunden per Bonjour `_kevscan._tcp`.
struct MacService: Identifiable, Hashable {
    let name: String
    let endpoint: NWEndpoint
    var id: String { name }
}

/// Antwort von `GET /` (SCAN.md).
struct MacInfo: Decodable {
    var dienst: String?
    var version: Int?
    var rechner: String?
    var projekt: String?
}

enum TransferError: LocalizedError {
    case resolve
    case timeout
    case server(String)

    var errorDescription: String? {
        switch self {
        case .resolve: return "Die Adresse des Macs ließ sich nicht ermitteln."
        case .timeout: return "Der Mac antwortet nicht. Läuft Kev CAD, und sind beide im selben WLAN?"
        case .server(let text): return text
        }
    }
}

final class MacBrowser: ObservableObject {
    static let serviceType = "_kevscan._tcp"

    @Published private(set) var services: [MacService] = []
    @Published private(set) var problem: String?
    @Published private(set) var searching = false

    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        let browser = NWBrowser(for: .bonjour(type: Self.serviceType, domain: nil), using: parameters)
        browser.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async {
                guard let self else { return }
                switch state {
                case .ready:
                    self.problem = nil
                    self.searching = true
                case .waiting(let error):
                    self.problem = "Suche wartet: \(error.localizedDescription). Erlaube Kev Scan den Zugriff unter Einstellungen > Datenschutz > Lokales Netzwerk."
                case .failed(let error):
                    self.problem = "Suche gescheitert: \(error.localizedDescription)"
                    self.searching = false
                case .cancelled:
                    self.searching = false
                default:
                    break
                }
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            var seen = Set<String>()
            let list = results
                .compactMap { result -> MacService? in
                    if case let .service(name, _, _, _) = result.endpoint {
                        return MacService(name: name, endpoint: result.endpoint)
                    }
                    return nil
                }
                .filter { seen.insert($0.name).inserted }
                .sorted { $0.name.localizedCompare($1.name) == .orderedAscending }
            DispatchQueue.main.async { self?.services = list }
        }
        browser.start(queue: .main)
        self.browser = browser
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }

    // MARK: Auflösen

    /// Ermittelt `http://<ip>:<port>` eines Dienstes. Erst IPv4, dann jede Adresse.
    static func resolve(_ endpoint: NWEndpoint) async throws -> URL {
        do {
            return try await resolve(endpoint, ipv4Only: true)
        } catch {
            return try await resolve(endpoint, ipv4Only: false)
        }
    }

    private static func resolve(_ endpoint: NWEndpoint, ipv4Only: Bool) async throws -> URL {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<URL, Error>) in
            let parameters = NWParameters.tcp
            if ipv4Only, let ip = parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options {
                ip.version = .v4
            }
            let connection = NWConnection(to: endpoint, using: parameters)
            let once = Once()
            let finish: (Result<URL, Error>) -> Void = { result in
                guard once.claim() else { return }
                connection.cancel()
                continuation.resume(with: result)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    if let remote = connection.currentPath?.remoteEndpoint,
                       case let .hostPort(host, port) = remote,
                       let url = makeURL(host: host, port: port) {
                        finish(.success(url))
                    } else {
                        finish(.failure(TransferError.resolve))
                    }
                case .failed(let error):
                    finish(.failure(error))
                default:
                    break
                }
            }
            connection.start(queue: .global(qos: .userInitiated))
            DispatchQueue.global().asyncAfter(deadline: .now() + 6) {
                finish(.failure(TransferError.timeout))
            }
        }
    }

    static func makeURL(host: NWEndpoint.Host, port: NWEndpoint.Port) -> URL? {
        let hostText: String
        switch host {
        case .ipv4(let address):
            let text = "\(address)"
            hostText = text.split(separator: "%").first.map(String.init) ?? text
        case .ipv6(let address):
            hostText = "[" + "\(address)".replacingOccurrences(of: "%", with: "%25") + "]"
        case .name(let name, _):
            hostText = name
        @unknown default:
            return nil
        }
        return URL(string: "http://\(hostText):\(port.rawValue)")
    }

    /// `GET /`: Rechnername und offenes Projekt.
    static func info(_ base: URL) async throws -> MacInfo {
        var request = URLRequest(url: base)
        request.timeoutInterval = 5
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(MacInfo.self, from: data)
    }
}

/// Lässt genau einen Aufruf durch (Zustandsmeldungen und Frist konkurrieren).
private final class Once {
    private let lock = NSLock()
    private var done = false

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if done { return false }
        done = true
        return true
    }
}
