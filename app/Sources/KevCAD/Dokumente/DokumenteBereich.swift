import AppKit
import KevCADCore
import SwiftUI

/// Bereich „Dokumente“ im Projektfenster (Mitte): Blattansicht, Bauplan oder Berichte, je nach Seitenleiste.
struct DokumenteBereich: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: DokumenteStore
    @ObservedObject var zustand: DokumenteZustand
    @EnvironmentObject private var session: AppSession

    var body: some View {
        Group {
            switch zustand.auswahl {
            case .blatt(let id)?:
                BlattAnsicht(model: model, store: store, zustand: zustand, blattID: id)
            case .bauplan?:
                BauplanBereich(model: model)
            case .berichte?:
                BerichteBereich(model: model)
            case nil:
                ContentUnavailableView {
                    Label("Kein Blatt gewählt", systemImage: "doc.text")
                } description: {
                    Text("Links ein Blatt, den Bauplan oder die Berichte wählen.")
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .underPageBackgroundColor))
        .onAppear {
            verbinden()
            if store.uebersicht == nil, model.kernelState == .ready { model.dokumenteActions?.dokumenteAnfordern() }
            waehleVorgabe()
        }
        .onChange(of: store.uebersicht) { _, _ in waehleVorgabe() }
        .onChange(of: model.kernelState) { _, s in
            if s == .ready, store.uebersicht == nil { model.dokumenteActions?.dokumenteAnfordern() }
        }
        .onChange(of: zustand.auswahl) { _, _ in zustand.merke(model.project?.path) }
    }

    /// Ausgabe-Aktionen für Menü und Kontextmenü der Leinwand.
    private func verbinden() {
        let model = self.model
        let zustand = self.zustand
        let session = self.session
        zustand.pdfSichern = {
            BlattAusgabe.pdfSichern(zustand.markierteBlaetter(model.dokumente), model: model,
                                    fenster: session.projectWindow) { t, f in zustand.melde(t, fehler: f) }
        }
        zustand.drucken = {
            BlattAusgabe.drucken(zustand.markierteBlaetter(model.dokumente), model: model,
                                 fenster: session.projectWindow) { t, f in zustand.melde(t, fehler: f) }
        }
    }

    /// Ohne Auswahl: das zuletzt gezeigte Blatt dieses Projekts, sonst der Zusammenbau, sonst das erste Blatt. Nach
    /// „Zeichnung anlegen“ im Teilebaum das neue Blatt dieser Teile.
    private func waehleVorgabe() {
        guard let u = store.uebersicht else { return }
        if let wunsch = zustand.wunschTeile,
           let e = u.blaetter.first(where: { Set(wunsch).isSubset(of: Set($0.teile)) && !$0.teile.isEmpty })
        {
            zustand.wunschTeile = nil
            zustand.waehle(.blatt(e.id))
            return
        }
        if let a = zustand.auswahl {
            if case .blatt(let id) = a, u.blatt(id) == nil { zustand.auswahl = nil } else { return }
        }
        if let g = zustand.gemerkt(model.project?.path) {
            if case .blatt(let id) = g, u.blatt(id) == nil {} else {
                zustand.waehle(g)
                return
            }
        }
        if let e = u.zusammenbau.first ?? u.einzelteile.first ?? u.baugruppen.first {
            zustand.waehle(.blatt(e.id))
        }
    }
}

/// Umschalter 3D-Modell / Dokumente / Material in der Werkzeugleiste (⌘1, ⌘2, ⌘3).
struct BereichUmschalter: View {
    @ObservedObject var state: ProjectWindowState

    var body: some View {
        Picker("Bereich", selection: Binding(
            get: { state.bereich },
            set: { b in withAnimation(.snappy(duration: 0.2)) { state.bereich = b } }
        )) {
            ForEach(ProjektBereich.allCases, id: \.self) { b in
                Label(b.titel, systemImage: b.symbol).tag(b)
            }
        }
        .pickerStyle(.segmented)
        .labelStyle(.iconOnly)
        .help("3D-Modell (⌘1) · Dokumente: Zeichnungen, Bauplan, Berichte (⌘2) · "
              + "Material: Stückliste, Zuschnitt, Bestand, Einkauf (⌘3) · "
              + "Simulation: Lastfälle, Kräfte, Lager, Ergebnisse, Topologie (⌘4)")
    }
}

/// Werkzeugleiste im Bereich Dokumente: Werkzeuge, Ansicht hinzufügen, Zoom, Teilen, PDF, Drucken, Inspektor.
struct DokumenteToolbar: ToolbarContent {
    @ObservedObject var model: AppModel
    @ObservedObject var store: DokumenteStore
    @ObservedObject var zustand: DokumenteZustand
    @ObservedObject var state: ProjectWindowState

    private var blatt: Zeichnung? { zustand.blattID.flatMap { store.zeichnung($0) } }

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .principal) {
            Picker("Werkzeug", selection: Binding(
                get: { zustand.werkzeug == .mass ? 1 : zustand.werkzeug == .notiz ? 2 : 0 },
                set: { zustand.setzeWerkzeug([BlattWerkzeug.auswahl, .mass, .notiz][$0]) }
            )) {
                Label("Auswählen", systemImage: "cursorarrow").tag(0)
                Label("Maß", systemImage: "ruler").tag(1)
                Label("Notiz", systemImage: "text.bubble").tag(2)
            }
            .pickerStyle(.segmented)
            .labelStyle(.iconOnly)
            .disabled(blatt == nil)
            .help("Auswählen und ziehen (V) · Maß zwischen zwei Elementen (D) · Notiz mit Zeiger (N)")

            Menu {
                ForEach(["vorn", "oben", "links", "rechts", "hinten", "unten", "iso"], id: \.self) { art in
                    Button(ZeichnungText.ansichtArt(art)) { zustand.setzeWerkzeug(.ansicht(art)) }
                }
                Divider()
                Button { zustand.setzeWerkzeug(.schnitt) } label: {
                    Label("Schnitt: Linie durch eine Ansicht ziehen", systemImage: "line.diagonal")
                }
                Button { zustand.setzeWerkzeug(.einzelheit) } label: {
                    Label("Einzelheit: Kreis aufziehen", systemImage: "circle.dashed")
                }
            } label: {
                Label("Ansicht hinzufügen", systemImage: "rectangle.badge.plus")
            }
            .disabled(blatt == nil)
            .help("Ansicht, Schnitt oder Einzelheit hinzufügen, dann auf dem Blatt setzen")

            ControlGroup {
                Button { zustand.ausfuehren(.verkleinern) } label: { Label("Verkleinern", systemImage: "minus.magnifyingglass") }
                    .help("Verkleinern (⌘−)")
                Button { zustand.ausfuehren(.einpassen) } label: {
                    Label("Blatt einpassen", systemImage: "arrow.up.left.and.down.right.magnifyingglass")
                }
                .help("Blatt einpassen (⌘9)")
                Button { zustand.ausfuehren(.vergroessern) } label: { Label("Vergrößern", systemImage: "plus.magnifyingglass") }
                    .help("Vergrößern (⌘+)")
            }
            .disabled(blatt == nil)
        }

        ToolbarItemGroup(placement: .primaryAction) {
            if let z = blatt {
                let liste = zustand.markierteBlaetter(store).compactMap { store.zeichnung($0) }
                let zs = liste.isEmpty ? [z] : liste
                ShareLink(item: BlattPDFDatei(zeichnungen: zs, name: BlattPDF.dateiname(zs, projekt: model.project?.name)),
                          preview: SharePreview(zs.count == 1 ? zs[0].blatt.titel : "\(zs.count) Zeichnungen")) {
                    Label("Teilen", systemImage: "square.and.arrow.up")
                }
                .help("Als PDF teilen (Mail, Nachrichten, AirDrop …)")
            }
            Button { zustand.pdfSichern?() } label: { Label("Als PDF sichern", systemImage: "arrow.down.doc") }
                .disabled(blatt == nil)
                .help("Als PDF sichern … (⌥⌘P)")
            Button { zustand.drucken?() } label: { Label("Drucken", systemImage: "printer") }
                .disabled(blatt == nil)
                .help("Drucken … (⌘P), 1:1 ohne Skalierung")
            Button {
                state.showInspector.toggle()
            } label: {
                Label("Inspektor", systemImage: "sidebar.trailing")
            }
            .help("Inspektor ein- oder ausblenden")
        }
    }
}
