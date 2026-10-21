import Foundation

/// Prüft Projektordner und findet Namen für neue Projekte. Ohne Oberfläche, damit testbar.
///
/// Ein Kev-CAD-Projekt ist ein Ordner mit `model.py` (PLAN-MVP.md, Abschnitt 10).
public enum ProjectLocator {
    public static let modelFileName = "model.py"

    /// Name für ein neues Projekt, wenn nichts eingegeben ist.
    public static let defaultName = "Neues Projekt"

    public enum Problem: Error, Equatable, LocalizedError, Sendable {
        case notFound(String)
        case notADirectory(String)
        case missingModel(String)

        public var errorDescription: String? {
            switch self {
            case .notFound(let path): return "Der Ordner „\(KevFormat.abbreviatedPath(path))“ existiert nicht mehr."
            case .notADirectory(let path): return "„\(KevFormat.abbreviatedPath(path))“ ist kein Ordner."
            case .missingModel(let path):
                return "Im Ordner „\(KevFormat.abbreviatedPath(path))“ liegt keine model.py. "
                    + "Ein Kev-CAD-Projekt braucht diese Datei."
            }
        }
    }

    /// Wählt jemand statt des Ordners die Datei `model.py`, gilt der Ordner darüber.
    public static func projectFolder(for url: URL) -> URL {
        let url = url.standardizedFileURL
        if url.lastPathComponent == modelFileName { return url.deletingLastPathComponent() }
        return url
    }

    /// Prüft einen Projektordner; `nil` heißt in Ordnung.
    public static func check(_ url: URL, fileManager: FileManager = .default) -> Problem? {
        let folder = projectFolder(for: url)
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: folder.path, isDirectory: &isDirectory) else {
            return .notFound(folder.path)
        }
        guard isDirectory.boolValue else { return .notADirectory(folder.path) }
        let model = folder.appendingPathComponent(modelFileName)
        var modelIsDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: model.path, isDirectory: &modelIsDirectory), !modelIsDirectory.boolValue
        else { return .missingModel(folder.path) }
        return nil
    }

    public static func isProject(_ url: URL, fileManager: FileManager = .default) -> Bool {
        check(url, fileManager: fileManager) == nil
    }

    /// Projektangaben für einen Ordner (Name = Ordnername).
    public static func projectInfo(for url: URL) -> ProjectInfo {
        let folder = projectFolder(for: url)
        return ProjectInfo(
            path: folder, name: folder.lastPathComponent, modelFile: folder.appendingPathComponent(modelFileName))
    }

    /// Macht aus einer Eingabe einen brauchbaren Ordnernamen: ohne „/“ und „:“, ohne Punkt am Anfang,
    /// ohne doppelte Leerzeichen, höchstens 80 Zeichen. Leere Eingabe ergibt `defaultName`.
    public static func sanitizedName(_ raw: String) -> String {
        var name = raw.replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-")
        name = name.components(separatedBy: .controlCharacters).joined()
        name = name.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        while name.hasPrefix(".") { name.removeFirst() }
        name = name.trimmingCharacters(in: .whitespaces)
        if name.count > 80 { name = String(name.prefix(80)).trimmingCharacters(in: .whitespaces) }
        return name.isEmpty ? defaultName : name
    }

    /// Ordner für ein neues Projekt ohne Namenskollision: "Wandhalter", sonst "Wandhalter 2", "Wandhalter 3" …
    public static func uniqueFolder(
        named raw: String, in parent: URL, exists: (URL) -> Bool = { FileManager.default.fileExists(atPath: $0.path) }
    ) -> URL {
        let base = sanitizedName(raw)
        var candidate = parent.appendingPathComponent(base, isDirectory: true)
        var number = 2
        while exists(candidate) {
            candidate = parent.appendingPathComponent("\(base) \(number)", isDirectory: true)
            number += 1
        }
        return candidate
    }
}
