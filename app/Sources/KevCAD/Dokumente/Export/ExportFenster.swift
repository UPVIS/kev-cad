import AppKit
import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

/// Fenster und Blätter des Exports (Strang P6-A2): Dialog „Dokumente exportieren …“ als Blatt am Projektfenster,
/// Sicherungsort, Fehlerhinweis.
@MainActor
enum ExportDialogFenster {
    private static var offen: NSWindow?

    static func zeige(session: AppSession, model: AppModel, vorauswahl: [ExportBausteinArt]? = nil) {
        guard model.project != nil else { return }
        model.exportActions?.exportVorlagenLaden()
        if let w = offen {
            w.makeKeyAndOrderFront(nil)
            return
        }
        let fenster = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 640),
                               styleMask: [.titled, .closable], backing: .buffered, defer: false)
        fenster.title = "Dokumente exportieren"
        fenster.isReleasedWhenClosed = false
        let schliessen: () -> Void = {
            if let parent = fenster.sheetParent { parent.endSheet(fenster) } else { fenster.close() }
            offen = nil
        }
        fenster.contentView = NSHostingView(rootView: ExportDialog(model: model, vorauswahl: vorauswahl,
                                                                   schliessen: schliessen)
            .environmentObject(session))
        offen = fenster
        if let parent = session.projectWindow ?? NSApp.mainWindow, parent.isVisible {
            parent.beginSheet(fenster)
        } else {
            fenster.center()
            fenster.makeKeyAndOrderFront(nil)
        }
    }

    /// Das offene Dialogfenster (für Selbsttests und Bildschirmfotos).
    static var fenster: NSWindow? { offen }

    /// Ort für das PDF; Vorgabe ist der Ausgabeordner des Projekts.
    static func speicherOrt(model: AppModel, name: String) async -> URL? {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.pdf]
        panel.nameFieldStringValue = name + ".pdf"
        panel.canCreateDirectories = true
        panel.isExtensionHidden = false
        if let p = model.project {
            let out = p.path.appendingPathComponent("output", isDirectory: true)
            try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
            panel.directoryURL = out
        }
        let parent = offen ?? NSApp.keyWindow
        if let parent {
            let r = await panel.beginSheetModal(for: parent)
            return r == .OK ? panel.url : nil
        }
        return panel.runModal() == .OK ? panel.url : nil
    }

    static func fehler(_ error: Error) {
        let a = NSAlert()
        a.messageText = "Export nicht möglich"
        a.informativeText = (error as? ExportFehler)?.description ?? error.localizedDescription
        a.alertStyle = .warning
        if let w = NSApp.keyWindow { a.beginSheetModal(for: w) } else { a.runModal() }
    }
}

/// Fenster „Bauplan und Berichte“, bis der Bereich „Dokumente“ im Projektfenster (P6-A1) sie aufnimmt.
@MainActor
enum DokumenteFenster {
    enum Reiter: String, CaseIterable { case bauplan, berichte }

    private static var offen: NSWindow?
    private static var zustand = DokumenteFensterZustand()

    static func zeige(session: AppSession, model: AppModel, reiter: Reiter = .bauplan) {
        zustand.reiter = reiter
        if let w = offen {
            w.makeKeyAndOrderFront(nil)
            return
        }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 820),
                         styleMask: [.titled, .closable, .resizable, .miniaturizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.title = "Bauplan und Berichte"
        w.isReleasedWhenClosed = false
        w.titlebarAppearsTransparent = false
        w.toolbarStyle = .unified
        w.contentView = NSHostingView(rootView: DokumenteFensterInhalt(model: model, zustand: zustand)
            .environmentObject(session))
        w.setFrameAutosaveName("KevCAD.BauplanBerichte")
        offen = w
        if AppInfo.isTestVariant {
            WindowHook.place(w, .large)
            w.orderFront(nil)
        } else {
            w.center()
            w.makeKeyAndOrderFront(nil)
        }
    }

    static var fenster: NSWindow? { offen }
    static func waehle(_ r: Reiter) { zustand.reiter = r }
}

@MainActor
final class DokumenteFensterZustand: ObservableObject {
    @Published var reiter: DokumenteFenster.Reiter = .bauplan
}

struct DokumenteFensterInhalt: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var zustand: DokumenteFensterZustand

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $zustand.reiter) {
                Label("Bauplan", systemImage: "hammer").tag(DokumenteFenster.Reiter.bauplan)
                Label("Berichte", systemImage: "doc.text").tag(DokumenteFenster.Reiter.berichte)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .padding(.vertical, 8)
            Divider()
            switch zustand.reiter {
            case .bauplan: BauplanAnsicht(model: model)
            case .berichte: BerichteAnsicht(model: model)
            }
        }
        .onReceive(model.bauplan.$zeige3D.dropFirst()) { _ in
            // Durchspielen oder Befund: das Projektfenster mit dem 3D-Bereich nach vorn
            session.projectWindow?.orderFront(nil)
        }
    }
}

/// Menüpunkte: Ablage › Dokumente exportieren … (⇧⌘E), Fenster › Bauplan und Berichte, Durchspielen.
struct DokumenteExportCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var bauplan: BauplanStore

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Button("Dokumente exportieren …") { ExportDialogFenster.zeige(session: session, model: model) }
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(model.project == nil || model.exportActions == nil)
        }
        CommandGroup(after: .windowArrangement) {
            Button("Bauplan und Berichte") { DokumenteFenster.zeige(session: session, model: model) }
                .disabled(model.project == nil)
        }
        CommandMenu("Bauplan") {
            Button(bauplan.durchspielen == nil ? "Durchspielen" : "Durchspielen neu beginnen") {
                model.bauplanActions?.durchspielenStarten(ab: nil)
            }
            .disabled(model.project == nil || model.bauplanActions == nil)
            Group {
                Button(bauplan.durchspielen?.spielt == true ? "Anhalten" : "Abspielen") {
                    model.bauplanActions?.durchspielenAbspielen(!(bauplan.durchspielen?.spielt ?? false))
                }
                .keyboardShortcut("p", modifiers: [.command, .option])
                Button("Nächster Schritt") { model.bauplanActions?.durchspielenSchritt(1) }
                    .keyboardShortcut(.rightArrow, modifiers: [.command, .option])
                Button("Voriger Schritt") { model.bauplanActions?.durchspielenSchritt(-1) }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                Button("Durchspielen beenden") { model.bauplanActions?.durchspielenBeenden() }
                    .keyboardShortcut(".", modifiers: [.command, .option])
            }
            .disabled(bauplan.durchspielen == nil)
            Divider()
            Button("Bauplan zeigen") { DokumenteFenster.zeige(session: session, model: model, reiter: .bauplan) }
                .disabled(model.project == nil)
            Button("Berichte zeigen") { DokumenteFenster.zeige(session: session, model: model, reiter: .berichte) }
                .disabled(model.project == nil)
        }
    }
}
