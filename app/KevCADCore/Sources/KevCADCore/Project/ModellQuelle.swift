import Foundation

/// Kleine, sichere Änderungen an `model.py` aus der Oberfläche (V2-3, Entscheidung V7: keine Manipulatoren, aber
/// Felder in der Werkstatt und Umbenennen bleiben).
///
/// Geändert wird nur, was sich eindeutig im Text findet: der Vorgabewert eines `param("name", 120)` und Teilnamen, die
/// als Zeichenkette in `show(…, "Gruppe/Teil")`, `verbauen(name=…)` und ähnlichem stehen. Entsteht ein Name im Code
/// (f-String, Schleife), bleibt die Datei unverändert und der Fehler sagt, dass der Agent das übernimmt.
public enum ModellQuelle {
    public enum Fehler: Error, Equatable, LocalizedError, Sendable {
        /// `param("name", Zahl)` steht nicht (oder nicht als einfache Zahl) in model.py.
        case parameterNichtGefunden(String)
        /// Der Parameter steht mehrfach da; welcher gemeint ist, bleibt offen.
        case parameterMehrdeutig(String, Int)
        /// Der Name steht nicht als Zeichenkette in model.py (er entsteht im Code).
        case nameNichtGefunden(String)
        case ungueltigerName(String)
        case ungueltigeZahl(String)

        public var errorDescription: String? {
            switch self {
            case .parameterNichtGefunden(let n):
                return "„\(n)“ steht in model.py nicht als einfache Zahl. Sag dem Agenten, welchen Wert du willst."
            case .parameterMehrdeutig(let n, let k):
                return "„\(n)“ steht \(k)-mal in model.py. Sag dem Agenten, welchen Wert du willst."
            case .nameNichtGefunden(let n):
                return "„\(n)“ entsteht im Code und steht so nicht in model.py. Sag dem Agenten, wie es heißen soll."
            case .ungueltigerName(let n):
                return "„\(n)“ geht als Name nicht: ohne Schrägstrich und Anführungszeichen."
            case .ungueltigeZahl(let t):
                return "„\(t)“ ist keine Zahl."
            }
        }
    }

    // MARK: Parameter

    /// Setzt den Vorgabewert von `param("name", …)` auf `wert`. Nur bei genau einem Aufruf mit einer einfachen Zahl.
    public static func setzeParameter(_ code: String, name: String, wert: Double) -> Result<String, Fehler> {
        let muster = #"param\(\s*(["'])"# + NSRegularExpression.escapedPattern(for: name)
            + #"\1\s*,\s*([-+]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(?=\s*[,)])"#
        guard let re = try? NSRegularExpression(pattern: muster) else { return .failure(.parameterNichtGefunden(name)) }
        let ns = code as NSString
        let treffer = re.matches(in: code, range: NSRange(location: 0, length: ns.length))
        guard !treffer.isEmpty else { return .failure(.parameterNichtGefunden(name)) }
        guard treffer.count == 1, let t = treffer.first else {
            return .failure(.parameterMehrdeutig(name, treffer.count))
        }
        return .success(ns.replacingCharacters(in: t.range(at: 2), with: zahlText(wert)))
    }

    /// Zahl so, wie sie in Python stehen soll: ganze Zahlen ohne Nachkommastellen, sonst bis zu vier Stellen.
    public static func zahlText(_ wert: Double) -> String {
        if wert == wert.rounded(), abs(wert) < 1e15 { return String(Int64(wert)) }
        var t = String(format: "%.4f", wert)
        while t.hasSuffix("0") { t.removeLast() }
        if t.hasSuffix(".") { t.removeLast() }
        return t
    }

    /// Liest eine Eingabe wie „1040“, „12,5“, „12.5 mm“ oder „Ø 100“.
    public static func zahl(aus eingabe: String) -> Double? {
        var t = eingabe.trimmingCharacters(in: .whitespacesAndNewlines)
        for weg in ["Ø", "mm", "kg", "°", "\u{00A0}"] { t = t.replacingOccurrences(of: weg, with: "") }
        t = t.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: " ", with: "")
        if t.contains(",") {
            t = t.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
        }
        guard !t.isEmpty, let d = Double(t), d.isFinite else { return nil }
        return d
    }

    // MARK: Namen

    /// Benennt ein Teil (`gruppe == false`, ganzer Name wie "Rahmen/Querstrebe") oder eine Gruppe (alle Namen, die mit
    /// "Rahmen/" beginnen) um. `neuerLetzterTeil` ersetzt nur den letzten Bestandteil des Namens. Gibt den neuen Code
    /// und die Zahl der geänderten Stellen zurück.
    public static func benenneUm(_ code: String, name: String, gruppe: Bool, neuerLetzterTeil: String)
        -> Result<(code: String, stellen: Int, neuerName: String), Fehler>
    {
        let neu = neuerLetzterTeil.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !neu.isEmpty, !neu.contains("/"), !neu.contains("\""), !neu.contains("'"), !neu.contains("\\"),
              !neu.contains("\n")
        else { return .failure(.ungueltigerName(neu)) }
        var teile = name.split(separator: "/").map(String.init)
        guard !teile.isEmpty else { return .failure(.nameNichtGefunden(name)) }
        teile[teile.count - 1] = neu
        let neuerName = teile.joined(separator: "/")
        let alt = NSRegularExpression.escapedPattern(for: name)
        // In einfachen oder doppelten Anführungszeichen: genau der Name bzw. der Name als Anfang eines Pfads
        let muster = gruppe ? #"(["'])"# + alt + #"(/[^"'\n]*)\1"# : #"(["'])"# + alt + #"\1"#
        guard let re = try? NSRegularExpression(pattern: muster) else { return .failure(.nameNichtGefunden(name)) }
        let ns = code as NSString
        let treffer = re.matches(in: code, range: NSRange(location: 0, length: ns.length))
        guard !treffer.isEmpty else { return .failure(.nameNichtGefunden(name)) }
        let ersatz = gruppe ? "$1" + NSRegularExpression.escapedTemplate(for: neuerName) + "$2$1"
            : "$1" + NSRegularExpression.escapedTemplate(for: neuerName) + "$1"
        let ergebnis = re.stringByReplacingMatches(
            in: code, range: NSRange(location: 0, length: ns.length), withTemplate: ersatz)
        return .success((ergebnis, treffer.count, neuerName))
    }

    // MARK: Datei

    /// Schreibt model.py ganz oder gar nicht (temporäre Datei, dann ersetzen), wie der Kernel bei `model_write`.
    public static func schreiben(_ code: String, nach datei: URL) throws {
        let tmp = datei.deletingLastPathComponent().appendingPathComponent(".\(datei.lastPathComponent).app.tmp")
        try Data(code.utf8).write(to: tmp)
        _ = try FileManager.default.replaceItemAt(datei, withItemAt: tmp)
    }
}
