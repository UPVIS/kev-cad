#if os(macOS)
import AppKit
#else
import UIKit
#endif
import ImageIO
import KevCADCore
import SwiftUI

/// Ein Eintrag der Startübersicht: zuletzt geöffnetes Projekt oder Entwurf mit Inhalt.
struct StartEintrag: Identifiable, Equatable {
    var url: URL
    var name: String
    var datum: Date
    var entwurf: Bool
    var fehlt: Bool

    var id: String { RecentProjects.normalizedPath(url) }
}

/// Startübersicht „Zuletzt geöffnet“ (V3, Zustand d im Entwurf): Karten mit Vorschaubild über dem leeren Projekt. Ein
/// Klick öffnet, esc, „Wegschieben“ oder ein Klick daneben schiebt sie weg.
struct Startuebersicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var recents: RecentProjects
    @ObservedObject private var bilder = Vorschaubilder.shared
    let breite: CGFloat
    let wegschieben: () -> Void
    @State private var markiert = 0
    @State private var entwuerfe: [StartEintrag] = []
    @FocusState private var fokus: Bool

    static let hoechstens = 8

    private var spalten: Int { breite < 760 ? 2 : 4 }

    var eintraege: [StartEintrag] {
        let aktuell = session.model.project.map { RecentProjects.normalizedPath($0.path) }
        let projekte = recents.items.map {
            StartEintrag(url: $0.url, name: $0.name, datum: $0.lastOpened, entwurf: false, fehlt: $0.isMissing)
        }
        let alle = (projekte + entwuerfe)
            .filter { $0.id != aktuell }
            .sorted { $0.datum > $1.datum }
        return Array(alle.prefix(Self.hoechstens))
    }

    var body: some View {
        let liste = eintraege
        OverlayKarte(titel: "Zuletzt geöffnet", fuss: "Ein Klick ins Leere oder esc schiebt die Liste weg.") {
            if AppSession.kannOrdnerWaehlen {  // iPad: Projekte aus der iCloud folgen in I-7
                Button {
                    session.presentOpenPanel()
                } label: {
                    Label("Ordner öffnen …", systemImage: "folder")
                }
                .buttonStyle(KevKnopfStil(form: .text))
                .help("Projektordner mit model.py öffnen (⌘O)")
            }
            Button(action: wegschieben) {
                Label("Wegschieben", systemImage: "chevron.down")
            }
            .buttonStyle(KevKnopfStil(form: .text))
            .help("Liste wegschieben (esc)")
        } inhalt: {
            if liste.isEmpty {
                Text("Noch keine Projekte. Sag dem Agenten, was entstehen soll.")
                    .font(GS.text)
                    .foregroundStyle(GF.asche)
                    .frame(maxWidth: .infinity, minHeight: 80)
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: spalten), spacing: 14) {
                    ForEach(Array(liste.enumerated()), id: \.element.id) { i, e in
                        StartKarte(eintrag: e, bild: bilder.bild(e.url), markiert: i == markiert) {
                            oeffnen(e)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: min(1124, breite - 2 * GA.xl))
        .focusable()
        .focused($fokus)
        .focusEffectDisabled()
        .onKeyPress(.return) {
            guard liste.indices.contains(markiert) else { return .ignored }
            oeffnen(liste[markiert])
            return .handled
        }
        .onKeyPress(keys: [.leftArrow, .rightArrow, .upArrow, .downArrow]) { druck in
            guard !liste.isEmpty else { return .ignored }
            switch druck.key {
            case .leftArrow: markiert = max(0, markiert - 1)
            case .rightArrow: markiert = min(liste.count - 1, markiert + 1)
            case .upArrow: markiert = max(0, markiert - spalten)
            default: markiert = min(liste.count - 1, markiert + spalten)
            }
            return .handled
        }
        .onAppear {
            recents.refresh()
            entwuerfe = Self.entwuerfeMitInhalt()
            bilder.laden((recents.items.map(\.url) + entwuerfe.map(\.url)).prefix(12).map { $0 })
            DispatchQueue.main.async { fokus = true }
        }
    }

    private func oeffnen(_ e: StartEintrag) {
        if e.fehlt {
            session.openRecent(RecentProject(path: e.url.path, name: e.name, lastOpened: e.datum, isMissing: true))
            return
        }
        wegschieben()
        session.openProject(at: e.url)
    }

    /// Entwürfe mit Inhalt aus der Ablage der Variante (ohne Namen, „Entwurf vom …“).
    static func entwuerfeMitInhalt() -> [StartEintrag] {
        let ablage = EntwurfAblage.standard
        return ablage.mitInhalt().map { url in
            let geaendert = (try? url.appendingPathComponent("model.py").resourceValues(
                forKeys: [.contentModificationDateKey]))?.contentModificationDate
            let datum = geaendert ?? ablage.erstellt(url) ?? Date.distantPast
            return StartEintrag(url: url, name: "Entwurf", datum: datum, entwurf: true, fehlt: false)
        }
    }
}

/// Karte eines Projekts: Vorschaubild, Name, Zeitpunkt.
private struct StartKarte: View {
    let eintrag: StartEintrag
    let bild: CGImage?
    let markiert: Bool
    let oeffnen: () -> Void
    @State private var hover = false

    private var form: RoundedRectangle { RoundedRectangle(cornerRadius: GR.karte, style: .continuous) }

    var body: some View {
        Button(action: oeffnen) {
            VStack(alignment: .leading, spacing: 0) {
                ZStack {
                    EllipticalGradient(colors: [Color(white: 0.27), Color(white: 0.155)], center: UnitPoint(x: 0.5, y: 0.35))
                    if let bild {
                        Image(decorative: bild, scale: 2)
                            .resizable()
                            .interpolation(.high)
                            .aspectRatio(contentMode: .fill)
                    } else {
                        Image(systemName: eintrag.fehlt ? "questionmark.folder" : "cube.transparent")
                            .font(.system(size: 34, weight: .light))
                            .foregroundStyle(GF.rauch)
                    }
                }
                .frame(height: 132)
                .frame(maxWidth: .infinity)
                .clipped()
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(eintrag.name)
                            .font(GS.karteName)
                            .foregroundStyle(GF.kreide)
                            .lineLimit(1)
                        if eintrag.entwurf { Marke(text: "ohne Namen") }
                        if eintrag.fehlt { Marke(text: "fehlt") }
                    }
                    Text(StartKarte.wann(eintrag.datum))
                        .font(GS.klein)
                        .foregroundStyle(GF.rauch)
                        .lineLimit(1)
                }
                .padding(EdgeInsets(top: 9, leading: 12, bottom: 11, trailing: 12))
            }
            .background(form.fill(Color.white.opacity(hover ? 0.07 : 0.04)))
            .clipShape(form)
            .overlay(form.strokeBorder(markiert ? GF.kevin.opacity(0.55) : Color.white.opacity(0.05),
                                       lineWidth: markiert ? 1.5 : 1))
            .opacity(eintrag.fehlt ? 0.55 : 1)
            .contentShape(form)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(eintrag.url.path)
        .accessibilityLabel("\(eintrag.name), \(StartKarte.wann(eintrag.datum))")
        .accessibilityHint("Öffnet das Projekt")
    }

    /// „heute, 14:32“, „gestern, 09:10“ oder „22.10.2026“.
    static func wann(_ d: Date) -> String {
        let cal = Calendar.current
        let zeit = DateFormatter()
        zeit.locale = Locale(identifier: "de_DE")
        zeit.dateFormat = "HH:mm"
        if cal.isDateInToday(d) { return "heute, \(zeit.string(from: d))" }
        if cal.isDateInYesterday(d) { return "gestern, \(zeit.string(from: d))" }
        let tag = DateFormatter()
        tag.locale = Locale(identifier: "de_DE")
        tag.dateFormat = "dd.MM.yyyy"
        return tag.string(from: d)
    }
}

/// Kleines Etikett auf einer Karte.
private struct Marke: View {
    let text: String

    var body: some View {
        Text(text)
            .font(GS.winzig)
            .foregroundStyle(GF.asche)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Capsule().fill(Color.white.opacity(0.08)))
    }
}

/// Vorschaubilder der Projekte: das jüngste Versionsbild (`.kevcad/versionen/bilder/<nr>.png`), verkleinert im
/// Hintergrund geladen.
@MainActor
final class Vorschaubilder: ObservableObject {
    static let shared = Vorschaubilder()

    @Published private(set) var bilder: [String: CGImage] = [:]
    private var laeuft: Set<String> = []

    func bild(_ projekt: URL) -> CGImage? { bilder[RecentProjects.normalizedPath(projekt)] }

    func laden(_ projekte: [URL]) {
        for p in projekte {
            let key = RecentProjects.normalizedPath(p)
            guard bilder[key] == nil, !laeuft.contains(key) else { continue }
            laeuft.insert(key)
            Task.detached(priority: .utility) {
                let bild = Vorschaubilder.vorschau(p)
                await MainActor.run {
                    Vorschaubilder.shared.laeuft.remove(key)
                    if let bild { Vorschaubilder.shared.bilder[key] = bild }
                }
            }
        }
    }

    /// Bild nach einem Lauf veraltet: beim nächsten Zeigen neu laden.
    func vergessen(_ projekt: URL) {
        bilder[RecentProjects.normalizedPath(projekt)] = nil
    }

    nonisolated static func vorschau(_ projekt: URL) -> CGImage? {
        let ordner = projekt.appendingPathComponent(".kevcad/versionen/bilder", isDirectory: true)
        guard let dateien = try? FileManager.default.contentsOfDirectory(atPath: ordner.path) else { return nil }
        let nummern = dateien.compactMap { f -> (Int, String)? in
            guard f.hasSuffix(".png"), let n = Int(f.dropLast(4)) else { return nil }
            return (n, f)
        }
        guard let neueste = nummern.max(by: { $0.0 < $1.0 }),
              let quelle = CGImageSourceCreateWithURL(ordner.appendingPathComponent(neueste.1) as CFURL, nil)
        else { return nil }
        let optionen: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: 640,
            kCGImageSourceCreateThumbnailWithTransform: true,
        ]
        return CGImageSourceCreateThumbnailAtIndex(quelle, 0, optionen as CFDictionary)
    }
}
