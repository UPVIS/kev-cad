import AppKit
import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

/// Abschnitt „Einkaufsliste“ im Bereich „Material“: Lagerware nach Abzug des Projektbestands und Zukaufteile, zum
/// Abhaken (je Projekt gemerkt), mit Preis, Stand und Bezugsquelle. Teilen als Text oder CSV, Kopieren, CSV in output/.
/// Darunter die Normteile zum Abzählen und das Filament der Druckteile.
struct MaterialEinkaufAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten
    var navigation: MaterialNavigation?

    private var k: MaterialKennzahlen { daten.kennzahlen }

    private var gefiltert: [MaterialEinkauf] {
        let q = material.suche.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return daten.einkauf }
        return daten.einkauf.filter {
            ($0.position.benennung + " " + $0.position.id + " " + ($0.position.hinweis ?? "")).lowercased().contains(q)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            MaterialAbschnittKopf(titel: MaterialAbschnitt.einkauf.titel, symbol: MaterialAbschnitt.einkauf.symbol,
                                  zeile: kennzeile) {
                EinkaufTeilenMenue(model: model, material: material, daten: daten)
                Button {
                    navigation?.bericht(.einkaufsliste)
                } label: {
                    Label("Als Bericht drucken", systemImage: "printer")
                }
                .disabled(navigation == nil)
                .help("Druckfassung in „Dokumente“ › Berichte: Einkaufsliste zum Abhaken")
            }
            Divider()
            inhalt
            if !daten.einkauf.isEmpty { fuss }
        }
        .onAppear { material.ladeAbgehakt(model.project?.path) }
        .onChange(of: model.project?.path) { _, p in material.ladeAbgehakt(p) }
    }

    private var kennzeile: String {
        guard k.mitBestand || k.einkaufZukauf > 0 else { return "Ohne Bestandsabgleich" }
        if daten.einkauf.isEmpty { return "Nichts zu kaufen: alles ist im Bestand des Projekts" }
        let offen = material.abgehakt.offen(daten.einkauf).count
        return [KevFormat.count(daten.einkauf.count, one: "Position", many: "Positionen"),
                offen == 0 ? "alles abgehakt" : "\(offen) offen", "Summe " + k.einkaufText]
            .joined(separator: " · ")
    }

    @ViewBuilder
    private var inhalt: some View {
        if !k.mitBestand && daten.zukaufEinkauf.isEmpty {
            MaterialLeer(titel: "Noch keine Einkaufsliste", symbol: "cart",
                         text: "Sie entsteht nach dem Lauf aus dem Abgleich der Stückliste mit dem Bestand des Projekts.")
        } else {
            VStack(spacing: 0) {
                if daten.einkauf.isEmpty {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.seal.fill").foregroundStyle(MaterialKennzeichen.rest.color)
                        Text("Nichts zu kaufen: alles für dieses Modell ist im Bestand des Projekts.")
                    }
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 120)
                } else {
                    tabelle
                }
                if !daten.stueckgut.isEmpty || !daten.filament.isEmpty {
                    Divider()
                    HStack(alignment: .top, spacing: 14) {
                        if !daten.stueckgut.isEmpty {
                            StueckgutBlock(stueckgut: daten.stueckgut)
                                .padding(14)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(KachelGrund())
                        }
                        if !daten.filament.isEmpty { filament }
                    }
                    .padding(16)
                    .frame(maxHeight: 260)
                }
            }
        }
    }

    private var tabelle: some View {
        Table(of: MaterialEinkauf.self, selection: $material.einkaufAuswahl) {
            TableColumn("") { z in
                Toggle("", isOn: Binding(get: { material.abgehakt.abgehakt(z) }, set: { _ in material.umschalten(z) }))
                    .toggleStyle(.checkbox)
                    .labelsHidden()
                    .help(material.abgehakt.abgehakt(z) ? "Wieder offen" : "Abhaken: gekauft")
            }
            .width(22)
            TableColumn(MaterialText.Spalte.menge) { z in
                ZahlZelle(text: z.position.mengeText, hervor: true)
                    .opacity(material.abgehakt.abgehakt(z) ? 0.45 : 1)
            }
            .width(min: 44, ideal: 54, max: 70)
            TableColumn(MaterialText.Spalte.einheit) { z in
                Text(z.position.einheit).lineLimit(1).help(z.position.einheit)
                    .foregroundStyle(material.abgehakt.abgehakt(z) ? .secondary : .primary)
            }
            .width(min: 90, ideal: 140)
            TableColumn(MaterialText.Spalte.benennung) { z in
                EinkaufBenennung(model: model, zeile: z, abgehakt: material.abgehakt.abgehakt(z))
            }
            .width(min: 180, ideal: 300)
            TableColumn(MaterialText.Spalte.preisJe) { z in
                ZahlZelle(text: z.position.preisJe.map(KevFormat.euro) ?? "–")
            }
            .width(min: 60, ideal: 76)
            TableColumn(MaterialText.Spalte.preis) { z in
                ZahlZelle(text: z.position.preis.map(KevFormat.euro) ?? "–", hervor: true)
                    .help(preisHilfe(z))
            }
            .width(min: 64, ideal: 84)
            TableColumn(MaterialText.Spalte.stand) { z in
                Text(stand(z) ?? "–")
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            .width(min: 76, ideal: 88)
            TableColumn(MaterialText.Spalte.bezugsquelle) { z in
                if let link = z.position.link {
                    Link(destination: link) {
                        Label(z.position.linkTitel ?? link.absoluteString, systemImage: "arrow.up.right.square")
                            .lineLimit(1)
                    }
                    .help(link.absoluteString)
                } else {
                    Text("–").foregroundStyle(.tertiary)
                }
            }
            .width(min: 90, ideal: 130)
        } rows: {
            let lager = gefiltert.filter { $0.art == .lager }
            let zukauf = gefiltert.filter { $0.art == .zukauf }
            if !lager.isEmpty {
                Section {
                    ForEach(lager) { TableRow($0) }
                } header: {
                    EinkaufGruppenKopf(titel: "Lagerware", symbol: "shippingbox", zeilen: lager,
                                       hinweis: "nach Abzug des Projektbestands")
                }
            }
            if !zukauf.isEmpty {
                Section {
                    ForEach(zukauf) { TableRow($0) }
                } header: {
                    EinkaufGruppenKopf(titel: "Zukaufteile", symbol: "bag", zeilen: zukauf,
                                       hinweis: "Bestand wird noch nicht geführt")
                }
            }
        }
        .tableStyle(.inset)
        .alternatingRowBackgrounds()
        .contextMenu(forSelectionType: MaterialEinkauf.ID.self) { ids in
            let zeilen = daten.einkauf.filter { ids.contains($0.id) }
            if !zeilen.isEmpty {
                let alleAb = zeilen.allSatisfy { material.abgehakt.abgehakt($0) }
                Button(alleAb ? "Wieder offen" : "Abhaken") {
                    var a = material.abgehakt
                    a.setze(zeilen, !alleAb)
                    material.setzeAbgehakt(a)
                }
                Divider()
                Button(zeilen.count == 1 ? "Zeile kopieren" : "Zeilen kopieren") {
                    copyToPasteboard(MaterialText.einkaufText(zeilen, projekt: nil)
                        .split(separator: "\n").filter { $0.hasPrefix("- ") || $0.hasPrefix("  ") }.joined(separator: "\n"))
                }
                if zeilen.count == 1, let link = zeilen[0].position.link {
                    Button("Bezugsquelle öffnen") { NSWorkspace.shared.open(link) }
                    Button("Link kopieren") { copyToPasteboard(link.absoluteString) }
                }
                if zeilen.count == 1, zeilen[0].art == .lager, model.catalog?.item(zeilen[0].position.id) != nil {
                    Button("Im Lagerkatalog zeigen") { session.showCatalog(focus: .item(zeilen[0].position.id)) }
                }
                if zeilen.count == 1, let pos = zeilen[0].pos ?? daten.positionen.first(where: { $0.stockID == zeilen[0].position.id })?.pos {
                    Button("In der Stückliste zeigen") { material.zeige(.stueckliste, position: pos) }
                }
            }
        } primaryAction: { ids in
            for z in daten.einkauf where ids.contains(z.id) { material.umschalten(z) }
        }
    }

    /// Stand der Preise aus dem Hinweis der Stückliste („Richtpreise, Stand 2026-10“), nur für Lagerware.
    private var standText: String? { MaterialText.standAusHinweis(daten.einkaufHinweis ?? k.preisHinweis) }

    private func stand(_ z: MaterialEinkauf) -> String? {
        MaterialText.stand(z.position.stand) ?? (z.art == .lager ? standText : nil)
    }

    private func preisHilfe(_ p: EinkaufsPosition) -> String {
        guard p.preis != nil else { return "Kein Preis im Katalog" }
        var t = "\(p.mengeText) × \(p.preisJe.map(KevFormat.euro) ?? "–")"
        if let stand = MaterialText.stand(p.stand) ?? standText { t += ", Stand \(stand)" }
        return t + " (Richtpreis)"
    }

    private func preisHilfe(_ z: MaterialEinkauf) -> String {
        guard z.art == .lager else {
            return z.position.preis == nil ? "Kein Preis beim Zukaufteil" : "Preis wie im Shop (Zukaufteil)"
        }
        return preisHilfe(z.position)
    }

    private var filament: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "printer.fill").foregroundStyle(MaterialKennzeichen.druckteil.color)
                Text("Filament für Druckteile").fontWeight(.semibold)
            }
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 3) {
                ForEach(daten.filament) { f in
                    GridRow {
                        Text(f.werkstoff)
                        Text(KevFormat.count(f.teile, one: "Teil", many: "Teile")).foregroundStyle(.secondary)
                        Text(KevFormat.mass(grams: f.gramm)).fontWeight(.semibold).gridColumnAlignment(.trailing)
                        Text(f.preis.map(KevFormat.euro) ?? "–").foregroundStyle(.secondary).gridColumnAlignment(.trailing)
                    }
                    .monospacedDigit()
                    .help(f.quelleText)
                }
            }
            Text((daten.filament.first?.stand != nil ? "Aus der Druckvorschau. " : "Aus der Stückliste (Volumen × Dichte). ")
                 + "Spulen werden noch nicht im Bestand geführt.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .font(.body)
        .padding(14)
        .frame(maxWidth: 360, alignment: .leading)
        .background(KachelGrund())
    }

    private var fuss: some View {
        HStack(spacing: 14) {
            if let stand = daten.bestandStand {
                Text("Bestand vom \(BestandText.anzeige(stand) ?? stand)")
                    .foregroundStyle(.secondary)
                    .help("Zeitpunkt der Bestandsdatei, nach der die Einkaufsliste gerechnet ist")
            }
            if let h = daten.einkaufHinweis, h != k.preisHinweis {
                Text(h).foregroundStyle(.secondary).lineLimit(1).help(h)
            } else if k.einkaufOhnePreis > 0 {
                Text("\(KevFormat.count(k.einkaufOhnePreis, one: "Position", many: "Positionen")) ohne Preis")
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            if k.einkaufLager > 0 && k.einkaufZukauf > 0 {
                KennzahlText(titel: "Lagerware", wert: k.einkaufLagerSumme.map(KevFormat.euro) ?? "–")
                KennzahlText(titel: "Zukauf", wert: k.einkaufZukaufSumme.map(KevFormat.euro) ?? "–")
            }
            KennzahlText(titel: "Summe", wert: k.einkaufText)
        }
        .font(.callout)
        .monospacedDigit()
        .lineLimit(1)
        .padding(.horizontal, 20)
        .frame(height: 30)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }
}

/// Benennung einer Einkaufszeile: Symbol der Art, Name, Hinweis darunter.
private struct EinkaufBenennung: View {
    @ObservedObject var model: AppModel
    let zeile: MaterialEinkauf
    let abgehakt: Bool

    var body: some View {
        let p = zeile.position
        HStack(spacing: 8) {
            if zeile.art == .zukauf {
                ArtTile(art: "zukaufteil", size: 22, tint: MaterialKennzeichen.zukauf.color)
            } else {
                ArtTile(art: model.lagerteilArt(p.id), size: 22, tint: MaterialKennzeichen.kaufen.color)
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(p.benennung).lineLimit(1)
                if let h = p.hinweis {
                    Text(h).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .strikethrough(abgehakt, color: .secondary)
            .foregroundStyle(abgehakt ? .secondary : .primary)
        }
        .help("\(p.benennung)\n\(zeile.art == .zukauf ? "Zukaufteil" : "Lagerteil") \(p.id)" + (p.hinweis.map { "\n\($0)" } ?? ""))
    }
}

private struct EinkaufGruppenKopf: View {
    let titel: String
    let symbol: String
    let zeilen: [MaterialEinkauf]
    let hinweis: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).foregroundStyle(.secondary).frame(width: 16)
            Text(titel).fontWeight(.semibold)
            Text(KevFormat.count(zeilen.count, one: "Position", many: "Positionen") + " · " + hinweis)
                .foregroundStyle(.secondary)
            Spacer(minLength: 8)
            let summe = zeilen.compactMap(\.position.preis).reduce(0, +)
            if summe > 0 { Text(KevFormat.euro(summe)).fontWeight(.medium).monospacedDigit() }
        }
        .lineLimit(1)
    }
}

// MARK: - Teilen

/// Menü „Teilen“ der Einkaufsliste: als Text oder CSV teilen, kopieren, CSV in output/ sichern, alle abhaken.
struct EinkaufTeilenMenue: View {
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten

    private var text: String {
        MaterialText.einkaufText(daten, projekt: model.project?.name,
                                 stand: BestandText.anzeige(BestandText.heute(), mitZeit: false),
                                 abgehakt: material.abgehakt.schluessel)
    }

    var body: some View {
        Menu {
            ShareLink(item: text, preview: SharePreview("Einkaufsliste \(model.project?.name ?? "")")) {
                Label("Als Text teilen …", systemImage: "text.alignleft")
            }
            ShareLink(item: EinkaufCSVDatei(daten: daten, projekt: model.project?.name ?? "Projekt"),
                      preview: SharePreview(EinkaufslisteFormat.dateiname(projekt: model.project?.name ?? "Projekt"))) {
                Label("Als CSV teilen …", systemImage: "tablecells")
            }
            Divider()
            Button("Als Text kopieren") { copyToPasteboard(text) }
            Button("Als CSV in output/ sichern") { EinkaufExport.sichern(model) }
                .disabled(model.project == nil)
            Divider()
            Button("Alle abhaken") {
                var a = material.abgehakt
                a.setze(daten.einkauf, true)
                material.setzeAbgehakt(a)
            }
            Button("Alle wieder offen") {
                var a = material.abgehakt
                a.setze(daten.einkauf, false)
                material.setzeAbgehakt(a)
            }
        } label: {
            Label("Teilen", systemImage: "square.and.arrow.up")
        }
        .disabled(daten.einkauf.isEmpty)
        .fixedSize()
        .help("Einkaufsliste als Text oder CSV weiterleiten (Nachrichten, Mail, AirDrop), kopieren oder sichern")
    }
}

/// CSV der Einkaufsliste zum Teilen (entsteht erst, wenn ein Dienst gewählt ist).
struct EinkaufCSVDatei: Transferable {
    let daten: MaterialDaten
    let projekt: String

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .commaSeparatedText) { d in
            let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("Kev CAD Teilen", isDirectory: true)
            try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
            let datei = ordner.appendingPathComponent(EinkaufslisteFormat.dateiname(projekt: d.projekt))
            try MaterialText.einkaufCSV(d.daten).write(to: datei, atomically: true, encoding: .utf8)
            return SentTransferredFile(datei)
        }
    }
}

/// Einkaufsliste als CSV in den Ausgabeordner des Projekts, dieselbe Liste wie am Bildschirm (mit Zukaufteilen,
/// Normteilen zum Abzählen und Filament) und byteweise wie der Export des Kernels.
@MainActor
enum EinkaufExport {
    @discardableResult
    static func sichern(_ model: AppModel, zeigen: Bool = true) -> URL? {
        guard let p = model.project else { return nil }
        let ordner = p.path.appendingPathComponent("output", isDirectory: true)
        let datei = ordner.appendingPathComponent(EinkaufslisteFormat.dateiname(projekt: p.name))
        do {
            try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
            try MaterialText.einkaufCSV(model.materialDaten).write(to: datei, atomically: true, encoding: .utf8)
            model.append(LogLine(text: "Einkaufsliste gesichert: \(datei.path)"))
            if zeigen { NSWorkspace.shared.activateFileViewerSelecting([datei]) }
            return datei
        } catch {
            model.append(LogLine(level: .error, text: "Einkaufsliste nicht gesichert: \(error.localizedDescription)"))
            return nil
        }
    }
}
