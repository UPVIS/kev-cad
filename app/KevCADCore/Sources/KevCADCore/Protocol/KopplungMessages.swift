import Foundation

// I-6 Live-Kopplung (PROTOCOL.md, Abschnitt „I-6 Live-Kopplung“; PLAN-IPAD.md, Abschnitt 5): Gemeinsame und Eigene
// Ansicht, Führung, Geräteliste, Live-Striche. Alle Felder werden nachsichtig gelesen. Testdateien `ansicht_*.frame`,
// `geraete.frame`, `sprechen_live_*.frame` aus kernel/tools/make_kopplung_fixtures.py.

/// Wie ein Gerät die Ansicht teilt.
public enum AnsichtModus: String, Codable, Sendable, CaseIterable {
    case gemeinsam, eigen
}

/// Grenzen, die Kernel und App gleich führen (`protocol.py`, Abschnitt „I-6 Live-Kopplung“).
public enum KopplungGrenzen {
    /// Nach so langer Ruhe des führenden Geräts darf ein anderes ohne neuen Griff übernehmen (Sekunden).
    public static let fuehrungPause: Double = 1.0
    /// ANSICHT höchstens so oft je Sekunde.
    public static let ansichtJeS: Double = 60
    /// SPRECHEN_LIVE höchstens so oft je Sekunde.
    public static let sprechenLiveJeS: Double = 20
    /// Punkte je Strich in SPRECHEN_LIVE.
    public static let punkteMax = 2000
    public static let textMax = 2000
    /// Schmaler als das (Punkte): Kacheln nebeneinander passen nicht, das Gerät zeigt die geteilten Kacheln dann als große
    /// Kachel (wie `GA.schmalAb` der Oberfläche).
    public static let kachelnNebeneinanderAb: Double = 640
    /// BLICK höchstens so oft je Sekunde.
    public static let blickJeS: Double = 10
}

/// Teile einer ANSICHT; nil = dieser Teil ist nicht dabei (unverändert).
public struct AnsichtStand: Equatable, Sendable {
    public struct Kamera: Codable, Equatable, Sendable {
        /// Quaternion [x, y, z, w] wie `CameraState.rotation`
        public var drehung: [Double]
        public var ziel: [Double]
        public var abstand: Double
        public var projektion: String
        public var fov: Double
        public var orthoHoehe: Double

        public init(drehung: [Double], ziel: [Double], abstand: Double, projektion: String, fov: Double,
                    orthoHoehe: Double) {
            self.drehung = drehung
            self.ziel = ziel
            self.abstand = abstand
            self.projektion = projektion
            self.fov = fov
            self.orthoHoehe = orthoHoehe
        }

        enum CodingKeys: String, CodingKey {
            case drehung, ziel, abstand, projektion, fov
            case orthoHoehe = "ortho_hoehe"
        }
    }

    public struct Sicht: Equatable, Sendable {
        public var verborgen: [String]
        public var isoliert: [String]?

        public init(verborgen: [String], isoliert: [String]?) {
            self.verborgen = verborgen
            self.isoliert = isoliert
        }
    }

    public struct Auswahl: Equatable, Sendable {
        public var run: Int?
        public var refs: [String]

        public init(run: Int?, refs: [String]) {
            self.run = run
            self.refs = refs
        }
    }

    /// Schnittebene wie im Viewport (`ClipPlane`: Normale und Abstand).
    public struct Schnitt: Codable, Equatable, Sendable {
        public var normale: [Double]
        public var abstand: Double

        public init(normale: [Double], abstand: Double) {
            self.normale = normale
            self.abstand = abstand
        }
    }

    /// Leisten und Kacheln wie `LAGE.flaeche`, ohne Rand (der gehört dem Fenster).
    public struct Flaeche: Equatable, Sendable {
        public var kacheln: [String]
        public var gross: String?
        public var aktiv: String?
        public var leisteLinks: Bool
        public var leisteRechts: Bool
        public var zeitleiste: Bool
        public var zweiteAnsicht: String
        public var blatt: String?

        public init(kacheln: [String], gross: String?, aktiv: String?, leisteLinks: Bool, leisteRechts: Bool,
                    zeitleiste: Bool, zweiteAnsicht: String, blatt: String?) {
            self.kacheln = kacheln
            self.gross = gross
            self.aktiv = aktiv
            self.leisteLinks = leisteLinks
            self.leisteRechts = leisteRechts
            self.zeitleiste = zeitleiste
            self.zweiteAnsicht = zweiteAnsicht
            self.blatt = blatt
        }
    }

    public var kamera: Kamera?
    public var sicht: Sicht?
    public var auswahl: Auswahl?
    public var darstellung: String?
    /// `.some(nil)`: kein Schnitt; nil: Teil nicht dabei.
    public var schnitt: Schnitt??
    public var explosion: Double?
    /// Seit 07.11.2026; Apps davor schicken ihn nicht, `voll` verlangt ihn deshalb nicht.
    public var flaeche: Flaeche?

    public init(kamera: Kamera? = nil, sicht: Sicht? = nil, auswahl: Auswahl? = nil, darstellung: String? = nil,
                schnitt: Schnitt?? = nil, explosion: Double? = nil, flaeche: Flaeche? = nil) {
        self.flaeche = flaeche
        self.kamera = kamera
        self.sicht = sicht
        self.auswahl = auswahl
        self.darstellung = darstellung
        self.schnitt = schnitt
        self.explosion = explosion
    }

    /// Alle Teile dabei (`voll`).
    public var vollstaendig: Bool {
        kamera != nil && sicht != nil && auswahl != nil && darstellung != nil && schnitt != nil && explosion != nil
    }

    public var leer: Bool {
        kamera == nil && sicht == nil && auswahl == nil && darstellung == nil && schnitt == nil && explosion == nil
            && flaeche == nil
    }

    /// Teile aus `neu` übernehmen, die dort dabei sind.
    public mutating func uebernehmen(_ neu: AnsichtStand) {
        if let k = neu.kamera { kamera = k }
        if let s = neu.sicht { sicht = s }
        if let a = neu.auswahl { auswahl = a }
        if let d = neu.darstellung { darstellung = d }
        if let s = neu.schnitt { schnitt = .some(s) }
        if let e = neu.explosion { explosion = e }
        if let f = neu.flaeche { flaeche = f }
    }
}

// MARK: - App → Kernel

/// ANSICHT_MODUS: Gemeinsame oder Eigene Ansicht dieses Geräts.
public struct AnsichtModusMessage: OutgoingMessage {
    public static let type = "ANSICHT_MODUS"
    public var seq = 0
    public var modus: AnsichtModus

    public init(modus: AnsichtModus) { self.modus = modus }

    enum CodingKeys: String, CodingKey { case type, seq, modus }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(modus, forKey: .modus)
    }
}

/// AKTIV (I-2): Kevin bedient dieses Gerät (höchstens einmal je Sekunde).
public struct AktivMessage: OutgoingMessage {
    public static let type = "AKTIV"
    public var seq = 0

    public init() {}

    enum CodingKeys: String, CodingKey { case type, seq }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
    }
}

// MARK: - Beide Richtungen

/// ANSICHT: Stand der Gemeinsamen Ansicht. App → Kernel ohne `von`, Kernel → App mit `von` (führendes Gerät).
public struct AnsichtMessage: OutgoingMessage, Decodable, Equatable {
    public static let type = "ANSICHT"
    public var seq = 0
    /// Unix-Zeit beim Senden (Sekunden)
    public var t: Double
    public var griff: Bool
    public var voll: Bool
    public var von: Int?
    public var stand: AnsichtStand

    public init(t: Double, griff: Bool, voll: Bool, stand: AnsichtStand, von: Int? = nil) {
        self.t = t
        self.griff = griff
        self.voll = voll
        self.stand = stand
        self.von = von
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, t, griff, voll, von, kamera, sicht, auswahl, darstellung, schnitt, explosion, flaeche
    }

    private enum FlaecheKeys: String, CodingKey {
        case kacheln, gross, aktiv, zeitleiste, blatt
        case leisteLinks = "leiste_links"
        case leisteRechts = "leiste_rechts"
        case zweiteAnsicht = "zweite_ansicht"
    }

    private enum SichtKeys: String, CodingKey { case verborgen, isoliert }
    private enum AuswahlKeys: String, CodingKey { case run, refs }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(t, forKey: .t)
        try c.encode(griff, forKey: .griff)
        try c.encode(voll, forKey: .voll)
        try c.encodeIfPresent(von, forKey: .von)
        try c.encodeIfPresent(stand.kamera, forKey: .kamera)
        if let s = stand.sicht {
            var n = c.nestedContainer(keyedBy: SichtKeys.self, forKey: .sicht)
            try n.encode(s.verborgen, forKey: .verborgen)
            try n.encode(s.isoliert, forKey: .isoliert)  // null = nicht isoliert
        }
        if let a = stand.auswahl {
            var n = c.nestedContainer(keyedBy: AuswahlKeys.self, forKey: .auswahl)
            try n.encode(a.run, forKey: .run)
            try n.encode(a.refs, forKey: .refs)
        }
        try c.encodeIfPresent(stand.darstellung, forKey: .darstellung)
        if let s = stand.schnitt { try c.encode(s, forKey: .schnitt) }  // .some(nil) = null
        try c.encodeIfPresent(stand.explosion, forKey: .explosion)
        if let f = stand.flaeche {
            var n = c.nestedContainer(keyedBy: FlaecheKeys.self, forKey: .flaeche)
            try n.encode(f.kacheln, forKey: .kacheln)
            try n.encode(f.gross, forKey: .gross)  // null = keine groß
            try n.encode(f.aktiv, forKey: .aktiv)
            try n.encode(f.leisteLinks, forKey: .leisteLinks)
            try n.encode(f.leisteRechts, forKey: .leisteRechts)
            try n.encode(f.zeitleiste, forKey: .zeitleiste)
            try n.encode(f.zweiteAnsicht, forKey: .zweiteAnsicht)
            try n.encode(f.blatt, forKey: .blatt)
        }
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = (try? c.decodeIfPresent(Double.self, forKey: .t)) ?? 0
        griff = (try? c.decodeIfPresent(Bool.self, forKey: .griff)) ?? false
        voll = (try? c.decodeIfPresent(Bool.self, forKey: .voll)) ?? false
        von = try? c.decodeIfPresent(Int.self, forKey: .von)
        var s = AnsichtStand()
        s.kamera = try? c.decodeIfPresent(AnsichtStand.Kamera.self, forKey: .kamera)
        if let n = try? c.nestedContainer(keyedBy: SichtKeys.self, forKey: .sicht) {
            s.sicht = .init(verborgen: (try? n.decodeIfPresent([String].self, forKey: .verborgen)) ?? [],
                            isoliert: (try? n.decodeIfPresent([String].self, forKey: .isoliert)) ?? nil)
        }
        if let n = try? c.nestedContainer(keyedBy: AuswahlKeys.self, forKey: .auswahl) {
            s.auswahl = .init(run: (try? n.decodeIfPresent(Int.self, forKey: .run)) ?? nil,
                              refs: (try? n.decodeIfPresent([String].self, forKey: .refs)) ?? [])
        }
        s.darstellung = try? c.decodeIfPresent(String.self, forKey: .darstellung)
        if c.contains(.schnitt) {
            s.schnitt = .some((try? c.decodeIfPresent(AnsichtStand.Schnitt.self, forKey: .schnitt)) ?? nil)
        }
        s.explosion = try? c.decodeIfPresent(Double.self, forKey: .explosion)
        if let n = try? c.nestedContainer(keyedBy: FlaecheKeys.self, forKey: .flaeche),
           let kacheln = try? n.decode([String].self, forKey: .kacheln) {
            let gross: String? = (try? n.decodeIfPresent(String.self, forKey: .gross)) ?? nil
            let aktiv: String? = (try? n.decodeIfPresent(String.self, forKey: .aktiv)) ?? nil
            let blatt: String? = (try? n.decodeIfPresent(String.self, forKey: .blatt)) ?? nil
            let links: Bool = (try? n.decodeIfPresent(Bool.self, forKey: .leisteLinks)) ?? true
            let rechts: Bool = (try? n.decodeIfPresent(Bool.self, forKey: .leisteRechts)) ?? false
            let zeitleiste: Bool = (try? n.decodeIfPresent(Bool.self, forKey: .zeitleiste)) ?? false
            let zweite: String = (try? n.decodeIfPresent(String.self, forKey: .zweiteAnsicht)) ?? "top"
            s.flaeche = AnsichtStand.Flaeche(kacheln: kacheln, gross: gross, aktiv: aktiv, leisteLinks: links,
                                             leisteRechts: rechts, zeitleiste: zeitleiste, zweiteAnsicht: zweite,
                                             blatt: blatt)
        }
        stand = s
    }
}

/// SPRECHEN_LIVE: Striche, Zeiger und Text beim Sprechen, live an die anderen Geräte.
public struct SprechenLiveMessage: OutgoingMessage, Decodable, Equatable {
    public static let type = "SPRECHEN_LIVE"

    public struct Strich: Codable, Equatable, Sendable {
        public var nr: Int
        /// Weltpunkte in mm
        public var punkte: [[Double]]
        public var fertig: Bool

        public init(nr: Int, punkte: [[Double]], fertig: Bool) {
            self.nr = nr
            self.punkte = punkte
            self.fertig = fertig
        }
    }

    public var seq = 0
    public var sitzung: String
    public var strich: Strich?
    /// `.some(nil)`: Zeiger neben dem Modell; nil: nicht dabei.
    public var zeiger: [Double]??
    public var text: String?
    public var ende: Bool
    public var von: Int?

    public init(sitzung: String, strich: Strich? = nil, zeiger: [Double]?? = nil, text: String? = nil,
                ende: Bool = false, von: Int? = nil) {
        self.sitzung = sitzung
        self.strich = strich
        self.zeiger = zeiger
        self.text = text
        self.ende = ende
        self.von = von
    }

    enum CodingKeys: String, CodingKey { case type, seq, sitzung, strich, zeiger, text, ende, von }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(sitzung, forKey: .sitzung)
        try c.encodeIfPresent(strich, forKey: .strich)
        if let z = zeiger { try c.encode(z, forKey: .zeiger) }
        try c.encodeIfPresent(text, forKey: .text)
        if ende { try c.encode(true, forKey: .ende) }
        try c.encodeIfPresent(von, forKey: .von)
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sitzung = (try? c.decodeIfPresent(String.self, forKey: .sitzung)) ?? ""
        strich = try? c.decodeIfPresent(Strich.self, forKey: .strich)
        if c.contains(.zeiger) { zeiger = .some((try? c.decodeIfPresent([Double].self, forKey: .zeiger)) ?? nil) }
        text = try? c.decodeIfPresent(String.self, forKey: .text)
        ende = (try? c.decodeIfPresent(Bool.self, forKey: .ende)) ?? false
        von = try? c.decodeIfPresent(Int.self, forKey: .von)
    }
}

/// BLICK: Kamera und Seitenverhältnis eines Geräts für den Rahmen „wo schaut das iPad hin“ in der Eigenen Ansicht.
/// App → Kernel ohne `von`, Kernel → App mit `von`.
public struct BlickMessage: OutgoingMessage, Decodable, Equatable {
    public static let type = "BLICK"
    public var seq = 0
    public var kamera: AnsichtStand.Kamera
    /// Breite durch Höhe der Ansicht
    public var seiten: Double
    public var von: Int?

    public init(kamera: AnsichtStand.Kamera, seiten: Double, von: Int? = nil) {
        self.kamera = kamera
        self.seiten = seiten
        self.von = von
    }

    enum CodingKeys: String, CodingKey { case type, seq, kamera, seiten, von }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(kamera, forKey: .kamera)
        try c.encode(seiten, forKey: .seiten)
        try c.encodeIfPresent(von, forKey: .von)
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kamera = try c.decode(AnsichtStand.Kamera.self, forKey: .kamera)
        seiten = (try? c.decodeIfPresent(Double.self, forKey: .seiten)) ?? 1.6
        von = try? c.decodeIfPresent(Int.self, forKey: .von)
    }
}

// MARK: - Kernel → App

/// Ein verbundenes Gerät aus GERAETE.
public struct GeraetEintrag: Decodable, Equatable, Identifiable, Sendable {
    public var nr: Int
    public var art: String
    public var name: String?
    public var aktiv: Bool
    public var ansicht: AnsichtModus?
    public var fuehrt: Bool
    public var ich: Bool

    public var id: Int { nr }
    public var istIPad: Bool { art == "ipad" }
    /// Name für die Oberfläche („iPad von Kevin“, sonst „iPad“ oder „Mac“).
    public var anzeigeName: String { name.flatMap { $0.isEmpty ? nil : $0 } ?? (istIPad ? "iPad" : "Mac") }

    public init(nr: Int, art: String, name: String?, aktiv: Bool, ansicht: AnsichtModus?, fuehrt: Bool, ich: Bool) {
        self.nr = nr
        self.art = art
        self.name = name
        self.aktiv = aktiv
        self.ansicht = ansicht
        self.fuehrt = fuehrt
        self.ich = ich
    }

    enum CodingKeys: String, CodingKey { case nr, art, name, aktiv, ansicht, fuehrt, ich }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nr = try c.decode(Int.self, forKey: .nr)
        art = (try? c.decodeIfPresent(String.self, forKey: .art)) ?? "mac"
        name = try? c.decodeIfPresent(String.self, forKey: .name)
        aktiv = (try? c.decodeIfPresent(Bool.self, forKey: .aktiv)) ?? false
        ansicht = (try? c.decodeIfPresent(String.self, forKey: .ansicht)).flatMap { AnsichtModus(rawValue: $0) }
        fuehrt = (try? c.decodeIfPresent(Bool.self, forKey: .fuehrt)) ?? false
        ich = (try? c.decodeIfPresent(Bool.self, forKey: .ich)) ?? false
    }
}

/// GERAETE: verbundene Geräte mit Ansicht und Führung, aus Sicht dieses Empfängers (`ich`).
public struct GeraeteMessage: Decodable, Equatable, Sendable {
    public var geraete: [GeraetEintrag]

    public init(geraete: [GeraetEintrag]) { self.geraete = geraete }
}

/// Nachrichten aus I-6 an die App.
public enum KopplungNachricht: Sendable {
    case geraete(GeraeteMessage)
    case ansicht(AnsichtMessage)
    case sprechenLive(SprechenLiveMessage)
    case blick(BlickMessage)

    public static let types: Set<String> = ["GERAETE", "ANSICHT", "SPRECHEN_LIVE", "BLICK"]

    public var typeName: String {
        switch self {
        case .geraete: return "GERAETE"
        case .ansicht: return "ANSICHT"
        case .sprechenLive: return "SPRECHEN_LIVE"
        case .blick: return "BLICK"
        }
    }

    public static func decode(type: String, header: Data) throws -> KopplungNachricht {
        let dec = JSONDecoder()
        switch type {
        case "GERAETE": return .geraete(try dec.decode(GeraeteMessage.self, from: header))
        case "ANSICHT": return .ansicht(try dec.decode(AnsichtMessage.self, from: header))
        case "BLICK": return .blick(try dec.decode(BlickMessage.self, from: header))
        default: return .sprechenLive(try dec.decode(SprechenLiveMessage.self, from: header))
        }
    }
}
