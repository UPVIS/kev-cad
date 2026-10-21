import KevCADCore
import SwiftUI

/// Zustand eines Projektfensters, der nur die Oberfläche betrifft (Seitenleisten, Schnittregler, Popover).
///
/// Über `focusedSceneObject` erreichen auch die Menübefehle diesen Zustand; ist er `nil`, ist das Projektfenster nicht
/// vorne, und die einbuchstabigen Kürzel sind abgeschaltet.
@MainActor
final class ProjectWindowState: ObservableObject {
    @Published var showInspector = true
    @Published var showExplode = false
    @Published var searchText = ""
    /// Fehlerband für diesen Lauf weggeklickt.
    @Published var dismissedErrorRun: Int?
    /// Band „Nicht aus dem Inventar“ für diese Verstöße weggeklickt.
    @Published var dismissedInventory: String?
    /// Band der Prüfung (Durchdringungen …) für diese Befunde weggeklickt; Liste der Befunde aufgeklappt.
    @Published var dismissedPruefung: String?
    @Published var pruefListeOffen = false

    // Schnitt: AppModel kennt nur `sectionEnabled`, Achse und Lage hält die Oberfläche.
    @Published var sectionAxis = "z"
    @Published var sectionOffset: Double = 0

    /// Letzter Explosionswert, damit E wieder dorthin springt.
    var lastExplode: Double = 0.6

    // MARK: Stückliste (Phase 2)

    /// Bereich „Stückliste“ unter dem Viewport; bleibt über Neustarts hinweg so, wie er zuletzt war.
    @Published var showBOM = UserDefaults.standard.bool(forKey: "showBOM") {
        didSet { UserDefaults.standard.set(showBOM, forKey: "showBOM") }
    }
    @Published var bomHeight: CGFloat = {
        let stored = UserDefaults.standard.double(forKey: "bomHeight")
        return stored >= 160 ? stored : 390
    }() {
        didSet { UserDefaults.standard.set(Double(bomHeight), forKey: "bomHeight") }
    }
    /// Die Stückliste hat sich in diesem Fenster schon einmal von selbst geöffnet (nur beim ersten Mal).
    var bomAutoShown = false

    static let bomHeightRange: ClosedRange<CGFloat> = 160...720

    // MARK: Schnitt

    static let axes = ["x", "y", "z"]

    func sectionRange(_ model: AppModel, axis: String? = nil) -> ClosedRange<Double> {
        guard let bounds = model.sceneBounds else { return -50...50 }
        let index = Self.axes.firstIndex(of: axis ?? sectionAxis) ?? 2
        let lo = Double(bounds.min[index])
        let hi = Double(bounds.max[index])
        return lo < hi ? lo...hi : (lo - 1)...(hi + 1)
    }

    func toggleSection(_ model: AppModel) {
        let enable = !model.sectionEnabled
        if enable {
            let range = sectionRange(model)
            if !range.contains(sectionOffset) || sectionOffset == 0 {
                sectionOffset = (range.lowerBound + range.upperBound) / 2
            }
        }
        model.actions?.setSection(enabled: enable, axis: sectionAxis, offset: sectionOffset)
    }

    /// Schnitt wurde von außen eingeschaltet (Agent, Menü): Lage für die Anzeige auf die Mitte setzen, falls unbekannt.
    /// AppModel meldet Achse und Lage nicht (Wunsch an den App-Kern), daher nur eine Annahme ohne Aktion.
    func adoptSectionIfUnknown(_ model: AppModel) {
        let range = sectionRange(model)
        if !range.contains(sectionOffset) || sectionOffset == 0 {
            sectionOffset = (range.lowerBound + range.upperBound) / 2
        }
    }

    func setSectionAxis(_ axis: String, _ model: AppModel) {
        sectionAxis = axis
        let range = sectionRange(model)
        sectionOffset = (range.lowerBound + range.upperBound) / 2
        applySection(model)
    }

    func applySection(_ model: AppModel) {
        model.actions?.setSection(enabled: true, axis: sectionAxis, offset: sectionOffset)
    }

    // MARK: Explosion

    func toggleExplode(_ model: AppModel) {
        if model.explodeFactor > 0 {
            lastExplode = model.explodeFactor
            model.actions?.setExplode(0)
        } else {
            model.actions?.setExplode(lastExplode > 0 ? lastExplode : 0.6)
        }
    }
}
