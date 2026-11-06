#if os(macOS)
import AppKit
#endif
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

// Weiche Kamerafahrten (Blender „Smooth View“, rund 0,2 s) im Takt des Bildschirms (120 Hz auf ProMotion) statt über
// den 60-Hz-Timer des Pakets. Ein Wechsel zwischen perspektivisch und parallel gleitet über den Öffnungswinkel: die
// Sichthöhe am Drehpunkt bleibt, der Winkel läuft gegen 1°, erst am Ende schaltet die Projektion um.

/// Eine laufende Fahrt.
struct Kamerafahrt {
    var start: CameraState
    var ziel: CameraState
    var dauer: CFTimeInterval
    var beginn: CFTimeInterval

    /// Öffnungswinkel, bei dem eine Perspektive wie parallel aussieht (Grad).
    static let fastParallel: Float = 1

    /// Sichthöhe am Drehpunkt (mm): parallel die Bildhöhe, perspektivisch die Höhe des Sichtkegels in Drehpunktabstand.
    static func sichthoehe(_ c: CameraState) -> Float {
        c.isOrthographic ? c.orthographicScale : 2 * c.distance * tan(c.fieldOfView * .pi / 360)
    }

    /// Weich ein- und auslaufen (kubisch).
    static func weich(_ t: Double) -> Float {
        let x = min(max(t, 0), 1)
        return Float(x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2)
    }

    /// Zwischenstand bei `t` (0…1, schon geglättet).
    static func zwischen(_ a: CameraState, _ b: CameraState, _ t: Float) -> CameraState {
        if t >= 1 { return b }
        if t <= 0 { return a }
        var c = b
        c.rotation = simd_slerp(a.rotation, b.rotation, t)
        c.pivot = a.pivot + (b.pivot - a.pivot) * t
        c.panOffset = a.panOffset + (b.panOffset - a.panOffset) * t
        let ha = max(sichthoehe(a), 1e-4), hb = max(sichthoehe(b), 1e-4)
        let h = exp(log(ha) + (log(hb) - log(ha)) * t)
        if a.isOrthographic && b.isOrthographic {
            c.isOrthographic = true
            c.orthographicScale = h
            c.distance = a.distance + (b.distance - a.distance) * t
            return c
        }
        let fa = a.isOrthographic ? fastParallel : a.fieldOfView
        let fb = b.isOrthographic ? fastParallel : b.fieldOfView
        let f = fa + (fb - fa) * t
        c.isOrthographic = false
        c.fieldOfView = f
        c.distance = h / (2 * tan(f * .pi / 360))
        // Der Öffnungswinkel des Ziels bleibt für den Rückweg erhalten
        if b.isOrthographic { c.orthographicScale = b.orthographicScale }
        return c
    }
}

/// Ziel für den Bildschirmtakt (NSView.displayLink bzw. CADisplayLink braucht ein NSObject).
final class FahrtTakt: NSObject {
    weak var coordinator: ViewportCoordinator?

    @objc func schritt(_ link: CADisplayLink) {
        MainActor.assumeIsolated { coordinator?.fahrtSchritt(link.targetTimestamp) }
    }
}

extension ViewportCoordinator {
    /// Läuft gerade eine Fahrt (eigene oder die des Pakets)?
    public var kameraBewegtSich: Bool { fahrt != nil || controller.isAnimating }

    /// Weich zur Kamera `ziel` fahren; `dauer` 0 setzt sofort.
    public func fahre(zu ziel: CameraState, dauer: Double = ViewerStil.kamerafahrt) {
        controller.cameraController.cancelAnimation()
        guard dauer > 0, let view = mtkView else {
            fahrt = nil
            controller.animateTo(ziel, duration: 0)
            return
        }
        mausPunkt = nil
        fahrt = Kamerafahrt(start: controller.cameraState, ziel: ziel, dauer: dauer, beginn: CACurrentMediaTime())
        if fahrtLink == nil {
            let takt = FahrtTakt()
            takt.coordinator = self
            let link = view.bildschirmtakt(takt, #selector(FahrtTakt.schritt(_:)))
            link.add(to: .main, forMode: .common)
            fahrtLink = link
            fahrtTakt = takt
        }
        fahrtLink?.isPaused = false
    }

    /// Laufende Fahrt abbrechen (Eingabe des Nutzers hat Vorrang).
    func fahrtAbbrechen() {
        fahrt = nil
        fahrtLink?.isPaused = true
        controller.cameraController.cancelAnimation()
    }

    func fahrtSchritt(_ jetzt: CFTimeInterval) {
        guard let f = fahrt else {
            fahrtLink?.isPaused = true
            return
        }
        let t = (jetzt - f.beginn) / max(f.dauer, 1e-3)
        let c = Kamerafahrt.zwischen(f.start, f.ziel, Kamerafahrt.weich(t))
        controller.animateTo(c, duration: 0)
        onKameraGesetzt?(c)
        if t >= 1 {
            fahrt = nil
            fahrtLink?.isPaused = true
            onFahrtEnde?()
            hoverAuffrischen()
        }
    }
}
