import AppKit
import KevCADCore
import SwiftUI

// Schnellansichten unter dem Viewport (Strang „Material“): Stückliste kompakt, Zuschnitt kompakt und, sobald das Modell
// Druckteile hat, die Druck-Schnellansicht. Jede klappt einzeln auf und zu; offene stehen untereinander mit Kopfzeile und
// ziehbarer Höhe, eingeklappte teilen sich eine schmale Leiste mit ihren Kennzahlen. „In Material öffnen“ springt in
// den Bereich „Material“ an dieselbe Stelle. Zustand und Höhen je Projektfenster (ProjectWindowState.schnell).

/// Höhe einer Kopfzeile bzw. der Leiste der eingeklappten Ansichten.
let schnellKopfHoehe: CGFloat = 30

struct SchnellansichtenBereich: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    /// Höhe, die Viewport und Schnellansichten zusammen haben (der Viewport behält mindestens `viewportMin`).
    var gesamtHoehe: CGFloat
    /// 3D-Bereich vorn. Verdeckt (Dokumente, Material) bleibt nur ein leerer Platzhalter in derselben Höhe: Der Viewport
    /// behält seine Größe, und die Tabellen zeichnen nicht bei jeder Änderung im verdeckten Bereich mit.
    var aktiv = true
    var navigation: MaterialNavigation?
    @State private var start: [Schnellansicht: Double]?

    static let viewportMin: CGFloat = 230

    var body: some View {
        let daten = model.materialDaten
        let sichtbar = Self.sichtbar(daten)
        let offen = state.schnell.offene(sichtbar)
        let zu = state.schnell.eingeklappte(sichtbar)
        let koepfe = CGFloat(offen.count) * schnellKopfHoehe + (zu.isEmpty ? 0 : schnellKopfHoehe)
        let platz = Double(max(0, gesamtHoehe - Self.viewportMin - koepfe))
        let hoehen = state.schnell.verteilt(sichtbar, platz: platz)
        if !aktiv {
            let inhalt = offen.reduce(0.0) { $0 + (hoehen[$1] ?? $1.standardHoehe) }
            Color.clear.frame(height: koepfe + CGFloat(inhalt) + CGFloat(offen.count) + (zu.isEmpty ? 0 : 1))
        } else {
            bereich(daten, sichtbar: sichtbar, offen: offen, zu: zu, hoehen: hoehen, platz: platz)
        }
    }

    private func bereich(
        _ daten: MaterialDaten, sichtbar: [Schnellansicht], offen: [Schnellansicht], zu: [Schnellansicht],
        hoehen: [Schnellansicht: Double], platz: Double
    ) -> some View {
        VStack(spacing: 0) {
            ForEach(offen) { a in
                SchnellGriff { dy in
                    if start == nil { start = hoehen }
                    if let s = start { state.schnell.ziehe(a, dy: dy, start: s, sichtbar: sichtbar, platz: platz) }
                } ende: {
                    start = nil
                }
                SchnellKopf(model: model, state: state, ansicht: a, daten: daten, offen: true, navigation: navigation)
                inhalt(a, daten)
                    .frame(height: CGFloat(hoehen[a] ?? a.standardHoehe))
                    .clipped()
            }
            if !zu.isEmpty {
                Divider()
                SchnellLeiste(model: model, state: state, ansichten: zu, daten: daten, navigation: navigation)
            }
        }
        .background(Color(nsColor: .controlBackgroundColor))
        .animation(.snappy(duration: 0.22), value: state.schnell.offen)
    }

    /// Welche Schnellansichten es gibt: Stückliste immer, Zuschnitt mit Stangen, Platten oder Normteilen, Druck mit
    /// Druckteilen.
    static func sichtbar(_ daten: MaterialDaten) -> [Schnellansicht] {
        var s: [Schnellansicht] = [.stueckliste]
        if !daten.zuschnitte.isEmpty || !daten.stueckgut.isEmpty { s.append(.zuschnitt) }
        if daten.kennzahlen.druckteile > 0 { s.append(.druck) }
        return s
    }

    @ViewBuilder
    private func inhalt(_ a: Schnellansicht, _ daten: MaterialDaten) -> some View {
        switch a {
        case .stueckliste: StuecklisteSchnell(model: model, daten: daten, navigation: navigation)
        case .zuschnitt: ZuschnittSchnell(model: model, daten: daten)
        case .druck: DruckSchnellansicht(model: model)
        }
    }
}

// MARK: - Kopf und Leiste

/// Kennzahlen einer Schnellansicht für Kopfzeile und Leiste.
private func schnellKennzahlen(_ a: Schnellansicht, _ daten: MaterialDaten, kurz: Bool) -> String {
    let k = daten.kennzahlen
    switch a {
    case .stueckliste:
        guard daten.hatStueckliste else { return "noch keine" }
        var t: [String] = []
        if !kurz { t.append(KevFormat.count(k.positionen, one: "Position", many: "Positionen")) }
        t += [KevFormat.count(k.teile, one: "Teil", many: "Teile"), KevFormat.kg(k.kg), k.kostenText]
        return t.joined(separator: " · ")
    case .zuschnitt:
        var t = [k.zuschnittText]
        if k.verschnittText != "–" { t.append("Verschnitt " + k.verschnittText) }
        if !kurz, k.neueReste > 0 { t.append(KevFormat.count(k.neueReste, one: "neuer Rest", many: "neue Reste")) }
        return t.joined(separator: " · ")
    case .druck:
        guard k.druckteile > 0 else { return "keine" }
        // mit Druckvorschau: Gramm, Kosten, Zeit und Platten aus ihr (Druck/DruckMaterial.swift)
        var t = kurz && k.druckZeitS != nil ? [] : [KevFormat.count(k.druckteile, one: "Teil", many: "Teile")]
        t.append(DruckFormat.gramm(k.druckGramm))
        if let p = k.druckPreis { t.append((k.druckZeitS != nil ? "≈ " : "") + KevFormat.euro(p)) }
        if let z = k.druckZeitS { t.append(DruckFormat.zeit(z)) }
        if let n = k.druckPlatten { t.append(KevFormat.count(n, one: "Platte", many: "Platten")) }
        return t.joined(separator: " · ")
    }
}

/// Ziel von „In Material öffnen“: derselbe Abschnitt, mit der gewählten Position bzw. ihrem Lagerteil.
@MainActor
private func materialZiel(_ a: Schnellansicht, _ model: AppModel, _ daten: MaterialDaten) -> (MaterialAbschnitt, Int?, String?) {
    let p = model.selectedPartIDs.first.flatMap { daten.position(enthaelt: $0) }
    switch a {
    case .stueckliste: return (.stueckliste, p?.pos, nil)
    case .zuschnitt:
        let sid = p?.stockID.flatMap { daten.zuschnitt($0) != nil ? $0 : nil }
        return (.zuschnitt, p?.pos, sid)
    case .druck: return (.druck, p?.herkunft == .druckteil ? p?.pos : nil, nil)
    }
}

/// Kopfzeile einer offenen Schnellansicht: Pfeil, Titel, Kennzahlen, Aktionen, „In Material öffnen“.
private struct SchnellKopf: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    let ansicht: Schnellansicht
    let daten: MaterialDaten
    let offen: Bool
    var navigation: MaterialNavigation?
    @State private var zeigeHinweise = false

    var body: some View {
        HStack(spacing: 10) {
            Button {
                withAnimation(.snappy(duration: 0.22)) { state.schnell.umschalten(ansicht) }
            } label: {
                HStack(spacing: 7) {
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(offen ? 90 : 0))
                        .frame(width: 12)
                    Image(systemName: ansicht.symbol).foregroundStyle(.secondary)
                    Text(ansicht.titel).fontWeight(.semibold).fixedSize()
                    ViewThatFits(in: .horizontal) {
                        Text(schnellKennzahlen(ansicht, daten, kurz: false))
                        Text(schnellKennzahlen(ansicht, daten, kurz: true))
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    Spacer(minLength: 8)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(offen ? "\(ansicht.titel) einklappen" : "\(ansicht.titel) aufklappen")
            .layoutPriority(1)  // Kennzahlen vor der Legende
            zusatz
            if let navigation {
                Button {
                    let z = materialZiel(ansicht, model, daten)
                    navigation.zeige(z.0, z.1, z.2)
                } label: {
                    Label("In Material öffnen", systemImage: "arrow.up.forward.app")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.borderless)
                .help("In Material öffnen: \(ansicht.titel) ausführlich (⌘3)")
            }
        }
        .font(.callout)
        .lineLimit(1)
        .padding(.leading, 10)
        .padding(.trailing, 10)
        .frame(height: schnellKopfHoehe)
        .background(.bar)
    }

    @ViewBuilder
    private var zusatz: some View {
        switch ansicht {
        case .stueckliste:
            if !daten.warnungen.isEmpty {
                Button {
                    zeigeHinweise.toggle()
                } label: {
                    Label("\(daten.warnungen.count)", systemImage: "exclamationmark.triangle.fill")
                        .symbolRenderingMode(.multicolor)
                }
                .buttonStyle(.borderless)
                .help(daten.warnungen[0] + (daten.warnungen.count > 1 ? " und \(daten.warnungen.count - 1) weitere" : ""))
                .popover(isPresented: $zeigeHinweise, arrowEdge: .bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Hinweise zur Stückliste").font(.headline)
                        ForEach(Array(daten.warnungen.enumerated()), id: \.offset) { _, w in
                            Label(w, systemImage: "exclamationmark.triangle.fill")
                                .symbolRenderingMode(.multicolor)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(14)
                    .frame(width: 380, alignment: .leading)
                }
            }
            Menu {
                Button("Als CSV exportieren") { model.actions?.export(formats: ["bom_csv"]) }
                    .disabled(daten.positionen.isEmpty)
                Button("Gebaut …") { BestandUI.shared.zeigeGebaut() }
                    .disabled(model.bestandActions == nil || model.bestandZustand.zuschnitt == nil || model.laufAktiv)
                Divider()
                Button("Als Bericht drucken …") { navigation?.bericht(.stueckliste) }
                    .disabled(navigation == nil)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Weitere Aktionen zur Stückliste")
        case .zuschnitt:
            if daten.kennzahlen.einkaufLager > 0 {
                Button {
                    navigation?.zeige(.einkauf, nil, nil)
                } label: {
                    KennzeichenMarke(kennzeichen: .kaufen, text: "Es fehlt Material")
                }
                .buttonStyle(.plain)
                .help("Nicht alles ist im Bestand des Projekts: zur Einkaufsliste")
            }
            ViewThatFits(in: .horizontal) {
                ZuschnittLegende()
                Color.clear.frame(width: 0, height: 0)
            }
            Menu {
                Button("Gebaut …") { BestandUI.shared.zeigeGebaut() }
                    .disabled(model.bestandActions == nil || model.bestandZustand.zuschnitt == nil || model.laufAktiv)
                Button("Einkaufsliste kopieren") {
                    copyToPasteboard(MaterialText.einkaufText(daten, projekt: model.project?.name,
                                                              stand: BestandText.anzeige(BestandText.heute(), mitZeit: false)))
                }
                .disabled(daten.einkauf.isEmpty)
                Divider()
                Button("Als Bericht drucken …") { navigation?.bericht(.zuschnitt) }
                    .disabled(navigation == nil)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Weitere Aktionen zum Zuschnitt")
        case .druck:
            EmptyView()
        }
    }
}

/// Leiste der eingeklappten Schnellansichten: je eine Kapsel mit Pfeil, Titel und Kennzahlen.
private struct SchnellLeiste: View {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState
    let ansichten: [Schnellansicht]
    let daten: MaterialDaten
    var navigation: MaterialNavigation?

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(ansichten.enumerated()), id: \.element) { i, a in
                if i > 0 { Divider().frame(height: 16) }
                SchnellKapsel(ansicht: a, text: schnellKennzahlen(a, daten, kurz: true)) {
                    withAnimation(.snappy(duration: 0.22)) { state.schnell.umschalten(a) }
                }
            }
            Spacer(minLength: 8)
            if let navigation {
                Button {
                    let a = ansichten.first ?? .stueckliste
                    let z = materialZiel(a, model, daten)
                    navigation.zeige(z.0, z.1, z.2)
                } label: {
                    Label("Material", systemImage: "arrow.up.forward.app")
                }
                .buttonStyle(.borderless)
                .help("In Material öffnen: Stückliste, Zuschnitt, Bestand, Einkaufsliste ausführlich (⌘3)")
            }
        }
        .font(.callout)
        .lineLimit(1)
        .padding(.horizontal, 6)
        .frame(height: schnellKopfHoehe)
        .background(.bar)
    }
}

private struct SchnellKapsel: View {
    let ansicht: Schnellansicht
    let text: String
    var aktion: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: aktion) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                Image(systemName: ansicht.symbol).foregroundStyle(.secondary)
                // Der Titel bleibt immer ganz, die Kennzahlen kürzen sich
                Text(ansicht.titel).fontWeight(.medium).fixedSize()
                Text(text)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(Color.primary.opacity(hover ? 0.07 : 0)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("\(ansicht.titel) aufklappen")
    }
}

/// Griff an der Oberkante einer offenen Schnellansicht: ziehen ändert die Höhe (über der ersten gegen den Viewport,
/// sonst zwischen zwei Ansichten).
private struct SchnellGriff: View {
    var zieht: (Double) -> Void
    var ende: () -> Void
    @State private var cursor = false

    var body: some View {
        Divider()
            .overlay {
                Color.clear
                    .frame(height: 9)
                    .contentShape(Rectangle())
                    .onHover { inside in
                        if inside, !cursor {
                            NSCursor.resizeUpDown.push()
                            cursor = true
                        } else if !inside, cursor {
                            NSCursor.pop()
                            cursor = false
                        }
                    }
                    .gesture(
                        DragGesture(minimumDistance: 1, coordinateSpace: .global)
                            .onChanged { v in zieht(Double(v.translation.height)) }
                            .onEnded { _ in ende() }
                    )
            }
            .zIndex(1)
    }
}

// MARK: - Inhalte

/// Stückliste kompakt: Tabelle wie bisher; ohne Stückliste ein leerer Zustand.
private struct StuecklisteSchnell: View {
    @ObservedObject var model: AppModel
    let daten: MaterialDaten
    var navigation: MaterialNavigation?

    var body: some View {
        if !daten.hatStueckliste {
            HStack(spacing: 10) {
                Text("Noch keine Stückliste: sie entsteht nach jedem Lauf aus den verbauten Lagerteilen.")
                    .foregroundStyle(.secondary)
                Button("Stückliste anfordern") { model.catalogActions?.requestBOM() }
                    .controlSize(.small)
                    .disabled(model.project == nil || !(model.kernelState == .ready || model.kernelState == .busy))
            }
            .font(.callout)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if daten.positionen.isEmpty {
            Text("Stückliste ist leer: im Modell stecken keine Lagerteile und keine Teile mit Material.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            StuecklisteKompaktTabelle(model: model, daten: daten, navigation: navigation)
        }
    }
}

/// Zuschnitt kompakt: je Lagerteil die Stangen bzw. Platten als Balken mit Resten, dann die Normteile.
private struct ZuschnittSchnell: View {
    @ObservedObject var model: AppModel
    let daten: MaterialDaten

    var body: some View {
        let gewaehlt = daten.positionen(mit: Set(model.selectedPartIDs))
        ScrollView(.vertical) {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(daten.zuschnitte) { z in
                    ZuschnittBlock(zuschnitt: z, lines: daten.lines(z.stockID), mindestrest: daten.mindestrest(z.stockID),
                                   verschnitt: daten.verschnitt(z), groesse: .kompakt, selected: gewaehlt) { line in
                        model.catalogActions?.showBOMLine(line)
                    }
                }
                if !daten.stueckgut.isEmpty {
                    StueckgutBlock(stueckgut: daten.stueckgut, groesse: .kompakt)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .scrollBounceBehavior(.basedOnSize)
    }
}
