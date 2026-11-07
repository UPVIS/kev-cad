#if os(macOS)
import AppKit
#endif
import Combine
import Foundation
import OCCTSwiftViewport
import simd

// V2-10: zweiter Viewer (Viewer/ZweiterViewer.swift) im App-Kern. Klicks, Rahmen, Kontextmenü, Ziffernblock und die
// Befehle der Belegung laufen über dieselben Wege wie im Hauptviewer; Kamerabefehle wirken im Viewer unter der Maus.
// Lagebild und Sprachpaket beziehen Bildpunkte immer auf das Bild des Hauptviewers: Punkte aus dem zweiten Viewer werden
// dafür über ihren Weltpunkt umgerechnet.

extension AppController {
    /// Viewer unter dem Mauszeiger: Tasten, Ziffernblock, Einpassen und Messen wirken wie in Blender dort. Steht die Maus
    /// nicht über dem zweiten Viewer, ist es der Hauptviewer (auch für Menübefehle, die man mit der Maus wählt).
    var eingabeViewport: ViewportCoordinator {
        let z = zweiterViewer.coordinator
        return zweiterViewer.aktiv && z.letzteMaus != nil ? z : viewport
    }

    func installZweiterViewer() {
        zweiterViewer.spiegeln(von: viewport)
        zweiterViewer.beiAktiv = { [weak self] in self?.zweiteAnsichtErscheint() }
        model.oberflaeche.$zustand
            .map(\.zweiteAnsichtSichtbar)
            .removeDuplicates()
            .sink { [weak self] an in self?.zweiterViewer.setSichtbar(an) }
            .store(in: &navCancellables)
        let z = zweiterViewer.coordinator
        z.onClick = { [weak self] pick, modifiers in self?.handleClick(pick, modifiers: modifiers) }
        z.onBoxSelect = { [weak self] picks, modifiers in self?.handleBoxSelect(picks, modifiers: modifiers) }
        z.onKontextmenue = { [weak self] treffer in self?.kontextEintraege(treffer: treffer) ?? [] }
        z.verlaufTitel = { [weak self] befehl in self?.verlaufTitel(befehl) }
        #if os(macOS)  // iPad: Ziffernblock über pressesBegan und die Belegung
        z.onNumpadKey = { [weak self] code, flags in self?.handleNumpadKey(code, flags) ?? false }
        #endif
        z.onBefehl = { [weak self] befehl in
            guard let self else { return false }
            self.ausfuehren(befehl)
            return true
        }
        z.onHover = { [weak self] pick, welt, bildpunkt in self?.zweiterHover(pick, welt, bildpunkt) }
        z.onStrich = { [weak self] e in self?.zweiterStrich(e) }
        strichStilInstallieren(z)
    }

    /// Beim Sprechen zeichnet Ziehen mit der linken Maustaste in beiden Viewern einen Strich.
    func zeichnenSetzen(_ an: Bool) {
        viewport.zeichnen = an
        zweiterViewer.coordinator.zeichnen = an
    }

    /// Weltpunkt → Bildpunkt im Hauptviewer (Ursprung oben links), nil hinter dessen Kamera.
    func imHauptbild(_ welt: SIMD3<Float>?) -> CGPoint? {
        guard let welt, let p = viewport.bildpunkt(welt) else { return nil }
        return CGPoint(x: p.x, y: viewport.viewSize.height - p.y)
    }

    /// Text des Messmodus unter der Maus: im Viewer, über dem sie steht; der andere zeigt keinen.
    func unterMausSetzen(_ text: String?) {
        let ort = eingabeViewport
        for c in [viewport, zweiterViewer.coordinator] {
            let neu = c === ort ? text : nil
            if c.eingabe.unterMaus != neu { c.eingabe.unterMaus = neu }
        }
    }

    // MARK: Maus und Striche im zweiten Viewer

    private func zweiterHover(_ pick: PickResult?, _ welt: SIMD3<Float>?, _ bildpunkt: CGPoint?) {
        hoverGeaendert(pick, welt, bildpunkt)  // misst mit Kamera und Größe des zweiten Viewers (eingabeViewport)
        sprache.maus(pick, welt, bildpunkt == nil ? nil : imHauptbild(welt))  // worauf Kevin beim Sprechen zeigt
    }

    /// Striche beim Sprechen: Weltpunkte aus dem zweiten Viewer (Treffer oder Ebene durch den letzten Treffer), Bildpunkte
    /// umgerechnet ins Bild des Hauptviewers, auf das sich das Paket bezieht.
    private func zweiterStrich(_ e: StrichEreignis) {
        let z = zweiterViewer.coordinator
        switch e {
        case .beginn:
            zweiterViewer.strichAnker = nil
            sprache.strich(e)
        case .ende:
            sprache.strich(e)
        case .punkt(let eingabe, _, let zeit, let treffer, let welt):
            if let welt { zweiterViewer.strichAnker = welt }
            guard let ort = welt ?? z.weltpunkt(eingabe, durch: zweiterViewer.strichAnker ?? z.camera.pivot) else { return }
            let bild = imHauptbild(ort) ?? CGPoint(x: -1, y: -1)
            let unten = CGPoint(x: bild.x, y: viewport.viewSize.height - bild.y)
            sprache.strich(.punkt(eingabe: unten, bild: bild, zeit: zeit, treffer: treffer, welt: ort))
        }
    }
}
