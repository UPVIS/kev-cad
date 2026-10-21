import Foundation
import simd

// Versionen (PLAN-VERSIONEN.md, PROTOCOL.md Abschnitt „Versionen“): Versionsleiste, Meilensteine, Wiederherstellen,
// Vergleich, Varianten. Eigenes Objekt (`AppModel.versionen`), damit die Leiste nicht das ganze Fenster neu zeichnet.
// Vertrag wie AppModel: der App-Kern (AppController+Versionen) schreibt, die Oberfläche liest und ruft
// `VersionenActions` (über `model.versionenActions`).

/// Kennzahlen einer Version: Teile, Masse, Kosten, Prüfstand.
public struct VersionKennzahlen: Equatable, Sendable {
    public var teile: Int
    public var masseKg: Double?
    public var kosten: Double?
    public var positionen: Int?
    public var fehler: Int?
    public var warnungen: Int?
    public var pruefung: String?

    public init(
        teile: Int, masseKg: Double? = nil, kosten: Double? = nil, positionen: Int? = nil, fehler: Int? = nil,
        warnungen: Int? = nil, pruefung: String? = nil
    ) {
        self.teile = teile
        self.masseKg = masseKg
        self.kosten = kosten
        self.positionen = positionen
        self.fehler = fehler
        self.warnungen = warnungen
        self.pruefung = pruefung
    }
}

public struct VersionMeilenstein: Equatable, Sendable {
    public var titel: String
    public var notiz: String
    public var wer: String?

    public init(titel: String, notiz: String = "", wer: String? = nil) {
        self.titel = titel
        self.notiz = notiz
        self.wer = wer
    }
}

/// Eine Version (ein Stand aller Projektdateien).
public struct VersionEintrag: Identifiable, Equatable, Sendable {
    /// Wer die Version erzeugt hat.
    public enum Wer: String, Sendable {
        case kevin, agent, kevcad, unbekannt
    }

    public var nr: Int
    public var commit: String
    public var zeit: Date
    public var wer: Wer
    public var werText: String
    /// lauf | wiederherstellen | sicherung | uebernahme | meilenstein
    public var quelle: String
    public var titel: String
    public var aus: Int?
    public var meilenstein: VersionMeilenstein?
    public var kennzahlen: VersionKennzahlen?
    public var params: [String: Double]
    public var bild: URL?
    public var aktuell: Bool
    /// Stammt aus der Variante, von der die aktuelle abzweigt.
    public var geerbt: Bool
    public var dateien: [String]
    public var gruppe: String?
    /// Nachberechnung gescheitert (Text) oder nil.
    public var nachberechnung: String?

    public var id: Int { nr }

    public init(
        nr: Int, commit: String = "", zeit: Date, wer: Wer = .unbekannt, werText: String = "", quelle: String = "lauf",
        titel: String = "", aus: Int? = nil, meilenstein: VersionMeilenstein? = nil,
        kennzahlen: VersionKennzahlen? = nil, params: [String: Double] = [:], bild: URL? = nil,
        aktuell: Bool = false, geerbt: Bool = false, dateien: [String] = [], gruppe: String? = nil,
        nachberechnung: String? = nil
    ) {
        self.nr = nr
        self.commit = commit
        self.zeit = zeit
        self.wer = wer
        self.werText = werText
        self.quelle = quelle
        self.titel = titel
        self.aus = aus
        self.meilenstein = meilenstein
        self.kennzahlen = kennzahlen
        self.params = params
        self.bild = bild
        self.aktuell = aktuell
        self.geerbt = geerbt
        self.dateien = dateien
        self.gruppe = gruppe
        self.nachberechnung = nachberechnung
    }

    /// Text für die Zeile: Meilensteintitel, sonst der Titel der Version.
    public var anzeigeTitel: String { meilenstein?.titel ?? titel }
}

/// Dichte Folge automatischer Versionen („12 Läufe in 4 Minuten“), in der Leiste zusammengefasst.
public struct VersionGruppe: Identifiable, Equatable, Sendable {
    public var id: String
    public var anzahl: Int
    public var neueste: Int
    public var aelteste: Int
    public var text: String

    public init(id: String, anzahl: Int, neueste: Int, aelteste: Int, text: String) {
        self.id = id
        self.anzahl = anzahl
        self.neueste = neueste
        self.aelteste = aelteste
        self.text = text
    }
}

public struct VersionVariante: Identifiable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var aktuell: Bool
    public var versionen: Int
    public var von: Int?

    public init(id: String, name: String, aktuell: Bool, versionen: Int = 0, von: Int? = nil) {
        self.id = id
        self.name = name
        self.aktuell = aktuell
        self.versionen = versionen
        self.von = von
    }
}

/// Inhalt von VERSIONEN.
public struct VersionenStand: Equatable, Sendable {
    public var projekt: String
    public var verfuegbar: Bool
    public var meldung: String?
    public var variante: String
    public var varianten: [VersionVariante]
    public var versionen: [VersionEintrag]
    public var gruppen: [VersionGruppe]
    public var anzahl: Int
    public var meilensteine: Int
    public var ungesichert: Bool

    public init(
        projekt: String = "", verfuegbar: Bool = true, meldung: String? = nil, variante: String = "haupt",
        varianten: [VersionVariante] = [], versionen: [VersionEintrag] = [], gruppen: [VersionGruppe] = [],
        anzahl: Int = 0, meilensteine: Int = 0, ungesichert: Bool = false
    ) {
        self.projekt = projekt
        self.verfuegbar = verfuegbar
        self.meldung = meldung
        self.variante = variante
        self.varianten = varianten
        self.versionen = versionen
        self.gruppen = gruppen
        self.anzahl = anzahl
        self.meilensteine = meilensteine
        self.ungesichert = ungesichert
    }

    public var aktuelleVariante: VersionVariante? { varianten.first(where: \.aktuell) }
    public var aktuelleVersion: VersionEintrag? { versionen.first(where: \.aktuell) }
    public func version(_ nr: Int) -> VersionEintrag? { versionen.first { $0.nr == nr } }

    /// Zeilen der Leiste: einzelne Versionen und zusammengefasste Folgen (aufgeklappte Folgen zeigen ihre Versionen).
    public func zeilen(aufgeklappt: Set<String> = []) -> [VersionZeile] {
        var out: [VersionZeile] = []
        var gezeigt = Set<String>()
        let gruppenNachID = Dictionary(gruppen.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        for v in versionen {
            if let g = v.gruppe, let gruppe = gruppenNachID[g] {
                if !gezeigt.contains(g) {
                    gezeigt.insert(g)
                    let mitglieder = versionen.filter { $0.gruppe == g }
                    out.append(.gruppe(gruppe, mitglieder))
                }
                if aufgeklappt.contains(g) { out.append(.version(v, eingerueckt: true)) }
                continue
            }
            out.append(.version(v, eingerueckt: false))
        }
        return out
    }
}

/// Eine Zeile der Versionsleiste.
public enum VersionZeile: Identifiable, Equatable, Sendable {
    case version(VersionEintrag, eingerueckt: Bool)
    case gruppe(VersionGruppe, [VersionEintrag])

    public var id: String {
        switch self {
        case .version(let v, _): return "v\(v.nr)"
        case .gruppe(let g, _): return g.id
        }
    }
}

// MARK: - Vergleich

/// Netz eines Geisterkörpers (Weltkoordinaten): Teil der alten Version, das sich geändert hat (`alt`) oder fehlt (`weg`).
public struct VergleichsNetz: Equatable, Sendable {
    public var teil: String
    public var art: String
    public var positions: [Float]
    public var normals: [Float]
    public var triangles: [UInt32]
    public var edgePoints: [Float]
    public var edgeOffsets: [UInt32]

    public init(
        teil: String, art: String, positions: [Float], normals: [Float], triangles: [UInt32], edgePoints: [Float] = [],
        edgeOffsets: [UInt32] = [0]
    ) {
        self.teil = teil
        self.art = art
        self.positions = positions
        self.normals = normals
        self.triangles = triangles
        self.edgePoints = edgePoints
        self.edgeOffsets = edgeOffsets
    }

    public var vertexCount: Int { positions.count / 3 }
    public var triangleCount: Int { triangles.count / 3 }

    /// Kanten als Polylinien.
    public var edgeLines: [[SIMD3<Float>]] {
        guard edgeOffsets.count > 1 else { return [] }
        var out: [[SIMD3<Float>]] = []
        for k in 0..<(edgeOffsets.count - 1) {
            let a = Int(edgeOffsets[k]), b = Int(edgeOffsets[k + 1])
            guard a < b, b * 3 <= edgePoints.count else { continue }
            out.append((a..<b).map { SIMD3(edgePoints[$0 * 3], edgePoints[$0 * 3 + 1], edgePoints[$0 * 3 + 2]) })
        }
        return out
    }
}

public struct ParameterAenderung: Equatable, Sendable, Identifiable {
    public var name: String
    public var alt: Double?
    public var neu: Double?
    /// neu | weg | geaendert
    public var art: String
    public var id: String { name }

    public init(name: String, alt: Double?, neu: Double?, art: String) {
        self.name = name
        self.alt = alt
        self.neu = neu
        self.art = art
    }
}

public struct TeilAenderung: Equatable, Sendable, Identifiable {
    public var name: String
    /// form | lage | farbe | material | lagerteil
    public var arten: [String]
    public var dvolumen: Double?
    public var dmasse: Double?
    public var id: String { name }

    public init(name: String, arten: [String], dvolumen: Double? = nil, dmasse: Double? = nil) {
        self.name = name
        self.arten = arten
        self.dvolumen = dvolumen
        self.dmasse = dmasse
    }
}

public struct StuecklistenAenderung: Equatable, Sendable {
    public var benennung: String
    public var masseText: String?
    public var anzahl: Int?
    public var altAnzahl: Int?
    public var neuAnzahl: Int?
    public var altMasseText: String?
    public var preis: Double?
    public var altPreis: Double?

    public init(
        benennung: String, masseText: String? = nil, anzahl: Int? = nil, altAnzahl: Int? = nil, neuAnzahl: Int? = nil,
        altMasseText: String? = nil, preis: Double? = nil, altPreis: Double? = nil
    ) {
        self.benennung = benennung
        self.masseText = masseText
        self.anzahl = anzahl
        self.altAnzahl = altAnzahl
        self.neuAnzahl = neuAnzahl
        self.altMasseText = altMasseText
        self.preis = preis
        self.altPreis = altPreis
    }
}

public struct CodeDatei: Equatable, Sendable, Identifiable {
    public var pfad: String
    /// A (neu), M (geändert), D (gelöscht)
    public var status: String
    public var plus: Int?
    public var minus: Int?
    public var binaer: Bool
    public var id: String { pfad }

    public init(pfad: String, status: String, plus: Int? = nil, minus: Int? = nil, binaer: Bool = false) {
        self.pfad = pfad
        self.status = status
        self.plus = plus
        self.minus = minus
        self.binaer = binaer
    }
}

/// Inhalt von VERSION_VERGLEICH.
public struct VersionVergleich: Equatable, Sendable {
    public struct Seite: Equatable, Sendable {
        public var nr: Int?
        public var titel: String
        public var zeit: String?
        public var kennzahlen: VersionKennzahlen?

        public init(nr: Int?, titel: String, zeit: String? = nil, kennzahlen: VersionKennzahlen? = nil) {
            self.nr = nr
            self.titel = titel
            self.zeit = zeit
            self.kennzahlen = kennzahlen
        }

        public var kurz: String { nr.map { "V\($0)" } ?? "aktueller Stand" }
    }

    public var a: Seite
    public var b: Seite
    /// b ist der aktuelle Stand (nur dann gibt es Geisterkörper).
    public var aktuell: Bool
    public var zusammenfassung: String
    public var params: [ParameterAenderung]
    public var teileNeu: [String]
    public var teileWeg: [String]
    public var teileGeaendert: [TeilAenderung]
    public var teileGleich: Int
    public var stuecklisteNeu: [StuecklistenAenderung]
    public var stuecklisteWeg: [StuecklistenAenderung]
    public var stuecklisteGeaendert: [StuecklistenAenderung]
    public var pruefungAlt: String?
    public var pruefungNeu: String?
    public var fehlerAlt: Int?
    public var fehlerNeu: Int?
    public var kennzahlenAlt: VersionKennzahlen?
    public var kennzahlenNeu: VersionKennzahlen?
    public var codeDateien: [CodeDatei]
    public var diff: String
    public var diffGekuerzt: Bool
    public var hinweise: [String]
    public var ms: Int
    public var geometrie: [VergleichsNetz]

    public init(
        a: Seite, b: Seite, aktuell: Bool = true, zusammenfassung: String = "", params: [ParameterAenderung] = [],
        teileNeu: [String] = [], teileWeg: [String] = [], teileGeaendert: [TeilAenderung] = [], teileGleich: Int = 0,
        stuecklisteNeu: [StuecklistenAenderung] = [], stuecklisteWeg: [StuecklistenAenderung] = [],
        stuecklisteGeaendert: [StuecklistenAenderung] = [], pruefungAlt: String? = nil, pruefungNeu: String? = nil,
        fehlerAlt: Int? = nil, fehlerNeu: Int? = nil, kennzahlenAlt: VersionKennzahlen? = nil,
        kennzahlenNeu: VersionKennzahlen? = nil, codeDateien: [CodeDatei] = [], diff: String = "",
        diffGekuerzt: Bool = false, hinweise: [String] = [], ms: Int = 0, geometrie: [VergleichsNetz] = []
    ) {
        self.a = a
        self.b = b
        self.aktuell = aktuell
        self.zusammenfassung = zusammenfassung
        self.params = params
        self.teileNeu = teileNeu
        self.teileWeg = teileWeg
        self.teileGeaendert = teileGeaendert
        self.teileGleich = teileGleich
        self.stuecklisteNeu = stuecklisteNeu
        self.stuecklisteWeg = stuecklisteWeg
        self.stuecklisteGeaendert = stuecklisteGeaendert
        self.pruefungAlt = pruefungAlt
        self.pruefungNeu = pruefungNeu
        self.fehlerAlt = fehlerAlt
        self.fehlerNeu = fehlerNeu
        self.kennzahlenAlt = kennzahlenAlt
        self.kennzahlenNeu = kennzahlenNeu
        self.codeDateien = codeDateien
        self.diff = diff
        self.diffGekuerzt = diffGekuerzt
        self.hinweise = hinweise
        self.ms = ms
        self.geometrie = geometrie
    }

    /// Nichts geändert (Teile, Parameter, Stückliste, Code).
    public var gleich: Bool {
        params.isEmpty && teileNeu.isEmpty && teileWeg.isEmpty && teileGeaendert.isEmpty && stuecklisteNeu.isEmpty
            && stuecklisteWeg.isEmpty && stuecklisteGeaendert.isEmpty && codeDateien.isEmpty
    }
}

// MARK: - Store und Aktionen

@MainActor
public final class VersionenStore: ObservableObject {
    /// Zuletzt aus VERSIONEN; nil, bis der Kernel die Liste geschickt hat.
    @Published public internal(set) var stand: VersionenStand?
    /// Laufender Vergleich (Geisterkörper und Färbung im Viewer), nil = kein Vergleich.
    @Published public internal(set) var vergleich: VersionVergleich?
    /// Ein Vergleich wird gerade gerechnet (alte Version ohne Zwischenspeicher: Lauf ohne Live-Aufbau).
    @Published public internal(set) var vergleichLaeuft: Int?
    /// Was der Kernel gerade für die Versionen tut („V12 wird wiederhergestellt“), nil = nichts.
    @Published public internal(set) var arbeitet: String?
    /// Ergebnis der letzten Aktion für die Leiste (Bestätigung oder Fehler).
    @Published public internal(set) var meldung: VersionenMeldung?

    public init() {}
}

public struct VersionenMeldung: Equatable, Sendable {
    public var text: String
    public var fehler: Bool
    public var zeit: Date

    public init(text: String, fehler: Bool = false, zeit: Date = Date()) {
        self.text = text
        self.fehler = fehler
        self.zeit = zeit
    }
}

/// Aktionen der Versionsleiste, implementiert vom App-Kern (AppController+Versionen) und im Demomodus.
@MainActor
public protocol VersionenActions: AnyObject {
    func requestVersionen()
    func restoreVersion(_ nr: Int)
    /// `b` nil = mit dem aktuellen Stand vergleichen.
    func compareVersion(_ a: Int, with b: Int?)
    func endCompare()
    /// `version` nil = aktueller Stand.
    func setMilestone(version: Int?, titel: String, notiz: String)
    func removeMilestone(version: Int)
    /// `from` nil = aktueller Stand.
    func createVariant(name: String, from version: Int?)
    func switchVariant(_ id: String)
    func renameVariant(_ id: String, to name: String)
}

extension AppModel {
    /// Versionsaktionen des App-Kerns (nil im Demomodus ohne Versionen).
    public var versionenActions: VersionenActions? { actions as? VersionenActions }
}
