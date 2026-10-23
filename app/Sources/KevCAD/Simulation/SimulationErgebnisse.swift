import AppKit
import KevCADCore
import SwiftUI

/// Ergebnisse unter dem Viewport im Bereich „Simulation“: Tabelle aller Teile und Stäbe des gewählten Lastfalls mit
/// Sicherheit, Ausnutzung, Verformung, Nachweis (S0, S1, FEM, Ablauf) und Ampel, sortierbar und filterbar; ein Klick
/// zeigt das Teil im Viewer mit seinem Farbverlauf. Daneben die Befunde mit Lösungsvorschlag. Vergleich mit einem
/// anderen Lastfall oder dem vorherigen Stand.
struct SimulationErgebnisAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var statik: StatikStore
    @ObservedObject var zustand: SimulationZustand

    private var actions: SimulationActions? { model.simulationActions }

    private var szenario: StatikSzenario? { statik.ergebnis?.szenario(store.auswahl) }

    var body: some View {
        VStack(spacing: 0) {
            kopf
            if zustand.ergebnisOffen {
                Divider()
                if let sz = szenario {
                    HStack(spacing: 0) {
                        if let v = vergleichsSzenario(sz) {
                            vergleichTabelle(sz, v)
                        } else {
                            tabelle(sz)
                        }
                        Divider()
                        befunde(sz)
                            .frame(width: 250)
                    }
                } else {
                    Text(store.auswahl == nil ? "Kein Lastfall gewählt"
                         : "„\(store.auswahl ?? "")“ ist noch nicht gerechnet (Rechnen oder model.py laufen lassen)")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .frame(height: zustand.ergebnisOffen ? 250 : 30)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var kopf: some View {
        HStack(spacing: 10) {
            Button {
                withAnimation(.snappy(duration: 0.2)) { zustand.ergebnisOffen.toggle() }
            } label: {
                Image(systemName: zustand.ergebnisOffen ? "chevron.down" : "chevron.right")
            }
            .buttonStyle(.borderless)
            Text("Ergebnisse").font(.headline)
            if let sz = szenario {
                AmpelPunkt(ampel: sz.ampel)
                Text(sz.name).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            if zustand.ergebnisOffen {
                Picker("Filter", selection: $store.filter) {
                    ForEach(SimulationStore.Filter.allCases, id: \.self) { Text($0.titel).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(width: 230)
                Picker("Vergleich", selection: $store.vergleich) {
                    Text("Kein Vergleich").tag(String?.none)
                    if let a = store.auswahl, store.vorher[a] != nil {
                        Text("Vorheriger Stand").tag(String?.some(SimulationStore.vorherSchluessel))
                    }
                    ForEach((statik.ergebnis?.szenarien ?? []).map(\.name).filter { $0 != store.auswahl },
                            id: \.self) { n in
                        Text("mit „\(n)“").tag(String?.some(n))
                    }
                }
                .frame(width: 210)
                Toggle(isOn: Binding(get: { statik.farbverlauf },
                                     set: { model.statikActions?.setStatikFarbverlauf($0) })) {
                    Image(systemName: "paintpalette")
                }
                .toggleStyle(.button)
                .help("Farbverlauf der Ausnutzung im Viewer (grün → gelb → rot)")
                Toggle(isOn: Binding(get: { statik.verformung },
                                     set: { model.statikActions?.setStatikVerformung($0) })) {
                    Image(systemName: "waveform.path")
                }
                .toggleStyle(.button)
                .help("Verformung überhöht als Geist")
            }
        }
        .controlSize(.small)
        .padding(.horizontal, 10)
        .frame(height: 30)
    }

    private func zeilen(_ sz: StatikSzenario) -> [SimErgebnisZeile] {
        SimErgebnis.gefiltert(SimErgebnis.zeilen(sz), store.filter).sorted(using: zustand.sortierung)
    }

    private func tabelle(_ sz: StatikSzenario) -> some View {
        Table(zeilen(sz), selection: $zustand.tabellenAuswahl, sortOrder: $zustand.sortierung) {
            TableColumn("", value: \.ampelSort) { z in AmpelPunkt(ampel: z.ampel) }
                .width(14)
            TableColumn("Teil", value: \.name) { z in Text(z.kurzName).help(z.name) }
                .width(min: 80, ideal: 140)
            TableColumn("Nachweis", value: \.nachweis.rawValue) { z in Text(z.nachweis.rawValue) }
                .width(56)
            TableColumn("Kriterium", value: \.kriterium) { z in Text(z.kriterium).help(z.text) }
                .width(min: 60, ideal: 96)
            TableColumn("Sicherheit", value: \.sicherheitSort) { z in
                Text(z.sicherheit.map(StatikZahl.sf) ?? "–").monospacedDigit()
            }
            .width(62)
            TableColumn("Ziel") { z in Text(z.ziel.map { KevFormat.number($0, digits: 0) } ?? "–").monospacedDigit() }
                .width(30)
            TableColumn("Ausnutzung", value: \.ausnutzung) { z in
                Text(KevFormat.number(z.ausnutzung, digits: 2)).monospacedDigit()
                    .foregroundStyle(z.ausnutzung > 1 ? (z.ausnutzung > 2 ? .red : .orange) : .primary)
            }
            .width(66)
            TableColumn("Verformung", value: \.verformungSort) { z in
                Text(z.verformungMm.map { "\(KevFormat.number($0, digits: 2)) mm" } ?? "–").monospacedDigit()
            }
            .width(70)
        }
        .onChange(of: zustand.tabellenAuswahl) { _, id in
            guard let id, let z = SimErgebnis.zeilen(sz).first(where: { $0.id == id }), let teil = z.teil else { return }
            actions?.zeigeErgebnisTeil(teil)
        }
    }

    private func vergleichsSzenario(_ sz: StatikSzenario) -> StatikSzenario? {
        guard let v = store.vergleich else { return nil }
        if v == SimulationStore.vorherSchluessel { return store.vorher[sz.name] }
        return statik.ergebnis?.szenario(v)
    }

    private func vergleichTabelle(_ sz: StatikSzenario, _ v: StatikSzenario) -> some View {
        let vorher = store.vergleich == SimulationStore.vorherSchluessel
        let zeilen = SimErgebnis.vergleich(vorher ? v : sz, vorher ? sz : v)
        return Table(zeilen) {
            TableColumn("Teil") { z in Text(simKurz(z.name)).help(z.name) }
                .width(min: 120, ideal: 180)
            TableColumn(vorher ? "Vorher" : "„\(sz.name)“") { z in
                HStack(spacing: 4) {
                    if let a = z.ampelA { AmpelPunkt(ampel: a) }
                    Text(z.a.map(StatikZahl.sf) ?? "–").monospacedDigit()
                }
            }
            TableColumn(vorher ? "Jetzt" : "„\(v.name)“") { z in
                HStack(spacing: 4) {
                    if let b = z.ampelB { AmpelPunkt(ampel: b) }
                    Text(z.b.map(StatikZahl.sf) ?? "–").monospacedDigit()
                }
            }
            TableColumn("Änderung") { z in
                Text(z.aenderung.map { (($0 >= 0) ? "+" : "") + KevFormat.number($0, digits: 0) + " %" } ?? "–")
                    .monospacedDigit()
                    .foregroundStyle((z.aenderung ?? 0) < -0.5 ? .red : ((z.aenderung ?? 0) > 0.5 ? .green : .secondary))
            }
        }
    }

    private func befunde(_ sz: StatikSzenario) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("Befunde").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                if sz.auffaellig.isEmpty {
                    Label("Alles im grünen Bereich", systemImage: "checkmark.seal")
                        .font(.callout).foregroundStyle(.green)
                }
                ForEach(sz.auffaellig) { u in
                    Button {
                        model.statikActions?.zeigeStatikUrteil(u)
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            AmpelPunkt(ampel: u.ampel)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(u.text).font(.callout).fixedSize(horizontal: false, vertical: true)
                                if !u.loesung.isEmpty {
                                    Text(u.loesung).font(.caption).foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("Im Viewer zeigen")
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// Sprünge in den Bereich „Simulation“ (aus dem Inspektor: Statik und Topologie).
@MainActor
enum SimulationOeffnen {
    static func lastfall(_ model: AppModel, _ state: ProjectWindowState) {
        if let a = model.statik.szenario?.name { model.simulationActions?.waehleLastfall(a) }
        state.simulationZustand.reiter = .lastfall
        state.zeige(.simulation)
    }

    static func topologie(_ model: AppModel, _ state: ProjectWindowState, _ teil: String) {
        model.simulationActions?.waehleTopologieTeil(teil)
        state.simulationZustand.reiter = .topologie
        state.zeige(.simulation)
    }
}

/// Werkzeugleiste im Bereich „Simulation“: Werkzeuge im Viewer, Rechnen, Inspektor.
struct SimulationToolbar: ToolbarContent {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var state: ProjectWindowState

    private var actions: SimulationActions? { model.simulationActions }

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .principal) {
            Picker("Werkzeug", selection: Binding(get: { store.werkzeug },
                                                  set: { actions?.setSimulationWerkzeug($0) })) {
                Label("Auswählen", systemImage: "cursorarrow").tag(SimulationStore.Werkzeug.keins)
                Label("Kraft setzen", systemImage: "arrow.down.to.line").tag(SimulationStore.Werkzeug.kraft)
                Label("Lager setzen", systemImage: "triangle.bottomhalf.filled").tag(SimulationStore.Werkzeug.lager)
                Label("Schutzfläche", systemImage: "shield.lefthalf.filled").tag(SimulationStore.Werkzeug.schutz)
            }
            .pickerStyle(.segmented)
            .labelStyle(.iconOnly)
            .disabled(actions == nil)
            .help("Auswählen · Kraft setzen · Lager setzen · Schutzfläche (Topologie); Esc beendet")
        }
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                actions?.simulationRechnen(was: "rechnen", lastfall: nil, teil: nil, fein: false, grenze: nil)
            } label: {
                Label("Rechnen", systemImage: "bolt")
            }
            .disabled(actions == nil || store.job?.laeuft == true)
            .help("Alle Lastfälle mit S0 und S1 rechnen (Millisekunden)")
            Button {
                actions?.simulationRechnen(was: "festigkeit", lastfall: store.auswahl, teil: nil, fein: false,
                                           grenze: nil)
            } label: {
                Label("Festigkeit (FEM)", systemImage: "cube.transparent")
            }
            .disabled(actions == nil || store.auswahl == nil || store.job?.laeuft == true)
            .help("Festkörper-FEM für die Teile mit Last im gewählten Lastfall")
            Button {
                state.showInspector.toggle()
            } label: {
                Label("Inspektor", systemImage: "sidebar.trailing")
            }
            .help("Inspektor ein- oder ausblenden")
        }
    }
}

/// Menü „Simulation“ (⌘4 wechselt in den Bereich, siehe Darstellung).
struct SimulationCommands: Commands {
    @ObservedObject var model: AppModel
    @FocusedObject private var window: ProjectWindowState?

    private var actions: SimulationActions? { model.simulationActions }
    private var bereit: Bool { window != nil && model.project != nil && actions != nil }

    var body: some Commands {
        CommandMenu("Simulation") {
            Button("Bereich Simulation") { window?.zeige(.simulation) }
                .disabled(window == nil || model.project == nil)
            Divider()
            Button("Neuer Lastfall") {
                let name = model.simulation.neuerName()
                actions?.simulationAendern([SimOp.lastfallNeu(name)]) { ok, _ in if ok { actions?.waehleLastfall(name) } }
                window?.zeige(.simulation)
            }
            .disabled(!bereit)
            Button("Kraft setzen") {
                window?.zeige(.simulation)
                window?.simulationZustand.reiter = .kraefte
                actions?.setSimulationWerkzeug(.kraft)
            }
            .keyboardShortcut("k", modifiers: [.command, .control])
            .disabled(!bereit || model.simulation.lastfall == nil)
            Button("Lager setzen") {
                window?.zeige(.simulation)
                window?.simulationZustand.reiter = .lager
                actions?.setSimulationWerkzeug(.lager)
            }
            .keyboardShortcut("l", modifiers: [.command, .control])
            .disabled(!bereit)
            Divider()
            Button("Rechnen") {
                actions?.simulationRechnen(was: "rechnen", lastfall: nil, teil: nil, fein: false, grenze: nil)
            }
            .keyboardShortcut("r", modifiers: [.command, .control])
            .disabled(!bereit || model.simulation.job?.laeuft == true)
            Button("Festigkeit (FEM)") {
                actions?.simulationRechnen(was: "festigkeit", lastfall: model.simulation.auswahl, teil: nil,
                                           fein: false, grenze: nil)
            }
            .disabled(!bereit || model.simulation.auswahl == nil || model.simulation.job?.laeuft == true)
            Button("Ablauf") {
                actions?.simulationRechnen(was: "ablauf", lastfall: model.simulation.auswahl, teil: nil, fein: false,
                                           grenze: nil)
            }
            .disabled(!bereit || model.simulation.job?.laeuft == true
                      || !(model.simulation.lastfall?.dynamisch ?? model.simulation.modellLastfall?.dynamisch ?? false))
            Menu("Grenze suchen") {
                Button("Wie viel Last") { grenze("last") }
                Button("Wie steil") { grenze("neigung") }
                Button("Wie schnell") { grenze("geschwindigkeit") }
            }
            .disabled(!bereit || model.simulation.auswahl == nil || model.simulation.job?.laeuft == true)
            Button("Abbrechen") { actions?.simulationAbbrechen() }
                .disabled(model.simulation.job?.laeuft != true)
        }
    }

    private func grenze(_ art: String) {
        actions?.simulationRechnen(was: "grenze", lastfall: model.simulation.auswahl, teil: nil, fein: false,
                                   grenze: art)
        window?.simulationZustand.reiter = .rechnen
        window?.zeige(.simulation)
    }
}
