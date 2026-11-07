import Foundation

// V2-6: eine Sitzung von V bis ↩ auf einer Uhr. Wörter, Mausweg, Striche, Kamera und Auswahl kommen hier zusammen; beim
// Abschließen bekommt jeder Satz, worauf Kevin beim Sprechen gezeigt hat (PROTOCOL.md, „V2-6 Sprach-Feedback“).
// Reine Logik ohne Fenster und Ton: `AppController+Sprache.swift` füttert sie, Tests rufen sie direkt.

public struct FeedbackSitzung: Sendable {
    public typealias Paket = FeedbackPaket

    /// Ein erkannter Satz in Uhrzeit der Sitzung.
    public struct RohSatz: Equatable, Sendable {
        public var text: String
        public var von: Double
        public var bis: Double
        public var worte: [RohWort]
        public var vorlaeufig: Bool

        public init(text: String, von: Double, bis: Double, worte: [RohWort] = [], vorlaeufig: Bool = false) {
            self.text = text
            self.von = von
            self.bis = bis
            self.worte = worte
            self.vorlaeufig = vorlaeufig
        }
    }

    public struct RohWort: Equatable, Sendable {
        public var text: String
        public var von: Double
        public var bis: Double

        public init(text: String, von: Double, bis: Double) {
            self.text = text
            self.von = von
            self.bis = bis
        }
    }

    /// Kennung für die Nachrichten an den Kernel.
    public let id: String
    /// Unix-Zeit von Uhrzeit 0.
    public let uhrStart: Double
    /// `ProcessInfo.systemUptime` von Uhrzeit 0: dieselbe Uhr wie die Zeiten aus dem Ton.
    public let uhrNull: Double

    public private(set) var abschnitte: [Paket.Abschnitt] = []
    public private(set) var saetze: [RohSatz] = []
    public private(set) var mausweg: [Paket.MausProbe] = []
    public private(set) var kameraVerlauf: [Paket.KameraProbe] = []
    public private(set) var auswahlVerlauf: [Paket.AuswahlProbe] = []
    public private(set) var striche: [Paket.Strich] = []
    /// Strich, der gerade entsteht.
    public private(set) var offenerStrich: Paket.Strich?

    public init(id: String, uhrStart: Double, uhrNull: Double) {
        self.id = id
        self.uhrStart = uhrStart
        self.uhrNull = uhrNull
    }

    /// Uptime → Sekunden ab Beginn der Sitzung.
    public func zeit(uptime: Double) -> Double { max(0, uptime - uhrNull) }

    // MARK: Mikrofon

    public mutating func mikrofonAn(t: Double) {
        guard abschnitte.last.map({ $0.bis >= 0 }) ?? true else { return }
        abschnitte.append(.init(von: t, bis: -1))
    }

    public mutating func mikrofonAus(t: Double) {
        guard let i = abschnitte.indices.last, abschnitte[i].bis < 0 else { return }
        abschnitte[i].bis = max(t, abschnitte[i].von)
    }

    // MARK: Satz

    /// Satz aus der Erkennung. Ein Ergebnis kann mehrere Sätze enthalten; mit Wortzeiten teilt es sich an Satzzeichen.
    public mutating func satz(text: String, von: Double, bis: Double, worte: [RohWort], vorlaeufig: Bool = false) {
        let sauber = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sauber.isEmpty else { return }
        for teil in Self.zerlegt(worte) {
            let t = teil.map(\.text).joined(separator: " ")
            saetze.append(RohSatz(text: t, von: teil[0].von, bis: max(teil[0].von, teil[teil.count - 1].bis), worte: teil,
                                  vorlaeufig: vorlaeufig))
        }
        if worte.isEmpty { saetze.append(RohSatz(text: sauber, von: von, bis: max(von, bis), vorlaeufig: vorlaeufig)) }
    }

    /// Wörter an Satzzeichen trennen.
    static func zerlegt(_ worte: [RohWort]) -> [[RohWort]] {
        var aus: [[RohWort]] = []
        var jetzt: [RohWort] = []
        for w in worte {
            jetzt.append(w)
            if let z = w.text.last, ".!?".contains(z) {
                aus.append(jetzt)
                jetzt = []
            }
        }
        if !jetzt.isEmpty { aus.append(jetzt) }
        return aus
    }

    // MARK: Mausweg, Kamera, Auswahl

    /// Neue Probe: jede Änderung des Ziels, sonst höchstens `mausJeS` je Sekunde.
    public mutating func maus(_ p: Paket.MausProbe) {
        if let letzte = mausweg.last {
            let selbesZiel = letzte.ref == p.ref && (letzte.bild == nil) == (p.bild == nil)
            if selbesZiel && p.t - letzte.t < 1 / FeedbackGrenzen.mausJeS { return }
            guard p.t >= letzte.t else { return }
        }
        mausweg.append(p)
    }

    public mutating func kamera(t: Double, _ kamera: JSONValue) {
        if let letzte = kameraVerlauf.last {
            if letzte.kamera == kamera || t - letzte.t < 1 / FeedbackGrenzen.kameraJeS { return }
        }
        kameraVerlauf.append(.init(t: t, kamera: kamera))
    }

    public mutating func auswahl(t: Double, run: Int, refs: [String]) {
        if let letzte = auswahlVerlauf.last, letzte.refs == refs { return }
        auswahlVerlauf.append(.init(t: t, run: run, refs: refs))
    }

    // MARK: Striche

    /// `farbe` und `geraet` (I-4): aus dem Werkzeugkranz bzw. das Gerät, an dem gezeichnet wird.
    public mutating func strichBeginnen(t: Double, run: Int, kamera: JSONValue, farbe: Strichfarbe? = nil,
                                        geraet: FeedbackGeraet? = nil) {
        offenerStrich = Paket.Strich(nr: striche.count + 1, t: t, bis: t, run: run, teile: [], laengeMm: 0,
                                     kamera: kamera, punkte: [], farbe: farbe?.rawValue, geraet: geraet?.rawValue)
    }

    public mutating func strichPunkt(_ p: Paket.StrichPunkt, teil: String?) {
        guard var s = offenerStrich else { return }
        if let vorher = s.punkte.last {
            s.laengeMm += Self.abstand(vorher.welt, p.welt)
        }
        s.punkte.append(p)
        s.bis = max(s.bis, p.t)
        if let teil, !s.teile.contains(teil) { s.teile.append(teil) }
        offenerStrich = s
    }

    /// Strich abschließen; ein Strich ohne Punkte zählt nicht. Punkte, die erst nach dem Loslassen ihren Treffer
    /// bekommen, gehen so nicht verloren: `strichEnden` kommt nach dem letzten Treffer.
    public mutating func strichEnden(t: Double) {
        guard var s = offenerStrich else { return }
        offenerStrich = nil
        guard !s.punkte.isEmpty else { return }
        s.bis = max(s.bis, t)
        striche.append(s)
    }

    static func abstand(_ a: [Double], _ b: [Double]) -> Double {
        guard a.count == 3, b.count == 3 else { return 0 }
        let x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2]
        return (x * x + y * y + z * z).squareRoot()
    }

    // MARK: Abschließen

    /// Stand einer Spur zur Zeit `t`: der letzte Eintrag davor, sonst der erste.
    private static func stand<T>(_ liste: [T], t: Double, zeit: (T) -> Double) -> T? {
        var treffer: T?
        for e in liste {
            if zeit(e) <= t { treffer = e } else { break }
        }
        return treffer ?? liste.first
    }

    /// Sätze mit Kamera, Auswahl und Bezügen, Wörter mit Satznummer.
    public func saetzeMitBezuegen(run: Int) -> (saetze: [Paket.Satz], worte: [Paket.Wort]) {
        var aus: [Paket.Satz] = []
        var worte: [Paket.Wort] = []
        let geordnet = saetze.sorted { $0.von < $1.von }
        for (i, s) in geordnet.enumerated() {
            let nr = i + 1
            var bezuege = Self.zeiger(satz: s, mausweg: mausweg, ende: abschlussZeit)
                .map { Paket.Bezug(zeiger: $0.probe, t: $0.von, bis: $0.bis, wort: $0.wort) }
            for strich in striche where Self.satzIndex(strich, in: geordnet) == i {
                bezuege.append(Paket.Bezug(strich: strich))
            }
            bezuege.sort { $0.t < $1.t }
            let kamera = Self.stand(kameraVerlauf, t: s.von) { $0.t }?.kamera ?? .object([:])
            let a = Self.stand(auswahlVerlauf, t: s.von) { $0.t }
            aus.append(Paket.Satz(nr: nr, text: s.text, von: s.von, bis: s.bis, vorlaeufig: s.vorlaeufig, kamera: kamera,
                                  auswahl: .init(run: a?.run ?? run, refs: a?.refs ?? []), bezuege: bezuege))
            worte.append(contentsOf: s.worte.map { .init(text: $0.text, von: $0.von, bis: $0.bis, satz: nr) })
        }
        return (aus, worte)
    }

    /// Letzte bekannte Zeit der Sitzung (Mausweg gilt bis hierhin).
    private var abschlussZeit: Double {
        max(abschnitte.last?.bis ?? 0, saetze.map(\.bis).max() ?? 0, mausweg.last?.t ?? 0)
    }

    /// Satz, zu dem ein Strich gehört: längste Überschneidung, sonst der nächste.
    static func satzIndex(_ s: Paket.Strich, in saetze: [RohSatz]) -> Int? {
        var best: (i: Int, wert: Double)?
        for (i, satz) in saetze.enumerated() {
            let schnitt = min(s.bis, satz.bis) - max(s.t, satz.von)
            // Überschneidung positiv, Abstand negativ: Der größte Wert gewinnt
            if best == nil || schnitt > best!.wert { best = (i, schnitt) }
        }
        return best?.i
    }

    /// Zeitraum, in dem die Maus auf einem Element stand.
    struct Verweilen: Equatable {
        var von: Double
        var bis: Double
        var probe: Paket.MausProbe
        var wort: String?

        var dauer: Double { bis - von }
    }

    /// Mausproben als Zeiträume je Element (nur auf einem Teil). Die letzte Probe gilt bis `ende`.
    static func verweilen(_ mausweg: [Paket.MausProbe], ende: Double) -> [Verweilen] {
        var aus: [Verweilen] = []
        for (i, p) in mausweg.enumerated() {
            let bis = i + 1 < mausweg.count ? mausweg[i + 1].t : max(ende, p.t)
            guard p.teil != nil else { continue }
            if var letzte = aus.last, letzte.probe.ref == p.ref, letzte.bis >= p.t - 1e-9 {
                letzte.bis = bis
                aus[aus.count - 1] = letzte
            } else {
                aus.append(Verweilen(von: p.t, bis: bis, probe: p))
            }
        }
        return aus
    }

    static func zeigewort(_ text: String) -> String? {
        let w = text.lowercased().trimmingCharacters(in: .punctuationCharacters.union(.whitespaces))
        return FeedbackGrenzen.zeigewoerter.contains(w) ? w : nil
    }

    /// Zeiger eines Satzes nach den Regeln des Protokolls, in zeitlicher Folge.
    static func zeiger(satz s: RohSatz, mausweg: [Paket.MausProbe], ende: Double) -> [Verweilen] {
        let alle = verweilen(mausweg, ende: ende)
        let w0 = s.von - FeedbackGrenzen.zeigerVorS, w1 = s.bis + FeedbackGrenzen.zeigerNachS
        var fenster: [Verweilen] = []
        var herkunft: [Int] = []  // Stelle in `alle`
        for (i, v) in alle.enumerated() {
            let a = max(v.von, w0), b = min(v.bis, w1)
            guard b > a || (a == b && v.von == v.bis) else { continue }
            var f = v
            f.von = a
            f.bis = b
            fenster.append(f)
            herkunft.append(i)
        }
        for w in s.worte {
            guard let wort = zeigewort(w.text) else { continue }
            let mitte = (w.von + w.bis) / 2
            let treffer = alle.firstIndex { $0.von <= mitte && mitte < $0.bis }
                ?? nachbar(alle, mitte: mitte)
            guard let i = treffer else { continue }
            if let j = herkunft.firstIndex(of: i) {
                if fenster[j].wort == nil { fenster[j].wort = wort }
            } else {
                var f = alle[i]
                f.wort = wort
                fenster.append(f)
                herkunft.append(i)
            }
        }
        var gute = fenster.filter { $0.dauer >= FeedbackGrenzen.zeigerMinS || $0.wort != nil }
        if gute.count > FeedbackGrenzen.zeigerJeSatz {
            gute.sort { a, b in
                if (a.wort != nil) != (b.wort != nil) { return a.wort != nil }
                return a.dauer > b.dauer
            }
            gute = Array(gute.prefix(FeedbackGrenzen.zeigerJeSatz))
        }
        return gute.sorted { $0.von < $1.von }
    }

    /// Nächster Zeitraum innerhalb der Suchweite um `mitte`.
    private static func nachbar(_ alle: [Verweilen], mitte: Double) -> Int? {
        var best: (i: Int, d: Double)?
        for (i, v) in alle.enumerated() {
            let d = mitte < v.von ? v.von - mitte : mitte - v.bis
            guard d <= FeedbackGrenzen.zeigewortSucheS else { continue }
            if best == nil || d < best!.d { best = (i, d) }
        }
        return best?.i
    }

    /// Das fertige Paket. `dauer` in Sekunden der Uhr; offene Striche und Abschnitte schließt es selbst.
    public func paket(name: String, erstellt: Date, dauer: Double, spracherkennung: String, wortzeiten: String = "ton",
                      projekt: Paket.Projekt, run: Int, ende: JSONValue, bild: Paket.Bild?,
                      geraet: FeedbackGeraet? = nil) -> Paket {
        var s = self
        s.strichEnden(t: dauer)
        s.mikrofonAus(t: dauer)
        let (saetze, worte) = s.saetzeMitBezuegen(run: run)
        let iso = ISO8601DateFormatter()
        iso.timeZone = .current
        return Paket(
            format: FeedbackGrenzen.format, name: name, erstellt: iso.string(from: erstellt), uhrStart: uhrStart,
            dauerS: dauer, spracherkennung: spracherkennung, wortzeiten: wortzeiten, projekt: projekt, run: run,
            abschnitte: s.abschnitte,
            worte: worte, saetze: saetze, striche: s.striche, mausweg: s.mausweg, kameraVerlauf: s.kameraVerlauf,
            auswahlVerlauf: s.auswahlVerlauf, ende: ende, bild: bild, geraet: geraet?.rawValue)
    }
}
