#if os(macOS)
import AppKit
#else
import UIKit
#endif
import KevCADCore
import SwiftUI

/// Kopfleiste des Hauptfensters (V2-9): schwebt ohne eigenen Grund über dem Viewer. Neben der Ampel der Schalter der
/// linken Leiste und der Projektname (Doppelklick benennt um, Pfeil öffnet das Projektmenü); rechts die Darstellung wie
/// in Blender (Röntgen, Drahtgitter, Solid, Material, Technisch, Optionen), Foto, Video, Messen, Isolieren, An den Rand
/// und ganz außen der Schalter der rechten Leiste. Jede Gruppe liegt in einer eigenen Kapsel und bleibt so auf hellem
/// wie dunklem Bild lesbar.
struct Kopfleiste: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var oberflaeche: OberflaechenStore
    /// Breite des Fensters
    let breite: CGFloat

    private var schmal: Bool { breite < GA.schmalAb }
    /// Leisten brauchen Platz neben dem Viewer (wie `Arbeitsgeometrie`)
    private var leisten: Bool { breite >= 760 }
    private var darstellung: Bool { breite >= 900 }
    private var a: OberflaechenActions? { model.oberflaechenActions }
    private var weitereKacheln: Bool { oberflaeche.kacheln.contains { $0 != .modell } }

    var body: some View {
        HStack(spacing: GA.s) {
            HStack(spacing: 2) {
                if leisten {
                    SymbolKnopf(symbol: "sidebar.left", titel: oberflaeche.leisteLinks ? "Objekte ausblenden" : "Objekte einblenden",
                                taste: "⌘1", an: oberflaeche.leisteLinks, form: .kopf) {
                        a?.setzeLeisteLinks(!oberflaeche.leisteLinks)
                    }
                }
                ProjektTitel(model: model, schmal: schmal)
                    .padding(.leading, leisten ? 4 : 8)
            }
            .kopfKapsel()
            Spacer(minLength: GA.s)
            if let meldung = session.meldung {
                MeldungsZeile(meldung: meldung)
                    .kopfKapsel()
                    .transition(.opacity)
            }
            #if os(macOS)
            // I-6: Ansicht mit dem iPad teilen. iPad: der Kopplungs-Chip oben übernimmt das.
            if leisten {
                GeraeteInsel(kopplung: model.kopplung, aktionen: model.actions as? KopplungsActions)
            }
            #endif
            if darstellung {
                Darstellung(viewer: model.viewer, v: model.actions as? ViewerActions)
                    .kopfKapsel()
            }
            Aktionen(model: model, viewer: model.viewer, oberflaeche: oberflaeche, schmal: schmal)
                .kopfKapsel()
            if leisten {
                HStack(spacing: 2) {
                    if weitereKacheln {
                        SymbolKnopf(symbol: "square.grid.2x2", titel: oberflaeche.kachelflaeche ? "Nur das Modell" : "Kacheln nebeneinander",
                                    taste: "⌘3", an: oberflaeche.kachelflaeche, form: .kopf) {
                            a?.vergroessereKachel(oberflaeche.kachelflaeche ? .modell : nil)
                        }
                    }
                    SymbolKnopf(symbol: "sidebar.right",
                                titel: oberflaeche.leisteRechts ? "Eigenschaften ausblenden" : "Eigenschaften einblenden",
                                taste: "⌘2", an: oberflaeche.leisteRechts, form: .kopf) {
                        a?.setzeLeisteRechts(!oberflaeche.leisteRechts)
                    }
                }
                .kopfKapsel()
            }
        }
        .padding(.leading, GA.ampel)
        .padding(.trailing, GA.m)
        .frame(height: GA.kopf)
        .animation(GB.standard, value: session.meldung)
    }
}

private extension View {
    /// Kapsel einer Gruppe in der Kopfleiste: dunkle Insel, damit Knöpfe und Text auch über hellem Bild lesbar sind.
    func kopfKapsel() -> some View {
        padding(2)
            .frame(minHeight: GA.kopfKnopf + 4)
            .background(Capsule(style: .continuous).fill(GF.insel))
            .overlay(Capsule(style: .continuous).strokeBorder(GF.linie, lineWidth: 1))
    }
}

/// Darstellung wie in Blender: Röntgen als Schalter, die Schattierung als Gruppe, daneben die Optionen. Röntgen schaltet
/// wie ⌥Z auf die Darstellung davor zurück.
private struct Darstellung: View {
    @ObservedObject var viewer: ViewerStore
    let v: ViewerActions?

    private static let gruppe: [ShadingModus] = [.drahtgitter, .solid, .material, .technisch]

    var body: some View {
        HStack(spacing: 2) {
            SymbolKnopf(symbol: ShadingModus.roentgen.symbol, titel: "Röntgen", taste: "⌥Z",
                        an: viewer.shading == .roentgen, form: .kopf) {
                v?.ausfuehren(.roentgen)
            }
            Rectangle().fill(GF.linie).frame(width: 1, height: 16)
                .padding(.horizontal, 3)
                .accessibilityHidden(true)
            ForEach(Self.gruppe, id: \.self) { m in
                SymbolKnopf(symbol: m.symbol, titel: m.titel, an: viewer.shading == m, form: .kopf) {
                    v?.setShading(m)
                }
            }
            DarstellungsOptionen(viewer: viewer, v: v)
        }
        .disabled(v == nil)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Darstellung")
    }
}

/// Pfeil neben der Darstellung: Schalter für Umgebungsverdeckung, Kantenbetonung, Schatten, Umriss und Kanten.
private struct DarstellungsOptionen: View {
    @ObservedObject var viewer: ViewerStore
    let v: ViewerActions?

    var body: some View {
        Menu {
            Section("Gilt in Solid, Material und Technisch") {
                ForEach(ShadingOption.allCases, id: \.self) { o in
                    Toggle(o.titel, isOn: Binding(get: { o.istAn(viewer.optionen) },
                                                  set: { v?.setShadingOption(o, $0) }))
                }
            }
        } label: {
            Image(systemName: "chevron.down")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(GF.asche)
                .frame(width: 16, height: GA.kopfKnopf)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Optionen der Darstellung")
        .accessibilityLabel("Optionen der Darstellung")
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
                    .beiEsc { bearbeiten = false }
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
            if AppSession.kannOrdnerWaehlen {  // iPad: Projekte aus der iCloud folgen in I-7
                Button("Öffnen …") { session.presentOpenPanel() }
            }
            Button("Letzte Projekte zeigen") { model.oberflaechenActions?.zeigeUebersicht(true) }
            Divider()
            if AppSession.kannDateienOeffnen {
                Button("Im Finder zeigen") { session.revealProjectInFinder() }
                    .disabled(model.project == nil)
                Button("model.py im Editor öffnen") { session.openModelInEditor() }
                    .disabled(model.project == nil)
            } else {
                // iPad: kein Finder und kein Editor; model.py vom Mac holen und über das Teilen-Blatt weitergeben
                Button("model.py teilen …") { session.openModelInEditor() }
                    .disabled(model.project == nil)
            }
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

/// Knöpfe rechts oben. Im schmalen Fenster nur Foto, Video und „zurück vom Rand“. Foto, Video, Messen und Isolieren
/// sind Befehle des Viewers (V2-4); der Demomodus kennt sie nicht und nimmt die einfachen Aktionen.
private struct Aktionen: View {
    @ObservedObject var model: AppModel
    @ObservedObject var viewer: ViewerStore
    @ObservedObject var oberflaeche: OberflaechenStore
    let schmal: Bool

    private var v: ViewerActions? { model.actions as? ViewerActions }

    var body: some View {
        HStack(spacing: 2) {
            SymbolKnopf(symbol: "camera", titel: "Bildschirmfoto", taste: "⌥⌘S", form: .kopf) {
                if let v { v.ausfuehren(.bildschirmfoto) } else { model.actions?.saveScreenshot() }
            }
            .disabled(model.project == nil)
            AufnahmeKnopf(laeuft: viewer.aufnahme != .keine, form: .kopf) { v?.ausfuehren(.video) }
                .disabled(model.parts.isEmpty || v == nil)
            if !schmal {
                SymbolKnopf(symbol: "ruler", titel: "Messen", taste: "M", an: model.measureMode, form: .kopf) {
                    if let v { v.ausfuehren(.messen) } else { model.toggleMeasureMode() }
                }
                .disabled(model.project == nil)
                SymbolKnopf(symbol: "scope", titel: "Isolieren", taste: "/", an: viewer.lokaleAnsicht, form: .kopf) {
                    if let v { v.ausfuehren(.isolieren) } else { model.isolateSelection() }
                }
                .disabled(model.selection.isEmpty && !viewer.lokaleAnsicht)
            }
            SymbolKnopf(
                symbol: oberflaeche.rand == nil ? "rectangle.righthalf.inset.filled" : "macwindow",
                titel: oberflaeche.rand == nil ? "An den Rand" : "Zurück vom Rand", taste: "⌃⌥→",
                an: oberflaeche.rand != nil, form: .kopf
            ) {
                model.oberflaechenActions?.setzeRand(oberflaeche.rand == nil ? .rechts : nil)
            }
        }
    }
}

#if os(macOS)
// iPad: der Kopplungs-Chip oben (KopplungsAnsicht.swift) übernimmt das.
/// I-6: Kapsel „Ansicht mit dem iPad“, nur solange ein anderes Gerät verbunden ist (beobachtet die Kopplung selbst).
private struct GeraeteInsel: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?

    var body: some View {
        if !kopplung.andere.isEmpty {
            AnsichtTeilenKapsel(kopplung: kopplung, aktionen: aktionen)
                .kopfKapsel()
        }
    }
}
#endif

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
        .padding(.horizontal, 10)
        .frame(maxWidth: 420, alignment: .trailing)
        .accessibilityElement(children: .combine)
    }
}
