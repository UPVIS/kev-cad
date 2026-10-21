import AppKit
import Foundation
import OCCTSwiftViewport

// Sitzung über einen Neustart retten: Beim Beenden merkt sich die App Projekt, Kamera und Darstellung. Hat das
// automatische Update (tools/auto-update.sh) die App für eine neue Version beendet, legt es vorher
// `relaunch.request` an; die neue Version öffnet dann dasselbe Projekt mit derselben Ansicht wieder.

struct SavedSession: Codable {
    var project: String
    var camera: CameraState?
    var displayStyle: String?
    var selectionMode: String?
    var hidden: [String]?
}

extension AppController {
    static var sessionFile: URL { AppInfo.supportDirectory.appendingPathComponent("session.json") }
    static var relaunchMarker: URL { AppInfo.supportDirectory.appendingPathComponent("relaunch.request") }

    func saveSession() {
        guard !AppInfo.isDemoMode else { return }
        guard let project = model.project else {
            try? FileManager.default.removeItem(at: Self.sessionFile)
            return
        }
        let saved = SavedSession(
            project: project.path.path, camera: viewport.camera, displayStyle: model.displayStyle.rawValue,
            selectionMode: model.selectionMode.rawValue, hidden: Array(scene.hidden))
        if let data = try? JSONEncoder().encode(saved) {
            try? data.write(to: Self.sessionFile, options: .atomic)
        }
    }

    /// Nach einem automatischen Update: Projekt wieder öffnen; Kamera und Darstellung folgen nach dem ersten Lauf.
    func restoreSessionIfRequested() {
        let fm = FileManager.default
        guard let attrs = try? fm.attributesOfItem(atPath: Self.relaunchMarker.path) else { return }
        try? fm.removeItem(at: Self.relaunchMarker)
        // Nur frische Anfragen (ein liegengebliebener Marker soll nicht Tage später wirken)
        if let date = attrs[.modificationDate] as? Date, Date().timeIntervalSince(date) > 15 * 60 { return }
        guard let data = try? Data(contentsOf: Self.sessionFile),
            let saved = try? JSONDecoder().decode(SavedSession.self, from: data),
            fm.fileExists(atPath: saved.project)
        else { return }
        pendingRestore = saved
        log(.info, "Neue Version: öffne \(URL(fileURLWithPath: saved.project).lastPathComponent) wieder")
        openProject(at: URL(fileURLWithPath: saved.project, isDirectory: true))
    }

    func applyRestoredView(_ saved: SavedSession) {
        pendingRestore = nil
        if let style = saved.displayStyle.flatMap(DisplayStyle.init(rawValue:)) { applyDisplayStyle(style) }
        if let mode = saved.selectionMode.flatMap(SelectionMode.init(rawValue:)) { model.selectionMode = mode }
        let known = (saved.hidden ?? []).filter { scene.record($0) != nil }
        if !known.isEmpty { setVisibility(known, visible: false) }
        if let camera = saved.camera {
            viewport.setCamera(camera)
        } else {
            viewport.fit(scene.visibleBounds(), animated: true)
        }
    }
}
