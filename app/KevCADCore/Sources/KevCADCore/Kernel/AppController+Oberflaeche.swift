import Foundation
import OCCTSwiftViewport

// V2-3 (OBERFLAECHE.md): Aktionen der Oberfläche. Die Befehle ändern den Zustand in `AppModel.oberflaeche`; der Agent
// erreicht sie über `VIEW_CMD flaeche` (AppController+Flaeche.swift). Hier setzt V2-6 die Spracherkennung an (`.sprechen`).

extension AppController: OberflaechenActions {
    public func oberflaeche(_ befehl: Oberflaechenbefehl) {
        model.oberflaeche.ausfuehren(befehl)
        if case .zweiteAnsicht = befehl { zweiteAnsichtNeu() }
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
