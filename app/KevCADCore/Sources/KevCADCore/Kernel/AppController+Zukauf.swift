import AppKit
import Foundation

// Phase 3 (Z-A): Zukaufteile im App-Kern. ZUKAUF_STATUS pflegt `model.zukaufStatus`; solange ein Teil auf CAD
// wartet, beobachtet die App den Downloads-Ordner, meldet neue CAD-Dateien mit DOWNLOAD_SEEN und fragt Kevin
// („Diese Datei als CAD für … übernehmen?“). Ja schickt ZUKAUF_CAD. Der Dialog „Zukaufteil hinzufügen …“ schickt
// ZUKAUF_NEU. Shop-Seiten lädt die App nie (PLAN-PHASE3-ZUKAUF.md, Z1).

extension AppInfo {
    /// Beobachteter Downloads-Ordner; `KEVCAD_DOWNLOADS_DIR` ersetzt ihn (Tests, Testvariante).
    public static var downloadsDirectory: URL {
        if let path = ProcessInfo.processInfo.environment["KEVCAD_DOWNLOADS_DIR"], !path.isEmpty {
            return URL(fileURLWithPath: (path as NSString).expandingTildeInPath, isDirectory: true)
        }
        return FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads", isDirectory: true)
    }
}

/// Zustand des App-Kerns für Zukaufteile (eigene Klasse, damit AppController nur ein Feld dazubekommt).
@MainActor
final class ZukaufControllerState {
    var watcher: DownloadWatcher?
    /// Beobachteter Ordner in Tests (sonst `AppInfo.downloadsDirectory`).
    var directoryOverride: URL?
    /// Dateien, die so viele Sekunden vor dem Beobachtungsbeginn kamen, zählen noch als neu.
    var lookback: TimeInterval = 120
    /// Weitere Rückfragen hinter `model.downloadOffer`.
    var queuedOffers: [DownloadOffer] = []
    /// Dateien, zu denen Kevin schon Ja oder Nein gesagt hat (Pfad).
    var answered: Set<String> = []
    /// Namen aus dem Dialog je Zukaufteil-id (bis der Katalog sie kennt).
    var names: [String: String] = [:]
    /// „CAD übernommen“ nach so vielen Sekunden wieder ausblenden.
    var importedDisplay: TimeInterval = 8
    var hideWork: [String: DispatchWorkItem] = [:]
    /// Nur in Tests: gesendete Nachrichten mitschreiben.
    var recordSent = false
    var sent: [(type: String, header: JSONValue)] = []
}

extension AppController: ZukaufActions {
    /// Zeitlimit für ZUKAUF_NEU und ZUKAUF_CAD (der Import großer STEP-Dateien kann dauern; die Antwort ist nur das ACK).
    static var zukaufTimeout: TimeInterval = 30

    // MARK: Senden

    private func record<M: OutgoingMessage>(_ message: M) {
        guard zukaufState.recordSent, let data = try? message.encodedHeader(),
              let json = try? JSONDecoder().decode(JSONValue.self, from: data)
        else { return }
        zukaufState.sent.append((M.type, json))
    }

    @discardableResult
    func sendZukauf<M: OutgoingMessage>(_ message: M) -> Bool {
        record(message)
        return send(message)
    }

    func requestZukauf<M: OutgoingRequest>(
        _ message: M, completion: @escaping (Result<KernelMessage, RequestError>) -> Void
    ) {
        record(message)
        request(message, timeout: Self.zukaufTimeout, completion: completion)
    }

    // MARK: ZUKAUF_STATUS

    func applyZukaufStatus(_ msg: ZukaufStatusMessage) {
        guard !msg.id.isEmpty else {
            log(.warning, "ZUKAUF_STATUS ohne id wird ignoriert")
            return
        }
        let previous = model.zukaufStatus(for: msg.id)
        let name = msg.name ?? zukaufState.names[msg.id] ?? model.catalog?.item(msg.id)?.name ?? previous?.name ?? msg.id
        let status = ZukaufStatus(
            id: msg.id, name: name, zustand: msg.zustand, text: msg.text, cadLinks: msg.cadLinks,
            erwartet: msg.erwartet.isEmpty ? ZukaufStatusMessage.defaultExtensions : msg.erwartet)
        if let i = model.zukaufStatus.firstIndex(where: { $0.id == msg.id }) {
            model.zukaufStatus[i] = status
        } else {
            model.zukaufStatus.append(status)
        }
        zukaufState.hideWork.removeValue(forKey: msg.id)?.cancel()
        let detail = msg.text.map { ": \($0)" } ?? ""
        switch msg.zustand {
        case .angelegt:
            log(.info, "Zukaufteil \(name) angelegt\(detail)")
            reloadCatalog()
        case .wartetAufCAD:
            if previous?.zustand != .wartetAufCAD {
                log(.info, "Zukaufteil \(name) wartet auf CAD\(detail)"
                    + (msg.cadLinks.isEmpty ? "" : " (\(KevFormat.count(msg.cadLinks.count, one: "Link", many: "Links")))"))
            }
        case .importiert:
            log(.info, "CAD für \(name) übernommen\(detail)")
            reloadCatalog()
            let id = msg.id
            let work = DispatchWorkItem { [weak self] in
                MainActor.assumeIsolated {
                    guard let self, self.model.zukaufStatus(for: id)?.zustand == .importiert else { return }
                    self.model.zukaufStatus.removeAll { $0.id == id }
                }
            }
            zukaufState.hideWork[id] = work
            DispatchQueue.main.asyncAfter(deadline: .now() + zukaufState.importedDisplay, execute: work)
        case .fehler:
            log(.warning, "Zukaufteil \(name): Fehler\(detail)")
        case .other(let t):
            log(.info, "Zukaufteil \(name): \(t)\(detail)")
        }
        pruneOffers()
        updateDownloadWatching()
    }

    // MARK: Downloads beobachten

    /// Beobachtung an, solange ein Zukaufteil auf CAD wartet; sonst aus.
    func updateDownloadWatching() {
        let waiting = model.waitingForCAD
        guard !waiting.isEmpty, !AppInfo.isDemoMode else {
            stopWatchingDownloads()
            return
        }
        let ext = Set(waiting.flatMap(\.erwartet))
        if let watcher = zukaufState.watcher {
            watcher.setExtensions(ext)
            return
        }
        let dir = zukaufState.directoryOverride ?? AppInfo.downloadsDirectory
        let watcher = DownloadWatcher(directory: dir, extensions: ext, lookback: zukaufState.lookback)
        watcher.onFile = { [weak self] file in self?.downloadSeen(file) }
        zukaufState.watcher = watcher
        model.watchedDownloads = dir
        log(.info, "Beobachte \(KevFormat.abbreviatedPath(dir.path)) auf neue CAD-Dateien ("
            + ext.sorted().map { ".\($0)" }.joined(separator: ", ") + ")")
        watcher.start()
    }

    func stopWatchingDownloads() {
        if let watcher = zukaufState.watcher {
            watcher.stop()
            zukaufState.watcher = nil
            log(.info, "Downloads-Beobachtung beendet")
        }
        if model.watchedDownloads != nil { model.watchedDownloads = nil }
        zukaufState.queuedOffers = []
        if model.downloadOffer != nil { model.downloadOffer = nil }
    }

    /// Neue, fertige Datei mit passender Endung: dem Kernel melden und Kevin fragen.
    func downloadSeen(_ file: DownloadCandidate) {
        guard !zukaufState.answered.contains(file.url.path) else { return }
        sendZukauf(DownloadSeenMessage(pfad: file.url.path, groesse: file.size, zeit: file.date))
        let ext = file.url.pathExtension.lowercased()
        let waiting = model.waitingForCAD
        var candidates = waiting.filter { $0.erwartet.contains(ext) }.map(\.id)
        if candidates.isEmpty { candidates = waiting.map(\.id) }
        guard !candidates.isEmpty else { return }
        log(.info, "Neue Datei in Downloads: \(file.url.lastPathComponent) (\(Self.byteText(file.size)))")
        let offer = DownloadOffer(file: file.url, size: file.size, date: file.date, candidates: candidates)
        if model.downloadOffer == nil {
            model.downloadOffer = offer
            requestAttentionForDownload()
        } else {
            zukaufState.queuedOffers.append(offer)
        }
    }

    private func requestAttentionForDownload() {
        guard Bundle.main.bundleURL.pathExtension == "app", !AppInfo.isTestVariant, !NSApp.isActive else { return }
        NSApp.requestUserAttention(.informationalRequest)
    }

    private func showNextOffer() {
        pruneOffers()
        model.downloadOffer = zukaufState.queuedOffers.isEmpty ? nil : zukaufState.queuedOffers.removeFirst()
    }

    /// Rückfragen nur für Teile, die noch warten.
    private func pruneOffers() {
        let waiting = Set(model.waitingForCAD.map(\.id))
        func pruned(_ o: DownloadOffer) -> DownloadOffer? {
            var o = o
            o.candidates = o.candidates.filter(waiting.contains)
            return o.candidates.isEmpty ? nil : o
        }
        zukaufState.queuedOffers = zukaufState.queuedOffers.compactMap(pruned)
        if let offer = model.downloadOffer {
            let p = pruned(offer)
            if p != offer {
                model.downloadOffer = p ?? (zukaufState.queuedOffers.isEmpty ? nil : zukaufState.queuedOffers.removeFirst())
            }
        }
    }

    /// Projektwechsel: alles zu Zukaufteilen vergessen.
    func resetZukauf() {
        stopWatchingDownloads()
        for (_, work) in zukaufState.hideWork { work.cancel() }
        zukaufState.hideWork = [:]
        zukaufState.answered = []
        if !model.zukaufStatus.isEmpty { model.zukaufStatus = [] }
        if model.zukaufActivity != .idle { model.zukaufActivity = .idle }
    }

    static func byteText(_ size: Int64) -> String {
        let f = ByteCountFormatter()
        f.countStyle = .file
        return f.string(fromByteCount: size)
    }

    // MARK: ZukaufActions

    public func addZukauf(eingabe: String, felder: Data, ebene: CatalogLevel) {
        guard !AppInfo.isDemoMode else { return }
        guard let entry = try? JSONDecoder().decode(JSONValue.self, from: felder), entry.objectValue != nil else {
            model.zukaufActivity = .failed("Die Felder sind kein gültiges JSON-Objekt.")
            return
        }
        guard ebene.isEditable else {
            model.zukaufActivity = .failed("Zukaufteile gehören ins Projekt oder in den eigenen Katalog.")
            return
        }
        guard helloReceived else {
            model.zukaufActivity = .failed("Der Kernel ist nicht verbunden, das Zukaufteil wurde nicht angelegt.")
            return
        }
        let entryID = entry["id"]?.lenientString ?? "?"
        if let name = entry["name"]?.lenientString { zukaufState.names[entryID] = name }
        model.zukaufActivity = .sending
        let msg = ZukaufNewMessage(id: nextRequestID(), eingabe: eingabe, felder: entry, ebene: ebene)
        requestZukauf(msg) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                let note = a.message.flatMap { $0.isEmpty ? nil : $0 }
                self.model.zukaufActivity = .accepted(id: entryID, message: note)
                self.log(.info, "Zukaufteil \(entryID) an den Kernel übergeben (\(ebene.title))" + (note.map { ", \($0)" } ?? ""))
                self.reloadCatalog()
            case .success(.ack(let a)):
                self.zukaufFailed(a.message ?? "Der Kernel hat das Zukaufteil abgelehnt.")
            case .success(let m):
                self.zukaufFailed("Unerwartete Antwort \(m.typeName) auf ZUKAUF_NEU")
            case .failure(let e):
                self.zukaufFailed(e.message.contains("keine Antwort")
                    ? "Der Kernel antwortet nicht. Ältere Kernel-Versionen kennen Zukaufteile noch nicht." : e.message)
            }
        }
    }

    private func zukaufFailed(_ text: String) {
        model.zukaufActivity = .failed(text)
        log(.warning, "Zukaufteil: \(text)")
    }

    public func acceptDownload(for teil: String) {
        guard let offer = model.downloadOffer else { return }
        zukaufState.answered.insert(offer.file.path)
        showNextOffer()
        submitCAD(file: offer.file, teil: teil)
    }

    public func declineDownload() {
        guard let offer = model.downloadOffer else { return }
        zukaufState.answered.insert(offer.file.path)
        log(.info, "\(offer.fileName) nicht als CAD übernommen")
        showNextOffer()
    }

    public func assignCAD(file: URL, to teil: String) {
        zukaufState.answered.insert(file.path)
        if model.downloadOffer?.file == file { showNextOffer() }
        submitCAD(file: file, teil: teil)
    }

    public func dismissZukaufStatus(_ id: String) {
        zukaufState.hideWork.removeValue(forKey: id)?.cancel()
        model.zukaufStatus.removeAll { $0.id == id }
        pruneOffers()
        updateDownloadWatching()
    }

    /// ZUKAUF_CAD schicken; bis ZUKAUF_STATUS kommt, zeigt der Zustand die übergebene Datei.
    private func submitCAD(file: URL, teil: String) {
        let name = model.zukaufStatus(for: teil)?.name ?? model.catalog?.item(teil)?.name ?? zukaufState.names[teil] ?? teil
        guard !AppInfo.isDemoMode else { return }
        guard helloReceived else {
            setZukaufError(teil, name: name, "Der Kernel ist nicht verbunden, die Datei wurde nicht übernommen.")
            return
        }
        if let i = model.zukaufStatus.firstIndex(where: { $0.id == teil }) {
            model.zukaufStatus[i].uebergabe = file.lastPathComponent
        } else {
            model.zukaufStatus.append(ZukaufStatus(id: teil, name: name, zustand: .angelegt, uebergabe: file.lastPathComponent))
        }
        log(.info, "\(file.lastPathComponent) als CAD für \(name) übergeben")
        let msg = ZukaufCADMessage(id: nextRequestID(), teil: teil, pfad: file.path)
        requestZukauf(msg) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                if let note = a.message, !note.isEmpty { self.log(.info, "Kernel: \(note)") }
            case .success(.ack(let a)):
                self.setZukaufError(teil, name: name, a.message ?? "Der Kernel hat die Datei abgelehnt.")
            case .success(let m):
                self.setZukaufError(teil, name: name, "Unerwartete Antwort \(m.typeName) auf ZUKAUF_CAD")
            case .failure(let e):
                self.setZukaufError(teil, name: name, e.message)
            }
        }
    }

    private func setZukaufError(_ teil: String, name: String, _ text: String) {
        log(.warning, "CAD für \(name): \(text)")
        if let i = model.zukaufStatus.firstIndex(where: { $0.id == teil }) {
            // Wartet das Teil noch, bleibt es dabei (Kevin kann eine andere Datei nehmen); die Meldung steht im Text
            model.zukaufStatus[i].uebergabe = nil
            if model.zukaufStatus[i].zustand != .wartetAufCAD { model.zukaufStatus[i].zustand = .fehler }
            model.zukaufStatus[i].text = text
        } else {
            model.zukaufStatus.append(ZukaufStatus(id: teil, name: name, zustand: .fehler, text: text))
        }
    }
}
