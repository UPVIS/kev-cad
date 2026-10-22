import ARKit
import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage(AppSettings.autoPhoto) private var autoPhoto = true
    @AppStorage(AppSettings.autoAngle) private var autoAngle = 15.0
    @AppStorage(AppSettings.autoDistance) private var autoDistance = 0.25
    @AppStorage(AppSettings.showMesh) private var showMesh = true

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Automatisch fotografieren", isOn: $autoPhoto)
                    if autoPhoto {
                        VStack(alignment: .leading) {
                            Text("Nach Drehung um \(Int(autoAngle))°")
                            Slider(value: $autoAngle, in: 5...45, step: 1)
                        }
                        VStack(alignment: .leading) {
                            Text("Oder nach \(Int((autoDistance * 100).rounded())) cm Weg")
                            Slider(value: $autoDistance, in: 0.1...1.0, step: 0.05)
                        }
                    }
                } header: {
                    Text("Fotos")
                } footer: {
                    Text("Während der Aufnahme entsteht ein hochaufgelöstes Foto, sobald sich das iPhone seit dem letzten Foto um diesen Winkel gedreht oder so weit bewegt hat. Der Auslöser geht immer von Hand.")
                }
                Section("Anzeige") {
                    Toggle("Erfasste Flächen als Netz zeigen", isOn: $showMesh)
                }
                Section("Gerät") {
                    LabeledContent("Modell", value: DeviceInfo.model)
                    LabeledContent("iOS", value: DeviceInfo.systemVersion)
                    LabeledContent("LiDAR", value: ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) ? "ja" : "nein")
                    if let format = CaptureController.bestVideoFormat() {
                        LabeledContent("Videoformat",
                                       value: "\(Int(format.imageResolution.width)) × \(Int(format.imageResolution.height)), \(format.framesPerSecond) fps")
                    }
                    LabeledContent("App", value: DeviceInfo.appVersion)
                }
            }
            .navigationTitle("Einstellungen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
        }
    }
}
