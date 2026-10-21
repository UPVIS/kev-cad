import AppKit
import KevCADCore
import SwiftUI

/// Teilebaum in der Seitenleiste, aufgebaut aus `PartNode.path`.
///
/// Klick wählt aus (`select`), Doppelklick fährt die Kamera hin (`focus`), Auge blendet ein und aus
/// (`setVisibility`), Kontextmenü: Einblenden, Ausblenden, Isolieren, Auf Teil zoomen.
struct PartTreeView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    @State private var collapsed: Set<String> = []

    var body: some View {
        let tree = PartTree.build(model.parts)
        let nodes = PartTree.filter(tree, query: state.searchText)
        List(selection: selection(in: tree)) {
            if !nodes.isEmpty {
                Section {
                    ForEach(nodes) { node in
                        PartTreeNodeView(node: node, model: model, collapsed: $collapsed, filtering: isFiltering)
                    }
                } header: {
                    HStack {
                        Text("Baugruppe")
                        Spacer()
                        Text(KevFormat.integer(model.parts.count))
                            .monospacedDigit()
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .contextMenu(forSelectionType: String.self) { ids in
            contextMenu(PartTree.expandToParts(Array(ids), in: tree))
        } primaryAction: { ids in
            let parts = PartTree.expandToParts(Array(ids), in: tree)
            if !parts.isEmpty { model.actions?.focus(on: parts) }
        }
        .searchable(text: $state.searchText, placement: .sidebar, prompt: "Teile filtern")
        .overlay { emptyState(nodes: nodes) }
        .safeAreaInset(edge: .bottom, spacing: 0) { footer }
    }

    private var isFiltering: Bool { !state.searchText.trimmingCharacters(in: .whitespaces).isEmpty }

    /// Auswahl im Baum = Teile der Auswahl im Modell; eine Gruppe anklicken wählt ihre Teile.
    private func selection(in tree: [PartTreeNode]) -> Binding<Set<String>> {
        Binding(
            get: { Set(model.selectedPartIDs) },
            set: { ids in
                let parts = PartTree.expandToParts(Array(ids), in: tree)
                guard Set(parts) != Set(model.selectedPartIDs) else { return }
                model.actions?.select(parts)
            })
    }

    @ViewBuilder
    private func contextMenu(_ parts: [String]) -> some View {
        if parts.isEmpty {
            Button("Alles einblenden") { model.actions?.showAll() }
        } else {
            Button("Einblenden") { model.actions?.setVisibility(parts, visible: true) }
            Button("Ausblenden") { model.actions?.setVisibility(parts, visible: false) }
            Button("Isolieren") { model.actions?.isolate(parts) }
            Divider()
            Button(parts.count == 1 ? "Auf Teil zoomen" : "Auf Teile zoomen") { model.actions?.focus(on: parts) }
            Divider()
            Button("Alles einblenden") { model.actions?.showAll() }
            Button(parts.count == 1 ? "Namen kopieren" : "Namen kopieren (\(parts.count))") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(parts.joined(separator: "\n"), forType: .string)
            }
        }
    }

    @ViewBuilder
    private func emptyState(nodes: [PartTreeNode]) -> some View {
        if model.parts.isEmpty {
            if model.isRunning {
                ContentUnavailableView {
                    Label("Teile entstehen …", systemImage: "cube.transparent")
                } description: {
                    Text("Jedes show() in model.py erscheint hier, sobald es gerechnet ist.")
                }
            } else {
                ContentUnavailableView {
                    Label("Noch keine Teile", systemImage: "cube.transparent")
                } description: {
                    Text("Jedes show() in model.py erscheint hier. ⌘R rechnet neu.")
                }
            }
        } else if nodes.isEmpty {
            ContentUnavailableView.search(text: state.searchText)
        }
    }

    @ViewBuilder
    private var footer: some View {
        let hidden = model.parts.filter { !$0.visible }.count
        if hidden > 0 {
            HStack(spacing: 8) {
                Image(systemName: "eye.slash").foregroundStyle(.secondary)
                Text("\(KevFormat.integer(hidden)) ausgeblendet")
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Alle einblenden") { model.actions?.showAll() }
                    .controlSize(.small)
            }
            .font(.subheadline)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)
            .overlay(alignment: .top) { Divider() }
        }
    }
}

/// Ein Knoten mit Unterknoten (rekursiv).
private struct PartTreeNodeView: View {
    let node: PartTreeNode
    @ObservedObject var model: AppModel
    @Binding var collapsed: Set<String>
    var filtering: Bool

    var body: some View {
        if let children = node.children {
            DisclosureGroup(isExpanded: expanded) {
                ForEach(children) { child in
                    AnyView(PartTreeNodeView(node: child, model: model, collapsed: $collapsed, filtering: filtering))
                }
            } label: {
                PartRow(node: node, model: model)
            }
            .tag(node.id)
        } else {
            PartRow(node: node, model: model)
                .tag(node.id)
        }
    }

    /// Gruppen sind aufgeklappt, bis jemand sie zuklappt; beim Filtern immer offen.
    private var expanded: Binding<Bool> {
        Binding(
            get: { filtering || !collapsed.contains(node.id) },
            set: { open in
                if open { collapsed.remove(node.id) } else { collapsed.insert(node.id) }
            })
    }
}

/// Zeile: Auge, Farbfleck, Name, bei Gruppen die Anzahl, bei Teilen das Material.
private struct PartRow: View {
    let node: PartTreeNode
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(spacing: 7) {
            Button(action: toggleVisibility) {
                Image(systemName: node.allHidden ? "eye.slash" : "eye")
                    .foregroundStyle(node.allHidden ? .tertiary : .secondary)
                    .opacity(node.allVisible || node.allHidden ? 1 : 0.55)
                    .frame(width: 18)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help(node.allHidden ? "Einblenden" : "Ausblenden")

            swatch
                .opacity(node.allHidden ? 0.35 : 1)

            Text(node.name)
                .foregroundStyle(node.allHidden ? .secondary : .primary)
                .lineLimit(1)
                .truncationMode(.middle)

            Spacer(minLength: 4)

            if node.isGroup {
                Text(KevFormat.integer(node.partCount))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(.quaternary))
            } else if let material = node.part?.material {
                Text(material.capitalized)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
        .help(help)
    }

    @ViewBuilder
    private var swatch: some View {
        if let part = node.part, !node.isGroup {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(Color(part: part.color))
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(.primary.opacity(0.18), lineWidth: 0.5)
                )
                .frame(width: 12, height: 12)
        } else {
            Image(systemName: "square.stack.3d.up")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .frame(width: 12, height: 12)
        }
    }

    private var help: String {
        if node.isGroup {
            return "\(node.id) · \(KevFormat.count(node.partCount, one: "Teil", many: "Teile")) · "
                + KevFormat.count(node.triangles, one: "Dreieck", many: "Dreiecke")
        }
        var parts = [node.id]
        if let material = node.part?.material { parts.append(material) }
        parts.append(KevFormat.count(node.triangles, one: "Dreieck", many: "Dreiecke"))
        return parts.joined(separator: " · ")
    }

    private func toggleVisibility() {
        model.actions?.setVisibility(node.partIDs, visible: !node.allVisible)
    }
}
