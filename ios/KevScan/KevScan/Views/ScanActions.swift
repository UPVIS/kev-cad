import SwiftUI
import UIKit

/// Aktionen auf einem Scan, gemeinsam für Liste und Detailansicht.
enum ScanAction: Identifiable {
    case rename(ScanItem)
    case delete(ScanItem)
    case send(ScanItem)
    case share(ScanItem)

    var id: String {
        switch self {
        case .rename(let item): return "rename-" + item.id
        case .delete(let item): return "delete-" + item.id
        case .send(let item): return "send-" + item.id
        case .share(let item): return "share-" + item.id
        }
    }
}

struct ScanActionButtons: View {
    let item: ScanItem
    @Binding var action: ScanAction?

    var body: some View {
        Button { action = .send(item) } label: { Label("An Mac senden", systemImage: "paperplane") }
        Button { action = .share(item) } label: { Label("Teilen (AirDrop)", systemImage: "square.and.arrow.up") }
        Button { action = .rename(item) } label: { Label("Umbenennen", systemImage: "pencil") }
        Button(role: .destructive) { action = .delete(item) } label: { Label("Löschen", systemImage: "trash") }
    }
}

struct SharePayload: Identifiable {
    let id = UUID()
    let url: URL
}

struct ScanActionsModifier: ViewModifier {
    @EnvironmentObject private var store: ScanStore
    @Binding var action: ScanAction?
    var onDelete: (() -> Void)?

    @State private var renameTarget: ScanItem?
    @State private var renameText = ""
    @State private var showRename = false
    @State private var deleteTarget: ScanItem?
    @State private var showDelete = false
    @State private var sendTarget: ScanItem?
    @State private var share: SharePayload?
    @State private var packing = false
    @State private var errorText: String?

    func body(content: Content) -> some View {
        content
            .onChange(of: action?.id) { _, _ in route() }
            .alert("Umbenennen", isPresented: $showRename) {
                TextField("Name", text: $renameText)
                Button("Abbrechen", role: .cancel) {}
                Button("Sichern") {
                    guard let item = renameTarget else { return }
                    do { try store.rename(item, to: renameText) } catch { errorText = error.localizedDescription }
                }
            }
            .confirmationDialog("Scan löschen?", isPresented: $showDelete, titleVisibility: .visible, presenting: deleteTarget) { item in
                Button("„\(item.name)“ löschen", role: .destructive) {
                    store.delete(item)
                    onDelete?()
                }
            } message: { item in
                Text("\(Formatting.bytes(item.sizeBytes)) werden auf dem iPhone frei. Auf den Mac gesendete Kopien bleiben.")
            }
            .sheet(item: $sendTarget) { item in
                SendView(itemID: item.id)
                    .environmentObject(store)
            }
            .sheet(item: $share, onDismiss: cleanupShare) { payload in
                ShareSheet(items: [payload.url])
                    .ignoresSafeArea()
            }
            .overlay {
                if packing {
                    ProgressView("Packe den Scan …")
                        .padding(20)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
            }
            .alert("Fehler", isPresented: Binding(get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(errorText ?? "")
            }
    }

    private func route() {
        guard let current = action else { return }
        action = nil
        switch current {
        case .rename(let item):
            renameTarget = item
            renameText = item.name
            showRename = true
        case .delete(let item):
            deleteTarget = item
            showDelete = true
        case .send(let item):
            sendTarget = item
        case .share(let item):
            packing = true
            Task { @MainActor in
                do {
                    let zip = try await store.makeZip(item)
                    packing = false
                    share = SharePayload(url: zip)
                } catch {
                    packing = false
                    errorText = error.localizedDescription
                }
            }
        }
    }

    private func cleanupShare() {
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory
        for entry in (try? fm.contentsOfDirectory(atPath: tmp.path)) ?? [] where entry.hasPrefix("zip-") {
            try? fm.removeItem(at: tmp.appendingPathComponent(entry))
        }
    }
}

extension View {
    func scanActions(_ action: Binding<ScanAction?>, onDelete: (() -> Void)? = nil) -> some View {
        modifier(ScanActionsModifier(action: action, onDelete: onDelete))
    }
}

/// Teilen-Menü (AirDrop, Dateien, …).
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
