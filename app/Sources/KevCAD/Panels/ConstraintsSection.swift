import KevCADCore
import SwiftUI

// Zwangsbedingungen im Inspektor (PLAN-BEDINGUNGEN.md): mit einem ausgewählten Teil dessen Bedingungen,
// Freiheitsgrade und Befestigung; sonst die Übersicht mit allem, was verletzt ist. Ein Klick zeigt die Bedingung im
// Viewer. Die Symbole am Teil lassen sich hier und im Menü Ansicht ausblenden.

extension AppModel {
    var constraintActions: ConstraintActions? { actions as? ConstraintActions }
}

struct ConstraintsSection: View {
    @ObservedObject var model: AppModel

    var body: some View {
        if let report = model.constraints, report.summary.gesamt > 0 || !report.findings.isEmpty {
            Section {
                content(report)
            } header: {
                HStack {
                    Text("Bedingungen")
                    Text(summaryText(report.summary))
                        .monospacedDigit()
                        .foregroundStyle(report.hasErrors ? .red : .secondary)
                    Spacer()
                    if model.constraintActions != nil {
                        Button {
                            BedingungenSchalter.umschalten(model)
                        } label: {
                            Image(systemName: model.showConstraintSymbols ? "eye" : "eye.slash")
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .help(model.showConstraintSymbols ? "Symbole am Teil ausblenden" : "Symbole am Teil zeigen")
                    }
                }
            }
        }
    }

    private func summaryText(_ s: ConstraintSummary) -> String {
        var parts = ["\(s.gesamt)"]
        if s.verletzt > 0 { parts.append("\(s.verletzt) verletzt") }
        if s.fehler > 0 && s.verletzt == 0 { parts.append("\(s.fehler) Befunde") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private func content(_ report: ConstraintReport) -> some View {
        let selected = model.selectedPartIDs
        if selected.count == 1, let id = selected.first {
            let items = report.items(for: id)
            if let part = report.part(id) {
                PartConstraintSummary(part: part)
            }
            if items.isEmpty {
                Text("Keine Bedingung an diesem Teil.")
                    .foregroundStyle(.secondary)
            }
            ForEach(items) { item in
                ConstraintRow(item: item, model: model)
            }
            ForEach(report.findings.filter { $0.bedingung == nil && $0.teile.contains(id) }) { f in
                FindingRow(finding: f)
            }
        } else {
            let violated = report.items.filter { $0.stand != .erfuellt }
            let extra = report.findings.filter { $0.bedingung == nil && $0.schwere != .hinweis }
            if violated.isEmpty && extra.isEmpty {
                Label("Alle Bedingungen erfüllt", systemImage: "checkmark.circle")
                    .foregroundStyle(.green)
            }
            ForEach(violated.prefix(12)) { item in
                ConstraintRow(item: item, model: model)
            }
            ForEach(extra.prefix(8)) { f in
                FindingRow(finding: f)
            }
            if violated.count > 12 {
                Text("und \(violated.count - 12) weitere")
                    .foregroundStyle(.secondary)
            }
            ForEach(report.motions.filter { !$0.blockiertDurch.isEmpty }) { m in
                MotionRow(motion: m)
            }
        }
        if let p = model.pruefung, p.wirdFertigGerechnet {
            // Bewegungsraum über dem Zeitlimit des Laufs: der Kernel rechnet weiter und schickt den Endstand
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text(p.bewegungsraumText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .help(p.imHintergrund.joined(separator: "\n"))
        }
    }
}

/// Glyphe und Farbe einer Bedingung wie im Viewport.
private struct ConstraintGlyph: View {
    var item: ConstraintItem

    var color: Color {
        switch item.stand {
        case .erfuellt: return .blue
        case .ungeprueft: return .gray
        case .verletzt: return item.isError ? .red : .orange
        }
    }

    var body: some View {
        Text(AppController.constraintGlyph(item.symbol))
            .font(.system(size: 11, weight: .semibold))
            .frame(width: 18, height: 18)
            .foregroundStyle(item.stand == .verletzt ? Color.white : color)
            .background(RoundedRectangle(cornerRadius: 4).fill(item.stand == .verletzt ? color : Color.clear))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(color, lineWidth: 1))
    }
}

private struct ConstraintRow: View {
    var item: ConstraintItem
    @ObservedObject var model: AppModel

    var body: some View {
        Button {
            model.constraintActions?.showConstraint(item.id)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                ConstraintGlyph(item: item)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.text)
                        .fixedSize(horizontal: false, vertical: true)
                    if item.stand == .verletzt {
                        Text("Soll \(item.soll) · Ist \(item.ist)")
                            .font(.caption)
                            .foregroundStyle(item.isError ? .red : .orange)
                            .fixedSize(horizontal: false, vertical: true)
                        if let l = item.loesung {
                            Text(l)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    } else if item.stand == .ungeprueft, let h = item.hinweis {
                        Text(h)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 4)
                if let z = item.zeile {
                    Text("Z. \(z)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.tertiary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Im Viewer zeigen")
        .contextMenu {
            Button("Text kopieren") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(
                    ([item.text, "Soll \(item.soll)", "Ist \(item.ist)"] + [item.loesung].compactMap { $0 })
                        .joined(separator: "\n"), forType: .string)
            }
        }
    }
}

private struct FindingRow: View {
    var finding: ConstraintFinding

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: finding.schwere == .fehler ? "exclamationmark.octagon.fill" : "exclamationmark.triangle")
                .foregroundStyle(finding.schwere == .fehler ? .red : .orange)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(finding.text)
                    .fixedSize(horizontal: false, vertical: true)
                if let l = finding.loesung {
                    Text(l)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private struct MotionRow: View {
    var motion: MotionRange

    var body: some View {
        let unit = motion.art == "drehen" ? "°" : " mm"
        let frei = motion.frei.map { "\(KevFormat.number($0[0], digits: 1)) … \(KevFormat.number($0[1], digits: 1))\(unit)" }
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: motion.art == "drehen" ? "arrow.clockwise" : "arrow.left.and.right")
                .foregroundStyle(.red)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(motion.name)
                Text("frei \(frei.isEmpty ? "nirgends" : frei.joined(separator: ", ")) · stößt an "
                    + motion.blockiertDurch.joined(separator: ", "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct PartConstraintSummary: View {
    var part: ConstraintPart

    var body: some View {
        let stand: String = {
            switch part.stand {
            case "bestimmt": return "voll bestimmt"
            case "unterbestimmt": return "unterbestimmt: \(part.frei) frei"
            case "widerspruch": return "Widerspruch"
            default: return "Gegenstück"
            }
        }()
        VStack(alignment: .leading, spacing: 3) {
            LabeledContent("Lage", value: stand)
            let frei = part.freiheitsgrade.filter { !$0.gelenk && !$0.unkritisch }.map(\.text)
            if !frei.isEmpty {
                Text(frei.joined(separator: "; "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !part.gelenke.isEmpty {
                LabeledContent("Gelenk", value: part.gelenke.joined(separator: "; "))
            }
            if let befestigt = part.befestigt {
                LabeledContent("Befestigung") {
                    Text(befestigt ? (part.verbindungen.isEmpty ? "ja" : part.verbindungen.joined(separator: ", "))
                         : "fehlt")
                        .foregroundStyle(befestigt ? Color.primary : Color.red)
                }
                if befestigt, part.amBoden == false {
                    Text("hängt nicht am Boden")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
        }
    }
}
