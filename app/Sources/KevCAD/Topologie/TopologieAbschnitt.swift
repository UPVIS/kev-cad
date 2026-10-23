import KevCADCore
import SwiftUI

// Topologieoptimierung im Inspektor (PLAN-TOPOLOGIE.md): Abschnitt „Optimieren“ für das ausgewählte Druckteil.
// Schieber „Behalten“, Lastfall, Überhangfilter, Start und Abbruch; während der Rechnung Fortschritt und die Dichte live
// im Viewer, danach Kennzahlen vorher → nachher, Ansicht Vorher/Nachher mit Spannungsfarben und „Als Variante
// übernehmen“. Immer dabei: Näherung, kein Festigkeitsnachweis.

extension AppModel {
    var topologieActions: TopologieActions? { actions as? TopologieActions }

    /// Namen der Druckteile im Modell (aus der Stückliste).
    var druckteilNamen: Set<String> {
        Set((bom?.lines ?? []).filter(\.druckteil).flatMap(\.teile))
    }
}

struct TopologieAbschnitt: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: TopologieStore
    @ObservedObject var statik: StatikStore
    var actions: TopologieActions?

    /// Teil des Abschnitts: das ausgewählte Druckteil, sonst das Teil des letzten Auftrags.
    private var teil: String? {
        let ids = model.selectedPartIDs
        if ids.count == 1, let t = ids.first, model.druckteilNamen.contains(t) { return t }
        return store.stand?.teil
    }

    var body: some View {
        if let teil {
            Section {
                einstellungen(teil)
                if let s = store.stand, s.teil == teil {
                    stand(s)
                }
            } header: {
                HStack(spacing: 6) {
                    Text("Optimieren")
                    if let s = store.stand, s.teil == teil, s.fertig {
                        AmpelPunkt(ampel: s.nachher.ampel)
                    }
                    Spacer()
                    if actions != nil {
                        Toggle(isOn: Binding(get: { store.schutzZeigen }, set: { actions?.setTopologieSchutz($0) })) {
                            Image(systemName: "shield.lefthalf.filled")
                        }
                        .toggleStyle(.button)
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .help("Schutzzonen zeigen (Bohrungen, Einsätze, Last- und Klemmflächen bleiben massiv)")
                    }
                }
            }
        }
    }

    // MARK: Einstellungen

    @ViewBuilder
    private func einstellungen(_ teil: String) -> some View {
        let laeuft = store.stand?.laeuft ?? false
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Behalten")
                Slider(value: $store.behalten, in: 0.1...0.9, step: 0.01)
                    .disabled(laeuft)
                Text("\(KevFormat.number(store.behalten * 100, digits: 0)) %")
                    .font(.body.monospacedDigit())
                    .frame(width: 44, alignment: .trailing)
            }
            .help("Volumenanteil, der bleibt (Schutzzonen zählen mit); der Rest wird entlang der Lastpfade entfernt")
            Picker("Lastfall", selection: $store.szenario) {
                Text("Automatisch").tag(String?.none)
                ForEach(statik.ergebnis?.szenarien.map(\.name) ?? [], id: \.self) { n in
                    Text(n).tag(String?.some(n))
                }
            }
            .disabled(laeuft)
            .help("Szenario aus der Statik; automatisch das mit der größten Ausnutzung des Teils")
            Toggle("Überhänge höchstens 45° (P1P)", isOn: $store.ueberhang)
                .disabled(laeuft)
                .help("Überhangfilter in Druckrichtung: keine neuen Überhänge, die Stützen brauchen")
            Toggle("Schrauben halten", isOn: $store.schraubenHalten)
                .disabled(laeuft)
                .help("Lager beim Optimieren sind die Bohrungen ohne Last (angeschraubte Halter), nicht die ganze "
                      + "Auflagefläche; sonst trägt die Platte alles und die Schraubenaugen bleiben als Inseln")
            Toggle("Feines Gitter", isOn: $store.fein)
                .disabled(laeuft)
                .help("Etwa dreimal so viele Voxel: feinere Stege, rechnet länger")
            HStack {
                if laeuft {
                    Button("Abbrechen", role: .cancel) { actions?.brecheTopologieAb() }
                } else {
                    Button {
                        actions?.starteTopologie(teil: teil)
                    } label: {
                        Label("Optimieren", systemImage: "wand.and.rays")
                    }
                    .help("Topologie im Hintergrund optimieren (etwa eine Minute), Dichte live im Viewer")
                }
                Spacer()
            }
            .disabled(actions == nil)
        }
    }

    // MARK: Stand

    @ViewBuilder
    private func stand(_ s: TopologieStand) -> some View {
        if s.laeuft {
            VStack(alignment: .leading, spacing: 3) {
                ProgressView(value: s.fortschritt)
                Text(s.text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                if let v = s.voxel, let h = s.hMm {
                    Text("\(KevFormat.integer(v)) Voxel, Kante \(KevFormat.number(h, digits: 2)) mm")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        } else if s.stand == "failed" || s.stand == "abgebrochen" {
            Text(s.stand == "failed" ? "Fehlgeschlagen: \(s.meldung ?? "?")" : "Abgebrochen")
                .font(.caption)
                .foregroundStyle(s.stand == "failed" ? .red : .secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        if s.fertig {
            kennzahlen(s)
            Picker("Ansicht", selection: Binding(get: { store.ansicht }, set: { actions?.setTopologieAnsicht($0) })) {
                ForEach(TopologieStore.Ansicht.allCases, id: \.self) { a in
                    Text(a.titel).tag(a)
                }
            }
            .pickerStyle(.segmented)
            .help("Vorher/Nachher: Spannungsfarben (Ausnutzung grün → gelb → rot) am Ausgangsteil bzw. am Ergebnis")
            HStack {
                Button {
                    actions?.uebernehmeTopologie()
                } label: {
                    Label(s.imModell ? "In model.py übernommen" : "Als Variante übernehmen",
                          systemImage: "arrow.triangle.branch")
                }
                .disabled(s.imModell || actions == nil)
                .help("Neue Variante anlegen und in model.py topologie.optimieren(…) eintragen; Kevin entscheidet, "
                      + "welche Variante bleibt")
                Spacer()
            }
            if let d = s.datei {
                Text(d)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        if !s.zonen.isEmpty {
            DisclosureGroup("Schutzzonen (\(s.zonen.count))") {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(s.zonen) { z in
                        Text(z.text.isEmpty ? z.art : "\(z.art): \(z.text)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .font(.caption)
        }
        ForEach(Array(s.hinweise.enumerated()), id: \.offset) { _, h in
            Text(h)
                .font(.caption)
                .foregroundStyle(.orange)
                .fixedSize(horizontal: false, vertical: true)
        }
        Text("Näherung, kein Festigkeitsnachweis")
            .font(.caption)
            .foregroundStyle(.secondary)
        if !s.grenzen.isEmpty {
            DisclosureGroup("Grenzen der Rechnung") {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(s.grenzen.enumerated()), id: \.offset) { _, t in
                        Text(t)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .font(.caption)
        }
    }

    @ViewBuilder
    private func kennzahlen(_ s: TopologieStand) -> some View {
        let v = s.vorher, n = s.nachher
        VStack(alignment: .leading, spacing: 2) {
            if let p = s.ersparnisProzent {
                Text("Volumen −\(KevFormat.number(p, digits: 0)) %")
                    .font(.headline)
            }
            zeile("Volumen", v.volumenMm3.map { $0 / 1000 }, n.volumenMm3.map { $0 / 1000 }, "cm³", 1)
            zeile("Masse", v.masseG, n.masseG, "g", 1)
            zeile("Filament", v.filamentG, n.filamentG, "g", 1)
            zeile("Druckzeit", v.druckzeitMin, n.druckzeitMin, "min", 0)
            zeile("Spannung", v.spannungMax, n.spannungMax, "N/mm²", 1)
            HStack(spacing: 4) {
                zeile("Sicherheit", v.sicherheit, n.sicherheit, n.ziel.map { "Ziel \(KevFormat.number($0, digits: 0))" }
                      ?? "", 2)
                AmpelPunkt(ampel: n.ampel)
            }
            zeile("Verformung", v.verformungMaxMm, n.verformungMaxMm, "mm", 2)
            if let st = n.stegMinMm {
                Text("Dünnster Steg \(KevFormat.number(st, digits: 1)) mm")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func zeile(_ titel: String, _ a: Double?, _ b: Double?, _ einheit: String, _ stellen: Int) -> some View {
        HStack {
            Text(titel)
                .font(.caption)
                .frame(width: 70, alignment: .leading)
            Text("\(a.map { KevFormat.number($0, digits: stellen) } ?? "–") → \(b.map { KevFormat.number($0, digits: stellen) } ?? "–") \(einheit)")
                .font(.caption.monospacedDigit())
        }
    }
}
