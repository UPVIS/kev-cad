import KevCADCore
import SwiftUI

/// Musterseite aller Grundbausteine (nur zum Prüfen der Gestaltung): Start mit `KEVCAD_MUSTER=1` zeigt sie statt der
/// Arbeitsfläche. Kevin bekommt sie nie zu sehen.
struct GestaltungMuster: View {
    static var an: Bool { ProcessInfo.processInfo.environment["KEVCAD_MUSTER"] == "1" }

    @State private var modus = "fokus"
    @State private var offen = true
    @State private var gewaehlt = "Querstrebe"
    @State private var bearbeiten: String?
    @State private var griff = "1040"
    @State private var spricht = false

    var body: some View {
        ZStack {
            GraphitGrund()
            HStack(alignment: .top, spacing: 28) {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(spacing: 18) {
                        Text("Kamerawagen").font(GS.projekt).foregroundStyle(GF.kreide)
                        ModusUmschalter(
                            optionen: [ModusUmschalter<String>.Option(wert: "fokus", titel: "Fokus", hilfe: "Fokus (⌘1)"),
                                       ModusUmschalter<String>.Option(wert: "werkstatt", titel: "Werkstatt",
                                                                      hilfe: "Werkstatt (⌘2)")],
                            auswahl: modus) { modus = $0 }
                    }
                    HStack(spacing: 8) {
                        SymbolKnopf(symbol: "camera", titel: "Bildschirmfoto", taste: "⌥⌘S") {}
                        AufnahmeKnopf(laeuft: false) {}
                        SymbolKnopf(symbol: "ruler", titel: "Messen", taste: "M", an: true) {}
                        SymbolKnopf(symbol: "scope", titel: "Isolieren", taste: "/") {}
                        SymbolKnopf(symbol: "rectangle.righthalf.inset.filled", titel: "An den Rand", taste: "⌃⌥→") {}
                    }
                    HStack(spacing: 10) {
                        Button {} label: { Label("Ordner öffnen …", systemImage: "folder") }
                            .buttonStyle(KevKnopfStil(form: .text))
                        Button {} label: { Label("Wegschieben", systemImage: "chevron.down") }
                            .buttonStyle(KevKnopfStil(form: .text))
                    }
                    VStack(alignment: .leading, spacing: 0) {
                        AbschnittTitel(titel: "Objekte", zusatz: "84")
                            .padding(.bottom, 6)
                        GliederungsZeile(titel: "Rahmen", anzahl: 4, gruppe: true)
                        GliederungsZeile(titel: "Lenkrollen", anzahl: 4, gruppe: true, befund: true)
                        GliederungsZeile(titel: "Schiebebügel", anzahl: 7, gruppe: true, offen: offen,
                                         aufklappen: { withAnimation(GB.kurz) { offen.toggle() } })
                        if offen {
                            ForEach(["Stütze links", "Querstrebe", "Griffrohr Ø 25"], id: \.self) { n in
                                GliederungsZeile(
                                    titel: n, ebene: 1, gewaehlt: gewaehlt == n, markiert: n == "Griffrohr Ø 25",
                                    bearbeiten: bearbeiten == n, waehlen: { _ in gewaehlt = n },
                                    umbenennenBeginnen: { bearbeiten = n }, umbenennen: { _ in bearbeiten = nil })
                            }
                        }
                    }
                    .frame(width: 232)
                    HStack(spacing: 22) {
                        TastenHinweis(tasten: ["↩"], text: "fertig")
                        TastenHinweis(tasten: ["D"], text: "halten und zeichnen")
                        TastenHinweis(tasten: ["⌃", "⌥", "→"], text: "an den Rand")
                        TastenHinweis(tasten: ["esc"], text: "verwerfen")
                    }
                }
                .frame(width: 520, alignment: .leading)

                VStack(alignment: .leading, spacing: 14) {
                    Text("Querstrebe").font(GS.name).foregroundStyle(GF.kreide)
                    EigenschaftsFeld(titel: "Profil", wert: "30 × 30 Nut 8")
                    EigenschaftsFeld(titel: "Länge", wert: "400", einheit: "mm")
                    EigenschaftsFeld(titel: "Griffhöhe", wert: griff, einheit: "mm", vorher: "960") { griff = $0 }
                    EigenschaftsFeld(titel: "Masse", wert: "0,34", einheit: "kg")
                    HStack(spacing: 8) {
                        Button("Isolieren") {}.buttonStyle(KevKnopfStil(form: .breit))
                        Button("Zeigen") {}.buttonStyle(KevKnopfStil(form: .breit))
                    }
                    KachelRahmen(
                        nummer: 2, titel: "Zeichnung", untertitel: "Blatt 1 von 2, eben erstellt", aktiv: true,
                        vergroessern: {}, schliessen: {}, zusatz: { EmptyView() },
                        inhalt: {
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(GF.papier)
                                .padding(12)
                        })
                        .frame(height: 220)
                    Statuszeile(spricht: spricht, gesagt: "Zeig mir die Zeichnung", agent: "Liegt rechts",
                                stand: "Lauf 12 · 84 Teile", standFarbe: .green) { spricht.toggle() }
                }
                .frame(width: 520)
            }
            .padding(36)
            Sprechrahmen(an: spricht)
        }
        .frame(minWidth: 1180, minHeight: 760)
        .preferredColorScheme(.dark)
    }
}
