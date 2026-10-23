import Foundation
import simd

// Topologieoptimierung (PROTOCOL.md „Topologie“, additiv; PLAN-TOPOLOGIE.md): TOPO trägt den Stand eines Auftrags
// (läuft mit Fortschritt und Verlauf, fertig mit Kennzahlen vorher und nachher), TOPO_FIELD die Netze dazu: Dichte
// einer Iteration, Schutzzonen, den optimierten Körper und die Festkörper-Felder vorher und nachher (mit Ausnutzung,
// Spannung und Verschiebung wie STATICS_FIELD). App → Kernel: TOPO_START, TOPO_CANCEL, TOPO_APPLY.

/// Kennzahlen vorher oder nachher.
public struct TopologieKennzahlen: Equatable, Sendable {
    public var volumenMm3: Double?
    public var masseG: Double?
    public var filamentG: Double?
    public var druckzeitMin: Double?
    public var spannungMax: Double?
    public var sicherheit: Double?
    public var ziel: Double?
    public var ampel: StatikAmpel
    public var verformungMaxMm: Double?
    public var stegMinMm: Double?
    public var ueberhangMm2: Double?

    init(json j: JSONValue?) {
        volumenMm3 = j?["volumen_mm3"]?.doubleValue
        masseG = j?["masse_g"]?.doubleValue
        filamentG = j?["filament_g"]?.doubleValue
        druckzeitMin = j?["druckzeit_min"]?.doubleValue
        spannungMax = j?["spannung_max"]?.doubleValue
        sicherheit = j?["sicherheit"]?.doubleValue
        ziel = j?["ziel"]?.doubleValue
        ampel = StatikAmpel(rawValue: j?["ampel"]?.stringValue ?? "") ?? .grau
        verformungMaxMm = j?["verformung_max_mm"]?.doubleValue
        stegMinMm = j?["steg_min_mm"]?.doubleValue
        ueberhangMm2 = j?["ueberhang_mm2"]?.doubleValue
    }
}

/// Eine Schutzzone (Bohrung, Einsatz, Last- oder Klemmfläche, Bett, aus model.py).
public struct TopologieZone: Equatable, Sendable, Identifiable {
    public var id: Int
    public var art: String
    public var text: String
}

/// Stand der Topologieoptimierung (TOPO).
public struct TopologieStand: Equatable, Sendable {
    public var run: Int
    public var stand: String
    public var auftrag: Int
    public var teil: String
    public var szenario: String?
    public var behalten: Double
    public var ueberhang: Bool
    public var fein: Bool
    public var fortschritt: Double
    public var phase: String?
    public var text: String
    public var textLang: String
    public var iteration: Int
    public var maxIter: Int
    /// Nachgiebigkeit relativ zur ersten Iteration und Volumenanteil je Iteration.
    public var verlauf: [(i: Int, c: Double, volumen: Double)]
    public var voxel: Int?
    public var hMm: Double?
    public var vorher: TopologieKennzahlen
    public var nachher: TopologieKennzahlen
    public var ersparnisProzent: Double?
    public var zonen: [TopologieZone]
    public var hinweise: [String]
    public var grenzen: [String]
    public var meldung: String?
    public var datei: String?
    public var imModell: Bool
    public var variante: String?
    public var quelle: String?

    public var laeuft: Bool { stand == "laeuft" }
    public var fertig: Bool { stand == "done" }

    public static func == (a: Self, b: Self) -> Bool {
        a.run == b.run && a.stand == b.stand && a.auftrag == b.auftrag && a.teil == b.teil
            && a.fortschritt == b.fortschritt && a.iteration == b.iteration && a.text == b.text
            && a.datei == b.datei && a.imModell == b.imModell && a.vorher == b.vorher && a.nachher == b.nachher
    }

    init(json j: JSONValue) {
        run = j["run"]?.intValue ?? 0
        stand = j["stand"]?.stringValue ?? "laeuft"
        auftrag = j["auftrag"]?.intValue ?? 0
        teil = j["teil"]?.stringValue ?? ""
        szenario = j["szenario"]?.stringValue
        let e = j["einstellungen"]
        behalten = e?["behalten"]?.doubleValue ?? 0.4
        ueberhang = e?["ueberhang"]?.boolValue ?? false
        fein = e?["fein"]?.boolValue ?? false
        fortschritt = j["fortschritt"]?.doubleValue ?? 0
        phase = j["phase"]?.stringValue
        text = j["text"]?.stringValue ?? ""
        textLang = j["text_lang"]?.stringValue ?? text
        iteration = j["iteration"]?.intValue ?? 0
        maxIter = j["max_iter"]?.intValue ?? 60
        let v = j["verlauf"]?.arrayValue ?? []
        let c0 = v.first?["c"]?.doubleValue ?? 1
        verlauf = v.compactMap { x in
            guard let i = x["i"]?.intValue, let c = x["c"]?.doubleValue else { return nil }
            return (i, c0 > 0 ? c / c0 : c, x["volumen"]?.doubleValue ?? 0)
        }
        voxel = j["voxel"]?.intValue
        hMm = j["h_mm"]?.doubleValue
        vorher = TopologieKennzahlen(json: j["kennzahlen"]?["vorher"])
        nachher = TopologieKennzahlen(json: j["kennzahlen"]?["nachher"])
        ersparnisProzent = j["kennzahlen"]?["ersparnis"]?["volumen_prozent"]?.doubleValue
        zonen = (j["schutz"]?["zonen"]?.arrayValue ?? []).enumerated().map { i, z in
            let art = z["art"]?.stringValue ?? "Zone"
            var teile: [String] = []
            if let d = z["d"]?.doubleValue { teile.append("Ø \(KevFormat.number(d, digits: 1))") }
            if let r = z["ring_mm"]?.doubleValue { teile.append("Ring \(KevFormat.number(r, digits: 1)) mm") }
            if let h = z["haut_mm"]?.doubleValue { teile.append("Haut \(KevFormat.number(h, digits: 1)) mm") }
            return TopologieZone(id: i, art: art, text: teile.joined(separator: ", "))
        }
        hinweise = j["hinweise"]?.arrayValue?.compactMap(\.stringValue) ?? []
        grenzen = j["grenzen"]?.arrayValue?.compactMap(\.stringValue) ?? []
        meldung = j["meldung"]?.stringValue
        datei = j["ergebnis"]?["datei"]?.stringValue
        imModell = j["ergebnis"]?["im_modell"]?.boolValue ?? false
        variante = j["ergebnis"]?["variante"]?.stringValue
        quelle = j["quelle"]?.stringValue
    }

    public static func decode(_ header: Data) throws -> TopologieStand {
        TopologieStand(json: try JSONDecoder().decode(JSONValue.self, from: header))
    }
}

public enum TopologieFeldArt: String, Sendable, CaseIterable {
    case dichte, schutz, koerper, vorher, nachher
}

/// Netz eines Auftrags (TOPO_FIELD): Punkte (Welt, mm) und Dreiecke; vorher und nachher zusätzlich Ausnutzung,
/// Spannung und Verschiebung je Punkt.
public struct TopologieFeld: Equatable, Sendable {
    public var art: TopologieFeldArt
    public var auftrag: Int
    public var teil: String
    public var iteration: Int?
    public var punkte: [SIMD3<Float>]
    public var dreiecke: [UInt32]
    /// Festkörper-Feld (nur vorher und nachher), im Format der Statik für dieselbe Darstellung.
    public var feld: StatikFeld?

    public static func decode(header: Data, payload: Data) throws -> TopologieFeld {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        guard let artText = j["art"]?.stringValue, let art = TopologieFeldArt(rawValue: artText),
            let n = j["punkte"]?.intValue, let m = j["dreiecke"]?.intValue, n >= 0, m >= 0
        else { throw StatikFeldFehler.kaputt("TOPO_FIELD: art, punkte oder dreiecke fehlen") }
        let mitWerten = j["werte"]?.stringValue == "ausnutzung"
        if mitWerten {
            // gleiche Nutzlast wie STATICS_FIELD: über dessen Decoder lesen
            var kopf: [String: JSONValue] = j.objectValue ?? [:]
            kopf["szenario"] = .string("Topologie")
            kopf["feld"] = .string("topologie-\(artText)")
            kopf["run"] = .number(0)
            let daten = try JSONEncoder().encode(JSONValue.object(kopf))
            let f = try StatikFeld.decode(header: daten, payload: payload)
            return TopologieFeld(
                art: art, auftrag: j["auftrag"]?.intValue ?? 0, teil: j["teil"]?.stringValue ?? "",
                iteration: j["iteration"]?.intValue, punkte: f.punkte, dreiecke: f.dreiecke, feld: f)
        }
        let erwartet = n * 12 + m * 12
        guard payload.count == erwartet else {
            throw StatikFeldFehler.kaputt("TOPO_FIELD: Nutzlast \(payload.count) Byte, erwartet \(erwartet)")
        }
        var punkte: [SIMD3<Float>] = []
        var dreiecke: [UInt32] = []
        payload.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var o = 0
            func u() -> UInt32 {
                let v = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: o, as: UInt32.self))
                o += 4
                return v
            }
            punkte.reserveCapacity(n)
            for _ in 0..<n { punkte.append(SIMD3(Float(bitPattern: u()), Float(bitPattern: u()), Float(bitPattern: u()))) }
            dreiecke.reserveCapacity(3 * m)
            for _ in 0..<(3 * m) { dreiecke.append(u()) }
        }
        if let groesst = dreiecke.max(), Int(groesst) >= n {
            throw StatikFeldFehler.kaputt("TOPO_FIELD: Dreieck zeigt auf Punkt \(groesst), es gibt \(n)")
        }
        return TopologieFeld(
            art: art, auftrag: j["auftrag"]?.intValue ?? 0, teil: j["teil"]?.stringValue ?? "",
            iteration: j["iteration"]?.intValue, punkte: punkte, dreiecke: dreiecke, feld: nil)
    }
}

/// App → Kernel: Optimierung starten (PROTOCOL.md „Topologie“).
public struct TopologieStartMessage: OutgoingMessage {
    public static let type = "TOPO_START"
    public var seq = 0
    public var teil: String?
    public var szenario: String?
    public var behalten: Double
    public var ueberhang: Bool
    public var fein: Bool
    /// Lager beim Optimieren: "kontakt" (Vorgabe) oder "bohrungen" (die Schrauben halten).
    public var lager: String?

    public init(teil: String?, szenario: String?, behalten: Double, ueberhang: Bool, fein: Bool,
                lager: String? = nil) {
        self.teil = teil
        self.szenario = szenario
        self.behalten = behalten
        self.ueberhang = ueberhang
        self.fein = fein
        self.lager = lager
    }

    enum CodingKeys: String, CodingKey { case type, seq, teil, szenario, behalten, ueberhang, fein, lager }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encodeIfPresent(teil, forKey: .teil)
        try c.encodeIfPresent(szenario, forKey: .szenario)
        try c.encode(behalten, forKey: .behalten)
        try c.encode(ueberhang, forKey: .ueberhang)
        try c.encode(fein, forKey: .fein)
        try c.encodeIfPresent(lager, forKey: .lager)
    }
}

/// App → Kernel: laufende Optimierung beenden.
public struct TopologieAbbrechenMessage: OutgoingMessage {
    public static let type = "TOPO_CANCEL"
    public var seq = 0

    public init() {}

    enum CodingKeys: String, CodingKey { case type, seq }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
    }
}

/// App → Kernel: das Ergebnis als Variante übernehmen (Variante anlegen, model.py ergänzen, Lauf).
public struct TopologieUebernehmenMessage: OutgoingMessage {
    public static let type = "TOPO_APPLY"
    public var seq = 0

    public init() {}

    enum CodingKeys: String, CodingKey { case type, seq }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
    }
}
