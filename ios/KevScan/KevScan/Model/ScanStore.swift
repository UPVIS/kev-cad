import Foundation

/// Ein Scan in der Liste: Ordner `<name>.kevscan/` in den Dokumenten der App.
struct ScanItem: Identifiable, Hashable {
    /// Stabil über Umbenennen hinweg: `id` aus meta.json, sonst der Ordnername.
    let id: String
    var url: URL
    var name: String
    var created: Date
    var sizeBytes: Int64
    var photoCount: Int
    var frameCount: Int
    var duration: Double?
    var hasObject: Bool
    var complete: Bool
    var sent: SentInfo?

    var previewURL: URL { url.appendingPathComponent("vorschau.jpg") }
    var folderName: String { url.lastPathComponent }
}

/// Wohin und wann ein Scan gesendet wurde (nur in der App, nicht Teil des Scans).
struct SentInfo: Codable, Hashable {
    var rechner: String
    var datum: Date
    var ordner: String?
}

enum ScanStoreError: LocalizedError {
    case zip
    case exists

    var errorDescription: String? {
        switch self {
        case .zip: return "Der Scan ließ sich nicht packen."
        case .exists: return "Ein Scan mit diesem Namen existiert schon."
        }
    }
}

final class ScanStore: ObservableObject {
    @Published private(set) var scans: [ScanItem] = []
    @Published private(set) var loaded = false

    let documents: URL
    private let statusURL: URL
    private var status: [String: SentInfo] = [:]

    init() {
        let fm = FileManager.default
        documents = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? fm.createDirectory(at: support, withIntermediateDirectories: true)
        statusURL = support.appendingPathComponent("status.json")
        if let data = try? Data(contentsOf: statusURL) {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            status = (try? decoder.decode([String: SentInfo].self, from: data)) ?? [:]
        }
        reload()
    }

    // MARK: Liste

    func reload() {
        let docs = documents
        let currentStatus = status
        DispatchQueue.global(qos: .userInitiated).async {
            let items = Self.scanDocuments(docs, status: currentStatus)
            DispatchQueue.main.async {
                self.scans = items
                self.loaded = true
            }
        }
    }

    func item(withID id: String) -> ScanItem? { scans.first { $0.id == id } }

    private static func scanDocuments(_ docs: URL, status: [String: SentInfo]) -> [ScanItem] {
        let fm = FileManager.default
        let urls = (try? fm.contentsOfDirectory(at: docs, includingPropertiesForKeys: [.isDirectoryKey, .creationDateKey],
                                                options: [.skipsHiddenFiles])) ?? []
        return urls
            .filter { $0.pathExtension == "kevscan" }
            .map { load($0, status: status) }
            .sorted { $0.created > $1.created }
    }

    private static func load(_ url: URL, status: [String: SentInfo]) -> ScanItem {
        let metaURL = url.appendingPathComponent("meta.json")
        let meta = (try? Data(contentsOf: metaURL)).flatMap { try? JSONDecoder().decode(ScanMetaLite.self, from: $0) }
        let folderName = url.deletingPathExtension().lastPathComponent
        var created = (try? url.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? Date.distantPast
        if let text = meta?.erstellt, let date = JSONFiles.isoFormatter.date(from: text) { created = date }
        let id = meta?.id ?? url.lastPathComponent
        return ScanItem(id: id,
                        url: url,
                        name: meta?.name ?? folderName,
                        created: created,
                        sizeBytes: folderSize(url),
                        photoCount: meta?.fotos?.anzahl ?? 0,
                        frameCount: meta?.video?.bilder ?? 0,
                        duration: meta?.dauer_s,
                        hasObject: meta?.objekt ?? false,
                        complete: meta != nil,
                        sent: status[id])
    }

    static func folderSize(_ url: URL) -> Int64 {
        let keys: [URLResourceKey] = [.totalFileAllocatedSizeKey, .fileSizeKey, .isRegularFileKey]
        guard let walker = FileManager.default.enumerator(at: url, includingPropertiesForKeys: keys) else { return 0 }
        var total: Int64 = 0
        for case let file as URL in walker {
            guard let values = try? file.resourceValues(forKeys: Set(keys)), values.isRegularFile == true else { continue }
            total += Int64(values.totalFileAllocatedSize ?? values.fileSize ?? 0)
        }
        return total
    }

    // MARK: Anlegen, Umbenennen, Löschen

    /// Dateiname ohne Zeichen, die im Dateisystem oder im ZIP stören.
    static func safeFileName(_ name: String) -> String {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let forbidden = CharacterSet(charactersIn: "/\\:?*\"<>|").union(.controlCharacters)
        let cleaned = trimmed.unicodeScalars.map { forbidden.contains($0) ? "-" : String($0) }.joined()
        let result = cleaned.trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        return result.isEmpty ? "Scan" : String(result.prefix(80))
    }

    private func uniqueFolder(for name: String, excluding: URL? = nil) -> URL {
        let base = Self.safeFileName(name)
        var candidate = documents.appendingPathComponent(base + ".kevscan", isDirectory: true)
        var counter = 2
        while FileManager.default.fileExists(atPath: candidate.path), candidate.standardizedFileURL != excluding?.standardizedFileURL {
            candidate = documents.appendingPathComponent("\(base) \(counter).kevscan", isDirectory: true)
            counter += 1
        }
        return candidate
    }

    /// Legt den Ordner für eine neue Aufnahme an.
    func makeScanFolder(named name: String) throws -> URL {
        let url = uniqueFolder(for: name)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    func rename(_ item: ScanItem, to newName: String) throws {
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        let target = uniqueFolder(for: name, excluding: item.url)
        if target.standardizedFileURL != item.url.standardizedFileURL {
            try FileManager.default.moveItem(at: item.url, to: target)
        }
        // Namen in meta.json nachziehen, unbekannte Felder bleiben erhalten.
        let metaURL = target.appendingPathComponent("meta.json")
        if let data = try? Data(contentsOf: metaURL),
           var dict = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dict["name"] = name
            let out = try JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            try out.write(to: metaURL, options: .atomic)
        }
        reload()
    }

    func delete(_ item: ScanItem) {
        try? FileManager.default.removeItem(at: item.url)
        status[item.id] = nil
        saveStatus()
        reload()
    }

    func markSent(_ item: ScanItem, to computer: String, folder: String?) {
        status[item.id] = SentInfo(rechner: computer, datum: Date(), ordner: folder)
        saveStatus()
        reload()
    }

    private func saveStatus() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(status) { try? data.write(to: statusURL, options: .atomic) }
    }

    // MARK: Packen

    /// Packt den Scan als `<name>.kevscan.zip` (oberste Ebene ist der Ordner `<name>.kevscan/`).
    /// Der Aufrufer löscht den zurückgegebenen Ordner `zip-…` nach Gebrauch.
    func makeZip(_ item: ScanItem) async throws -> URL {
        let source = item.url
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let fm = FileManager.default
                let coordinator = NSFileCoordinator()
                var coordinationError: NSError?
                var result: Result<URL, Error> = .failure(ScanStoreError.zip)
                coordinator.coordinate(readingItemAt: source, options: [.forUploading], error: &coordinationError) { zipURL in
                    do {
                        let dir = fm.temporaryDirectory.appendingPathComponent("zip-\(UUID().uuidString)", isDirectory: true)
                        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
                        let target = dir.appendingPathComponent(source.lastPathComponent + ".zip")
                        do {
                            try fm.moveItem(at: zipURL, to: target)
                        } catch {
                            try fm.copyItem(at: zipURL, to: target)
                        }
                        result = .success(target)
                    } catch {
                        result = .failure(error)
                    }
                }
                if let coordinationError {
                    continuation.resume(throwing: coordinationError)
                } else {
                    continuation.resume(with: result)
                }
            }
        }
    }

    /// Entfernt liegengebliebene ZIP-Dateien früherer Läufe.
    static func cleanTemporaryFiles() {
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory
        let entries = (try? fm.contentsOfDirectory(atPath: tmp.path)) ?? []
        for entry in entries where entry.hasPrefix("zip-") {
            try? fm.removeItem(at: tmp.appendingPathComponent(entry))
        }
    }
}
