import Foundation

// V2-6: Paketformat `kevcad-feedback/1` (PROTOCOL.md, Abschnitt „V2-6 Sprach-Feedback“). Referenz und Prüfung stehen in
// kernel/src/kevcad_kernel/protocol.py, Beispiel in Fixtures/feedback_beispiel.json. Kamera und Lage bleiben `JSONValue`
// mit den Feldern von LAGE: Sie gehen nur durch und werden hier nicht ausgewertet.

/// Grenzen und Namen, die Kernel und App gleich führen (`protocol.py`).
public enum FeedbackGrenzen {
    public static let format = "kevcad-feedback/1"
    public static let ordner = "feedback"
    public static let zeigerVorS = 0.5
    public static let zeigerNachS = 0.3
    public static let zeigerMinS = 0.25
    public static let zeigewortSucheS = 0.4
    public static let zeigerJeSatz = 6
    public static let mausJeS = 10.0
    public static let kameraJeS = 5.0
    public static let bildLaengeMax = 1600
    public static let zeigewoerter: Set<String> = [
        "hier", "da", "dort", "dahin", "hierhin", "dorthin", "das", "dies", "diese", "dieser", "dieses", "diesem",
        "diesen",
    ]
}

public struct FeedbackPaket: Codable, Equatable, Sendable {
    public struct Projekt: Codable, Equatable, Sendable {
        public var name: String
        public var pfad: String

        public init(name: String, pfad: String) {
            self.name = name
            self.pfad = pfad
        }
    }

    /// Zeitraum, in dem das Mikrofon an war.
    public struct Abschnitt: Codable, Equatable, Sendable {
        public var von: Double
        public var bis: Double

        public init(von: Double, bis: Double) {
            self.von = von
            self.bis = bis
        }
    }

    public struct Wort: Codable, Equatable, Sendable {
        public var text: String
        public var von: Double
        public var bis: Double
        public var satz: Int

        public init(text: String, von: Double, bis: Double, satz: Int) {
            self.text = text
            self.von = von
            self.bis = bis
            self.satz = satz
        }
    }

    public struct Auswahl: Codable, Equatable, Sendable {
        public var run: Int
        public var refs: [String]

        public init(run: Int, refs: [String]) {
            self.run = run
            self.refs = refs
        }
    }

    /// Worauf ein Satz sich bezieht: Zeiger (Teil unter der Maus) oder Strich.
    public struct Bezug: Codable, Equatable, Sendable {
        public var art: String
        public var t: Double
        public var bis: Double
        /// Zeiger
        public var wort: String?
        public var teil: String?
        public var ref: String?
        public var run: Int?
        public var punkt: [Double]?
        public var normale: [Double]?
        public var bild: [Double]?
        /// Strich
        public var strich: Int?
        public var teile: [String]?

        public init(zeiger p: MausProbe, t: Double, bis: Double, wort: String?) {
            art = "zeiger"
            self.t = t
            self.bis = bis
            self.wort = wort
            teil = p.teil
            ref = p.ref
            run = p.run
            punkt = p.punkt
            normale = p.normale
            bild = p.bild
        }

        public init(strich s: Strich) {
            art = "strich"
            t = s.t
            bis = s.bis
            strich = s.nr
            teile = s.teile
        }

        enum CodingKeys: String, CodingKey {
            case art, t, bis, wort, teil, ref, run, punkt, normale, bild, strich, teile
        }

        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(art, forKey: .art)
            try c.encode(t, forKey: .t)
            try c.encode(bis, forKey: .bis)
            if art == "strich" {
                try c.encode(strich, forKey: .strich)
                try c.encode(teile, forKey: .teile)
            } else {
                try c.encode(wort, forKey: .wort)
                try c.encode(teil, forKey: .teil)
                try c.encode(ref, forKey: .ref)
                try c.encode(run, forKey: .run)
                try c.encode(punkt, forKey: .punkt)
                try c.encode(normale, forKey: .normale)
                try c.encode(bild, forKey: .bild)
            }
        }
    }

    public struct Satz: Codable, Equatable, Sendable {
        public var nr: Int
        public var text: String
        public var von: Double
        public var bis: Double
        public var vorlaeufig: Bool
        public var kamera: JSONValue
        public var auswahl: Auswahl
        public var bezuege: [Bezug]

        public init(nr: Int, text: String, von: Double, bis: Double, vorlaeufig: Bool, kamera: JSONValue,
                    auswahl: Auswahl, bezuege: [Bezug]) {
            self.nr = nr
            self.text = text
            self.von = von
            self.bis = bis
            self.vorlaeufig = vorlaeufig
            self.kamera = kamera
            self.auswahl = auswahl
            self.bezuege = bezuege
        }
    }

    public struct StrichPunkt: Codable, Equatable, Sendable {
        public var t: Double
        public var bild: [Double]
        public var welt: [Double]
        public var ref: String?

        public init(t: Double, bild: [Double], welt: [Double], ref: String?) {
            self.t = t
            self.bild = bild
            self.welt = welt
            self.ref = ref
        }

        enum CodingKeys: String, CodingKey { case t, bild, welt, ref }

        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(t, forKey: .t)
            try c.encode(bild, forKey: .bild)
            try c.encode(welt, forKey: .welt)
            try c.encode(ref, forKey: .ref)
        }
    }

    public struct Strich: Codable, Equatable, Sendable {
        public var nr: Int
        public var t: Double
        public var bis: Double
        public var run: Int
        public var teile: [String]
        public var laengeMm: Double
        public var kamera: JSONValue
        public var punkte: [StrichPunkt]

        public init(nr: Int, t: Double, bis: Double, run: Int, teile: [String], laengeMm: Double, kamera: JSONValue,
                    punkte: [StrichPunkt]) {
            self.nr = nr
            self.t = t
            self.bis = bis
            self.run = run
            self.teile = teile
            self.laengeMm = laengeMm
            self.kamera = kamera
            self.punkte = punkte
        }

        enum CodingKeys: String, CodingKey {
            case nr, t, bis, run, teile, kamera, punkte
            case laengeMm = "laenge_mm"
        }
    }

    /// Eine Probe des Mauswegs. `teil` nil: neben dem Modell; `bild` nil: außerhalb des Viewers.
    public struct MausProbe: Codable, Equatable, Sendable {
        public var t: Double
        public var bild: [Double]?
        public var teil: String?
        public var ref: String?
        public var run: Int?
        public var punkt: [Double]?
        public var normale: [Double]?

        public init(t: Double, bild: [Double]? = nil, teil: String? = nil, ref: String? = nil, run: Int? = nil,
                    punkt: [Double]? = nil, normale: [Double]? = nil) {
            self.t = t
            self.bild = bild
            self.teil = teil
            self.ref = ref
            self.run = run
            self.punkt = punkt
            self.normale = normale
        }

        enum CodingKeys: String, CodingKey { case t, bild, teil, ref, run, punkt, normale }

        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(t, forKey: .t)
            try c.encode(bild, forKey: .bild)
            try c.encode(teil, forKey: .teil)
            try c.encode(ref, forKey: .ref)
            try c.encode(run, forKey: .run)
            try c.encode(punkt, forKey: .punkt)
            try c.encode(normale, forKey: .normale)
        }
    }

    public struct KameraProbe: Codable, Equatable, Sendable {
        public var t: Double
        public var kamera: JSONValue

        public init(t: Double, kamera: JSONValue) {
            self.t = t
            self.kamera = kamera
        }
    }

    public struct AuswahlProbe: Codable, Equatable, Sendable {
        public var t: Double
        public var run: Int
        public var refs: [String]

        public init(t: Double, run: Int, refs: [String]) {
            self.t = t
            self.run = run
            self.refs = refs
        }
    }

    public struct Bild: Codable, Equatable, Sendable {
        public var datei: String
        public var breite: Int
        public var hoehe: Int

        public init(datei: String, breite: Int, hoehe: Int) {
            self.datei = datei
            self.breite = breite
            self.hoehe = hoehe
        }
    }

    public var format: String
    public var name: String
    public var erstellt: String
    public var uhrStart: Double
    public var dauerS: Double
    public var spracherkennung: String
    /// `ton`: gemessen; `geschaetzt`: aus dem Takt der Zwischenstände (Wortlaut nennt keine Zeiten je Wort).
    public var wortzeiten: String
    public var projekt: Projekt
    public var run: Int
    public var abschnitte: [Abschnitt]
    public var worte: [Wort]
    public var saetze: [Satz]
    public var striche: [Strich]
    public var mausweg: [MausProbe]
    public var kameraVerlauf: [KameraProbe]
    public var auswahlVerlauf: [AuswahlProbe]
    public var ende: JSONValue
    public var bild: Bild?

    enum CodingKeys: String, CodingKey {
        case format, name, erstellt, spracherkennung, wortzeiten, projekt, run, abschnitte, worte, saetze, striche, mausweg
        case ende, bild
        case uhrStart = "uhr_start"
        case dauerS = "dauer_s"
        case kameraVerlauf = "kamera_verlauf"
        case auswahlVerlauf = "auswahl_verlauf"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(format, forKey: .format)
        try c.encode(name, forKey: .name)
        try c.encode(erstellt, forKey: .erstellt)
        try c.encode(uhrStart, forKey: .uhrStart)
        try c.encode(dauerS, forKey: .dauerS)
        try c.encode(spracherkennung, forKey: .spracherkennung)
        try c.encode(wortzeiten, forKey: .wortzeiten)
        try c.encode(projekt, forKey: .projekt)
        try c.encode(run, forKey: .run)
        try c.encode(abschnitte, forKey: .abschnitte)
        try c.encode(worte, forKey: .worte)
        try c.encode(saetze, forKey: .saetze)
        try c.encode(striche, forKey: .striche)
        try c.encode(mausweg, forKey: .mausweg)
        try c.encode(kameraVerlauf, forKey: .kameraVerlauf)
        try c.encode(auswahlVerlauf, forKey: .auswahlVerlauf)
        try c.encode(ende, forKey: .ende)
        try c.encode(bild, forKey: .bild)
    }

    /// JSON, wie es in der Datei steht.
    public func json() throws -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.withoutEscapingSlashes, .sortedKeys]
        return try enc.encode(self)
    }
}

/// Schreibt ein Paket nach `<projekt>/feedback/`: erst das Bild, zuletzt die JSON-Datei, beide über eine temporäre Datei
/// im selben Ordner. Wer die JSON-Datei sieht, findet alles andere schon vor.
public enum FeedbackAblage {
    /// `fb-JJJJMMTT-HHMMSS`; bei gleicher Sekunde hängt `name(…)` eine Nummer an.
    public static func stamm(_ datum: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return "fb-" + f.string(from: datum)
    }

    /// Name, den es im Ordner noch nicht gibt.
    public static func name(in ordner: URL, datum: Date) -> String {
        let basis = stamm(datum)
        var name = basis
        var n = 1
        let fm = FileManager.default
        while fm.fileExists(atPath: ordner.appendingPathComponent(name + ".json").path) {
            n += 1
            name = "\(basis)-\(n)"
        }
        return name
    }

    public static func ordner(projekt: URL) -> URL {
        projekt.appendingPathComponent(FeedbackGrenzen.ordner, isDirectory: true)
    }

    /// Schreibt Bild und Paket; Rückgabe ist der Pfad der JSON-Datei.
    @discardableResult
    public static func schreiben(_ paket: FeedbackPaket, bild: Data?, in ordner: URL) throws -> URL {
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        if let bild, let name = paket.bild?.datei {
            try bild.write(to: ordner.appendingPathComponent(name), options: .atomic)
        }
        let ziel = ordner.appendingPathComponent(paket.name + ".json")
        try paket.json().write(to: ziel, options: .atomic)
        return ziel
    }
}
