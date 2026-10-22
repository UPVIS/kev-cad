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

/// Menüpunkte: Ablage › Dokumente exportieren … (⇧⌘E); Menü „Bauplan“ mit Durchspielen (⌥⌘← ⌥⌘→ ⌥⌘.) und dem Sprung
/// zu Bauplan und Berichten im Bereich Dokumente. ⌘P und ⌥⌘P gehören den Blättern (P6-A1).
struct DokumenteExportCommands: Commands {
    @ObservedObject var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var bauplan: BauplanStore
    @FocusedObject private var window: ProjectWindowState?

    var body: some Commands {
        CommandGroup(after: .importExport) {
            Button("Dokumente exportieren …") { ExportDialogFenster.zeige(session: session, model: model) }
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(model.project == nil || model.exportActions == nil)
        }
        CommandMenu("Bauplan") {
            Button("Bauplan zeigen") { zeige(.bauplan) }
                .disabled(window == nil || model.project == nil)
            Button("Berichte zeigen") { zeige(.berichte) }
                .disabled(window == nil || model.project == nil)
            Divider()
            Button(bauplan.durchspielen == nil ? "Durchspielen" : "Durchspielen neu beginnen") {
                model.bauplanActions?.durchspielenStarten(ab: nil)
            }
            .disabled(model.project == nil || model.bauplanActions == nil)
            Group {
                Button(bauplan.durchspielen?.spielt == true ? "Anhalten" : "Abspielen") {
                    model.bauplanActions?.durchspielenAbspielen(!(bauplan.durchspielen?.spielt ?? false))
                }
                Button("Nächster Schritt") { model.bauplanActions?.durchspielenSchritt(1) }
                    .keyboardShortcut(.rightArrow, modifiers: [.command, .option])
                Button("Voriger Schritt") { model.bauplanActions?.durchspielenSchritt(-1) }
                    .keyboardShortcut(.leftArrow, modifiers: [.command, .option])
                Button("Durchspielen beenden") { model.bauplanActions?.durchspielenBeenden() }
                    .keyboardShortcut(".", modifiers: [.command, .option])
            }
            .disabled(bauplan.durchspielen == nil)
        }
    }

    private func zeige(_ a: DokumentAuswahl) {
        withAnimation(.snappy(duration: 0.2)) { window?.bereich = .dokumente }
        window?.dokumenteZustand?.waehle(a)
    }
}
