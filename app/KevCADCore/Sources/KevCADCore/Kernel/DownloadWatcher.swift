import Foundation

/// Eine fertig heruntergeladene Datei.
public struct DownloadCandidate: Equatable, Sendable {
    public var url: URL
    public var size: Int64
    /// Wann die Datei in den Ordner kam (Datum „Hinzugefügt“ bzw. Änderungsdatum, das spätere).
    public var date: Date

    public init(url: URL, size: Int64, date: Date) {
        self.url = url
        self.size = size
        self.date = date
    }
}

/// Erkennt neue Dateien in einem Ordner, ohne Oberfläche und ohne Zeitgeber (testbar mit festem `now`).
///
/// Gemeldet wird eine Datei, wenn sie eine erwartete Endung hat, nach `since` in den Ordner kam, nicht leer ist und ihre
/// Größe über `stableInterval` gleich bleibt (Browser schreiben erst in `.crdownload`, `.download` oder `.part` und
/// benennen am Ende um; diese Endungen passen ohnehin nicht). Jede Datei wird einmal gemeldet; lädt Kevin dieselbe
/// Datei noch einmal, zählt sie wieder als neu.
public struct DownloadScanner: Sendable {
    public let directory: URL
    public var extensions: Set<String>
    public var since: Date
    public var stableInterval: TimeInterval

    private var pending: [String: (size: Int64, seenAt: Date)] = [:]
    private var reported: Set<String> = []

    public init(directory: URL, extensions: Set<String>, since: Date, stableInterval: TimeInterval = 0.8) {
        self.directory = directory
        self.extensions = Set(extensions.map(ZukaufStatusMessage.normalizedExtension))
        self.since = since
        self.stableInterval = stableInterval
    }

    static let keys: [URLResourceKey] = [
        .isRegularFileKey, .fileSizeKey, .contentModificationDateKey, .addedToDirectoryDateKey, .isHiddenKey,
    ]

    /// Ordner einlesen; Rückgabe: jetzt fertige, noch nicht gemeldete Dateien (älteste zuerst).
    public mutating func scan(now: Date = Date()) -> [DownloadCandidate] {
        let fm = FileManager.default
        guard let urls = try? fm.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: Self.keys, options: [.skipsHiddenFiles, .skipsPackageDescendants])
        else { return [] }
        var ready: [DownloadCandidate] = []
        var present = Set<String>()
        for found in urls {
            // Pfad so, wie der Ordner angegeben ist (nicht aufgelöst, z. B. /var statt /private/var)
            let url = directory.appendingPathComponent(found.lastPathComponent)
            guard extensions.contains(url.pathExtension.lowercased()),
                  let v = try? found.resourceValues(forKeys: Set(Self.keys)), v.isRegularFile == true, v.isHidden != true
            else { continue }
            let size = Int64(v.fileSize ?? 0)
            let date = [v.addedToDirectoryDate, v.contentModificationDate].compactMap { $0 }.max() ?? now
            guard size > 0, date >= since else { continue }
            let key = "\(url.lastPathComponent)|\(size)|\(Int(date.timeIntervalSince1970))"
            present.insert(url.lastPathComponent)
            guard !reported.contains(key) else { continue }
            if let p = pending[url.lastPathComponent], p.size == size {
                if now.timeIntervalSince(p.seenAt) >= stableInterval {
                    reported.insert(key)
                    pending.removeValue(forKey: url.lastPathComponent)
                    ready.append(DownloadCandidate(url: url, size: size, date: date))
                }
            } else {
                pending[url.lastPathComponent] = (size, now)
            }
        }
        // Verschwundene Dateien vergessen (z. B. wieder gelöscht)
        pending = pending.filter { present.contains($0.key) }
        return ready.sorted { $0.date < $1.date }
    }

    /// Noch nicht fertige Dateien (Größe ändert sich noch oder erst einmal gesehen).
    public var pendingCount: Int { pending.count }
}

/// Beobachtet einen Ordner (DispatchSource auf das Verzeichnis, dazu jede Sekunde ein Blick als Rückfall und für die
/// Größenprüfung) und meldet fertige neue Dateien auf dem Hauptthread. Läuft nur zwischen `start()` und `stop()`;
/// vor dem Freigeben immer `stop()` rufen.
@MainActor
public final class DownloadWatcher {
    public let directory: URL
    public var onFile: ((DownloadCandidate) -> Void)?
    private var scanner: DownloadScanner
    private var source: DispatchSourceFileSystemObject?
    private var timer: Timer?
    private var fd: Int32 = -1

    /// `lookback`: Dateien, die so viele Sekunden vor dem Start kamen, zählen auch als neu (Kevin lädt oft schon,
    /// bevor der Kernel „wartet auf CAD“ meldet).
    public init(directory: URL, extensions: Set<String>, lookback: TimeInterval = 120, now: Date = Date()) {
        self.directory = directory
        scanner = DownloadScanner(directory: directory, extensions: extensions, since: now.addingTimeInterval(-lookback))
    }

    public var extensions: Set<String> { scanner.extensions }
    public var isRunning: Bool { timer != nil }

    public func setExtensions(_ ext: Set<String>) {
        scanner.extensions = Set(ext.map(ZukaufStatusMessage.normalizedExtension))
    }

    public func start() {
        guard timer == nil else { return }
        fd = open(directory.path, O_EVTONLY)
        if fd >= 0 {
            let src = DispatchSource.makeFileSystemObjectSource(
                fileDescriptor: fd, eventMask: [.write, .rename, .extend, .attrib], queue: .main)
            src.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.scan() } }
            let descriptor = fd
            src.setCancelHandler { close(descriptor) }
            src.resume()
            source = src
        }
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.scan() }
        }
        scan()
    }

    public func stop() {
        timer?.invalidate()
        timer = nil
        source?.cancel()
        source = nil
        fd = -1
    }

    public func scan(now: Date = Date()) {
        for file in scanner.scan(now: now) { onFile?(file) }
    }
}
