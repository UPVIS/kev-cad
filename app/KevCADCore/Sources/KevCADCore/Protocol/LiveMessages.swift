import Foundation

// V2-5 Live (PROTOCOL.md, Abschnitt „V2-5 Live“): Fähigkeiten, Delta, In Arbeit, Agentenspur, Lagebild. Alle Felder
// werden nachsichtig gelesen. Testdateien `live_*.frame` aus kernel/tools/make_live_fixtures.py.

/// Fähigkeiten aus `HELLO.faehigkeiten` und `HELLO_APP.faehigkeiten`.
public enum LiveFaehigkeit {
    public static let delta = "delta-1"
    public static let inArbeit = "in-arbeit-1"
    public static let spur = "spur-1"
    public static let lage = "lage-1"
    public static let liveMasse = "live-masse-1"
    public static let flaeche = "flaeche-1"
    /// I-8: Der Kernel liefert Dateien ans Gerät (DATEI_REQ); nur der Kernel meldet sie, die App fragt.
    public static let datei = DateiAnsGeraet.faehigkeit

    /// Was diese App dem Kernel meldet. Was hier steht, muss auf der App-Seite vollständig funktionieren.
    public static let app: [String] = [delta, inArbeit, spur, lage, liveMasse, flaeche]
}

/// Grenzen, die Kernel und App gleich führen (`protocol.py`).
public enum LiveGrenzen {
    /// Inhalte je Teilname (PART_SAME) und Felder je Paar aus Szenario und Teil
    public static let teilInhalte = 4
    /// Rahmen je Art als mögliche Basis für WIE_ZUVOR
    public static let wieZuvorBasen = 6
    public static let spurLaenge = 50
    public static let wieZuvorArten: Set<String> = [
        "CHECK", "STATICS", "CONSTRAINTS", "BOM", "PRINT_PREVIEW", "SIM", "DOCS", "VERSIONEN",
    ]
}

// MARK: - Kernel → App

/// PART_SAME: Das Teil zeigt einen Inhalt, den die App schon hat.
public struct PartSameMessage: Decodable, Equatable, Sendable {
    public var run: Int
    public var name: String
    public var inhalt: String

    public init(run: Int, name: String, inhalt: String) {
        self.run = run
        self.name = name
        self.inhalt = inhalt
    }

    enum CodingKeys: String, CodingKey { case run, name, inhalt }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        name = try c.decode(String.self, forKey: .name)
        inhalt = (try? c.decodeIfPresent(String.self, forKey: .inhalt)) ?? ""
    }
}

/// IN_ARBEIT: das Teil, das der Kernel als Nächstes erwartet.
public struct InArbeitMessage: Decodable, Equatable, Sendable {
    public var run: Int
    public var teil: String
    public var nach: String?
    public var ms: Double

    public init(run: Int, teil: String, nach: String? = nil, ms: Double = 0) {
        self.run = run
        self.teil = teil
        self.nach = nach
        self.ms = ms
    }

    enum CodingKeys: String, CodingKey { case run, teil, nach, ms }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        run = (try? c.decodeIfPresent(Int.self, forKey: .run)) ?? 0
        teil = try c.decode(String.self, forKey: .teil)
        nach = try? c.decodeIfPresent(String.self, forKey: .nach)
        ms = (try? c.decodeIfPresent(Double.self, forKey: .ms)) ?? 0
    }
}

/// Ein Schritt der Agentenspur (ein Werkzeugaufruf); `id` bleibt über alle Stände gleich.
public struct AgentSchritt: Decodable, Equatable, Identifiable, Sendable {
    public enum Stand: String, Sendable { case laeuft, ok, fehler }

    public var id: String
    public var werkzeug: String
    public var text: String?
    public var absicht: String?
    public var sitzung: String?
    /// Sekunden Unix-Zeit
    public var beginn: Double
    public var ende: Double?
    public var dauerMs: Double?
    public var stand: Stand
    public var fehler: String?
    /// Nur `run`: Laufnummer und Zeitpunkte in ms ab Laufbeginn
    public var phasen: JSONValue?

    public init(
        id: String, werkzeug: String, text: String? = nil, absicht: String? = nil, sitzung: String? = nil,
        beginn: Double = 0, ende: Double? = nil, dauerMs: Double? = nil, stand: Stand = .laeuft, fehler: String? = nil,
        phasen: JSONValue? = nil
    ) {
        self.id = id
        self.werkzeug = werkzeug
        self.text = text
        self.absicht = absicht
        self.sitzung = sitzung
        self.beginn = beginn
        self.ende = ende
        self.dauerMs = dauerMs
        self.stand = stand
        self.fehler = fehler
        self.phasen = phasen
    }

    enum CodingKeys: String, CodingKey {
        case id, werkzeug, text, absicht, sitzung, beginn, ende, stand, fehler, phasen
        case dauerMs = "dauer_ms"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        werkzeug = (try? c.decodeIfPresent(String.self, forKey: .werkzeug)) ?? ""
        text = try? c.decodeIfPresent(String.self, forKey: .text)
        absicht = try? c.decodeIfPresent(String.self, forKey: .absicht)
        sitzung = try? c.decodeIfPresent(String.self, forKey: .sitzung)
        beginn = (try? c.decodeIfPresent(Double.self, forKey: .beginn)) ?? 0
        ende = try? c.decodeIfPresent(Double.self, forKey: .ende)
        dauerMs = try? c.decodeIfPresent(Double.self, forKey: .dauerMs)
        stand = ((try? c.decodeIfPresent(String.self, forKey: .stand)) ?? nil).flatMap(Stand.init(rawValue:)) ?? .laeuft
        fehler = try? c.decodeIfPresent(String.self, forKey: .fehler)
        phasen = (try? c.decodeIfPresent(JSONValue.self, forKey: .phasen)).flatMap { $0?.isNull == true ? nil : $0 }
    }
}

public struct AgentSpurMessage: Decodable, Sendable {
    public var schritte: [AgentSchritt]

    enum CodingKeys: String, CodingKey { case schritte }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schritte = (try? c.decodeIfPresent([AgentSchritt].self, forKey: .schritte)) ?? []
    }
}

public struct AgentSchrittMessage: Decodable, Sendable {
    public var schritt: AgentSchritt
}

/// LAGE_REQ: Der Kernel fragt, was Kevin gerade sieht.
public struct LageRequestMessage: Decodable, Sendable {
    public var id: String
}

// MARK: - App → Kernel

/// PARTS_REQ: Der Kernel schickt jedes genannte Teil als vollständiges PART_UPSERT; `nil` = alle.
public struct PartsRequestMessage: OutgoingMessage {
    public static let type = "PARTS_REQ"
    public var seq = 0
    public var teile: [String]?

    public init(teile: [String]?) { self.teile = teile }

    enum CodingKeys: String, CodingKey { case type, seq, teile }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(teile, forKey: .teile)  // null = alle
    }
}

/// NOCHMAL: Die App kennt die Basis eines WIE_ZUVOR nicht, der Kernel schickt die neueste Nachricht der Art vollständig.
public struct NochmalMessage: OutgoingMessage {
    public static let type = "NOCHMAL"
    public var seq = 0
    public var art: String

    public init(art: String) { self.art = art }

    enum CodingKeys: String, CodingKey { case type, seq, art }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(art, forKey: .art)
    }
}

/// LAGE: was gerade zu sehen ist, Antwort auf LAGE_REQ. `felder` trägt alles außer `reply_to`, `zeit` und `ms`.
public struct LageMessage: OutgoingMessage {
    public static let type = "LAGE"
    public var seq = 0
    public var replyTo: String
    public var zeit: Double
    public var ms: Double
    public var felder: [String: JSONValue]

    public init(replyTo: String, zeit: Double, ms: Double, felder: [String: JSONValue]) {
        self.replyTo = replyTo
        self.zeit = zeit
        self.ms = ms
        self.felder = felder
    }

    private struct Schluessel: CodingKey {
        var stringValue: String
        var intValue: Int? { nil }
        init(_ s: String) { stringValue = s }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: Schluessel.self)
        try c.encode(Self.type, forKey: Schluessel("type"))
        try c.encode(seq, forKey: Schluessel("seq"))
        try c.encode(replyTo, forKey: Schluessel("reply_to"))
        try c.encode(zeit, forKey: Schluessel("zeit"))
        try c.encode(ms, forKey: Schluessel("ms"))
        for (k, v) in felder { try c.encode(v, forKey: Schluessel(k)) }
    }
}
