import Foundation

// Formate für Stückliste und Lagerkatalog (Phase 2): Euro, Gehrung, Längen und Eingabezahlen.

extension KevFormat {
    /// Betrag in Euro, z. B. "26,96 €".
    public static func euro(_ value: Double) -> String {
        "\(number(value, digits: 2)) €"
    }

    /// Masse in Kilogramm (Stückliste), angezeigt wie im Inspektor: "248,0 g", "2,87 kg", "36,2 kg".
    public static func kg(_ value: Double) -> String {
        mass(grams: value * 1000)
    }

    /// Zahl mit so wenigen Nachkommastellen wie nötig (höchstens `maxDigits`): 33.7 → "33,7", 2 → "2", 6000 → "6.000".
    public static func compact(_ value: Double, maxDigits: Int = 3) -> String {
        guard value.isFinite else { return "–" }
        var digits = 0
        while digits < maxDigits {
            let factor = pow(10, Double(digits))
            if abs((value * factor).rounded() - value * factor) < 1e-6 { break }
            digits += 1
        }
        return number(value, digits: digits)
    }

    /// Länge in mm ohne überflüssige Nachkommastellen: "882 mm", "6.000 mm", "33,7 mm".
    public static func length(_ value: Double) -> String {
        "\(compact(value, maxDigits: 1)) mm"
    }

    /// Gehrung an Anfang und Ende: "–" für gerade Schnitte, sonst "45° / 45°" bzw. "0° / 45°".
    public static func gehrung(_ angles: [Double]) -> String {
        let a = angles.first ?? 0
        let b = angles.count > 1 ? angles[1] : a
        if abs(a) < 1e-9 && abs(b) < 1e-9 { return "–" }
        return "\(compact(a, maxDigits: 1))° / \(compact(b, maxDigits: 1))°"
    }

    /// Zahl für ein Eingabefeld: deutsches Komma, ohne Tausenderpunkt, so kurz wie möglich ("33,7", "6000").
    public static func input(_ value: Double) -> String {
        compact(value, maxDigits: 4).replacingOccurrences(of: ".", with: "")
    }

    /// Liest eine Zahl aus einem Eingabefeld: "33,7", "33.7", "1.234,5", "6000", "  12 mm". Sonst nil.
    public static func parseNumber(_ text: String) -> Double? {
        var t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for unit in ["mm", "kg/m", "€/m²", "€/m", "€/stück", "€/kg", "€", "g/cm³", "%"]
        where t.lowercased().hasSuffix(unit) {
            t = String(t.dropLast(unit.count)).trimmingCharacters(in: .whitespaces)
            break
        }
        t = t.replacingOccurrences(of: " ", with: "")
        guard !t.isEmpty else { return nil }
        if t.contains(",") {
            t = t.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
        }
        guard let d = Double(t), d.isFinite else { return nil }
        return d
    }
}
