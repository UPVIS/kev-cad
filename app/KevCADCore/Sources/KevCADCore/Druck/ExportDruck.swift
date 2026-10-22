import CoreGraphics
import Foundation

// Baustein „3D-Druck“ im Dokument-Export (DRUCKVORSCHAU.md, Abschnitt „App“): Kennzahlen, Filament je Material, je
// Platte die Draufsicht mit der Anordnung und eine Tabelle der Teile mit Einstellungen, zuletzt die Hinweise. Im
// Seitenlayout der übrigen Berichte (Seitenfluss, Kopf- und Fußzeile, Tabellen brechen zwischen Zeilen).

public enum ExportDruckSeiten {
    /// Farben je Material in der Reihenfolge des ersten Auftretens (Kennfarbe zuerst).
    static let palette: [CGColor] = [
        ExportStil.akzent, ExportStil.blau, ExportStil.gruen, ExportStil.farbe(0.55, 0.32, 0.72),
        ExportStil.farbe(0.80, 0.18, 0.45), ExportStil.farbe(0.15, 0.60, 0.65),
    ]

    public static func seiten(_ q: ExportQuellen, _ wahl: ExportBausteinWahl, _ format: ExportSeitenformat,
                              _ hinweise: inout [String]) -> [ExportSeite]
    {
        guard let d = q.druck, !d.istLeer else {
            hinweise.append("3D-Druck: keine Druckvorschau (keine Druckteile im Modell oder noch kein Lauf)")
            return []
        }
        let farben = materialFarben(d)
        let nummern = Dictionary(uniqueKeysWithValues: d.teile.enumerated().map { ($1.gruppe, $0 + 1) })
        var bloecke: [ExportBlock] = []
        let kennzeile = [
            KevFormat.count(d.summe.platten, one: "Platte", many: "Platten"),
            DruckFormat.zeit(d.summe.zeitMitWechselS) + (d.summe.wechselS > 0 ? " mit Plattenwechseln" : ""),
            DruckFormat.gramm(d.summe.gramm) + " Filament",
            d.summe.kosten.map { "≈ " + DruckFormat.euro($0) },
            d.drucker,
        ].compactMap { $0 }.joined(separator: " · ")
        bloecke.append(ExportBauer.ueberschrift("3D-Druck", kennzeile))
        bloecke.append(kennzahlen(d))
        if d.stand != .slicer {
            bloecke.append(ExportBauer.hinweisZeile(
                d.stand == .schaetzung
                    ? "Werte aus der schnellen Schätzung des Kernels; Bambu Studio rechnet sie im Hintergrund nach."
                    : "Teils von Bambu Studio gerechnet, der Rest geschätzt (\(d.slicer.fertig) von \(d.slicer.gesamt))."))
        }
        // Filament je Material
        bloecke += [.abstand(4), .marke("Filament"), ExportBauer.zwischentitel("Filament", "je Material")]
        bloecke.append(.tabelle(filamentTabelle(d)))
        var fuss: [String] = []
        if let s = d.summe.kostenStrom { fuss.append("Strom \(DruckFormat.euro(s))") }
        if let f = d.summe.kostenFilament { fuss.append("Filament \(DruckFormat.euro(f))") }
        let staende = Set(d.summe.material.compactMap(\.preisStand))
        if !staende.isEmpty { fuss.append("Preise aus dem Materialkatalog, Stand \(staende.sorted().joined(separator: ", "))") }
        if d.summe.wechselS > 0 { fuss.append("Plattenwechsel \(DruckFormat.zeit(d.summe.wechselS))") }
        if !fuss.isEmpty { bloecke += [.abstand(1.5), ExportBauer.hinweisZeile(fuss.joined(separator: " · "))] }
        // Je Platte: Draufsicht und Teile mit Einstellungen
        let spalten = wahl.wirksameSpalten
        for p in d.platten {
            let titel = "Platte \(p.nr)"
            let rechts = [DruckFormat.zeit(p.zeitS), DruckFormat.gramm(p.gramm),
                          "\(DruckFormat.prozent(DruckPlattenGeometrie.auslastung(p, bett: d.bett))) belegt",
                          p.stand.titel].joined(separator: " · ")
            bloecke += [.abstand(5), .marke(titel), ExportBauer.zwischentitel(titel, rechts)]
            bloecke.append(plattenBild(p, d, farben: farben, nummern: nummern))
            bloecke.append(.abstand(2))
            bloecke.append(.tabelle(teileTabelle(p, d, spalten: spalten, nummern: nummern)))
        }
        // Teile, die auf keiner Platte liegen (etwa zu groß für den Bauraum)
        let aufPlatten = Set(d.platten.flatMap { $0.teile.compactMap(\.gruppe) })
        let ohne = d.teile.filter { !aufPlatten.contains($0.gruppe) && !$0.teile.contains { n in d.platte(vonTeil: n) != nil } }
        if !ohne.isEmpty, !d.platten.isEmpty {
            bloecke += [.abstand(5), ExportBauer.zwischentitel("Ohne Platte", "nicht angeordnet")]
            let p = DruckPlatte(nr: 0, teile: ohne.flatMap { g in
                (0..<g.anzahl).map { _ in DruckPlattenTeil(name: g.teile.first ?? g.name, gruppe: g.gruppe, x: 0, y: 0) }
            })
            bloecke.append(.tabelle(teileTabelle(p, d, spalten: spalten, nummern: nummern)))
        }
        // Hinweise
        let alle = d.alleHinweise
        if !alle.isEmpty {
            bloecke += [.abstand(5), .marke("Hinweise"), ExportBauer.zwischentitel("Hinweise", "für einen gelungenen Druck")]
            for (h, gruppen) in alle {
                let namen = gruppen.compactMap { g in d.gruppe(g).map { gr in (nummern[g].map { "\($0) " } ?? "") + gr.kurzname } }
                bloecke.append(hinweisBlock(h, betrifft: namen))
            }
        }
        return ExportBauer.flussSeiten(.druck, format, bloecke)
    }

    // MARK: Bausteine

    /// Vier Kacheln wie auf dem Deckblatt: Platten, Druckzeit, Filament, Kosten.
    static func kennzahlen(_ d: Druckvorschau) -> ExportBlock {
        let zahlen: [(String, String)] = [
            (KevFormat.integer(d.summe.platten), d.summe.platten == 1 ? "Platte" : "Platten"),
            (DruckFormat.zeit(d.summe.zeitMitWechselS), "Druckzeit"),
            (DruckFormat.gramm(d.summe.gramm), "Filament"),
            (d.summe.kosten.map { "≈ " + DruckFormat.euro($0) } ?? "–", "Kosten"),
        ]
        return .fest(hoehe: 22, mitNaechstem: false) { l, r in
            let w = (r.width - 3 * 4) / 4
            for (i, z) in zahlen.enumerated() {
                let x = r.minX + CGFloat(i) * (w + 4)
                l.rechteck(CGRect(x: x, y: r.minY + 2, width: w, height: 17), rand: ExportStil.linie, randBreite: 0.2,
                           radius: 2)
                l.text(z.0, x: x + 4, y: r.minY + 10.6, .fett(13), farbe: ExportStil.tinte, maxBreite: w - 8)
                l.text(z.1.uppercased(), x: x + 4, y: r.minY + 15.6, .mittel(6.5), farbe: ExportStil.grau, laufweite: 0.2)
            }
        }
    }

    static func filamentTabelle(_ d: Druckvorschau) -> ExportTabelle {
        let spalten = [
            ExportSpalte("material", "Material", mindest: 24, gewicht: 1),
            ExportSpalte("filament", "Filament", mindest: 40, gewicht: 2),
            ExportSpalte("gewicht", "Gewicht", mindest: 18, .rechts),
            ExportSpalte("laenge", "Länge", mindest: 18, .rechts),
            ExportSpalte("preis_kg", "Preis je kg", mindest: 20, .rechts),
            ExportSpalte("kosten", "Kosten", mindest: 18, .rechts),
        ]
        var zeilen: [ExportZeile] = d.summe.material.map { m in
            ExportZeile([
                "material": ExportZelle(m.name, fett: true), "filament": ExportZelle(m.filament ?? "Systemprofil",
                                                                                     unter: m.stand.titel),
                "gewicht": ExportZelle(DruckFormat.gramm(m.g)), "laenge": ExportZelle(m.m.map(DruckFormat.meter) ?? "–"),
                "preis_kg": ExportZelle(m.preisKg.map { DruckFormat.euro($0) } ?? "–"),
                "kosten": ExportZelle(m.kosten.map(DruckFormat.euro) ?? "–"),
            ])
        }
        if d.summe.material.count > 1 || d.summe.kostenStrom != nil {
            zeilen.append(.summe([
                "material": ExportZelle("Summe"), "gewicht": ExportZelle(DruckFormat.gramm(d.summe.gramm)),
                "laenge": ExportZelle(d.summe.meter.map(DruckFormat.meter) ?? "–"),
                "kosten": ExportZelle(d.summe.kosten.map(DruckFormat.euro) ?? "–"),
            ]))
        }
        return ExportTabelle(spalten: spalten, zeilen: zeilen)
    }

    /// Tabelle der Teile einer Platte: je Gruppe eine Zeile mit Anzahl auf dieser Platte und den Einstellungen.
    static func teileTabelle(_ p: DruckPlatte, _ d: Druckvorschau, spalten: [ExportSpalte], nummern: [String: Int])
        -> ExportTabelle
    {
        var zeilen: [ExportZeile] = []
        for (key, anzahl) in p.gruppen {
            let g = d.gruppe(key) ?? d.gruppe(vonTeil: key)
            let e = g?.einstellungen ?? DruckEinstellungen(json: nil)
            let anteil = Double(anzahl) / Double(max(1, g?.anzahl ?? anzahl))
            let gesetzt = DruckFormat.vorgaben(g?.vorgaben ?? [:])
            var unter = g?.begruendung.first
            if !gesetzt.isEmpty { unter = gesetzt.joined(separator: " · ") + (unter.map { " · " + $0 } ?? "") }
            var z: [String: ExportZelle] = [:]
            z["nr"] = ExportZelle(g.flatMap { nummern[$0.gruppe] }.map(String.init) ?? "–", fett: true)
            z["teil"] = ExportZelle(g?.kurzname ?? key, unter: unter,
                                    farbe: g?.ampel == .rot ? ExportStil.rot : nil)
            z["anzahl"] = ExportZelle("\(anzahl)", fett: true)
            z["material"] = ExportZelle((g?.material).map { $0.uppercased() } ?? "–")
            z["zweck"] = ExportZelle(DruckFormat.zweck(g?.zweck), unter: g?.zweckGeschaetzt == true ? "geschätzt" : nil)
            z["schicht"] = ExportZelle(e.schichtMM.map(DruckFormat.schicht) ?? "–")
            z["waende"] = ExportZelle(e.waende.map(String.init) ?? "–")
            z["fuellung"] = ExportZelle(e.fuellung.map(DruckFormat.prozent) ?? "–", unter: e.muster.map(DruckFormat.muster))
            z["stuetzen"] = ExportZelle(DruckFormat.stuetzen(e.stuetzen))
            z["brim"] = ExportZelle(e.brim == true ? "ja" : e.brim == false ? "–" : "")
            z["ausrichtung"] = ExportZelle(e.ausrichtung ?? "–")
            z["zeit"] = ExportZelle(g.map { DruckFormat.zeit($0.zeitS * anteil) } ?? "–")
            z["gewicht"] = ExportZelle(g.map { DruckFormat.gramm($0.g * anteil) } ?? "–")
            z["kosten"] = ExportZelle(g?.kosten.map { DruckFormat.euro($0 * anteil) } ?? "–")
            zeilen.append(ExportZeile(z))
        }
        if p.nr > 0 {
            zeilen.append(.summe([
                "teil": ExportZelle("Platte \(p.nr)"), "anzahl": ExportZelle("\(p.teile.count)"),
                "zeit": ExportZelle(DruckFormat.zeit(p.zeitS)), "gewicht": ExportZelle(DruckFormat.gramm(p.gramm)),
            ]))
        }
        var t = ExportTabelle(spalten: spalten, zeilen: zeilen)
        t.schrift = .normal(7.5)
        t.kopfSchrift = .mittel(6.2)
        return t
    }

    /// Draufsicht der Platte im Maßstab (vorn unten) mit Sperrzone, Teile als Umriss mit ihrer Nummer; rechts daneben
    /// Material und Belegung.
    static func plattenBild(_ p: DruckPlatte, _ d: Druckvorschau, farben: [String: CGColor], nummern: [String: Int])
        -> ExportBlock
    {
        let seite: CGFloat = 66
        return .fest(hoehe: seite + 4, mitNaechstem: false) { l, r in
            let rahmen = CGRect(x: r.minX, y: r.minY + 1, width: seite, height: seite)
            let geo = DruckPlattenGeometrie(bett: d.bett, in: rahmen)
            zeichnePlatte(l, geo, p, d, farben: farben, nummern: nummern)
            // rechts: Legende
            var y = r.minY + 4
            let x = rahmen.maxX + 8
            let w = r.maxX - x
            l.text("BELEGUNG", x: x, y: y + 2, .mittel(6.5), farbe: ExportStil.grau, laufweite: 0.2)
            y += 8
            let anteil = DruckPlattenGeometrie.auslastung(p, bett: d.bett)
            let balken = CGRect(x: x, y: y - 3, width: min(60, w), height: 2.4)
            l.rechteck(balken, fuellung: ExportStil.flaecheTief, radius: 1.2)
            l.rechteck(CGRect(x: balken.minX, y: balken.minY, width: balken.width * CGFloat(anteil), height: balken.height),
                       fuellung: ExportStil.akzent, radius: 1.2)
            l.text(DruckFormat.prozent(anteil), x: balken.maxX + 3, y: y - 0.8, .mittel(8), farbe: ExportStil.tinte)
            y += 7
            l.text("MATERIAL", x: x, y: y, .mittel(6.5), farbe: ExportStil.grau, laufweite: 0.2)
            y += 5.5
            for m in p.material {
                l.rechteck(CGRect(x: x, y: y - 2.6, width: 3.2, height: 3.2), fuellung: farben[m.material] ?? palette[0],
                           radius: 0.6)
                let name = d.summe.material.first { $0.material == m.material }?.name ?? m.material.uppercased()
                l.text("\(name)  \(DruckFormat.gramm(m.g))", x: x + 5, y: y, .normal(8.5), farbe: ExportStil.tinte,
                       maxBreite: w - 5)
                y += 5
            }
            y += 2
            l.text("TEILE", x: x, y: y, .mittel(6.5), farbe: ExportStil.grau, laufweite: 0.2)
            y += 5.5
            for (key, anzahl) in p.gruppen.prefix(7) {
                let g = d.gruppe(key)
                let nr = g.flatMap { nummern[$0.gruppe] }.map { "\($0)" } ?? "–"
                l.text(nr, x: x + 2.5, y: y, .fett(8), farbe: ExportStil.tinte, .mitte)
                l.text("\(anzahl) × \(g?.kurzname ?? key)", x: x + 6, y: y, .normal(8.5), farbe: ExportStil.tinte,
                       maxBreite: w - 6)
                y += 4.8
            }
            if p.gruppen.count > 7 {
                l.text("und \(p.gruppen.count - 7) weitere", x: x + 6, y: y, .normal(8), farbe: ExportStil.grau)
            }
        }
    }

    /// Platte mit Raster, Sperrzone, Teilen und Nummern auf der Leinwand (mm, Ursprung links oben).
    static func zeichnePlatte(_ l: ExportLeinwand, _ geo: DruckPlattenGeometrie, _ p: DruckPlatte, _ d: Druckvorschau,
                              farben: [String: CGColor], nummern: [String: Int])
    {
        let pr = geo.platte
        l.rechteck(pr, fuellung: ExportStil.flaeche, rand: ExportStil.grau, randBreite: 0.3, radius: 1.2)
        let raster = geo.gitter(schritt: 50)
        for x in raster.x {
            let a = geo.punkt(SIMD2(x, 0)), b = geo.punkt(SIMD2(x, d.bett.tiefe))
            l.linie(a, b, breite: 0.1, farbe: ExportStil.linie)
        }
        for y in raster.y {
            let a = geo.punkt(SIMD2(0, y)), b = geo.punkt(SIMD2(d.bett.breite, y))
            l.linie(a, b, breite: 0.1, farbe: ExportStil.linie)
        }
        // Sperrzone schraffiert
        for z in geo.sperrzonen {
            l.rechteck(z, fuellung: ExportStil.rotHell, rand: ExportStil.rot, randBreite: 0.15)
            l.ctx.saveGState()
            l.ctx.clip(to: z)
            var s = z.minX - z.height
            while s < z.maxX {
                l.linie(CGPoint(x: s, y: z.maxY), CGPoint(x: s + z.height, y: z.minY), breite: 0.12, farbe: ExportStil.rot)
                s += 1.2
            }
            l.ctx.restoreGState()
        }
        // Teile
        for t in p.teile {
            let farbe = farben[d.gruppe(t.gruppe ?? "")?.material ?? ""] ?? palette[0]
            let pfad = geo.pfad(t.plattenUmriss)
            l.ctx.saveGState()
            l.ctx.addPath(pfad)
            l.ctx.setFillColor(farbe.copy(alpha: 0.28) ?? farbe)
            l.ctx.fillPath()
            l.ctx.addPath(pfad)
            l.ctx.setStrokeColor(farbe)
            l.ctx.setLineWidth(0.25)
            l.ctx.strokePath()
            l.ctx.restoreGState()
        }
        for t in p.teile {
            guard let g = t.gruppe.flatMap(d.gruppe(_:)) ?? d.gruppe(vonTeil: t.name), let nr = nummern[g.gruppe] else {
                continue
            }
            let m = geo.punkt(t.mitte)
            let box = geo.pfad(t.plattenUmriss).boundingBox
            guard box.width > 2.6, box.height > 2.6 else { continue }
            l.text("\(nr)", x: m.x, y: m.y + 1.1, .fett(min(7, max(4.5, box.height * 0.6))), farbe: ExportStil.tinte, .mitte)
        }
        // vorn markieren
        l.text("VORN", x: pr.midX, y: pr.maxY + 3, .mittel(5.5), farbe: ExportStil.grau, .mitte, laufweite: 0.3)
    }

    static func hinweisBlock(_ h: DruckpraxisHinweis, betrifft: [String]) -> ExportBlock {
        let text = h.text + (betrifft.isEmpty ? "" : "  (" + betrifft.joined(separator: ", ") + ")")
        let breite: CGFloat = 165
        let hoehe = ExportSatz(text, breite: breite, schrift: .normal(8.5)).hoehe + 2.2
        return .fest(hoehe: hoehe, mitNaechstem: false) { l, r in
            let farbe: CGColor
            switch h.schwere {
            case .fehler: farbe = ExportStil.rot
            case .warnung: farbe = ExportStil.gelb
            case .hinweis: farbe = ExportStil.gruen
            }
            l.kreis(CGPoint(x: r.minX + 1.8, y: r.minY + 2.9), radius: 1.3, fuellung: farbe)
            l.text(h.schwere.titel.uppercased(), x: r.minX + 5, y: r.minY + 3.9, .mittel(6.5), farbe: ExportStil.grau,
                   laufweite: 0.2)
            l.absatz(text, x: r.minX + 22, y: r.minY + 0.8, breite: r.width - 22, .normal(8.5), farbe: ExportStil.tinte)
        }
    }

    static func materialFarben(_ d: Druckvorschau) -> [String: CGColor] {
        var out: [String: CGColor] = [:]
        var reihenfolge = d.summe.material.map(\.material)
        for g in d.teile { if let m = g.material, !reihenfolge.contains(m) { reihenfolge.append(m) } }
        for (i, m) in reihenfolge.enumerated() { out[m] = palette[i % palette.count] }
        return out
    }
}
