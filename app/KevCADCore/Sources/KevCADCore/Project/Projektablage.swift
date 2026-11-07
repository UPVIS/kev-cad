import Foundation

/// Wo Projekte liegen (PLAN-IPAD.md, I-7): lokal oder im Ordner „Kev CAD“ in iCloud Drive. Prototyp hinter einem Schalter,
/// Vorgabe aus.
///
/// **Mac:** Der Schalter ist die Datei `projektablage.json` im Datenordner der App (`AppInfo.supportDirectory`), dieselbe,
/// die der Kernel liest (`kernel/src/kevcad_kernel/ablage.py`): `{"ort": "icloud"}` legt neue Projekte in
/// `~/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD` an, `{"ordner": "/pfad"}` in einem eigenen Ordner; ohne Datei
/// gilt `~/Documents/Kev CAD`. Der Kernel arbeitet dort mit gewöhnlichen Dateien und hält seine internen Daten (`.kevcad`)
/// lokal.
///
/// **iPad:** Die App hat keinen eigenen iCloud-Container (keine Berechtigung, keine Änderung an der Signatur). Kevin wählt
/// den Ordner einmal in der Dateien-App aus, die App merkt sich ein Lesezeichen darauf (`PadOrdner`). Der Schalter ist
/// „Projekte aus iCloud (Versuch)“ in den Einstellungen des iPad (Settings.bundle, UserDefaults `KevCAD.ablage.icloud`).
/// Geöffnet wird über den Mac: Das iPad schickt den Pfad mit `~` (`kernelPfad`), der Kernel löst ihn am Mac auf.
public enum Projektablage {
    public enum Ort: String, Codable, Sendable { case lokal, icloud }

    /// Inhalt von `projektablage.json`.
    public struct Schalter: Codable, Equatable, Sendable {
        public var ort: Ort?
        public var ordner: String?
        public init(ort: Ort? = nil, ordner: String? = nil) {
            self.ort = ort
            self.ordner = ordner
        }
    }

    public static let schalterDatei = "projektablage.json"
    /// UserDefaults-Schlüssel des Schalters auf dem iPad (Settings.bundle).
    public static let padSchalterKey = "KevCAD.ablage.icloud"
    /// Teil jedes Pfads in der iCloud, am Mac (`~/Library/Mobile Documents/…`) wie auf dem iPad
    /// (`/private/var/mobile/Library/Mobile Documents/…`).
    public static let iCloudMarke = "/Library/Mobile Documents/"
    /// Unterordner von iCloud Drive für die Projekte.
    public static let ordnerName = "Kev CAD"

    /// iCloud Drive am Mac. Auf dem iPad gibt es keinen festen Pfad, dort zählt der gewählte Ordner.
    public static var iCloudDrive: URL {
        URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
            .appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs", isDirectory: true)
    }

    /// Ordner der Projekte in iCloud Drive am Mac („iCloud Drive › Kev CAD“).
    public static var iCloudOrdner: URL { iCloudDrive.appendingPathComponent(ordnerName, isDirectory: true) }

    /// Bisheriger Ort am Mac.
    public static var lokalerOrdner: URL {
        URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true).appendingPathComponent("Documents/Kev CAD", isDirectory: true)
    }

    // MARK: Schalter am Mac

    public static func schalterLesen(in ordner: URL) -> Schalter {
        guard let daten = try? Data(contentsOf: ordner.appendingPathComponent(schalterDatei)),
              let s = try? JSONDecoder().decode(Schalter.self, from: daten)
        else { return Schalter() }
        return s
    }

    /// Schreibt den Schalter; `.lokal` ohne eigenen Ordner entfernt die Datei (Vorgabe).
    public static func schalterSchreiben(_ s: Schalter, in ordner: URL) throws {
        let datei = ordner.appendingPathComponent(schalterDatei)
        if s.ort != .icloud, (s.ordner ?? "").isEmpty {
            try? FileManager.default.removeItem(at: datei)
            return
        }
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        try enc.encode(s).write(to: datei, options: .atomic)
    }

    /// Projektordner nach Vorrang: Umgebung (`KEVCAD_PROJECTS_DIR`), Schalter, Vorgabe. Ohne Seiteneffekte, für Tests.
    public static func ordner(umgebung: [String: String], schalter: Schalter, vorgabe: URL) -> URL {
        if let eigen = umgebung["KEVCAD_PROJECTS_DIR"], !eigen.isEmpty {
            return URL(fileURLWithPath: (eigen as NSString).expandingTildeInPath, isDirectory: true)
        }
        if let o = schalter.ordner, !o.isEmpty {
            return URL(fileURLWithPath: (o as NSString).expandingTildeInPath, isDirectory: true)
        }
        if schalter.ort == .icloud { return iCloudOrdner }
        return vorgabe
    }

    // MARK: Pfade

    /// Liegt die Adresse in der iCloud (iCloud Drive oder Ordner einer App)?
    public static func inICloud(_ url: URL) -> Bool {
        (url.standardizedFileURL.path + "/").contains(iCloudMarke)
    }

    /// Teil des Pfads hinter „Mobile Documents/“ („com~apple~CloudDocs/Kev CAD/Wandhalter“), sonst nil.
    public static func iCloudRest(_ url: URL) -> String? {
        let pfad = url.standardizedFileURL.path
        guard let r = pfad.range(of: iCloudMarke) else { return nil }
        let rest = String(pfad[r.upperBound...]).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return rest.isEmpty ? nil : rest
    }

    /// Pfad, unter dem der Kernel am Mac den Ordner findet: iCloud-Ordner mit `~` (der Kernel löst ihn am Mac auf,
    /// `project.open_project`); ein Ordner unter `lokalerOrdner` (der Projektordner des iPad ohne iCloud) als bloßer Name,
    /// den der Kernel im Projektordner des Mac anlegt bzw. sucht (`ablage.aufloesen`); alles andere unverändert.
    public static func kernelPfad(_ url: URL, lokalerOrdner: URL? = nil) -> String {
        if let rest = iCloudRest(url) { return "~" + iCloudMarke + rest }
        let pfad = url.standardizedFileURL.path
        if let basis = lokalerOrdner?.standardizedFileURL.path, pfad.hasPrefix(basis + "/") {
            return String(pfad.dropFirst(basis.count + 1))
        }
        return pfad
    }

    /// Wurzel der iCloud auf diesem Gerät („…/Library/Mobile Documents“), abgelesen an einer Adresse darin.
    public static func iCloudWurzel(von url: URL) -> URL? {
        let pfad = url.standardizedFileURL.path
        guard let r = pfad.range(of: iCloudMarke) else { return nil }
        return URL(fileURLWithPath: String(pfad[..<r.upperBound]), isDirectory: true)
    }

    /// Dieselbe iCloud-Datei unter der Wurzel dieses Geräts: ein Pfad vom Mac
    /// („/Users/k/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD/A“) wird auf dem iPad zu „…/mobile/Library/Mobile
    /// Documents/com~apple~CloudDocs/Kev CAD/A“. Nil außerhalb der iCloud oder ohne Wurzel.
    public static func hierAbgelegt(_ url: URL, wurzel: URL?) -> URL? {
        guard let wurzel, let rest = iCloudRest(url) else { return nil }
        return wurzel.appendingPathComponent(rest, isDirectory: true)
    }
}

/// Ein Projekt in der Projektliste (iPad aus der iCloud, auch ohne Mac).
public struct ProjektEintrag: Identifiable, Equatable, Sendable {
    public var url: URL
    public var name: String
    /// Zuletzt geändert (model.py, sonst der Ordner).
    public var geaendert: Date?
    /// model.py liegt auf diesem Gerät (false: nur in der iCloud, wird beim Öffnen geladen).
    public var geladen: Bool
    /// Konfliktkopien („model 2.py“) oder offene Konflikte, die iCloud für model.py meldet.
    public var konflikte: [String]
    /// Vorschaubild, falls das Projekt eins trägt (`vorschau.png` im Projektordner).
    public var vorschau: URL?

    public var id: String { url.standardizedFileURL.path }

    public init(url: URL, name: String, geaendert: Date?, geladen: Bool, konflikte: [String], vorschau: URL? = nil) {
        self.url = url
        self.name = name
        self.geaendert = geaendert
        self.geladen = geladen
        self.konflikte = konflikte
        self.vorschau = vorschau
    }
}

/// Liest die Projekte eines Ordners, ohne Dateien aus der iCloud zu laden (nur Metadaten).
public enum ProjektListe {
    /// Platzhalter, den iCloud für nicht geladene Dateien zeigen kann (`.model.py.icloud`).
    static let platzhalter = "." + ProjectLocator.modelFileName + ".icloud"
    public static let vorschauDatei = "vorschau.png"

    /// Projekte im Ordner, neueste zuerst. Unterordner ohne model.py zählen nicht.
    public static func lesen(_ ordner: URL, fileManager: FileManager = .default) -> [ProjektEintrag] {
        var kinder: [URL] = []
        var fehler: NSError?
        // Koordiniert lesen, damit iCloud den neuesten Stand der Liste liefert; nur Metadaten, nichts wird geladen.
        NSFileCoordinator(filePresenter: nil).coordinate(
            readingItemAt: ordner, options: [.immediatelyAvailableMetadataOnly], error: &fehler
        ) { url in
            kinder = (try? fileManager.contentsOfDirectory(
                at: url, includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
                options: [.skipsHiddenFiles])) ?? []
        }
        return kinder.compactMap { eintrag($0, fileManager: fileManager) }
            .sorted { ($0.geaendert ?? .distantPast) > ($1.geaendert ?? .distantPast) }
    }

    static func eintrag(_ url: URL, fileManager: FileManager) -> ProjektEintrag? {
        guard (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else { return nil }
        let model = url.appendingPathComponent(ProjectLocator.modelFileName)
        let platz = url.appendingPathComponent(platzhalter)
        let hatModel = fileManager.fileExists(atPath: model.path)
        guard hatModel || fileManager.fileExists(atPath: platz.path) else { return nil }
        let werte = try? (hatModel ? model : platz).resourceValues(
            forKeys: [.contentModificationDateKey, .ubiquitousItemDownloadingStatusKey])
        let geladen: Bool
        if !hatModel {
            geladen = false
        } else if let status = werte?.ubiquitousItemDownloadingStatus {
            geladen = status == .current
        } else {
            geladen = true  // nicht in der iCloud
        }
        let namen = (try? fileManager.contentsOfDirectory(atPath: url.path)) ?? []
        var konflikte = konfliktKopien(namen)
        if hatModel, let offen = NSFileVersion.unresolvedConflictVersionsOfItem(at: model), !offen.isEmpty {
            konflikte.append(ProjectLocator.modelFileName)
        }
        let vorschau = url.appendingPathComponent(vorschauDatei)
        return ProjektEintrag(
            url: url, name: url.lastPathComponent,
            geaendert: werte?.contentModificationDate
                ?? (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate,
            geladen: geladen, konflikte: konflikte,
            vorschau: fileManager.fileExists(atPath: vorschau.path) ? vorschau : nil)
    }

    /// Konfliktkopien, wie iCloud sie neben eine Datei legt: „model 2.py“ neben „model.py“, „kevcad 3.json“ neben
    /// „kevcad.json“. Nur Namen, deren Original daneben liegt (sonst ist „Teil 2.py“ ein gewöhnlicher Name).
    public static func konfliktKopien(_ namen: [String]) -> [String] {
        let menge = Set(namen)
        return namen.filter { name in
            let url = URL(fileURLWithPath: name)
            let ext = url.pathExtension
            let stamm = ext.isEmpty ? name : String(name.dropLast(ext.count + 1))
            guard let leer = stamm.lastIndex(of: " "),
                  let nummer = Int(stamm[stamm.index(after: leer)...]), nummer >= 2
            else { return false }
            let original = String(stamm[..<leer]) + (ext.isEmpty ? "" : "." + ext)
            return menge.contains(original)
        }.sorted()
    }
}
