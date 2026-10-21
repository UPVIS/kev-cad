import Foundation
import simd

// Prüfung (PROTOCOL.md Abschnitt „Prüfung“): Befunde nach jedem Lauf, zuerst Durchdringungen. Rein additiv zu AppModel
// (eigenes @Published-Feld `pruefung`), damit die Stränge beim Zusammenführen nicht kollidieren.

public enum PruefSchwere: String, Sendable, CaseIterable, Comparable {
    case fehler, warnung, hinweis

    var rang: Int { self == .fehler ? 0 : self == .warnung ? 1 : 2 }

    public static func < (a: PruefSchwere, b: PruefSchwere) -> Bool { a.rang < b.rang }
}

/// Ein Befund: allgemeines Format, auch für andere Prüfungen (Druck, Bedingungen).
public struct PruefBefund: Identifiable, Equatable, Sendable {
    public var id: String
    public var art: String
    public var teile: [String]
    public var schwere: PruefSchwere
    public var text: String
    public var loesung: String
    public var ort: SIMD3<Float>?
    /// Index in `PruefErgebnis.geometrie` (Schnittkörper) oder nil.
    public var geometrie: Int?
    /// Zahlen aus `wert` (Volumen, Tiefe …), flach.
    public var werte: [String: Double]

    public init(
        id: String, art: String, teile: [String], schwere: PruefSchwere, text: String, loesung: String = "",
        ort: SIMD3<Float>? = nil, geometrie: Int? = nil, werte: [String: Double] = [:]
    ) {
        self.id = id
        self.art = art
        self.teile = teile
        self.schwere = schwere
        self.text = text
        self.loesung = loesung
        self.ort = ort
        self.geometrie = geometrie
        self.werte = werte
    }
}

/// Schnittkörper eines Befunds (Weltkoordinaten): Punkte und Normalen je 3 Werte, Dreiecke je 3 Indizes.
public struct PruefGeometrie: Equatable, Sendable {
    public var befund: String?
    public var positions: [Float]
    public var normals: [Float]
    public var triangles: [UInt32]

    public var vertexCount: Int { positions.count / 3 }
    public var triangleCount: Int { triangles.count / 3 }

    public init(befund: String?, positions: [Float], normals: [Float], triangles: [UInt32]) {
        self.befund = befund
        self.positions = positions
        self.normals = normals
        self.triangles = triangles
    }
}

/// Ein Schritt der Montagereihenfolge (CHECK.montage.schritte): Teil oder Baugruppe mit Einführrichtung.
public struct MontageSchritt: Identifiable, Equatable, Sendable {
    public var nr: Int
    public var name: String
    public var teile: [String]
    public var gruppe: Bool
    /// „Grundteil“, „von oben“, „von −X her“ …
    public var richtungText: String
    public var richtung: SIMD3<Float>?
    public var werkzeug: String?

    public var id: Int { nr }

    public init(
        nr: Int, name: String, teile: [String], gruppe: Bool = false, richtungText: String,
        richtung: SIMD3<Float>? = nil, werkzeug: String? = nil
    ) {
        self.nr = nr
        self.name = name
        self.teile = teile
        self.gruppe = gruppe
        self.richtungText = richtungText
        self.richtung = richtung
        self.werkzeug = werkzeug
    }

    public init?(json: JSONValue) {
        guard let nr = json["nr"]?.intValue else { return nil }
        let teile = json["teile"]?.stringList ?? []
        self.init(
            nr: nr, name: json["name"]?.stringValue ?? teile.first ?? "Schritt \(nr)", teile: teile,
            gruppe: json["gruppe"]?.boolValue ?? false, richtungText: json["richtung_text"]?.stringValue ?? "",
            richtung: json["richtung"]?.vector3, werkzeug: json["werkzeug"]?.stringValue)
    }
}

public struct PruefErgebnis: Equatable, Sendable {
    public enum Zustand: String, Sendable {
        case running, done, cancelled, failed
    }

    public var run: Int
    public var zustand: Zustand
    /// Eine neuere Prüfung läuft (die Befunde sind die der letzten fertigen).
    public var laeuft: Bool
    public var dauerMs: Double?
    public var meldung: String?
    /// „2 Durchdringungen · 1 Teil nicht einbaubar“; leer, wenn nichts offen ist.
    public var zusammenfassung: String
    public var fehler: Int
    public var warnungen: Int
    public var hinweise: Int
    public var befunde: [PruefBefund]
    public var geometrie: [PruefGeometrie]
    /// Weitere Teile des Ergebnisses (Montagereihenfolge, Standsicherheit), roh für spätere Ansichten.
    public var montage: JSONValue?
    public var stand: JSONValue?

    public init(
        run: Int, zustand: Zustand, laeuft: Bool = false, dauerMs: Double? = nil, meldung: String? = nil,
        zusammenfassung: String = "", fehler: Int = 0, warnungen: Int = 0, hinweise: Int = 0,
        befunde: [PruefBefund] = [], geometrie: [PruefGeometrie] = [], montage: JSONValue? = nil,
        stand: JSONValue? = nil
    ) {
        self.run = run
        self.zustand = zustand
        self.laeuft = laeuft
        self.dauerMs = dauerMs
        self.meldung = meldung
        self.zusammenfassung = zusammenfassung
        self.fehler = fehler
        self.warnungen = warnungen
        self.hinweise = hinweise
        self.befunde = befunde
        self.geometrie = geometrie
        self.montage = montage
        self.stand = stand
    }

    /// Befunde, die den Export sperren.
    public var offen: [PruefBefund] { befunde.filter { $0.schwere == .fehler } }

    /// Teile, die rot markiert werden (Fehler und Warnungen).
    public var betroffeneTeile: Set<String> {
        Set(befunde.filter { $0.schwere != .hinweis }.flatMap(\.teile))
    }

    /// Text für das Band: die Zusammenfassung des Kernels, sonst aus den Befunden gezählt.
    public var bandText: String {
        if !zusammenfassung.isEmpty { return zusammenfassung }
        let n = befunde.filter { $0.schwere != .hinweis }.count
        return n == 0 ? "" : KevFormat.count(n, one: "Befund", many: "Befunde")
    }

    /// Montagereihenfolge (Einbau), leer ohne Montageprüfung.
    public var montageSchritte: [MontageSchritt] {
        (montage?["schritte"]?.arrayValue ?? []).compactMap(MontageSchritt.init(json:))
    }

    /// Teile, die sich nicht einbauen lassen (CHECK.montage.offen).
    public var montageOffen: [String] { montage?["offen"]?.stringList ?? [] }

    /// Kennung für „Band weggeklickt, bis sich die Befunde ändern“.
    public var schluessel: String {
        befunde.filter { $0.schwere != .hinweis }.map { "\($0.art):\($0.teile.joined(separator: "+"))" }
            .joined(separator: "|")
    }
}

/// Aktionen zur Prüfung, implementiert vom App-Kern (AppController). Die Oberfläche ruft sie über
/// `model.actions as? PruefActions` auf; der Demomodus braucht sie nicht.
@MainActor
public protocol PruefActions: AnyObject {
    /// Teile des Befunds auswählen und die Kamera auf den Ort fahren.
    func zeigeBefund(_ befund: PruefBefund)
    /// Rote Schnittkörper im Viewer ein- oder ausblenden (AppModel.schnittkoerperSichtbar).
    func setSchnittkoerperSichtbar(_ sichtbar: Bool)
    /// Montage Schritt für Schritt: nur die Teile der Schritte 1 … `schritt` zeigen, die des letzten ausgewählt;
    /// nil zeigt wieder alles.
    func zeigeMontageSchritt(_ schritt: Int?)
}
