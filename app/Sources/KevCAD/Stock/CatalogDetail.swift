import AppKit
import KevCADCore
import SwiftUI

/// Details eines Lagerteils: Maße, Werkstoff, Lieferform, Preis, Ebene; unten die Aktionen.
struct CatalogItemDetail: View {
    @ObservedObject var model: AppModel
    let item: CatalogItem
    let catalog: Catalog
    var onEdit: () -> Void
    var onCopy: () -> Void
    var onDelete: () -> Void
    var onApprove: () -> Void

    private var entry: JSONValue { item.entry }
    private var art: CatalogSchema.Art { CatalogSchema.art(item.art) }
    private var material: CatalogMaterial? { catalog.material(item.material) }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    DetailHeader(
                        title: item.name, id: item.id, level: item.ebene, suggested: item.vorgeschlagen,
                        subtitle: [art.title, item.norm].compactMap { $0 }.joined(separator: " · ")
                    ) {
                        ArtTile(art: item.art, size: 44)
                    }
                }
                Section {
                    ForEach(measureRows, id: \.key) { row in
                        LabeledContent(row.label) { Text(row.value).monospacedDigit().textSelection(.enabled) }
                    }
                    if !art.profile.isEmpty {
                        LabeledContent("Querschnitt") { Text(art.profile).foregroundStyle(.secondary) }
                    }
                } header: {
                    Text("Maße")
                }
                Section("Werkstoff") {
                    LabeledContent("Material") {
                        HStack(spacing: 6) {
                            MaterialSwatch(hex: material?.farbe)
                            Text(material?.name ?? item.material)
                        }
                    }
                    if let m = material {
                        LabeledContent("Dichte") { Text("\(KevFormat.compact(m.dichte)) g/cm³").monospacedDigit() }
                    }
                    if art.supply == .bar {
                        LabeledContent("Gewicht je Meter") {
                            if let kg = item.kgJeM {
                                Text("\(KevFormat.compact(kg)) kg/m").monospacedDigit()
                            } else {
                                Text("aus Querschnitt × Dichte").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section("Lieferform") {
                    switch art.supply {
                    case .bar:
                        LabeledContent("Stangenlänge") {
                            Text(entry["stangenlaenge"]?.doubleValue.map(KevFormat.length) ?? "–").monospacedDigit()
                        }
                    case .sheet:
                        LabeledContent("Standardformat") {
                            let f = (entry["platte"] ?? entry["masse"]?["platte"])?.doubles ?? []
                            Text(f.count == 2 ? "\(KevFormat.compact(f[0])) × \(KevFormat.compact(f[1])) mm" : "–")
                                .monospacedDigit()
                        }
                    case .piece:
                        LabeledContent("Stückware") { Text("Länge beim Verbauen").foregroundStyle(.secondary) }
                    }
                }
                Section {
                    LabeledContent("Preis") {
                        Text(item.preisText ?? "kein Preis").monospacedDigit()
                            .foregroundStyle(item.preisText == nil ? .secondary : .primary)
                    }
                    if let q = entry["preis"]?["quelle"]?.lenientString { LabeledContent("Quelle", value: q) }
                    if let s = entry["preis"]?["stand"]?.lenientString { LabeledContent("Stand", value: s) }
                } header: {
                    Text("Preis")
                } footer: {
                    Text("Richtwert netto; die Stückliste kennzeichnet Summen daraus als Richtpreis.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !item.tags.isEmpty {
                    Section("Suchbegriffe") {
                        Text(item.tags.joined(separator: ", ")).foregroundStyle(.secondary)
                    }
                }
                RawJSONSection(json: item.json)
            }
            .formStyle(.grouped)
            DetailActions(level: item.ebene, suggested: item.vorgeschlagen, model: model, entryID: item.id,
                          kindTitle: "Teil", onEdit: onEdit, onCopy: onCopy, onDelete: onDelete, onApprove: onApprove)
        }
    }

    /// Maße in der Reihenfolge der Art, unbekannte dahinter.
    private var measureRows: [(key: String, label: String, value: String)] {
        let masse = entry["masse"]?.objectValue ?? [:]
        let known = art.fields.map(\.key).filter { masse[$0] != nil }
        let rest = masse.keys.filter { !known.contains($0) && $0 != "platte" }.sorted()
        return (known + rest).map { key in
            (key, CatalogSchema.measureLabel(key, art: item.art),
             CatalogSchema.measureValue(masse[key] ?? .null, key: key, art: item.art))
        }
    }
}

/// Details eines Materials.
struct CatalogMaterialDetail: View {
    @ObservedObject var model: AppModel
    let material: CatalogMaterial
    let catalog: Catalog
    var onEdit: () -> Void
    var onCopy: () -> Void
    var onDelete: () -> Void
    var onApprove: () -> Void

    private var entry: JSONValue { material.entry }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    DetailHeader(
                        title: material.name, id: material.id, level: material.ebene, suggested: material.vorgeschlagen,
                        subtitle: material.gruppe
                    ) {
                        MaterialSwatch(hex: material.farbe, size: 44)
                    }
                }
                Section("Eigenschaften") {
                    LabeledContent("Gruppe", value: material.gruppe.isEmpty ? "–" : material.gruppe)
                    LabeledContent("Dichte") { Text("\(KevFormat.compact(material.dichte)) g/cm³").monospacedDigit() }
                    LabeledContent("Farbe") {
                        HStack(spacing: 6) {
                            MaterialSwatch(hex: material.farbe)
                            Text(material.farbe).font(.body.monospaced()).textSelection(.enabled)
                        }
                    }
                    if let v = entry["metallisch"]?.doubleValue {
                        LabeledContent("Metallisch") { Text(KevFormat.compact(v, maxDigits: 2)).monospacedDigit() }
                    }
                    if let v = entry["rauheit"]?.doubleValue {
                        LabeledContent("Rauheit") { Text(KevFormat.compact(v, maxDigits: 2)).monospacedDigit() }
                    }
                    LabeledContent("3D-Druck") {
                        if material.druckbar {
                            Label("druckbar", systemImage: "printer.fill").foregroundStyle(.teal)
                        } else {
                            Text("nein").foregroundStyle(.secondary)
                        }
                    }
                }
                Section(material.druckbar ? "Filamentpreis" : "Preis") {
                    LabeledContent("Preis je kg") {
                        Text(material.preisJeKg.map { "\(KevFormat.number($0, digits: 2)) €/kg" } ?? "kein Preis")
                            .monospacedDigit()
                    }
                    if let q = entry["preis_quelle"]?.lenientString { LabeledContent("Quelle", value: q) }
                    if let s = entry["preis_stand"]?.lenientString { LabeledContent("Stand", value: s) }
                }
                if let aliases = entry["aliase"]?.stringList, !aliases.isEmpty {
                    Section {
                        Text(aliases.joined(separator: ", ")).foregroundStyle(.secondary)
                    } header: {
                        Text("Weitere Namen")
                    } footer: {
                        Text("Auch so lässt sich das Material in model.py angeben (material=…).")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                let users = catalog.items.filter { $0.material == material.id }
                if !users.isEmpty {
                    Section("Verwendet von") {
                        Text(users.prefix(6).map(\.name).joined(separator: ", ")
                            + (users.count > 6 ? " und \(users.count - 6) weiteren" : ""))
                            .foregroundStyle(.secondary)
                    }
                }
                RawJSONSection(json: material.json)
            }
            .formStyle(.grouped)
            DetailActions(level: material.ebene, suggested: material.vorgeschlagen, model: model, entryID: material.id,
                          kindTitle: "Material", onEdit: onEdit, onCopy: onCopy, onDelete: onDelete, onApprove: onApprove)
        }
    }
}

// MARK: - Bausteine

private struct DetailHeader<Icon: View>: View {
    var title: String
    var id: String
    var level: CatalogLevel
    var suggested = false
    var subtitle: String
    @ViewBuilder var icon: Icon

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            icon
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.title3.weight(.semibold))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 6) {
                    if suggested { SuggestionBadge() }
                    LevelBadge(level: level)
                    if !subtitle.isEmpty {
                        Text(subtitle).foregroundStyle(.secondary)
                    }
                }
                .font(.callout)
                Text(id)
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }
}

/// Der Eintrag so, wie er im Katalog steht.
private struct RawJSONSection: View {
    let json: Data
    @State private var open = false

    private var pretty: String {
        guard let obj = try? JSONSerialization.jsonObject(with: json),
              let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys,
                                                                                   .withoutEscapingSlashes])
        else { return String(decoding: json, as: UTF8.self) }
        return String(decoding: data, as: UTF8.self)
    }

    var body: some View {
        Section {
            DisclosureGroup("Eintrag als JSON", isExpanded: $open) {
                VStack(alignment: .trailing, spacing: 6) {
                    Text(pretty)
                        .font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button("Kopieren") { copyToPasteboard(pretty) }
                        .controlSize(.small)
                }
                .padding(.top, 4)
            }
        }
    }
}

/// Aktionsleiste unten in den Details.
private struct DetailActions: View {
    let level: CatalogLevel
    var suggested = false
    @ObservedObject var model: AppModel
    let entryID: String
    let kindTitle: String
    var onEdit: () -> Void
    var onCopy: () -> Void
    var onDelete: () -> Void
    var onApprove: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            if suggested {
                Button(role: .destructive, action: onDelete) {
                    Label("Ablehnen …", systemImage: "xmark")
                }
                Text("Von Claude vorgeschlagen")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Button("Ändern …", action: onEdit)
                    .help("Vor dem Freigeben anpassen; Sichern gibt den Eintrag frei")
                    .disabled(!level.isEditable)
                Button(action: onApprove) {
                    Label("Freigeben", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
                .help("Eintrag freigeben (status frei), danach steht er wie jeder andere im Katalog")
            } else if level.isEditable {
                Button(role: .destructive, action: onDelete) {
                    Label("Löschen …", systemImage: "trash")
                }
                status
                Spacer(minLength: 8)
                Button("Duplizieren …", action: onCopy)
                Button("Bearbeiten …", action: onEdit)
                    .buttonStyle(.borderedProminent)
            } else {
                Label("Mitgeliefert, nur ansehen", systemImage: "lock")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Button(action: onCopy) {
                    Label("Als eigenes \(kindTitle) kopieren …", systemImage: "doc.on.doc")
                }
                .buttonStyle(.borderedProminent)
                .help("Kopie im eigenen Katalog anlegen, z. B. mit eigenem Preis")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    @ViewBuilder
    private var status: some View {
        if case .saved(let id, let message) = model.catalogActivity, id == entryID {
            Label("Gespeichert" + (message.map { " · \($0)" } ?? ""), systemImage: "checkmark.circle.fill")
                .font(.callout)
                .foregroundStyle(.green)
                .lineLimit(1)
        }
    }
}
