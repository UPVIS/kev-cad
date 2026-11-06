import AppKit
import SwiftUI

// Belegung des Viewers wie in Blender: diese Datei ist die einzige Quelle. Menükürzel (Commands.swift), die Tasten im
// Viewport (Ziffernblock, Zahlenreihe als „Numpad emulieren“, ^ für das Ansichtsmenü), die Hinweisleiste unten im
// Viewport und die Tastenübersicht (?) lesen alle hier. Wer eine Taste ändert, ändert sie nur hier.

/// Ein Befehl des Viewers, unabhängig davon, wie er ausgelöst wird (Taste, Menü, Sprache, Agent).
public enum ViewerBefehl: String, CaseIterable, Sendable {
    // Ansicht
    case vorne, hinten, rechts, links, oben, unten
    case gegenseite, projektion, ansichtMenue
    case auswahlEinrahmen, allesEinrahmen
    case drehenLinks, drehenRechts, drehenHoch, drehenRunter
    case schwenkenLinks, schwenkenRechts, schwenkenHoch, schwenkenRunter
    case zoomRein, zoomRaus
    case kameraBlick, kameraAufAnsicht
    // Auswahl
    case allesAuswaehlen, auswahlAufheben, auswahlUmkehren, elementModus, abbrechen
    // Sichtbarkeit
    case ausblenden, andereAusblenden, allesEinblenden, isolieren
    // Darstellung
    case shadingMenue, roentgen, schnitt, explosion
    // Messen
    case messen, messungAbschliessen
    // Aufnahme
    case bildschirmfoto, video, navigationAufnehmen
    // Sprechen (V2-6)
    case sprechen, sprechenFertig, sprechenVerwerfen
    // Hilfe
    case tastenuebersicht, hinweisleiste
}

/// Sondertasten einer Belegung.
public struct TastenMods: OptionSet, Hashable, Sendable {
    public let rawValue: Int
    public init(rawValue: Int) { self.rawValue = rawValue }
    public static let umschalt = TastenMods(rawValue: 1)
    public static let strg = TastenMods(rawValue: 2)
    public static let wahl = TastenMods(rawValue: 4)
    public static let befehl = TastenMods(rawValue: 8)

    public init(_ flags: NSEvent.ModifierFlags) {
        var m: TastenMods = []
        if flags.contains(.shift) { m.insert(.umschalt) }
        if flags.contains(.control) { m.insert(.strg) }
        if flags.contains(.option) { m.insert(.wahl) }
        if flags.contains(.command) { m.insert(.befehl) }
        self = m
    }

    public var swiftUI: EventModifiers {
        var m: EventModifiers = []
        if contains(.umschalt) { m.insert(.shift) }
        if contains(.strg) { m.insert(.control) }
        if contains(.wahl) { m.insert(.option) }
        if contains(.befehl) { m.insert(.command) }
        return m
    }

    /// „⌃⌥⇧⌘“ in der Reihenfolge des Mac.
    public var zeichen: String {
        (contains(.strg) ? "⌃" : "") + (contains(.wahl) ? "⌥" : "") + (contains(.umschalt) ? "⇧" : "")
            + (contains(.befehl) ? "⌘" : "")
    }
}

/// Eine Taste mit Sondertasten.
public struct Taste: Hashable, Sendable {
    public enum Art: Hashable, Sendable {
        case zeichen(Character)
        case pos1, esc, tab
        /// Taste links der 1 (deutsche Tastatur „^“, ein Akzent ohne eigenes Zeichen): nur im Viewport, kein Menükürzel.
        case linksVon1
        /// Eingabetaste: nur im Viewport (als Menükürzel nähme sie Dialogen ihren Standardknopf).
        case eingabe
    }

    public var art: Art
    public var mods: TastenMods

    public init(_ art: Art, _ mods: TastenMods = []) {
        self.art = art
        self.mods = mods
    }

    public static func z(_ c: Character, _ mods: TastenMods = []) -> Taste { Taste(.zeichen(c), mods) }

    /// Für SwiftUI-Menüs; nil, wenn die Taste kein Menükürzel sein kann.
    public var keyEquivalent: KeyEquivalent? {
        switch art {
        case .zeichen(let c): return KeyEquivalent(c)
        case .pos1: return .home
        case .esc: return .escape
        case .tab: return .tab
        case .linksVon1, .eingabe: return nil
        }
    }

    /// Anzeige wie auf der Tastatur: „⌃1“, „⇧H“, „Pos1“, „^“.
    public var anzeige: String {
        let name: String
        switch art {
        case .zeichen(let c): name = String(c).uppercased()
        case .pos1: name = "Pos1"
        case .esc: name = "Esc"
        case .tab: name = "Tab"
        case .linksVon1: name = "^"
        case .eingabe: name = "↩"
        }
        return mods.zeichen + name
    }

    /// Einbuchstabig ohne Befehls-, Control- und Wahltaste (feuert sonst auch beim Tippen in Textfeldern).
    public var istEinfach: Bool { mods.intersection([.strg, .wahl, .befehl]).isEmpty }
}

/// Gruppen der Tastenübersicht (Reihenfolge = Reihenfolge der Anzeige).
public enum BelegungsGruppe: String, CaseIterable, Sendable {
    case ansicht = "Ansicht"
    case navigation = "Drehen, Schwenken, Zoomen"
    case auswahl = "Auswahl"
    case sichtbarkeit = "Sichtbarkeit"
    case darstellung = "Darstellung"
    case messen = "Messen"
    case aufnahme = "Bild und Video"
    case sprechen = "Sprechen"
    case hilfe = "Hilfe"
}

/// Eine Zeile der Belegung: Befehl, Titel und Tasten (die erste ist das Menükürzel).
public struct Belegung: Identifiable, Sendable {
    public var befehl: ViewerBefehl
    public var titel: String
    public var gruppe: BelegungsGruppe
    public var tasten: [Taste]
    /// Kurze Erklärung für die Übersicht.
    public var erklaerung: String?

    public var id: ViewerBefehl { befehl }
    public var menuTaste: Taste? { tasten.first { $0.keyEquivalent != nil } }
}

/// Maus- und Trackpad-Eingaben (für Hinweisleiste und Übersicht; ausgewertet in BlenderNavigation.swift).
public struct MausBelegung: Identifiable, Sendable {
    public enum Geraet: String, Sendable {
        case links = "Links", mitte = "Mitte", rechts = "Rechts", rad = "Rad", zweiFinger = "2 Finger",
            zusammenziehen = "Zoomgeste"
    }
    public enum Zustand: Sendable { case immer, auswahl, messen, sprechen }

    public var geraet: Geraet
    public var ziehen: Bool
    public var mods: TastenMods
    public var wirkung: String
    public var zustand: Zustand
    /// Kurzform für die Hinweisleiste (sonst `wirkung`).
    public var kurz: String?

    public init(geraet: Geraet, ziehen: Bool, mods: TastenMods, wirkung: String, zustand: Zustand, kurz: String? = nil) {
        self.geraet = geraet
        self.ziehen = ziehen
        self.mods = mods
        self.wirkung = wirkung
        self.zustand = zustand
        self.kurz = kurz
    }

    public var id: String { "\(geraet.rawValue)-\(ziehen)-\(mods.rawValue)-\(zustand)" }

    /// „Mitte ziehen“, „⇧ Links“, „Rad“.
    public var eingabe: String {
        let g: String
        switch geraet {
        case .rad, .zweiFinger, .zusammenziehen: g = geraet.rawValue
        default: g = geraet.rawValue + (ziehen ? " ziehen" : " klicken")
        }
        return mods.isEmpty ? g : mods.zeichen + " " + g
    }
}

/// Die Belegung des Viewers.
public enum Tastenbelegung {
    public static let alle: [Belegung] = [
        // Ansicht (Ziffernblock oder Zahlenreihe, „Numpad emulieren“)
        Belegung(befehl: .vorne, titel: "Vorne", gruppe: .ansicht, tasten: [.z("1")]),
        Belegung(befehl: .hinten, titel: "Hinten", gruppe: .ansicht, tasten: [.z("1", .strg)]),
        Belegung(befehl: .rechts, titel: "Rechts", gruppe: .ansicht, tasten: [.z("3")]),
        Belegung(befehl: .links, titel: "Links", gruppe: .ansicht, tasten: [.z("3", .strg)]),
        Belegung(befehl: .oben, titel: "Oben", gruppe: .ansicht, tasten: [.z("7")]),
        Belegung(befehl: .unten, titel: "Unten", gruppe: .ansicht, tasten: [.z("7", .strg)]),
        Belegung(befehl: .gegenseite, titel: "Gegenseite", gruppe: .ansicht, tasten: [.z("9")],
                 erklaerung: "Blick von der anderen Seite"),
        Belegung(befehl: .projektion, titel: "Perspektive oder parallel", gruppe: .ansicht, tasten: [.z("5")]),
        Belegung(befehl: .auswahlEinrahmen, titel: "Auswahl einrahmen", gruppe: .ansicht,
                 tasten: [.z("."), .z(","), .z("f")], erklaerung: "ohne Auswahl alles"),
        Belegung(befehl: .allesEinrahmen, titel: "Alles einrahmen", gruppe: .ansicht,
                 tasten: [Taste(.pos1), .z("c", .umschalt)]),
        Belegung(befehl: .ansichtMenue, titel: "Ansichtsmenü", gruppe: .ansicht, tasten: [Taste(.linksVon1)],
                 erklaerung: "Taste links der 1, Maus über dem Viewport"),
        Belegung(befehl: .kameraBlick, titel: "Durch Kamera schauen", gruppe: .ansicht, tasten: [.z("0")]),
        Belegung(befehl: .kameraAufAnsicht, titel: "Aktive Kamera auf Ansicht setzen", gruppe: .ansicht,
                 tasten: [.z("0", [.strg, .wahl])]),
        // Navigation in Schritten
        Belegung(befehl: .drehenLinks, titel: "Nach links drehen", gruppe: .navigation, tasten: [.z("4")]),
        Belegung(befehl: .drehenRechts, titel: "Nach rechts drehen", gruppe: .navigation, tasten: [.z("6")]),
        Belegung(befehl: .drehenHoch, titel: "Nach oben drehen", gruppe: .navigation, tasten: [.z("8")]),
        Belegung(befehl: .drehenRunter, titel: "Nach unten drehen", gruppe: .navigation, tasten: [.z("2")]),
        Belegung(befehl: .schwenkenLinks, titel: "Nach links schwenken", gruppe: .navigation, tasten: [.z("4", .strg)]),
        Belegung(befehl: .schwenkenRechts, titel: "Nach rechts schwenken", gruppe: .navigation,
                 tasten: [.z("6", .strg)]),
        Belegung(befehl: .schwenkenHoch, titel: "Nach oben schwenken", gruppe: .navigation, tasten: [.z("8", .strg)]),
        Belegung(befehl: .schwenkenRunter, titel: "Nach unten schwenken", gruppe: .navigation,
                 tasten: [.z("2", .strg)]),
        Belegung(befehl: .zoomRein, titel: "Heranzoomen", gruppe: .navigation, tasten: [.z("+")]),
        Belegung(befehl: .zoomRaus, titel: "Herauszoomen", gruppe: .navigation, tasten: [.z("-")]),
        // Auswahl
        Belegung(befehl: .allesAuswaehlen, titel: "Alles auswählen", gruppe: .auswahl, tasten: [.z("a")]),
        Belegung(befehl: .auswahlAufheben, titel: "Auswahl aufheben", gruppe: .auswahl, tasten: [.z("a", .wahl)]),
        Belegung(befehl: .auswahlUmkehren, titel: "Auswahl umkehren", gruppe: .auswahl, tasten: [.z("i", .strg)]),
        Belegung(befehl: .elementModus, titel: "Flächen und Kanten auswählen", gruppe: .auswahl,
                 tasten: [Taste(.tab)], erklaerung: "zwischen ganzen Teilen und Elementen wechseln"),
        Belegung(befehl: .abbrechen, titel: "Abbrechen", gruppe: .auswahl, tasten: [Taste(.esc)],
                 erklaerung: "Messen oder Werkzeug beenden, sonst Auswahl aufheben"),
        // Sichtbarkeit
        Belegung(befehl: .ausblenden, titel: "Ausblenden", gruppe: .sichtbarkeit, tasten: [.z("h")]),
        Belegung(befehl: .andereAusblenden, titel: "Andere ausblenden", gruppe: .sichtbarkeit,
                 tasten: [.z("h", .umschalt)]),
        Belegung(befehl: .allesEinblenden, titel: "Alles einblenden", gruppe: .sichtbarkeit, tasten: [.z("h", .wahl)]),
        Belegung(befehl: .isolieren, titel: "Isolieren (lokale Ansicht)", gruppe: .sichtbarkeit, tasten: [.z("/")],
                 erklaerung: "nur die Auswahl, noch einmal: zurück"),
        // Darstellung
        Belegung(befehl: .shadingMenue, titel: "Darstellung wählen", gruppe: .darstellung, tasten: [.z("z")],
                 erklaerung: "Solid, Material, Röntgen, Drahtgitter, Technisch"),
        Belegung(befehl: .roentgen, titel: "Röntgen an/aus", gruppe: .darstellung, tasten: [.z("z", .wahl)]),
        Belegung(befehl: .schnitt, titel: "Schnitt", gruppe: .darstellung, tasten: [.z("s")]),
        Belegung(befehl: .explosion, titel: "Explosion", gruppe: .darstellung, tasten: [.z("e")]),
        // Messen
        Belegung(befehl: .messen, titel: "Messen", gruppe: .messen, tasten: [.z("m")],
                 erklaerung: "Fangen an Ecken, Kantenmitten und Kreismitten"),
        Belegung(befehl: .messungAbschliessen, titel: "Gewähltes Element allein messen", gruppe: .messen,
                 tasten: [Taste(.eingabe)], erklaerung: "Radius und Durchmesser, Länge, Fläche"),
        // Bild und Video
        Belegung(befehl: .bildschirmfoto, titel: "Bildschirmfoto (PNG)", gruppe: .aufnahme,
                 tasten: [.z("s", [.befehl, .wahl])], erklaerung: "doppelte Auflösung der Ansicht"),
        Belegung(befehl: .video, titel: "Video: Drehung um das Ziel", gruppe: .aufnahme,
                 tasten: [.z("v", [.befehl, .wahl, .umschalt])], erklaerung: "8 s, 60 Bilder/s, HEVC"),
        Belegung(befehl: .navigationAufnehmen, titel: "Navigation aufnehmen (an/aus)", gruppe: .aufnahme,
                 tasten: [.z("r", [.befehl, .wahl, .umschalt])]),
        // Sprechen: ↩ und esc teilen sich die Tasten oben, eine offene Sitzung geht dort vor
        Belegung(befehl: .sprechen, titel: "Sprechen an und aus", gruppe: .sprechen, tasten: [.z("v")],
                 erklaerung: "aus hält an, die Sitzung bleibt offen"),
        Belegung(befehl: .sprechenFertig, titel: "Fertig, an den Agenten schicken", gruppe: .sprechen,
                 tasten: [Taste(.eingabe)], erklaerung: "mit Text, Zeiger und Strichen"),
        Belegung(befehl: .sprechenVerwerfen, titel: "Sitzung verwerfen", gruppe: .sprechen, tasten: [Taste(.esc)]),
        // Hilfe
        Belegung(befehl: .tastenuebersicht, titel: "Tastenübersicht", gruppe: .hilfe, tasten: [.z("?")]),
        Belegung(befehl: .hinweisleiste, titel: "Hinweisleiste an/aus", gruppe: .hilfe,
                 tasten: [.z("h", [.befehl, .wahl, .umschalt])]),
    ]

    /// Reihenfolge = Wichtigkeit in der Hinweisleiste (bei wenig Platz fallen die hinteren weg).
    public static let maus: [MausBelegung] = [
        MausBelegung(geraet: .mitte, ziehen: true, mods: [], wirkung: "Drehen um Punkt unter der Maus", zustand: .immer,
                     kurz: "Drehen"),
        MausBelegung(geraet: .mitte, ziehen: true, mods: .umschalt, wirkung: "Verschieben", zustand: .immer),
        MausBelegung(geraet: .rad, ziehen: false, mods: [], wirkung: "Zoomen zur Maus", zustand: .immer, kurz: "Zoom"),
        MausBelegung(geraet: .links, ziehen: true, mods: [], wirkung: "Zeichnen auf dem Modell", zustand: .sprechen,
                     kurz: "Zeichnen"),
        MausBelegung(geraet: .links, ziehen: false, mods: [], wirkung: "Auswählen", zustand: .auswahl),
        MausBelegung(geraet: .links, ziehen: false, mods: [], wirkung: "Element oder Fangpunkt messen",
                     zustand: .messen, kurz: "Messen"),
        MausBelegung(geraet: .links, ziehen: true, mods: [], wirkung: "Rahmen aufziehen", zustand: .auswahl,
                     kurz: "Rahmen"),
        MausBelegung(geraet: .rechts, ziehen: false, mods: [], wirkung: "Kontextmenü", zustand: .auswahl, kurz: "Menü"),
        MausBelegung(geraet: .links, ziehen: false, mods: .umschalt, wirkung: "Auswahl ergänzen", zustand: .auswahl,
                     kurz: "Ergänzen"),
        MausBelegung(geraet: .links, ziehen: true, mods: .umschalt, wirkung: "Rahmen ergänzt", zustand: .auswahl,
                     kurz: "Rahmen ergänzt"),
        MausBelegung(geraet: .links, ziehen: true, mods: .strg, wirkung: "Rahmen zieht ab", zustand: .auswahl,
                     kurz: "Rahmen zieht ab"),
        MausBelegung(geraet: .mitte, ziehen: true, mods: .strg, wirkung: "Zoomen", zustand: .immer),
        MausBelegung(geraet: .mitte, ziehen: false, mods: .wahl, wirkung: "Ansicht auf Punkt", zustand: .immer),
        MausBelegung(geraet: .links, ziehen: true, mods: .wahl, wirkung: "Drehen wie Mitte", zustand: .immer,
                     kurz: "Drehen"),
        MausBelegung(geraet: .rad, ziehen: false, mods: .strg, wirkung: "Waagrecht schwenken", zustand: .immer),
        MausBelegung(geraet: .rad, ziehen: false, mods: .umschalt, wirkung: "Senkrecht schwenken", zustand: .immer),
        MausBelegung(geraet: .zweiFinger, ziehen: false, mods: [], wirkung: "Drehen", zustand: .immer),
        MausBelegung(geraet: .zweiFinger, ziehen: false, mods: .umschalt, wirkung: "Verschieben", zustand: .immer),
        MausBelegung(geraet: .zweiFinger, ziehen: false, mods: .strg, wirkung: "Zoomen", zustand: .immer),
        MausBelegung(geraet: .zusammenziehen, ziehen: false, mods: [], wirkung: "Zoomen zur Maus", zustand: .immer),
    ]

    public static func belegung(_ befehl: ViewerBefehl) -> Belegung? { alle.first { $0.befehl == befehl } }

    public static func menuTaste(_ befehl: ViewerBefehl) -> Taste? { belegung(befehl)?.menuTaste }

    /// Alle Zeichen, die einbuchstabig (ohne Befehls-, Control-, Wahltaste) belegt sind; der KeyboardGuard leitet sie
    /// an Textfelder weiter statt ans Menü.
    public static var einfacheZeichen: Set<String> {
        var out = Set<String>()
        for b in alle {
            for t in b.tasten where t.istEinfach {
                if case .zeichen(let c) = t.art { out.insert(String(c).lowercased()) }
            }
        }
        return out
    }

    // MARK: Tastendruck im Viewport → Befehl

    /// Tastencodes des Ziffernblocks (unabhängig vom Tastaturlayout).
    static let ziffernblock: [UInt16: Character] = [
        82: "0", 83: "1", 84: "2", 85: "3", 86: "4", 87: "5", 88: "6", 89: "7", 91: "8", 92: "9",
        65: ".", 69: "+", 78: "-", 75: "/",
    ]
    /// Taste links der 1: ISO (deutsche Tastatur „^“) und ANSI („`“).
    static let linksVon1Codes: Set<UInt16> = [10, 50]
    static let pos1Code: UInt16 = 115
    static let eingabeCodes: Set<UInt16> = [36, 76]

    /// Befehl zu einem Tastendruck im Viewport (Ziffernblock, Zahlenreihe, ^, ?); nil = nicht belegt.
    public static func befehl(keyCode: UInt16, zeichen: String?, flags: NSEvent.ModifierFlags) -> ViewerBefehl? {
        var mods = TastenMods(flags)
        let art: Taste.Art
        if linksVon1Codes.contains(keyCode) {
            art = .linksVon1
        } else if keyCode == pos1Code {
            art = .pos1
        } else if eingabeCodes.contains(keyCode) {
            art = .eingabe
        } else if let c = ziffernblock[keyCode] {
            art = .zeichen(c)
        } else if let z = zeichen?.lowercased(), let c = z.first, z.count == 1 {
            art = .zeichen(c)
            // Zeichen, für die es die Umschalttaste braucht (?, /), tragen sie nicht als eigene Sondertaste
            if !c.isLetter, !c.isNumber { mods.remove(.umschalt) }
        } else {
            return nil
        }
        let gesucht = Taste(art, mods)
        if let b = alle.first(where: { $0.tasten.contains(gesucht) }) { return b.befehl }
        // Ziffernblock und Zahlenreihe: Umschalttaste nicht als Teil der Belegung verlangen
        return nil
    }
}

/// SwiftUI: Tastenkürzel eines Viewer-Befehls aus der Belegung setzen.
extension View {
    public func tastenkuerzel(_ befehl: ViewerBefehl) -> some View {
        modifier(TastenkuerzelModifier(taste: Tastenbelegung.menuTaste(befehl)))
    }
}

private struct TastenkuerzelModifier: ViewModifier {
    let taste: Taste?

    func body(content: Content) -> some View {
        if let taste, let key = taste.keyEquivalent {
            content.keyboardShortcut(key, modifiers: taste.mods.swiftUI)
        } else {
            content
        }
    }
}
