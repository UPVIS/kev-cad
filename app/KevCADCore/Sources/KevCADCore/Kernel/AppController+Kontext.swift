import Foundation
import OCCTSwiftViewport

// V2-10 (Kevin, 06.11.2026: „Auch die Zeichnungen sollen dann immer kontextbasiert switchen, während man erklärt“): Das
// Blatt der Kachel Zeichnung folgt dem, wovon gerade die Rede ist:
// - Kevin wählt ein Teil oder eine Baugruppe (Viewer, zweiter Viewer, Objekte, Agent mit `select`),
// - der Agent zeigt etwas mit `view(focus=…)` oder hebt es hervor,
// - Kevin zeigt beim Sprechen eine gute halbe Sekunde auf ein Teil.
// Welches Blatt passt, rechnet `Blattwahl`. Hält Kevin das Blatt fest (Nadel im Kopf der Kachel), bleibt es stehen.

extension AppController {
    /// Wie lange Kevin beim Sprechen auf ein Teil zeigen muss, bis das Blatt folgt: kurz genug für „das hier“, lang genug,
    /// dass ein Überstreichen auf dem Weg zum Ziel nichts umschaltet.
    static let kontextVerweilen: TimeInterval = 0.6

    /// Die Auswahl hat sich geändert.
    func blattZurAuswahl() {
        var gesehen = Set<String>()
        let teile = scene.selection.map(\.part).filter { gesehen.insert($0).inserted }
        blattZumKontext(teile: teile)
    }

    /// Blatt zu Teil- oder Baugruppennamen (auch Elementen wie „Rohr#f3“) wählen, sofern die Kachel Zeichnung offen ist,
    /// es Blätter gibt und Kevin das Blatt nicht festhält.
    func blattZumKontext(teile ids: [String]) {
        let z = model.oberflaeche.zustand
        guard z.blattFolgt, z.kacheln.contains(.zeichnung), !ids.isEmpty,
            let blaetter = model.dokumente.uebersicht?.blaetter, !blaetter.isEmpty
        else { return }
        let namen = scene.expand(ids.compactMap(ElementRef.init).map(\.partRef)).known.map(\.part)
        let gleiche = model.bom?.lines.map(\.teile) ?? []
        guard let id = Blattwahl.blatt(fuer: namen, in: blaetter, gleiche: gleiche), id != z.blatt else { return }
        oberflaeche(.blatt(id))
    }

    /// Maus über einem Teil (Haupt- oder zweiter Viewer). Nur während einer Sprechsitzung: Bleibt die Maus
    /// `kontextVerweilen` auf demselben Teil, folgt das Blatt.
    func kontextZeigen(_ pick: PickResult?) {
        guard model.oberflaeche.sitzungOffen else {
            if kontextAuftrag != nil {
                kontextAuftrag?.cancel()
                kontextAuftrag = nil
                kontextTeil = nil
            }
            return
        }
        let teil = pick.flatMap { scene.resolve($0)?.part }
        guard teil != kontextTeil else { return }
        kontextTeil = teil
        kontextAuftrag?.cancel()
        guard let teil else {
            kontextAuftrag = nil
            return
        }
        let auftrag = DispatchWorkItem { [weak self] in
            guard let self, self.kontextTeil == teil, self.model.oberflaeche.sitzungOffen else { return }
            self.blattZumKontext(teile: [teil])
        }
        kontextAuftrag = auftrag
        DispatchQueue.main.asyncAfter(deadline: .now() + Self.kontextVerweilen, execute: auftrag)
    }
}
