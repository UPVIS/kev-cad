import KevCADCore
import SwiftUI

/// Seitenleiste im Bereich „Simulation“ (⌘4): Lastfälle der App (anlegen, kopieren, umbenennen, löschen), Szenarien
/// aus model.py (nur lesbar, „als Kopie bearbeiten“), Lager aus App und model.py, abgeleitete Lager (abschaltbar).
struct SimulationSeitenleiste: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    @ObservedObject var zustand: SimulationZustand

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        let s = store.stand
        List(selection: Binding(get: { store.auswahl }, set: { actions?.waehleLastfall($0) })) {
            Section {
                ForEach(s?.lastfaelle ?? []) { l in
                    appZeile(l)
                        .tag(Optional(l.name))
                        .contextMenu { appMenue(l) }
                }
                if (s?.lastfaelle ?? []).isEmpty {
                    Text("Noch keine: + legt einen an, oder ein Szenario aus model.py als Kopie bearbeiten")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } header: {
                Text("Lastfälle (App)")
            }
            if let m = s?.modell, !m.isEmpty {
                Section("Aus model.py") {
                    ForEach(m) { x in
                        modellZeile(x)
                            .tag(x.ersetzt ? nil : Optional(x.name))
                            .contextMenu {
                                Button("Als Kopie bearbeiten") { kopieren(x.name) }
                            }
                    }
                }
            }
            lagerAbschnitt(s)
            abgeleitetAbschnitt(s)
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom, spacing: 0) { fuss(s) }
        .sheet(item: Binding(get: { zustand.umbenennen.map(UmbenennenAuftrag.init) },
                             set: { zustand.umbenennen = $0?.name })) { a in
            UmbenennenSheet(alt: a.name, name: $zustand.neuerName) { neu in
                actions?.simulationAendern([SimOp.umbenennen(a.name, neu: neu)]) { ok, _ in
                    if ok { actions?.waehleLastfall(neu) }
                }
                zustand.umbenennen = nil
            } abbrechen: {
                zustand.umbenennen = nil
            }
        }
    }

    // MARK: Zeilen

    private func appZeile(_ l: SimLastfall) -> some View {
        HStack(spacing: 8) {
            SimAmpel(ampel: l.ampel)
            VStack(alignment: .leading, spacing: 1) {
                Text(l.name).lineLimit(1)
                Text(untertitel(l))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            if l.nichtZuordenbar > 0 {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .help("\(l.nichtZuordenbar) Kräfte nicht mehr zuordenbar")
            }
            if store.job?.laeuft == true, store.job?.lastfall == l.name {
                ProgressView().controlSize(.mini)
            }
        }
        .padding(.vertical, 2)
    }

    private func untertitel(_ l: SimLastfall) -> String {
        var t = [l.dynamisch ? "dynamisch" : "statisch",
                 KevFormat.count(l.lasten.count, one: "Kraft", many: "Kräfte")]
        if l.neigungGrad > 0 { t.append("\(KevFormat.number(l.neigungGrad, digits: 0))° Neigung") }
        if store.stand?.modell.contains(where: { $0.ersetzt && $0.name == l.name }) == true { t.append("ersetzt model.py") }
        return t.joined(separator: " · ")
    }

    private func modellZeile(_ x: SimModellLastfall) -> some View {
        HStack(spacing: 8) {
            SimAmpel(ampel: x.ersetzt ? nil : x.ampel)
            VStack(alignment: .leading, spacing: 1) {
                Text(x.name)
                    .lineLimit(1)
                    .strikethrough(x.ersetzt)
                    .foregroundStyle(x.ersetzt ? .secondary : .primary)
                Text(x.ersetzt ? "ersetzt durch den Lastfall der App" : x.herkunft
                     + (x.dynamisch ? " · dynamisch" : ""))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            Image(systemName: "lock")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .help("aus model.py, nur lesbar: „Als Kopie bearbeiten“ legt einen Lastfall der App an")
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private func appMenue(_ l: SimLastfall) -> some View {
        Button("Umbenennen …") {
            zustand.neuerName = l.name
            zustand.umbenennen = l.name
        }
        Button("Kopieren") { kopieren(l.name) }
        Divider()
        Button("Löschen", role: .destructive) {
            actions?.simulationAendern([SimOp.loeschen(l.name)], fertig: nil)
        }
    }

    private func kopieren(_ von: String) {
        let name = store.neuerName(von + " (Kopie)")
        actions?.simulationAendern([SimOp.kopieren(von: von, name: name)]) { ok, _ in
            if ok { actions?.waehleLastfall(name) }
        }
    }

    // MARK: Lager

    @ViewBuilder
    private func lagerAbschnitt(_ s: SimStand?) -> some View {
        let lager = (s?.lager ?? []) + (s?.modellLager ?? [])
        Section("Lager") {
            ForEach(lager) { l in
                HStack(spacing: 6) {
                    Image(systemName: l.art == .fest ? "square.bottomhalf.filled"
                          : (l.art == .gelenkig ? "triangle" : "triangle.bottomhalf.filled"))
                        .foregroundStyle(.secondary)
                        .frame(width: 16)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(l.id) · \(l.art.titel)").lineLimit(1)
                        Text("\(simKurz(l.teil)) · \(l.auf.titel)" + (l.quelle == "modell" ? " · model.py" : "")
                             + (l.szenarien != nil ? " · \(l.giltText)" : ""))
                            .font(.caption)
                            .foregroundStyle(l.giltFuer(store.auswahl) ? Color.secondary : Color.orange)
                            .lineLimit(1)
                            .help(l.giltText)
                    }
                    Spacer(minLength: 2)
                    SimZuordnungZeichen(zustand: l.zustand, text: l.zustandText)
                }
                .contextMenu {
                    if l.quelle != "modell" {
                        ForEach(SimLager.Art.allCases, id: \.self) { a in
                            Button(a.titel) {
                                var neu = l
                                neu.art = a
                                actions?.simulationAendern([SimOp.lagerSetzen(neu)], fertig: nil)
                            }
                            .disabled(a == l.art)
                        }
                        Divider()
                        Button("Löschen", role: .destructive) {
                            actions?.simulationAendern([SimOp.lagerLoeschen(l.id)], fertig: nil)
                        }
                    }
                }
            }
            if lager.isEmpty {
                Text("Keine gesetzt: es gelten die abgeleiteten Lager")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func abgeleitetAbschnitt(_ s: SimStand?) -> some View {
        if let ab = s?.abgeleitet, !ab.isEmpty {
            Section("Abgeleitete Lager") {
                ForEach(ab) { a in
                    Toggle(isOn: Binding(get: { a.aktiv }, set: { an in
                        actions?.simulationAendern([SimOp.abgeleitet(a.id, aktiv: an)], fertig: nil)
                    })) {
                        Text(a.text)
                            .font(.caption)
                            .lineLimit(2)
                    }
                    .toggleStyle(.checkbox)
                    .disabled(a.ersetzt != nil)
                    .help(a.ersetzt != nil ? "ersetzt durch Lager \(a.ersetzt ?? "")"
                          : (a.art == "boden" ? "Steht auf dem Boden bzw. der Kulisse: Auflager im Stabwerk"
                             : "Kontakt hält das Teil im Bauteil-Nachweis und in der FEM"))
                }
            }
        }
    }

    // MARK: Fuß

    private func fuss(_ s: SimStand?) -> some View {
        HStack(spacing: 6) {
            Menu {
                Button("Statischer Lastfall") { neu(dynamisch: false) }
                Button("Dynamischer Lastfall (Fahrt)") { neu(dynamisch: true) }
            } label: {
                Image(systemName: "plus")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("Neuer Lastfall")
            Button {
                if let a = store.auswahl { kopieren(a) }
            } label: {
                Image(systemName: "plus.square.on.square")
            }
            .buttonStyle(.borderless)
            .disabled(store.auswahl == nil)
            .help("Gewählten Lastfall kopieren (Szenarien aus model.py: als Kopie bearbeiten)")
            Button {
                if let l = store.lastfall { actions?.simulationAendern([SimOp.loeschen(l.name)], fertig: nil) }
            } label: {
                Image(systemName: "minus")
            }
            .buttonStyle(.borderless)
            .disabled(store.lastfall == nil)
            .help("Gewählten Lastfall der App löschen")
            Spacer()
            Text(s.map { $0.vorhanden ? "\($0.datei) · Stand \($0.stand)" : "noch keine \($0.datei)" } ?? "")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.bar)
        .disabled(actions == nil)
    }

    private func neu(dynamisch: Bool) {
        let name = store.neuerName(dynamisch ? "Fahrt" : "Lastfall")
        actions?.simulationAendern([SimOp.lastfallNeu(name, dynamisch: dynamisch)]) { ok, _ in
            if ok {
                actions?.waehleLastfall(name)
                zustand.reiter = .lastfall
            }
        }
    }
}

private struct UmbenennenAuftrag: Identifiable {
    var name: String
    var id: String { name }
}

/// Sheet „Lastfall umbenennen“.
private struct UmbenennenSheet: View {
    var alt: String
    @Binding var name: String
    var ok: (String) -> Void
    var abbrechen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Lastfall umbenennen").font(.headline)
            TextField("Name", text: $name)
                .frame(width: 280)
                .onSubmit { fertig() }
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel, action: abbrechen)
                    .keyboardShortcut(.cancelAction)
                Button("Umbenennen") { fertig() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || name == alt)
            }
        }
        .padding(20)
    }

    private func fertig() {
        let n = name.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty, n != alt else { return }
        ok(n)
    }
}
