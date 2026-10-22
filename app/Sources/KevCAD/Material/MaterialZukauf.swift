import AppKit
import KevCADCore
import SwiftUI

/// Abschnitt „Zukaufteile“ im Bereich „Material“: je Zukaufteil Produktbild, Hersteller, Nummer und EAN, Stückpreis
/// mit Datum, Anzahl und Summe, CAD-Quelle, Link zum Shop; dazu was auf ein CAD wartet und Claudes Vorschläge zum
/// Freigeben. „Zukaufteil hinzufügen …“ öffnet den Dialog aus Phase 3.
struct MaterialZukaufAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten
    var navigation: MaterialNavigation?
    var zeigeIm3D: ([String]) -> Void

    private var zukauf: [MaterialPosition] {
        daten.positionen(in: .zukauf).filter { $0.passt(material.suche) }
    }

    /// Vorschläge von Claude für Zukaufteile, die auf Kevins Freigabe warten.
    private var vorschlaege: [CatalogItem] {
        (model.catalog?.items ?? []).filter { $0.isZukauf && $0.vorgeschlagen }
    }

    var body: some View {
        VStack(spacing: 0) {
            MaterialAbschnittKopf(titel: MaterialAbschnitt.zukauf.titel, symbol: MaterialAbschnitt.zukauf.symbol,
                                  zeile: kennzeile) {
                Button {
                    session.showZukaufDialog()
                } label: {
                    Label("Zukaufteil hinzufügen …", systemImage: "plus")
                }
                .help("Shop-Link, Herstellernummer oder EAN einfügen (⌥⇧⌘K)")
                Button {
                    session.showCatalog(section: .art("zukaufteil"))
                } label: {
                    Label("Lagerkatalog", systemImage: "books.vertical")
                }
                .help("Alle Zukaufteile im Lagerkatalog")
            }
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(model.waitingForCAD) { s in wartet(s) }
                    if !vorschlaege.isEmpty { vorschlagKarte }
                    if zukauf.isEmpty {
                        MaterialLeer(titel: "Keine Zukaufteile", symbol: "bag",
                                     text: "Das Modell verbaut keine fertig gekauften Teile. Füge eines per Shop-Link, Herstellernummer oder EAN hinzu.") {
                            Button("Zukaufteil hinzufügen …") { session.showZukaufDialog() }
                        }
                        .frame(minHeight: 260)
                    } else {
                        ForEach(zukauf) { p in
                            ZukaufKarte(model: model, position: p, bild: material.bilder.bild(p),
                                        gewaehlt: material.auswahl.contains(p.pos), zeigeIm3D: zeigeIm3D) {
                                material.auswahl = [p.pos]
                            }
                            .contextMenu {
                                PositionsMenue(model: model, positionen: [p], navigation: navigation, zeigeIm3D: zeigeIm3D)
                                if let z = p.line.zukauf {
                                    if let url = z.url { Button("Link kopieren") { copyToPasteboard(url.absoluteString) } }
                                    if let mpn = z.mpn { Button("Nummer kopieren") { copyToPasteboard(mpn) } }
                                }
                            }
                        }
                        if zukauf.contains(where: { $0.line.zukauf?.vereinfacht == true }) {
                            Label("Vereinfachte Teile sind Ersatzkörper aus den Shop-Maßen, bis das Hersteller-CAD da ist.",
                                  systemImage: "cube.transparent")
                                .font(.callout)
                                .foregroundStyle(.orange)
                        }
                    }
                }
                .padding(20)
            }
        }
    }

    private var kennzeile: String {
        let k = daten.kennzahlen
        let positionen = daten.positionen(in: .zukauf)
        guard !positionen.isEmpty else { return "Fertig gekaufte Teile mit Hersteller und Nummer" }
        var t = [KevFormat.count(positionen.count, one: "Position", many: "Positionen"),
                 KevFormat.count(k.zukaufteile, one: "Stück", many: "Stück")]
        if let s = k.einkaufZukaufSumme { t.append("≈ " + KevFormat.euro(s)) }
        if k.wartetAufCAD > 0 { t.append("\(k.wartetAufCAD) wartet auf CAD") }
        return t.joined(separator: " · ")
    }

    private func wartet(_ s: ZukaufStatus) -> some View {
        HStack(spacing: 10) {
            ZukaufStatusLabel(status: s)
            Text(session.zukaufName(s.id)).fontWeight(.medium)
            if let t = s.text { Text(t).foregroundStyle(.secondary).lineLimit(1) }
            Spacer()
            Button("CAD-Datei wählen …") { session.chooseCADFile(for: s.id) }
                .controlSize(.small)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.orange.opacity(0.10)))
    }

    private var vorschlagKarte: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(KevFormat.count(vorschlaege.count, one: "Vorschlag von Claude wartet auf Freigabe",
                                  many: "Vorschläge von Claude warten auf Freigabe"),
                  systemImage: "checkmark.seal")
                .font(.headline)
                .foregroundStyle(.orange)
            ForEach(vorschlaege) { item in
                HStack {
                    Text(item.name)
                    Spacer()
                    Button("Prüfen und freigeben …") { session.showZukaufDialog(for: item, mode: .confirm) }
                        .controlSize(.small)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(KachelGrund())
    }
}

/// Ein Zukaufteil als Karte.
private struct ZukaufKarte: View {
    @ObservedObject var model: AppModel
    let position: MaterialPosition
    let bild: NSImage?
    let gewaehlt: Bool
    var zeigeIm3D: ([String]) -> Void
    var waehle: () -> Void
    @Environment(\.openURL) private var openURL

    var body: some View {
        let z = position.line.zukauf ?? ZukaufBOMInfo()
        HStack(alignment: .center, spacing: 14) {
            ZStack(alignment: .bottomTrailing) {
                if z.bild != nil {
                    ZukaufImage(url: z.bild, size: 64)
                } else {
                    PositionsBild(bild: bild, art: "zukaufteil", groesse: 64, tint: MaterialKennzeichen.zukauf.color)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(position.line.benennung).font(.headline).lineLimit(1)
                    if z.vereinfacht || z.cadQuelle != nil {
                        CADSourceBadge(simplified: z.vereinfacht, title: z.vereinfacht ? "vereinfacht" : z.cadTitle)
                    }
                }
                Text(([z.hersteller, z.mpn.map { "Nr. \($0)" }, z.gtin.map { "EAN \($0)" }, "Pos. \(position.pos)"] as [String?])
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .textSelection(.enabled)
                if let s = model.zukaufStatus(for: position.stockID ?? ""), s.zustand != .importiert {
                    ZukaufStatusLabel(status: s).font(.callout)
                }
            }
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(position.anzahl) × " + (position.line.preisJe.map(KevFormat.euro) ?? "ohne Preis"))
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                Text(position.preis.map(KevFormat.euro) ?? "–")
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                Text(([z.preisBrutto.map { $0 ? "brutto" : "netto" }, MaterialText.stand(z.preisStand).map { "Stand \($0)" }]
                    as [String?]).compactMap { $0 }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 130, alignment: .trailing)
            VStack(spacing: 6) {
                Button {
                    if let url = z.url { openURL(url) }
                } label: {
                    Label("Shop", systemImage: "arrow.up.right.square").frame(minWidth: 72)
                }
                .disabled(z.url == nil)
                .help(z.url?.absoluteString ?? "kein Link")
                Button {
                    zeigeIm3D(position.teile)
                } label: {
                    Label("Im 3D", systemImage: "cube").frame(minWidth: 72)
                }
                .disabled(position.teile.isEmpty)
                .help("Im 3D-Modell zeigen")
            }
            .controlSize(.small)
        }
        .padding(14)
        .background(KachelGrund(hervor: gewaehlt))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.accentColor.opacity(gewaehlt ? 0.8 : 0), lineWidth: 2)
        )
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { zeigeIm3D(position.teile) }
        .onTapGesture(perform: waehle)
    }
}
