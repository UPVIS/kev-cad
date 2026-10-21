import KevCADCore
import SwiftUI

extension AppModel {
    /// Teile, die die Inventar-Regel verletzen (aus PART_UPSERT und RUN_END), in Baumreihenfolge.
    var inventoryViolations: [String] {
        var names = parts.filter(\.inventarFehlt).map(\.id)
        for name in inventarVerstoesse where !names.contains(name) { names.append(name) }
        return names
    }

    var inventoryActions: InventoryActions? { actions as? InventoryActions }
}

/// Band über dem Viewport, solange Teile nicht aus dem Inventar stammen (Inventar-Regel des Projekts).
struct InventoryBanner: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    var dismiss: () -> Void

    var body: some View {
        let names = model.inventoryViolations
        let suggestions = model.catalog?.suggestionCount ?? 0
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 10) {
                Image(systemName: "shippingbox.fill")
                    .font(.title3)
                    .foregroundStyle(.red)
                    .overlay(alignment: .bottomTrailing) {
                        Image(systemName: "exclamationmark.circle.fill")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.white, .red)
                            .offset(x: 4, y: 3)
                    }
                VStack(alignment: .leading, spacing: 1) {
                    Text("Nicht aus dem Inventar: " + Self.list(names))
                        .font(.headline)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Text(KevFormat.count(names.count, one: "Teil ist", many: "Teile sind")
                        + " weder verbautes Lagerteil noch gekennzeichnetes 3D-Druckteil (rot markiert)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                Button("Teile zeigen") {
                    let known = names.filter { n in model.parts.contains { $0.id == n } }
                    model.actions?.select(known)
                    model.actions?.focus(on: known)
                }
                if suggestions > 0 {
                    Button("Vorschläge prüfen (\(suggestions))") { session.showCatalog(section: .suggestions) }
                        .buttonStyle(.borderedProminent)
                } else {
                    Button("Lagerkatalog") { session.showCatalog() }
                }
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Band ausblenden, bis sich die Verstöße ändern")
            }
            Text("Gebaut wird nur aus dem Lagerkatalog. Bitte Claude, passende Lagerteile zu verbauen oder neue "
                + "vorzuschlagen, die du im Lagerkatalog freigibst. Für Nachbauten und Skizzen lässt sich die "
                + "Inventar-Regel im Inspektor unter „Projekt“ ausschalten.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.red.opacity(0.05)))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Color.red.opacity(0.4), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
        }
    }

    /// "A", "A und B", "A, B und 3 weitere".
    static func list(_ names: [String]) -> String {
        let short = names.map { $0.split(separator: "/").last.map(String.init) ?? $0 }
        switch short.count {
        case 0: return ""
        case 1: return short[0]
        case 2: return "\(short[0]) und \(short[1])"
        case 3: return "\(short[0]), \(short[1]) und \(short[2])"
        default: return "\(short[0]), \(short[1]) und \(short.count - 2) weitere"
        }
    }
}
