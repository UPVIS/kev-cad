import Foundation
import OCCTSwiftViewport

// V2-3 (OBERFLAECHE.md): Aktionen der Oberfläche. Die Befehle ändern den Zustand in `AppModel.oberflaeche`; Sprechen
// steuert die Sitzung (V2-6, SprachSteuerung), der Agent stellt die Fläche über `VIEW_CMD flaeche`
// (AppController+Flaeche.swift).

extension AppController: OberflaechenActions {
    public func oberflaeche(_ befehl: Oberflaechenbefehl) {
        switch befehl {
        case .sprechen(let an): sprache.umschalten(an: an)
        case .sprechenFertig: sprache.fertig()
        case .sprechenVerwerfen: sprache.verwerfen()
        case .sprechText(let t):
            model.sprache.text = t
            model.oberflaeche.ausfuehren(befehl)
        case .zweiteAnsicht:
            model.oberflaeche.ausfuehren(befehl)
            zweiteAnsichtNeu()
        default: model.oberflaeche.ausfuehren(befehl)
        }
    }

    static func protokollName(_ v: StandardViewName) -> String {
        switch v {
        case .top: return "top"
        case .bottom: return "bottom"
        case .front: return "front"
        case .back: return "back"
        case .left: return "left"
        case .right: return "right"
        case .iso: return "iso"
        case .isoFrontLeft: return "iso_front_left"
        case .isoBackRight: return "iso_back_right"
        case .isoBackLeft: return "iso_back_left"
        }
    }
}

extension AppController {
    /// Hat das automatische Update einen Neustart mit Wiederherstellen angefordert? Die Oberfläche fragt das vor
    /// `start()` ab (dort wird die Marke gelöscht) und legt dann kein leeres Projekt an.
    public static var wiederherstellenAngefordert: Bool {
        FileManager.default.fileExists(atPath: relaunchMarker.path)
    }
}
