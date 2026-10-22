import ARKit
import SwiftUI

struct CaptureRequest: Identifiable {
    let id = UUID()
    let name: String
}

struct ScanListView: View {
    @EnvironmentObject private var store: ScanStore
    @State private var action: ScanAction?
    @State private var askName = false
    @State private var newName = ""
    @State private var capture: CaptureRequest?
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            Group {
                if store.scans.isEmpty && store.loaded {
                    ContentUnavailableView {
                        Label("Noch keine Scans", systemImage: "viewfinder")
                    } description: {
                        Text("Tippe auf +, um ein Objekt mit Kamera und LiDAR aufzunehmen. Kev CAD macht daraus auf dem Mac ein Modell.")
                    } actions: {
                        Button("Neuer Scan") { startNew() }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    List {
                        ForEach(store.scans) { item in
                            NavigationLink(value: item.id) {
                                ScanRow(item: item)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) { action = .delete(item) } label: {
                                    Label("Löschen", systemImage: "trash")
                                }
                                Button { action = .rename(item) } label: {
                                    Label("Umbenennen", systemImage: "pencil")
                                }
                                .tint(.orange)
                            }
                            .swipeActions(edge: .leading) {
                                Button { action = .send(item) } label: {
                                    Label("Senden", systemImage: "paperplane")
                                }
                                .tint(.accentColor)
                            }
                            .contextMenu {
                                ScanActionButtons(item: item, action: $action)
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable { store.reload() }
                }
            }
            .navigationTitle("Kev Scan")
            .navigationDestination(for: String.self) { id in
                ScanDetailView(itemID: id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showSettings = true } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Einstellungen")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { startNew() } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Neuer Scan")
                }
            }
        }
        .scanActions($action)
        .alert("Neuer Scan", isPresented: $askName) {
            TextField("Name des Objekts", text: $newName)
            Button("Abbrechen", role: .cancel) {}
            Button("Aufnehmen") {
                let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
                capture = CaptureRequest(name: name.isEmpty ? Self.defaultName() : name)
            }
        } message: {
            Text("Wie heißt das Objekt? Der Name lässt sich später ändern.")
        }
        .fullScreenCover(item: $capture) { request in
            CaptureView(name: request.name)
                .environmentObject(store)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
    }

    private func startNew() {
        newName = Self.defaultName()
        askName = true
    }

    static func defaultName() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "de_DE")
        formatter.dateFormat = "dd.MM. HH.mm"
        return "Scan \(formatter.string(from: Date()))"
    }
}

struct ScanRow: View {
    let item: ScanItem

    var body: some View {
        HStack(spacing: 12) {
            ScanThumbnail(url: item.previewURL)
                .frame(width: 54, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(item.name)
                    .font(.headline)
                    .lineLimit(1)
                Text(item.created.formatted(date: .abbreviated, time: .shortened))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    Text(ByteCountFormatter.string(fromByteCount: item.sizeBytes, countStyle: .file))
                    if item.photoCount > 0 {
                        Label("\(item.photoCount)", systemImage: "camera")
                    }
                    if let duration = item.duration {
                        Label(Formatting.duration(duration), systemImage: "timer")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .labelStyle(.titleAndIcon)
                StatusBadge(item: item)
            }
        }
        .padding(.vertical, 2)
    }
}

struct StatusBadge: View {
    let item: ScanItem

    var body: some View {
        if !item.complete {
            badge("unvollständig", systemImage: "exclamationmark.triangle", color: .orange)
        } else if let sent = item.sent {
            badge("gesendet an \(sent.rechner)", systemImage: "checkmark.circle.fill", color: .green)
        } else {
            badge("lokal", systemImage: "iphone", color: .secondary)
        }
    }

    private func badge(_ text: String, systemImage: String, color: Color) -> some View {
        Label(text, systemImage: systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .lineLimit(1)
    }
}

struct ScanThumbnail: View {
    let url: URL
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Rectangle().fill(Color(.secondarySystemFill))
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Image(systemName: "cube.transparent")
                    .foregroundStyle(.secondary)
            }
        }
        .task(id: url) {
            let path = url.path
            image = await Task.detached(priority: .utility) { UIImage(contentsOfFile: path) }.value
        }
    }
}

enum Formatting {
    static func duration(_ seconds: Double) -> String {
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    static func bytes(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}
