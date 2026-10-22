import CoreGraphics
import Foundation

// Berichtsseiten (Strang P6-A2): Deckblatt, Stückliste, Teileliste, Einkaufsliste, Zuschnitt. Daten aus einem
// Schnappschuss des App-Modells (`ExportQuellen`), Seiten über den Seitenfluss, gezeichnet auf der Leinwand.

/// Ein Zeichnungsblatt für den Export (gezeichnet von der gemeinsamen Zeichenfunktion der Blätter, Strang P6-A1).
public struct ExportZeichnungsblatt {
    public var id: String
    public var titel: String
    /// Blattgröße in mm (A4/A3, hoch/quer).
    public var groesse: CGSize
    /// Zeichnet das Blatt in Punkt, Ursprung links unten.
    public var zeichne: (CGContext, CGSize) -> Void

    public init(id: String, titel: String, groesse: CGSize, zeichne: @escaping (CGContext, CGSize) -> Void) {
        self.id = id
        self.titel = titel
        self.groesse = groesse
        self.zeichne = zeichne
    }
}

/// Alles, was die Seiten brauchen, als Schnappschuss (die Seiten zeichnen später, auch nach dem nächsten Lauf).
public struct ExportQuellen {
    public var kopf: ExportKopf
    public var bom: BillOfMaterials?
    public var bestand: BOMBestand?
    public var teile: [PartNode]
    public var bauplan: Bauplan?
    public var strichbilder: [String: BauplanStrichbild]
    /// Vorschaubilder je Teilname (weißer Grund, isometrisch).
    public var teilBilder: [String: CGImage]
    public var gesamtBild: CGImage?
    public var zeichnungen: [ExportZeichnungsblatt]
    /// Offene Befunde der Prüfung (für das Deckblatt).
    public var pruefFehler: Int?

    public init(kopf: ExportKopf, bom: BillOfMaterials? = nil, bestand: BOMBestand? = nil, teile: [PartNode] = [],
                bauplan: Bauplan? = nil, strichbilder: [String: BauplanStrichbild] = [:],
                teilBilder: [String: CGImage] = [:], gesamtBild: CGImage? = nil,
                zeichnungen: [ExportZeichnungsblatt] = [], pruefFehler: Int? = nil)
    {
        self.kopf = kopf
        self.bom = bom
        self.bestand = bestand
        self.teile = teile
        self.bauplan = bauplan
        self.strichbilder = strichbilder
        self.teilBilder = teilBilder
        self.gesamtBild = gesamtBild
        self.zeichnungen = zeichnungen
        self.pruefFehler = pruefFehler
    }

    /// Bild einer Stücklistenzeile: das erste ihrer Teile mit Bild.
    func bild(_ line: BOMLine) -> CGImage? {
        for t in line.teile { if let b = teilBilder[t] { return b } }
        return nil
    }
}

/// Baut das Dokument aus Vorlage und Quellen.
public enum ExportBauer {
    public static func dokument(_ vorlage: ExportVorlage, _ q: ExportQuellen) -> ExportDokument {
        var seiten: [ExportSeite] = []
        var hinweise: [String] = []
        let format = vorlage.seitenformat
        for wahl in vorlage.aktive {
            let neu: [ExportSeite]
            switch wahl.art {
            case .deckblatt: neu = deckblatt(q, vorlage, format)
            case .stueckliste: neu = stueckliste(q, wahl, format, &hinweise)
            case .teileliste: neu = teileliste(q, wahl, format, &hinweise)
            case .einkaufsliste: neu = einkaufsliste(q, wahl, format, &hinweise)
            case .zuschnitt: neu = zuschnitt(q, wahl, format, &hinweise)
            case .zeichnungen: neu = zeichnungen(q, wahl, &hinweise)
            case .bauplan: neu = ExportBauplanSeiten.seiten(q, format, &hinweise)
            }
            seiten += neu
        }
        return ExportDokument(kopf: q.kopf, seiten: seiten, hinweise: hinweise)
    }

    /// Seiten eines Bausteins aus Blöcken im Fluss; die erste Seite trägt die Überschrift.
    static func flussSeiten(_ art: ExportBausteinArt, _ format: ExportFormat, titel: String? = nil,
                            _ bloecke: [ExportBlock]) -> [ExportSeite]
    {
        let inhalt = ExportRand.inhalt(format.mm)
        return ExportFluss.verteile(bloecke, inhalt: inhalt).map { seite in
            ExportSeite(groesse: format.mm, baustein: art, titel: titel ?? art.titel, gliederung: seite.marken,
                        inhalt: .leinwand { l, _ in
                            for a in seite.auftraege { a.zeichne(l, a.rect) }
                        })
        }
    }

    // MARK: Bausteinkopf

    /// Große Überschrift eines Bausteins mit Kennzeile darunter.
    static func ueberschrift(_ titel: String, _ zeile: String?, symbol: ExportBausteinArt? = nil) -> ExportBlock {
        let h: CGFloat = zeile == nil ? 13 : 19
        return .fest(hoehe: h, mitNaechstem: true) { l, r in
            l.text(titel, x: r.minX, y: r.minY + 8.5, .fett(20), farbe: ExportStil.tinte)
            if let zeile {
                l.text(zeile, x: r.minX, y: r.minY + 15, .normal(9.5), farbe: ExportStil.grau, maxBreite: r.width)
            }
        }
    }

    static func zwischentitel(_ titel: String, _ rechts: String? = nil) -> ExportBlock {
        .fest(hoehe: 10, mitNaechstem: true) { l, r in
            l.text(titel, x: r.minX, y: r.minY + 6.5, .fett(11.5), farbe: ExportStil.tinte, maxBreite: r.width * 0.7)
            if let rechts {
                l.text(rechts, x: r.maxX, y: r.minY + 6.5, .normal(8.5), farbe: ExportStil.grau, .rechts,
                       maxBreite: r.width * 0.45)
            }
        }
    }

    static func hinweisZeile(_ text: String, farbe: CGColor = ExportStil.grau) -> ExportBlock {
        let breite: CGFloat = 170
        let h = ExportSatz(text, breite: breite, schrift: .normal(8)).hoehe + 2
        return .fest(hoehe: h, mitNaechstem: false) { l, r in
            l.absatz(text, x: r.minX, y: r.minY + 1, breite: r.width, .normal(8), farbe: farbe)
        }
    }

    static func leer(_ text: String) -> ExportBlock {
        .fest(hoehe: 24, mitNaechstem: false) { l, r in
            let box = CGRect(x: r.minX, y: r.minY + 2, width: r.width, height: 18)
            l.rechteck(box, fuellung: ExportStil.flaeche, radius: 2)
            l.text(text, x: box.midX, y: box.midY + 1.2, .normal(9.5), farbe: ExportStil.grau, .mitte,
                   maxBreite: box.width - 8)
        }
    }

    // MARK: Deckblatt

    static func deckblatt(_ q: ExportQuellen, _ vorlage: ExportVorlage, _ format: ExportFormat) -> [ExportSeite] {
        let titel = q.kopf.projekt
        let inhaltArten = vorlage.aktive.map(\.art).filter { $0 != .deckblatt }
        let seite = ExportSeite(groesse: format.mm, baustein: .deckblatt, titel: "Deckblatt", mitKopf: false,
                                inhalt: .leinwand { l, info in
            let w = l.groesse.width, h = l.groesse.height
            let x0: CGFloat = 22, x1 = w - 22
            // Kennband oben
            l.rechteck(CGRect(x: 0, y: 0, width: w, height: 4.5), fuellung: ExportStil.akzent)
            var y: CGFloat = 26
            l.text("BAUUNTERLAGEN", x: x0, y: y, .mittel(9), farbe: ExportStil.akzent, laufweite: 0.35)
            y += 13
            let titelSatz = ExportSatz(titel, breite: x1 - x0, schrift: .fett(34), zeilenabstand: 0.95, maxZeilen: 2)
            l.zeichne(titelSatz, x: x0, y: y - 9, breite: x1 - x0)
            y += titelSatz.hoehe - 2
            let inhaltText = inhaltArten.map(\.titel).joined(separator: "  ·  ")
            l.text(inhaltText, x: x0, y: y + 4, .normal(11), farbe: ExportStil.grau, maxBreite: x1 - x0)
            y += 12
            // Gesamtansicht
            let quer = l.groesse.width > l.groesse.height
            let bildH: CGFloat = quer ? h - y - 60 : min(118, h * 0.4)
            let bildR = CGRect(x: x0, y: y, width: quer ? (x1 - x0) * 0.58 : x1 - x0, height: bildH)
            l.rechteck(bildR, fuellung: ExportStil.flaeche, radius: 3)
            if let img = q.gesamtBild {
                l.bild(img, in: bildR.insetBy(dx: 4, dy: 4))
            } else {
                l.text("Keine Gesamtansicht", x: bildR.midX, y: bildR.midY, .normal(10), farbe: ExportStil.grauHell,
                       .mitte)
            }
            // Kennzahlen
            var zahlen: [(String, String)] = []
            if let bom = q.bom {
                zahlen.append((KevFormat.integer(bom.totals.teile), "Teile"))
                zahlen.append((KevFormat.integer(bom.totals.positionen), "Positionen"))
                zahlen.append((KevFormat.kg(bom.totals.kg), "Gewicht"))
                if let p = bom.totals.preis { zahlen.append(("≈ " + KevFormat.euro(p), "Material")) }
            } else if !q.teile.isEmpty {
                zahlen.append((KevFormat.integer(q.teile.count), "Teile"))
            }
            if let plan = q.bauplan, inhaltArten.contains(.bauplan) {
                zahlen.append((KevFormat.integer(plan.alleSchritte.count), "Bauschritte"))
            }
            if inhaltArten.contains(.zeichnungen), !q.zeichnungen.isEmpty {
                zahlen.append((KevFormat.integer(q.zeichnungen.count), "Zeichnungen"))
            }
            let kx0 = quer ? bildR.maxX + 10 : x0
            let kw = quer ? x1 - kx0 : x1 - x0
            var ky = quer ? y : bildR.maxY + 9
            let spaltenZahl = quer ? 2 : min(3, max(1, zahlen.count))
            let kachelW = (kw - CGFloat(spaltenZahl - 1) * 4) / CGFloat(spaltenZahl)
            for (i, z) in zahlen.enumerated() {
                let sx = kx0 + CGFloat(i % spaltenZahl) * (kachelW + 4)
                let sy = ky + CGFloat(i / spaltenZahl) * 20
                l.rechteck(CGRect(x: sx, y: sy, width: kachelW, height: 17), rand: ExportStil.linie, randBreite: 0.2,
                           radius: 2)
                l.text(z.0, x: sx + 4, y: sy + 8.6, .fett(14), farbe: ExportStil.tinte, maxBreite: kachelW - 8)
                l.text(z.1.uppercased(), x: sx + 4, y: sy + 13.6, .mittel(6.5), farbe: ExportStil.grau,
                       laufweite: 0.2)
            }
            ky += CGFloat((zahlen.count + spaltenZahl - 1) / spaltenZahl) * 20 + 8
            // Inhalt mit Seitenzahlen
            l.text("INHALT", x: kx0, y: ky + 3, .mittel(7.5), farbe: ExportStil.grau, laufweite: 0.3)
            ky += 6
            for b in info.bausteinSeiten where b.art != .deckblatt {
                l.linie(CGPoint(x: kx0, y: ky + 6.8), CGPoint(x: kx0 + kw, y: ky + 6.8), breite: 0.12,
                        farbe: ExportStil.linieFein)
                l.text(b.art.titel, x: kx0, y: ky + 5, .mittel(10.5), farbe: ExportStil.tinte)
                let n = b.anzahl == 1 ? "Seite \(b.seite)" : "Seite \(b.seite)–\(b.seite + b.anzahl - 1)"
                l.text(n, x: kx0 + kw, y: ky + 5, .normal(9.5), farbe: ExportStil.grau, .rechts)
                ky += 8
            }
            // Fuß: Eigentümer, Version, Datum, Programm
            let fy = h - 22
            l.linie(CGPoint(x: x0, y: fy), CGPoint(x: x1, y: fy), breite: 0.3, farbe: ExportStil.tinte)
            let felder: [(String, String)] = [
                ("Projekt", q.kopf.projekt), ("Stand", q.kopf.version ?? "aktueller Stand"),
                ("Datum", q.kopf.datumText), ("Eigentümer", q.kopf.autor),
            ]
            let fw = (x1 - x0) / CGFloat(felder.count)
            for (i, f) in felder.enumerated() {
                let fx = x0 + CGFloat(i) * fw
                l.text(f.0.uppercased(), x: fx, y: fy + 5, .mittel(6.5), farbe: ExportStil.grau, laufweite: 0.2)
                l.text(f.1, x: fx, y: fy + 10, .normal(9), farbe: ExportStil.tinte, maxBreite: fw - 4)
            }
            l.text("Erstellt mit Kev CAD", x: x1, y: h - 6, .normal(7), farbe: ExportStil.grauHell, .rechts)
        })
        return [seite]
    }

    // MARK: Stückliste

    static func artGruppe(_ art: String) -> (Int, String) {
        switch art {
        case "rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil",
            "holz":
            return (0, "Stangen und Profile")
        case "platte": return (1, "Platten")
        case "druckteil": return (2, "3D-Druckteile")
        case "schraube", "mutter", "scheibe": return (3, "Normteile")
        case "zukaufteil", "kamera", "objektiv", "kamerazubehoer": return (4, "Zukaufteile")
        case "eigenteil": return (5, "Eigenteile ohne Lager")
        default: return (6, "Weitere")
        }
    }

    static func herkunft(_ line: BOMLine) -> String {
        switch line.art {
        case "druckteil": return "3D-Druck"
        case "zukaufteil", "kamera", "objektiv", "kamerazubehoer": return line.zukauf?.hersteller ?? "Zukauf"
        case "eigenteil": return "Eigenteil"
        default: return "Lager"
        }
    }

    static func masseText(_ line: BOMLine) -> String {
        var t = line.masseText
        if let l = line.laenge {
            t = (t.isEmpty ? "" : t + ", ") + "L = " + KevFormat.length(l)
            let g = KevFormat.gehrung(line.gehrung)
            if g != "–" { t += ", Gehrung " + g }
        }
        return t
    }

    static func stueckliste(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ format: ExportFormat,
                            _ hinweise: inout [String]) -> [ExportSeite]
    {
        guard let bom = q.bom, !bom.lines.isEmpty else {
            hinweise.append("Stückliste leer: noch kein Lauf mit Teilen")
            return flussSeiten(.stueckliste, format, [ueberschrift("Stückliste", nil), leer("Keine Stückliste: erst model.py rechnen")])
        }
        let spalten = wahl.wirksameSpalten
        var zeilen: [ExportZeile] = []
        let gruppen = Dictionary(grouping: bom.lines) { artGruppe($0.art).0 }
        for key in gruppen.keys.sorted() {
            let lines = gruppen[key]!.sorted { $0.pos < $1.pos }
            zeilen.append(.gruppe(artGruppe(lines[0].art).1))
            for line in lines {
                var z: [String: ExportZelle] = [:]
                z["pos"] = ExportZelle("\(line.pos)", fett: true)
                z["bild"] = ExportZelle(bild: q.bild(line))
                z["benennung"] = ExportZelle(line.benennung, unter: line.zukauf?.mpn.map { "Nr. \($0)" } ?? line.norm)
                z["norm"] = ExportZelle(line.norm ?? "")
                z["material"] = ExportZelle(line.material ?? "–")
                z["masse"] = ExportZelle(masseText(line))
                z["anzahl"] = ExportZelle("\(line.anzahl)", fett: true)
                z["gewicht"] = ExportZelle(line.kg.map(KevFormat.kg) ?? "–")
                z["preis_je"] = ExportZelle(line.preisJe.map(KevFormat.euro) ?? "–")
                z["preis"] = ExportZelle(line.preis.map(KevFormat.euro) ?? "–")
                z["herkunft"] = ExportZelle(herkunft(line))
                zeilen.append(ExportZeile(z))
            }
        }
        zeilen.append(.summe([
            "benennung": ExportZelle("Summe"), "anzahl": ExportZelle("\(bom.totals.teile)"),
            "gewicht": ExportZelle(KevFormat.kg(bom.totals.kg)),
            "preis": ExportZelle(bom.totals.preis.map(KevFormat.euro) ?? "–"),
        ]))
        var t = ExportTabelle(spalten: spalten, zeilen: zeilen)
        if !spalten.contains(where: { $0.id == "bild" }) { t.bildHoehe = 0 }
        let kennzeile = "\(KevFormat.count(bom.totals.positionen, one: "Position", many: "Positionen")), "
            + "\(KevFormat.count(bom.totals.teile, one: "Teil", many: "Teile")), \(KevFormat.kg(bom.totals.kg))"
            + (bom.totals.preis.map { ", Material ≈ \(KevFormat.euro($0))" } ?? "")
        var bloecke: [ExportBlock] = [ueberschrift("Stückliste", kennzeile), .tabelle(t)]
        if let h = bom.totals.preisHinweis, !h.isEmpty { bloecke += [.abstand(2), hinweisZeile(h)] }
        for w in bom.warnings.prefix(4) { bloecke.append(hinweisZeile(w, farbe: ExportStil.rot)) }
        return flussSeiten(.stueckliste, format, bloecke)
    }

    // MARK: Teileliste

    static func herkunft(_ p: PartNode) -> (String, String?) {
        if let s = p.stock {
            var unter: String?
            if let l = s.laenge { unter = "L = " + KevFormat.length(l) }
            return (s.name, unter)
        }
        if let z = p.zukauf { return ("Zukauf" + (z.hersteller.map { " · \($0)" } ?? ""), z.mpn) }
        if p.inventarFehlt { return ("nicht im Inventar", nil) }
        return ("3D-Druck", p.material)
    }

    static func teileliste(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ format: ExportFormat,
                           _ hinweise: inout [String]) -> [ExportSeite]
    {
        guard !q.teile.isEmpty else {
            return flussSeiten(.teileliste, format, [ueberschrift("Teileliste", nil), leer("Keine Teile")])
        }
        let spalten = wahl.wirksameSpalten
        var zeilen: [ExportZeile] = []
        var nr = 0
        var gruppe: String?
        let sortiert = q.teile.enumerated().sorted { a, b in
            let ga = a.element.path.count > 1 ? a.element.path[0] : ""
            let gb = b.element.path.count > 1 ? b.element.path[0] : ""
            return ga == gb ? a.offset < b.offset : ga < gb
        }.map(\.element)
        for p in sortiert {
            let g = p.path.count > 1 ? p.path[0] : "Einzelteile"
            if g != gruppe {
                zeilen.append(.gruppe(g))
                gruppe = g
            }
            nr += 1
            let (her, herUnter) = herkunft(p)
            let size = p.bboxMax - p.bboxMin
            var z: [String: ExportZelle] = [:]
            z["nr"] = ExportZelle("\(nr)", fett: true)
            z["bild"] = ExportZelle(bild: q.teilBilder[p.id])
            z["name"] = ExportZelle(p.name, unter: p.path.count > 2 ? p.path.dropLast().joined(separator: " / ") : nil)
            z["baugruppe"] = ExportZelle(p.path.dropLast().joined(separator: " / "))
            z["herkunft"] = ExportZelle(her, unter: herUnter, farbe: p.inventarFehlt ? ExportStil.rot : nil)
            z["material"] = ExportZelle(p.material ?? p.stock?.material ?? "–")
            z["abmessungen"] = ExportZelle(KevFormat.dimensions(min: p.bboxMin, max: p.bboxMin + size, digits: 1))
            z["gewicht"] = ExportZelle(p.mass.map { KevFormat.mass(grams: $0) } ?? "–")
            zeilen.append(ExportZeile(z))
        }
        let masse = q.teile.compactMap(\.mass).reduce(0, +)
        zeilen.append(.summe([
            "name": ExportZelle("\(q.teile.count) Teile"),
            "gewicht": ExportZelle(KevFormat.mass(grams: masse)),
        ]))
        var t = ExportTabelle(spalten: spalten, zeilen: zeilen)
        if !spalten.contains(where: { $0.id == "bild" }) { t.bildHoehe = 0 }
        let mitBild = q.teile.filter { q.teilBilder[$0.id] != nil }.count
        if spalten.contains(where: { $0.id == "bild" }) && mitBild < q.teile.count {
            hinweise.append("Teileliste: \(q.teile.count - mitBild) Teile ohne Vorschaubild (ausgeblendet)")
        }
        let kennzeile = "\(KevFormat.count(q.teile.count, one: "Teil", many: "Teile")) einzeln, nach Baugruppe"
        return flussSeiten(.teileliste, format, [ueberschrift("Teileliste", kennzeile), .tabelle(t)])
    }

    // MARK: Einkaufsliste

    static func einkaufsliste(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ format: ExportFormat,
                              _ hinweise: inout [String]) -> [ExportSeite]
    {
        let spalten = wahl.wirksameSpalten
        var bloecke: [ExportBlock] = []
        guard let b = q.bestand else {
            hinweise.append("Einkaufsliste ohne Bestandsabgleich (Kernel hat keinen Zuschnitt mit Bestand geschickt)")
            return flussSeiten(.einkaufsliste, format, [ueberschrift("Einkaufsliste", nil),
                                                        leer("Noch keine Einkaufsliste: erst model.py rechnen")])
        }
        let summe = b.summe ?? b.einkaufSumme
        let kennzeile = b.einkaufsliste.isEmpty ? "Alles im Projektbestand vorhanden"
            : "\(KevFormat.count(b.einkaufsliste.count, one: "Position", many: "Positionen")) nach Abzug des Bestands"
                + (summe.map { ", zusammen ≈ \(KevFormat.euro($0))" } ?? "")
        bloecke.append(ueberschrift("Einkaufsliste", kennzeile))
        if b.einkaufsliste.isEmpty {
            bloecke.append(leer("Nichts zu kaufen: alles ist im Projektbestand"))
        } else {
            var zeilen: [ExportZeile] = b.einkaufsliste.map { e in
                ExportZeile([
                    "abhaken": ExportZelle(kaestchen: true), "menge": ExportZelle(e.mengeText, fett: true),
                    "einheit": ExportZelle(e.einheit), "benennung": ExportZelle(e.benennung, unter: e.hinweis),
                    "preis_je": ExportZelle(e.preisJe.map(KevFormat.euro) ?? "–"),
                    "preis": ExportZelle(e.preis.map(KevFormat.euro) ?? "–"),
                    "bezugsquelle": ExportZelle(e.linkTitel ?? "–", farbe: e.link != nil ? ExportStil.blau : nil,
                                                verweis: e.link),
                    "hinweis": ExportZelle(e.hinweis ?? ""),
                ])
            }
            zeilen.append(.summe(["benennung": ExportZelle("Summe"),
                                  "preis": ExportZelle(summe.map(KevFormat.euro) ?? "–")]))
            bloecke.append(.tabelle(ExportTabelle(spalten: spalten, zeilen: zeilen)))
            if let h = b.einkaufHinweis, !h.isEmpty { bloecke += [.abstand(2), hinweisZeile(h)] }
            if b.ohnePreis > 0 {
                bloecke.append(hinweisZeile("\(b.ohnePreis) Positionen ohne Preis im Katalog, Summe daher unvollständig"))
            }
        }
        // Kleinteile: Bedarf, aus Bestand, kaufen
        if !b.stueckgut.isEmpty {
            bloecke += [.abstand(6), zwischentitel("Kleinteile abzählen", "Bedarf, aus dem Projektbestand, zu kaufen")]
            let sp = [
                ExportSpalte("abhaken", "", mindest: 7, .mitte), ExportSpalte("benennung", "Benennung", mindest: 60, gewicht: 3),
                ExportSpalte("masse", "Maße", mindest: 24, gewicht: 1), ExportSpalte("anzahl", "Bedarf", mindest: 14, .rechts),
                ExportSpalte("bestand", "Bestand", mindest: 14, .rechts), ExportSpalte("kaufen", "Kaufen", mindest: 14, .rechts),
            ]
            let zeilen = b.stueckgut.map { s in
                ExportZeile([
                    "abhaken": ExportZelle(kaestchen: true), "benennung": ExportZelle(s.benennung),
                    "masse": ExportZelle(s.laenge.map { "\(s.masseText), L = \(KevFormat.length($0))" } ?? s.masseText),
                    "anzahl": ExportZelle("\(s.anzahl)", fett: true), "bestand": ExportZelle("\(s.ausBestand)"),
                    "kaufen": ExportZelle("\(s.kaufen)", fett: s.kaufen > 0, farbe: s.kaufen > 0 ? ExportStil.akzent : nil),
                ])
            }
            bloecke.append(.tabelle(ExportTabelle(spalten: sp, zeilen: zeilen)))
        }
        if let s = b.bestandStand {
            bloecke += [.abstand(2), hinweisZeile("Bestand vom \(BestandText.anzeige(s) ?? s)")]
        }
        return flussSeiten(.einkaufsliste, format, bloecke)
    }

    // MARK: Zuschnitt

    static func zuschnitt(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ format: ExportFormat,
                          _ hinweise: inout [String]) -> [ExportSeite]
    {
        var bloecke: [ExportBlock] = []
        let zuschnitte = q.bestand?.zuschnitte ?? []
        if zuschnitte.isEmpty, let cuts = q.bom?.cuts, !cuts.isEmpty {
            // ohne Bestandsabgleich: Zuschnitt aus der Stückliste (alle Stangen neu)
            bloecke.append(ueberschrift("Zuschnitt", "Ohne Projektbestand: alle Stangen neu"))
            for c in cuts {
                bloecke.append(zwischentitel(c.benennung, "\(c.stangen.count) × \(KevFormat.length(c.stangenlaenge)), "
                                             + "Sägeblatt \(KevFormat.length(c.saegeschnitt))"))
                for (i, st) in c.stangen.enumerated() {
                    let quelle = ZuschnittQuelle(json: [
                        "art": "kaufen", "laenge": .number(c.stangenlaenge), "stuecke": .array(st.map { .number($0) }),
                    ], index: i)
                    if let quelle { bloecke.append(leiste(quelle, nummer: i + 1, saege: c.saegeschnitt, mindest: 100,
                                                          skala: c.stangenlaenge)) }
                }
                bloecke.append(.abstand(4))
            }
            return flussSeiten(.zuschnitt, format, bloecke)
        }
        guard !zuschnitte.isEmpty else {
            return flussSeiten(.zuschnitt, format, [ueberschrift("Zuschnitt", nil), leer("Nichts zuzuschneiden")])
        }
        let stangen = zuschnitte.filter { !$0.istPlatte }.reduce(0) { $0 + $1.quellen.count }
        let platten = zuschnitte.filter(\.istPlatte).reduce(0) { $0 + $1.quellen.count }
        var kz: [String] = []
        if stangen > 0 { kz.append(KevFormat.count(stangen, one: "Stange", many: "Stangen")) }
        if platten > 0 { kz.append(KevFormat.count(platten, one: "Platte", many: "Platten")) }
        bloecke.append(ueberschrift("Zuschnitt", kz.joined(separator: ", ") + " · Reste aus dem Bestand zuerst"))
        bloecke.append(legende())
        var tabelle: [ExportZeile] = []
        for z in zuschnitte {
            bloecke.append(zwischentitel(z.benennung, z.herkunftText))
            let saege = z.saegeschnitt
            let mindest = z.mindestrest ?? 100
            for (i, quelle) in z.quellen.enumerated() {
                if z.istPlatte {
                    bloecke.append(platte(quelle, nummer: i + 1, saege: saege))
                } else {
                    bloecke.append(leiste(quelle, nummer: i + 1, saege: saege, mindest: mindest, skala: z.laengsteQuelle))
                }
                let rest: String
                if quelle.istPlatte {
                    rest = quelle.resteNeu.map(\.masseText).joined(separator: ", ")
                } else {
                    let r = quelle.restLaenge(saegeschnitt: saege)
                    rest = r > 0.05 ? KevFormat.length(r) : "–"
                }
                let stuecke = quelle.istPlatte ? quelle.flaechen.map(\.masseText).joined(separator: ", ")
                    : quelle.stuecke.map { KevFormat.compact($0, maxDigits: 1) }.joined(separator: " + ") + " mm"
                tabelle.append(ExportZeile([
                    "stange": ExportZelle("\(z.istPlatte ? "Platte" : "Stange") \(i + 1)", unter: z.benennung),
                    "herkunft": ExportZelle(quelle.titel, farbe: ExportStil.farbe(quelle.art.farbe)),
                    "stuecke": ExportZelle(stuecke), "rest": ExportZelle(rest),
                    "verschnitt": ExportZelle(quelle.restIstVerschnitt(saegeschnitt: saege, mindestrest: mindest)
                                              ? "ja" : "–"),
                ]))
            }
            if z.hatNeueReste {
                bloecke.append(hinweisZeile("Neue Reste für den Bestand: \(z.neueResteText)", farbe: ExportStil.gruen))
            }
            bloecke.append(.abstand(4))
        }
        if !tabelle.isEmpty {
            bloecke += [zwischentitel("Übersicht"), .tabelle(ExportTabelle(spalten: wahl.wirksameSpalten, zeilen: tabelle))]
        }
        return flussSeiten(.zuschnitt, format, bloecke)
    }

    static func legende() -> ExportBlock {
        .fest(hoehe: 9, mitNaechstem: false) { l, r in
            var x = r.minX
            let eintraege: [(ZuschnittFarbe, String)] = [
                (.rest, "aus Rest"), (.bestand, "aus Bestand"), (.kaufen, "kaufen"), (.restNeu, "neuer Rest"),
                (.verschnitt, "Verschnitt"),
            ]
            for (f, t) in eintraege {
                let box = CGRect(x: x, y: r.minY + 2, width: 5, height: 3.4)
                if f == .restNeu {
                    l.rechteck(box, rand: ExportStil.farbe(f), randBreite: 0.35, radius: 0.5, strich: [0.8, 0.6])
                } else {
                    l.rechteck(box, fuellung: ExportStil.farbe(f), radius: 0.5)
                }
                x += 6.5
                x += l.text(t, x: x, y: r.minY + 4.9, .normal(7.5), farbe: ExportStil.grau) + 6
            }
        }
    }

    /// Zuschnittleiste einer Stange: Stücke farbig nach Quelle mit Längen, Sägeschnitte, neuer Rest, Verschnitt.
    static func leiste(_ q: ZuschnittQuelle, nummer: Int, saege: Double, mindest: Double, skala: Double) -> ExportBlock {
        .fest(hoehe: 15, mitNaechstem: false) { l, r in
            let labelW: CGFloat = 30
            l.text("\(nummer)", x: r.minX, y: r.minY + 7.6, .fett(10), farbe: ExportStil.tinte)
            l.text(q.titel, x: r.minX + 5, y: r.minY + 7.6, .normal(7.5), farbe: ExportStil.grau, maxBreite: labelW - 6)
            let bx = r.minX + labelW
            let bw = r.width - labelW
            let k = bw / CGFloat(max(1, skala))
            let gesamt = CGFloat(q.laenge ?? skala) * k
            let barY = r.minY + 3, barH: CGFloat = 6.5
            l.rechteck(CGRect(x: bx, y: barY, width: gesamt, height: barH), rand: ExportStil.linie, randBreite: 0.2)
            let farbe = ExportStil.farbe(q.art.farbe)
            for s in q.segmente(saegeschnitt: saege, mindestrest: mindest) {
                let sr = CGRect(x: bx + CGFloat(s.start) * k, y: barY, width: max(0.2, CGFloat(s.laenge) * k), height: barH)
                switch s.art {
                case .stueck:
                    l.rechteck(sr, fuellung: farbe)
                    let txt = KevFormat.compact(s.laenge, maxDigits: 1)
                    if ExportLeinwand.breite(txt, .mittel(7)) < sr.width - 1.5 {
                        l.text(txt, x: sr.midX, y: barY + barH / 2 + 1.2, .mittel(7), farbe: ExportStil.weiss, .mitte)
                    }
                case .schnitt:
                    l.rechteck(sr, fuellung: ExportStil.tinte)
                case .restNeu:
                    l.rechteck(sr.insetBy(dx: 0.2, dy: 0.2), rand: ExportStil.farbe(.restNeu), randBreite: 0.35,
                               strich: [0.8, 0.6])
                    let txt = "Rest " + KevFormat.compact(s.laenge, maxDigits: 0)
                    if ExportLeinwand.breite(txt, .normal(6.5)) < sr.width - 1.5 {
                        l.text(txt, x: sr.midX, y: barY + barH / 2 + 1.1, .normal(6.5), farbe: ExportStil.gruen, .mitte)
                    }
                case .verschnitt:
                    l.rechteck(sr, fuellung: ExportStil.farbe(.verschnitt))
                }
            }
            // Maßlinie über die ganze Stange
            l.text(KevFormat.length(q.laenge ?? skala), x: bx + gesamt, y: barY + barH + 3.6, .normal(6.5),
                   farbe: ExportStil.grau, .rechts)
        }
    }

    /// Plattenzuschnitt: Platte mit Stücken (Lage aus dem Kernel), neue Reste gestrichelt.
    static func platte(_ q: ZuschnittQuelle, nummer: Int, saege: Double) -> ExportBlock {
        let pb = CGFloat(q.b ?? 1000), ph = CGFloat(q.h ?? 500)
        let breite: CGFloat = 120
        let k = breite / max(1, pb)
        let hoehe = ph * k
        return .fest(hoehe: hoehe + 10, mitNaechstem: false) { l, r in
            l.text("\(nummer)", x: r.minX, y: r.minY + 5, .fett(10), farbe: ExportStil.tinte)
            l.text(q.titel, x: r.minX + 5, y: r.minY + 5, .normal(7.5), farbe: ExportStil.grau, maxBreite: 26)
            let ox = r.minX + 32, oy = r.minY + 2
            let rahmen = CGRect(x: ox, y: oy, width: breite, height: hoehe)
            l.rechteck(rahmen, fuellung: ExportStil.flaeche, rand: ExportStil.grau, randBreite: 0.25)
            let farbe = ExportStil.farbe(q.art.farbe)
            for f in q.flaechen {
                let sr = CGRect(x: ox + CGFloat(f.x) * k, y: oy + CGFloat(f.y) * k, width: CGFloat(f.b) * k,
                                height: CGFloat(f.h) * k)
                l.rechteck(sr, fuellung: farbe, rand: ExportStil.weiss, randBreite: 0.3)
                if ExportLeinwand.breite(f.masseText, .mittel(6.5)) < sr.width - 2 && sr.height > 4 {
                    l.text(f.masseText, x: sr.midX, y: sr.midY + 1.1, .mittel(6.5), farbe: ExportStil.weiss, .mitte)
                }
            }
            for f in q.resteNeu {
                let sr = CGRect(x: ox + CGFloat(f.x) * k, y: oy + CGFloat(f.y) * k, width: CGFloat(f.b) * k,
                                height: CGFloat(f.h) * k)
                l.rechteck(sr.insetBy(dx: 0.4, dy: 0.4), rand: ExportStil.farbe(.restNeu), randBreite: 0.35,
                           strich: [0.8, 0.6])
            }
            l.text(BestandText.format(Double(pb), Double(ph)), x: rahmen.maxX + 3, y: rahmen.minY + 3, .normal(7),
                   farbe: ExportStil.grau)
        }
    }

    // MARK: Zeichnungen

    static func zeichnungen(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ hinweise: inout [String])
        -> [ExportSeite]
    {
        var blaetter = q.zeichnungen
        if let a = wahl.auswahl, !a.isEmpty {
            let fehlen = a.filter { id in !blaetter.contains { $0.id == id } }
            if !fehlen.isEmpty { hinweise.append("Zeichnungen nicht gefunden: \(fehlen.joined(separator: ", "))") }
            blaetter = a.compactMap { id in blaetter.first { $0.id == id } }
        }
        if blaetter.isEmpty {
            hinweise.append("Keine Zeichnungen: erst „Zeichnungen erstellen“")
            return []
        }
        return blaetter.map { b in
            ExportSeite(groesse: b.groesse, baustein: .zeichnungen, titel: b.titel, mitKopf: false,
                        gliederung: [b.titel], inhalt: .roh(b.zeichne))
        }
    }
}
