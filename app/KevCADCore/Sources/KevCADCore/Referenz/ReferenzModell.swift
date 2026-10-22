import CoreGraphics
import Foundation
import simd

// Phase 4: Foto und Video als Referenz (PROTOCOL.md „Phase 4: Referenzen“). Referenzen stehen in
// `AppModel.referenzen` (ReferenzStore), werden vom App-Kern gepflegt und über `ReferenzActions` bedient (die Oberfläche
// ruft `model.actions as? ReferenzActions`).

/// Eine Referenz aus REF_LIST.
public struct ReferenzInfo: Identifiable, Equatable, Sendable {
    public enum Zustand: String, Sendable { case leer, rechnet, fertig, fehler }

    public var name: String
    /// "video" oder "fotos"
    public var art: String
    public var quelle: String
    public var zustand: Zustand
    /// "capture" oder "messung", solange etwas läuft
    public var laeuft: String?
    public var fortschritt: Double?
    public var text: String?
    public var meldung: String?
    public var netz: Bool
    public var fotos: Int
    public var messung: Bool
    public var erstellt: String?
    /// Object Capture: Hüllmaß mit Anbauten und Grundkörper (dichteste waagrechte Schicht), getrennt angezeigt.
    public var captureHuelle: SIMD3<Double>?
    public var captureGrundkoerper: SIMD2<Double>?
    public var captureDauer: Double?
    public var captureBilder: (gesamt: Int, ausgerichtet: Int)?
    /// Netz an das Modell angelegt (Drehung um Z in Grad), sonst nil.
    public var lageDrehung: Double?
    public var lageRest: Double?

    public var id: String { name }
    public var istVideo: Bool { art == "video" }

    public static func == (a: ReferenzInfo, b: ReferenzInfo) -> Bool {
        a.name == b.name && a.art == b.art && a.quelle == b.quelle && a.zustand == b.zustand && a.laeuft == b.laeuft
            && a.fortschritt == b.fortschritt && a.text == b.text && a.meldung == b.meldung && a.netz == b.netz
            && a.fotos == b.fotos && a.messung == b.messung && a.captureHuelle == b.captureHuelle
            && a.captureGrundkoerper == b.captureGrundkoerper && a.lageDrehung == b.lageDrehung
            && a.captureBilder?.gesamt == b.captureBilder?.gesamt
            && a.captureBilder?.ausgerichtet == b.captureBilder?.ausgerichtet
    }

    public init?(json: JSONValue) {
        guard let name = json["name"]?.stringValue, !name.isEmpty else { return nil }
        self.name = name
        art = json["art"]?.stringValue ?? "video"
        quelle = json["quelle"]?.stringValue ?? ""
        zustand = Zustand(rawValue: json["zustand"]?.stringValue ?? "") ?? .leer
        laeuft = json["laeuft"]?.stringValue
        fortschritt = json["fortschritt"]?.doubleValue
        text = json["text"]?.stringValue
        meldung = json["meldung"]?.stringValue
        netz = json["netz"]?.boolValue ?? false
        fotos = json["fotos"]?.intValue ?? 0
        messung = json["messung"]?.boolValue ?? false
        erstellt = json["erstellt"]?.stringValue
        let cap = json["capture"]
        if let h = cap?["huelle"], let l = h["laenge"]?.doubleValue, let b = h["breite"]?.doubleValue,
           let ho = h["hoehe"]?.doubleValue {
            captureHuelle = SIMD3(l, b, ho)
        }
        if let g = cap?["grundkoerper"], let l = g["laenge"]?.doubleValue, let b = g["breite"]?.doubleValue {
            captureGrundkoerper = SIMD2(l, b)
        }
        captureDauer = cap?["dauer_s"]?.doubleValue
        if let n = cap?["bilder"]?.intValue {
            captureBilder = (n, cap?["ausgerichtet"]?.intValue ?? n)
        }
        lageDrehung = json["lage"]?["drehung_z"]?.doubleValue
        lageRest = json["lage"]?["rest_mm"]?.doubleValue
    }
}

/// Eingepasste Kamera eines Fotos (OpenCV-Konvention: x rechts, y unten, z Blick; Pixel = f·x/z + c).
public struct ReferenzKamera: Equatable, Sendable {
    /// Welt → Kamera, zeilenweise
    public var R: [SIMD3<Double>]
    public var t: SIMD3<Double>
    public var f: Double
    public var cx: Double
    public var cy: Double
    public var breite: Int
    public var hoehe: Int

    public init(R: [SIMD3<Double>], t: SIMD3<Double>, f: Double, cx: Double, cy: Double, breite: Int, hoehe: Int) {
        self.R = R
        self.t = t
        self.f = f
        self.cx = cx
        self.cy = cy
        self.breite = breite
        self.hoehe = hoehe
    }

    public init?(json: JSONValue?) {
        guard let json, let rows = json["R"]?.arrayValue, rows.count == 3,
              let t = json["t"]?.doubles, t.count == 3, let f = json["f"]?.doubleValue, f > 0,
              let w = json["w"]?.intValue, let h = json["h"]?.intValue, w > 0, h > 0
        else { return nil }
        var r: [SIMD3<Double>] = []
        for row in rows {
            guard let d = row.doubles, d.count == 3 else { return nil }
            r.append(SIMD3(d[0], d[1], d[2]))
        }
        R = r
        self.t = SIMD3(t[0], t[1], t[2])
        self.f = f
        cx = json["cx"]?.doubleValue ?? Double(w) / 2
        cy = json["cy"]?.doubleValue ?? Double(h) / 2
        breite = w
        hoehe = h
    }

    /// Projektionszentrum in Weltkoordinaten (mm): −Rᵀ t.
    public var zentrum: SIMD3<Double> { -(R[0] * t.x + R[1] * t.y + R[2] * t.z) }
    /// Blickrichtung (Welt): dritte Zeile von R.
    public var blick: SIMD3<Double> { simd_normalize(R[2]) }
    /// Oben im Bild (Welt): minus zweite Zeile von R.
    public var oben: SIMD3<Double> { -simd_normalize(R[1]) }

    /// Bildpunkt (Pixel, Ursprung links oben) und Tiefe eines Weltpunkts.
    public func projiziere(_ p: SIMD3<Double>) -> (SIMD2<Double>, Double) {
        let x = SIMD3(simd_dot(R[0], p), simd_dot(R[1], p), simd_dot(R[2], p)) + t
        let z = max(x.z, 1e-9)
        return (SIMD2(f * x.x / z + cx, f * x.y / z + cy), x.z)
    }
}

/// Ein Foto mit eingepasster Kamera (REF_PHOTOS.fotos[i]).
public struct ReferenzFoto: Identifiable, Equatable, Sendable {
    public var name: String
    public var bild: URL
    public var maske: URL?
    public var kontrolle: URL?
    public var zeit: Double?
    public var iou: Double?
    public var kamera: ReferenzKamera

    public var id: String { name }

    public init?(json: JSONValue) {
        guard let name = json["name"]?.stringValue, let bild = json["bild"]?.stringValue,
              let kamera = ReferenzKamera(json: json["kamera"])
        else { return nil }
        self.name = name
        self.bild = URL(fileURLWithPath: bild)
        maske = json["maske"]?.stringValue.map { URL(fileURLWithPath: $0) }
        kontrolle = json["kontrolle"]?.stringValue.map { URL(fileURLWithPath: $0) }
        zeit = json["zeit"]?.doubleValue
        iou = json["iou"]?.doubleValue
        self.kamera = kamera
    }

    /// Kurzer Titel: „14,8 s“ bei Videobildern, sonst der Dateiname.
    public var titel: String {
        if let zeit { return KevFormat.number(zeit, digits: 1) + " s" }
        return name
    }
}

/// Ein gemessenes Maß (REF_RESULT.masse[i]).
public struct ReferenzMass: Identifiable, Equatable, Sendable {
    public var name: String
    public var wert: Double
    public var sigma: Double
    public var start: Double?
    public var id: String { name }

    public var aenderung: Double? { start.map { wert - $0 } }
    /// Auf 0,1 mm gerundet, so wie „Maße übernehmen“ es in model.py schreibt.
    public var gerundet: Double { (wert * 10).rounded() / 10 }
}

public struct ReferenzEmpfehlung: Identifiable, Equatable, Sendable {
    public var art: String
    public var text: String
    public var id: String { art + text }
}

/// Messergebnis (REF_RESULT).
public struct ReferenzErgebnis: Equatable, Sendable {
    public var referenz: String
    public var stand: String?
    public var masse: [ReferenzMass]
    public var bekannt: [String: Double]
    public var huelle: SIMD3<Double>?
    public var grundkoerperTeil: String?
    public var grundkoerper: SIMD3<Double>?
    public var bilder: Int
    public var verworfen: [String]
    public var ueberdeckung: Double?
    public var empfehlungen: [ReferenzEmpfehlung]
    public var dauer: Double?

    public init?(json: JSONValue) {
        guard let ref = json["referenz"]?.stringValue else { return nil }
        referenz = ref
        stand = json["stand"]?.stringValue
        masse = (json["masse"]?.arrayValue ?? []).compactMap { m in
            guard let name = m["name"]?.stringValue, let w = m["wert"]?.doubleValue else { return nil }
            return ReferenzMass(name: name, wert: w, sigma: m["sigma"]?.doubleValue ?? 0, start: m["start"]?.doubleValue)
        }
        var b: [String: Double] = [:]
        for (k, v) in json["bekannt"]?.objectValue ?? [:] { if let d = v.doubleValue { b[k] = d } }
        bekannt = b
        func groesse(_ v: JSONValue?) -> SIMD3<Double>? {
            guard let g = v?["groesse"]?.doubles, g.count == 3 else { return nil }
            return SIMD3(g[0], g[1], g[2])
        }
        huelle = groesse(json["huelle"])
        grundkoerper = groesse(json["grundkoerper"])
        grundkoerperTeil = json["grundkoerper"]?["teil"]?.stringValue
        bilder = json["bilder"]?.intValue ?? 0
        verworfen = json["verworfen"]?.stringList ?? []
        ueberdeckung = json["ueberdeckung"]?.doubleValue
        empfehlungen = (json["empfehlungen"]?.arrayValue ?? []).compactMap { e in
            guard let t = e["text"]?.stringValue else { return nil }
            return ReferenzEmpfehlung(art: e["art"]?.stringValue ?? "", text: t)
        }
        dauer = json["dauer_s"]?.doubleValue
    }

    public func mass(_ name: String) -> ReferenzMass? { masse.first { $0.name == name } }
}

/// Referenznetz (REF_UPSERT) in Weltkoordinaten des Modells.
public struct ReferenzNetz: Equatable, Sendable {
    public var name: String
    /// sRGB, mit Deckkraft
    public var farbe: SIMD4<Float>
    public var positions: [Float]
    public var normals: [Float]
    public var triangles: [UInt32]
    public var bboxMin: SIMD3<Float>
    public var bboxMax: SIMD3<Float>

    public var vertexCount: Int { positions.count / 3 }
    public var triangleCount: Int { triangles.count / 3 }
}

/// Nachrichten der Referenzen (Kernel → App).
public enum ReferenzNachricht: Sendable {
    case liste([ReferenzInfo])
    case netz(ReferenzNetz)
    case entfernen(String)
    case fotos(referenz: String, satz: String, fotos: [ReferenzFoto])
    case ergebnis(ReferenzErgebnis)

    public static let types: Set<String> = ["REF_LIST", "REF_UPSERT", "REF_REMOVE", "REF_PHOTOS", "REF_RESULT"]

    public var typeName: String {
        switch self {
        case .liste: return "REF_LIST"
        case .netz: return "REF_UPSERT"
        case .entfernen: return "REF_REMOVE"
        case .fotos: return "REF_PHOTOS"
        case .ergebnis: return "REF_RESULT"
        }
    }

    struct Fehler: Error, CustomStringConvertible {
        var description: String
    }

    public static func decode(type: String, frame: Frame) throws -> ReferenzNachricht {
        let json = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        switch type {
        case "REF_LIST":
            return .liste((json["referenzen"]?.arrayValue ?? []).compactMap(ReferenzInfo.init(json:)))
        case "REF_REMOVE":
            guard let n = json["name"]?.stringValue else { throw Fehler(description: "REF_REMOVE ohne name") }
            return .entfernen(n)
        case "REF_PHOTOS":
            guard let r = json["referenz"]?.stringValue else { throw Fehler(description: "REF_PHOTOS ohne referenz") }
            return .fotos(referenz: r, satz: json["satz"]?.stringValue ?? "messung",
                          fotos: (json["fotos"]?.arrayValue ?? []).compactMap(ReferenzFoto.init(json:)))
        case "REF_RESULT":
            guard let e = ReferenzErgebnis(json: json) else { throw Fehler(description: "REF_RESULT ohne referenz") }
            return .ergebnis(e)
        case "REF_UPSERT":
            guard let name = json["name"]?.stringValue, let nv = json["counts"]?["vert"]?.intValue,
                  let nt = json["counts"]?["tri"]?.intValue, nv >= 0, nt >= 0
            else { throw Fehler(description: "REF_UPSERT ohne name oder counts") }
            let p = frame.payload
            let erwartet = nv * 12 * 2 + nt * 12
            guard p.count == erwartet else {
                throw Fehler(description: "REF_UPSERT: Nutzlast \(p.count) Byte, erwartet \(erwartet)")
            }
            func floats(_ start: Int, _ n: Int) -> [Float] {
                var out = [Float](repeating: 0, count: n)
                out.withUnsafeMutableBytes { dst in
                    p.withUnsafeBytes { src in
                        dst.copyMemory(from: UnsafeRawBufferPointer(rebasing: src[start..<(start + n * 4)]))
                    }
                }
                return out.map { Float(bitPattern: $0.bitPattern.littleEndian) }
            }
            let pos = floats(0, nv * 3)
            let nrm = floats(nv * 12, nv * 3)
            var tri = [UInt32](repeating: 0, count: nt * 3)
            tri.withUnsafeMutableBytes { dst in
                p.withUnsafeBytes { src in
                    dst.copyMemory(from: UnsafeRawBufferPointer(rebasing: src[(nv * 24)..<(nv * 24 + nt * 12)]))
                }
            }
            tri = tri.map { UInt32(littleEndian: $0) }
            if let m = tri.max(), Int(m) >= nv { throw Fehler(description: "REF_UPSERT: Dreieck verweist ins Leere") }
            let lo = json["bbox"]?["min"]?.vector3 ?? .zero
            let hi = json["bbox"]?["max"]?.vector3 ?? .zero
            let farbe = json["farbe"]?.vector4 ?? SIMD4(0.36, 0.62, 0.86, 0.45)
            return .netz(ReferenzNetz(name: name, farbe: farbe, positions: pos, normals: nrm, triangles: tri,
                                      bboxMin: lo, bboxMax: hi))
        default:
            throw Fehler(description: "Unbekannte Referenznachricht \(type)")
        }
    }
}

// MARK: - App → Kernel

/// REF_ADD: Video oder Fotos als Referenz hinzufügen (Drag and Drop, Dialog).
public struct ReferenzHinzufuegenMessage: OutgoingRequest {
    public static let type = "REF_ADD"
    public var seq = 0
    public var id: String
    public var pfade: [String]
    public var name: String?
    public var masz: [String: Double]?
    public var auflage: Bool
    public var von: Double?
    public var bis: Double?
    public var einstellung: String

    public init(id: String, pfade: [String], name: String? = nil, masz: [String: Double]? = nil, auflage: Bool = false,
                von: Double? = nil, bis: Double? = nil, einstellung: String = "schnell") {
        self.id = id
        self.pfade = pfade
        self.name = name
        self.masz = masz
        self.auflage = auflage
        self.von = von
        self.bis = bis
        self.einstellung = einstellung
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, pfade, name, masz, auflage, von, bis, einstellung }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(pfade, forKey: .pfade)
        try c.encode(name, forKey: .name)
        try c.encode(masz, forKey: .masz)
        try c.encode(auflage, forKey: .auflage)
        try c.encode(von, forKey: .von)
        try c.encode(bis, forKey: .bis)
        try c.encode(einstellung, forKey: .einstellung)
    }
}

/// REF_MEASURE_REQ: Referenz vermessen (Knopf „Vermessen“).
public struct ReferenzVermessenMessage: OutgoingRequest {
    public static let type = "REF_MEASURE_REQ"
    public var seq = 0
    public var id: String
    public var referenz: String
    /// nil = Angaben aus messmodell() in model.py
    public var frei: [String]?
    public var bekannt: [String: Double]
    public var bilder: Int

    public init(id: String, referenz: String, frei: [String]?, bekannt: [String: Double], bilder: Int) {
        self.id = id
        self.referenz = referenz
        self.frei = frei
        self.bekannt = bekannt
        self.bilder = bilder
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, referenz, frei, bekannt, bilder }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(referenz, forKey: .referenz)
        try c.encode(frei, forKey: .frei)
        try c.encode(bekannt, forKey: .bekannt)
        try c.encode(bilder, forKey: .bilder)
    }
}

/// REF_APPLY: Kevins Klick „Maße übernehmen“.
public struct ReferenzUebernehmenMessage: OutgoingRequest {
    public static let type = "REF_APPLY"
    public var seq = 0
    public var id: String
    public var referenz: String
    public var werte: [String: Double]

    public init(id: String, referenz: String, werte: [String: Double]) {
        self.id = id
        self.referenz = referenz
        self.werte = werte
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, referenz, werte }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(referenz, forKey: .referenz)
        try c.encode(werte, forKey: .werte)
    }
}

// MARK: - Zustand für die Oberfläche

/// Blick durch die eingepasste Kamera eines Fotos.
public struct FotoAnsicht: Equatable, Sendable {
    public enum Modus: String, CaseIterable, Sendable { case ueberlagern, differenz }

    public var referenz: String
    public var satz: String
    public var index: Int
    /// Deckkraft des Modells über dem Foto (0 = nur Foto, 1 = Modell deckend)
    public var deckkraft: Double
    public var modus: Modus

    public init(referenz: String, satz: String, index: Int, deckkraft: Double = 0.55, modus: Modus = .ueberlagern) {
        self.referenz = referenz
        self.satz = satz
        self.index = index
        self.deckkraft = deckkraft
        self.modus = modus
    }
}

/// Referenzen des Projekts. Gehört zu AppModel (`model.referenzen`); geändert nur vom App-Kern.
@MainActor
public final class ReferenzStore: ObservableObject {
    @Published public internal(set) var referenzen: [ReferenzInfo] = []
    /// Fotos je Referenz und Satz („messung“: fotomess mit Maske, „capture“: Object Capture)
    @Published public internal(set) var fotos: [String: [String: [ReferenzFoto]]] = [:]
    @Published public internal(set) var ergebnisse: [String: ReferenzErgebnis] = [:]
    /// Referenzen mit Netz in der Szene
    @Published public internal(set) var netze: [String: ReferenzNetz] = [:]
    @Published public internal(set) var verborgen: Set<String> = []
    @Published public internal(set) var deckkraft: [String: Double] = [:]
    @Published public internal(set) var fotoansicht: FotoAnsicht?
    /// Fertiges Bild der Fotoansicht (Foto mit Modell bzw. Differenz) und die Überdeckung von Modell und Maske.
    @Published public internal(set) var fotoBild: CGImage?
    @Published public internal(set) var fotoUeberdeckung: Double?
    @Published public internal(set) var fotoMeldung: String?
    /// Alle param()-Werte des letzten Laufs (RUN_END), für „Vermessen“.
    @Published public internal(set) var params: [String: Double] = [:]
    /// Letzte Antwort des Kernels (Übernehmen, Hinzufügen), für einen kurzen Hinweis.
    @Published public internal(set) var meldung: String?

    public static let standardDeckkraft = 0.45

    public init() {}

    public func referenz(_ name: String) -> ReferenzInfo? { referenzen.first { $0.name == name } }

    public func fotos(_ name: String) -> [ReferenzFoto] {
        let s = fotos[name] ?? [:]
        return (s["messung"] ?? []) + (s["capture"] ?? [])
    }

    public func fotoSatz(_ name: String, _ satz: String) -> [ReferenzFoto] { fotos[name]?[satz] ?? [] }

    public func deckkraft(_ name: String) -> Double { deckkraft[name] ?? Self.standardDeckkraft }

    public var aktuellesFoto: ReferenzFoto? {
        guard let a = fotoansicht else { return nil }
        let liste = fotoSatz(a.referenz, a.satz)
        return liste.indices.contains(a.index) ? liste[a.index] : nil
    }

    public var laeuftEtwas: Bool { referenzen.contains { $0.zustand == .rechnet } }
}

/// Aktionen rund um Referenzen, implementiert vom App-Kern (AppController).
@MainActor
public protocol ReferenzActions: AnyObject {
    /// Video oder Fotos hinzufügen (REF_ADD); `masz` z. B. ["laenge": 180].
    func referenzHinzufuegen(
        _ urls: [URL], name: String?, masz: [String: Double]?, auflage: Bool, von: Double?, bis: Double?,
        einstellung: String)
    /// Vermessen (REF_MEASURE_REQ); `frei` nil = Angaben aus messmodell().
    func referenzVermessen(_ name: String, frei: [String]?, bekannt: [String: Double], bilder: Int)
    /// „Maße übernehmen“ (REF_APPLY): schreibt die Werte in die param()-Aufrufe von model.py.
    func referenzMasseUebernehmen(_ name: String, werte: [String: Double])
    func referenzNetzZeigen(_ name: String, _ sichtbar: Bool)
    func referenzNetzDeckkraft(_ name: String, _ wert: Double)
    /// Fotoansicht: Blick durch die eingepasste Kamera, Foto hinter dem Modell.
    func fotoansichtOeffnen(_ name: String, satz: String, index: Int)
    func fotoansichtSchliessen()
    func fotoWechseln(_ schritt: Int)
    func fotoDeckkraft(_ wert: Double)
    func fotoModus(_ modus: FotoAnsicht.Modus)
    func referenzImFinder(_ name: String)
}
