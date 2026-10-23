import Foundation
import simd

// Phase 7: Renderings (PROTOCOL.md „Phase 7: Renderings“). Kernel → App: RENDER_REQ (schnell rendern), RENDER_SCENE_REQ
// (Kamera, Lagen und Sichtbarkeit für Blender), RENDER_STATUS (Stand eines Auftrags). App → Kernel: RENDER_START (Dialog),
// RENDER_CANCEL, RENDER_RES, RENDER_SCENE. Gelesen wird tolerant wie bei allen Nachrichten.

/// Szene eines Renderings, wie der Kernel sie auflöst (render/szenen.py).
public struct RenderSzene: Equatable, Sendable {
    public var name: String
    public var titel: String
    /// "studio" (eigene Softbox-Umgebung) oder "umgebung" (HDRI aus `umgebung`)
    public var licht: String
    /// Absoluter Pfad einer Radiance-HDR oder nil
    public var umgebung: String?
    public var staerke: Double
    /// Drehung der Umgebung um Z in Grad
    public var drehung: Double
    /// "#RRGGBB", "umgebung" oder "transparent"
    public var hintergrund: String
    public var transparent: Bool
    public var boden: Bool

    public init(
        name: String = "studio", titel: String = "Studio", licht: String = "studio", umgebung: String? = nil,
        staerke: Double = 1, drehung: Double = 0, hintergrund: String = "#F1F2F4", transparent: Bool = false,
        boden: Bool = true
    ) {
        self.name = name
        self.titel = titel
        self.licht = licht
        self.umgebung = umgebung
        self.staerke = staerke
        self.drehung = drehung
        self.hintergrund = hintergrund
        self.transparent = transparent
        self.boden = boden
    }

    init(json j: JSONValue?) {
        let j = j ?? .null
        name = j["name"]?.lenientString ?? "studio"
        titel = j["titel"]?.lenientString ?? name
        licht = j["licht"]?.lenientString ?? "studio"
        umgebung = j["umgebung"]?.lenientString
        staerke = j["staerke"]?.doubleValue ?? 1
        drehung = j["drehung"]?.doubleValue ?? 0
        hintergrund = j["hintergrund"]?.lenientString ?? "#F1F2F4"
        transparent = j["transparent"]?.boolValue ?? (hintergrund == "transparent")
        boden = j["boden"]?.boolValue ?? true
    }

    /// Hintergrundfarbe (sRGB 0…1), falls der Hintergrund eine Farbe ist.
    public var hintergrundFarbe: SIMD3<Float>? { Self.hex(hintergrund) }

    public static func hex(_ text: String) -> SIMD3<Float>? {
        var t = text.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("#") { t.removeFirst() }
        guard t.count == 6, let v = UInt32(t, radix: 16) else { return nil }
        return SIMD3(Float((v >> 16) & 0xFF), Float((v >> 8) & 0xFF), Float(v & 0xFF)) / 255
    }
}

/// Darstellung eines Teils (render/materialien.py, KATALOG.md „Rendering“).
public struct RenderPBR: Equatable, Sendable {
    public var name: String
    /// sRGB 0…1
    public var basisfarbe: SIMD3<Float>
    public var metallisch: Float
    public var rauheit: Float
    public var oberflaeche: String
    public var klarlack: Float
    public var klarlackRauheit: Float
    public var anisotropie: Float
    public var durchsichtig: Float
    /// mm, nur bei `schichten`
    public var schichthoehe: Float
    public var material: String?
    /// Kulisse (Boden, Wand): im Bild, aber nicht für den Ausschnitt
    public var kulisse: Bool
    /// Aufbaurichtung des Druckteils (Modell, Einheitsvektor) aus der Druckprüfung; Schichtlinien liegen quer dazu.
    /// nil: quer zur Z-Achse des Modells
    public var druckOben: SIMD3<Float>?

    public init(
        name: String, basisfarbe: SIMD3<Float>, metallisch: Float = 0, rauheit: Float = 0.5,
        oberflaeche: String = "glatt", klarlack: Float = 0, klarlackRauheit: Float = 0.1, anisotropie: Float = 0,
        durchsichtig: Float = 0, schichthoehe: Float = 0.2, material: String? = nil, kulisse: Bool = false,
        druckOben: SIMD3<Float>? = nil
    ) {
        self.druckOben = druckOben
        self.name = name
        self.basisfarbe = basisfarbe
        self.metallisch = metallisch
        self.rauheit = rauheit
        self.oberflaeche = oberflaeche
        self.klarlack = klarlack
        self.klarlackRauheit = klarlackRauheit
        self.anisotropie = anisotropie
        self.durchsichtig = durchsichtig
        self.schichthoehe = schichthoehe
        self.material = material
        self.kulisse = kulisse
    }

    init(json j: JSONValue) {
        name = j["name"]?.lenientString ?? ""
        basisfarbe = j["basisfarbe"]?.vector3 ?? SIMD3(0.72, 0.75, 0.79)
        metallisch = Float(j["metallisch"]?.doubleValue ?? 0)
        rauheit = Float(j["rauheit"]?.doubleValue ?? 0.5)
        oberflaeche = j["oberflaeche"]?.lenientString ?? "glatt"
        klarlack = Float(j["klarlack"]?.doubleValue ?? 0)
        klarlackRauheit = Float(j["klarlack_rauheit"]?.doubleValue ?? 0.1)
        anisotropie = Float(j["anisotropie"]?.doubleValue ?? 0)
        durchsichtig = Float(j["durchsichtig"]?.doubleValue ?? 0)
        schichthoehe = Float(j["schichthoehe"]?.doubleValue ?? 0.2)
        material = j["material"]?.lenientString
        kulisse = j["kulisse"]?.boolValue ?? false
        druckOben = j["druck_oben"]?.vector3.flatMap { simd_length($0) > 1e-6 ? simd_normalize($0) : nil }
    }
}

/// RENDER_REQ: die App rendert schnell (RealityKit) und schreibt das PNG nach `path`.
public struct RenderAuftrag: Equatable, Sendable {
    public var id: String
    public var auftrag: String
    public var szene: RenderSzene
    /// "aktuell", "produkt" oder eine Standardansicht
    public var ansicht: String
    /// "Kamera/<name>" oder nil
    public var kamera: String?
    public var width: Int
    public var height: Int
    public var teile: [RenderPBR]
    public var path: String
    public var vorschau: Bool
    /// Wann die App die Anfrage gelesen hat (Wartezeit bis zum Start, nur für die Phasen)
    public var empfangen = Date()

    public init(
        id: String, auftrag: String, szene: RenderSzene, ansicht: String = "aktuell", kamera: String? = nil,
        width: Int, height: Int, teile: [RenderPBR] = [], path: String, vorschau: Bool = false
    ) {
        self.id = id
        self.auftrag = auftrag
        self.szene = szene
        self.ansicht = ansicht
        self.kamera = kamera
        self.width = width
        self.height = height
        self.teile = teile
        self.path = path
        self.vorschau = vorschau
    }

    init(json j: JSONValue) {
        id = j["id"]?.lenientString ?? ""
        auftrag = j["auftrag"]?.lenientString ?? ""
        szene = RenderSzene(json: j["szene"])
        ansicht = j["ansicht"]?.lenientString ?? "aktuell"
        kamera = j["kamera"]?.lenientString
        width = max(16, min(j["width"]?.intValue ?? 1920, 8192))
        height = max(16, min(j["height"]?.intValue ?? 1080, 8192))
        teile = (j["teile"]?.arrayValue ?? []).map(RenderPBR.init(json:))
        path = j["path"]?.lenientString ?? ""
        vorschau = j["vorschau"]?.boolValue ?? false
    }
}

/// RENDER_SCENE_REQ: Kamera, Lagen und Sichtbarkeit für einen Foto-Lauf (Blender im Kernel).
public struct RenderSzeneAnfrage: Equatable, Sendable {
    public var id: String
    public var auftrag: String
    public var ansicht: String
    public var kamera: String?
    public var width: Int
    public var height: Int
    /// Kulisse-Teile (zählen nicht für den Ausschnitt)
    public var kulisse: [String]

    init(json j: JSONValue) {
        id = j["id"]?.lenientString ?? ""
        auftrag = j["auftrag"]?.lenientString ?? ""
        ansicht = j["ansicht"]?.lenientString ?? "aktuell"
        kamera = j["kamera"]?.lenientString
        width = max(16, min(j["width"]?.intValue ?? 1920, 8192))
        height = max(16, min(j["height"]?.intValue ?? 1080, 8192))
        kulisse = j["kulisse"]?.stringList ?? []
    }
}

public enum RenderZustand: String, Equatable, Sendable {
    case wartet, laeuft, fertig, fehler, abgebrochen

    public var titel: String {
        switch self {
        case .wartet: return "wartet"
        case .laeuft: return "läuft"
        case .fertig: return "fertig"
        case .fehler: return "Fehler"
        case .abgebrochen: return "abgebrochen"
        }
    }

    public var istEnde: Bool { self == .fertig || self == .fehler || self == .abgebrochen }
}

/// RENDER_STATUS: Stand eines Auftrags (bei jedem Wechsel, im Lauf höchstens alle 0,4 s).
public struct RenderStatus: Equatable, Sendable {
    public var auftrag: String
    public var zustand: RenderZustand
    public var qualitaet: String
    public var szene: String
    public var fortschritt: Double
    public var text: String
    public var pfad: String?
    public var width: Int
    public var height: Int
    public var ms: Int?
    /// "agent" oder "app"
    public var von: String
    public var vorschau: Bool
    public var fehler: String?

    public init(
        auftrag: String, zustand: RenderZustand, qualitaet: String = "schnell", szene: String = "studio",
        fortschritt: Double = 0, text: String = "", pfad: String? = nil, width: Int = 0, height: Int = 0,
        ms: Int? = nil, von: String = "app", vorschau: Bool = false, fehler: String? = nil
    ) {
        self.auftrag = auftrag
        self.zustand = zustand
        self.qualitaet = qualitaet
        self.szene = szene
        self.fortschritt = fortschritt
        self.text = text
        self.pfad = pfad
        self.width = width
        self.height = height
        self.ms = ms
        self.von = von
        self.vorschau = vorschau
        self.fehler = fehler
    }

    init(json j: JSONValue) {
        auftrag = j["auftrag"]?.lenientString ?? ""
        zustand = RenderZustand(rawValue: j["zustand"]?.lenientString ?? "") ?? .laeuft
        qualitaet = j["qualitaet"]?.lenientString ?? "schnell"
        szene = j["szene"]?.lenientString ?? "studio"
        fortschritt = max(0, min(1, j["fortschritt"]?.doubleValue ?? 0))
        text = j["text"]?.lenientString ?? ""
        pfad = j["pfad"]?.lenientString
        width = j["width"]?.intValue ?? 0
        height = j["height"]?.intValue ?? 0
        ms = j["ms"]?.intValue
        von = j["von"]?.lenientString ?? "agent"
        vorschau = j["vorschau"]?.boolValue ?? false
        fehler = j["fehler"]?.lenientString
    }
}

/// Nachrichten Kernel → App.
public enum RenderNachricht: Sendable {
    case auftrag(RenderAuftrag)
    case szeneAnfrage(RenderSzeneAnfrage)
    case status(RenderStatus)

    public static let types: Set<String> = ["RENDER_REQ", "RENDER_SCENE_REQ", "RENDER_STATUS"]

    public var typeName: String {
        switch self {
        case .auftrag: return "RENDER_REQ"
        case .szeneAnfrage: return "RENDER_SCENE_REQ"
        case .status: return "RENDER_STATUS"
        }
    }

    public static func decode(type: String, header: Data) throws -> RenderNachricht {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        switch type {
        case "RENDER_REQ": return .auftrag(RenderAuftrag(json: j))
        case "RENDER_SCENE_REQ": return .szeneAnfrage(RenderSzeneAnfrage(json: j))
        default: return .status(RenderStatus(json: j))
        }
    }
}

// MARK: - App → Kernel

/// RENDER_START: Kevin startet im Dialog „Rendern …“ (der Kernel antwortet mit ACK, `message` = Auftrag „R-n“).
public struct RenderStartMessage: OutgoingRequest {
    public static let type = "RENDER_START"
    public var seq = 0
    public var id: String
    public var szene: String
    public var ansicht: String
    public var kamera: String?
    public var breite: Int
    public var hoehe: Int
    public var qualitaet: String
    public var hintergrund: String?
    public var ziel: String?
    public var vorschau: Bool

    public init(
        id: String, szene: String, ansicht: String = "aktuell", kamera: String? = nil, breite: Int, hoehe: Int,
        qualitaet: String = "schnell", hintergrund: String? = nil, ziel: String? = nil, vorschau: Bool = false
    ) {
        self.id = id
        self.szene = szene
        self.ansicht = ansicht
        self.kamera = kamera
        self.breite = breite
        self.hoehe = hoehe
        self.qualitaet = qualitaet
        self.hintergrund = hintergrund
        self.ziel = ziel
        self.vorschau = vorschau
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, id, szene, ansicht, kamera, breite, hoehe, qualitaet, hintergrund, ziel, vorschau
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(szene, forKey: .szene)
        try c.encode(ansicht, forKey: .ansicht)
        try c.encode(kamera, forKey: .kamera)
        try c.encode(breite, forKey: .breite)
        try c.encode(hoehe, forKey: .hoehe)
        try c.encode(qualitaet, forKey: .qualitaet)
        try c.encode(hintergrund, forKey: .hintergrund)
        try c.encode(ziel, forKey: .ziel)
        try c.encode(vorschau, forKey: .vorschau)
    }
}

/// RENDER_CANCEL: Auftrag abbrechen (Antwort ACK).
public struct RenderCancelMessage: OutgoingRequest {
    public static let type = "RENDER_CANCEL"
    public var seq = 0
    public var id: String
    public var auftrag: String

    public init(id: String, auftrag: String) {
        self.id = id
        self.auftrag = auftrag
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, auftrag }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(auftrag, forKey: .auftrag)
    }
}

/// RENDER_RES: Antwort auf RENDER_REQ.
public struct RenderResponseMessage: OutgoingMessage {
    public static let type = "RENDER_RES"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var path: String?
    public var width: Int
    public var height: Int
    public var ms: Int
    public var kamera: JSONValue
    public var message: String?
    public var phasen: [String: Int]

    public init(
        replyTo: String, ok: Bool, path: String?, width: Int, height: Int, ms: Int, kamera: JSONValue = .null,
        message: String? = nil, phasen: [String: Int] = [:]
    ) {
        self.replyTo = replyTo
        self.ok = ok
        self.path = path
        self.width = width
        self.height = height
        self.ms = ms
        self.kamera = kamera
        self.message = message
        self.phasen = phasen
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, path, width, height, ms, kamera, message, phasen
        case replyTo = "reply_to"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(path, forKey: .path)
        try c.encode(width, forKey: .width)
        try c.encode(height, forKey: .height)
        try c.encode(ms, forKey: .ms)
        try c.encode(kamera, forKey: .kamera)
        try c.encode(message, forKey: .message)
        try c.encode(phasen, forKey: .phasen)
    }
}

/// RENDER_SCENE: Antwort auf RENDER_SCENE_REQ (Kamera und sichtbare Teile mit Lage).
public struct RenderSceneMessage: OutgoingMessage {
    public static let type = "RENDER_SCENE"
    public var seq = 0
    public var replyTo: String
    public var ok: Bool
    public var kamera: JSONValue
    /// je Teil der Name und die Lage (16 Zahlen spaltenweise) oder nil (Ruhelage)
    public var teile: [(name: String, matrix: [Float]?)]
    public var message: String?

    public init(
        replyTo: String, ok: Bool, kamera: JSONValue = .null, teile: [(name: String, matrix: [Float]?)] = [],
        message: String? = nil
    ) {
        self.replyTo = replyTo
        self.ok = ok
        self.kamera = kamera
        self.teile = teile
        self.message = message
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, ok, kamera, teile, message
        case replyTo = "reply_to"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(replyTo, forKey: .replyTo)
        try c.encode(ok, forKey: .ok)
        try c.encode(kamera, forKey: .kamera)
        let liste: [JSONValue] = teile.map { t in
            .object([
                "name": .string(t.name),
                "matrix": t.matrix.map { m in .array(m.map { .number(Double($0)) }) } ?? .null,
            ])
        }
        try c.encode(liste, forKey: .teile)
        try c.encode(message, forKey: .message)
    }
}

// MARK: - Zustand für die Oberfläche

/// Was der Dialog „Rendern …“ zeigt: eingestellte Werte, laufende Aufträge, letztes Ergebnis, Vorschau.
@MainActor
public final class RenderStore: ObservableObject {
    /// Szenen, Größen und Qualitäten für den Dialog (wie render/szenen.py)
    public static let szenen: [(id: String, titel: String)] = [
        ("studio", "Studio"), ("werkstatt", "Werkstatt"), ("draussen", "Draußen"), ("wohnraum", "Wohnraum"),
        ("freigestellt", "Freigestellt"),
    ]
    public static let groessen: [(id: String, titel: String, breite: Int, hoehe: Int)] = [
        ("hd", "Full HD", 1920, 1080), ("4k", "4K UHD", 3840, 2160), ("quadrat", "Quadrat", 2048, 2048),
        ("hochkant", "Instagram hochkant", 1080, 1350), ("story", "Story", 1080, 1920),
        ("deckblatt", "Deckblatt 3:2", 2400, 1600), ("a4", "A4 quer, 300 dpi", 3508, 2480),
    ]
    public static let hintergruende: [(id: String?, titel: String)] = [
        (nil, "wie die Szene"), ("weiss", "Weiß"), ("hell", "Hellgrau"), ("grau", "Grau"), ("dunkel", "Dunkel"),
        ("transparent", "Transparent"),
    ]
    public static let ansichten: [(id: String, titel: String)] = [
        ("aktuell", "Aktuelle Ansicht"), ("produkt", "Produktansicht"), ("iso", "Isometrisch vorn rechts"),
        ("iso_front_left", "Isometrisch vorn links"), ("front", "Vorne"), ("right", "Rechts"), ("top", "Oben"),
    ]

    @Published public var szene = "studio"
    @Published public var groesse = "hd"
    @Published public var qualitaet = "schnell"
    @Published public var hintergrund: String? = nil
    @Published public var ansicht = "produkt"
    @Published public var kamera: String? = nil
    /// Laufende und fertige Aufträge (neueste zuerst)
    @Published public private(set) var auftraege: [RenderStatus] = []
    /// Zuletzt fertiges Bild (nicht Vorschau)
    @Published public private(set) var letztesBild: URL?
    /// Vorschau im Dialog
    @Published public private(set) var vorschauBild: URL?
    @Published public private(set) var vorschauLaeuft = false
    /// Stand des letzten Vorschau-Auftrags (auch für das Produktbild im Export)
    @Published public private(set) var letzteVorschau: RenderStatus?
    @Published public var meldung: String?
    /// Zähler, damit die Ansicht ein neu geschriebenes Vorschaubild auch unter gleichem Pfad neu lädt
    @Published public private(set) var vorschauStand = 0

    public init() {}

    public var groesseWerte: (breite: Int, hoehe: Int) {
        let g = Self.groessen.first { $0.id == groesse } ?? Self.groessen[0]
        return (g.breite, g.hoehe)
    }

    public func status(_ s: RenderStatus) {
        if s.vorschau {
            letzteVorschau = s
            vorschauLaeuft = !s.zustand.istEnde
            if s.zustand == .fertig, let p = s.pfad {
                vorschauBild = URL(fileURLWithPath: p)
                vorschauStand += 1
            }
            if s.zustand == .fehler { meldung = s.fehler ?? s.text }
            return
        }
        if let i = auftraege.firstIndex(where: { $0.auftrag == s.auftrag }) {
            auftraege[i] = s
        } else {
            auftraege.insert(s, at: 0)
            if auftraege.count > 20 { auftraege.removeLast(auftraege.count - 20) }
        }
        if s.zustand == .fertig, let p = s.pfad { letztesBild = URL(fileURLWithPath: p) }
    }

    public func vorschauGestartet() { vorschauLaeuft = true }
    public func vorschauFehlgeschlagen(_ text: String) {
        vorschauLaeuft = false
        meldung = text
    }

    public var laufende: [RenderStatus] { auftraege.filter { !$0.zustand.istEnde } }
}
