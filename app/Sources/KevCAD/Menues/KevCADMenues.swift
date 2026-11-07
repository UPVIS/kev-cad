import KevCADCore
import SwiftUI

/// Alle Menüs von Kev CAD in einer Quelle für Mac und iPad (PLAN-IPAD.md, I-9): Mac-Szene (Mac/KevCADApp.swift) und
/// iPad-Szene (KevCADPad/KevCADPadApp.swift) binden dieselbe Liste ein, in derselben Reihenfolge. Auf dem iPad mit
/// iPadOS 26 erscheinen sie in der Menüleiste und in der Übersicht beim Halten von ⌘, mit denselben Kürzeln. Was nur
/// am Mac geht (Finder, eigene Fenster), steht in den einzelnen Dateien hinter `#if os(macOS)` samt iPad-Weg.
struct KevCADMenues: Commands {
    let session: AppSession

    var body: some Commands {
        KevCADCommands(session: session, model: session.model, recents: session.recents)
        OberflaechenCommands(session: session, model: session.model, oberflaeche: session.model.oberflaeche)
        DemoCommands(session: session)
        StockCommands(session: session, model: session.model)
        BestandCommands(model: session.model)
        ZukaufCommands(session: session, model: session.model)
        DokumenteCommands(model: session.model)  // Ablage › Drucken
        DokumenteExportCommands(session: session, model: session.model)  // Dokumente exportieren (⇧⌘E)
        RenderCommands(model: session.model)  // Phase 7: Rendern … (⌥⌘R)
    }
}
