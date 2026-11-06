#if os(macOS)
import AppKit
#else
import UIKit
#endif
import KevCADCore
import SwiftUI

/// Gliederung: nur Gruppen und Objekte (V4). Klick wählt, Doppelklick benennt um, ⇧ oder ⌘ nimmt dazu, ↑ und ↓ wandern,
/// Zeilenschalter benennt die gewählte Zeile um. Im Fokus steht sie leise im Bild, in der Werkstatt in der Spalte.
struct Gliederung: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    /// Im Bild über dem Viewer (Fokus): Text mit Schatten, ohne Suche.
    var imBild = false
    /// Suchtext (Werkstatt); leer = alles.
    var filter = ""
    /// Höchstens so hoch, sonst so hoch wie die Zeilen (im Fokus liegt darunter der Viewer, der sein Mausrad behält).
    var maxHoehe: CGFloat?
    @State private var geoeffnet: Set<String> = []
    @State private var geschlossen: Set<String> = []
    @State private var bearbeitet: String?
    @FocusState private var fokus: Bool

    /// Sichtbare Zeile der Gliederung.
    struct Zeile: Identifiable {
        let knoten: PartTreeNode
        let ebene: Int
        var id: String { knoten.id }
    }

    var body: some View {
        let baum = PartTree.filter(PartTree.build(model.parts), query: filter)
        let gewaehlt = Set(model.selectedPartIDs)
        let befunde = befundTeile
        let zeilen = sichtbareZeilen(baum, gewaehlt: gewaehlt)
        ScrollViewReader { leser in
            ScrollView(.vertical) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(zeilen) { z in
                        zeile(z, gewaehlt: gewaehlt, befunde: befunde)
                            .id(z.id)
                    }
                }
                .padding(.horizontal, imBild ? 0 : 2)
            }
            .scrollIndicators(.never)
            .frame(height: maxHoehe.map { min($0, Self.hoehe(zeilen)) })
            .onChange(of: model.selectedPartIDs.first) { _, id in
                guard let id, let z = zeilen.first(where: { $0.knoten.partIDs.contains(id) && !$0.knoten.isGroup })
                    ?? zeilen.first(where: { $0.knoten.partIDs.contains(id) })
                else { return }
                withAnimation(GB.kurz) { leser.scrollTo(z.id, anchor: .center) }
            }
        }
        .focusable()
        .focused($fokus)
        .focusEffectDisabled()
        #if os(macOS)
        .onMoveCommand { richtung in wandern(richtung, zeilen: zeilen, gewaehlt: gewaehlt) }
        #endif
        // iPad: Pfeiltasten einer Hardware-Tastatur folgen in I-3b
        .onKeyPress(.return) {
            guard bearbeitet == nil, let z = zeilen.first(where: { istGewaehlt($0, gewaehlt) }) else { return .ignored }
            bearbeitet = z.id
            return .handled
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Objekte")
    }

    @ViewBuilder
    private func zeile(_ z: Zeile, gewaehlt: Set<String>, befunde: Set<String>) -> some View {
        let k = z.knoten
        let aufgeklappt = istOffen(k, gewaehlt: gewaehlt)
        GliederungsZeile(
            titel: k.name,
            anzahl: k.isGroup ? k.partCount : nil,
            ebene: z.ebene,
            gruppe: k.isGroup,
            offen: aufgeklappt,
            gewaehlt: istGewaehlt(z, gewaehlt),
            befund: !befunde.isDisjoint(with: k.partIDs),
            ausgeblendet: k.allHidden,
            bearbeiten: bearbeitet == k.id,
            aufklappen: { umschalten(k, warOffen: aufgeklappt) },
            waehlen: { dazu in waehlen(k, dazu: dazu, gewaehlt: gewaehlt) },
            umbenennenBeginnen: { bearbeitet = k.id },
            umbenennen: { neu in
                bearbeitet = nil
                if let neu { session.teilBenennen(k.id, gruppe: k.isGroup && k.part == nil, neu: neu) }
            }
        )
        .modifier(ImBild(an: imBild))
        .contextMenu { menue(k) }
    }

    @ViewBuilder
    private func menue(_ k: PartTreeNode) -> some View {
        Button("Umbenennen") { bearbeitet = k.id }
        Button("Zeigen") { model.actions?.focus(on: k.partIDs) }
        Button("Isolieren") { model.actions?.isolate(k.partIDs) }
        Divider()
        if k.allVisible {
            Button("Ausblenden") { model.actions?.setVisibility(k.partIDs, visible: false) }
        } else {
            Button("Einblenden") { model.actions?.setVisibility(k.partIDs, visible: true) }
        }
        Button("Alles einblenden") { model.actions?.showAll() }
        Divider()
        Button("Namen kopieren") { Zwischenablage.setzen(k.partIDs.joined(separator: "\n")) }
    }

    /// Höhe aller sichtbaren Zeilen.
    static func hoehe(_ zeilen: [Zeile]) -> CGFloat {
        zeilen.reduce(0) { $0 + ($1.ebene == 0 ? GA.zeile : GA.zeileKind) }
    }

    // MARK: Zustand

    /// Gruppen sind zu, bis man sie öffnet; eine Gruppe mit gewählten Teilen öffnet sich von selbst (bis man sie
    /// schließt). Beim Filtern ist alles offen.
    private func istOffen(_ k: PartTreeNode, gewaehlt: Set<String>) -> Bool {
        if !filter.trimmingCharacters(in: .whitespaces).isEmpty { return true }
        if geoeffnet.contains(k.id) { return true }
        if geschlossen.contains(k.id) { return false }
        // Offen, wenn eine Auswahl darin liegt, die nicht die ganze Gruppe ist
        let drin = k.partIDs.filter { gewaehlt.contains($0) }
        return !drin.isEmpty && drin.count < k.partCount
    }

    private func umschalten(_ k: PartTreeNode, warOffen: Bool) {
        withAnimation(GB.kurz) {
            if warOffen {
                geoeffnet.remove(k.id)
                geschlossen.insert(k.id)
            } else {
                geschlossen.remove(k.id)
                geoeffnet.insert(k.id)
            }
        }
    }

    private func sichtbareZeilen(_ baum: [PartTreeNode], gewaehlt: Set<String>) -> [Zeile] {
        var out: [Zeile] = []
        func gehe(_ knoten: [PartTreeNode], _ ebene: Int) {
            for k in knoten {
                out.append(Zeile(knoten: k, ebene: ebene))
                if let kinder = k.children, istOffen(k, gewaehlt: gewaehlt) { gehe(kinder, ebene + 1) }
            }
        }
        gehe(baum, 0)
        return out
    }

    /// Gewählt: Teil in der Auswahl, Gruppe ganz in der Auswahl.
    private func istGewaehlt(_ z: Zeile, _ gewaehlt: Set<String>) -> Bool {
        let ids = z.knoten.partIDs
        return !ids.isEmpty && ids.allSatisfy { gewaehlt.contains($0) }
    }

    /// Teile mit Fehlern oder Warnungen der Prüfung oder außerhalb der Inventar-Regel.
    private var befundTeile: Set<String> {
        var s = Set(model.inventarVerstoesse)
        for b in model.pruefung?.befunde ?? [] where b.schwere != .hinweis { s.formUnion(b.teile) }
        return s
    }

    private func waehlen(_ k: PartTreeNode, dazu: Bool, gewaehlt: Set<String>) {
        fokus = true
        var teile = k.partIDs
        if dazu {
            let alle = k.partIDs.allSatisfy { gewaehlt.contains($0) }
            var neu = model.selectedPartIDs
            if alle {
                neu.removeAll { k.partIDs.contains($0) }
            } else {
                neu += k.partIDs.filter { !gewaehlt.contains($0) }
            }
            teile = neu
        }
        model.actions?.select(teile)
    }

    #if os(macOS)
    private func wandern(_ richtung: MoveCommandDirection, zeilen: [Zeile], gewaehlt: Set<String>) {
        guard bearbeitet == nil, !zeilen.isEmpty else { return }
        let jetzt = zeilen.firstIndex { istGewaehlt($0, gewaehlt) }
        let ziel: Int
        switch richtung {
        case .up: ziel = max(0, (jetzt ?? zeilen.count) - 1)
        case .down: ziel = min(zeilen.count - 1, (jetzt ?? -1) + 1)
        case .left:
            if let j = jetzt, zeilen[j].knoten.isGroup, istOffen(zeilen[j].knoten, gewaehlt: gewaehlt) {
                umschalten(zeilen[j].knoten, warOffen: true)
            }
            return
        case .right:
            if let j = jetzt, zeilen[j].knoten.isGroup, !istOffen(zeilen[j].knoten, gewaehlt: gewaehlt) {
                umschalten(zeilen[j].knoten, warOffen: false)
            }
            return
        @unknown default: return
        }
        model.actions?.select(zeilen[ziel].knoten.partIDs)
    }
    #endif
}

/// Zeilen im Bild (Fokus): Schatten für die Lesbarkeit über dem Modell.
private struct ImBild: ViewModifier {
    let an: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if an { content.textImBild() } else { content }
    }
}
