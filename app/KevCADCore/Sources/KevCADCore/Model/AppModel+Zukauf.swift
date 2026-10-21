import Foundation

// Phase 3 (Z-A, additiv): Zukaufteile per Shop-Link, Herstellernummer oder EAN (PLAN-PHASE3-ZUKAUF.md, PROTOCOL.md
// Abschnitt „Phase 3“). Teil des Vertrags zwischen App-Kern und Oberfläche wie AppModel.swift: Der App-Kern füllt die
// Werte (`zukaufStatus`, `downloadOffer`, `zukaufActivity`, `watchedDownloads` in AppModel), die Oberfläche liest sie
// und ruft nur `ZukaufActions`.

/// Letzter bekannter Zustand eines Zukaufteils (aus ZUKAUF_STATUS).
public struct ZukaufStatus: Identifiable, Equatable, Sendable {
    /// Zukaufteil-id
    public var id: String
    /// Anzeigename (aus ZUKAUF_STATUS, dem Katalog oder dem Dialog), sonst die id.
    public var name: String
    public var zustand: ZukaufZustand
    public var text: String?
    public var cadLinks: [CADLink]
    /// Dateiendungen, auf die die Downloads-Beobachtung achtet (klein, ohne Punkt).
    public var erwartet: [String]
    /// Datei, die gerade als CAD übergeben wurde (ZUKAUF_CAD gesendet, Antwort steht aus).
    public var uebergabe: String?
    public var date: Date

    public init(
        id: String, name: String, zustand: ZukaufZustand, text: String? = nil, cadLinks: [CADLink] = [],
        erwartet: [String] = ZukaufStatusMessage.defaultExtensions, uebergabe: String? = nil, date: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.zustand = zustand
        self.text = text
        self.cadLinks = cadLinks
        self.erwartet = erwartet
        self.uebergabe = uebergabe
        self.date = date
    }

    public var isWaiting: Bool { zustand == .wartetAufCAD }
}

/// Neue Datei in Downloads, für die Kevin bestätigen soll, ob sie das CAD eines wartenden Zukaufteils ist.
public struct DownloadOffer: Identifiable, Equatable, Sendable {
    public var id = UUID()
    public var file: URL
    public var size: Int64
    public var date: Date
    /// Wartende Zukaufteile, zu denen die Endung passt (das erste ist der Vorschlag).
    public var candidates: [String]

    public init(file: URL, size: Int64, date: Date, candidates: [String]) {
        self.file = file
        self.size = size
        self.date = date
        self.candidates = candidates
    }

    public var fileName: String { file.lastPathComponent }
}

/// Stand des Dialogs „Zukaufteil hinzufügen …“ (ZUKAUF_NEU).
public enum ZukaufActivity: Equatable, Sendable {
    case idle
    case sending
    /// Der Kernel hat das Teil angenommen (ACK); ZUKAUF_STATUS folgt.
    case accepted(id: String, message: String?)
    case failed(String)
}

/// Aktionen für Zukaufteile. Implementiert vom App-Kern (AppController); die Oberfläche ruft sie über
/// `model.actions as? ZukaufActions` auf (im Demomodus nicht vorhanden).
@MainActor
public protocol ZukaufActions: AnyObject {
    /// ZUKAUF_NEU: `eingabe` wie eingefügt, `felder` Eintrag laut KATALOG.md (von Kevin bestätigt).
    func addZukauf(eingabe: String, felder: Data, ebene: CatalogLevel)
    /// Rückfrage bejaht: `downloadOffer.file` ist das CAD von `teil` (ZUKAUF_CAD).
    func acceptDownload(for teil: String)
    /// Rückfrage verneint: diese Datei nicht wieder anbieten.
    func declineDownload()
    /// Datei selbst gewählt (z. B. über „CAD-Datei wählen …“): ZUKAUF_CAD.
    func assignCAD(file: URL, to teil: String)
    /// Meldung zu einem Zukaufteil ausblenden (Fehler oder „übernommen“).
    func dismissZukaufStatus(_ id: String)
}

extension AppModel {
    /// Zukaufteile, die auf eine CAD-Datei warten (in Reihenfolge der Meldungen).
    public var waitingForCAD: [ZukaufStatus] { zukaufStatus.filter(\.isWaiting) }

    public func zukaufStatus(for id: String) -> ZukaufStatus? { zukaufStatus.first { $0.id == id } }

    public var zukaufActions: ZukaufActions? { actions as? ZukaufActions }
}
