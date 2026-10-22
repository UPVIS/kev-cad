import SwiftUI

struct ScanDetailView: View {
    let itemID: String
    @EnvironmentObject private var store: ScanStore
    @Environment(\.dismiss) private var dismiss
    @State private var action: ScanAction?

    var body: some View {
        Group {
            if let item = store.item(withID: itemID) {
                List {
                    Section {
                        ScanThumbnail(url: item.previewURL)
                            .frame(maxWidth: .infinity)
                            .frame(height: 280)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .listRowInsets(EdgeInsets())
                    }
                    Section {
                        Button { action = .send(item) } label: {
                            Label("An Mac senden", systemImage: "paperplane.fill")
                        }
                        .disabled(!item.complete)
                        Button { action = .share(item) } label: {
                            Label("Teilen (AirDrop)", systemImage: "square.and.arrow.up")
                        }
                        .disabled(!item.complete)
                    }
                    Section("Scan") {
                        LabeledContent("Aufgenommen", value: item.created.formatted(date: .long, time: .shortened))
                        if let duration = item.duration {
                            LabeledContent("Dauer", value: Formatting.duration(duration))
                        }
                        LabeledContent("Videobilder", value: "\(item.frameCount)")
                        LabeledContent("Fotos", value: "\(item.photoCount)")
                        LabeledContent("Objekt-Box", value: item.hasObject ? "gesetzt" : "keine")
                        LabeledContent("Größe", value: Formatting.bytes(item.sizeBytes))
                        LabeledContent("Ordner", value: item.folderName)
                    }
                    Section("Status") {
                        StatusBadge(item: item)
                        if let sent = item.sent {
                            LabeledContent("Gesendet", value: sent.datum.formatted(date: .abbreviated, time: .shortened))
                            if let folder = sent.ordner {
                                LabeledContent("Ordner am Mac", value: folder)
                            }
                        }
                    }
                    Section {
                        Button { action = .rename(item) } label: {
                            Label("Umbenennen", systemImage: "pencil")
                        }
                        Button(role: .destructive) { action = .delete(item) } label: {
                            Label("Löschen", systemImage: "trash")
                        }
                    }
                }
                .navigationTitle(item.name)
                .navigationBarTitleDisplayMode(.inline)
            } else {
                ContentUnavailableView("Scan nicht gefunden", systemImage: "questionmark.folder")
            }
        }
        .scanActions($action, onDelete: { dismiss() })
    }
}
