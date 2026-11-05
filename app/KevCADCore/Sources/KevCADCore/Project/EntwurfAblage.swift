import CryptoKit
import Foundation

/// Entwürfe: das leere Projekt, mit dem Kev CAD ohne Dialog startet (V2-3, Entscheidung V3; OBERFLAECHE.md, Abschnitt 3).
///
/// Der Kernel braucht einen Projektordner mit `model.py`. Ein Entwurf liegt deshalb unter Application Support der
/// laufenden Variante, nicht in ~/Documents/Kev CAD:
///
/// ```
/// <Application Support>/<Bundle-ID>/Entwürfe/<JJJJ-MM-TT HH.MM.SS>/Neues Projekt/   ← der Projektordner
/// ```
///
/// - Leer heißt: `model.py` ist seit dem Anlegen unverändert (Prüfsumme in `.kevcad/entwurf.json`) und außer dem, was
///   der Kernel selbst anlegt, liegt nichts darin. Leere Entwürfe räumt die App weg (beim Start, beim Wechsel in ein
///   anderes Projekt, beim Beenden). Ohne Marke gilt ein Entwurf nie als leer.
/// - Mit Inhalt bleibt ein Entwurf liegen und steht in der Startübersicht, bis Kevin ihn benennt. Mit dem Namen zieht
///   er nach ~/Documents/Kev CAD (`uebernehmen`). Pfade ändern sich nie von selbst: Der Agent arbeitet mit dem Pfad aus
///   `status` und soll ihn nicht unter den Händen verlieren.
public struct EntwurfAblage: Sendable {
    public static let projektName = ProjectLocator.defaultName
    public static let markeName = "entwurf.json"
    /// Einträge, die der Kernel bzw. macOS in jedem Projekt anlegt und die nichts über den Inhalt sagen.
    static let erlaubteEintraege: Set<String> = [
        "model.py", "kevcad.json", "output", ".kevcad", ".DS_Store", "__pycache__",
    ]

    public let ordner: URL

    public init(ordner: URL) {
        self.ordner = ordner.standardizedFileURL
    }

    /// Ablage der laufenden Variante (Application Support, je Bundle-ID getrennt).
    public static var standard: EntwurfAblage {
        EntwurfAblage(ordner: AppInfo.supportDirectory.appendingPathComponent("Entwürfe", isDirectory: true))
    }

    /// Projektordner für einen neuen Entwurf (existiert noch nicht).
    public func neuerProjektordner(datum: Date = Date()) -> URL {
        let f = DateFormatter()
        f.locale = Locale(identifier: "de_DE")
        f.dateFormat = "yyyy-MM-dd HH.mm.ss"
        var stempel = f.string(from: datum)
        var n = 2
        while FileManager.default.fileExists(atPath: ordner.appendingPathComponent(stempel).path) {
            stempel = f.string(from: datum) + " \(n)"
            n += 1
        }
        return ordner.appendingPathComponent(stempel, isDirectory: true)
            .appendingPathComponent(Self.projektName, isDirectory: true)
    }

    /// Liegt der Projektordner in dieser Ablage?
    public func enthaelt(_ projekt: URL) -> Bool {
        let p = RecentProjects.normalizedPath(projekt)
        let o = RecentProjects.normalizedPath(ordner)
        return p.hasPrefix(o + "/")
    }

    // MARK: Marke

    struct Marke: Codable {
        var erstellt: Date
        var modelSHA256: String

        enum CodingKeys: String, CodingKey {
            case erstellt
            case modelSHA256 = "model_sha256"
        }
    }

    static func marke(_ projekt: URL) -> URL {
        projekt.appendingPathComponent(".kevcad", isDirectory: true).appendingPathComponent(markeName)
    }

    /// Hält fest, wie `model.py` beim Anlegen aussah. Einmal je Entwurf, gleich nach dem Anlegen.
    @discardableResult
    public func merken(_ projekt: URL, datum: Date = Date()) -> Bool {
        guard enthaelt(projekt), let hash = Self.pruefsumme(projekt.appendingPathComponent("model.py")) else {
            return false
        }
        let url = Self.marke(projekt)
        if FileManager.default.fileExists(atPath: url.path) { return true }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        guard let data = try? enc.encode(Marke(erstellt: datum, modelSHA256: hash)) else { return false }
        return (try? data.write(to: url, options: .atomic)) != nil
    }

    public func hatMarke(_ projekt: URL) -> Bool {
        FileManager.default.fileExists(atPath: Self.marke(projekt).path)
    }

    /// Wann der Entwurf angelegt wurde (aus der Marke), sonst nil.
    public func erstellt(_ projekt: URL) -> Date? {
        guard let data = try? Data(contentsOf: Self.marke(projekt)) else { return nil }
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        return (try? dec.decode(Marke.self, from: data))?.erstellt
    }

    // MARK: Leer oder mit Inhalt

    /// Leer: in der Ablage, mit Marke, `model.py` unverändert, nur erlaubte Einträge und keine Datei in `output`.
    public func istLeer(_ projekt: URL) -> Bool {
        let fm = FileManager.default
        guard enthaelt(projekt), let data = try? Data(contentsOf: Self.marke(projekt)),
              let marke = try? JSONDecoder().decode(MarkeOhneDatum.self, from: data),
              let hash = Self.pruefsumme(projekt.appendingPathComponent("model.py")), hash == marke.modelSHA256,
              let eintraege = try? fm.contentsOfDirectory(atPath: projekt.path)
        else { return false }
        guard eintraege.allSatisfy({ Self.erlaubteEintraege.contains($0) }) else { return false }
        return !Self.enthaeltDateien(projekt.appendingPathComponent("output", isDirectory: true))
    }

    private struct MarkeOhneDatum: Decodable {
        var modelSHA256: String
        enum CodingKeys: String, CodingKey { case modelSHA256 = "model_sha256" }
    }

    /// Alle Entwürfe der Ablage (Projektordner), neueste zuerst.
    public func alle() -> [URL] {
        let fm = FileManager.default
        guard let stempel = try? fm.contentsOfDirectory(
            at: ordner, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])
        else { return [] }
        return stempel.sorted { $0.lastPathComponent > $1.lastPathComponent }.compactMap { s in
            guard let inhalt = try? fm.contentsOfDirectory(
                at: s, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])
            else { return nil }
            return inhalt.first { ProjectLocator.isProject($0) }
        }
    }

    /// Entwürfe mit Inhalt (für die Startübersicht).
    public func mitInhalt() -> [URL] { alle().filter { !istLeer($0) } }

    /// Löscht leere Entwürfe (samt Zeitstempel-Ordner), außer den genannten. Gibt die gelöschten Projektordner zurück.
    @discardableResult
    public func aufraeumen(ausser: [URL] = []) -> [URL] {
        let behalten = Set(ausser.map { RecentProjects.normalizedPath($0) })
        var weg: [URL] = []
        for p in alle() where !behalten.contains(RecentProjects.normalizedPath(p)) && istLeer(p) {
            if loeschen(p) { weg.append(p) }
        }
        // Zeitstempel-Ordner ohne Projekt (abgebrochenes Anlegen) ebenfalls weg
        if let stempel = try? FileManager.default.contentsOfDirectory(
            at: ordner, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])
        {
            for s in stempel where Self.istLeererOrdner(s) { try? FileManager.default.removeItem(at: s) }
        }
        return weg
    }

    /// Löscht einen leeren Entwurf samt Zeitstempel-Ordner. Nur innerhalb der Ablage und nur, wenn er leer ist.
    @discardableResult
    public func loeschenWennLeer(_ projekt: URL) -> Bool {
        guard istLeer(projekt) else { return false }
        return loeschen(projekt)
    }

    private func loeschen(_ projekt: URL) -> Bool {
        let stempel = projekt.deletingLastPathComponent()
        guard enthaelt(projekt), RecentProjects.normalizedPath(stempel.deletingLastPathComponent())
            == RecentProjects.normalizedPath(ordner)
        else { return false }
        return (try? FileManager.default.removeItem(at: stempel)) != nil
    }

    // MARK: Benennen

    /// Gibt dem Entwurf einen Namen: Er zieht als `<ziel>/<Name>` (ohne Namenskollision) aus der Ablage, die Marke
    /// fällt weg. Gibt den neuen Projektordner zurück.
    public func uebernehmen(_ projekt: URL, name: String, nach ziel: URL) throws -> URL {
        let fm = FileManager.default
        try fm.createDirectory(at: ziel, withIntermediateDirectories: true)
        let neu = ProjectLocator.uniqueFolder(named: name, in: ziel)
        try fm.moveItem(at: projekt, to: neu)
        try? fm.removeItem(at: Self.marke(neu))
        let stempel = projekt.deletingLastPathComponent()
        if Self.istLeererOrdner(stempel) { try? fm.removeItem(at: stempel) }
        return neu
    }

    /// Benennt einen gewöhnlichen Projektordner um (im selben Elternordner, ohne Namenskollision).
    public static func umbenennen(_ projekt: URL, name: String) throws -> URL {
        let eltern = projekt.deletingLastPathComponent()
        let gewuenscht = ProjectLocator.sanitizedName(name)
        if gewuenscht == projekt.lastPathComponent { return projekt }
        let neu = ProjectLocator.uniqueFolder(named: gewuenscht, in: eltern)
        try FileManager.default.moveItem(at: projekt, to: neu)
        return neu
    }

    // MARK: Hilfen

    static func pruefsumme(_ datei: URL) -> String? {
        guard let data = try? Data(contentsOf: datei) else { return nil }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Enthält der Ordner (rekursiv) eine Datei außer .DS_Store?
    static func enthaeltDateien(_ ordner: URL) -> Bool {
        guard let e = FileManager.default.enumerator(
            at: ordner, includingPropertiesForKeys: [.isRegularFileKey], options: [])
        else { return false }
        for case let url as URL in e where url.lastPathComponent != ".DS_Store" {
            if (try? url.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile == true { return true }
        }
        return false
    }

    static func istLeererOrdner(_ url: URL) -> Bool {
        guard let inhalt = try? FileManager.default.contentsOfDirectory(atPath: url.path) else { return false }
        return inhalt.allSatisfy { $0 == ".DS_Store" }
    }
}
