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
