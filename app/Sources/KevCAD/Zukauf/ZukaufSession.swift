import AppKit
import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

// Phase 3 (Z-A): Zukaufteile in der Oberfläche. Fenster „Zukaufteil hinzufügen …“, Rückfrage zu neuen Dateien in
// Downloads, Anzeige im Teilebaum, Inspektor, Stückliste und Lagerkatalog. Shop-Seiten lädt die App nie (PLAN Z1).

extension WindowID {
    static let zukauf = "zukauf"
}

/// Auftrag für das Fenster „Zukaufteil hinzufügen …“.
struct ZukaufDialogRequest: Identifiable, Equatable {
    enum Mode: Equatable {
        /// Neu: Eingabe, Felder, dann ZUKAUF_NEU
        case new
        /// Vorschlag von Claude prüfen und freigeben (CATALOG_SAVE mit status frei)
        case confirm
        /// Vorhandenes Zukaufteil ändern (CATALOG_SAVE)
        case edit
    }

    let id = UUID()
    var mode: Mode
    var draft: ZukaufDraft
    var ebene: CatalogLevel
    /// Bei `.new`: mit den Feldern beginnen statt mit der Eingabe.
    var startWithFields = false

    static func new(input: String = "", ebene: CatalogLevel = .projekt) -> ZukaufDialogRequest {
        ZukaufDialogRequest(mode: .new, draft: ZukaufDraft(input: input), ebene: ebene)
    }

    static func == (a: ZukaufDialogRequest, b: ZukaufDialogRequest) -> Bool { a.id == b.id }
}

extension AppSession {
    /// Fenster „Zukaufteil hinzufügen …“ öffnen (neu, Vorschlag prüfen oder bearbeiten).
    func showZukaufDialog(_ request: ZukaufDialogRequest? = nil) {
        var r = request ?? .new()
        if r.mode == .new, r.ebene == .projekt, model.project == nil { r.ebene = .eigen }
        zukaufRequest = r
        showWindow(WindowID.zukauf)
    }

    /// Vorschlag von Claude (oder vorhandenes Zukaufteil) im Dialog öffnen.
    func showZukaufDialog(for item: CatalogItem, mode: ZukaufDialogRequest.Mode) {
        showZukaufDialog(ZukaufDialogRequest(
            mode: mode, draft: ZukaufDraft(entry: item.entry), ebene: item.ebene.isEditable ? item.ebene : .eigen))
    }

    /// Anzeigename eines Zukaufteils: Katalog, sonst der Name aus ZUKAUF_STATUS, sonst die id.
    func zukaufName(_ id: String) -> String {
        model.catalog?.item(id)?.name ?? model.zukaufStatus(for: id)?.name ?? id
    }

    /// Dateiauswahl für ein CAD (STEP, STP, ZIP); ruft `assignCAD`.
    func chooseCADFile(for teil: String) {
        let panel = NSOpenPanel()
        panel.title = "CAD-Datei für „\(zukaufName(teil))“"
        panel.message = "STEP-Datei des Herstellers wählen (auch als ZIP)"
        panel.prompt = "Übernehmen"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = ["step", "stp", "zip"].compactMap { UTType(filenameExtension: $0) }
        panel.directoryURL = model.watchedDownloads ?? AppInfo.downloadsDirectory
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            Task { @MainActor in self?.model.zukaufActions?.assignCAD(file: url, to: teil) }
        }
    }

    /// Ein Fenster per id öffnen (über das `openWindow`, das jedes Fenster bei `attach` meldet).
    fileprivate func showWindow(_ id: String) {
        openWindowAction?(id: id)
    }
}

// MARK: - Bausteine

/// Produktbild aus dem Shop (nur das Bild, keine Seite), sonst ein Platzhalter.
struct ZukaufImage: View {
    var url: URL?
    var size: CGFloat = 40

    var body: some View {
        Group {
            if let url {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image): image.resizable().scaledToFit()
                    case .failure: placeholder
                    default: ProgressView().controlSize(.small)
                    }
                }
            } else {
                placeholder
            }
        }
        .frame(width: size, height: size)
        .background(RoundedRectangle(cornerRadius: size * 0.18, style: .continuous).fill(Color.white.opacity(0.9)))
        .clipShape(RoundedRectangle(cornerRadius: size * 0.18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: size * 0.18, style: .continuous)
                .strokeBorder(.primary.opacity(0.12), lineWidth: 0.5)
        )
    }

    private var placeholder: some View {
        Image(systemName: "cart")
            .font(.system(size: size * 0.42, weight: .medium))
            .foregroundStyle(.tint)
            .frame(width: size, height: size)
            .background(Color.accentColor.opacity(0.1))
    }
}

/// Etikett der CAD-Quelle: Hersteller-CAD (blau) oder vereinfacht (orange).
struct CADSourceBadge: View {
    var simplified: Bool
    var title: String? = nil

    var body: some View {
        Badge(text: title ?? (simplified ? "vereinfacht" : "Hersteller-CAD"), color: simplified ? .orange : .blue)
            .help(simplified
                ? "Ersatzkörper aus den Shop-Maßen: maßlich richtig, halbtransparent, bis das Hersteller-CAD da ist"
                : "Eingebettetes Modell des Herstellers")
    }
}

/// Symbol für ein Zukaufteil im Teilebaum und in Listen.
enum ZukaufSymbol {
    static func name(simplified: Bool) -> String { simplified ? "cube.transparent" : "cart.fill" }
}

/// Zustand eines Zukaufteils als kurzer Text mit Symbol.
struct ZukaufStatusLabel: View {
    var status: ZukaufStatus

    var body: some View {
        Label {
            Text(status.uebergabe.map { "\($0) wird übernommen …" } ?? status.zustand.title.capitalizedFirst)
        } icon: {
            if status.uebergabe != nil {
                ProgressView().controlSize(.mini)
            } else {
                Image(systemName: symbol).foregroundStyle(color)
            }
        }
    }

    private var symbol: String {
        switch status.zustand {
        case .wartetAufCAD: return "hourglass"
        case .importiert: return "checkmark.circle.fill"
        case .fehler: return "xmark.octagon.fill"
        default: return "info.circle"
        }
    }

    private var color: Color {
        switch status.zustand {
        case .wartetAufCAD: return .orange
        case .importiert: return .green
        case .fehler: return .red
        default: return .secondary
        }
    }
}

/// „CAD suchen“: einer oder mehrere Links aus ZUKAUF_STATUS im Standardbrowser öffnen.
struct CADSearchButton: View {
    var links: [CADLink]
    var title = "CAD suchen"
    @Environment(\.openURL) private var openURL

    var body: some View {
        if links.count == 1, let link = links.first {
            Button {
                openURL(link.url)
            } label: {
                Label(title, systemImage: "magnifyingglass")
            }
            .help("\(link.titel) im Standardbrowser öffnen")
        } else if !links.isEmpty {
            Menu {
                ForEach(links) { link in
                    Button(link.titel) { openURL(link.url) }
                }
            } label: {
                Label(title, systemImage: "magnifyingglass")
            } primaryAction: {
                openURL(links[0].url)
            }
            .fixedSize()
            .help("Klick: \(links[0].titel) im Browser; Pfeil: weitere Quellen")
        }
    }
}

extension String {
    /// Erster Buchstabe groß („wartet auf CAD“ → „Wartet auf CAD“).
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
