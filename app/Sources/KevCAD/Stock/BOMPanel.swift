import AppKit
import KevCADCore
import SwiftUI

/// Bereich „Stückliste“ unter dem Viewport: Positionen als Tabelle, darunter der Zuschnitt je Stangenware, oben die
/// Summen und der CSV-Export. Ein Klick auf eine Zeile oder einen Abschnitt wählt die Teile im Viewport aus.
struct BOMPanel: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    @State private var selection: Int?
    @State private var showWarnings = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let bom = model.bom, !bom.lines.isEmpty {
                // Mit Bestand färbt der Zuschnitt nach Quelle, nicht nach Position
                let palette = model.bestandZustand.zuschnitt == nil ? Self.palette(bom) : [:]
                BOMTable(model: model, bom: bom, palette: palette, selection: $selection)
                if let zuschnitt = model.bestandZustand.zuschnitt {
                    // Bestand: Zuschnitt mit Resten und Einkaufsliste
                    Divider()
                    StuecklisteUntenView(model: model, bom: bom, zuschnitt: zuschnitt, selected: selection) { line in
                        selection = line.pos
                    }
                } else if !bom.cuts.isEmpty {
                    Divider()
                    CutPlansView(bom: bom, palette: palette, selected: selection) { line in selection = line.pos }
                }
                footer(bom)
            } else {
                emptyState
            }
        }
        .background(Color(nsColor: .controlBackgroundColor))
        .onChange(of: selection) { _, pos in
            guard let pos, let line = model.bom?.lines.first(where: { $0.pos == pos }) else { return }
            // Schon ausgewählt (z. B. beim Start im Demomodus): nicht noch einmal die Kamera bewegen
            if Set(model.selectedPartIDs) == Set(line.teile) { return }
            model.catalogActions?.showBOMLine(line)
        }
        .onChange(of: model.selectedPartIDs) { _, ids in
            // Andere Auswahl im Viewport oder Baum: Zeile nicht mehr markieren
            guard let pos = selection, let line = model.bom?.lines.first(where: { $0.pos == pos }) else { return }
            if ids.isEmpty || !Set(ids).isSubset(of: Set(line.teile)) { selection = nil }
        }
        .onChange(of: model.bom?.run) { _, _ in
            if let pos = selection, model.bom?.lines.contains(where: { $0.pos == pos }) != true { selection = nil }
        }
        .onAppear {
            if selection == nil, let pos = session.demo?.config.bomLine { selection = pos }
        }
    }

    // MARK: Kopf

    private var header: some View {
        HStack(spacing: 14) {
            HStack(spacing: 7) {
                UntererBereichReiter()
                if let bom = model.bom, !bom.lines.isEmpty {
                    Text("\(KevFormat.count(bom.totals.positionen, one: "Position", many: "Positionen")) · "
                        + KevFormat.count(bom.totals.teile, one: "Teil", many: "Teile"))
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
            }
            .lineLimit(1)
            Spacer(minLength: 8)
            if let bom = model.bom, !bom.lines.isEmpty {
                Total(label: "Gewicht", value: KevFormat.kg(bom.totals.kg))
                Total(label: "Material", value: bom.totals.preis.map(KevFormat.euro) ?? "–")
                    .help(bom.totals.preisHinweis ?? "Richtpreise")
                if model.bestandZustand.zuschnitt != nil {
                    Button {
                        BestandUI.shared.gebautDialog = true
                    } label: {
                        Label("Gebaut …", systemImage: "hammer")
                    }
                    .controlSize(.small)
                    .disabled(model.bestandActions == nil || model.laufAktiv)
                    .help("Bestand abbuchen: was der Zuschnitt verplant, geht weg; neue Reste kommen dazu")
                }
                Button {
                    model.actions?.export(formats: ["bom_csv"])
                } label: {
                    Label("Als CSV exportieren", systemImage: "square.and.arrow.up")
                }
                .controlSize(.small)
                .help("Stückliste und Zuschnitt als CSV in output/ speichern und im Finder zeigen (Numbers, Excel)")
            }
            Button {
                withAnimation(.snappy(duration: 0.2)) { state.showBOM = false }
            } label: {
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 16, height: 16)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Stückliste ausblenden (⇧⌘B)")
        }
        .padding(.leading, 12)
        .padding(.trailing, 10)
        .frame(height: 36)
        .background(.bar)
    }

    private struct Total: View {
        var label: String
        var value: String

        var body: some View {
            HStack(spacing: 5) {
                Text(label).foregroundStyle(.secondary)
                Text(value).fontWeight(.semibold).monospacedDigit()
            }
            .lineLimit(1)
            .fixedSize()
        }
    }

    // MARK: Fuß: Hinweise und Preisangabe

    private func footer(_ bom: BillOfMaterials) -> some View {
        HStack(spacing: 10) {
            if !bom.warnings.isEmpty {
                Button {
                    showWarnings.toggle()
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                        Text(bom.warnings[0])
                        if bom.warnings.count > 1 {
                            Text("und \(bom.warnings.count - 1) weitere").foregroundStyle(.secondary)
                        }
                    }
                    .lineLimit(1)
                    .truncationMode(.tail)
                }
                .buttonStyle(.plain)
                .popover(isPresented: $showWarnings, arrowEdge: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Hinweise zur Stückliste").font(.headline)
                        ForEach(Array(bom.warnings.enumerated()), id: \.offset) { _, w in
                            Label(w, systemImage: "exclamationmark.triangle.fill")
                                .symbolRenderingMode(.multicolor)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(14)
                    .frame(width: 380, alignment: .leading)
                }
            }
            Spacer(minLength: 8)
            Text(([bom.totals.preisHinweis ?? "Richtpreise ohne Gewähr"] + ["Lauf \(bom.run)"]).joined(separator: " · "))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .font(.caption)
        .padding(.horizontal, 12)
        .frame(height: 24)
        .overlay(alignment: .top) { Divider() }
    }

    // MARK: Leer

    @ViewBuilder
    private var emptyState: some View {
        let ready = model.kernelState == .ready || model.kernelState == .busy
        if model.bom != nil {
            ContentUnavailableView {
                Label("Stückliste ist leer", systemImage: "list.bullet.rectangle")
            } description: {
                Text("Im Modell stecken keine Lagerteile und keine Teile mit Material.")
            }
        } else {
            ContentUnavailableView {
                Label("Noch keine Stückliste", systemImage: "list.bullet.rectangle")
            } description: {
                Text("Sie entsteht nach jedem Lauf aus den verbauten Lagerteilen (lager.teil(…).verbauen(…)) und den "
                    + "Teilen mit Material.")
            } actions: {
                Button("Stückliste anfordern") { model.catalogActions?.requestBOM() }
                    .disabled(!ready || model.project == nil)
            }
        }
    }

    // MARK: Farben

    static let colors: [Color] = [.blue, .teal, .orange, .pink, .purple, .green, .indigo, .brown, .mint, .cyan]

    /// Farbe je Position, die im Zuschnitt vorkommt (gleiche Farbe in Tabelle und Balken).
    static func palette(_ bom: BillOfMaterials) -> [Int: Color] {
        let ids = Set(bom.cuts.map(\.stockID))
        var map: [Int: Color] = [:]
        var i = 0
        for line in bom.lines where line.laenge != nil && line.stockID.map(ids.contains) == true {
            map[line.pos] = colors[i % colors.count]
            i += 1
        }
        return map
    }
}

// MARK: - Tabelle

private struct BOMTable: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    let bom: BillOfMaterials
    let palette: [Int: Color]
    @Binding var selection: Int?

    var body: some View {
        Table(bom.lines, selection: $selection) {
            TableColumn("Pos.") { line in
                HStack(spacing: 6) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(palette[line.pos] ?? .clear)
                        .frame(width: 8, height: 8)
                    Text("\(line.pos)").monospacedDigit()
                }
            }
            .width(44)
            TableColumn("Benennung") { line in
                NameCell(line: line)
            }
            .width(min: 160, ideal: 226)
            TableColumn("Maß") { line in
                Text(line.masseText).monospacedDigit().help(line.masseText)
            }
            .width(min: 80, ideal: 130)
            TableColumn("Gehrung") { line in
                let text = KevFormat.gehrung(line.gehrung)
                Text(text)
                    .monospacedDigit()
                    .foregroundStyle(text == "–" ? .tertiary : .primary)
                    .help(text == "–" ? "gerade Schnitte" : "Gehrung an Anfang und Ende")
            }
            .width(min: 60, ideal: 78)
            TableColumn("Material") { line in
                Text(line.material ?? "–").foregroundStyle(line.material == nil ? .tertiary : .primary)
            }
            .width(min: 80, ideal: 120)
            TableColumn("Anzahl") { line in
                Text(KevFormat.integer(line.anzahl))
                    .monospacedDigit()
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 46, ideal: 52)
            TableColumn("Gewicht") { line in
                Text(line.kg.map(KevFormat.kg) ?? "–")
                    .monospacedDigit()
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .help(line.kgJe.map { "je Stück \(KevFormat.kg($0))" } ?? "")
            }
            .width(min: 60, ideal: 76)
            TableColumn("Preis") { line in
                Text(line.preis.map(KevFormat.euro) ?? "–")
                    .monospacedDigit()
                    .foregroundStyle(line.preis == nil ? .tertiary : .primary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .help(line.preisJe.map { "je Stück \(KevFormat.euro($0))" } ?? "ohne Preis")
            }
            .width(min: 60, ideal: 80)
        }
        .tableStyle(.inset)
        .alternatingRowBackgrounds()
        .contextMenu(forSelectionType: Int.self) { ids in
            if let pos = ids.first, let line = bom.lines.first(where: { $0.pos == pos }) {
                Button("Teile zeigen") { model.catalogActions?.showBOMLine(line) }
                Button("Teile isolieren") { model.actions?.isolate(line.teile) }
                if let id = line.stockID {
                    Button("Im Lagerkatalog zeigen") { session.showCatalog(focus: .item(id)) }
                }
                Divider()
                Button("Zeile kopieren") { copyToPasteboard(Self.text(line)) }
                Button("Teilenamen kopieren") { copyToPasteboard(line.teile.joined(separator: "\n")) }
            }
        } primaryAction: { ids in
            if let pos = ids.first, let line = bom.lines.first(where: { $0.pos == pos }) {
                model.catalogActions?.showBOMLine(line)
            }
        }
    }

    /// Zeile als Text mit Tabulatoren (für Numbers und Excel).
    static func text(_ line: BOMLine) -> String {
        [
            "\(line.pos)", line.benennung, line.masseText, KevFormat.gehrung(line.gehrung), line.material ?? "",
            "\(line.anzahl)", line.kg.map(KevFormat.kg) ?? "", line.preis.map(KevFormat.euro) ?? "",
        ].joined(separator: "\t")
    }

    private struct NameCell: View {
        let line: BOMLine

        var body: some View {
            HStack(spacing: 6) {
                Image(systemName: line.eigenteil ? "hammer" : CatalogSchema.art(line.art).symbol)
                    .foregroundStyle(line.eigenteil ? Color.orange : (line.druckteil ? Color.teal : Color.secondary))
                    .frame(width: 16)
                // Norm nur, wenn Platz ist; sonst steht sie im Tooltip
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) {
                        name
                        if let norm = line.norm, !line.eigenteil, !line.benennung.contains(norm) {
                            Text(norm).foregroundStyle(.secondary).lineLimit(1).fixedSize()
                        }
                        Spacer(minLength: 0)
                    }
                    HStack(spacing: 6) {
                        name.truncationMode(.tail)
                        Spacer(minLength: 0)
                    }
                }
                if line.eigenteil {
                    Badge(text: "Eigenteil", color: .orange)
                } else if line.druckteil {
                    Badge(text: "3D-Druck", color: .teal)
                }
            }
            .help(help)
        }

        private var name: some View {
            Text(line.benennung).lineLimit(1)
        }

        private var help: String {
            var parts = [line.benennung + (line.norm.map { " · \($0)" } ?? "")]
            if line.eigenteil { parts.append("Eigenteil: frei modelliert, Masse aus Volumen × Dichte") }
            if line.druckteil { parts.append("3D-Druckteil: Masse aus Volumen × Dichte, Kosten aus dem Filamentpreis") }
            if let id = line.stockID { parts.append("Lagerteil \(id)") }
            parts.append(line.teile.prefix(8).joined(separator: ", ") + (line.teile.count > 8 ? " …" : ""))
            return parts.joined(separator: "\n")
        }
    }
}

// MARK: - Zuschnitt

/// Zuschnitt je Stangenware: jede Stange als Balken mit ihren Abschnitten und dem Rest.
private struct CutPlansView: View {
    let bom: BillOfMaterials
    let palette: [Int: Color]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    private var height: CGFloat {
        let bars = bom.cuts.reduce(0) { $0 + $1.stangen.count }
        return min(CGFloat(bars) * 22 + CGFloat(bom.cuts.count) * 26 + 10, 190)
    }

    var body: some View {
        ScrollView(.vertical) {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(bom.cuts) { cut in
                    CutPlanRow(cut: cut, lines: bom.lines.filter { $0.stockID == cut.stockID }, palette: palette,
                               selected: selected, onSelect: onSelect)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .frame(height: height)
        .scrollBounceBehavior(.basedOnSize)
    }
}

private struct CutPlanRow: View {
    let cut: CutPlan
    let lines: [BOMLine]
    let palette: [Int: Color]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "scissors").foregroundStyle(.secondary)
                Text("Zuschnitt").fontWeight(.semibold)
                Text(cut.benennung).fontWeight(.medium)
                Text("· " + KevFormat.count(cut.stangen.count, one: "Stange", many: "Stangen")
                    + " à \(KevFormat.length(cut.stangenlaenge)) · Sägeschnitt \(KevFormat.length(cut.saegeschnitt))")
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Text("Verschnitt \(KevFormat.number(cut.verschnittProzent, digits: 1)) %")
                    .foregroundStyle(.secondary)
                    .help("Anteil der gekauften Länge, der nicht in Teilen steckt (Sägeschnitte und Reste)")
            }
            .font(.callout)
            .monospacedDigit()
            .lineLimit(1)
            ForEach(Array(cut.stangen.enumerated()), id: \.offset) { index, pieces in
                HStack(spacing: 8) {
                    Text("\(index + 1)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 14, alignment: .trailing)
                    CutBar(cut: cut, pieces: pieces, rest: cut.rest(ofBar: index), lineFor: line(for:),
                           palette: palette, selected: selected, onSelect: onSelect)
                        .frame(height: 18)
                }
            }
        }
    }

    /// Stücklistenzeile zu einem Abschnitt (gleiches Lagerteil, gleiche Länge).
    func line(for length: Double) -> BOMLine? {
        lines.first { abs(($0.laenge ?? -1) - length) < 0.5 }
    }
}

private struct CutBar: View {
    let cut: CutPlan
    let pieces: [Double]
    let rest: Double
    let lineFor: (Double) -> BOMLine?
    let palette: [Int: Color]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        GeometryReader { geo in
            let scale = geo.size.width / max(cut.stangenlaenge, 1)
            let kerf = max(1.5, cut.saegeschnitt * scale)
            HStack(spacing: 0) {
                ForEach(Array(pieces.enumerated()), id: \.offset) { _, length in
                    let line = lineFor(length)
                    let width = max(2, length * scale)
                    Segment(
                        length: length, width: width, color: line.flatMap { palette[$0.pos] } ?? .gray,
                        highlighted: line != nil && line?.pos == selected, dimmed: selected != nil && line?.pos != selected)
                        .frame(width: width)
                        .help(segmentHelp(length, line))
                        .onTapGesture { if let line { onSelect(line) } }
                    Color.clear.frame(width: kerf)
                }
                restView(width: max(0, geo.size.width - pieces.reduce(0) { $0 + max(2, $1 * scale) + kerf }))
            }
        }
    }

    private func segmentHelp(_ length: Double, _ line: BOMLine?) -> String {
        guard let line else { return KevFormat.length(length) }
        var text = "Pos. \(line.pos) · \(KevFormat.length(length))"
        let g = KevFormat.gehrung(line.gehrung)
        if g != "–" { text += " · Gehrung \(g)" }
        return text
    }

    @ViewBuilder
    private func restView(width: CGFloat) -> some View {
        if width > 0.5 {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(Color.primary.opacity(0.04))
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.22), style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
                )
                .overlay {
                    if width > 74 {
                        Text("Rest \(KevFormat.length(rest))")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                .frame(width: width)
                .help("Rest \(KevFormat.length(rest))")
        }
    }

    private struct Segment: View {
        let length: Double
        let width: CGFloat
        let color: Color
        let highlighted: Bool
        let dimmed: Bool

        var body: some View {
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(color.opacity(dimmed ? 0.35 : 0.8))
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(highlighted ? Color.primary.opacity(0.75) : Color.black.opacity(0.12),
                                      lineWidth: highlighted ? 1.5 : 0.5)
                )
                .overlay {
                    if width > 30 {
                        Text(KevFormat.compact(length, maxDigits: 1))
                            .font(.caption2.weight(.medium).monospacedDigit())
                            .foregroundStyle(dimmed ? Color.primary.opacity(0.55) : Color.white)
                            .shadow(color: .black.opacity(dimmed ? 0 : 0.25), radius: 0.5, y: 0.5)
                            .lineLimit(1)
                    }
                }
                .contentShape(Rectangle())
        }
    }
}

// MARK: - Größe ändern

/// Griff an der Oberkante der Stückliste: ziehen ändert die Höhe.
struct PanelResizeHandle: View {
    @Binding var height: CGFloat
    var range: ClosedRange<CGFloat>
    @State private var start: CGFloat?

    var body: some View {
        Divider()
            .overlay {
                Color.clear
                    .frame(height: 8)
                    .contentShape(Rectangle())
                    .onHover { inside in
                        if inside { NSCursor.resizeUpDown.push() } else { NSCursor.pop() }
                    }
                    .gesture(
                        DragGesture(minimumDistance: 1, coordinateSpace: .global)
                            .onChanged { value in
                                let base = start ?? height
                                if start == nil { start = height }
                                height = min(max(base - value.translation.height, range.lowerBound), range.upperBound)
                            }
                            .onEnded { _ in start = nil }
                    )
            }
    }
}
