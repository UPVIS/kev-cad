import AppKit
import KevCADCore
import SwiftUI

/// Rechte Spalte des Willkommensfensters: „Zuletzt geöffnet“ mit Name, Pfad und Datum.
/// Doppelklick oder Return öffnet, fehlende Ordner sind ausgegraut.
struct RecentProjectsList: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var recents: RecentProjects
    @State private var selection: RecentProject.ID?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Zuletzt geöffnet")
                    .font(.headline)
                Spacer()
                if !recents.items.isEmpty {
                    Menu {
                        Button("Fehlende entfernen") { recents.removeMissing() }
                            .disabled(!recents.items.contains(where: \.isMissing))
                        Button("Liste leeren") { recents.clear() }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .menuStyle(.borderlessButton)
                    .menuIndicator(.hidden)
                    .fixedSize()
                    .help("Liste bearbeiten")
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 8)

            if recents.items.isEmpty {
                ContentUnavailableView {
                    Label("Noch keine Projekte", systemImage: "clock")
                } description: {
                    Text("Geöffnete Projekte erscheinen hier.")
                }
                .frame(maxHeight: .infinity)
            } else {
                List(recents.items, selection: $selection) { item in
                    RecentRow(item: item)
                        .tag(item.id)
                }
                .listStyle(.inset)
                .scrollContentBackground(.hidden)
                .contextMenu(forSelectionType: RecentProject.ID.self) { ids in
                    if let item = item(ids.first) {
                        Button("Öffnen") { session.openRecent(item) }
                        Button("Im Finder zeigen") { NSWorkspace.shared.activateFileViewerSelecting([item.url]) }
                            .disabled(item.isMissing)
                        Divider()
                        Button("Aus Liste entfernen") { recents.remove(item.url) }
                    }
                } primaryAction: { ids in
                    if let item = item(ids.first) { session.openRecent(item) }
                }
            }
        }
        .frame(maxHeight: .infinity)
        // Hintergrund und Trennlinie reichen bis unter die (versteckte) Titelleiste.
        .background { Rectangle().fill(.background.secondary).ignoresSafeArea() }
        .overlay(alignment: .leading) {
            Rectangle().fill(.separator).frame(width: 1).ignoresSafeArea()
        }
    }

    private func item(_ id: RecentProject.ID?) -> RecentProject? {
        guard let id else { return nil }
        return recents.items.first { $0.id == id }
    }
}

private struct RecentRow: View {
    var item: RecentProject

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: item.isMissing ? "questionmark.folder" : "cube.fill")
                .font(.system(size: 15))
                .foregroundStyle(item.isMissing ? AnyShapeStyle(.tertiary) : AnyShapeStyle(.tint))
                .frame(width: 30, height: 30)
                .background(
                    RoundedRectangle(cornerRadius: 7, style: .continuous)
                        .fill(Color.primary.opacity(item.isMissing ? 0.04 : 0.07))
                )
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(item.name)
                        .font(.body.weight(.medium))
                        .lineLimit(1)
                    if item.isMissing {
                        Text("fehlt")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 5)
                            .background(Capsule().fill(Color.primary.opacity(0.08)))
                    }
                }
                Text(KevFormat.abbreviatedPath(item.path))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 6)
            Text(KevFormat.recentDate(item.lastOpened))
                .font(.caption)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
        }
        .padding(.vertical, 3)
        .opacity(item.isMissing ? 0.55 : 1)
        .help(item.isMissing ? "Ordner fehlt: \(item.path)" : item.path)
    }
}
