#if os(macOS)
import AppKit
#endif
import Combine
import Foundation
import OCCTSwiftViewport

// Blender-Steuerung im App-Kern: Tastaturbefehle (NavigationActions), Rahmenauswahl, Kontextmenü, Auswahlmodus.
// Maus und Trackpad selbst verarbeitet die Eingabeebene in Viewer/BlenderNavigation.swift.

extension AppController: NavigationActions {
    func installNavigation() {
        viewport.onBoxSelect = { [weak self] picks, modifiers in self?.handleBoxSelect(picks, modifiers: modifiers) }
        #if os(macOS)
        viewport.onContextMenu = { [weak self] in self?.contextMenu() }
        viewport.onNumpadKey = { [weak self] code, flags in self?.handleNumpadKey(code, flags) ?? false }
        #endif
        // iPad: Kontextmenü (langes Drücken) und Tasten einer Hardware-Tastatur folgen in I-3.
        viewport.controller.$cameraState
            .map(\.isOrthographic)
            .removeDuplicates()
            .sink { [weak self] ortho in self?.model.orthographic = ortho }
            .store(in: &navCancellables)
    }

    // MARK: Ansicht

    // V2-10: Ansichtsbefehle wirken wie in Blender im Viewer unter der Maus (Haupt- oder zweiter Viewer).

    public func axisView(_ view: StandardViewName) {
        eingabeViewport.navAxisView(ViewportCoordinator.standardView(view))
    }

    public func viewOpposite() { eingabeViewport.navOpposite() }

    public func toggleProjection() { eingabeViewport.navToggleProjection() }

    public func orbitStep(yaw: Double, pitch: Double) {
        eingabeViewport.navOrbitStep(yaw: Float(yaw), pitch: Float(pitch))
    }

    public func panStep(x: Double, y: Double) { eingabeViewport.navPanStep(x: Float(x), y: Float(y)) }

    public func zoomStep(_ steps: Int) {
        eingabeViewport.navZoom(factor: pow(1 / BlenderNav.wheelStep, Float(steps)))
    }

    public func viewSelected() {
        let refs = scene.expand(scene.selection).known
        guard !refs.isEmpty, let b = scene.worldBounds(of: refs) else {
            viewAll()
            return
        }
        eingabeViewport.fit(b, animated: true)
    }

    public func viewAll() {
        eingabeViewport.fit(scene.visibleBounds(), animated: true)
    }

    // MARK: Auswahl und Sichtbarkeit

    private var visiblePartRefs: [ElementRef] {
        scene.order.filter { scene.isVisible($0) }.map { ElementRef.part($0) }
    }

    private var selectedPartNames: Set<String> { Set(scene.selection.map(\.part)) }

    public func selectAll() {
        measurePending = []
        applySelection(visiblePartRefs)
    }

    public func invertSelection() {
        let selected = selectedPartNames
        applySelection(visiblePartRefs.filter { !selected.contains($0.part) })
    }

    public func hideUnselected() {
        let selected = selectedPartNames
        guard !selected.isEmpty else { return }
        setVisibility(scene.order.filter { !selected.contains($0) && scene.isVisible($0) }, visible: false)
    }

    /// Wie Blenders lokale Ansicht: nur die Auswahl zeigen und einpassen; ein zweites Mal stellt Sichtbarkeit und
    /// Kamera wieder her. Mit Hauch (Vorgabe, `AppModel.viewer.hauch`) bleiben die übrigen Teile durchscheinend stehen.
    public func toggleLocalView() {
        if let saved = localView {
            localView = nil
            scene.setHauch([])
            scene.showAll()
            if !saved.hidden.isEmpty { scene.setVisible(Array(saved.hidden), false) }
            updateParts()
            refreshOverlay()
            viewport.smoothCamera(saved.camera, duration: 0.25)
            model.viewer.lokaleAnsicht = false
            return
        }
        let selected = Array(selectedPartNames)
        guard !selected.isEmpty else { return }
        localView = (scene.hidden, viewport.kameraZiel)
        if model.viewer.hauch {
            let keep = Set(selected)
            scene.setVisible(selected, true)
            scene.setHauch(Set(scene.order.filter { !keep.contains($0) && scene.isVisible($0) }))
            updateParts()
            refreshOverlay()
        } else {
            isolate(selected)
        }
        viewSelected()
        model.viewer.lokaleAnsicht = true
    }

    public func setSelectionMode(_ mode: SelectionMode) {
        model.selectionMode = mode
        if mode == .parts {
            applySelection(scene.selection.map(\.partRef))
        }
        log(.info, mode == .parts ? "Auswahl: ganze Teile" : "Auswahl: Flächen, Kanten und Punkte")
    }

    /// Rahmenauswahl: ohne Sondertaste ersetzen, Umschalt erweitert, Strg zieht ab (wie Blender).
    func handleBoxSelect(_ picks: [PickResult], modifiers: PlattformTastenFlags) {
        guard !model.measureMode else { return }
        var found: [ElementRef] = []
        var seen = Set<ElementRef>()
        for p in picks {
            guard var r = scene.resolve(p) else { continue }
            if model.selectionMode == .parts { r = r.partRef }
            if seen.insert(r).inserted { found.append(r) }
        }
        var refs = scene.selection
        if modifiers.contains(.shift) {
            for r in found where !refs.contains(r) { refs.append(r) }
        } else if modifiers.contains(.control) || modifiers.contains(.command) {
            refs.removeAll { r in seen.contains(r) || (model.selectionMode == .parts && seen.contains(r.partRef)) }
        } else {
            refs = found
        }
        measurePending = []
        applySelection(refs)
    }

    #if os(macOS)
    /// Ziffernblock wie in Blender (Tastencodes des Mac, unabhängig vom Tastaturlayout).
    func handleNumpadKey(_ code: UInt16, _ flags: NSEvent.ModifierFlags) -> Bool {
        let ctrl = flags.contains(.control)
        switch code {
        case 83: axisView(ctrl ? .back : .front)  // 1
        case 85: axisView(ctrl ? .left : .right)  // 3
        case 89: axisView(ctrl ? .bottom : .top)  // 7
        case 87: toggleProjection()  // 5
        case 92: viewOpposite()  // 9
        case 86: ctrl ? panStep(x: -0.1, y: 0) : orbitStep(yaw: -15, pitch: 0)  // 4
        case 88: ctrl ? panStep(x: 0.1, y: 0) : orbitStep(yaw: 15, pitch: 0)  // 6
        case 91: ctrl ? panStep(x: 0, y: 0.1) : orbitStep(yaw: 0, pitch: -15)  // 8
        case 84: ctrl ? panStep(x: 0, y: -0.1) : orbitStep(yaw: 0, pitch: 15)  // 2
        case 65: viewSelected()  // Komma bzw. Punkt des Ziffernblocks
        case 69: zoomStep(1)  // +
        case 78: zoomStep(-1)  // -
        case 75: toggleLocalView()  // /
        case 115: viewAll()  // Pos1
        case 82:  // 0: durch die Kamera schauen, Strg+Alt+0: Kamera auf die Ansicht (wie Blender)
            if ctrl && flags.contains(.option) { setActiveCameraToView() } else { toggleCameraView() }
        default: return false
        }
        return true
    }

    // MARK: Kontextmenü (rechte Maustaste)

    func contextMenu() -> NSMenu? {
        let menu = NSMenu()
        let hasSelection = !scene.selection.isEmpty
        func add(_ title: String, _ key: String = "", _ mods: NSEvent.ModifierFlags = [], enabled: Bool = true,
                 _ action: @escaping () -> Void) {
            let item = NSMenuItem(title: title, action: #selector(MenuClosure.run), keyEquivalent: key)
            item.keyEquivalentModifierMask = mods
            let closure = MenuClosure(action)
            item.target = closure
            item.representedObject = closure
            item.isEnabled = enabled
            menu.addItem(item)
        }
        menu.autoenablesItems = false
        add(hasSelection ? "Auswahl zentrieren" : "Alles zentrieren", ",") { [weak self] in self?.viewSelected() }
        add("Alles zeigen", String(UnicodeScalar(NSHomeFunctionKey)!)) { [weak self] in self?.viewAll() }
        menu.addItem(.separator())
        add("Ausblenden", "h", enabled: hasSelection) { [weak self] in
            guard let self else { return }
            self.setVisibility(Array(self.selectedPartNames), visible: false)
        }
        add("Andere ausblenden", "h", .shift, enabled: hasSelection) { [weak self] in self?.hideUnselected() }
        add("Alles einblenden", "h", .option) { [weak self] in self?.showAll() }
        add(localView == nil ? "Lokale Ansicht" : "Lokale Ansicht beenden", "/", enabled: hasSelection || localView != nil) {
            [weak self] in self?.toggleLocalView()
        }
        menu.addItem(.separator())
        add(model.measureMode ? "Messen beenden" : "Messen", "m") { [weak self] in
            guard let self else { return }
            self.setMeasureMode(!self.model.measureMode)
        }
        let hatMasse = !model.measurements.isEmpty || viewer.stehendeAnmerkungen > 0
        add(viewer.masseSichtbar ? "Maße ausblenden" : "Maße einblenden", "m", .shift, enabled: hatMasse) {
            [weak self] in self?.ausfuehren(.masseUmschalten)
        }
        add("Alle Maße löschen", "m", .option, enabled: hatMasse || !annotations.isEmpty) { [weak self] in
            self?.ausfuehren(.masseLoeschen)
        }
        add(model.selectionMode == .parts ? "Flächen und Kanten auswählen" : "Ganze Teile auswählen", "\t") {
            [weak self] in
            guard let self else { return }
            self.setSelectionMode(self.model.selectionMode == .parts ? .elements : .parts)
        }
        return menu
    }
    #endif
}

#if os(macOS)
/// Ziel für Menüeinträge mit Closure (vom Menüeintrag über representedObject festgehalten).
final class MenuClosure: NSObject {
    let action: () -> Void
    init(_ action: @escaping () -> Void) { self.action = action }
    @objc func run() { action() }
}
#endif
