import AppKit
import KevCADCore
import SwiftUI

/// Seitenleiste im Bereich „Material“: Übersicht, Stückliste, Zuschnitt, Bestand, Einkaufsliste, Zukaufteile,
/// Druckteile, je mit Kennzahl; unten Lagerkatalog, Freigaben und „Als Bericht drucken“.
struct MaterialSeitenleiste: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    var navigation: MaterialNavigation?

    var body: some View {
        let daten = model.materialDaten
        let k = daten.kennzahlen
        List(selection: Binding(get: { material.abschnitt }, set: { if let a = $0 { material.abschnitt = a } })) {
            Section {
                zeile(.uebersicht, untertitel: model.project?.name ?? "Auf einen Blick")
            }
            Section("Listen") {
                zeile(.stueckliste, untertitel: daten.hatStueckliste
                      ? KevFormat.count(k.positionen, one: "Position", many: "Positionen") + " · " + k.kostenText
                      : "noch keine", zahl: k.positionen)
                zeile(.zuschnitt, untertitel: k.verschnittText == "–" ? k.zuschnittText
                      : k.zuschnittText + " · " + k.verschnittText)
                zeile(.bestand, untertitel: k.lagerteileImBestand == 0 ? "noch leer"
                      : KevFormat.count(k.lagerteileImBestand, one: "Lagerteil", many: "Lagerteile") + " · "
                        + KevFormat.count(k.resteImBestand, one: "Rest", many: "Reste"))
                zeile(.einkauf, untertitel: einkaufText(daten),
                      zahl: material.abgehakt.offen(daten.einkauf).count,
                      farbe: daten.einkauf.isEmpty ? nil : MaterialKennzeichen.kaufen.color)
            }
            Section("Teile") {
                zeile(.zukauf, untertitel: k.zukaufteile == 0 ? "keine"
                      : KevFormat.count(k.zukaufteile, one: "Stück", many: "Stück") + (k.wartetAufCAD > 0 ? " · wartet auf CAD" : ""),
                      zahl: k.zukaufteile, farbe: k.wartetAufCAD > 0 ? .orange : nil)
                zeile(.druck, untertitel: k.druckteile == 0 ? "keine"
                      : KevFormat.count(k.druckteile, one: "Teil", many: "Teile") + " · " + KevFormat.mass(grams: k.druckGramm),
                      zahl: k.druckteile)
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom, spacing: 0) { fuss(k) }
        .onAppear { material.ladeAbgehakt(model.project?.path) }
    }

    private func einkaufText(_ d: MaterialDaten) -> String {
        guard d.kennzahlen.mitBestand || !d.zukaufEinkauf.isEmpty else { return "ohne Bestandsabgleich" }
        if d.einkauf.isEmpty { return "nichts zu kaufen" }
        return KevFormat.count(d.einkauf.count, one: "Position", many: "Positionen") + " · " + d.kennzahlen.einkaufText
    }

    private func zeile(_ a: MaterialAbschnitt, untertitel: String, zahl: Int? = nil, farbe: Color? = nil) -> some View {
        HStack(spacing: 8) {
            Image(systemName: a.symbol)
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(a.titel).lineLimit(1)
                Text(untertitel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            if let zahl, zahl > 0 {
                Text("\(zahl)")
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .foregroundStyle(farbe == nil ? Color.secondary : Color.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(farbe ?? Color.primary.opacity(0.08)))
            }
        }
        .padding(.vertical, 2)
        .tag(a)
    }

    private func fuss(_ k: MaterialKennzahlen) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if k.freigaben > 0 {
                Button {
                    session.showCatalog(section: .suggestions)
                } label: {
                    Label(KevFormat.count(k.freigaben, one: "Vorschlag prüfen", many: "Vorschläge prüfen"),
                          systemImage: "checkmark.seal")
                        .foregroundStyle(.orange)
                }
                .buttonStyle(.borderless)
                .help("Vorschläge von Claude im Lagerkatalog freigeben")
            }
            HStack(spacing: 12) {
                Button {
                    session.showCatalog()
                } label: {
                    Label("Lagerkatalog", systemImage: "books.vertical")
                }
                .buttonStyle(.borderless)
                .help("Lagerkatalog öffnen (⇧⌘K)")
                Spacer()
                Button {
                    navigation?.bericht(material.abschnitt.bericht)
                } label: {
                    Image(systemName: "printer")
                }
                .buttonStyle(.borderless)
                .disabled(navigation == nil)
                .help("Als Bericht drucken: \(material.abschnitt.bericht.titel) in „Dokumente“")
            }
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }
}
