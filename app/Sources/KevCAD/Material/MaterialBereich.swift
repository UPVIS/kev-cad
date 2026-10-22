import AppKit
import KevCADCore
import SwiftUI

/// Bereich „Material“ im Projektfenster (⌘3), Mitte: der gewählte Abschnitt. Die Auswahl gilt in beide Richtungen: wer
/// hier Positionen wählt, wählt ihre Teile im 3D-Bereich und im Teilebaum; wer dort Teile wählt, sieht hier ihre Zeilen.
struct MaterialBereich: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var material: MaterialZustand
    var navigation: MaterialNavigation?
    var zeigeIm3D: ([String]) -> Void

    var body: some View {
        let daten = model.materialDaten
        Group {
            switch material.abschnitt {
            case .uebersicht:
                MaterialUebersichtAnsicht(model: model, material: material, daten: daten)
            case .stueckliste:
                MaterialStuecklisteAnsicht(model: model, material: material, daten: daten, navigation: navigation,
                                           zeigeIm3D: zeigeIm3D)
            case .zuschnitt:
                MaterialZuschnittAnsicht(model: model, material: material, daten: daten, navigation: navigation)
            case .bestand:
                BestandAnsicht(model: model, material: material)
            case .einkauf:
                MaterialEinkaufAnsicht(model: model, material: material, daten: daten, navigation: navigation)
            case .zukauf:
                MaterialZukaufAnsicht(model: model, material: material, daten: daten, navigation: navigation,
                                      zeigeIm3D: zeigeIm3D)
            case .druck:
                DruckAbschnitt(model: model)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
        // Gleicher Platzhalter in allen Abschnitten: ein wechselnder baut die Werkzeugleiste jedes Mal neu auf
        .searchable(text: $material.suche, placement: .toolbar, prompt: "Material durchsuchen")
        .onAppear {
            if model.catalog == nil { model.catalogActions?.requestCatalog(query: nil, art: nil) }
            if model.bom == nil, model.kernelState == .ready { model.catalogActions?.requestBOM() }
            material.ladeAbgehakt(model.project?.path)
            auswahlAus3D(model.selectedPartIDs)
            material.bilder.lade(model, daten: daten)
        }
        .onChange(of: model.bom?.run) { _, _ in material.bilder.lade(model, daten: model.materialDaten) }
        .onChange(of: material.auswahl) { _, neu in auswahlIns3D(neu) }
        .onChange(of: model.selectedPartIDs) { _, ids in auswahlAus3D(ids) }
        .onChange(of: model.project?.path) { _, p in
            material.auswahl = []
            material.ladeAbgehakt(p)
        }
    }

    /// Gewählte Positionen: ihre Teile im 3D-Bereich und im Teilebaum auswählen.
    private func auswahlIns3D(_ positionen: Set<Int>) {
        let teile = model.materialDaten.positionen.filter { positionen.contains($0.pos) }.flatMap(\.teile)
        let jetzt = Set(model.selectedPartIDs)
        guard Set(teile) != jetzt, !teile.isEmpty || positionen.isEmpty else { return }
        // Auswahl kam aus dem 3D-Bereich und passt schon zu den Zeilen: nicht ausweiten
        if !jetzt.isEmpty, model.materialDaten.positionen(mit: jetzt) == positionen { return }
        model.actions?.select(teile)
    }

    /// Auswahl im 3D-Bereich oder im Teilebaum: die Zeilen ihrer Teile markieren.
    private func auswahlAus3D(_ ids: [String]) {
        let pos = model.materialDaten.positionen(mit: Set(ids))
        if pos != material.auswahl { material.auswahl = pos }
    }
}

/// Werkzeugleiste im Bereich „Material“: Bestand erfassen, Zukaufteil, Bericht, Inspektor. Die Abschnitte wählt die
/// Seitenleiste, die Suche hängt am Bereich selbst. Den Zustand des Bereichs beobachtet die Leiste nicht (sonst baut
/// sie sich bei jedem Abschnitt und jeder Auswahl neu auf); „Als Bericht drucken“ liest ihn beim Klick.
struct MaterialToolbar: ToolbarContent {
    @ObservedObject var model: AppModel
    let material: MaterialZustand
    @ObservedObject var state: ProjectWindowState
    var navigation: MaterialNavigation?
    let session: AppSession

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                BestandUI.shared.erfassen = ErfassenAnfrage(stockID: nil)
            } label: {
                Label("Bestand erfassen", systemImage: "shippingbox.and.arrow.backward")
            }
            .disabled(model.bestandActions == nil || model.bestandZustand.bestand == nil)
            .help("Lagerteil in den Bestand dieses Projekts aufnehmen")
            Button {
                session.showZukaufDialog()
            } label: {
                Label("Zukaufteil hinzufügen", systemImage: "bag.badge.plus")
            }
            .help("Zukaufteil hinzufügen … (⌥⇧⌘K)")
            Button {
                navigation?.bericht(material.abschnitt.bericht)
            } label: {
                Label("Als Bericht drucken", systemImage: "printer")
            }
            .disabled(navigation == nil)
            .help("Als Bericht drucken: derselbe Inhalt in „Dokumente“ › Berichte")
            Button {
                state.showInspector.toggle()
            } label: {
                Label("Inspektor", systemImage: "sidebar.trailing")
            }
            .help("Inspektor ein- oder ausblenden")
        }
    }
}
