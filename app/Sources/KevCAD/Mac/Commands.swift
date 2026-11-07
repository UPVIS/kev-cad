import KevCADCore
import SwiftUI

/// Menüs und Tastenkürzel. Einbuchstabige Kürzel wirken nur, wenn das Projektfenster vorne ist, und nicht, solange ein
/// Textfeld den Fokus hat (siehe `KeyboardGuard`).
struct KevCADCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var recents: RecentProjects
    /// Gesetzt, solange das Projektfenster das Hauptfenster ist.
    @FocusedObject private var window: ProjectWindowState?

    private var hasProject: Bool { model.project != nil }
    /// Projektfenster vorne und 3D-Bereich sichtbar (in „Dokumente“ und „Material“ gelten deren Kürzel bzw. keine).
    private var inProject: Bool { window != nil && hasProject && window?.bereich == .modell }
    private var hasSelection: Bool { !model.selection.isEmpty }
    /// Blender-Befehle des App-Kerns (im Demomodus nicht vorhanden).
    private var nav: NavigationActions? { model.actions as? NavigationActions }
    /// Viewer V2: Befehle der Belegung (Tastenbelegung.swift), Darstellung, Bild und Video.
    private var viewer: ViewerActions? { model.actions as? ViewerActions }

    private func axisView(_ view: StandardViewName) {
        if let nav { nav.axisView(view) } else { model.actions?.setStandardView(view) }
    }

    private func viewSelected() {
        if let nav { nav.viewSelected() } else { model.fitSelection() }
    }

    /// Zweit- und Drittbelegungen für „Auswahl einrahmen“ und „Alles einrahmen“ (F, Komma, Umschalt-C).
    private var zweitTasten: [(String, Taste, ViewerBefehl)] {
        [ViewerBefehl.auswahlEinrahmen, .allesEinrahmen].flatMap { b -> [(String, Taste, ViewerBefehl)] in
            guard let bel = Tastenbelegung.belegung(b) else { return [] }
            return bel.tasten.dropFirst().filter { $0.keyEquivalent != nil }.map { ("\(bel.titel) (\($0.anzeige))", $0, b) }
        }
    }

    private func viewAll() {
        if let nav { nav.viewAll() } else { model.actions?.focus(on: model.parts.filter(\.visible).map(\.id)) }
    }

    var body: some Commands {
        // Ablage
        CommandGroup(replacing: .newItem) {
            Button("Neues Projekt") { session.neuesProjekt() }  // V2-3: ohne Formular
                .keyboardShortcut("n")
            Button("Öffnen …") { session.presentOpenPanel() }
                .keyboardShortcut("o")
            Button(session.istEntwurf ? "Sichern unter …" : "Umbenennen …") { session.umbenennenAnfrage += 1 }
                .keyboardShortcut("s", modifiers: [.command, .shift])
                .disabled(!hasProject)
            Menu("Zuletzt geöffnet") {
                ForEach(recents.items) { item in
                    Button(item.isMissing ? "\(item.name) (fehlt)" : item.name) { session.openRecent(item) }
                }
                if recents.items.isEmpty {
                    Text("Keine Projekte")
                }
                Divider()
                Button("Fehlende entfernen") { recents.removeMissing() }
                    .disabled(!recents.items.contains(where: \.isMissing))
                Button("Liste leeren") { recents.clear() }
                    .disabled(recents.items.isEmpty)
            }
            Divider()
            // I-2b (PLAN-IPAD.md): QR-Code für Kev CAD auf dem iPad, gekoppelte iPads verwalten
            Button("iPad koppeln …") { session.ipadKoppelnZeigen() }
                .disabled(!(model.actions is KopplungsActions))
        }
        CommandGroup(replacing: .saveItem) {
            Button("model.py im Editor öffnen") { session.openModelInEditor() }
                .keyboardShortcut("o", modifiers: [.command, .option])
                .disabled(!hasProject)
            Button("Projektordner im Finder zeigen") { session.revealProjectInFinder() }
                .disabled(!hasProject)
        }
        CommandGroup(replacing: .importExport) {
            Menu("Exportieren") {
                // ⇧⌘E öffnet seit Phase 6 „Dokumente exportieren …“ (DokumenteExportCommands)
                Button("STEP, STL und 3MF") { model.actions?.export(formats: ExportFormat.standard.map(\.rawValue)) }
                    .keyboardShortcut("e", modifiers: [.command, .shift, .option])
                Divider()
                ForEach(ExportFormat.allCases) { format in
                    Button("Nur \(format.title)") { model.actions?.export(formats: [format.rawValue]) }
                }
            }
            .disabled(!hasProject || model.parts.isEmpty)
            Button("Bildschirmfoto (PNG)") {
                if let viewer { viewer.bildschirmfoto(model.viewer.fotoGroesse) } else { model.actions?.saveScreenshot() }
            }
            .tastenkuerzel(.bildschirmfoto)
            .disabled(!hasProject)
            Button("Bildschirmfoto in 4K") { viewer?.bildschirmfoto(.uhd4k) }
                .disabled(!hasProject || viewer == nil)
            Button("Video: Drehung um das Ziel") { viewer?.videoDrehung() }
                .tastenkuerzel(.video)
                .disabled(!hasProject || viewer == nil || model.parts.isEmpty)
            Button(model.viewer.aufnahme.laeuft ? "Navigation aufnehmen beenden" : "Navigation aufnehmen") {
                viewer?.navigationAufnehmen()
            }
            .tastenkuerzel(.navigationAufnehmen)
            .disabled(!hasProject || viewer == nil)
        }

        // Darstellung
        CommandGroup(before: .toolbar) {
            Group {
                // Ansicht wie in Blender (Ziffernblock oder Zahlenreihe)
                // Belegung aus Tastenbelegung.swift (einzige Quelle; Ziffernblock oder Zahlenreihe)
                ForEach(StandardViewName.menuOrder.filter { $0.befehl != nil }, id: \.self) { view in
                    Button(view.title) { axisView(view) }
                        .tastenkuerzel(view.befehl!)
                }
                Button("Gegenseite") { nav?.viewOpposite() }
                    .tastenkuerzel(.gegenseite)
                // Phase 5: Kameras wie in Blender (Ziffernblock oder Zahlenreihe 0)
                Button("Durch Kamera schauen (an/aus)") {
                    model.cameraActions?.toggleCameraView()
                }
                .tastenkuerzel(.kameraBlick)
                Button("Aktive Kamera auf Ansicht setzen") { model.cameraActions?.setActiveCameraToView() }
                    .tastenkuerzel(.kameraAufAnsicht)
                Button(model.orthographic ? "Perspektive" : "Parallelprojektion") { nav?.toggleProjection() }
                    .tastenkuerzel(.projektion)
                Menu("Isometrisch") {
                    ForEach([StandardViewName.iso] + StandardViewName.extraIsoOrder, id: \.self) { view in
                        Button(view.title) { model.actions?.setStandardView(view) }
                    }
                }
                Menu("Drehen, Schwenken, Zoomen") {
                    Button("Nach links drehen") { nav?.orbitStep(yaw: -15, pitch: 0) }
                        .tastenkuerzel(.drehenLinks)
                    Button("Nach rechts drehen") { nav?.orbitStep(yaw: 15, pitch: 0) }
                        .tastenkuerzel(.drehenRechts)
                    Button("Nach oben drehen") { nav?.orbitStep(yaw: 0, pitch: -15) }
                        .tastenkuerzel(.drehenHoch)
                    Button("Nach unten drehen") { nav?.orbitStep(yaw: 0, pitch: 15) }
                        .tastenkuerzel(.drehenRunter)
                    Divider()
                    Button("Nach links schwenken") { nav?.panStep(x: -0.1, y: 0) }
                        .tastenkuerzel(.schwenkenLinks)
                    Button("Nach rechts schwenken") { nav?.panStep(x: 0.1, y: 0) }
                        .tastenkuerzel(.schwenkenRechts)
                    Button("Nach oben schwenken") { nav?.panStep(x: 0, y: 0.1) }
                        .tastenkuerzel(.schwenkenHoch)
                    Button("Nach unten schwenken") { nav?.panStep(x: 0, y: -0.1) }
                        .tastenkuerzel(.schwenkenRunter)
                    Divider()
                    Button("Heranzoomen") { nav?.zoomStep(1) }
                        .tastenkuerzel(.zoomRein)
                    Button("Herauszoomen") { nav?.zoomStep(-1) }
                        .tastenkuerzel(.zoomRaus)
                    Divider()
                    // Zweit- und Drittbelegungen aus der Tabelle (F, Komma, Umschalt-C)
                    ForEach(zweitTasten, id: \.0) { titel, taste, befehl in
                        Button(titel) { befehl == .allesEinrahmen ? viewAll() : viewSelected() }
                            .keyboardShortcut(taste.keyEquivalent!, modifiers: taste.mods.swiftUI)
                    }
                }
                Button("Ansichtsmenü (^ über dem Viewport)") { viewer?.menueOeffnen(.ansicht) }
                    .disabled(viewer == nil)
                Divider()
                Button(hasSelection ? "Auswahl einrahmen" : "Alles einrahmen") { viewSelected() }
                    .tastenkuerzel(.auswahlEinrahmen)
                Button("Alles einrahmen") { viewAll() }
                    .tastenkuerzel(.allesEinrahmen)
                Divider()
                Button("Alles auswählen") { nav?.selectAll() }
                    .tastenkuerzel(.allesAuswaehlen)
                Button("Auswahl aufheben") { model.clearSelection() }
                    .tastenkuerzel(.auswahlAufheben)
                    .disabled(!inProject || !hasSelection)
                Button("Auswahl umkehren") { nav?.invertSelection() }
                    .tastenkuerzel(.auswahlUmkehren)
                Toggle("Flächen und Kanten auswählen", isOn: Binding(
                    get: { model.selectionMode == .elements },
                    set: { nav?.setSelectionMode($0 ? .elements : .parts) }
                ))
                .tastenkuerzel(.elementModus)
                Button("Abbrechen") {
                    if model.oberflaeche.uebersicht {  // V2-3: Startübersicht wegschieben
                        model.oberflaechenActions?.zeigeUebersicht(false)
                    } else if model.oberflaeche.sitzungOffen {  // V2-6: Sitzung verwerfen
                        model.oberflaechenActions?.sprechenVerwerfen()
                    } else if let viewer {
                        viewer.ausfuehren(.abbrechen)  // Menü, Übersicht, Werkzeug, Messen, Auswahl
                    } else if model.measureMode {
                        model.actions?.setMeasureMode(false)
                    } else {
                        model.clearSelection()
                    }
                }
                .tastenkuerzel(.abbrechen)
                Divider()
                Button("Ausblenden") { model.hideSelection() }
                    .tastenkuerzel(.ausblenden)
                    .disabled(!inProject || !hasSelection)
                Button("Andere ausblenden") { nav?.hideUnselected() }
                    .tastenkuerzel(.andereAusblenden)
                    .disabled(!inProject || !hasSelection)
                Button("Alles einblenden") { model.actions?.showAll() }
                    .tastenkuerzel(.allesEinblenden)
                Button(model.viewer.lokaleAnsicht ? "Lokale Ansicht beenden" : "Isolieren (lokale Ansicht)") {
                    nav?.toggleLocalView()
                }
                .tastenkuerzel(.isolieren)
                Toggle("Übrige Teile als Hauch", isOn: Binding(
                    get: { model.viewer.hauch }, set: { viewer?.setHauch($0) }))
                Divider()
                Menu("Darstellung") {
                    ForEach(ShadingModus.allCases, id: \.self) { m in
                        Toggle(m.titel, isOn: Binding(
                            get: { model.viewer.shading == m }, set: { _ in viewer?.setShading(m) }))
                    }
                    Divider()
                    ForEach(ShadingOption.allCases, id: \.self) { o in
                        Toggle(o.titel, isOn: Binding(
                            get: { o.istAn(model.viewer.optionen) }, set: { viewer?.setShadingOption(o, $0) }))
                    }
                }
                .disabled(viewer == nil)
                Button("Darstellung wählen …") { viewer?.menueOeffnen(.darstellung) }
                    .tastenkuerzel(.shadingMenue)
                    .disabled(viewer == nil)
                // I-4: derselbe Kranz wie am iPad mit dem Stift, hier an der Maus
                Button("Werkzeugkranz …") { viewer?.ausfuehren(.werkzeugkranz) }
                    .tastenkuerzel(.werkzeugkranz)
                    .disabled(viewer == nil)
                Toggle("Röntgen", isOn: Binding(
                    get: { model.viewer.shading == .roentgen }, set: { _ in viewer?.ausfuehren(.roentgen) }))
                    .tastenkuerzel(.roentgen)
                    .disabled(viewer == nil)
                Toggle("Messen", isOn: Binding(get: { model.measureMode }, set: { model.actions?.setMeasureMode($0) }))
                    .tastenkuerzel(.messen)
                Toggle("Schnitt", isOn: Binding(
                    get: { model.sectionEnabled }, set: { _ in window?.toggleSection(model) }
                ))
                .tastenkuerzel(.schnitt)
                Toggle("Explosion", isOn: Binding(
                    get: { model.explodeFactor > 0 }, set: { _ in window?.toggleExplode(model) }
                ))
                .tastenkuerzel(.explosion)
                Toggle("Bedingungen am Teil", isOn: Binding(
                    get: { model.showConstraintSymbols },
                    set: { BedingungenSchalter.setzen(model, $0) }
                ))
                .keyboardShortcut("b", modifiers: [.command, .option])
                .disabled(model.constraintActions == nil)
            }
            .disabled(!inProject)
            Divider()
        }

        // Modell
        CommandMenu("Modell") {
            Button("Neu rechnen") { model.actions?.runModel() }
                .keyboardShortcut("r")
                .disabled(!hasProject)
            Toggle("Auto-Lauf beim Speichern", isOn: Binding(
                get: { model.autoRun }, set: { model.actions?.setAutoRun($0) }
            ))
            .disabled(!hasProject)
            Toggle("Zeitlupe", isOn: Binding(get: { model.slowMotion }, set: { model.actions?.setSlowMotion($0) }))
                .disabled(!hasProject)
            Divider()
            ModellUntermenues(session: session, model: model)  // V2-3: statt eigener Menüs in der Menüleiste
            Divider()
            Button("Kernel neu starten") { model.actions?.restartKernel() }
                .keyboardShortcut("k", modifiers: [.command, .option])
        }

        // Hilfe
        CommandGroup(replacing: .help) {
            Button("Tastenübersicht") { viewer?.ausfuehren(.tastenuebersicht) }
                .tastenkuerzel(.tastenuebersicht)
                .disabled(!inProject || viewer == nil)
            Toggle("Hinweisleiste im Viewport", isOn: Binding(
                get: { model.viewer.hinweisleiste },
                set: { if $0 != model.viewer.hinweisleiste { viewer?.ausfuehren(.hinweisleiste) } }))
                .tastenkuerzel(.hinweisleiste)
            Divider()
            Button("Protokoll zeigen") { session.showLog() }
        }
    }
}

/// Zusatzmenü im Demomodus: Zustände von Hand auslösen.
struct DemoCommands: Commands {
    @ObservedObject var session: AppSession

    var body: some Commands {
        if let demo = session.demo {
            CommandMenu("Demo") {
                Button("Lauf starten") { demo.runModel() }
                Button("Fehler im Lauf auslösen") { demo.triggerError() }
                    .keyboardShortcut("f", modifiers: [.command, .option, .control])
                Button("Agent verbinden oder trennen") { demo.toggleAgent() }
                Button("Kernel-Absturz simulieren") { demo.simulateKernelCrash() }
                Divider()
                Button("Projekt schließen") { demo.closeProject() }
            }
        }
    }
}
