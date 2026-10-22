import AppKit
import KevCADCore
import SwiftUI

// Stückliste als Tabelle: groß im Bereich „Material“ (Bild, Gruppen, Suche, Sortierung, Spalten wählbar) und kompakt in
// der Schnellansicht unter dem Viewport (wie die bisherige Stückliste). Beide lesen MaterialDaten und teilen Kontextmenü,
// Zellen und Texte.

extension MaterialPosition {
    // Sortierschlüssel (KeyPathComparator braucht Comparable)
    var kgWert: Double { kg ?? -1 }
    var preisWert: Double { preis ?? -1 }
    var preisJeWert: Double { line.preisJe ?? -1 }
    var werkstoffText: String { werkstoff ?? "" }
    var masseWert: Double { line.laenge ?? 0 }
    var kennzeichenText: String { kennzeichen.map(\.titel).joined(separator: " ") }
    var lagerteilText: String { stockID ?? "" }
    var normText: String { line.norm ?? "" }
}

// MARK: - Kontextmenü

/// Aktionen an Positionen (Tabellen, Zuschnitt, Inspektor): zeigen, isolieren, Katalog, Shop, Zuschnitt, Bestand, kopieren.
struct PositionsMenue: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    let positionen: [MaterialPosition]
    var navigation: MaterialNavigation?
    /// Im Bereich „Material“: in den 3D-Bereich wechseln und dort zeigen.
    var zeigeIm3D: (([String]) -> Void)?

    var body: some View {
        let teile = positionen.flatMap(\.teile)
        if !teile.isEmpty {
            Button(positionen.count == 1 ? "Im 3D-Modell zeigen" : "Teile im 3D-Modell zeigen") {
                if let zeigeIm3D { zeigeIm3D(teile) } else if positionen.count == 1 {
                    model.catalogActions?.showBOMLine(positionen[0].line)
                } else {
                    model.actions?.select(teile)
                    model.actions?.focus(on: teile)
                }
            }
            Button("Teile isolieren") {
                model.actions?.isolate(teile)
                zeigeIm3D?(teile)
            }
        }
        if positionen.count == 1, let p = positionen.first {
            Divider()
            if let id = p.stockID, p.herkunft == nil || p.herkunft == .zukauf {
                Button("Im Lagerkatalog zeigen") { session.showCatalog(focus: .item(id)) }
            }
            if let url = p.line.zukauf?.url {
                Button("Produktseite öffnen") { NSWorkspace.shared.open(url) }
            } else if let url = p.link {
                Button("Bezugsquelle öffnen") { NSWorkspace.shared.open(url) }
            }
            if let navigation, let id = p.stockID, p.gruppe == .stangen || p.gruppe == .platten {
                Button("Im Zuschnitt zeigen") { navigation.zeige(.zuschnitt, p.pos, id) }
            }
            if let navigation, let id = p.stockID, p.herkunft == nil {
                Button("Im Bestand zeigen") {
                    BestandUI.shared.auswahl = id
                    navigation.zeige(.bestand, p.pos, id)
                }
            }
        }
        Divider()
        Button(positionen.count == 1 ? "Zeile kopieren" : "Zeilen kopieren") {
            copyToPasteboard(positionen.map(MaterialText.zeile).joined(separator: "\n"))
        }
        Button("Teilenamen kopieren") { copyToPasteboard(teile.joined(separator: "\n")) }
    }
}

// MARK: - Zellen

/// Benennung: Symbol der Art, Name, darunter Norm bzw. Nummer bzw. Baugruppe (groß) oder Norm daneben (kompakt).
struct BenennungZelle: View {
    let position: MaterialPosition
    var kompakt = false

    var body: some View {
        HStack(spacing: 7) {
            if kompakt {
                Image(systemName: CatalogSchema.art(position.symbolArt).symbol)
                    .foregroundStyle(position.symbolFarbe)
                    .frame(width: 16)
            }
            if kompakt {
                // Kennzeichen zuerst: der Name kürzt sich, die Norm fällt als Erstes weg
                HStack(spacing: 6) {
                    ViewThatFits(in: .horizontal) {
                        if let norm = position.line.norm, !position.line.benennung.contains(norm) {
                            HStack(spacing: 6) {
                                Text(position.line.benennung).fixedSize()
                                Text(norm).foregroundStyle(.secondary).fixedSize()
                            }
                        }
                        Text(position.line.benennung)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    .layoutPriority(1)
                    Spacer(minLength: 0)
                    marken
                        .layoutPriority(2)
                }
            } else {
                VStack(alignment: .leading, spacing: 1) {
                    Text(position.name)
                        .fontWeight(.medium)
                        .lineLimit(1)
                    if let unter = position.unter {
                        Text(unter)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .help(position.hilfe)
    }

    @ViewBuilder
    private var marken: some View {
        if let z = position.line.zukauf, z.vereinfacht {
            CADSourceBadge(simplified: true, title: "vereinfacht")
        } else {
            KennzeichenReihe(kennzeichen: position.kennzeichen)
        }
    }
}

// MARK: - Groß (Bereich „Material“)

/// Stückliste im Bereich „Material“: Bild, Gruppen mit Zwischensummen, Sortierung über die Spaltenköpfe, Spalten über das
/// Kontextmenü der Köpfe ein- und ausblendbar.
struct StuecklisteGrossTabelle: View {
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    @ObservedObject var bilder: MaterialBilderSpeicher
    let positionen: [MaterialPosition]
    var navigation: MaterialNavigation?
    var zeigeIm3D: ([String]) -> Void
    @State private var sortierung: [KeyPathComparator<MaterialPosition>] = [KeyPathComparator(\.pos)]
    /// Gewählte Spalten; einmal beim Erscheinen gelesen (ein Startwert hier liefe bei jedem Neuaufbau der Ansicht).
    @State private var spalten = TableColumnCustomization<MaterialPosition>()
    @State private var spaltenGeladen = false

    static let spaltenSchluessel = "material.stueckliste.spalten"

    static func geladeneSpalten() -> TableColumnCustomization<MaterialPosition> {
        guard let d = UserDefaults.standard.data(forKey: spaltenSchluessel),
              let c = try? JSONDecoder().decode(TableColumnCustomization<MaterialPosition>.self, from: d)
        else { return TableColumnCustomization() }
        return c
    }

    private var sortiert: [MaterialPosition] { positionen.sorted(using: sortierung) }

    typealias Sortierung = KeyPathComparator<MaterialPosition>

    /// Erste Spaltengruppe (der Spaltenbaukasten nimmt höchstens zehn Spalten je Block).
    @TableColumnBuilder<MaterialPosition, Sortierung>
    private var spaltenVorn: some TableColumnContent<MaterialPosition, Sortierung> {
        TableColumn(MaterialText.Spalte.bild) { p in
            PositionsBild(bild: bilder.bild(p), art: p.symbolArt, groesse: 38, tint: p.symbolFarbe)
                .padding(.vertical, 2)
        }
        .width(46)
        .customizationID("bild")
        TableColumn(MaterialText.Spalte.pos, value: \.pos) { p in
            Text("\(p.pos)").monospacedDigit().foregroundStyle(.secondary)
        }
        .width(min: 34, ideal: 40, max: 56)
        .customizationID("pos")
        TableColumn(MaterialText.Spalte.benennung, value: \.name) { p in
            BenennungZelle(position: p)
        }
        .width(min: 160, ideal: 220)
        .customizationID("benennung")
        TableColumn(MaterialText.Spalte.kennzeichen, value: \.kennzeichenText) { p in
            KennzeichenReihe(kennzeichen: p.kennzeichen)
        }
        .width(min: 64, ideal: 104)
        .customizationID("quelle")
        TableColumn(MaterialText.Spalte.masse, value: \.masseWert) { p in
            Text(p.masseText).monospacedDigit().lineLimit(1).help(p.masseText)
        }
        .width(min: 76, ideal: 120)
        .customizationID("masse")
        TableColumn(MaterialText.Spalte.gehrung) { p in
            Text(p.gehrungText)
                .monospacedDigit()
                .foregroundStyle(p.gehrungText == "–" ? .tertiary : .primary)
                .help(p.gehrungText == "–" ? "gerade Schnitte" : "Gehrung an Anfang und Ende")
        }
        .width(min: 52, ideal: 66)
        .customizationID("gehrung")
    }

    @TableColumnBuilder<MaterialPosition, Sortierung>
    private var spaltenHinten: some TableColumnContent<MaterialPosition, Sortierung> {
        TableColumn(MaterialText.Spalte.werkstoff, value: \.werkstoffText) { p in
            Text(p.werkstoff ?? "–").foregroundStyle(p.werkstoff == nil ? .tertiary : .primary).lineLimit(1)
        }
        .width(min: 70, ideal: 110)
        .customizationID("werkstoff")
        TableColumn(MaterialText.Spalte.norm, value: \.normText) { p in
            Text(p.line.norm ?? "–").foregroundStyle(p.line.norm == nil ? .tertiary : .secondary).lineLimit(1)
        }
        .width(min: 60, ideal: 100)
        .customizationID("norm")
        .defaultVisibility(.hidden)
        TableColumn(MaterialText.Spalte.lagerteil, value: \.lagerteilText) { p in
            Text(p.stockID ?? "–").font(.callout.monospaced()).foregroundStyle(.secondary).lineLimit(1)
        }
        .width(min: 80, ideal: 150)
        .customizationID("lagerteil")
        .defaultVisibility(.hidden)
        TableColumn(MaterialText.Spalte.anzahl, value: \.anzahl) { p in
            ZahlZelle(text: KevFormat.integer(p.anzahl), hervor: true)
        }
        .width(min: 44, ideal: 54)
        .customizationID("anzahl")
        TableColumn(MaterialText.Spalte.gewicht, value: \.kgWert) { p in
            ZahlZelle(text: p.kg.map(KevFormat.kg) ?? "–")
                .help(p.line.kgJe.map { "je Stück \(KevFormat.kg($0))" } ?? "")
        }
        .width(min: 58, ideal: 74)
        .customizationID("gewicht")
        TableColumn(MaterialText.Spalte.preisJe, value: \.preisJeWert) { p in
            ZahlZelle(text: p.line.preisJe.map(KevFormat.euro) ?? "–")
        }
        .width(min: 60, ideal: 78)
        .customizationID("preis_je")
        .defaultVisibility(.hidden)
        TableColumn(MaterialText.Spalte.preis, value: \.preisWert) { p in
            ZahlZelle(text: p.preis.map(KevFormat.euro) ?? "–").help(p.preisHilfe)
        }
        .width(min: 60, ideal: 80)
        .customizationID("preis")
    }

    @TableRowBuilder<MaterialPosition>
    private var zeilen: some TableRowContent<MaterialPosition> {
        if material.gruppieren {
            let liste = sortiert
            let rang = Dictionary(uniqueKeysWithValues: liste.enumerated().map { ($1.pos, $0) })
            ForEach(MaterialDaten.gruppiert(liste, sortierung: { (rang[$0.pos] ?? 0) < (rang[$1.pos] ?? 0) }),
                    id: \.gruppe) { g in
                Section {
                    ForEach(g.positionen) { p in TableRow(p) }
                } header: {
                    GruppenKopf(gruppe: g.gruppe, positionen: g.positionen)
                }
            }
        } else {
            ForEach(sortiert) { p in TableRow(p) }
        }
    }

    var body: some View {
        ScrollViewReader { leser in
            Table(of: MaterialPosition.self, selection: $material.auswahl, sortOrder: $sortierung,
                  columnCustomization: $spalten) {
                spaltenVorn
                spaltenHinten
            } rows: {
                zeilen
            }
            .tableStyle(.inset)
            .alternatingRowBackgrounds()
            .contextMenu(forSelectionType: Int.self) { ids in
                PositionsMenue(model: model, positionen: positionen.filter { ids.contains($0.pos) },
                               navigation: navigation, zeigeIm3D: zeigeIm3D)
            } primaryAction: { ids in
                let teile = positionen.filter { ids.contains($0.pos) }.flatMap(\.teile)
                if !teile.isEmpty { zeigeIm3D(teile) }
            }
            .onChange(of: spalten) { _, c in
                if let d = try? JSONEncoder().encode(c) { UserDefaults.standard.set(d, forKey: Self.spaltenSchluessel) }
            }
            .onChange(of: material.stuecklisteFokus) { _, pos in
                guard let pos else { return }
                withAnimation(.snappy(duration: 0.25)) { leser.scrollTo(pos, anchor: .center) }
                material.stuecklisteFokus = nil
            }
            .onAppear {
                if !spaltenGeladen {
                    spaltenGeladen = true
                    spalten = Self.geladeneSpalten()
                }
                if let pos = material.stuecklisteFokus {
                    DispatchQueue.main.async { leser.scrollTo(pos, anchor: .center) }
                    material.stuecklisteFokus = nil
                }
            }
        }
    }
}

/// Kopf einer Gruppe in der Tabelle: Symbol, Titel, Anzahl, Gewicht und Preis der Gruppe.
struct GruppenKopf: View {
    let gruppe: MaterialGruppe
    let positionen: [MaterialPosition]

    var body: some View {
        let s = MaterialDaten.summen(positionen)
        HStack(spacing: 8) {
            Image(systemName: gruppe.symbol).foregroundStyle(.secondary).frame(width: 16)
            Text(gruppe.titel).fontWeight(.semibold)
            Text(KevFormat.count(positionen.count, one: "Position", many: "Positionen") + " · "
                + KevFormat.count(s.teile, one: "Teil", many: "Teile"))
                .foregroundStyle(.secondary)
            Spacer(minLength: 8)
            if s.kg > 0 { Text(KevFormat.kg(s.kg)).foregroundStyle(.secondary) }
            if let p = s.preis { Text(KevFormat.euro(p)).fontWeight(.medium) }
        }
        .monospacedDigit()
        .lineLimit(1)
    }
}

// MARK: - Kompakt (Schnellansicht)

/// Stückliste kompakt wie bisher unter dem Viewport: eine Zeile je Position, Kennzeichen hinter dem Namen.
struct StuecklisteKompaktTabelle: View {
    @ObservedObject var model: AppModel
    let daten: MaterialDaten
    var navigation: MaterialNavigation?

    /// Zeile, deren Teile gerade gewählt sind (Auswahl im Viewport oder im Baum).
    private var auswahl: Binding<Int?> {
        Binding(
            get: {
                let ids = Set(model.selectedPartIDs)
                guard !ids.isEmpty, let p = daten.positionen.first(where: { ids.isSubset(of: Set($0.teile)) }) else { return nil }
                return p.pos
            },
            set: { pos in
                guard let pos, let p = daten.position(pos) else { return }
                if Set(model.selectedPartIDs) == Set(p.teile) { return }
                model.catalogActions?.showBOMLine(p.line)
            })
    }

    var body: some View {
        Table(daten.positionen, selection: auswahl) {
            TableColumn(MaterialText.Spalte.pos) { p in
                Text("\(p.pos)").monospacedDigit().foregroundStyle(.secondary)
            }
            .width(36)
            TableColumn(MaterialText.Spalte.benennung) { p in
                BenennungZelle(position: p, kompakt: true)
            }
            .width(min: 180, ideal: 300)
            TableColumn(MaterialText.Spalte.masse) { p in
                Text(p.masseText).monospacedDigit().lineLimit(1).help(p.masseText)
            }
            .width(min: 80, ideal: 140)
            TableColumn(MaterialText.Spalte.gehrung) { p in
                Text(p.gehrungText)
                    .monospacedDigit()
                    .foregroundStyle(p.gehrungText == "–" ? .tertiary : .primary)
            }
            .width(min: 52, ideal: 70)
            TableColumn(MaterialText.Spalte.werkstoff) { p in
                Text(p.werkstoff ?? "–").foregroundStyle(p.werkstoff == nil ? .tertiary : .primary).lineLimit(1)
            }
            .width(min: 70, ideal: 120)
            TableColumn(MaterialText.Spalte.anzahl) { p in
                ZahlZelle(text: KevFormat.integer(p.anzahl))
            }
            .width(min: 44, ideal: 52)
            TableColumn(MaterialText.Spalte.gewicht) { p in
                ZahlZelle(text: p.kg.map(KevFormat.kg) ?? "–")
                    .help(p.line.kgJe.map { "je Stück \(KevFormat.kg($0))" } ?? "")
            }
            .width(min: 58, ideal: 74)
            TableColumn(MaterialText.Spalte.preis) { p in
                ZahlZelle(text: p.preis.map(KevFormat.euro) ?? "–").help(p.preisHilfe)
            }
            .width(min: 60, ideal: 80)
        }
        .tableStyle(.inset)
        .alternatingRowBackgrounds()
        .contextMenu(forSelectionType: Int.self) { ids in
            PositionsMenue(model: model, positionen: daten.positionen.filter { ids.contains($0.pos) }, navigation: navigation)
        } primaryAction: { ids in
            if let pos = ids.first, let p = daten.position(pos) { model.catalogActions?.showBOMLine(p.line) }
        }
    }
}
