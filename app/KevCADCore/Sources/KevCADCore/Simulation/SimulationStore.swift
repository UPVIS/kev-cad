import Foundation
import simd

/// Bereich „Simulation“ im Fenster (additiv zu AppModel, PLAN-SIMULATION.md): letzter Stand (SIM), laufender Auftrag
/// (SIM_JOB), gewählter Lastfall, Werkzeug im Viewer (Kraft, Lager, Schutzfläche) mit dem Entwurf aus dem letzten
/// Klick, Filter und Vergleich der Ergebnistabelle. Die Oberfläche liest den Store und ruft nur `SimulationActions`.
@MainActor
public final class SimulationStore: ObservableObject {
    /// Werkzeug im Viewer: ein Klick auf eine Fläche oder einen Punkt erzeugt einen Entwurf.
    public enum Werkzeug: String, Sendable, CaseIterable {
        case keins, kraft, lager, schutz

        public var hinweis: String {
            switch self {
            case .keins: return ""
            case .kraft: return "Kraft setzen: Fläche oder Punkt am Teil anklicken (Esc beendet)"
            case .lager: return "Lager setzen: Fläche oder Punkt am Teil anklicken (Esc beendet)"
            case .schutz: return "Schutzfläche: Flächen des Druckteils anklicken, noch einmal entfernt sie (Esc beendet)"
            }
        }
    }

    /// Filter der Ergebnistabelle.
    public enum Filter: String, Sendable, CaseIterable {
        case alle, gelbRot, rot

        public var titel: String {
            switch self {
            case .alle: return "Alle"
            case .gelbRot: return "Gelb und rot"
            case .rot: return "Nur rot"
            }
        }
    }

    /// Kraft aus dem letzten Klick, noch nicht gespeichert (oder eine gespeicherte Last in Bearbeitung).
    public struct KraftEntwurf: Equatable, Sendable {
        public var last: SimLast
        /// Gespeicherte Last, die geändert wird (sonst neu).
        public var bearbeitet: String?

        public init(last: SimLast, bearbeitet: String? = nil) {
            self.last = last
            self.bearbeitet = bearbeitet
        }

        /// Kraft (N, Welt) für die Vorschau; nil, wenn sie nicht zu rechnen ist.
        public var kraft: SIMD3<Float>? {
            SimKraft.kraft(last.richtung, betrag: last.betrag, einheit: last.einheit,
                           normale: last.ort.normale, flaecheMm2: last.flaecheMm2)
        }
    }

    /// Welcher Teil des Pfeil-Griffs gezogen wird (additiv, simulation2).
    public enum GriffArt: String, Sendable {
        /// nichts
        case keins
        /// Kugel am Pfeilende: frei im Raum drehen (Arcball)
        case kugel
        /// Breitenkreis durch den Griff: nur der Azimut ändert sich
        case ringAzimut
        /// Meridian durch den Griff: nur die Höhe ändert sich
        case ringHoehe

        public var titel: String {
            switch self {
            case .keins: return ""
            case .kugel: return "frei drehen"
            case .ringAzimut: return "nur Azimut"
            case .ringHoehe: return "nur Höhe"
            }
        }
    }

    static let bildschirmfestSchluessel = "simulationPfeileBildschirmfest"

    @Published public var stand: SimStand?
    @Published public var job: SimJob?
    /// Letzter fertiger Auftrag „Grenze suchen“ (bleibt stehen, bis ein neuer fertig ist).
    @Published public var grenze: SimJob?
    /// Gewählter Lastfall (Name; App oder model.py).
    @Published public var auswahl: String?
    @Published public var werkzeug: Werkzeug = .keins
    @Published public var entwurf: KraftEntwurf?
    /// Lager aus dem letzten Klick (noch nicht gespeichert).
    @Published public var lagerEntwurf: SimLager?
    /// Art und Fläche/Punkt für das nächste Lager.
    @Published public var lagerArt: SimLager.Art = .fest
    @Published public var lagerAuf: SimLager.Auf = .flaeche
    /// Gewählte Last (Kennung) in der Liste des Lastfalls.
    @Published public var lastAuswahl: String?
    @Published public var filter: Filter = .alle
    /// Vergleich: anderer Lastfall (Name) oder `vorherSchluessel` (vorheriger Stand desselben Lastfalls).
    @Published public var vergleich: String?
    /// Vorheriger Stand je Lastfall (für „vorher und nachher“), aus dem letzten STATICS mit anderem Inhalt.
    @Published public var vorher: [String: StatikSzenario] = [:]
    /// Meldung des letzten Auftrags oder einer Änderung (Fehler rot in der Oberfläche).
    @Published public var meldung: String?
    @Published public var meldungFehler = false
    /// Topologie im Bereich: Druckteil und Schutzflächen (Nummern) für die nächste Optimierung.
    @Published public var topologieTeil: String?
    @Published public var schutzFlaechen: [Int] = []
    @Published public var schutzBohrungen = true
    @Published public var schutzEinsaetze = true
    @Published public var schutzKontakt = true
    @Published public var schutzBett = false
    @Published public var steg: Double = 6
    /// Der Bereich Simulation ist vorne: Kräfte, Lager und Flächen stehen im Viewer.
    @Published public var aktiv = false
    /// Der Pfeil-Griff wird gerade gezogen.
    @Published public var griffAktiv = false
    /// Gezogener Teil des Griffs (Kugel, Ring Azimut, Ring Höhe).
    @Published public var griffArt: GriffArt = .keins
    /// Beim Ziehen eingerastet auf eine Achse oder die Normale („−Z“, „Normale“), sonst nil.
    @Published public var eingerastet: String?
    /// Lastfälle für das nächste Lager: nil = alle, Namen = nur diese.
    @Published public var lagerSzenarien: [String]?
    /// Gleitrichtung für das nächste gleitende Lager: nil = in der Fläche.
    @Published public var lagerGleiten: SimGleiten?
    /// Der nächste Klick auf eine Kante setzt die Gleitrichtung (Werkzeug „Lager“).
    @Published public var kanteWaehlen = false
    /// Pfeile, Lagersymbole und Griff mit fester Größe auf dem Bildschirm statt in Millimetern (gemerkt).
    @Published public var pfeileBildschirmfest: Bool = UserDefaults.standard.bool(
        forKey: SimulationStore.bildschirmfestSchluessel) {
        didSet { UserDefaults.standard.set(pfeileBildschirmfest, forKey: Self.bildschirmfestSchluessel) }
    }
    /// Nach dem Speichern einer neuen Kraft: die neue Last wählen, sobald SIM sie bringt.
    public var neueLastErwartet: Bool?
    public var alteLasten: Set<String> = []
    /// Für dieses Druckteil sind die Topologie-Einstellungen aus simulation.json geladen.
    public var topologieGeladen: String?

    /// Ziehen des Griffs (nur App-Kern): Art, Richtung beim Anfassen, freie Richtung jetzt (ohne Einrasten), letzter
    /// Mauspunkt.
    struct GriffZug {
        var art: GriffArt
        var d0: SIMD3<Float>
        var d: SIMD3<Float>
        var letzter: CGPoint
    }

    var griffZug: GriffZug?
    /// Kamera beim letzten Bau der bildschirmfesten Pfeile (Abstand, Drehung, Drehpunkt, Größe), für „nur bei
    /// merklicher Änderung“.
    var bildschirmSchluessel: [Float] = []

    public static let vorherSchluessel = "\u{1F}vorher"

    public init() {}

    public var lastfall: SimLastfall? { stand?.lastfall(auswahl) }

    public var istAppLastfall: Bool { lastfall != nil }

    public var modellLastfall: SimModellLastfall? {
        guard let a = auswahl, lastfall == nil else { return nil }
        return stand?.modell.first { $0.name == a && !$0.ersetzt }
    }

    /// Ein neuer Name, den es noch nicht gibt („Lastfall 3“).
    public func neuerName(_ basis: String = "Lastfall") -> String {
        let vorhanden = Set(stand?.alleNamen ?? [])
        if !vorhanden.contains(basis) && basis != "Lastfall" { return basis }
        var i = (stand?.lastfaelle.count ?? 0) + 1
        while vorhanden.contains("\(basis) \(i)") { i += 1 }
        return "\(basis) \(i)"
    }
}

/// Aktionen des Bereichs Simulation; die Oberfläche ruft sie über `model.actions as? SimulationActions`.
@MainActor
public protocol SimulationActions: AnyObject {
    /// Operationen auf simulation.json (SIM_EDIT); `fertig` mit Erfolg und Meldung.
    func simulationAendern(_ ops: [JSONValue], fertig: ((Bool, String) -> Void)?)
    /// Auftrag starten (SIM_RUN): rechnen, festigkeit, ablauf, grenze (`grenze`: last, neigung, geschwindigkeit).
    func simulationRechnen(was: String, lastfall: String?, teil: String?, fein: Bool, grenze: String?)
    func simulationAbbrechen()
    /// Lastfall wählen: Statik zeigt ihn (Farbverlauf), Kräfte und Lager im Viewer.
    func waehleLastfall(_ name: String?)
    /// Werkzeug im Viewer (Kraft, Lager, Schutzfläche); `.keins` beendet es und verwirft den Entwurf nicht.
    func setSimulationWerkzeug(_ w: SimulationStore.Werkzeug)
    /// Entwurf ändern (Richtung, Betrag …): Pfeil im Viewer folgt.
    func setKraftEntwurf(_ e: SimulationStore.KraftEntwurf?)
    func setLagerEntwurf(_ l: SimLager?)
    /// Entwurf speichern (last_setzen bzw. lager_setzen).
    func kraftEntwurfSpeichern()
    func lagerEntwurfSpeichern()
    /// Gespeicherte Last zum Bearbeiten in den Entwurf holen.
    func lastBearbeiten(_ id: String)
    func waehleLast(_ id: String?)
    /// Teil der Ergebnistabelle zeigen: auswählen, einpassen, Farbverlauf an.
    func zeigeErgebnisTeil(_ name: String)
    /// Schutzfläche an- oder abwählen (Werkzeug „Schutzfläche“ oder Liste).
    func schaltSchutzflaeche(_ index: Int)
    /// Topologie mit den Einstellungen des Bereichs starten (Einstellungen gehen auch in simulation.json).
    func starteSimulationsTopologie(teil: String)
    /// SIM neu anfordern.
    func simulationLaden()
    /// Bereich Simulation vorne (Kräfte, Lager und Flächen im Viewer) oder nicht (Werkzeug endet).
    func setSimulationAktiv(_ an: Bool)
    /// Druckteil für die Topologie im Bereich wählen: Einstellungen und Schutzflächen aus simulation.json laden.
    func waehleTopologieTeil(_ teil: String?)
    /// Ort aus einem Klick (auch ohne Maus, Selbsttest): je Werkzeug Kraft- bzw. Lagerentwurf oder Schutzfläche.
    func simulationOrtGewaehlt(teil: String, flaeche: Int?, punkt: SIMD3<Float>?, normale: SIMD3<Float>?)
    /// Grenze suchen (SIM_RUN `grenze` mit `verfahren`): "s0s1" schnell oder "fem" mit der Festkörper-FEM (additiv).
    func simulationGrenzeSuchen(lastfall: String?, art: String, verfahren: String)
    /// Pfeile, Lagersymbole und Griff bildschirmfest (wahlweise, gemerkt).
    func setPfeileBildschirmfest(_ an: Bool)
    /// Kante gewählt (Werkzeug „Lager“, „Kante wählen“): Gleitrichtung des gleitenden Lagers entlang dieser Kante.
    func simulationKanteGewaehlt(teil: String, kante: Int)
}

// MARK: - Ergebnistabelle (rein, testbar)

/// Eine Zeile der Ergebnistabelle: ein Teil, Stab oder Nachweis eines Lastfalls.
public struct SimErgebnisZeile: Identifiable, Equatable, Sendable {
    public enum Nachweis: String, Sendable, CaseIterable {
        case s0 = "S0", s1 = "S1", fem = "FEM", ablauf = "Ablauf"
    }

    public var id: String
    public var name: String
    public var nachweis: Nachweis
    /// Kriterium (Festigkeit, Kippen, Rutschen, Knicken …).
    public var kriterium: String
    public var sicherheit: Double?
    public var ziel: Double?
    public var ausnutzung: Double
    public var verformungMm: Double?
    public var ampel: StatikAmpel
    public var text: String
    public var loesung: String
    /// Teil im Viewer (nil für Kippen und Rutschen der ganzen Gruppe).
    public var teil: String?

    /// Sortierschlüssel (Table braucht vergleichbare Werte).
    public var sicherheitSort: Double { sicherheit ?? .infinity }
    public var verformungSort: Double { verformungMm ?? -1 }
    public var ampelSort: Int { ampel.rangOeffentlich }
    public var kurzName: String { name.split(separator: "/").last.map(String.init) ?? name }
}

extension StatikAmpel {
    /// Rang für Sortierung (rot 3 … grau 0).
    public var rangOeffentlich: Int { rang }
}

public enum SimErgebnis {
    /// Zeilen eines Szenarios: Teile (FEM vor Stab vor S0-Kragträger), Kippen und Rutschen, Urteile des Ablaufs.
    public static func zeilen(_ sz: StatikSzenario) -> [SimErgebnisZeile] {
        var out: [SimErgebnisZeile] = []
        let staebe = Set(sz.staebe.map(\.name))
        let fem = Dictionary(
            (sz.festkoerper?.teile ?? []).filter { $0.stand == "done" }.map { ($0.teil, $0) },
            uniquingKeysWith: { a, _ in a })
        for t in sz.teile {
            let urteil = sz.urteile.first { $0.teil == t.name && !$0.art.hasPrefix("dyn_") }
            let nachweis: SimErgebnisZeile.Nachweis =
                fem[t.name] != nil || t.fem ? .fem : (staebe.contains(t.name) ? .s1 : .s0)
            let ziel = fem[t.name]?.ziel ?? urteil?.ziel ?? sz.ziel
            out.append(
                SimErgebnisZeile(
                    id: "t\u{1F}\(t.name)", name: t.name, nachweis: nachweis,
                    kriterium: kriteriumText(urteil?.art ?? "festigkeit"), sicherheit: fem[t.name]?.sicherheit
                        ?? t.sicherheit ?? urteil?.sicherheit, ziel: ziel, ausnutzung: t.ausnutzung,
                    verformungMm: fem[t.name]?.verformungMaxMm ?? t.verformungMm, ampel: t.ampel,
                    text: urteil?.text ?? "", loesung: urteil?.loesung ?? "", teil: t.name))
        }
        // FEM-Teile, die (noch) nicht in `teile` stehen
        for (name, f) in fem where !out.contains(where: { $0.teil == name }) {
            out.append(
                SimErgebnisZeile(
                    id: "t\u{1F}\(name)", name: name, nachweis: .fem, kriterium: kriteriumText("festkoerper"),
                    sicherheit: f.sicherheit, ziel: f.ziel,
                    ausnutzung: f.sicherheit.flatMap { s in f.ziel.map { z in s > 0 ? z / s : 9 } } ?? 0,
                    verformungMm: f.verformungMaxMm, ampel: f.ampel, text: f.text, loesung: "", teil: name))
        }
        let schon = Set(out.compactMap(\.teil))
        for u in sz.urteile where u.art != "ueberdimensioniert" {
            let dyn = u.art.hasPrefix("dyn_")
            if let teil = u.teil, schon.contains(teil), !dyn { continue }
            guard dyn || ["kippen", "rutschen", "schraube", "knicken", "durchbiegung", "stabwerk"].contains(u.art)
            else { continue }
            let a = u.ziel.flatMap { z in u.sicherheit.map { s in s > 0 ? z / s : 9 } } ?? ausnutzung(u.ampel)
            out.append(
                SimErgebnisZeile(
                    id: "u\u{1F}\(u.id)\u{1F}\(u.art)", name: u.teil ?? kriteriumText(u.art),
                    nachweis: dyn ? .ablauf : .s0, kriterium: kriteriumText(u.art), sicherheit: u.sicherheit,
                    ziel: u.ziel, ausnutzung: a, verformungMm: nil, ampel: u.ampel, text: u.text,
                    loesung: u.loesung, teil: u.teil.flatMap { $0.contains("(") ? nil : $0 }))
        }
        return out
    }

    /// Ampel aus der Ausnutzung (Ziel / Sicherheit, T9): bis 1 grün, bis 2 gelb, darüber rot.
    public static func ampel(ausnutzung a: Double) -> StatikAmpel {
        a <= 1 ? .gruen : (a <= 2 ? .gelb : .rot)
    }

    static func ausnutzung(_ a: StatikAmpel) -> Double {
        switch a {
        case .gruen: return 0.5
        case .gelb: return 1.5
        case .rot: return 2.5
        case .grau: return 0
        }
    }

    public static func kriteriumText(_ art: String) -> String {
        switch art {
        case "festigkeit": return "Festigkeit"
        case "bauteil": return "Bauteil (Kragträger)"
        case "festkoerper": return "Festkörper"
        case "knicken": return "Knicken"
        case "durchbiegung": return "Durchbiegung"
        case "kippen": return "Kippen"
        case "rutschen": return "Rutschen"
        case "schraube": return "Schrauben"
        case "stabwerk": return "Stabwerk"
        case "dyn_kippen": return "Ablauf: Kippen"
        case "dyn_ladung": return "Ablauf: Ladung"
        case "dyn_rutschen": return "Ablauf: Rutschen"
        default: return art
        }
    }

    /// Filter: alle, gelb und rot, nur rot.
    public static func gefiltert(_ z: [SimErgebnisZeile], _ f: SimulationStore.Filter) -> [SimErgebnisZeile] {
        switch f {
        case .alle: return z
        case .gelbRot: return z.filter { $0.ampel == .gelb || $0.ampel == .rot }
        case .rot: return z.filter { $0.ampel == .rot }
        }
    }

    /// Vergleich zweier Stände: je Zeile (gleiche Kennung) die Sicherheit vorher und nachher, nur mit demselben
    /// Verfahren (FEM mit FEM, S0 mit S0, S1 mit S1, Ablauf mit Ablauf).
    public struct Vergleich: Identifiable, Equatable, Sendable {
        public var id: String
        public var name: String
        public var a: Double?
        public var b: Double?
        public var ampelA: StatikAmpel?
        public var ampelB: StatikAmpel?
        /// Verfahren, mit dem verglichen wird (additiv): S0, S1, FEM oder Ablauf.
        public var verfahren: String? = nil
        /// Gesetzt, wenn die beiden Stände kein gemeinsames Verfahren haben: „nicht vergleichbar (FEM ↔ S0)“; dann
        /// gibt es keine Änderung in Prozent.
        public var hinweis: String? = nil

        /// Änderung der Sicherheit in Prozent (positiv = besser); nil bei verschiedenen Verfahren.
        public var aenderung: Double? {
            guard hinweis == nil, let a, let b, a > 0, a.isFinite, b.isFinite else { return nil }
            return (b - a) / a * 100
        }

        /// Spalte „Verfahren“: „FEM“ oder der Hinweis.
        public var verfahrenText: String { hinweis ?? verfahren ?? "–" }
    }

    /// Werte einer Zeile je Verfahren: das gezeigte (Nachweis der Zeile) und weitere, die im Stand stecken (bei
    /// FEM-Teilen der Kragträger-Wert aus S0).
    struct Werte {
        var primaer: SimErgebnisZeile.Nachweis
        var je: [SimErgebnisZeile.Nachweis: (Double?, StatikAmpel?)]
    }

    static func werteJeVerfahren(_ sz: StatikSzenario) -> [String: Werte] {
        var out: [String: Werte] = [:]
        let fem = Dictionary(
            (sz.festkoerper?.teile ?? []).filter { $0.stand == "done" }.map { ($0.teil, $0) },
            uniquingKeysWith: { a, _ in a })
        for z in zeilen(sz) {
            var w = Werte(primaer: z.nachweis, je: [z.nachweis: (z.sicherheit, z.ampel)])
            if z.nachweis == .fem, let t = z.teil, let k = fem[t]?.kragtraeger {
                let ziel = fem[t]?.ziel ?? z.ziel
                w.je[.s0] = (k, ziel.map { k > 0 ? ampel(ausnutzung: $0 / k) : .rot })
            }
            out[z.id] = w
        }
        return out
    }

    public static func vergleich(_ a: StatikSzenario, _ b: StatikSzenario) -> [Vergleich] {
        let za = Dictionary(zeilen(a).map { ($0.id, $0) }, uniquingKeysWith: { x, _ in x })
        let zb = Dictionary(zeilen(b).map { ($0.id, $0) }, uniquingKeysWith: { x, _ in x })
        let wa = werteJeVerfahren(a), wb = werteJeVerfahren(b)
        var ids = zeilen(a).map(\.id)
        for i in zeilen(b).map(\.id) where za[i] == nil { ids.append(i) }
        let reihe: [SimErgebnisZeile.Nachweis] = [.fem, .s1, .s0, .ablauf]
        return ids.map { i in
            var v = Vergleich(id: i, name: za[i]?.name ?? zb[i]?.name ?? i, a: za[i]?.sicherheit,
                              b: zb[i]?.sicherheit, ampelA: za[i]?.ampel, ampelB: zb[i]?.ampel)
            guard let x = wa[i], let y = wb[i] else {
                v.verfahren = (za[i] ?? zb[i])?.nachweis.rawValue
                return v
            }
            // dasselbe Verfahren wie gezeigt, sonst ein gemeinsames (FEM vor S1 vor S0), sonst nicht vergleichbar
            let gemeinsam: SimErgebnisZeile.Nachweis? =
                x.primaer == y.primaer ? x.primaer : reihe.first { x.je[$0] != nil && y.je[$0] != nil }
            if let g = gemeinsam, let wA = x.je[g], let wB = y.je[g] {
                v.verfahren = g.rawValue
                v.a = wA.0
                v.b = wB.0
                v.ampelA = wA.1 ?? v.ampelA
                v.ampelB = wB.1 ?? v.ampelB
            } else {
                v.hinweis = "nicht vergleichbar (\(x.primaer.rawValue) ↔ \(y.primaer.rawValue))"
            }
            return v
        }
    }
}
