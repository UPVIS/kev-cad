import CoreGraphics
import Foundation

/// Vorschaubilder für den Bereich „Material“ (additiv): dieselben Bilder wie in den Berichten (isometrisch, weißer
/// Grund, 260 Pixel), aus demselben Zwischenspeicher je Teil und Formstand. Implementiert vom App-Kern; die Oberfläche
/// ruft sie über `model.materialBildActions` auf (im Demomodus nicht vorhanden, dann zeigt sie das Symbol der Art).
@MainActor
public protocol MaterialBildActions: AnyObject {
    /// Bilder der genannten Teile; Teile ohne Geometrie fehlen im Ergebnis.
    func materialBilder(_ teile: [String]) async -> [String: CGImage]
}

extension AppModel {
    public var materialBildActions: MaterialBildActions? { actions as? MaterialBildActions }
}

extension AppController: MaterialBildActions {
    public func materialBilder(_ teile: [String]) async -> [String: CGImage] {
        // Kleine Schritte, damit die Oberfläche beim ersten Öffnen flüssig bleibt
        await exportTeilBilder(teile, nachJeweils: 3)
    }
}
