import CoreGraphics
import Foundation
import simd

// Nachrichten des Bauplans (DOKUMENTE.md, Protokoll; Strang P6-A2): BAUPLAN (Kernel → App) mit Strichbildern als
// Polylinien-Nutzlast; BAUPLAN_REQ, BAUPLAN_EDIT, BAUPLAN_PRUEFEN (App → Kernel). Referenz: protocol.pack_bauplan.

/// BAUPLAN: der Plan samt Prüfung und je Schritt mit Bild ein Strichbild.
public struct BauplanNachricht: Sendable {
    public var replyTo: String?
    public var run: Int?
    public var plan: Bauplan
    public var bilder: [BauplanStrichbild]
    /// Feld der Strichbilder in mm (180 × 120).
    public var feld: CGSize
    public var linienReihenfolge: [String]

    public enum DecodeError: Error, CustomStringConvertible {
        case nutzlast(String)
        public var description: String {
            switch self {
            case .nutzlast(let s): return "BAUPLAN: \(s)"
            }
        }
    }

    public static func decode(_ frame: Frame) throws -> BauplanNachricht {
        let j = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        let reihenfolge = j["linien_reihenfolge"]?.stringList ?? BauplanPolylinien.standardReihenfolge
        let koepfe = j["bilder"]?.arrayValue ?? []
        let gruppen = try BauplanPolylinien.decode(
            frame.payload, gruppen: koepfe.count, reihenfolge: reihenfolge)
        var bilder: [BauplanStrichbild] = []
        for (k, g) in zip(koepfe, gruppen) {
            let r = k["rahmen"]?.doubles ?? [0, 0, 180, 120]
            let rahmen = r.count == 4 ? CGRect(x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1])
                : CGRect(x: 0, y: 0, width: 180, height: 120)
            bilder.append(
                BauplanStrichbild(
                    schritt: k["schritt"]?.stringValue ?? "", rahmen: rahmen, massstab: k["massstab"]?.doubleValue,
                    linien: g, fehler: k["fehler"]?.stringValue))
        }
        let feld = j["feld"]?.doubles ?? [180, 120]
        var plan = BauplanDecoder.plan(j["bauplan"] ?? .null)
        if plan.run == nil { plan.run = j["run"]?.intValue }
        return BauplanNachricht(
            replyTo: j["reply_to"]?.stringValue, run: j["run"]?.intValue, plan: plan, bilder: bilder,
            feld: CGSize(width: feld.first ?? 180, height: feld.count > 1 ? feld[1] : 120),
            linienReihenfolge: reihenfolge)
    }
}

/// Polylinien-Nutzlast (DOKUMENTE.md): je Gruppe, je Linienart in Reihenfolge: u32 Anzahl Polylinien, je Polylinie
/// u32 Punktzahl und f32 x, y paarweise (little-endian).
public enum BauplanPolylinien {
    public static let standardReihenfolge = [
        "sichtbar", "verdeckt", "mitte", "schnitt", "schraffur", "duenn", "nachbar", "bruch", "neu", "pfeil",
    ]

    public static func decode(_ data: Data, gruppen: Int, reihenfolge: [String]) throws
        -> [[String: [[CGPoint]]]]
    {
        let bytes = [UInt8](data)
        var off = 0
        func u32() throws -> Int {
            guard off + 4 <= bytes.count else { throw BauplanNachricht.DecodeError.nutzlast("zu kurz bei Byte \(off)") }
            let v = UInt32(bytes[off]) | UInt32(bytes[off + 1]) << 8 | UInt32(bytes[off + 2]) << 16
                | UInt32(bytes[off + 3]) << 24
            off += 4
            return Int(v)
        }
        func f32() throws -> CGFloat {
            let bits = UInt32(try u32())
            return CGFloat(Float(bitPattern: bits))
        }
        var out: [[String: [[CGPoint]]]] = []
        for _ in 0..<gruppen {
            var linien: [String: [[CGPoint]]] = [:]
            for art in reihenfolge {
                let n = try u32()
                guard n <= 10_000_000 else { throw BauplanNachricht.DecodeError.nutzlast("\(n) Polylinien in \(art)") }
                var ls: [[CGPoint]] = []
                ls.reserveCapacity(n)
                for _ in 0..<n {
                    let k = try u32()
                    guard off + 8 * k <= bytes.count else {
                        throw BauplanNachricht.DecodeError.nutzlast("Polylinie mit \(k) Punkten passt nicht")
                    }
                    var pl: [CGPoint] = []
                    pl.reserveCapacity(k)
                    for _ in 0..<k {
                        let x = try f32()
                        let y = try f32()
                        pl.append(CGPoint(x: x, y: y))
                    }
                    ls.append(pl)
                }
                linien[art] = ls
            }
            out.append(linien)
        }
        guard off == bytes.count else {
            throw BauplanNachricht.DecodeError.nutzlast("\(bytes.count) Byte, gelesen \(off)")
        }
        return out
    }
}

/// Liest bauplan.json (aus BAUPLAN oder aus der Datei).
public enum BauplanDecoder {
    public static func plan(_ j: JSONValue) -> Bauplan {
        let abschnitte = (j["abschnitte"]?.arrayValue ?? []).map { a in
            BauplanAbschnitt(
                art: BauplanAbschnittArt(a["art"]?.stringValue ?? ""), titel: a["titel"]?.stringValue ?? "",
                schritte: (a["schritte"]?.arrayValue ?? []).map(schritt),
                reihenfolgeFest: a["reihenfolge"]?.stringValue == "fest")
        }
        let vorher = (j["vorher"]?.arrayValue ?? []).enumerated().map { i, v in
            BauplanReihenfolge(
                index: i, a: v["a"]?.stringValue ?? "", b: v["b"]?.stringValue ?? "",
                grund: v["grund"]?.stringValue ?? "", quelle: v["quelle"]?.stringValue ?? "auto")
        }
        let stand = j["stand"]
        let nicht = (stand?["nicht_im_aufbau"]?.objectValue ?? [:]).map { ($0.key, $0.value.stringValue ?? "") }
            .sorted { $0.0 < $1.0 }
        return Bauplan(
            version: j["version"]?.intValue ?? 1, titel: j["titel"]?.stringValue ?? "", abschnitte: abschnitte,
            vorher: vorher, run: stand?["run"]?.intValue, gesamtMS: stand?["gesamt_ms"]?.doubleValue,
            nichtImAufbau: nicht.map { (teil: $0.0, grund: $0.1) },
            ohneVerbinde: stand?["verbinde"]?.boolValue == false)
    }

    static func strings(_ v: JSONValue?) -> [String] { v?.stringList ?? [] }

    static func schritt(_ s: JSONValue) -> BauplanSchritt {
        BauplanSchritt(
            id: s["id"]?.stringValue ?? UUID().uuidString, titel: s["titel"]?.stringValue ?? "",
            text: s["text"]?.stringValue ?? "", quelle: s["quelle"]?.stringValue ?? "auto",
            fest: s["fest"]?.boolValue ?? false, verwaist: s["verwaist"]?.boolValue ?? false,
            teile: strings(s["teile"]), neu: strings(s["neu"]), baugruppe: s["baugruppe"]?.stringValue,
            anzahl: max(1, s["anzahl"]?.intValue ?? 1),
            verbindungsmittel: (s["verbindungsmittel"]?.arrayValue ?? []).map { v in
                BauplanVerbindungsmittel(
                    id: v["id"]?.stringValue ?? "", benennung: v["benennung"]?.stringValue ?? v["id"]?.stringValue ?? "",
                    laenge: v["laenge"]?.doubleValue, anzahl: v["anzahl"]?.intValue ?? 1,
                    geschaetzt: v["geschaetzt"]?.boolValue ?? false)
            },
            werkzeug: strings(s["werkzeug"]),
            bohrbild: (s["bohrbild"]?.arrayValue ?? []).map { b in
                BauplanBohrung(
                    teil: b["teil"]?.stringValue ?? "", durchmesser: b["durchmesser"]?.doubleValue,
                    tiefe: b["tiefe"]?.doubleValue, lage: b["lage_mm"]?.doubles ?? [], von: b["von"]?.stringValue,
                    senkung: text(b["senkung"]), gewinde: text(b["gewinde"]), fuer: b["fuer"]?.stringValue,
                    text: b["text"]?.stringValue, art: b["art"]?.stringValue)
            },
            zuschnitt: (s["zuschnitt"]?.arrayValue ?? []).map { z in
                BauplanZuschnittPosten(
                    stockID: z["stock_id"]?.stringValue ?? "", laenge: z["laenge"]?.doubleValue ?? 0,
                    gehrung: z["gehrung"]?.doubles ?? [0, 0], anzahl: z["anzahl"]?.intValue ?? 1)
            },
            druck: s["druck"].flatMap { d in
                guard d.objectValue != nil else { return nil }
                return BauplanDruck(
                    teil: d["teil"]?.stringValue ?? "", material: d["material"]?.stringValue,
                    seite: d["seite"]?.stringValue, hoeheMM: d["hoehe_mm"]?.doubleValue,
                    masseG: d["masse_g"]?.doubleValue, hinweise: strings(d["hinweise"]))
            },
            material: (s["material"]?.arrayValue ?? []).map { m in
                BauplanMaterial(
                    benennung: m["benennung"]?.stringValue ?? "", menge: m["menge"]?.doubleValue ?? 0,
                    einheit: m["einheit"]?.stringValue ?? "", preis: m["preis"]?.doubleValue,
                    quelle: m["quelle"]?.stringValue, hinweis: m["hinweis"]?.stringValue)
            },
            bild: s["bild"].flatMap(bild), pruefung: (s["pruefung"]?.arrayValue ?? []).enumerated().map { befund($0.offset, $0.element) },
            hinweise: strings(s["hinweise"]),
            einbau: (s["einbau"]?.arrayValue ?? []).map { e in
                BauplanEinbau(
                    name: e["name"]?.stringValue ?? "", art: e["art"]?.stringValue ?? "teil",
                    teile: strings(e["teile"]), richtung: e["richtung"]?.vector3, weg: e["weg"]?.doubleValue ?? 0,
                    aufbocken: e["aufbocken"]?.doubleValue ?? 0, grundteil: e["grundteil"]?.boolValue ?? false)
            })
    }

    /// Senkung und Gewinde kommen als Text oder als Objekt (`{"art", "durchmesser", "text"}`).
    static func text(_ v: JSONValue?) -> String? {
        guard let v, !v.isNull else { return nil }
        if let s = v.stringValue { return s.isEmpty ? nil : s }
        if let t = v["text"]?.stringValue { return t }
        if let n = v["name"]?.stringValue { return n }
        if let d = v["durchmesser"]?.doubleValue {
            return "\(v["art"]?.stringValue ?? "") Ø \(KevFormat.compact(d, maxDigits: 1))"
                .trimmingCharacters(in: .whitespaces)
        }
        return nil
    }

    static func befund(_ i: Int, _ b: JSONValue) -> BauplanBefund {
        BauplanBefund(
            id: b["id"]?.stringValue ?? "b\(i)", art: b["art"]?.stringValue ?? "",
            teile: strings(b["teile"]), schwere: BauplanSchwere(b["schwere"]?.stringValue),
            text: b["text"]?.stringValue ?? "", loesung: b["loesung"]?.stringValue,
            schritt: b["schritt"]?.stringValue, ort: b["ort"]?.vector3)
    }

    static func bild(_ b: JSONValue) -> BauplanBildParameter? {
        guard b.objectValue != nil else { return nil }
        let k = b["kamera"]
        var rot: simd_quatf?
        if let q = k?["rotation"]?.doubles, q.count == 4 {
            rot = simd_quatf(ix: Float(q[0]), iy: Float(q[1]), iz: Float(q[2]), r: Float(q[3]))
        }
        var explosion: [String: SIMD3<Float>] = [:]
        for (t, v) in b["explosion"]?.objectValue ?? [:] {
            if let d = v.vector3 { explosion[t] = d }
        }
        var sicht: [String: Double] = [:]
        for (t, v) in b["sichtbarkeit"]?.objectValue ?? [:] {
            if let d = v.doubleValue { sicht[t] = d }
        }
        return BauplanBildParameter(
            rotation: rot, pivot: k?["pivot"]?.vector3, distance: k?["distance"]?.doubleValue.map(Float.init),
            ortho: k?["ortho"]?.boolValue ?? true, blick: b["ansicht"]?["richtung"]?.vector3,
            oben: b["ansicht"]?["oben"]?.vector3, explosion: explosion,
            pfeile: (b["pfeile"]?.arrayValue ?? []).compactMap { p in
                guard let r = p["richtung"]?.vector3 else { return nil }
                return BauplanPfeil(
                    teil: p["teil"]?.stringValue ?? "", richtung: r, von: p["von"]?.vector3, nach: p["nach"]?.vector3)
            },
            hervorheben: strings(b["hervorheben"]), kontext: strings(b["kontext"]),
            ausschnittMin: b["ausschnitt"]?["min"]?.vector3, ausschnittMax: b["ausschnitt"]?["max"]?.vector3,
            sichtbarkeit: sicht, quelle: b["quelle"]?.stringValue ?? "auto")
    }
}

// MARK: - App → Kernel

public struct BauplanAnfrageMessage: OutgoingRequest {
    public static let type = "BAUPLAN_REQ"
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

/// BAUPLAN_EDIT mit Operationen (DOKUMENTE.md; Kernel `bauplan/datei.py::bearbeiten`).
public struct BauplanBearbeitenMessage: OutgoingRequest {
    public static let type = "BAUPLAN_EDIT"
    public var seq = 0
    public var id: String
    public var ops: [JSONValue]
    public var von: String

    public init(id: String, ops: [JSONValue], von: String = "kevin") {
        self.id = id
        self.ops = ops
        self.von = von
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, ops, von }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(ops, forKey: .ops)
        try c.encode(von, forKey: .von)
    }
}

public struct BauplanPruefenMessage: OutgoingRequest {
    public static let type = "BAUPLAN_PRUEFEN"
    public var seq = 0
    public var id: String
    /// nil = alle Schritte
    public var schritt: String?

    public init(id: String, schritt: String? = nil) {
        self.id = id
        self.schritt = schritt
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, schritt }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        if let schritt { try c.encode(schritt, forKey: .schritt) } else { try c.encodeNil(forKey: .schritt) }
    }
}

/// Operationen für BAUPLAN_EDIT, so wie der Kernel sie versteht.
public enum BauplanOp {
    public static func text(schritt: String, titel: String?, text: String?, hinweise: [String]? = nil) -> JSONValue {
        var o: [String: JSONValue] = ["op": "text", "schritt": .string(schritt)]
        if let titel { o["titel"] = .string(titel) }
        if let text { o["text"] = .string(text) }
        if let hinweise { o["hinweise"] = .array(hinweise.map(JSONValue.string)) }
        return .object(o)
    }

    public static func fest(schritt: String, _ wert: Bool) -> JSONValue {
        ["op": "fest", "schritt": .string(schritt), "wert": .bool(wert)]
    }

    /// `nach` nil = an den Anfang des Abschnitts.
    public static func verschieben(schritt: String, nach: String?) -> JSONValue {
        ["op": "verschieben", "schritt": .string(schritt), "nach": nach.map(JSONValue.string) ?? .null]
    }

    public static func zusammenfassen(_ schritte: [String], titel: String? = nil) -> JSONValue {
        var o: [String: JSONValue] = ["op": "zusammenfassen", "schritte": .array(schritte.map(JSONValue.string))]
        if let titel { o["titel"] = .string(titel) }
        return .object(o)
    }

    public static func teilen(schritt: String, teile: [String], titel: String? = nil) -> JSONValue {
        var o: [String: JSONValue] = [
            "op": "teilen", "schritt": .string(schritt), "teile": .array(teile.map(JSONValue.string)),
        ]
        if let titel { o["titel"] = .string(titel) }
        return .object(o)
    }

    public static func vorher(a: String, b: String, grund: String) -> JSONValue {
        ["op": "vorher", "a": .string(a), "b": .string(b), "grund": .string(grund)]
    }

    public static func vorherLoeschen(index: Int) -> JSONValue {
        ["op": "vorher_loeschen", "index": .number(Double(index))]
    }

    public static func werkzeug(schritt: String, _ werkzeug: [String]) -> JSONValue {
        ["op": "werkzeug", "schritt": .string(schritt), "werkzeug": .array(werkzeug.map(JSONValue.string))]
    }
}
