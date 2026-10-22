import CoreGraphics
import Foundation

// Nachrichten der Zeichnungen (DOKUMENTE.md, Abschnitt „Protokoll“ und Anhang P6-Z): DOCS und DRAWING (Kernel → App).
// Gemeinsam als `KernelMessage.dokumente(DokumenteMessage)`, damit Messages.swift und AppController nur eine Stelle dafür
// brauchen. Die Anfragen der App (DOCS_REQ, DRAWING_REQ, DRAWING_EDIT) stehen in ZeichnungsAnfragen.swift.

public enum DokumenteMessage: Sendable {
    case docs(DocsUebersicht, replyTo: String?)
    case drawing(Zeichnung, replyTo: String?)

    public static let types: Set<String> = ["DOCS", "DRAWING"]

    public var typeName: String {
        switch self {
        case .docs: return "DOCS"
        case .drawing: return "DRAWING"
        }
    }

    public var replyTo: String? {
        switch self {
        case .docs(_, let r), .drawing(_, let r): return r
        }
    }

    public enum DecodeError: Error, CustomStringConvertible {
        case nutzlast(String)

        public var description: String {
            switch self {
            case .nutzlast(let s): return "Zeichnung: \(s)"
            }
        }
    }

    public static func decode(type: String, frame: Frame) throws -> DokumenteMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        let reply = json["reply_to"]?.stringValue
        switch type {
        case "DOCS":
            return .docs(uebersicht(json), replyTo: reply)
        default:
            return .drawing(try zeichnung(json, payload: frame.payload), replyTo: reply)
        }
    }

    // MARK: DOCS

    static func uebersicht(_ j: JSONValue) -> DocsUebersicht {
        let blaetter = (j["blaetter"]?.arrayValue ?? []).compactMap { b -> BlattEintrag? in
            guard let id = b["id"]?.lenientString else { return nil }
            let inhalt = b["inhalt"]
            return BlattEintrag(
                id: id, titel: b["titel"]?.lenientString ?? id, inhaltArt: inhalt?["art"]?.stringValue,
                teile: inhalt?["teile"]?.stringList ?? [], format: b["format"]?.stringValue,
                ausrichtung: b["ausrichtung"]?.stringValue, massstab: b["massstab"]?.stringValue,
                verwaisteMasse: b["verwaiste_masse"]?.intValue ?? 0, masse: b["masse"]?.intValue ?? 0,
                stand: b["stand"]?.stringValue, hinweise: b["hinweise"]?.stringList ?? [],
                pruefung: b["pruefung"]?.intValue ?? 0, fehler: b["fehler"]?.lenientString)
        }
        return DocsUebersicht(run: j["run"]?.intValue, blaetter: blaetter, bauplan: bauplanKurz(j["bauplan"]))
    }

    static func bauplanKurz(_ j: JSONValue?) -> BauplanKurz? {
        guard let j, j.objectValue != nil else { return nil }
        let abschnitte = (j["abschnitte"]?.arrayValue ?? []).map { a in
            BauplanKurz.Abschnitt(
                art: a["art"]?.stringValue ?? "", titel: a["titel"]?.lenientString ?? a["art"]?.stringValue ?? "",
                schritte: a["schritte"]?.intValue ?? 0)
        }
        return BauplanKurz(
            abschnitte: abschnitte, schritte: j["schritte"]?.intValue ?? abschnitte.reduce(0) { $0 + $1.schritte },
            probleme: j["probleme"]?.intValue ?? 0, fehler: j["fehler"]?.intValue ?? 0,
            hinweise: j["hinweise"]?.intValue ?? 0, json: j)
    }

    // MARK: DRAWING

    static func zeichnung(_ j: JSONValue, payload: Data) throws -> Zeichnung {
        let reihenfolge = j["linien_reihenfolge"]?.stringList.flatMap { $0.isEmpty ? nil : $0 } ?? Linienart.reihenfolge
        let geo = j["geometrie"]?.arrayValue ?? []
        let linien = try PolylinienNutzlast.lesen(payload, gruppen: geo.count, reihenfolge: reihenfolge)
        let gruppen = zip(geo, linien).map { g, l in
            ZeichnungsGruppe(
                id: g["id"]?.lenientString ?? "", art: g["art"]?.stringValue ?? "", rahmen: rechteck(g["rahmen"]) ?? .zero,
                massstab: g["massstab"]?.stringValue, titel: g["titel"]?.lenientString, linien: l)
        }
        let blatt = blattInfo(j["blatt"] ?? .object([:]))
        var groesse = CGSize(width: 297, height: 210)
        if let g = j["blattgroesse"]?.doubles, g.count >= 2, g[0] > 0, g[1] > 0 {
            groesse = CGSize(width: g[0], height: g[1])
        } else if let r = gruppen.first(where: \.istBlatt)?.rahmen, r.width > 0 {
            groesse = r.size
        }
        return Zeichnung(
            blatt: blatt, groesse: groesse, gruppen: gruppen,
            masse: (j["masse"]?.arrayValue ?? []).compactMap(mass),
            texte: (j["texte"]?.arrayValue ?? []).compactMap { text($0, ankerVorgabe: .links) },
            gefuellt: (j["gefuellt"]?.arrayValue ?? []).map(punkte).filter { $0.count >= 3 },
            pruefung: (j["pruefung"]?.arrayValue ?? []).map(befund),
            hinweise: j["hinweise"]?.stringList ?? [], stand: j["stand"]?.lenientString ?? "",
            run: j["run"]?.intValue, linienReihenfolge: reihenfolge)
    }

    static func punkt(_ j: JSONValue?) -> CGPoint? {
        guard let d = j?.doubles, d.count >= 2 else { return nil }
        return CGPoint(x: d[0], y: d[1])
    }

    static func punkte(_ j: JSONValue) -> [CGPoint] {
        (j.arrayValue ?? []).compactMap { punkt($0) }
    }

    /// `[x0, y0, x1, y1]` als Rechteck (auch vertauschte Ecken).
    static func rechteck(_ j: JSONValue?) -> CGRect? {
        guard let d = j?.doubles, d.count >= 4 else { return nil }
        return CGRect(x: min(d[0], d[2]), y: min(d[1], d[3]), width: abs(d[2] - d[0]), height: abs(d[3] - d[1]))
    }

    static func text(_ t: JSONValue, ankerVorgabe: TextAnker) -> BlattText? {
        guard let s = t["text"]?.lenientString, let lage = punkt(t["lage"]) else { return nil }
        return BlattText(
            text: s, lage: lage, hoehe: t["hoehe"]?.doubleValue ?? 3.5, winkel: t["winkel"]?.doubleValue ?? 0,
            anker: t["anker"]?.stringValue.flatMap(TextAnker.init(rawValue:)) ?? ankerVorgabe,
            art: t["art"]?.stringValue ?? "blatt", wert: t["wert"]?.doubleValue)
    }

    static func mass(_ m: JSONValue) -> MassDarstellung? {
        guard let id = m["id"]?.lenientString else { return nil }
        let pfeile = (m["pfeile"]?.arrayValue ?? []).compactMap { p -> MassPfeil? in
            guard let spitze = punkt(p["spitze"]) else { return nil }
            let r = p["richtung"]?.doubles ?? [1, 0]
            return MassPfeil(
                spitze: spitze, richtung: CGVector(dx: r.first ?? 1, dy: r.count > 1 ? r[1] : 0),
                art: p["art"]?.stringValue ?? "voll", laenge: p["laenge"]?.doubleValue ?? 2.5,
                breite: p["breite"]?.doubleValue ?? 0.66, polygon: p["polygon"].map(punkte) ?? [])
        }
        return MassDarstellung(
            id: id, linien: (m["linien"]?.arrayValue ?? []).map(punkte).filter { $0.count >= 2 }, pfeile: pfeile,
            text: m["text"]?.lenientString ?? "", textLage: punkt(m["text_lage"]) ?? .zero,
            textWinkel: m["text_winkel"]?.doubleValue ?? 0, textHoehe: m["text_hoehe"]?.doubleValue ?? 3.5,
            wert: m["wert"]?.doubleValue, einheit: m["einheit"]?.stringValue ?? "mm", box: rechteck(m["box"]),
            texte: (m["texte"]?.arrayValue ?? []).compactMap { text($0, ankerVorgabe: .mitte) },
            ansicht: m["ansicht"]?.lenientString, art: m["art"]?.stringValue ?? "linear",
            quelle: m["quelle"]?.stringValue ?? "auto", fest: m["fest"]?.boolValue ?? false,
            verwaist: m["verwaist"]?.boolValue ?? false)
    }

    static func befund(_ b: JSONValue) -> BlattBefund {
        BlattBefund(
            art: b["art"]?.stringValue ?? "bemassung", pruefung: b["pruefung"]?.stringValue ?? "",
            schwere: b["schwere"]?.stringValue ?? "hinweis", text: b["text"]?.lenientString ?? "",
            masse: b["masse"]?.stringList ?? [], merkmal: b["merkmal"]?.lenientString)
    }

    // MARK: Blattdatei

    static func blattInfo(_ b: JSONValue) -> BlattInfo {
        let inhalt = b["inhalt"]
        let auto = b["auto"]
        let ansichten = (b["ansichten"]?.arrayValue ?? []).compactMap { a -> BlattAnsichtEintrag? in
            guard let id = a["id"]?.lenientString else { return nil }
            return BlattAnsichtEintrag(
                id: id, art: a["art"]?.stringValue ?? "", lage: punkt(a["lage"]), massstab: a["massstab"]?.stringValue,
                fest: a["fest"]?.boolValue ?? false, optional: a["optional"]?.boolValue ?? false,
                titel: a["titel"]?.lenientString)
        }
        let masse = (b["masse"]?.arrayValue ?? []).compactMap { m -> BlattMassEintrag? in
            guard let id = m["id"]?.lenientString else { return nil }
            let tv = m["text_versatz"]
            return BlattMassEintrag(
                id: id, art: m["art"]?.stringValue ?? "linear", ansicht: m["ansicht"]?.lenientString,
                richtung: m["richtung"]?.stringValue, versatz: m["versatz"]?.doubleValue, text: m["text"]?.stringValue,
                toleranz: m["toleranz"]?.lenientString, quelle: m["quelle"]?.stringValue ?? "auto",
                fest: m["fest"]?.boolValue ?? false, verwaist: m["verwaist"]?.boolValue ?? false,
                schluessel: m["schluessel"]?.stringValue, seite: m["seite"]?.stringValue,
                anker: (m["anker"]?.arrayValue ?? []).compactMap { punkt($0) },
                textVersatz: (tv == nil || tv?.isNull == true) ? nil : tv, bezuege: m["bezuege"]?.arrayValue ?? [])
        }
        let notizen = (b["notizen"]?.arrayValue ?? []).compactMap { n -> BlattNotiz? in
            guard let id = n["id"]?.lenientString else { return nil }
            let z = n["zeiger"]
            return BlattNotiz(
                id: id, text: n["text"]?.lenientString ?? "", lage: punkt(n["lage"]) ?? CGPoint(x: 30, y: 30),
                zeiger: (z == nil || z?.isNull == true) ? nil : z, quelle: n["quelle"]?.stringValue ?? "kevin")
        }
        let unterdrueckt = (b["unterdrueckt"]?.arrayValue ?? []).map { u in
            BlattUnterdrueckung(
                art: u["art"]?.stringValue ?? "", ansicht: u["ansicht"]?.lenientString,
                schluessel: u["schluessel"]?.stringValue, bezuege: u["bezuege"]?.arrayValue ?? [])
        }
        return BlattInfo(
            id: b["id"]?.lenientString ?? "", titel: b["titel"]?.lenientString ?? b["id"]?.lenientString ?? "",
            format: b["format"]?.stringValue ?? "A4", ausrichtung: b["ausrichtung"]?.stringValue ?? "quer",
            massstab: b["massstab"]?.stringValue ?? "1:1", inhaltArt: inhalt?["art"]?.stringValue ?? "teil",
            teile: inhalt?["teile"]?.stringList ?? [], schriftfeld: b["schriftfeld"]?.objectValue ?? [:],
            schriftfeldFest: b["schriftfeld_fest"]?.stringList ?? [], ansichten: ansichten, masse: masse,
            notizen: notizen, unterdrueckt: unterdrueckt, autoAnsichten: auto?["ansichten"]?.boolValue ?? true,
            autoMasse: auto?["masse"]?.boolValue ?? true, autoMassstab: auto?["massstab"]?.boolValue ?? true,
            autoFormat: auto?["format"]?.boolValue ?? true, allgemein: b["allgemein"]?.stringList ?? [], json: b)
    }
}

// MARK: - Polylinien-Nutzlast

/// Polylinien-Nutzlast (DOKUMENTE.md): je Gruppe, je Linienart in `reihenfolge`: u32 Anzahl Polylinien, je Polylinie u32
/// Punktzahl und f32 x, y paarweise, alles little-endian. Gleiches Format bei DRAWING (`geometrie`) und BAUPLAN
/// (`bilder`, mit den Linienarten `neu` und `pfeil`).
public enum PolylinienNutzlast {
    public enum Fehler: Error, Equatable, CustomStringConvertible {
        case zuKurz(gelesen: Int, laenge: Int)
        case restBytes(gelesen: Int, laenge: Int)

        public var description: String {
            switch self {
            case .zuKurz(let g, let l): return "Polylinien-Nutzlast endet nach \(l) Byte, gebraucht mehr ab Byte \(g)"
            case .restBytes(let g, let l): return "Polylinien-Nutzlast hat \(l) Byte, gelesen \(g)"
            }
        }
    }

    /// Je Gruppe ein Wörterbuch Linienart → Polylinien (Polylinien mit weniger als zwei Punkten entfallen).
    public static func lesen(_ payload: Data, gruppen: Int, reihenfolge: [String]) throws -> [LinienGruppe] {
        guard gruppen > 0 else {
            if !payload.isEmpty { throw Fehler.restBytes(gelesen: 0, laenge: payload.count) }
            return []
        }
        return try payload.withUnsafeBytes { (raw: UnsafeRawBufferPointer) -> [LinienGruppe] in
            let n = raw.count
            var off = 0
            func u32() throws -> Int {
                guard off + 4 <= n else { throw Fehler.zuKurz(gelesen: off, laenge: n) }
                let v = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: off, as: UInt32.self))
                off += 4
                return Int(v)
            }
            var out: [LinienGruppe] = []
            out.reserveCapacity(gruppen)
            for _ in 0..<gruppen {
                var g: LinienGruppe = [:]
                for art in reihenfolge {
                    let anzahl = try u32()
                    var liste: [[CGPoint]] = []
                    liste.reserveCapacity(anzahl)
                    for _ in 0..<anzahl {
                        let k = try u32()
                        guard k <= (n - off) / 8 else { throw Fehler.zuKurz(gelesen: off, laenge: n) }
                        var pl = [CGPoint]()
                        pl.reserveCapacity(k)
                        for i in 0..<k {
                            let bx = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: off + 8 * i, as: UInt32.self))
                            let by = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: off + 8 * i + 4, as: UInt32.self))
                            pl.append(CGPoint(x: CGFloat(Float(bitPattern: bx)), y: CGFloat(Float(bitPattern: by))))
                        }
                        off += 8 * k
                        if pl.count >= 2 { liste.append(pl) }
                    }
                    if g[art] != nil { g[art]! += liste } else { g[art] = liste }
                }
                out.append(g)
            }
            if off != n { throw Fehler.restBytes(gelesen: off, laenge: n) }
            return out
        }
    }
}
