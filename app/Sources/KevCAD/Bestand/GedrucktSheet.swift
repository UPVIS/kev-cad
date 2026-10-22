import KevCADCore
import SwiftUI

// Knopf „Gedruckt“ (Strang „Rest Druck“, BESTAND.md „Spulen in der App“): bucht das Filament der Druckvorschau ab wie
// MCP `gedruckt_buchen` (GEDRUCKT_REQ). Aus dem Bereich „Bestand“ (alle noch nicht gebuchten Platten eines Materials)
// und aus der Druckvorschau (eine Platte). Danach zeigt das Blatt die Antwort und den neuen Stand der Spulen mit
// „Rückgängig“.

/// Anfrage für das Blatt „Gedruckt“: vorgewählte Platten (leer = alle noch nicht gebuchten) bzw. ein Material.
struct GedrucktAnfrage: Identifiable, Equatable {
    var id = UUID()
    var platten: [Int] = []
    var material: String?
}

struct GedrucktSheet: View {
    @ObservedObject var model: AppModel
    let anfrage: GedrucktAnfrage
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var ui = BestandUI.shared
    @State private var wahl: Set<Int> = []
    @State private var spule = ""
    /// Die Anfrage ist unterwegs bzw. beantwortet (dann Ergebnis statt Auswahl).
    @State private var gesendet = false
    @State private var vorher: BuchungsHinweis?

    private var vorschau: Druckvorschau? { model.druck.vorschau }
    /// Nach dem Buchen das Ergebnis zeigen (auch, wenn der Selbsttest über `BestandUI.gedrucktBuchen` bucht).
    private var zeigtErgebnis: Bool { gesendet }
    private var filament: GebautFilament? { model.bestandZustand.gebautFilament }
    private var fuehrt: Bool { model.bestandZustand.bestand?.fuehrtFilament == true }
    private var busy: Bool { model.bestandZustand.aktivitaet == .saving }

    /// Platten, die das Blatt anbietet (je nach Anfrage).
    private var platten: [DruckPlatte] {
        guard let v = vorschau else { return [] }
        return v.platten.filter { p in
            if !anfrage.platten.isEmpty { return anfrage.platten.contains(p.nr) }
            if let m = anfrage.material { return p.material.contains { $0.material == m } }
            return true
        }
    }

    private func gebucht(_ nr: Int) -> String? {
        guard let f = filament, f.run == vorschau?.run else { return nil }
        return f.platten.first { $0.nr == nr }?.gebucht ?? f.ganzGebucht
    }

    /// Materialien der gewählten Platten (für die Spulenwahl und den Stand danach).
    private var materialien: [String] {
        var out: [String] = []
        for p in platten where wahl.contains(p.nr) {
            for m in p.material where !out.contains(m.material) { out.append(m.material) }
        }
        if out.isEmpty, let m = anfrage.material { out = [m] }
        return out
    }

    private var spulen: [BestandSpule] {
        materialien.flatMap { model.bestandZustand.bestand?.spulen(material: $0) ?? [] }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            kopf.padding(20)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if zeigtErgebnis {
                        ergebnis
                    } else if !fuehrt {
                        nichtGefuehrt
                    } else if platten.isEmpty {
                        Text("Keine Druckplatten in der Druckvorschau.").foregroundStyle(.secondary)
                    } else {
                        plattenListe
                        spulenWahl
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minHeight: 160, idealHeight: 280, maxHeight: 460)
            Divider()
            fuss.padding(.horizontal, 20).padding(.vertical, 14)
        }
        .frame(width: 500)
        .onAppear {
            wahl = Set(platten.filter { gebucht($0.nr) == nil }.map(\.nr))
            vorher = model.bestandZustand.hinweis
        }
        .onChange(of: ui.gedrucktBuchen) { _, _ in
            if sperre == nil && !gesendet { buchen() }
        }
    }

    private var kopf: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "printer.filled.and.paper")
                .font(.system(size: 30))
                .foregroundStyle(MaterialKennzeichen.druckteil.color)
            VStack(alignment: .leading, spacing: 4) {
                Text(anfrage.platten.count == 1 ? "Platte \(anfrage.platten[0]) als gedruckt buchen"
                    : "Als gedruckt buchen").font(.title3.weight(.semibold))
                Text("Das Filament der gewählten Platten geht von den Spulen des Projekts ab (wie „gedruckt_buchen“). "
                    + "Reicht der Bestand nicht, gilt der Rest als von einer gekauften Spule gedruckt.")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var plattenListe: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Platten").font(.headline)
            ForEach(platten) { p in
                let schon = gebucht(p.nr)
                Toggle(isOn: Binding(get: { wahl.contains(p.nr) }, set: { an in
                    if an { wahl.insert(p.nr) } else { wahl.remove(p.nr) }
                })) {
                    HStack(spacing: 8) {
                        Text("Platte \(p.nr)").monospacedDigit().frame(width: 62, alignment: .leading)
                        Text(p.material.map { m in vorschau?.summe.material.first { $0.material == m.material }?.name
                                ?? m.material.uppercased() }.joined(separator: ", ") + (p.farbe.map { " \($0)" } ?? ""))
                            .frame(width: 110, alignment: .leading)
                        Text(DruckFormat.gramm(p.gramm)).monospacedDigit().frame(width: 64, alignment: .trailing)
                        if let schon {
                            Label("schon gebucht (\(schon))", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green).font(.caption)
                        }
                    }
                }
                .toggleStyle(.checkbox)
                .disabled(schon != nil)
            }
        }
    }

    private var spulenWahl: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Spule").font(.headline)
            Picker("Spule", selection: $spule) {
                Text("Automatisch (angebrochene zuerst, dann volle)").tag("")
                ForEach(spulen) { s in
                    Text("\(s.kennung) · \(s.bezeichnung) · \(KevFormat.mass(grams: s.gramm))").tag(s.kennung)
                }
            }
            .labelsHidden()
            .frame(maxWidth: 420)
            if spulen.isEmpty {
                Text("Keine Spule dieses Materials im Bestand: das Filament gilt als von gekauften Spulen gedruckt.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var nichtGefuehrt: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Das Projekt führt kein Filament.", systemImage: "info.circle").font(.headline)
            Text("Erst die Spulen aufnehmen, die du für dieses Projekt hast; dann bucht „Gedruckt“ das Filament ab.")
                .foregroundStyle(.secondary)
            HStack {
                Button("Spule aufnehmen …") {
                    dismiss()
                    DispatchQueue.main.async { ui.spule = SpulenAnfrage(material: anfrage.material) }
                }
                Button("Kein Filament da") {
                    model.bestandActions?.fuehreFilament(grund: "Filament führen, keine Spule da")
                }
            }
            .disabled(model.bestandActions == nil || busy)
        }
    }

    /// Nach dem Buchen: Antwort des Kernels und der neue Stand der Spulen.
    @ViewBuilder
    private var ergebnis: some View {
        let z = model.bestandZustand
        if busy {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Wird gebucht …")
            }
        } else if case .failed(let t) = z.aktivitaet {
            Label(t, systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                .fixedSize(horizontal: false, vertical: true)
        } else if let h = z.hinweis, h != vorher {
            Label(h.text, systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Spulen jetzt").font(.headline)
                if spulen.isEmpty {
                    Text("Keine Spule mehr im Bestand.").foregroundStyle(.secondary)
                }
                ForEach(spulen) { s in
                    HStack(spacing: 8) {
                        SpulenKennung(spule: s)
                        Text(s.bezeichnung).lineLimit(1).frame(maxWidth: 180, alignment: .leading)
                        SpulenBalken(spule: s, breite: 96)
                    }
                }
            }
        }
    }

    private var fuss: some View {
        HStack(spacing: 10) {
            if zeigtErgebnis {
                if let id = model.bestandZustand.hinweis?.buchung, model.bestandZustand.hinweis != vorher {
                    let schon = model.bestandZustand.buchungen.first { $0.id == id }?.schonRueckgaengig ?? false
                    Button("Rückgängig") { model.bestandActions?.buchungRueckgaengig(id) }
                        .disabled(schon || busy)
                        .help("Buchung \(id) zurücknehmen: Spulen wie vorher")
                }
                Spacer(minLength: 8)
                Button("Fertig") { dismiss() }.keyboardShortcut(.defaultAction)
            } else {
                Text(sperre ?? "Lässt sich danach rückgängig machen.")
                    .font(.callout).foregroundStyle(.secondary).lineLimit(2)
                Spacer(minLength: 8)
                Button("Abbrechen", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Gedruckt buchen") { buchen() }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(sperre != nil)
            }
        }
    }

    private func buchen() {
        vorher = model.bestandZustand.hinweis
        gesendet = true
        let alle = Set(platten.filter { gebucht($0.nr) == nil }.map(\.nr))
        // Alle offenen Platten der ganzen Vorschau: leer schicken (der Kernel nimmt die noch nicht gebuchten)
        let ganz = anfrage.platten.isEmpty && anfrage.material == nil && wahl == alle
        model.bestandActions?.bucheGedruckt(platten: ganz ? [] : wahl.sorted(), spule: spule.isEmpty ? nil : spule)
    }

    private var sperre: String? {
        if model.bestandActions == nil { return "Buchen geht nur mit verbundenem Kernel." }
        if !fuehrt { return "Das Projekt führt kein Filament." }
        if model.laufAktiv { return "Das Modell wird gerade neu gerechnet." }
        if wahl.isEmpty { return "Keine Platte gewählt." }
        if busy { return "Einen Moment …" }
        return nil
    }
}

/// Kleiner Knopf bzw. Stand „Gedruckt“ je Platte der Druckvorschau.
struct GedrucktPlattenKnopf: View {
    @ObservedObject var model: AppModel
    let platte: DruckPlatte
    var kompakt = false

    private var gebucht: String? {
        guard let f = model.bestandZustand.gebautFilament, f.run == model.druck.vorschau?.run else { return nil }
        return f.platten.first { $0.nr == platte.nr }?.gebucht ?? f.ganzGebucht
    }

    var body: some View {
        if let id = gebucht {
            HStack(spacing: 4) {
                Label(kompakt ? "gedruckt" : "Gedruckt gebucht (\(id))", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                if !kompakt {
                    Button("Rückgängig") { model.bestandActions?.buchungRueckgaengig(id) }
                        .buttonStyle(.link)
                        .disabled(model.bestandZustand.aktivitaet == .saving)
                        .help("Buchung \(id) zurücknehmen (die ganze Buchung)")
                }
            }
            .font(.caption)
        } else {
            Button {
                BestandUI.shared.gedruckt = GedrucktAnfrage(platten: [platte.nr])
            } label: {
                Label(kompakt ? "Gedruckt" : "Gedruckt …", systemImage: "checkmark.circle")
            }
            .controlSize(.small)
            .disabled(model.bestandActions == nil)
            .help("Platte \(platte.nr) als gedruckt buchen: ihr Filament geht von den Spulen des Projekts ab")
        }
    }
}
