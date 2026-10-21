import AppKit
import Combine
import OCCTSwiftViewport

// Blender-Steuerung im App-Kern: Tastaturbefehle (NavigationActions), Rahmenauswahl, Kontextmenü, Auswahlmodus.
// Maus und Trackpad selbst verarbeitet die Eingabeebene in Viewer/BlenderNavigation.swift.

extension AppController: NavigationActions {
    func installNavigation() {
        viewport.onBoxSelect = { [weak self] picks, modifiers in self?.handleBoxSelect(picks, modifiers: modifiers) }
        viewport.onContextMenu = { [weak self] in self?.contextMenu() }
        viewport.onNumpadKey = { [weak self] code, flags in self?.handleNumpadKey(code, flags) ?? false }
        viewport.controller.$cameraState
            .map(\.isOrthographic)
            .removeDuplicates()
            .sink { [weak self] ortho in self?.model.orthographic = ortho }
            .store(in: &navCancellables)
    }

    // MARK: Ansicht

    public func axisView(_ view: StandardViewName) {
        viewport.navAxisView(ViewportCoordinator.standardView(view))
    }

    public func viewOpposite() { viewport.navOpposite() }

    public func toggleProjection() { viewport.navToggleProjection() }

    public func orbitStep(yaw: Double, pitch: Double) {
        viewport.navOrbitStep(yaw: Float(yaw), pitch: Float(pitch))
    }

    public func panStep(x: Double, y: Double) { viewport.navPanStep(x: Float(x), y: Float(y)) }

    public func zoomStep(_ steps: Int) {
        viewport.navZoom(factor: pow(1 / BlenderNav.wheelStep, Float(steps)))
    }

    public func viewSelected() {
        let refs = scene.expand(scene.selection).known
        guard !refs.isEmpty, let b = scene.worldBounds(of: refs) else {
            viewAll()
            return
        }
        viewport.fit(b, animated: true)
    }

    public func viewAll() {
        viewport.fit(scene.visibleBounds(), animated: true)
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

    /// Wie Blenders lokale Ansicht: nur die Auswahl zeigen und einpassen; ein zweites Mal stellt alles wieder her.
    public func toggleLocalView() {
        if let saved = localView {
            localView = nil
            scene.showAll()
            if !saved.hidden.isEmpty { scene.setVisible(Array(saved.hidden), false) }
            updateParts()
            refreshOverlay()
            viewport.smoothCamera(saved.camera, duration: 0.25)
            return
        }
        let selected = Array(selectedPartNames)
        guard !selected.isEmpty else { return }
        localView = (scene.hidden, viewport.camera)
        isolate(selected)
        viewSelected()
    }

    public func setSelectionMode(_ mode: SelectionMode) {
        model.selectionMode = mode
        if mode == .parts {
            applySelection(scene.selection.map(\.partRef))
        }
        log(.info, mode == .parts ? "Auswahl: ganze Teile" : "Auswahl: Flächen, Kanten und Punkte")
    }

    /// Rahmenauswahl: ohne Sondertaste ersetzen, Umschalt erweitert, Strg zieht ab (wie Blender).
    func handleBoxSelect(_ picks: [PickResult], modifiers: NSEvent.ModifierFlags) {
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

    /// Ziffernblock wie in Blender (Tastencodes unabhängig vom Tastaturlayout).
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
        add("Alle Maße löschen", enabled: !model.measurements.isEmpty || annotations.contains {
            if case .dimension = $0.item { return true } else { return false }
        }) { [weak self] in self?.clearMeasurements() }
        add(model.selectionMode == .parts ? "Flächen und Kanten auswählen" : "Ganze Teile auswählen", "\t") {
            [weak self] in
            guard let self else { return }
            self.setSelectionMode(self.model.selectionMode == .parts ? .elements : .parts)
        }
        return menu
    }
}

/// Ziel für Menüeinträge mit Closure (vom Menüeintrag über representedObject festgehalten).
final class MenuClosure: NSObject {
    let action: () -> Void
    init(_ action: @escaping () -> Void) { self.action = action }
    @objc func run() { action() }
}
