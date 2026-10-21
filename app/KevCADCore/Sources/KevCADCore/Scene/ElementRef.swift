import Foundation

/// Referenz auf ein Teil oder ein Element darin (PROTOCOL.md, Abschnitt Referenzen):
/// `Halter/Lasche`, `Halter/Lasche#f12`, `Halter/Lasche#e3`, `Halter/Lasche#v2`.
public struct ElementRef: Hashable, Sendable, CustomStringConvertible {
    public enum Kind: String, Sendable {
        case part, face, edge, vertex

        var letter: String {
            switch self {
            case .part: return ""
            case .face: return "f"
            case .edge: return "e"
            case .vertex: return "v"
            }
        }
    }

    public var part: String
    public var kind: Kind
    public var index: Int

    public init(part: String, kind: Kind = .part, index: Int = 0) {
        self.part = part
        self.kind = kind
        self.index = kind == .part ? 0 : index
    }

    public static func part(_ name: String) -> ElementRef { ElementRef(part: name) }
    public static func face(_ part: String, _ i: Int) -> ElementRef { ElementRef(part: part, kind: .face, index: i) }
    public static func edge(_ part: String, _ i: Int) -> ElementRef { ElementRef(part: part, kind: .edge, index: i) }
    public static func vertex(_ part: String, _ i: Int) -> ElementRef { ElementRef(part: part, kind: .vertex, index: i) }

    /// Text im Protokollformat.
    public var string: String { kind == .part ? part : "\(part)#\(kind.letter)\(index)" }
    public var description: String { string }

    /// Liest eine Referenz. Text ohne gültige Endung `#f…`, `#e…`, `#v…` gilt als Teilname.
    public init?(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return nil }
        if let hash = t.lastIndex(of: "#") {
            let name = String(t[..<hash])
            let suffix = t[t.index(after: hash)...]
            if !name.isEmpty, let letter = suffix.first, let idx = Int(suffix.dropFirst()), idx >= 0,
                suffix.dropFirst().allSatisfy(\.isNumber)
            {
                switch letter {
                case "f": self.init(part: name, kind: .face, index: idx); return
                case "e": self.init(part: name, kind: .edge, index: idx); return
                case "v": self.init(part: name, kind: .vertex, index: idx); return
                default: break
                }
            }
        }
        self.init(part: t)
    }

    /// Dasselbe Teil als Ganzes.
    public var partRef: ElementRef { ElementRef(part: part) }
}
