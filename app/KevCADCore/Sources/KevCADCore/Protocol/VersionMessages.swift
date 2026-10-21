import Foundation
import simd

// Versionen (PROTOCOL.md Abschnitt „Versionen“): VERSIONEN, VERSION_VERGLEICH, VERSION_BILD_REQ (Kernel → App) und die
// Anfragen der App. Gemeinsam als `KernelMessage.versionen(VersionMessage)`, damit Messages.swift und AppController nur
// eine Stelle dafür brauchen. Alle Felder werden nachsichtig gelesen (fehlende Felder haben Vorgaben).

public struct VersionBildAnfrage: Sendable {
    public struct Teil: Sendable {
        public var teil: String
        /// sRGB, wie in model.py
        public var farbe: SIMD4<Float>
        public var netz: VergleichsNetz
    }

    public var id: String
    public var nr: Int
    public var width: Int
    public var height: Int
    public var view: String
    public var teile: [Teil]
}

public enum VersionMessage: Sendable {
    case liste(VersionenStand, replyTo: String?)
    case vergleich(VersionVergleich, replyTo: String?)
    case bildAnfrage(VersionBildAnfrage)

    public static let types: Set<String> = ["VERSIONEN", "VERSION_VERGLEICH", "VERSION_BILD_REQ"]

    public enum DecodeError: Error, CustomStringConvertible {
        case payload(String)
        public var description: String {
            switch self {
            case .payload(let s): return "Versionen: \(s)"
            }
        }
    }

    public var typeName: String {
        switch self {
        case .liste: return "VERSIONEN"
        case .vergleich: return "VERSION_VERGLEICH"
        case .bildAnfrage: return "VERSION_BILD_REQ"
        }
    }

    public var replyTo: String? {
        switch self {
        case .liste(_, let r), .vergleich(_, let r): return r
        case .bildAnfrage: return nil
        }
    }

    public static func decode(type: String, frame: Frame) throws -> VersionMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        switch type {
        case "VERSIONEN":
            return .liste(stand(json), replyTo: json["reply_to"]?.stringValue)
        case "VERSION_VERGLEICH":
            let netze = try decodeNetze(json["geometrie"]?.arrayValue ?? [], payload: frame.payload)
            return .vergleich(vergleich(json, netze: netze.map(\.1)), replyTo: json["reply_to"]?.stringValue)
        default:
            let netze = try decodeNetze(json["teile"]?.arrayValue ?? [], payload: frame.payload)
            let teile = netze.map { kopf, netz in
                VersionBildAnfrage.Teil(
                    teil: kopf["teil"]?.stringValue ?? netz.teil, farbe: kopf["farbe"]?.vector4 ?? SIMD4(0.72, 0.75, 0.79, 1),
                    netz: netz)
            }
            return .bildAnfrage(
                VersionBildAnfrage(
                    id: json["id"]?.stringValue ?? "", nr: json["nr"]?.intValue ?? 0, width: json["width"]?.intValue ?? 288,
                    height: json["height"]?.intValue ?? 180, view: json["view"]?.stringValue ?? "iso", teile: teile))
        }
    }

    // MARK: VERSIONEN

    static func stand(_ j: JSONValue) -> VersionenStand {
        let versionen = (j["versionen"]?.arrayValue ?? []).compactMap(version)
        let gruppen = (j["gruppen"]?.arrayValue ?? []).compactMap { g -> VersionGruppe? in
            guard let id = g["id"]?.stringValue else { return nil }
            return VersionGruppe(
                id: id, anzahl: g["anzahl"]?.intValue ?? 0, neueste: g["neueste"]?.intValue ?? 0,
                aelteste: g["aelteste"]?.intValue ?? 0, text: g["text"]?.stringValue ?? "")
        }
        let varianten = (j["varianten"]?.arrayValue ?? []).compactMap { v -> VersionVariante? in
            guard let id = v["id"]?.stringValue else { return nil }
            return VersionVariante(
                id: id, name: v["name"]?.stringValue ?? id, aktuell: v["aktuell"]?.boolValue ?? false,
                versionen: v["versionen"]?.intValue ?? 0, von: v["von"]?.intValue)
        }
        return VersionenStand(
            projekt: j["projekt"]?.stringValue ?? "", verfuegbar: j["verfuegbar"]?.boolValue ?? true,
            meldung: j["meldung"]?.stringValue, variante: j["variante"]?.stringValue ?? "haupt", varianten: varianten,
            versionen: versionen, gruppen: gruppen, anzahl: j["anzahl"]?.intValue ?? versionen.count,
            meilensteine: j["meilensteine"]?.intValue ?? versionen.filter { $0.meilenstein != nil }.count,
            ungesichert: j["ungesichert"]?.boolValue ?? false)
    }

    static func version(_ v: JSONValue) -> VersionEintrag? {
        guard let nr = v["nr"]?.intValue else { return nil }
        var params: [String: Double] = [:]
        for (k, w) in v["params"]?.objectValue ?? [:] {
            if let d = w.doubleValue { params[k] = d }
        }
        let ms = v["meilenstein"].flatMap { m -> VersionMeilenstein? in
            guard let t = m["titel"]?.stringValue else { return nil }
            return VersionMeilenstein(titel: t, notiz: m["notiz"]?.stringValue ?? "", wer: m["wer"]?.stringValue)
        }
        return VersionEintrag(
            nr: nr, commit: v["commit"]?.stringValue ?? "",
            zeit: Date(timeIntervalSince1970: v["ts"]?.doubleValue ?? 0),
            wer: VersionEintrag.Wer(rawValue: v["wer"]?.stringValue ?? "") ?? .unbekannt,
            werText: v["wer_text"]?.stringValue ?? "", quelle: v["quelle"]?.stringValue ?? "lauf",
            titel: v["titel"]?.stringValue ?? "", aus: v["aus"]?.intValue, meilenstein: ms,
            kennzahlen: v["kennzahlen"].flatMap(kennzahlen), params: params,
            bild: v["bild"]?.stringValue.map { URL(fileURLWithPath: $0) }, aktuell: v["aktuell"]?.boolValue ?? false,
            geerbt: v["geerbt"]?.boolValue ?? false, dateien: v["dateien"]?.stringList ?? [],
            gruppe: v["gruppe"]?.stringValue, nachberechnung: v["nachberechnung"]?.stringValue)
    }

    static func kennzahlen(_ k: JSONValue) -> VersionKennzahlen? {
        guard k.objectValue != nil else { return nil }
        return VersionKennzahlen(
            teile: k["teile"]?.intValue ?? 0, masseKg: k["masse_kg"]?.doubleValue, kosten: k["kosten"]?.doubleValue,
            positionen: k["positionen"]?.intValue, fehler: k["fehler"]?.intValue, warnungen: k["warnungen"]?.intValue,
            pruefung: k["pruefung"]?.stringValue)
    }

    // MARK: VERSION_VERGLEICH

    static func vergleich(_ j: JSONValue, netze: [VergleichsNetz]) -> VersionVergleich {
        func seite(_ s: JSONValue?) -> VersionVergleich.Seite {
            VersionVergleich.Seite(
                nr: s?["nr"]?.intValue, titel: s?["titel"]?.stringValue ?? "", zeit: s?["zeit"]?.stringValue,
                kennzahlen: s?["kennzahlen"].flatMap(kennzahlen))
        }
        func zeile(_ z: JSONValue) -> StuecklistenAenderung {
            StuecklistenAenderung(
                benennung: z["benennung"]?.stringValue ?? "", masseText: z["masse_text"]?.stringValue,
                anzahl: z["anzahl"]?.intValue, altAnzahl: z["alt_anzahl"]?.intValue,
                neuAnzahl: z["neu_anzahl"]?.intValue, altMasseText: z["alt_masse_text"]?.stringValue,
                preis: z["preis"]?.doubleValue, altPreis: z["alt_preis"]?.doubleValue)
        }
        let teile = j["teile"]
        let sl = j["stueckliste"]
        let pa = j["pruefung"]?["alt"], pb = j["pruefung"]?["neu"]
        let code = j["code"]
        let params = (j["params"]?.arrayValue ?? []).compactMap { p -> ParameterAenderung? in
            guard let n = p["name"]?.stringValue else { return nil }
            return ParameterAenderung(
                name: n, alt: p["alt"]?.doubleValue, neu: p["neu"]?.doubleValue, art: p["art"]?.stringValue ?? "geaendert")
        }
        let geaendert = (teile?["geaendert"]?.arrayValue ?? []).compactMap { g -> TeilAenderung? in
            guard let n = g["name"]?.stringValue else { return nil }
            return TeilAenderung(
                name: n, arten: g["arten"]?.stringList ?? [], dvolumen: g["dvolumen"]?.doubleValue,
                dmasse: g["dmasse"]?.doubleValue)
        }
        let dateien = (code?["dateien"]?.arrayValue ?? []).compactMap { d -> CodeDatei? in
            guard let p = d["pfad"]?.stringValue else { return nil }
            return CodeDatei(
                pfad: p, status: d["status"]?.stringValue ?? "M", plus: d["plus"]?.intValue, minus: d["minus"]?.intValue,
                binaer: d["binaer"]?.boolValue ?? false)
        }
        func pruefText(_ p: JSONValue?) -> String? {
            guard let p, p.objectValue != nil else { return nil }
            let z = p["zusammenfassung"]?.stringValue ?? ""
            return z.isEmpty ? "in Ordnung" : z
        }
        return VersionVergleich(
            a: seite(j["a"]), b: seite(j["b"]), aktuell: j["aktuell"]?.boolValue ?? (j["b"]?["nr"]?.intValue == nil),
            zusammenfassung: j["zusammenfassung"]?.stringValue ?? "", params: params,
            teileNeu: teile?["neu"]?.stringList ?? [], teileWeg: teile?["weg"]?.stringList ?? [],
            teileGeaendert: geaendert, teileGleich: teile?["gleich"]?.intValue ?? 0,
            stuecklisteNeu: (sl?["neu"]?.arrayValue ?? []).map(zeile),
            stuecklisteWeg: (sl?["weg"]?.arrayValue ?? []).map(zeile),
            stuecklisteGeaendert: (sl?["geaendert"]?.arrayValue ?? []).map(zeile),
            pruefungAlt: pruefText(pa), pruefungNeu: pruefText(pb), fehlerAlt: pa?["zaehler"]?["fehler"]?.intValue,
            fehlerNeu: pb?["zaehler"]?["fehler"]?.intValue,
            kennzahlenAlt: j["kennzahlen"]?["alt"].flatMap(kennzahlen),
            kennzahlenNeu: j["kennzahlen"]?["neu"].flatMap(kennzahlen), codeDateien: dateien,
            diff: code?["diff"]?.stringValue ?? "", diffGekuerzt: code?["gekuerzt"]?.boolValue ?? false,
            hinweise: j["hinweise"]?.stringList ?? [], ms: j["ms"]?.intValue ?? 0, geometrie: netze)
    }

    // MARK: Netze (Nutzlast)

    /// Je Kopf positions f32 (vert × 3), normals f32 (vert × 3), triangles u32 (tri × 3), edge_points f32 (epts × 3),
    /// edge_offsets u32 (edge + 1), wie `protocol.pack_netze`.
    static func decodeNetze(_ koepfe: [JSONValue], payload: Data) throws -> [(JSONValue, VergleichsNetz)] {
        var offset = 0
        func floats(_ n: Int) throws -> [Float] {
            let bytes = n * 4
            guard n >= 0, offset + bytes <= payload.count else { throw DecodeError.payload("Nutzlast zu kurz") }
            var arr = [Float](repeating: 0, count: n)
            _ = arr.withUnsafeMutableBytes { payload.copyBytes(to: $0, from: (payload.startIndex + offset)..<(payload.startIndex + offset + bytes)) }
            offset += bytes
            return arr.map { Float(bitPattern: UInt32(littleEndian: $0.bitPattern)) }
        }
        func uints(_ n: Int) throws -> [UInt32] {
            let bytes = n * 4
            guard n >= 0, offset + bytes <= payload.count else { throw DecodeError.payload("Nutzlast zu kurz") }
            var arr = [UInt32](repeating: 0, count: n)
            _ = arr.withUnsafeMutableBytes { payload.copyBytes(to: $0, from: (payload.startIndex + offset)..<(payload.startIndex + offset + bytes)) }
            offset += bytes
            return arr.map { UInt32(littleEndian: $0) }
        }
        var out: [(JSONValue, VergleichsNetz)] = []
        for k in koepfe {
            let nv = k["vert"]?.intValue ?? 0, nt = k["tri"]?.intValue ?? 0
            let ne = k["epts"]?.intValue ?? 0, nk = k["edge"]?.intValue ?? 0
            let pos = try floats(nv * 3)
            let nrm = try floats(nv * 3)
            let tri = try uints(nt * 3)
            let ept = try floats(ne * 3)
            let eof = try uints(nk + 1)
            if let bad = tri.first(where: { Int($0) >= nv }) {
                throw DecodeError.payload("Dreiecksindex \(bad) außerhalb von \(nv) Punkten")
            }
            if let last = eof.last, Int(last) > ne {
                throw DecodeError.payload("Kantenversatz \(last) außerhalb von \(ne) Kantenpunkten")
            }
            out.append(
                (k, VergleichsNetz(
                    teil: k["teil"]?.stringValue ?? "", art: k["art"]?.stringValue ?? "alt", positions: pos, normals: nrm,
                    triangles: tri, edgePoints: ept, edgeOffsets: eof)))
        }
        guard offset == payload.count else {
            throw DecodeError.payload("Nutzlast hat \(payload.count) Byte, erwartet \(offset)")
        }
        return out
    }
}

// MARK: - App → Kernel

public struct VersionenRequestMessage: OutgoingRequest {
    public static let type = "VERSIONEN_REQ"
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

public struct VersionRestoreMessage: OutgoingRequest {
    public static let type = "VERSION_RESTORE"
    public var seq = 0
    public var id: String
    public var version: String

    public init(id: String, version: String) {
        self.id = id
        self.version = version
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, version }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(version, forKey: .version)
    }
}

public struct VersionCompareMessage: OutgoingRequest {
    public static let type = "VERSION_COMPARE"
    public var seq = 0
    public var id: String
    public var a: String
    /// nil = aktueller Stand
    public var b: String?

    public init(id: String, a: String, b: String?) {
        self.id = id
        self.a = a
        self.b = b
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, a, b }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(a, forKey: .a)
        try c.encode(b, forKey: .b)
    }
}

public struct VersionMilestoneMessage: OutgoingRequest {
    public static let type = "VERSION_MILESTONE"
    public var seq = 0
    public var id: String
    /// nil = aktueller Stand
    public var version: String?
    public var titel: String
    public var notiz: String
    public var entfernen: Bool

    public init(id: String, version: String?, titel: String, notiz: String = "", entfernen: Bool = false) {
        self.id = id
        self.version = version
        self.titel = titel
        self.notiz = notiz
        self.entfernen = entfernen
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, version, titel, notiz, entfernen }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(version, forKey: .version)
        try c.encode(titel, forKey: .titel)
        try c.encode(notiz, forKey: .notiz)
        try c.encode(entfernen, forKey: .entfernen)
    }
}

public struct VariantMessage: OutgoingRequest {
    public static let type = "VARIANT"
    public var seq = 0
    public var id: String
    /// anlegen | wechseln | umbenennen
    public var aktion: String
    public var name: String
    public var von: String?
    public var neuerName: String?

    public init(id: String, aktion: String, name: String, von: String? = nil, neuerName: String? = nil) {
        self.id = id
        self.aktion = aktion
        self.name = name
        self.von = von
        self.neuerName = neuerName
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, aktion, name, von
        case neuerName = "neuer_name"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(aktion, forKey: .aktion)
        try c.encode(name, forKey: .name)
        try c.encode(von, forKey: .von)
        try c.encode(neuerName, forKey: .neuerName)
    }
}
