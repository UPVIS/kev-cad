import AppKit
import KevCADCore
import SwiftUI

/// Kopfleiste des Hauptfensters: Platz für die Ampel, Projektname (Doppelklick benennt um, Pfeil öffnet das
/// Projektmenü), Umschalter Fokus/Werkstatt; rechts Foto, Video, Messen, Isolieren, An den Rand.
struct Kopfleiste: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    let schmal: Bool

    var body: some View {
        HStack(spacing: schmal ? GA.m : GA.l) {
            ProjektTitel(model: model, schmal: schmal)
            ModusUmschalter(
                optionen: [
                    ModusUmschalter<ArbeitsModus>.Option(wert: .fokus, titel: "Fokus", hilfe: "Fokus: nur Modell und Agent (⌘1)"),
                    ModusUmschalter<ArbeitsModus>.Option(wert: .werkstatt, titel: "Werkstatt", hilfe: "Werkstatt: Eigenschaften und Kacheln (⌘2)"),
                ],
                auswahl: oberflaeche.modus
            ) { m in
                withAnimation(GB.standard) { model.oberflaechenActions?.setzeModus(m) }
            }
            .fixedSize()
            Spacer(minLength: GA.s)
            if let meldung = session.meldung {
                MeldungsZeile(meldung: meldung)
                    .transition(.opacity)
            }
            Aktionen(model: model, oberflaeche: oberflaeche, schmal: schmal)
        }
        .padding(.leading, GA.ampel)
        .padding(.trailing, GA.m)
        .frame(height: GA.kopf)
        .animation(GB.standard, value: session.meldung)
    }
}

/// Projektname mit Zusatz („noch nicht gesichert“ beim Entwurf) und Projektmenü.
private struct ProjektTitel: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    let schmal: Bool
    @State private var bearbeiten = false
    @State private var entwurf = ""
    @FocusState private var fokus: Bool

    var body: some View {
        HStack(spacing: 6) {
            if bearbeiten {
                TextField("Projektname", text: $entwurf)
                    .textFieldStyle(.plain)
                    .font(GS.projekt)
                    .foregroundStyle(GF.kreide)
                    .focused($fokus)
                    .frame(width: 200)
                    .padding(.horizontal, 6)
                    .frame(height: 22)
                    .background(RoundedRectangle(cornerRadius: 5, style: .continuous).fill(GF.feldFokus))
                    .overlay(RoundedRectangle(cornerRadius: 5, style: .continuous).strokeBorder(GF.kevin.opacity(0.6)))
                    .onSubmit { fertig() }
                    .onExitCommand { bearbeiten = false }
                    .onChange(of: fokus) { _, f in if !f && bearbeiten { fertig() } }
            } else {
                Text(session.projektTitel)
                    .font(GS.projekt)
                    .foregroundStyle(GF.kreide)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .frame(maxWidth: schmal ? 150 : nil, alignment: .leading)
                    .fixedSize(horizontal: !schmal, vertical: false)
                    .onTapGesture(count: 2) { beginnen() }
                    .help("Doppelklick: Projekt benennen")
                    .accessibilityLabel("Projekt \(session.projektTitel)")
                    .accessibilityAction(named: "Umbenennen") { beginnen() }
                if session.istEntwurf && !schmal {
                    Text("noch nicht gesichert")
                        .font(GS.projektZusatz)
                        .foregroundStyle(GF.rauch)
                        .lineLimit(1)
                        .help("Liegt als Entwurf in der App. Mit einem Namen zieht es nach \(KevFormat.abbreviatedPath(AppInfo.projectsDirectory.path)).")
                }
            }
            ProjektMenue(model: model, umbenennen: beginnen)
        }
        .onChange(of: session.umbenennenAnfrage) { _, n in if n > 0 { beginnen() } }
    }

    private func beginnen() {
        guard model.project != nil else { return }
        entwurf = session.istEntwurf ? "" : session.projektTitel
        bearbeiten = true
        DispatchQueue.main.async { fokus = true }
    }

    private func fertig() {
        let name = entwurf.trimmingCharacters(in: .whitespacesAndNewlines)
        bearbeiten = false
        guard !name.isEmpty else { return }
        session.projektBenennen(name)
    }
}

/// Pfeil neben dem Projektnamen: Projektmenü.
private struct ProjektMenue: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    let umbenennen: () -> Void

    var body: some View {
        Menu {
            Button("Umbenennen …", action: umbenennen)
                .disabled(model.project == nil)
            Divider()
            Button("Neues Projekt") { session.neuesProjekt() }
            Button("Öffnen …") { session.presentOpenPanel() }
            Button("Letzte Projekte zeigen") { model.oberflaechenActions?.zeigeUebersicht(true) }
            Divider()
            Button("Im Finder zeigen") { session.revealProjectInFinder() }
                .disabled(model.project == nil)
            Button("model.py im Editor öffnen") { session.openModelInEditor() }
                .disabled(model.project == nil)
        } label: {
            Image(systemName: "chevron.down")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(GF.asche)
                .frame(width: 18, height: 18)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Projekt")
        .accessibilityLabel("Projektmenü")
    }
}

/// Knöpfe rechts oben. Im schmalen Fenster nur Foto, Video und „zurück vom Rand“.
private struct Aktionen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    let schmal: Bool
    @ObservedObject private var platzhalter = ViewerPlatzhalter.shared

    private var nav: NavigationActions? { model.actions as? NavigationActions }

    var body: some View {
        HStack(spacing: GA.s) {
            SymbolKnopf(symbol: "camera", titel: "Bildschirmfoto", taste: "⌥⌘S") {
                model.actions?.saveScreenshot()
            }
            .disabled(model.project == nil)
            AufnahmeKnopf(laeuft: platzhalter.videoLaeuft) {
                platzhalter.videoUmschalten(model)
            }
            if !schmal {
                SymbolKnopf(symbol: "ruler", titel: "Messen", taste: "M", an: model.measureMode) {
                    model.toggleMeasureMode()
                }
                .disabled(model.project == nil)
                SymbolKnopf(symbol: "scope", titel: "Isolieren", taste: "/") {
                    if let nav { nav.toggleLocalView() } else { model.isolateSelection() }
                }
                .disabled(model.selection.isEmpty)
            }
            SymbolKnopf(
                symbol: oberflaeche.rand == nil ? "rectangle.righthalf.inset.filled" : "macwindow",
                titel: oberflaeche.rand == nil ? "An den Rand" : "Zurück vom Rand", taste: "⌃⌥→",
                an: oberflaeche.rand != nil
            ) {
                model.oberflaechenActions?.setzeRand(oberflaeche.rand == nil ? .rechts : nil)
            }
        }
    }
}

/// Kurze Meldung in der Kopfleiste (Umbenennen ging nicht, Name entsteht im Code …).
private struct MeldungsZeile: View {
    let meldung: AppSession.Meldung

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(meldung.fehler ? GF.befund : GF.agent).frame(width: 6, height: 6)
            Text(meldung.text)
                .font(GS.klein)
                .foregroundStyle(GF.asche)
                .lineLimit(2)
                .truncationMode(.tail)
        }
        .frame(maxWidth: 420, alignment: .trailing)
        .accessibilityElement(children: .combine)
    }
}

/// Platzhalter für Funktionen, die der Viewer-Strang V2-4 liefert (Video mit einem Klick). Bis dahin merkt er sich nur
/// den Zustand und schreibt eine Zeile ins Protokoll.
@MainActor
final class ViewerPlatzhalter: ObservableObject {
    static let shared = ViewerPlatzhalter()
    @Published private(set) var videoLaeuft = false

    func videoUmschalten(_ model: AppModel) {
        videoLaeuft.toggle()
        model.append(LogLine(level: .warning, text: videoLaeuft
            ? "Video aufnehmen: Platzhalter, die Aufnahme kommt mit V2-4"
            : "Video beendet (Platzhalter bis V2-4)"))
    }
}
