import Foundation
import simd

/// Zahlen und Bezeichnungen für die Oberfläche: deutsches Zahlenformat (Komma, Tausenderpunkt), mm und Grad.
public enum GermanFormat {
    private static let locale = Locale(identifier: "de_DE")

    /// `200,0`, `6.000,0`, `-12,500`.
    public static func number(_ value: Double, decimals: Int = 1) -> String {
        let f = NumberFormatter()
        f.locale = locale
        f.numberStyle = .decimal
        f.usesGroupingSeparator = true
        f.minimumFractionDigits = decimals
        f.maximumFractionDigits = decimals
        let v = abs(value) < 0.5 * pow(10, Double(-decimals)) ? 0 : value  // kein "-0,0"
        return f.string(from: NSNumber(value: v)) ?? String(format: "%.\(decimals)f", v)
    }

    public static func mm(_ value: Double, decimals: Int = 3) -> String { "\(number(value, decimals: decimals)) mm" }
    public static func mm2(_ value: Double, decimals: Int = 1) -> String { "\(number(value, decimals: decimals)) mm²" }
    public static func mm3(_ value: Double, decimals: Int = 1) -> String { "\(number(value, decimals: decimals)) mm³" }
    public static func degrees(_ value: Double, decimals: Int = 2) -> String { "\(number(value, decimals: decimals))°" }

    /// Masse in g, ab 1 kg in kg.
    public static func mass(_ grams: Double) -> String {
        grams >= 1000 ? "\(number(grams / 1000, decimals: 3)) kg" : "\(number(grams, decimals: 1)) g"
    }

    /// `(5,0; -10,0; 15,0)`
    public static func point(_ p: SIMD3<Float>, decimals: Int = 1) -> String {
        "(\(number(Double(p.x), decimals: decimals)); \(number(Double(p.y), decimals: decimals)); \(number(Double(p.z), decimals: decimals)))"
    }

    /// `10 × 20 × 30 mm`
    public static func size(_ s: SIMD3<Float>, decimals: Int = 1) -> String {
        let parts = [s.x, s.y, s.z].map { number(Double($0), decimals: decimals) }
        return parts.joined(separator: " × ") + " mm"
    }

    public static func faceType(_ t: String) -> String {
        switch t {
        case "plane": return "Ebene"
        case "cylinder": return "Zylinder"
        case "cone": return "Kegel"
        case "sphere": return "Kugel"
        case "torus": return "Torus"
        case "bspline": return "Freiform"
        default: return "Fläche"
        }
    }

    public static func edgeType(_ t: String) -> String {
        switch t {
        case "line": return "Gerade"
        case "circle": return "Kreis"
        case "ellipse": return "Ellipse"
        case "bspline": return "Freiform"
        default: return "Kante"
        }
    }
}
