import CoreGraphics
import Foundation

/// Zustand des Dokument-Exports (Strang P6-A2): Vorlagen des Projekts, laufender Export, letztes Ergebnis, Vorschaubilder.
/// Gepflegt vom App-Kern (ExportSteuerung); die Oberfläche liest und ruft `ExportActions`.
@MainActor
public final class ExportStore: ObservableObject {
    /// Inhalt von <projekt>/dokumente/vorlagen.json.
    @Published public internal(set) var vorlagen = ExportVorlagenDatei()
    /// Fehler beim Lesen der Vorlagen (kaputte Datei).
    @Published public internal(set) var vorlagenFehler: String?
    /// Was gerade passiert („Bilder werden gerendert“, „PDF wird geschrieben“), nil = nichts.
    @Published public internal(set) var laeuft: String?
    @Published public internal(set) var letztes: ExportErgebnis?
    @Published public internal(set) var fehler: String?

    /// Vorschaubilder je Teil und Formschlüssel (bleiben über Exporte, solange sich das Teil nicht ändert).
    var bildCache: [String: (digest: Int, bild: CGImage)] = [:]
    var gesamtCache: (signatur: Int, bild: CGImage)?

    public init() {}

    func leeren() {
        vorlagen = ExportVorlagenDatei()
        vorlagenFehler = nil
        laeuft = nil
        letztes = nil
        fehler = nil
        bildCache = [:]
        gesamtCache = nil
    }
}

/// Aktionen des Export-Dialogs und der Berichte, implementiert vom App-Kern (ExportSteuerung).
@MainActor
public protocol ExportActions: AnyObject {
    /// Vorlagen aus <projekt>/dokumente/vorlagen.json lesen (in `model.export.vorlagen`).
    func exportVorlagenLaden()
    /// Vorlage speichern (ersetzt eine gleichnamige) bzw. löschen.
    func exportVorlageSpeichern(_ v: ExportVorlage) throws
    func exportVorlageLoeschen(_ name: String) throws
    /// Das Dokument bauen: holt fehlende Daten (Bauplan, Blätter) und rendert Vorschaubilder. Für Vorschau und Export.
    func exportDokument(_ v: ExportVorlage) async -> ExportDokument
    /// PDF schreiben.
    func exportPDF(_ v: ExportVorlage, nach url: URL) async throws -> ExportErgebnis
    /// Druckdialog öffnen (je Blattformat ein Auftrag, 1:1).
    func exportDrucken(_ v: ExportVorlage) async throws -> ExportErgebnis
}

extension AppModel {
    /// Exportaktionen des App-Kerns (nil im Demomodus).
    public var exportActions: ExportActions? { actions as? ExportActions }
}
