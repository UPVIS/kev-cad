import OCCTSwiftViewport
import SwiftUI

// STUB aus der Vertragsphase. Zuständig: App-Kern. Die Signatur `KevViewport(controller:)` bleibt stabil.

/// Der 3D-Bereich des Projektfensters.
public struct KevViewport: View {
    @ObservedObject private var model: AppModel
    private let controller: AppController
    @StateObject private var viewport: ViewportController = {
        var cfg = ViewportConfiguration.cad
        cfg.pickingConfiguration = PickingConfiguration(isEnabled: true)
        return ViewportController(configuration: cfg)
    }()
    @State private var bodies: [ViewportBody] = []

    public init(controller: AppController) {
        self.controller = controller
        self._model = ObservedObject(wrappedValue: controller.model)
    }

    public var body: some View {
        MetalViewportView(controller: viewport, bodies: $bodies)
    }
}
