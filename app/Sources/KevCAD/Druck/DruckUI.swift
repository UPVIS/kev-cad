import KevCADCore
import SwiftUI

// Druckvorschau (DRUCKVORSCHAU.md, Abschnitt „App“): gemeinsamer Zustand der Ansichten (Auswahl, gezeigte Platte),
// Farben und kleine Bausteine für `DruckAnsicht` und `DruckKompakt`.

/// Zustand, den volle Ansicht, Schnellansicht und Selbsttest teilen. Die Auswahl im 3D-Bereich bleibt die Wahrheit:
/// Ein Klick hier wählt dort aus, eine Auswahl dort wählt hier Gruppe und Platte.
@MainActor
final class DruckUI: ObservableObject {
    static let shared = DruckUI()

    /// Gewählte Gruppe (Detail mit Einstellungen).
    @Published var auswahl: String?
    /// Gezeigte Platte beim Blättern.
    @Published var platte = 1
    /// Alle Platten nebeneinander statt blättern.
    @Published var nebeneinander: Bool {
        didSet { UserDefaults.standard.set(nebeneinander, forKey: "druckPlattenNebeneinander") }
    }
    /// Teil unter der Maus in der Plattenansicht.
    @Published var hover: String?

    private init() {
        nebeneinander = UserDefaults.standard.bool(forKey: "druckPlattenNebeneinander")
    }

    /// Gruppe wählen und ihre Teile im 3D-Bereich auswählen (auf Wunsch einpassen).
    func waehle(_ g: DruckGruppe?, vorschau: Druckvorschau?, model: AppModel, einpassen: Bool = false) {
        auswahl = g?.gruppe
        guard let g else {
            model.druckActions?.druckTeileWaehlen([], einpassen: false)
            return
        }
        if let v = vorschau, let p = v.platten.first(where: { p in p.teile.contains { $0.gruppe == g.gruppe } }) {
            zeigePlatte(p.nr)
        }
        model.druckActions?.druckTeileWaehlen(g.teile, einpassen: einpassen)
    }

    /// Ein Teil auf der Platte angeklickt: dieses Teil auswählen, seine Gruppe zeigen.
    func waehleTeil(_ name: String, vorschau: Druckvorschau, model: AppModel, einpassen: Bool = false) {
        auswahl = vorschau.gruppe(vonTeil: name)?.gruppe ?? auswahl
        model.druckActions?.druckTeileWaehlen([name], einpassen: einpassen)
    }

    /// Die Auswahl im 3D-Bereich oder Teilebaum hat sich geändert: Gruppe und Platte nachführen.
    func folge(auswahl ids: [String], vorschau: Druckvorschau?) {
        guard let v = vorschau, !ids.isEmpty else { return }
        let gruppen = Set(ids.compactMap { v.gruppe(vonTeil: $0)?.gruppe })
        guard gruppen.count == 1, let g = gruppen.first else { return }
        if auswahl != g { auswahl = g }
        if let p = v.platte(vonTeil: ids[0]) { zeigePlatte(p.nr) }
    }

    func zeigePlatte(_ nr: Int) {
        guard platte != nr else { return }
        withAnimation(.snappy(duration: 0.25)) { platte = nr }
    }

    /// Neue Vorschau: Auswahl und Platte gültig halten.
    func pruefe(_ v: Druckvorschau?) {
        guard let v else { return }
        if let a = auswahl, v.gruppe(a) == nil { auswahl = nil }
        if !v.platten.contains(where: { $0.nr == platte }) { platte = v.platten.first?.nr ?? 1 }
    }
}

// MARK: - Farben

enum DruckFarben {
    static let palette: [Color] = [
        Color(.sRGB, red: 0.95, green: 0.55, blue: 0.16), Color(.sRGB, red: 0.20, green: 0.52, blue: 0.95),
        Color(.sRGB, red: 0.22, green: 0.70, blue: 0.42), Color(.sRGB, red: 0.62, green: 0.40, blue: 0.86),
        Color(.sRGB, red: 0.92, green: 0.32, blue: 0.52), Color(.sRGB, red: 0.15, green: 0.66, blue: 0.70),
    ]

    /// Farbe je Material: die häufigste Teilfarbe des Materials im Modell (so wie Kevin es im 3D sieht), sonst die
    /// Palette in der Reihenfolge der Summe.
    static func material(_ v: Druckvorschau?, parts: [PartNode]) -> [String: Color] {
        guard let v else { return [:] }
        var reihenfolge = v.summe.material.map(\.material)
        for g in v.teile { if let m = g.material, !reihenfolge.contains(m) { reihenfolge.append(m) } }
        let farbeJeTeil = Dictionary(parts.map { ($0.id, $0.color) }, uniquingKeysWith: { a, _ in a })
        var out: [String: Color] = [:]
        var vergeben: [SIMD4<Float>] = []
        for (i, m) in reihenfolge.enumerated() {
            var zahl: [SIMD4<Float>: Int] = [:]
            for g in v.teile where g.material == m {
                for t in g.teile { if let c = farbeJeTeil[t] { zahl[c, default: 0] += 1 } }
            }
            // gleiche Farbe wie ein anderes Material: dann die Palette, damit sich die Materialien unterscheiden
            if let c = zahl.max(by: { $0.value < $1.value })?.key, !vergeben.contains(c), c.w > 0.2 {
                out[m] = Color(part: SIMD4(c.x, c.y, c.z, 1))
                vergeben.append(c)
            } else {
                out[m] = palette[i % palette.count]
            }
        }
        return out
    }

    static func ampel(_ a: DruckAmpel) -> Color {
        switch a {
        case .gruen: return .green
        case .gelb: return .orange
        case .rot: return .red
        }
    }

    static func schwere(_ s: DruckpraxisHinweis.Schwere) -> (farbe: Color, symbol: String) {
        switch s {
        case .hinweis: return (.green, "lightbulb.fill")
        case .warnung: return (.orange, "exclamationmark.triangle.fill")
        case .fehler: return (.red, "xmark.octagon.fill")
        }
    }
}

// MARK: - Bausteine

/// „Schätzung“, „Bambu Studio“ oder „Bambu Studio 2/4“ mit Fortschritt des Slicers.
struct DruckStandMarke: View {
    var vorschau: Druckvorschau
    var kompakt = false

    var body: some View {
        let s = vorschau.slicer
        HStack(spacing: 5) {
            if s.laeuft {
                ZStack {
                    Circle().stroke(farbe.opacity(0.25), lineWidth: 2)
                    Circle().trim(from: 0, to: max(0.06, s.anteil ?? 0.15))
                        .stroke(farbe, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                }
                .frame(width: 11, height: 11)
                .animation(.smooth(duration: 0.5), value: s.anteil)
            } else {
                Image(systemName: symbol).font(.system(size: 10, weight: .semibold))
            }
            Text(text).lineLimit(1)
        }
        .font(.caption.weight(.semibold).monospacedDigit())
        .foregroundStyle(farbe)
        .padding(.horizontal, 7)
        .padding(.vertical, 2)
        .background(Capsule().fill(farbe.opacity(0.13)))
        .overlay(Capsule().strokeBorder(farbe.opacity(0.25), lineWidth: 0.5))
        .contentTransition(.interpolate)
        .animation(.smooth(duration: 0.45), value: vorschau.stand)
        .help(hilfe)
    }

    private var text: String {
        let s = vorschau.slicer
        if s.laeuft && s.gesamt > 0 { return kompakt ? "\(s.fertig)/\(s.gesamt)" : "Bambu Studio \(s.fertig)/\(s.gesamt)" }
        if s.laeuft { return kompakt ? "rechnet" : "Bambu Studio rechnet" }
        return vorschau.stand.titel
    }

    private var symbol: String {
        switch vorschau.stand {
        case .slicer: return "checkmark.seal.fill"
        case .gemischt: return "circle.lefthalf.filled"
        case .schaetzung: return vorschau.slicer.zustand == .fehler ? "exclamationmark.circle" : "gauge.with.dots.needle.33percent"
        }
    }

    private var farbe: Color {
        if vorschau.slicer.zustand == .fehler { return .orange }
        switch vorschau.stand {
        case .slicer: return .green
        case .gemischt: return .teal
        case .schaetzung: return .secondary
        }
    }

    private var hilfe: String {
        var t = [vorschau.stand.beschreibung]
        if let m = vorschau.slicer.meldung { t.append(m) }
        if let v = vorschau.slicer.version, vorschau.slicer.meldung?.contains(v) != true { t.append("Bambu Studio \(v)") }
        if vorschau.regler { t.append("Lauf mit Reglerwerten: geschätzt, nichts gespeichert, kein Slicer") }
        return t.joined(separator: "\n")
    }
}

/// Ampel als Punkt.
struct DruckAmpelPunkt: View {
    var ampel: DruckAmpel
    var groesse: CGFloat = 8

    var body: some View {
        Circle()
            .fill(DruckFarben.ampel(ampel).gradient)
            .frame(width: groesse, height: groesse)
            .shadow(color: DruckFarben.ampel(ampel).opacity(0.5), radius: ampel == .gruen ? 0 : 2)
            .help(ampel.titel)
    }
}

/// Eine Kennzahl: Wert groß in Monospace, Titel klein darunter.
struct DruckZahl: View {
    var wert: String
    var titel: String
    var hilfe: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(wert)
                .font(.system(.title3, design: .rounded).weight(.semibold).monospacedDigit())
                .contentTransition(.numericText())
                .lineLimit(1)
            Text(titel.uppercased())
                .font(.system(size: 9, weight: .medium))
                .kerning(0.4)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .fixedSize()
        .help(hilfe ?? "")
    }
}

/// „von Kevin“ an einem fest vorgegebenen Wert, mit Zurücksetzen.
struct DruckVorgabeMarke: View {
    var quelle: DruckQuelle
    var zuruecksetzen: (() -> Void)?

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: "pin.fill").font(.system(size: 8, weight: .semibold))
            Text(quelle.titel)
            if let zuruecksetzen {
                Button(action: zuruecksetzen) {
                    Image(systemName: "arrow.uturn.backward")
                        .font(.system(size: 9, weight: .semibold))
                        .frame(width: 14, height: 14)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Zurücksetzen: wieder die Empfehlung des Kernels")
            }
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(Color.kevAkzent)
        .padding(.leading, 6)
        .padding(.trailing, zuruecksetzen == nil ? 6 : 2)
        .padding(.vertical, 1)
        .background(Capsule().fill(Color.kevAkzent.opacity(0.12)))
        .fixedSize()
    }
}

/// Zweck als kleine Kapsel; geschätzt gestrichelt.
struct DruckZweckMarke: View {
    var zweck: String?
    var geschaetzt: Bool

    var body: some View {
        Text(DruckFormat.zweck(zweck))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(geschaetzt ? Color.secondary : Color.primary.opacity(0.8))
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Capsule().fill(Color.primary.opacity(geschaetzt ? 0.0 : 0.07)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.25),
                                            style: StrokeStyle(lineWidth: 0.6, dash: geschaetzt ? [2, 1.5] : [])))
            .fixedSize()
            .help(geschaetzt ? "Zweck geschätzt (in model.py nicht angegeben)" : DruckFormat.zweckBeschreibung(zweck ?? ""))
    }
}

/// Hinweis mit Symbol in der Farbe seiner Schwere.
struct DruckHinweisZeile: View {
    var hinweis: DruckpraxisHinweis
    var betrifft: [String] = []

    var body: some View {
        let s = DruckFarben.schwere(hinweis.schwere)
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Image(systemName: s.symbol)
                .font(.system(size: 11))
                .foregroundStyle(s.farbe)
                .frame(width: 14)
            VStack(alignment: .leading, spacing: 1) {
                Text(hinweis.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if !betrifft.isEmpty {
                    Text(betrifft.joined(separator: ", "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .font(.callout)
    }
}

extension Druckvorschau {
    /// Fortschrittsanteil des Slicers über die Gruppen (für Animationen), 1 ohne Slicer.
    var signatur: String { "\(run)|\(stand.rawValue)|\(slicer.fertig)|\(summe.zeitMitWechselS)|\(summe.gramm)" }
}
