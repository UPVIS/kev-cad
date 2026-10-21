import KevCADCore
import SwiftUI

/// Bereich unter der Stücklisten-Tabelle, sobald der Kernel Bestandsangaben schickt (BESTAND.md): Zuschnitt mit Resten
/// oder Einkaufsliste, umschaltbar. Ohne Bestandsangaben bleibt der bisherige Zuschnitt der Stückliste.
struct StuecklisteUntenView: View {
    @ObservedObject var model: AppModel
    let bom: BillOfMaterials
    let zuschnitt: BOMBestand
    let selected: Int?
    var onSelect: (BOMLine) -> Void
    @ObservedObject private var ui = BestandUI.shared

    /// Zuschnitte mit Quellen und, falls der Kernel für ein Lagerteil keine Quellen schickt, der bisherige Zuschnitt.
    private var zuschnitte: [BestandZuschnitt] {
        var out = zuschnitt.zuschnitte
        for cut in bom.cuts where !out.contains(where: { $0.stockID == cut.stockID }) {
            out.append(BestandZuschnitt(cut: cut))
        }
        return out
    }

    var body: some View {
        let liste = zuschnitte
        VStack(spacing: 0) {
            leiste(liste)
            Divider()
            switch ui.unten {
            case .zuschnitt:
                ZuschnittListe(
                    model: model, bom: bom, zuschnitte: liste, stueckgut: zuschnitt.stueckgut, selected: selected,
                    onSelect: onSelect)
            case .einkauf:
                EinkaufslisteView(model: model, zuschnitt: zuschnitt)
            }
        }
        .frame(minHeight: 120, idealHeight: idealHeight(liste), maxHeight: min(idealHeight(liste), 360))
        // Zuschnitt bzw. Einkaufsliste bekommen ihre Höhe zuerst, die Tabelle darüber scrollt
        .layoutPriority(1)
    }

    private func idealHeight(_ liste: [BestandZuschnitt]) -> CGFloat {
        switch ui.unten {
        case .zuschnitt:
            let inhalt = liste.reduce(CGFloat(0)) { sum, z in
                sum + 30 + (z.istPlatte ? 150 : CGFloat(max(1, z.quellen.count)) * 24)
            }
            let stueck = zuschnitt.stueckgut.isEmpty ? 0 : 30 + CGFloat(zuschnitt.stueckgut.count) * 20
            return 30 + max(60, inhalt + stueck) + 12
        case .einkauf:
            return 30 + 30 + CGFloat(max(2, zuschnitt.einkaufsliste.count)) * 34 + 30
        }
    }

    // MARK: Leiste

    private func leiste(_ liste: [BestandZuschnitt]) -> some View {
        HStack(spacing: 12) {
            Picker("Ansicht", selection: $ui.unten) {
                Text("Zuschnitt").tag(StuecklisteUnten.zuschnitt)
                Text(zuschnitt.einkaufsliste.isEmpty ? "Einkaufsliste" : "Einkaufsliste · \(zuschnitt.einkaufsliste.count)")
                    .tag(StuecklisteUnten.einkauf)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .controlSize(.small)
            .fixedSize()
            if zuschnitt.fehlt, ui.unten == .zuschnitt {
                Label("Es fehlt Material", systemImage: "cart.badge.plus")
                    .foregroundStyle(ZuschnittFarbe.kaufen.color)
                    .help("Nicht alles ist im Bestand des Projekts, siehe Einkaufsliste")
            }
            Spacer(minLength: 8)
            switch ui.unten {
            case .zuschnitt:
                ZuschnittLegende()
            case .einkauf:
                einkaufKnoepfe
            }
        }
        .font(.callout)
        .lineLimit(1)
        .padding(.horizontal, 12)
        .frame(height: 30)
    }

    @ViewBuilder
    private var einkaufKnoepfe: some View {
        if let summe = zuschnitt.summe {
            HStack(spacing: 5) {
                Text("Summe").foregroundStyle(.secondary)
                Text(KevFormat.euro(summe)).fontWeight(.semibold).monospacedDigit()
            }
            .help(zuschnitt.ohnePreis > 0
                ? "\(KevFormat.count(zuschnitt.ohnePreis, one: "Position", many: "Positionen")) ohne Preis" : "Richtpreise")
        }
        Button {
            copyToPasteboard(EinkaufslisteFormat.text(
                zuschnitt.einkaufsliste, summe: zuschnitt.summe, projekt: model.project?.name,
                stand: BestandText.anzeige(BestandText.heute(), mitZeit: false)))
        } label: {
            Label("Kopieren", systemImage: "doc.on.doc")
        }
        .controlSize(.small)
        .help("Einkaufsliste als Text kopieren, zum Weiterleiten per Nachricht oder Mail")
        Button {
            model.bestandActions?.exportEinkaufsliste()
        } label: {
            Label("Als CSV exportieren", systemImage: "square.and.arrow.up")
        }
        .controlSize(.small)
        .disabled(model.bestandActions == nil)
        .help("Einkaufsliste als CSV in output/ speichern und im Finder zeigen (Numbers, Excel)")
    }
}

/// Farberklärung des Zuschnitts.
struct ZuschnittLegende: View {
    var body: some View {
        HStack(spacing: 10) {
            ForEach(ZuschnittQuelleArt.allCases, id: \.self) { art in
                HStack(spacing: 4) {
                    RoundedRectangle(cornerRadius: 2, style: .continuous).fill(art.color.opacity(0.85))
                        .frame(width: 10, height: 10)
                    Text(art.farbe.titel)
                }
            }
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .strokeBorder(ZuschnittFarbe.restNeu.color, style: StrokeStyle(lineWidth: 1.2, dash: [3, 2]))
                    .frame(width: 12, height: 10)
                Text(ZuschnittFarbe.restNeu.titel)
            }
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 2, style: .continuous).fill(ZuschnittFarbe.verschnitt.color.opacity(0.45))
                    .frame(width: 10, height: 10)
                Text(ZuschnittFarbe.verschnitt.titel)
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }
}

// MARK: - Zuschnitt

private struct ZuschnittListe: View {
    @ObservedObject var model: AppModel
    let bom: BillOfMaterials
    let zuschnitte: [BestandZuschnitt]
    var stueckgut: [StueckgutBedarf] = []
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        if zuschnitte.isEmpty && stueckgut.isEmpty {
            Text("Kein Zuschnitt: das Modell verbaut keine Stangenware und keine Platten.")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView(.vertical) {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(zuschnitte) { z in
                        ZuschnittBlock(
                            zuschnitt: z, lines: bom.lines.filter { $0.stockID == z.stockID },
                            mindestrest: z.mindestrest ?? model.bestandZustand.bestand?.mindestrest(z.stockID)
                                ?? BestandEinstellungen.standard.mindestrestMM,
                            selected: selected, onSelect: onSelect)
                    }
                    if !stueckgut.isEmpty {
                        StueckgutBlock(model: model, stueckgut: stueckgut)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }
}

private struct ZuschnittBlock: View {
    let zuschnitt: BestandZuschnitt
    let lines: [BOMLine]
    let mindestrest: Double
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            kopf
            if zuschnitt.istPlatte {
                PlattenReihe(zuschnitt: zuschnitt, lines: lines, selected: selected, onSelect: onSelect)
                if !zuschnitt.zuGross.isEmpty {
                    Label("Größer als die Platte: " + zuschnitt.zuGross.map(\.masseText).joined(separator: ", "),
                          systemImage: "exclamationmark.triangle.fill")
                        .symbolRenderingMode(.multicolor)
                        .font(.callout)
                }
            } else {
                ForEach(zuschnitt.quellen) { q in
                    HStack(spacing: 8) {
                        QuellenMarke(art: q.art, text: marke(q))
                            .frame(width: 132, alignment: .leading)
                            .help(hilfe(q))
                        GeometryReader { geo in
                            let skala = ZuschnittMassstab.skala(
                                breite: geo.size.width, laengen: zuschnitt.quellen.compactMap(\.laenge))
                            ZuschnittLeiste(
                                quelle: q, saegeschnitt: zuschnitt.saegeschnitt, mindestrest: mindestrest, skala: skala,
                                lines: lines, selected: selected, onSelect: onSelect)
                        }
                        .frame(height: 18)
                    }
                }
            }
        }
    }

    private var kopf: some View {
        HStack(spacing: 6) {
            Image(systemName: "scissors").foregroundStyle(.secondary)
            Text(zuschnitt.benennung).fontWeight(.semibold)
            Text("· " + zuschnitt.herkunftText).foregroundStyle(.secondary)
            Spacer(minLength: 8)
            if zuschnitt.hatNeueReste {
                Text("neue Reste: " + zuschnitt.neueResteText)
                    .foregroundStyle(ZuschnittFarbe.restNeu.color)
                    .help("Kommen nach „Gebaut“ mit neuer Kennung in den Bestand")
            }
            if let v = zuschnitt.verschnittProzent {
                Text("Verschnitt \(KevFormat.number(v, digits: 1)) %")
                    .foregroundStyle(.secondary)
                    .help("Anteil der verplanten Länge bzw. Fläche, der nicht in Teilen steckt")
            }
        }
        .font(.callout)
        .monospacedDigit()
        .lineLimit(1)
    }

    private func marke(_ q: ZuschnittQuelle) -> String {
        let laenge = q.laenge.map { KevFormat.compact($0, maxDigits: 1) } ?? "–"
        switch q.art {
        case .rest: return "\(q.kennung ?? "Rest") · \(laenge)"
        case .bestand: return "Bestand · \(laenge)"
        case .kaufen: return "kaufen · \(laenge)"
        }
    }

    private func hilfe(_ q: ZuschnittQuelle) -> String {
        switch q.art {
        case .rest: return "Rest \(q.kennung ?? "") aus dem Bestand, \(q.laenge.map(KevFormat.length) ?? "")"
        case .bestand: return "Ganze Stange aus dem Bestand, \(q.laenge.map(KevFormat.length) ?? "")"
        case .kaufen: return "Muss gekauft werden: Stange \(q.laenge.map(KevFormat.length) ?? "")"
        }
    }
}

/// Eine Stange maßstäblich: Stücke in der Farbe der Quelle, Sägeschnitte als Lücke, am Ende neuer Rest oder Verschnitt.
private struct ZuschnittLeiste: View {
    let quelle: ZuschnittQuelle
    let saegeschnitt: Double
    let mindestrest: Double
    let skala: Double
    let lines: [BOMLine]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        let segmente = quelle.segmente(saegeschnitt: saegeschnitt, mindestrest: mindestrest)
        ZStack(alignment: .leading) {
            ForEach(Array(segmente.enumerated()), id: \.offset) { _, s in
                segment(s)
                    .frame(width: max(s.art == .schnitt ? 0 : 2, CGFloat(s.laenge * skala)), height: 18)
                    .offset(x: CGFloat(s.start * skala))
            }
        }
        .frame(width: CGFloat((quelle.laenge ?? 0) * skala), alignment: .leading)
        .clipped()
    }

    @ViewBuilder
    private func segment(_ s: LeistenSegment) -> some View {
        let breite = CGFloat(s.laenge * skala)
        switch s.art {
        case .stueck:
            let line = lines.first { abs(($0.laenge ?? -1) - s.laenge) < 0.5 }
            let dimmed = selected != nil && line?.pos != selected
            let hervor = line != nil && line?.pos == selected
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(quelle.art.color.opacity(dimmed ? 0.35 : 0.85))
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(hervor ? Color.primary.opacity(0.75) : Color.black.opacity(0.12),
                                      lineWidth: hervor ? 1.5 : 0.5))
                .overlay {
                    if breite > 30 {
                        Text(KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(.caption2.weight(.medium).monospacedDigit())
                            .foregroundStyle(dimmed ? Color.primary.opacity(0.55) : Color.white)
                            .shadow(color: .black.opacity(dimmed ? 0 : 0.25), radius: 0.5, y: 0.5)
                            .lineLimit(1)
                    }
                }
                .contentShape(Rectangle())
                .help(line.map { "Pos. \($0.pos) · \(KevFormat.length(s.laenge))" } ?? KevFormat.length(s.laenge))
                .onTapGesture { if let line { onSelect(line) } }
        case .schnitt:
            Color.clear
        case .restNeu:
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(ZuschnittFarbe.restNeu.color.opacity(0.08))
                .overlay(
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .strokeBorder(ZuschnittFarbe.restNeu.color, style: StrokeStyle(lineWidth: 1.2, dash: [4, 2])))
                .overlay {
                    if breite > 46 {
                        Text((breite > 96 ? "neuer Rest " : "") + KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(.caption2.weight(.medium).monospacedDigit())
                            .foregroundStyle(ZuschnittFarbe.restNeu.color)
                            .lineLimit(1)
                    }
                }
                .help("Neuer Rest \(KevFormat.length(s.laenge)): kommt nach „Gebaut“ mit Kennung in den Bestand")
        case .verschnitt:
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(ZuschnittFarbe.verschnitt.color.opacity(0.35))
                .overlay {
                    if breite > 40 {
                        Text(KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                .help("Verschnitt \(KevFormat.length(s.laenge)): unter dem Mindestrest von \(KevFormat.length(mindestrest)), "
                    + "kommt nicht in den Bestand")
        }
    }
}

/// Platten als 2D-Ansicht, alle im selben Maßstab.
private struct PlattenReihe: View {
    let zuschnitt: BestandZuschnitt
    let lines: [BOMLine]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    static let box = CGSize(width: 280, height: 112)

    var body: some View {
        let platten = zuschnitt.quellen.map { (b: $0.b ?? zuschnitt.platteB ?? 1, h: $0.h ?? zuschnitt.platteH ?? 1) }
        let skala = ZuschnittMassstab.skala2D(breite: Self.box.width, hoehe: Self.box.height, platten: platten)
        ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: 16) {
                ForEach(zuschnitt.quellen) { q in
                    VStack(alignment: .leading, spacing: 4) {
                        PlattenZeichnung(
                            quelle: q, b: q.b ?? zuschnitt.platteB ?? 1, h: q.h ?? zuschnitt.platteH ?? 1, skala: skala,
                            saegeschnitt: zuschnitt.saegeschnitt, lines: lines, selected: selected, onSelect: onSelect)
                        QuellenMarke(art: q.art, text: q.titel)
                    }
                }
            }
            .padding(.vertical, 2)
        }
        .scrollBounceBehavior(.basedOnSize)
    }
}

private struct PlattenZeichnung: View {
    let quelle: ZuschnittQuelle
    let b: Double
    let h: Double
    let skala: Double
    let saegeschnitt: Double
    let lines: [BOMLine]
    let selected: Int?
    var onSelect: (BOMLine) -> Void

    var body: some View {
        let farbe = quelle.art.color
        ZStack(alignment: .topLeading) {
            // ganze Platte bzw. Rest: was nicht belegt ist, ist Verschnitt (grau)
            Rectangle()
                .fill(ZuschnittFarbe.verschnitt.color.opacity(0.22))
                .overlay(Rectangle().strokeBorder(farbe.opacity(0.9), lineWidth: 1))
                .frame(width: CGFloat(b * skala), height: CGFloat(h * skala))
            ForEach(Array(quelle.resteNeu.enumerated()), id: \.offset) { _, r in
                Rectangle()
                    .fill(Color(nsColor: .controlBackgroundColor))
                    .overlay(
                        Rectangle().strokeBorder(
                            ZuschnittFarbe.restNeu.color, style: StrokeStyle(lineWidth: 1.2, dash: [4, 2])))
                    .overlay {
                        if r.b * skala > 60, r.h * skala > 14 {
                            Text(KevFormat.compact(r.b, maxDigits: 1) + " × " + KevFormat.compact(r.h, maxDigits: 1))
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(ZuschnittFarbe.restNeu.color)
                        }
                    }
                    .frame(width: CGFloat(r.b * skala), height: CGFloat(r.h * skala))
                    .offset(x: CGFloat(r.x * skala), y: CGFloat((h - r.y - r.h) * skala))
                    .help("Neuer Rest \(r.masseText): kommt nach „Gebaut“ mit Kennung in den Bestand")
            }
            ForEach(Array(quelle.flaechenLayout(saegeschnitt: saegeschnitt).enumerated()), id: \.offset) { _, f in
                let line = line(for: f)
                let dimmed = selected != nil && line?.pos != selected
                Rectangle()
                    .fill(farbe.opacity(dimmed ? 0.35 : 0.8))
                    .overlay(Rectangle().strokeBorder(Color.black.opacity(0.18), lineWidth: 0.5))
                    .overlay {
                        if f.b * skala > 58, f.h * skala > 14 {
                            HStack(spacing: 2) {
                                if f.gedreht { Image(systemName: "rotate.right").font(.system(size: 8, weight: .semibold)) }
                                Text(KevFormat.compact(f.b, maxDigits: 1) + " × " + KevFormat.compact(f.h, maxDigits: 1))
                            }
                            .font(.caption2.weight(.medium).monospacedDigit())
                            .foregroundStyle(.white)
                            .shadow(color: .black.opacity(0.3), radius: 0.5, y: 0.5)
                        }
                    }
                    .frame(width: CGFloat(f.b * skala), height: CGFloat(f.h * skala))
                    .offset(x: CGFloat(f.x * skala), y: CGFloat((h - f.y - f.h) * skala))
                    .contentShape(Rectangle())
                    .help((line.map { "Pos. \($0.pos) · " } ?? "") + f.masseText + (f.gedreht ? " · gedreht" : ""))
                    .onTapGesture { if let line { onSelect(line) } }
            }
        }
        .frame(width: CGFloat(b * skala), height: CGFloat(h * skala), alignment: .topLeading)
        .clipped()
        .overlay(Rectangle().strokeBorder(farbe, lineWidth: 1.5))
    }

    /// Stücklistenzeile eines Plattenstücks (gleiche Maße, auch gedreht).
    private func line(for f: ZuschnittFlaeche) -> BOMLine? {
        let a = BestandText.format(f.b, f.h)
        let c = BestandText.format(f.h, f.b)
        return lines.first { $0.masseText == a || $0.masseText == c } ?? (lines.count == 1 ? lines.first : nil)
    }
}

// MARK: - Einkaufsliste

/// Einkaufsliste unter der Stückliste: Menge, Einheit, Preis mit Stand, Link, Hinweis.
struct EinkaufslisteView: View {
    @ObservedObject var model: AppModel
    let zuschnitt: BOMBestand

    var body: some View {
        if zuschnitt.einkaufsliste.isEmpty {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                Text("Nichts zu kaufen: alles für dieses Modell ist im Bestand des Projekts.")
            }
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            VStack(spacing: 0) {
                Table(zuschnitt.einkaufsliste) {
                    TableColumn("Menge") { p in
                        Text(p.mengeText)
                            .monospacedDigit()
                            .frame(maxWidth: .infinity, alignment: .trailing)
                    }
                    .width(min: 44, ideal: 52, max: 70)
                    TableColumn("Einheit") { p in
                        Text(p.einheit).lineLimit(1).help(p.einheit)
                    }
                    .width(min: 90, ideal: 130)
                    TableColumn("Benennung") { p in
                        HStack(spacing: 6) {
                            ArtTile(art: model.lagerteilArt(p.id), size: 18, tint: ZuschnittFarbe.kaufen.color)
                            Text(p.benennung).lineLimit(1)
                        }
                        .help("\(p.benennung)\nLagerteil \(p.id)")
                    }
                    .width(min: 140, ideal: 210)
                    TableColumn("Preis") { p in
                        VStack(alignment: .trailing, spacing: 0) {
                            Text(p.preis.map(KevFormat.euro) ?? "–")
                                .monospacedDigit()
                                .foregroundStyle(p.preis == nil ? .tertiary : .primary)
                            if let je = p.preisJe, p.menge != 1 {
                                Text("je \(KevFormat.euro(je))").font(.caption2).foregroundStyle(.secondary).monospacedDigit()
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .help(preisHilfe(p))
                    }
                    .width(min: 64, ideal: 84)
                    TableColumn("Stand") { p in
                        Text(p.stand.flatMap { BestandText.anzeige($0, mitZeit: false) } ?? standText ?? "–")
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    .width(min: 56, ideal: 80)
                    TableColumn("Bezugsquelle") { p in
                        if let link = p.link {
                            Link(destination: link) {
                                Label(p.linkTitel ?? link.absoluteString, systemImage: "arrow.up.right.square")
                                    .lineLimit(1)
                            }
                            .help(link.absoluteString)
                        } else {
                            Text("–").foregroundStyle(.tertiary)
                        }
                    }
                    .width(min: 80, ideal: 110)
                    TableColumn("Hinweis") { p in
                        Text(p.hinweis ?? "")
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .help(p.hinweis ?? "")
                    }
                    .width(min: 100, ideal: 240)
                }
                .tableStyle(.inset)
                .alternatingRowBackgrounds()
                .contextMenu(forSelectionType: EinkaufsPosition.ID.self) { ids in
                    if let id = ids.first, let p = zuschnitt.einkaufsliste.first(where: { $0.id == id }) {
                        Button("Zeile kopieren") {
                            copyToPasteboard(EinkaufslisteFormat.text([p], summe: nil, projekt: nil)
                                .split(separator: "\n").dropFirst().joined(separator: "\n"))
                        }
                        if let link = p.link {
                            Button("Bezugsquelle öffnen") { NSWorkspace.shared.open(link) }
                            Button("Link kopieren") { copyToPasteboard(link.absoluteString) }
                        }
                    }
                }
                summenZeile
            }
        }
    }

    /// Stand der Preise: aus dem Hinweis der Stückliste („Richtpreise, Stand 2026-10“).
    private var standText: String? {
        guard let hinweis = model.bom?.totals.preisHinweis, let r = hinweis.range(of: "Stand ") else { return nil }
        return String(hinweis[r.upperBound...]).trimmingCharacters(in: .whitespaces)
    }

    private func preisHilfe(_ p: EinkaufsPosition) -> String {
        guard p.preis != nil else { return "Kein Preis im Katalog" }
        var t = "\(p.mengeText) × \(p.preisJe.map(KevFormat.euro) ?? "–")"
        if let stand = p.stand ?? standText { t += ", Stand \(stand)" }
        return t + " (Richtpreis)"
    }

    private var summenZeile: some View {
        HStack(spacing: 10) {
            if let stand = zuschnitt.bestandStand {
                Text("Bestand vom \(BestandText.anzeige(stand) ?? stand)")
                    .foregroundStyle(.secondary)
                    .help("Zeitpunkt der Bestandsdatei, nach der die Einkaufsliste gerechnet ist")
            }
            Spacer(minLength: 8)
            if let h = zuschnitt.einkaufHinweis, h != model.bom?.totals.preisHinweis {
                Text(h).foregroundStyle(.secondary).help(h)
            } else if zuschnitt.ohnePreis > 0 {
                Text("\(KevFormat.count(zuschnitt.ohnePreis, one: "Position", many: "Positionen")) ohne Preis")
                    .foregroundStyle(.secondary)
            }
            Text("Summe").foregroundStyle(.secondary)
            Text(zuschnitt.summe.map(KevFormat.euro) ?? "–")
                .fontWeight(.semibold)
                .monospacedDigit()
        }
        .font(.callout)
        .lineLimit(1)
        .padding(.horizontal, 12)
        .frame(height: 28)
        .overlay(alignment: .top) { Divider() }
    }
}

/// Stückgut des Modells: gebraucht, aus dem Bestand, zu kaufen (BOM.stueckgut).
private struct StueckgutBlock: View {
    @ObservedObject var model: AppModel
    let stueckgut: [StueckgutBedarf]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "screwdriver").foregroundStyle(.secondary)
                Text("Stückgut").fontWeight(.semibold)
            }
            .font(.callout)
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 3) {
                ForEach(stueckgut) { s in
                    GridRow {
                        Text(s.benennung + (s.laenge != nil && !s.benennung.contains("Länge") ? " · \(s.masseText)" : ""))
                            .lineLimit(1)
                        Text("\(KevFormat.integer(s.anzahl)) gebraucht").foregroundStyle(.secondary)
                        QuellenMarke(art: .bestand, text: "\(KevFormat.integer(s.ausBestand)) aus Bestand")
                            .opacity(s.ausBestand > 0 ? 1 : 0.4)
                        if s.kaufen > 0 {
                            QuellenMarke(art: .kaufen, text: "\(KevFormat.integer(s.kaufen)) kaufen")
                        } else {
                            Text("")
                        }
                    }
                    .monospacedDigit()
                }
            }
            .font(.callout)
        }
    }
}
