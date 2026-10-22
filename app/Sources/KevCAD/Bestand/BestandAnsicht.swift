import AppKit
import KevCADCore
import SwiftUI

/// Abschnitt „Bestand“ im Bereich „Material“ (BESTAND.md, Abschnitt „App“): links die Lagerteile des Projektbestands
/// und die noch nicht erfassten Lagerteile der Stückliste, nach Gruppen wie die Stückliste, rechts ganze Stangen bzw.
/// Platten, Reste und Stückgut des ausgewählten Lagerteils mit schnellem Erfassen. Jede Änderung geht als BESTAND_SAVE an
/// den Kernel, der sie bucht; Buchungsprotokoll mit „Rückgängig“, Einstellungen und „Gebaut …“ sitzen im Kopf.
struct BestandAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    @ObservedObject private var ui = BestandUI.shared
    @State private var zeigeBuchungen = false
    @State private var zeigeEinstellungen = false

    private var bestand: Bestand? { model.bestandZustand.bestand }

    /// Posten im Bestand: Gruppen wie in der Stückliste (Stangen und Profile, Platten, Normteile), darin nach Namen.
    private var posten: [BestandPosten] {
        (bestand?.posten ?? []).sorted {
            let ga = gruppe($0), gb = gruppe($1)
            if ga != gb { return ga < gb }
            return model.lagerteilName($0.id).localizedStandardCompare(model.lagerteilName($1.id)) == .orderedAscending
        }
    }

    private func gruppe(_ p: BestandPosten) -> MaterialGruppe {
        switch p.form {
        case .stange: return .stangen
        case .platte: return .platten
        case .stueckgut: return .normteile
        }
    }

    /// Suche im Bereich „Material“ (Name, id).
    private func passt(_ id: String) -> Bool {
        passtText(model.lagerteilName(id) + " " + id)
    }

    private func passtText(_ text: String) -> Bool {
        let q = material.suche.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return true }
        return text.lowercased().contains(q)
    }

    /// Lagerteile der Stückliste, die noch nicht im Bestand stehen.
    private var nichtErfasst: [String] {
        var seen = Set(bestand?.posten.map(\.id) ?? [])
        var out: [String] = []
        // Stangenware, Platten, Stückgut; Zukaufteile, Kameras und Objektive als Stückgut (Strang „Feinschliff 2“)
        for line in model.bom?.lines ?? [] where !line.eigenteil && !line.druckteil && CatalogSchema.art(line.art).imBestand {
            guard let id = line.stockID, seen.insert(id).inserted else { continue }
            out.append(id)
        }
        return out
    }

    /// Filament (Strang „Bestand Stufe 2“): je Material eine Zeile; führt das Projekt kein Filament, aber das Modell hat
    /// Druckteile, eine Hinweiszeile („filament:“).
    private var filamentIDs: [String] {
        let materialien = model.filamentMaterialienImBestand
        if !materialien.isEmpty { return materialien.map(FilamentAuswahl.id) }
        let druck = (model.bom?.lines ?? []).contains { $0.druckteil && !$0.gedruckt }
        return bestand?.fuehrtFilament == false && druck ? [FilamentAuswahl.praefix] : []
    }

    var body: some View {
        VStack(spacing: 0) {
            kopf
            Divider()
            inhalt
        }
        .onAppear {
            if model.catalog == nil { model.catalogActions?.requestCatalog(query: nil, art: nil) }
            if !model.bestandZustand.empfangen { model.bestandActions?.requestBestand() }
            waehleErstes()
        }
        .onChange(of: model.bestandZustand.bestand?.posten.map(\.id)) { _, _ in waehleErstes() }
        .onChange(of: filamentIDs) { _, _ in waehleErstes() }
        .onChange(of: ui.auswahl) { _, id in teileZeigen(id) }
        .onChange(of: model.selectedPartIDs) { _, ids in auswahlAus3D(ids) }
    }

    /// Auswahl wirkt in den 3D-Bereich: die Teile dieses Lagerteils auswählen.
    private func teileZeigen(_ id: String?) {
        guard let id else { return }
        let teile = (model.bom?.lines ?? []).filter { $0.stockID == id }.flatMap(\.teile)
        let jetzt = Set(model.selectedPartIDs)
        // Schon ein Teil dieses Lagerteils gewählt (etwa im 3D-Bereich): die Auswahl dort nicht ausweiten
        guard !teile.isEmpty, jetzt.isEmpty || !jetzt.isSubset(of: Set(teile)) else { return }
        model.actions?.select(teile)
    }

    /// Auswahl aus dem 3D-Bereich oder dem Teilebaum: das Lagerteil des gewählten Teils zeigen.
    private func auswahlAus3D(_ ids: [String]) {
        guard let teil = ids.first, let line = model.bom?.line(containing: teil), let sid = line.stockID,
              sid != ui.auswahl, (posten.map(\.id) + nichtErfasst).contains(sid)
        else { return }
        ui.auswahl = sid
    }

    /// Ohne gültige Auswahl das erste Lagerteil zeigen (der Bestand kommt oft erst nach dem Erscheinen).
    private func waehleErstes() {
        let ids = posten.map(\.id) + filamentIDs + nichtErfasst
        if ui.auswahl.map({ !ids.contains($0) }) ?? true { ui.auswahl = ids.first }
    }

    // MARK: Kopf

    private var kopf: some View {
        MaterialAbschnittKopf(titel: MaterialAbschnitt.bestand.titel, symbol: MaterialAbschnitt.bestand.symbol,
                              zeile: zusammenfassung.isEmpty ? "Material, das du für dieses Projekt hast" : zusammenfassung) {
            if model.bestandZustand.aktivitaet == .saving {
                ProgressView().controlSize(.small)
                Text("Wird gebucht …").foregroundStyle(.secondary)
            }
            Button {
                ui.erfassen = ErfassenAnfrage(stockID: nil)
            } label: {
                Label("Lagerteil aufnehmen …", systemImage: "plus")
            }
            .disabled(!bereit)
            .help("Lagerteil aus dem Katalog in den Bestand dieses Projekts aufnehmen")
            Button {
                ui.spule = SpulenAnfrage(material: FilamentAuswahl.material(ui.auswahl).flatMap { $0.isEmpty ? nil : $0 })
            } label: {
                Label("Spule aufnehmen …", systemImage: "printer")
            }
            .disabled(!bereit)
            .help("Filamentspule in den Bestand dieses Projekts aufnehmen")
            Button {
                zeigeBuchungen.toggle()
            } label: {
                Label("Buchungen", systemImage: "clock.arrow.circlepath")
            }
            .help("Buchungsprotokoll: jede Änderung am Bestand, mit „Rückgängig“")
            .popover(isPresented: $zeigeBuchungen, arrowEdge: .bottom) {
                BuchungenListe(model: model)
            }
            Button {
                zeigeEinstellungen.toggle()
            } label: {
                Label("Einstellungen", systemImage: "gearshape")
                    .labelStyle(.iconOnly)
            }
            .disabled(bestand == nil)
            .help("Mindestrest und Sägeblatt")
            .popover(isPresented: $zeigeEinstellungen, arrowEdge: .bottom) {
                BestandEinstellungenForm(model: model, einstellungen: bestand?.einstellungen ?? .standard)
            }
            Button {
                ui.zeigeGebaut()
            } label: {
                Label("Gebaut …", systemImage: "hammer")
            }
            .disabled(model.bestandActions == nil || model.bestandZustand.zuschnitt == nil || model.laufAktiv)
            .help("Bestand abbuchen: was der Zuschnitt verplant, geht weg; neue Reste kommen dazu")
        }
        .help(model.bestandZustand.datei.map { "Bestand dieses Projekts: \($0)" } ?? "")
    }

    private var bereit: Bool { model.bestandActions != nil && bestand != nil }

    private var zusammenfassung: String {
        guard let b = bestand else { return "" }
        let reste = b.posten.reduce(0) { $0 + $1.reste.count }
        var t = KevFormat.count(b.posten.count, one: "Lagerteil", many: "Lagerteile")
        if reste > 0 { t += " · " + KevFormat.count(reste, one: "Rest", many: "Reste") }
        let spulen = b.spulen.count
        if spulen > 0 { t += " · " + KevFormat.count(spulen, one: "Spule", many: "Spulen") }
        return t
    }

    // MARK: Inhalt

    @ViewBuilder
    private var inhalt: some View {
        if model.bestandActions == nil {
            ContentUnavailableView(
                "Bestand nicht verfügbar", systemImage: "shippingbox",
                description: Text("Der Bestand kommt vom Kernel; im Demomodus gibt es ihn nicht."))
        } else if !model.bestandZustand.empfangen {
            ContentUnavailableView {
                Label("Noch kein Bestand geladen", systemImage: "shippingbox")
            } description: {
                Text("Der Kernel hat noch keinen Bestand geschickt. Ältere Kernel-Versionen kennen den Bestand nicht.")
            } actions: {
                Button("Erneut anfragen") { model.bestandActions?.requestBestand() }
            }
        } else if let fehler = model.bestandZustand.fehler {
            ContentUnavailableView {
                Label("bestand.json ist nicht lesbar", systemImage: "exclamationmark.triangle")
            } description: {
                Text(fehler)
            } actions: {
                if let datei = model.bestandZustand.datei {
                    Button("Im Finder zeigen") {
                        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: datei)])
                    }
                }
                Button("Erneut laden") { model.bestandActions?.requestBestand() }
            }
        } else if bestand == nil {
            ContentUnavailableView(
                "Kein Projektbestand", systemImage: "shippingbox",
                description: Text("Der Bestand gehört zum offenen Projekt (bestand.json im Projektordner)."))
        } else {
            HStack(spacing: 0) {
                liste
                    .frame(width: 320)
                Divider()
                detail
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var liste: some View {
        List(selection: $ui.auswahl) {
            let gefiltert = posten.filter { passt($0.id) }
            ForEach(MaterialGruppe.allCases.filter { g in gefiltert.contains { gruppe($0) == g } }) { g in
                Section(g.titel) {
                    ForEach(gefiltert.filter { gruppe($0) == g }) { p in
                        PostenZeile(model: model, id: p.id, text: p.zusammenfassung, leer: p.leer)
                            .tag(p.id)
                            .contextMenu { menu(p) }
                    }
                }
            }
            let filament = filamentIDs.filter { id in
                guard let m = FilamentAuswahl.material(id), !m.isEmpty else { return true }
                return passt(id) || passtText(model.filamentName(m) + " filament")
            }
            if !filament.isEmpty {
                let kaufen = Set(model.materialDaten.lagerEinkauf.map(\.position.id))
                Section("Filament") {
                    ForEach(filament, id: \.self) { id in
                        let m = FilamentAuswahl.material(id) ?? ""
                        Group {
                            if m.isEmpty {
                                HStack(spacing: 9) {
                                    Image(systemName: "printer").foregroundStyle(.secondary).frame(width: 24)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text("Filament").fontWeight(.medium)
                                        Text("nicht geführt").font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                .padding(.vertical, 2)
                            } else {
                                FilamentZeile(model: model, material: m, kaufen: kaufen.contains(m))
                            }
                        }
                        .tag(id)
                        .contextMenu {
                            Button("Spule aufnehmen …") { ui.spule = SpulenAnfrage(material: m.isEmpty ? nil : m) }
                        }
                    }
                }
            }
            let fehlen = nichtErfasst.filter(passt)
            if !fehlen.isEmpty {
                Section("Aus der Stückliste, nicht erfasst") {
                    ForEach(fehlen, id: \.self) { id in
                        PostenZeile(model: model, id: id, text: "nicht im Bestand", leer: true)
                            .tag(id)
                            .contextMenu {
                                Button("In den Bestand aufnehmen …") { ui.erfassen = ErfassenAnfrage(stockID: id) }
                            }
                    }
                }
            }
        }
        .listStyle(.inset)
        .overlay {
            if posten.isEmpty && nichtErfasst.isEmpty && filamentIDs.isEmpty {
                ContentUnavailableView {
                    Label("Noch nichts im Bestand", systemImage: "shippingbox")
                } description: {
                    Text("Trage ein, was du für dieses Projekt schon hast: ganze Stangen, Reste, Platten, Schrauben.")
                } actions: {
                    Button("Lagerteil aufnehmen …") { ui.erfassen = ErfassenAnfrage(stockID: nil) }
                }
            }
        }
    }

    @ViewBuilder
    private func menu(_ p: BestandPosten) -> some View {
        if p.form != .stueckgut {
            Button("+1 \(p.form.einheit)") { PostenAenderung(model: model, posten: p).ganze(+1) }
            Button("−1 \(p.form.einheit)") { PostenAenderung(model: model, posten: p).ganze(-1) }
                .disabled(p.ganzeAnzahl == 0)
            Button("Rest hinzufügen …") { ui.erfassen = ErfassenAnfrage(stockID: p.id, nurReste: true) }
        } else {
            Button("Stückgut hinzufügen …") { ui.erfassen = ErfassenAnfrage(stockID: p.id) }
        }
        Divider()
        Button("Im Lagerkatalog zeigen") { session.showCatalog(focus: .item(p.id)) }
        Button("ID kopieren") { copyToPasteboard(p.id) }
        Divider()
        Button("Aus dem Bestand entfernen", role: .destructive) {
            PostenAenderung(model: model, posten: p).entfernen()
        }
    }

    @ViewBuilder
    private var detail: some View {
        if let m = FilamentAuswahl.material(ui.auswahl) {
            if m.isEmpty {
                FilamentNichtGefuehrt(model: model)
            } else {
                FilamentDetail(model: model, material: material, materialID: m)
                    .id(ui.auswahl)
            }
        } else if let id = ui.auswahl, let p = bestand?.posten(id) {
            PostenDetail(model: model, material: material, posten: p)
                .id(id)
        } else if let id = ui.auswahl, nichtErfasst.contains(id) {
            ContentUnavailableView {
                Label(model.lagerteilName(id), systemImage: CatalogSchema.art(model.lagerteilArt(id)).symbol)
            } description: {
                Text("Steckt in der Stückliste, ist aber noch nicht im Bestand dieses Projekts. Ohne Bestand plant der "
                    + "Zuschnitt alles als Einkauf.")
            } actions: {
                Button("In den Bestand aufnehmen …") { ui.erfassen = ErfassenAnfrage(stockID: id) }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            ContentUnavailableView(
                "Kein Lagerteil ausgewählt", systemImage: "shippingbox",
                description: Text("Wähle links ein Lagerteil oder nimm mit + ein neues auf."))
        }
    }
}

// MARK: - Zeile

private struct PostenZeile: View {
    @ObservedObject var model: AppModel
    let id: String
    let text: String
    let leer: Bool

    var body: some View {
        HStack(spacing: 9) {
            ArtTile(art: model.lagerteilArt(id), size: 24, tint: leer ? .secondary : .accentColor)
            VStack(alignment: .leading, spacing: 1) {
                Text(model.lagerteilName(id))
                    .fontWeight(.medium)
                    .lineLimit(1)
                Text(text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            if model.bestandZustand.zuschnitt?.einkaufsliste.contains(where: { $0.id == id }) == true {
                Image(systemName: "cart")
                    .foregroundStyle(ZuschnittFarbe.kaufen.color)
                    .help("Für das Modell fehlt davon etwas (Einkaufsliste)")
            }
        }
        .padding(.vertical, 2)
        .help("\(model.lagerteilName(id))\nLagerteil \(id)")
    }
}

// MARK: - Änderungen

/// Änderungen an einem Posten, jeweils als ganzer Posten an den Kernel (BESTAND_SAVE).
@MainActor
struct PostenAenderung {
    let model: AppModel
    let posten: BestandPosten

    private var name: String { model.lagerteilName(posten.id) }
    private var item: CatalogItem? { model.catalog?.item(posten.id) }

    private func speichern(_ json: JSONValue?, _ grund: String) {
        model.bestandActions?.saveBestandPosten(id: posten.id, posten: json, grund: grund)
    }

    func ganze(_ delta: Int) {
        let z = model.bestandZustand.zuschnitt?.zuschnitt(posten.id)
        let json = BestandBearbeitung.ganze(
            posten.json, delta: delta, laenge: item?.stangenlaenge ?? z?.stangenlaenge, b: item?.plattenformat?.b,
            h: item?.plattenformat?.h)
        let wort = delta > 0 ? "+\(delta)" : "−\(-delta)"
        speichern(json, "\(name): \(wort) \(abs(delta) == 1 ? posten.form.einheit : posten.form.einheitMehrzahl)")
    }

    func setzeGanze(anzahl: Int, laenge: Double?, b: Double?, h: Double?) {
        speichern(
            BestandBearbeitung.setzeGanze(posten.json, anzahl: anzahl, laenge: laenge, b: b, h: h),
            "\(name): ganze \(posten.form.einheitMehrzahl) auf \(anzahl) gesetzt")
    }

    func restAendern(_ rest: BestandRest, laenge: Double?, b: Double?, h: Double?, ort: String?) {
        speichern(
            BestandBearbeitung.restAendern(posten.json, rest: rest.id, laenge: laenge, b: b, h: h, ort: ort),
            "\(name): Rest \(rest.kennung ?? "") geändert")
    }

    func restEntfernen(_ rest: BestandRest) {
        speichern(
            BestandBearbeitung.restEntfernen(posten.json, rest: rest.id),
            "\(name): Rest \(rest.kennung ?? "") (\(rest.masseText)) entfernt")
    }

    func stueck(laenge: Double?, delta: Int) {
        let l = laenge.map { " \(KevFormat.length($0))" } ?? ""
        speichern(
            BestandBearbeitung.stueck(posten.json, laenge: laenge, delta: delta),
            "\(name)\(l): \(delta > 0 ? "+" : "−")\(abs(delta)) Stück")
    }

    func setzeStueck(laenge: Double?, anzahl: Int) {
        let l = laenge.map { " \(KevFormat.length($0))" } ?? ""
        speichern(
            BestandBearbeitung.setzeStueck(posten.json, laenge: laenge, anzahl: anzahl),
            "\(name)\(l): auf \(anzahl) Stück gesetzt")
    }

    func mindestrest(_ wert: Double?) {
        speichern(
            BestandBearbeitung.mindestrest(posten.json, wert),
            "\(name): Mindestrest " + (wert.map(KevFormat.length) ?? "wie Einstellung"))
    }

    func entfernen() {
        speichern(nil, "\(name) aus dem Bestand entfernt")
    }
}

// MARK: - Detail

private struct PostenDetail: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    let posten: BestandPosten
    @ObservedObject private var ui = BestandUI.shared
    @State private var entfernenFragen = false

    private var aenderung: PostenAenderung { PostenAenderung(model: model, posten: posten) }
    private var item: CatalogItem? { model.catalog?.item(posten.id) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                kopf
                switch posten.form {
                case .stange, .platte:
                    GanzeZeile(model: model, posten: posten)
                    ResteAbschnitt(model: model, posten: posten)
                    MindestrestZeile(model: model, posten: posten)
                case .stueckgut:
                    StueckAbschnitt(model: model, posten: posten, mitLaenge: item?.stueckMitLaenge ?? posten.stueck.contains { $0.laenge != nil })
                }
                verplant
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .confirmationDialog(
            "„\(model.lagerteilName(posten.id))“ aus dem Bestand entfernen?", isPresented: $entfernenFragen,
            titleVisibility: .visible
        ) {
            Button("Entfernen", role: .destructive) { aenderung.entfernen() }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Ganze \(posten.form.einheitMehrzahl), Reste und Stückgut dieses Lagerteils verschwinden aus dem Bestand. "
                + "Die Buchung lässt sich rückgängig machen.")
        }
    }

    private var kopf: some View {
        HStack(alignment: .top, spacing: 12) {
            ArtTile(art: model.lagerteilArt(posten.id), size: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.lagerteilName(posten.id))
                    .font(.title3.weight(.semibold))
                    .textSelection(.enabled)
                Text(untertitel)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 8)
            Menu {
                Button("Im Lagerkatalog zeigen") { session.showCatalog(focus: .item(posten.id)) }
                Button("ID kopieren") { copyToPasteboard(posten.id) }
                Divider()
                Button("Aus dem Bestand entfernen …", role: .destructive) { entfernenFragen = true }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("Weitere Aktionen")
        }
    }

    private var untertitel: String {
        var parts = [posten.id]
        if let norm = item?.norm { parts.append(norm) }
        if let m = model.materialName(item?.material) { parts.append(m) }
        return parts.joined(separator: " · ")
    }

    /// Was der aktuelle Zuschnitt von diesem Lagerteil verplant.
    @ViewBuilder
    private var verplant: some View {
        if let z = model.bestandZustand.zuschnitt?.zuschnitt(posten.id) {
            Divider()
            HStack(spacing: 8) {
                Image(systemName: "scissors").foregroundStyle(.secondary)
                Text("Zuschnitt des Modells: " + z.herkunftText)
                if z.hatNeueReste {
                    Text("· neue Reste: " + z.neueResteText).foregroundStyle(ZuschnittFarbe.restNeu.color)
                }
                Spacer(minLength: 8)
                Button("Zuschnitt zeigen") {
                    material.zeige(.zuschnitt, stockID: posten.id)
                }
                .controlSize(.small)
            }
            .font(.callout)
            .monospacedDigit()
        }
    }
}

/// Ganze Stangen bzw. Platten: Anzahl mit −1 und +1, Format.
private struct GanzeZeile: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    @State private var bearbeiten = false

    private var aenderung: PostenAenderung { PostenAenderung(model: model, posten: posten) }

    var body: some View {
        HStack(spacing: 10) {
            Text("Ganze \(posten.form.einheitMehrzahl)")
                .foregroundStyle(.secondary)
                .frame(width: 112, alignment: .leading)
            Button {
                aenderung.ganze(-1)
            } label: {
                Text("−1").frame(minWidth: 22)
            }
            .disabled(posten.ganzeAnzahl == 0 || busy)
            .help("Eine ganze \(posten.form.einheit) weniger")
            Text(KevFormat.integer(posten.ganzeAnzahl))
                .font(.title2.weight(.semibold).monospacedDigit())
                .frame(minWidth: 30)
            Button {
                aenderung.ganze(+1)
            } label: {
                Text("+1 \(posten.form.einheit)")
            }
            .disabled(busy)
            .help("Eine ganze \(posten.form.einheit) dazu")
            if let masse = posten.ganzeMasseText {
                Text("à \(masse)").foregroundStyle(.secondary).monospacedDigit()
            }
            Button("Bearbeiten …") { bearbeiten = true }
                .controlSize(.small)
                .disabled(busy)
                .popover(isPresented: $bearbeiten, arrowEdge: .bottom) {
                    GanzeForm(model: model, posten: posten) { bearbeiten = false }
                }
            Spacer(minLength: 0)
        }
    }

    private var busy: Bool { model.bestandZustand.aktivitaet == .saving }
}

private struct GanzeForm: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    var fertig: () -> Void
    @State private var anzahl = ""
    @State private var laenge = ""
    @State private var b = ""
    @State private var h = ""

    var body: some View {
        Form {
            TextField("Anzahl", text: $anzahl)
            if posten.form == .stange {
                TextField("Länge je Stange (mm)", text: $laenge)
            } else {
                TextField("Breite (mm)", text: $b)
                TextField("Höhe (mm)", text: $h)
            }
        }
        .formStyle(.grouped)
        .frame(width: 300)
        .safeAreaInset(edge: .bottom) {
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel, action: fertig)
                Button("Übernehmen") {
                    PostenAenderung(model: model, posten: posten).setzeGanze(
                        anzahl: Int(KevFormat.parseNumber(anzahl) ?? 0), laenge: KevFormat.parseNumber(laenge),
                        b: KevFormat.parseNumber(b), h: KevFormat.parseNumber(h))
                    fertig()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(KevFormat.parseNumber(anzahl).map { $0 < 0 || $0 != $0.rounded() } ?? true)
            }
            .padding([.horizontal, .bottom], 14)
        }
        .onAppear {
            anzahl = String(posten.ganzeAnzahl)
            laenge = posten.ganzeLaenge.map(KevFormat.input) ?? model.catalog?.item(posten.id)?.stangenlaenge.map(KevFormat.input) ?? ""
            b = posten.ganzeB.map(KevFormat.input) ?? ""
            h = posten.ganzeH.map(KevFormat.input) ?? ""
        }
    }
}

/// Reste mit Kennung, Maß, Ort und Datum; hinzufügen, bearbeiten, entfernen.
private struct ResteAbschnitt: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    @ObservedObject private var ui = BestandUI.shared
    @State private var schnell = ""
    @State private var bearbeiten: String?

    private var aenderung: PostenAenderung { PostenAenderung(model: model, posten: posten) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text("Reste").font(.headline)
                Text(KevFormat.integer(posten.reste.count)).foregroundStyle(.secondary).monospacedDigit()
                Spacer(minLength: 8)
                TextField(posten.form == .stange ? "Rest: Länge in mm" : "Rest: B × H in mm", text: $schnell)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 170)
                    .onSubmit(schnellErfassen)
                    .help(posten.form == .stange
                        ? "Länge eingeben und Return drücken; mehrere mit Komma: 430, 610, 180"
                        : "Maß eingeben und Return drücken, z. B. 600 × 400")
                Button("Rest hinzufügen …") { ui.erfassen = ErfassenAnfrage(stockID: posten.id, nurReste: true) }
                    .controlSize(.small)
                    .help("Reste mit Ort erfassen")
            }
            if posten.reste.isEmpty {
                Text("Keine Reste.").foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                    GridRow {
                        Text("Kennung")
                        Text(posten.form == .stange ? "Länge" : "Maß")
                        Text("Ort")
                        Text("Seit")
                        Text("")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    ForEach(posten.resteSortiert) { rest in
                        GridRow {
                            QuellenMarke(art: .rest, text: rest.kennung ?? "ohne")
                            Text(rest.masseText).monospacedDigit()
                            Text(rest.ort ?? "–").foregroundStyle(rest.ort == nil ? .tertiary : .primary).lineLimit(1)
                            Text(BestandText.anzeige(rest.seit, mitZeit: false) ?? "–").foregroundStyle(.secondary)
                                .monospacedDigit()
                            HStack(spacing: 2) {
                                Button {
                                    bearbeiten = rest.id
                                } label: {
                                    Image(systemName: "pencil")
                                }
                                .help("Rest bearbeiten")
                                .popover(isPresented: Binding(
                                    get: { bearbeiten == rest.id }, set: { if !$0 { bearbeiten = nil } }
                                ), arrowEdge: .trailing) {
                                    RestForm(model: model, posten: posten, rest: rest) { bearbeiten = nil }
                                }
                                Button {
                                    aenderung.restEntfernen(rest)
                                } label: {
                                    Image(systemName: "minus.circle")
                                }
                                .help("Rest entfernen (verbraucht oder weggeworfen)")
                            }
                            .buttonStyle(.borderless)
                        }
                        .contextMenu {
                            Button("Bearbeiten …") { bearbeiten = rest.id }
                            Button("Kennung kopieren") { copyToPasteboard(rest.kennung ?? "") }
                            Divider()
                            Button("Entfernen", role: .destructive) { aenderung.restEntfernen(rest) }
                        }
                    }
                }
            }
        }
    }

    /// Return im Feld: Rest(e) sofort eintragen.
    private func schnellErfassen() {
        let name = model.lagerteilName(posten.id)
        var e = BestandErfassung(form: posten.form)
        if posten.form == .stange {
            guard let l = BestandText.laengen(schnell) else { return NSSound.beep() }
            e.resteLaengen = l
        } else {
            guard let r = BestandText.rechtecke(schnell) else { return NSSound.beep() }
            e.resteFlaechen = r.map { ZuschnittFlaeche(b: $0.b, h: $0.h) }
        }
        model.bestandActions?.saveBestandPosten(
            id: posten.id, posten: e.posten(vorher: posten.json, bestand: model.bestandZustand.bestand),
            grund: e.grund(name: name))
        schnell = ""
    }
}

private struct RestForm: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    let rest: BestandRest
    var fertig: () -> Void
    @State private var laenge = ""
    @State private var b = ""
    @State private var h = ""
    @State private var ort = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Rest \(rest.kennung ?? "")").font(.headline)
            Form {
                if rest.istPlatte {
                    TextField("Breite (mm)", text: $b)
                    TextField("Höhe (mm)", text: $h)
                } else {
                    TextField("Länge (mm)", text: $laenge)
                }
                TextField("Ort", text: $ort, prompt: Text("z. B. Regal 2"))
            }
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel, action: fertig)
                Button("Übernehmen") {
                    PostenAenderung(model: model, posten: posten).restAendern(
                        rest, laenge: rest.istPlatte ? nil : KevFormat.parseNumber(laenge),
                        b: rest.istPlatte ? KevFormat.parseNumber(b) : nil, h: rest.istPlatte ? KevFormat.parseNumber(h) : nil,
                        ort: ort)
                    fertig()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!gueltig)
            }
        }
        .padding(14)
        .frame(width: 280)
        .onAppear {
            laenge = rest.laenge.map(KevFormat.input) ?? ""
            b = rest.b.map(KevFormat.input) ?? ""
            h = rest.h.map(KevFormat.input) ?? ""
            ort = rest.ort ?? ""
        }
    }

    private var gueltig: Bool {
        if rest.istPlatte {
            return (KevFormat.parseNumber(b) ?? 0) > 0 && (KevFormat.parseNumber(h) ?? 0) > 0
        }
        return (KevFormat.parseNumber(laenge) ?? 0) > 0
    }
}

/// Eigener Mindestrest des Lagerteils (überschreibt die Einstellung).
private struct MindestrestZeile: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    @State private var text = ""

    private var standard: Double { model.bestandZustand.bestand?.einstellungen.mindestrestMM ?? 100 }

    var body: some View {
        HStack(spacing: 10) {
            Text("Mindestrest")
                .foregroundStyle(.secondary)
                .frame(width: 112, alignment: .leading)
            TextField("wie Einstellung (\(KevFormat.compact(standard)) mm)", text: $text)
                .textFieldStyle(.roundedBorder)
                .frame(width: 190)
                .onSubmit(sichern)
            Text("mm").foregroundStyle(.secondary)
            if posten.mindestrestMM != nil {
                Button("Wie Einstellung") {
                    PostenAenderung(model: model, posten: posten).mindestrest(nil)
                }
                .controlSize(.small)
            }
            Spacer(minLength: 0)
        }
        .help("Kürzere Reste gelten bei diesem Lagerteil als Verschnitt und kommen nicht in den Bestand")
        .onAppear { text = posten.mindestrestMM.map(KevFormat.input) ?? "" }
    }

    private func sichern() {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty {
            if posten.mindestrestMM != nil { PostenAenderung(model: model, posten: posten).mindestrest(nil) }
            return
        }
        guard let v = KevFormat.parseNumber(t), v >= 0 else { return NSSound.beep() }
        if v != posten.mindestrestMM { PostenAenderung(model: model, posten: posten).mindestrest(v) }
    }
}

/// Stückgut: Anzahl je Länge (Schrauben) bzw. eine Anzahl.
private struct StueckAbschnitt: View {
    @ObservedObject var model: AppModel
    let posten: BestandPosten
    let mitLaenge: Bool
    @State private var neueLaenge = ""
    @State private var neueAnzahl = ""

    private var aenderung: PostenAenderung { PostenAenderung(model: model, posten: posten) }
    private var busy: Bool { model.bestandZustand.aktivitaet == .saving }

    private var zeilen: [BestandStueck] {
        let s = posten.stueck.sorted { ($0.laenge ?? 0) < ($1.laenge ?? 0) }
        return s.isEmpty && !mitLaenge ? [BestandStueck(laenge: nil, anzahl: 0)] : s
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Stückgut").font(.headline)
                Text("\(KevFormat.integer(posten.stueckGesamt)) Stück").foregroundStyle(.secondary).monospacedDigit()
            }
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                ForEach(zeilen) { s in
                    GridRow {
                        Text(s.laenge.map { "Länge \(KevFormat.length($0))" } ?? "Anzahl")
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                        Button("−1") { aenderung.stueck(laenge: s.laenge, delta: -1) }
                            .disabled(s.anzahl == 0 || busy)
                        StueckFeld(anzahl: s.anzahl) { aenderung.setzeStueck(laenge: s.laenge, anzahl: $0) }
                        Button("+1") { aenderung.stueck(laenge: s.laenge, delta: +1) }
                            .disabled(busy)
                        Button("+10") { aenderung.stueck(laenge: s.laenge, delta: +10) }
                            .disabled(busy)
                    }
                }
            }
            if mitLaenge {
                HStack(spacing: 8) {
                    TextField("Länge (mm)", text: $neueLaenge)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 100)
                    TextField("Anzahl", text: $neueAnzahl)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 80)
                        .onSubmit(hinzu)
                    Button("Länge hinzufügen", action: hinzu)
                        .controlSize(.small)
                        .disabled(KevFormat.parseNumber(neueLaenge) == nil || busy)
                }
            }
        }
    }

    private func hinzu() {
        guard let l = KevFormat.parseNumber(neueLaenge), l > 0 else { return NSSound.beep() }
        let n = Int(KevFormat.parseNumber(neueAnzahl) ?? 1)
        guard n > 0 else { return NSSound.beep() }
        aenderung.stueck(laenge: l, delta: n)
        neueLaenge = ""
        neueAnzahl = ""
    }
}

/// Anzahl zum direkten Eintippen (Return übernimmt).
private struct StueckFeld: View {
    let anzahl: Int
    var setzen: (Int) -> Void
    @State private var text = ""

    var body: some View {
        TextField("", text: $text)
            .textFieldStyle(.roundedBorder)
            .multilineTextAlignment(.trailing)
            .monospacedDigit()
            .frame(width: 64)
            .onSubmit {
                guard let v = KevFormat.parseNumber(text), v >= 0, v == v.rounded() else {
                    text = String(anzahl)
                    return NSSound.beep()
                }
                if Int(v) != anzahl { setzen(Int(v)) }
            }
            .onAppear { text = String(anzahl) }
            .onChange(of: anzahl) { _, n in text = String(n) }
    }
}

// MARK: - Buchungen

/// Buchungsprotokoll: neueste zuerst, jede Buchung mit „Rückgängig“.
struct BuchungenListe: View {
    @ObservedObject var model: AppModel

    var body: some View {
        let buchungen = model.bestandZustand.buchungen
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Buchungen").font(.headline)
                Spacer()
                Text(model.project?.name ?? "").foregroundStyle(.secondary)
            }
            .padding(12)
            Divider()
            if buchungen.isEmpty {
                Text("Noch keine Buchungen in diesem Projekt.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 80)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(buchungen) { b in
                            BuchungZeile(model: model, buchung: b)
                            Divider()
                        }
                    }
                }
                .frame(maxHeight: 400)
            }
        }
        .frame(width: 460)
    }
}

private struct BuchungZeile: View {
    @ObservedObject var model: AppModel
    let buchung: BestandBuchung

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Badge(text: buchung.artTitel, color: farbe)
                .frame(width: 84, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(buchung.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .strikethrough(buchung.schonRueckgaengig, color: .secondary)
                    .foregroundStyle(buchung.schonRueckgaengig ? .secondary : .primary)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 6)
            if buchung.schonRueckgaengig {
                Text("zurückgenommen").font(.caption).foregroundStyle(.secondary)
            } else {
                Button("Rückgängig") { model.bestandActions?.buchungRueckgaengig(buchung.id) }
                    .controlSize(.small)
                    .disabled(model.bestandZustand.aktivitaet == .saving)
                    .help("Buchung \(buchung.id) zurücknehmen")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var farbe: Color {
        switch buchung.art {
        case "gebaut": return .accentColor
        case "rueckgaengig": return .secondary
        case "korrektur": return .orange
        default: return .green
        }
    }

    private var detail: String {
        var parts = [BestandText.anzeige(buchung.zeitText) ?? buchung.zeitText]
        if let von = buchung.vonTitel { parts.append(von) }
        if let g = buchung.grund, g != buchung.text { parts.append(g) }
        if let bezug = buchung.bezug { parts.append("zu \(bezug)") }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

// MARK: - Einstellungen

struct BestandEinstellungenForm: View {
    @ObservedObject var model: AppModel
    let einstellungen: BestandEinstellungen
    @State private var mindestrest = ""
    @State private var saegeblatt = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Bestand: Einstellungen").font(.headline)
            Form {
                TextField("Mindestrest (mm)", text: $mindestrest)
                    .help("Kürzere Reste gelten als Verschnitt und kommen nicht in den Bestand; je Lagerteil änderbar")
                TextField("Sägeblatt (mm)", text: $saegeblatt)
                    .help("Schnittbreite für Stangen und Platten")
            }
            Text("Gilt für dieses Projekt. Der Zuschnitt wird danach neu gerechnet.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel) { dismiss() }
                Button("Übernehmen") {
                    guard let neu = neueEinstellungen else { return }
                    model.bestandActions?.saveBestandEinstellungen(
                        neu, grund: "Einstellungen: Mindestrest \(KevFormat.length(neu.mindestrestMM)), "
                            + "Sägeblatt \(KevFormat.length(neu.saegeblattMM))")
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(neueEinstellungen == nil || neueEinstellungen == einstellungen)
            }
        }
        .padding(14)
        .frame(width: 300)
        .onAppear {
            mindestrest = KevFormat.input(einstellungen.mindestrestMM)
            saegeblatt = KevFormat.input(einstellungen.saegeblattMM)
        }
    }

    private var neueEinstellungen: BestandEinstellungen? {
        guard let m = KevFormat.parseNumber(mindestrest), let s = KevFormat.parseNumber(saegeblatt), m >= 0, s >= 0, s < 50
        else { return nil }
        return BestandEinstellungen(mindestrestMM: m, saegeblattMM: s)
    }
}
