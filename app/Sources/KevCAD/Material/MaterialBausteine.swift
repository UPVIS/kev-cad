import AppKit
import KevCADCore
import SwiftUI

// Gemeinsame Bausteine des Bereichs „Material“ und der Schnellansichten: Kennzeichen, Vorschaubild, Kennzahlen,
// Abschnittskopf. Farben und Texte kommen aus der gemeinsamen Datenquelle (MaterialDaten), damit Bildschirm und Bericht
// gleich aussehen.

extension MaterialKennzeichen {
    var color: Color {
        let c = rgb
        return Color(.sRGB, red: c.r, green: c.g, blue: c.b)
    }
}

/// Kennzeichen als kleine Kapsel: „Bestand“, „Kaufen“, „Zukauf“ …
struct KennzeichenMarke: View {
    var kennzeichen: MaterialKennzeichen
    var text: String?
    /// Nur Symbol (enge Spalten).
    var nurSymbol = false

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: kennzeichen.symbol)
                .font(.system(size: 9, weight: .semibold))
            if !nurSymbol {
                Text(text ?? kennzeichen.titel).lineLimit(1)
            }
        }
        .font(.caption.weight(.medium).monospacedDigit())
        .foregroundStyle(kennzeichen.color)
        .padding(.horizontal, nurSymbol ? 4 : 6)
        .padding(.vertical, 1.5)
        .background(Capsule().fill(kennzeichen.color.opacity(0.14)))
        .fixedSize()
        .help(kennzeichen.hilfe)
    }
}

/// Mehrere Kennzeichen nebeneinander (Rest + Bestand + Kaufen), schmal nur die Symbole.
struct KennzeichenReihe: View {
    var kennzeichen: [MaterialKennzeichen]

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 4) { ForEach(kennzeichen, id: \.self) { KennzeichenMarke(kennzeichen: $0) } }
            HStack(spacing: 3) { ForEach(kennzeichen, id: \.self) { KennzeichenMarke(kennzeichen: $0, nurSymbol: true) } }
        }
    }
}

/// Vorschaubild einer Position wie im Bericht (isometrisch auf weißem Grund), sonst das Symbol der Art.
struct PositionsBild: View {
    var bild: NSImage?
    var art: String
    var groesse: CGFloat = 40
    var tint: Color = .secondary

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: groesse * 0.2, style: .continuous)
                .fill(bild == nil ? AnyShapeStyle(tint.opacity(0.10)) : AnyShapeStyle(Color.white))
            if let bild {
                Image(nsImage: bild)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .padding(groesse * 0.04)
            } else {
                Image(systemName: CatalogSchema.art(art).symbol)
                    .font(.system(size: groesse * 0.42, weight: .medium))
                    .foregroundStyle(tint)
            }
        }
        .frame(width: groesse, height: groesse)
        .clipShape(RoundedRectangle(cornerRadius: groesse * 0.2, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: groesse * 0.2, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
    }
}

extension MaterialPosition {
    /// Art für das Symbol (Eigenteile mit Hammer).
    var symbolArt: String { herkunft == .eigenteil ? "eigenteil" : line.art }

    /// Hilfe zur Gewichtszelle: bei Druckteilen „Filament 39,0 g (gedruckt, Schätzung) · Vollkörper 104,7 g“.
    var gewichtHilfe: String {
        gewichtText ?? line.kgJe.map { "je Stück \(KevFormat.kg($0))" } ?? ""
    }

    /// Farbe des Symbols: Kennzeichen der Herkunft, sonst neutral.
    var symbolFarbe: Color { herkunft?.color ?? .secondary }
}

/// Kennzahl in einer Kopfzeile: „Gewicht 18,2 kg“.
struct KennzahlText: View {
    var titel: String
    var wert: String
    var hervor: Color? = nil

    var body: some View {
        HStack(spacing: 5) {
            Text(titel).foregroundStyle(.secondary)
            Text(wert)
                .fontWeight(.semibold)
                .monospacedDigit()
                .foregroundStyle(hervor ?? .primary)
        }
        .lineLimit(1)
        .fixedSize()
    }
}

/// Kopf eines Abschnitts im Bereich „Material“: großer Titel, Kennzeile, Aktionen rechts.
struct MaterialAbschnittKopf<Aktionen: View>: View {
    var titel: String
    var symbol: String
    var zeile: String?
    @ViewBuilder var aktionen: () -> Aktionen

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(.tint)
                .frame(width: 34, height: 34)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.accentColor.opacity(0.12)))
            VStack(alignment: .leading, spacing: 2) {
                Text(titel)
                    .font(.title2.weight(.semibold))
                    .lineLimit(1)
                if let zeile {
                    Text(zeile)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }
            .frame(minWidth: 150, alignment: .leading)
            Spacer(minLength: 12)
            // Knöpfe bleiben ganz, die Kennzeile kürzt sich (Popover der Knöpfe gibt es so nur einmal)
            HStack(spacing: 8) { aktionen() }
                .controlSize(.regular)
                .fixedSize()
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 12)
    }
}

/// Leerer Zustand eines Abschnitts mit Erklärung und Aktion.
struct MaterialLeer<Aktionen: View>: View {
    var titel: String
    var symbol: String
    var text: String
    @ViewBuilder var aktionen: () -> Aktionen

    var body: some View {
        ContentUnavailableView {
            Label(titel, systemImage: symbol)
        } description: {
            Text(text)
        } actions: {
            aktionen()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

extension MaterialLeer where Aktionen == EmptyView {
    init(titel: String, symbol: String, text: String) {
        self.init(titel: titel, symbol: symbol, text: text) { EmptyView() }
    }
}

/// Zahl im Tabellenstil: rechtsbündig, Monospace, „–“ grau.
struct ZahlZelle: View {
    var text: String
    var hervor = false

    var body: some View {
        Text(text)
            .monospacedDigit()
            .fontWeight(hervor ? .semibold : .regular)
            .foregroundStyle(text == "–" ? .tertiary : .primary)
            .frame(maxWidth: .infinity, alignment: .trailing)
    }
}

extension MaterialPosition {
    /// Hilfetext der Benennung (Tabellen).
    var hilfe: String {
        var parts = [line.benennung + (line.norm.map { " · \($0)" } ?? "")]
        for k in kennzeichen { parts.append(k.hilfe) }
        if let z = line.zukauf {
            parts.append("Zukaufteil \(z.title)" + (z.vereinfacht ? ", vereinfacht (Ersatzkörper)" : ""))
            if let url = z.url { parts.append(url.absoluteString) }
        } else if let id = line.stockID {
            parts.append("Lagerteil \(id)")
        }
        parts.append(line.teile.prefix(8).joined(separator: ", ") + (line.teile.count > 8 ? " …" : ""))
        return parts.joined(separator: "\n")
    }

    /// Tooltip der Preisspalte; bei Zukaufteilen mit brutto/netto und Datum.
    var preisHilfe: String {
        if let f = filament, let k = f.kosten {  // Druckteile: Filamentkosten aus der Druckvorschau
            var t = "Filament \(KevFormat.euro(k)) (Druckvorschau, \(f.stand.titel))"
            if let v = line.preis { t += " · Vollkörper × Filamentpreis \(KevFormat.euro(v))" }
            return t
        }
        guard let je = line.preisJe else { return "ohne Preis" }
        var text = "je Stück \(KevFormat.euro(je))"
        if let z = line.zukauf {
            if let b = z.preisBrutto { text += b ? " brutto" : " netto" }
            if let s = MaterialText.stand(z.preisStand) { text += ", Stand \(s)" }
        }
        return text + " (Richtpreis)"
    }
}
