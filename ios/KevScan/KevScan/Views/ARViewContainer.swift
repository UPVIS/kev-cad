import ARKit
import RealityKit
import SwiftUI
import UIKit

/// RealityKit-ARView mit eigener Sitzung (CaptureController) und Gesten für die Objekt-Box.
struct ARViewContainer: UIViewRepresentable {
    let controller: CaptureController

    func makeCoordinator() -> Coordinator { Coordinator(controller: controller) }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        view.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disableCameraGrain, .disableHDR,
                              .disableAREnvironmentLighting, .disableGroundingShadows, .disablePersonOcclusion]
        let coordinator = context.coordinator
        let tap = UITapGestureRecognizer(target: coordinator, action: #selector(Coordinator.tap(_:)))
        let pan = UIPanGestureRecognizer(target: coordinator, action: #selector(Coordinator.pan(_:)))
        pan.maximumNumberOfTouches = 1
        let pinch = UIPinchGestureRecognizer(target: coordinator, action: #selector(Coordinator.pinch(_:)))
        let rotation = UIRotationGestureRecognizer(target: coordinator, action: #selector(Coordinator.rotate(_:)))
        for recognizer in [tap, pan, pinch, rotation] as [UIGestureRecognizer] {
            recognizer.delegate = coordinator
            view.addGestureRecognizer(recognizer)
        }
        controller.attach(view)
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {}

    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        coordinator.controller.detach()
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        let controller: CaptureController

        init(controller: CaptureController) {
            self.controller = controller
        }

        @objc func tap(_ recognizer: UITapGestureRecognizer) {
            controller.handleTap(at: recognizer.location(in: recognizer.view))
        }

        @objc func pan(_ recognizer: UIPanGestureRecognizer) {
            controller.handlePan(recognizer.state, at: recognizer.location(in: recognizer.view))
        }

        @objc func pinch(_ recognizer: UIPinchGestureRecognizer) {
            controller.handlePinch(recognizer.state, scale: recognizer.scale)
        }

        @objc func rotate(_ recognizer: UIRotationGestureRecognizer) {
            controller.handleRotation(recognizer.state, rotation: recognizer.rotation)
        }

        func gestureRecognizerShouldBegin(_ recognizer: UIGestureRecognizer) -> Bool {
            controller.boxMode
        }

        func gestureRecognizer(_ recognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            (recognizer is UIPinchGestureRecognizer || recognizer is UIRotationGestureRecognizer)
                && (other is UIPinchGestureRecognizer || other is UIRotationGestureRecognizer)
        }
    }
}
