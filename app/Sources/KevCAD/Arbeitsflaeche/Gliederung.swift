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
    /// iPad: Diese Gliederung ist zu sehen und nimmt die Pfeiltasten (die verborgene zweite nicht).
    var tastenAktiv = true
    @State private var geoeffnet: Set<String> = []
    @State private var geschlossen: Set<String> = []
    @State private var bearbeitet: String?
    @FocusState private var fokus: Bool
    /// iPad: zählt hoch, wenn eine Zeile gewählt wurde; der Tastenfänger nimmt dann die Tastatur.
    @State private var tastenAnfrage = 0

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
        .onMoveCommand { richtung in
            switch richtung {
            case .up: wandern(.hoch, zeilen: zeilen, gewaehlt: gewaehlt)
            case .down: wandern(.runter, zeilen: zeilen, gewaehlt: gewaehlt)
            case .left: wandern(.links, zeilen: zeilen, gewaehlt: gewaehlt)
            case .right: wandern(.rechts, zeilen: zeilen, gewaehlt: gewaehlt)
            @unknown default: break
            }
        }
        #else
        // iPad (I-3b): Pfeiltasten am Magic Keyboard. Ein Tipp in SwiftUI setzt keinen Tastaturfokus (die Tasten gingen an
        // den Viewer); ein Tipp auf eine Zeile macht deshalb einen kleinen Tastenfänger zum First Responder, wie der Fokus
        // am Mac. Ein Tipp in den Viewer holt die Tastatur wieder dorthin.
        .background {
            if tastenAktiv {
                PfeilFaenger(anfrage: tastenAnfrage) { r in wandern(r, zeilen: zeilen, gewaehlt: gewaehlt) }
            }
        }
        #endif
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
        tastenAnfrage += 1
        var teile = k.partIDs
        if dazu || model.viewer.mehrfach {  // ⇧, ⌘ oder am iPad „Mehrfach“
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

    /// Pfeiltaste in der Gliederung: ↑ ↓ wandern, ← klappt zu, → klappt auf.
    enum Richtung { case hoch, runter, links, rechts }

    private func wandern(_ richtung: Richtung, zeilen: [Zeile], gewaehlt: Set<String>) {
        guard bearbeitet == nil, !zeilen.isEmpty else { return }
        let jetzt = zeilen.firstIndex { istGewaehlt($0, gewaehlt) }
        let ziel: Int
        switch richtung {
        case .hoch: ziel = max(0, (jetzt ?? zeilen.count) - 1)
        case .runter: ziel = min(zeilen.count - 1, (jetzt ?? -1) + 1)
        case .links:
            if let j = jetzt, zeilen[j].knoten.isGroup, istOffen(zeilen[j].knoten, gewaehlt: gewaehlt) {
                umschalten(zeilen[j].knoten, warOffen: true)
            }
            return
        case .rechts:
            if let j = jetzt, zeilen[j].knoten.isGroup, !istOffen(zeilen[j].knoten, gewaehlt: gewaehlt) {
                umschalten(zeilen[j].knoten, warOffen: false)
            }
            return
        }
        model.actions?.select(zeilen[ziel].knoten.partIDs)
    }
}

#if os(iOS)
/// Nimmt am iPad die Pfeiltasten für die Gliederung, sobald eine Zeile gewählt wurde (`anfrage` zählt hoch).
private struct PfeilFaenger: UIViewRepresentable {
    let anfrage: Int
    let wandern: (Gliederung.Richtung) -> Void

    func makeUIView(context: Context) -> PfeilFaengerView {
        let v = PfeilFaengerView()
        v.isUserInteractionEnabled = false
        v.isAccessibilityElement = false
        return v
    }

    func updateUIView(_ v: PfeilFaengerView, context: Context) {
        v.wandern = wandern
        if v.anfrage != anfrage {
            v.anfrage = anfrage
            if anfrage > 0 { DispatchQueue.main.async { _ = v.becomeFirstResponder() } }
        }
    }
}

final class PfeilFaengerView: UIView {
    var wandern: ((Gliederung.Richtung) -> Void)?
    var anfrage = 0

    override var canBecomeFirstResponder: Bool { true }

    override var keyCommands: [UIKeyCommand]? {
        [UIKeyCommand.inputUpArrow, UIKeyCommand.inputDownArrow, UIKeyCommand.inputLeftArrow,
         UIKeyCommand.inputRightArrow].map { taste in
            let k = UIKeyCommand(input: taste, modifierFlags: [], action: #selector(pfeil(_:)))
            k.wantsPriorityOverSystemBehavior = true
            return k
        }
    }

    @objc private func pfeil(_ k: UIKeyCommand) {
        switch k.input {
        case UIKeyCommand.inputUpArrow: wandern?(.hoch)
        case UIKeyCommand.inputDownArrow: wandern?(.runter)
        case UIKeyCommand.inputLeftArrow: wandern?(.links)
        default: wandern?(.rechts)
        }
    }
}
#endif

/// Zeilen im Bild (Fokus): Schatten für die Lesbarkeit über dem Modell.
private struct ImBild: ViewModifier {
    let an: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if an { content.textImBild() } else { content }
    }
}
