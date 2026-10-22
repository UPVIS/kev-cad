import Foundation
import XCTest

@testable import KevCADCore

/// Strang „Material“: eine Datenquelle für Bereich, Schnellansichten und Berichte (gleiche Summen überall) und der
/// Zustand der Schnellansichten.
final class MaterialTests: XCTestCase {
    // MARK: Hilfen

    private func bomMitBestand() throws -> BOMMessage {
        guard case .bom(let m) = try Fixtures.message("bom_bestand.frame") else {
            XCTFail("kein BOM")
            throw NSError(domain: "test", code: 1)
        }
        return m
    }

    private func bomZukauf() throws -> BOMMessage {
        guard case .bom(let m) = try Fixtures.message("bom_zukauf.frame") else {
            XCTFail("kein BOM")
            throw NSError(domain: "test", code: 1)
        }
        return m
    }

    private func line(_ pos: Int, art: String, stock: String? = nil, laenge: Double? = nil, masse: String = "",
                      anzahl: Int = 1, kg: Double? = nil, preis: Double? = nil, teile: [String] = [],
                      eigenteil: Bool = false, material: String? = nil) -> BOMLine
    {
        BOMLine(pos: pos, art: art, stockID: stock, benennung: "Teil \(pos)", material: material, laenge: laenge,
                masseText: masse, anzahl: anzahl, kg: kg, preis: preis, teile: teile, eigenteil: eigenteil)
    }

    // MARK: Gruppen und Kennzeichen

    func testGruppenInFesterReihenfolge() {
        XCTAssertEqual(MaterialGruppe(art: "rohr"), .stangen)
        XCTAssertEqual(MaterialGruppe(art: "nutprofil"), .stangen)
        XCTAssertEqual(MaterialGruppe(art: "holz"), .stangen)
        XCTAssertEqual(MaterialGruppe(art: "platte"), .platten)
        XCTAssertEqual(MaterialGruppe(art: "schraube"), .normteile)
        XCTAssertEqual(MaterialGruppe(art: "scheibe"), .normteile)
        XCTAssertEqual(MaterialGruppe(art: "zukaufteil"), .zukauf)
        XCTAssertEqual(MaterialGruppe(art: "kamera"), .zukauf)
        XCTAssertEqual(MaterialGruppe(art: "druckteil"), .druckteile)
        XCTAssertEqual(MaterialGruppe(art: "eigenteil"), .eigenteile)
        XCTAssertEqual(MaterialGruppe(art: "gibtsnicht"), .weitere)
        XCTAssertEqual(MaterialGruppe.allCases.map(\.titel),
                       ["Stangen und Profile", "Platten", "Normteile", "Zukaufteile", "Druckteile", "Eigenteile", "Weitere"])
        // Der Bericht nimmt dieselben Gruppen
        XCTAssertEqual(ExportBauer.artGruppe("druckteil").1, "Druckteile")
        XCTAssertEqual(ExportBauer.artGruppe("platte").0, MaterialGruppe.platten.rawValue)
        // Kennzeichen: gleiche Begriffe und Farben wie im Zuschnitt
        XCTAssertEqual([MaterialKennzeichen.kaufen, .bestand, .rest, .zukauf, .druckteil, .eigenteil].map(\.titel),
                       ["Kaufen", "Bestand", "Rest", "Zukauf", "Druckteil", "Eigenteil"])
        XCTAssertEqual(MaterialKennzeichen.kaufen.rgb.r, ZuschnittFarbe.kaufen.rgb.r)
        XCTAssertEqual(MaterialKennzeichen(ZuschnittQuelleArt.rest), .rest)
    }

    // MARK: Datenquelle

    func testSummenWieStuecklisteUndKernel() throws {
        let m = try bomMitBestand()
        let z = try XCTUnwrap(m.bestand)
        let d = MaterialDaten(bom: m.bom, bestand: z)
        XCTAssertEqual(d.run, m.bom.run)
        XCTAssertEqual(d.kennzahlen.teile, m.bom.totals.teile)
        XCTAssertEqual(d.kennzahlen.positionen, m.bom.totals.positionen)
        XCTAssertEqual(d.kennzahlen.kg, m.bom.totals.kg, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.preis, m.bom.totals.preis)
        // Einkaufsliste wie vom Kernel, Summe wie dort
        XCTAssertEqual(d.lagerEinkauf.map(\.position.id), z.einkaufsliste.map(\.id))
        XCTAssertEqual(d.kennzahlen.einkaufLagerSumme, z.summe)
        XCTAssertEqual(d.kennzahlen.einkaufSumme, z.summe)
        XCTAssertTrue(d.zukaufEinkauf.isEmpty)
        // Gruppen der Positionen
        XCTAssertEqual(d.gruppen.map(\.gruppe), [.stangen, .platten, .normteile])
        XCTAssertEqual(d.gruppen.map { $0.positionen.count }, [4, 2, 2])
        // Summen der Gruppen ergeben die Summen der Stückliste
        let teile = d.gruppen.map { MaterialDaten.summen($0.positionen).teile }.reduce(0, +)
        XCTAssertEqual(teile, m.bom.totals.teile)
        // Zuschnitt: Kernel-Quellen, Kennzahlen aus den Quellen
        XCTAssertEqual(d.zuschnitte.map(\.stockID), z.zuschnitte.map(\.stockID))
        XCTAssertEqual(d.kennzahlen.stangen, z.zuschnitt("rohr-alfer-12x1")?.quellen.count)
        XCTAssertEqual(d.kennzahlen.platten, z.zuschnitt("platte-multiplex-birke-18")?.quellen.count)
        XCTAssertNotNil(d.kennzahlen.verschnittStangen)
        XCTAssertEqual(d.mindestrest("rohr-alfer-12x1"), 80)
        XCTAssertEqual(d.stueckgut.count, 2)
    }

    func testVersorgungJePosition() throws {
        let m = try bomMitBestand()
        let d = MaterialDaten(bom: m.bom, bestand: m.bestand)
        // 1.000 mm: ganze Stangen aus dem Bestand und eine gekaufte
        XCTAssertEqual(d.position(1)?.versorgung, [.bestand, .kaufen])
        // kurze Stücke aus Resten
        XCTAssertEqual(d.position(2)?.versorgung, [.rest])
        XCTAssertEqual(d.position(4)?.versorgung, [.rest])
        // Schrauben: 12 aus dem Bestand, 4 kaufen
        XCTAssertEqual(d.position(7)?.versorgung, [.bestand, .kaufen])
        XCTAssertEqual(d.position(7)?.kennzeichen, [.bestand, .kaufen])
        XCTAssertNil(d.position(7)?.herkunft)
        XCTAssertFalse(d.position(5)?.versorgung.isEmpty ?? true)
        // ohne Bestandsabgleich keine Versorgung
        let ohne = MaterialDaten(bom: m.bom)
        XCTAssertTrue(ohne.positionen.allSatisfy { $0.versorgung.isEmpty })
        XCTAssertFalse(ohne.kennzahlen.mitBestand)
        // Zuschnitt ohne Quellen: aus der Stückliste, alle Stangen neu
        XCTAssertEqual(ohne.zuschnitte.count, m.bom.cuts.filter { !$0.stangen.isEmpty }.count)
        XCTAssertFalse(ohne.zuschnitte.isEmpty)
        XCTAssertTrue(ohne.zuschnitte.flatMap(\.quellen).allSatisfy { $0.art == .kaufen })
    }

    func testZukaufteileStehenAufDerEinkaufsliste() throws {
        let m = try bomZukauf()
        let d = MaterialDaten(bom: m.bom, bestand: m.bestand)
        let p = try XCTUnwrap(d.positionen.first)
        XCTAssertEqual(p.herkunft, .zukauf)
        XCTAssertEqual(p.gruppe, .zukauf)
        XCTAssertEqual(p.kennzeichen, [.zukauf])
        XCTAssertEqual(d.zukaufEinkauf.count, 1)
        XCTAssertEqual(d.zukaufEinkauf.first?.position.preis, 24.99)
        XCTAssertEqual(d.zukaufEinkauf.first?.pos, p.pos)
        XCTAssertEqual(d.kennzahlen.einkaufZukaufSumme, 24.99)
        XCTAssertEqual(d.kennzahlen.zukaufteile, 1)
        XCTAssertEqual(d.kennzahlen.einkaufSumme, 24.99)
        XCTAssertNotNil(d.zukaufEinkauf.first?.position.link)
        XCTAssertTrue(p.herkunftText.contains("ALUTEC"))
    }

    func testDruckEigenteileUndFilament() {
        let bom = BillOfMaterials(run: 2, lines: [
            line(1, art: "druckteil", masse: "40 × 20 × 10", anzahl: 4, kg: 0.048, preis: 1.2, teile: ["H/1", "H/2"],
                 material: "PETG"),
            line(2, art: "druckteil", anzahl: 1, kg: 0.012, preis: 0.3, teile: ["Clip"], material: "PETG"),
            line(3, art: "eigenteil", anzahl: 1, kg: 2, teile: ["Kufe"], eigenteil: true, material: "Stahl"),
        ], cuts: [], totals: BOMTotals(kg: 2.06, preis: 1.5, positionen: 3, teile: 6))
        let d = MaterialDaten(bom: bom)
        XCTAssertEqual(d.kennzahlen.druckteile, 5)
        XCTAssertEqual(d.kennzahlen.druckGramm, 60, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.druckPreis ?? 0, 1.5, accuracy: 1e-9)
        XCTAssertEqual(d.kennzahlen.eigenteile, 1)
        XCTAssertEqual(d.filament.map(\.werkstoff), ["PETG"])
        XCTAssertEqual(d.filament.first?.gramm ?? 0, 60, accuracy: 1e-9)
        XCTAssertEqual(d.position(3)?.kennzeichen, [.eigenteil])
        XCTAssertEqual(d.position(1)?.name, "Teil 1")
        // Teileliste: Eigenteil nach der Stückliste, nicht „3D-Druck“
        let kufe = PartNode(id: "Kufe", color: .zero, material: "stahl")
        XCTAssertEqual(d.herkunft(kufe).titel, "Eigenteil")
        let clip = PartNode(id: "Clip", color: .zero, material: "petg")
        XCTAssertEqual(d.herkunft(clip).titel, "Druckteil")
        XCTAssertEqual(ExportBauer.herkunft(kufe, d).0, "Eigenteil")
    }

    func testNamenUndStand() {
        var zukauf = line(1, art: "zukaufteil", stock: "senkschraube")
        zukauf.benennung = "Senkschraube 3/8\"-16 UNC × 5/8\", 82°, Stahl"
        var druck = line(2, art: "druckteil", teile: ["Halter/Lasche"])
        druck.benennung = "Halter/Lasche"
        let d = MaterialDaten(bom: BillOfMaterials(run: 1, lines: [zukauf, druck], cuts: [],
                                                   totals: BOMTotals(kg: 0, preis: nil, positionen: 2, teile: 2)))
        // Katalognamen mit „/“ bleiben ganz, Teilpfade von Druck- und Eigenteilen werden geteilt
        XCTAssertEqual(d.position(1)?.name, zukauf.benennung)
        XCTAssertNil(d.position(1)?.unter)
        XCTAssertEqual(d.position(2)?.name, "Lasche")
        XCTAssertEqual(d.position(2)?.unter, "Halter")
        // Preisstand aus dem Hinweis der Stückliste
        XCTAssertEqual(MaterialText.standAusHinweis("Richtpreise, Stand 2026-10; Zukaufteile zum Shoppreis brutto"), "10/2026")
        XCTAssertEqual(MaterialText.standAusHinweis("Richtpreise, Stand 2026-10-21"), "21.10.2026")
        XCTAssertNil(MaterialText.standAusHinweis("Richtpreise"))
        XCTAssertEqual(MaterialText.stand("2026-10-22"), "22.10.2026")
    }

    func testVerschnittEinheitlich() {
        // Stange 1.000 mm: 400 + 300, zwei Schnitte à 3 → Rest 294 (verwertbar ab 100): Verschnitt 6 mm
        // Stange 1.000 mm: 940, ein Schnitt → Rest 57 unter dem Mindestrest: Verschnitt 60 mm
        let z = BestandZuschnitt(
            stockID: "rohr", benennung: "Rohr", stangenlaenge: 1000, saegeschnitt: 3,
            quellen: [ZuschnittQuelle(index: 0, art: .kaufen, laenge: 1000, stuecke: [400, 300]),
                      ZuschnittQuelle(index: 1, art: .bestand, laenge: 1000, stuecke: [940])])
        let b = MaterialZuschnitt.bilanz(z, mindestrest: 100)
        XCTAssertEqual(b.gesamt, 2000)
        XCTAssertEqual(b.verschnitt, 66, accuracy: 1e-9)
        XCTAssertEqual(MaterialZuschnitt.prozent(z, mindestrest: 100) ?? 0, 3.3, accuracy: 1e-9)
        // Platte 1.000 × 500 mit einem Stück 400 × 500 und einem neuen Rest 590 × 500: Verschnitt 10 × 500
        let p = BestandZuschnitt(
            stockID: "platte", benennung: "Platte", istPlatte: true, platteB: 1000, platteH: 500,
            quellen: [ZuschnittQuelle(index: 0, art: .kaufen, b: 1000, h: 500,
                                      flaechen: [ZuschnittFlaeche(b: 400, h: 500)],
                                      resteNeu: [ZuschnittFlaeche(b: 590, h: 500, x: 410)])])
        XCTAssertEqual(MaterialZuschnitt.prozent(p, mindestrest: 100) ?? 0, 1, accuracy: 1e-9)
        let k = MaterialDaten(bom: BillOfMaterials(run: 1, lines: [], cuts: [], totals: BOMTotals(kg: 0, preis: nil, positionen: 0, teile: 0)),
                              bestand: BOMBestand(run: 1, zuschnitte: [z, p], einkaufsliste: [])).kennzahlen
        XCTAssertEqual(k.verschnittStangen ?? 0, 3.3, accuracy: 1e-9)
        XCTAssertEqual(k.verschnittPlatten ?? 0, 1, accuracy: 1e-9)
        XCTAssertEqual(k.verschnittText, "3,3 % · 1,0 %")
        XCTAssertEqual(k.zuschnittText, "2 Stangen · 1 Platte")
    }

    func testBerichtLiestDieselbenDaten() throws {
        let m = try bomMitBestand()
        let q = ExportQuellen(kopf: ExportKopf(projekt: "Kugelschieber"), bom: m.bom, bestand: m.bestand)
        let d = MaterialDaten(bom: m.bom, bestand: m.bestand)
        XCTAssertEqual(q.material, d)
        // Einkaufsliste und Zuschnitt als Seiten aus derselben Quelle
        let vorlage = ExportVorlage(name: "t", bausteine: [ExportBausteinWahl(art: .einkaufsliste),
                                                             ExportBausteinWahl(art: .zuschnitt),
                                                             ExportBausteinWahl(art: .stueckliste)])
        let doc = ExportBauer.dokument(vorlage, q)
        XCTAssertEqual(Set(doc.bausteinSeiten.map(\.art)), [.einkaufsliste, .zuschnitt, .stueckliste])
        XCTAssertFalse(doc.hinweise.contains { $0.contains("ohne Bestandsabgleich") })
        // Zukaufteile kommen auch im Bericht auf die Einkaufsliste
        let z = try bomZukauf()
        let qz = ExportQuellen(kopf: ExportKopf(projekt: "Roller"), bom: z.bom, bestand: z.bestand)
        let dz = ExportBauer.dokument(ExportVorlage(name: "t", bausteine: [ExportBausteinWahl(art: .einkaufsliste)]), qz)
        XCTAssertFalse(dz.hinweise.contains { $0.contains("ohne Bestandsabgleich") })
        XCTAssertEqual(qz.material.kennzahlen.einkaufSumme, 24.99)
        // Maße wie auf der Sägeliste, mit Gehrung nur im Druck
        var l = line(1, art: "rohr", stock: "r", laenge: 882, masse: "40 × 40 × 3")
        l.gehrung = [45, 45]
        XCTAssertEqual(MaterialText.masse(l), "40 × 40 × 3, L = 882 mm")
        XCTAssertEqual(ExportBauer.masseText(l), "40 × 40 × 3, L = 882 mm, Gehrung 45° / 45°")
        XCTAssertEqual(MaterialText.masse(line(2, art: "rohr", laenge: 175, masse: "175 mm")), "175 mm")
        XCTAssertEqual(ExportSpalte.alle(.stueckliste).first { $0.id == "anzahl" }?.titel, MaterialText.Spalte.anzahl)
    }

    func testEinkaufTextCSVUndAbhaken() throws {
        let m = try bomMitBestand()
        let z = try bomZukauf()
        var d = MaterialDaten(bom: m.bom, bestand: m.bestand)
        d.einkauf += MaterialDaten(bom: z.bom, bestand: z.bestand).einkauf
        XCTAssertEqual(d.einkauf.count, 4)
        var a = EinkaufAbgehakt()
        a.umschalten(d.einkauf[0])
        XCTAssertTrue(a.abgehakt(d.einkauf[0]))
        XCTAssertEqual(a.offen(d.einkauf).count, 3)
        let text = MaterialText.einkaufText(d.einkauf, projekt: "Kugelschieber", abgehakt: a.schluessel)
        XCTAssertTrue(text.contains("Lagerware"))
        XCTAssertTrue(text.contains("Zukaufteile"))
        XCTAssertTrue(text.contains("- [x] 1 × Stange 1.000 mm"))
        XCTAssertTrue(text.contains("- [ ] 1 × Stück: ALUTEC"))
        let csv = MaterialText.einkaufCSV(d.einkauf)
        XCTAssertTrue(csv.hasPrefix("\u{FEFF}Gruppe;Menge;Einheit;Benennung"))
        XCTAssertTrue(csv.contains("\r\nZukaufteile;1;Stück;ALUTEC"))
        XCTAssertTrue(csv.contains("\r\n;;;Summe;;;29,73;;;;\r\n"))
        // Ändert sich die Menge, ist die Zeile wieder offen
        var anders = d.einkauf
        anders[0].position.menge = 2
        XCTAssertFalse(a.bereinigt(anders).abgehakt(anders[0]))
        a.setze(d.einkauf, true)
        XCTAssertTrue(a.offen(d.einkauf).isEmpty)
        XCTAssertNotEqual(EinkaufAbgehakt.defaultsKey(URL(fileURLWithPath: "/a")),
                          EinkaufAbgehakt.defaultsKey(URL(fileURLWithPath: "/b")))
    }

    func testAuswahlUndSuche() throws {
        let m = try bomMitBestand()
        let d = MaterialDaten(bom: m.bom, bestand: m.bestand)
        let p = try XCTUnwrap(d.positionen.first { !$0.teile.isEmpty })
        XCTAssertEqual(d.positionen(mit: Set(p.teile)), [p.pos])
        XCTAssertEqual(d.position(enthaelt: p.teile[0])?.pos, p.pos)
        XCTAssertTrue(d.positionen(mit: []).isEmpty)
        XCTAssertTrue(p.passt(""))
        XCTAssertTrue(d.positionen.contains { $0.passt("alfer 12") })
        XCTAssertFalse(d.positionen.contains { $0.passt("gibtsnicht") })
    }

    // MARK: Schnellansichten

    func testSchnellansichtenAufUndZu() {
        var z = SchnellansichtenZustand()
        let alle = Schnellansicht.allCases
        XCTAssertTrue(z.offene(alle).isEmpty)
        z.umschalten(.stueckliste)
        XCTAssertEqual(z.offene(alle), [.stueckliste])
        z.umschalten(.zuschnitt)
        XCTAssertEqual(z.offene(alle), [.stueckliste, .zuschnitt])  // mehrere zugleich, feste Reihenfolge
        XCTAssertEqual(z.eingeklappte(alle), [.druck])
        z.umschalten(.stueckliste)
        XCTAssertEqual(z.offene(alle), [.zuschnitt])  // einzeln zu
        z.oeffne(.stueckliste)
        z.alleZu()
        XCTAssertTrue(z.offene(alle).isEmpty)
        XCTAssertEqual(z.zuletzt, [.stueckliste, .zuschnitt])
        z.allesUmschalten(alle)  // das zuletzt Offene wieder auf
        XCTAssertEqual(z.offene(alle), [.stueckliste, .zuschnitt])
        z.allesUmschalten(alle)
        XCTAssertTrue(z.offen.isEmpty)
        // Ohne Druckteile ist „Druck“ nicht sichtbar, auch wenn sie offen gemerkt ist
        z.alleAuf(alle)
        XCTAssertEqual(z.offene([.stueckliste, .zuschnitt]), [.stueckliste, .zuschnitt])
        // Nichts gemerkt: Umschalten öffnet die Stückliste
        var leer = SchnellansichtenZustand(zuletzt: [.druck])
        leer.allesUmschalten([.stueckliste, .zuschnitt])
        XCTAssertEqual(leer.offene(alle), [.stueckliste])
    }

    func testSchnellansichtenHoehen() {
        var z = SchnellansichtenZustand(offen: [.stueckliste, .zuschnitt])
        z.setzeHoehe(.stueckliste, 300)
        z.setzeHoehe(.zuschnitt, 100)
        let alle = Schnellansicht.allCases
        // genug Platz: wie eingestellt
        XCTAssertEqual(z.verteilt(alle, platz: 1000), [.stueckliste: 300, .zuschnitt: 100])
        // zu wenig: im Verhältnis gekürzt (300 : 100 bei 600 Punkten)
        let halb = z.verteilt(alle, platz: 300)
        XCTAssertEqual(halb[.stueckliste] ?? 0, 225, accuracy: 1e-9)
        XCTAssertEqual(halb[.zuschnitt] ?? 0, 75, accuracy: 1e-9)
        // fiele eine unter die Mindesthöhe, hält sie die, der Rest teilt sich den Platz
        let k = z.verteilt(alle, platz: 200)
        XCTAssertEqual((k[.stueckliste] ?? 0) + (k[.zuschnitt] ?? 0), 200, accuracy: 1e-6)
        XCTAssertEqual(k[.zuschnitt] ?? 0, SchnellansichtenZustand.mindestHoehe, accuracy: 1e-9)
        XCTAssertEqual(k[.stueckliste] ?? 0, 200 - SchnellansichtenZustand.mindestHoehe, accuracy: 1e-9)
        // gar kein Platz: gleich verteilt
        XCTAssertEqual(z.verteilt(alle, platz: 100)[.stueckliste] ?? 0, 50, accuracy: 1e-9)
        // Grenzen beim Setzen
        z.setzeHoehe(.druck, 5)
        XCTAssertEqual(z.hoehe(.druck), SchnellansichtenZustand.mindestHoehe)
        z.setzeHoehe(.druck, 5000)
        XCTAssertEqual(z.hoehe(.druck), SchnellansichtenZustand.hoechstHoehe)
        XCTAssertEqual(SchnellansichtenZustand().hoehe(.stueckliste), Schnellansicht.stueckliste.standardHoehe)
    }

    func testSchnellansichtenZiehen() {
        var z = SchnellansichtenZustand(offen: [.stueckliste, .zuschnitt])
        z.setzeHoehe(.stueckliste, 200)
        z.setzeHoehe(.zuschnitt, 150)
        let alle = Schnellansicht.allCases
        let start = z.verteilt(alle, platz: 800)
        // Griff über der ersten: nach oben ziehen vergrößert sie gegen den Viewport, die zweite bleibt
        z.ziehe(.stueckliste, dy: -100, start: start, sichtbar: alle, platz: 800)
        XCTAssertEqual(z.hoehe(.stueckliste), 300)
        XCTAssertEqual(z.hoehe(.zuschnitt), 150)
        // nicht über den Platz hinaus
        z.ziehe(.stueckliste, dy: -2000, start: start, sichtbar: alle, platz: 800)
        XCTAssertEqual(z.hoehe(.stueckliste), 650)
        // Griff zwischen beiden: Höhe wandert, die Summe bleibt
        z.ziehe(.zuschnitt, dy: -50, start: start, sichtbar: alle, platz: 800)
        XCTAssertEqual(z.hoehe(.zuschnitt), 200)
        XCTAssertEqual(z.hoehe(.stueckliste), 150)
        z.ziehe(.zuschnitt, dy: 500, start: start, sichtbar: alle, platz: 800)
        XCTAssertEqual(z.hoehe(.zuschnitt), SchnellansichtenZustand.mindestHoehe)
        XCTAssertEqual(z.hoehe(.stueckliste), 350 - SchnellansichtenZustand.mindestHoehe)
    }

    func testSchnellansichtenGemerkt() {
        var z = SchnellansichtenZustand(offen: [.zuschnitt])
        z.setzeHoehe(.zuschnitt, 222)
        z.alleZu()
        let wieder = SchnellansichtenZustand.aus(z.daten)
        XCTAssertEqual(wieder, z)
        XCTAssertEqual(wieder?.zuletzt, [.zuschnitt])
        XCTAssertEqual(wieder?.hoehe(.zuschnitt), 222)
        XCTAssertNil(SchnellansichtenZustand.aus(nil))
        XCTAssertNil(SchnellansichtenZustand.aus(Data("kaputt".utf8)))
    }
}
