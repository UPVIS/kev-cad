#if os(macOS)
import AppKit
#endif
import Foundation
import OCCTSwiftViewport
import simd

// ViewerActions (V2): Befehle der Belegung, Menüs im Viewport, lokale Ansicht, Darstellung, Bild und Video.

extension AppController: ViewerActions {
    var viewer: ViewerStore { model.viewer }

    func installViewer() {
        viewport.onBefehl = { [weak self] befehl in
            guard let self else { return false }
            self.ausfuehren(befehl)
            return true
        }
        viewport.onHover = { [weak self] pick, welt, bildpunkt in
            self?.hoverGeaendert(pick, welt, bildpunkt)
            self?.sprache.maus(pick, welt, bildpunkt)  // V2-6: Worauf zeigt Kevin beim Sprechen?
        }
        viewport.onStrich = { [weak self] e in self?.sprache.strich(e) }
        strichStilInstallieren(viewport)
        darstellungAnwenden()
    }

    // MARK: Befehle

    public func ausfuehren(_ befehl: ViewerBefehl) {
        // Ein offenes Menü im Viewport schließt jeder Befehl (außer dem, der es öffnet)
        if befehl != .ansichtMenue && befehl != .shadingMenue && viewer.menue != nil { viewer.menue = nil }
        if befehl != .werkzeugkranz && befehl != .abbrechen && viewer.kranz != nil { viewer.kranz = nil }
        switch befehl {
        case .vorne: axisView(.front)
        case .hinten: axisView(.back)
        case .rechts: axisView(.right)
        case .links: axisView(.left)
        case .oben: axisView(.top)
        case .unten: axisView(.bottom)
        case .gegenseite: viewOpposite()
        case .projektion: toggleProjection()
        case .ansichtMenue: menueOeffnen(viewer.menue == .ansicht ? nil : .ansicht)
        case .auswahlEinrahmen: viewSelected()
        case .allesEinrahmen: viewAll()
        case .drehenLinks: orbitStep(yaw: -15, pitch: 0)
        case .drehenRechts: orbitStep(yaw: 15, pitch: 0)
        case .drehenHoch: orbitStep(yaw: 0, pitch: -15)
        case .drehenRunter: orbitStep(yaw: 0, pitch: 15)
        case .schwenkenLinks: panStep(x: -0.1, y: 0)
        case .schwenkenRechts: panStep(x: 0.1, y: 0)
        case .schwenkenHoch: panStep(x: 0, y: 0.1)
        case .schwenkenRunter: panStep(x: 0, y: -0.1)
        case .zoomRein: zoomStep(1)
        case .zoomRaus: zoomStep(-1)
        case .kameraBlick: toggleCameraView()
        case .kameraAufAnsicht: setActiveCameraToView()
        case .allesAuswaehlen: selectAll()
        case .auswahlAufheben: select([])
        case .auswahlUmkehren: invertSelection()
        case .elementModus: setSelectionMode(model.selectionMode == .parts ? .elements : .parts)
        case .abbrechen: abbrechen()
        case .ausblenden:
            let teile = Array(Set(scene.selection.map(\.part)))
            if !teile.isEmpty { setVisibility(teile, visible: false) }
        case .andereAusblenden: hideUnselected()
        case .allesEinblenden: showAll()
        case .isolieren: lokaleAnsicht(hauch: nil)
        case .shadingMenue: menueOeffnen(viewer.menue == .darstellung ? nil : .darstellung)
        case .roentgen: setShading(viewer.shading == .roentgen ? letzteDarstellung : .roentgen)
        case .schnitt: schnittUmschalten()
        case .explosion: setExplode(model.explodeFactor > 0 ? 0 : 1)
        case .messen: setMeasureMode(!model.measureMode)
        case .messungAbschliessen:
            if sprache.offen { sprache.fertig() } else { messungAbschliessen() }  // ↩ gehört der offenen Sitzung
        case .masseUmschalten:
            masseSichtbarSetzen(!viewer.masseSichtbar)
            viewer.zeige(viewer.masseSichtbar ? "Maße eingeblendet" : "Maße ausgeblendet")
        case .masseLoeschen:
            let hatte = !model.measurements.isEmpty || viewer.stehendeAnmerkungen > 0
            clearMeasurements()
            if hatte { viewer.zeige("Alle Maße gelöscht") }
        case .bildschirmfoto: bildschirmfoto(viewer.fotoGroesse)
        case .video: videoDrehung()
        case .navigationAufnehmen: navigationAufnehmen()
        case .sprechen: oberflaeche(.sprechen(!model.oberflaeche.spricht))
        case .sprechenFertig: sprache.fertig()
        case .sprechenVerwerfen: sprache.verwerfen()
        case .rueckgaengig: rueckgaengig()
        case .wiederholen: wiederholen()
        case .werkzeugkranz: kranzOeffnen(bei: nil)
        case .tastenuebersicht: viewer.tastenuebersicht.toggle()
        case .hinweisleiste: viewer.hinweisleiste.toggle()
        }
    }

    /// Esc: Sitzung, Menü, Übersicht, Werkzeug, Messen, sonst Auswahl.
    func abbrechen() {
        if viewer.kranz != nil {
            kranzSchliessen(zuruecksetzen: true)
        } else if sprache.offen {
            sprache.verwerfen()
        } else if viewer.menue != nil {
            viewer.menue = nil
        } else if viewer.tastenuebersicht {
            viewer.tastenuebersicht = false
        } else if model.simulation.werkzeug != .keins {
            setSimulationWerkzeug(.keins)
        } else if model.measureMode {
            setMeasureMode(false)
        } else {
            select([])
        }
    }

    /// I-4: Farbe und Breite der Striche aus dem Kranz, Stift beginnt das Sprechen (Haupt- und zweiter Viewer).
    func strichStilInstallieren(_ c: ViewportCoordinator) {
        c.strichStil = { [weak self] in
            guard let v = self?.viewer else { return (ViewerStil.strich, 3) }
            return (v.strichfarbe.rgba, CGFloat(v.strichbreite))
        }
        c.stiftBeginntSprechen = { [weak self] in
            // Ohne Sitzung beginnt sie, in der Pause geht sie weiter
            guard let self, self.viewer.stiftSprechen, !self.sprache.spricht, self.model.project != nil else { return false }
            self.oberflaeche(.sprechen(true))
            return self.sprache.spricht
        }
    }

    /// Schnitt ohne die Schnittleiste der Oberfläche: quer zu Z durch die Mitte der sichtbaren Teile, bzw. aus.
    func schnittUmschalten() {
        if model.sectionEnabled {
            setSection(enabled: false, axis: "z", offset: 0)
        } else {
            let mitte = scene.visibleBounds()?.center.z ?? 0
            setSection(enabled: true, axis: "z", offset: Double(mitte))
        }
    }

    public func menueOeffnen(_ menue: ViewerMenue?) {
        guard let menue else {
            viewer.menue = nil
            return
        }
        // An der Maus (oben links gemessen), sonst in der Mitte
        let size = viewport.viewSize
        if let p = viewport.letzteMaus {
            viewer.menuePunkt = CGPoint(x: p.x, y: size.height - p.y)
        } else {
            viewer.menuePunkt = CGPoint(x: size.width / 2, y: size.height / 2)
        }
        viewer.menue = menue
    }

    // MARK: Lokale Ansicht

    public func lokaleAnsicht(hauch: Bool?) {
        if let hauch { viewer.hauch = hauch }
        toggleLocalView()
    }

    public func setHauch(_ an: Bool) { viewer.hauch = an }

    // MARK: Darstellung (Schritt 5 erweitert)

    /// Röntgen schaltet mit ⌥Z zurück auf die Darstellung davor.
    var letzteDarstellung: ShadingModus { vorRoentgen ?? .solid }

    public func setShading(_ modus: ShadingModus) {
        if modus == .roentgen, viewer.shading != .roentgen { vorRoentgen = viewer.shading }
        viewer.shading = modus
        darstellungAnwenden()
    }

    public func setShadingOption(_ option: ShadingOption, _ an: Bool) {
        var o = viewer.optionen
        option.setzen(&o, an)
        viewer.optionen = o
        darstellungAnwenden()
    }

    // MARK: Messungen kopieren

    public func messungKopieren(_ id: UUID) {
        guard let m = model.measurements.first(where: { $0.id == id }) else { return }
        zwischenablage(Self.messText(m))
        viewer.zeige("Messung kopiert")
    }

    public func messungenKopieren() {
        guard !model.measurements.isEmpty else { return }
        zwischenablage(model.measurements.map(Self.messText).joined(separator: "\n"))
        viewer.zeige("\(model.measurements.count) Messungen kopiert")
    }

    static func messText(_ m: MeasurementItem) -> String {
        m.refs.isEmpty ? m.text : m.text + " (" + m.refs.joined(separator: " ↔ ") + ")"
    }

    func zwischenablage(_ text: String) {
        Zwischenablage.setzen(text)
    }
}
