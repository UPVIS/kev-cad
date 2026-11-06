import Foundation

/// V2-5 (delta-1): je Teilname die letzten 4 verschiedenen Inhalte (Kopf und Netz, nach `inhalt`), der gezeigte zuletzt
/// (PROTOCOL.md, „Inhalte je Teil“). Der Kernel führt dieselbe Liste je Verbindung; deshalb bleibt sie stehen, wenn die
/// Szene geleert wird, und geht erst mit PART_REMOVE oder der Verbindung.
public struct TeilInhalte: Sendable {
    private var je: [String: [PartRecord]] = [:]

    public init() {}

    public func hat(_ name: String, _ inhalt: String) -> Bool {
        je[name]?.contains { $0.header.inhalt == inhalt } ?? false
    }

    /// Schlüssel der Inhalte eines Teils, der gezeigte zuletzt.
    public func schluessel(_ name: String) -> [String] { (je[name] ?? []).compactMap(\.header.inhalt) }

    /// PART_UPSERT: Der Inhalt wird der gezeigte, ein fünfter verdrängt den ältesten. Ohne Schlüssel gibt es nichts,
    /// worauf PART_SAME sich beziehen könnte (der Kernel vergisst das Teil dann ebenso).
    public mutating func merken(_ record: PartRecord) {
        guard let inhalt = record.header.inhalt, !inhalt.isEmpty else {
            je[record.name] = nil
            return
        }
        var liste = je[record.name] ?? []
        liste.removeAll { $0.header.inhalt == inhalt }
        liste.append(record)
        if liste.count > LiveGrenzen.teilInhalte { liste.removeFirst(liste.count - LiveGrenzen.teilInhalte) }
        je[record.name] = liste
    }

    /// PART_SAME: Macht den Inhalt zum gezeigten und gibt ihn zurück; nil, wenn er fehlt.
    public mutating func zeigen(_ name: String, _ inhalt: String) -> PartRecord? {
        guard var liste = je[name], let i = liste.firstIndex(where: { $0.header.inhalt == inhalt }) else { return nil }
        let r = liste.remove(at: i)
        liste.append(r)
        je[name] = liste
        return r
    }

    /// Inhalt lesen, ohne die Reihenfolge zu ändern (Versionsbild aus der Szene).
    public func inhalt(_ name: String, _ inhalt: String) -> PartRecord? {
        je[name]?.first { $0.header.inhalt == inhalt }
    }

    /// PART_REMOVE: alle Inhalte des Namens vergessen.
    public mutating func vergessen(_ name: String) { je[name] = nil }

    public mutating func leeren() { je = [:] }
}
