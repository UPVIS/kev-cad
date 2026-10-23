import KevCADCore
import SwiftUI
import simd

extension AppModel {
    var simulationActions: SimulationActions? { actions as? SimulationActions }
}

/// Reiter des Inspektors im Bereich „Simulation“.
enum SimulationReiter: String, CaseIterable, Identifiable {
    case lastfall, kraefte, lager, rechnen, topologie

    var id: String { rawValue }

    var titel: String {
        switch self {
        case .lastfall: return "Lastfall"
        case .kraefte: return "Kräfte"
        case .lager: return "Lager"
        case .rechnen: return "Rechnen"
        case .topologie: return "Topologie"
        }
    }

    var symbol: String {
        switch self {
        case .lastfall: return "slider.horizontal.3"
        case .kraefte: return "arrow.down.to.line"
        case .lager: return "triangle.bottomhalf.filled"
        case .rechnen: return "play.circle"
        case .topologie: return "wand.and.rays"
        }
    }
}

/// Zustand des Bereichs „Simulation“ in einem Fenster, der nur die Oberfläche betrifft (Reiter, Ergebnistabelle,
/// Umbenennen). Daten und Werkzeuge liegen im `SimulationStore` des App-Kerns.
@MainActor
final class SimulationZustand: ObservableObject {
    @Published var reiter: SimulationReiter = .lastfall
    /// Lastfall, der gerade umbenannt wird (Sheet).
    @Published var umbenennen: String?
    @Published var neuerName = ""
    @Published var ergebnisOffen = true
    @Published var grenzeArt = "last"
    @Published var festigkeitTeil: String?
    @Published var fein = false
    @Published var sortierung = [KeyPathComparator(\SimErgebnisZeile.ampelSort, order: .reverse)]
    @Published var tabellenAuswahl: SimErgebnisZeile.ID?

    /// Untergründe zum Rutschen (Katalog: Reibwerte); nil = der des Modells (Standard Beton).
    static let untergruende: [(id: String?, titel: String)] = [
        (nil, "wie im Modell"), ("beton", "Beton"), ("eiche", "Holz (Eiche)"), ("stahl-s235", "Stahl"),
        ("alu-6060", "Aluminium"), ("Kunststoff", "Kunststoff"), ("Elastomer", "Gummi"),
    ]
    static let richtungen = ["+x", "-x", "+y", "-y"]
    static let achsen = ["+x", "-x", "+y", "-y", "+z", "-z"]
}

/// Ampel als Punkt (wie im Statik-Abschnitt), mit „nicht gerechnet“ für nil.
struct SimAmpel: View {
    var ampel: StatikAmpel?

    var body: some View {
        if let ampel {
            AmpelPunkt(ampel: ampel)
        } else {
            Circle().strokeBorder(Color.secondary.opacity(0.6), lineWidth: 1).frame(width: 9, height: 9)
                .help("noch nicht gerechnet")
        }
    }
}

/// Zustand einer Last bzw. eines Lagers nach der Zuordnung: neu zugeordnet (orange), nicht mehr zuordenbar (rot).
struct SimZuordnungZeichen: View {
    var zustand: SimZuordnung
    var text: String

    var body: some View {
        switch zustand {
        case .fehlt:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .help("nicht mehr zuordenbar, zählt nicht mit: \(text)")
        case .neu:
            Image(systemName: "arrow.triangle.2.circlepath")
                .foregroundStyle(.orange)
                .help("nach einer Modelländerung neu zugeordnet: \(text)")
        case .offen:
            Image(systemName: "clock")
                .foregroundStyle(.secondary)
                .help("wird beim nächsten Lauf zugeordnet")
        case .ok:
            EmptyView()
        }
    }
}

/// Zahlenfeld mit Einheit, das nur beim Bestätigen schreibt (deutsches Komma erlaubt); leer = nil.
struct SimZahlFeld: View {
    var titel: String
    var einheit: String
    @Binding var wert: Double?
    var stellen = 2
    var breite: CGFloat = 70
    @State private var text = ""
    @FocusState private var fokus: Bool

    var body: some View {
        HStack(spacing: 6) {
            Text(titel)
                .frame(minWidth: 0, alignment: .leading)
            Spacer(minLength: 4)
            TextField("", text: $text, prompt: Text("–"))
                .multilineTextAlignment(.trailing)
                .frame(width: breite)
                .focused($fokus)
                .onSubmit(uebernehmen)
                .onChange(of: fokus) { _, f in if !f { uebernehmen() } }
            Text(einheit)
                .foregroundStyle(.secondary)
                .frame(width: 34, alignment: .leading)
        }
        .onAppear { text = Self.format(wert, stellen) }
        .onChange(of: wert) { _, w in if !fokus { text = Self.format(w, stellen) } }
    }

    private func uebernehmen() {
        let t = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
        if t.isEmpty {
            wert = nil
        } else if let d = Double(t), d.isFinite {
            wert = d
        }
        text = Self.format(wert, stellen)
    }

    static func format(_ w: Double?, _ stellen: Int) -> String {
        guard let w else { return "" }
        return KevFormat.number(w, digits: stellen)
    }
}

/// Einblendung im Viewport, solange ein Werkzeug der Simulation aktiv ist: Hinweis und „Fertig“.
struct SimulationWerkzeugLeiste: View {
    @ObservedObject var store: SimulationStore
    var actions: SimulationActions?

    var body: some View {
        if store.aktiv, store.werkzeug != .keins {
            HStack(spacing: 8) {
                Image(systemName: symbol).foregroundStyle(.orange)
                Text(store.werkzeug.hinweis)
                    .lineLimit(1)
                if store.griffAktiv {
                    Text("Richtung ziehen …").foregroundStyle(.secondary)
                }
                Button("Fertig") { actions?.setSimulationWerkzeug(.keins) }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
            }
            .font(.callout)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(.regularMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.orange.opacity(0.5)))
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private var symbol: String {
        switch store.werkzeug {
        case .kraft: return "arrow.down.to.line"
        case .lager: return "triangle.bottomhalf.filled"
        case .schutz: return "shield.lefthalf.filled"
        case .keins: return "cursorarrow"
        }
    }
}

/// Kurzer Teilname (letzter Teil hinter „/“).
func simKurz(_ name: String) -> String {
    name.split(separator: "/").last.map(String.init) ?? name
}

/// Kraft als Text: „294 N (0; 0; −294)“.
func simKraftText(_ f: SIMD3<Float>) -> String {
    let b = Double(simd_length(f))
    let stellen = b < 100 ? 1 : 0
    return "\(KevFormat.number(b, digits: stellen)) N (" + [f.x, f.y, f.z]
        .map { KevFormat.number(Double($0), digits: stellen) }.joined(separator: "; ") + ")"
}
