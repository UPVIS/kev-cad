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
