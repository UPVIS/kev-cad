import KevCADCore
import SwiftUI

/// Ein Schritt der Anleitung: großes Strichbild, Mengen deutlich („4×“), Werkzeug, Sicherheit gelb, Probleme rot mit
/// Sprung ins 3D, Bohrbild, Zuschnitt, Druck und Material. Aktionen über die Leiste oben rechts.
struct BauplanSchrittAnsicht: View {
    let plan: Bauplan
    let schritt: BauplanSchritt
    let bild: BauplanStrichbild?
    @ObservedObject var store: BauplanStore
    let actions: BauplanActions?
    let bearbeiten: (BauplanSchritt) -> Void
    let teilen: (BauplanSchritt) -> Void
    let regel: (BauplanSchritt) -> Void

    private var abschnitt: BauplanAbschnitt? { plan.abschnitt(von: schritt.id) }
    private var istMontage: Bool { abschnitt?.art == .montage }
    private var index: Int? { abschnitt?.schritte.firstIndex(of: schritt) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                kopf
                if schritt.bild != nil || bild != nil {
                    BauplanBildKarte(bild: bild)
                        .aspectRatio(1.5, contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: 560)
                        .overlay(alignment: .bottomTrailing) {
                            if istMontage {
                                Button {
                                    actions?.durchspielenStarten(ab: schritt.id)
                                } label: {
                                    Label("Im 3D durchspielen", systemImage: "play.fill")
                                }
                                .buttonStyle(.borderedProminent)
                                .tint(.kevAkzent)
                                .padding(12)
                            }
                        }
                }
                HStack(alignment: .top, spacing: 18) {
                    VStack(alignment: .leading, spacing: 14) {
                        if !schritt.text.isEmpty {
                            Text(schritt.text)
                                .font(.system(size: 15))
                                .lineSpacing(3)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        if !schritt.sicherheitsHinweise.isEmpty {
                            BauplanSicherheit(texte: schritt.sicherheitsHinweise)
                        }
                        if !schritt.uebrigeHinweise.isEmpty {
                            VStack(alignment: .leading, spacing: 5) {
                                ForEach(schritt.uebrigeHinweise, id: \.self) { h in
                                    Label(h, systemImage: "hand.point.right")
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        details
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    seitenleiste
                        .frame(width: 270)
                }
                if !schritt.pruefung.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Simulation").font(.headline)
                        ForEach(BauplanBefund.zusammengefasst(schritt.pruefung).sorted { $0.schwere < $1.schwere }) { b in
                            BauplanBefundKarte(befund: b) { actions?.bauplanZeigen(teile: b.teile, ort: b.ort) }
                        }
                    }
                }
                if !schritt.bohrbild.isEmpty { bohrbild }
                if !schritt.material.isEmpty { material }
            }
            .padding(24)
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: Kopf

    private var kopf: some View {
        HStack(alignment: .center, spacing: 14) {
            BauplanNummer(nummer: plan.nummer(schritt.id) ?? 0, groesse: 46)
            VStack(alignment: .leading, spacing: 3) {
                Text(schritt.titel)
                    .font(.title2.weight(.bold))
                    .lineLimit(2)
                    .textSelection(.enabled)
                HStack(spacing: 8) {
                    if let a = abschnitt { Label(a.titel, systemImage: a.art.symbol) }
                    if istMontage { Text(schritt.baugruppe.map { "Vormontage \($0)" } ?? "Hauptmontage") }
                    if schritt.fest { Label("fest", systemImage: "lock.fill") }
                    if schritt.quelle == "kevin" { Label("von dir", systemImage: "person.fill") }
                    if schritt.quelle == "agent" { Label("von Claude formuliert", systemImage: "sparkles") }
                    if schritt.verwaist { Label("Teile fehlen im Modell", systemImage: "questionmark.diamond") }
                }
                .font(.callout)
                .foregroundStyle(.secondary)
            }
            Spacer()
            if schritt.anzahl > 1 { BauplanMengenMarke(anzahl: schritt.anzahl, gross: true) }
            leiste
        }
    }

    private var leiste: some View {
        HStack(spacing: 6) {
            Button {
                bearbeiten(schritt)
            } label: {
                Label("Text bearbeiten", systemImage: "square.and.pencil")
            }
            .help("Titel, Anleitungstext und Hinweise bearbeiten")
            Toggle(isOn: Binding(get: { schritt.fest }, set: { on in
                actions?.bauplanBearbeiten([BauplanOp.fest(schritt: schritt.id, on)], titel: on ? "Schritt fest" : "Schritt gelöst")
            })) {
                Label("Fest", systemImage: schritt.fest ? "lock.fill" : "lock.open")
            }
            .toggleStyle(.button)
            .help("Fest: Der Schritt bleibt bei neuen Läufen, wie er ist")
            Menu {
                if let i = index, let a = abschnitt {
                    Button("Nach oben") {
                        actions?.bauplanBearbeiten([BauplanOp.verschieben(schritt: schritt.id,
                                                                           nach: i >= 2 ? a.schritte[i - 2].id : nil)],
                                                   titel: "Schritt verschoben")
                    }
                    .disabled(i == 0)
                    Button("Nach unten") {
                        actions?.bauplanBearbeiten([BauplanOp.verschieben(schritt: schritt.id, nach: a.schritte[i + 1].id)],
                                                   titel: "Schritt verschoben")
                    }
                    .disabled(i + 1 >= a.schritte.count)
                    Button("Mit dem nächsten zusammenfassen") {
                        actions?.bauplanBearbeiten([BauplanOp.zusammenfassen([schritt.id, a.schritte[i + 1].id])],
                                                   titel: "Schritte zusammengefasst")
                    }
                    .disabled(i + 1 >= a.schritte.count)
                }
                Button("Teilen …") { teilen(schritt) }
                    .disabled(schritt.teile.count < 2)
                Divider()
                Button("Reihenfolge festlegen …") { regel(schritt) }
                    .disabled(!istMontage)
                Divider()
                Button("Im 3D zeigen") { actions?.bauplanZeigen(teile: schritt.neu.isEmpty ? schritt.teile : schritt.neu, ort: nil) }
                    .disabled(schritt.teile.isEmpty)
                Button("Diesen Schritt prüfen") { actions?.bauplanPruefen(schritt: schritt.id) }
            } label: {
                Label("Mehr", systemImage: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .labelStyle(.iconOnly)
        .controlSize(.large)
    }

    // MARK: Seitenleiste: Teile, Verbindungsmittel, Werkzeug

    private var seitenleiste: some View {
        VStack(alignment: .leading, spacing: 12) {
            let teile = schritt.neueTeileGruppiert
            if !teile.isEmpty {
                MengenKasten(titel: "Neu in diesem Schritt", eintraege: teile.map { ($0.anzahl, $0.name) })
            }
            if !schritt.verbindungsmittel.isEmpty {
                MengenKasten(titel: "Verbindungsmittel", eintraege: schritt.verbindungsmittel.map { v in
                    var n = v.benennung
                    if let l = v.laenge, !n.contains("×") { n += " × \(KevFormat.compact(l, maxDigits: 1))" }
                    return (v.anzahl, n + (v.geschaetzt ? " (geschätzt)" : ""))
                })
            }
            if !schritt.werkzeug.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    Text("WERKZEUG").font(.caption.weight(.semibold)).foregroundStyle(.secondary).tracking(0.8)
                    ForEach(schritt.werkzeug, id: \.self) { w in
                        Label {
                            Text(w)
                        } icon: {
                            Image(systemName: BauplanWerkzeug.symbol(w))
                                .frame(width: 22, height: 22)
                                .background(RoundedRectangle(cornerRadius: 5).strokeBorder(.secondary.opacity(0.5)))
                        }
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.quaternary.opacity(0.45)))
            }
        }
    }

    // MARK: Zuschnitt, Druck

    @ViewBuilder
    private var details: some View {
        let zeilen = detailZeilen
        if !zeilen.isEmpty {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                ForEach(Array(zeilen.enumerated()), id: \.offset) { _, z in
                    GridRow {
                        Text(z.0.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Text(z.1).fontWeight(.medium).textSelection(.enabled)
                    }
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.quaternary.opacity(0.45)))
        }
    }

    private var detailZeilen: [(String, String)] {
        var out: [(String, String)] = []
        for (i, z) in schritt.zuschnitt.enumerated() {
            var t = "\(z.anzahl)× \(KevFormat.length(z.laenge))"
            let g = KevFormat.gehrung(z.gehrung)
            if g != "–" { t += ", Gehrung \(g)" }
            out.append((schritt.zuschnitt.count > 1 ? "Ablängen \(i + 1)" : "Ablängen", t))
            out.append((schritt.zuschnitt.count > 1 ? "Lagerteil \(i + 1)" : "Lagerteil", z.stockID))
        }
        if let d = schritt.druck {
            if let m = d.material { out.append(("Material", m.uppercased())) }
            if let s = d.seite { out.append(("Lage", "\(s) aufs Bett")) }
            if let h = d.hoeheMM { out.append(("Höhe", KevFormat.length(h))) }
            if let g = d.masseG { out.append(("Filament", "je ≈ \(KevFormat.mass(grams: g))")) }
        }
        return out
    }

    // MARK: Bohrbild

    private var bohrbild: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Bohrbild").font(.headline)
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                GridRow {
                    ForEach(["Nr.", "Teil", "Bohrer", "Lage", "gemessen ab", "Tiefe", "Senkung / für"], id: \.self) {
                        Text($0.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    }
                }
                Divider().gridCellUnsizedAxes(.horizontal)
                ForEach(Array(schritt.bohrbild.enumerated()), id: \.offset) { i, b in
                    GridRow {
                        Text("\(i + 1)").monospacedDigit().foregroundStyle(.secondary)
                        Text(BauplanSchritt.kurzname(b.teil)).lineLimit(1)
                        Text(b.bohrerText).fontWeight(.semibold)
                        Text(b.lageText).monospacedDigit()
                        Text(b.von ?? "–").foregroundStyle(.secondary)
                        Text(b.tiefe.map(KevFormat.length) ?? "durch")
                        Text([b.senkung, b.fuer.map { "für \($0)" }].compactMap { $0 }.joined(separator: ", "))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .textSelection(.enabled)
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.quaternary.opacity(0.35)))
        }
    }

    private var material: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Material").font(.headline)
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                ForEach(Array(schritt.material.enumerated()), id: \.offset) { _, m in
                    GridRow {
                        Text(KevFormat.compact(m.menge, maxDigits: 3)).fontWeight(.bold).monospacedDigit()
                            .gridColumnAlignment(.trailing)
                        Text(m.einheit).foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(m.benennung)
                            if let h = m.hinweis { Text(h).font(.caption).foregroundStyle(.secondary) }
                        }
                        Text(m.quelle ?? "").foregroundStyle(.secondary)
                        Text(m.preis.map(KevFormat.euro) ?? "–").monospacedDigit().gridColumnAlignment(.trailing)
                    }
                }
            }
            .textSelection(.enabled)
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.quaternary.opacity(0.35)))
        }
    }
}

/// Kasten im Stil eines LEGO-Teilekastens: „4×“ groß in Orange, Name daneben.
struct MengenKasten: View {
    let titel: String
    let eintraege: [(Int, String)]
    @State private var alle = false

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(titel.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary).tracking(0.8)
            let sichtbar = alle ? eintraege : Array(eintraege.prefix(10))
            ForEach(Array(sichtbar.enumerated()), id: \.offset) { _, e in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(e.0)×")
                        .font(.system(size: 17, weight: .heavy, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(Color.kevAkzent)
                        .frame(minWidth: 34, alignment: .trailing)
                    Text(e.1).fixedSize(horizontal: false, vertical: true)
                }
            }
            if eintraege.count > 10 {
                Button(alle ? "Weniger zeigen" : "Alle \(eintraege.count) zeigen") { alle.toggle() }
                    .buttonStyle(.link)
                    .font(.callout)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.quaternary.opacity(0.45)))
    }
}
