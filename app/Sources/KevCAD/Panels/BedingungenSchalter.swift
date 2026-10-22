import Foundation
import KevCADCore

/// „Bedingungen am Teil“ ein oder aus, von Kevin geschaltet (Werkzeugleiste, Menü Ansicht, Inspektor), und für den
/// nächsten Start gemerkt. Das Durchspielen des Bauplans blendet die Symbole nur vorübergehend aus und geht deshalb
/// direkt über `setConstraintSymbolsVisible`.
@MainActor
enum BedingungenSchalter {
    static let schluessel = "bedingungenAmTeil"

    static func setzen(_ model: AppModel, _ an: Bool) {
        UserDefaults.standard.set(an, forKey: schluessel)
        model.constraintActions?.setConstraintSymbolsVisible(an)
    }

    static func umschalten(_ model: AppModel) {
        setzen(model, !model.showConstraintSymbols)
    }

    /// Beim Öffnen des Projektfensters die gemerkte Wahl übernehmen (ohne gemerkte Wahl bleiben sie sichtbar).
    static func wiederherstellen(_ model: AppModel) {
        guard let an = UserDefaults.standard.object(forKey: schluessel) as? Bool, an != model.showConstraintSymbols
        else { return }
        model.constraintActions?.setConstraintSymbolsVisible(an)
    }
}
