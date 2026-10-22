import AppKit
import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

/// Volle Druckvorschau (DRUCKVORSCHAU.md, Abschnitt „App“): oben der Platz für die Druckerleiste (Phase 8), Kopf mit
/// Stand und Summe (Platten, Zeit mit Plattenwechseln, Filament, Kosten) und „Als 3MF sichern …“; darunter links die
/// Platten in der Draufsicht, in der Mitte Filament je Material, Platten, Teile mit Empfehlung und Hinweise als Ampel,
/// rechts die gewählte Gruppe mit ihren Einstellungen. Eingebaut vom Material-Strang (`DruckAbschnitt`).
struct DruckAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var druck: DruckStore
    @ObservedObject private var ui = DruckUI.shared
    /// Im Bereich „Material“ eingebettet: Titel und Symbol trägt der Abschnittskopf, hier nur Stand und Summe.
    var eingebettet = false

    init(model: AppModel, eingebettet: Bool = false) {
        self.model = model
        self.eingebettet = eingebettet
        _druck = ObservedObject(wrappedValue: model.druck)
    }

    var body: some View {
        VStack(spacing: 0) {
            DruckerPlatz(model: model)
            kopf
            Divider()
            baender
            inhalt
        }
        .background(Color(nsColor: .controlBackgroundColor))
        .onAppear {
            ui.pruefe(druck.vorschau)
            if druck.vorschau == nil { model.druckActions?.druckvorschauAnfordern() }
        }
        .onChange(of: druck.vorschau) { _, v in ui.pruefe(v) }
        .onChange(of: model.selectedPartIDs) { _, ids in ui.folge(auswahl: ids, vorschau: druck.vorschau) }
    }

    // MARK: Kopf

    private var kopf: some View {
        HStack(spacing: 16) {
            HStack(spacing: 8) {
                if !eingebettet {
                    Image(systemName: "printer.fill").foregroundStyle(Color.kevAkzent)
                    Text("3D-Druck").font(.headline)
                }
                if let v = druck.vorschau, !v.istLeer {
                    DruckStandMarke(vorschau: v)
                    if model.isRunning {
                        ProgressView().controlSize(.mini).help("Lauf läuft, die Vorschau folgt")
                    }
                }
            }
            .fixedSize()
            Spacer(minLength: 8)
            if let v = druck.vorschau, !v.istLeer {
                ViewThatFits(in: .horizontal) {
                    summen(v, alle: true)
                    summen(v, alle: false)
                    EmptyView()
                }
                exportKnopf(v)
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 50)
        .background(.bar)
    }

    private func summen(_ v: Druckvorschau, alle: Bool) -> some View {
        HStack(spacing: 18) {
            DruckZahl(wert: KevFormat.integer(v.summe.platten), titel: v.summe.platten == 1 ? "Platte" : "Platten")
            DruckZahl(wert: DruckFormat.zeit(v.summe.zeitMitWechselS), titel: "Druckzeit",
                      hilfe: "\(DruckFormat.zeit(v.summe.zeitS)) Druck" + (v.summe.wechselS > 0
                          ? " und \(DruckFormat.zeit(v.summe.wechselS)) für Plattenwechsel" : ""))
            if alle {
                DruckZahl(wert: DruckFormat.gramm(v.summe.gramm), titel: "Filament",
                          hilfe: v.summe.meter.map { DruckFormat.meter($0) } ?? "")
            }
            DruckZahl(wert: v.summe.kosten.map { DruckFormat.euro($0) } ?? "–", titel: "Kosten", hilfe: kostenHilfe(v))
            DruckAmpelPunkt(ampel: v.ampel, groesse: 9)
        }
        .animation(.snappy(duration: 0.4), value: v.signatur)
    }

    private func kostenHilfe(_ v: Druckvorschau) -> String {
        var t: [String] = []
        if let f = v.summe.kostenFilament { t.append("Filament \(DruckFormat.euro(f))") }
        if let s = v.summe.kostenStrom { t.append("Strom \(DruckFormat.euro(s))") }
        if let r = v.summe.kostenRisiko { t.append("Aufschlag Fehldruck \(DruckFormat.euro(r))") }
        return t.joined(separator: "\n")
    }

    private func exportKnopf(_ v: Druckvorschau) -> some View {
        Menu {
            Button("Alle Platten als 3MF sichern …") { exportieren([]) }
            if v.platten.count > 1 {
                Divider()
                ForEach(v.platten) { p in
                    Button("Nur Platte \(p.nr) als 3MF sichern …") { exportieren([p.nr]) }
                }
            }
        } label: {
            Label("Als 3MF sichern …", systemImage: "square.and.arrow.down.on.square")
        } primaryAction: {
            exportieren([])
        }
        .menuStyle(.button)
        .fixedSize()
        .controlSize(.small)
        .disabled(model.druckActions == nil || v.platten.isEmpty || druck.export.laeuftGerade)
        .help("Ohne Drucken: die angeordneten Platten als 3MF für Bambu Studio sichern, je Material eine Datei. "
              + "Zum Drucken „Drucken …“ in der Druckerleiste.")
    }

    /// Ziel wählen und PRINT_EXPORT_REQ senden.
    private func exportieren(_ platten: [Int]) {
        let panel = NSSavePanel()
        panel.title = platten.isEmpty ? "Platten als 3MF sichern" : "Platte \(platten[0]) als 3MF sichern"
        panel.message = "Je Material entsteht eine eigene Datei (ohne AMS druckt der P1P ein Material je Platte)."
        panel.allowedContentTypes = [UTType(filenameExtension: "3mf") ?? .data]
        panel.canCreateDirectories = true
        let name = model.project?.name ?? "Projekt"
        panel.nameFieldStringValue = platten.isEmpty ? "\(name)-druck.3mf" : "\(name)-druck-platte-\(platten[0]).3mf"
        if let p = model.project?.path {
            let out = p.appendingPathComponent("output", isDirectory: true)
            try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
            panel.directoryURL = out
        }
        let senden: (NSApplication.ModalResponse) -> Void = { r in
            guard r == .OK, let url = panel.url else { return }
            model.druckActions?.druckExportieren(platten: platten, nach: url)
        }
        if let fenster = NSApp.keyWindow {
            panel.beginSheetModal(for: fenster, completionHandler: senden)
        } else {
            senden(panel.runModal())
        }
    }

    // MARK: Bänder (Änderung, Export, Fehler)

    @ViewBuilder
    private var baender: some View {
        VStack(spacing: 6) {
            if let a = druck.aenderung { DruckAenderungBand(aenderung: a) { druck.aenderungVerwerfen() } }
            DruckExportBand(model: model, druck: druck)
            if let f = druck.fehler {
                DruckBand(symbol: "xmark.octagon.fill", farbe: .red, titel: f, text: nil,
                          schliessen: { druck.fehlerVerwerfen() })
            }
            if druck.vorschau?.regler == true {
                DruckBand(symbol: "slider.horizontal.3", farbe: .secondary, titel: "Lauf mit Reglerwerten",
                          text: "Nur geschätzt, nichts gespeichert, kein Slicer.", schliessen: nil)
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, hatBand ? 8 : 0)
        .animation(.snappy(duration: 0.3), value: druck.aenderung)
        .animation(.snappy(duration: 0.3), value: druck.export)
        .animation(.snappy(duration: 0.3), value: druck.fehler)
    }

    private var hatBand: Bool {
        druck.aenderung != nil || druck.export != .bereit || druck.fehler != nil || druck.vorschau?.regler == true
    }

    // MARK: Inhalt

    @ViewBuilder
    private var inhalt: some View {
        if let v = druck.vorschau, !v.istLeer {
            GeometryReader { geo in
                let breit = geo.size.width >= 1040
                let mitPlatten = geo.size.width >= 640
                HStack(spacing: 0) {
                    if mitPlatten {
                        ScrollView {
                            DruckPlattenBereich(model: model, vorschau: v, farben: farben(v), nummern: nummern(v))
                                .padding(12)
                        }
                        .frame(width: plattenBreite(v, gesamt: geo.size.width - (breit ? 361 : 0)))
                        Divider()
                    }
                    DruckListe(model: model, druck: druck, vorschau: v, farben: farben(v), nummern: nummern(v),
                               detailAlsPopover: !breit)
                        .frame(minWidth: 300, maxWidth: .infinity)
                    if breit {
                        Divider()
                        ScrollView {
                            detail(v).frame(width: 360)
                        }
                        .frame(width: 360)
                    }
                }
                .animation(.snappy(duration: 0.25), value: ui.nebeneinander)
            }
        } else {
            leer
        }
    }

    @ViewBuilder
    private func detail(_ v: Druckvorschau) -> some View {
        if let id = ui.auswahl, let g = v.gruppe(id) {
            DruckGruppeDetail(model: model, druck: druck, gruppe: g, vorschau: v,
                              farbe: farben(v)[g.material ?? ""] ?? DruckFarben.palette[0], nummer: nummern(v)[id])
                .id(id)
                .transition(.opacity)
        } else {
            DruckUeberblick(vorschau: v)
        }
    }

    @ViewBuilder
    private var leer: some View {
        if let v = druck.vorschau, v.istLeer {
            ContentUnavailableView {
                Label("Keine Druckteile im Modell", systemImage: "printer")
            } description: {
                Text(v.slicer.meldung ?? "Mit lager.druckteil(…) gekennzeichnete Teile erscheinen hier mit Filament, Zeit, Platten und Kosten.")
            }
        } else if druck.nichtUnterstuetzt {
            ContentUnavailableView {
                Label("Druckvorschau nicht verfügbar", systemImage: "printer")
            } description: {
                Text("Dieser Kernel kennt die Druckvorschau noch nicht.")
            }
        } else {
            ContentUnavailableView {
                Label("Noch keine Druckvorschau", systemImage: "printer")
            } description: {
                Text("Sie entsteht nach jedem Lauf mit Druckteilen (lager.druckteil(…)).")
            } actions: {
                Button("Vorschau holen") { model.druckActions?.druckvorschauAnfordern() }
                    .disabled(model.druckActions == nil || model.project == nil)
            }
        }
    }

    private func farben(_ v: Druckvorschau) -> [String: Color] { DruckFarben.material(v, parts: model.parts) }

    /// Plattenspalte: eine Platte etwa 300 breit; nebeneinander so breit, dass zwei bis drei Platten nebeneinander
    /// passen, höchstens die Hälfte.
    private func plattenBreite(_ v: Druckvorschau, gesamt: CGFloat) -> CGFloat {
        if ui.nebeneinander && v.platten.count > 1 {
            let wunsch = CGFloat(min(3, v.platten.count)) * 200 + 34
            return max(280, min(wunsch, gesamt * 0.5))
        }
        return min(340, max(260, gesamt * 0.3))
    }

    private func nummern(_ v: Druckvorschau) -> [String: Int] {
        Dictionary(uniqueKeysWithValues: v.teile.enumerated().map { ($1.gruppe, $0 + 1) })
    }
}

extension DruckExportZustand {
    var laeuftGerade: Bool { if case .laeuft = self { return true } else { return false } }
}

// MARK: - Liste

/// Mitte: Filament je Material, Platten, Teile mit Empfehlung, Hinweise.
struct DruckListe: View {
    @ObservedObject var model: AppModel
    @ObservedObject var druck: DruckStore
    @ObservedObject private var ui = DruckUI.shared
    var vorschau: Druckvorschau
    var farben: [String: Color]
    var nummern: [String: Int]
    /// Schmal: Einstellungen der gewählten Gruppe als Popover an ihrer Zeile.
    var detailAlsPopover = false

    var body: some View {
        ScrollViewReader { leser in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                    Section { filament } header: { kopf("Filament", rechts: DruckFormat.gramm(vorschau.summe.gramm)) }
                    Section { platten } header: {
                        kopf("Platten", rechts: KevFormat.count(vorschau.platten.count, one: "Platte", many: "Platten"))
                    }
                    Section { teile } header: {
                        kopf("Teile", rechts: KevFormat.count(vorschau.stueck, one: "Stück", many: "Stück")
                            + " in " + KevFormat.count(vorschau.teile.count, one: "Gruppe", many: "Gruppen"))
                    }
                    let alle = vorschau.alleHinweise
                    if !alle.isEmpty {
                        Section { hinweise(alle) } header: {
                            kopf("Hinweise", rechts: hinweisZahl(alle.map(\.hinweis)))
                        }
                    }
                }
                .padding(.bottom, 10)
            }
            .onChange(of: ui.auswahl) { _, id in
                guard let id else { return }
                withAnimation(.snappy(duration: 0.25)) { leser.scrollTo("gruppe-" + id, anchor: .center) }
            }
        }
    }

    private func kopf(_ titel: String, rechts: String) -> some View {
        HStack {
            Text(titel.uppercased()).font(.caption.weight(.semibold)).kerning(0.4)
            Spacer()
            Text(rechts).font(.caption.monospacedDigit())
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .padding(.top, 10)
        .padding(.bottom, 4)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.97))
    }

    private func hinweisZahl(_ h: [DruckpraxisHinweis]) -> String {
        let w = h.filter { $0.schwere == .warnung }.count, f = h.filter { $0.schwere == .fehler }.count
        var t: [String] = []
        if f > 0 { t.append(KevFormat.count(f, one: "Fehler", many: "Fehler")) }
        if w > 0 { t.append(KevFormat.count(w, one: "Warnung", many: "Warnungen")) }
        return t.isEmpty ? KevFormat.count(h.count, one: "Hinweis", many: "Hinweise") : t.joined(separator: ", ")
    }

    // MARK: Filament

    private var filament: some View {
        VStack(spacing: 0) {
            ForEach(vorschau.summe.material) { m in
                HStack(spacing: 8) {
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill((farben[m.material] ?? .gray).gradient)
                        .frame(width: 12, height: 12)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(m.name).fontWeight(.semibold)
                        Text([m.filament, m.preisKg.map { "\(DruckFormat.euro($0))/kg" }, m.preisStand.map { "Stand \($0)" }]
                            .compactMap { $0 }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    zahlen([DruckFormat.gramm(m.g), m.m.map(DruckFormat.meter) ?? "–", m.kosten.map(DruckFormat.euro) ?? "–"],
                           breiten: [56, 62, 58])
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 5)
                .help(m.stand.beschreibung)
            }
            if vorschau.summe.material.count > 1 || vorschau.summe.kostenStrom != nil {
                Divider().padding(.horizontal, 14)
                HStack(spacing: 8) {
                    Text("Summe").fontWeight(.semibold)
                    if let s = vorschau.summe.kostenStrom {
                        Text("inkl. Strom \(DruckFormat.euro(s))"
                             + (vorschau.summe.kostenRisiko.map { ", Fehldruck \(DruckFormat.euro($0))" } ?? ""))
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    zahlen([DruckFormat.gramm(vorschau.summe.gramm), vorschau.summe.meter.map(DruckFormat.meter) ?? "–",
                            vorschau.summe.kosten.map(DruckFormat.euro) ?? "–"], breiten: [56, 62, 58], fett: true)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 5)
            }
        }
        .font(.callout)
    }

    private func zahlen(_ werte: [String], breiten: [CGFloat], fett: Bool = false) -> some View {
        HStack(spacing: 6) {
            ForEach(Array(werte.enumerated()), id: \.offset) { i, w in
                Text(w)
                    .fontWeight(fett ? .semibold : .regular)
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .lineLimit(1)
                    .frame(minWidth: breiten[min(i, breiten.count - 1)], alignment: .trailing)
            }
        }
        .animation(.snappy(duration: 0.35), value: werte)
    }

    // MARK: Platten

    private var platten: some View {
        VStack(spacing: 0) {
            ForEach(vorschau.platten) { p in
                Button {
                    ui.zeigePlatte(p.nr)
                } label: {
                    HStack(spacing: 8) {
                        Text("\(p.nr)")
                            .font(.caption.weight(.bold).monospacedDigit())
                            .frame(width: 18, height: 18)
                            .background(RoundedRectangle(cornerRadius: 4, style: .continuous)
                                .fill(ui.platte == p.nr ? Color.accentColor.opacity(0.2) : Color.primary.opacity(0.07)))
                        VStack(alignment: .leading, spacing: 0) {
                            Text(p.gruppen.map { "\($0.anzahl) × \(vorschau.gruppe($0.gruppe)?.kurzname ?? $0.gruppe)" }
                                .joined(separator: ", "))
                                .lineLimit(1)
                            Text([p.material.map { m in vorschau.summe.material.first { $0.material == m.material }?.name
                                ?? m.material.uppercased() }.joined(separator: ", "),
                                  "\(DruckFormat.prozent(DruckPlattenGeometrie.auslastung(p, bett: vorschau.bett))) belegt",
                                  p.stand.titel].joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Spacer(minLength: 8)
                        zahlen([DruckFormat.gramm(p.gramm), DruckFormat.zeit(p.zeitS)], breiten: [56, 84])
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 14)
                .padding(.vertical, 5)
            }
            if vorschau.summe.wechselS > 0 {
                HStack {
                    Text("Plattenwechsel").foregroundStyle(.secondary)
                    Spacer()
                    Text("+ \(DruckFormat.zeit(vorschau.summe.wechselS))").monospacedDigit().foregroundStyle(.secondary)
                }
                .font(.caption)
                .padding(.horizontal, 14)
                .padding(.vertical, 3)
            }
        }
        .font(.callout)
    }

    // MARK: Teile

    private var teile: some View {
        VStack(spacing: 2) {
            ForEach(vorschau.teile) { g in
                DruckGruppenZeile(model: model, druck: druck, gruppe: g, vorschau: vorschau,
                                  farbe: farben[g.material ?? ""] ?? DruckFarben.palette[0], nummer: nummern[g.gruppe],
                                  gewaehlt: ui.auswahl == g.gruppe,
                                  imModell: !Set(model.selectedPartIDs).isDisjoint(with: g.teile),
                                  detailAlsPopover: detailAlsPopover)
                    .id("gruppe-" + g.gruppe)
            }
        }
        .padding(.horizontal, 6)
    }

    // MARK: Hinweise

    private func hinweise(_ alle: [(hinweis: DruckpraxisHinweis, gruppen: [String])]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(alle.enumerated()), id: \.offset) { _, h in
                DruckHinweisZeile(hinweis: h.hinweis,
                                  betrifft: h.gruppen.compactMap { vorschau.gruppe($0)?.kurzname })
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 4)
    }
}

/// Eine Gruppe in der Liste: Ampel, Nummer, Name, Anzahl, Zweck, Einstellungen kurz, Zeit und Gewicht.
struct DruckGruppenZeile: View {
    @ObservedObject var model: AppModel
    @ObservedObject var druck: DruckStore
    var gruppe: DruckGruppe
    var vorschau: Druckvorschau
    var farbe: Color
    var nummer: Int?
    var gewaehlt: Bool
    /// Teile der Gruppe sind im 3D-Bereich ausgewählt.
    var imModell: Bool
    var detailAlsPopover = false
    @State private var schwebt = false
    @State private var detailOffen = false

    var body: some View {
        HStack(alignment: .center, spacing: 9) {
            DruckAmpelPunkt(ampel: gruppe.ampel)
            if let nummer {
                Text("\(nummer)")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .frame(width: 17, height: 17)
                    .background(Circle().fill(farbe))
            }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(gruppe.kurzname).fontWeight(.medium).lineLimit(1)
                    if gruppe.anzahl > 1 {
                        Text("× \(gruppe.anzahl)").monospacedDigit().foregroundStyle(.secondary)
                    }
                    DruckZweckMarke(zweck: gruppe.zweck, geschaetzt: gruppe.zweckGeschaetzt)
                    if gruppe.hatVorgaben {
                        Image(systemName: "pin.fill")
                            .font(.system(size: 9))
                            .foregroundStyle(Color.kevAkzent)
                            .help(DruckFormat.vorgaben(gruppe.vorgaben).joined(separator: "\n"))
                    }
                    if druck.wartet(.gruppe(gruppe.gruppe)) { ProgressView().controlSize(.mini) }
                }
                Text(([gruppe.einstellungen.schichtMM.map(DruckFormat.schicht)] + [DruckFormat.kurz(gruppe.einstellungen)])
                    .compactMap { t in t.flatMap { $0.isEmpty ? nil : $0 } }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(DruckFormat.zeit(gruppe.zeitS)).monospacedDigit().contentTransition(.numericText())
                HStack(spacing: 4) {
                    if gruppe.stand == .slicer {
                        Image(systemName: "checkmark.seal.fill").font(.system(size: 8)).foregroundStyle(.green)
                            .help("von Bambu Studio gerechnet")
                    }
                    Text(DruckFormat.gramm(gruppe.g)).monospacedDigit().contentTransition(.numericText())
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            .animation(.snappy(duration: 0.35), value: gruppe.zeitS)
            if detailAlsPopover && gewaehlt {
                Button {
                    detailOffen.toggle()
                } label: {
                    Image(systemName: "slider.horizontal.3")
                        .font(.system(size: 13, weight: .medium))
                        .frame(width: 22, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Empfehlung und Einstellungen")
                .popover(isPresented: $detailOffen, arrowEdge: .trailing) {
                    ScrollView {
                        DruckGruppeDetail(model: model, druck: druck, gruppe: gruppe, vorschau: vorschau, farbe: farbe,
                                          nummer: nummer)
                            .frame(width: 360)
                    }
                    .frame(width: 360, height: 560)
                }
                .transition(.opacity)
            }
        }
        .font(.callout)
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(gewaehlt ? Color.accentColor.opacity(0.16) : schwebt ? Color.primary.opacity(0.05) : .clear)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .strokeBorder(imModell && !gewaehlt ? Color.accentColor.opacity(0.5) : .clear, lineWidth: 1)
        )
        .contentShape(Rectangle())
        .onHover { schwebt = $0 }
        .onTapGesture(count: 2) { DruckUI.shared.waehle(gruppe, vorschau: vorschau, model: model, einpassen: true) }
        .onTapGesture { DruckUI.shared.waehle(gruppe, vorschau: vorschau, model: model) }
        .help(hilfe)
        .contextMenu {
            Button("Im 3D zeigen") { DruckUI.shared.waehle(gruppe, vorschau: vorschau, model: model, einpassen: true) }
            Button("Teile isolieren") { model.actions?.isolate(gruppe.teile) }
            if gruppe.hatVorgaben {
                Divider()
                Button("Alle Vorgaben zurücksetzen") {
                    model.druckActions?.druckZuruecksetzen(.gruppe(gruppe.gruppe), schluessel: [])
                }
            }
            Divider()
            Button("Teilenamen kopieren") { copyToPasteboard(gruppe.teile.joined(separator: "\n")) }
        }
    }

    private var hilfe: String {
        var t = [gruppe.name]
        t += gruppe.begruendung
        t += gruppe.hinweise.map { "\($0.schwere.titel): \($0.text)" }
        if gruppe.teile.count > 1 { t.append(gruppe.teile.prefix(6).joined(separator: "\n")) }
        return t.joined(separator: "\n")
    }
}

// MARK: - Überblick (rechts ohne Auswahl)

struct DruckUeberblick: View {
    var vorschau: Druckvorschau

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Überblick").font(.title3.weight(.semibold))
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                reihe("Drucker", vorschau.drucker)
                reihe("Druck", DruckFormat.zeit(vorschau.summe.zeitS))
                if vorschau.summe.wechselS > 0 { reihe("Plattenwechsel", DruckFormat.zeit(vorschau.summe.wechselS)) }
                reihe("Gesamt", DruckFormat.zeit(vorschau.summe.zeitMitWechselS))
                Divider().gridCellColumns(2)
                if let f = vorschau.summe.kostenFilament { reihe("Filament", DruckFormat.euro(f)) }
                if let s = vorschau.summe.kostenStrom { reihe("Strom", DruckFormat.euro(s)) }
                if let r = vorschau.summe.kostenRisiko { reihe("Aufschlag Fehldruck", DruckFormat.euro(r)) }
                if let k = vorschau.summe.kosten { reihe("Kosten", DruckFormat.euro(k), fett: true) }
                if let p = vorschau.projekt {
                    Divider().gridCellColumns(2)
                    if let s = p.strompreisKwh { reihe("Strompreis", "\(DruckFormat.euro(s))/kWh") }
                    if let l = p.leistungW { reihe("Leistung", "\(KevFormat.compact(l, maxDigits: 0)) W") }
                    if let w = p.plattenwechselS { reihe("Je Plattenwechsel", DruckFormat.zeit(w)) }
                    if let pl = p.platte { reihe("Druckplatte", pl) }
                }
            }
            .font(.callout)
            VStack(alignment: .leading, spacing: 4) {
                Text("Slicer").font(.subheadline.weight(.semibold))
                HStack(spacing: 6) {
                    DruckStandMarke(vorschau: vorschau)
                    if let v = vorschau.slicer.version { Text("Bambu Studio \(v)").foregroundStyle(.secondary) }
                }
                if let m = vorschau.slicer.meldung { Text(m).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
                if let ms = vorschau.ms {
                    Text("Schätzung in \(KevFormat.compact(ms, maxDigits: 0)) ms").font(.caption).foregroundStyle(.tertiary)
                }
            }
            .font(.callout)
            Label("Ein Teil anklicken, um Empfehlung und Einstellungen zu sehen.", systemImage: "hand.point.up.left")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func reihe(_ titel: String, _ wert: String, fett: Bool = false) -> some View {
        GridRow {
            Text(titel).foregroundStyle(.secondary)
            Text(wert).monospacedDigit().fontWeight(fett ? .semibold : .regular).gridColumnAlignment(.trailing)
        }
    }
}

// MARK: - Bänder

/// Ein Hinweisband über dem Inhalt.
struct DruckBand<Knopf: View>: View {
    var symbol: String
    var farbe: Color
    var titel: String
    var text: String?
    var schliessen: (() -> Void)?
    @ViewBuilder var knoepfe: Knopf

    init(symbol: String, farbe: Color, titel: String, text: String?, schliessen: (() -> Void)?,
         @ViewBuilder knoepfe: () -> Knopf)
    {
        self.symbol = symbol
        self.farbe = farbe
        self.titel = titel
        self.text = text
        self.schliessen = schliessen
        self.knoepfe = knoepfe()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(farbe).font(.system(size: 14, weight: .semibold))
            VStack(alignment: .leading, spacing: 1) {
                Text(titel).fontWeight(.semibold).lineLimit(2)
                if let text { Text(text).foregroundStyle(.secondary).lineLimit(3).textSelection(.enabled) }
            }
            Spacer(minLength: 8)
            knoepfe.controlSize(.small)
            if let schliessen {
                Button(action: schliessen) {
                    Image(systemName: "xmark").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        .frame(width: 16, height: 16).contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .help("Schließen")
            }
        }
        .font(.callout)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(farbe.opacity(0.3)))
        .transition(.move(edge: .top).combined(with: .opacity))
    }
}

extension DruckBand where Knopf == EmptyView {
    init(symbol: String, farbe: Color, titel: String, text: String?, schliessen: (() -> Void)?) {
        self.init(symbol: symbol, farbe: farbe, titel: titel, text: text, schliessen: schliessen) { EmptyView() }
    }
}

/// „Bambu Studio hat nachgerechnet“: was sich gegenüber der Schätzung wie stark geändert hat.
struct DruckAenderungBand: View {
    var aenderung: DruckAenderung
    var schliessen: () -> Void

    var body: some View {
        DruckBand(symbol: "sparkles", farbe: .green, titel: "\(aenderung.titel): \(aenderung.urteil.lowercasedFirst)",
                  text: text, schliessen: schliessen)
            .task(id: aenderung.id) {
                try? await Task.sleep(for: .seconds(30))
                schliessen()
            }
    }

    private var text: String {
        var zeilen = aenderung.werte.map(\.zeile)
        if !aenderung.teile.isEmpty {
            zeilen.append("Am meisten: " + aenderung.teile.map { "\($0.name) \(DruckFormat.aenderung($0.relativ))" }
                .joined(separator: ", "))
        }
        return zeilen.joined(separator: " · ")
    }
}

/// Export läuft, fertig (mit „In Bambu Studio öffnen“) oder gescheitert.
struct DruckExportBand: View {
    @ObservedObject var model: AppModel
    @ObservedObject var druck: DruckStore

    var body: some View {
        switch druck.export {
        case .bereit:
            EmptyView()
        case .laeuft(let ziel):
            DruckBand(symbol: "square.and.arrow.down.on.square", farbe: .secondary,
                      titel: "Platten werden als 3MF gesichert …",
                      text: (ziel?.lastPathComponent).map { $0 + " · Bambu Studio ordnet an und prüft" }, schliessen: nil) {
                ProgressView().controlSize(.small)
            }
        case .fertig(let e) where e.dateien.count > 1:
            DruckBand(symbol: "checkmark.circle.fill", farbe: .green,
                      titel: "\(e.dateien.count) Dateien als 3MF gesichert, je Material eine"
                          + (e.geprueft == true ? ", in Bambu Studio geprüft" : ""),
                      text: e.hinweise.isEmpty ? nil : e.hinweise.joined(separator: " · "),
                      schliessen: { druck.exportHinweisVerwerfen() })
            VStack(spacing: 4) {
                ForEach(e.dateien) { d in DruckExportDateiZeile(model: model, datei: d) }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            .transition(.move(edge: .top).combined(with: .opacity))
        case .fertig(let e):
            DruckBand(symbol: "checkmark.circle.fill", farbe: .green,
                      titel: (e.platten.isEmpty ? "Platten" : KevFormat.count(e.platten.count, one: "Platte", many: "Platten"))
                          + " als 3MF gesichert" + (e.geprueft == true ? ", in Bambu Studio geprüft" : ""),
                      text: ([e.pfad?.lastPathComponent].compactMap { $0 } + e.hinweise).joined(separator: " · "),
                      schliessen: { druck.exportHinweisVerwerfen() }) {
                if let pfad = e.pfad {
                    DruckBambuKnoepfe(model: model, pfad: pfad)
                }
            }
        case .fehler(let f):
            DruckBand(symbol: "xmark.octagon.fill", farbe: .red, titel: "3MF-Export fehlgeschlagen", text: f,
                      schliessen: { druck.exportHinweisVerwerfen() })
        }
    }
}

extension String {
    var lowercasedFirst: String { prefix(1).lowercased() + dropFirst() }
}

/// „In Bambu Studio öffnen“ (nur auf Klick) und „Im Finder zeigen“ für eine 3MF-Datei.
struct DruckBambuKnoepfe: View {
    @ObservedObject var model: AppModel
    var pfad: URL
    var kompakt = false

    var body: some View {
        Button {
            model.druckActions?.druckInBambuStudioOeffnen(pfad)
        } label: {
            Label("In Bambu Studio öffnen", systemImage: "arrow.up.forward.app")
        }
        .buttonStyle(.borderedProminent)
        .disabled(DruckStore.bambuStudio == nil)
        .help(DruckStore.bambuStudio == nil ? "Bambu Studio ist nicht unter /Applications installiert"
              : "\(pfad.lastPathComponent) in Bambu Studio öffnen")
        Button {
            NSWorkspace.shared.activateFileViewerSelecting([pfad])
        } label: {
            if kompakt { Image(systemName: "folder") } else { Text("Im Finder zeigen") }
        }
        .help("Im Finder zeigen")
    }
}

/// Eine von mehreren 3MF-Dateien (je Material): Farbe, Material, Platten, Filamentprofil, Datei, Knöpfe.
struct DruckExportDateiZeile: View {
    @ObservedObject var model: AppModel
    var datei: DruckExportDatei

    var body: some View {
        let v = model.druck.vorschau
        let farbe = DruckFarben.material(v, parts: model.parts)[datei.material ?? ""] ?? .gray
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 3, style: .continuous).fill(farbe.gradient).frame(width: 12, height: 12)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(datei.material.map { m in v?.summe.material.first { $0.material == m }?.name ?? m.uppercased() }
                         ?? "3MF").fontWeight(.semibold)
                    if !datei.platten.isEmpty {
                        Text(datei.platten.count == 1 ? "Platte \(datei.platten[0])"
                             : "Platten " + datei.platten.map(String.init).joined(separator: ", "))
                            .foregroundStyle(.secondary)
                    }
                }
                Text([datei.pfad.lastPathComponent, datei.filament].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 8)
            DruckBambuKnoepfe(model: model, pfad: datei.pfad, kompakt: true)
                .controlSize(.small)
        }
        .font(.callout)
        .padding(.vertical, 2)
    }
}
