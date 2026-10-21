import Foundation

/// Ein Knoten im Teilebaum: Gruppe aus dem Pfad ("Halter") oder Teil ("Halter/Lasche"). Ein Name kann beides sein,
/// wenn `show()` sowohl "Halter" als auch "Halter/Lasche" zeigt.
public struct PartTreeNode: Identifiable, Equatable, Sendable {
    /// Vollständiger Pfad, bei Teilen gleich `PartNode.id`.
    public var id: String
    public var name: String
    public var part: PartNode?
    /// `nil` bei Blättern (für `List(children:)`), sonst die Unterknoten.
    public var children: [PartTreeNode]?
    /// Alle Teile im Unterbaum einschließlich des Knotens selbst, in Baumreihenfolge.
    public var partIDs: [String]
    public var visibleCount: Int
    public var triangles: Int

    public var isGroup: Bool { children != nil }
    public var partCount: Int { partIDs.count }
    public var allHidden: Bool { visibleCount == 0 && partCount > 0 }
    public var allVisible: Bool { visibleCount == partCount }
}

/// Baut den Teilebaum aus `PartNode.path`. Ohne Oberfläche, damit testbar.
public enum PartTree {
    /// Baum in der Reihenfolge, in der die Teile zuerst auftauchen (also wie im Modellcode gezeigt).
    public static func build(_ parts: [PartNode]) -> [PartTreeNode] {
        final class Builder {
            var name: String
            var id: String
            var part: PartNode?
            var children: [Builder] = []
            var index: [String: Builder] = [:]

            init(name: String, id: String) {
                self.name = name
                self.id = id
            }

            func child(_ name: String, id: String) -> Builder {
                if let existing = index[name] { return existing }
                let node = Builder(name: name, id: id)
                index[name] = node
                children.append(node)
                return node
            }

            func freeze() -> PartTreeNode {
                let frozen = children.map { $0.freeze() }
                var ids = part.map { [$0.id] } ?? []
                ids += frozen.flatMap(\.partIDs)
                let visible = (part?.visible == true ? 1 : 0) + frozen.reduce(0) { $0 + $1.visibleCount }
                let triangles = (part?.triangles ?? 0) + frozen.reduce(0) { $0 + $1.triangles }
                return PartTreeNode(
                    id: id, name: name, part: part, children: frozen.isEmpty ? nil : frozen, partIDs: ids,
                    visibleCount: visible, triangles: triangles)
            }
        }

        let root = Builder(name: "", id: "")
        for part in parts {
            let path = part.path.isEmpty ? [part.id] : part.path
            var node = root
            for (depth, component) in path.enumerated() {
                node = node.child(component, id: path[0...depth].joined(separator: "/"))
            }
            node.part = part
        }
        return root.children.map { $0.freeze() }
    }

    /// Filtert nach Namen (Groß-/Kleinschreibung egal). Gruppen bleiben stehen, wenn ein Unterknoten passt;
    /// passt die Gruppe selbst, bleibt sie mit allen Unterknoten.
    public static func filter(_ nodes: [PartTreeNode], query: String) -> [PartTreeNode] {
        let query = query.trimmingCharacters(in: .whitespaces)
        guard !query.isEmpty else { return nodes }
        return nodes.compactMap { node in
            if node.name.localizedCaseInsensitiveContains(query) { return node }
            guard let children = node.children else { return nil }
            let kept = filter(children, query: query)
            guard !kept.isEmpty else { return nil }
            var copy = node
            copy.children = kept
            return copy
        }
    }

    /// Alle Knoten-IDs (Gruppen und Teile), z. B. um alles aufzuklappen.
    public static func allIDs(_ nodes: [PartTreeNode]) -> [String] {
        nodes.flatMap { [$0.id] + allIDs($0.children ?? []) }
    }

    /// Sucht einen Knoten nach ID.
    public static func node(_ id: String, in nodes: [PartTreeNode]) -> PartTreeNode? {
        for node in nodes {
            if node.id == id { return node }
            if let found = self.node(id, in: node.children ?? []) { return found }
        }
        return nil
    }

    /// Teilname aus einer Referenz: "Halter/Lasche#f12" → "Halter/Lasche".
    public static func partID(fromRef ref: String) -> String {
        if let hash = ref.firstIndex(of: "#") { return String(ref[..<hash]) }
        return ref
    }

    /// Teilnamen aus Referenzen, ohne Doppelte, in Reihenfolge.
    public static func partIDs(fromRefs refs: [String]) -> [String] {
        var seen: Set<String> = []
        return refs.map(partID(fromRef:)).filter { seen.insert($0).inserted }
    }

    /// Löst Knoten-IDs (auch Gruppen) in die enthaltenen Teile auf.
    public static func expandToParts(_ ids: [String], in nodes: [PartTreeNode]) -> [String] {
        var seen: Set<String> = []
        var result: [String] = []
        for id in ids {
            let parts = node(id, in: nodes)?.partIDs ?? [id]
            for part in parts where seen.insert(part).inserted { result.append(part) }
        }
        return result
    }
}
