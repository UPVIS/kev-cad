import KevCADCore
import SwiftUI

// Reiter „Rechnen“ und „Topologie“ im Inspektor des Bereichs Simulation.

/// Rechnen per Knopf: S0 und S1 sofort, Festigkeit (FEM) je Teil oder für alle mit Last, Ablauf für dynamische
/// Lastfälle, Grenze suchen (wie viel Last, wie steil, wie schnell); Fortschritt und Abbruch.
struct RechnenAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var zustand: SimulationZustand

    private var actions: SimulationActions? { model.simulationActions }
    private var laeuft: Bool { store.job?.laeuft == true }

    var body: some View {
        let name = store.auswahl
        let dynamisch = store.lastfall?.dynamisch ?? store.modellLastfall?.dynamisch ?? false
        VStack(alignment: .leading, spacing: 10) {
            if let j = store.job {
                jobAnsicht(j)
            }
            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    knopf("Rechnen (S0, S1)", "bolt", "Alle Lastfälle sofort: Kippen, Rutschen, Stabwerk, Bauteile") {
                        actions?.simulationRechnen(was: "rechnen", lastfall: nil, teil: nil, fein: false, grenze: nil)
                    }
                    Divider()
                    HStack {
                        Picker("Teil", selection: $zustand.festigkeitTeil) {
                            Text("alle mit Last").tag(String?.none)
                            ForEach(fem_teile, id: \.self) { Text(simKurz($0)).tag(String?.some($0)) }
                        }
                        Toggle("fein", isOn: $zustand.fein)
                            .help("Feineres Netz (für Kerben und kleine Löcher)")
                    }
                    knopf("Festigkeit (FEM)", "cube.transparent",
                          "Festkörper-FEM im eigenen Prozess für die Teile mit Last in „\(name ?? "allen Lastfällen")“") {
                        actions?.simulationRechnen(was: "festigkeit", lastfall: name, teil: zustand.festigkeitTeil,
                                                   fein: zustand.fein, grenze: nil)
                    }
                    .disabled(name == nil)
                    Divider()
                    knopf("Ablauf", "figure.walk.motion", "Fahrt simulieren (MuJoCo): Kippen, Abheben, Ladung") {
                        actions?.simulationRechnen(was: "ablauf", lastfall: name, teil: nil, fein: false, grenze: nil)
                    }
                    .disabled(name == nil || !dynamisch)
                    Divider()
                    Picker("Grenze", selection: $zustand.grenzeArt) {
                        Text("Wie viel Last").tag("last")
                        Text("Wie steil").tag("neigung")
                        Text("Wie schnell").tag("geschwindigkeit")
                    }
                    Picker("Verfahren", selection: Binding(
                        get: { zustand.grenzeArt == "geschwindigkeit" ? "s0s1" : zustand.grenzeVerfahren },
                        set: { zustand.grenzeVerfahren = $0 })) {
                        Text("S0 und S1 (schnell)").tag("s0s1")
                        Text("mit FEM (genauer)").tag("fem")
                    }
                    .disabled(zustand.grenzeArt == "geschwindigkeit")
                    .help(zustand.grenzeArt == "geschwindigkeit"
                          ? "„Wie schnell“ sucht der Ablauf (S2) mit Rollouts"
                          : "Mit FEM: dazu die Festkörper-FEM der Teile mit Last (Halbierung über den Faktor, "
                            + "Zwischenspeicher, Probe bei der Grenze); dauert Sekunden bis Minuten")
                    knopf("Grenze suchen", "scope", "Wert, bei dem „\(name ?? "")“ gerade noch hält") {
                        actions?.simulationGrenzeSuchen(lastfall: name, art: zustand.grenzeArt,
                                                        verfahren: zustand.grenzeVerfahren)
                    }
                    .disabled(name == nil || (zustand.grenzeArt == "geschwindigkeit" && !dynamisch))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .disabled(actions == nil || laeuft)
            if let g = store.grenze, g.lastfall == name {
                grenzeAnsicht(g)
            }
            if let sz = model.statik.ergebnis?.szenario(name), let ab = sz.ablauf, ab.fertig {
                Button {
                    model.statikActions?.zeigeAblauf(sz.name)
                } label: {
                    Label("Ablauf zeigen", systemImage: "play.fill")
                }
                .help("Spielt den simulierten Ablauf in der Zeitleiste ab")
            }
        }
    }

    private var fem_teile: [String] {
        let sz = model.statik.ergebnis?.szenario(store.auswahl)
        return (sz?.teile.map(\.name) ?? []).filter { n in !(sz?.staebe.contains { $0.name == n } ?? false) }
    }

    private func knopf(_ titel: String, _ symbol: String, _ hilfe: String, aktion: @escaping () -> Void) -> some View {
        Button(action: aktion) {
            Label(titel, systemImage: symbol).frame(maxWidth: .infinity, alignment: .leading)
        }
        .help(hilfe)
    }

    @ViewBuilder
    private func jobAnsicht(_ j: SimJob) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(j.titel + (j.lastfall.map { " · \($0)" } ?? "")).font(.callout.weight(.medium))
                    Spacer()
                    if j.laeuft {
                        Button("Abbrechen", role: .cancel) { actions?.simulationAbbrechen() }
                            .controlSize(.small)
                    } else {
                        Text(j.stand == "done" ? "fertig" : (j.stand == "abgebrochen" ? "abgebrochen" : "Fehler"))
                            .font(.caption).foregroundStyle(j.stand == "failed" ? .red : .secondary)
                    }
                }
                if j.laeuft {
                    if let f = j.fortschritt {
                        ProgressView(value: f)
                    } else {
                        ProgressView().progressViewStyle(.linear)
                    }
                }
                Text(j.laeuft ? j.text : (j.meldung ?? j.text))
                    .font(.caption)
                    .foregroundStyle(j.stand == "failed" ? .red : .secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let ms = j.ms, !j.laeuft {
                    Text("\(KevFormat.number(ms / 1000, digits: 1)) s").font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func grenzeAnsicht(_ g: SimJob) -> some View {
        GroupBox(g.titel + (g.verfahren == "fem" ? " (mit FEM)" : "")) {
            VStack(alignment: .leading, spacing: 4) {
                if let t = g.ergebnisText { Text(t).font(.callout).fixedSize(horizontal: false, vertical: true) }
                ForEach(g.werte) { w in
                    HStack {
                        Text(w.kriterium).font(.caption)
                        if let v = w.verfahren {
                            Text(v)
                                .font(.caption2.weight(.semibold))
                                .padding(.horizontal, 4)
                                .background(Capsule().fill(v == "FEM" ? Color.accentColor.opacity(0.18)
                                                           : Color.secondary.opacity(0.15)))
                        }
                        Spacer()
                        Text(w.einheit == "×" ? "\(KevFormat.number(w.grenze, digits: 2))-fach"
                             + (w.lastN.map { " (\(KevFormat.number($0, digits: 0)) N)" } ?? "")
                             : "\(KevFormat.number(w.grenze, digits: w.einheit == "°" ? 1 : 2)) \(w.einheit)")
                            .font(.caption.monospacedDigit())
                    }
                    .help(w.text + (w.massgebend.map { " – maßgebend: \($0)" } ?? ""))
                }
                if let m = g.massgebendVerfahren {
                    Text("Maßgebend: \(m)" + (g.werte.first?.massgebend.map { ", \(simKurz($0))" } ?? ""))
                        .font(.caption.weight(.medium))
                }
                if let f = g.probeFaktor, let a = g.probeAusnutzung {
                    Text("Probe mit FEM beim \(KevFormat.number(f, digits: 2))-fachen: Ausnutzung "
                         + KevFormat.number(a, digits: 2) + (g.probeTeil.map { " (\(simKurz($0)))" } ?? ""))
                        .font(.caption).foregroundStyle(.secondary)
                }
                if !g.werte.isEmpty {
                    Text(g.hinweis ?? (g.verfahren == "fem" ? "Gesucht mit S0, S1 und FEM"
                                       : "Gesucht mit S0 und S1 (ohne FEM)"))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// Topologie im Bereich Simulation: Druckteil, Lastfall, Behalten, Überhang, Mindeststeg, feines Gitter, Schrauben
/// halten; automatische Schutzzonen je Art an und aus, eigene Schutzflächen per Klick; Start und Abbruch, Dichte live,
/// vorher und nachher, „Als Variante übernehmen“.
struct SimTopologieAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var topo: TopologieStore

    private var actions: SimulationActions? { model.simulationActions }
    private var laeuft: Bool { topo.stand?.laeuft ?? false }

    var body: some View {
        let druckteile = model.druckteilNamen.sorted()
        VStack(alignment: .leading, spacing: 10) {
            Picker("Druckteil", selection: Binding(get: { store.topologieTeil },
                                                   set: { actions?.waehleTopologieTeil($0) })) {
                Text("wählen …").tag(String?.none)
                ForEach(druckteile, id: \.self) { Text(simKurz($0)).tag(String?.some($0)) }
            }
            .disabled(laeuft)
            if druckteile.isEmpty {
                Text("Optimiert werden Druckteile (lager.druckteil); im Modell gibt es keins.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let teil = store.topologieTeil {
                einstellungen(teil)
                if let s = topo.stand, s.teil == teil {
                    TopologieStandAnsicht(store: topo, actions: model.topologieActions, s: s)
                }
            }
        }
    }

    @ViewBuilder
    private func einstellungen(_ teil: String) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 6) {
                Picker("Lastfall", selection: $topo.szenario) {
                    Text("Automatisch").tag(String?.none)
                    ForEach(model.statik.ergebnis?.szenarien.map(\.name) ?? [], id: \.self) { n in
                        Text(n).tag(String?.some(n))
                    }
                }
                HStack {
                    Text("Behalten")
                    Slider(value: $topo.behalten, in: 0.1...0.9, step: 0.01)
                    Text("\(KevFormat.number(topo.behalten * 100, digits: 0)) %")
                        .font(.body.monospacedDigit()).frame(width: 44, alignment: .trailing)
                }
                Toggle("Überhänge höchstens 45° (P1P)", isOn: $topo.ueberhang)
                Stepper(value: $store.steg, in: 2...40, step: 1) {
                    Text("Mindeststeg \(KevFormat.number(store.steg, digits: 0)) Linien = "
                         + "\(KevFormat.number(store.steg * 0.42, digits: 1)) mm")
                }
                Toggle("Feines Gitter", isOn: $topo.fein)
                Toggle("Schrauben halten", isOn: $topo.schraubenHalten)
                    .help("Lager beim Optimieren sind die Bohrungen ohne Last (angeschraubte Halter)")
            }
            .disabled(laeuft)
        }
        GroupBox("Schutzzonen") {
            VStack(alignment: .leading, spacing: 5) {
                Text("Automatisch").font(.caption.weight(.semibold))
                Toggle("Bohrungen mit Wandring", isOn: $store.schutzBohrungen)
                Toggle("Gewindeeinsätze mit Mindestwand", isOn: $store.schutzEinsaetze)
                Toggle("Last- und Klemmflächen", isOn: $store.schutzKontakt)
                Toggle("Bettfläche (geschlossene Unterseite)", isOn: $store.schutzBett)
                HStack {
                    Text("Eigene Flächen").font(.caption.weight(.semibold))
                    Spacer()
                    Toggle(isOn: Binding(get: { store.werkzeug == .schutz },
                                         set: { actions?.setSimulationWerkzeug($0 ? .schutz : .keins) })) {
                        Label("per Klick", systemImage: "hand.tap")
                    }
                    .toggleStyle(.button)
                    .controlSize(.small)
                    .help("Flächen des Druckteils im Viewer anklicken: bleiben massiv (noch einmal: entfernt)")
                }
                if store.schutzFlaechen.isEmpty {
                    Text("keine").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(store.schutzFlaechen, id: \.self) { f in
                    HStack {
                        Text("Fläche \(f)").font(.caption)
                        if let z = store.stand?.topologie[teil]?.schutz.first(where: { $0.index == f }) {
                            SimZuordnungZeichen(zustand: z.zustand, text: z.text)
                        }
                        Spacer()
                        Button {
                            actions?.schaltSchutzflaeche(f)
                        } label: {
                            Image(systemName: "minus.circle")
                        }
                        .buttonStyle(.borderless)
                    }
                }
                if let z = topo.stand?.zonen, topo.stand?.teil == teil, !z.isEmpty {
                    Toggle("Schutzzonen im Viewer", isOn: Binding(get: { topo.schutzZeigen },
                                                                   set: { model.topologieActions?.setTopologieSchutz($0) }))
                        .font(.caption)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .disabled(laeuft)
        }
        HStack {
            if laeuft {
                Button("Abbrechen", role: .cancel) { model.topologieActions?.brecheTopologieAb() }
            } else {
                Button {
                    actions?.starteSimulationsTopologie(teil: teil)
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
