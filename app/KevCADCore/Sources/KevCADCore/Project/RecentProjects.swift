import Combine
import Foundation

/// Ein Eintrag der Liste „Zuletzt geöffnet“.
public struct RecentProject: Codable, Equatable, Identifiable, Sendable {
    /// Normalisierter Pfad des Projektordners (ohne Schrägstrich am Ende, Symlinks aufgelöst).
    public var path: String
    public var name: String
    public var lastOpened: Date
    /// Ordner fehlt auf der Platte (wird nicht gespeichert, sondern bei jedem Laden neu geprüft).
    public var isMissing: Bool = false

    public var id: String { path }
    public var url: URL { URL(fileURLWithPath: path, isDirectory: true) }

    public init(path: String, name: String, lastOpened: Date, isMissing: Bool = false) {
        self.path = path
        self.name = name
        self.lastOpened = lastOpened
        self.isMissing = isMissing
    }

    enum CodingKeys: String, CodingKey { case path, name, lastOpened }
}

/// Liste „Zuletzt geöffnet“ in den UserDefaults.
///
/// Je Variante automatisch getrennt: `UserDefaults.standard` gehört zur Bundle-ID, die Testvarianten
/// (`de.upvis.kevcad.test…`) haben also ihre eigene Liste. Höchstens `limit` Einträge, neueste zuerst; derselbe Ordner
/// erscheint nur einmal (auch über Symlinks oder einen Schrägstrich am Ende). Fehlende Ordner bleiben in der Liste und
/// werden markiert, bis sie jemand entfernt.
@MainActor
public final class RecentProjects: ObservableObject {
    public nonisolated static let defaultLimit = 15
    public nonisolated static let defaultsKey = "KevCAD.recentProjects"

    @Published public private(set) var items: [RecentProject] = []

    private let defaults: UserDefaults
    private let key: String
    private let limit: Int
    private let exists: (URL) -> Bool

    public init(
        defaults: UserDefaults = .standard, key: String = RecentProjects.defaultsKey,
        limit: Int = RecentProjects.defaultLimit,
        exists: @escaping (URL) -> Bool = RecentProjects.folderExists
    ) {
        self.defaults = defaults
        self.key = key
        self.limit = max(1, limit)
        self.exists = exists
        load()
    }

    /// Merkt ein geöffnetes Projekt vor (ganz oben). Der Name ist ohne Angabe der Ordnername.
    public func note(_ url: URL, name: String? = nil, date: Date = Date()) {
        let path = Self.normalizedPath(url)
        let entry = RecentProject(
            path: path, name: name ?? URL(fileURLWithPath: path).lastPathComponent, lastOpened: date,
            isMissing: !exists(URL(fileURLWithPath: path, isDirectory: true)))
        items = Self.merge(items, adding: entry, limit: limit)
        save()
    }

    public func remove(_ url: URL) {
        let path = Self.normalizedPath(url)
        items.removeAll { $0.path == path }
        save()
    }

    public func removeMissing() {
        refresh()
        items.removeAll(where: \.isMissing)
        save()
    }

    public func clear() {
        items = []
        save()
    }

    /// Prüft erneut, welche Ordner fehlen (z. B. wenn das Willkommensfenster erscheint).
    public func refresh() {
        let updated = items.map { item -> RecentProject in
            var item = item
            item.isMissing = !exists(item.url)
            return item
        }
        if updated != items { items = updated }
    }

    // MARK: Reine Logik (testbar ohne UserDefaults)

    /// Fügt einen Eintrag oben ein, entfernt ältere Einträge desselben Ordners und kürzt auf `limit`.
    public nonisolated static func merge(_ list: [RecentProject], adding entry: RecentProject, limit: Int)
        -> [RecentProject]
    {
        var result = [entry]
        var seen: Set<String> = [entry.path]
        for item in list where !seen.contains(item.path) {
            seen.insert(item.path)
            result.append(item)
        }
        return Array(result.prefix(max(1, limit)))
    }

    /// Einheitlicher Pfad für den Vergleich: absolut, ohne "..", Symlinks aufgelöst, ohne "/" am Ende.
    public nonisolated static func normalizedPath(_ url: URL) -> String {
        var path = url.standardizedFileURL.resolvingSymlinksInPath().path
        while path.count > 1 && path.hasSuffix("/") { path.removeLast() }
        return path
    }

    public nonisolated static func folderExists(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) && isDirectory.boolValue
    }

    // MARK: Speichern

    private func load() {
        guard let data = defaults.data(forKey: key),
              let decoded = try? JSONDecoder().decode([RecentProject].self, from: data)
        else {
            items = []
            return
        }
        // Alte oder doppelte Einträge zusammenführen, Reihenfolge nach Datum.
        var merged: [RecentProject] = []
        for item in decoded.sorted(by: { $0.lastOpened > $1.lastOpened }) {
            var item = item
            item.path = Self.normalizedPath(item.url)
            guard !merged.contains(where: { $0.path == item.path }) else { continue }
            item.isMissing = !exists(item.url)
            merged.append(item)
        }
        items = Array(merged.prefix(limit))
    }

    private func save() {
        if let data = try? JSONEncoder().encode(items) {
            defaults.set(data, forKey: key)
        }
    }
}
