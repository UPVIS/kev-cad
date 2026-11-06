import AppKit
import Combine
import MetalKit
import OCCTSwiftViewport
import SwiftUI
import simd

// V2-10 (Kevin, 06.11.2026, nach der Abnahme von V2): „dass man auch beliebig die anderen Ansichten, egal welche das
// sind, zoomen kann … in Blender auch so, dass das auch eine 3D-Ansicht sein könnte, die die gleichen Controls hat …
// Man soll drin messen können, soll drin zeichnen können, soll drin arbeiten können.“
//
// Die Kachel „Zweite Ansicht“ war bis dahin ein Bild, das der App-Kern im Hintergrund rechnete. Jetzt ist sie ein zweiter
// Viewer mit eigener Kamera. Körper, Darstellung, Schnitt, Umriss der Auswahl und die Überlagerung (Maße, Striche,
// Anmerkungen) übernimmt er vom Hauptviewer; Maus, Trackpad und Tasten wirken wie dort (BlenderNavigation.swift).
// Auswahl, Messungen und Striche sind dieselben, gleich in welchem Viewer sie entstehen. Tasten wirken wie in Blender im
// Viewer unter dem Mauszeiger (`AppController.eingabeViewport`). Gezeichnet wird nur, wenn sich etwas ändert: Ein
// stehender zweiter Viewer kostet keine Rechenzeit.

/// Zweiter Viewer der Kachel „Zweite Ansicht“; gehört dem `AppController` und überlebt das Schließen der Kachel (die
/// Kamera bleibt, wie Kevin sie verlassen hat).
@MainActor
public final class ZweiterViewer {
    public let coordinator: ViewportCoordinator
    /// Die Ansicht ist eingehängt (bleibt es auch, wenn die Kachelfläche verborgen ist).
    public private(set) var offen = false
    /// Laut Oberfläche zu sehen (`OberflaechenZustand.zweiteAnsichtSichtbar`).
    public private(set) var sichtbar = false
    /// Eingehängt und zu sehen: nimmt Eingaben an und zeichnet.
    public var aktiv: Bool { offen && sichtbar }
    /// Bildanforderungen, solange er aktiv ist (Lagebild `statistik.zweite_ansicht`, Selbsttest).
    public private(set) var bilder = 0
    /// Wird aktiv: Kamera stellen, falls sie noch nicht steht (AppController+Flaeche.swift).
    var beiAktiv: (() -> Void)?
    /// Die Kamera steht in der Richtung der Kachel und ist eingepasst; danach bewegt nur noch Kevin oder ein Kamerabefehl
    /// des Agenten sie, nicht jeder Lauf.
    var eingepasst = false
    /// Letzter Treffer eines Strichs in diesem Viewer: Punkte neben dem Modell liegen auf der Ebene durch ihn.
    var strichAnker: SIMD3<Float>?
    private var abos = Set<AnyCancellable>()

    init() {
        coordinator = ViewportCoordinator()
        coordinator.aufAbruf = true
        coordinator.eingabeAktiv = false  // erst wenn die Kachel zu sehen ist
    }

    /// Alles außer der Kamera folgt dem Hauptviewer. Jede Änderung an Körpern, Kamera oder Darstellung fordert ein Bild an.
    func spiegeln(von haupt: ViewportCoordinator) {
        let z = coordinator
        let h = haupt.controller, k = z.controller
        haupt.$bodies.sink { [weak z] b in z?.bodies = b }.store(in: &abos)
        haupt.$overlayItems.sink { [weak z] o in z?.setOverlay(o) }.store(in: &abos)
        haupt.$hint.sink { [weak z] t in z?.hint = t }.store(in: &abos)
        h.$displayMode.sink { [weak k] m in k?.displayMode = m }.store(in: &abos)
        h.$lightingConfiguration.sink { [weak k] l in k?.lightingConfiguration = l }.store(in: &abos)
        h.$configuration.sink { [weak k] c in k?.configuration = c }.store(in: &abos)
        h.$clipPlanes.sink { [weak k] c in k?.clipPlanes = c }.store(in: &abos)
        h.$selectedBodyIDs.sink { [weak k] s in k?.selectedBodyIDs = s }.store(in: &abos)
        h.$edgeIntensity.sink { [weak k] e in k?.edgeIntensity = e }.store(in: &abos)
        z.$bodies.sink { [weak self] _ in self?.neuZeichnen() }.store(in: &abos)
        k.objectWillChange.sink { [weak self] _ in self?.neuZeichnen() }.store(in: &abos)
    }

    func neuZeichnen() {
        guard aktiv else { return }
        bilder += 1
        coordinator.neuZeichnen()
    }

    /// Die Ansicht wird eingehängt bzw. abgebaut.
    func setOffen(_ an: Bool) {
        guard an != offen else { return }
        offen = an
        aktivGeaendert()
    }

    /// Die Oberfläche zeigt die Kachel bzw. verbirgt sie.
    func setSichtbar(_ an: Bool) {
        guard an != sichtbar else { return }
        sichtbar = an
        aktivGeaendert()
    }

    private func aktivGeaendert() {
        coordinator.eingabeAktiv = aktiv
        if aktiv {
            neuZeichnen()
            beiAktiv?()
        } else {
            coordinator.letzteMaus = nil
        }
    }
}

/// Inhalt der Kachel „Zweite Ansicht“: Viewport mit eigener Kamera, Eingabe wie im Hauptviewer (Drehen, Verschieben,
/// Zoomen, Auswählen, Rahmen, Messen, Zeichnen beim Sprechen, Ziffernblock), Überlagerung, Achsen-Gizmo und eine Zeile
/// für den Messmodus.
public struct ZweiterViewerAnsicht: View {
    @ObservedObject private var coordinator: ViewportCoordinator
    private let viewer: ZweiterViewer

    public init(controller: AppController) {
        viewer = controller.zweiterViewer
        _coordinator = ObservedObject(wrappedValue: controller.zweiterViewer.coordinator)
    }

    public var body: some View {
        ZStack(alignment: .topTrailing) {
            MetalViewportView(controller: coordinator.controller, bodies: $coordinator.bodies)
                .background(MTKViewProbe { [weak c = coordinator] view in c?.attach(view) })
            NavigationInputLayer(coordinator: coordinator)
            OverlayCanvas(coordinator: coordinator, viewport: coordinator.controller)
                .allowsHitTesting(false)
            AxisGizmo(viewport: coordinator.controller, coordinator: coordinator)
                .padding(.top, 4)
                .padding(.trailing, 4)
            ZweiterViewerHinweis(eingabe: coordinator.eingabe, coordinator: coordinator)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                .allowsHitTesting(false)
        }
        .clipped()
        .onAppear { viewer.setOffen(true) }
        .onDisappear { viewer.setOffen(false) }
    }
}

/// Unten rechts im zweiten Viewer (links steht der Maßstab): was der Messmodus unter der Maus findet bzw. welcher
/// Schritt dran ist.
private struct ZweiterViewerHinweis: View {
    @ObservedObject var eingabe: ViewerEingabe
    @ObservedObject var coordinator: ViewportCoordinator

    var body: some View {
        if let text = eingabe.unterMaus ?? coordinator.hint {
            Text(text)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color.white.opacity(0.92))
                .lineLimit(1)
                .truncationMode(.middle)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Capsule().fill(Color.black.opacity(0.5)))
                .padding(8)
        }
    }
}
