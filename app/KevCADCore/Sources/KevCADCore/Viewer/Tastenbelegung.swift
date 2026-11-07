#if os(macOS)
import AppKit
#endif
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
    case messen, messungAbschliessen, masseUmschalten, masseLoeschen
    // Aufnahme
    case bildschirmfoto, video, navigationAufnehmen
    // Sprechen (V2-6)
    case sprechen, sprechenFertig, sprechenVerwerfen
    // Verlauf von Ansicht, Auswahl und Sichtbarkeit (I-3b)
    case rueckgaengig, wiederholen
    // Werkzeugkranz (I-4)
    case werkzeugkranz
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

    public init(_ flags: PlattformTastenFlags) {
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
    case verlauf = "Rückgängig"
    case kranz = "Werkzeugkranz"
    case hilfe = "Hilfe"
}

/// Auslöser eines Befehls am iPad ohne Tastatur (I-4, Befehlskatalog). Der Werkzeugkranz kommt aus
/// `Tastenbelegung.kranz…` dazu und steht hier nicht noch einmal.
public enum IPadAusloeser: Hashable, Sendable {
    /// Finger- oder Stiftgeste aus `Tastenbelegung.gesten`
    case geste(GestenBelegung.Geste)
    /// Knopf auf dem Bildschirm (Daumenleiste, Knopf „Maße“ …)
    case knopf(String)
    /// bewusst ohne Auslöser am iPad, mit Grund
    case ausnahme(String)

    public var text: String {
        switch self {
        case .geste(let g): return GestenBelegung(geste: g, wirkung: "", zustand: .immer).eingabe
        case .knopf(let k): return "Knopf „\(k)“"
        case .ausnahme(let grund): return "nur mit Tastatur: \(grund)"
        }
    }
}

/// Eine Zeile der Belegung: Befehl, Titel und Tasten (die erste ist das Menükürzel).
public struct Belegung: Identifiable, Sendable {
    public var befehl: ViewerBefehl
    public var titel: String
    public var gruppe: BelegungsGruppe
    public var tasten: [Taste]
    /// Kurze Erklärung für die Übersicht.
    public var erklaerung: String?
    /// Auslöser am iPad außer dem Werkzeugkranz (Gesten, Knöpfe); die Tasten oben gelten am Magic Keyboard ohnehin.
    public var ipad: [IPadAusloeser] = []

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

/// Finger- und Stiftgesten am iPad (PLAN-IPAD.md, 4.2 und 4.3; für Hinweisleiste und Übersicht, ausgewertet in
/// TouchNavigation.swift, das Wischen vom Rand in der iPad-Hülle, RandWischen.swift). Hier steht nur, was die Eingabeebene wirklich tut; eine neue Geste kommt hier und dort im
/// selben Schritt dazu.
public struct GestenBelegung: Identifiable, Sendable {
    /// Kurzname in der Kappe der Hinweisleiste.
    public enum Geste: String, Sendable, CaseIterable {
        case einFinger = "1 Finger", zweiFinger = "2 Finger", spreizen = "Spreizen", tippen = "Tippen",
            doppeltTippen = "2× Tippen", halten = "Halten", zweiFingerTippen = "2 Finger tippen",
            dreiFingerTippen = "3 Finger tippen", randWischen = "Vom Rand", stift = "Stift", schweben = "Schweben",
            stiftDoppelt = "Stift 2×"
    }

    public var geste: Geste
    public var wirkung: String
    public var zustand: MausBelegung.Zustand
    /// Kurzform für die Hinweisleiste (sonst `wirkung`).
    public var kurz: String?

    public init(geste: Geste, wirkung: String, zustand: MausBelegung.Zustand, kurz: String? = nil) {
        self.geste = geste
        self.wirkung = wirkung
        self.zustand = zustand
        self.kurz = kurz
    }

    public var id: String { "\(geste.rawValue)-\(zustand)" }

    /// Ausführlich für die Übersicht: „1 Finger ziehen“, „Lange drücken“.
    public var eingabe: String {
        switch geste {
        case .einFinger: return "1 Finger ziehen"
        case .zweiFinger: return "2 Finger ziehen"
        case .spreizen: return "2 Finger spreizen"
        case .tippen: return "Tippen mit Finger oder Stift"
        case .doppeltTippen: return "Doppeltippen"
        case .halten: return "Lange drücken oder Sekundärklick"
        case .zweiFingerTippen: return "Mit 2 Fingern tippen"
        case .dreiFingerTippen: return "Mit 3 Fingern tippen"
        case .randWischen: return "Vom Rand wischen, zum Rand hin schließt"
        case .stift: return "Stift ziehen"
        case .schweben: return "Stift über dem Glas"
        case .stiftDoppelt: return "Pencil doppelt tippen (Pencil Pro: drücken)"
        }
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
                 tasten: [.z("."), .z(","), .z("f")], erklaerung: "ohne Auswahl alles", ipad: [.geste(.doppeltTippen)]),
        Belegung(befehl: .allesEinrahmen, titel: "Alles einrahmen", gruppe: .ansicht,
                 tasten: [Taste(.pos1), .z("c", .umschalt)], ipad: [.geste(.doppeltTippen)]),
        Belegung(befehl: .ansichtMenue, titel: "Ansichtsmenü", gruppe: .ansicht, tasten: [Taste(.linksVon1)],
                 erklaerung: "Taste links der 1, Maus über dem Viewport"),
        Belegung(befehl: .kameraBlick, titel: "Durch Kamera schauen", gruppe: .ansicht, tasten: [.z("0")]),
        Belegung(befehl: .kameraAufAnsicht, titel: "Aktive Kamera auf Ansicht setzen", gruppe: .ansicht,
                 tasten: [.z("0", [.strg, .wahl])]),
        // Navigation in Schritten
        Belegung(befehl: .drehenLinks, titel: "Nach links drehen", gruppe: .navigation, tasten: [.z("4")],
                 ipad: [.geste(.einFinger)]),
        Belegung(befehl: .drehenRechts, titel: "Nach rechts drehen", gruppe: .navigation, tasten: [.z("6")],
                 ipad: [.geste(.einFinger)]),
        Belegung(befehl: .drehenHoch, titel: "Nach oben drehen", gruppe: .navigation, tasten: [.z("8")],
                 ipad: [.geste(.einFinger)]),
        Belegung(befehl: .drehenRunter, titel: "Nach unten drehen", gruppe: .navigation, tasten: [.z("2")],
                 ipad: [.geste(.einFinger)]),
        Belegung(befehl: .schwenkenLinks, titel: "Nach links schwenken", gruppe: .navigation, tasten: [.z("4", .strg)],
                 ipad: [.geste(.zweiFinger)]),
        Belegung(befehl: .schwenkenRechts, titel: "Nach rechts schwenken", gruppe: .navigation,
                 tasten: [.z("6", .strg)], ipad: [.geste(.zweiFinger)]),
        Belegung(befehl: .schwenkenHoch, titel: "Nach oben schwenken", gruppe: .navigation, tasten: [.z("8", .strg)],
                 ipad: [.geste(.zweiFinger)]),
        Belegung(befehl: .schwenkenRunter, titel: "Nach unten schwenken", gruppe: .navigation,
                 tasten: [.z("2", .strg)], ipad: [.geste(.zweiFinger)]),
        Belegung(befehl: .zoomRein, titel: "Heranzoomen", gruppe: .navigation, tasten: [.z("+")],
                 ipad: [.geste(.spreizen)]),
        Belegung(befehl: .zoomRaus, titel: "Herauszoomen", gruppe: .navigation, tasten: [.z("-")],
                 ipad: [.geste(.spreizen)]),
        // Auswahl
        Belegung(befehl: .allesAuswaehlen, titel: "Alles auswählen", gruppe: .auswahl, tasten: [.z("a")]),
        Belegung(befehl: .auswahlAufheben, titel: "Auswahl aufheben", gruppe: .auswahl, tasten: [.z("a", .wahl)]),
        Belegung(befehl: .auswahlUmkehren, titel: "Auswahl umkehren", gruppe: .auswahl, tasten: [.z("i", .strg)]),
        Belegung(befehl: .elementModus, titel: "Flächen und Kanten auswählen", gruppe: .auswahl,
                 tasten: [Taste(.tab)], erklaerung: "zwischen ganzen Teilen und Elementen wechseln"),
        Belegung(befehl: .abbrechen, titel: "Abbrechen", gruppe: .auswahl, tasten: [Taste(.esc)],
                 erklaerung: "Messen oder Werkzeug beenden, sonst Auswahl aufheben", ipad: [.geste(.tippen)]),
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
        // Kevin, 07.11.2026: „nicht weiß, wie ich Messungen ein- und ausblende … insbesondere auf dem iPad“. Am iPad
        // ohne Tastatur dieselben Befehle über den Knopf „Maße“ unten im Viewer (ViewportArea, MassePill).
        Belegung(befehl: .masseUmschalten, titel: "Maße ein- und ausblenden", gruppe: .messen,
                 tasten: [.z("m", .umschalt)], erklaerung: "auch der Knopf „Maße“ unten im Viewer",
                 ipad: [.knopf("Maße")]),
        Belegung(befehl: .masseLoeschen, titel: "Alle Maße löschen", gruppe: .messen, tasten: [.z("m", .wahl)],
                 erklaerung: "Messungen und stehende Einblendungen des Agenten"),
        // Bild und Video
        Belegung(befehl: .bildschirmfoto, titel: "Bildschirmfoto (PNG)", gruppe: .aufnahme,
                 tasten: [.z("s", [.befehl, .wahl])], erklaerung: "doppelte Auflösung der Ansicht"),
        Belegung(befehl: .video, titel: "Video: Drehung um das Ziel", gruppe: .aufnahme,
                 tasten: [.z("v", [.befehl, .wahl, .umschalt])], erklaerung: "8 s, 60 Bilder/s, HEVC"),
        Belegung(befehl: .navigationAufnehmen, titel: "Navigation aufnehmen (an/aus)", gruppe: .aufnahme,
                 tasten: [.z("r", [.befehl, .wahl, .umschalt])]),
        // Sprechen: ↩ und esc teilen sich die Tasten oben, eine offene Sitzung geht dort vor
        Belegung(befehl: .sprechen, titel: "Sprechen an und aus", gruppe: .sprechen, tasten: [.z("v")],
                 erklaerung: "aus hält an, die Sitzung bleibt offen", ipad: [.knopf("Sprechen")]),
        Belegung(befehl: .sprechenFertig, titel: "Fertig, an den Agenten schicken", gruppe: .sprechen,
                 tasten: [Taste(.eingabe)], erklaerung: "mit Text, Zeiger und Strichen", ipad: [.knopf("Senden")]),
        Belegung(befehl: .sprechenVerwerfen, titel: "Sitzung verwerfen", gruppe: .sprechen, tasten: [Taste(.esc)],
                 ipad: [.knopf("Verwerfen")]),
        // Rückgängig (I-3b): am Mac über das Menü Bearbeiten, solange der Viewer die Tastatur hat; am iPad auch 2 und 3
        // Finger tippen und die Daumenleiste
        Belegung(befehl: .rueckgaengig, titel: "Ansicht, Auswahl oder Sichtbarkeit zurück", gruppe: .verlauf,
                 tasten: [.z("z", .befehl)], erklaerung: "am iPad auch 2 Finger tippen",
                 ipad: [.geste(.zweiFingerTippen), .knopf("↶")]),
        Belegung(befehl: .wiederholen, titel: "Wiederholen", gruppe: .verlauf, tasten: [.z("z", [.befehl, .umschalt])],
                 erklaerung: "am iPad auch 3 Finger tippen", ipad: [.geste(.dreiFingerTippen), .knopf("↷")]),
        // Werkzeugkranz (I-4, PLAN-IPAD.md 4.4): am Mac an der Maus, am iPad an der Stiftspitze
        Belegung(befehl: .werkzeugkranz, titel: "Werkzeugkranz", gruppe: .kranz, tasten: [.z("q")],
                 erklaerung: "Farben, Ansichten, Darstellung und mehr an der Maus; Rad dreht den Regler",
                 ipad: [.geste(.stiftDoppelt), .knopf("Kranz")]),
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

    /// Gesten am iPad; Reihenfolge = Wichtigkeit in der Hinweisleiste (bei wenig Platz fallen die hinteren weg).
    public static let gesten: [GestenBelegung] = [
        GestenBelegung(geste: .einFinger, wirkung: "Drehen um den Punkt unter dem Finger", zustand: .immer,
                       kurz: "Drehen"),
        GestenBelegung(geste: .zweiFinger, wirkung: "Verschieben", zustand: .immer),
        GestenBelegung(geste: .spreizen, wirkung: "Zoomen zur Mitte der Finger", zustand: .immer, kurz: "Zoom"),
        GestenBelegung(geste: .stift, wirkung: "Zeichnen auf dem Modell", zustand: .sprechen, kurz: "Zeichnen"),
        GestenBelegung(geste: .tippen, wirkung: "Auswählen", zustand: .auswahl),
        GestenBelegung(geste: .tippen, wirkung: "Element oder Fangpunkt messen", zustand: .messen, kurz: "Messen"),
        GestenBelegung(geste: .doppeltTippen, wirkung: "Teil einrahmen, auf leerem Grund alles", zustand: .immer,
                       kurz: "Einrahmen"),
        GestenBelegung(geste: .halten, wirkung: "Kontextmenü am Teil: Ausblenden, Isolieren, Messen …",
                       zustand: .auswahl, kurz: "Menü"),
        GestenBelegung(geste: .zweiFingerTippen, wirkung: "Ansicht, Auswahl oder Sichtbarkeit zurück", zustand: .immer,
                       kurz: "Zurück"),
        GestenBelegung(geste: .dreiFingerTippen, wirkung: "Wiederholen", zustand: .immer),
        // I-4: Ein Strich ohne Sitzung beginnt das Sprechen (abschaltbar im Kranz unter „Mehr“, dann dreht der Stift)
        GestenBelegung(geste: .stift, wirkung: "Strich: Sprechen beginnt und der Stift zeichnet", zustand: .auswahl,
                       kurz: "Sprechen"),
        GestenBelegung(geste: .stiftDoppelt, wirkung: "Werkzeugkranz an der Spitze", zustand: .immer, kurz: "Kranz"),
        GestenBelegung(geste: .schweben, wirkung: "Zeigen wie die Maus: Teil leuchtet, beim Messen die Vorschau",
                       zustand: .immer, kurz: "Zeigen"),
        GestenBelegung(geste: .randWischen, wirkung: "Links die Gliederung, rechts die Eigenschaften (wie ⌘1, ⌘2)",
                       zustand: .immer, kurz: "Leisten"),
    ]

    // MARK: Werkzeugkranz (I-4)

    /// Was ein Feld des Kranzes ohne zweiten Ring direkt tut.
    public static func kranzDirekt(_ feld: KranzFeld) -> KranzAktion? {
        feld == .sprechen ? .sprechenOderSenden : nil
    }

    /// Der zweite Ring eines Felds (leer: das Feld wirkt direkt, `kranzDirekt`). Reihenfolge = Lage im Uhrzeigersinn
    /// ab oben; bei den Ansichten liegen Oben, Rechts, Unten und Links in ihrer Richtung.
    public static func kranz(_ feld: KranzFeld) -> [KranzEintrag] {
        switch feld {
        case .sprechen:
            return []
        case .ansichten:
            return [.befehl(.oben, "arrow.up.to.line"), .befehl(.hinten, "square.dashed"),
                    .befehl(.gegenseite, "arrow.triangle.2.circlepath"), .befehl(.rechts, "arrow.right.to.line"),
                    .befehl(.projektion, "perspective", "Perspektive"), .befehl(.vorne, "square"),
                    .befehl(.unten, "arrow.down.to.line"), .befehl(.kameraBlick, "camera", "Kamera"),
                    KranzEintrag("Zweite Ansicht", "rectangle.split.2x1", .kachel(.ansicht)),
                    .befehl(.links, "arrow.left.to.line"),
                    .befehl(.allesEinrahmen, "arrow.up.left.and.arrow.down.right"),
                    .befehl(.auswahlEinrahmen, "scope")]
        case .darstellung:
            return ShadingModus.allCases.filter { $0 != .roentgen }.map {
                KranzEintrag($0.titel, $0.symbol, .darstellung($0))
            } + [.befehl(.roentgen, ShadingModus.roentgen.symbol, "Röntgen"),
                 KranzEintrag(KranzRegler.explosion.name, KranzRegler.explosion.symbol, .regler(.explosion)),
                 KranzEintrag(KranzRegler.schnitt.name, KranzRegler.schnitt.symbol, .regler(.schnitt)),
                 KranzEintrag(KranzRegler.roentgen.name, KranzRegler.roentgen.symbol, .regler(.roentgen)),
                 .befehl(.explosion, "square.stack.3d.up", "Explosion an/aus"),
                 .befehl(.schnitt, "rectangle.split.1x2", "Schnitt an/aus")]
        case .messen:
            return [.befehl(.messen, "ruler", "Messen an/aus"),
                    .befehl(.messungAbschliessen, "circle.dashed", "Element allein messen"),
                    .befehl(.masseUmschalten, "eye.slash", "Maße zeigen"),
                    .befehl(.masseLoeschen, "trash", "Maße löschen")]
        case .sichtbarkeit:
            return [.befehl(.isolieren, "circle.circle", "Isolieren"), .befehl(.ausblenden, "eye.slash"),
                    .befehl(.andereAusblenden, "rectangle.dashed"), .befehl(.allesEinblenden, "eye"),
                    .befehl(.elementModus, "square.on.square.dashed", "Teil oder Element"),
                    .befehl(.allesAuswaehlen, "checkmark.circle"),
                    .befehl(.auswahlUmkehren, "arrow.left.arrow.right"),
                    .befehl(.auswahlAufheben, "xmark.circle")]
        case .kacheln:
            return [(KachelArt.druck, "printer"), (.zeichnung, "doc.richtext"), (.bauplan, "list.number"),
                    (.stueckliste, "list.bullet.rectangle"), (.animation, "play.circle"), (.simulation, "scalemass"),
                    (.versionen, "clock.arrow.circlepath"), (.render, "camera.aperture")].map {
                KranzEintrag($0.0.titel, $0.1, .kachel($0.0))
            }
        case .agent:
            return [KranzEintrag("Bild an den Agenten", "photo.on.rectangle", .bildAnAgent),
                    KranzEintrag("Neu rechnen", "arrow.clockwise", .neuRechnen),
                    KranzEintrag("Meilensteine", "flag", .kachel(.versionen)),
                    .befehl(.sprechenVerwerfen, "xmark", "Sitzung verwerfen")]
        case .mehr:
            let breite = KranzRegler.strichbreite
            return [KranzEintrag(breite.name, breite.symbol, .regler(breite)),
                    KranzEintrag(KranzRegler.animation.name, KranzRegler.animation.symbol, .regler(.animation)),
                    KranzEintrag(KranzRegler.zoomZweite.name, KranzRegler.zoomZweite.symbol, .regler(.zoomZweite)),
                    KranzEintrag("Stift startet Sprechen", "pencil.and.scribble", .stiftSprechen),
                    .befehl(.bildschirmfoto, "camera", "Bildschirmfoto"),
                    .befehl(.video, "video", "Video"),
                    .befehl(.navigationAufnehmen, "record.circle", "Navigation aufnehmen"),
                    .befehl(.kameraAufAnsicht, "camera.viewfinder", "Kamera auf Ansicht"),
                    .befehl(.hinweisleiste, "text.below.photo", "Hinweisleiste"),
                    .befehl(.tastenuebersicht, "keyboard", "Tastenübersicht")]
        }
    }

    /// Seitenblatt eines Felds (nil: keins).
    public static func kranzBlatt(_ feld: KranzFeld) -> KranzBlatt? {
        feld == .darstellung ? .darstellung : nil
    }

    /// Befehle, die ein Feld selbst ersetzt (das Feld tut dasselbe wie die Taste am Mac). Als Tabelle, damit auch
    /// tools/paritaet.py sie findet (`weitere` in paritaet.json).
    static let kranzDecktTabelle: [ViewerBefehl: KranzFeld] = [
        .sprechen: KranzFeld.sprechen, .sprechenFertig: KranzFeld.sprechen, .ansichtMenue: KranzFeld.ansichten,
        .shadingMenue: KranzFeld.darstellung,
    ]

    static func kranzDeckt(_ feld: KranzFeld) -> [ViewerBefehl] {
        ViewerBefehl.allCases.filter { kranzDecktTabelle[$0] == feld }
    }

    /// Weg im Kranz zu einem Befehl („Kranz › Ansichten › Vorne“); nil, wenn er dort nicht liegt.
    public static func kranzWeg(_ befehl: ViewerBefehl) -> String? {
        for f in KranzFeld.allCases {
            if kranzDeckt(f).contains(befehl) { return "Kranz › \(f.name)" }
            if let e = kranz(f).first(where: { $0.aktion == .befehl(befehl) }) {
                return "Kranz › \(f.name) › \(e.name)"
            }
        }
        return nil
    }

    /// Alle Auslöser am iPad ohne Tastatur (Befehlskatalog): Gesten, Knöpfe, Kranz.
    public static func ipadAusloeser(_ befehl: ViewerBefehl) -> [String] {
        var out = (belegung(befehl)?.ipad ?? []).map(\.text)
        if let weg = kranzWeg(befehl) { out.append(weg) }
        return out
    }

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

    /// Befehl zu einem Tastendruck im Viewport (Ziffernblock, Zahlenreihe, ^, ?); nil = nicht belegt. `keyCode` ist der
    /// Tastencode des Mac (am iPad ordnet `NavigationInputView.macTastencode` die HID-Codes zu).
    public static func befehl(keyCode: UInt16, zeichen: String?, flags: PlattformTastenFlags) -> ViewerBefehl? {
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
