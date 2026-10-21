import Foundation
import simd

/// Deutsche Zahlen- und Einheitenformate für Oberfläche, Statusleiste und Inspektor.
///
/// Alle Längen sind Millimeter, Volumen mm³ (ab 1.000 mm³ als cm³), Massen Gramm (ab 1.000 g als kg),
/// Dauern Millisekunden. Dezimaltrennzeichen ist das Komma, Tausender werden mit Punkt gruppiert.
public enum KevFormat {
    public static let locale = Locale(identifier: "de_DE")

    // MARK: Zahlen

    /// Zahl mit fester Zahl an Nachkommastellen, z. B. `number(1234.5, digits: 1)` → "1.234,5".
    public static func number(_ value: Double, digits: Int) -> String {
        guard value.isFinite else { return "–" }
        let digits = max(0, digits)
        let factor = pow(10, Double(digits))
        var rounded = (value * factor).rounded() / factor
        if rounded == 0 { rounded = 0 }  // keine "-0,0"
        return rounded.formatted(.number.precision(.fractionLength(digits)).locale(locale))
    }

    /// Ganze Zahl mit Tausenderpunkt, z. B. "134.000".
    public static func integer(_ value: Int) -> String {
        value.formatted(.number.locale(locale))
    }

    /// Zählwort mit Einzahl und Mehrzahl, z. B. "1 Teil", "7 Teile", "12.480 Dreiecke".
    public static func count(_ value: Int, one: String, many: String) -> String {
        "\(integer(value)) \(value == 1 ? one : many)"
    }

    // MARK: Einheiten

    /// Länge in mm, z. B. "12,5 mm".
    public static func mm(_ value: Double, digits: Int = 1) -> String {
        "\(number(value, digits: digits)) mm"
    }

    /// Hüllmaße L × B × H aus einem Hüllquader, z. B. "120,0 × 80,0 × 5,0 mm".
    public static func dimensions(min: SIMD3<Float>, max: SIMD3<Float>, digits: Int = 1) -> String {
        let size = max - min
        return dimensions(SIMD3<Double>(Double(size.x), Double(size.y), Double(size.z)), digits: digits)
    }

    public static func dimensions(_ size: SIMD3<Double>, digits: Int = 1) -> String {
        "\(number(size.x, digits: digits)) × \(number(size.y, digits: digits)) × \(number(size.z, digits: digits)) mm"
    }

    /// Volumen: unter 1.000 mm³ in mm³, sonst in cm³ ("850,0 mm³", "4,76 cm³", "128,6 cm³", "48.000 cm³").
    public static func volume(mm3 value: Double) -> String {
        guard value.isFinite else { return "–" }
        if abs(value) < 1000 { return "\(number(value, digits: 1)) mm³" }
        let cm3 = value / 1000
        let digits = abs(cm3) < 10 ? 2 : (abs(cm3) < 1000 ? 1 : 0)
        return "\(number(cm3, digits: digits)) cm³"
    }

    /// Flächeninhalt: unter 10.000 mm² in mm², sonst in cm².
    public static func area(mm2 value: Double) -> String {
        guard value.isFinite else { return "–" }
        if abs(value) < 10_000 { return "\(number(value, digits: 1)) mm²" }
        return "\(number(value / 100, digits: 1)) cm²"
    }

    /// Masse: unter 1.000 g in g, sonst in kg ("7,25 g", "128,6 g", "1,30 kg", "24,5 kg").
    public static func mass(grams value: Double) -> String {
        guard value.isFinite else { return "–" }
        if abs(value) < 1000 {
            return "\(number(value, digits: abs(value) < 10 ? 2 : 1)) g"
        }
        let kg = value / 1000
        return "\(number(kg, digits: abs(kg) < 10 ? 2 : 1)) kg"
    }

    /// Winkel in Grad mit zwei Nachkommastellen, z. B. "90,00°".
    public static func angle(_ degrees: Double) -> String {
        "\(number(degrees, digits: 2))°"
    }

    /// Anteil 0…1 als Prozent, z. B. "40 %".
    public static func percent(_ fraction: Double) -> String {
        "\(number(fraction * 100, digits: 0)) %"
    }

    /// Dauer: "85 ms", "0,4 s", "12 s", "1 min 05 s".
    public static func duration(ms: Int) -> String {
        if ms < 100 { return "\(max(0, ms)) ms" }
        if ms < 10_000 { return "\(number(Double(ms) / 1000, digits: 1)) s" }
        if ms < 59_500 { return "\(number(Double(ms) / 1000, digits: 0)) s" }
        let seconds = Int((Double(ms) / 1000).rounded())
        return "\(seconds / 60) min \(String(format: "%02d", seconds % 60)) s"
    }

    /// Punkt in Weltkoordinaten, z. B. "x 12,000 · y 4,500 · z 0,000 mm".
    public static func point(_ p: SIMD3<Float>, digits: Int = 3) -> String {
        "x \(number(Double(p.x), digits: digits)) · y \(number(Double(p.y), digits: digits)) · "
            + "z \(number(Double(p.z), digits: digits)) mm"
    }

    // MARK: Datum und Pfade

    /// Datum für die Liste „Zuletzt geöffnet“: "Heute, 14:32", "Gestern, 09:10", "Montag, 10:00", "12.10.2026".
    public static func recentDate(_ date: Date, now: Date = Date(), calendar: Calendar = .current) -> String {
        func format(_ pattern: String) -> String {
            let formatter = DateFormatter()
            formatter.locale = locale
            formatter.timeZone = calendar.timeZone
            formatter.dateFormat = pattern
            return formatter.string(from: date)
        }
        let days = calendar.dateComponents(
            [.day], from: calendar.startOfDay(for: date), to: calendar.startOfDay(for: now)
        ).day ?? 0
        switch days {
        case 0: return "Heute, \(format("HH:mm"))"
        case 1: return "Gestern, \(format("HH:mm"))"
        case 2...6: return format("EEEE, HH:mm")
        default: return format("dd.MM.yyyy")
        }
    }

    /// Pfad mit "~" statt Benutzerordner.
    public static func abbreviatedPath(_ path: String, home: String = NSHomeDirectory()) -> String {
        let home = home.hasSuffix("/") ? String(home.dropLast()) : home
        guard !home.isEmpty else { return path }
        if path == home { return "~" }
        if path.hasPrefix(home + "/") { return "~" + path.dropFirst(home.count) }
        return path
    }

    // MARK: Messwerte

    /// Ein Wert aus `SelectionItem.values` oder `MeasurementItem.values` mit deutscher Bezeichnung.
    public struct LabeledValue: Equatable, Sendable, Identifiable {
        public var key: String
        public var label: String
        public var value: String
        public var id: String { key }
    }

    /// Reihenfolge bekannter Schlüssel im Inspektor; unbekannte folgen alphabetisch.
    static let valueOrder = [
        "distance", "angle", "length", "diameter", "radius", "area", "perimeter", "volume", "mass", "dx", "dy", "dz",
        "x", "y", "z", "parallel",
    ]

    /// Wandelt ein Wertewörterbuch in eine geordnete Liste mit Bezeichnung und formatiertem Wert.
    public static func labeledValues(_ values: [String: Double]) -> [LabeledValue] {
        values.keys.sorted { a, b in
            let ia = valueOrder.firstIndex(of: a) ?? Int.max
            let ib = valueOrder.firstIndex(of: b) ?? Int.max
            return ia == ib ? a < b : ia < ib
        }.map { labeledValue(key: $0, values[$0] ?? 0) }
    }

    public static func labeledValue(key: String, _ value: Double) -> LabeledValue {
        let (label, text): (String, String)
        switch key {
        case "distance": (label, text) = ("Abstand", mm(value, digits: 3))
        case "length": (label, text) = ("Länge", mm(value, digits: 3))
        case "radius": (label, text) = ("Radius", mm(value, digits: 3))
        case "diameter": (label, text) = ("Durchmesser", mm(value, digits: 3))
        case "perimeter": (label, text) = ("Umfang", mm(value, digits: 3))
        case "area": (label, text) = ("Fläche", area(mm2: value))
        case "angle": (label, text) = ("Winkel", angle(value))
        case "volume": (label, text) = ("Volumen", volume(mm3: value))
        case "mass": (label, text) = ("Masse", mass(grams: value))
        case "dx": (label, text) = ("Δx", mm(value, digits: 3))
        case "dy": (label, text) = ("Δy", mm(value, digits: 3))
        case "dz": (label, text) = ("Δz", mm(value, digits: 3))
        case "x": (label, text) = ("X", mm(value, digits: 3))
        case "y": (label, text) = ("Y", mm(value, digits: 3))
        case "z": (label, text) = ("Z", mm(value, digits: 3))
        case "parallel": (label, text) = ("Parallel", value != 0 ? "ja" : "nein")
        default: (label, text) = (key, number(value, digits: 3))
        }
        return LabeledValue(key: key, label: label, value: text)
    }
}
