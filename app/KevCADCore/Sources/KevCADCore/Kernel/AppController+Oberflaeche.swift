import CoreGraphics
import Foundation
import OCCTSwiftViewport

// V2-3 (OBERFLAECHE.md): Aktionen der Oberfläche und das Bild für die Kachel „zweite Ansicht“.
//
// Die Befehle ändern heute nur den Zustand in `AppModel.oberflaeche`. Später setzt hier V2-6 die Spracherkennung an
// (`.sprechen`) und V2-7 meldet Kacheln und Modus an den Kernel.

extension AppController: OberflaechenActions {
    public func oberflaeche(_ befehl: Oberflaechenbefehl) {
        model.oberflaeche.ausfuehren(befehl)
    }

    /// Bild einer Standardansicht, eingepasst auf alles Sichtbare, ohne Kevins Kamera, Darstellung und Auswahl zu
    /// ändern (Kachel „zweite Ansicht“). Platzhalter, bis V2-4 eine zweite, lebende Ansicht liefert. Rechnet auf dem
    /// Hauptfaden (eigener Offscreen-Renderer mit dunklem Grund); die Oberfläche ruft es nur nach einem Lauf und bei
    /// einer neuen Größe der Kachel.
    public func zweiteAnsicht(_ ansicht: StandardViewName, breite: Int, hoehe: Int) -> CGImage? {
        guard !scene.isEmpty else { return nil }
        let w = max(16, min(breite, 2048)), h = max(16, min(hoehe, 2048))
        let name = Self.protokollName(ansicht)
        var camera = Self.ansichtKamera(.object(["standard": .string(name)]), scene: scene,
                                        aspect: Float(w) / Float(h))
        if ansicht != .iso && ansicht != .isoFrontLeft && ansicht != .isoBackLeft && ansicht != .isoBackRight {
            camera.isOrthographic = true
        }
        let r = zweiteAnsichtRenderer.render(
            bodies: scene.snapshotBodies(), camera: camera, width: w, height: h, displayMode: .shadedWithEdges,
            lighting: viewport.controller.lightingConfiguration, overlay: [])
        return r?.image
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

/// Eigener Renderer für die zweite Ansicht (dunkler Grund wie Graphit), getrennt von den Bildern für den Agenten.
@MainActor
private enum ZweiteAnsichtSpeicher {
    static let renderer: ScreenshotRenderer = {
        let r = ScreenshotRenderer()
        r.backgroundColor = SIMD4<Float>(0.18, 0.19, 0.20, 1)
        return r
    }()
}

extension AppController {
    fileprivate var zweiteAnsichtRenderer: ScreenshotRenderer { ZweiteAnsichtSpeicher.renderer }
}

extension AppController {
    /// Hat das automatische Update einen Neustart mit Wiederherstellen angefordert? Die Oberfläche fragt das vor
    /// `start()` ab (dort wird die Marke gelöscht) und legt dann kein leeres Projekt an.
    public static var wiederherstellenAngefordert: Bool {
        FileManager.default.fileExists(atPath: relaunchMarker.path)
    }
}
