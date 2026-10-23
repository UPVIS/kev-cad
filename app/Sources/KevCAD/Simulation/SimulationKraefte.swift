import KevCADCore
import SwiftUI

// Reiter „Kräfte“ und „Lager“ im Inspektor des Bereichs Simulation: Kraft per Klick auf eine Fläche oder einen Punkt,
// Richtung entlang der Normale, einer Achse oder frei (Winkel oder Pfeil-Griff im Viewer), Betrag in N oder kg,
// Kraftpaar mit einem Gegenstück; Lager per Klick (fest, gelenkig, gleitend, auf Fläche oder Punkt).

struct KraefteAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        if let lf = store.lastfall {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Toggle(isOn: Binding(get: { store.werkzeug == .kraft },
                                         set: { actions?.setSimulationWerkzeug($0 ? .kraft : .keins) })) {
                        Label("Kraft setzen", systemImage: "hand.tap")
                    }
                    .toggleStyle(.button)
                    .help("Im Viewer eine Fläche oder einen Punkt anklicken: dort entsteht ein Kraftpfeil (Esc beendet)")
                    Spacer()
                }
                if let e = store.entwurf {
                    KraftEditor(model: model, store: store, entwurf: e)
                }
                liste(lf)
            }
        } else {
            Text(store.modellLastfall != nil ? "Kräfte eines Szenarios aus model.py sind nur lesbar: „Als Kopie "
                 + "bearbeiten“ legt einen Lastfall der App an." : "Erst einen Lastfall wählen oder anlegen.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func liste(_ lf: SimLastfall) -> some View {
        GroupBox("Kräfte in „\(lf.name)“") {
            VStack(alignment: .leading, spacing: 4) {
                if lf.lasten.isEmpty {
                    Text("Noch keine: „Kraft setzen“ und im Viewer klicken").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(lf.lasten) { l in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Image(systemName: l.paar ? "arrow.right.and.line.vertical.and.arrow.left" : "arrow.down.to.line")
                            .foregroundStyle(l.paar ? Color.purple : Color.blue)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("\(l.id) · \(simKurz(l.teil))" + (l.gegen.map { " ↔ \(simKurz($0))" } ?? ""))
                                .lineLimit(1)
                            Text(kraftText(l))
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                            if l.zustand == .fehlt || l.zustand == .neu {
                                Text(l.zustandText)
                                    .font(.caption)
                                    .foregroundStyle(l.zustand == .fehlt ? .red : .orange)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: 2)
                        SimZuordnungZeichen(zustand: l.zustand, text: l.zustandText)
                        Button {
                            actions?.lastBearbeiten(l.id)
                        } label: {
                            Image(systemName: "pencil")
                        }
                        .buttonStyle(.borderless)
                        .help("Ändern (Richtung, Betrag; neu anklicken setzt den Ort)")
                        Button {
                            actions?.simulationAendern([SimOp.lastLoeschen(lf.name, id: l.id)], fertig: nil)
                        } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                        .help("Kraft löschen")
                    }
                    .padding(4)
                    .background(RoundedRectangle(cornerRadius: 5).fill(
                        store.lastAuswahl == l.id ? Color.accentColor.opacity(0.15) : Color.clear))
                    .contentShape(Rectangle())
                    .onTapGesture { actions?.waehleLast(store.lastAuswahl == l.id ? nil : l.id) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func kraftText(_ l: SimLast) -> String {
        let r: String
        switch l.richtung.art {
        case .normale: r = l.richtung.umkehren ? "aus der Fläche" : "in die Fläche"
        case .achse: r = "entlang \(l.richtung.umkehren ? "−" : "")\(l.richtung.achse)"
        case .frei: r = "frei \(KevFormat.number(l.richtung.azimut, digits: 0))° / \(KevFormat.number(l.richtung.hoehe, digits: 0))°"
        }
        let b = l.einheit == "kg" ? "\(KevFormat.number(l.betrag, digits: 1)) kg" : "\(KevFormat.number(l.betrag, digits: 0)) N"
        let f = l.kraftWirksam.map { " = " + simKraftText($0) } ?? ""
        return "\(b) \(r)\(f)"
    }
}

/// Entwurf einer Kraft: Ort aus dem Klick, Richtung, Betrag, Kraftpaar; „Übernehmen“ speichert (last_setzen).
struct KraftEditor: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore
    var entwurf: SimulationStore.KraftEntwurf

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        let l = entwurf.last
        GroupBox(entwurf.bearbeitet.map { "Kraft \($0) ändern" } ?? "Neue Kraft") {
            VStack(alignment: .leading, spacing: 7) {
                Text(ortText(l))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Picker("Richtung", selection: bind(\.richtung.art)) {
                    ForEach(SimRichtung.Art.allCases, id: \.self) { a in
                        Text(a.titel).tag(a).disabled(a == .normale && l.ort.normale == nil)
                    }
                }
                .pickerStyle(.segmented)
                switch l.richtung.art {
                case .normale:
                    Text("Senkrecht auf die angeklickte Fläche, in das Teil hinein").font(.caption)
                        .foregroundStyle(.secondary)
                case .achse:
                    Picker("Achse", selection: bind(\.richtung.achse)) {
                        ForEach(SimulationZustand.achsen, id: \.self) { Text($0).tag($0) }
                    }
                case .frei:
                    HStack {
                        Text("Azimut")
                        TextField("", value: bind(\.richtung.azimut), format: .number.precision(.fractionLength(0...1)))
                            .frame(width: 56).multilineTextAlignment(.trailing)
                        Text("°")
                        Spacer()
                        Text("Höhe")
                        TextField("", value: bind(\.richtung.hoehe), format: .number.precision(.fractionLength(0...1)))
                            .frame(width: 56).multilineTextAlignment(.trailing)
                        Text("°")
                    }
                    Text("Oder den weißen Griff am Pfeilende im Viewer ziehen").font(.caption)
                        .foregroundStyle(.secondary)
                }
                Toggle("Umkehren", isOn: bind(\.richtung.umkehren))
                HStack {
                    Text("Betrag")
                    TextField("", value: bind(\.betrag), format: .number.precision(.fractionLength(0...2)))
                        .frame(width: 72).multilineTextAlignment(.trailing)
                    Picker("", selection: bind(\.einheit)) {
                        Text("N").tag("N")
                        Text("kg").tag("kg")
                    }
                    .labelsHidden()
                    .frame(width: 64)
                }
                Picker("Kraftpaar mit", selection: bind(\.gegen)) {
                    Text("keinem (äußere Last)").tag(String?.none)
                    ForEach(model.parts.map(\.id).filter { $0 != l.teil }, id: \.self) { n in
                        Text(simKurz(n)).tag(String?.some(n))
                    }
                }
                .help("Innere Kraft: die Gegenkraft wirkt am selben Punkt auf dieses Teil (zählt nicht beim Kippen "
                      + "und Rutschen des Ganzen)")
                if let f = entwurf.kraft {
                    Text("F = " + simKraftText(f)).font(.callout.monospacedDigit())
                } else {
                    Text("Betrag über 0 und eine Richtung angeben").font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Button("Übernehmen") { actions?.kraftEntwurfSpeichern() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(entwurf.kraft == nil)
                    Button("Verwerfen") { actions?.setKraftEntwurf(nil) }
                    Spacer()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func ortText(_ l: SimLast) -> String {
        var t = simKurz(l.teil)
        if let f = l.ort.flaeche { t += " · Fläche \(f)" }
        if let p = l.ort.punkt {
            t += " · (" + [p.x, p.y, p.z].map { KevFormat.number(Double($0), digits: 1) }.joined(separator: "; ") + ")"
        }
        if l.ort.normale == nil { t += " · ohne Normale" }
        return t + " – neu klicken setzt den Ort"
    }

    private func bind<T>(_ k: WritableKeyPath<SimLast, T>) -> Binding<T> {
        Binding(get: { entwurf.last[keyPath: k] }, set: { v in
            var e = entwurf
            e.last[keyPath: k] = v
            actions?.setKraftEntwurf(e)
        })
    }
}

// MARK: - Reiter Lager

struct LagerAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: SimulationStore

    private var actions: SimulationActions? { model.simulationActions }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Lager gelten für alle Lastfälle. Ohne ausdrückliches Lager leitet Kev CAD sie aus den Kontakten ab "
                 + "(Boden, Kulisse, befestigt, tragende Nachbarn).")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Picker("Art", selection: $store.lagerArt) {
                ForEach(SimLager.Art.allCases, id: \.self) { Text($0.titel).tag($0) }
            }
            .pickerStyle(.segmented)
            .help(store.lagerArt.hilfe)
            Text(store.lagerArt.hilfe).font(.caption).foregroundStyle(.secondary)
            Picker("Auf", selection: $store.lagerAuf) {
                ForEach(SimLager.Auf.allCases, id: \.self) { Text($0.titel).tag($0) }
            }
            .pickerStyle(.segmented)
            Toggle(isOn: Binding(get: { store.werkzeug == .lager },
                                 set: { actions?.setSimulationWerkzeug($0 ? .lager : .keins) })) {
                Label("Lager setzen", systemImage: "hand.tap")
            }
            .toggleStyle(.button)
            .help("Im Viewer eine Fläche oder einen Punkt anklicken (Esc beendet)")
            if let l = store.lagerEntwurf {
                GroupBox("Neues Lager") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(simKurz(l.teil)) · \(l.auf.titel)" + (l.ort.flaeche.map { " · Fläche \($0)" } ?? ""))
                            .font(.caption).foregroundStyle(.secondary)
                        Picker("Art", selection: Binding(get: { l.art }, set: { a in
                            var x = l
                            x.art = a
                            actions?.setLagerEntwurf(x)
                        })) {
                            ForEach(SimLager.Art.allCases, id: \.self) { Text($0.titel).tag($0) }
                        }
                        Picker("Auf", selection: Binding(get: { l.auf }, set: { a in
                            var x = l
                            x.auf = a
                            actions?.setLagerEntwurf(x)
                        })) {
                            ForEach(SimLager.Auf.allCases, id: \.self) { a in
                                Text(a.titel).tag(a).disabled(a == .flaeche && l.ort.flaeche == nil)
                            }
                        }
                        if l.art == .gleitend && l.ort.normale == nil {
                            Text("Gleitend braucht eine Fläche mit Normale").font(.caption).foregroundStyle(.red)
                        }
                        HStack {
                            Button("Übernehmen") { actions?.lagerEntwurfSpeichern() }
                                .keyboardShortcut(.defaultAction)
                                .disabled(l.art == .gleitend && l.ort.normale == nil)
                            Button("Verwerfen") { actions?.setLagerEntwurf(nil) }
                            Spacer()
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            let alle = (store.stand?.lager ?? []) + (store.stand?.modellLager ?? [])
            GroupBox("Gesetzte Lager") {
                VStack(alignment: .leading, spacing: 4) {
                    if alle.isEmpty { Text("keine").font(.caption).foregroundStyle(.secondary) }
                    ForEach(alle) { l in
                        HStack(spacing: 6) {
                            Text("\(l.id) · \(l.art.titel) · \(simKurz(l.teil)) · \(l.auf.titel)").lineLimit(1)
                            if l.quelle == "modell" {
                                Text("model.py" + (l.zeile.map { " Z. \($0)" } ?? "")).font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 2)
                            SimZuordnungZeichen(zustand: l.zustand, text: l.zustandText)
                            if l.quelle != "modell" {
                                Button {
                                    actions?.simulationAendern([SimOp.lagerLoeschen(l.id)], fertig: nil)
                                } label: {
                                    Image(systemName: "trash")
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                        if l.zustand == .fehlt || l.zustand == .neu {
                            Text(l.zustandText).font(.caption).foregroundStyle(l.zustand == .fehlt ? .red : .orange)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let ab = store.stand?.abgeleitet, !ab.isEmpty {
                GroupBox("Abgeleitete Lager") {
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(ab) { a in
                            Toggle(isOn: Binding(get: { a.aktiv }, set: { an in
                                actions?.simulationAendern([SimOp.abgeleitet(a.id, aktiv: an)], fertig: nil)
                            })) {
                                Text(a.text).font(.caption).lineLimit(2)
                            }
                            .toggleStyle(.checkbox)
                            .disabled(a.ersetzt != nil)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
}
