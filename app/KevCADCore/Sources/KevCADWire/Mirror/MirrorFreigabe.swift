import Foundation

// Freigabe vom iPhone (MIRROR.md, Version 1.1, rein additiv; Kevin am 22.10.2026 über KevCup).
//
// Vorschläge von Claude im Lagerkatalog gibt nur Kevin frei. Die Freigabe vom iPhone läuft deshalb am Agenten vorbei,
// direkt zwischen der VoiceBridge-App und Kev CAD über den Spiegel-Socket:
//
// - FREIGABE (Kev CAD → VoiceBridge): eine offene Anfrage (`freigabe_anfragen` eines Agenten hat den Dialog im
//   Projektfenster geöffnet), mit Nonce und Ablauf. Geht ohne Miete an jede geprüfte Gegenstelle, nach dem HELLO auch
//   alle noch offenen.
// - CMD `op: "freigabe"` (VoiceBridge → Kev CAD): Kevins Entscheidung zu einem Eintrag; Antwort CMD_RES mit `status`.
// - FREIGABE_ENDE (Kev CAD → VoiceBridge): ein Eintrag (mit `id`) oder die ganze Anfrage (ohne `id`) ist erledigt.
//
// Alle Typen lesen tolerant und schreiben genau die Felder aus MIRROR.md.

extension MirrorProtocol {
    /// Merkmal im HELLO von Kev CAD: kennt FREIGABE, FREIGABE_ENDE und CMD `freigabe`.
    public static let freigabeFeature = "freigabe-1"
    /// Eine Anfrage gilt höchstens so lange (danach FREIGABE_ENDE mit `grund: "abgelaufen"`).
    public static let freigabeLaufzeit: TimeInterval = 24 * 60 * 60
    /// Länge der Nonce in Byte (128 Bit, als 32 Hex-Zeichen auf der Leitung).
    public static let freigabeNonceBytes = 16
    /// `freigegeben_von` im Katalogeintrag, wenn Kevin vom iPhone freigibt.
    public static let freigabeVonIPhone = "Kevin (iPhone)"
}

/// Kevins Entscheidung zu einem Eintrag.
public enum MirrorFreigabeEntscheidung: String, Codable, Sendable, CaseIterable {
    /// Freigeben: der Eintrag ist danach verbaubar (`status: "frei"`).
    case frei
    /// Ablehnen: der Vorschlag wird aus dem Katalog gelöscht.
    case abgelehnt
}

/// Ein Vorschlag in einer Freigabe-Anfrage, so knapp, dass er auf eine Karte passt.
public struct MirrorFreigabeEintrag: Codable, Equatable, Sendable {
    /// Katalog-ID des Vorschlags.
    public var id: String
    /// `teil` (Lagerteil, Zukaufteil) oder `material`.
    public var kind: String
    public var name: String
    /// Art des Lagerteils (`rohr`, `zukaufteil`, …) bzw. `material`.
    public var art: String
    /// Kurzdaten in einer Zeile: Maße, Preis, Händler („d 16 · s 1 mm · 4,20 €/m · ALFER“); leer, wenn nichts bekannt.
    public var kurz: String
    /// Link zum Produkt, nur `https` (sonst nil und auf der Leitung weggelassen).
    public var link: String?
    /// Wofür der Agent die Teile braucht (eine Zeile) oder nil.
    public var grund: String?
    /// Name des offenen Projekts (nie der Pfad) oder nil.
    public var projekt: String?

    public init(
        id: String, kind: String, name: String, art: String, kurz: String = "", link: String? = nil,
        grund: String? = nil, projekt: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.name = name
        self.art = art
        self.kurz = kurz
        self.link = Self.httpsLink(link)
        self.grund = grund
        self.projekt = projekt
    }

    /// Nur `https` mit Rechnername gilt als Link, alles andere fällt weg.
    public static func httpsLink(_ text: String?) -> String? {
        guard let t = text?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty,
            let u = URL(string: t), u.scheme?.lowercased() == "https", let host = u.host, !host.isEmpty
        else { return nil }
        return t
    }

    enum CodingKeys: String, CodingKey { case id, kind, name, art, kurz, link, grund, projekt }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "teil"
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? id
        art = (try? c.decodeIfPresent(String.self, forKey: .art)) ?? ""
        kurz = (try? c.decodeIfPresent(String.self, forKey: .kurz)) ?? ""
        link = Self.httpsLink(try? c.decodeIfPresent(String.self, forKey: .link))
        grund = try? c.decodeIfPresent(String.self, forKey: .grund)
        projekt = try? c.decodeIfPresent(String.self, forKey: .projekt)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(kind, forKey: .kind)
        try c.encode(name, forKey: .name)
        try c.encode(art, forKey: .art)
        try c.encode(kurz, forKey: .kurz)
        try c.encodeIfPresent(Self.httpsLink(link), forKey: .link)
        try c.encode(grund, forKey: .grund)
        try c.encode(projekt, forKey: .projekt)
    }
}

/// FREIGABE (Kev CAD → VoiceBridge): eine offene Anfrage mit ihren Einträgen.
public struct MirrorFreigabeMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "FREIGABE"
    public var prio: MirrorPriority { .zustand }

    public var epoche: String
    /// Kennung der Anfrage, eindeutig je Programmstart von Kev CAD.
    public var anfrageID: String
    /// 128 Bit Zufall (32 Hex-Zeichen), einmalig je Anfrage; gehört in jedes CMD `freigabe` dieser Anfrage. Nur im
    /// Speicher halten und nie protokollieren.
    public var nonce: String
    /// Ablaufzeitpunkt, ISO 8601 in UTC („2026-10-23T14:03:12Z“), 24 h nach der Anfrage.
    public var ablauf: String
    /// Noch offene Einträge (schon entschiedene fehlen).
    public var eintraege: [MirrorFreigabeEintrag]

    public init(epoche: String, anfrageID: String, nonce: String, ablauf: String, eintraege: [MirrorFreigabeEintrag]) {
        self.epoche = epoche
        self.anfrageID = anfrageID
        self.nonce = nonce
        self.ablauf = ablauf
        self.eintraege = eintraege
    }

    /// `ablauf` als Datum (nil, wenn unlesbar).
    public var ablaufDatum: Date? { MirrorFreigabeZeit.datum(ablauf) }

    /// Abgelaufen zum Zeitpunkt `now` (ein unlesbarer Ablauf gilt als abgelaufen).
    public func abgelaufen(now: Date = Date()) -> Bool { (ablaufDatum.map { now >= $0 }) ?? true }

    enum CodingKeys: String, CodingKey {
        case epoche, nonce, ablauf, eintraege
        case anfrageID = "anfrage_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        anfrageID = (try? c.decodeIfPresent(String.self, forKey: .anfrageID)) ?? ""
        nonce = (try? c.decodeIfPresent(String.self, forKey: .nonce)) ?? ""
        ablauf = (try? c.decodeIfPresent(String.self, forKey: .ablauf)) ?? ""
        eintraege = (try? c.decodeIfPresent([MirrorFreigabeEintrag].self, forKey: .eintraege)) ?? []
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(anfrageID, forKey: .anfrageID)
        try c.encode(nonce, forKey: .nonce)
        try c.encode(ablauf, forKey: .ablauf)
        try c.encode(eintraege, forKey: .eintraege)
    }
}

/// FREIGABE_ENDE (Kev CAD → VoiceBridge): Mit `id` ist ein Eintrag erledigt, ohne `id` die ganze Anfrage. Die Karte
/// auf dem iPhone verschwindet sofort; die Nonce gilt für den Eintrag bzw. die Anfrage nicht mehr.
public struct MirrorFreigabeEndeMessage: MirrorOutgoing, Decodable, Equatable {
    public static let type = "FREIGABE_ENDE"
    public var prio: MirrorPriority { .zustand }

    public enum Grund: String, Codable, Sendable, CaseIterable {
        /// Kevin hat am Mac entschieden (Dialog, Lagerkatalog) oder den Dialog geschlossen.
        case mac
        /// Vom iPhone entschieden (CMD `freigabe`).
        case iphone
        /// 24 h ohne Entscheidung.
        case abgelaufen
        /// Eine neue Anfrage hat diese ersetzt, oder der Agent hat sie zurückgezogen.
        case zurueckgezogen
    }

    public var epoche: String
    public var anfrageID: String
    /// Katalog-ID des erledigten Eintrags; nil = die ganze Anfrage ist erledigt.
    public var id: String?
    public var grund: Grund
    /// Nur mit `id`: `frei` oder `abgelehnt`.
    public var ergebnis: MirrorFreigabeEntscheidung?

    public init(
        epoche: String, anfrageID: String, id: String? = nil, grund: Grund, ergebnis: MirrorFreigabeEntscheidung? = nil
    ) {
        self.epoche = epoche
        self.anfrageID = anfrageID
        self.id = id
        self.grund = grund
        self.ergebnis = id == nil ? nil : ergebnis
    }

    enum CodingKeys: String, CodingKey {
        case epoche, id, grund, ergebnis
        case anfrageID = "anfrage_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        epoche = (try? c.decodeIfPresent(String.self, forKey: .epoche)) ?? ""
        anfrageID = (try? c.decodeIfPresent(String.self, forKey: .anfrageID)) ?? ""
        id = try? c.decodeIfPresent(String.self, forKey: .id)
        // Unbekannter Grund (neuere Version): die Karte verschwindet trotzdem
        grund = (try? c.decodeIfPresent(Grund.self, forKey: .grund)) ?? .zurueckgezogen
        ergebnis = try? c.decodeIfPresent(MirrorFreigabeEntscheidung.self, forKey: .ergebnis)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(epoche, forKey: .epoche)
        try c.encode(anfrageID, forKey: .anfrageID)
        try c.encodeIfPresent(id, forKey: .id)
        try c.encode(grund, forKey: .grund)
        if id != nil { try c.encodeIfPresent(ergebnis, forKey: .ergebnis) }
    }
}

/// `status` im CMD_RES auf ein CMD `freigabe`.
public enum MirrorFreigabeStatus: String, Codable, Sendable, CaseIterable {
    /// Freigegeben und im neu geladenen Katalog bestätigt (`ok: true`).
    case frei
    /// Abgelehnt: aus dem Katalog gelöscht und bestätigt (`ok: true`).
    case abgelehnt
    /// War schon freigegeben (am Mac oder anderswo).
    case schonFrei = "schon_frei"
    /// Steht nicht mehr im Katalog.
    case fehlt
    /// `anfrage_id`, `nonce`, `id` oder `entscheidung` passen nicht.
    case ungueltig
    /// Dieser Eintrag ist mit dieser Nonce schon entschieden oder wird gerade ausgeführt (Wiederholung).
    case verbraucht
    /// Die Anfrage ist abgelaufen (24 h).
    case abgelaufen
    /// Die Anfrage ist erledigt (am Mac geschlossen, ersetzt, alle Einträge entschieden).
    case beendet
    /// Die Gegenstelle ist nicht die VoiceBridge-App (Signatur, Argumente) und darf nicht freigeben.
    case nichtErlaubt = "nicht_erlaubt"
    /// Kernel oder Katalog hat abgelehnt, ist nicht verbunden oder hat nicht bestätigt; `fehler` nennt den Grund.
    case katalogfehler
}

/// Argumente eines CMD `freigabe`.
public struct MirrorFreigabeBefehl: Equatable, Sendable {
    public var anfrageID: String
    public var nonce: String
    /// Katalog-ID des Eintrags.
    public var id: String
    /// nil, wenn `entscheidung` fehlt oder unbekannt ist.
    public var entscheidung: MirrorFreigabeEntscheidung?

    public init(anfrageID: String, nonce: String, id: String, entscheidung: MirrorFreigabeEntscheidung?) {
        self.anfrageID = anfrageID
        self.nonce = nonce
        self.id = id
        self.entscheidung = entscheidung
    }
}

extension MirrorCommand {
    /// Kevins Entscheidung vom iPhone zu einem Eintrag einer Anfrage (FREIGABE); Antwort CMD_RES mit `status`.
    public static func freigabe(
        id: String, anfrageID: String, nonce: String, eintrag: String, entscheidung: MirrorFreigabeEntscheidung
    ) -> MirrorCommand {
        MirrorCommand(
            id: id, op: Op.freigabe.rawValue,
            args: .object([
                "anfrage_id": .string(anfrageID), "nonce": .string(nonce), "id": .string(eintrag),
                "entscheidung": .string(entscheidung.rawValue),
            ]))
    }

    /// Die Argumente eines CMD `freigabe` (leere Texte, wenn Felder fehlen).
    public var freigabeBefehl: MirrorFreigabeBefehl {
        MirrorFreigabeBefehl(
            anfrageID: args["anfrage_id"]?.stringValue ?? "", nonce: args["nonce"]?.stringValue ?? "",
            id: args["id"]?.stringValue ?? "",
            entscheidung: args["entscheidung"]?.stringValue.flatMap(MirrorFreigabeEntscheidung.init(rawValue:)))
    }
}

extension MirrorCommandResult {
    /// Antwort auf ein CMD `freigabe`.
    public static func freigabe(replyTo: String, status: MirrorFreigabeStatus, fehler: String? = nil)
        -> MirrorCommandResult
    {
        MirrorCommandResult(
            replyTo: replyTo, ok: status == .frei || status == .abgelehnt, fehler: fehler, status: status.rawValue)
    }

    /// `status` als bekannter Wert.
    public var freigabeStatus: MirrorFreigabeStatus? { status.flatMap(MirrorFreigabeStatus.init(rawValue:)) }
}

/// Zeitangaben der Freigabe (ISO 8601 in UTC, ganze Sekunden).
public enum MirrorFreigabeZeit {
    public static func text(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: date)
    }

    public static func datum(_ text: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        if let d = f.date(from: text) { return d }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: text)
    }
}
