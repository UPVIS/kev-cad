import Foundation

// V2-10 (Kevin, 06.11.2026: „Auch die Zeichnungen sollen dann immer kontextbasiert switchen, während man erklärt“):
// Welches Blatt zu den Teilen passt, von denen gerade die Rede ist. Reine Rechnung, damit sie testbar bleibt; wann sie
// greift (Auswahl, Kamerabefehl des Agenten, Zeigen beim Sprechen), steht in AppController+Kontext.swift.

public enum Blattwahl {
    /// Blatt für diese Teile (volle Teilnamen wie „Rahmen/Rohr 2“), nil, wenn keins passt.
    ///
    /// - Ein Teil (oder mehrere gleiche einer Stücklistenposition): sein Teileblatt. Gleiche Teile teilen sich ein Blatt,
    ///   das nur das erste nennt; `gleiche` sind die Teile je Stücklistenposition.
    /// - Mehrere verschiedene Teile: die engste Baugruppe, die alle enthält (Teile- oder Gruppennamen im Blatt).
    /// - Sonst der Zusammenbau: Er zeigt jedes Teil im Zusammenhang (auch Zukaufteile ohne eigenes Blatt).
    public static func blatt(fuer teile: [String], in blaetter: [BlattEintrag], gleiche: [[String]] = []) -> String? {
        let auswahl = Set(teile)
        guard !auswahl.isEmpty, !blaetter.isEmpty else { return nil }
        func geschwister(_ t: String) -> Set<String> {
            Set(gleiche.first { $0.contains(t) } ?? [t]).union([t])
        }
        // Alle gewählten Teile gehören zu einer Position: Teileblatt
        let erste = geschwister(auswahl.first!)
        if auswahl.allSatisfy({ erste.contains($0) }) {
            if let b = blaetter.first(where: { $0.inhaltArt == "teil" && !erste.isDisjoint(with: $0.teile) }) {
                return b.id
            }
        }
        // Engste Baugruppe, die alle Teile enthält
        func enthaelt(_ wahl: String, _ teil: String) -> Bool { teil == wahl || teil.hasPrefix(wahl + "/") }
        let gruppen = blaetter.filter { b in
            b.inhaltArt == "baugruppe" && !b.teile.isEmpty
                && auswahl.allSatisfy { t in b.teile.contains { enthaelt($0, t) } }
        }
        func tiefe(_ b: BlattEintrag) -> Int {
            b.teile.map { $0.split(separator: "/").count }.min() ?? 0
        }
        if let g = gruppen.max(by: { (tiefe($0), -$0.teile.count) < (tiefe($1), -$1.teile.count) }) { return g.id }
        return blaetter.first { $0.inhaltArt == "zusammenbau" }?.id
    }
}
