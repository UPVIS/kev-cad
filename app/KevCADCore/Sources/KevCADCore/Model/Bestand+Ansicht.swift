import Foundation

// Ansichtslogik zum Bestand ohne SwiftUI (testbar): Vorschau der Buchung „Gebaut“, Einkaufsliste als CSV und Text.

/// Was „Gebaut“ bucht, gerechnet aus dem Zuschnitt der Stückliste (BESTAND.md, Abschnitt „Buchen“): verplante Reste
/// und ganze Stangen weg, neue Reste ab Mindestrest dazu, Stückgut abziehen. Gekauftes wird vorausgesetzt.
public struct GebautVorschau: Equatable, Sendable {
    public enum Art: String, Sendable {
        case restWeg, ganzeWeg, stueckWeg, restNeu, kaufen, verschnitt
    }

    public struct Zeile: Identifiable, Equatable, Sendable {
        public var id: String
        public var art: Art
        /// „Rest R-0008 · 610 mm“, „1 ganze Stange · 1.000 mm“, „Rest 144 mm“.
        public var text: String
        /// Lagerteil, z. B. „ALFER-Rundrohr 12 × 1“.
        public var teil: String
        public var hinweis: String?

        public init(id: String, art: Art, text: String, teil: String, hinweis: String? = nil) {
            self.id = id
            self.art = art
            self.text = text
            self.teil = teil
            self.hinweis = hinweis
        }
    }

    public var weg: [Zeile]
    public var neu: [Zeile]
    public var kaufen: [Zeile]
    public var verschnitt: [Zeile]

    public init(weg: [Zeile] = [], neu: [Zeile] = [], kaufen: [Zeile] = [], verschnitt: [Zeile] = []) {
        self.weg = weg
        self.neu = neu
        self.kaufen = kaufen
        self.verschnitt = verschnitt
    }

    /// Nichts aus dem Bestand und keine neuen Reste: „Gebaut“ hätte nichts zu buchen.
    public var leer: Bool { weg.isEmpty && neu.isEmpty }

    /// Kurzfassung für die Bestätigung: „2 Posten weg, 2 Reste neu“.
    public var kurz: String {
        var parts: [String] = []
        if !weg.isEmpty { parts.append(KevFormat.count(weg.count, one: "Posten", many: "Posten") + " weg") }
        if !neu.isEmpty { parts.append(KevFormat.count(neu.count, one: "Rest", many: "Reste") + " neu") }
        return parts.isEmpty ? "nichts zu buchen" : parts.joined(separator: ", ")
    }

    /// - Parameters:
    ///   - lines: Stücklistenzeilen (für Stückgut aus dem Bestand).
    ///   - name: Anzeigename eines Lagerteils (Katalog oder Stückliste).
    public static func berechnen(
        zuschnitt: BOMBestand, bestand: Bestand?, lines: [BOMLine], name: (String) -> String? = { _ in nil }
    ) -> GebautVorschau {
        var v = GebautVorschau()
        for z in zuschnitt.zuschnitte {
            let teil = name(z.stockID) ?? z.benennung
            let einheit = z.istPlatte ? ("ganze Platte", "ganze Platten") : ("ganze Stange", "ganze Stangen")
            let kaufEinheit = z.istPlatte ? ("Platte", "Platten") : ("Stange", "Stangen")
            let mindestrest = bestand?.mindestrest(z.stockID) ?? BestandEinstellungen.standard.mindestrestMM
            // Reste weg (je Kennung)
            for q in z.quellen where q.art == .rest {
                v.weg.append(Zeile(
                    id: "\(z.stockID)/rest/\(q.kennung ?? String(q.index))", art: .restWeg,
                    text: "Rest \(q.kennung ?? "ohne Kennung") · \(masse(q))", teil: teil))
            }
            // Ganze aus dem Bestand und zu kaufende, je Format zusammengefasst
            for (art, ziel) in [(ZuschnittQuelleArt.bestand, Art.ganzeWeg), (.kaufen, .kaufen)] {
                var gruppen: [(masse: String, n: Int)] = []
                for q in z.quellen where q.art == art {
                    let m = masse(q)
                    if let i = gruppen.firstIndex(where: { $0.masse == m }) { gruppen[i].n += 1 } else { gruppen.append((m, 1)) }
                }
                for g in gruppen {
                    let wort = art == .bestand ? einheit : kaufEinheit
                    let zeile = Zeile(
                        id: "\(z.stockID)/\(art.rawValue)/\(g.masse)", art: ziel,
                        text: "\(KevFormat.count(g.n, one: wort.0, many: wort.1)) · \(g.masse)", teil: teil,
                        hinweis: art == .kaufen ? "muss vorher gekauft sein; der Rest daraus kommt in den Bestand" : nil)
                    if art == .bestand { v.weg.append(zeile) } else { v.kaufen.append(zeile) }
                }
            }
            // Neue Reste: Angabe des Kernels, sonst aus den Quellen (ab Mindestrest)
            if z.istPlatte {
                for (i, f) in z.neueResteFlaechen.enumerated() {
                    v.neu.append(Zeile(id: "\(z.stockID)/neu/\(i)", art: .restNeu, text: "Rest \(f.masseText)", teil: teil))
                }
            } else {
                for (i, l) in z.neueReste.enumerated() {
                    v.neu.append(Zeile(id: "\(z.stockID)/neu/\(i)", art: .restNeu, text: "Rest \(KevFormat.length(l))", teil: teil))
                }
                let abfall = z.quellen.filter { $0.restIstVerschnitt(saegeschnitt: z.saegeschnitt, mindestrest: mindestrest) }
                    .map { $0.restLaenge(saegeschnitt: z.saegeschnitt) }.filter { $0 > 0.05 }
                if !abfall.isEmpty {
                    v.verschnitt.append(Zeile(
                        id: "\(z.stockID)/verschnitt", art: .verschnitt,
                        text: abfall.map(KevFormat.length).joined(separator: ", "), teil: teil,
                        hinweis: "unter \(KevFormat.length(mindestrest)), kommt nicht in den Bestand"))
                }
            }
        }
        // Stückgut aus dem Bestand
        for posten in bestand?.posten ?? [] where posten.form == .stueckgut {
            let zeilen = lines.filter { $0.stockID == posten.id }
            guard !zeilen.isEmpty else { continue }
            let teil = name(posten.id) ?? zeilen.first?.benennung ?? posten.id
            var bedarf: [(laenge: Double?, n: Int)] = []
            for line in zeilen {
                let l = posten.stueck.contains(where: { $0.laenge != nil }) ? schraubenLaenge(line) : nil
                if let i = bedarf.firstIndex(where: { BestandBearbeitung.gleicheLaenge($0.laenge, l) }) {
                    bedarf[i].n += line.anzahl
                } else {
                    bedarf.append((l, line.anzahl))
                }
            }
            for b in bedarf {
                let da = posten.stueck.first { BestandBearbeitung.gleicheLaenge($0.laenge, b.laenge) }?.anzahl ?? 0
                let n = min(da, b.n)
                guard n > 0 else { continue }
                let laengeText = b.laenge.map { " · \(KevFormat.length($0))" } ?? ""
                v.weg.append(Zeile(
                    id: "\(posten.id)/stueck/\(b.laenge.map { KevFormat.input($0) } ?? "-")", art: .stueckWeg,
                    text: "\(KevFormat.integer(n)) Stück\(laengeText)", teil: teil,
                    hinweis: b.n > da ? "\(KevFormat.integer(b.n)) gebraucht, \(KevFormat.integer(da)) im Bestand" : nil))
            }
        }
        return v
    }

    static func masse(_ q: ZuschnittQuelle) -> String {
        if let b = q.b, let h = q.h { return BestandText.format(b, h) }
        return q.laenge.map(KevFormat.length) ?? "–"
    }

    /// Länge einer Schraube aus der Stückliste: `laenge`, sonst die Zahl hinter „ד in „M8 × 60“.
    public static func schraubenLaenge(_ line: BOMLine) -> Double? {
        if let l = line.laenge { return l }
        guard let teil = line.masseText.split(separator: "×").last, line.masseText.contains("×") else { return nil }
        return KevFormat.parseNumber(String(teil))
    }
}

/// Eingabe „Erfassen“ (Lagerteil aufnehmen, Reste hinzufügen): ergibt den ganzen Posten für BESTAND_SAVE und den Grund.
public struct BestandErfassung: Equatable, Sendable {
    public var form: BestandForm
    /// Ganze Stangen bzw. Platten, die dazukommen.
    public var ganze: Int
    /// Format der ganzen: Länge (Stange) bzw. Breite × Höhe (Platte).
    public var laenge: Double?
    public var b: Double?
    public var h: Double?
    public var resteLaengen: [Double]
    public var resteFlaechen: [ZuschnittFlaeche]
    public var ort: String?
    /// Stückgut, das dazukommt, und seine Länge (Schrauben).
    public var stueck: Int
    public var stueckLaenge: Double?

    public init(
        form: BestandForm, ganze: Int = 0, laenge: Double? = nil, b: Double? = nil, h: Double? = nil,
        resteLaengen: [Double] = [], resteFlaechen: [ZuschnittFlaeche] = [], ort: String? = nil, stueck: Int = 0,
        stueckLaenge: Double? = nil
    ) {
        self.form = form
        self.ganze = ganze
        self.laenge = laenge
        self.b = b
        self.h = h
        self.resteLaengen = resteLaengen
        self.resteFlaechen = resteFlaechen
        self.ort = ort
        self.stueck = stueck
        self.stueckLaenge = stueckLaenge
    }

    private var resteAnzahl: Int { form == .platte ? resteFlaechen.count : (form == .stange ? resteLaengen.count : 0) }

    /// Nichts einzutragen.
    public var leer: Bool {
        switch form {
        case .stange, .platte: return ganze <= 0 && resteAnzahl == 0
        case .stueckgut: return stueck <= 0
        }
    }

    /// Der Posten nach dem Erfassen. `vorher`: der Posten aus dem Bestand (nil = neu).
    public func posten(vorher: JSONValue?, bestand: Bestand?) -> JSONValue {
        var p = vorher ?? BestandBearbeitung.neuerPosten(form: form, laenge: laenge, b: b, h: h)
        switch form {
        case .stange, .platte:
            if ganze > 0 {
                let bisher = p["ganze"]?["anzahl"]?.intValue ?? 0
                p = BestandBearbeitung.setzeGanze(
                    p, anzahl: bisher + ganze, laenge: form == .stange ? laenge : nil, b: form == .platte ? b : nil,
                    h: form == .platte ? h : nil, nurWennFehlt: bisher > 0)
            }
            let kennungen = (bestand ?? .leer).naechsteKennungen(form, anzahl: resteAnzahl)
            if form == .stange {
                for (l, k) in zip(resteLaengen, kennungen) {
                    p = BestandBearbeitung.restHinzu(p, kennung: k, laenge: l, ort: ort)
                }
            } else {
                for (f, k) in zip(resteFlaechen, kennungen) {
                    p = BestandBearbeitung.restHinzu(p, kennung: k, b: f.b, h: f.h, ort: ort)
                }
            }
        case .stueckgut:
            if stueck > 0 { p = BestandBearbeitung.stueck(p, laenge: stueckLaenge, delta: stueck) }
        }
        return p
    }

    /// „Erfasst: 2 Stangen à 1.000 mm, 3 Reste (430, 610, 180 mm)“.
    public func grund(name: String) -> String {
        var teile: [String] = []
        switch form {
        case .stange, .platte:
            if ganze > 0 {
                let n = KevFormat.count(ganze, one: form.einheit, many: form.einheitMehrzahl)
                var masse = laenge.map(KevFormat.length)
                if form == .platte {
                    masse = nil
                    if let b, let h { masse = BestandText.format(b, h) }
                }
                teile.append(masse.map { "\(n) à \($0)" } ?? n)
            }
            if resteAnzahl > 0 {
                let masse = form == .stange
                    ? resteLaengen.map { KevFormat.compact($0, maxDigits: 1) }.joined(separator: ", ") + " mm"
                    : resteFlaechen.map(\.masseText).joined(separator: ", ")
                teile.append("\(KevFormat.count(resteAnzahl, one: "Rest", many: "Reste")) (\(masse))")
            }
        case .stueckgut:
            teile.append("\(KevFormat.integer(stueck)) Stück" + (stueckLaenge.map { " · \(KevFormat.length($0))" } ?? ""))
        }
        return "Erfasst \(name): " + teile.joined(separator: ", ")
    }
}

/// Einkaufsliste als CSV (Semikolon, deutsche Zahlen, UTF-8 mit BOM für Excel) und als Text zum Weiterleiten.
public enum EinkaufslisteFormat {
    static func zahl(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "" }
        return String(format: "%.2f", value).replacingOccurrences(of: ".", with: ",")
    }

    static func feld(_ text: String) -> String {
        guard text.contains(";") || text.contains("\"") || text.contains("\n") else { return text }
        return "\"" + text.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }

    public static func csv(_ liste: [EinkaufsPosition], summe: Double?) -> String {
        var zeilen = ["Menge;Einheit;Benennung;Lagerteil;Preis je (EUR);Preis (EUR);Preisstand;Bezugsquelle;Link;Hinweis"]
        for p in liste {
            zeilen.append([
                KevFormat.compact(p.menge, maxDigits: 2).replacingOccurrences(of: ".", with: ""), p.einheit, p.benennung,
                p.id, zahl(p.preisJe), zahl(p.preis), p.stand ?? "", p.linkName ?? "", p.link?.absoluteString ?? "",
                p.hinweis ?? "",
            ].map(feld).joined(separator: ";"))
        }
        zeilen.append(";;Summe;;;\(zahl(summe));;;;")
        return "\u{FEFF}" + zeilen.joined(separator: "\r\n") + "\r\n"
    }

    /// „Einkaufsliste Kugelschieber“ mit einer Zeile je Position und der Summe.
    public static func text(_ liste: [EinkaufsPosition], summe: Double?, projekt: String?, stand: String? = nil) -> String {
        var out = ["Einkaufsliste" + (projekt.map { " \($0)" } ?? "") + (stand.map { " (Stand \($0))" } ?? "")]
        if liste.isEmpty { out.append("Nichts zu kaufen, alles ist im Bestand.") }
        for p in liste {
            var zeile = "- \(p.mengeText) × \(p.einheit): \(p.benennung)"
            if let preis = p.preis { zeile += ", \(KevFormat.euro(preis))" }
            if let link = p.link { zeile += " (\(link.absoluteString))" }
            out.append(zeile)
            if let h = p.hinweis { out.append("  \(h)") }
        }
        if let summe { out.append("Summe: \(KevFormat.euro(summe))") }
        return out.joined(separator: "\n")
    }

    /// Dateiname im Ausgabeordner: „<Projekt>-einkaufsliste.csv“.
    public static func dateiname(projekt: String) -> String {
        let erlaubt = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: " -_"))
        let name = String(projekt.unicodeScalars.map { erlaubt.contains($0) ? Character($0) : "-" })
            .trimmingCharacters(in: .whitespaces)
        return (name.isEmpty ? "projekt" : name) + "-einkaufsliste.csv"
    }
}
