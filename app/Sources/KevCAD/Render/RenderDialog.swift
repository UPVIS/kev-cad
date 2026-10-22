import AppKit
import KevCADCore
import SwiftUI

/// Offen/zu für den Dialog „Rendern …“ (Menü, Werkzeugleiste, Selbsttest).
@MainActor
final class RenderUI: ObservableObject {
    static let shared = RenderUI()
    @Published var offen = false
}

/// Menüeintrag „Rendern …“ (⌥⌘R) unter „Ablage“ neben „Bild speichern“.
struct RenderCommands: Commands {
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Button("Rendern …") { RenderUI.shared.offen = true }
                .keyboardShortcut("r", modifiers: [.command, .option])
                .disabled(model.project == nil || model.parts.isEmpty)
        }
    }
}

/// Hängt den Dialog an das Projektfenster.
struct RenderDialoge: ViewModifier {
    @ObservedObject var model: AppModel
    @ObservedObject private var ui = RenderUI.shared

    func body(content: Content) -> some View {
        content.sheet(isPresented: $ui.offen) { RenderDialog(model: model, store: model.render) }
    }
}

/// Dialog „Rendern …“ (Phase 7): Szene, Größe, Qualität, Hintergrund, Ansicht, Vorschau; laufende und fertige Aufträge
/// mit Fortschritt, „Im Finder zeigen“ und „Teilen“. Schnell rendert RealityKit in der App, Foto Blender im Hintergrund.
struct RenderDialog: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: RenderStore
    @ObservedObject private var kameras: CameraStore
    @Environment(\.dismiss) private var dismiss
    @State private var vorschauAuftrag: DispatchWorkItem?

    init(model: AppModel, store: RenderStore) {
        self.model = model
        self.store = store
        _kameras = ObservedObject(wrappedValue: model.cameras)
    }

    private var actions: RenderActions? { model.renderActions }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Rendern", systemImage: "camera.aperture").font(.title2.weight(.semibold))
                Spacer()
                Text(store.qualitaet == "foto" ? "Blender Cycles, im Hintergrund" : "RealityKit, in Sekunden")
                    .foregroundStyle(.secondary).font(.callout)
            }
            HStack(alignment: .top, spacing: 18) {
                vorschau
                einstellungen.frame(width: 300)
            }
            if !store.auftraege.isEmpty {
                Divider()
                auftraege
            }
            if let m = store.meldung {
                Label(m, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.callout)
            }
            HStack {
                Text("Bilder landen in output/renders/ des Projekts.").foregroundStyle(.secondary).font(.callout)
                Spacer()
                Button("Schließen") { dismiss() }.keyboardShortcut(.cancelAction)
                Button(store.qualitaet == "foto" ? "Foto rendern" : "Rendern") {
                    store.meldung = nil
                    actions?.renderStarten()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(model.project == nil || model.parts.isEmpty)
            }
        }
        .padding(20)
        .frame(width: 900)
        .onAppear { vorschauBald(sofort: true) }
        .onChange(of: store.szene) { _, _ in vorschauBald() }
        .onChange(of: store.hintergrund) { _, _ in vorschauBald() }
        .onChange(of: store.ansicht) { _, _ in vorschauBald() }
        .onChange(of: store.kamera) { _, _ in vorschauBald() }
        .onChange(of: store.groesse) { _, _ in vorschauBald() }
    }

    // MARK: Vorschau

    private var vorschau: some View {
        ZStack {
            Schachbrett().opacity(0.5)
            if let url = store.vorschauBild, let bild = NSImage(contentsOf: url) {
                Image(nsImage: bild).resizable().aspectRatio(contentMode: .fit).id(store.vorschauStand)
            } else {
                Text("Vorschau").foregroundStyle(.secondary)
            }
            if store.vorschauLaeuft {
                ProgressView().controlSize(.small).padding(8)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            }
        }
        .frame(width: 540, height: 340)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
    }

    private func vorschauBald(sofort: Bool = false) {
        vorschauAuftrag?.cancel()
        let a = DispatchWorkItem { [actions] in actions?.renderVorschau() }
        vorschauAuftrag = a
        DispatchQueue.main.asyncAfter(deadline: .now() + (sofort ? 0.05 : 0.35), execute: a)
    }

    // MARK: Einstellungen

    private var einstellungen: some View {
        Form {
            Picker("Szene", selection: $store.szene) {
                ForEach(RenderStore.szenen, id: \.id) { Text($0.titel).tag($0.id) }
            }
            Picker("Hintergrund", selection: $store.hintergrund) {
                ForEach(RenderStore.hintergruende, id: \.titel) { Text($0.titel).tag($0.id) }
            }
            Picker("Größe", selection: $store.groesse) {
                ForEach(RenderStore.groessen, id: \.id) { g in Text("\(g.titel) · \(g.breite) × \(g.hoehe)").tag(g.id) }
            }
            Picker("Qualität", selection: $store.qualitaet) {
                Text("Schnell").tag("schnell")
                Text("Foto").tag("foto")
            }
            .pickerStyle(.segmented)
            Picker("Ansicht", selection: $store.ansicht) {
                ForEach(RenderStore.ansichten, id: \.id) { Text($0.titel).tag($0.id) }
            }
            .disabled(store.kamera != nil)
            if !kameras.cameras.isEmpty {
                Picker("Kamera", selection: $store.kamera) {
                    Text("keine (Ansicht oben)").tag(String?.none)
                    ForEach(kameras.cameras, id: \.name) { c in Text(c.displayName).tag(Optional(c.name)) }
                }
            }
            Text(hinweis).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .formStyle(.grouped)
    }

    private var hinweis: String {
        if store.qualitaet == "foto" {
            return "Foto: Blender Cycles mit Flächenlicht und echten Spiegelungen, etwa eine bis wenige Minuten. "
                + "Du kannst weiterarbeiten; der Fortschritt steht unten."
        }
        return "Schnell: PBR-Materialien aus dem Katalog, Bildbeleuchtung und weicher Schatten, ein bis wenige Sekunden."
    }

    // MARK: Aufträge

    private var auftraege: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(store.auftraege.prefix(5), id: \.auftrag) { a in
                HStack(spacing: 10) {
                    Image(systemName: symbol(a)).foregroundStyle(farbe(a))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(a.auftrag) · \(a.szene) · \(a.qualitaet == "foto" ? "Foto" : "schnell") · \(a.width) × \(a.height)")
                            .font(.callout.weight(.medium))
                        if a.zustand.istEnde {
                            Text(a.zustand == .fertig ? (a.pfad.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "")
                                 : (a.fehler ?? a.text))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                        } else {
                            ProgressView(value: a.fortschritt) { Text(a.text).font(.caption) }
                                .progressViewStyle(.linear)
                        }
                    }
                    Spacer()
                    if !a.zustand.istEnde {
                        Button("Abbrechen") { actions?.renderAbbrechen(a.auftrag) }
                    } else if a.zustand == .fertig, let p = a.pfad {
                        let url = URL(fileURLWithPath: p)
                        Button("Im Finder zeigen") { actions?.renderImFinderZeigen(url) }
                        ShareLink(item: url) { Label("Teilen", systemImage: "square.and.arrow.up") }
                    }
                }
            }
        }
    }

    private func symbol(_ a: RenderStatus) -> String {
        switch a.zustand {
        case .fertig: return "checkmark.circle.fill"
        case .fehler: return "xmark.octagon.fill"
        case .abgebrochen: return "stop.circle"
        case .wartet: return "hourglass"
        case .laeuft: return "camera.aperture"
        }
    }

    private func farbe(_ a: RenderStatus) -> Color {
        switch a.zustand {
        case .fertig: return .green
        case .fehler: return .red
        default: return .secondary
        }
    }
}

/// Schachbrett hinter durchsichtigen Bildern.
private struct Schachbrett: View {
    var body: some View {
        Canvas { ctx, size in
            let s: CGFloat = 12
            for y in stride(from: 0, to: size.height, by: s) {
                for x in stride(from: 0, to: size.width, by: s) where (Int(x / s) + Int(y / s)) % 2 == 0 {
                    ctx.fill(Path(CGRect(x: x, y: y, width: s, height: s)), with: .color(.gray.opacity(0.35)))
                }
            }
        }
    }
}
