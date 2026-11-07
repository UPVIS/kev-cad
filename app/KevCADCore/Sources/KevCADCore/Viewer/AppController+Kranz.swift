import CoreGraphics
import Foundation

// I-4 (PLAN-IPAD.md 4.4): Werkzeugkranz im App-Kern. Öffnen an Maus, Stiftspitze oder letzter Berührung; ausführen,
// was ein Feld oder Eintrag sagt; Drehregler live anwenden. Mac und iPad sind derselbe Code.

extension AppController {
    // MARK: Öffnen

    public func kranzOeffnen(bei punkt: CGPoint?) {
        if viewer.kranz != nil {  // noch einmal Q bzw. Doppeltippen schließt
            kranzSchliessen(zuruecksetzen: true)
            return
        }
        viewer.menue = nil
        let size = viewport.viewSize
        let ort: CGPoint
        if let punkt {
            ort = punkt
        } else if let p = viewport.letzteMaus ?? viewport.letzteBeruehrung {
            ort = CGPoint(x: p.x, y: size.height - p.y)  // Eingabeebene zählt von unten
        } else {
            ort = CGPoint(x: size.width / 2, y: size.height / 2)
        }
        viewer.kranz = KranzZustand(mitte: KranzGeometrie.mitte(fuer: ort, in: size))
    }

    /// Schließt den Kranz; `zuruecksetzen`: ein offener Drehregler kehrt zum Wert beim Öffnen zurück (Esc).
    func kranzSchliessen(zuruecksetzen: Bool) {
        if zuruecksetzen, let k = viewer.kranz, case .regler(let r) = k.ebene, k.wert != k.startWert {
            kranzRegler(r, wert: k.startWert)
        }
        viewer.kranz = nil
    }

    // MARK: Ausführen

    public func kranzAusfuehren(_ aktion: KranzAktion) {
        if case .regler(let r) = aktion {
            reglerOeffnen(r)
            return
        }
        viewer.kranz = nil
        switch aktion {
        case .befehl(let b): ausfuehren(b)
        case .sprechenOderSenden:
            if sprache.offen { sprache.fertig() } else { oberflaeche(.sprechen(true)) }
        case .darstellung(let m): setShading(m)
        case .kachel(let k): oberflaeche(.kachelZeigen(k))
        case .neuRechnen: runModel()
        case .bildAnAgent: sprache.bildSenden()
        case .stiftSprechen:
            viewer.stiftSprechen.toggle()
            viewer.zeige(viewer.stiftSprechen ? "Ein Stiftstrich beginnt jetzt das Sprechen"
                         : "Der Stift dreht jetzt wie ein Finger")
        case .schwung:
            viewer.schwung.toggle()
            viewer.zeige(viewer.schwung ? "Schwung an: schnell losgelassen dreht es kurz weiter" : "Schwung aus")
        case .regler: break
        }
    }

    public func setStrichfarbe(_ farbe: Strichfarbe) {
        viewer.strichfarbe = farbe
        viewer.kranz = nil
    }

    // MARK: Drehregler

    /// Bereich und aktueller Wert eines Reglers.
    func reglerStand(_ r: KranzRegler) -> (wert: Double, bereich: KranzReglerBereich) {
        switch r {
        case .explosion:
            return (model.explodeFactor, KranzReglerBereich(min: 0, max: 1, raster: 0.05))
        case .schnitt:
            let b = scene.visibleBounds()
            let unten = Double(b?.min.z ?? 0), oben = Double(b?.max.z ?? 100)
            // ClipPlane mit Normale −Z: Abstand = Höhe der Ebene (SceneStore.setSection)
            let jetzt = scene.section.map { Double($0.distance) } ?? (unten + oben) / 2
            return (jetzt, KranzReglerBereich(min: unten.rounded(.down), max: oben.rounded(.up), raster: 1))
        case .strichbreite:
            return (viewer.strichbreite, ViewerStore.strichbreiten)
        case .roentgen:
            return (Double(scene.roentgenDeckkraft), KranzReglerBereich(min: 0.1, max: 0.9, raster: 0.05))
        case .animation:
            return (model.animation.time, KranzReglerBereich(min: 0, max: model.animation.duration, raster: 1.0 / 30))
        case .zoomZweite:
            return (0, KranzReglerBereich(min: -2, max: 2, raster: 0.1))
        }
    }

    private func reglerOeffnen(_ r: KranzRegler) {
        guard var k = viewer.kranz else { return }
        // Was es gerade nicht gibt, öffnet kein leeres Ziffernblatt
        if r == .animation, model.animation.duration <= 0 {
            viewer.kranz = nil
            viewer.zeige("Es ist keine Animation geladen.")
            return
        }
        if r == .zoomZweite, !model.oberflaeche.zustand.zweiteAnsichtSichtbar {
            viewer.kranz = nil
            viewer.zeige("Die zweite Ansicht ist nicht offen.")
            return
        }
        let (wert, bereich) = reglerStand(r)
        k.ebene = .regler(r)
        k.bereich = bereich
        k.wert = bereich.klemmen(wert)
        k.roh = k.wert
        k.startWert = k.wert
        k.markiert = nil
        k.letzterWinkel = nil
        viewer.kranz = k
    }

    /// Pencil Pro: Rollen dreht einen offenen Drehregler ohne Kreisen (eine Umdrehung = der ganze Bereich, wie Kreisen).
    /// `winkel` im Bogenmaß, nil = der Stift ist weg.
    func kranzRollen(_ winkel: Double?) -> Bool {
        guard var k = viewer.kranz, case .regler(let r) = k.ebene else { return false }
        guard let winkel else {
            k.letzteRolle = nil
            viewer.kranz = k
            return false
        }
        let grad = winkel * 180 / .pi
        if let alt = k.letzteRolle {
            k.roh = KranzGeometrie.reglerWert(k.roh, grad: KranzGeometrie.winkelSchritt(von: alt, nach: grad),
                                              bereich: k.bereich)
            let neu = k.bereich.klemmen(k.roh)
            if neu != k.wert {
                kranzRegler(r, wert: neu)  // vor dem Setzen: der Zoom rechnet mit dem alten Wert
                k.wert = neu
            }
        }
        k.letzteRolle = grad
        viewer.kranz = k
        return true
    }

    public func kranzRegler(_ regler: KranzRegler, wert: Double) {
        switch regler {
        case .explosion: setExplode(wert)
        case .schnitt: setSection(enabled: true, axis: "z", offset: wert)
        case .strichbreite: viewer.strichbreite = ViewerStore.strichbreiten.klemmen(wert)
        case .roentgen:
            if viewer.shading != .roentgen { setShading(.roentgen) }
            scene.setRoentgenDeckkraft(Float(wert))
            UserDefaults.standard.set(Double(scene.roentgenDeckkraft), forKey: ViewerStore.roentgenKey)
        case .animation: seekAnimation(to: wert)
        case .zoomZweite:
            // Der Kranz hält noch den vorigen Wert (die Ansicht setzt ihn erst nach diesem Aufruf): Zoom als Verhältnis
            let alt = viewer.kranz?.wert ?? 0
            let z = zweiterViewer.coordinator
            z.navZoom(factor: Float(pow(2, alt - wert)), zu: CGPoint(x: z.viewSize.width / 2, y: z.viewSize.height / 2))
        }
    }
}
