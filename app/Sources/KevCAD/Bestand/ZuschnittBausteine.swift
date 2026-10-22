import KevCADCore
import SwiftUI

// Zuschnitt (BESTAND.md, Abschnitt „App“): je Stangenware und Platte die Stücke, farbig nach Quelle (Rest, Bestand,
// kaufen), neue Reste gestrichelt, Verschnitt grau. Dieselben Bausteine zeigen die Schnellansicht „Zuschnitt“ unter dem
// Viewport (kompakt) und der Abschnitt „Zuschnitt“ im Bereich „Material“ (groß). Die Daten kommen aus MaterialDaten.

/// Darstellungsgröße der Zuschnitt-Bausteine.
enum ZuschnittGroesse {
    case kompakt, gross

    var leiste: CGFloat { self == .kompakt ? 14 : 24 }
    var markenBreite: CGFloat { self == .kompakt ? 120 : 168 }
    var platte: CGSize { self == .kompakt ? CGSize(width: 170, height: 64) : CGSize(width: 440, height: 210) }
    var abstand: CGFloat { self == .kompakt ? 3 : 7 }
    var schrift: Font { self == .kompakt ? .callout : .body }
    var stueckSchrift: Font { self == .kompakt ? .system(size: 9, weight: .medium).monospacedDigit() : .caption.weight(.medium).monospacedDigit() }
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
        .lineLimit(1)
        .fixedSize()
        .help(MaterialZuschnitt.hilfe)
    }
}

// MARK: - Block je Lagerteil

/// Zuschnitt eines Lagerteils: Kopf mit Herkunft, neuen Resten und Verschnitt, darunter die Stangen bzw. Platten.
struct ZuschnittBlock: View {
    let zuschnitt: BestandZuschnitt
    let lines: [BOMLine]
    let mindestrest: Double
    let verschnitt: Double?
    var groesse: ZuschnittGroesse = .gross
    let selected: Set<Int>
    var onSelect: (BOMLine) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: groesse.abstand) {
            kopf
            if zuschnitt.istPlatte {
                PlattenReihe(zuschnitt: zuschnitt, lines: lines, groesse: groesse, selected: selected, onSelect: onSelect)
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
                            .frame(width: groesse.markenBreite, alignment: .leading)
                            .help(hilfe(q))
                        GeometryReader { geo in
                            let skala = ZuschnittMassstab.skala(
                                breite: geo.size.width, laengen: zuschnitt.quellen.compactMap(\.laenge))
                            ZuschnittLeiste(
                                quelle: q, saegeschnitt: zuschnitt.saegeschnitt, mindestrest: mindestrest, skala: skala,
                                hoehe: groesse.leiste, schrift: groesse.stueckSchrift, lines: lines, selected: selected,
                                onSelect: onSelect)
                        }
                        .frame(height: groesse.leiste)
                    }
                }
            }
        }
    }

    /// Kopf: wird es eng, fällt erst die Herkunft weg, dann die neuen Reste; der Name kürzt sich zuletzt.
    private var kopf: some View {
        ViewThatFits(in: .horizontal) {
            kopfZeile(herkunft: true, neueReste: true)
            kopfZeile(herkunft: false, neueReste: true)
            kopfZeile(herkunft: false, neueReste: false)
        }
        .font(groesse.schrift)
        .monospacedDigit()
        .lineLimit(1)
        .help(zuschnitt.benennung + " · " + zuschnitt.herkunftText
            + (zuschnitt.hatNeueReste ? "\nneue Reste: " + zuschnitt.neueResteText : ""))
    }

    private func kopfZeile(herkunft: Bool, neueReste: Bool) -> some View {
        HStack(spacing: 6) {
            if groesse == .gross {
                Image(systemName: zuschnitt.istPlatte ? "square.fill" : "line.diagonal").foregroundStyle(.secondary)
            }
            Text(zuschnitt.benennung).fontWeight(.semibold).truncationMode(.tail)
            if herkunft { Text("· " + zuschnitt.herkunftText).foregroundStyle(.secondary).fixedSize() }
            Spacer(minLength: 8)
            if neueReste, zuschnitt.hatNeueReste {
                Text("neue Reste: " + zuschnitt.neueResteText)
                    .foregroundStyle(ZuschnittFarbe.restNeu.color)
                    .fixedSize()
                    .help(MaterialKennzeichen.restNeu.hilfe)
            }
            if let v = verschnitt {
                Text("Verschnitt \(KevFormat.number(v, digits: 1)) %")
                    .foregroundStyle(.secondary)
                    .fixedSize()
                    .help(MaterialZuschnitt.hilfe)
            }
        }
    }

    private func marke(_ q: ZuschnittQuelle) -> String {
        let laenge = q.laenge.map { KevFormat.compact($0, maxDigits: 1) } ?? "–"
        switch q.art {
        case .rest: return "\(q.kennung ?? "Rest") · \(laenge)"
        case .bestand: return "\(MaterialKennzeichen.bestand.titel) · \(laenge)"
        case .kaufen: return "\(MaterialKennzeichen.kaufen.titel) · \(laenge)"
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
struct ZuschnittLeiste: View {
    let quelle: ZuschnittQuelle
    let saegeschnitt: Double
    let mindestrest: Double
    let skala: Double
    var hoehe: CGFloat = 18
    var schrift: Font = .caption2.weight(.medium).monospacedDigit()
    let lines: [BOMLine]
    let selected: Set<Int>
    var onSelect: (BOMLine) -> Void

    var body: some View {
        let segmente = quelle.segmente(saegeschnitt: saegeschnitt, mindestrest: mindestrest)
        ZStack(alignment: .leading) {
            ForEach(Array(segmente.enumerated()), id: \.offset) { _, s in
                segment(s)
                    .frame(width: max(s.art == .schnitt ? 0 : 2, CGFloat(s.laenge * skala)), height: hoehe)
                    .offset(x: CGFloat(s.start * skala))
            }
        }
        .frame(width: CGFloat((quelle.laenge ?? 0) * skala), alignment: .leading)
        .clipped()
    }

    @ViewBuilder
    private func segment(_ s: LeistenSegment) -> some View {
        let breite = CGFloat(s.laenge * skala)
        let radius: CGFloat = hoehe < 16 ? 2 : 3
        switch s.art {
        case .stueck:
            let line = lines.first { abs(($0.laenge ?? -1) - s.laenge) < 0.5 }
            let dimmed = !selected.isEmpty && !(line.map { selected.contains($0.pos) } ?? false)
            let hervor = line.map { selected.contains($0.pos) } ?? false
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .fill(quelle.art.color.opacity(dimmed ? 0.35 : 0.85))
                .overlay(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .strokeBorder(hervor ? Color.primary.opacity(0.75) : Color.black.opacity(0.12),
                                      lineWidth: hervor ? 1.5 : 0.5))
                .overlay {
                    if breite > 30 {
                        Text(KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(schrift)
                            .foregroundStyle(dimmed ? Color.primary.opacity(0.55) : Color.white)
                            .shadow(color: .black.opacity(dimmed ? 0 : 0.25), radius: 0.5, y: 0.5)
                            .lineLimit(1)
                    }
                }
                .contentShape(Rectangle())
                .help(line.map { "Pos. \($0.pos) · \(KevFormat.length(s.laenge))" + gehrung($0) } ?? KevFormat.length(s.laenge))
                .onTapGesture { if let line { onSelect(line) } }
        case .schnitt:
            Color.clear
        case .restNeu:
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .fill(ZuschnittFarbe.restNeu.color.opacity(0.08))
                .overlay(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .strokeBorder(ZuschnittFarbe.restNeu.color, style: StrokeStyle(lineWidth: 1.2, dash: [4, 2])))
                .overlay {
                    if breite > 46 {
                        Text((breite > 96 ? "neuer Rest " : "") + KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(schrift)
                            .foregroundStyle(ZuschnittFarbe.restNeu.color)
                            .lineLimit(1)
                    }
                }
                .help("Neuer Rest \(KevFormat.length(s.laenge)): kommt nach „Gebaut“ mit Kennung in den Bestand")
        case .verschnitt:
            RoundedRectangle(cornerRadius: radius, style: .continuous)
                .fill(ZuschnittFarbe.verschnitt.color.opacity(0.35))
                .overlay {
                    if breite > 40 {
                        Text(KevFormat.compact(s.laenge, maxDigits: 1))
                            .font(schrift)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                .help("Verschnitt \(KevFormat.length(s.laenge)): unter dem Mindestrest von \(KevFormat.length(mindestrest)), "
                    + "kommt nicht in den Bestand")
        }
    }

    private func gehrung(_ line: BOMLine) -> String {
        let g = KevFormat.gehrung(line.gehrung)
        return g == "–" ? "" : " · Gehrung \(g)"
    }
}

/// Platten als 2D-Ansicht, alle im selben Maßstab.
struct PlattenReihe: View {
    let zuschnitt: BestandZuschnitt
    let lines: [BOMLine]
    var groesse: ZuschnittGroesse = .gross
    let selected: Set<Int>
    var onSelect: (BOMLine) -> Void

    var body: some View {
        let box = groesse.platte
        let platten = zuschnitt.quellen.map { (b: $0.b ?? zuschnitt.platteB ?? 1, h: $0.h ?? zuschnitt.platteH ?? 1) }
        let skala = ZuschnittMassstab.skala2D(breite: box.width, hoehe: box.height, platten: platten)
        ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: groesse == .kompakt ? 10 : 18) {
                ForEach(zuschnitt.quellen) { q in
                    VStack(alignment: .leading, spacing: 4) {
                        PlattenZeichnung(
                            quelle: q, b: q.b ?? zuschnitt.platteB ?? 1, h: q.h ?? zuschnitt.platteH ?? 1, skala: skala,
                            saegeschnitt: zuschnitt.saegeschnitt, beschriften: groesse == .gross, lines: lines,
                            selected: selected, onSelect: onSelect)
                        QuellenMarke(art: q.art, text: q.titel)
                    }
                }
            }
            .padding(.vertical, 2)
        }
        .scrollBounceBehavior(.basedOnSize)
    }
}

/// Eine Platte bzw. ein Plattenrest mit den Stücken (Ursprung des Kernels links unten) und neuen Resten.
struct PlattenZeichnung: View {
    let quelle: ZuschnittQuelle
    let b: Double
    let h: Double
    let skala: Double
    let saegeschnitt: Double
    var beschriften = true
    let lines: [BOMLine]
    let selected: Set<Int>
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
                        if beschriften, r.b * skala > 60, r.h * skala > 14 {
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
                let dimmed = !selected.isEmpty && !(line.map { selected.contains($0.pos) } ?? false)
                Rectangle()
                    .fill(farbe.opacity(dimmed ? 0.35 : 0.8))
                    .overlay(Rectangle().strokeBorder(Color.black.opacity(0.18), lineWidth: 0.5))
                    .overlay {
                        if beschriften, f.b * skala > 58, f.h * skala > 14 {
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

/// Normteile des Modells: gebraucht, aus dem Bestand, zu kaufen (BOM.stueckgut).
struct StueckgutBlock: View {
    let stueckgut: [StueckgutBedarf]
    var groesse: ZuschnittGroesse = .gross

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: MaterialGruppe.normteile.symbol).foregroundStyle(.secondary)
                Text(MaterialGruppe.normteile.titel).fontWeight(.semibold)
                Text("· abzählen").foregroundStyle(.secondary)
            }
            .font(groesse.schrift)
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
            .font(groesse.schrift)
        }
    }
}
