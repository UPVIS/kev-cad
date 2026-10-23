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
                        let wert = store.wirksamerFeldWert(fuer: sz)
                        FestkoerperDetail(
                            fk: fk, mitFeld: !store.felder(fuer: sz).isEmpty, farbverlauf: store.farbverlauf,
                            feldWerte: store.feldWerte(fuer: sz), feldWert: wert,
                            feldGroesster: store.feldGroesster(wert, fuer: sz), actions: actions)
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
                        .help(sz.festkoerper?.teile.contains(where: \.istCalculix) == true
                            ? "Festkörper (Stufe 4, CalculiX): mit Kontakt, Plastizität und Traglast gerechnet"
                            : "Festkörper (Stufe 3): Teile mit Last als Volumen gerechnet")
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
            ForEach(Array(sz.lasten.enumerated()), id: \.offset) { _, l in
                LastZeile(last: l)
            }
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

/// Eine Last des Szenarios; ein Kraftpaar (innere Kraft) mit beiden Seiten und dem Hinweis, dass es beim Kippen und
/// Rutschen nicht zählt. Farben wie die Pfeile im Viewer (Last blau, Kraftpaar violett).
private struct LastZeile: View {
    var last: StatikLast

    private func kurz(_ namen: [String]) -> String {
        namen.map { $0.split(separator: "/").last.map(String.init) ?? $0 }.joined(separator: ", ")
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: last.paar ? "arrow.right.and.line.vertical.and.arrow.left" : "arrow.down.to.line")
                .foregroundStyle(last.paar ? Color.purple : Color.blue)
            if last.paar {
                Text("Kraftpaar \(KevFormat.number(Double(last.betrag), digits: 0)) N: \(kurz(last.teile)) ↔ "
                    + kurz(last.gegen))
            } else {
                Text("\(KevFormat.number(Double(last.betrag), digits: 0)) N auf \(kurz(last.teile))")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .help(last.paar
            ? "Innere Kraft: \(kurz(last.teile)) und \(kurz(last.gegen)) drücken am selben Punkt gegeneinander. "
                + "Beim Kippen, Rutschen und Abheben des Ganzen heben sich beide auf; jede Seite belastet ihre Teile."
            : "Äußere Last auf \(kurz(last.teile))")
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
/// Stufe 4 (CalculiX): zusätzlich Traglast, Sicherheit unter Last, Kontakt je Partner, Klemmkraft, Plastizität,
/// Beulen und „rutscht“; trägt das Feld Zusatzwerte, die Wahl des Farbfelds.
private struct FestkoerperDetail: View {
    var fk: StatikFestkoerper
    var mitFeld: Bool
    var farbverlauf: Bool
    /// Wählbare Werte des Farbfelds (`StatikFeldWert`), erster ist die Ausnutzung.
    var feldWerte: [String]
    /// Wert, nach dem gerade gefärbt wird.
    var feldWert: String
    /// Größter Wert des gewählten Zusatzwerts über alle Felder (nil bei der Ausnutzung).
    var feldGroesster: Double?
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
            if mitFeld && feldWerte.count > 1 {
                Picker("Farbfeld", selection: Binding(get: { feldWert }, set: { actions?.waehleStatikFeldWert($0) })) {
                    ForEach(feldWerte, id: \.self) { w in
                        Text(StatikFeldWert.titel(w)).tag(w)
                    }
                }
                .pickerStyle(.menu)
                .controlSize(.small)
                .font(.caption)
                .disabled(actions == nil)
                .help("Wert, nach dem das Netz gefärbt wird: Ausnutzung oder Ergebnis von CalculiX (S4)")
            }
            if mitFeld && farbverlauf {
                FeldSkala(wert: feldWert, groesster: feldGroesster)
                    .frame(height: 22)
                    .help(skalaHilfe)
            }
        }
        .padding(.vertical, 2)
    }

    private var skalaHilfe: String {
        if feldWert == StatikFeldWert.ausnutzung {
            return "Farbverlauf auf dem Netz: Ausnutzung = Ziel / örtliche Sicherheit (grün bis 1, gelb bis 2, "
                + "darüber rot); Verformung überhöht als Geist"
        }
        return "Farbverlauf auf dem Netz: \(StatikFeldWert.titel(feldWert)) von 0 (grün) bis "
            + "\(StatikFeldWert.text(feldWert, feldGroesster ?? 0)) (rot); Verformung überhöht als Geist"
    }

    /// Vielfaches der Last, z. B. "6,2" oder "12".
    private func fach(_ x: Double) -> String {
        KevFormat.number(x, digits: x >= 10 ? 0 : 1)
    }

    private func kurz(_ name: String) -> String {
        name.split(separator: "/").last.map(String.init) ?? name
    }

    private func traglastText(_ tl: StatikTraglast) -> String? {
        if tl.nichtErreicht {
            return "über \(fach(tl.lastfaktorMax ?? tl.erreicht ?? 0))-fach"
        }
        guard let f = tl.faktor else { return nil }
        return "\(fach(f))-fach" + (tl.text.map { ", \($0)" } ?? "")
    }

    private func kontaktText(_ k: StatikKontaktPaar) -> String {
        var t: [String] = []
        if let d = k.druckMax { t.append("Druck bis \(StatikFeldWert.text("kontaktdruck", d))") }
        if let a = k.anteilTraegt { t.append("trägt \(KevFormat.percent(a))") }
        if let kl = k.klaffenMaxMm, kl > 0.001 { t.append("klafft \(StatikFeldWert.text("klaffen", kl))") }
        if let s = k.schlupfMaxMm, s > 0.001 { t.append("gleitet \(StatikFeldWert.text("schlupf", s))") }
        return "\(kurz(k.mit)): " + (t.isEmpty ? "berührt" : t.joined(separator: ", "))
    }

    private func kontaktHilfe(_ k: StatikKontaktPaar) -> String {
        var t = ["Kontakt mit \(k.mit)" + (k.rolle.map { " (\($0))" } ?? "")]
        if let f = k.kraftN { t.append("Kraft \(KevFormat.number(f, digits: 1)) N") }
        if let a = k.traegtMm2 { t.append("trägt \(KevFormat.number(a, digits: 0)) mm²") }
        if let mu = k.reibwert { t.append("Reibwert \(KevFormat.number(mu, digits: 2))") }
        if let r = k.reibungAusnutzung { t.append("Reibung zu \(KevFormat.percent(r)) genutzt") }
        if let g = k.gleitetAnteil { t.append("gleitet auf \(KevFormat.percent(g)) der tragenden Fläche") }
        if let q = k.quelle { t.append(q) }
        return t.joined(separator: " · ")
    }

    private func plastischText(_ pl: StatikPlastisch) -> String {
        guard pl.fliesst else { return "bleibt elastisch" }
        var t: [String] = []
        if let d = pl.dehnungMax { t.append("Dehnung \(StatikFeldWert.text("plast_dehnung", d))") }
        if let b = pl.bleibendMm { t.append("bleibend \(StatikFeldWert.text("klaffen", b))") }  // mm wie Klaffen
        return t.isEmpty ? "fließt" : t.joined(separator: ", ")
    }

    private func plastischHilfe(_ pl: StatikPlastisch) -> String {
        var t: [String] = []
        if let m = pl.modell { t.append(m) }
        if let g = pl.grenzdehnung { t.append("Grenzdehnung \(StatikFeldWert.text("plast_dehnung", g))") }
        if let f = pl.fliessgrenze { t.append("Fließgrenze \(KevFormat.number(f, digits: 1)) N/mm²") }
        return t.joined(separator: " · ")
    }

    @ViewBuilder
    private func teilZeile(_ t: StatikFestkoerperTeil) -> some View {
        let name = t.teil.split(separator: "/").last.map(String.init) ?? t.teil
        if t.stand == "done" {
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    AmpelPunkt(ampel: t.ampel)
                    Text(name).font(.callout)
                    if t.istCalculix {
                        Text("CalculiX (S4)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 4)
                            .padding(.vertical, 1)
                            .background(Capsule().fill(Color.secondary.opacity(0.15)))
                            .help("Stufe 4: mit CalculiX gerechnet (Kontakt, Plastizität, Traglast)")
                    }
                    if t.rutscht {
                        Text("rutscht")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.red)
                            .help("Ein Kontaktpartner rutscht schon unter der Last: Die Klemmung hält nicht")
                    }
                    Spacer(minLength: 4)
                    Text("FEM \(t.sicherheit.map(StatikZahl.sf) ?? "–") / \(KevFormat.number(t.ziel ?? 2, digits: 0))")
                        .font(.caption.monospacedDigit())
                        .help(t.istCalculix
                            ? "Sicherheit (CalculiX) gegen das Ziel: der Traglastfaktor, ohne Traglast die Sicherheit "
                                + "unter Last"
                            : "Sicherheit (Festkörper) gegen das Ziel")
                }
                Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 1) {
                    traglastZeilen(t)  // Stufe 4
                    if let k = t.kriterium {
                        zeile("Maßgebend", k == "schicht" ? "Schichtfuge (quer zur Schicht)"
                            : (k == "quer_unbekannt" ? "Drucklage unbekannt" : "von Mises"))
                    }
                    kontaktZeilen(t)  // Stufe 4
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

    /// Stufe 4: Traglast und Sicherheit unter Last (Zeilen im Grid des Teils).
    @ViewBuilder
    private func traglastZeilen(_ t: StatikFestkoerperTeil) -> some View {
        if let tl = t.traglast, let text = traglastText(tl) {
            zeile("Traglast", text, hilfe: traglastHilfe(tl))
        }
        if let sl = t.sicherheitLast {
            zeile("Unter Last", "Sicherheit \(StatikZahl.sf(sl))",
                  hilfe: "Sicherheit unter der Last aus den elastisch-plastischen Spannungen mit Kontakt")
        }
    }

    /// Stufe 4: je Kontaktpaar eine Zeile, Klemmkräfte, Plastizität, Beulen (Zeilen im Grid des Teils).
    @ViewBuilder
    private func kontaktZeilen(_ t: StatikFestkoerperTeil) -> some View {
        ForEach(Array(t.kontaktPaare.enumerated()), id: \.offset) { _, k in
            zeile("Kontakt", kontaktText(k), hilfe: kontaktHilfe(k))
        }
        ForEach(Array(t.klemmungen.enumerated()), id: \.offset) { _, c in
            zeile("Klemmkraft", klemmText(c), hilfe: c.quelle)
        }
        if let pl = t.plastisch {
            zeile("Plastisch", plastischText(pl), hilfe: plastischHilfe(pl))
        }
        if let b = t.beulfaktor {
            zeile("Beulen", "bei \(fach(b))-facher Last")
        }
    }

    private func traglastHilfe(_ tl: StatikTraglast) -> String? {
        guard let e = tl.erreicht else { return nil }
        var t = "Last gesteigert bis zum \(fach(e))-Fachen"
        if let m = tl.lastfaktorMax { t += ", höchstens \(fach(m))-fach" }
        return t
    }

    private func klemmText(_ c: StatikKlemmung) -> String {
        let kraft = c.kraftN.map { KevFormat.number($0, digits: 0) } ?? "–"
        return "\(kraft) N" + (c.schraube.map { " (\(kurz($0)))" } ?? "")
    }

    @ViewBuilder
    private func zeile(_ a: String, _ b: String, hilfe: String? = nil) -> some View {
        GridRow {
            Text(a).foregroundStyle(.secondary).hilfe(hilfe)
            Text(b).monospacedDigit().fixedSize(horizontal: false, vertical: true).hilfe(hilfe)
        }
    }
}

private extension View {
    /// Tooltip nur, wenn es einen Text gibt (sonst bleibt der des umgebenden Views).
    @ViewBuilder
    func hilfe(_ text: String?) -> some View {
        if let text, !text.isEmpty {
            help(text)
        } else {
            self
        }
    }
}

/// Farbskala wie im Viewer: Bänder von 0 bis 2. Für die Ausnutzung mit Marke bei 1 (Ziel erreicht), für einen
/// Zusatzwert der Stufe 4 mit Name, Einheit und Bereich von 0 bis zum größten Wert.
private struct FeldSkala: View {
    var wert: String = StatikFeldWert.ausnutzung
    var groesster: Double?

    private var istAusnutzung: Bool { wert == StatikFeldWert.ausnutzung }

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
                if istAusnutzung {
                    var mitte = Path()
                    mitte.move(to: CGPoint(x: size.width / 2, y: 0))
                    mitte.addLine(to: CGPoint(x: size.width / 2, y: size.height))
                    ctx.stroke(mitte, with: .color(.black.opacity(0.5)), lineWidth: 1)
                }
            }
            .frame(height: 8)
            .clipShape(RoundedRectangle(cornerRadius: 2))
            HStack {
                Text("0")
                Spacer()
                if istAusnutzung {
                    Text("1 = Ziel")
                    Spacer()
                    Text("2")
                } else {
                    Text(StatikFeldWert.titel(wert))
                    Spacer()
                    Text(StatikFeldWert.text(wert, groesster ?? 0))
                }
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }
}
