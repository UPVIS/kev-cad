import Foundation
import OCCTSwiftViewport
import simd

// Statik Stufe 3 (PROTOCOL.md „Festkörper (Stufe 3)“, additiv): Ergebnis der Festkörper-FEM je Szenario und Teil.
// STATICS trägt je Szenario `festkoerper` (Stand, Fortschritt, je Teil Sicherheit, Kriterium, Ort, Drucklagen), die
// Nachricht STATICS_FIELD das Oberflächennetz des Teils mit Ausnutzung, von-Mises-Spannung und Verschiebung je Punkt.

// Statik Stufe 4 (CalculiX, additiv): je Teil zusätzlich Verfahren, Sicherheit unter Last, Kontakt je Paar mit
// Klemmungen, Plastizität, Traglast, Beulen, Rutschen und die größten Zusatzwerte des Felds; STATICS_FIELD trägt dann
// hinter den bisherigen Werten Kontaktdruck, plastische Dehnung, Klaffen und Schlupf je Punkt.

/// Stufe 4: Kontakt des Teils mit einem Partner (Lager, Nachbarteil) unter der Last.
public struct StatikKontaktPaar: Equatable, Sendable {
    public var mit: String
    public var rolle: String?
    public var reibwert: Double?
    /// Größter Kontaktdruck in N/mm².
    public var druckMax: Double?
    public var kraftN: Double?
    public var traegtMm2: Double?
    /// Anteil der Berührfläche, der trägt (0 … 1).
    public var anteilTraegt: Double?
    public var klaffenMaxMm: Double?
    public var schlupfMaxMm: Double?
    /// Genutzter Anteil der Haftreibung (0 … 1).
    public var reibungAusnutzung: Double?
    /// Anteil der tragenden Fläche, der gleitet (0 … 1).
    public var gleitetAnteil: Double?
    public var quelle: String?

    init(json j: JSONValue) {
        mit = j["mit"]?.stringValue ?? ""
        rolle = j["rolle"]?.stringValue
        reibwert = j["reibwert"]?.doubleValue
        druckMax = j["druck_max"]?.doubleValue
        kraftN = j["kraft_n"]?.doubleValue
        traegtMm2 = j["traegt_mm2"]?.doubleValue
        anteilTraegt = j["anteil_traegt"]?.doubleValue
        klaffenMaxMm = j["klaffen_max_mm"]?.doubleValue
        schlupfMaxMm = j["schlupf_max_mm"]?.doubleValue
        reibungAusnutzung = j["reibung_ausnutzung"]?.doubleValue
        gleitetAnteil = j["gleitet_anteil"]?.doubleValue
        quelle = j["quelle"]?.stringValue
    }
}

/// Stufe 4: Vorspannung einer Schraube, die das Teil klemmt.
public struct StatikKlemmung: Equatable, Sendable {
    public var schraube: String?
    public var kraftN: Double?
    public var quelle: String?

    init(json j: JSONValue) {
        schraube = j["schraube"]?.stringValue
        kraftN = j["kraft_n"]?.doubleValue
        quelle = j["quelle"]?.stringValue
    }
}

/// Stufe 4: elastisch-plastisches Verhalten unter der Last.
public struct StatikPlastisch: Equatable, Sendable {
    /// Größte plastische Vergleichsdehnung (dimensionslos, 0,004 = 0,4 %).
    public var dehnungMax: Double?
    public var bleibendMm: Double?
    public var fliesst: Bool
    public var grenzdehnung: Double?
    /// Fließgrenze in N/mm².
    public var fliessgrenze: Double?
    public var modell: String?
    public var ort: SIMD3<Float>?

    init(json j: JSONValue) {
        dehnungMax = j["dehnung_max"]?.doubleValue
        bleibendMm = j["bleibend_mm"]?.doubleValue
        fliesst = j["fliesst"]?.boolValue ?? false
        grenzdehnung = j["grenzdehnung"]?.doubleValue
        fliessgrenze = j["fliessgrenze"]?.doubleValue
        modell = j["modell"]?.stringValue
        ort = j["ort"]?.vector3
    }
}

/// Stufe 4: Traglast, das Vielfache der Last, bei dem das Teil versagt (Grenzdehnung, Schichtfuge, Rutschen, Kollaps).
public struct StatikTraglast: Equatable, Sendable {
    public var faktor: Double?
    /// Maßgebendes Kriterium; "nicht_erreicht": bis `lastfaktorMax` gerechnet, ohne zu versagen.
    public var kriterium: String?
    public var text: String?
    public var lastfaktorMax: Double?
    /// Bis zu welchem Vielfachen die Rechnung kam.
    public var erreicht: Double?

    public var nichtErreicht: Bool { kriterium == "nicht_erreicht" }

    init(json j: JSONValue) {
        faktor = j["faktor"]?.doubleValue
        kriterium = j["kriterium"]?.stringValue
        text = j["text"]?.stringValue
        lastfaktorMax = j["lastfaktor_max"]?.doubleValue
        erreicht = j["erreicht"]?.doubleValue
    }
}

/// Ein Teil im Festkörper eines Szenarios.
public struct StatikFestkoerperTeil: Equatable, Sendable {
    public var teil: String
    public var stand: String
    public var ampel: StatikAmpel
    public var sicherheit: Double?
    public var ziel: Double?
    public var spannungMax: Double?
    public var kriterium: String?
    public var ort: SIMD3<Float>?
    public var verformungMaxMm: Double?
    public var kragtraeger: Double?
    public var druckteil: Bool
    public var q: Double?
    /// Sicherheit je Drucklage (ausrichtung "-z", "-y", "-x"), aus demselben Spannungsfeld.
    public var ausrichtungen: [(String, Double)]
    public var ausrichtungBeste: String?
    public var tetraeder: Int?
    public var freiheitsgrade: Int?
    public var hMm: Double?
    public var ms: Double?
    public var feld: String?
    public var text: String
    public var meldung: String?
    public var ausSpeicher: Bool
    /// Stufe 4: Rechenverfahren ("ccx" = CalculiX); nil bei Stufe 3. Bei "ccx" ist `sicherheit` der Traglastfaktor
    /// (ohne gerechnete Traglast die Sicherheit unter Last).
    public var verfahren: String?
    /// Stufe 4: Sicherheit unter der Last aus den elastisch-plastischen Spannungen mit Kontakt.
    public var sicherheitLast: Double?
    public var kontaktPaare: [StatikKontaktPaar]
    public var klemmungen: [StatikKlemmung]
    public var plastisch: StatikPlastisch?
    public var traglast: StatikTraglast?
    public var beulfaktor: Double?
    /// Stufe 4: Ein Kontaktpartner rutscht schon unter der Last (die Klemmung hält nicht).
    public var rutscht: Bool
    /// Stufe 4: größte Zusatzwerte des Felds (Namen wie `StatikFeldWert.zusatz`).
    public var zusatzMax: [String: Double]

    /// Stufe 4 (CalculiX) gerechnet.
    public var istCalculix: Bool { verfahren == "ccx" }

    public static func == (a: Self, b: Self) -> Bool {
        a.teil == b.teil && a.stand == b.stand && a.ampel == b.ampel && a.sicherheit == b.sicherheit
            && a.feld == b.feld && a.text == b.text && a.meldung == b.meldung && a.verfahren == b.verfahren
            && a.sicherheitLast == b.sicherheitLast && a.kontaktPaare == b.kontaktPaare && a.klemmungen == b.klemmungen
            && a.plastisch == b.plastisch && a.traglast == b.traglast && a.beulfaktor == b.beulfaktor
            && a.rutscht == b.rutscht && a.zusatzMax == b.zusatzMax
    }

    init(json j: JSONValue) {
        teil = j["teil"]?.stringValue ?? ""
        stand = j["stand"]?.stringValue ?? "done"
        ampel = StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau
        sicherheit = j["sicherheit"]?.doubleValue
        ziel = j["ziel"]?.doubleValue
        spannungMax = j["spannung_max"]?.doubleValue
        kriterium = j["kriterium"]?.stringValue
        ort = j["ort"]?.vector3
        verformungMaxMm = j["verformung_max_mm"]?.doubleValue
        kragtraeger = j["kragtraeger"]?.doubleValue
        druckteil = j["druckteil"]?.boolValue ?? false
        q = j["q"]?.doubleValue
        let alt = j["ausrichtungen"]?.objectValue ?? [:]
        ausrichtungen = alt.compactMap { k, v in v.doubleValue.map { (k, $0) } }.sorted { $0.1 > $1.1 }
        ausrichtungBeste = j["ausrichtung_beste"]?.stringValue
        tetraeder = j["netz"]?["tetraeder"]?.intValue
        freiheitsgrade = j["netz"]?["freiheitsgrade"]?.intValue
        hMm = j["netz"]?["h_mm"]?.doubleValue
        ms = j["ms"]?.doubleValue
        feld = j["feld"]?.stringValue
        text = j["text"]?.stringValue ?? ""
        meldung = j["meldung"]?.stringValue
        ausSpeicher = j["aus_speicher"]?.boolValue ?? false
        verfahren = j["verfahren"]?.stringValue
        sicherheitLast = j["sicherheit_last"]?.doubleValue
        kontaktPaare = (j["kontakt"]?["paare"]?.arrayValue ?? []).map(StatikKontaktPaar.init(json:))
        klemmungen = (j["kontakt"]?["klemmungen"]?.arrayValue ?? []).map(StatikKlemmung.init(json:))
        plastisch = j["plastisch"].flatMap { $0.objectValue == nil ? nil : StatikPlastisch(json: $0) }
        traglast = j["traglast"].flatMap { $0.objectValue == nil ? nil : StatikTraglast(json: $0) }
        beulfaktor = j["beulen"]?["faktor"]?.doubleValue
        rutscht = j["rutscht"]?.boolValue ?? false
        zusatzMax = (j["zusatz_max"]?.objectValue ?? [:]).compactMapValues(\.doubleValue)
    }
}

/// Festkörper (Stufe 3) eines Szenarios: läuft im Hintergrund (mit Fortschritt) oder ist gerechnet.
public struct StatikFestkoerper: Equatable, Sendable {
    public var stand: String
    public var fortschritt: Double
    public var text: String
    public var meldung: String?
    public var teile: [StatikFestkoerperTeil]

    public var laeuft: Bool { stand == "laeuft" }

    init(json j: JSONValue) {
        stand = j["stand"]?.stringValue ?? "done"
        fortschritt = j["fortschritt"]?.doubleValue ?? 0
        text = j["text"]?.stringValue ?? ""
        meldung = j["meldung"]?.stringValue
        teile = (j["teile"]?.arrayValue ?? []).map(StatikFestkoerperTeil.init(json:))
    }
}

public enum StatikFeldFehler: Error, Equatable, CustomStringConvertible {
    case kaputt(String)

    public var description: String {
        switch self {
        case .kaputt(let t): return "STATICS_FIELD: \(t)"
        }
    }
}

/// Oberflächennetz eines Teils mit Ausnutzung (Zielsicherheit / örtliche Sicherheit), Spannung (N/mm²) und
/// Verschiebung (mm) je Punkt (STATICS_FIELD).
public struct StatikFeld: Equatable, Sendable {
    public var run: Int
    public var szenario: String
    public var teil: String
    public var schluessel: String
    public var ziel: Double?
    public var sicherheit: Double?
    public var ampel: StatikAmpel
    public var spannungMax: Double?
    public var verformungMaxMm: Double?
    public var ueberhoehung: Float
    public var punkte: [SIMD3<Float>]
    /// Drei Indizes je Dreieck, nach außen orientiert.
    public var dreiecke: [UInt32]
    public var ausnutzung: [Float]
    public var spannung: [Float]
    public var verschiebung: [SIMD3<Float>]
    /// Stufe 4: Rechenverfahren ("ccx"), nil bei Stufe 3.
    public var verfahren: String? = nil
    /// Stufe 4: Namen der Zusatzwerte in der Reihenfolge der Nutzlast (aus `StatikFeldWert.zusatz`).
    public var zusatzNamen: [String] = []
    /// Stufe 4: Zusatzwerte je Punkt (Kontaktdruck N/mm², plastische Dehnung dimensionslos, Klaffen und Schlupf mm).
    public var zusatz: [String: [Float]] = [:]
    /// Stufe 4: größter Wert je Zusatzname (aus dem Kopf, sonst aus den Werten).
    public var zusatzMax: [String: Double] = [:]

    public var key: String { Self.key(szenario, teil) }
    public static func key(_ szenario: String, _ teil: String) -> String { szenario + "\u{1F}" + teil }

    /// Größter Wert eines Zusatzwerts (nil, wenn das Feld ihn nicht trägt).
    public func groesster(_ wert: String) -> Double? {
        guard let w = zusatz[wert] else { return nil }
        if let m = zusatzMax[wert], m.isFinite { return m }
        return Double(w.filter(\.isFinite).max() ?? 0)
    }

    public static func decode(header: Data, payload: Data) throws -> StatikFeld {
        let j = try JSONDecoder().decode(JSONValue.self, from: header)
        guard let n = j["punkte"]?.intValue, let m = j["dreiecke"]?.intValue, n >= 0, m >= 0 else {
            throw StatikFeldFehler.kaputt("punkte oder dreiecke fehlen")
        }
        // Stufe 4 (additiv): je Zusatzname n float32 hinter den bisherigen Werten
        let namen = j["zusatz"]?.arrayValue?.compactMap(\.stringValue) ?? []
        if Set(namen).count != namen.count || namen.contains(StatikFeldWert.ausnutzung) {
            throw StatikFeldFehler.kaputt("Zusatzwerte doppelt: \(namen.joined(separator: ", "))")
        }
        let erwartet = n * 12 + m * 12 + n * 4 + n * 4 + n * 12 + namen.count * n * 4
        guard payload.count == erwartet else {
            throw StatikFeldFehler.kaputt("Nutzlast \(payload.count) Byte, erwartet \(erwartet)")
        }
        var punkte: [SIMD3<Float>] = []
        var dreiecke: [UInt32] = []
        var aus: [Float] = []
        var span: [Float] = []
        var versch: [SIMD3<Float>] = []
        var zusatz: [String: [Float]] = [:]
        payload.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var o = 0
            func f() -> Float {
                let v = Float(bitPattern: UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: o, as: UInt32.self)))
                o += 4
                return v
            }
            func u() -> UInt32 {
                let v = UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: o, as: UInt32.self))
                o += 4
                return v
            }
            punkte.reserveCapacity(n)
            for _ in 0..<n { punkte.append(SIMD3(f(), f(), f())) }
            dreiecke.reserveCapacity(3 * m)
            for _ in 0..<(3 * m) { dreiecke.append(u()) }
            for _ in 0..<n { aus.append(f()) }
            for _ in 0..<n { span.append(f()) }
            for _ in 0..<n { versch.append(SIMD3(f(), f(), f())) }
            for name in namen {
                var w: [Float] = []
                w.reserveCapacity(n)
                for _ in 0..<n { w.append(f()) }
                zusatz[name] = w
            }
        }
        if let groesst = dreiecke.max(), Int(groesst) >= n {
            throw StatikFeldFehler.kaputt("Dreieck zeigt auf Punkt \(groesst), es gibt \(n)")
        }
        let maxKopf = j["zusatz_max"]?.objectValue ?? [:]
        var zusatzMax: [String: Double] = [:]
        for name in namen {
            if let x = maxKopf[name]?.doubleValue, x.isFinite {
                zusatzMax[name] = x
            } else {
                zusatzMax[name] = Double(zusatz[name]?.filter(\.isFinite).max() ?? 0)
            }
        }
        return StatikFeld(
            run: j["run"]?.intValue ?? 0, szenario: j["szenario"]?.stringValue ?? "", teil: j["teil"]?.stringValue ?? "",
            schluessel: j["feld"]?.stringValue ?? "", ziel: j["ziel"]?.doubleValue,
            sicherheit: j["sicherheit"]?.doubleValue,
            ampel: StatikAmpel(rawValue: j["ampel"]?.stringValue ?? "") ?? .grau,
            spannungMax: j["spannung_max"]?.doubleValue, verformungMaxMm: j["verformung_max_mm"]?.doubleValue,
            ueberhoehung: Float(j["ueberhoehung"]?.doubleValue ?? 1), punkte: punkte, dreiecke: dreiecke,
            ausnutzung: aus, spannung: span, verschiebung: versch, verfahren: j["verfahren"]?.stringValue,
            zusatzNamen: namen, zusatz: zusatz, zusatzMax: zusatzMax)
    }
}

/// Wert, nach dem der Farbverlauf eines Felds gefärbt wird: die Ausnutzung (Standard) oder, bei Stufe 4, einer der
/// Zusatzwerte. Namen, Einheiten und Zahlenformat für Oberfläche und Skala.
public enum StatikFeldWert {
    public static let ausnutzung = "ausnutzung"
    /// Zusatzwerte der Stufe 4 in fester Reihenfolge (PROTOCOL.md, STATICS_FIELD `zusatz`).
    public static let zusatz = ["kontaktdruck", "plast_dehnung", "klaffen", "schlupf"]

    public static func titel(_ wert: String) -> String {
        switch wert {
        case ausnutzung: return "Ausnutzung"
        case "kontaktdruck": return "Kontaktdruck"
        case "plast_dehnung": return "plastische Dehnung"
        case "klaffen": return "Klaffen"
        case "schlupf": return "Schlupf"
        default: return wert
        }
    }

    /// Einheit, in der `text` den Wert zeigt (plastische Dehnung in Prozent).
    public static func einheit(_ wert: String) -> String {
        switch wert {
        case "kontaktdruck": return "N/mm²"
        case "plast_dehnung": return "%"
        case "klaffen", "schlupf": return "mm"
        default: return ""
        }
    }

    /// Zahl ohne Einheit, mit so vielen Nachkommastellen, dass kleine Werte lesbar bleiben, ohne Nullen am Ende
    /// (plastische Dehnung in %): 6,5 · 0,4 · 0,08 · 0,004.
    public static func zahl(_ wert: String, _ x: Double) -> String {
        let v = wert == "plast_dehnung" ? x * 100 : x
        let a = abs(v)
        let stellen: Int
        if a == 0 || a >= 100 {
            stellen = 0
        } else if a >= 1 {
            stellen = 1
        } else if a >= 0.1 {
            stellen = 2
        } else if a >= 0.01 {
            stellen = 3
        } else {
            stellen = 4
        }
        var s = KevFormat.number(v, digits: stellen)
        if s.contains(",") {
            while s.hasSuffix("0") { s.removeLast() }
            if s.hasSuffix(",") { s.removeLast() }
        }
        return s
    }

    /// Zahl mit Einheit, z. B. "6,5 N/mm²", "0,40 %", "0,08 mm".
    public static func text(_ wert: String, _ x: Double) -> String {
        let e = einheit(wert)
        return e.isEmpty ? zahl(wert, x) : "\(zahl(wert, x)) \(e)"
    }
}

/// Körper für den Viewport aus einem Feld: der Farbverlauf als Bänder gleicher Ausnutzung (je Band ein Körper mit
/// einer Farbe, Grenzen genau auf den Höhenlinien, flach schattiert, darum klar abgesetzt wie in FEM-Programmen) und
/// die überhöhte Verformung als durchscheinender Geist. Rein, testbar, ohne Szene.
public enum StatikFeldGeometrie {
    /// Bandbreite der Ausnutzung: 0,1 von 0 bis 2 (darüber rot wie 2).
    public static let bandbreite: Float = 0.1
    public static let baender = 20
    /// Höchstens so viele Dreiecke je Körper (AP0: Körper über 16 000 Dreiecke aufteilen).
    static let maxDreiecke = 16_000

    /// Band eines Werts (0 …  baender − 1).
    public static func band(_ a: Float) -> Int {
        let x = a.isFinite ? max(0, a) : 2
        return min(Int(x / bandbreite), baender - 1)
    }

    /// Werte je Punkt auf der Skala der Ausnutzung (0 … 2): die Ausnutzung selbst oder, für einen Zusatzwert der Stufe 4,
    /// 2 · Wert / größter Wert (größter Wert 0: alles 0), damit dieselben Bänder und Farben gelten. `groesster` setzt
    /// den Bezug für mehrere Felder auf einer gemeinsamen Skala (Standard: der größte Wert dieses Felds). Trägt das Feld
    /// den Zusatzwert nicht, bleibt es bei der Ausnutzung.
    public static func skalenwerte(_ f: StatikFeld, wert: String, groesster: Double? = nil) -> [Float] {
        guard wert != StatikFeldWert.ausnutzung, let w = f.zusatz[wert], w.count == f.ausnutzung.count else {
            return f.ausnutzung
        }
        let m = Float(groesster ?? f.groesster(wert) ?? 0)
        guard m.isFinite, m > 0 else { return Array(repeating: 0, count: w.count) }
        return w.map { $0.isFinite ? 2 * max($0, 0) / m : 0 }
    }

    /// Bänder des Felds als Körper; `id` unterscheidet mehrere Felder in derselben Szene. `wert`: Ausnutzung (Standard)
    /// oder ein Zusatzwert der Stufe 4, abgebildet wie in `skalenwerte`.
    public static func farbverlauf(
        _ f: StatikFeld, id: String, wert: String = StatikFeldWert.ausnutzung, groesster: Double? = nil
    ) -> [ViewportBody] {
        var soup = [[Float]](repeating: [], count: baender)
        let p = f.punkte, a = skalenwerte(f, wert: wert, groesster: groesster)
        let n = f.dreiecke.count / 3
        for t in 0..<n {
            let i0 = Int(f.dreiecke[3 * t]), i1 = Int(f.dreiecke[3 * t + 1]), i2 = Int(f.dreiecke[3 * t + 2])
            let q = [p[i0], p[i1], p[i2]]
            let v = [klemme(a[i0]), klemme(a[i1]), klemme(a[i2])]
            var nrm = simd_cross(q[1] - q[0], q[2] - q[0])
            let l = simd_length(nrm)
            if l < 1e-12 { continue }
            nrm /= l
            let b0 = band(v.min()!), b1 = band(v.max()!)
            if b0 == b1 {
                anhaengen(&soup[b0], [q[0], q[1], q[2]], nrm)
                continue
            }
            for b in b0...b1 {
                let lo = Float(b) * bandbreite
                let hi = b == baender - 1 ? Float.greatestFiniteMagnitude : Float(b + 1) * bandbreite
                var poly = Array(zip(q, v))
                poly = schneide(poly, grenze: lo, oben: true)
                poly = schneide(poly, grenze: hi, oben: false)
                guard poly.count >= 3 else { continue }
                for k in 1..<(poly.count - 1) {
                    anhaengen(&soup[b], [poly[0].0, poly[k].0, poly[k + 1].0], nrm)
                }
            }
        }
        var out: [ViewportBody] = []
        for (b, vd) in soup.enumerated() where !vd.isEmpty {
            let mitte = (Double(b) + 0.5) * Double(bandbreite)
            let farbe = SIMD4(StatikGeometrie.farbe(mitte), 1)
            out += zerlege(vd, id: "\(StatikGeometrie.praefix)f\(id)\u{1F}\(b)", farbe: farbe)
        }
        return out
    }

    /// Verformte Oberfläche (Punkte + Verschiebung × Überhöhung) als Geist, jedes Dreieck um `einzug` nach innen
    /// versetzt: Wo sich nichts bewegt (am Lager), liegt der Geist knapp unter dem Farbverlauf statt mit ihm zu
    /// flimmern.
    public static func verformung(_ f: StatikFeld, id: String) -> [ViewportBody] {
        let u = max(f.ueberhoehung, 1)
        let q = zip(f.punkte, f.verschiebung).map { $0 + $1 * u }
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for p in f.punkte {
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
        }
        let einzug = f.punkte.isEmpty ? 0 : max(0.2, 0.004 * simd_reduce_max(hi - lo))
        var vd: [Float] = []
        vd.reserveCapacity(f.dreiecke.count * 6)
        for t in 0..<(f.dreiecke.count / 3) {
            let a = q[Int(f.dreiecke[3 * t])], b = q[Int(f.dreiecke[3 * t + 1])], c = q[Int(f.dreiecke[3 * t + 2])]
            var nrm = simd_cross(b - a, c - a)
            let l = simd_length(nrm)
            if l < 1e-12 { continue }
            nrm /= l
            let d = -nrm * einzug
            anhaengen(&vd, [a + d, b + d, c + d], nrm)
        }
        return zerlege(vd, id: "\(StatikGeometrie.praefix)g\(id)", farbe: PartBodies.linear(StatikGeometrie.geist))
    }

    static func klemme(_ x: Float) -> Float { x.isFinite ? min(max(x, 0), 2.5) : 2.5 }

    static func anhaengen(_ vd: inout [Float], _ q: [SIMD3<Float>], _ n: SIMD3<Float>) {
        for p in q { vd += [p.x, p.y, p.z, n.x, n.y, n.z] }
    }

    /// Sutherland-Hodgman an der Höhenlinie `grenze` des linear interpolierten Werts: behält v ≥ grenze (`oben`) bzw.
    /// v ≤ grenze.
    static func schneide(_ poly: [(SIMD3<Float>, Float)], grenze: Float, oben: Bool) -> [(SIMD3<Float>, Float)] {
        guard !poly.isEmpty else { return [] }
        func drin(_ v: Float) -> Bool { oben ? v >= grenze : v <= grenze }
        var out: [(SIMD3<Float>, Float)] = []
        for i in poly.indices {
            let a = poly[i], b = poly[(i + 1) % poly.count]
            let ia = drin(a.1), ib = drin(b.1)
            if ia { out.append(a) }
            if ia != ib {
                let t = (grenze - a.1) / (b.1 - a.1)
                out.append((a.0 + (b.0 - a.0) * t, grenze))
            }
        }
        return out
    }

    /// Dreieckssuppe in Körper mit höchstens `maxDreiecke` Dreiecken.
    static func zerlege(_ vd: [Float], id: String, farbe: SIMD4<Float>) -> [ViewportBody] {
        let proDreieck = 18
        let n = vd.count / proDreieck
        var out: [ViewportBody] = []
        var start = 0
        var teil = 0
        while start < n {
            let ende = min(n, start + maxDreiecke)
            let stueck = Array(vd[(start * proDreieck)..<(ende * proDreieck)])
            out.append(
                ViewportBody(
                    id: "\(id)\u{1F}\(teil)", vertexData: stueck, indices: (0..<UInt32((ende - start) * 3)).map { $0 },
                    edges: [], color: farbe, roughness: 0.55, isPickable: false))
            start = ende
            teil += 1
        }
        return out
    }
}
