import Foundation
import simd

// Bereich „Simulation“ (PROTOCOL.md „Simulation“, PLAN-SIMULATION.md, additiv): SIM trägt die Lastfälle, Lasten und Lager
// aus <projekt>/simulation.json mit ihrem Zustand im aktuellen Modell, dazu die Szenarien und Lager aus model.py, die
// abgeleiteten Lager und die Topologie-Einstellungen; SIM_JOB den Stand eines Auftrags (Rechnen, Festigkeit, Ablauf,
// Grenze). App → Kernel: SIM_REQ, SIM_EDIT (Operationen), SIM_RUN, SIM_CANCEL.

/// Zustand einer Last bzw. eines Lagers im aktuellen Modell.
public enum SimZuordnung: String, Sendable, Equatable {
    /// Teil und Fläche passen.
    case ok
    /// nach einer Modelländerung einer anderen Fläche bzw. einem umbenannten Teil zugeordnet
    case neu
    /// nicht mehr zuordenbar: zählt nicht mit
    case fehlt
    /// noch kein Lauf
    case offen
}

/// Ort einer Last bzw. eines Lagers: Fläche (Nummer wie im Viewer), Punkt (Welt, mm), Normale und Signatur der Fläche.
public struct SimOrt: Equatable, Sendable {
    public var flaeche: Int?
    public var punkt: SIMD3<Float>?
    public var normale: SIMD3<Float>?
    /// Signatur wie `PART_UPSERT.faces[i]` (für die Zuordnung nach Modelländerungen).
    public var signatur: JSONValue?

    public init(flaeche: Int? = nil, punkt: SIMD3<Float>? = nil, normale: SIMD3<Float>? = nil,
                signatur: JSONValue? = nil) {
        self.flaeche = flaeche
        self.punkt = punkt
        self.normale = normale
        self.signatur = signatur
    }

    init(json j: JSONValue?) {
        flaeche = j?["flaeche"]?.intValue
        punkt = j?["punkt"]?.vector3
        normale = j?["normale"]?.vector3
        signatur = j?["signatur"].flatMap { $0.objectValue == nil ? nil : $0 }
    }

    public var json: JSONValue {
        var o: [String: JSONValue] = [:]
        o["flaeche"] = flaeche.map { .number(Double($0)) } ?? .null
        o["punkt"] = punkt.map(SimJSON.vec) ?? .null
        o["normale"] = normale.map(SimJSON.vec) ?? .null
        o["signatur"] = signatur ?? .null
        return .object(o)
    }
}

/// Richtung einer Kraft: entlang der Normale (in die Fläche hinein), entlang einer Achse oder frei.
public struct SimRichtung: Equatable, Sendable {
    public enum Art: String, CaseIterable, Sendable {
        case normale, achse, frei

        public var titel: String {
            switch self {
            case .normale: return "Normale"
            case .achse: return "Achse"
            case .frei: return "Frei"
            }
        }
    }

    public var art: Art
    /// `+x`, `-x`, `+y`, `-y`, `+z`, `-z`
    public var achse: String
    /// Frei: Azimut in der XY-Ebene ab +X (Grad) und Höhe über der XY-Ebene (Grad).
    public var azimut: Double
    public var hoehe: Double
    /// Frei als Vektor (aus model.py oder vom Agenten); hat Vorrang vor den Winkeln.
    public var vektor: SIMD3<Float>?
    public var umkehren: Bool

    public init(art: Art = .normale, achse: String = "-z", azimut: Double = 0, hoehe: Double = -90,
                vektor: SIMD3<Float>? = nil, umkehren: Bool = false) {
        self.art = art
        self.achse = achse
        self.azimut = azimut
        self.hoehe = hoehe
        self.vektor = vektor
        self.umkehren = umkehren
    }

    init(json j: JSONValue?) {
        art = Art(rawValue: j?["art"]?.stringValue ?? "") ?? .normale
        achse = j?["achse"]?.stringValue ?? "-z"
        vektor = j?["vektor"]?.vector3
        umkehren = j?["umkehren"]?.boolValue ?? false
        if let v = vektor, simd_length(v) > 1e-9 {
            let w = SimKraft.winkel(v)
            azimut = w.azimut
            hoehe = w.hoehe
        } else {
            azimut = j?["azimut"]?.doubleValue ?? 0
            hoehe = j?["hoehe"]?.doubleValue ?? 0
        }
    }

    public var json: JSONValue {
        var o: [String: JSONValue] = ["art": .string(art.rawValue)]
        switch art {
        case .normale: break
        case .achse: o["achse"] = .string(achse)
        case .frei:
            o["azimut"] = .number(azimut)
            o["hoehe"] = .number(hoehe)
        }
        if umkehren { o["umkehren"] = .bool(true) }
        return .object(o)
    }
}

/// Gleitrichtung eines gleitenden Lagers (additiv, simulation2): in der Fläche (hält nur senkrecht zu ihr) oder nur
/// entlang einer Richtung (Schiene: hält quer dazu in beide Richtungen).
public struct SimGleiten: Equatable, Sendable {
    public enum Art: String, Sendable { case flaeche, richtung }

    public var art: Art
    /// Richtung, entlang der das Lager frei ist (Welt, Einheitsvektor), nur bei `.richtung`.
    public var richtung: SIMD3<Float>?
    /// achse | kante | frei
    public var quelle: String
    /// Angeklickte Kante (Nummer wie im Viewer), wenn `quelle` "kante" ist.
    public var kante: Int?

    public init(art: Art = .flaeche, richtung: SIMD3<Float>? = nil, quelle: String = "frei", kante: Int? = nil) {
        self.art = art
        self.richtung = richtung.map { simd_length($0) > 1e-9 ? simd_normalize($0) : $0 }
        self.quelle = quelle
        self.kante = kante
    }

    /// In der Fläche (Standard).
    public static let flaeche = SimGleiten()

    /// Entlang einer Weltachse ("+x" … "-z").
    public static func achse(_ t: String) -> SimGleiten {
        SimGleiten(art: .richtung, richtung: SimKraft.achse(t), quelle: "achse")
    }

    init?(json j: JSONValue?) {
        guard let j, j.objectValue != nil else { return nil }
        art = Art(rawValue: j["art"]?.stringValue ?? "") ?? (j["richtung"] != nil ? .richtung : .flaeche)
        richtung = j["richtung"]?.vector3
        quelle = j["quelle"]?.stringValue ?? "frei"
        kante = j["kante"]?.intValue
    }

    /// Für SIM_EDIT (`lager_setzen.lager.gleiten`); nil für „in der Fläche“.
    public var json: JSONValue? {
        guard art == .richtung, let r = richtung else { return nil }
        var o: [String: JSONValue] = ["art": .string("richtung"), "richtung": SimJSON.vec(r), "quelle": .string(quelle)]
        if let k = kante { o["kante"] = .number(Double(k)) }
        return .object(o)
    }

    /// Kurztext: „in der Fläche“, „entlang +X“, „entlang Kante 7“, „entlang (0,71; 0,71; 0)“.
    public var titel: String {
        guard art == .richtung, let r = richtung else { return "in der Fläche" }
        if quelle == "kante", let k = kante { return "entlang Kante \(k)" }
        if let a = SimKraft.achsen.first(where: { simd_dot($0.1, r) > 0.9999 }) {
            return "entlang " + a.0.replacingOccurrences(of: "-", with: "−").uppercased()
        }
        let f = { (x: Float) in String(format: "%.2f", Double(x)).replacingOccurrences(of: ".", with: ",") }
        return "entlang (\(f(r.x)); \(f(r.y)); \(f(r.z)))"
    }
}

/// Eine Last eines Lastfalls aus der App.
public struct SimLast: Identifiable, Equatable, Sendable {
    public var id: String
    public var teil: String
    /// Kraftpaar: die Gegenkraft wirkt am selben Punkt auf dieses Teil.
    public var gegen: String?
    public var ort: SimOrt
    public var richtung: SimRichtung
    public var betrag: Double
    /// "N", "kg" oder "N/mm2" (Druck auf die ganze Fläche)
    public var einheit: String
    /// Kraft in N (Welt), wie gespeichert.
    public var kraft: SIMD3<Float>
    public var zustand: SimZuordnung
    public var zustandText: String
    /// Im aktuellen Modell wirksam (nach der Zuordnung), sonst nil.
    public var kraftWirksam: SIMD3<Float>?
    public var punktWirksam: SIMD3<Float>?
    public var normaleWirksam: SIMD3<Float>?
    public var flaecheWirksam: Int?
    /// Am Klickpunkt ("punkt", Standard) oder gleichmäßig auf der ganzen angeklickten Fläche ("flaeche"), additiv.
    public var verteilung: String = "punkt"
    /// Flächeninhalt (mm²), mit dem der Kernel eine Last auf der ganzen Fläche rechnet.
    public var flaecheMm2Wirksam: Double?

    public init(id: String = "", teil: String, gegen: String? = nil, ort: SimOrt, richtung: SimRichtung,
                betrag: Double, einheit: String = "N", kraft: SIMD3<Float> = .zero, zustand: SimZuordnung = .offen,
                zustandText: String = "", verteilung: String = "punkt") {
        self.id = id
        self.teil = teil
        self.gegen = gegen
        self.ort = ort
        self.richtung = richtung
        self.betrag = betrag
        self.einheit = einheit
        self.kraft = kraft
        self.zustand = zustand
        self.zustandText = zustandText
        self.verteilung = verteilung
    }

    init(json j: JSONValue) {
        self.init(
            id: j["id"]?.stringValue ?? "", teil: j["teil"]?.stringValue ?? "", gegen: j["gegen"]?.stringValue,
            ort: SimOrt(json: j["ort"]), richtung: SimRichtung(json: j["richtung"]),
            betrag: j["betrag"]?.doubleValue ?? 0, einheit: j["einheit"]?.stringValue ?? "N",
            kraft: j["kraft"]?.vector3 ?? .zero,
            zustand: SimZuordnung(rawValue: j["zustand"]?.stringValue ?? "") ?? .offen,
            zustandText: j["zustand_text"]?.stringValue ?? "", verteilung: j["verteilung"]?.stringValue ?? "punkt")
        kraftWirksam = j["kraft_wirksam"]?.vector3
        punktWirksam = j["punkt_wirksam"]?.vector3
        normaleWirksam = j["normale_wirksam"]?.vector3
        flaecheWirksam = j["flaeche_wirksam"]?.intValue
        flaecheMm2Wirksam = j["flaeche_mm2_wirksam"]?.doubleValue
    }

    /// Für SIM_EDIT (`last_setzen`): ohne Zustand und ohne Kraft (die rechnet der Kernel).
    public var json: JSONValue {
        var o: [String: JSONValue] = [
            "teil": .string(teil), "ort": ort.json, "richtung": richtung.json, "betrag": .number(betrag),
            "einheit": .string(einheit),
        ]
        if !id.isEmpty { o["id"] = .string(id) }
        o["gegen"] = gegen.map(JSONValue.string) ?? .null
        if verteilung == "flaeche" { o["verteilung"] = .string("flaeche") }
        return .object(o)
    }

    /// Angriffspunkt für den Viewer: wirksam, sonst gespeichert.
    public var punkt: SIMD3<Float>? { punktWirksam ?? ort.punkt }
    /// Auf der ganzen Fläche (gleichmäßig oder als Druck).
    public var aufFlaeche: Bool { verteilung == "flaeche" }
    /// Flächeninhalt (mm²): wirksam, sonst aus der Signatur der angeklickten Fläche.
    public var flaecheMm2: Double? { flaecheMm2Wirksam ?? ort.signatur?["a"]?.doubleValue }
    public var betragN: Double { SimKraft.betragN(betrag, einheit: einheit, flaecheMm2: flaecheMm2) }
    public var paar: Bool { gegen != nil }
}

/// Ein Lager (aus der App oder aus model.py).
public struct SimLager: Identifiable, Equatable, Sendable {
    public enum Art: String, CaseIterable, Sendable {
        case fest, gelenkig, gleitend

        public var titel: String {
            switch self {
            case .fest: return "Fest"
            case .gelenkig: return "Gelenkig"
            case .gleitend: return "Gleitend"
            }
        }
        public var hilfe: String {
            switch self {
            case .fest: return "eingespannt: hält in allen Richtungen und gegen Drehen"
            case .gelenkig:
                return "hält in allen Richtungen, dreht frei (am Stab ein Gelenk; in der FEM hält die Fläche im Mittel "
                    + "und dreht frei, Bohrung: nur um ihre Achse)"
            case .gleitend:
                return "gleitet in der Fläche und hält nur senkrecht zu ihr, oder wie auf einer Schiene nur entlang "
                    + "einer Richtung (Achse, Kante)"
            }
        }
    }

    /// Lagerfläche: ganze Fläche, Umkreis eines Punkts oder ganzes Teil.
    public enum Auf: String, CaseIterable, Sendable {
        case flaeche, punkt, teil

        public var titel: String {
            switch self {
            case .flaeche: return "Fläche"
            case .punkt: return "Punkt"
            case .teil: return "Ganzes Teil"
            }
        }
    }

    public var id: String
    public var teil: String
    public var art: Art
    public var auf: Auf
    public var ort: SimOrt
    public var quelle: String
    public var zeile: Int?
    public var zustand: SimZuordnung
    public var zustandText: String
    public var punktWirksam: SIMD3<Float>?
    public var normaleWirksam: SIMD3<Float>?
    /// Lastfälle, in denen das Lager gilt (additiv): nil = alle, Namen = nur diese, leer = in keinem.
    public var szenarien: [String]?
    /// Gleitrichtung (nur gleitend, additiv): nil = in der Fläche.
    public var gleiten: SimGleiten?
    /// Gehaltene Richtungen (Einheitsvektoren, Welt), wie der Kernel rechnet (nur gleitend).
    public var gehaltenWirksam: [SIMD3<Float>] = []

    public init(id: String = "", teil: String, art: Art = .fest, auf: Auf = .flaeche, ort: SimOrt = SimOrt(),
                quelle: String = "app", zeile: Int? = nil, zustand: SimZuordnung = .offen, zustandText: String = "",
                szenarien: [String]? = nil, gleiten: SimGleiten? = nil) {
        self.id = id
        self.teil = teil
        self.art = art
        self.auf = auf
        self.ort = ort
        self.quelle = quelle
        self.zeile = zeile
        self.zustand = zustand
        self.zustandText = zustandText
        self.szenarien = szenarien
        self.gleiten = gleiten
    }

    init(json j: JSONValue) {
        // Lager aus model.py tragen Punkt und Normale flach (Kurzfassung des Kernels)
        var ort = SimOrt(json: j["ort"])
        if j["ort"] == nil {
            ort = SimOrt(flaeche: j["flaeche"]?.intValue, punkt: j["punkt"]?.vector3, normale: j["normale"]?.vector3)
        }
        let szen: [String]? = j["szenarien"]?.arrayValue.map { $0.compactMap(\.stringValue) }
        self.init(
            id: j["id"]?.stringValue ?? "", teil: j["teil"]?.stringValue ?? "",
            art: Art(rawValue: j["art"]?.stringValue ?? "") ?? .fest,
            auf: Auf(rawValue: j["auf"]?.stringValue ?? "") ?? (ort.flaeche != nil ? .flaeche : .punkt), ort: ort,
            quelle: j["quelle"]?.stringValue ?? "app", zeile: j["zeile"]?.intValue,
            zustand: SimZuordnung(rawValue: j["zustand"]?.stringValue ?? "") ?? .offen,
            zustandText: j["zustand_text"]?.stringValue ?? "", szenarien: szen,
            gleiten: SimGleiten(json: j["gleiten"]).flatMap { $0.art == .richtung ? $0 : nil })
        punktWirksam = j["punkt_wirksam"]?.vector3 ?? (j["ort"] == nil ? ort.punkt : nil)
        normaleWirksam = j["normale_wirksam"]?.vector3 ?? (j["ort"] == nil ? ort.normale : nil)
        gehaltenWirksam = (j["gehalten_wirksam"]?.arrayValue ?? j["gehalten"]?.arrayValue ?? []).compactMap(\.vector3)
    }

    public var json: JSONValue {
        var o: [String: JSONValue] = [
            "teil": .string(teil), "art": .string(art.rawValue), "auf": .string(auf.rawValue), "ort": ort.json,
            "szenarien": szenarien.map { .array($0.map(JSONValue.string)) } ?? .null,
        ]
        if !id.isEmpty { o["id"] = .string(id) }
        if art == .gleitend, let g = gleiten?.json { o["gleiten"] = g }
        return .object(o)
    }

    public var punkt: SIMD3<Float>? { punktWirksam ?? ort.punkt }
    public var normale: SIMD3<Float>? { normaleWirksam ?? ort.normale }

    /// Gilt das Lager im Lastfall `name`? (nil: ohne Lastfall nur Lager für alle)
    public func giltFuer(_ name: String?) -> Bool {
        guard let s = szenarien else { return true }
        guard let name else { return false }
        return s.contains(name)
    }

    /// „alle Lastfälle“, „nur „A““, „„A“, „B““, „in keinem Lastfall“.
    public var giltText: String {
        guard let s = szenarien else { return "alle Lastfälle" }
        if s.isEmpty { return "in keinem Lastfall" }
        let namen = s.map { "„\($0)“" }.joined(separator: ", ")
        return s.count == 1 ? "nur \(namen)" : namen
    }
}

/// Fahrt eines dynamischen Lastfalls (Ablauf, Stufe 2).
public struct SimFahrt: Equatable, Sendable {
    public enum Bremsen: Equatable, Sendable {
        case abrupt, anprall, verzoegerung(Double), keins

        public var json: JSONValue {
            switch self {
            case .abrupt: return .string("abrupt")
            case .anprall: return .string("anprall")
            case .verzoegerung(let a): return .number(a)
            case .keins: return .null
            }
        }
    }

    public var geschwindigkeit: Double?
    public var bremsen: Bremsen
    public var dauer: Double?
    public var animation: String?
    /// Angriff am Boden (nil) oder in einer Höhe (mm).
    public var angriffHoehe: Double?
    public var fahrtrichtung: String
    public var antrieb: String?

    public init(geschwindigkeit: Double? = 1, bremsen: Bremsen = .abrupt, dauer: Double? = nil,
                animation: String? = nil, angriffHoehe: Double? = nil, fahrtrichtung: String = "+x",
                antrieb: String? = nil) {
        self.geschwindigkeit = geschwindigkeit
        self.bremsen = bremsen
        self.dauer = dauer
        self.animation = animation
        self.angriffHoehe = angriffHoehe
        self.fahrtrichtung = fahrtrichtung
        self.antrieb = antrieb
    }

    init?(json j: JSONValue?) {
        guard let j, j.objectValue != nil else { return nil }
        geschwindigkeit = j["geschwindigkeit"]?.doubleValue
        switch j["bremsen"] {
        case .string("abrupt")?: bremsen = .abrupt
        case .string("anprall")?: bremsen = .anprall
        case .number(let a)?: bremsen = .verzoegerung(a)
        default: bremsen = .keins
        }
        dauer = j["dauer"]?.doubleValue
        animation = j["animation"]?.stringValue
        angriffHoehe = j["angriff"]?.doubleValue
        fahrtrichtung = j["fahrtrichtung"]?.stringValue ?? "+x"
        antrieb = j["antrieb"]?.stringValue
    }

    public var json: JSONValue {
        .object([
            "geschwindigkeit": geschwindigkeit.map(JSONValue.number) ?? .null, "bremsen": bremsen.json,
            "dauer": dauer.map(JSONValue.number) ?? .null, "animation": animation.map(JSONValue.string) ?? .null,
            "angriff": angriffHoehe.map(JSONValue.number) ?? .string("boden"),
            "fahrtrichtung": .string(fahrtrichtung), "antrieb": antrieb.map(JSONValue.string) ?? .null,
        ])
    }
}

/// Ein Lastfall aus der App.
public struct SimLastfall: Identifiable, Equatable, Sendable {
    public var name: String
    public var dynamisch: Bool
    public var beschreibung: String
    public var kopieVon: String?
    public var neigungGrad: Double
    public var neigungRichtung: String
    public var beschleunigung: SIMD3<Float>?
    public var fahrt: SimFahrt?
    public var stoss: Double?
    public var untergrund: String?
    public var zielSicherheit: Double?
    /// Durchbiegung L/x (x).
    public var zielDurchbiegung: Double?
    public var lasten: [SimLast]
    public var ampel: StatikAmpel?
    public var text: String
    public var gerechnet: Bool

    public var id: String { name }

    public init(name: String, dynamisch: Bool = false, lasten: [SimLast] = []) {
        self.name = name
        self.dynamisch = dynamisch
        beschreibung = ""
        neigungGrad = 0
        neigungRichtung = "+x"
        self.lasten = lasten
        text = ""
        gerechnet = false
    }

    init(json j: JSONValue) {
        self.init(name: j["name"]?.stringValue ?? "?", dynamisch: j["art"]?.stringValue == "dynamisch",
                  lasten: (j["lasten"]?.arrayValue ?? []).map(SimLast.init(json:)))
        beschreibung = j["beschreibung"]?.stringValue ?? ""
        kopieVon = j["kopie_von"]?.stringValue
        neigungGrad = j["neigung"]?["grad"]?.doubleValue ?? 0
        if let r = j["neigung"]?["richtung"]?.stringValue {
            neigungRichtung = r
        } else if let v = j["neigung"]?["richtung"]?.vector3 {
            neigungRichtung = SimJSON.achsText(v)
        }
        beschleunigung = j["beschleunigung"]?.vector3
        fahrt = SimFahrt(json: j["fahrt"])
        stoss = j["stoss"]?.doubleValue
        untergrund = j["untergrund"]?.stringValue
        zielSicherheit = j["ziel"]?["sicherheit"]?.doubleValue
        zielDurchbiegung = j["ziel"]?["durchbiegung"]?.doubleValue
        ampel = j["ampel"]?.stringValue.flatMap(StatikAmpel.init(rawValue:))
        text = j["text"]?.stringValue ?? ""
        gerechnet = j["gerechnet"]?.boolValue ?? false
    }

    /// Felder für `lastfall_setzen` (ohne Lasten).
    public var felder: JSONValue {
        var z: JSONValue = .null
        if zielSicherheit != nil || zielDurchbiegung != nil {
            z = .object(["sicherheit": zielSicherheit.map(JSONValue.number) ?? .null,
                         "durchbiegung": zielDurchbiegung.map(JSONValue.number) ?? .null])
        }
        return .object([
            "art": .string(dynamisch ? "dynamisch" : "statisch"), "beschreibung": .string(beschreibung),
            "neigung": neigungGrad > 0 ? .object(["grad": .number(neigungGrad), "richtung": .string(neigungRichtung)])
                : .null,
            "beschleunigung": beschleunigung.map(SimJSON.vec) ?? .null, "fahrt": fahrt?.json ?? .null,
            "stoss": stoss.map(JSONValue.number) ?? .null, "untergrund": untergrund.map(JSONValue.string) ?? .null,
            "ziel": z,
        ])
    }

    public func last(_ id: String?) -> SimLast? {
        guard let id else { return nil }
        return lasten.first { $0.id == id }
    }

    public var nichtZuordenbar: Int { lasten.filter { $0.zustand == .fehlt }.count }
}

/// Ein Szenario aus model.py oder ein Standardszenario (nur lesbar; „als Kopie bearbeiten“).
public struct SimModellLastfall: Identifiable, Equatable, Sendable {
    public var name: String
    /// modell | standard | agent
    public var quelle: String
    public var dynamisch: Bool
    public var zeile: Int?
    public var ampel: StatikAmpel?
    public var text: String
    public var beschreibung: String?
    /// Von einem gleichnamigen Lastfall der App ersetzt.
    public var ersetzt: Bool

    public var id: String { "\(name)\u{1F}\(ersetzt)" }

    init(json j: JSONValue) {
        name = j["name"]?.stringValue ?? "?"
        quelle = j["quelle"]?.stringValue ?? "modell"
        dynamisch = j["art"]?.stringValue == "dynamisch" || (j["dynamisch"]?.boolValue ?? false)
        zeile = j["zeile"]?.intValue
        ampel = j["ampel"]?.stringValue.flatMap(StatikAmpel.init(rawValue:))
        text = j["text"]?.stringValue ?? ""
        beschreibung = j["beschreibung"]?.stringValue
        ersetzt = j["ersetzt"]?.boolValue ?? false
    }

    public var herkunft: String {
        switch quelle {
        case "standard": return "Standard"
        case "agent": return "Agent"
        default: return zeile.map { "model.py, Zeile \($0)" } ?? "model.py"
        }
    }
}

/// Ein abgeleitetes Lager (Boden, Kulisse, Kontakt), abschaltbar.
public struct SimAbgeleitet: Identifiable, Equatable, Sendable {
    public var id: String
    /// boden | kontakt
    public var art: String
    public var teil: String
    public var nachbar: String?
    public var text: String
    public var punkt: SIMD3<Float>?
    public var aktiv: Bool
    /// Von einem ausdrücklichen Lager ersetzt (Kennung).
    public var ersetzt: String?

    init(json j: JSONValue) {
        id = j["id"]?.stringValue ?? ""
        art = j["art"]?.stringValue ?? "boden"
        teil = j["teil"]?.stringValue ?? ""
        nachbar = j["nachbar"]?.stringValue
        text = j["text"]?.stringValue ?? id
        punkt = j["punkt"]?.vector3
        aktiv = j["aktiv"]?.boolValue ?? true
        ersetzt = j["ersetzt"]?.stringValue
    }
}

/// Topologie-Einstellungen eines Druckteils (in simulation.json).
public struct SimTopologie: Equatable, Sendable {
    public struct Schutz: Equatable, Sendable, Identifiable {
        public var index: Int
        public var zustand: SimZuordnung
        public var text: String
        public var id: Int { index }
    }

    public var szenario: String?
    public var behalten: Double?
    public var ueberhang: Bool?
    public var fein: Bool?
    public var steg: Double?
    public var bohrungen: Bool?
    public var einsaetze: Bool?
    public var kontakt: Bool?
    public var bett: Bool?
    public var lager: String?
    public var schutz: [Schutz]

    public init() { schutz = [] }

    init(json j: JSONValue) {
        szenario = j["szenario"]?.stringValue
        behalten = j["behalten"]?.doubleValue
        ueberhang = j["ueberhang"]?.boolValue
        fein = j["fein"]?.boolValue
        steg = j["steg"]?.doubleValue
        bohrungen = j["bohrungen"]?.boolValue
        einsaetze = j["einsaetze"]?.boolValue
        kontakt = j["kontakt"]?.boolValue
        bett = j["bett"]?.boolValue
        lager = j["lager"]?.stringValue
        schutz = (j["schutz"]?.arrayValue ?? []).compactMap { s in
            guard let i = s["index"]?.intValue else { return nil }
            return Schutz(index: i, zustand: SimZuordnung(rawValue: s["zustand"]?.stringValue ?? "") ?? .ok,
                          text: s["text"]?.stringValue ?? "")
        }
    }
}

/// Ein Grenzwert aus „Grenze suchen“.
public struct SimGrenzwert: Equatable, Sendable, Identifiable {
    public var kriterium: String
    public var grenze: Double
    public var einheit: String
    public var text: String
    public var massgebend: String?
    public var lastN: Double?
    /// Verfahren, mit dem der Wert gesucht ist (additiv): S0, S1, FEM oder Ablauf.
    public var verfahren: String?
    public var id: String { kriterium + "\u{1F}" + (verfahren ?? "") }
}

/// Stand eines Auftrags (SIM_JOB).
public struct SimJob: Equatable, Sendable {
    public var auftrag: Int
    /// rechnen | festigkeit | ablauf | grenze
    public var was: String
    public var lastfall: String?
    public var teil: String?
    public var grenze: String?
    public var stand: String
    public var fortschritt: Double?
    public var text: String
    public var meldung: String?
    public var werte: [SimGrenzwert]
    public var ergebnisText: String?
    public var ms: Double?
    /// Grenze: gesucht mit "s0s1" oder "fem" (additiv), maßgebendes Verfahren, Probe der FEM bei der Grenze, Hinweis.
    public var verfahren: String?
    public var massgebendVerfahren: String?
    public var probeFaktor: Double?
    public var probeAusnutzung: Double?
    public var probeTeil: String?
    public var hinweis: String?

    public var laeuft: Bool { stand == "laeuft" }

    public init(json j: JSONValue) {
        auftrag = j["auftrag"]?.intValue ?? 0
        was = j["was"]?.stringValue ?? "rechnen"
        lastfall = j["lastfall"]?.stringValue
        teil = j["teil"]?.stringValue
        grenze = j["grenze"]?.stringValue
        stand = j["stand"]?.stringValue ?? "laeuft"
        fortschritt = j["fortschritt"]?.doubleValue
        text = j["text"]?.stringValue ?? ""
        meldung = j["meldung"]?.stringValue
        ergebnisText = j["ergebnis"]?["text"]?.stringValue
        werte = (j["ergebnis"]?["werte"]?.arrayValue ?? []).map { w in
            SimGrenzwert(kriterium: w["kriterium"]?.stringValue ?? "", grenze: w["grenze"]?.doubleValue ?? 0,
                         einheit: w["einheit"]?.stringValue ?? "", text: w["text"]?.stringValue ?? "",
                         massgebend: w["massgebend"]?.stringValue, lastN: w["last_n"]?.doubleValue,
                         verfahren: w["verfahren"]?.stringValue)
        }
        ms = j["ms"]?.doubleValue
        let e = j["ergebnis"]
        verfahren = e?["verfahren"]?.stringValue
        massgebendVerfahren = e?["massgebend_verfahren"]?.stringValue
        probeFaktor = e?["probe"]?["faktor"]?.doubleValue
        probeAusnutzung = e?["probe"]?["ausnutzung"]?.doubleValue
        probeTeil = e?["probe"]?["teil"]?.stringValue
        hinweis = e?["hinweis"]?.stringValue
    }

    public var titel: String {
        switch was {
        case "rechnen": return "Rechnen"
        case "festigkeit": return "Festigkeit (FEM)"
        case "ablauf": return "Ablauf"
        default:
            switch grenze {
            case "last": return "Grenze: wie viel Last"
            case "neigung": return "Grenze: wie steil"
            default: return "Grenze: wie schnell"
            }
        }
    }

    public static func decode(_ header: Data) throws -> SimJob {
        SimJob(json: try JSONDecoder().decode(JSONValue.self, from: header))
    }
}

/// Inhalt von SIM.
public struct SimStand: Equatable, Sendable {
    public var run: Int
    /// Stand von simulation.json (zählt jede Änderung).
    public var stand: Int
    public var datei: String
    public var vorhanden: Bool
    public var lastfaelle: [SimLastfall]
    public var modell: [SimModellLastfall]
    public var lager: [SimLager]
    public var modellLager: [SimLager]
    public var abgeleitet: [SimAbgeleitet]
    public var topologie: [String: SimTopologie]
    public var hinweise: [String]
    public var fehler: String?
    public var job: SimJob?
    public var replyTo: String?

    public init(json j: JSONValue) {
        run = j["run"]?.intValue ?? 0
        stand = j["stand"]?.intValue ?? 0
        datei = j["datei"]?.stringValue ?? "simulation.json"
        vorhanden = j["vorhanden"]?.boolValue ?? false
        lastfaelle = (j["lastfaelle"]?.arrayValue ?? []).map(SimLastfall.init(json:))
        modell = (j["modell"]?.arrayValue ?? []).map(SimModellLastfall.init(json:))
        lager = (j["lager"]?.arrayValue ?? []).map(SimLager.init(json:))
        modellLager = (j["modell_lager"]?.arrayValue ?? []).map(SimLager.init(json:))
        abgeleitet = (j["abgeleitet"]?.arrayValue ?? []).map(SimAbgeleitet.init(json:))
        var t: [String: SimTopologie] = [:]
        for (k, v) in j["topologie"]?.objectValue ?? [:] { t[k] = SimTopologie(json: v) }
        topologie = t
        hinweise = j["hinweise"]?.stringList ?? []
        fehler = j["fehler"]?.stringValue
        job = j["job"].flatMap { $0.objectValue == nil ? nil : SimJob(json: $0) }
        replyTo = j["reply_to"]?.stringValue
    }

    public func lastfall(_ name: String?) -> SimLastfall? {
        guard let name else { return nil }
        return lastfaelle.first { $0.name == name }
    }

    /// Alle Namen (App zuerst, dann model.py ohne die ersetzten).
    public var alleNamen: [String] {
        lastfaelle.map(\.name) + modell.filter { !$0.ersetzt }.map(\.name)
    }

    public static func decode(_ header: Data) throws -> SimStand {
        SimStand(json: try JSONDecoder().decode(JSONValue.self, from: header))
    }
}

// MARK: - Kraft (Spiegel von kernel/src/kevcad_kernel/simulation/kraft.py)

public enum SimKraft {
    public static let g = 9.81
    public static let achsen: [(String, SIMD3<Float>)] = [
        ("+x", SIMD3(1, 0, 0)), ("-x", SIMD3(-1, 0, 0)), ("+y", SIMD3(0, 1, 0)), ("-y", SIMD3(0, -1, 0)),
        ("+z", SIMD3(0, 0, 1)), ("-z", SIMD3(0, 0, -1)),
    ]

    public static func achse(_ t: String) -> SIMD3<Float> {
        var s = t.lowercased().replacingOccurrences(of: "−", with: "-")
        if let c = s.first, c != "+" && c != "-" { s = "+" + s }
        return achsen.first { $0.0 == s }?.1 ?? SIMD3(0, 0, -1)
    }

    /// Richtung aus Azimut (Grad in der XY-Ebene ab +X) und Höhe (Grad über der XY-Ebene).
    public static func ausWinkeln(azimut: Double, hoehe: Double) -> SIMD3<Float> {
        let a = azimut * .pi / 180, h = hoehe * .pi / 180
        return SIMD3(Float(cos(h) * cos(a)), Float(cos(h) * sin(a)), Float(sin(h)))
    }

    public static func winkel(_ v: SIMD3<Float>) -> (azimut: Double, hoehe: Double) {
        let n = simd_normalize(v)
        let hoehe = asin(Double(max(-1, min(1, n.z)))) * 180 / .pi
        let az = hypot(Double(n.x), Double(n.y)) > 1e-9 ? atan2(Double(n.y), Double(n.x)) * 180 / .pi : 0
        return ((az * 1e6).rounded() / 1e6, (hoehe * 1e6).rounded() / 1e6)
    }

    /// Einheitsvektor der Kraft; nil, wenn „Normale“ ohne Normale.
    public static func richtung(_ r: SimRichtung, normale: SIMD3<Float>?) -> SIMD3<Float>? {
        var d: SIMD3<Float>
        switch r.art {
        case .normale:
            guard let n = normale, simd_length(n) > 1e-9 else { return nil }
            d = -simd_normalize(n)
        case .achse:
            d = achse(r.achse)
        case .frei:
            if let v = r.vektor, simd_length(v) > 1e-9 { d = simd_normalize(v) } else {
                d = ausWinkeln(azimut: r.azimut, hoehe: r.hoehe)
            }
        }
        return r.umkehren ? -d : d
    }

    /// Einheit des Drucks auf die ganze Fläche (N/mm², wie im Kernel "N/mm2").
    public static let druck = "N/mm2"

    /// Betrag in N; Druck (N/mm²) mal Flächeninhalt (mm²), ohne Fläche 0.
    public static func betragN(_ betrag: Double, einheit: String, flaecheMm2: Double? = nil) -> Double {
        switch einheit {
        case "kg": return betrag * g
        case druck: return betrag * max(flaecheMm2 ?? 0, 0)
        default: return betrag
        }
    }

    /// Kraft in N (Welt). Druck (N/mm²) nur senkrecht auf die Fläche (Richtung „Normale“) und mit Flächeninhalt.
    public static func kraft(_ r: SimRichtung, betrag: Double, einheit: String, normale: SIMD3<Float>?,
                             flaecheMm2: Double? = nil) -> SIMD3<Float>?
    {
        guard betrag > 0, let d = richtung(r, normale: normale) else { return nil }
        if einheit == druck {
            guard r.art == .normale, let a = flaecheMm2, a > 0 else { return nil }
        }
        return d * Float(betragN(betrag, einheit: einheit, flaecheMm2: flaecheMm2))
    }
}

enum SimJSON {
    static func vec(_ v: SIMD3<Float>) -> JSONValue {
        .array([.number(Double(v.x)), .number(Double(v.y)), .number(Double(v.z))])
    }

    static func achsText(_ v: SIMD3<Float>) -> String {
        let i = abs(v.x) >= abs(v.y) ? 0 : 1
        let c = i == 0 ? v.x : v.y
        return (c >= 0 ? "+" : "-") + (i == 0 ? "x" : "y")
    }
}

// MARK: - Operationen (SIM_EDIT, wie MCP simulation_aendern)

public enum SimOp {
    public static func lastfallNeu(_ name: String, dynamisch: Bool = false) -> JSONValue {
        var o: [String: JSONValue] = ["op": .string("lastfall_neu"), "name": .string(name),
                                      "art": .string(dynamisch ? "dynamisch" : "statisch")]
        if dynamisch { o["fahrt"] = SimFahrt().json }
        return .object(o)
    }

    public static func lastfallSetzen(_ l: SimLastfall) -> JSONValue {
        .object(["op": .string("lastfall_setzen"), "name": .string(l.name), "felder": l.felder])
    }

    public static func kopieren(von: String, name: String) -> JSONValue {
        .object(["op": .string("lastfall_kopieren"), "von": .string(von), "name": .string(name)])
    }

    public static func umbenennen(_ name: String, neu: String) -> JSONValue {
        .object(["op": .string("lastfall_umbenennen"), "name": .string(name), "neu": .string(neu)])
    }

    public static func loeschen(_ name: String) -> JSONValue {
        .object(["op": .string("lastfall_loeschen"), "name": .string(name)])
    }

    public static func lastSetzen(_ lastfall: String, _ last: SimLast) -> JSONValue {
        .object(["op": .string("last_setzen"), "lastfall": .string(lastfall), "last": last.json])
    }

    public static func lastLoeschen(_ lastfall: String, id: String) -> JSONValue {
        .object(["op": .string("last_loeschen"), "lastfall": .string(lastfall), "id": .string(id)])
    }

    public static func lagerSetzen(_ lager: SimLager) -> JSONValue {
        .object(["op": .string("lager_setzen"), "lager": lager.json])
    }

    public static func lagerLoeschen(_ id: String) -> JSONValue {
        .object(["op": .string("lager_loeschen"), "id": .string(id)])
    }

    public static func abgeleitet(_ id: String, aktiv: Bool) -> JSONValue {
        .object(["op": .string("abgeleitet"), "id": .string(id), "aktiv": .bool(aktiv)])
    }

    public static func topologie(_ teil: String, _ e: [String: JSONValue]) -> JSONValue {
        .object(["op": .string("topologie"), "teil": .string(teil), "einstellungen": .object(e)])
    }
}

// MARK: - Nachrichten der App

/// App → Kernel: Operationen auf simulation.json (Antwort ACK, danach STATICS und SIM).
public struct SimEditMessage: OutgoingRequest {
    public static let type = "SIM_EDIT"
    public var seq = 0
    public var id: String
    public var basis: Int?
    public var ops: [JSONValue]

    public init(id: String, basis: Int?, ops: [JSONValue]) {
        self.id = id
        self.basis = basis
        self.ops = ops
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, basis, ops }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(basis, forKey: .basis)
        try c.encode(ops, forKey: .ops)
    }
}

/// App → Kernel: Auftrag (Rechnen, Festigkeit, Ablauf, Grenze), Antwort ACK, Stand als SIM_JOB.
public struct SimRunMessage: OutgoingRequest {
    public static let type = "SIM_RUN"
    public var seq = 0
    public var id: String
    public var was: String
    public var lastfall: String?
    public var teil: String?
    public var fein: Bool
    public var grenze: String?
    /// Grenze suchen mit "s0s1" (Standard) oder "fem" (additiv); nil = wie bisher.
    public var verfahren: String?

    public init(id: String, was: String, lastfall: String? = nil, teil: String? = nil, fein: Bool = false,
                grenze: String? = nil, verfahren: String? = nil) {
        self.id = id
        self.was = was
        self.lastfall = lastfall
        self.teil = teil
        self.fein = fein
        self.grenze = grenze
        self.verfahren = verfahren
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, was, lastfall, teil, fein, grenze, verfahren }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(was, forKey: .was)
        try c.encodeIfPresent(lastfall, forKey: .lastfall)
        try c.encodeIfPresent(teil, forKey: .teil)
        try c.encode(fein, forKey: .fein)
        try c.encodeIfPresent(grenze, forKey: .grenze)
        try c.encodeIfPresent(verfahren, forKey: .verfahren)
    }
}

/// App → Kernel: laufenden Auftrag abbrechen.
public struct SimCancelMessage: OutgoingMessage {
    public static let type = "SIM_CANCEL"
    public var seq = 0

    public init() {}

    enum CodingKeys: String, CodingKey { case type, seq }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
    }
}

/// App → Kernel: SIM anfordern (Antwort SIM mit reply_to).
public struct SimReqMessage: OutgoingRequest {
    public static let type = "SIM_REQ"
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

/// TOPO_START mit den Erweiterungen des Bereichs Simulation (additiv): automatische Schutzzonen je Art und
/// Schutzflächen per Klick.
public struct TopologieStartErweitert: OutgoingMessage {
    public static let type = "TOPO_START"
    public var seq = 0
    public var basis: TopologieStartMessage
    public var bohrungen: Bool
    public var einsaetze: Bool
    public var kontakt: Bool
    public var bett: Bool
    public var steg: Double?
    public var schutz: [Int]

    public init(basis: TopologieStartMessage, bohrungen: Bool, einsaetze: Bool, kontakt: Bool, bett: Bool,
                steg: Double? = nil, schutz: [Int]) {
        self.basis = basis
        self.bohrungen = bohrungen
        self.einsaetze = einsaetze
        self.kontakt = kontakt
        self.bett = bett
        self.steg = steg
        self.schutz = schutz
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, teil, szenario, behalten, ueberhang, fein, lager, bohrungen, einsaetze, kontakt, bett, steg
        case schutz
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encodeIfPresent(basis.teil, forKey: .teil)
        try c.encodeIfPresent(basis.szenario, forKey: .szenario)
        try c.encode(basis.behalten, forKey: .behalten)
        try c.encode(basis.ueberhang, forKey: .ueberhang)
        try c.encode(basis.fein, forKey: .fein)
        try c.encodeIfPresent(basis.lager, forKey: .lager)
        try c.encode(bohrungen, forKey: .bohrungen)
        try c.encode(einsaetze, forKey: .einsaetze)
        try c.encode(kontakt, forKey: .kontakt)
        try c.encode(bett, forKey: .bett)
        try c.encodeIfPresent(steg, forKey: .steg)
        try c.encode(schutz.map { JSONValue.object(["art": .string("index"), "index": .number(Double($0))]) },
                     forKey: .schutz)
    }
}
