import AppKit
import KevCADCore
import SwiftUI

/// Bereich des Projektfensters: 3D-Modell oder Dokumente (Zeichnungen, Bauplan, Berichte).
enum ProjektBereich: String {
    case modell, dokumente
}

/// Was die Seitenleiste des Bereichs Dokumente gerade zeigt.
enum DokumentAuswahl: Hashable {
    case blatt(String)
    case bauplan
    case berichte

    var zeile: String {
        switch self {
        case .blatt(let id): return "blatt:" + id
        case .bauplan: return "bauplan"
        case .berichte: return "berichte"
        }
    }

    init?(zeile: String) {
        if zeile == "bauplan" {
            self = .bauplan
        } else if zeile == "berichte" {
            self = .berichte
        } else if zeile.hasPrefix("blatt:") {
            self = .blatt(String(zeile.dropFirst(6)))
        } else {
            return nil
        }
    }
}

/// Werkzeug auf dem Blatt.
enum BlattWerkzeug: Equatable {
    case auswahl
    /// Neues Maß: zwei Elemente anklicken, dann die Maßlinie platzieren (Doppelklick: Maß an einem Element).
    case mass
    /// Notiz: klicken (ohne Zeiger) oder vom Ziel zur Textlage ziehen (mit Zeiger).
    case notiz
    /// Ansicht dieser Art an der Klickstelle hinzufügen.
    case ansicht(String)
    /// Schnitt: Schnittlinie durch eine Ansicht ziehen oder mit zwei Klicks setzen.
    case schnitt
    /// Einzelheit: Kreis um die Stelle aufziehen (Mitte, dann Radius).
    case einzelheit

    var titel: String {
        switch self {
        case .auswahl: return "Auswählen"
        case .mass: return "Maß"
        case .notiz: return "Notiz"
        case .ansicht(let art): return ZeichnungText.ansichtArt(art)
        case .schnitt: return "Schnitt"
        case .einzelheit: return "Einzelheit"
        }
    }
}

/// Befehl an die Blattansicht (Menü, Werkzeugleiste); `id` macht jeden Aufruf eindeutig.
struct BlattBefehl: Equatable {
    enum Art: Equatable {
        case einpassen, originalgroesse, vergroessern, verkleinern
    }

    var art: Art
    var id = UUID()
}

/// Auswahl auf dem Blatt.
enum BlattElement: Equatable {
    case mass(String)
    case ansicht(String)
    case notiz(String)
}

/// Eingabe eines Textes in einer Sprechblase über dem Blatt (Notiz, Maßtext, Schriftfeld).
struct BlattTextEingabe: Identifiable, Equatable {
    enum Zweck: Equatable {
        case notiz(lage: CGPoint, zeiger: ZeichnungsKlick?)
        case massText(id: String)
        case schriftfeld(feld: String)
    }

    let id = UUID()
    var zweck: Zweck
    var titel: String
    var text: String
    var toleranz: String = ""
    /// Ort der Sprechblase (Blatt-mm).
    var ort: CGPoint
}

/// Zustand des Bereichs Dokumente je Projektfenster (nur Oberfläche). Über `focusedSceneObject` erreichen ihn auch die
/// Menübefehle.
@MainActor
final class DokumenteZustand: ObservableObject {
    @Published var auswahl: DokumentAuswahl?
    /// Mehrfachauswahl in der Seitenleiste (Zeilen-Kennungen, siehe `DokumentAuswahl.zeile`), z. B. für ein PDF mehrerer Blätter.
    @Published var markiert: Set<String> = []
    @Published var werkzeug: BlattWerkzeug = .auswahl
    @Published var element: BlattElement?
    @Published var befehl: BlattBefehl?
    /// Bestätigung vor dem Löschen einer Ansicht (ihre Maße fallen mit weg, nicht rückgängig).
    @Published var ansichtLoeschen: String?
    /// Zeitpunkt, zu dem Kevin ein Blatt gewählt hat (Messwert „Zeit bis zur ersten Darstellung“).
    var gewaehltUm: (blatt: String, zeit: Date)?

    /// Laufend wechselnde Anzeige (Zoom, Zeiger, Hinweis) als eigenes Objekt, damit nur die Statuszeile neu zeichnet.
    let anzeige = BlattAnzeige()
    let bearbeiter = BlattBearbeiter()
    /// PDF und Druck des gezeigten bzw. der markierten Blätter (gesetzt vom Bereich Dokumente).
    var pdfSichern: (() -> Void)?
    var drucken: (() -> Void)?
    /// Teile im 3D-Bereich zeigen (gesetzt vom Projektfenster).
    var zeigeIm3D: (([String]) -> Void)?
    /// Meldung der Oberfläche (PDF gesichert, Rückgängig nicht möglich …).
    @Published var meldung: DokumenteMeldung?
    /// Nach „Zeichnung anlegen“ im Teilebaum: das neue Blatt dieser Teile wählen, sobald es in der Übersicht steht.
    var wunschTeile: [String]?

    func waehle(_ a: DokumentAuswahl) {
        guard auswahl != a else { return }
        auswahl = a
        element = nil
        massKlickZuruecksetzen()
        if case .blatt(let id) = a { gewaehltUm = (id, Date()) }
        if !markiert.contains(a.zeile) { markiert = [a.zeile] }
    }

    private func massKlickZuruecksetzen() {
        if werkzeug != .auswahl { werkzeug = .auswahl }
    }

    func melde(_ text: String, fehler: Bool = false) {
        meldung = DokumenteMeldung(text: text, fehler: fehler)
    }

    var blattID: String? {
        if case .blatt(let id) = auswahl { return id }
        return nil
    }

    /// Blätter der Mehrfachauswahl (oder das gezeigte Blatt), in der Reihenfolge der Übersicht.
    func markierteBlaetter(_ store: DokumenteStore) -> [String] {
        let ids = Set(markiert.compactMap { DokumentAuswahl(zeile: $0) }.compactMap { a -> String? in
            if case .blatt(let id) = a { return id }
            return nil
        })
        let reihenfolge = store.uebersicht?.blaetter.map(\.id) ?? []
        let liste = reihenfolge.filter { ids.contains($0) }
        if liste.count > 1 { return liste }
        return blattID.map { [$0] } ?? liste
    }

    func ausfuehren(_ b: BlattBefehl.Art) {
        befehl = BlattBefehl(art: b)
    }

    func setzeWerkzeug(_ w: BlattWerkzeug) {
        werkzeug = w
        if w != .auswahl { element = nil }
    }

    // MARK: Gemerkte Auswahl je Projekt

    private static func schluessel(_ projekt: URL) -> String { "dokumente.auswahl." + projekt.path }

    func merke(_ projekt: URL?) {
        guard let projekt, let a = auswahl else { return }
        UserDefaults.standard.set(a.zeile, forKey: Self.schluessel(projekt))
    }

    func gemerkt(_ projekt: URL?) -> DokumentAuswahl? {
        guard let projekt, let z = UserDefaults.standard.string(forKey: Self.schluessel(projekt)) else { return nil }
        return DokumentAuswahl(zeile: z)
    }
}

/// Zoom, Zeigerlage und Werkzeughinweis der Blattansicht (für die Statuszeile).
@MainActor
final class BlattAnzeige: ObservableObject {
    @Published var zoomProzent: Int = 100
    @Published var zeiger: CGPoint?
    @Published var hinweis: String?
}

/// Führt Zeichnungsänderungen aus und führt die Rückgängig-Liste des Bereichs Dokumente (⌘Z, ⇧⌘Z über die Blattansicht).
///
/// Der Kernel kennt kein Rückgängig: Zu jeder Änderung rechnet die App nach dem ACK die Gegenoperationen
/// (`ZeichnungsUmkehr`). Rückgängig schickt sie als neue Änderung, deren Gegenoperationen wiederum Wiederholen sind. Was
/// sich so nicht umkehren lässt (Ansicht löschen, Automatik zurücksetzen), meldet das und verweist auf die Versionen.
/// Eine eigene Liste statt des UndoManagers des Fensters: dessen automatische Gruppen fassen Änderungen, die ohne
/// Ereignis entstehen (Antworten des Kernels, Zeitgeber), zu einem Schritt zusammen.
@MainActor
final class BlattBearbeiter: ObservableObject {
    final class Schritt {
        let blatt: String
        let titel: String
        var gegen: [ZeichnungsOp]?
        var fertig = false

        init(blatt: String, titel: String) {
            self.blatt = blatt
            self.titel = titel
        }
    }

    enum Richtung { case neu, rueckgaengig, wiederholen }

    weak var model: AppModel?
    /// Bereich Dokumente mit diesem Blatt zeigen.
    var zeige: (String) -> Void = { _ in }
    /// Meldung in der Blattansicht.
    var melde: (String) -> Void = { _ in }

    @Published private(set) var rueckgaengigListe: [Schritt] = []
    @Published private(set) var wiederholenListe: [Schritt] = []
    static let maxSchritte = 100

    var rueckgaengigTitel: String? { rueckgaengigListe.last?.titel }
    var wiederholenTitel: String? { wiederholenListe.last?.titel }

    /// Projektwechsel: Listen leeren.
    func vergessen() {
        rueckgaengigListe = []
        wiederholenListe = []
    }

    func ausfuehren(_ ops: [ZeichnungsOp], blatt: String, titel: String? = nil, richtung: Richtung = .neu,
                    abschluss: (@MainActor (ZeichnungsBearbeitung) -> Void)? = nil) {
        guard let model, let actions = model.dokumenteActions, !ops.isEmpty else { return }
        let name = titel ?? (ops.count == 1 ? ops[0].titel : ops.first(where: { $0.name != "mass_aendern" })?.titel
            ?? "Zeichnung ändern")
        let schritt = Schritt(blatt: blatt, titel: name)
        let vorher = model.dokumente.zeichnung(blatt)
        switch richtung {
        case .neu:
            rueckgaengigListe.append(schritt)
            wiederholenListe = []
        case .wiederholen:
            rueckgaengigListe.append(schritt)
        case .rueckgaengig:
            wiederholenListe.append(schritt)
        }
        if rueckgaengigListe.count > Self.maxSchritte { rueckgaengigListe.removeFirst() }
        actions.zeichnungBearbeiten(blatt, ops: ops) { [weak self] erg in
            schritt.fertig = true
            if let vorher {
                schritt.gegen = ZeichnungsUmkehr.gegen(ops, vorher: vorher, bearbeitung: erg)
            }
            if !erg.ok, erg.ergebnisse.allSatisfy({ !$0.ok }) {
                schritt.gegen = []
                // gescheitert: nichts zum Umkehren, aus der Liste nehmen
                self?.rueckgaengigListe.removeAll { $0 === schritt }
                self?.wiederholenListe.removeAll { $0 === schritt }
            }
            if let f = erg.fehlerText { self?.melde("\(name): \(f)") }
            abschluss?(erg)
        }
    }

    func rueckgaengig() {
        guard let s = rueckgaengigListe.last else { return }
        guard umkehrbar(s) else { return }
        rueckgaengigListe.removeLast()
        zeige(s.blatt)
        ausfuehren(s.gegen ?? [], blatt: s.blatt, titel: s.titel, richtung: .rueckgaengig)
    }

    func wiederholen() {
        guard let s = wiederholenListe.last else { return }
        guard umkehrbar(s) else { return }
        wiederholenListe.removeLast()
        zeige(s.blatt)
        ausfuehren(s.gegen ?? [], blatt: s.blatt, titel: s.titel, richtung: .wiederholen)
    }

    private func umkehrbar(_ s: Schritt) -> Bool {
        guard s.fertig else {
            melde("„\(s.titel)“ läuft noch – gleich noch einmal versuchen")
            return false
        }
        guard let ops = s.gegen, !ops.isEmpty else {
            melde("„\(s.titel)“ lässt sich hier nicht umkehren. Ein früherer Stand liegt in den Versionen (⌥⌘V).")
            rueckgaengigListe.removeAll { $0 === s }
            wiederholenListe.removeAll { $0 === s }
            return false
        }
        return true
    }
}
