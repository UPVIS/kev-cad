import AppKit
import KevCADCore
import SwiftUI

/// Abschnitt des Bereichs „Material“ (Seitenleiste, Menü, Sprung aus Schnellansichten und Berichten).
enum MaterialAbschnitt: String, CaseIterable, Identifiable {
    case uebersicht, stueckliste, zuschnitt, bestand, einkauf, zukauf, druck

    var id: String { rawValue }

    var titel: String {
        switch self {
        case .uebersicht: return "Übersicht"
        case .stueckliste: return "Stückliste"
        case .zuschnitt: return "Zuschnitt"
        case .bestand: return "Bestand"
        case .einkauf: return "Einkaufsliste"
        case .zukauf: return "Zukaufteile"
        case .druck: return "Druckteile"
        }
    }

    var symbol: String {
        switch self {
        case .uebersicht: return "square.grid.2x2"
        case .stueckliste: return "list.bullet.rectangle"
        case .zuschnitt: return "scissors"
        case .bestand: return "shippingbox"
        case .einkauf: return "cart"
        case .zukauf: return "bag"
        case .druck: return "printer"
        }
    }

    /// Bericht in „Dokumente“, der denselben Inhalt druckt („Als Bericht drucken“).
    var bericht: ExportBausteinArt {
        switch self {
        case .uebersicht, .stueckliste, .zukauf, .druck: return .stueckliste
        case .zuschnitt: return .zuschnitt
        case .bestand, .einkauf: return .einkaufsliste
        }
    }

    /// Abschnitt zu einem Bericht („Im Material-Bereich öffnen“).
    init(bericht: ExportBausteinArt) {
        switch bericht {
        case .zuschnitt: self = .zuschnitt
        case .einkaufsliste: self = .einkauf
        default: self = .stueckliste
        }
    }
}

/// Zustand des Bereichs „Material“ je Projektfenster (nur Oberfläche). Über `focusedSceneObject` erreichen ihn auch die
/// Menübefehle.
@MainActor
final class MaterialZustand: ObservableObject {
    @Published var abschnitt: MaterialAbschnitt = .uebersicht {
        didSet { UserDefaults.standard.set(abschnitt.rawValue, forKey: "material.abschnitt") }
    }
    /// Gewählte Positionen (Stückliste, Zukauf, Druck, Zuschnitt): wirkt in beide Richtungen mit 3D und Teilebaum.
    @Published var auswahl: Set<Int> = []
    /// Lagerteil, zu dem der Zuschnitt scrollen soll (Sprung aus der Schnellansicht oder dem Bestand).
    @Published var zuschnittFokus: String?
    /// Position, zu der die Stückliste scrollen soll.
    @Published var stuecklisteFokus: Int?
    @Published var suche = ""
    @Published var gruppieren = UserDefaults.standard.object(forKey: "material.gruppieren") as? Bool ?? true {
        didSet { UserDefaults.standard.set(gruppieren, forKey: "material.gruppieren") }
    }
    /// Gewählte Zeile der Einkaufsliste (für den Inspektor).
    @Published var einkaufAuswahl: String?
    /// Abgehakte Zeilen der Einkaufsliste des offenen Projekts.
    @Published private(set) var abgehakt = EinkaufAbgehakt()
    private var abgehaktProjekt: URL?

    let bilder = MaterialBilderSpeicher()

    init() {
        if let a = UserDefaults.standard.string(forKey: "material.abschnitt").flatMap(MaterialAbschnitt.init(rawValue:)) {
            abschnitt = a
        }
    }

    /// Abschnitt zeigen, auf Wunsch mit Position bzw. Lagerteil im Blick.
    func zeige(_ a: MaterialAbschnitt, position: Int? = nil, stockID: String? = nil) {
        abschnitt = a
        if let position {
            auswahl = [position]
            stuecklisteFokus = position
        }
        if let stockID { zuschnittFokus = stockID }
    }

    // MARK: Abhaken

    func ladeAbgehakt(_ projekt: URL?) {
        guard projekt != abgehaktProjekt else { return }
        abgehaktProjekt = projekt
        guard let projekt else {
            abgehakt = EinkaufAbgehakt()
            return
        }
        let liste = UserDefaults.standard.stringArray(forKey: EinkaufAbgehakt.defaultsKey(projekt)) ?? []
        abgehakt = EinkaufAbgehakt(Set(liste))
    }

    func setzeAbgehakt(_ neu: EinkaufAbgehakt) {
        abgehakt = neu
        if let p = abgehaktProjekt {
            UserDefaults.standard.set(Array(neu.schluessel).sorted(), forKey: EinkaufAbgehakt.defaultsKey(p))
        }
    }

    func umschalten(_ z: MaterialEinkauf) {
        var a = abgehakt
        a.umschalten(z)
        setzeAbgehakt(a)
    }
}

/// Vorschaubilder je Teil (wie im Bericht), nachgeladen vom App-Kern und im Fenster gehalten.
@MainActor
final class MaterialBilderSpeicher: ObservableObject {
    @Published private(set) var bilder: [String: NSImage] = [:]
    private var geladenFuer: Int?
    private var laeuft = false

    func bild(_ p: MaterialPosition) -> NSImage? {
        for t in p.teile { if let b = bilder[t] { return b } }
        return nil
    }

    /// Bilder für das erste Teil jeder Position holen (einmal je Lauf; der App-Kern hält sie je Formstand).
    func lade(_ model: AppModel, daten: MaterialDaten) {
        guard let actions = model.materialBildActions, daten.run != geladenFuer, !laeuft else { return }
        let namen = daten.positionen.compactMap { p in p.teile.first { t in model.parts.contains { $0.id == t } } }
        guard !namen.isEmpty else { return }
        laeuft = true
        let run = daten.run
        Task { @MainActor in
            let neu = await actions.materialBilder(namen)
            var b = self.bilder
            for (name, cg) in neu { b[name] = NSImage(cgImage: cg, size: NSSize(width: cg.width / 2, height: cg.height / 2)) }
            self.bilder = b
            self.geladenFuer = run
            self.laeuft = false
            // Kam inzwischen ein neuer Lauf, gleich noch einmal
            if model.bom?.run != run { self.lade(model, daten: model.materialDaten) }
        }
    }
}

/// Sprünge zwischen den Bereichen für Ansichten außerhalb des Bereichs „Material“ (Berichte, Bauplan, Inspektor,
/// Schnellansichten): gesetzt vom Projektfenster, sonst nil (dann bleiben die Knöpfe aus).
struct MaterialNavigation {
    var zeige: @MainActor (MaterialAbschnitt, Int?, String?) -> Void
    var bericht: @MainActor (ExportBausteinArt) -> Void
}

private struct MaterialNavigationKey: EnvironmentKey {
    static let defaultValue: MaterialNavigation? = nil
}

extension EnvironmentValues {
    var materialNavigation: MaterialNavigation? {
        get { self[MaterialNavigationKey.self] }
        set { self[MaterialNavigationKey.self] = newValue }
    }
}
