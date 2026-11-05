import AppKit
import Foundation
import OCCTSwiftViewport
import simd

// Darstellung des Viewports (V2, Schritt 5): Solid, Material, Röntgen, Drahtgitter, Technisch und ihre Schalter
// (Umgebungsverdeckung, Kantenbetonung, Schatten, Umriss der Auswahl, Kanten). Verdeckung und Kantenbetonung rechnet
// die lokale Kopie von OCCTSwiftViewport (app/Packages, KEVCAD-AENDERUNGEN.md).

extension AppController {
    /// Darstellung aus `AppModel.viewer` auf Szene und Viewport anwenden.
    func darstellungAnwenden() {
        let modus = viewer.shading
        let o = viewer.optionen
        let flaechen = modus == .solid || modus == .material || modus == .technisch

        // Szene: Röntgen, Drahtgitter und Kanten über DisplayStyle; Farben je Darstellung
        let style: DisplayStyle
        switch modus {
        case .roentgen: style = .xray
        case .drahtgitter: style = .wireframe
        case .technisch: style = .shadedEdges
        case .solid, .material: style = o.kanten ? .shadedEdges : .shaded
        }
        scene.setDisplayStyle(style)
        scene.setFarbmodus(modus == .technisch ? .technisch : (modus == .material ? .material : .normal))
        viewport.controller.displayMode = scene.viewportDisplayMode
        model.displayStyle = style

        // Licht
        var licht: LightingConfiguration
        switch modus {
        case .material: licht = Self.materialLicht
        case .technisch: licht = Self.technischLicht
        default: licht = ViewportCoordinator.zUpLighting
        }
        let skala = Float(viewport.mtkView?.window?.backingScaleFactor ?? 2)
        licht.enableSSAO = o.umgebungsverdeckung && flaechen
        licht.ssaoIntensity = modus == .technisch ? 0.35 : 0.6
        licht.kevAORadiusPixels = 16 * skala
        licht.kevCavityIntensity = o.kantenbetonung && flaechen ? (modus == .technisch ? 0.5 : 0.85) : 0
        licht.shadowsEnabled = o.schatten && (modus == .solid || modus == .material)
        licht.shadowIntensity = 0.32
        viewport.controller.lightingConfiguration = licht

        // Konfiguration: Silhouetten (Umrisse runder Flächen), Hintergrund, Kantenlinien
        var cfg = viewport.controller.configuration
        cfg.enableSilhouettes = flaechen && (o.kanten || modus == .technisch)
        cfg.silhouetteIntensity = modus == .technisch ? 1.0 : 0.55
        cfg.silhouetteThickness = modus == .technisch ? 1.5 : 1.0
        cfg.edgeLineConfiguration.width = modus == .technisch ? 1.5 : 1.0
        cfg.backgroundColor = modus == .technisch ? SIMD4(1, 1, 1, 1) : Self.hintergrund
        // Technisch immer auf Weiß, sonst wie bisher (im Dunkelmodus Dunkelgrau)
        cfg.backgroundFollowsAppearance = modus != .technisch
        viewport.controller.configuration = cfg

        // Umriss der Auswahl
        viewport.controller.selectedBodyIDs = o.umriss ? scene.outlinedBodyIDs : []
    }

    /// Körper-IDs für den Umriss des Viewports (Schalter „Umriss der Auswahl“).
    var umrissKoerper: Set<String> { viewer.optionen.umriss ? scene.outlinedBodyIDs : [] }

    /// Hintergrund wie bisher (ViewportConfiguration.cad).
    static let hintergrund = SIMD4<Float>(0.95, 0.95, 0.95, 1)
    /// Hintergrund des Pakets im Dunkelmodus.
    static let hintergrundDunkel = SIMD4<Float>(0.12, 0.12, 0.12, 1)

    /// Hintergrund, den der Viewport gerade zeigt (Dunkelmodus beachtet), für Bildschirmfoto und Video.
    var wirksamerHintergrund: SIMD4<Float> {
        let cfg = viewport.controller.configuration
        let dunkel = (viewport.mtkView?.effectiveAppearance ?? NSApp.effectiveAppearance)
            .bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        return dunkel && cfg.backgroundFollowsAppearance ? Self.hintergrundDunkel : cfg.backgroundColor
    }

    /// Material: physikalisch basiert mit Umgebungsbild (Halle, CC0 aus den Renderings), sonst wie Solid.
    static var materialLicht: LightingConfiguration {
        var l = ViewportCoordinator.zUpLighting
        if let hdr = umgebungsbild("halle") { l.environmentMapURL = hdr }
        l.environmentIntensity = 0.9
        l.drawBackground = false
        l.keyLight.intensity = 0.8
        l.fillLight.intensity = 0.25
        l.backLight.intensity = 0.25
        l.specularIntensity = 0.6
        l.exposure = 1.25
        return l
    }

    /// Technisch: gleichmäßiges, fast schattenloses Licht; die Linien tragen die Form.
    static var technischLicht: LightingConfiguration {
        var l = ViewportCoordinator.zUpLighting
        l.keyLight.intensity = 0.45
        l.fillLight.intensity = 0.3
        l.backLight.intensity = 0.15
        l.ambientIntensity = 0.75
        l.specularIntensity = 0.05
        l.fresnelIntensity = 0
        l.exposure = 1.15
        return l
    }

    /// HDR-Umgebung aus kernel/src/kevcad_kernel/render/umgebungen (Repo oder Installation).
    static func umgebungsbild(_ name: String) -> URL? {
        guard let repo = AppInfo.repoDirectory else { return nil }
        let url = repo.appendingPathComponent("kernel/src/kevcad_kernel/render/umgebungen/\(name).hdr")
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    /// Darstellungsart von außen (VIEW_CMD `display`, Menü „Darstellung“ der Oberfläche) in den Viewer übernehmen.
    func darstellungUebernehmen(_ style: DisplayStyle) {
        switch style {
        case .xray: viewer.shading = .roentgen
        case .wireframe: viewer.shading = .drahtgitter
        case .shaded, .shadedEdges:
            if viewer.shading == .roentgen || viewer.shading == .drahtgitter { viewer.shading = .solid }
            viewer.optionen.kanten = style == .shadedEdges
        }
        darstellungAnwenden()
    }
}
