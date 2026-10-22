import KevCADCore
import SwiftUI

/// Eine Gruppe gleicher Druckteile im Detail: Kennzahlen, Empfehlung mit Begründung, Hinweise als Ampel und die
/// Einstellungen zum Ändern (Zweck, Wände, Füllung, Muster, Stützen, Brim → PRINT_SETTINGS). Was Kevin festgelegt hat,
/// trägt „von Kevin“ und lässt sich einzeln oder ganz zurücksetzen.
struct DruckGruppeDetail: View {
    @ObservedObject var model: AppModel
    @ObservedObject var druck: DruckStore
    var gruppe: DruckGruppe
    var vorschau: Druckvorschau
    var farbe: Color
    var nummer: Int?
    /// Füllung während des Ziehens (gesendet wird beim Loslassen).
    @State private var fuellungZiehen: Double?
    /// Gesendete Werte, sichtbar bis die neue Vorschau kommt (kein Zurückspringen beim Klicken).
    @State private var lokal: [String: JSONValue] = [:]

    private var ziel: DruckZiel { .gruppe(gruppe.gruppe) }
    /// Einstellungen der Vorschau mit den eben gesendeten Werten darüber.
    private var e: DruckEinstellungen {
        var j = gruppe.einstellungen.json
        for (k, v) in lokal where k != "zweck" { j[k] = v }
        return DruckEinstellungen(json: .object(j))
    }
    private var zweck: String? { lokal["zweck"]?.stringValue ?? gruppe.zweck }
    private var wartet: Bool { druck.wartet(ziel) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            kopf
            kennzahlen
            if !gruppe.begruendung.isEmpty { empfehlung }
            if !gruppe.hinweise.isEmpty { hinweise }
            einstellungen
            profil
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .onChange(of: wartet) { _, w in if !w { lokal = [:] } }
        .onChange(of: druck.fehler) { _, f in if f != nil { lokal = [:] } }
        .onChange(of: gruppe.gruppe) { _, _ in lokal = [:]; fuellungZiehen = nil }
    }

    // MARK: Kopf

    private var kopf: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if let nummer {
                    Text("\(nummer)")
                        .font(.system(size: 11, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                        .frame(width: 18, height: 18)
                        .background(Circle().fill(farbe))
                }
                Text(gruppe.kurzname)
                    .font(.title3.weight(.semibold))
                    .help(gruppe.name)
                    .lineLimit(2)
                    .textSelection(.enabled)
                Spacer(minLength: 4)
                DruckAmpelPunkt(ampel: gruppe.ampel, groesse: 10)
            }
            HStack(spacing: 6) {
                Text("\(gruppe.anzahl) ×").monospacedDigit()
                Text((gruppe.material ?? "–").uppercased() + (gruppe.farbe.map { " \($0)" } ?? ""))
                    .help(gruppe.farbe.map { "Druckfarbe \($0) (lager.druckteil(…, farbe=…))" } ?? "")
                DruckZweckMarke(zweck: gruppe.zweck, geschaetzt: gruppe.zweckGeschaetzt)
                if gruppe.modifier > 0 {
                    Label(KevFormat.count(gruppe.modifier, one: "Modifier", many: "Modifier"), systemImage: "cylinder")
                        .labelStyle(.titleAndIcon)
                        .foregroundStyle(.secondary)
                        .help("Modifier um Gewindeeinsätze bzw. Kernlöcher: mehr Wände und 100 % Füllung nur dort")
                }
                if gruppe.stand == .slicer {
                    Label("Bambu Studio", systemImage: "checkmark.seal.fill")
                        .labelStyle(.titleAndIcon)
                        .foregroundStyle(.green)
                } else {
                    Text("Schätzung").foregroundStyle(.secondary)
                }
                if wartet { ProgressView().controlSize(.mini).help("Neue Werte werden gerechnet") }
            }
            .font(.caption.weight(.medium))
            HStack(spacing: 8) {
                Button {
                    DruckUI.shared.waehle(gruppe, vorschau: vorschau, model: model, einpassen: true)
                } label: {
                    Label("Im 3D zeigen", systemImage: "scope")
                }
                if gruppe.hatVorgaben {
                    Button {
                        model.druckActions?.druckZuruecksetzen(ziel, schluessel: [])
                    } label: {
                        Label("Alles zurücksetzen", systemImage: "arrow.uturn.backward")
                    }
                    .help("Alle festen Werte dieser Teile zurücknehmen: wieder die Empfehlung des Kernels")
                }
            }
            .controlSize(.small)
            .buttonStyle(.bordered)
        }
    }

    private var kennzahlen: some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
            GridRow {
                DruckZahl(wert: DruckFormat.zeit(gruppe.zeitS), titel: gruppe.anzahl > 1 ? "Zeit, alle" : "Zeit")
                DruckZahl(wert: DruckFormat.gramm(gruppe.g), titel: gruppe.anzahl > 1 ? "Filament, alle" : "Filament")
                if let k = gruppe.kosten { DruckZahl(wert: DruckFormat.euro(k), titel: "Kosten") }
            }
            if gruppe.anzahl > 1 {
                GridRow {
                    Text("je Stück \(DruckFormat.zeit(gruppe.zeitJeS)) · \(DruckFormat.gramm(gruppe.grammJe))")
                        .gridCellColumns(3)
                }
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            let zusatz = zusatzZeile
            if !zusatz.isEmpty {
                GridRow {
                    Text(zusatz).gridCellColumns(3)
                }
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }
        }
        .animation(.snappy(duration: 0.3), value: gruppe.zeitS)
    }

    private var zusatzZeile: String {
        var t: [String] = []
        if let s = gruppe.stuetzenG, s > 0.05 { t.append("Stützen \(DruckFormat.gramm(s))") }
        if let r = gruppe.risiko { t.append("Fehldruck-Risiko \(DruckFormat.prozent(r))") }
        if let a = gruppe.abweichung {
            t.append("Schätzung lag \(DruckFormat.prozent(abs(a))) daneben"
                     + (gruppe.abweichungMaterial.map { " (Filament \(DruckFormat.prozent(abs($0))))" } ?? ""))
        }
        return t.joined(separator: " · ")
    }

    // MARK: Empfehlung und Hinweise

    private var empfehlung: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Empfehlung").font(.subheadline.weight(.semibold))
            ForEach(Array(gruppe.begruendung.enumerated()), id: \.offset) { _, b in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)).foregroundStyle(Color.kevAkzent)
                    Text(b).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
                .font(.callout)
            }
        }
    }

    private var hinweise: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Hinweise").font(.subheadline.weight(.semibold))
            ForEach(gruppe.hinweise.sorted { $0.schwere > $1.schwere }) { h in
                DruckHinweisZeile(hinweis: h)
            }
        }
    }

    // MARK: Einstellungen

    private var einstellungen: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Einstellungen").font(.subheadline.weight(.semibold))
                Spacer()
                if wartet {
                    Text("wird gerechnet …").font(.caption).foregroundStyle(.secondary)
                }
            }
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 7) {
                zeile("Zweck", "zweck") {
                    Picker("Zweck", selection: Binding(
                        get: { zweck ?? "funktion" },
                        set: { z in senden(zweck: .string(z)) })) {
                        ForEach(DruckFormat.zwecke, id: \.self) { z in
                            Text(DruckFormat.zweck(z)).tag(z)
                        }
                    }
                    .labelsHidden()
                    .fixedSize()
                    .help(DruckFormat.zweckBeschreibung(zweck ?? "funktion"))
                }
                zeile("Wände", "waende") {
                    Stepper(value: Binding(get: { e.waende ?? 3 }, set: { senden(["waende": .number(Double($0))]) }),
                            in: 1...12) {
                        Text(DruckFormat.waende(e.waende ?? 3)).monospacedDigit()
                    }
                }
                zeile("Füllung", "fuellung") {
                    HStack(spacing: 8) {
                        Slider(value: Binding(
                            get: { fuellungZiehen ?? (e.fuellung ?? 0.2) },
                            set: { fuellungZiehen = ($0 * 20).rounded() / 20 }),
                               in: 0...1, step: 0.05, onEditingChanged: { an in
                            if !an, let f = fuellungZiehen {
                                fuellungZiehen = nil
                                if abs(f - (e.fuellung ?? -1)) > 0.001 { senden(["fuellung": .number(f)]) }
                            }
                        })
                        .frame(minWidth: 90, maxWidth: 160)
                        Text(DruckFormat.prozent(fuellungZiehen ?? (e.fuellung ?? 0.2)))
                            .monospacedDigit()
                            .frame(width: 38, alignment: .trailing)
                    }
                }
                zeile("Muster", "muster") {
                    Picker("Muster", selection: Binding(
                        get: { e.muster ?? "gyroid" },
                        set: { senden(["muster": .string($0)]) })) {
                        ForEach(musterListe, id: \.self) { m in Text(DruckFormat.muster(m)).tag(m) }
                    }
                    .labelsHidden()
                    .fixedSize()
                }
                zeile("Stützen", "stuetzen") {
                    Picker("Stützen", selection: Binding(
                        get: { normStuetzen(e.stuetzen) },
                        set: { senden(["stuetzen": .string($0)]) })) {
                        ForEach(DruckFormat.stuetzenArten, id: \.self) { s in Text(DruckFormat.stuetzen(s)).tag(s) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .fixedSize()
                }
                zeile("Brim", "brim") {
                    Toggle("Brim", isOn: Binding(get: { e.brim ?? false }, set: { senden(["brim": .bool($0)]) }))
                        .labelsHidden()
                        .toggleStyle(.switch)
                        .controlSize(.mini)
                }
                Divider().gridCellColumns(3)
                nurLesen("Schicht", e.schichtMM.map(DruckFormat.schicht))
                nurLesen("Decken / Böden", e.decken.map { d in "\(d) / \(e.boeden.map(String.init) ?? "–")" })
                nurLesen("Ausrichtung", e.ausrichtung)
            }
            .controlSize(.small)
            .disabled(model.druckActions == nil || vorschau.regler)
            if vorschau.regler {
                Text("Lauf mit Reglerwerten: Einstellungen erst nach einem normalen Lauf ändern.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    /// Muster des Kernels plus der aktuelle Wert, falls er nicht in der Liste steht.
    private var musterListe: [String] {
        var l = DruckFormat.muster
        if let m = e.muster, !l.contains(m) { l.insert(m, at: 0) }
        return l
    }

    private func normStuetzen(_ s: String?) -> String {
        switch s?.lowercased() {
        case "baum", "tree", "tree(auto)": return "baum"
        case "normal", "normal(auto)", "grid": return "normal"
        default: return "keine"
        }
    }

    @ViewBuilder
    private func zeile<Inhalt: View>(_ titel: String, _ schluessel: String, @ViewBuilder inhalt: () -> Inhalt) -> some View {
        let quelle = gruppe.quelle(schluessel)
        GridRow(alignment: .center) {
            // Bezeichnung, darunter „von Kevin“, wenn der Wert fest vorgegeben ist
            VStack(alignment: .trailing, spacing: 0) {
                Text(titel).foregroundStyle(quelle == nil ? Color.secondary : Color.primary)
                if let quelle {
                    HStack(spacing: 2) {
                        Image(systemName: "pin.fill").font(.system(size: 7, weight: .semibold))
                        Text(quelle.titel)
                    }
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(Color.kevAkzent)
                    .fixedSize()
                }
            }
            .gridColumnAlignment(.trailing)
            inhalt()
                .frame(maxWidth: .infinity, alignment: .leading)
            Group {
                if quelle != nil {
                    Button {
                        model.druckActions?.druckZuruecksetzen(ziel, schluessel: [schluessel])
                    } label: {
                        Image(systemName: "arrow.uturn.backward.circle.fill")
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(Color.kevAkzent)
                            .font(.system(size: 14))
                    }
                    .buttonStyle(.borderless)
                    .help("\(titel) zurücksetzen: wieder die Empfehlung des Kernels")
                } else {
                    Color.clear.frame(width: 14, height: 1)
                }
            }
        }
        .font(.callout)
    }

    @ViewBuilder
    private func nurLesen(_ titel: String, _ wert: String?) -> some View {
        if let wert {
            GridRow(alignment: .firstTextBaseline) {
                Text(titel).foregroundStyle(.secondary)
                Text(wert).monospacedDigit().lineLimit(2).textSelection(.enabled).gridCellColumns(2)
            }
            .font(.callout)
        }
    }

    @ViewBuilder
    private var profil: some View {
        if gruppe.profilProzess != nil || gruppe.profilFilament != nil {
            VStack(alignment: .leading, spacing: 2) {
                Text("Profile in Bambu Studio").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                if let p = gruppe.profilProzess { Text(p) }
                if let f = gruppe.profilFilament { Text(f) }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
        }
    }

    private func senden(_ werte: [String: JSONValue]) {
        lokal.merge(werte) { _, neu in neu }
        model.druckActions?.druckEinstellen(ziel, einstellungen: werte, zweck: nil)
    }

    private func senden(zweck: JSONValue) {
        lokal["zweck"] = zweck
        model.druckActions?.druckEinstellen(ziel, einstellungen: nil, zweck: zweck)
    }
}
