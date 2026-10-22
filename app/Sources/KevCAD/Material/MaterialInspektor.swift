import AppKit
import KevCADCore
import SwiftUI

/// Inspektor im Bereich „Material“: die gewählte Position mit großem Bild, Kennzeichen, Werten, Bestand und Teilen;
/// ohne Auswahl die Kennzahlen des Abschnitts. Aktionen führen in den 3D-Bereich, den Katalog oder den Shop.
struct MaterialInspektor: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    var navigation: MaterialNavigation?
    var zeigeIm3D: ([String]) -> Void

    var body: some View {
        let daten = model.materialDaten
        let gewaehlt = daten.positionen.filter { material.auswahl.contains($0.pos) }
        Form {
            if material.abschnitt == .einkauf, let id = material.einkaufAuswahl,
               let z = daten.einkauf.first(where: { $0.id == id }) {
                einkauf(z)
            } else if gewaehlt.count == 1, let p = gewaehlt.first, ![.bestand, .einkauf].contains(material.abschnitt) {
                position(p, daten)
            } else if gewaehlt.count > 1, ![.bestand, .einkauf].contains(material.abschnitt) {
                mehrere(gewaehlt)
            } else {
                ueberblick(daten)
            }
        }
        .formStyle(.grouped)
    }

    // MARK: Eine Position

    @ViewBuilder
    private func position(_ p: MaterialPosition, _ daten: MaterialDaten) -> some View {
        Section {
            VStack(spacing: 10) {
                if let url = p.line.zukauf?.bild {
                    ZukaufImage(url: url, size: 180)
                } else {
                    PositionsBild(bild: material.bilder.bild(p), art: p.symbolArt, groesse: 180, tint: p.symbolFarbe)
                }
                VStack(spacing: 4) {
                    Text(p.name).font(.title3.weight(.semibold)).multilineTextAlignment(.center).textSelection(.enabled)
                    if let u = p.unter { Text(u).foregroundStyle(.secondary).textSelection(.enabled) }
                    HStack(spacing: 5) {
                        Text("Pos. \(p.pos)").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                        Text(p.gruppe.titel).font(.caption).foregroundStyle(.secondary)
                        KennzeichenReihe(kennzeichen: p.kennzeichen)
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
        }
        Section("Werte") {
            InfoRow(MaterialText.Spalte.anzahl, KevFormat.count(p.anzahl, one: "Stück", many: "Stück"))
            InfoRow(MaterialText.Spalte.masse, p.masseText)
            if p.gehrungText != "–" { InfoRow(MaterialText.Spalte.gehrung, p.gehrungText) }
            InfoRow(MaterialText.Spalte.werkstoff, p.werkstoff ?? "–")
            if let n = p.line.norm { InfoRow(MaterialText.Spalte.norm, n) }
            if let f = p.filament {  // Druckteile: Filament (gedruckt) und Vollkörper getrennt benannt
                InfoRow("Filament", "\(KevFormat.mass(grams: f.gramm)) (gedruckt, \(f.stand.titel))")
                InfoRow("Vollkörper", (p.vollkoerperKg.map(KevFormat.kg) ?? "–")
                    + (p.line.kgJe.map { p.anzahl > 1 ? " (je \(KevFormat.kg($0)))" : "" } ?? ""))
            } else {
                InfoRow(MaterialText.Spalte.gewicht, (p.kg.map(KevFormat.kg) ?? "–")
                    + (p.line.kgJe.map { p.anzahl > 1 ? " (je \(KevFormat.kg($0)))" : "" } ?? ""))
            }
            InfoRow(MaterialText.Spalte.preis, (p.preis.map(KevFormat.euro) ?? "–")
                + (p.filament?.kosten != nil ? " (Filament, \(p.filament!.stand.titel))"
                    : (p.line.preisJe.map { p.anzahl > 1 ? " (je \(KevFormat.euro($0)))" : "" } ?? "")))
            if let id = p.stockID { InfoRow(MaterialText.Spalte.lagerteil, id, monospaced: true) }
        }
        if let sid = p.stockID, p.herkunft == nil {
            Section("Bestand und Zuschnitt") {
                if let posten = model.bestandZustand.bestand?.posten(sid), !posten.leer {
                    InfoRow("Im Bestand", posten.zusammenfassung)
                } else {
                    InfoRow("Im Bestand", "nichts")
                }
                if let z = daten.zuschnitt(sid) {
                    InfoRow("Zuschnitt", z.herkunftText)
                    if let v = daten.verschnitt(z) { InfoRow("Verschnitt", KevFormat.number(v, digits: 1) + " %") }
                    if z.hatNeueReste { InfoRow("Neue Reste", z.neueResteText) }
                }
                if let e = daten.einkauf.first(where: { $0.position.id == sid }) {
                    InfoRow("Zu kaufen", "\(e.position.mengeText) × \(e.position.einheit)")
                }
                HStack {
                    if p.gruppe == .stangen || p.gruppe == .platten {
                        Button("Zuschnitt") { material.zeige(.zuschnitt, stockID: sid) }
                    }
                    Button("Bestand") {
                        BestandUI.shared.auswahl = sid
                        material.zeige(.bestand)
                    }
                }
                .controlSize(.small)
            }
        }
        if let z = p.line.zukauf {
            Section("Zukauf") {
                if let h = z.hersteller { InfoRow("Hersteller", h) }
                if let m = z.mpn { InfoRow("Nummer", m, monospaced: true) }
                if let g = z.gtin { InfoRow("EAN", g, monospaced: true) }
                if let s = MaterialText.stand(z.preisStand) {
                    InfoRow("Preisstand", s + (z.preisBrutto.map { $0 ? ", brutto" : ", netto" } ?? ""))
                }
                InfoRow("CAD", z.cadTitle)
                if let url = z.url {
                    Link(destination: url) { Label("Produktseite öffnen", systemImage: "arrow.up.right.square") }
                }
            }
        }
        Section {
            ForEach(p.teile.prefix(40), id: \.self) { t in
                Button {
                    zeigeIm3D([t])
                } label: {
                    HStack {
                        Image(systemName: "cube").foregroundStyle(.secondary)
                        Text(t).lineLimit(1).truncationMode(.middle)
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("„\(t)“ im 3D-Modell zeigen")
            }
            if p.teile.count > 40 { Text("und \(p.teile.count - 40) weitere").foregroundStyle(.secondary) }
        } header: {
            Text(KevFormat.count(p.teile.count, one: "Teil im Modell", many: "Teile im Modell"))
        }
        Section {
            Button {
                zeigeIm3D(p.teile)
            } label: {
                Label("Im 3D-Modell zeigen", systemImage: "cube")
            }
            .disabled(p.teile.isEmpty)
            if let id = p.stockID, p.herkunft == nil || p.herkunft == .zukauf {
                Button {
                    session.showCatalog(focus: .item(id))
                } label: {
                    Label("Im Lagerkatalog zeigen", systemImage: "books.vertical")
                }
            }
            Button {
                copyToPasteboard(MaterialText.zeile(p))
            } label: {
                Label("Zeile kopieren", systemImage: "doc.on.doc")
            }
        }
    }

    private func mehrere(_ liste: [MaterialPosition]) -> some View {
        let s = MaterialDaten.summen(liste)
        return Section(KevFormat.count(liste.count, one: "Position gewählt", many: "Positionen gewählt")) {
            InfoRow(MaterialText.Spalte.anzahl, KevFormat.count(s.teile, one: "Teil", many: "Teile"))
            InfoRow(MaterialText.Spalte.gewicht, KevFormat.kg(s.kg))
            InfoRow(MaterialText.Spalte.preis, s.preis.map(KevFormat.euro) ?? "–")
            Button {
                zeigeIm3D(liste.flatMap(\.teile))
            } label: {
                Label("Im 3D-Modell zeigen", systemImage: "cube")
            }
        }
    }

    // MARK: Einkauf

    @ViewBuilder
    private func einkauf(_ z: MaterialEinkauf) -> some View {
        let p = z.position
        Section(z.art == .zukauf ? "Zukaufteil" : "Lagerware") {
            Text(p.benennung).font(.headline).textSelection(.enabled)
            InfoRow(MaterialText.Spalte.menge, "\(p.mengeText) × \(p.einheit)")
            InfoRow(MaterialText.Spalte.preisJe, p.preisJe.map(KevFormat.euro) ?? "–")
            InfoRow(MaterialText.Spalte.preis, p.preis.map(KevFormat.euro) ?? "–")
            if let s = MaterialText.stand(p.stand) { InfoRow(MaterialText.Spalte.stand, s) }
            if let h = p.hinweis {
                Text(h).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if let link = p.link {
                Link(destination: link) { Label(p.linkTitel ?? "Bezugsquelle", systemImage: "arrow.up.right.square") }
            }
            Toggle("Gekauft (abgehakt)", isOn: Binding(
                get: { material.abgehakt.abgehakt(z) }, set: { _ in material.umschalten(z) }))
        }
    }

    // MARK: Überblick

    @ViewBuilder
    private func ueberblick(_ daten: MaterialDaten) -> some View {
        let k = daten.kennzahlen
        Section(material.abschnitt.titel) {
            InfoRow("Teile", KevFormat.integer(k.teile))
            InfoRow("Positionen", KevFormat.integer(k.positionen))
            InfoRow("Gewicht", KevFormat.kg(k.kg))
            InfoRow("Materialkosten", k.kostenText)
            InfoRow("Zu kaufen", k.einkaufPositionen == 0 ? "nichts" : k.einkaufText)
            InfoRow("Zuschnitt", k.zuschnittText)
            InfoRow("Verschnitt", k.verschnittText)
            InfoRow("Reste im Bestand", KevFormat.integer(k.resteImBestand))
            InfoRow("Druckteile", KevFormat.integer(k.druckteile))
            InfoRow("Zukaufteile", KevFormat.integer(k.zukaufteile))
        }
        if material.abschnitt == .bestand {
            Section("Buchungen") {
                let b = model.bestandZustand.buchungen.prefix(8)
                if b.isEmpty { Text("Noch keine Buchungen").foregroundStyle(.secondary) }
                ForEach(Array(b)) { x in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(x.text).strikethrough(x.schonRueckgaengig).lineLimit(2)
                        Text([x.artTitel, BestandText.anzeige(x.zeitText) ?? x.zeitText].joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        if k.freigaben > 0 || k.inventarVerstoesse > 0 {
            Section("Freigaben") {
                if k.freigaben > 0 {
                    Button {
                        session.showCatalog(section: .suggestions)
                    } label: {
                        Label(KevFormat.count(k.freigaben, one: "Vorschlag von Claude prüfen",
                                              many: "Vorschläge von Claude prüfen"), systemImage: "checkmark.seal")
                    }
                }
                if k.inventarVerstoesse > 0 {
                    Label(KevFormat.count(k.inventarVerstoesse, one: "Teil nicht im Inventar", many: "Teile nicht im Inventar"),
                          systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
        }
        Section {
            Button {
                navigation?.bericht(material.abschnitt.bericht)
            } label: {
                Label("Als Bericht drucken", systemImage: "printer")
            }
            .disabled(navigation == nil)
            Button {
                session.showCatalog()
            } label: {
                Label("Lagerkatalog öffnen", systemImage: "books.vertical")
            }
        } footer: {
            Text(k.preisHinweis ?? "Richtpreise ohne Gewähr").font(.caption).foregroundStyle(.secondary)
        }
    }
}
