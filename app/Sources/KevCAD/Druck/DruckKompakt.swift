import KevCADCore
import SwiftUI

/// Schnellansicht der Druckvorschau als schmales Band: g und € je Material, Platten, Gesamtzeit, Stand „Schätzung /
/// Bambu Studio“ und die Ampel der Hinweise. Wird es eng, fallen erst die Meter, dann die Materialien weg. Eingebaut vom
/// Material-Strang (`DruckSchnellansicht`); `oeffnen` führt auf Wunsch zur vollen Ansicht.
struct DruckKompakt: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var druck: DruckStore
    var oeffnen: (() -> Void)?

    init(model: AppModel, oeffnen: (() -> Void)? = nil) {
        self.model = model
        _druck = ObservedObject(wrappedValue: model.druck)
        self.oeffnen = oeffnen
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "printer.fill")
                .foregroundStyle(Color.kevAkzent)
                .font(.system(size: 12, weight: .semibold))
            if let v = druck.vorschau, !v.istLeer {
                ViewThatFits(in: .horizontal) {
                    inhalt(v, materialien: true, meter: true)
                    inhalt(v, materialien: true, meter: false)
                    inhalt(v, materialien: false, meter: false)
                    knapp(v)
                }
            } else {
                Text(leerText).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
            }
        }
        .font(.callout)
        .padding(.horizontal, 12)
        .frame(minHeight: 30)
        .contentShape(Rectangle())
        .onTapGesture { oeffnen?() }
        .help(hilfe)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("3D-Druck: " + hilfe)
    }

    private var leerText: String {
        if druck.vorschau?.istLeer == true { return "Keine Druckteile" }
        if druck.nichtUnterstuetzt { return "Druckvorschau nicht verfügbar" }
        return "Druckvorschau folgt nach dem Lauf"
    }

    private func inhalt(_ v: Druckvorschau, materialien: Bool, meter: Bool) -> some View {
        HStack(spacing: 12) {
            if materialien {
                let farben = DruckFarben.material(v, parts: model.parts)
                ForEach(v.summe.material) { m in
                    HStack(spacing: 5) {
                        RoundedRectangle(cornerRadius: 2.5, style: .continuous)
                            .fill((farben[m.material] ?? .gray).gradient)
                            .frame(width: 9, height: 9)
                        Text(m.name).fontWeight(.medium)
                        Text(DruckFormat.gramm(m.g)).monospacedDigit().contentTransition(.numericText())
                        if meter, let mm = m.m {
                            Text(DruckFormat.meter(mm)).monospacedDigit().foregroundStyle(.secondary)
                        }
                        if let k = m.kosten {
                            Text(DruckFormat.euro(k)).monospacedDigit().foregroundStyle(.secondary)
                                .contentTransition(.numericText())
                        }
                    }
                    .fixedSize()
                }
                trenner
            }
            knapp(v)
        }
        .animation(.snappy(duration: 0.35), value: v.signatur)
    }

    /// Platten, Zeit, Summe, Stand und Ampel (passt immer).
    private func knapp(_ v: Druckvorschau) -> some View {
        HStack(spacing: 10) {
            Text(KevFormat.count(v.summe.platten, one: "Platte", many: "Platten")).monospacedDigit()
            Text(DruckFormat.zeit(v.summe.zeitMitWechselS))
                .fontWeight(.semibold)
                .monospacedDigit()
                .contentTransition(.numericText())
            if let k = v.summe.kosten {
                Text("≈ " + DruckFormat.euro(k)).monospacedDigit().contentTransition(.numericText())
            }
            Spacer(minLength: 4)
            DruckStandMarke(vorschau: v, kompakt: true)
            ampel(v)
        }
        .lineLimit(1)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func ampel(_ v: Druckvorschau) -> some View {
        let h = v.alleHinweise.map(\.hinweis)
        let w = h.filter { $0.schwere >= .warnung }.count
        return HStack(spacing: 4) {
            DruckAmpelPunkt(ampel: v.ampel)
            if w > 0 { Text("\(w)").font(.caption.weight(.semibold).monospacedDigit()).foregroundStyle(.secondary) }
        }
        .help(h.isEmpty ? "Keine Hinweise"
              : h.sorted { $0.schwere > $1.schwere }.prefix(6).map { "\($0.schwere.titel): \($0.text)" }.joined(separator: "\n"))
    }

    private var trenner: some View {
        Rectangle().fill(Color.primary.opacity(0.15)).frame(width: 1, height: 14)
    }

    private var hilfe: String {
        guard let v = druck.vorschau, !v.istLeer else { return leerText }
        var t = ["\(KevFormat.count(v.summe.platten, one: "Platte", many: "Platten")), \(DruckFormat.zeit(v.summe.zeitMitWechselS))"
            + (v.summe.kosten.map { ", \(DruckFormat.euro($0))" } ?? "")]
        t += v.summe.material.map { "\($0.name): \(DruckFormat.gramm($0.g))" + ($0.m.map { ", \(DruckFormat.meter($0))" } ?? "") }
        t.append(v.stand.beschreibung)
        return t.joined(separator: "\n")
    }
}

/// Platten als kleine Draufsichten nebeneinander (Schnellansicht, aufgezogen): Klick wählt das Teil im 3D-Bereich.
struct DruckPlattenStreifen: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var druck: DruckStore
    @ObservedObject private var ui = DruckUI.shared

    init(model: AppModel) {
        self.model = model
        _druck = ObservedObject(wrappedValue: model.druck)
    }

    var body: some View {
        GeometryReader { geo in
            if let v = druck.vorschau, !v.istLeer {
                let seite = max(40, geo.size.height - 30)
                let farben = DruckFarben.material(v, parts: model.parts)
                let nummern = Dictionary(uniqueKeysWithValues: v.teile.enumerated().map { ($1.gruppe, $0 + 1) })
                ScrollView(.horizontal) {
                    HStack(alignment: .top, spacing: 14) {
                        ForEach(v.platten) { p in
                            VStack(alignment: .leading, spacing: 3) {
                                DruckPlattenBild(
                                    platte: p, vorschau: v, farben: farben, ausgewaehlt: Set(model.selectedPartIDs),
                                    gruppe: nil, nummern: nummern, hover: ui.hover,
                                    klick: { t, n in
                                        if let t { ui.waehleTeil(t.name, vorschau: v, model: model, einpassen: n == 2) }
                                    },
                                    schwebt: { t in if ui.hover != t?.name { ui.hover = t?.name } })
                                    .frame(width: seite, height: seite)
                                HStack(spacing: 4) {
                                    Text("\(p.nr)").fontWeight(.semibold)
                                    if let m = p.material.first {
                                        Circle().fill(farben[m.material] ?? .gray).frame(width: 6, height: 6)
                                    }
                                    Text(DruckFormat.zeit(p.zeitS)).monospacedDigit()
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .frame(width: seite, alignment: .leading)
                            }
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                }
                .scrollIndicators(.never)
            }
        }
    }
}
