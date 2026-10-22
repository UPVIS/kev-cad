import Foundation

// Formate der Druckvorschau für Panel, Plattenansicht und Bericht: Zeiten als „6 h 8 min“, Gewichte, Längen und
// Kosten deutsch formatiert und sinnvoll gerundet, dazu die Bezeichnungen der Einstellungen.

public enum DruckFormat {
    // MARK: Zahlen

    /// Druckzeit: „< 1 min“, „45 min“, „2 h“, „6 h 8 min“ (auch über 24 h in Stunden, wie im Slicer üblich).
    public static func zeit(_ sekunden: Double) -> String {
        guard sekunden.isFinite, sekunden > 0 else { return "0 min" }
        let minuten = Int((sekunden / 60).rounded())
        if minuten == 0 { return "< 1 min" }
        let h = minuten / 60, m = minuten % 60
        if h == 0 { return "\(m) min" }
        if m == 0 { return "\(KevFormat.integer(h)) h" }
        return "\(KevFormat.integer(h)) h \(m) min"
    }

    /// Filamentgewicht: unter 10 g eine Nachkommastelle, bis 1 kg ganze Gramm, darüber kg mit zwei Stellen.
    public static func gramm(_ g: Double) -> String {
        guard g.isFinite else { return "–" }
        if abs(g) < 10 { return "\(KevFormat.number(g, digits: 1)) g" }
        if abs(g) < 999.5 { return "\(KevFormat.number(g, digits: 0)) g" }
        return "\(KevFormat.number(g / 1000, digits: 2)) kg"
    }

    /// Filamentlänge: unter 10 m zwei Nachkommastellen, bis 1 km eine, darüber ganze Meter.
    public static func meter(_ m: Double) -> String {
        guard m.isFinite else { return "–" }
        if abs(m) < 10 { return "\(KevFormat.number(m, digits: 2)) m" }
        if abs(m) < 1000 { return "\(KevFormat.number(m, digits: 1)) m" }
        return "\(KevFormat.number(m, digits: 0)) m"
    }

    public static func euro(_ v: Double) -> String { KevFormat.euro(v) }

    /// Anteil 0…1 als Prozent: ganze Prozent, unter 10 % mit einer Stelle, wenn sie nicht null ist („7,5 %“).
    public static func prozent(_ anteil: Double) -> String {
        guard anteil.isFinite else { return "–" }
        let p = anteil * 100
        if abs(p) < 10 && abs(p - p.rounded()) > 0.05 { return "\(KevFormat.number(p, digits: 1)) %" }
        return "\(KevFormat.number(p, digits: 0)) %"
    }

    /// Relative Änderung mit Vorzeichen: „+12 %“, „−3 %“, „±0 %“.
    public static func aenderung(_ relativ: Double) -> String {
        guard relativ.isFinite else { return "–" }
        let p = (relativ * 100).rounded()
        if p == 0 { return "±0 %" }
        return (p > 0 ? "+" : "−") + "\(KevFormat.number(abs(p), digits: 0)) %"
    }

    /// Schichthöhe: „0,2 mm“, „0,16 mm“.
    public static func schicht(_ mm: Double) -> String { "\(KevFormat.compact(mm, maxDigits: 2)) mm" }

    /// Abmessung „120 × 80 mm“.
    public static func flaeche(_ b: Double, _ t: Double) -> String {
        "\(KevFormat.compact(b, maxDigits: 0)) × \(KevFormat.compact(t, maxDigits: 0)) mm"
    }

    /// Teilname für die Anzeige: letzter Pfadteil ohne „(Druck)“ („Kugelschieber/Fangrolle (Druck)“ → „Fangrolle“).
    public static func teilname(_ name: String) -> String {
        var n = name.split(separator: "/").last.map(String.init) ?? name
        if n.hasSuffix(" (Druck)") { n = String(n.dropLast(8)) }
        return n.isEmpty ? name : n
    }

    // MARK: Bezeichnungen

    /// Zwecke laut Vertrag in der Reihenfolge der Auswahl.
    public static let zwecke = ["zier", "funktion", "tragend", "bewegt", "aussen"]

    public static func zweck(_ z: String?) -> String {
        switch z {
        case "zier": return "Zierteil"
        case "funktion": return "Funktionsteil"
        case "tragend": return "Tragend"
        case "bewegt": return "Bewegt"
        case "aussen": return "Außen"
        case nil: return "–"
        case let z?: return z.prefix(1).uppercased() + z.dropFirst()
        }
    }

    public static func zweckBeschreibung(_ z: String) -> String {
        switch z {
        case "zier": return "Sieht gut aus, trägt nichts: wenig Wände, wenig Füllung"
        case "funktion": return "Normale Beanspruchung: Standardwerte"
        case "tragend": return "Trägt Last: mehr Wände, dichtere Füllung, Last längs der Schichten"
        case "bewegt": return "Gleitet oder dreht sich: glatte Flächen, maßhaltig, verschleißfest"
        case "aussen": return "Draußen: UV und Wetter, dichte Hülle"
        default: return ""
        }
    }

    /// Füllmuster, die das Panel anbietet (Schlüssel wie in Bambu Studio).
    public static let muster = ["gyroid", "grid", "cubic", "honeycomb", "triangles", "crosshatch", "lightning",
                                "rectilinear", "zigzag", "line", "concentric"]

    public static func muster(_ m: String?) -> String {
        switch m?.lowercased() {
        case "gyroid": return "Gyroid"
        case "grid": return "Gitter"
        case "cubic": return "Kubisch"
        case "adaptivecubic": return "Adaptiv kubisch"
        case "honeycomb", "3dhoneycomb": return "Waben"
        case "triangles": return "Dreiecke"
        case "tri-hexagon": return "Dreieck-Sechseck"
        case "crosshatch": return "Kreuzschraffur"
        case "lightning": return "Blitz"
        case "rectilinear", "alignedrectilinear": return "Geradlinig"
        case "zigzag", "zig-zag": return "Zickzack"
        case "line": return "Linien"
        case "concentric": return "Konzentrisch"
        case "hilbertcurve": return "Hilbert-Kurve"
        case nil: return "–"
        case let m?: return m.prefix(1).uppercased() + m.dropFirst()
        }
    }

    public static let stuetzenArten = ["keine", "baum", "normal"]

    public static func stuetzen(_ s: String?) -> String {
        switch s?.lowercased() {
        case "keine", "aus", "none": return "Keine"
        case "baum", "tree", "tree(auto)": return "Baum"
        case "normal", "normal(auto)", "grid": return "Normal"
        case nil: return "–"
        case let s?: return s.prefix(1).uppercased() + s.dropFirst()
        }
    }

    public static func brim(_ b: Bool?) -> String {
        switch b {
        case true?: return "Brim"
        case false?: return "Kein Brim"
        case nil: return "–"
        }
    }

    public static func waende(_ n: Int) -> String { KevFormat.count(n, one: "Wand", many: "Wände") }

    /// Kurzfassung der Einstellungen: „4 Wände · 25 % Gyroid · Baumstützen · Brim“.
    public static func kurz(_ e: DruckEinstellungen) -> String {
        var t: [String] = []
        if let w = e.waende { t.append(waende(w)) }
        if let f = e.fuellung { t.append(prozent(f) + (e.muster.map { " " + muster($0) } ?? "")) }
        switch e.stuetzen?.lowercased() {
        case "baum", "tree", "tree(auto)": t.append("Baumstützen")
        case "normal", "normal(auto)", "grid": t.append("Stützen")
        default: break
        }
        if e.brim == true { t.append("Brim") }
        return t.joined(separator: " · ")
    }

    /// Feste Vorgaben nach Quelle: „Von Kevin: Wände, Zweck“, „Vom Agenten: Füllung“.
    public static func vorgaben(_ v: [String: DruckQuelle]) -> [String] {
        [DruckQuelle.kevin, .agent].compactMap { q in
            let k = v.filter { $0.value == q }.keys.sorted().map(schluessel)
            guard !k.isEmpty else { return nil }
            return q.titel.prefix(1).uppercased() + q.titel.dropFirst() + ": " + k.joined(separator: ", ")
        }
    }

    /// Titel der Schlüssel in `einstellungen` (für „von Kevin“, Hinweise und den Bericht).
    public static func schluessel(_ k: String) -> String {
        switch k {
        case "schicht_mm": return "Schichthöhe"
        case "waende": return "Wände"
        case "decken": return "Decken"
        case "boeden": return "Böden"
        case "fuellung": return "Füllung"
        case "muster": return "Muster"
        case "stuetzen": return "Stützen"
        case "brim": return "Brim"
        case "ausrichtung": return "Ausrichtung"
        case "zweck": return "Zweck"
        default: return k
        }
    }
}
