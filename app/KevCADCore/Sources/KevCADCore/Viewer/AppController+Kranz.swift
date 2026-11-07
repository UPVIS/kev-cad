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
        case .stiftSprechen:
            viewer.stiftSprechen.toggle()
            viewer.zeige(viewer.stiftSprechen ? "Ein Stiftstrich beginnt jetzt das Sprechen"
                         : "Der Stift dreht jetzt wie ein Finger")
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
        }
    }

    private func reglerOeffnen(_ r: KranzRegler) {
        guard var k = viewer.kranz else { return }
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

    public func kranzRegler(_ regler: KranzRegler, wert: Double) {
        switch regler {
        case .explosion: setExplode(wert)
        case .schnitt: setSection(enabled: true, axis: "z", offset: wert)
        case .strichbreite: viewer.strichbreite = ViewerStore.strichbreiten.klemmen(wert)
        }
    }
}
