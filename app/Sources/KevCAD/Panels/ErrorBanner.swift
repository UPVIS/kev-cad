import AppKit
import KevCADCore
import SwiftUI

/// Fehlerband über dem Viewport bei `RunState.failed`: Meldung, Zeile, Codeauszug, "model.py öffnen", "Neu rechnen".
/// Die letzte gute Geometrie bleibt darunter stehen (PLAN-MVP.md Abschnitt 4).
struct ErrorBanner: View {
    var run: Int
    var message: String
    var line: Int?
    var excerpt: String
    var openModel: () -> Void
    var rerun: () -> Void
    var dismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.title3)
                    .foregroundStyle(.red)
                VStack(alignment: .leading, spacing: 1) {
                    Text(line.map { "model.py · Fehler in Zeile \($0)" } ?? "model.py · Fehler")
                        .font(.headline)
                    Text("Lauf \(run) abgebrochen, die letzte gute Geometrie bleibt stehen")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                Button("model.py öffnen", action: openModel)
                    .help("model.py im Standard-Editor öffnen (⌥⌘O)")
                Button("Neu rechnen", action: rerun)
                    .buttonStyle(.borderedProminent)
                    .help("Neu rechnen (⌘R)")
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Band ausblenden")
            }

            Text(message)
                .font(.callout.monospaced())
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)

            if !excerpt.isEmpty {
                ExcerptView(excerpt: excerpt, line: line)
            }
        }
        .padding(14)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Color.red.opacity(0.06))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Color.red.opacity(0.45), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.18), radius: 14, y: 4)
        }
    }
}

/// Codeauszug in Monospace; die Fehlerzeile ist hervorgehoben.
private struct ExcerptView: View {
    var excerpt: String
    var line: Int?

    var body: some View {
        let lines = excerpt.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, text in
                let isError = Self.isErrorLine(text, line: line)
                Text(text.isEmpty ? " " : text)
                    .font(.system(size: 11.5, design: .monospaced))
                    .foregroundStyle(isError ? Color.primary : Color.secondary)
                    .fontWeight(isError ? .semibold : .regular)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 1.5)
                    .background(isError ? Color.red.opacity(0.16) : Color.clear)
            }
        }
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.primary.opacity(0.06))
        )
        .textSelection(.enabled)
    }

    /// Fehlerzeile erkennen: Markierung ">" oder "→" am Anfang, sonst die Zeilennummer am Anfang.
    static func isErrorLine(_ text: String, line: Int?) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix(">") || trimmed.hasPrefix("→") { return true }
        guard let line else { return false }
        let digits = trimmed.prefix(while: \.isNumber)
        return Int(digits) == line
    }
}
