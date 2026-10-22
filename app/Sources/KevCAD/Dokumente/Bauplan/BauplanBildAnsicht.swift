import KevCADCore
import SwiftUI

/// Strichbild eines Schritts am Bildschirm: dieselbe Zeichenfunktion wie im PDF (BauplanZeichner), Linienbreiten wie
/// auf dem Papier bei der gezeigten Größe, Farben passend zu Hell und Dunkel.
struct BauplanBildAnsicht: View {
    let bild: BauplanStrichbild?
    var fehlt: String = "Kein Bild für diesen Schritt"
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { geo in
            if let bild, !bild.leer {
                Canvas { ctx, size in
                    ctx.withCGContext { cg in
                        // Canvas: Ursprung links oben, y nach unten, Punkte. Papierbreite des Felds ~ 180 mm.
                        let ziel = CGRect(origin: .zero, size: size).insetBy(dx: 10, dy: 10)
                        let ptJeMM = max(1.2, min(ziel.width / 180, ziel.height / 120) * 1.15)
                        BauplanZeichner.zeichne(bild, in: cg, ziel: ziel, palette: scheme == .dark ? .dunkel : .papier,
                                                einheitJeMM: ptJeMM)
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height)
                .accessibilityLabel("Strichbild des Schritts")
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "photo.on.rectangle.angled")
                        .font(.system(size: 34, weight: .light))
                        .foregroundStyle(.tertiary)
                    Text(bild?.fehler.map { "Kein Bild: \($0)" } ?? fehlt)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

/// Karte mit dem Strichbild (Papiergrund im hellen, dunkler Grund im dunklen Erscheinungsbild).
struct BauplanBildKarte: View {
    let bild: BauplanStrichbild?
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        BauplanBildAnsicht(bild: bild)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(scheme == .dark ? Color(white: 0.13) : Color.white))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.08)))
            .shadow(color: .black.opacity(scheme == .dark ? 0.35 : 0.07), radius: 10, y: 3)
    }
}

/// Schrittnummer als orange Plakette wie im PDF.
struct BauplanNummer: View {
    let nummer: Int
    var groesse: CGFloat = 24

    var body: some View {
        Text("\(nummer)")
            .font(.system(size: groesse * (nummer >= 100 ? 0.42 : 0.52), weight: .bold, design: .rounded))
            .monospacedDigit()
            .foregroundStyle(.white)
            .frame(width: groesse, height: groesse)
            .background(RoundedRectangle(cornerRadius: groesse * 0.24, style: .continuous).fill(Color.kevAkzent))
            .accessibilityLabel("Schritt \(nummer)")
    }
}

/// „4×“ wie in LEGO-Anleitungen.
struct BauplanMengenMarke: View {
    let anzahl: Int
    var gross = false

    var body: some View {
        Text(BauplanText.menge(anzahl))
            .font(.system(size: gross ? 22 : 12, weight: .heavy, design: .rounded))
            .monospacedDigit()
            .padding(.horizontal, gross ? 10 : 5)
            .padding(.vertical, gross ? 3 : 1)
            .overlay(RoundedRectangle(cornerRadius: gross ? 7 : 4, style: .continuous).strokeBorder(.primary, lineWidth: gross ? 2 : 1))
            .help("\(anzahl)-mal ausführen")
    }
}

extension Color {
    /// Kev CAD Orange (wie die neuen Teile im Strichbild und die Schrittnummern im PDF).
    static let kevAkzent = Color(.sRGB, red: 0.93, green: 0.38, blue: 0.06)
    static let kevSicherheit = Color(.sRGB, red: 1.0, green: 0.80, blue: 0.0)
}

extension BauplanSchwere {
    var farbe: Color {
        switch self {
        case .fehler: return .red
        case .warnung: return .orange
        case .hinweis: return .secondary
        }
    }

    var symbol: String {
        switch self {
        case .fehler: return "xmark.octagon.fill"
        case .warnung: return "exclamationmark.triangle.fill"
        case .hinweis: return "info.circle"
        }
    }
}
