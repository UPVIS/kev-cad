import AppKit
import KevCADCore
import SwiftUI
import simd

/// Inspektor rechts: Auswahl mit Werten, Teileigenschaften, Liste der Messungen.
struct InspectorView: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    /// Phase 4: für die Dialoge der Referenzen (nil in Vorschauen)
    var state: ProjectWindowState?
    @Environment(\.materialNavigation) private var materialNavigation

    var body: some View {
        Form {
            CameraInspectorSection(store: model.cameras, actions: model.cameraActions)  // Phase 5: Kameras
            selectionSection
            propertiesSection
            stockSection
            ZukaufInspectorSection(model: model)
            ConstraintsSection(model: model)
            if let state {  // Phase 4: Referenzen aus Video und Fotos
                ReferenzInspectorSection(model: model, store: model.referenzen, state: state)
            }
            StatikAbschnitt(store: model.statik, actions: model.statikActions,
                            oeffnen: state.map { st in { SimulationOeffnen.lastfall(model, st) } })  // Statik
            TopologieAbschnitt(model: model, store: model.topologie, statik: model.statik,
                               actions: model.topologieActions,
                               oeffnen: state.map { st in { teil in SimulationOeffnen.topologie(model, st, teil) } })
            measurementsSection
            projectSection
        }
        .formStyle(.grouped)
    }

    // MARK: Auswahl

    private var selectionSection: some View {
        Section {
            if model.selection.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Nichts ausgewählt")
                    Text("Teil, Fläche oder Kante im Viewport oder im Teilebaum anklicken.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 2)
            } else {
                ForEach(model.selection.prefix(6)) { item in
                    SelectionRow(item: item)
                }
                if model.selection.count > 6 {
                    Text("und \(KevFormat.integer(model.selection.count - 6)) weitere")
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            HStack {
                Text("Auswahl")
                Spacer()
                if !model.selection.isEmpty {
                    Button("Aufheben") { model.clearSelection() }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .help("Auswahl aufheben (Esc)")
                }
            }
        }
    }

    // MARK: Teileigenschaften

    private var selectedParts: [PartNode] {
        let ids = Set(model.selectedPartIDs)
        return model.parts.filter { ids.contains($0.id) }
    }

    @ViewBuilder
    private var propertiesSection: some View {
        let parts = selectedParts
        if parts.count == 1, let part = parts.first {
            Section {
                PropertyRow("Name", part.id)
                PropertyRow("Hüllmaße", KevFormat.dimensions(min: part.bboxMin, max: part.bboxMax))
                PropertyRow("Volumen", part.volume.map { KevFormat.volume(mm3: $0) } ?? "–")
                if let f = model.druckFilament(teil: part.id) {
                    // Strang „Feinschliff 2“: Druckteile mit Filament (gedruckt) und Vollkörper, gleich benannt wie im
                    // Bereich „Material“
                    PropertyRow("Filament", "\(KevFormat.mass(grams: f.gramm)) (gedruckt, \(f.stand.titel))")
                    PropertyRow("Vollkörper", part.mass.map { KevFormat.mass(grams: $0) } ?? "–")
                } else {
                    PropertyRow("Masse", part.mass.map { KevFormat.mass(grams: $0) } ?? "– (ohne Material)")
                }
                PropertyRow("Material", model.materialTitle(for: part) ?? "–")
                PropertyRow("Dreiecke", KevFormat.integer(part.triangles))
                PropertyRow("Flächen · Kanten", "\(KevFormat.integer(part.faces)) · \(KevFormat.integer(part.edges))")
                if !part.visible {
                    Label("Ausgeblendet", systemImage: "eye.slash").foregroundStyle(.secondary)
                }
            } header: {
                HStack(spacing: 6) {
                    RoundedRectangle(cornerRadius: 3).fill(Color(part: part.color)).frame(width: 10, height: 10)
                    Text("Teil · \(part.name)")
                }
            } footer: {
                Text("Hüllmaße als L × B × H entlang X, Y, Z.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } else {
            let group = parts.isEmpty ? model.parts : parts
            if !group.isEmpty {
                Section(parts.isEmpty ? "Modell" : "\(KevFormat.integer(parts.count)) Teile") {
                    PropertyRow("Teile", KevFormat.integer(group.count))
                    PropertyRow("Hüllmaße", Self.dimensions(of: group))
                    PropertyRow("Volumen", Self.sum(group.map(\.volume)).map { KevFormat.volume(mm3: $0) } ?? "–")
                    PropertyRow("Masse", Self.massText(group))
                    PropertyRow("Dreiecke", KevFormat.integer(group.reduce(0) { $0 + $1.triangles }))
                }
            }
        }
    }

    // MARK: Projekt (Phase 2: Inventar-Regel)

    @ViewBuilder
    private var projectSection: some View {
        if model.project != nil {
            Section {
                Toggle(isOn: Binding(
                    get: { model.inventarRegel }, set: { model.inventoryActions?.setInventarRegel($0) }
                )) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Inventar-Regel")
                        Text(model.inventarRegel
                            ? "Nur Lagerteile und gekennzeichnete 3D-Druckteile, Materialien aus dem Katalog"
                            : "Aus: frei modellierte Teile erscheinen als Eigenteile")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .disabled(model.inventoryActions == nil)
            } header: {
                Text("Projekt")
            } footer: {
                Text("Aus nur für Nachbauten und Skizzen. Claude kann die Regel nicht umschalten.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: Lagerteil (Phase 2)

    @ViewBuilder
    private var stockSection: some View {
        let parts = selectedParts
        if parts.count == 1, let part = parts.first, part.inventarFehlt {
            Section {
                Label {
                    Text("Weder verbautes Lagerteil noch gekennzeichnetes 3D-Druckteil. Claude soll ein passendes "
                        + "Lagerteil verbauen oder vorschlagen.")
                        .fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
                Button {
                    session.showCatalog(section: (model.catalog?.suggestionCount ?? 0) > 0 ? .suggestions : nil)
                } label: {
                    Label("Lagerkatalog öffnen", systemImage: "books.vertical")
                }
                .controlSize(.small)
            } header: {
                Text("Nicht aus dem Inventar")
            }
        }
        if parts.count == 1, let part = parts.first, let stock = part.stock {
            Section {
                PropertyRow("Lagerteil", stock.name)
                if let laenge = stock.laenge { PropertyRow("Zuschnitt", KevFormat.length(laenge)) }
                let miter = KevFormat.gehrung(stock.gehrung)
                PropertyRow("Gehrung", miter == "–" ? "gerade" : miter)
                PropertyRow(MaterialText.Spalte.werkstoff, model.materialName(stock.material) ?? "–")
                PropertyRow(MaterialText.Spalte.gewicht, stock.kg.map(KevFormat.kg) ?? "–")
                PropertyRow(MaterialText.Spalte.preis, stock.preis.map { "\(KevFormat.euro($0)) (Richtpreis)" } ?? "–")
                HStack {
                    Button {
                        session.showCatalog(focus: .item(stock.id))
                    } label: {
                        Label("Im Lagerkatalog zeigen", systemImage: "books.vertical")
                    }
                    .disabled(stock.id.isEmpty)
                    if let materialNavigation, let line = model.bomLine(for: part.id) {
                        Button {
                            materialNavigation.zeige(.stueckliste, line.pos, stock.id)
                        } label: {
                            Label("In Material zeigen", systemImage: "shippingbox")
                        }
                        .help("Position \(line.pos) im Bereich Material: Stückliste, Zuschnitt, Bestand (⌘3)")
                    }
                }
                .controlSize(.small)
            } header: {
                HStack(spacing: 6) {
                    Image(systemName: "shippingbox").foregroundStyle(.secondary)
                    Text("Lagerteil")
                }
            } footer: {
                if let line = model.bomLine(for: part.id) {
                    Text("Stückliste Pos. \(line.pos): \(KevFormat.count(line.anzahl, one: "Stück", many: "Stück")) "
                        + "\(line.masseText)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text(stock.id)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
        }
    }

    static func dimensions(of parts: [PartNode]) -> String {
        guard let first = parts.first else { return "–" }
        var lo = first.bboxMin
        var hi = first.bboxMax
        for part in parts.dropFirst() {
            lo = simd_min(lo, part.bboxMin)
            hi = simd_max(hi, part.bboxMax)
        }
        return KevFormat.dimensions(min: lo, max: hi)
    }

    static func sum(_ values: [Double?]) -> Double? {
        let known = values.compactMap { $0 }
        return known.isEmpty ? nil : known.reduce(0, +)
    }

    static func massText(_ parts: [PartNode]) -> String {
        guard let total = sum(parts.map(\.mass)) else { return "– (ohne Material)" }
        let missing = parts.filter { $0.mass == nil }.count
        let text = KevFormat.mass(grams: total)
        return missing > 0 ? "\(text) (ohne \(missing) Teile)" : text
    }

    // MARK: Messungen

    private var measurementsSection: some View {
        Section {
            if model.measurements.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Keine Messungen")
                    Text("M schaltet Messen ein. Ein Element zeigt seine Werte, zwei Elemente Abstand oder Winkel.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if !model.measureMode {
                        Button("Messen einschalten") { model.actions?.setMeasureMode(true) }
                            .controlSize(.small)
                            .padding(.top, 2)
                    }
                }
                .padding(.vertical, 2)
            } else {
                ForEach(model.measurements) { item in
                    MeasurementRow(item: item, model: model)
                }
            }
        } header: {
            HStack {
                Text("Messungen")
                if !model.measurements.isEmpty {
                    Text(KevFormat.integer(model.measurements.count))
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if !model.measurements.isEmpty {
                    Button("Alle löschen") { model.actions?.clearMeasurements() }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                }
            }
        }
    }
}

/// Bezeichnung links, Wert rechts, Zahlen mit fester Ziffernbreite.
private struct PropertyRow: View {
    var label: String
    var value: String
    var monospaced = false

    init(_ label: String, _ value: String, monospaced: Bool = false) {
        self.label = label
        self.value = value
        self.monospaced = monospaced
    }

    var body: some View {
        LabeledContent(label) {
            Text(value)
                .font(monospaced ? .body.monospaced() : .body)
                .monospacedDigit()
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }
}

/// Ein ausgewähltes Element: Kurzbeschreibung, Referenz, Sofortwerte.
private struct SelectionRow: View {
    var item: SelectionItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: Self.symbol(for: item.ref))
                    .foregroundStyle(.tint)
                    .frame(width: 16)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.summary)
                        .fontWeight(.medium)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(item.ref)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            let values = KevFormat.labeledValues(item.values)
            if !values.isEmpty {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 3) {
                    ForEach(values) { value in
                        GridRow {
                            Text(value.label)
                                .foregroundStyle(.secondary)
                            Text(value.value)
                                .monospacedDigit()
                                .textSelection(.enabled)
                                .gridColumnAlignment(.trailing)
                                .frame(maxWidth: .infinity, alignment: .trailing)
                        }
                    }
                }
                .font(.callout)
                .padding(.leading, 22)
            }
        }
        .padding(.vertical, 2)
        .contextMenu {
            Button("Referenz kopieren") { copy(item.ref) }
            Button("Werte kopieren") {
                copy(([item.summary] + KevFormat.labeledValues(item.values).map { "\($0.label): \($0.value)" })
                    .joined(separator: "\n"))
            }
        }
    }

    /// Teil, Fläche (#f), Kante (#e) oder Punkt (#v), siehe PROTOCOL.md Referenzen.
    static func symbol(for ref: String) -> String {
        guard let hash = ref.firstIndex(of: "#") else { return "cube" }
        switch ref[ref.index(after: hash)...].first {
        case "f": return "square.fill"
        case "e": return "line.diagonal"
        case "v": return "circle.circle"
        default: return "cube"
        }
    }
}

/// Eine Messung mit Text, Referenzen und Löschknopf.
private struct MeasurementRow: View {
    var item: MeasurementItem
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: item.kind == "angle" ? "angle" : "ruler")
                .foregroundStyle(.orange)
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.text)
                    .monospacedDigit()
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                Text(item.refs.joined(separator: " ↔ "))
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer(minLength: 4)
            if model.canRemoveSingleMeasurement {
                Button {
                    model.removeMeasurement(item.id)
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.tertiary)
                }
                .buttonStyle(.borderless)
                .help("Messung löschen")
            }
        }
        .padding(.vertical, 2)
        .contextMenu {
            Button("Text kopieren") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(item.text, forType: .string)
            }
            if model.canRemoveSingleMeasurement {
                Button("Löschen") { model.removeMeasurement(item.id) }
            }
            Button("Alle löschen") { model.actions?.clearMeasurements() }
        }
    }
}

private func copy(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}

extension AppModel {
    /// Filament eines Druckteils aus der Druckvorschau desselben Laufs (je Stück seiner Gruppe); nil ohne Vorschau,
    /// für andere Teile und für schon gedruckte.
    func druckFilament(teil: String) -> DruckFilamentWert? {
        guard let v = druck.vorschau, let bom, v.run == bom.run,
              let line = bom.lines.first(where: { $0.teile.contains(teil) }), line.druckteil, !line.gedruckt
        else { return nil }
        return DruckFilamentWert.aus(v, teile: [teil])
    }
}
