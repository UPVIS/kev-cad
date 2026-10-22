import AppKit
import KevCADCore
import SwiftUI

// Statik im Inspektor (PLAN-STATIK.md, Stufe 1): Szenarien mit Ampel und Kennzahlen; das gewählte Szenario zeigt der
// Viewer als Farbverlauf der Ausnutzung (grün → gelb → rot) an Teilen und Stäben und mit überhöhter Verformung als
// Geist. Darunter immer die Grenzen der Rechnung (T7).

extension AppModel {
    var statikActions: StatikActions? { actions as? StatikActions }
}

struct StatikAbschnitt: View {
    @ObservedObject var store: StatikStore
    var actions: StatikActions?

    var body: some View {
        if let e = store.ergebnis, !e.szenarien.isEmpty {
            Section {
                ForEach(e.szenarien) { sz in
                    SzenarioZeile(sz: sz, gewaehlt: sz.name == store.szenario?.name) {
                        actions?.waehleStatikSzenario(sz.name)
                    }
                }
                if let sz = store.szenario {
                    SzenarioDetail(sz: sz, actions: actions)
                }
                if !e.vereinfachungen.isEmpty || !e.grenzen.isEmpty {
                    DisclosureGroup("Grenzen der Rechnung") {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array((e.grenzen + e.vereinfachungen).enumerated()), id: \.offset) { _, t in
                                Text(t)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .font(.caption)
                }
            } header: {
                HStack(spacing: 6) {
                    Text("Statik")
                    AmpelPunkt(ampel: e.ampel)
                    if let ms = e.ms {
                        Text("\(KevFormat.number(ms, digits: 0)) ms")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.tertiary)
                    }
                    Spacer()
                    if actions != nil {
                        Toggle(isOn: Binding(get: { store.farbverlauf }, set: { actions?.setStatikFarbverlauf($0) })) {
                            Image(systemName: "paintpalette")
                        }
                        .toggleStyle(.button)
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .help("Farbverlauf der Ausnutzung an Teilen und Stäben (grün → gelb → rot)")
                        Toggle(isOn: Binding(get: { store.verformung }, set: { actions?.setStatikVerformung($0) })) {
                            Image(systemName: "waveform.path")
                        }
                        .toggleStyle(.button)
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                        .help("Verformung überhöht als Geist")
                    }
                }
            }
        }
    }
}

struct AmpelPunkt: View {
    var ampel: StatikAmpel

    var farbe: Color {
        switch ampel {
        case .gruen: return .green
        case .gelb: return .yellow
        case .rot: return .red
        case .grau: return .gray
        }
    }

    var body: some View {
        Circle()
            .fill(farbe)
            .frame(width: 9, height: 9)
            .help(ampel.text)
    }
}

private struct SzenarioZeile: View {
    var sz: StatikSzenario
    var gewaehlt: Bool
    var waehlen: () -> Void

    var body: some View {
        Button(action: waehlen) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                AmpelPunkt(ampel: sz.ampel)
                VStack(alignment: .leading, spacing: 1) {
                    Text(sz.name)
                        .fontWeight(gewaehlt ? .semibold : .regular)
                    if let kurz = kurztext {
                        Text(kurz)
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 4)
                if sz.art == "dynamisch" {
                    Text("dyn.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(sz.beschreibung ?? sz.text)
    }

    var kurztext: String? {
        let k = sz.kennzahlen
        var t: [String] = []
        if let s = k.sicherheit { t.append("Sicherheit \(StatikZahl.sf(s))") }
        if let r = k.kippreserve { t.append("Kippreserve \(KevFormat.number(r, digits: 2))") }
        if let d = k.durchbiegungMm, d > 0.05 { t.append("\(KevFormat.number(d, digits: 1)) mm") }
        return t.isEmpty ? nil : t.joined(separator: " · ")
    }
}

enum StatikZahl {
    static func sf(_ x: Double) -> String {
        if !x.isFinite || x > 999 { return "über 999" }
        return KevFormat.number(x, digits: x < 10 ? 2 : 1)
    }
}

private struct SzenarioDetail: View {
    var sz: StatikSzenario
    var actions: StatikActions?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 2) {
                let k = sz.kennzahlen
                if let s = k.sicherheit {
                    zeile("Sicherheit", "\(StatikZahl.sf(s)) (Ziel \(KevFormat.number(sz.ziel ?? 2, digits: 0)))")
                }
                if let kn = k.knicken { zeile("Knicken", "bei \(StatikZahl.sf(kn))-facher Last") }
                if let d = k.durchbiegungMm {
                    zeile("Durchbiegung", "\(KevFormat.number(d, digits: 1)) mm von "
                        + "\(KevFormat.number(k.durchbiegungGrenzeMm ?? 0, digits: 1)) mm")
                }
                if let v = k.verformungMaxMm, v > 0 { zeile("Verschiebung", "\(KevFormat.number(v, digits: 1)) mm") }
                if let r = k.kippreserve { zeile("Kippreserve", KevFormat.number(r, digits: 2)) }
                if let r = k.rutschreserve { zeile("Rutschreserve", KevFormat.number(r, digits: 2)) }
                if sz.ueberhoehung > 1.05 { zeile("Überhöhung", "\(KevFormat.number(Double(sz.ueberhoehung), digits: 0))-fach") }
            }
            .font(.caption)
            ForEach(sz.auffaellig) { u in
                Button {
                    actions?.zeigeStatikUrteil(u)
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        AmpelPunkt(ampel: u.ampel)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(u.text)
                                .font(.callout)
                                .fixedSize(horizontal: false, vertical: true)
                            if !u.loesung.isEmpty {
                                Text(u.loesung)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Im Viewer zeigen")
                .contextMenu {
                    Button("Text kopieren") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString([u.text, u.loesung].filter { !$0.isEmpty }
                            .joined(separator: "\n"), forType: .string)
                    }
                }
            }
            ForEach(Array(sz.kippen.enumerated()), id: \.offset) { _, k in
                if !k.jeRichtung.isEmpty {
                    Text("Kippt bei " + k.jeRichtung.map {
                        "\($0.richtung) \(KevFormat.number($0.kippwinkel, digits: 0))°"
                    }.joined(separator: ", ") + " Neigung")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .help("\(k.name): Neigung bzw. Beschleunigung, bei der es kippt: " + k.jeRichtung.map {
                            "\($0.richtung) \(KevFormat.number($0.aKipp, digits: 1)) m/s²"
                        }.joined(separator: ", "))
                }
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private func zeile(_ a: String, _ b: String) -> some View {
        GridRow {
            Text(a).foregroundStyle(.secondary)
            Text(b).monospacedDigit()
        }
    }
}
