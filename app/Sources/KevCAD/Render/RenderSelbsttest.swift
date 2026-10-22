import AppKit
import KevCADCore
import SwiftUI

/// Selbsttest „Rendern …“ (Phase 7) in der Testvariante (`KEVCAD_SELFTEST=render`), ohne Maus- und Tastatureingaben:
///
/// 1. wartet auf ein offenes Projekt mit Teilen (öffnen über MCP `project_open` oder `KEVCAD_SELFTEST_PROJEKT`),
/// 2. öffnet den Dialog, wartet auf die Vorschau (Studio), fotografiert ihn,
/// 3. stellt „Freigestellt“, 1080 × 1350 ein, wartet auf die neue Vorschau, startet „Rendern“ (schnell) und prüft die
///    Datei unter output/renders/ (PNG mit Alpha),
/// 4. fotografiert den Dialog mit dem fertigen Auftrag und schließt ihn.
///
/// Bilder und Ergebnis in `KEVCAD_SELFTEST_AUSGABE` (`selftest-render.txt`).
@MainActor
enum RenderSelbsttest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "render"
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-render", isDirectory: true)
    }

    static func runIfRequested(_ session: AppSession) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session) }
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        let store = model.render
        var lines: [String] = []
        var passed = true
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Rendern: \(line)"))
        }
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }
        func foto(_ name: String) {
            // Der Dialog ist ein Sheet am Projektfenster
            guard let w = NSApp.windows.first(where: { $0.isSheet && $0.isVisible }) ?? NSApp.windows.first(where: \.isVisible),
                let v = w.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds)
            else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }

        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty, model.project == nil {
            _ = await wait(240) { model.kernelState == .ready }
            model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
        }
        check(await wait(600) { model.project != nil && !model.isRunning && !model.parts.isEmpty },
              "Projekt offen, Lauf fertig (\(model.parts.count) Teile)")
        check(model.renderActions != nil, "RenderActions vorhanden")

        // Dialog mit Vorschau
        let stand0 = store.vorschauStand
        RenderUI.shared.offen = true
        check(await wait(60) { store.vorschauStand > stand0 && !store.vorschauLaeuft }, "Vorschau im Dialog (Studio)")
        try? await Task.sleep(for: .milliseconds(400))
        foto("01-dialog-vorschau")

        // Freigestellt, hochkant
        let stand1 = store.vorschauStand
        store.szene = "freigestellt"
        store.groesse = "hochkant"
        check(await wait(60) { store.vorschauStand > stand1 && !store.vorschauLaeuft }, "Vorschau freigestellt")
        try? await Task.sleep(for: .milliseconds(400))
        foto("02-dialog-freigestellt")
        let vorher = store.auftraege.count
        model.renderActions?.renderStarten()
        check(await wait(120) { store.auftraege.count > vorher && store.auftraege.first?.zustand.istEnde == true },
              "Auftrag fertig")
        if let a = store.auftraege.first {
            lines.append("      \(a.auftrag): \(a.zustand.titel), \(a.text), \(a.width) × \(a.height)")
            let url = a.pfad.map { URL(fileURLWithPath: $0) }
            let bild = url.flatMap { u -> CGImage? in
                guard let s = CGImageSourceCreateWithURL(u as CFURL, nil) else { return nil }
                return CGImageSourceCreateImageAtIndex(s, 0, nil)
            }
            check(a.zustand == .fertig && bild != nil, "PNG geschrieben: \(url?.lastPathComponent ?? "-")")
            if let bild {
                check(bild.width == 1080 && bild.height == 1350, "Größe 1080 × 1350")
                let alpha = bild.alphaInfo
                check(alpha != .none && alpha != .noneSkipLast && alpha != .noneSkipFirst, "PNG mit Alpha")
            }
            check(store.letztesBild == url, "letztes Bild im Dialog")
        }
        try? await Task.sleep(for: .milliseconds(400))
        foto("03-dialog-fertig")
        RenderUI.shared.offen = false
        lines.append(passed ? "ERGEBNIS: bestanden" : "ERGEBNIS: FEHLER")
        try? lines.joined(separator: "\n").write(to: ausgabe.appendingPathComponent("selftest-render.txt"),
                                                atomically: true, encoding: .utf8)
        model.append(LogLine(level: passed ? .info : .error, text: "Selbsttest Rendern: \(passed ? "bestanden" : "FEHLER")"))
    }
}
