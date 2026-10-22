import CoreGraphics
import Foundation

// Anfragen der App an den Kernel (DOKUMENTE.md, Protokoll): DOCS_REQ, DRAWING_REQ, DRAWING_EDIT. Die Operationen von
// DRAWING_EDIT sind als `ZeichnungsOp` getippt; `json` ergibt genau die Felder des Vertrags.

/// DOCS_REQ: alle Blätter rechnen, Antwort DOCS mit `reply_to`.
public struct DocsRequestMessage: OutgoingRequest {
    public static let type = "DOCS_REQ"
    public var seq = 0
    public var id: String

    public init(id: String) { self.id = id }

    enum CodingKeys: String, CodingKey { case type, seq, id }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
    }
}

/// DRAWING_REQ: ein Blatt, Antwort DRAWING mit `reply_to`.
public struct DrawingRequestMessage: OutgoingRequest {
    public static let type = "DRAWING_REQ"
    public var seq = 0
    public var id: String
    public var blatt: String

    public init(id: String, blatt: String) {
        self.id = id
        self.blatt = blatt
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, blatt }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(blatt, forKey: .blatt)
    }
}

/// DRAWING_CREATE (Vertrag 1.2): Blätter anlegen. Ohne `teile` alle gefertigten Teile und den Zusammenbau. Antwort ACK,
/// danach DOCS mit `reply_to`.
public struct DrawingCreateMessage: OutgoingRequest {
    public static let type = "DRAWING_CREATE"
    public var seq = 0
    public var id: String
    public var teile: [String]?
    /// `teil`, `baugruppe` oder `zusammenbau`.
    public var art: String
    /// z. B. „A3“ oder „A4 hoch“; nil = Kev CAD wählt.
    public var format: String?

    public init(id: String, teile: [String]? = nil, art: String = "teil", format: String? = nil) {
        self.id = id
        self.teile = teile
        self.art = art
        self.format = format
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, teile, art, format }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        if let teile { try c.encode(teile, forKey: .teile) }
        try c.encode(art, forKey: .art)
        if let format { try c.encode(format, forKey: .format) }
    }
}

/// DRAWING_EDIT: Operationen auf einem Blatt, `von: "kevin"`. Antwort ACK (mit `ergebnisse`), danach DRAWING.
public struct DrawingEditMessage: OutgoingRequest {
    public static let type = "DRAWING_EDIT"
    public var seq = 0
    public var id: String
    public var blatt: String
    public var ops: [ZeichnungsOp]
    public var von: String

    public init(id: String, blatt: String, ops: [ZeichnungsOp], von: String = "kevin") {
        self.id = id
        self.blatt = blatt
        self.ops = ops
        self.von = von
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, blatt, von, ops }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(blatt, forKey: .blatt)
        try c.encode(von, forKey: .von)
        try c.encode(ops.map(\.json), forKey: .ops)
    }
}

/// Klick in eine Ansicht (Blatt-mm); der Kernel sucht das nächste Element.
public struct ZeichnungsKlick: Equatable, Sendable {
    public var ansicht: String?
    public var punkt: CGPoint

    public init(ansicht: String?, punkt: CGPoint) {
        self.ansicht = ansicht
        self.punkt = punkt
    }

    var json: JSONValue {
        var o: [String: JSONValue] = ["punkt": .array([.number(Double(punkt.x)), .number(Double(punkt.y))])]
        if let ansicht { o["ansicht"] = .string(ansicht) }
        return .object(o)
    }
}

/// Eine Operation von DRAWING_EDIT (DOKUMENTE.md, `DRAWING_EDIT.ops`, dazu `format` und `mass_aendern` aus dem Anhang).
public enum ZeichnungsOp: Equatable, Sendable {
    /// `versatz`: Abstand der Maßlinie (Blatt-mm, Vorzeichen wie im Blatt); `textLage`: Lage der Zahl (Blatt-mm).
    case massVerschieben(id: String, versatz: Double?, textLage: CGPoint?)
    case massLoeschen(id: String)
    /// `bezuege`: Klicks oder vollständige Bezüge (z. B. beim Wiederherstellen eines gelöschten Maßes).
    case massNeu(art: String?, ansicht: String?, richtung: String?, versatz: Double?, klicks: [ZeichnungsKlick],
                 bezuege: [JSONValue], text: String?, toleranz: String?)
    /// `text`: nil = unverändert, "" = Messwert; `fest`: nil = unverändert lassen (der Kernel setzt sonst fest).
    case massAendern(id: String, text: String?, toleranz: String?, fest: Bool?)
    case ansichtNeu(art: String, lage: CGPoint?)
    /// Schnitt aus einer gezogenen Linie (zwei Punkte, Blatt-mm); der Kernel rechnet die Ebene (DOKUMENTE.md 1.3).
    /// `umkehren`: Blick zur anderen Seite als der vorgeschlagenen.
    case schnittNeu(von: String?, linie: [CGPoint], umkehren: Bool = false)
    /// Blickrichtung eines Schnitts umkehren.
    case schnittUmkehren(id: String)
    /// Einzelheit aus einem aufgezogenen Kreis (Mitte und Radius in Blatt-mm); der Kernel wählt den Faktor.
    case einzelheitNeu(von: String?, mitte: CGPoint, radius: Double)
    case ansichtVerschieben(id: String, lage: CGPoint)
    case ansichtLoeschen(id: String)
    case massstab(String)
    case format(String, ausrichtung: String?)
    case notiz(text: String, lage: CGPoint, zeiger: ZeichnungsKlick?)
    case notizLoeschen(id: String)
    case schriftfeld(feld: String, wert: JSONValue)
    case auto(ansichten: Bool?, masse: Bool?, zuruecksetzen: Bool?)
    case unterdrueckungAufheben(index: Int)
    /// Unveränderte Operation (z. B. aus einer neueren Vertragsfassung).
    case roh(JSONValue)

    static func zahl(_ v: Double) -> JSONValue { .number(v) }
    static func punkt(_ p: CGPoint) -> JSONValue { .array([.number(Double(p.x)), .number(Double(p.y))]) }

    /// Name der Operation im Vertrag.
    public var name: String {
        switch self {
        case .massVerschieben: return "mass_verschieben"
        case .massLoeschen: return "mass_loeschen"
        case .massNeu: return "mass_neu"
        case .massAendern: return "mass_aendern"
        case .ansichtNeu, .schnittNeu, .einzelheitNeu: return "ansicht_neu"
        case .schnittUmkehren: return "schnitt_umkehren"
        case .ansichtVerschieben: return "ansicht_verschieben"
        case .ansichtLoeschen: return "ansicht_loeschen"
        case .massstab: return "massstab"
        case .format: return "format"
        case .notiz: return "notiz"
        case .notizLoeschen: return "notiz_loeschen"
        case .schriftfeld: return "schriftfeld"
        case .auto: return "auto"
        case .unterdrueckungAufheben: return "unterdrueckung_aufheben"
        case .roh(let j): return j["op"]?.stringValue ?? "?"
        }
    }

    /// Bezeichnung für „Rückgängig: …“ im Menü Bearbeiten.
    public var titel: String {
        switch self {
        case .massVerschieben(_, let v, let t): return v != nil || t == nil ? "Maß verschieben" : "Maßzahl verschieben"
        case .massLoeschen: return "Maß löschen"
        case .massNeu: return "Neues Maß"
        case .massAendern: return "Maß ändern"
        case .ansichtNeu: return "Ansicht hinzufügen"
        case .schnittNeu: return "Schnitt anlegen"
        case .schnittUmkehren: return "Blickrichtung umkehren"
        case .einzelheitNeu: return "Einzelheit anlegen"
        case .ansichtVerschieben: return "Ansicht verschieben"
        case .ansichtLoeschen: return "Ansicht löschen"
        case .massstab: return "Maßstab ändern"
        case .format: return "Format ändern"
        case .notiz: return "Notiz"
        case .notizLoeschen: return "Notiz löschen"
        case .schriftfeld: return "Schriftfeld ändern"
        case .auto: return "Automatik"
        case .unterdrueckungAufheben: return "Maß wiederherstellen"
        case .roh(let j): return j["op"]?.stringValue ?? "Zeichnung ändern"
        }
    }

    public var json: JSONValue {
        var o: [String: JSONValue] = ["op": .string(name)]
        switch self {
        case .massVerschieben(let id, let versatz, let textLage):
            o["id"] = .string(id)
            if let versatz { o["versatz"] = Self.zahl(versatz) }
            if let textLage { o["text_lage"] = Self.punkt(textLage) }
        case .massLoeschen(let id), .ansichtLoeschen(let id), .notizLoeschen(let id):
            o["id"] = .string(id)
        case .massNeu(let art, let ansicht, let richtung, let versatz, let klicks, let bezuege, let text, let toleranz):
            if let art { o["art"] = .string(art) }
            if let ansicht { o["ansicht"] = .string(ansicht) }
            if let richtung { o["richtung"] = .string(richtung) }
            if let versatz { o["versatz"] = Self.zahl(versatz) }
            o["bezuege"] = .array(klicks.map(\.json) + bezuege)
            if let text { o["text"] = .string(text) }
            if let toleranz { o["toleranz"] = .string(toleranz) }
        case .massAendern(let id, let text, let toleranz, let fest):
            o["id"] = .string(id)
            if let text { o["text"] = .string(text) }
            if let toleranz { o["toleranz"] = .string(toleranz) }
            if let fest { o["fest"] = .bool(fest) }
        case .ansichtNeu(let art, let lage):
            o["art"] = .string(art)
            if let lage { o["lage"] = Self.punkt(lage) }
        case .schnittNeu(let von, let linie, let umkehren):
            o["art"] = "schnitt"
            var sp: [String: JSONValue] = ["linie": .array(linie.map(Self.punkt))]
            if let von { sp["von"] = .string(von) }
            if umkehren { sp["umkehren"] = .bool(true) }
            o["schnitt"] = .object(sp)
        case .schnittUmkehren(let id):
            o["id"] = .string(id)
        case .einzelheitNeu(let von, let mitte, let radius):
            o["art"] = "einzelheit"
            let kreis: [String: JSONValue] = ["mitte": Self.punkt(mitte), "radius": Self.zahl(radius)]
            var ez: [String: JSONValue] = ["kreis": .object(kreis)]
            if let von { ez["von"] = .string(von) }
            o["einzelheit"] = .object(ez)
        case .ansichtVerschieben(let id, let lage):
            o["id"] = .string(id)
            o["lage"] = Self.punkt(lage)
        case .massstab(let wert):
            o["wert"] = .string(wert)
        case .format(let wert, let ausrichtung):
            o["wert"] = .string(wert)
            if let ausrichtung { o["ausrichtung"] = .string(ausrichtung) }
        case .notiz(let text, let lage, let zeiger):
            o["text"] = .string(text)
            o["lage"] = Self.punkt(lage)
            o["zeiger"] = zeiger?.json ?? .null
        case .schriftfeld(let feld, let wert):
            o["feld"] = .string(feld)
            o["wert"] = wert
        case .auto(let ansichten, let masse, let zuruecksetzen):
            if let ansichten { o["ansichten"] = .bool(ansichten) }
            if let masse { o["masse"] = .bool(masse) }
            if let zuruecksetzen { o["zuruecksetzen"] = .bool(zuruecksetzen) }
        case .unterdrueckungAufheben(let index):
            o["index"] = .number(Double(index))
        case .roh(let j):
            return j
        }
        return .object(o)
    }
}

/// Ergebnis einer DRAWING_EDIT-Anfrage (ACK mit `ergebnisse`, je Operation `{op, ok, id?, fehler?}`).
public struct ZeichnungsBearbeitung: Sendable {
    public struct Ergebnis: Sendable {
        public var op: String
        public var ok: Bool
        public var id: String?
        public var fehler: String?
        public var json: JSONValue
    }

    public var ok: Bool
    public var meldung: String?
    public var ergebnisse: [Ergebnis]

    public init(ok: Bool, meldung: String? = nil, ergebnisse: [JSONValue] = []) {
        self.ok = ok
        self.meldung = meldung
        self.ergebnisse = ergebnisse.map { e in
            Ergebnis(
                op: e["op"]?.stringValue ?? "", ok: e["ok"]?.boolValue ?? false, id: e["id"]?.lenientString,
                fehler: e["fehler"]?.lenientString, json: e)
        }
    }

    /// Fehlertexte der gescheiterten Operationen, sonst die Meldung.
    public var fehlerText: String? {
        let f = ergebnisse.filter { !$0.ok }.map { ($0.fehler ?? $0.op) }
        if !f.isEmpty { return f.joined(separator: "; ") }
        return ok ? nil : (meldung ?? "Der Kernel hat die Änderung abgelehnt")
    }
}
