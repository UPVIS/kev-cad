import KevCADCore
import SwiftUI

/// Blatt „Erfassen“: Lagerteil aus dem Katalog wählen (Suche) und eintragen, was da ist, z. B. „2 ganze Stangen,
/// Reste 430, 610 und 180 mm“. Für ein schon gewähltes Lagerteil nur die Mengen bzw. nur Reste.
struct BestandErfassenSheet: View {
    @ObservedObject var model: AppModel
    let anfrage: ErfassenAnfrage
    @Environment(\.dismiss) private var dismiss

    @State private var stockID: String?
    @State private var suche = ""
    @State private var ganze = ""
    @State private var laenge = ""
    @State private var b = ""
    @State private var h = ""
    @State private var reste = ""
    @State private var ort = ""
    @State private var stueck = ""
    @State private var stueckLaenge = ""

    private var item: CatalogItem? { stockID.flatMap { model.catalog?.item($0) } }
    private var form: BestandForm { stockID.map(model.bestandForm) ?? .stange }
    private var vorher: BestandPosten? { stockID.flatMap { model.bestandZustand.bestand?.posten($0) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(titel)
                .font(.title3.weight(.semibold))
                .padding([.horizontal, .top], 20)
                .padding(.bottom, 12)
            if anfrage.stockID == nil {
                auswahl
                    .frame(height: 230)
                Divider()
            }
            if let id = stockID {
                eingabe(id)
            } else {
                Text("Wähle oben das Lagerteil aus dem Katalog.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 120)
            }
            Divider()
            fuss
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
        }
        .frame(width: 520)
        .onAppear {
            stockID = anfrage.stockID
            if model.catalog == nil { model.catalogActions?.requestCatalog(query: nil, art: nil) }
            vorbelegen()
        }
        .onChange(of: stockID) { _, _ in vorbelegen() }
    }

    private var titel: String {
        if anfrage.nurReste, let id = stockID { return "Reste erfassen: \(model.lagerteilName(id))" }
        if let id = anfrage.stockID { return "In den Bestand: \(model.lagerteilName(id))" }
        return "Lagerteil in den Bestand aufnehmen"
    }

    // MARK: Auswahl aus dem Katalog

    private var treffer: [CatalogItem] {
        guard let catalog = model.catalog else { return [] }
        let t = CatalogSearch.tokens(suche)
        let imModell = Set(model.bom?.lines.compactMap(\.stockID) ?? [])
        return CatalogSearch.sorted(catalog.items)
            // erste Stufe: nur Stangenware, Platten und Stückgut (Zukaufteile und Kameras folgen später)
            .filter { !$0.vorgeschlagen && CatalogSchema.art($0.art).isKnown && CatalogSearch.matches($0, tokens: t, material: catalog.material($0.material)) }
            .sorted { imModell.contains($0.id) && !imModell.contains($1.id) }
    }

    @ViewBuilder
    private var auswahl: some View {
        VStack(spacing: 8) {
            TextField("Suchen: Name, Maß, Norm, Material", text: $suche)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal, 20)
            if model.catalog == nil {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Lagerkatalog wird geladen …").foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let imModell = Set(model.bom?.lines.compactMap(\.stockID) ?? [])
                List(treffer, selection: $stockID) { item in
                    HStack(spacing: 8) {
                        ArtTile(art: item.art, size: 20)
                        Text(item.name).lineLimit(1)
                        Spacer(minLength: 4)
                        if imModell.contains(item.id) { Badge(text: "im Modell", color: .accentColor) }
                        if let p = model.bestandZustand.bestand?.posten(item.id) {
                            Text(p.zusammenfassung).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    .tag(item.id)
                }
                .listStyle(.bordered)
                .padding(.horizontal, 20)
                .overlay {
                    if treffer.isEmpty { ContentUnavailableView.search(text: suche) }
                }
            }
        }
        .padding(.bottom, 12)
    }

    // MARK: Eingabe

    private func eingabe(_ id: String) -> some View {
        Form {
            if let p = vorher {
                LabeledContent("Schon im Bestand", value: p.zusammenfassung)
            }
            switch form {
            case .stange:
                if !anfrage.nurReste {
                    TextField("Ganze Stangen", text: $ganze, prompt: Text("0"))
                    TextField("Länge je Stange (mm)", text: $laenge)
                        .disabled((vorher?.ganzeAnzahl ?? 0) > 0)
                        .help((vorher?.ganzeAnzahl ?? 0) > 0
                            ? "Die Länge der ganzen Stangen steht schon fest; ändern über „Bearbeiten …“" : "")
                }
                TextField("Reste (mm)", text: $reste, prompt: Text("z. B. 430, 610, 180"))
                    .help("Längen mit Komma, Leerzeichen oder „und“ trennen; jeder Rest bekommt eine eigene Kennung")
                TextField("Ort", text: $ort, prompt: Text("optional, z. B. Regal 2"))
            case .platte:
                if !anfrage.nurReste {
                    TextField("Ganze Platten", text: $ganze, prompt: Text("0"))
                    HStack {
                        TextField("Format (mm)", text: $b, prompt: Text("Breite"))
                        Text("×")
                        TextField("", text: $h, prompt: Text("Höhe")).labelsHidden()
                    }
                }
                TextField("Reste (mm)", text: $reste, prompt: Text("z. B. 600 × 400, 300 × 200"))
                    .help("Breite × Höhe, mehrere mit Komma oder Semikolon trennen")
                TextField("Ort", text: $ort, prompt: Text("optional, z. B. Plattenregal"))
            case .stueckgut:
                TextField("Anzahl", text: $stueck, prompt: Text("0"))
                if item?.stueckMitLaenge ?? (vorher?.stueck.contains { $0.laenge != nil } ?? false) {
                    TextField("Länge (mm)", text: $stueckLaenge, prompt: Text("z. B. 16"))
                }
            }
            if let fehler = fehlerText {
                Label(fehler, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }
        }
        .formStyle(.grouped)
        .scrollDisabled(true)
        .frame(minHeight: 150)
    }

    // MARK: Fuß

    private var fuss: some View {
        HStack {
            if let e = erfassung, !e.leer, let id = stockID {
                Text(e.grund(name: model.lagerteilName(id)))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer(minLength: 8)
            Button("Abbrechen", role: .cancel) { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button("In den Bestand") { eintragen() }
                .keyboardShortcut(.defaultAction)
                .disabled(erfassung?.leer ?? true || fehlerText != nil || model.bestandActions == nil)
        }
    }

    private func vorbelegen() {
        guard let id = stockID else { return }
        let p = vorher
        let z = model.bestandZustand.zuschnitt?.zuschnitt(id)
        ganze = anfrage.nurReste || p != nil ? "" : (form == .stueckgut ? "" : "1")
        laenge = (p?.ganzeLaenge ?? item?.stangenlaenge ?? z?.stangenlaenge).map(KevFormat.input) ?? ""
        b = (p?.ganzeB ?? item?.plattenformat?.b ?? z?.platteB).map(KevFormat.input) ?? ""
        h = (p?.ganzeH ?? item?.plattenformat?.h ?? z?.platteH).map(KevFormat.input) ?? ""
        if form == .stueckgut {
            // Schrauben: Länge aus der Stückliste vorschlagen, Menge wie im Modell
            let lines = model.bom?.lines.filter { $0.stockID == id } ?? []
            stueck = lines.isEmpty ? "" : String(lines.reduce(0) { $0 + $1.anzahl })
            stueckLaenge = lines.first.flatMap(GebautVorschau.schraubenLaenge).map(KevFormat.input) ?? ""
        }
    }

    private func zahl(_ text: String) -> Int? {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return 0 }
        guard let v = KevFormat.parseNumber(t), v >= 0, v == v.rounded() else { return nil }
        return Int(v)
    }

    private var fehlerText: String? {
        guard stockID != nil else { return nil }
        if zahl(ganze) == nil || zahl(stueck) == nil { return "Anzahl als ganze Zahl angeben." }
        let r = reste.trimmingCharacters(in: .whitespaces)
        if !r.isEmpty {
            if form == .stange, BestandText.laengen(r) == nil { return "Reste als Längen in mm angeben, z. B. 430, 610." }
            if form == .platte, BestandText.rechtecke(r) == nil { return "Reste als Breite × Höhe angeben, z. B. 600 × 400." }
        }
        if (zahl(ganze) ?? 0) > 0 {
            if form == .stange, KevFormat.parseNumber(laenge) == nil { return "Länge der ganzen Stangen fehlt." }
            if form == .platte, KevFormat.parseNumber(b) == nil || KevFormat.parseNumber(h) == nil {
                return "Format der ganzen Platten fehlt."
            }
        }
        return nil
    }

    private var erfassung: BestandErfassung? {
        guard stockID != nil, fehlerText == nil else { return nil }
        let r = reste.trimmingCharacters(in: .whitespaces)
        return BestandErfassung(
            form: form, ganze: zahl(ganze) ?? 0, laenge: KevFormat.parseNumber(laenge), b: KevFormat.parseNumber(b),
            h: KevFormat.parseNumber(h),
            resteLaengen: form == .stange && !r.isEmpty ? BestandText.laengen(r) ?? [] : [],
            resteFlaechen: form == .platte && !r.isEmpty
                ? (BestandText.rechtecke(r) ?? []).map { ZuschnittFlaeche(b: $0.b, h: $0.h) } : [],
            ort: ort, stueck: zahl(stueck) ?? 0, stueckLaenge: KevFormat.parseNumber(stueckLaenge))
    }

    private func eintragen() {
        guard let id = stockID, let e = erfassung, !e.leer else { return }
        model.bestandActions?.saveBestandPosten(
            id: id, posten: e.posten(vorher: vorher?.json, bestand: model.bestandZustand.bestand),
            grund: e.grund(name: model.lagerteilName(id)))
        BestandUI.shared.auswahl = id
        dismiss()
    }
}
