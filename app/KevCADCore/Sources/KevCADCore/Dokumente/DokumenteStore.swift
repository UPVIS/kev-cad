import Foundation

/// Blätter des offenen Projekts (DOKUMENTE.md): Übersicht aus DOCS, gerechnete Blätter aus DRAWING, laufende Anfragen.
/// Gepflegt vom App-Kern (AppController+Dokumente); die Oberfläche liest nur und ruft `DokumenteActions`.
@MainActor
public final class DokumenteStore: ObservableObject {
    /// Letzte Übersicht (DOCS); nil, bis der Kernel sie geschickt hat.
    @Published public internal(set) var uebersicht: DocsUebersicht?
    /// Gerechnete Blätter nach Kennung (letztes DRAWING je Blatt).
    @Published public internal(set) var zeichnungen: [String: Zeichnung] = [:]
    /// Blätter, deren DRAWING gerade angefordert ist.
    @Published public internal(set) var laedt: Set<String> = []
    /// DOCS_REQ läuft (alle Blätter werden gerechnet).
    @Published public internal(set) var uebersichtLaedt = false
    /// DRAWING_CREATE läuft (Blätter werden angelegt).
    @Published public internal(set) var erzeugt = false
    /// Fehler beim Laden eines Blatts (Text des Kernels).
    @Published public internal(set) var fehler: [String: String] = [:]
    /// Änderungen, die gerade beim Kernel liegen (Blatt → Bezeichnung), für die Anzeige „wird geändert …“.
    @Published public internal(set) var bearbeitung: [String: String] = [:]
    /// Ergebnis der letzten Aktion (Bestätigung oder Fehler) für die Leiste.
    @Published public internal(set) var meldung: DokumenteMeldung?

    /// Zeitpunkt der Anfrage je Blatt (Messwert „Zeit bis zur ersten Darstellung“).
    public internal(set) var angefordert: [String: Date] = [:]
    /// Rechenzeit der letzten Antwort je Blatt in ms (Anfrage bis DRAWING).
    public internal(set) var antwortMs: [String: Double] = [:]

    public init() {}

    public func zeichnung(_ id: String) -> Zeichnung? { zeichnungen[id] }

    /// Das gezeigte Blatt passt nicht mehr zur Übersicht (neuer Lauf): es wird neu angefordert.
    public func istVeraltet(_ id: String) -> Bool {
        guard let z = zeichnungen[id], let e = uebersicht?.blatt(id), let s = e.stand else { return false }
        return !s.isEmpty && s != z.stand
    }

    /// Projektwechsel: alles verwerfen.
    func leeren() {
        uebersicht = nil
        zeichnungen = [:]
        laedt = []
        uebersichtLaedt = false
        erzeugt = false
        fehler = [:]
        bearbeitung = [:]
        meldung = nil
        angefordert = [:]
        antwortMs = [:]
    }
}

public struct DokumenteMeldung: Equatable, Sendable {
    public var text: String
    public var fehler: Bool
    public var zeit: Date

    public init(text: String, fehler: Bool = false, zeit: Date = Date()) {
        self.text = text
        self.fehler = fehler
        self.zeit = zeit
    }
}

/// Aktionen des Bereichs „Dokumente“, implementiert vom App-Kern (AppController+Dokumente).
@MainActor
public protocol DokumenteActions: AnyObject {
    /// DOCS_REQ: alle Blätter rechnen und die Übersicht schicken lassen.
    func dokumenteAnfordern()
    /// DRAWING_REQ: ein Blatt anfordern (das alte bleibt bis zur Antwort sichtbar).
    func zeichnungAnfordern(_ blatt: String)
    /// DRAWING_CREATE (Vertrag 1.2): Blätter anlegen, ohne `teile` für alle gefertigten Teile und den Zusammenbau. Die neue
    /// Übersicht kommt danach als DOCS.
    func zeichnungenErzeugen(teile: [String]?, art: String, format: String?)
    /// DRAWING_EDIT mit `von: "kevin"`. `abschluss` bekommt das ACK (Ergebnisse je Operation); das neue Blatt kommt
    /// danach als DRAWING und landet im Store.
    func zeichnungBearbeiten(_ blatt: String, ops: [ZeichnungsOp],
                             abschluss: (@MainActor (ZeichnungsBearbeitung) -> Void)?)
}

extension AppModel {
    /// Zeichnungsaktionen des App-Kerns (nil im Demomodus).
    public var dokumenteActions: DokumenteActions? { actions as? DokumenteActions }
}
