import KevCADCore
import SwiftUI
import simd

/// Inspektor im Bereich „Simulation“: Kopf mit dem gewählten Lastfall, darunter die Reiter Lastfall (Art, Neigung,
/// Beschleunigung, Fahrt, Stoß, Untergrund, Ziele), Kräfte, Lager, Rechnen und Topologie.
struct SimulationInspektor: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var zustand: SimulationZustand

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        VStack(spacing: 0) {
            kopf
            Picker("Reiter", selection: $zustand.reiter) {
                ForEach(SimulationReiter.allCases) { r in
                    Label(r.titel, systemImage: r.symbol).tag(r)
                }
            }
            .pickerStyle(.segmented)
            .labelStyle(.iconOnly)
            .labelsHidden()
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
            .help("Lastfall · Kräfte · Lager · Rechnen · Topologie")
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(zustand.reiter.titel)
                        .font(.headline)
                    switch zustand.reiter {
                    case .lastfall: LastfallEditor(model: model, store: store)
                    case .kraefte: KraefteAnsicht(model: model, store: store)
                    case .lager: LagerAnsicht(model: model, store: store)
                    case .rechnen: RechnenAnsicht(model: model, store: store, zustand: zustand)
                    case .topologie: SimTopologieAnsicht(model: model, store: store, topo: model.topologie)
                    }
                    if let m = store.meldung, !m.isEmpty {
                        Text(m)
                            .font(.caption)
                            .foregroundStyle(store.meldungFehler ? .red : .secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(Array((store.stand?.hinweise ?? []).enumerated()), id: \.offset) { _, h in
                        Label(h, systemImage: "info.circle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var kopf: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if let l = store.lastfall {
                SimAmpel(ampel: l.ampel)
                VStack(alignment: .leading, spacing: 1) {
                    Text(l.name).font(.title3.weight(.semibold)).lineLimit(1)
                    Text("App · " + (l.dynamisch ? "dynamisch" : "statisch")
                         + (l.kopieVon.map { " · Kopie von „\($0)“" } ?? ""))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            } else if let m = store.modellLastfall {
                SimAmpel(ampel: m.ampel)
                VStack(alignment: .leading, spacing: 1) {
                    Text(m.name).font(.title3.weight(.semibold)).lineLimit(1)
                    Text("\(m.herkunft) · nur lesbar").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Button("Als Kopie bearbeiten") {
                    let name = store.neuerName(m.name + " (App)")
                    actions?.simulationAendern([SimOp.kopieren(von: m.name, name: name)]) { ok, _ in
                        if ok { actions?.waehleLastfall(name) }
                    }
                }
                .controlSize(.small)
            } else {
                Text("Kein Lastfall gewählt").foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
    }
}

// MARK: - Reiter Lastfall

/// Lastfall der App bearbeiten: Entwurf in der Ansicht, „Übernehmen“ schickt `lastfall_setzen`.
struct LastfallEditor: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @State private var e: SimLastfall?

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        if let l = store.lastfall {
            let geaendert = e != nil && e?.felder != l.felder
            VStack(alignment: .leading, spacing: 10) {
                Picker("Art", selection: binding(\.dynamisch, l)) {
                    Text("Statisch").tag(false)
                    Text("Dynamisch (Fahrt)").tag(true)
                }
                .pickerStyle(.segmented)
                TextField("Beschreibung", text: binding(\.beschreibung, l), axis: .vertical)
                    .lineLimit(1...3)
                GroupBox("Umgebung") {
                    VStack(alignment: .leading, spacing: 6) {
                        SimZahlFeld(titel: "Neigung", einheit: "°", wert: Binding(
                            get: { (e ?? l).neigungGrad > 0 ? (e ?? l).neigungGrad : nil },
                            set: { v in setze(l) { x in x.neigungGrad = max(0, min(60, v ?? 0)) } }), stellen: 1)
                        Picker("abwärts nach", selection: binding(\.neigungRichtung, l)) {
                            ForEach(SimulationZustand.richtungen, id: \.self) { Text($0).tag($0) }
                        }
                        .disabled((e ?? l).neigungGrad <= 0)
                        HStack(spacing: 4) {
                            Text("Beschl.").help("Beschleunigung in m/s²")
                            Spacer()
                            ForEach(0..<3, id: \.self) { i in
                                TextField(["x", "y", "z"][i], value: achse(i, l),
                                          format: .number.precision(.fractionLength(0...2)))
                                    .frame(width: 44)
                                    .multilineTextAlignment(.trailing)
                            }
                            Text("m/s²").foregroundStyle(.secondary)
                        }
                        .help("Beschleunigung des ganzen Gegenstands (Anfahren, Bremsen, Kurve); Trägheitskräfte "
                              + "wirken entgegen")
                        Picker("Untergrund", selection: binding(\.untergrund, l)) {
                            ForEach(SimulationZustand.untergruende, id: \.titel) { u in Text(u.titel).tag(u.id) }
                        }
                        .help("Boden zum Rutschen (Reibwert aus dem Katalog); gilt für S0, der Ablauf nimmt den des Modells")
                    }
                }
                if (e ?? l).dynamisch {
                    fahrt(l)
                }
                GroupBox("Stoß und Ziele") {
                    VStack(alignment: .leading, spacing: 6) {
                        SimZahlFeld(titel: "Stoßfaktor", einheit: "×", wert: binding(\.stoss, l), stellen: 2)
                            .help("Faktor auf die Lasten (plötzlich aufgebracht: 2); im Ablauf auf die Verzögerung")
                        SimZahlFeld(titel: "Ziel-Sicherheit", einheit: "", wert: binding(\.zielSicherheit, l),
                                    stellen: 1)
                            .help("leer: statisch 2, dynamisch 3, Druckteile das Doppelte")
                        SimZahlFeld(titel: "Durchbiegung L /", einheit: "", wert: binding(\.zielDurchbiegung, l),
                                    stellen: 0)
                            .help("leer: L/200")
                    }
                }
                HStack {
                    Button("Übernehmen") {
                        guard let x = e else { return }
                        actions?.simulationAendern([SimOp.lastfallSetzen(x)]) { ok, _ in if ok { e = nil } }
                    }
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(!geaendert)
                    Button("Zurücksetzen") { e = nil }
                        .disabled(!geaendert)
                    Spacer()
                }
                if geaendert {
                    Text("Geändert, noch nicht gerechnet (Übernehmen speichert in simulation.json und rechnet neu)")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
            .onChange(of: store.auswahl) { _, _ in e = nil }
        } else if let m = store.modellLastfall {
            VStack(alignment: .leading, spacing: 6) {
                Text(m.beschreibung ?? m.text).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("Szenarien aus model.py sind hier nur lesbar. „Als Kopie bearbeiten“ (oben) legt einen Lastfall "
                     + "der App an; heißt er gleich, ersetzt er den aus model.py.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        } else {
            Text("Links einen Lastfall wählen oder mit + anlegen.").foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func fahrt(_ l: SimLastfall) -> some View {
        let f = (e ?? l).fahrt ?? SimFahrt()
        GroupBox("Fahrt (Ablauf)") {
            VStack(alignment: .leading, spacing: 6) {
                SimZahlFeld(titel: "Geschwindigkeit", einheit: "m/s", wert: Binding(
                    get: { f.geschwindigkeit }, set: { v in setzeFahrt(l) { $0.geschwindigkeit = v } }), stellen: 2)
                Picker("Bremsen", selection: Binding(
                    get: { bremsArt(f.bremsen) },
                    set: { a in setzeFahrt(l) { x in
                        switch a {
                        case "abrupt": x.bremsen = .abrupt
                        case "anprall": x.bremsen = .anprall
                        case "verzoegerung": x.bremsen = .verzoegerung(3)
                        default: x.bremsen = .keins
                        }
                    } })) {
                    Text("Abrupt (0,1 s)").tag("abrupt")
                    Text("Anprall (0,02 s)").tag("anprall")
                    Text("Verzögerung").tag("verzoegerung")
                    Text("Nicht bremsen").tag("keins")
                }
                if case .verzoegerung(let a) = f.bremsen {
                    SimZahlFeld(titel: "Verzögerung", einheit: "m/s²", wert: Binding(
                        get: { a }, set: { v in setzeFahrt(l) { $0.bremsen = .verzoegerung(max(0.05, v ?? 3)) } }))
                }
                SimZahlFeld(titel: "Dauer", einheit: "s", wert: Binding(
                    get: { f.dauer }, set: { v in setzeFahrt(l) { $0.dauer = v } }), stellen: 1)
                Picker("Antrieb", selection: Binding(
                    get: { f.animation }, set: { v in setzeFahrt(l) { $0.animation = v } })) {
                    Text("Geschwindigkeit").tag(String?.none)
                    ForEach(model.animation.entries.filter { !$0.name.hasPrefix("Ablauf:") }.map(\.name), id: \.self) {
                        n in Text("Animation „\(n)“").tag(String?.some(n))
                    }
                }
                .help("Sollbahn des geschobenen Teils aus einer Animation statt einer festen Geschwindigkeit")
                SimZahlFeld(titel: "Angriffshöhe", einheit: "mm", wert: Binding(
                    get: { f.angriffHoehe }, set: { v in setzeFahrt(l) { $0.angriffHoehe = v } }), stellen: 0)
                    .help("leer: am Boden unter dem Schwerpunkt (wie blockierte Räder); sonst in dieser Höhe geschoben")
                Picker("Fahrtrichtung", selection: Binding(
                    get: { f.fahrtrichtung }, set: { v in setzeFahrt(l) { $0.fahrtrichtung = v } })) {
                    ForEach(SimulationZustand.richtungen, id: \.self) { Text($0).tag($0) }
                }
            }
        }
    }

    /// Eine Komponente der Beschleunigung (m/s²) als Feld; alle null = keine Beschleunigung.
    private func achse(_ i: Int, _ l: SimLastfall) -> Binding<Double> {
        Binding(
            get: { Double((e ?? l).beschleunigung?[i] ?? 0) },
            set: { (v: Double) in
                setze(l) { (x: inout SimLastfall) in
                    var b: SIMD3<Float> = x.beschleunigung ?? .zero
                    b[i] = Float(v)
                    x.beschleunigung = simd_length(b) > 1e-9 ? b : nil
                }
            })
    }

    private func bremsArt(_ b: SimFahrt.Bremsen) -> String {
        switch b {
        case .abrupt: return "abrupt"
        case .anprall: return "anprall"
        case .verzoegerung: return "verzoegerung"
        case .keins: return "keins"
        }
    }

    private func binding<T>(_ k: WritableKeyPath<SimLastfall, T>, _ l: SimLastfall) -> Binding<T> {
        Binding(get: { (e ?? l)[keyPath: k] }, set: { v in setze(l) { $0[keyPath: k] = v } })
    }

    private func setze(_ l: SimLastfall, _ f: (inout SimLastfall) -> Void) {
        var x = e ?? l
        f(&x)
        if x.dynamisch && x.fahrt == nil { x.fahrt = SimFahrt() }
        e = x
    }

    private func setzeFahrt(_ l: SimLastfall, _ f: (inout SimFahrt) -> Void) {
        setze(l) { x in
            var fa = x.fahrt ?? SimFahrt()
            f(&fa)
            x.fahrt = fa
        }
    }
}
