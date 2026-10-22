import Foundation

// Druckvorschau im Bereich „Material“: Die Kennzahlen der Druckteile (Seitenleiste, Übersicht, Schnellansicht) kommen,
// sobald eine Vorschau da ist, aus ihr statt aus der Stückliste. Die Stückliste rechnet Vollkörper mal Dichte; die
// Vorschau kennt Wände, Füllung und Stützen, dazu Zeit, Platten und Kosten samt Strom.

extension MaterialDaten {
    public mutating func druckvorschauEinrechnen(_ v: Druckvorschau?) {
        // Nur die Vorschau desselben Laufs (wie Filament und Einkaufsliste): direkt nach einem neuen Lauf zeigte die
        // Übersicht sonst noch die alte Vorschau, die Einkaufsliste schon die Stückliste (Strang „Feinschliff 2“)
        guard let v, !v.istLeer, !hatStueckliste || v.run == run else { return }
        var k = kennzahlen
        k.druckZeitS = v.summe.zeitMitWechselS
        k.druckPlatten = v.summe.platten
        k.druckStand = v.stand
        if v.summe.gramm > 0 { k.druckGramm = v.summe.gramm }
        if let kosten = v.summe.kosten { k.druckPreis = kosten }
        if k.druckteile == 0 { k.druckteile = v.stueck }
        kennzahlen = k
    }
}
