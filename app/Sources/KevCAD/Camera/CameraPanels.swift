import AppKit
import KevCADCore
import SwiftUI

// Phase 5, Strang KAM: Kameras in der Oberfläche. Abschnitt „Kameras“ im Teilebaum (wählen, durch die Kamera schauen)
// und im Inspektor (alle Werte der gewählten Kamera). Eingestellt wird in model.py (oder vom Agenten über MCP); die
// Oberfläche zeigt nur an und löst Ansicht, Kamerabild und den Vorschlag aus der Ansicht aus.

extension AppModel {
    var cameraActions: CameraActions? { actions as? CameraActions }
}

/// Abschnitt „Kameras“ im Teilebaum.
struct CameraTreeSection: View {
    @ObservedObject var store: CameraStore
    let actions: CameraActions?

    var body: some View {
        if !store.cameras.isEmpty {
            Section {
                ForEach(store.cameras) { cam in
                    CameraRow(cam: cam, store: store, actions: actions)
                }
            } header: {
                HStack {
                    Text("Kameras")
                    Spacer()
                    Text(KevFormat.integer(store.cameras.count)).monospacedDigit()
                }
            }
        }
    }
}

private struct CameraRow: View {
    let cam: CameraInfo
    @ObservedObject var store: CameraStore
    let actions: CameraActions?

    private var active: Bool { store.activeView == cam.name }
    private var selected: Bool { store.selected == cam.name }

    var body: some View {
        HStack(spacing: 7) {
            Button {
                actions?.lookThrough(active ? nil : cam.name)
            } label: {
                Image(systemName: active ? "video.fill" : "video")
                    .foregroundStyle(active ? Color.orange : .secondary)
                    .frame(width: 18)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help(active ? "Zurück zur freien Ansicht (0)" : "Durch die Kamera schauen (0)")

            VStack(alignment: .leading, spacing: 1) {
                Text(cam.displayName)
                    .fontWeight(selected ? .semibold : .regular)
                    .lineLimit(1)
                Text("\(cam.brennweiteText) · \(cam.blendeText) · \(cam.formatName)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: 4)
            if cam.vorschlag {
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.orange)
                    .help("Lage aus der Ansicht vorgeschlagen (Strg+Alt+0), model.py noch unverändert")
            } else if cam.vignettierung {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.yellow)
                    .help("Bildkreis des Objektivs kleiner als das Format: die Ecken vignettieren")
            } else if cam.teil != nil {
                Image(systemName: "link")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .help("Hängt an \(cam.teil ?? "")")
            }
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { actions?.lookThrough(cam.name) }
        .onTapGesture { actions?.selectCamera(cam.name) }
        .contextMenu {
            Button(active ? "Freie Ansicht" : "Durch Kamera schauen") { actions?.lookThrough(active ? nil : cam.name) }
            Button("Kamerabild speichern (\(cam.aufloesungText))") { actions?.renderCameraImage(cam.name) }
            Divider()
            Button("Kamera auf Ansicht setzen (Vorschlag)") {
                actions?.selectCamera(cam.name)
                actions?.setActiveCameraToView()
            }
            Button("Namen kopieren") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(cam.displayName, forType: .string)
            }
        }
        .help("\(cam.name) · \(cam.kameraName) · \(cam.objektivName ?? "ohne Objektiv") · Doppelklick: durch die Kamera schauen")
    }
}

/// Abschnitt „Kamera“ im Inspektor: die gewählte (oder aktive) Kamera mit allen Werten.
struct CameraInspectorSection: View {
    @ObservedObject var store: CameraStore
    let actions: CameraActions?

    private var cam: CameraInfo? {
        if let s = store.selected, let c = store.camera(s) { return c }
        if let a = store.activeView, let c = store.camera(a) { return c }
        return nil
    }

    var body: some View {
        if let cam {
            Section {
                row("Kamera", cam.kameraName)
                row("Objektiv", cam.objektivName ?? "ideal (nicht aus dem Katalog)")
                row("Format", cam.formatName)
                row("Auflösung", "\(cam.aufloesungText) px")
                row("Sensorfläche", "\(KevFormat.number(cam.sensorMM.x, digits: 2)) × \(KevFormat.number(cam.sensorMM.y, digits: 2)) mm")
                row("Brennweite", cam.brennweiteText)
                row("Bildwinkel", "\(cam.bildwinkelText) (diagonal \(KevFormat.number(cam.bildwinkelD, digits: 1))°)")
                row("Blende", cam.blendeText)
                row("Fokus", "\(cam.fokusText) ab Sensorebene")
                row("Schärfentiefe", cam.schaerfeText)
                row("Hyperfokal", CameraInfo.distanceText(cam.hyperfokal))
                row("Zerstreuungskreis", "\(KevFormat.number(cam.zerstreuungskreis, digits: 3)) mm")
                row("Sensormitte", vec(cam.sensorPos))
                row("Blickrichtung", vec(cam.blick, digits: 3))
                if let teil = cam.teil { row("Hängt an", teil) }
                if cam.vorschlag {
                    Label("Lage aus der Ansicht vorgeschlagen; übernimmt der Agent in model.py", systemImage: "arrow.triangle.2.circlepath")
                        .foregroundStyle(.orange)
                        .font(.caption)
                }
                if cam.vignettierung {
                    Label("Bildkreis kleiner als das Format: die Ecken vignettieren", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.yellow)
                        .font(.caption)
                }
                HStack {
                    Button(store.activeView == cam.name ? "Freie Ansicht" : "Durch Kamera schauen") {
                        actions?.lookThrough(store.activeView == cam.name ? nil : cam.name)
                    }
                    Button("Kamerabild speichern") { actions?.renderCameraImage(cam.name) }
                }
                .controlSize(.small)
                Text("Einstellen in model.py (lager.kamera …) oder über Claude.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                HStack {
                    Text("Kamera \(cam.displayName)")
                    Spacer()
                    if store.selected != nil {
                        Button("Schließen") { actions?.selectCamera(nil) }
                            .buttonStyle(.borderless)
                            .controlSize(.small)
                    }
                }
            }
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        LabeledContent(label) {
            Text(value)
                .monospacedDigit()
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    private func vec(_ v: SIMD3<Float>, digits: Int = 1) -> String {
        [v.x, v.y, v.z].map { KevFormat.number(Double($0), digits: digits) }.joined(separator: "; ")
    }
}
