import Combine
import Foundation
import OCCTSwiftViewport
import simd

// Phase 5, Strang KAM: Kameras aus model.py (PROTOCOL.md „Phase 5: Kameras“). Kameras heißen `Kamera/<name>`, stehen
// in `AppModel.cameras` (CameraStore) und werden über `CameraActions` bedient (die Oberfläche ruft
// `model.actions as? CameraActions`).

/// Eine Kamera aus CAMERA_UPSERT. Lage und Bildwinkel genau so, wie der Kernel sie gerechnet hat.
public struct CameraInfo: Identifiable, Equatable, Sendable {
    /// `Kamera/<name>`
    public var name: String
    public var kurzname: String
    public var run: Int
    public var kameraID: String
    public var kameraName: String
    public var objektivID: String?
    public var objektivName: String?
    public var formatID: String
    public var formatName: String
    public var sensorPos: SIMD3<Float>
    /// Projektionszentrum (Sensormitte plus Brennweite in Blickrichtung)
    public var auge: SIMD3<Float>
    public var blick: SIMD3<Float>
    public var oben: SIMD3<Float>
    public var rechts: SIMD3<Float>
    public var sensorMM: SIMD2<Double>
    public var aufloesung: SIMD2<Int>
    public var seitenverhaeltnis: Double
    public var brennweite: Double
    public var bildwinkelH: Double
    public var bildwinkelV: Double
    public var bildwinkelD: Double
    public var blende: Double
    /// "f" (Fotoobjektiv) oder "t" (Cine, T-Blende)
    public var blendenart: String
    /// mm ab Sensorebene; nil = unendlich
    public var fokus: Double?
    public var schaerfeNah: Double?
    public var schaerfeFern: Double?
    public var hyperfokal: Double?
    public var zerstreuungskreis: Double
    /// Gezeigtes Teil, an dem die Kamera hängt
    public var teil: String?
    /// Gezeigtes Teil, dessen Bewegung (Animation, Explosion) die Kamera mitmacht: `teil`, sonst das eigene Gehäuse
    /// aus `koerper()`; nil = Kamera steht fest. Ältere Kernel schicken es nicht, dann gilt `teil`.
    public var folgt: String?
    /// Beim Blick durch die Kamera auszublenden (eigenes Objektiv)
    public var ausblenden: [String]
    /// Sensorebene bis Frontlinse in mm
    public var objektivVorne: Double
    public var vignettierung: Bool
    /// Lage stammt aus Strg+Alt+0 in der App (Vorschlag), nicht aus model.py
    public var vorschlag = false

    public var id: String { name }

    public static let prefix = "Kamera/"

    /// Name ohne „Kamera/“.
    public var displayName: String {
        kurzname.isEmpty ? String(name.dropFirst(name.hasPrefix(Self.prefix) ? Self.prefix.count : 0)) : kurzname
    }

    public init?(json: JSONValue) {
        guard let name = json["name"]?.stringValue, !name.isEmpty else { return nil }
        func v3(_ key: String, _ fallback: SIMD3<Float>) -> SIMD3<Float> { json[key]?.vector3 ?? fallback }
        self.name = name
        kurzname = json["kurzname"]?.stringValue ?? ""
        run = json["run"]?.intValue ?? 0
        kameraID = json["kamera"]?["id"]?.stringValue ?? ""
        let kid = json["kamera"]?["id"]?.stringValue ?? ""
        kameraName = json["kamera"]?["name"]?.stringValue ?? kid
        objektivID = json["objektiv"]?["id"]?.stringValue
        objektivName = json["objektiv"]?["name"]?.stringValue
        let fid = json["format"]?["id"]?.stringValue ?? ""
        formatID = fid
        formatName = json["format"]?["name"]?.stringValue ?? fid
        let pos = v3("sensor_pos", .zero)
        let d = simd_normalize(v3("blick", SIMD3(1, 0, 0)))
        let dir: SIMD3<Float> = d.x.isFinite ? d : SIMD3(1, 0, 0)
        let up = v3("oben", SIMD3(0, 0, 1))
        sensorPos = pos
        blick = dir
        oben = up
        rechts = v3("rechts", simd_cross(dir, up))
        let s = json["sensor_mm"]?.doubles ?? [36, 24]
        let sensor = SIMD2(s.count > 0 ? s[0] : 36, s.count > 1 ? s[1] : 24)
        sensorMM = sensor
        let r = json["aufloesung"]?.doubles ?? []
        let res = SIMD2(r.count > 0 ? Int(r[0]) : 1920, r.count > 1 ? Int(r[1]) : 1080)
        aufloesung = res
        seitenverhaeltnis = json["seitenverhaeltnis"]?.doubleValue ?? Double(res.x) / Double(max(res.y, 1))
        let f = json["brennweite"]?.doubleValue ?? 50
        brennweite = f
        bildwinkelH = json["bildwinkel_h"]?.doubleValue ?? 2 * atan(sensor.x / (2 * f)) * 180 / .pi
        bildwinkelV = json["bildwinkel_v"]?.doubleValue ?? 2 * atan(sensor.y / (2 * f)) * 180 / .pi
        bildwinkelD = json["bildwinkel_d"]?.doubleValue ?? 0
        auge = json["auge"]?.vector3 ?? (pos + dir * Float(f))
        blende = json["blende"]?.doubleValue ?? 2.8
        blendenart = json["blendenart"]?.stringValue ?? "f"
        fokus = json["fokus"]?.doubleValue
        schaerfeNah = json["schaerfe_nah"]?.doubleValue
        schaerfeFern = json["schaerfe_fern"]?.doubleValue
        hyperfokal = json["hyperfokal"]?.doubleValue
        zerstreuungskreis = json["zerstreuungskreis"]?.doubleValue ?? 0.03
        teil = json["teil"]?.stringValue
        folgt = json["folgt"]?.stringValue ?? json["teil"]?.stringValue
        ausblenden = json["ausblenden"]?.stringList ?? []
        objektivVorne = json["objektiv_vorne"]?.doubleValue ?? 18 + f
        vignettierung = json["vignettierung"]?.boolValue ?? false
    }

    /// Dieselbe Kamera, starr mit `m` bewegt (Lage des Teils, dem sie folgt, relativ zu seiner Ruhelage).
    public func transformed(by m: simd_float4x4) -> CameraInfo {
        func point(_ v: SIMD3<Float>) -> SIMD3<Float> {
            let r = m * SIMD4(v, 1)
            return SIMD3(r.x, r.y, r.z)
        }
        func direction(_ v: SIMD3<Float>) -> SIMD3<Float> {
            let r = m * SIMD4(v, 0)
            let d = SIMD3(r.x, r.y, r.z)
            let len = simd_length(d)
            return len > 1e-9 ? d / len : v
        }
        var c = self
        c.sensorPos = point(sensorPos)
        c.auge = point(auge)
        c.blick = direction(blick)
        c.oben = direction(oben)
        c.rechts = direction(rechts)
        return c
    }

    /// Neue Lage (Vorschlag aus der Ansicht): Augpunkt, Blick und Oben; die Sensormitte liegt eine Brennweite dahinter.
    public func moved(auge: SIMD3<Float>, blick: SIMD3<Float>, oben: SIMD3<Float>) -> CameraInfo {
        var c = self
        c.blick = simd_normalize(blick)
        c.rechts = simd_normalize(simd_cross(c.blick, oben))
        c.oben = simd_cross(c.rechts, c.blick)
        c.auge = auge
        c.sensorPos = auge - c.blick * Float(brennweite)
        c.vorschlag = true
        return c
    }

    // MARK: Texte

    /// Zahl ohne überflüssige Nachkommastelle: 35 → "35", 2,8 → "2,8".
    public static func trimmed(_ v: Double, digits: Int = 1) -> String {
        abs(v - v.rounded()) < 1e-9 ? KevFormat.number(v, digits: 0) : KevFormat.number(v, digits: digits)
    }

    public var blendeText: String {
        let n = Self.trimmed(blende)
        return blendenart == "t" ? "T\(n)" : "f/\(n)"
    }

    public static func distanceText(_ mm: Double?) -> String {
        guard let mm, mm.isFinite else { return "∞" }
        if mm < 1000 { return "\(KevFormat.number(mm / 10, digits: 1)) cm" }
        return "\(KevFormat.number(mm / 1000, digits: 2)) m"
    }

    public var fokusText: String { Self.distanceText(fokus) }

    public var schaerfeText: String {
        "\(Self.distanceText(schaerfeNah)) – \(Self.distanceText(schaerfeFern))"
    }

    public var brennweiteText: String { "\(Self.trimmed(brennweite)) mm" }

    public var bildwinkelText: String {
        "\(KevFormat.number(bildwinkelH, digits: 1))° × \(KevFormat.number(bildwinkelV, digits: 1))°"
    }

    public var aufloesungText: String { "\(aufloesung.x) × \(aufloesung.y)" }

    /// „FX6 · 35 mm · T2,8 · Fokus 1,50 m“
    public var kurzText: String { "\(displayName) · \(brennweiteText) · \(blendeText) · Fokus \(fokusText)" }
}

/// CAMERA_UPSERT oder CAMERA_REMOVE.
public enum CameraMessage: Sendable {
    case upsert(CameraInfo)
    case remove(name: String)

    public var typeName: String {
        switch self {
        case .upsert: return "CAMERA_UPSERT"
        case .remove: return "CAMERA_REMOVE"
        }
    }

    public static func decode(_ header: Data, type: String) throws -> CameraMessage {
        let json = try JSONDecoder().decode(JSONValue.self, from: header)
        if type == "CAMERA_REMOVE" {
            guard let name = json["name"]?.stringValue else {
                throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "CAMERA_REMOVE ohne name"))
            }
            return .remove(name: name)
        }
        guard let info = CameraInfo(json: json) else {
            throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "CAMERA_UPSERT ohne name"))
        }
        return .upsert(info)
    }
}

/// CAMERA_SUGGEST (App → Kernel): aktuelle Ansicht als neue Lage der Kamera.
public struct CameraSuggestMessage: OutgoingMessage {
    public static let type = "CAMERA_SUGGEST"
    public var seq = 0
    public var name: String
    public var sensorPos: SIMD3<Float>
    public var auge: SIMD3<Float>
    public var blick: SIMD3<Float>
    public var oben: SIMD3<Float>
    public var rechts: SIMD3<Float>
    /// Grad gegenüber einer waagrechten Kamera (oben = Welt-Z), positiv im Uhrzeigersinn von hinten
    public var roll: Double

    public init(
        name: String, sensorPos: SIMD3<Float>, auge: SIMD3<Float>, blick: SIMD3<Float>, oben: SIMD3<Float>,
        rechts: SIMD3<Float>, roll: Double
    ) {
        self.name = name
        self.sensorPos = sensorPos
        self.auge = auge
        self.blick = blick
        self.oben = oben
        self.rechts = rechts
        self.roll = roll
    }

    enum CodingKeys: String, CodingKey {
        case type, seq, name, auge, blick, oben, rechts, roll
        case sensorPos = "sensor_pos"
    }

    public func encode(to encoder: Encoder) throws {
        func a(_ v: SIMD3<Float>) -> [Double] { [Double(v.x), Double(v.y), Double(v.z)] }
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(name, forKey: .name)
        try c.encode(a(sensorPos), forKey: .sensorPos)
        try c.encode(a(auge), forKey: .auge)
        try c.encode(a(blick), forKey: .blick)
        try c.encode(a(oben), forKey: .oben)
        try c.encode(a(rechts), forKey: .rechts)
        try c.encode(roll, forKey: .roll)
    }
}

/// Kameras des Projekts und der Blick durch eine Kamera. Gehört zu AppModel (`model.cameras`); geändert nur vom
/// App-Kern (die Oberfläche liest und ruft `CameraActions`).
@MainActor
public final class CameraStore: ObservableObject {
    @Published public private(set) var cameras: [CameraInfo] = []
    /// Kamera, durch die der Viewport gerade schaut (nil = freie Ansicht).
    @Published public internal(set) var activeView: String?
    /// Im Teilebaum oder Inspektor gewählte Kamera (Ziel von Taste 0 und Strg+Alt+0).
    @Published public internal(set) var selected: String?
    /// Zuletzt gespeichertes Kamerabild (Pfad), für die Oberfläche.
    @Published public internal(set) var lastImage: URL?

    // Zustand der Kameraansicht (nur App-Kern)
    var savedViewport: CameraState?
    var lastApplied: CameraState?
    var ignoreChangesUntil = Date.distantPast
    var trackingInstalled = false

    public init() {}

    public func camera(_ name: String) -> CameraInfo? {
        if let c = cameras.first(where: { $0.name == name }) { return c }
        let low = name.lowercased()
        return cameras.first { $0.displayName.lowercased() == low || $0.name.lowercased() == low }
    }

    /// Kamera für Taste 0 und Strg+Alt+0: die aktive, sonst die gewählte, sonst die erste.
    public var target: CameraInfo? {
        if let a = activeView, let c = camera(a) { return c }
        if let s = selected, let c = camera(s) { return c }
        return cameras.first
    }

    func upsert(_ c: CameraInfo) {
        if let i = cameras.firstIndex(where: { $0.name == c.name }) { cameras[i] = c } else { cameras.append(c) }
    }

    func remove(_ name: String) {
        cameras.removeAll { $0.name == name }
        if selected == name { selected = nil }
    }

    func removeAll() {
        cameras = []
        selected = nil
    }
}

/// Aktionen rund um Kameras, implementiert vom App-Kern (AppController).
@MainActor
public protocol CameraActions: AnyObject {
    /// Durch die Kamera schauen (Name `Kamera/<name>` oder Kurzname); nil = zurück zur Ansicht davor.
    func lookThrough(_ name: String?)
    /// Taste 0: durch die gewählte (sonst erste) Kamera schauen bzw. zurück.
    func toggleCameraView()
    /// Strg+Alt+0: aktive Kamera auf die aktuelle Ansicht setzen (Vorschlag an Kernel und Agent).
    func setActiveCameraToView()
    /// Kamera im Teilebaum/Inspektor wählen.
    func selectCamera(_ name: String?)
    /// Kamerabild in voller Auflösung des Formats nach `<Projekt>/output/kameras/` rendern.
    func renderCameraImage(_ name: String)
}
