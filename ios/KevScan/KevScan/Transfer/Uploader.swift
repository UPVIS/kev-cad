import Foundation

/// Antwort von `POST /scan` (SCAN.md).
struct UploadAnswer: Decodable {
    var ok: Bool
    var id: String?
    var ordner: String?
    var fehler: String?
}

/// Lädt das ZIP eines Scans per HTTP POST auf den Mac, mit Fortschritt.
/// Vordergrund-Sitzung; einen kurzen Wechsel in den Hintergrund überbrückt die Aufgabe in SendView.
final class Uploader: NSObject, ObservableObject, URLSessionDataDelegate {
    enum Phase: Equatable {
        case idle
        case packing
        case connecting(String)
        case uploading(String)
        case done(String)
        case failed(String)
    }

    @Published var phase: Phase = .idle
    @Published private(set) var progress: Double = 0
    @Published private(set) var sentBytes: Int64 = 0
    @Published private(set) var totalBytes: Int64 = 0

    private var received = Data()
    private var continuation: CheckedContinuation<UploadAnswer, Error>?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300
        config.timeoutIntervalForResource = 6 * 3600
        config.waitsForConnectivity = false
        return URLSession(configuration: config, delegate: self, delegateQueue: .main)
    }()

    /// Name als Kopfzeile, URL-kodiert (nur ungeschützte Zeichen nach RFC 3986 bleiben stehen).
    static func encodeHeader(_ name: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        return name.addingPercentEncoding(withAllowedCharacters: allowed) ?? "Scan"
    }

    func upload(file: URL, to base: URL, name: String) async throws -> UploadAnswer {
        var request = URLRequest(url: base.appendingPathComponent("scan"))
        request.httpMethod = "POST"
        request.setValue("application/zip", forHTTPHeaderField: "Content-Type")
        request.setValue(Self.encodeHeader(name), forHTTPHeaderField: "X-KevScan-Name")
        let attributes = try? FileManager.default.attributesOfItem(atPath: file.path)
        let size = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.main.async {
                self.received = Data()
                self.totalBytes = size
                self.sentBytes = 0
                self.progress = 0
                self.continuation = continuation
                self.session.uploadTask(with: request, fromFile: file).resume()
            }
        }
    }

    // MARK: URLSession

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        sentBytes = totalBytesSent
        let total = totalBytesExpectedToSend > 0 ? totalBytesExpectedToSend : totalBytes
        if total > 0 { progress = min(1, Double(totalBytesSent) / Double(total)) }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        received.append(data)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let continuation else { return }
        self.continuation = nil
        if let error {
            continuation.resume(throwing: error)
            return
        }
        let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        if let answer = try? JSONDecoder().decode(UploadAnswer.self, from: received) {
            continuation.resume(returning: answer)
        } else if (200..<300).contains(status) {
            continuation.resume(returning: UploadAnswer(ok: true, id: nil, ordner: nil, fehler: nil))
        } else {
            let text = String(data: received, encoding: .utf8) ?? ""
            continuation.resume(throwing: TransferError.server("Der Mac antwortet mit \(status). \(text.prefix(200))"))
        }
    }
}
