import AppKit
import KevCADCore
import SwiftUI

/// Fenster „Protokoll“: AppModel.log mit Filter nach Stufe, Suche und Kopieren.
struct LogWindow: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @State private var level: LevelFilter = .all
    @State private var search = ""
    @State private var selection = Set<LogLine.ID>()
    @State private var follow = true
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    enum LevelFilter: String, CaseIterable, Identifiable {
        case all, info, warning, error
        var id: String { rawValue }
        var title: String {
            switch self {
            case .all: return "Alle"
            case .info: return "Info"
            case .warning: return "Warnungen"
            case .error: return "Fehler"
            }
        }
    }

    private var lines: [LogLine] {
        model.log.filter { line in
            let levelOK: Bool
            switch level {
            case .all: levelOK = true
            case .info: levelOK = line.level == .info
            case .warning: levelOK = line.level == .warning
            case .error: levelOK = line.level == .error
            }
            return levelOK && (search.isEmpty || line.text.localizedCaseInsensitiveContains(search))
        }
    }

    var body: some View {
        let lines = self.lines
        ScrollViewReader { proxy in
            List(lines, selection: $selection) { line in
                LogRow(line: line).id(line.id)
            }
            .listStyle(.inset)
            .alternatingRowBackgrounds()
            .overlay {
                if lines.isEmpty {
                    ContentUnavailableView(
                        model.log.isEmpty ? "Noch keine Einträge" : "Keine passenden Einträge",
                        systemImage: "text.alignleft")
                }
            }
            .onChange(of: model.log.last?.id) {
                guard follow, let last = self.lines.last else { return }
                proxy.scrollTo(last.id, anchor: .bottom)
            }
            .onAppear {
                if let last = lines.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
        .onCopyCommand { [NSItemProvider(object: copyText() as NSString)] }
        .searchable(text: $search, placement: .toolbar, prompt: "Protokoll durchsuchen")
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("Stufe", selection: $level) {
                    ForEach(LevelFilter.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)
                .help("Nach Stufe filtern")
            }
            ToolbarItemGroup(placement: .primaryAction) {
                Toggle(isOn: $follow) {
                    Label("Mitlaufen", systemImage: "arrow.down.to.line")
                }
                .help("Automatisch zur neuesten Zeile springen")
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(copyText(), forType: .string)
                } label: {
                    Label("Kopieren", systemImage: "doc.on.doc")
                }
                .help(selection.isEmpty ? "Alle gezeigten Zeilen kopieren" : "Ausgewählte Zeilen kopieren (⌘C)")
            }
        }
        .navigationTitle("Protokoll")
        .navigationSubtitle(subtitle)
        .frame(minWidth: 560, minHeight: 300)
        .background(WindowHook(placement: .trailing(width: 860, height: 520)))
        .onAppear { session.attach(openWindow: openWindow, dismissWindow: dismissWindow) }
    }

    private var subtitle: String {
        let shown = lines.count
        let total = model.log.count
        return shown == total
            ? KevFormat.count(total, one: "Zeile", many: "Zeilen")
            : "\(KevFormat.integer(shown)) von \(KevFormat.count(total, one: "Zeile", many: "Zeilen"))"
    }

    /// Ausgewählte Zeilen, sonst alle gezeigten, als Text.
    private func copyText() -> String {
        let chosen = selection.isEmpty ? lines : lines.filter { selection.contains($0.id) }
        return chosen.map(LogRow.plainText).joined(separator: "\n")
    }
}

private struct LogRow: View {
    var line: LogLine

    static let timeFormat: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = KevFormat.locale
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()

    static func plainText(_ line: LogLine) -> String {
        "\(timeFormat.string(from: line.date))  \(line.level.title.uppercased().padding(toLength: 8, withPad: " ", startingAt: 0))\(line.text)"
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(Self.timeFormat.string(from: line.date))
                .foregroundStyle(.secondary)
                .frame(width: 62, alignment: .leading)
            Image(systemName: line.level.symbol)
                .foregroundStyle(line.level.color)
                .frame(width: 14)
            Text(line.text)
                .foregroundStyle(line.level == .error ? Color.red : Color.primary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.system(size: 11.5, design: .monospaced))
        .padding(.vertical, 1)
    }
}
