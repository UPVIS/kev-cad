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
    /// Stufe 3 (additiv): Ausnutzung aus der Festkörper-FEM.
    public var fem: Bool

    init(json j: JSONValue) {
        name = j["name"]?.stringValue ?? ""
        ausnutzung = j["ausnutzung"]?.doubleValue ?? 0
        ampel = StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau
        verformungMm = j["verformung_mm"]?.doubleValue
        sicherheit = j["sicherheit"]?.doubleValue
        fem = j["fem"]?.boolValue ?? false
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

/// Eine Last des Szenarios mit Angriffspunkt (Welt, mm) und Kraft (N). Ein Kraftpaar (innere Kraft zwischen zwei Teilen,
/// `st.last(…, gegen=…)`) hat `gegen`: dort wirkt am selben Punkt die Gegenkraft −kraft (PROTOCOL.md „Statik“, `lasten`).
public struct StatikLast: Equatable, Sendable {
    public var teile: [String]
    public var gegen: [String]
    public var kraft: SIMD3<Float>
    public var punkt: SIMD3<Float>
    public var kg: Double?
    /// Last aus der App (Bereich Simulation): Kennung in simulation.json (additiv).
    public var id: String?

    public var paar: Bool { !gegen.isEmpty }
    /// Betrag der Kraft in N.
    public var betrag: Float { simd_length(kraft) }

    public init(teile: [String], gegen: [String] = [], kraft: SIMD3<Float>, punkt: SIMD3<Float>, kg: Double? = nil) {
        self.teile = teile
        self.gegen = gegen
        self.kraft = kraft
        self.punkt = punkt
        self.kg = kg
    }

    init?(json j: JSONValue) {
        guard let kraft = j["kraft"]?.vector3, let punkt = j["punkt"]?.vector3 else { return nil }
        self.init(
            teile: j["teile"]?.stringList ?? [], gegen: j["gegen"]?.stringList ?? [], kraft: kraft, punkt: punkt,
            kg: j["kg"]?.doubleValue)
        id = j["id"]?.stringValue
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

/// Ablauf (Stufe 2, Dynamik mit MuJoCo) eines Szenarios: Stand, Ampel, Kennzahlen, Verlauf je Bild und
/// Kontaktpfeile; abgespielt wird er als Animation `animation` (ANIM_DEF) in der Zeitleiste.
public struct StatikAblauf: Equatable, Sendable {
    public struct Ladung: Equatable, Sendable {
        public var name: String
        public var versatzMm: Double?
        public var hebtMm: Double?
        public var bleibt: Bool
        public var vGrenze: Double?
    }

    /// Kontaktkraft in einem Bild: Angriffspunkt (Welt, mm) und Kraft (N), Paar der Körper.
    public struct Pfeil: Equatable, Sendable {
        public var punkt: SIMD3<Float>
        public var kraft: SIMD3<Float>
        public var paar: [String]
    }

    public var stand: String
    public var ampel: StatikAmpel
    public var text: String
    public var animation: String?
    public var meldung: String?
    public var dauer: Double?
    public var fps: Double
    public var bilder: Int
    public var geschwindigkeit: Double?
    public var verzoegerung: Double?
    public var bremsen: String?
    public var kippreserve: Double?
    public var aAbheben: Double?
    public var aAbhebenOhneLadung: Double?
    public var aKippHand: Double?
    public var vAbheben: Double?
    public var abhebenMaxMm: Double?
    public var kippwinkelMax: Double?
    public var rutschgrenze: Double?
    public var rutschreserve: Double?
    public var setztAuf: String?
    public var ladung: [Ladung]
    public var handrechnung: String?
    public var zeit: [Double]
    public var kipp: [Double]
    public var abheben: [Double]
    public var pfeile: [[Pfeil]]
    public var msAblauf: Double?
    public var msSuche: Double?
    public var varianten: Int?

    public var laeuft: Bool { stand == "laeuft" }
    public var fertig: Bool { stand == "done" }

    init(json j: JSONValue) {
        stand = j["stand"]?.stringValue ?? "done"
        ampel = StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau
        text = j["text"]?.stringValue ?? ""
        animation = j["animation"]?.stringValue
        meldung = j["meldung"]?.stringValue
        dauer = j["dauer"]?.doubleValue
        fps = j["fps"]?.doubleValue ?? 50
        bilder = j["bilder"]?.intValue ?? 0
        let an = j["antrieb"]
        geschwindigkeit = an?["geschwindigkeit"]?.doubleValue
        verzoegerung = an?["verzoegerung"]?.doubleValue
        bremsen = an?["bremsen"]?.stringValue
        let k = j["kennzahlen"]
        kippreserve = k?["kippreserve"]?.doubleValue
        aAbheben = k?["a_abheben"]?.doubleValue
        aAbhebenOhneLadung = k?["a_abheben_ohne_ladung"]?.doubleValue
        aKippHand = k?["a_kipp_hand"]?.doubleValue
        vAbheben = k?["v_abheben"]?.doubleValue
        abhebenMaxMm = k?["abheben_max_mm"]?.doubleValue
        kippwinkelMax = k?["kippwinkel_max"]?.doubleValue
        rutschgrenze = k?["rutschgrenze"]?.doubleValue
        rutschreserve = k?["rutschreserve"]?.doubleValue
        setztAuf = k?["setzt_auf"]?.stringValue
        ladung = (k?["ladung"]?.arrayValue ?? []).map {
            Ladung(
                name: $0["name"]?.stringValue ?? "", versatzMm: $0["versatz_max_mm"]?.doubleValue,
                hebtMm: $0["hebt_max_mm"]?.doubleValue, bleibt: $0["bleibt"]?.boolValue ?? true,
                vGrenze: $0["v_grenze"]?.doubleValue)
        }
        handrechnung = j["handrechnung"]?["text"]?.stringValue
        let v = j["verlauf"]
        zeit = v?["zeit"]?.doubles ?? []
        kipp = v?["kipp"]?.doubles ?? []
        abheben = v?["abheben"]?.doubles ?? []
        pfeile = (j["pfeile"]?.arrayValue ?? []).map { bild in
            (bild.arrayValue ?? []).compactMap { p in
                guard let punkt = p["punkt"]?.vector3, let kraft = p["kraft"]?.vector3 else { return nil }
                return Pfeil(punkt: punkt, kraft: kraft, paar: p["paar"]?.stringList ?? [])
            }
        }
        msAblauf = j["ms"]?["ablauf"]?.doubleValue
        msSuche = j["ms"]?["suche"]?.doubleValue
        varianten = j["ms"]?["varianten"]?.intValue
    }

    /// Bild zur Zeit t (wie ANIM_DEF: Bild k bei k / fps).
    public func bild(zur t: Double) -> Int {
        guard bilder > 0 else { return 0 }
        return min(max(Int((t * fps).rounded()), 0), bilder - 1)
    }

    /// Größte Kontaktkraft über alle Bilder (N), für den Maßstab der Pfeile.
    public var kraftMax: Float {
        pfeile.flatMap { $0 }.map { simd_length($0.kraft) }.max() ?? 0
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
    /// Lasten mit Angriffspunkt, Kraftpaare mit Gegenseite (additiv; ältere Kernel schicken keine).
    public var lasten: [StatikLast]
    /// Stufe 2: Ablauf (nur bei Szenarien mit Geschwindigkeit, Bremsen oder Animation).
    public var ablauf: StatikAblauf?
    /// Stufe 3: Festkörper-FEM der Teile mit Last (läuft im Hintergrund nach dem Lauf oder auf Anfrage).
    public var festkoerper: StatikFestkoerper?
    /// Simulation (additiv): Kennungen der ausdrücklichen Lager, die in diesem Szenario gelten (Lager je Lastfall);
    /// nil bei älteren Kerneln.
    public var lagerIDs: [String]?
    /// Simulation (additiv): eigener Untergrund des Szenarios (Rutschen in S0 und Ablauf), sonst nil.
    public var untergrund: String?

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
        lasten = (j["lasten"]?.arrayValue ?? []).compactMap(StatikLast.init(json:))
        ablauf = j["ablauf"].flatMap { $0.objectValue == nil ? nil : StatikAblauf(json: $0) }
        festkoerper = j["festkoerper"].flatMap { $0.objectValue == nil ? nil : StatikFestkoerper(json: $0) }
        lagerIDs = j["lager"]?.arrayValue.map { $0.compactMap(\.stringValue) }
        untergrund = j["untergrund"]?.stringValue
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
