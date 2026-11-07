#if os(macOS)
import AppKit
#elseif os(iOS)
import UIKit
#endif
import Foundation
import OCCTSwiftViewport

// I-3b (PLAN-IPAD.md 4.2): Kontextmenü am Teil, eine Quelle für beide Geräte. Am Mac öffnet es die rechte Maustaste
// (BlenderNavigation.swift, NSMenu), am iPad langes Drücken oder der Sekundärklick mit Trackpad oder Maus
// (TouchNavigation.swift, UIContextMenuInteraction). Jeder Eintrag ist ein Befehl der Belegung (Tastenbelegung.swift):
// Wirkung und Taste kommen von dort.

/// Ein Eintrag des Kontextmenüs.
public struct KontextEintrag: Sendable {
    public var befehl: ViewerBefehl
    public var titel: String
    /// SF Symbol (das iPad zeigt es, der Mac nicht, wie in seinen Menüs üblich).
    public var symbol: String
    public var aktiv: Bool

    public init(_ befehl: ViewerBefehl, _ titel: String, symbol: String, aktiv: Bool = true) {
        self.befehl = befehl
        self.titel = titel
        self.symbol = symbol
        self.aktiv = aktiv
    }

    /// Taste aus der Belegung (der Mac zeigt sie im Menü).
    public var taste: Taste? { Tastenbelegung.menuTaste(befehl) }
}

extension AppController {
    /// Einträge des Kontextmenüs in Gruppen (zwischen den Gruppen ein Trennstrich).
    ///
    /// `treffer`: Teil unter dem Finger am iPad. Liegt es nicht in der Auswahl, wird es zuerst ausgewählt, damit sich das
    /// Menü auf das gedrückte Teil bezieht: Am iPad gibt es kein Zeigen vor dem Drücken, langes Drücken ist der Griff
    /// „am Teil“. Der Mac übergibt nil und lässt die Auswahl stehen wie Blender (erst links klicken, dann rechts).
    func kontextEintraege(treffer: PickResult?) -> [[KontextEintrag]] {
        if let treffer, !model.measureMode, var ref = scene.resolve(treffer) {
            if model.selectionMode == .parts { ref = ref.partRef }
            let drin = model.selectionMode == .parts
                ? scene.selection.contains { $0.part == ref.part } : scene.selection.contains(ref)
            if !drin {
                measurePending = []
                applySelection([ref])
            }
        }
        let hatAuswahl = !scene.selection.isEmpty
        let hatMasse = !model.measurements.isEmpty || viewer.stehendeAnmerkungen > 0
        return [
            [
                KontextEintrag(.auswahlEinrahmen, hatAuswahl ? "Auswahl zentrieren" : "Alles zentrieren",
                               symbol: "viewfinder"),
                KontextEintrag(.allesEinrahmen, "Alles zeigen", symbol: "arrow.up.left.and.arrow.down.right"),
            ],
            [
                KontextEintrag(.ausblenden, "Ausblenden", symbol: "eye.slash", aktiv: hatAuswahl),
                KontextEintrag(.andereAusblenden, "Andere ausblenden", symbol: "circle.lefthalf.filled",
                               aktiv: hatAuswahl),
                KontextEintrag(.allesEinblenden, "Alles einblenden", symbol: "eye"),
                KontextEintrag(.isolieren, localView == nil ? "Lokale Ansicht" : "Lokale Ansicht beenden",
                               symbol: "scope", aktiv: hatAuswahl || localView != nil),
            ],
            [
                KontextEintrag(.messen, model.measureMode ? "Messen beenden" : "Messen", symbol: "ruler"),
                KontextEintrag(.masseUmschalten, viewer.masseSichtbar ? "Maße ausblenden" : "Maße einblenden",
                               symbol: "ruler.fill", aktiv: hatMasse),
                KontextEintrag(.masseLoeschen, "Alle Maße löschen", symbol: "trash", aktiv: hatMasse || !annotations.isEmpty),
                KontextEintrag(.elementModus,
                               model.selectionMode == .parts ? "Flächen und Kanten auswählen" : "Ganze Teile auswählen",
                               symbol: model.selectionMode == .parts ? "square.on.square.dashed" : "cube"),
            ],
        ]
    }
}

#if os(macOS)
/// NSMenu aus den Einträgen (rechte Maustaste am Mac).
@MainActor
enum KontextmenueMac {
    static func menu(_ gruppen: [[KontextEintrag]], ausfuehren: @escaping (ViewerBefehl) -> Void) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        for (i, gruppe) in gruppen.enumerated() {
            if i > 0 { menu.addItem(.separator()) }
            for e in gruppe {
                let item = NSMenuItem(title: e.titel, action: #selector(MenuClosure.run), keyEquivalent: "")
                if let t = e.taste, let key = taste(t) {
                    item.keyEquivalent = key
                    var mods: NSEvent.ModifierFlags = []
                    if t.mods.contains(.umschalt) { mods.insert(.shift) }
                    if t.mods.contains(.strg) { mods.insert(.control) }
                    if t.mods.contains(.wahl) { mods.insert(.option) }
                    if t.mods.contains(.befehl) { mods.insert(.command) }
                    item.keyEquivalentModifierMask = mods
                }
                let befehl = e.befehl
                let closure = MenuClosure { ausfuehren(befehl) }
                item.target = closure
                item.representedObject = closure
                item.isEnabled = e.aktiv
                menu.addItem(item)
            }
        }
        return menu
    }

    /// Zeichen für `NSMenuItem.keyEquivalent` (nur zur Anzeige; das Kontextmenü löst keine Tasten aus).
    private static func taste(_ t: Taste) -> String? {
        switch t.art {
        case .zeichen(let c): return String(c).lowercased()
        case .pos1: return String(UnicodeScalar(NSHomeFunctionKey)!)
        case .tab: return "\t"
        case .esc: return "\u{1B}"
        case .linksVon1, .eingabe: return nil
        }
    }
}

/// Ziel für Menüeinträge mit Closure (vom Menüeintrag über representedObject festgehalten).
final class MenuClosure: NSObject {
    let action: () -> Void
    init(_ action: @escaping () -> Void) { self.action = action }
    @objc func run() { action() }
}
#elseif os(iOS)
/// UIMenu aus den Einträgen (langes Drücken, Sekundärklick am iPad).
@MainActor
enum KontextmenuePad {
    static func elemente(_ gruppen: [[KontextEintrag]], ausfuehren: @escaping (ViewerBefehl) -> Void) -> [UIMenuElement] {
        gruppen.map { gruppe in
            UIMenu(options: .displayInline, children: gruppe.map { e in
                let befehl = e.befehl
                let a = UIAction(title: e.titel, image: UIImage(systemName: e.symbol)) { _ in
                    MainActor.assumeIsolated { ausfuehren(befehl) }
                }
                if !e.aktiv { a.attributes = .disabled }
                a.accessibilityIdentifier = "kontext.\(befehl.rawValue)"
                return a
            })
        }
    }
}
#endif
