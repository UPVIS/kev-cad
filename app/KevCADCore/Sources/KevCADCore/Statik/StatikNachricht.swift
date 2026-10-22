import Foundation
import simd

// Statik (PROTOCOL.md Abschnitt „Statik“, additiv): STATICS vom Kernel nach jeder Prüfung und nach `szenario_rechnen`.
// Je Szenario Ampel, Kennzahlen, Urteile, Ausnutzung je Teil und je Stab (Stationen mit Ausnutzung und Verschiebung).

public enum StatikAmpel: String, Sendable, CaseIterable {
    case gruen, gelb, rot, grau

    var rang: Int {
        switch self {
        case .rot: return 3
        case .gelb: return 2
        case .gruen: return 1
        case .grau: return 0
        }
    }

    public var text: String {
        switch self {
        case .gruen: return "grün"
        case .gelb: return "gelb"
        case .rot: return "rot"
        case .grau: return "nicht gerechnet"
        }
    }
}

public struct StatikUrteil: Identifiable, Equatable, Sendable {
    public var id: Int
    public var art: String
    public var teil: String?
    public var ampel: StatikAmpel
    public var text: String
    public var loesung: String
    public var sicherheit: Double?
    public var ziel: Double?
    public var ort: SIMD3<Float>?

    public init(
        id: Int, art: String, teil: String?, ampel: StatikAmpel, text: String, loesung: String = "",
        sicherheit: Double? = nil, ziel: Double? = nil, ort: SIMD3<Float>? = nil
    ) {
        self.id = id
        self.art = art
        self.teil = teil
        self.ampel = ampel
        self.text = text
        self.loesung = loesung
        self.sicherheit = sicherheit
        self.ziel = ziel
        self.ort = ort
    }

    init(json j: JSONValue, index: Int) {
        self.init(
            id: index, art: j["art"]?.stringValue ?? "", teil: j["teil"]?.stringValue,
            ampel: StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau, text: j["text"]?.stringValue ?? "",
            loesung: j["loesung"]?.stringValue ?? "", sicherheit: j["sicherheit"]?.doubleValue,
            ziel: j["ziel"]?.doubleValue, ort: j["ort"]?.vector3)
    }
}

/// Ausnutzung eines Teils im Szenario: Zielsicherheit / vorhandene Sicherheit (1 = gerade noch grün, über 2 rot).
public struct StatikTeil: Equatable, Sendable {
    public var name: String
    public var ausnutzung: Double
    public var ampel: StatikAmpel
    public var verformungMm: Double?
    public var sicherheit: Double?

    init(json j: JSONValue) {
        name = j["name"]?.stringValue ?? ""
        ausnutzung = j["ausnutzung"]?.doubleValue ?? 0
        ampel = StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau
        verformungMm = j["verformung_mm"]?.doubleValue
        sicherheit = j["sicherheit"]?.doubleValue
    }
}

/// Ein Stab (Rohr, Profil) mit Stationen entlang der Achse: Ausnutzung und Verschiebung (mm) je Station.
public struct StatikStab: Equatable, Sendable {
    public var name: String
    public var punkte: [SIMD3<Float>]
    public var ausnutzung: [Double]
    public var verschiebung: [SIMD3<Float>]
    public var radius: Float
    public var sicherheit: Double?
    public var ampel: StatikAmpel

    public init(
        name: String, punkte: [SIMD3<Float>], ausnutzung: [Double], verschiebung: [SIMD3<Float>], radius: Float,
        sicherheit: Double? = nil, ampel: StatikAmpel = .grau
    ) {
        self.name = name
        self.punkte = punkte
        self.ausnutzung = ausnutzung
        self.verschiebung = verschiebung
        self.radius = radius
        self.sicherheit = sicherheit
        self.ampel = ampel
    }

    init(json j: JSONValue) {
        let punkte = (j["punkte"]?.arrayValue ?? []).compactMap(\.vector3)
        let versch = (j["verschiebung"]?.arrayValue ?? []).compactMap(\.vector3)
        let aus = j["ausnutzung"]?.doubles ?? []
        let n = min(punkte.count, versch.count, aus.count)
        self.init(
            name: j["name"]?.stringValue ?? "", punkte: Array(punkte.prefix(n)), ausnutzung: Array(aus.prefix(n)),
            verschiebung: Array(versch.prefix(n)), radius: Float(j["radius"]?.doubleValue ?? 5),
            sicherheit: j["sicherheit"]?.doubleValue,
            ampel: StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau)
    }
}

public struct StatikKennzahlen: Equatable, Sendable {
    public var sicherheit: Double?
    public var knicken: Double?
    public var kippreserve: Double?
    public var rutschreserve: Double?
    public var durchbiegungMm: Double?
    public var durchbiegungGrenzeMm: Double?
    public var verformungMaxMm: Double?

    init(json j: JSONValue?) {
        sicherheit = j?["sicherheit"]?.doubleValue
        knicken = j?["knicken"]?.doubleValue
        kippreserve = j?["kippreserve"]?.doubleValue
        rutschreserve = j?["rutschreserve"]?.doubleValue
        durchbiegungMm = j?["durchbiegung_mm"]?.doubleValue
        durchbiegungGrenzeMm = j?["durchbiegung_grenze_mm"]?.doubleValue
        verformungMaxMm = j?["verformung_max_mm"]?.doubleValue
    }
}

/// Kippen einer Gruppe: Reserve im Szenario und je Richtung Kippwinkel (Grad) und Beschleunigung (m/s²), bei der sie
/// kippt.
public struct StatikKippen: Equatable, Sendable {
    public struct Richtung: Equatable, Sendable {
        public var richtung: String
        public var kippwinkel: Double
        public var aKipp: Double
    }

    public var name: String
    public var reserve: Double?
    public var richtungText: String?
    public var jeRichtung: [Richtung]

    init(json j: JSONValue) {
        name = j["name"]?.stringValue ?? ""
        reserve = j["reserve"]?.doubleValue
        richtungText = j["richtung_text"]?.stringValue
        let ordnung = ["+X", "−X", "+Y", "−Y"]
        let obj = j["je_richtung"]?.objectValue ?? [:]
        jeRichtung = obj.keys.sorted { (ordnung.firstIndex(of: $0) ?? 9, $0) < (ordnung.firstIndex(of: $1) ?? 9, $1) }
            .map { k in
                Richtung(
                    richtung: k, kippwinkel: obj[k]?["kippwinkel"]?.doubleValue ?? 0,
                    aKipp: obj[k]?["a_kipp"]?.doubleValue ?? 0)
            }
    }
}

public struct StatikSzenario: Identifiable, Equatable, Sendable {
    public var name: String
    public var art: String
    public var quelle: String
    public var ampel: StatikAmpel
    public var ziel: Double?
    public var text: String
    public var beschreibung: String?
    public var kennzahlen: StatikKennzahlen
    public var urteile: [StatikUrteil]
    public var teile: [StatikTeil]
    public var staebe: [StatikStab]
    public var ueberhoehung: Float
    public var kippen: [StatikKippen]

    public var id: String { name }

    init(json j: JSONValue) {
        name = j["name"]?.stringValue ?? "?"
        art = j["art"]?.stringValue ?? "statisch"
        quelle = j["quelle"]?.stringValue ?? "modell"
        ampel = StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau
        ziel = j["ziel"]?.doubleValue
        text = j["text"]?.stringValue ?? ""
        beschreibung = j["beschreibung"]?.stringValue
        kennzahlen = StatikKennzahlen(json: j["kennzahlen"])
        urteile = (j["urteile"]?.arrayValue ?? []).enumerated().map { StatikUrteil(json: $1, index: $0) }
        teile = (j["teile"]?.arrayValue ?? []).map(StatikTeil.init(json:))
        staebe = (j["staebe"]?.arrayValue ?? []).map(StatikStab.init(json:))
        ueberhoehung = Float(j["ueberhoehung"]?.doubleValue ?? 1)
        kippen = (j["kippen"]?.arrayValue ?? []).map(StatikKippen.init(json:))
    }

    /// Urteile, die etwas zu sagen haben (rot, gelb, überdimensioniert, nicht gerechnet).
    public var auffaellig: [StatikUrteil] {
        urteile.filter { $0.ampel != .gruen || $0.art == "ueberdimensioniert" }
            .sorted { $0.ampel.rang > $1.ampel.rang }
    }
}

public struct StatikErgebnis: Equatable, Sendable {
    public var run: Int
    public var stand: String
    public var aktiv: String?
    public var meldung: String?
    public var szenarien: [StatikSzenario]
    public var ueberdimensioniert: [StatikUrteil]
    public var grenzen: [String]
    public var vereinfachungen: [String]
    public var ms: Double?
    /// Der Kernel will das Szenario `aktiv` im Viewer zeigen (Agent: `szenario_rechnen`, `statik(szenario)`).
    public var zeigen: Bool
    public var replyTo: String?

    public init(json j: JSONValue) {
        run = j["run"]?.intValue ?? 0
        stand = j["stand"]?.stringValue ?? "done"
        aktiv = j["aktiv"]?.stringValue
        meldung = j["meldung"]?.stringValue
        szenarien = (j["szenarien"]?.arrayValue ?? []).map(StatikSzenario.init(json:))
        ueberdimensioniert = (j["ueberdimensioniert"]?.arrayValue ?? []).enumerated()
            .map { StatikUrteil(json: $1, index: $0) }
        grenzen = j["grenzen"]?.stringList ?? []
        vereinfachungen = j["vereinfachungen"]?.stringList ?? []
        ms = j["ms"]?.doubleValue
        zeigen = j["zeigen"]?.boolValue ?? false
        replyTo = j["reply_to"]?.stringValue
    }

    public func szenario(_ name: String?) -> StatikSzenario? {
        guard let name else { return nil }
        return szenarien.first { $0.name == name }
    }

    /// Schlechteste Ampel über alle Szenarien.
    public var ampel: StatikAmpel {
        szenarien.map(\.ampel).max { $0.rang < $1.rang } ?? .grau
    }

    public static func decode(_ header: Data) throws -> StatikErgebnis {
        StatikErgebnis(json: try JSONDecoder().decode(JSONValue.self, from: header))
    }
}
