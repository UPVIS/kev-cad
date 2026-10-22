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
                    if let ab = sz.ablauf {
                        AblaufDetail(ab: ab, szenario: sz.name, pfeile: store.kontaktpfeile, actions: actions)
                    }
                    if let fk = sz.festkoerper {
                        FestkoerperDetail(
                            fk: fk, mitFeld: !store.felder(fuer: sz).isEmpty, farbverlauf: store.farbverlauf,
                            actions: actions)
                    }
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
                if sz.festkoerper?.laeuft == true {
                    ProgressView(value: sz.festkoerper?.fortschritt ?? 0)
                        .progressViewStyle(.circular)
                        .controlSize(.mini)
                        .help("Festkörper-FEM wird gerechnet (eigener Prozess)")
                } else if sz.festkoerper?.teile.contains(where: { $0.stand == "done" }) == true {
                    Image(systemName: "cube.transparent")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .help("Festkörper (Stufe 3): Teile mit Last als Volumen gerechnet")
                }
                if let ab = sz.ablauf {
                    if ab.laeuft {
                        ProgressView()
                            .controlSize(.mini)
                            .help("Ablauf wird gerechnet (eigener Prozess)")
                    } else {
                        Image(systemName: "figure.walk.motion")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .help("Ablauf (Stufe 2): simuliert über der Zeit")
                    }
                } else if sz.art == "dynamisch" {
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

/// Stufe 2: Ablauf eines Szenarios (MuJoCo): Kennzahlen, Handrechnung, Kippwinkel über der Zeit und „Ablauf zeigen“
/// (spielt die Animation „Ablauf: …“ in der Zeitleiste, Kontaktkräfte als Pfeile).
private struct AblaufDetail: View {
    var ab: StatikAblauf
    var szenario: String
    var pfeile: Bool
    var actions: StatikActions?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if ab.laeuft {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Ablauf wird gerechnet …").font(.caption).foregroundStyle(.secondary)
                }
            } else if !ab.fertig {
                Text("Ablauf nicht gerechnet: \(ab.meldung ?? "?")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                HStack(spacing: 8) {
                    Button {
                        actions?.zeigeAblauf(szenario)
                    } label: {
                        Label("Ablauf zeigen", systemImage: "play.fill")
                    }
                    .controlSize(.small)
                    .disabled(ab.animation == nil)
                    .help("Spielt den simulierten Ablauf in der Zeitleiste ab")
                    Toggle(isOn: Binding(get: { pfeile }, set: { actions?.setKontaktpfeile($0) })) {
                        Image(systemName: "arrow.up.right")
                    }
                    .toggleStyle(.button)
                    .buttonStyle(.borderless)
                    .controlSize(.small)
                    .help("Kontaktkräfte als Pfeile im Ablauf")
                    Spacer()
                    if let ms = ab.msAblauf {
                        Text("\(KevFormat.number(ms, digits: 0)) ms")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.tertiary)
                            .help("Rechenzeit des Ablaufs; Suche: \(ab.varianten ?? 0) Varianten in "
                                + "\(KevFormat.number(ab.msSuche ?? 0, digits: 0)) ms")
                    }
                }
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 2) {
                    if let v = ab.geschwindigkeit {
                        zeile("Schieben", "\(KevFormat.number(v, digits: 2)) m/s, bremsen \(ab.bremsen ?? "–")")
                    }
                    if let r = ab.kippreserve {
                        zeile("Kippreserve", KevFormat.number(r, digits: 2)
                            + (ab.aAbheben.map { " (hebt ab \(KevFormat.number($0, digits: 1)) m/s²)" } ?? ""))
                    }
                    if let h = ab.abhebenMaxMm, h > 0.05 {
                        zeile("Abheben", "\(KevFormat.number(h, digits: 0)) mm, "
                            + "\(KevFormat.number(ab.kippwinkelMax ?? 0, digits: 1))°"
                            + (ab.setztAuf.map { ", \($0) setzt auf" } ?? ""))
                    }
                    if let hand = ab.aKippHand {
                        zeile("Handrechnung", "a = g·b/h = \(KevFormat.number(hand, digits: 1)) m/s²"
                            + (ab.aAbhebenOhneLadung.map { ", Sim. ohne Ladung \(KevFormat.number($0, digits: 1))" }
                                ?? ""))
                    }
                    ForEach(Array(ab.ladung.enumerated()), id: \.offset) { _, l in
                        zeile(
                            l.name.split(separator: "/").last.map(String.init) ?? l.name,
                            (l.bleibt ? "bleibt" : "springt heraus")
                                + (l.hebtMm.map { ", hebt \(KevFormat.number($0, digits: 0)) mm" } ?? "")
                                + (l.vGrenze.map { ", Grenze \(KevFormat.number($0, digits: 2)) m/s" } ?? ""))
                    }
                    if let r = ab.rutschgrenze {
                        zeile("Rutschgrenze", "\(KevFormat.number(r, digits: 1)) m/s² (blockierte Räder)")
                    }
                }
                .font(.caption)
                if ab.kipp.count > 2 {
                    KippVerlauf(zeit: ab.zeit, kipp: ab.kipp)
                        .frame(height: 34)
                        .help("Kippwinkel über der Zeit (+ = nach vorn), größter \(KevFormat.number(ab.kippwinkelMax ?? 0, digits: 2))°")
                }
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private func zeile(_ a: String, _ b: String) -> some View {
        GridRow {
            Text(a).foregroundStyle(.secondary)
            Text(b).monospacedDigit().fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// Kippwinkel über der Zeit als kleine Linie (Nulllinie gestrichelt).
private struct KippVerlauf: View {
    var zeit: [Double]
    var kipp: [Double]

    var body: some View {
        Canvas { ctx, size in
            guard let t0 = zeit.first, let t1 = zeit.last, t1 > t0 else { return }
            let lo = min(kipp.min() ?? 0, 0), hi = max(kipp.max() ?? 0, 0.1)
            func pt(_ i: Int) -> CGPoint {
                CGPoint(x: (zeit[i] - t0) / (t1 - t0) * size.width,
                        y: size.height - (kipp[i] - lo) / (hi - lo) * (size.height - 2) - 1)
            }
            var null = Path()
            let y0 = size.height - (0 - lo) / (hi - lo) * (size.height - 2) - 1
            null.move(to: CGPoint(x: 0, y: y0))
            null.addLine(to: CGPoint(x: size.width, y: y0))
            ctx.stroke(null, with: .color(.secondary.opacity(0.5)), style: StrokeStyle(lineWidth: 0.5, dash: [2, 2]))
            var linie = Path()
            let n = min(zeit.count, kipp.count)
            linie.move(to: pt(0))
            for i in 1..<n { linie.addLine(to: pt(i)) }
            ctx.stroke(linie, with: .color(.orange), lineWidth: 1.2)
        }
    }
}

/// Stufe 3: Festkörper-FEM eines Szenarios: Fortschritt mit Abbruch, je Teil Ampel, Sicherheit (Ziel), maßgebendes
/// Kriterium, Sicherheit in den anderen Drucklagen und der Vergleich mit dem Kragträger; dazu die Farbskala.
private struct FestkoerperDetail: View {
    var fk: StatikFestkoerper
    var mitFeld: Bool
    var farbverlauf: Bool
    var actions: StatikActions?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            switch fk.stand {
            case "laeuft":
                HStack(spacing: 6) {
                    ProgressView(value: fk.fortschritt)
                        .controlSize(.small)
                    Button {
                        actions?.festkoerperAbbrechen()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                    }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
                    .help("Festkörper-Rechnung abbrechen")
                }
                Text("Festkörper: \(fk.text)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            case "abgebrochen":
                Text("Festkörper abgebrochen")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case "failed":
                Text("Festkörper nicht gerechnet: \(fk.meldung ?? "?")")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            default:
                EmptyView()
            }
            ForEach(Array(fk.teile.enumerated()), id: \.offset) { _, t in
                teilZeile(t)
            }
            if mitFeld && farbverlauf {
                FeldSkala()
                    .frame(height: 22)
                    .help("Farbverlauf auf dem Netz: Ausnutzung = Ziel / örtliche Sicherheit (grün bis 1, gelb bis 2, "
                        + "darüber rot); Verformung überhöht als Geist")
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private func teilZeile(_ t: StatikFestkoerperTeil) -> some View {
        let name = t.teil.split(separator: "/").last.map(String.init) ?? t.teil
        if t.stand == "done" {
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    AmpelPunkt(ampel: t.ampel)
                    Text(name).font(.callout)
                    Spacer(minLength: 4)
                    Text("FEM \(t.sicherheit.map(StatikZahl.sf) ?? "–") / \(KevFormat.number(t.ziel ?? 2, digits: 0))")
                        .font(.caption.monospacedDigit())
                        .help("Sicherheit (Festkörper) gegen das Ziel")
                }
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 1) {
                    if let k = t.kriterium {
                        zeile("Maßgebend", k == "schicht" ? "Schichtfuge (quer zur Schicht)"
                            : (k == "quer_unbekannt" ? "Drucklage unbekannt" : "von Mises"))
                    }
                    if let sp = t.spannungMax { zeile("Spannung", "\(KevFormat.number(sp, digits: 1)) N/mm²") }
                    if let v = t.verformungMaxMm { zeile("Verschiebung", "\(KevFormat.number(v, digits: 2)) mm") }
                    if let k = t.kragtraeger { zeile("Kragträger S0", StatikZahl.sf(k)) }
                    if !t.ausrichtungen.isEmpty {
                        zeile("Drucklagen", t.ausrichtungen.map { "\($0.0) \(StatikZahl.sf($0.1))" }.joined(separator: ", "))
                    }
                    if let n = t.tetraeder {
                        zeile("Netz", "\(n) Tetraeder P2, h \(KevFormat.number(t.hMm ?? 0, digits: 1)) mm"
                            + (t.ms.map { ", \(KevFormat.number($0, digits: 0)) ms" } ?? "")
                            + (t.ausSpeicher ? " (gemerkt)" : ""))
                    }
                }
                .font(.caption)
            }
            .help(t.text)
        } else {
            HStack(spacing: 6) {
                if t.stand == "laeuft" {
                    ProgressView().controlSize(.mini)
                } else {
                    AmpelPunkt(ampel: .grau)
                }
                Text(name + (t.stand == "laeuft" ? "" : ": \(t.meldung ?? "nicht gerechnet")"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func zeile(_ a: String, _ b: String) -> some View {
        GridRow {
            Text(a).foregroundStyle(.secondary)
            Text(b).monospacedDigit().fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// Farbskala der Ausnutzung wie im Viewer: Bänder von 0 bis 2, Marke bei 1 (Ziel erreicht).
private struct FeldSkala: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Canvas { ctx, size in
                let n = StatikFeldGeometrie.baender
                let w = size.width / CGFloat(n)
                for b in 0..<n {
                    let c = StatikGeometrie.farbe((Double(b) + 0.5) * Double(StatikFeldGeometrie.bandbreite))
                    let r = CGRect(x: CGFloat(b) * w, y: 0, width: w + 0.5, height: size.height)
                    ctx.fill(Path(r), with: .color(Color(.sRGBLinear, red: Double(c.x), green: Double(c.y),
                                                         blue: Double(c.z))))
                }
                var mitte = Path()
                mitte.move(to: CGPoint(x: size.width / 2, y: 0))
                mitte.addLine(to: CGPoint(x: size.width / 2, y: size.height))
                ctx.stroke(mitte, with: .color(.black.opacity(0.5)), lineWidth: 1)
            }
            .frame(height: 8)
            .clipShape(RoundedRectangle(cornerRadius: 2))
            HStack {
                Text("0")
                Spacer()
                Text("1 = Ziel")
                Spacer()
                Text("2")
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }
}
