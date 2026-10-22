import AppKit
import KevCADCore
import SwiftUI

// Abschnitte „Stückliste“ und „Zuschnitt“ im Bereich „Material“.

// MARK: - Stückliste

struct MaterialStuecklisteAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten
    var navigation: MaterialNavigation?
    var zeigeIm3D: ([String]) -> Void
    @State private var filter: MaterialGruppe?
    @State private var zeigeHinweise = false

    private var gefiltert: [MaterialPosition] {
        daten.positionen.filter { (filter == nil || $0.gruppe == filter) && $0.passt(material.suche) }
    }

    var body: some View {
        VStack(spacing: 0) {
            MaterialAbschnittKopf(titel: MaterialAbschnitt.stueckliste.titel, symbol: MaterialAbschnitt.stueckliste.symbol,
                                  zeile: kennzeile) {
                Toggle(isOn: $material.gruppieren) {
                    Label("Gruppieren", systemImage: "rectangle.3.group")
                }
                .toggleStyle(.button)
                .help("Nach Gruppen: Stangen und Profile, Platten, Normteile, Zukaufteile, Druckteile")
                Button {
                    model.actions?.export(formats: ["bom_csv"])
                } label: {
                    Label("Als CSV exportieren", systemImage: "square.and.arrow.up")
                }
                .disabled(daten.positionen.isEmpty)
                .help("Stückliste und Zuschnitt als CSV in output/ speichern und im Finder zeigen (Numbers, Excel)")
                Button {
                    navigation?.bericht(.stueckliste)
                } label: {
                    Label("Als Bericht drucken", systemImage: "printer")
                }
                .disabled(navigation == nil)
                .help("Druckfassung in „Dokumente“ › Berichte: Stückliste mit Bild, A4 oder A3")
            }
            if !daten.positionen.isEmpty {
                GruppenFilter(daten: daten, filter: $filter)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
            }
            Divider()
            inhalt
            fuss
        }
    }

    private var kennzeile: String {
        let k = daten.kennzahlen
        guard daten.hatStueckliste else { return "Entsteht nach dem ersten Lauf" }
        return [KevFormat.count(k.positionen, one: "Position", many: "Positionen"),
                KevFormat.count(k.teile, one: "Teil", many: "Teile"), KevFormat.kg(k.kg), k.kostenText]
            .joined(separator: " · ")
    }

    @ViewBuilder
    private var inhalt: some View {
        if !daten.hatStueckliste {
            MaterialLeer(titel: "Noch keine Stückliste", symbol: "list.bullet.rectangle",
                         text: "Sie entsteht nach jedem Lauf aus den verbauten Lagerteilen (lager.teil(…).verbauen(…)) und den Teilen mit Material.") {
                Button("Stückliste anfordern") { model.catalogActions?.requestBOM() }
                    .disabled(model.project == nil || !(model.kernelState == .ready || model.kernelState == .busy))
            }
        } else if daten.positionen.isEmpty {
            MaterialLeer(titel: "Stückliste ist leer", symbol: "list.bullet.rectangle",
                         text: "Im Modell stecken keine Lagerteile und keine Teile mit Material.")
        } else if gefiltert.isEmpty {
            MaterialLeer(titel: "Keine Treffer", symbol: "magnifyingglass",
                         text: "Keine Position passt zu „\(material.suche)“\(filter.map { " in \($0.titel)" } ?? "").")
        } else {
            StuecklisteGrossTabelle(model: model, material: material, bilder: material.bilder, positionen: gefiltert,
                                    navigation: navigation, zeigeIm3D: zeigeIm3D)
        }
    }

    /// Fuß: Summen der Auswahl bzw. der gezeigten Positionen, Hinweise, Preisangabe.
    private var fuss: some View {
        let gewaehlt = gefiltert.filter { material.auswahl.contains($0.pos) }
        let liste = gewaehlt.isEmpty ? gefiltert : gewaehlt
        let s = MaterialDaten.summen(liste)
        return HStack(spacing: 14) {
            Text(gewaehlt.isEmpty
                 ? (liste.count == daten.positionen.count ? "Gesamt" : "Gezeigt")
                 : KevFormat.count(gewaehlt.count, one: "Position gewählt", many: "Positionen gewählt"))
                .foregroundStyle(.secondary)
            KennzahlText(titel: "Teile", wert: KevFormat.integer(s.teile))
            KennzahlText(titel: "Gewicht", wert: KevFormat.kg(s.kg))
            KennzahlText(titel: "Preis", wert: s.preis.map(KevFormat.euro) ?? "–")
            if !daten.warnungen.isEmpty {
                Button {
                    zeigeHinweise.toggle()
                } label: {
                    Label(KevFormat.count(daten.warnungen.count, one: "Hinweis", many: "Hinweise"),
                          systemImage: "exclamationmark.triangle.fill")
                        .symbolRenderingMode(.multicolor)
                }
                .buttonStyle(.borderless)
                .popover(isPresented: $zeigeHinweise, arrowEdge: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Hinweise zur Stückliste").font(.headline)
                        ForEach(Array(daten.warnungen.enumerated()), id: \.offset) { _, w in
                            Label(w, systemImage: "exclamationmark.triangle.fill")
                                .symbolRenderingMode(.multicolor)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(14)
                    .frame(width: 400, alignment: .leading)
                }
            }
            Spacer(minLength: 8)
            Text(([daten.kennzahlen.preisHinweis ?? "Richtpreise ohne Gewähr"] + (daten.run > 0 ? ["Lauf \(daten.run)"] : []))
                .joined(separator: " · "))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .font(.callout)
        .monospacedDigit()
        .padding(.horizontal, 20)
        .frame(height: 30)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }
}

/// Filter nach Gruppe als Reihe von Kapseln mit Anzahl.
struct GruppenFilter: View {
    let daten: MaterialDaten
    @Binding var filter: MaterialGruppe?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                kapsel(nil, titel: "Alle", anzahl: daten.positionen.count)
                ForEach(daten.gruppen, id: \.gruppe) { g in
                    kapsel(g.gruppe, titel: g.gruppe.titel, anzahl: g.positionen.count)
                }
            }
        }
    }

    private func kapsel(_ g: MaterialGruppe?, titel: String, anzahl: Int) -> some View {
        let an = filter == g
        return Button {
            withAnimation(.snappy(duration: 0.15)) { filter = g }
        } label: {
            HStack(spacing: 5) {
                if let g { Image(systemName: g.symbol).font(.caption) }
                Text(titel)
                Text("\(anzahl)")
                    .monospacedDigit()
                    .foregroundStyle(an ? Color.white.opacity(0.85) : .secondary)
            }
            .font(.callout.weight(an ? .semibold : .regular))
            .foregroundStyle(an ? Color.white : .primary)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Capsule().fill(an ? Color.accentColor : Color.primary.opacity(0.06)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Zuschnitt

struct MaterialZuschnittAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten
    var navigation: MaterialNavigation?

    private var gefiltert: [BestandZuschnitt] {
        let q = material.suche.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return daten.zuschnitte }
        return daten.zuschnitte.filter { ($0.benennung + " " + $0.stockID).lowercased().contains(q) }
    }

    var body: some View {
        VStack(spacing: 0) {
            MaterialAbschnittKopf(titel: MaterialAbschnitt.zuschnitt.titel, symbol: MaterialAbschnitt.zuschnitt.symbol,
                                  zeile: kennzeile) {
                Button {
                    BestandUI.shared.zeigeGebaut()
                } label: {
                    Label("Gebaut …", systemImage: "hammer")
                }
                .disabled(model.bestandActions == nil || model.bestandZustand.zuschnitt == nil || model.laufAktiv)
                .help("Bestand abbuchen: was der Zuschnitt verplant, geht weg; neue Reste kommen dazu")
                Button {
                    navigation?.bericht(.zuschnitt)
                } label: {
                    Label("Als Bericht drucken", systemImage: "printer")
                }
                .disabled(navigation == nil)
                .help("Druckfassung in „Dokumente“ › Berichte: Schnittpläne je Stange und Platte")
            }
            Divider()
            if daten.zuschnitte.isEmpty && daten.stueckgut.isEmpty {
                MaterialLeer(titel: "Kein Zuschnitt", symbol: "scissors",
                             text: "Das Modell verbaut keine Stangenware und keine Platten.")
            } else {
                ScrollViewReader { leser in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            HStack(spacing: 12) {
                                ZuschnittLegende()
                                Spacer(minLength: 8)
                                if daten.kennzahlen.mitBestand == false {
                                    Label("Ohne Bestandsabgleich: alle Stangen und Platten werden neu gekauft.",
                                          systemImage: "info.circle")
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            ForEach(gefiltert) { z in
                                karte(z).id(z.stockID)
                            }
                            if !daten.stueckgut.isEmpty {
                                StueckgutBlock(stueckgut: daten.stueckgut)
                                    .padding(16)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(KachelGrund())
                            }
                            Text(MaterialZuschnitt.hilfe)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(20)
                    }
                    .onChange(of: material.zuschnittFokus) { _, id in springe(id, leser) }
                    .onAppear { springe(material.zuschnittFokus, leser) }
                }
            }
        }
    }

    private func springe(_ id: String?, _ leser: ScrollViewProxy) {
        guard let id else { return }
        DispatchQueue.main.async {
            withAnimation(.snappy(duration: 0.3)) { leser.scrollTo(id, anchor: .top) }
            material.zuschnittFokus = nil
        }
    }

    private var kennzeile: String {
        let k = daten.kennzahlen
        var t = [k.zuschnittText]
        if k.verschnittText != "–" { t.append("Verschnitt " + k.verschnittText) }
        if k.neueReste > 0 { t.append(KevFormat.count(k.neueReste, one: "neuer Rest", many: "neue Reste")) }
        if k.mitBestand { t.append("Reste aus dem Bestand zuerst") }
        return t.joined(separator: " · ")
    }

    private func karte(_ z: BestandZuschnitt) -> some View {
        let lines = daten.lines(z.stockID)
        let posten = model.bestandZustand.bestand?.posten(z.stockID)
        return VStack(alignment: .leading, spacing: 12) {
            ZuschnittBlock(zuschnitt: z, lines: lines, mindestrest: daten.mindestrest(z.stockID),
                           verschnitt: daten.verschnitt(z), groesse: .gross, selected: material.auswahl) { line in
                waehle(line)
            }
            Divider()
            HStack(alignment: .top, spacing: 24) {
                // Stücke dieses Lagerteils (aus der Stückliste)
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 4) {
                    GridRow {
                        Text(MaterialText.Spalte.pos)
                        Text(MaterialText.Spalte.masse)
                        Text(MaterialText.Spalte.gehrung)
                        Text(MaterialText.Spalte.anzahl).gridColumnAlignment(.trailing)
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    ForEach(lines) { line in
                        let an = material.auswahl.contains(line.pos)
                        GridRow {
                            Text("\(line.pos)").foregroundStyle(.secondary)
                            Text(MaterialText.masse(line)).fontWeight(an ? .semibold : .regular)
                            Text(KevFormat.gehrung(line.gehrung)).foregroundStyle(.secondary)
                            Text("\(line.anzahl) ×").fontWeight(.semibold)
                        }
                        .monospacedDigit()
                        .contentShape(Rectangle())
                        .onTapGesture { waehle(line) }
                    }
                }
                .font(.callout)
                Spacer(minLength: 12)
                VStack(alignment: .trailing, spacing: 6) {
                    if let posten, !posten.leer {
                        Text("Im Bestand: " + posten.zusammenfassung)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    } else if daten.kennzahlen.mitBestand {
                        Text("Nicht im Bestand").font(.callout).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 8) {
                        Button("Bestand zeigen") {
                            BestandUI.shared.auswahl = z.stockID
                            material.zeige(.bestand)
                        }
                        if model.catalog?.item(z.stockID) != nil {
                            Button("Im Lagerkatalog") { session.showCatalog(focus: .item(z.stockID)) }
                        }
                    }
                    .controlSize(.small)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(KachelGrund(hervor: !Set(lines.map(\.pos)).isDisjoint(with: material.auswahl)))
    }

    private func waehle(_ line: BOMLine) {
        material.auswahl = [line.pos]
    }
}
