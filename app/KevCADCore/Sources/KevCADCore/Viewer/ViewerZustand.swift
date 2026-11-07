#if os(macOS)
import AppKit
#endif
import Foundation
import SwiftUI

// Zustand und Aktionen des Viewers (V2): Darstellung, Hinweisleiste, Menüs im Viewport, lokale Ansicht, Meldungen,
// Aufnahmen. Die Oberfläche liest `AppModel.viewer` und ruft `model.actions as? ViewerActions`.

/// Darstellungsart des Viewports (Z öffnet die Auswahl, ⌥Z schaltet Röntgen).
public enum ShadingModus: String, CaseIterable, Sendable {
    /// Studiolicht, Teilfarben, Kanten
    case solid
    /// physikalisch basiert mit Umgebungslicht (Metall glänzt, Kunststoff matt)
    case material
    /// durchscheinend mit Kanten
    case roentgen
    /// nur Kanten
    case drahtgitter
    /// Silhouetten und Kanten auf hellem Grund, Teile weiß
    case technisch

    public var titel: String {
        switch self {
        case .solid: return "Solid"
        case .material: return "Material"
        case .roentgen: return "Röntgen"
        case .drahtgitter: return "Drahtgitter"
        case .technisch: return "Technisch"
        }
    }

    public var symbol: String {
        switch self {
        case .solid: return "cube.fill"
        case .material: return "circle.lefthalf.filled"
        case .roentgen: return "square.3.layers.3d"
        case .drahtgitter: return "cube.transparent"
        case .technisch: return "pencil.and.outline"
        }
    }

    /// Name im Protokoll (VIEW_CMD `display`, additiv zu den vier bisherigen).
    public var protokollName: String {
        switch self {
        case .solid: return "solid"
        case .material: return "material"
        case .roentgen: return "xray"
        case .drahtgitter: return "wireframe"
        case .technisch: return "technical"
        }
    }
}

/// Schalter der Darstellung (gelten in Solid, Material und Technisch).
public struct ShadingOptionen: Equatable, Sendable {
    /// Umgebungsverdeckung (SSAO): Ecken und Fugen dunkler
    public var umgebungsverdeckung = true
    /// Kantenbetonung (Cavity): Grate heller, Kehlen dunkler
    public var kantenbetonung = true
    /// Schlagschatten der Hauptlampe
    public var schatten = false
    /// Umriss der ausgewählten Teile
    public var umriss = true
    /// B-Rep-Kanten als Linien
    public var kanten = true

    public init() {}
}

/// Ein Schalter der Darstellung, für Menüs und Aktionen.
public enum ShadingOption: String, CaseIterable, Sendable {
    case umgebungsverdeckung, kantenbetonung, schatten, umriss, kanten

    public var titel: String {
        switch self {
        case .umgebungsverdeckung: return "Umgebungsverdeckung"
        case .kantenbetonung: return "Kantenbetonung"
        case .schatten: return "Schatten"
        case .umriss: return "Umriss der Auswahl"
        case .kanten: return "Kanten"
        }
    }

    public var kurz: String {
        switch self {
        case .umgebungsverdeckung: return "AO"
        case .kantenbetonung: return "Kavität"
        case .schatten: return "Schatten"
        case .umriss: return "Umriss"
        case .kanten: return "Kanten"
        }
    }

    public func istAn(_ o: ShadingOptionen) -> Bool { wert(o) }

    func wert(_ o: ShadingOptionen) -> Bool {
        switch self {
        case .umgebungsverdeckung: return o.umgebungsverdeckung
        case .kantenbetonung: return o.kantenbetonung
        case .schatten: return o.schatten
        case .umriss: return o.umriss
        case .kanten: return o.kanten
        }
    }

    func setzen(_ o: inout ShadingOptionen, _ an: Bool) {
        switch self {
        case .umgebungsverdeckung: o.umgebungsverdeckung = an
        case .kantenbetonung: o.kantenbetonung = an
        case .schatten: o.schatten = an
        case .umriss: o.umriss = an
        case .kanten: o.kanten = an
        }
    }
}

/// Kurze Meldung im Viewport (Bild gespeichert …), optional mit Datei für „Im Finder zeigen“.
public struct ViewerMeldung: Identifiable, Equatable, Sendable {
    public var id = UUID()
    public var text: String
    public var datei: URL?
    public var fehler = false

    public init(text: String, datei: URL? = nil, fehler: Bool = false) {
        self.text = text
        self.datei = datei
        self.fehler = fehler
    }
}

/// Größe des Bildschirmfotos.
public enum FotoGroesse: String, CaseIterable, Sendable {
    /// Ansicht in doppelter Auflösung (Retina-Pixel × 2)
    case doppelt
    /// 3840 × 2160 im Seitenverhältnis der Ansicht
    case uhd4k

    public var titel: String { self == .doppelt ? "Doppelte Auflösung" : "4K" }
}

/// Aufnahme eines Videos.
public enum AufnahmeZustand: Equatable, Sendable {
    case keine
    /// Drehung um das Ziel wird gerechnet (Fortschritt 0…1)
    case drehung(Double)
    /// Navigation wird mitgeschnitten (Beginn)
    case navigation(Date)
    /// Navigation wird zu einem Video gerechnet (Fortschritt 0…1)
    case navigationRechnen(Double)

    public var laeuft: Bool { self != .keine }
}

/// Menü im Viewport an der Mausposition (Ansicht über ^, Darstellung über Z).
public enum ViewerMenue: Equatable, Sendable {
    case ansicht, darstellung
}

@MainActor
public final class ViewerStore: ObservableObject {
    @Published public var shading: ShadingModus = .solid
    @Published public var optionen = ShadingOptionen()
    /// Hinweisleiste am unteren Rand (merkt sich die App).
    @Published public var hinweisleiste: Bool {
        didSet { UserDefaults.standard.set(hinweisleiste, forKey: Self.hinweisKey) }
    }
    @Published public var tastenuebersicht = false
    /// Offenes Menü im Viewport und wo (Punkte, Ursprung oben links).
    @Published public var menue: ViewerMenue?
    @Published public var menuePunkt: CGPoint = .zero
    /// Lokale Ansicht (/) aktiv; `hauch`: die übrigen Teile bleiben als Hauch sichtbar statt ausgeblendet.
    @Published public var lokaleAnsicht = false
    @Published public var hauch: Bool {
        didSet { UserDefaults.standard.set(hauch, forKey: Self.hauchKey) }
    }
    @Published public var meldung: ViewerMeldung?
    @Published public var aufnahme: AufnahmeZustand = .keine
    @Published public var fotoGroesse: FotoGroesse = .doppelt
    /// Platz oben im Viewport, über dem die Kopfleiste des Fensters schwebt (V2-9); der Achsenwürfel rückt darunter.
    @Published public var obenFrei: CGFloat = 0
    /// Messungen und stehende Einblendungen des Agenten im Bild (Kevin, 07.11.2026). Kurze Einblendungen mit Ablauf
    /// und die Beschriftungen von Hervorhebungen bleiben auch ausgeblendet sichtbar. Setzen über `MasseSichtbarkeit`.
    @Published public var masseSichtbar = true
    /// Stehende Einblendungen des Agenten (annotate ohne dauer_s, keine Beschriftung einer Hervorhebung); zählen im
    /// Knopf „Maße“ mit den Messungen zusammen.
    @Published public var stehendeAnmerkungen = 0
    /// I-3b: „Rückgängig: Auswahl“ bzw. „Wiederholen: Ansicht“ für Menü und Daumenleiste; nil = nichts da.
    @Published public internal(set) var rueckgaengigTitel: String?
    /// I-3b: Auswahl erweitern ohne Tastatur (iPad, Knopf „Mehrfach“ der Daumenleiste): Tippen nimmt dazu bzw. wieder
    /// heraus wie Klicken mit ⇧ am Mac. Bleibt an, bis es ausgeschaltet wird.
    @Published public internal(set) var mehrfach = false
    @Published public internal(set) var wiederholenTitel: String?
    /// I-4: offener Werkzeugkranz (nil = zu). Wo er steht, was markiert ist und der Wert eines Drehreglers.
    @Published public var kranz: KranzZustand?
    /// I-4: Farbe der nächsten Striche beim Sprechen (Kranz innen; merkt sich die App).
    @Published public var strichfarbe: Strichfarbe {
        didSet { UserDefaults.standard.set(strichfarbe.rawValue, forKey: Self.farbeKey) }
    }
    /// I-4: Breite der Striche in Punkten (Drehregler im Kranz unter „Mehr“).
    @Published public var strichbreite: Double {
        didSet { UserDefaults.standard.set(strichbreite, forKey: Self.breiteKey) }
    }
    /// I-4: Ein Stiftstrich ohne Sitzung beginnt das Sprechen (Vorgabe an; aus: der Stift dreht wie ein Finger).
    @Published public var stiftSprechen: Bool {
        didSet { UserDefaults.standard.set(stiftSprechen, forKey: Self.stiftKey) }
    }
    /// I-3b: Schwung nach schnellem Loslassen beim Drehen (Kranz › Mehr). Vorgabe am iPad an; am Mac aus, dort bleibt es
    /// wie in Blender beim Stillstand nach dem Loslassen, bis Kevin den Nachlauf des Trackpads einschaltet.
    @Published public var schwung: Bool {
        didSet { UserDefaults.standard.set(schwung, forKey: Self.schwungKey) }
    }

    static let hinweisKey = "viewer.hinweisleiste"
    static let hauchKey = "viewer.hauch"
    static let farbeKey = "viewer.strichfarbe"
    static let breiteKey = "viewer.strichbreite"
    static let stiftKey = "viewer.stiftSprechen"
    /// I-4: Deckkraft im Röntgen (Drehregler im Kranz); gilt für die Szene, gemerkt wie die Strichbreite.
    public static let roentgenKey = "viewer.roentgenDeckkraft"
    static let schwungKey = "viewer.schwung"
    /// Bereich der Strichbreite (Punkte).
    public static let strichbreiten = KranzReglerBereich(min: 1, max: 11, raster: 1)

    public init() {
        let d = UserDefaults.standard
        hinweisleiste = d.object(forKey: Self.hinweisKey) as? Bool ?? true
        hauch = d.object(forKey: Self.hauchKey) as? Bool ?? true
        strichfarbe = (d.string(forKey: Self.farbeKey)).flatMap(Strichfarbe.init(rawValue:)) ?? .blau
        strichbreite = Self.strichbreiten.klemmen(d.object(forKey: Self.breiteKey) as? Double ?? 3)
        stiftSprechen = d.object(forKey: Self.stiftKey) as? Bool ?? true
        #if os(iOS)
        schwung = d.object(forKey: Self.schwungKey) as? Bool ?? true
        #else
        schwung = d.object(forKey: Self.schwungKey) as? Bool ?? false
        #endif
    }

    public func zeige(_ text: String, datei: URL? = nil, fehler: Bool = false) {
        meldung = ViewerMeldung(text: text, datei: datei, fehler: fehler)
    }
}

/// Was gerade mit Maus und Tastatur im Viewport passiert (für die Hinweisleiste). Eigenes Objekt, weil es sich bei
/// jedem Druck auf eine Sondertaste ändert und sonst andere Ansichten neu zeichnen ließe.
@MainActor
public final class ViewerEingabe: ObservableObject {
    public enum Navigation: Equatable, Sendable { case drehen, verschieben, zoomen, rahmen, griff, strich }

    @Published public internal(set) var mods: TastenMods = []
    @Published public internal(set) var navigation: Navigation?
    @Published public internal(set) var mausImViewport = false
    /// Kurzbeschreibung des Elements unter der Maus (Messmodus): „Kreiskante Ø 12,00 mm“.
    @Published public internal(set) var unterMaus: String?
    /// Gesetzte Ziele der laufenden Messung (0, 1).
    @Published public internal(set) var messZiele = 0

    public init() {}
}

/// Aktionen des Viewers. Implementiert vom App-Kern (AppController); Oberfläche, Sprache und Agent rufen sie über
/// `model.actions as? ViewerActions`.
@MainActor
public protocol ViewerActions: AnyObject {
    /// Einen Befehl der Belegung ausführen (Tastatur, Menü, Sprache).
    func ausfuehren(_ befehl: ViewerBefehl)
    func setShading(_ modus: ShadingModus)
    func setShadingOption(_ option: ShadingOption, _ an: Bool)
    /// Lokale Ansicht der Auswahl an/aus; `hauch`: übrige Teile durchscheinend statt ausgeblendet.
    func lokaleAnsicht(hauch: Bool?)
    /// Vorgabe für die lokale Ansicht: übrige Teile als Hauch (an) oder ausgeblendet (aus).
    func setHauch(_ an: Bool)
    /// I-3b: Auswahl erweitern ohne Tastatur an/aus (wie gehaltenes ⇧).
    func setzeMehrfach(_ an: Bool)
    /// Bildschirmfoto der aktuellen Ansicht in den Projektordner.
    func bildschirmfoto(_ groesse: FotoGroesse)
    /// Video: Drehung um das Ziel (8 s, 60 Bilder/s, HEVC).
    func videoDrehung()
    /// Mitschnitt der eigenen Navigation an/aus; beim Beenden entsteht das Video.
    func navigationAufnehmen()
    /// Menü im Viewport öffnen (an der Mausposition).
    func menueOeffnen(_ menue: ViewerMenue?)
    /// Werte einer Messung als Text in die Zwischenablage.
    func messungKopieren(_ id: UUID)
    /// Alle Messungen als Text in die Zwischenablage.
    func messungenKopieren()
    /// I-4: Werkzeugkranz öffnen; `punkt` im Viewport oben links gemessen, nil = an der Maus bzw. der Stiftspitze.
    func kranzOeffnen(bei punkt: CGPoint?)
    /// I-4: Was ein Eintrag oder Feld des Kranzes tut (Drehregler öffnen sich, alles andere schließt den Kranz).
    func kranzAusfuehren(_ aktion: KranzAktion)
    /// I-4: Wert eines Drehreglers setzen (live, beim Drehen).
    func kranzRegler(_ regler: KranzRegler, wert: Double)
    /// I-4: Farbe der nächsten Striche.
    func setStrichfarbe(_ farbe: Strichfarbe)
}

/// Maße im Bild ein- und ausblenden (Knopf „Maße“, ⇧M). Eigenes Protokoll, damit es auch der Demomodus anbietet, der
/// `ViewerActions` nicht kennt. Löschen geht über `AppActions.clearMeasurements()`.
@MainActor
public protocol MasseSichtbarkeit: AnyObject {
    func masseSichtbarSetzen(_ an: Bool)
}
