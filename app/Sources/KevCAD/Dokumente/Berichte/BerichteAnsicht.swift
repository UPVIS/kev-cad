import KevCADCore
import SwiftUI

/// Berichte (Strang P6-A2): Stückliste, Teileliste, Einkaufsliste und Zuschnitt als druckfertige Vorschau. Gezeigt werden
/// genau die Seiten, die auch ins PDF und auf den Drucker gehen (dieselbe Zeichenfunktion). Von hier aus als PDF
/// sichern, drucken oder in den Export-Dialog.
struct BerichteAnsicht: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @ObservedObject var export: ExportStore
    @State private var bericht: ExportBausteinArt = .stueckliste
    @State private var format = ExportSeitenformat()
    @State private var dokument: ExportDokument?
    @State private var baut = false
    @State private var zoom: CGFloat = 1
    @State private var stand = 0

    init(model: AppModel) {
        self.model = model
        self.export = model.export
    }

    static let berichte: [ExportBausteinArt] = [.stueckliste, .teileliste, .einkaufsliste, .zuschnitt]

    private var vorlage: ExportVorlage {
        ExportVorlage(name: bericht.titel, format: format.papier, ausrichtung: format.ausrichtung,
                      bausteine: [ExportBausteinWahl(art: bericht)])
    }

    var body: some View {
        HStack(spacing: 0) {
            liste.frame(width: 230)
            Divider()
            VStack(spacing: 0) {
                leiste
                Divider()
                vorschau
            }
        }
        .frame(minWidth: 820, minHeight: 520)
        .task(id: aufbauSchluessel) { await neuBauen() }
    }

    /// Ändert sich, wenn die Seiten neu gesetzt werden müssen.
    private var aufbauSchluessel: String {
        "\(bericht.rawValue)|\(format.name)|\(model.bom?.run ?? 0)|\(model.bestandZustand.zuschnitt?.run ?? 0)|\(stand)"
    }

    private func neuBauen() async {
        guard let a = model.exportActions else { return }
        baut = true
        let d = await a.exportDokument(vorlage)
        dokument = d
        baut = false
    }

    private var liste: some View {
        List(selection: Binding(get: { bericht }, set: { if let b = $0 { bericht = b } })) {
            Section("Berichte") {
                ForEach(Self.berichte) { b in
                    Label {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(b.titel)
                            Text(b.beschreibung).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                    } icon: {
                        Image(systemName: b.symbol)
                    }
                    .tag(b)
                    .padding(.vertical, 2)
                }
            }
        }
        .listStyle(.sidebar)
    }

    private var leiste: some View {
        HStack(spacing: 12) {
            Picker("Format", selection: Binding(get: { format.papier }, set: { format.papier = $0 })) {
                ForEach(ExportPapier.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .fixedSize()
            Picker("Ausrichtung", selection: Binding(get: { format.ausrichtung }, set: { format.ausrichtung = $0 })) {
                Image(systemName: "rectangle.portrait").help("Hochformat").tag(ExportAusrichtung.hoch)
                Image(systemName: "rectangle").help("Querformat").tag(ExportAusrichtung.quer)
            }
            .pickerStyle(.segmented)
            .fixedSize()
            .labelsHidden()
            if let d = dokument {
                Text(KevFormat.count(d.seiten.count, one: "Seite", many: "Seiten"))
                    .foregroundStyle(.secondary).monospacedDigit()
            }
            if baut || export.laeuft != nil {
                ProgressView().controlSize(.small)
                if let l = export.laeuft { Text(l).foregroundStyle(.secondary).lineLimit(1) }
            }
            Spacer()
            Slider(value: $zoom, in: 0.5...2) { Text("Zoom") }
                .frame(width: 110)
                .help("Größe der Vorschau")
            Button {
                stand += 1
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("Neu setzen (Vorschaubilder und Daten frisch)")
            Button("Drucken …") { drucken() }
                .disabled(dokument?.seiten.isEmpty != false)
            Button("Als PDF sichern …") { sichern() }
                .disabled(dokument?.seiten.isEmpty != false)
            Button {
                ExportDialogFenster.zeige(session: session, model: model, vorauswahl: [bericht])
            } label: {
                Label("Exportieren …", systemImage: "square.and.arrow.up.on.square")
            }
            .help("Dokumente exportieren: Bausteine zusammenstellen (⇧⌘E)")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
    }

    @ViewBuilder
    private var vorschau: some View {
        if let d = dokument, !d.seiten.isEmpty {
            SeitenVorschau(dokument: d, zoom: zoom)
        } else if baut {
            ProgressView("Seiten werden gesetzt …").frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ContentUnavailableView("Keine Seiten", systemImage: "doc",
                                   description: Text("Erst model.py rechnen, dann entstehen Stückliste und Zuschnitt."))
        }
    }

    private func sichern() {
        Task { @MainActor in
            guard let url = await ExportDialogFenster.speicherOrt(model: model, name: "\(model.project?.name ?? "Kev CAD") – \(bericht.titel)")
            else { return }
            do {
                _ = try await model.exportActions?.exportPDF(vorlage, nach: url)
                NSWorkspace.shared.activateFileViewerSelecting([url])
            } catch {
                ExportDialogFenster.fehler(error)
            }
        }
    }

    private func drucken() {
        Task { @MainActor in
            do {
                _ = try await model.exportActions?.exportDrucken(vorlage)
            } catch {
                ExportDialogFenster.fehler(error)
            }
        }
    }
}

/// Seiten wie Papier auf grauem Grund, untereinander, mit Schatten und Seitenzahl.
struct SeitenVorschau: View {
    let dokument: ExportDokument
    var zoom: CGFloat = 1

    var body: some View {
        GeometryReader { geo in
            ScrollView([.vertical, .horizontal]) {
                LazyVStack(spacing: 22) {
                    ForEach(dokument.seiten.indices, id: \.self) { i in
                        let s = dokument.seiten[i]
                        let basis = min(geo.size.width - 80, 760) / 210  // Punkte je mm bei Zoom 1 (A4 hoch passt)
                        let k = max(1.2, basis) * zoom
                        VStack(spacing: 6) {
                            SeiteAnsicht(dokument: dokument, index: i)
                                .frame(width: s.groesse.width * k, height: s.groesse.height * k)
                                .background(Color.white)
                                .shadow(color: .black.opacity(0.22), radius: 6, y: 2)
                            Text("Seite \(i + 1) von \(dokument.seiten.count) · \(s.titel) · \(s.formatName)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(28)
                .frame(minWidth: geo.size.width)
            }
            .background(Color(nsColor: .underPageBackgroundColor))
        }
    }
}

/// Eine Seite des Dokuments am Bildschirm (dieselbe Zeichenfunktion wie das PDF).
struct SeiteAnsicht: View {
    let dokument: ExportDokument
    let index: Int

    var body: some View {
        Canvas(rendersAsynchronously: true) { ctx, size in
            ctx.withCGContext { cg in
                let s = dokument.seiten[index]
                let k = size.width / s.punkte.width
                // Canvas hat y nach unten; die Seite zeichnet wie ein PDF mit Ursprung links unten
                cg.translateBy(x: 0, y: size.height)
                cg.scaleBy(x: k, y: -k)
                cg.setFillColor(CGColor(gray: 1, alpha: 1))
                cg.fill(CGRect(origin: .zero, size: s.punkte))
                dokument.zeichne(index, in: cg)
            }
        }
        .accessibilityLabel("Seite \(index + 1)")
    }
}
