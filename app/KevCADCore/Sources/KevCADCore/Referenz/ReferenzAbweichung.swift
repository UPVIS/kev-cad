import Foundation
import OCCTSwiftViewport
import simd

// Rest von Phase 4 (PROTOCOL.md „Abweichung, Maßstab, Scans in der App“, additiv): Abweichung zwischen Modell und
// Referenznetz als Farbkarte (REF_DEVIATION und die Kurzfassung in REF_LIST), Maßstab nachträglich (REF_SCALE) und
// die Scans vom iPhone (SCAN_LIST, SCAN_IMPORT).

/// Kennzahlen einer Abweichung (Feld oder Kurzfassung): Mittel des Betrags, 95 %, größte, Versatz mit Vorzeichen,
/// abgedeckter Anteil der Fläche.
public struct ReferenzKennzahlen: Equatable, Sendable {
    public var mittel: Double?
    public var p95: Double?
    public var max: Double?
    public var versatz: Double?
    public var abgedeckt: Double
    public var ortMax: SIMD3<Float>?

    init(json j: JSONValue?) {
        mittel = j?["mittel_mm"]?.doubleValue
        p95 = j?["p95_mm"]?.doubleValue
        max = j?["max_mm"]?.doubleValue
        versatz = j?["versatz_mm"]?.doubleValue
        abgedeckt = j?["abgedeckt"]?.doubleValue ?? 0
        ortMax = j?["ort_max"]?.vector3
    }
}

/// Kennzahlen eines Teils in der Kurzfassung.
public struct ReferenzAbweichungTeil: Identifiable, Equatable, Sendable {
    public var teil: String
    public var feld: String
    public var kennzahlen: ReferenzKennzahlen
    public var id: String { teil }
}

/// `REF_LIST.referenzen[i].abweichung`: Stand, Legende, Kennzahlen je Teil und für das Referenznetz, Schlüssel der
/// Felder, die dazu gehören.
public struct ReferenzAbweichungKurz: Equatable, Sendable {
    public var stand: String
    public var run: Int
    public var grenze: Double
    public var skala: Double
    public var skalaAuto: Double
    public var skalaFest: Bool
    public var angelegt: Bool
    public var meldung: String?
    public var teile: [ReferenzAbweichungTeil]
    public var referenzFeld: String?
    public var referenz: ReferenzKennzahlen?

    public init?(json j: JSONValue?) {
        guard let j, case .object = j, let stand = j["stand"]?.stringValue else { return nil }
        self.stand = stand
        run = j["run"]?.intValue ?? 0
        grenze = j["grenze_mm"]?.doubleValue ?? 10
        skala = j["skala_mm"]?.doubleValue ?? 1
        skalaAuto = j["skala_auto"]?.doubleValue ?? skala
        skalaFest = j["skala_fest"]?.boolValue ?? false
        angelegt = j["angelegt"]?.boolValue ?? false
        meldung = j["meldung"]?.stringValue
        teile = (j["teile"]?.arrayValue ?? []).compactMap { t in
            guard let teil = t["teil"]?.stringValue, let feld = t["feld"]?.stringValue else { return nil }
            return ReferenzAbweichungTeil(teil: teil, feld: feld, kennzahlen: ReferenzKennzahlen(json: t))
        }
        referenzFeld = j["referenz"]?["feld"]?.stringValue
        referenz = j["referenz"].flatMap { v -> ReferenzKennzahlen? in
            if case .object = v { return ReferenzKennzahlen(json: v) }
            return nil
        }
    }

    /// Schlüssel aller Felder, die zu diesem Stand gehören.
    public var schluessel: Set<String> { Set(teile.map(\.feld) + (referenzFeld.map { [$0] } ?? [])) }
    /// Teile mit der größten Abweichung zuerst.
    public var nachGroesse: [ReferenzAbweichungTeil] {
        teile.sorted { ($0.kennzahlen.max ?? -1) > ($1.kennzahlen.max ?? -1) }
    }
}

/// Gesetzter Maßstab (`REF_LIST.referenzen[i].massstab`).
public struct ReferenzMassstab: Equatable, Sendable {
    public var faktor: Double
    public var mm: Double?
    public var istMm: Double?
    public var quelle: String?
    public var kante: String?
    public var stand: String?

    init?(json j: JSONValue?) {
        guard let j, let f = j["faktor"]?.doubleValue else { return nil }
        faktor = f
        mm = j["mm"]?.doubleValue
        istMm = j["ist_mm"]?.doubleValue
        quelle = j["quelle"]?.stringValue
        kante = j["kante"]?.stringValue
        stand = j["stand"]?.stringValue
    }
}

/// Feld einer Abweichung (REF_DEVIATION): Netz in Weltkoordinaten mit dem Abstand je Punkt (mm, positiv = Referenz
/// außerhalb des Modells, NaN = keine Referenz in der Nähe).
public struct ReferenzAbweichungFeld: Equatable, Sendable {
    public enum Auf: String, Sendable, CaseIterable { case modell, referenz }

    public var referenz: String
    public var run: Int
    public var auf: Auf
    public var teil: String?
    public var feld: String
    public var grenze: Double?
    public var kennzahlen: ReferenzKennzahlen
    public var punkte: [SIMD3<Float>]
    public var dreiecke: [UInt32]
    public var werte: [Float]

    /// Schlüssel im Speicher der App: Referenz, Richtung, Teil.
    public var key: String { Self.key(referenz, auf, teil) }
    public static func key(_ referenz: String, _ auf: Auf, _ teil: String?) -> String {
        referenz + "\u{1F}" + auf.rawValue + "\u{1F}" + (teil ?? "")
    }

    struct Fehler: Error, CustomStringConvertible {
        var description: String
    }

    public static func decode(header: Data, payload: Data) throws -> ReferenzAbweichungFeld {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        guard let ref = j["referenz"]?.stringValue, let feld = j["feld"]?.stringValue,
              let auf = Auf(rawValue: j["auf"]?.stringValue ?? ""), let n = j["punkte"]?.intValue,
              let m = j["dreiecke"]?.intValue, n >= 0, m >= 0
        else { throw Fehler(description: "REF_DEVIATION ohne referenz, feld, auf oder Anzahl") }
        let erwartet = n * 12 + m * 12 + n * 4
        guard payload.count == erwartet else {
            throw Fehler(description: "REF_DEVIATION: Nutzlast \(payload.count) Byte, erwartet \(erwartet)")
        }
        var punkte: [SIMD3<Float>] = []
        var dreiecke: [UInt32] = []
        var werte: [Float] = []
        punkte.reserveCapacity(n)
        dreiecke.reserveCapacity(3 * m)
        werte.reserveCapacity(n)
        payload.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var o = 0
            func u() -> UInt32 {
                let v = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: o, as: UInt32.self))
                o += 4
                return v
            }
            func f() -> Float { Float(bitPattern: u()) }
            for _ in 0..<n { punkte.append(SIMD3(f(), f(), f())) }
            for _ in 0..<(3 * m) { dreiecke.append(u()) }
            for _ in 0..<n { werte.append(f()) }
        }
        if let g = dreiecke.max(), Int(g) >= n {
            throw Fehler(description: "REF_DEVIATION: Dreieck zeigt auf Punkt \(g), es gibt \(n)")
        }
        let teil = j["teil"]?.stringValue
        return ReferenzAbweichungFeld(
            referenz: ref, run: j["run"]?.intValue ?? 0, auf: auf, teil: teil?.isEmpty == true ? nil : teil, feld: feld,
            grenze: j["grenze_mm"]?.doubleValue, kennzahlen: ReferenzKennzahlen(json: j["kennzahlen"]), punkte: punkte,
            dreiecke: dreiecke, werte: werte)
    }
}

/// Farbkarte, die gerade gezeigt wird.
public struct FarbkarteAnzeige: Equatable, Sendable {
    public var referenz: String
    public var auf: ReferenzAbweichungFeld.Auf
    /// Spanne der Legende in mm (± skala); nil = die des Kernels.
    public var skala: Double?

    public init(referenz: String, auf: ReferenzAbweichungFeld.Auf, skala: Double? = nil) {
        self.referenz = referenz
        self.auf = auf
        self.skala = skala
    }
}

/// Körper der Farbkarte: Bänder gleicher Abweichung (je Band ein Körper mit einer Farbe, Grenzen genau auf den
/// Höhenlinien wie beim Festkörper-Feld der Statik), dazu grau, wo keine Referenz in der Nähe ist. Rein, testbar.
public enum AbweichungGeometrie {
    public static let praefix = "\u{1F}abweichung\u{1F}"
    /// Elf Bänder von −skala bis +skala; das mittlere (|d| < skala / 11) ist grün.
    public static let baender = 11
    /// Farben in sRGB: blau (Modell zu groß) → türkis → grün (passt) → gelb → rot (Modell zu klein).
    static let stuetzen: [(Float, SIMD3<Float>)] = [
        (-1, SIMD3(0.16, 0.33, 0.86)), (-0.5, SIMD3(0.12, 0.70, 0.86)), (0, SIMD3(0.20, 0.72, 0.34)),
        (0.5, SIMD3(0.98, 0.80, 0.15)), (1, SIMD3(0.88, 0.14, 0.11)),
    ]
    public static let grau = SIMD3<Float>(0.47, 0.47, 0.49)

    /// Farbe (sRGB) für t = Abweichung / skala, auf −1 … 1 begrenzt.
    public static func farbeSRGB(_ t: Double) -> SIMD3<Float> {
        let x = Float(max(-1, min(1, t.isFinite ? t : 0)))
        for k in 1..<stuetzen.count where x <= stuetzen[k].0 {
            let (a, ca) = stuetzen[k - 1], (b, cb) = stuetzen[k]
            let w = (x - a) / (b - a)
            return ca + (cb - ca) * w
        }
        return stuetzen.last!.1
    }

    /// Band (0 … baender − 1) eines Werts bei Spanne `skala`.
    public static func band(_ d: Float, skala: Float) -> Int {
        let breite = 2 * skala / Float(baender)
        let k = Int(((d + skala) / breite).rounded(.down))
        return min(max(k, 0), baender - 1)
    }

    /// Mitte eines Bands in Vielfachen von `skala` (−1 … 1), für die Farbe.
    public static func bandMitte(_ k: Int) -> Double { (Double(k) + 0.5) * 2 / Double(baender) - 1 }

    /// Bänder des Felds als Körper (Farben linear), `alpha` für die Deckkraft.
    public static func koerper(_ f: ReferenzAbweichungFeld, skala: Double, id: String, alpha: Float = 1)
        -> [ViewportBody]
    {
        let s = Float(max(skala, 0.01))
        let breite = 2 * s / Float(baender)
        // Bänder 0 … baender − 1, dazu als letztes grau (ohne Referenz)
        var soup = [[Float]](repeating: [], count: baender + 1)
        let n = f.dreiecke.count / 3
        // Schnellweg ohne Zwischenfelder: die feinen Netze liegen fast ganz in je einem Band (Kevins Scan 225 000
        // Dreiecke); nur Dreiecke über einer Bandgrenze werden geschnitten
        @inline(__always) func setze(_ vd: inout [Float], _ a: SIMD3<Float>, _ b: SIMD3<Float>, _ c: SIMD3<Float>,
                                     _ nrm: SIMD3<Float>) {
            @inline(__always) func ein(_ q: SIMD3<Float>) {
                vd.append(q.x); vd.append(q.y); vd.append(q.z)
                vd.append(nrm.x); vd.append(nrm.y); vd.append(nrm.z)
            }
            ein(a); ein(b); ein(c)
        }
        f.punkte.withUnsafeBufferPointer { p in
            f.werte.withUnsafeBufferPointer { w in
                f.dreiecke.withUnsafeBufferPointer { d in
                    for t in 0..<n {
                        let i0 = Int(d[3 * t]), i1 = Int(d[3 * t + 1]), i2 = Int(d[3 * t + 2])
                        let a = p[i0], b = p[i1], c = p[i2]
                        var nrm = simd_cross(b - a, c - a)
                        let l = simd_length(nrm)
                        if l < 1e-12 { continue }
                        nrm /= l
                        let wa = w[i0], wb = w[i1], wc = w[i2]
                        if !(wa.isFinite && wb.isFinite && wc.isFinite) {
                            setze(&soup[baender], a, b, c, nrm)
                            continue
                        }
                        let ka = min(max(wa, -s * 1.5), s * 1.5), kb = min(max(wb, -s * 1.5), s * 1.5)
                        let kc = min(max(wc, -s * 1.5), s * 1.5)
                        let b0 = band(min(ka, kb, kc), skala: s), b1 = band(max(ka, kb, kc), skala: s)
                        if b0 == b1 {
                            setze(&soup[b0], a, b, c, nrm)
                            continue
                        }
                        schneiden(&soup, [a, b, c], [ka, kb, kc], nrm, b0, b1, s, breite)
                    }
                }
            }
        }
        var out: [ViewportBody] = []
        for (b, vd) in soup.enumerated() where !vd.isEmpty {
            let srgb = b == baender ? grau : farbeSRGB(bandMitte(b))
            var farbe = PartBodies.linear(SIMD4(srgb, 1))
            farbe.w = alpha
            out += StatikFeldGeometrie.zerlege(vd, id: "\(praefix)\(id)\u{1F}\(b == baender ? "g" : "\(b)")", farbe: farbe)
        }
        return out
    }

    /// Dreieck über mehrere Bänder: an den Bandgrenzen schneiden (Sutherland-Hodgman wie beim Festkörper-Feld).
    static func schneiden(_ soup: inout [[Float]], _ q: [SIMD3<Float>], _ k: [Float], _ nrm: SIMD3<Float>, _ b0: Int,
                          _ b1: Int, _ s: Float, _ breite: Float) {
        for b in b0...b1 {
            let lo = b == 0 ? -Float.greatestFiniteMagnitude : -s + Float(b) * breite
            let hi = b == baender - 1 ? Float.greatestFiniteMagnitude : -s + Float(b + 1) * breite
            var poly = Array(zip(q, k))
            poly = StatikFeldGeometrie.schneide(poly, grenze: lo, oben: true)
            poly = StatikFeldGeometrie.schneide(poly, grenze: hi, oben: false)
            guard poly.count >= 3 else { continue }
            for j in 1..<(poly.count - 1) {
                StatikFeldGeometrie.anhaengen(&soup[b], [poly[0].0, poly[j].0, poly[j + 1].0], nrm)
            }
        }
    }
}

/// Ein Scan vom iPhone (SCAN_LIST.scans[i]).
public struct ScanInfo: Identifiable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var empfangen: String?
    public var erstellt: String?
    public var geraet: String?
    public var fotos: Int
    public var videobilder: Int
    public var objekt: Bool
    public var groesseMB: Double?
    public var vorschau: URL?
    public var neu: Bool
    /// Referenzen, in die der Scan übernommen wurde (Projektpfad und Name).
    public var referenzen: [(projekt: String, name: String)]

    public static func == (a: ScanInfo, b: ScanInfo) -> Bool {
        a.id == b.id && a.name == b.name && a.neu == b.neu && a.fotos == b.fotos && a.videobilder == b.videobilder
            && a.referenzen.map(\.name) == b.referenzen.map(\.name)
    }

    init?(json j: JSONValue) {
        guard let id = j["id"]?.stringValue else { return nil }
        self.id = id
        name = j["name"]?.stringValue ?? id
        empfangen = j["empfangen"]?.stringValue
        erstellt = j["erstellt"]?.stringValue
        geraet = j["geraet"]?.stringValue
        fotos = j["fotos"]?.intValue ?? 0
        videobilder = j["videobilder"]?.intValue ?? 0
        objekt = j["objekt"]?.boolValue ?? false
        groesseMB = j["groesse_mb"]?.doubleValue
        vorschau = j["vorschau"]?.stringValue.map { URL(fileURLWithPath: $0) }
        neu = (j["zustand"]?.stringValue ?? "neu") == "neu"
        referenzen = (j["referenzen"]?.arrayValue ?? []).compactMap { r in
            guard let n = r["name"]?.stringValue else { return nil }
            return (r["projekt"]?.stringValue ?? "", n)
        }
    }

    /// „22.10. 21:40“ aus `empfangen` (ISO, lokale Zeit).
    public var empfangenKurz: String? {
        guard let e = empfangen, e.count >= 16 else { return nil }
        let d = e.split(separator: "T")
        guard d.count == 2 else { return nil }
        let datum = d[0].split(separator: "-")
        guard datum.count == 3 else { return nil }
        return "\(datum[2]).\(datum[1]). \(d[1].prefix(5))"
    }
}

/// SCAN_LIST: alle Scans und der Empfänger.
public struct ScanListe: Equatable, Sendable {
    public var scans: [ScanInfo]
    public var ordner: String?
    public var neu: String?
    public var empfaengerLaeuft: Bool
    public var empfaengerName: String?

    init(json j: JSONValue) {
        scans = (j["scans"]?.arrayValue ?? []).compactMap(ScanInfo.init(json:))
        ordner = j["ordner"]?.stringValue
        neu = j["neu"]?.stringValue
        empfaengerLaeuft = j["empfaenger"]?["laeuft"]?.boolValue ?? false
        empfaengerName = j["empfaenger"]?["name"]?.stringValue
    }
}

/// Werkzeug „Maßstab setzen“: Kevin klickt zwei Punkte am Referenznetz.
public struct MassstabWerkzeug: Equatable, Sendable {
    public var referenz: String
    public var punkte: [SIMD3<Float>]
    public init(referenz: String, punkte: [SIMD3<Float>] = []) {
        self.referenz = referenz
        self.punkte = punkte
    }
    public var abstand: Double? {
        punkte.count == 2 ? Double(simd_distance(punkte[0], punkte[1])) : nil
    }
}

// MARK: - App → Kernel

/// REF_SCALE: Maßstab nachträglich (zwei Punkte am Netz oder ein benanntes Maß, dazu das echte Maß).
public struct ReferenzMassstabMessage: OutgoingRequest {
    public static let type = "REF_SCALE"
    public var seq = 0
    public var id: String
    public var referenz: String
    public var punkte: [[Double]]?
    public var kante: String?
    public var mm: Double

    public init(id: String, referenz: String, punkte: [SIMD3<Float>]? = nil, kante: String? = nil, mm: Double) {
        self.id = id
        self.referenz = referenz
        self.punkte = punkte.map { $0.map { [Double($0.x), Double($0.y), Double($0.z)] } }
        self.kante = kante
        self.mm = mm
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, referenz, punkte, kante, mm }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(referenz, forKey: .referenz)
        try c.encode(punkte, forKey: .punkte)
        try c.encode(kante, forKey: .kante)
        try c.encode(mm, forKey: .mm)
    }
}

/// SCAN_IMPORT: „Scan übernehmen“ ins offene Projekt (wie MCP `scan_importieren`).
public struct ScanImportMessage: OutgoingRequest {
    public static let type = "SCAN_IMPORT"
    public var seq = 0
    public var id: String
    public var scan: String
    public var name: String?
    public var schnell: Bool

    public init(id: String, scan: String, name: String? = nil, schnell: Bool) {
        self.id = id
        self.scan = scan
        self.name = name
        self.schnell = schnell
    }

    enum CodingKeys: String, CodingKey { case type, seq, id, scan, name, schnell }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(Self.type, forKey: .type)
        try c.encode(seq, forKey: .seq)
        try c.encode(id, forKey: .id)
        try c.encode(scan, forKey: .scan)
        try c.encode(name, forKey: .name)
        try c.encode(schnell, forKey: .schnell)
    }
}
