import SwiftUI
import UIKit

/// Sucht Macs mit Kev CAD (Bonjour `_kevscan._tcp`) und lädt den Scan als ZIP hoch.
struct SendView: View {
    let itemID: String
    @EnvironmentObject private var store: ScanStore
    @Environment(\.dismiss) private var dismiss
    @StateObject private var browser = MacBrowser()
    @StateObject private var uploader = Uploader()
    @State private var share: SharePayload?
    @State private var task: Task<Void, Never>?

    private var item: ScanItem? { store.item(withID: itemID) }

    var body: some View {
        NavigationStack {
            List {
                if let item {
                    Section {
                        HStack(spacing: 12) {
                            ScanThumbnail(url: item.previewURL)
                                .frame(width: 42, height: 56)
                                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                            VStack(alignment: .leading) {
                                Text(item.name).font(.headline)
                                Text("\(Formatting.bytes(item.sizeBytes)) · \(item.photoCount) Fotos")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                switch uploader.phase {
                case .idle:
                    macSection
                case .packing:
                    Section { ProgressView("Packe den Scan …") }
                case .connecting(let mac):
                    Section { ProgressView("Verbinde mit \(mac) …") }
                case .uploading(let mac):
                    Section("Sende an \(mac)") {
                        ProgressView(value: uploader.progress) {
                            Text("\(Int(uploader.progress * 100)) %")
                        } currentValueLabel: {
                            Text("\(Formatting.bytes(uploader.sentBytes)) von \(Formatting.bytes(uploader.totalBytes))")
                        }
                        Text("Kev Scan bitte geöffnet lassen, bis die Übertragung fertig ist.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                case .done(let mac):
                    Section {
                        Label("Gesendet an \(mac)", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.headline)
                        Text("Kev CAD legt den Scan unter Dokumente > Kev CAD > Scans ab. Übernommen wird er dort auf Anfrage.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                case .failed(let text):
                    Section {
                        Label(text, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                        Button("Nochmal versuchen") { uploader.phase = .idle }
                    }
                }
                Section {
                    Button {
                        shareInstead()
                    } label: {
                        Label("Stattdessen teilen (AirDrop)", systemImage: "square.and.arrow.up")
                    }
                } footer: {
                    Text("Ohne gemeinsames WLAN: das ZIP per AirDrop an den Mac schicken. Es landet dort in Downloads.")
                }
            }
            .navigationTitle("An Mac senden")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(isDone ? "Fertig" : "Abbrechen") {
                        task?.cancel()
                        dismiss()
                    }
                }
            }
            .onAppear { browser.start() }
            .onDisappear { browser.stop() }
            .sheet(item: $share) { payload in
                ShareSheet(items: [payload.url]).ignoresSafeArea()
            }
        }
    }

    private var isDone: Bool {
        if case .done = uploader.phase { return true }
        return false
    }

    @ViewBuilder
    private var macSection: some View {
        Section {
            if browser.services.isEmpty {
                HStack(spacing: 10) {
                    ProgressView()
                    Text("Suche Kev CAD im WLAN …")
                        .foregroundStyle(.secondary)
                }
            }
            ForEach(browser.services) { mac in
                Button { send(to: mac) } label: {
                    MacRow(mac: mac)
                }
                .disabled(item?.complete != true)
            }
        } header: {
            Text("Rechner")
        } footer: {
            if let problem = browser.problem {
                Text(problem).foregroundStyle(.orange)
            } else {
                Text("Kev CAD muss auf dem Mac laufen, beide Geräte im selben WLAN.")
            }
        }
    }

    private func send(to mac: MacService) {
        guard let item else { return }
        task = Task { @MainActor in
            let background = BackgroundActivity(name: "Scan senden")
            defer { background.end() }
            var zipFolder: URL?
            do {
                uploader.phase = .packing
                let zip = try await store.makeZip(item)
                zipFolder = zip.deletingLastPathComponent()
                uploader.phase = .connecting(mac.name)
                let base = try await MacBrowser.resolve(mac.endpoint)
                uploader.phase = .uploading(mac.name)
                let answer = try await uploader.upload(file: zip, to: base, name: item.name)
                if answer.ok {
                    store.markSent(item, to: mac.name, folder: answer.ordner ?? answer.id)
                    uploader.phase = .done(mac.name)
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                } else {
                    uploader.phase = .failed(answer.fehler ?? "Der Mac hat den Scan abgelehnt.")
                }
            } catch {
                uploader.phase = .failed(error.localizedDescription)
            }
            if let zipFolder { try? FileManager.default.removeItem(at: zipFolder) }
        }
    }

    private func shareInstead() {
        guard let item else { return }
        Task { @MainActor in
            uploader.phase = .packing
            do {
                let zip = try await store.makeZip(item)
                uploader.phase = .idle
                share = SharePayload(url: zip)
            } catch {
                uploader.phase = .failed(error.localizedDescription)
            }
        }
    }
}

/// Hält die App nach einem Wechsel in den Hintergrund noch kurz wach, damit eine Übertragung fertig wird.
@MainActor
final class BackgroundActivity {
    private var identifier: UIBackgroundTaskIdentifier = .invalid

    init(name: String) {
        identifier = UIApplication.shared.beginBackgroundTask(withName: name) { [weak self] in
            self?.end()
        }
    }

    func end() {
        guard identifier != .invalid else { return }
        UIApplication.shared.endBackgroundTask(identifier)
        identifier = .invalid
    }
}

struct MacRow: View {
    let mac: MacService
    @State private var info: MacInfo?

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "desktopcomputer")
                .font(.title2)
                .foregroundStyle(Color.accentColor)
                .frame(width: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(info?.rechner ?? mac.name)
                    .foregroundStyle(.primary)
                if let projekt = info?.projekt {
                    Text("Projekt: \(projekt)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Kev CAD")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            Image(systemName: "paperplane")
                .foregroundStyle(Color.accentColor)
        }
        .task(id: mac.name) {
            guard let base = try? await MacBrowser.resolve(mac.endpoint) else { return }
            info = try? await MacBrowser.info(base)
        }
    }
}
