import SwiftUI
import UIKit

/// Aufnahme: Live-Bild mit Netz, Objekt-Box, Start/Stopp, Fotos und Hinweisen. Immer dunkel.
struct CaptureView: View {
    let name: String
    @EnvironmentObject private var store: ScanStore
    @Environment(\.dismiss) private var dismiss
    @StateObject private var capture = CaptureController()
    @AppStorage(AppSettings.showMesh) private var showMesh = true
    @AppStorage(AppSettings.autoPhoto) private var autoPhoto = true
    @State private var confirmClose = false
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            ARViewContainer(controller: capture)
                .ignoresSafeArea()
            if capture.photoFlash {
                Color.white.opacity(0.3)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
            }
            VStack(spacing: 8) {
                topBar
                guide
                warningList
                Spacer(minLength: 0)
                if capture.boxMode { boxPanel }
                statsBar
                controls
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 6)
            if capture.finishing {
                savingOverlay
            }
        }
        .environment(\.colorScheme, .dark)
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .onAppear {
            capture.configure(store: store, name: name)
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            UIApplication.shared.isIdleTimerDisabled = false
            store.reload()
        }
        .onChange(of: showMesh) { _, visible in capture.setMeshVisible(visible) }
        .onChange(of: capture.finished) { _, done in
            if done && capture.errorText == nil { dismiss() }
        }
        .confirmationDialog("Aufnahme verwerfen?", isPresented: $confirmClose, titleVisibility: .visible) {
            Button("Verwerfen", role: .destructive) {
                capture.cancelRecording()
                dismiss()
            }
            Button("Weiter aufnehmen", role: .cancel) {}
        } message: {
            Text("Video, Tiefe und Fotos dieser Aufnahme werden gelöscht.")
        }
        .alert("Hinweis", isPresented: Binding(get: { capture.errorText != nil },
                                                set: { if !$0 { capture.errorText = nil } })) {
            Button("OK", role: .cancel) {
                if capture.finished { dismiss() }
            }
        } message: {
            Text(capture.errorText ?? "")
        }
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environment(\.colorScheme, .dark)
        }
    }

    // MARK: Teile

    private var topBar: some View {
        HStack(spacing: 10) {
            roundButton("xmark", label: "Schließen") {
                if capture.isRecording { confirmClose = true } else { dismiss() }
            }
            Spacer(minLength: 0)
            HStack(spacing: 6) {
                Circle()
                    .fill(trackingColor)
                    .frame(width: 9, height: 9)
                Text(capture.trackingText)
                    .lineLimit(1)
                if let distance = capture.distanceText {
                    Text("·").foregroundStyle(.secondary)
                    Text(distance).monospacedDigit()
                }
            }
            .font(.footnote.weight(.medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(.ultraThinMaterial, in: Capsule())
            Spacer(minLength: 0)
            roundButton("gearshape", label: "Einstellungen") { showSettings = true }
                .disabled(capture.isRecording)
                .opacity(capture.isRecording ? 0.4 : 1)
        }
        .padding(.top, 4)
    }

    private var guide: some View {
        Text(guideText)
            .font(.footnote)
            .multilineTextAlignment(.center)
            .foregroundStyle(.white.opacity(0.9))
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var guideText: String {
        if capture.boxMode {
            return "Auf den Boden neben das Objekt tippen. Ziehen verschiebt die Box, zwei Finger ändern Größe und Drehung."
        }
        if capture.isRecording {
            return "Langsam einmal rundherum gehen, dann einmal von oben. Abstand etwa 0,3 bis 1,5 m, ruhig halten."
        }
        return "\(name): optional zuerst die Box um das Objekt setzen, dann die Aufnahme starten."
    }

    private var warningList: some View {
        VStack(spacing: 6) {
            ForEach(capture.warnings, id: \.self) { text in
                Label(text, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.orange, in: Capsule())
            }
        }
        .animation(.easeInOut(duration: 0.2), value: capture.warnings)
    }

    private var boxPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            if capture.box != nil {
                sizeSlider("Breite", axis: 0)
                sizeSlider("Tiefe", axis: 2)
                sizeSlider("Höhe", axis: 1)
                HStack {
                    Text("Drehung").frame(width: 64, alignment: .leading)
                    Slider(value: yawBinding, in: -180...180)
                    Text("\(Int(yawBinding.wrappedValue))°")
                        .monospacedDigit()
                        .frame(width: 52, alignment: .trailing)
                }
            } else {
                Text("Noch keine Box gesetzt.")
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button(role: .destructive) { capture.box = nil } label: {
                    Label("Entfernen", systemImage: "trash")
                }
                .disabled(capture.box == nil)
                Spacer()
                Button("Fertig") { capture.boxMode = false }
                    .buttonStyle(.borderedProminent)
            }
        }
        .font(.footnote)
        .padding(12)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func sizeSlider(_ title: String, axis: Int) -> some View {
        let binding = Binding<Double>(
            get: { Double(capture.box?.size[axis] ?? 0.3) * 100 },
            set: { value in capture.updateBox { $0.size[axis] = Float(value / 100) } }
        )
        return HStack {
            Text(title).frame(width: 64, alignment: .leading)
            Slider(value: binding, in: 3...300)
            Text("\(Int(binding.wrappedValue.rounded())) cm")
                .monospacedDigit()
                .frame(width: 52, alignment: .trailing)
        }
    }

    private var yawBinding: Binding<Double> {
        Binding<Double>(
            get: {
                let degrees = Double(capture.box?.yaw ?? 0) * 180 / .pi
                return (degrees + 540).truncatingRemainder(dividingBy: 360) - 180
            },
            set: { value in capture.updateBox { $0.yaw = Float(value * .pi / 180) } }
        )
    }

    private var statsBar: some View {
        HStack(spacing: 14) {
            Label(Formatting.duration(capture.duration), systemImage: capture.isRecording ? "record.circle" : "timer")
                .foregroundStyle(capture.isRecording ? Color.red : Color.white)
            Label("\(capture.photoCount)", systemImage: "camera")
            Label("\(capture.frameCount)", systemImage: "film")
            Label(Formatting.bytes(capture.freeBytes), systemImage: "internaldrive")
        }
        .font(.footnote.weight(.medium).monospacedDigit())
        .labelStyle(.titleAndIcon)
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .background(.ultraThinMaterial, in: Capsule())
    }

    private var controls: some View {
        HStack {
            sideButton(systemImage: capture.box == nil ? "cube.transparent" : "cube.transparent.fill",
                       title: "Box",
                       active: capture.boxMode) {
                capture.boxMode.toggle()
            }
            .disabled(capture.isRecording)
            .opacity(capture.isRecording ? 0.4 : 1)

            Spacer()

            Button {
                if capture.isRecording { capture.stopRecording() } else { capture.startRecording() }
            } label: {
                ZStack {
                    Circle()
                        .strokeBorder(.white, lineWidth: 4)
                        .frame(width: 78, height: 78)
                    RoundedRectangle(cornerRadius: capture.isRecording ? 8 : 32, style: .continuous)
                        .fill(Color.red)
                        .frame(width: capture.isRecording ? 32 : 64, height: capture.isRecording ? 32 : 64)
                        .animation(.easeInOut(duration: 0.2), value: capture.isRecording)
                }
            }
            .accessibilityLabel(capture.isRecording ? "Aufnahme beenden" : "Aufnahme starten")
            .disabled(!capture.lidarAvailable || capture.finishing)

            Spacer()

            sideButton(systemImage: "camera.aperture",
                       title: autoPhoto ? "Foto · auto" : "Foto",
                       active: false) {
                capture.takePhoto()
            }
            .disabled(!capture.isRecording)
            .opacity(capture.isRecording ? 1 : 0.4)
        }
        .padding(.horizontal, 8)
    }

    private var savingOverlay: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(spacing: 12) {
                ProgressView()
                Text("Speichere den Scan …")
                    .font(.headline)
            }
            .padding(24)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
    }

    private var trackingColor: Color {
        switch capture.trackingLevel {
        case 2: return .green
        case 1: return .yellow
        default: return .red
        }
    }

    private func roundButton(_ systemImage: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 16, weight: .semibold))
                .frame(width: 38, height: 38)
                .background(.ultraThinMaterial, in: Circle())
        }
        .accessibilityLabel(label)
    }

    private func sideButton(systemImage: String, title: String, active: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: systemImage)
                    .font(.system(size: 22, weight: .medium))
                    .frame(width: 56, height: 56)
                    .background(active ? AnyShapeStyle(Color.accentColor) : AnyShapeStyle(.ultraThinMaterial), in: Circle())
                Text(title)
                    .font(.caption2.weight(.medium))
            }
            .foregroundStyle(.white)
            .frame(width: 84)
        }
    }
}
