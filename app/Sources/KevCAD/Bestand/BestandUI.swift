import KevCADCore
import SwiftUI

// Bestand (BESTAND.md, Abschnitt „App“): gemeinsamer Oberflächenzustand (Dialoge „Gebaut …“ und „Erfassen“), Farben
// und das Band nach einer Buchung. Bestand, Zuschnitt und Einkaufsliste zeigt seit dem Strang „Material“ der Bereich
// „Material“ (⌘3); die Dialoge hängen am Projektfenster und sind aus beiden Bereichen erreichbar.

extension AppModel {
    /// Bestandsaktionen des App-Kerns (im Demomodus nicht vorhanden).
    var bestandActions: BestandActions? { actions as? BestandActions }

    /// Anzeigename eines Lagerteils: Katalog, Stückliste, Zuschnitt, Einkaufsliste, sonst die id.
    func lagerteilName(_ id: String) -> String {
        if let item = catalog?.item(id) { return item.name }
        if let line = bom?.lines.first(where: { $0.stockID == id }) { return line.benennung }
        if let z = bestandZustand.zuschnitt?.zuschnitt(id) { return z.benennung }
        if let p = bestandZustand.zuschnitt?.einkaufsliste.first(where: { $0.id == id }) { return p.benennung }
        return id
    }

    /// Lieferform eines Lagerteils: aus dem Bestand, sonst aus der Katalog-Art bzw. der Stückliste.
    func bestandForm(_ id: String) -> BestandForm {
        if let p = bestandZustand.bestand?.posten(id), !p.leer || p.json["ganze"] != nil || p.json["stueck"] != nil {
            return p.form
        }
        if let item = catalog?.item(id) { return item.bestandForm }
        if let line = bom?.lines.first(where: { $0.stockID == id }), !line.art.isEmpty { return BestandForm(art: line.art) }
        if let z = bestandZustand.zuschnitt?.zuschnitt(id) { return z.istPlatte ? .platte : .stange }
        return .stange
    }

    /// Art eines Lagerteils für das Symbol.
    func lagerteilArt(_ id: String) -> String {
        catalog?.item(id)?.art ?? bom?.lines.first(where: { $0.stockID == id })?.art
            ?? (bestandZustand.bestand?.posten(id)?.form == .platte ? "platte" : "rohr")
    }

    /// Ein Lauf ist aktiv: Bestand nicht buchen, solange die Stückliste gleich neu kommt.
    var laufAktiv: Bool {
        if case .running = run { return true }
        return false
    }
}

/// Zustand der Bestandsoberfläche, den Menü, Stückliste und Bestand teilen.
@MainActor
final class BestandUI: ObservableObject {
    static let shared = BestandUI()

    /// Dialog „Gebaut …“ zeigen.
    @Published var gebautDialog = false
    /// Blatt zum Erfassen (Lagerteil aufnehmen, Reste hinzufügen).
    @Published var erfassen: ErfassenAnfrage?
    /// Ausgewählter Posten im Bestand (Filament: „filament:petg“, siehe `FilamentAuswahl`).
    @Published var auswahl: String?
    /// Blatt „Spule aufnehmen“ bzw. „Spule ändern“ (Strang „Bestand Stufe 2“).
    @Published var spule: SpulenAnfrage?
    /// Blatt „Gedruckt“ (Strang „Rest Druck“): Filament von Platten der Druckvorschau abbuchen.
    @Published var gedruckt: GedrucktAnfrage?
    /// Selbsttest: das offene Blatt „Gedruckt“ bucht wie mit seinem Knopf (ohne Maus und Tastatur).
    @Published var gedrucktBuchen = 0

    private init() {}

    /// Dialog „Gebaut …“ öffnen (Menü, Material-Bereich, Schnellansicht).
    func zeigeGebaut() {
        DispatchQueue.main.async { self.gebautDialog = true }
    }
}

/// Anfrage für das Blatt „Erfassen“.
struct ErfassenAnfrage: Identifiable, Equatable {
    var id = UUID()
    /// Lagerteil (nil: im Blatt aus dem Katalog wählen).
    var stockID: String?
    /// Nur Reste hinzufügen (ganze Stangen vorbelegt mit 0).
    var nurReste = false
}

// MARK: - Farben

extension ZuschnittFarbe {
    var color: Color {
        let c = rgb
        return Color(.sRGB, red: c.r, green: c.g, blue: c.b)
    }
}

extension ZuschnittQuelleArt {
    var color: Color { farbe.color }

    var symbol: String {
        switch self {
        case .rest: return "arrow.3.trianglepath"
        case .bestand: return "shippingbox"
        case .kaufen: return "cart"
        }
    }
}

// MARK: - Dialoge und Band

/// Dialoge „Gebaut …“ und „Erfassen“ am Projektfenster (alle Bereiche). Das Band nach einer Buchung hängt oben in der
/// Mitte des Fensters (ProjectWindow).
struct BestandDialoge: ViewModifier {
    @ObservedObject var model: AppModel
    @ObservedObject private var ui = BestandUI.shared

    func body(content: Content) -> some View {
        content
            .sheet(isPresented: $ui.gebautDialog) {
                GebautDialog(model: model)
            }
            .sheet(item: $ui.erfassen) { anfrage in
                BestandErfassenSheet(model: model, anfrage: anfrage)
            }
            .sheet(item: $ui.spule) { anfrage in
                SpuleSheet(model: model, anfrage: anfrage)
            }
            .sheet(item: $ui.gedruckt) { anfrage in
                GedrucktSheet(model: model, anfrage: anfrage)
            }
    }
}

/// Hinweis nach „Gebaut“ bzw. „Rückgängig“ und Fehler beim Speichern, mit „Rückgängig“.
struct BuchungsBand: View {
    @ObservedObject var model: AppModel

    var body: some View {
        let z = model.bestandZustand
        Group {
            if case .failed(let text) = z.aktivitaet {
                band(symbol: "xmark.octagon.fill", farbe: .red, text: text, rueckgaengig: nil)
            } else if let h = z.hinweis {
                band(symbol: "checkmark.circle.fill", farbe: .green, text: h.text, rueckgaengig: h.buchung)
                    .task(id: h.zeit) {
                        try? await Task.sleep(for: .seconds(25))
                        if model.bestandZustand.hinweis?.zeit == h.zeit { model.bestandActions?.verwerfeBuchungsHinweis() }
                    }
            }
        }
        .animation(.snappy(duration: 0.2), value: z.hinweis)
    }

    private func band(symbol: String, farbe: Color, text: String, rueckgaengig: String?) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(farbe)
            Text(text)
                .lineLimit(2)
                .textSelection(.enabled)
            Spacer(minLength: 8)
            if let id = rueckgaengig {
                let schon = model.bestandZustand.buchungen.first { $0.id == id }?.schonRueckgaengig ?? false
                Button("Rückgängig") { model.bestandActions?.buchungRueckgaengig(id) }
                    .disabled(schon || model.bestandZustand.aktivitaet == .saving)
                    .help("Buchung \(id) zurücknehmen: Bestand wie vorher")
            }
            Button {
                model.bestandActions?.verwerfeBuchungsHinweis()
            } label: {
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 16, height: 16)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Hinweis schließen")
        }
        .font(.callout)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(farbe.opacity(0.35)))
        .shadow(color: .black.opacity(0.12), radius: 6, y: 2)
        .frame(maxWidth: 640)
        .transition(.move(edge: .top).combined(with: .opacity))
    }
}

/// Kleine Kennzeichnung der Quelle: farbiger Punkt bzw. Kapsel mit Text.
struct QuellenMarke: View {
    var art: ZuschnittQuelleArt
    var text: String

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: art.symbol)
                .font(.system(size: 9, weight: .semibold))
            Text(text)
                .lineLimit(1)
        }
        .font(.caption.weight(.medium).monospacedDigit())
        .foregroundStyle(art.color)
        .padding(.horizontal, 6)
        .padding(.vertical, 1)
        .background(Capsule().fill(art.color.opacity(0.14)))
    }
}
