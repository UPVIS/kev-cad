import AppKit
import KevCADCore
import SwiftUI

/// Übersicht im Bereich „Material“: das Wichtigste auf einen Blick. Kacheln für Teile, Gewicht, Materialkosten, was zu
/// kaufen ist, Zuschnitt mit Verschnitt, Reste, Druck- und Zukaufteile und offene Freigaben; darunter die Kosten nach
/// Gruppen, die offenen Einkäufe und die Hinweise der Stückliste. Jede Kachel führt in ihren Abschnitt.
struct MaterialUebersichtAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let daten: MaterialDaten

    private var k: MaterialKennzahlen { daten.kennzahlen }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                kopf
                if !daten.hatStueckliste {
                    MaterialLeer(titel: "Noch keine Stückliste", symbol: "list.bullet.rectangle",
                                 text: "Sie entsteht nach jedem Lauf aus den verbauten Lagerteilen, Zukauf- und Druckteilen.") {
                        Button("Stückliste anfordern") { model.catalogActions?.requestBOM() }
                            .disabled(model.project == nil || model.kernelState != .ready)
                    }
                    .frame(minHeight: 260)
                } else {
                    kacheln
                    if !daten.positionen.isEmpty { gruppenAnteile }
                    HStack(alignment: .top, spacing: 18) {
                        einkaufVorschau
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                        zuschnittVorschau
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                    if !daten.warnungen.isEmpty { hinweise }
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 20)
            .frame(maxWidth: 1180, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: Kopf

    private var kopf: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text("Material")
                .font(.largeTitle.weight(.bold))
            Text(model.project?.name ?? "")
                .font(.title3)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer(minLength: 12)
            Text(standText)
                .font(.callout)
                .foregroundStyle(.secondary)
                .monospacedDigit()
                .lineLimit(1)
        }
    }

    private var standText: String {
        var t: [String] = []
        if daten.run > 0 { t.append("Lauf \(daten.run)") }
        if let s = daten.bestandStand { t.append("Bestand vom \(BestandText.anzeige(s) ?? s)") }
        if let h = k.preisHinweis { t.append(h) }
        return t.joined(separator: " · ")
    }

    // MARK: Kacheln

    private var kacheln: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 196, maximum: 320), spacing: 14)], spacing: 14) {
            KennzahlKachel(titel: "Teile", symbol: "cube", wert: KevFormat.integer(k.teile),
                           unter: KevFormat.count(k.positionen, one: "Position", many: "Positionen")) {
                material.zeige(.stueckliste)
            }
            KennzahlKachel(titel: "Gewicht", symbol: "scalemass", wert: KevFormat.kg(k.kg),
                           unter: k.eigenteile > 0 ? KevFormat.count(k.eigenteile, one: "Eigenteil", many: "Eigenteile") + " dabei" : "aus Stückliste") {
                material.zeige(.stueckliste)
            }
            KennzahlKachel(titel: "Materialkosten", symbol: "eurosign", wert: k.kostenText,
                           unter: k.preisHinweis ?? "Richtpreise ohne Gewähr") {
                material.zeige(.stueckliste)
            }
            KennzahlKachel(titel: "Zu kaufen", symbol: "cart", wert: einkaufWert, unter: einkaufUnter,
                           farbe: daten.einkauf.isEmpty ? MaterialKennzeichen.rest.color : MaterialKennzeichen.kaufen.color) {
                material.zeige(.einkauf)
            }
            KennzahlKachel(titel: "Zuschnitt", symbol: "scissors", wert: k.zuschnittText,
                           unter: k.verschnittText == "–" ? "nichts zu schneiden" : "Verschnitt " + k.verschnittText) {
                material.zeige(.zuschnitt)
            }
            .help(MaterialZuschnitt.hilfe)
            KennzahlKachel(titel: "Reste", symbol: "arrow.3.trianglepath",
                           wert: KevFormat.count(k.resteImBestand, one: "Rest", many: "Reste"),
                           unter: k.neueReste > 0
                               ? KevFormat.count(k.neueReste, one: "neuer Rest", many: "neue Reste") + " nach dem Bau"
                               : KevFormat.count(k.lagerteileImBestand, one: "Lagerteil", many: "Lagerteile") + " im Bestand",
                           farbe: MaterialKennzeichen.rest.color) {
                material.zeige(.bestand)
            }
            KennzahlKachel(titel: "Druckteile", symbol: "printer.fill", wert: KevFormat.integer(k.druckteile),
                           unter: k.druckteile == 0 ? "keine"
                               : KevFormat.mass(grams: k.druckGramm) + " Filament" + (k.druckPreis.map { " · " + KevFormat.euro($0) } ?? ""),
                           farbe: MaterialKennzeichen.druckteil.color) {
                material.zeige(.druck)
            }
            KennzahlKachel(titel: "Zukaufteile", symbol: "bag", wert: KevFormat.integer(k.zukaufteile),
                           unter: k.wartetAufCAD > 0 ? "\(k.wartetAufCAD) wartet auf CAD"
                               : (k.einkaufZukaufSumme.map { "≈ " + KevFormat.euro($0) } ?? "keine"),
                           farbe: MaterialKennzeichen.zukauf.color) {
                material.zeige(.zukauf)
            }
            KennzahlKachel(titel: "Freigaben", symbol: "checkmark.seal",
                           wert: k.freigaben == 0 ? "Keine offen" : KevFormat.count(k.freigaben, one: "Vorschlag", many: "Vorschläge"),
                           unter: k.inventarVerstoesse > 0
                               ? KevFormat.count(k.inventarVerstoesse, one: "Teil", many: "Teile") + " nicht im Inventar"
                               : "Lagerkatalog öffnen",
                           farbe: k.freigaben > 0 || k.inventarVerstoesse > 0 ? .orange : .secondary) {
                session.showCatalog(section: k.freigaben > 0 ? .suggestions : nil)
            }
        }
    }

    private var einkaufWert: String {
        guard k.mitBestand || k.einkaufZukauf > 0 else { return "–" }
        if daten.einkauf.isEmpty { return "Nichts" }
        return k.einkaufText
    }

    private var einkaufUnter: String {
        guard k.mitBestand || k.einkaufZukauf > 0 else { return "ohne Bestandsabgleich" }
        if daten.einkauf.isEmpty { return "alles im Bestand" }
        let offen = material.abgehakt.offen(daten.einkauf).count
        var t = KevFormat.count(daten.einkauf.count, one: "Position", many: "Positionen")
        if offen < daten.einkauf.count { t += ", \(offen) offen" }
        return t
    }

    // MARK: Anteile

    private var gruppenAnteile: some View {
        let gruppen = daten.gruppen
        let gesamt = gruppen.compactMap { MaterialDaten.summen($0.positionen).preis }.reduce(0, +)
        return VStack(alignment: .leading, spacing: 10) {
            Text("Kosten nach Gruppen").font(.headline)
            if gesamt > 0 {
                GeometryReader { geo in
                    HStack(spacing: 2) {
                        ForEach(gruppen, id: \.gruppe) { g in
                            let p = MaterialDaten.summen(g.positionen).preis ?? 0
                            if p > 0 {
                                RoundedRectangle(cornerRadius: 3, style: .continuous)
                                    .fill(Self.farbe(g.gruppe))
                                    .frame(width: max(3, (geo.size.width - CGFloat(gruppen.count) * 2) * p / gesamt))
                                    .help("\(g.gruppe.titel): \(KevFormat.euro(p))")
                            }
                        }
                    }
                }
                .frame(height: 12)
            }
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                ForEach(gruppen, id: \.gruppe) { g in
                    let s = MaterialDaten.summen(g.positionen)
                    GridRow {
                        HStack(spacing: 7) {
                            Circle().fill(Self.farbe(g.gruppe)).frame(width: 8, height: 8)
                            Text(g.gruppe.titel)
                        }
                        Text(KevFormat.count(g.positionen.count, one: "Position", many: "Positionen"))
                            .foregroundStyle(.secondary)
                        Text(KevFormat.count(s.teile, one: "Teil", many: "Teile")).foregroundStyle(.secondary)
                            .gridColumnAlignment(.trailing)
                        Text(s.kg > 0 ? KevFormat.kg(s.kg) : "–").foregroundStyle(.secondary)
                            .gridColumnAlignment(.trailing)
                        Text(s.preis.map(KevFormat.euro) ?? "–").fontWeight(.medium)
                            .gridColumnAlignment(.trailing)
                        Text(gesamt > 0 && (s.preis ?? 0) > 0 ? KevFormat.number((s.preis ?? 0) / gesamt * 100, digits: 0) + " %" : "")
                            .foregroundStyle(.secondary)
                            .gridColumnAlignment(.trailing)
                    }
                    .monospacedDigit()
                    .contentShape(Rectangle())
                    .onTapGesture { material.zeige(.stueckliste) }
                }
            }
            .font(.callout)
        }
        .padding(16)
        .background(KachelGrund())
    }

    /// Ruhige Farben je Gruppe (Kosten-Balken), passend zu den Kennzeichen.
    static func farbe(_ g: MaterialGruppe) -> Color {
        switch g {
        case .stangen: return Color(.sRGB, red: 0.29, green: 0.50, blue: 0.80)
        case .platten: return Color(.sRGB, red: 0.40, green: 0.66, blue: 0.86)
        case .normteile: return Color(.sRGB, red: 0.55, green: 0.57, blue: 0.62)
        case .zukauf: return MaterialKennzeichen.zukauf.color
        case .druckteile: return MaterialKennzeichen.druckteil.color
        case .eigenteile: return MaterialKennzeichen.eigenteil.color
        case .weitere: return Color(.sRGB, red: 0.70, green: 0.70, blue: 0.72)
        }
    }

    // MARK: Vorschauen

    private var einkaufVorschau: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Einkaufsliste", systemImage: "cart").font(.headline)
                Spacer()
                Button("Alle zeigen") { material.zeige(.einkauf) }
                    .buttonStyle(.link)
            }
            if !k.mitBestand && daten.zukaufEinkauf.isEmpty {
                Text("Der Kernel hat den Bestand noch nicht abgeglichen.").foregroundStyle(.secondary)
            } else if daten.einkauf.isEmpty {
                Label("Nichts zu kaufen: alles ist im Bestand des Projekts.", systemImage: "checkmark.seal.fill")
                    .foregroundStyle(MaterialKennzeichen.rest.color)
            } else {
                ForEach(daten.einkauf.prefix(6)) { z in
                    EinkaufKurzZeile(zeile: z, abgehakt: material.abgehakt.abgehakt(z)) { material.umschalten(z) }
                }
                if daten.einkauf.count > 6 {
                    Text("und \(daten.einkauf.count - 6) weitere").font(.callout).foregroundStyle(.secondary)
                }
                Divider()
                HStack {
                    Text("Summe").foregroundStyle(.secondary)
                    Spacer()
                    Text(k.einkaufText).fontWeight(.semibold).monospacedDigit()
                }
            }
        }
        .padding(16)
        .background(KachelGrund())
    }

    private var zuschnittVorschau: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Zuschnitt", systemImage: "scissors").font(.headline)
                Spacer()
                Button("Alle zeigen") { material.zeige(.zuschnitt) }
                    .buttonStyle(.link)
            }
            if daten.zuschnitte.isEmpty {
                Text("Kein Zuschnitt: das Modell verbaut keine Stangenware und keine Platten.").foregroundStyle(.secondary)
            } else {
                ForEach(daten.zuschnitte.prefix(3)) { z in
                    ZuschnittBlock(zuschnitt: z, lines: daten.lines(z.stockID), mindestrest: daten.mindestrest(z.stockID),
                                   verschnitt: daten.verschnitt(z), groesse: .kompakt, selected: material.auswahl) { line in
                        material.zeige(.zuschnitt, position: line.pos, stockID: z.stockID)
                    }
                }
                if daten.zuschnitte.count > 3 {
                    Text("und \(daten.zuschnitte.count - 3) weitere Lagerteile").font(.callout).foregroundStyle(.secondary)
                }
            }
        }
        .padding(16)
        .background(KachelGrund())
    }

    private var hinweise: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Hinweise zur Stückliste", systemImage: "exclamationmark.triangle").font(.headline)
            ForEach(Array(daten.warnungen.enumerated()), id: \.offset) { _, w in
                Label(w, systemImage: "exclamationmark.triangle.fill")
                    .symbolRenderingMode(.multicolor)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(KachelGrund())
    }
}

/// Grund einer Kachel: ruhige Fläche mit feinem Rand, in Hell und Dunkel.
struct KachelGrund: View {
    var hervor = false

    var body: some View {
        RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(Color(nsColor: .controlBackgroundColor))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color.primary.opacity(hervor ? 0.18 : 0.08), lineWidth: 1)
            )
            .shadow(color: .black.opacity(hervor ? 0.10 : 0.04), radius: hervor ? 8 : 3, y: hervor ? 3 : 1)
    }
}

/// Kachel mit einer Kennzahl: Symbol, Titel, großer Wert, Zeile darunter; Klick führt in den Abschnitt.
struct KennzahlKachel: View {
    let titel: String
    let symbol: String
    let wert: String
    let unter: String
    var farbe: Color = .accentColor
    var aktion: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: aktion) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Image(systemName: symbol)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(farbe)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(farbe.opacity(0.14)))
                    Text(titel)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .opacity(hover ? 1 : 0)
                }
                Text(wert)
                    .font(.system(size: 24, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(unter)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(KachelGrund(hervor: hover))
            .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.easeOut(duration: 0.12)) { hover = h } }
        .accessibilityLabel("\(titel): \(wert), \(unter)")
    }
}

/// Kurze Zeile der Einkaufsliste mit Häkchen (Übersicht, Inspektor).
struct EinkaufKurzZeile: View {
    let zeile: MaterialEinkauf
    let abgehakt: Bool
    var umschalten: () -> Void

    var body: some View {
        let p = zeile.position
        HStack(spacing: 8) {
            Button(action: umschalten) {
                Image(systemName: abgehakt ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 14))
                    .foregroundStyle(abgehakt ? MaterialKennzeichen.rest.color : Color.secondary)
            }
            .buttonStyle(.plain)
            .help(abgehakt ? "Wieder offen" : "Abhaken: gekauft")
            Text("\(p.mengeText) ×").monospacedDigit().fontWeight(.semibold).frame(minWidth: 28, alignment: .trailing)
            VStack(alignment: .leading, spacing: 0) {
                Text(p.benennung).lineLimit(1)
                Text(p.einheit).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            .strikethrough(abgehakt, color: .secondary)
            .foregroundStyle(abgehakt ? .secondary : .primary)
            Spacer(minLength: 6)
            if zeile.art == .zukauf { KennzeichenMarke(kennzeichen: .zukauf, nurSymbol: true) }
            Text(p.preis.map(KevFormat.euro) ?? "–").monospacedDigit().foregroundStyle(.secondary)
        }
        .font(.callout)
    }
}
