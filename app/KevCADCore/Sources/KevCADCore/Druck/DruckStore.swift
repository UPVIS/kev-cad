import Foundation

/// Zustand der Druckvorschau (DRUCKVORSCHAU.md, Abschnitt „App“), gepflegt vom App-Kern (AppController+Druck); die
/// Oberfläche liest und ruft `DruckActions`. Eine neue Vorschau ersetzt die alte erst, wenn sie da ist (kein Leeren beim
/// Laufbeginn, damit nichts flackert).
@MainActor
public final class DruckStore: ObservableObject {
    /// Letzte Vorschau des Kernels (nil vor dem ersten PRINT_PREVIEW des Projekts).
    @Published public internal(set) var vorschau: Druckvorschau?
    /// Wann sie kam.
    @Published public internal(set) var zeit: Date?
    /// Der Kernel kennt die Druckvorschau nicht (ältere Fassung): Anfrage ohne Antwort oder mit „unbekannt“.
    @Published public internal(set) var nichtUnterstuetzt = false
    /// Was sich beim Wechsel von der Schätzung zu Bambu Studio geändert hat (Hinweis im Panel), bis er geschlossen wird.
    @Published public internal(set) var aenderung: DruckAenderung?
    /// Gruppen bzw. Teile mit gesendeten Einstellungen, für die noch keine neue Vorschau da ist.
    @Published public internal(set) var ausstehend: Set<String> = []
    /// 3MF-Export der Platten.
    @Published public internal(set) var export: DruckExportZustand = .bereit
    /// Letzter Fehler (Einstellungen abgelehnt, Kernel nicht verbunden …), bis zur nächsten Aktion.
    @Published public internal(set) var fehler: String?

    /// Erste Schätzung des laufenden Laufs: Grundlage des Vergleichs, wenn der Slicer fertig ist.
    var schaetzungDesLaufs: Druckvorschau?
    /// Laufende Exportanfrage (für PRINT_EXPORT_RES nach dem ACK).
    var exportID: String?

    public init() {}

    /// Neue Vorschau übernehmen. Gleicher Lauf und jetzt von Bambu Studio: Unterschied zur Schätzung festhalten.
    public func uebernehmen(_ v: Druckvorschau, jetzt: Date = Date()) {
        let alt = vorschau
        if alt?.run != v.run {
            schaetzungDesLaufs = v.stand == .slicer ? nil : v
            if aenderung?.run != v.run { aenderung = nil }
        } else if schaetzungDesLaufs == nil && v.stand != .slicer {
            // gleicher Lauf, neue Schätzung (etwa nach geänderten Einstellungen): neuer Vergleich
            schaetzungDesLaufs = v
        }
        if v.stand == .slicer, let s = schaetzungDesLaufs, s.run == v.run {
            aenderung = DruckAenderung.vergleiche(s, v)
            schaetzungDesLaufs = nil
        }
        vorschau = v
        zeit = jetzt
        nichtUnterstuetzt = false
        ausstehend = []
    }

    /// Projektwechsel: alles des alten Projekts verwerfen.
    public func leeren() {
        vorschau = nil
        zeit = nil
        aenderung = nil
        ausstehend = []
        export = .bereit
        fehler = nil
        schaetzungDesLaufs = nil
        exportID = nil
    }

    func setzeNichtUnterstuetzt(_ an: Bool) { nichtUnterstuetzt = an }
    func setzeFehler(_ text: String?) { fehler = text }
    func setzeExport(_ z: DruckExportZustand) { export = z }
    func markiere(_ ziel: DruckZiel) { ausstehend.insert(ziel.schluessel) }
    func entmarkiere(_ ziel: DruckZiel) { ausstehend.remove(ziel.schluessel) }

    public func aenderungVerwerfen() { aenderung = nil }
    public func fehlerVerwerfen() { fehler = nil }

    public func exportHinweisVerwerfen() {
        if case .laeuft = export { return }
        export = .bereit
    }

    /// Steht für diese Gruppe noch eine Antwort auf Einstellungen aus?
    public func wartet(_ ziel: DruckZiel) -> Bool { ausstehend.contains(ziel.schluessel) }

    /// Bambu Studio im Programme-Ordner (für „In Bambu Studio öffnen“).
    public static var bambuStudio: URL? {
        let url = URL(fileURLWithPath: "/Applications/BambuStudio.app", isDirectory: true)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }
}

/// 3MF-Export der Platten.
public enum DruckExportZustand: Equatable, Sendable {
    case bereit
    case laeuft(ziel: URL?)
    case fertig(DruckExportErgebnis)
    case fehler(String)
}

/// Was sich beim Wechsel von der schnellen Schätzung zu Bambu Studio geändert hat.
public struct DruckAenderung: Equatable, Sendable, Identifiable {
    public struct Wert: Equatable, Sendable {
        public var titel: String
        public var alt: Double
        public var neu: Double
        public var altText: String
        public var neuText: String

        /// Relative Änderung (neu − alt) / alt; nil bei alt = 0.
        public var relativ: Double? { alt != 0 ? (neu - alt) / alt : nil }

        /// „Druckzeit 5 h 30 min → 6 h 8 min (+12 %)“
        public var zeile: String {
            "\(titel) \(altText) → \(neuText)" + (relativ.map { " (\(DruckFormat.aenderung($0)))" } ?? "")
        }
    }

    public var id: String { "\(run)" }
    public var run: Int
    public var werte: [Wert]
    /// Teile mit der größten Änderung der Druckzeit (Name, relative Änderung), höchstens drei.
    public var teile: [(name: String, relativ: Double)]

    public static func == (a: DruckAenderung, b: DruckAenderung) -> Bool {
        a.run == b.run && a.werte == b.werte && a.teile.map(\.name) == b.teile.map(\.name)
            && a.teile.map(\.relativ) == b.teile.map(\.relativ)
    }

    public var titel: String { "Bambu Studio hat nachgerechnet" }

    /// Größte relative Änderung (Betrag) über Zeit, Filament und Kosten.
    public var groesste: Double { werte.compactMap(\.relativ).map(abs).max() ?? 0 }

    /// „Schätzung lag gut“ (unter 5 %), „etwas daneben“ (unter 15 %), sonst „deutlich daneben“.
    public var urteil: String {
        let g = groesste
        if g < 0.05 { return "Die Schätzung lag gut" }
        if g < 0.15 { return "Die Schätzung lag etwas daneben" }
        return "Die Schätzung lag deutlich daneben"
    }

    /// Eine Zeile für die Kopfzeile: „Druckzeit +12 %, Filament +3 %, Kosten +4 %“.
    public var kurz: String {
        werte.compactMap { w in w.relativ.map { "\(w.titel) \(DruckFormat.aenderung($0))" } }.joined(separator: ", ")
    }

    public static func vergleiche(_ alt: Druckvorschau, _ neu: Druckvorschau) -> DruckAenderung {
        var werte: [Wert] = []
        werte.append(Wert(titel: "Druckzeit", alt: alt.summe.zeitMitWechselS, neu: neu.summe.zeitMitWechselS,
                          altText: DruckFormat.zeit(alt.summe.zeitMitWechselS),
                          neuText: DruckFormat.zeit(neu.summe.zeitMitWechselS)))
        werte.append(Wert(titel: "Filament", alt: alt.summe.gramm, neu: neu.summe.gramm,
                          altText: DruckFormat.gramm(alt.summe.gramm), neuText: DruckFormat.gramm(neu.summe.gramm)))
        if let a = alt.summe.kosten, let n = neu.summe.kosten {
            werte.append(Wert(titel: "Kosten", alt: a, neu: n, altText: DruckFormat.euro(a), neuText: DruckFormat.euro(n)))
        }
        if alt.summe.platten != neu.summe.platten {
            werte.append(Wert(titel: "Platten", alt: Double(alt.summe.platten), neu: Double(neu.summe.platten),
                              altText: "\(alt.summe.platten)", neuText: "\(neu.summe.platten)"))
        }
        var teile: [(String, Double)] = []
        for g in neu.teile {
            guard let a = alt.gruppe(g.gruppe), a.zeitS > 0 else { continue }
            teile.append((g.kurzname, (g.zeitS - a.zeitS) / a.zeitS))
        }
        teile.sort { abs($0.1) > abs($1.1) }
        return DruckAenderung(run: neu.run, werte: werte,
                              teile: teile.prefix(3).filter { abs($0.1) >= 0.005 }.map { (name: $0.0, relativ: $0.1) })
    }
}

/// Aktionen der Druckvorschau, implementiert vom App-Kern (AppController+Druck); die Oberfläche ruft sie über
/// `model.druckActions` auf.
@MainActor
public protocol DruckActions: AnyObject {
    /// PRINT_PREVIEW_REQ: die aktuelle Vorschau holen.
    func druckvorschauAnfordern()
    /// PRINT_SETTINGS von Kevin: Teilmenge der Einstellungen (`.null` setzt einen Wert zurück) und bzw. oder der Zweck;
    /// `zuruecksetzen` nimmt alle Vorgaben des Teils bzw. der Gruppe zurück.
    func druckEinstellen(_ ziel: DruckZiel, einstellungen: [String: JSONValue]?, zweck: JSONValue?, zuruecksetzen: Bool)
    /// PRINT_EXPORT_REQ: Platten (leer = alle) als 3MF nach `ziel` (nil = `<projekt>/output/<projekt>-druck.3mf`).
    func druckExportieren(platten: [Int], nach ziel: URL?)
    /// PRINT_EXPORT_REQ mit dem Filament je Material, das Kevin gewählt hat (Strang „Druckexport 2“; ohne Filament
    /// fragt der Kernel nach und schreibt nichts).
    func druckExportieren(platten: [Int], nach ziel: URL?, filament: [String: String])
    /// Die exportierte Datei in Bambu Studio öffnen (nur auf Klick).
    func druckInBambuStudioOeffnen(_ datei: URL)
    /// Teile im 3D-Bereich und im Teilebaum auswählen, auf Wunsch einpassen.
    func druckTeileWaehlen(_ teile: [String], einpassen: Bool)
}

extension DruckActions {
    public func druckExportieren(platten: [Int], nach ziel: URL?, filament: [String: String]) {
        druckExportieren(platten: platten, nach: ziel)
    }

    public func druckEinstellen(_ ziel: DruckZiel, einstellungen: [String: JSONValue]?, zweck: JSONValue?) {
        druckEinstellen(ziel, einstellungen: einstellungen, zweck: zweck, zuruecksetzen: false)
    }

    /// Kevins Vorgaben zurücknehmen: die genannten Schlüssel (`null` je Wert), leer = alle (`zuruecksetzen`).
    public func druckZuruecksetzen(_ ziel: DruckZiel, schluessel: [String]) {
        guard !schluessel.isEmpty else {
            druckEinstellen(ziel, einstellungen: nil, zweck: nil, zuruecksetzen: true)
            return
        }
        let ohneZweck = schluessel.filter { $0 != "zweck" }
        var e: [String: JSONValue]?
        if !ohneZweck.isEmpty { e = Dictionary(uniqueKeysWithValues: ohneZweck.map { ($0, JSONValue.null) }) }
        druckEinstellen(ziel, einstellungen: e, zweck: schluessel.contains("zweck") ? .null : nil, zuruecksetzen: false)
    }
}

extension AppModel {
    /// Aktionen der Druckvorschau (nil im Demomodus).
    public var druckActions: DruckActions? { actions as? DruckActions }
}
