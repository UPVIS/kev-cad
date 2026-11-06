import KevCADCore
import SwiftUI
import simd

/// Eigenschaften der Auswahl in der Werkstatt: Name (Stift oder Doppelklick benennt um), Werte des Teils, Isolieren und
/// Zeigen, darunter die Maße des Modells (`param()` in model.py) als Felder mit „vorher“. Ein geänderter Wert landet in
/// model.py, der nächste Lauf zeigt ihn.
struct Eigenschaften: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var verlauf: ParameterVerlauf
    @State private var nameBearbeiten = false
    @State private var neuerName = ""
    @FocusState private var nameFokus: Bool

    private var teile: [PartNode] {
        let ids = Set(model.selectedPartIDs)
        return model.parts.filter { ids.contains($0.id) }
    }

    private var nav: NavigationActions? { model.actions as? NavigationActions }

    var body: some View {
        VStack(alignment: .leading, spacing: GA.l) {
            if let teil = teile.first, teile.count == 1 {
                kopf(teil.name, umbenennbar: true, id: teil.id, gruppe: false)
                einzeln(teil)
                knoepfe
            } else if !teile.isEmpty {
                kopf(gemeinsameGruppe ?? KevFormat.count(teile.count, one: "Teil", many: "Teile"),
                     umbenennbar: gemeinsameGruppe != nil, id: gemeinsameGruppe ?? "", gruppe: true)
                mehrere(teile)
                knoepfe
            } else if model.project != nil {
                kopf(session.projektTitel, umbenennbar: false, id: "", gruppe: false)
                ganzesModell
            }
            parameter
        }
    }

    // MARK: Kopf

    private func kopf(_ titel: String, umbenennbar: Bool, id: String, gruppe: Bool) -> some View {
        HStack(spacing: GA.s) {
            if nameBearbeiten {
                TextField("Name", text: $neuerName)
                    .textFieldStyle(.plain)
                    .font(GS.name)
                    .foregroundStyle(GF.kreide)
                    .focused($nameFokus)
                    .onSubmit { benennen(id, gruppe: gruppe) }
                    .onExitCommand { nameBearbeiten = false }
                    .onChange(of: nameFokus) { _, f in if !f && nameBearbeiten { benennen(id, gruppe: gruppe) } }
            } else {
                Text(titel)
                    .font(GS.name)
                    .foregroundStyle(GF.kreide)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .onTapGesture(count: 2) { if umbenennbar { beginnen(titel) } }
                if umbenennbar {
                    Button { beginnen(titel) } label: { Image(systemName: "pencil") }
                        .buttonStyle(KevKnopfStil(form: .leise, farbe: GF.rauch))
                        .help("Umbenennen")
                        .accessibilityLabel("\(titel) umbenennen")
                }
            }
        }
        .accessibilityAddTraits(.isHeader)
        .onChange(of: model.selectedPartIDs) { _, _ in nameBearbeiten = false }
    }

    private func beginnen(_ titel: String) {
        neuerName = titel
        nameBearbeiten = true
        DispatchQueue.main.async { nameFokus = true }
    }

    private func benennen(_ id: String, gruppe: Bool) {
        let neu = neuerName.trimmingCharacters(in: .whitespacesAndNewlines)
        nameBearbeiten = false
        guard !neu.isEmpty, !id.isEmpty else { return }
        let alt = id.split(separator: "/").last.map(String.init) ?? id
        guard neu != alt else { return }
        session.teilBenennen(id, gruppe: gruppe, neu: neu)
    }

    /// Gruppe, deren Teile genau die Auswahl sind ("Schiebebügel").
    private var gemeinsameGruppe: String? {
        let ids = Set(model.selectedPartIDs)
        guard ids.count > 1 else { return nil }
        func suche(_ knoten: [PartTreeNode]) -> String? {
            for k in knoten {
                if k.isGroup && Set(k.partIDs) == ids { return k.id }
                if let f = suche(k.children ?? []) { return f }
            }
            return nil
        }
        return suche(PartTree.build(model.parts))
    }

    // MARK: Werte

    @ViewBuilder
    private func einzeln(_ t: PartNode) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let s = t.stock {
                EigenschaftsFeld(titel: "Lagerteil", wert: s.name, hilfe: s.id)
                if let l = s.laenge { EigenschaftsFeld(titel: "Länge", wert: Self.zahl(l), einheit: "mm") }
            } else if let z = t.zukauf {
                EigenschaftsFeld(titel: "Zukaufteil", wert: [z.hersteller, z.mpn].compactMap { $0 }.joined(separator: " ")
                    .isEmpty ? z.id : [z.hersteller, z.mpn].compactMap { $0 }.joined(separator: " "), hilfe: z.id)
            }
            EigenschaftsFeld(titel: "Maße", wert: Self.masse(t.bboxMax - t.bboxMin), einheit: "mm")
            if let m = t.material { EigenschaftsFeld(titel: "Werkstoff", wert: werkstoff(m)) }
            if let kg = t.mass { EigenschaftsFeld(titel: "Masse", wert: Self.kg(kg), einheit: "kg") }
            if t.inventarFehlt {
                Text("Nicht aus dem Inventar: Lagerteil, Zukaufteil oder Druckteil daraus machen.")
                    .font(GS.klein)
                    .foregroundStyle(GF.befund)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private func mehrere(_ t: [PartNode]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            EigenschaftsFeld(titel: "Teile", wert: KevFormat.integer(t.count))
            if let b = Self.huelle(t) { EigenschaftsFeld(titel: "Maße", wert: Self.masse(b), einheit: "mm") }
            let kg = t.compactMap(\.mass).reduce(0, +)
            if kg > 0 { EigenschaftsFeld(titel: "Masse", wert: Self.kg(kg), einheit: "kg") }
        }
    }

    @ViewBuilder
    private var ganzesModell: some View {
        VStack(alignment: .leading, spacing: 6) {
            EigenschaftsFeld(titel: "Teile", wert: KevFormat.integer(model.parts.count))
            if let b = model.sceneBounds {
                EigenschaftsFeld(titel: "Maße", wert: Self.masse(b.max - b.min), einheit: "mm")
            }
            if let bom = model.bom {
                // Ohne Werkstoffe (Nachbau, Skizze) kennt die Stückliste keine Masse: dann kein „0,00 kg“, wie bei der
                // Auswahl mehrerer Teile
                if bom.totals.kg > 0 { EigenschaftsFeld(titel: "Masse", wert: Self.kg(bom.totals.kg), einheit: "kg") }
                if let p = bom.totals.preis { EigenschaftsFeld(titel: "Kosten", wert: KevFormat.euro(p)) }
            }
        }
    }

    private var knoepfe: some View {
        HStack(spacing: GA.s) {
            Button("Isolieren") {
                if let nav { nav.toggleLocalView() } else { model.isolateSelection() }
            }
            .buttonStyle(KevKnopfStil(form: .breit))
            .help("Nur die Auswahl zeigen (/)")
            Button("Zeigen") { model.fitSelection() }
                .buttonStyle(KevKnopfStil(form: .breit))
                .help("Auswahl einpassen (F)")
        }
    }

    // MARK: Parameter

    @ViewBuilder
    private var parameter: some View {
        let namen = verlauf.namen
        if !namen.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                AbschnittTitel(titel: "Maße des Modells", zusatz: KevFormat.integer(namen.count))
                    .padding(.bottom, 2)
                ForEach(namen, id: \.self) { n in
                    if let w = verlauf.werte[n] {
                        EigenschaftsFeld(
                            titel: n, wert: Self.zahl(w),
                            vorher: verlauf.vorher[n].map { Self.zahl($0) },
                            hilfe: "param(\"\(n)\") in model.py") { text in
                                session.parameterSetzen(n, text: text)
                            }
                    }
                }
            }
        }
    }

    // MARK: Formate

    private func werkstoff(_ id: String) -> String {
        model.catalog?.materials.first { $0.id == id }?.name ?? id
    }

    static func zahl(_ v: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "de_DE")
        f.minimumFractionDigits = 0
        f.maximumFractionDigits = abs(v) >= 100 ? 1 : 2
        f.usesGroupingSeparator = false
        return f.string(from: NSNumber(value: v)) ?? String(v)
    }

    static func kg(_ v: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: "de_DE")
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = v >= 10 ? 1 : 2
        return f.string(from: NSNumber(value: v)) ?? String(v)
    }

    /// Mit schmalen Leerzeichen um „×“: drei Maße passen so ins schmale Feld der rechten Leiste, ohne in der Mitte
    /// abgeschnitten zu werden („266,9 ×…6,9 × 93,8“, 06.11.2026).
    static func masse(_ d: SIMD3<Float>) -> String {
        [d.x, d.y, d.z].map { zahl(Double(($0 * 10).rounded() / 10)) }.joined(separator: "\u{2009}×\u{2009}")
    }

    static func huelle(_ t: [PartNode]) -> SIMD3<Float>? {
        guard let erst = t.first else { return nil }
        var lo = erst.bboxMin, hi = erst.bboxMax
        for p in t.dropFirst() {
            lo = simd_min(lo, p.bboxMin)
            hi = simd_max(hi, p.bboxMax)
        }
        return hi - lo
    }
}
