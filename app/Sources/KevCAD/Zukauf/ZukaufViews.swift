import AppKit
import KevCADCore
import SwiftUI

// Phase 3: Zukaufteile im Inspektor, in der Stückliste und im Lagerkatalog.

// MARK: - Inspektor

/// Abschnitt „Zukaufteil“ im Inspektor: Hersteller, Nummer, Preis mit Datum, Link, CAD-Quelle und Zustand.
struct ZukaufInspectorSection: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel

    var body: some View {
        let ids = Set(model.selectedPartIDs)
        let parts = model.parts.filter { ids.contains($0.id) }
        if parts.count == 1, let part = parts.first, let z = part.zukauf {
            content(part: part, z: z)
        }
    }

    @ViewBuilder
    private func content(part: PartNode, z: ZukaufPartInfo) -> some View {
        let item = model.catalog?.item(z.id)
        let info = item?.zukaufInfo
        let line = model.bomLine(for: part.id)?.zukauf
        let status = model.zukaufStatus(for: z.id)
        let url = z.url ?? info?.url ?? line?.url
        Section {
            HStack(spacing: 10) {
                ZukaufImage(url: info?.bild ?? line?.bild, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item?.name ?? model.bomLine(for: part.id)?.benennung ?? z.title)
                        .fontWeight(.medium)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    CADSourceBadge(simplified: z.isSimplified)
                }
            }
            .padding(.vertical, 2)
            InfoRow("Hersteller", z.hersteller ?? info?.hersteller ?? line?.hersteller ?? "–")
            InfoRow("Nummer", z.mpn ?? info?.number ?? line?.mpn ?? "–", monospaced: true)
            if let gtin = info?.gtin ?? line?.gtin { InfoRow("EAN", gtin, monospaced: true) }
            InfoRow("Preis", priceText(z: z, info: info, line: line))
            if let url {
                LabeledContent("Link") {
                    Link(destination: url) {
                        Text(ZukaufInput.shopName(url))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    .help(url.absoluteString)
                }
            }
            InfoRow("CAD-Quelle", cadText(z: z, info: info, line: line))
            if let status { ZukaufStatusLabel(status: status) }
            HStack(spacing: 8) {
                if let status, status.isWaiting { CADSearchButton(links: status.cadLinks) }
                if z.isSimplified {
                    Button("CAD-Datei wählen …") { session.chooseCADFile(for: z.id) }
                        .help("Hersteller-STEP selbst auswählen; ersetzt den Ersatzkörper")
                }
                Button {
                    session.showCatalog(focus: .item(z.id))
                } label: {
                    Label("Im Lagerkatalog", systemImage: "books.vertical")
                }
                .disabled(z.id.isEmpty)
            }
            .controlSize(.small)
        } header: {
            HStack(spacing: 6) {
                Image(systemName: ZukaufSymbol.name(simplified: z.isSimplified)).foregroundStyle(.secondary)
                Text("Zukaufteil")
            }
        } footer: {
            if z.isSimplified {
                Text("Ersatzkörper aus den Shop-Maßen (halbtransparent). Mit dem Hersteller-CAD wird er beim nächsten "
                    + "Lauf ersetzt.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func priceText(z: ZukaufPartInfo, info: ZukaufEntryInfo?, line: ZukaufBOMInfo?) -> String {
        guard let preis = z.preis ?? info?.preis else { return "–" }
        let brutto = info?.brutto ?? line?.preisBrutto
        let stand = ZukaufDate.display(info?.preisStand ?? line?.preisStand)
        var text = KevFormat.euro(preis)
        if let brutto { text += brutto ? " brutto" : " netto" }
        if let stand { text += " · \(stand)" }
        return text
    }

    private func cadText(z: ZukaufPartInfo, info: ZukaufEntryInfo?, line: ZukaufBOMInfo?) -> String {
        if z.isSimplified { return "vereinfacht (Ersatzkörper)" }
        if let info, info.cadQuelle != nil { return info.cadTitle }
        if let line, line.cadQuelle != nil { return line.cadTitle }
        return z.cad.title
    }
}

/// Bezeichnung links, Wert rechts (wie im Inspektor).
struct InfoRow: View {
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

// MARK: - Stückliste

/// Unter der Stückliste: je Zukaufteil Bild, Hersteller und Nummer, Stückpreis mit Datum, CAD-Quelle und Link.
struct BOMZukaufList: View {
    @ObservedObject var model: AppModel
    let lines: [BOMLine]
    var selected: Int?
    var onSelect: (BOMLine) -> Void
    @Environment(\.openURL) private var openURL

    private var height: CGFloat { min(CGFloat(lines.count) * 46 + 30, 176) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Image(systemName: "cart").foregroundStyle(.secondary)
                Text("Zukaufteile").fontWeight(.semibold)
                Text("· Stückpreise wie im Shop, mit Datum").foregroundStyle(.secondary)
                Spacer()
                if lines.contains(where: { $0.zukauf?.vereinfacht == true }) {
                    Label("vereinfachte Teile sind Ersatzkörper", systemImage: "cube.transparent")
                        .foregroundStyle(.orange)
                        .help("Für diese Teile fehlt noch das Hersteller-CAD; im Modell stehen Quader oder Zylinder aus den Shop-Maßen")
                }
            }
            .font(.callout)
            .lineLimit(1)
            .padding(.horizontal, 12)
            .padding(.top, 7)
            .padding(.bottom, 4)
            ScrollView(.vertical) {
                VStack(spacing: 2) {
                    ForEach(lines) { line in
                        row(line)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 6)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .frame(height: height)
    }

    private func row(_ line: BOMLine) -> some View {
        let z = line.zukauf ?? ZukaufBOMInfo()
        return HStack(spacing: 10) {
            ZukaufImage(url: z.bild, size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text(line.benennung).fontWeight(.medium).lineLimit(1)
                Text(([z.title.isEmpty ? nil : z.title, z.gtin.map { "EAN \($0)" }, "Pos. \(line.pos)"] as [String?])
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(line.preisJe.map { "\(KevFormat.euro($0)) / Stück" } ?? "ohne Preis")
                    .monospacedDigit()
                    .foregroundStyle(line.preisJe == nil ? .secondary : .primary)
                Text(([z.preisBrutto.map { $0 ? "brutto" : "netto" }, ZukaufDate.display(z.preisStand).map { "Stand \($0)" }]
                    as [String?]).compactMap { $0 }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 130, alignment: .trailing)
            CADSourceBadge(simplified: z.vereinfacht, title: z.vereinfacht ? "vereinfacht" : z.cadTitle)
                .frame(minWidth: 96, alignment: .leading)
            Button {
                if let url = z.url { openURL(url) }
            } label: {
                Label("Shop", systemImage: "arrow.up.right.square")
            }
            .controlSize(.small)
            .disabled(z.url == nil)
            .help(z.url?.absoluteString ?? "kein Link")
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(selected == line.pos ? Color.accentColor.opacity(0.14) : Color.clear)
        )
        .contentShape(Rectangle())
        .onTapGesture { onSelect(line) }
        .contextMenu {
            if let url = z.url {
                Button("Produktseite öffnen") { openURL(url) }
                Button("Link kopieren") { copyToPasteboard(url.absoluteString) }
            }
            if let mpn = z.mpn { Button("Nummer kopieren") { copyToPasteboard(mpn) } }
        }
    }
}

// MARK: - Lagerkatalog

/// Zeile eines Zukaufteils in der Liste des Lagerkatalogs.
struct ZukaufItemRow: View {
    @ObservedObject var model: AppModel
    let item: CatalogItem

    var body: some View {
        let info = item.zukaufInfo ?? ZukaufEntryInfo(entry: item.entry)
        let status = model.zukaufStatus(for: item.id)
        HStack(spacing: 10) {
            ZukaufImage(url: info.bild, size: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.name)
                    .fontWeight(.medium)
                    .lineLimit(1)
                Text(([info.hersteller, info.number, info.masseText == "–" ? nil : info.masseText] as [String?])
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 6)
            VStack(alignment: .trailing, spacing: 3) {
                Text(info.preisText ?? "–")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(info.preisText == nil ? .tertiary : .primary)
                Group {
                    if item.vorgeschlagen {
                        SuggestionBadge()
                    } else if let status, status.isWaiting {
                        Badge(text: "wartet auf CAD", color: .orange)
                    } else {
                        CADSourceBadge(simplified: info.isSimplified, title: info.isSimplified ? "vereinfacht" : "CAD")
                    }
                }
                .fixedSize()
            }
        }
        .padding(.vertical, 3)
    }
}

/// Details eines Zukaufteils im Lagerkatalog.
struct ZukaufCatalogDetail: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    let item: CatalogItem
    var onDelete: () -> Void
    var onApprove: () -> Void
    @Environment(\.openURL) private var openURL

    var body: some View {
        let info = item.zukaufInfo ?? ZukaufEntryInfo(entry: item.entry)
        let status = model.zukaufStatus(for: item.id)
        VStack(spacing: 0) {
            Form {
                Section {
                    HStack(alignment: .center, spacing: 14) {
                        ZukaufImage(url: info.bild, size: 72)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.name)
                                .font(.title3.weight(.semibold))
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                            HStack(spacing: 6) {
                                if item.vorgeschlagen { SuggestionBadge() }
                                LevelBadge(level: item.ebene)
                                CADSourceBadge(simplified: info.isSimplified)
                            }
                            .font(.callout)
                            Text(item.id)
                                .font(.caption.monospaced())
                                .foregroundStyle(.tertiary)
                                .textSelection(.enabled)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 4)
                }
                Section("Produkt") {
                    InfoRow("Hersteller", info.hersteller ?? "–")
                    InfoRow("Herstellernummer", info.mpn ?? "–", monospaced: true)
                    if let nr = info.shopNr { InfoRow("Shop-Nummer", nr, monospaced: true) }
                    if let g = info.gtin { InfoRow("EAN", g, monospaced: true) }
                    if let url = info.url {
                        LabeledContent("Link") {
                            Link(ZukaufInput.shopName(url), destination: url).help(url.absoluteString)
                        }
                    }
                }
                Section {
                    InfoRow("Preis je Stück", info.preisText ?? "kein Preis")
                    if let s = ZukaufDate.display(info.preisStand) { InfoRow("Stand", s) }
                    if let q = info.preisQuelle { InfoRow("Quelle", q) }
                } header: {
                    Text("Preis")
                } footer: {
                    Text("So, wie der Shop ihn angibt (brutto oder netto); Preise veralten.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("Maße") {
                    InfoRow("Hüllmaße", info.masseText)
                    InfoRow("Ersatzkörper", info.form.title)
                    if let g = info.gewicht { InfoRow("Gewicht", KevFormat.mass(grams: g)) }
                    if !item.material.isEmpty { InfoRow("Material", model.materialName(item.material) ?? item.material) }
                }
                Section {
                    InfoRow("Quelle", info.cadTitle)
                    if let d = info.cadDatei { InfoRow("Datei", d, monospaced: true) }
                    if let s = ZukaufDate.display(info.cadStand) { InfoRow("Stand", s) }
                    if let l = info.cadLizenz { InfoRow("Lizenz", l) }
                    if let status {
                        ZukaufStatusLabel(status: status)
                        if let t = status.text { Text(t).font(.callout).foregroundStyle(.secondary) }
                    }
                    HStack {
                        if let status, status.isWaiting { CADSearchButton(links: status.cadLinks) }
                        if info.isSimplified || status?.isWaiting == true {
                            Button("CAD-Datei wählen …") { session.chooseCADFile(for: item.id) }
                        }
                    }
                    .controlSize(.small)
                } header: {
                    Text("CAD")
                } footer: {
                    Text("Hersteller-CAD liegt nur im Projektordner, nie im Git (Bedingungen der Hersteller).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let h = info.hinweis {
                    Section("Hinweis") { Text(h).foregroundStyle(.secondary) }
                }
            }
            .formStyle(.grouped)
            actions(info)
        }
    }

    private func actions(_ info: ZukaufEntryInfo) -> some View {
        HStack(spacing: 10) {
            if item.vorgeschlagen {
                Button(role: .destructive, action: onDelete) {
                    Label("Ablehnen …", systemImage: "xmark")
                }
                Text("Von Claude vorgeschlagen")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Button("Prüfen …") { session.showZukaufDialog(for: item, mode: .confirm) }
                    .help("Felder im Dialog prüfen und ändern; Freigeben speichert den Eintrag")
                Button(action: onApprove) {
                    Label("Freigeben", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
            } else if item.ebene.isEditable {
                Button(role: .destructive, action: onDelete) {
                    Label("Löschen …", systemImage: "trash")
                }
                Spacer(minLength: 8)
                if let url = info.url {
                    Button("Produktseite") { openURL(url) }
                }
                Button("Bearbeiten …") { session.showZukaufDialog(for: item, mode: .edit) }
                    .buttonStyle(.borderedProminent)
            } else {
                Label("Mitgeliefert, nur ansehen", systemImage: "lock")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }
}
