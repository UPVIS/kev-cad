import AppKit
import KevCADCore
import SwiftUI
import simd

// Rest von Phase 4 in der Oberfläche: Abweichung als Farbkarte (Schalter im Inspektor, Legende in mm unten links im
// Viewport), Maßstab nachträglich (Dialog „Maßstab …“ und Leiste für die zwei Punkte am Netz), Scans vom iPhone (Band
// „Neuer Scan empfangen“, Liste im Abschnitt „Referenzen“). Die Oberfläche liest nur `model.referenzen` und ruft
// `ReferenzActions`.

// MARK: - Abweichung im Inspektor

/// Schalter und Kennzahlen der Abweichung in der Zeile einer Referenz.
struct ReferenzAbweichungZeile: View {
    @ObservedObject var store: ReferenzStore
    let referenz: ReferenzInfo
    let actions: ReferenzActions?

    private var an: Bool { store.farbkarte?.referenz == referenz.name }

    var body: some View {
        if let a = referenz.abweichung {
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Toggle(isOn: Binding(get: { an }, set: { actions?.farbkarteZeigen($0 ? referenz.name : nil,
                                                                                         auf: store.farbkarte?.auf ?? .modell) })) {
                        Text("Abweichung")
                    }
                    .toggleStyle(.checkbox)
                    .disabled(a.stand != "done")
                    .help("Abstand zwischen Modell und Referenznetz als Farbkarte im Viewer (Legende unten links)")
                    Picker("", selection: Binding(
                        get: { store.farbkarte?.auf ?? .modell },
                        set: { actions?.farbkarteZeigen(referenz.name, auf: $0) })
                    ) {
                        Text("Modell").tag(ReferenzAbweichungFeld.Auf.modell)
                        Text("Netz").tag(ReferenzAbweichungFeld.Auf.referenz)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .controlSize(.small)
                    .frame(width: 120)
                    .disabled(!an)
                    .help("Farben auf den Teilen des Modells oder auf dem Referenznetz")
                }
                if a.stand == "done" {
                    Text(zusammenfassung(a)).font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if an {
                        ForEach(a.nachGroesse.prefix(5)) { t in
                            HStack(spacing: 6) {
                                Text(t.teil.split(separator: "/").last.map(String.init) ?? t.teil).lineLimit(1)
                                Spacer()
                                Text(Self.mm(t.kennzahlen.mittel) + " / " + Self.mm(t.kennzahlen.max))
                                    .monospacedDigit()
                                    .foregroundStyle((t.kennzahlen.max ?? 0) > a.skala ? Color.orange : .secondary)
                            }
                            .font(.caption)
                            .help("\(t.teil): mittlere / größte Abweichung in mm, \(Int((t.kennzahlen.abgedeckt * 100).rounded())) % abgedeckt")
                        }
                    }
                    if !a.angelegt {
                        Label("Netz nicht am Modell angelegt (erst vermessen): der Lagefehler steckt mit drin",
                              systemImage: "exclamationmark.triangle")
                            .font(.caption).foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else if let m = a.meldung {
                    Text(m).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func zusammenfassung(_ a: ReferenzAbweichungKurz) -> String {
        let mittel = a.teile.compactMap(\.kennzahlen.mittel)
        let groesst = a.teile.compactMap(\.kennzahlen.max).max()
        guard !mittel.isEmpty else { return "Keine Referenz in der Nähe des Modells" }
        return "Modell zur Referenz: im Mittel \(Self.mm(mittel.reduce(0, +) / Double(mittel.count))) mm, größte "
            + "\(Self.mm(groesst)) mm (\(KevFormat.count(a.teile.count, one: "Teil", many: "Teile")))"
    }

    static func mm(_ v: Double?) -> String { v.map { KevFormat.number($0, digits: 1) } ?? "–" }
}

// MARK: - Legende im Viewport

/// Legende der Farbkarte unten links: Farbband von −skala bis +skala in mm, grau ohne Referenz, Spanne wählbar.
struct AbweichungLegende: View {
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?

    var body: some View {
        if let k = store.farbkarte, let skala = store.farbkarteSkala, let r = store.referenz(k.referenz),
           let a = r.abweichung {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Image(systemName: "paintpalette").foregroundStyle(.secondary)
                    Text("Abweichung \(k.auf == .modell ? "auf dem Modell" : "auf dem Netz")")
                        .font(.callout.weight(.medium))
                    Spacer(minLength: 8)
                    Menu("±\(KevFormat.number(skala, digits: 1)) mm") {
                        Button("Automatisch (±\(KevFormat.number(a.skalaAuto, digits: 1)) mm)") { actions?.farbkarteSkala(nil) }
                        Divider()
                        ForEach([0.5, 1, 2, 3, 5, 10, 15, 20, 30, 50], id: \.self) { s in
                            Button("±\(KevFormat.number(s, digits: 1)) mm") { actions?.farbkarteSkala(s) }
                        }
                    }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                    .help("Spanne der Farben")
                    Button {
                        actions?.farbkarteZeigen(nil, auf: k.auf)
                    } label: {
                        Image(systemName: "xmark").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    .buttonStyle(.borderless)
                    .help("Farbkarte aus")
                }
                band
                HStack {
                    ForEach([-1.0, -0.5, 0, 0.5, 1], id: \.self) { t in
                        Text(beschriftung(t * skala))
                            .frame(maxWidth: .infinity, alignment: t < 0 ? .leading : t > 0 ? .trailing : .center)
                    }
                }
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.secondary)
                HStack(spacing: 10) {
                    punkt(farbe(-0.9), "Modell zu groß")
                    punkt(farbe(0), "passt")
                    punkt(farbe(0.9), "Modell zu klein")
                    punkt(Color(red: Double(AbweichungGeometrie.grau.x), green: Double(AbweichungGeometrie.grau.y),
                                blue: Double(AbweichungGeometrie.grau.z)), "ohne Referenz")
                }
                .font(.caption2)
                Text("Abstand Modell ↔ \(k.referenz) in mm, ab \(KevFormat.number(a.grenze, digits: 0)) mm ohne Referenz")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(width: 360)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(.regularMaterial))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(.primary.opacity(0.08)))
            .shadow(color: .black.opacity(0.14), radius: 8, y: 2)
        }
    }

    private var band: some View {
        HStack(spacing: 0) {
            ForEach(0..<AbweichungGeometrie.baender, id: \.self) { k in
                Rectangle().fill(farbe(AbweichungGeometrie.bandMitte(k)))
            }
        }
        .frame(height: 12)
        .clipShape(RoundedRectangle(cornerRadius: 3))
    }

    private func punkt(_ farbe: Color, _ text: String) -> some View {
        HStack(spacing: 3) {
            Circle().fill(farbe).frame(width: 7, height: 7)
            Text(text).foregroundStyle(.secondary).lineLimit(1).fixedSize()
        }
    }

    private func farbe(_ t: Double) -> Color {
        let c = AbweichungGeometrie.farbeSRGB(t)
        return Color(red: Double(c.x), green: Double(c.y), blue: Double(c.z))
    }

    private func beschriftung(_ v: Double) -> String {
        (v > 0 ? "+" : v < 0 ? "−" : "") + KevFormat.number(abs(v), digits: 1)
    }
}

// MARK: - Maßstab

/// Leiste unten im Viewport, solange „Maßstab setzen“ läuft: zwei Punkte am Netz anklicken, echtes Maß eintragen.
struct MassstabLeiste: View {
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?
    @State private var mm = ""

    var body: some View {
        if let w = store.massstabWerkzeug {
            Pill(symbol: "ruler", tint: .orange) {
                HStack(spacing: 8) {
                    if let d = w.abstand {
                        Text("Maßstab: \(KevFormat.number(d, digits: 1)) mm am Netz sind")
                        TextField("mm", text: $mm)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 70)
                            .onSubmit(uebernehmen)
                        Text("mm")
                    } else {
                        Text("Maßstab: \(w.punkte.isEmpty ? "ersten" : "zweiten") Punkt am Netz anklicken")
                    }
                }
            } trailing: {
                HStack(spacing: 6) {
                    if w.abstand != nil {
                        Button("Übernehmen", action: uebernehmen)
                            .disabled(wert == nil)
                            .keyboardShortcut(.defaultAction)
                    }
                    Button("Abbrechen") { actions?.massstabWerkzeug(nil) }
                        .keyboardShortcut(.cancelAction)
                }
                .buttonStyle(.borderless)
                .controlSize(.small)
            }
            .help("Maßstab der Referenz \(w.referenz): zwei Punkte am Referenznetz anklicken (das Modell lässt Klicks "
                + "durch), dann den echten Abstand eintragen")
            .layoutPriority(1)
            .onChange(of: w.punkte.count) { mm = "" }
        }
    }

    private var wert: Double? {
        Double(mm.replacingOccurrences(of: ",", with: ".")).flatMap { $0 > 0 ? $0 : nil }
    }

    private func uebernehmen() {
        guard let w = store.massstabWerkzeug, w.punkte.count == 2, let v = wert else { return }
        actions?.massstabSetzen(w.referenz, mm: v, punkte: w.punkte, kante: nil)
    }
}

/// Dialog „Maßstab …“: zwei Punkte am Netz wählen oder ein bekanntes Maß der Hülle bzw. der Vermessung eintragen.
struct MassstabDialog: View {
    let referenz: String
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?
    let schliessen: () -> Void
    @State private var art = "punkte"
    @State private var kante = "laenge"
    @State private var mm = ""

    private var info: ReferenzInfo? { store.referenz(referenz) }

    /// Wählbare Maße mit dem aktuellen Wert: Hülle und Grundkörper des Netzes, gemessene Maße.
    private var kanten: [(id: String, titel: String, wert: Double)] {
        var out: [(String, String, Double)] = []
        if let h = info?.captureHuelle {
            out += [("laenge", "Länge der Hülle", h.x), ("breite", "Breite der Hülle", h.y), ("hoehe", "Höhe der Hülle", h.z)]
        }
        if let g = info?.captureGrundkoerper {
            out += [("grund_laenge", "Länge des Grundkörpers", g.x), ("grund_breite", "Breite des Grundkörpers", g.y)]
        }
        for m in store.ergebnisse[referenz]?.masse ?? [] {
            out.append((m.name, "gemessen: \(m.name)", m.wert))
        }
        return out.map { (id: $0.0, titel: $0.1, wert: $0.2) }
    }

    private var wert: Double? {
        Double(mm.replacingOccurrences(of: ",", with: ".")).flatMap { $0 > 0 ? $0 : nil }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Maßstab von \(referenz)").font(.title3.weight(.semibold))
            Text("Object Capture rechnet ohne LiDAR ohne echten Maßstab. Ein bekanntes Maß skaliert Netz, Kameras und "
                + "Bericht; ein gemessenes Maß skaliert auch die Vermessung.")
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let m = info?.massstab {
                Text("Bisher gesetzt: Faktor \(KevFormat.number(m.faktor, digits: 4))"
                    + (m.mm.map { ", \(KevFormat.number($0, digits: 1)) mm" } ?? ""))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Picker("", selection: $art) {
                Text("Zwei Punkte am Netz").tag("punkte")
                Text("Bekanntes Maß").tag("kante")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            if art == "punkte" {
                Text("Im Viewer zwei Punkte am Referenznetz anklicken, deren echten Abstand du kennst (etwa zwei Ecken "
                    + "einer Kante), dann das Maß eintragen.")
                    .fixedSize(horizontal: false, vertical: true)
                if info?.netz != true {
                    Text("Diese Referenz hat kein Netz.").font(.caption).foregroundStyle(.orange)
                }
            } else {
                Form {
                    Picker("Maß", selection: $kante) {
                        ForEach(kanten, id: \.id) { k in
                            Text("\(k.titel) (\(KevFormat.number(k.wert, digits: 1)) mm)").tag(k.id)
                        }
                    }
                    HStack {
                        TextField("echt", text: $mm).frame(width: 90)
                        Text("mm").foregroundStyle(.secondary)
                    }
                }
                .formStyle(.grouped)
            }
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel, action: schliessen).keyboardShortcut(.cancelAction)
                if art == "punkte" {
                    Button("Punkte wählen") {
                        actions?.massstabWerkzeug(referenz)
                        schliessen()
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(info?.netz != true)
                } else {
                    Button("Übernehmen") {
                        if let v = wert { actions?.massstabSetzen(referenz, mm: v, punkte: nil, kante: kante) }
                        schliessen()
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(wert == nil || !kanten.contains { $0.id == kante })
                }
            }
        }
        .padding(20)
        .frame(width: 480)
        .onAppear {
            if info?.netz != true { art = "kante" }
            if let erste = kanten.first, !kanten.contains(where: { $0.id == kante }) { kante = erste.id }
        }
    }
}

// MARK: - Scans vom iPhone

/// Band oben im Viewport: „Neuer Scan empfangen: <Name>“ mit „Scan übernehmen“ (Schnell oder Genau).
struct ScanBand: View {
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?
    let projektOffen: Bool

    var body: some View {
        if let s = store.neuerScan {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "iphone.gen3.radiowaves.left.and.right")
                    .font(.title2)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Neuer Scan empfangen: \(s.name)").font(.headline).lineLimit(1)
                    Text(ScanZeile.details(s) + (projektOffen ? "" : " · erst ein Projekt öffnen"))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                Menu("Scan übernehmen") {
                    Button("Genau (PromptDA Large, 2 bis 4 Minuten)") { actions?.scanUebernehmen(s.id, schnell: false) }
                    Button("Schnell (Vorschau, 1 bis 2 Minuten)") { actions?.scanUebernehmen(s.id, schnell: true) }
                } primaryAction: {
                    actions?.scanUebernehmen(s.id, schnell: false)
                }
                .menuStyle(.borderedButton)
                .fixedSize()
                .disabled(!projektOffen)
                .help("Als Referenz ins offene Projekt übernehmen; Klick = Genau, Pfeil = Auswahl")
                Button {
                    actions?.scanBandAusblenden(s.id)
                } label: {
                    Image(systemName: "xmark")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Band ausblenden; der Scan bleibt in der Liste unter „Referenzen“")
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.regularMaterial)
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.accentColor.opacity(0.05)))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Color.accentColor.opacity(0.4), lineWidth: 1))
                    .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
            }
            .frame(maxWidth: 820)
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }
}

/// Liste der Scans im Abschnitt „Referenzen“ (zugeklappt, neueste zuerst).
struct ScanListeAbschnitt: View {
    @ObservedObject var store: ReferenzStore
    let actions: ReferenzActions?
    @State private var offen = false

    var body: some View {
        if !store.scans.isEmpty || store.scanEmpfaengerLaeuft {
            DisclosureGroup(isExpanded: $offen) {
                if store.scans.isEmpty {
                    Text("Noch keine Scans. Kev Scan auf dem iPhone sendet per WLAN an „\(store.scanEmpfaenger ?? "diesen Mac")“.")
                        .font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                ForEach(store.scans.prefix(12)) { s in
                    ScanZeile(scan: s, uebernahme: store.scanWirdAusgewertet(s.id), actions: actions)
                }
            } label: {
                HStack {
                    Image(systemName: "iphone.gen3").foregroundStyle(.secondary).frame(width: 16)
                    Text("Scans vom iPhone (\(store.scans.count))")
                    if store.scans.contains(where: \.neu) {
                        Text("neu").font(.caption2.weight(.semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Capsule().fill(Color.accentColor))
                    }
                }
            }
        }
    }
}

struct ScanZeile: View {
    let scan: ScanInfo
    let uebernahme: Bool
    let actions: ReferenzActions?

    static func details(_ s: ScanInfo) -> String {
        var teile: [String] = []
        if let e = s.empfangenKurz { teile.append(e) }
        teile.append(KevFormat.count(s.fotos, one: "Foto", many: "Fotos"))
        teile.append("\(s.videobilder) Videobilder")
        if let mb = s.groesseMB { teile.append("\(KevFormat.number(mb, digits: 0)) MB") }
        if s.objekt { teile.append("Box gesetzt") }
        return teile.joined(separator: " · ")
    }

    var body: some View {
        HStack(spacing: 6) {
            VStack(alignment: .leading, spacing: 1) {
                Text(scan.name).lineLimit(1)
                Text(Self.details(scan)
                    + (scan.neu ? "" : " · übernommen in " + scan.referenzen.map(\.name).joined(separator: ", ")))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            Spacer()
            if uebernahme {
                ProgressView().controlSize(.small)
            } else {
                Menu(scan.neu ? "Übernehmen" : "Erneut") {
                    Button("Genau") { actions?.scanUebernehmen(scan.id, schnell: false) }
                    Button("Schnell (Vorschau)") { actions?.scanUebernehmen(scan.id, schnell: true) }
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .controlSize(.small)
                .help("Scan ins offene Projekt übernehmen")
            }
        }
        .padding(.vertical, 1)
    }
}
