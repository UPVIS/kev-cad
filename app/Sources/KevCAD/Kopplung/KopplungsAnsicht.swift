import CoreImage
import CoreImage.CIFilterBuiltins
import KevCADCore
import SwiftUI
#if os(iOS)
import VisionKit
#endif

// I-2b, I-3b (PLAN-IPAD.md): Kopplung von Mac und iPad in der Oberfläche. Am Mac zeigt das Fenster „iPad koppeln“ den
// QR-Code und die gekoppelten iPads; auf dem iPad scannt ein Blatt den Code oder fügt ihn aus der Zwischenablage ein
// (Universal Clipboard: am Mac „Code kopieren“). Zustand: `AppModel.kopplung`, Aktionen: `KopplungsActions`.

/// QR-Code als Bild (CoreImage, ganzzahlig vergrößert, damit die Module scharf bleiben).
enum QRBild {
    static func erzeugen(_ text: String, kante: CGFloat) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let bild = filter.outputImage, bild.extent.width > 0 else { return nil }
        let faktor = max(1, (kante / bild.extent.width).rounded(.down))
        let gross = bild.transformed(by: CGAffineTransform(scaleX: faktor, y: faktor))
        return CIContext().createCGImage(gross, from: gross.extent)
    }
}

#if os(macOS)
/// Fenster „iPad koppeln“ (Ablage › iPad koppeln …): neuer Code beim Öffnen, Liste der gekoppelten iPads.
struct KopplungsFenster: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?
    @State private var jetzt = Date()
    private let takt = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: GA.l) {
            Text("iPad koppeln").font(GS.karteTitel).foregroundStyle(GF.kreide)
            HStack(alignment: .top, spacing: GA.xl) {
                codeFlaeche
                anleitung
            }
            Rectangle().fill(GF.linie).frame(height: 1)
            geraeteListe
            Text(kopplung.eingangPort.map { "Das iPad erreicht diesen Mac über Port \($0)." }
                    ?? "Ohne gekoppeltes iPad ist kein Port offen.")
                .font(GS.winzig).foregroundStyle(GF.rauch)
        }
        .padding(GA.xl)
        .frame(width: 600)
        .background(GF.tief)
        .onAppear { aktionen?.ipadKoppeln() }
        .onDisappear { aktionen?.ipadKopplungSchliessen() }
        .onReceive(takt) { jetzt = $0 }
    }

    @ViewBuilder private var codeFlaeche: some View {
        let kante: CGFloat = 220
        ZStack {
            RoundedRectangle(cornerRadius: 14).fill(Color.white)
            if let code = kopplung.code, let text = try? code.text(), code.bis > jetzt,
                let bild = QRBild.erzeugen(text, kante: kante * 2)
            {
                Image(decorative: bild, scale: 2).interpolation(.none).resizable().frame(width: kante - 24, height: kante - 24)
            } else {
                Text("Kein gültiger Code").font(GS.text).foregroundStyle(Color.gray)
            }
        }
        .frame(width: kante, height: kante)
        .accessibilityLabel("QR-Code zum Koppeln eines iPads")
    }

    private var anleitung: some View {
        VStack(alignment: .leading, spacing: GA.m) {
            Text("Scanne diesen Code mit Kev CAD auf deinem iPad. Danach verbindet sich das iPad von selbst, sobald beide im selben WLAN sind oder Tailscale läuft.")
                .font(GS.text).foregroundStyle(GF.kreide).fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: GA.xs) {
                Text("1. Öffne Kev CAD auf dem iPad.")
                Text("2. Tippe auf „Code scannen“ und halte die Kamera auf diesen Code.")
                Text("3. Ohne Kamera: Kopiere den Code hier und tippe auf dem iPad auf „Einsetzen“.")
            }
            .font(GS.text).foregroundStyle(GF.asche).fixedSize(horizontal: false, vertical: true)
            Text(gueltigkeit).font(GS.klein).foregroundStyle(GF.rauch)
            HStack(spacing: GA.s) {
                Button("Code kopieren") {
                    if let text = try? kopplung.code?.text() { Zwischenablage.setzen(text) }
                }
                .disabled(kopplung.code == nil || (kopplung.code?.bis ?? .distantPast) <= jetzt)
                Button("Neuer Code") { aktionen?.ipadKoppeln() }
            }
            .buttonStyle(KevKnopfStil(form: .text))
        }
    }

    private var gueltigkeit: String {
        guard let bis = kopplung.code?.bis else { return "Gleich erscheint ein neuer Code." }
        let rest = Int(bis.timeIntervalSince(jetzt))
        if rest <= 0 { return "Der Code ist abgelaufen. Mit „Neuer Code“ gibt es einen frischen." }
        let minuten = (rest + 59) / 60
        return minuten == 1 ? "Der Code gilt noch eine Minute für die erste Verbindung."
            : "Der Code gilt noch \(minuten) Minuten für die erste Verbindung."
    }

    private var geraeteListe: some View {
        VStack(alignment: .leading, spacing: GA.s) {
            Text("Gekoppelte iPads").font(GS.abschnitt).foregroundStyle(GF.asche)
            let geraete = kopplung.geraete.filter(\.bestaetigt)
            if geraete.isEmpty {
                Text("Noch kein iPad gekoppelt.").font(GS.text).foregroundStyle(GF.rauch)
            }
            ForEach(geraete) { g in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(g.name).font(GS.zeile).foregroundStyle(GF.kreide)
                        Text(g.zuletzt.map { "zuletzt verbunden \($0.formatted(date: .abbreviated, time: .shortened))" }
                                ?? "noch nie verbunden")
                            .font(GS.winzig).foregroundStyle(GF.rauch)
                    }
                    Spacer()
                    Button("Entfernen") { aktionen?.ipadEntfernen(g.kennung) }
                        .buttonStyle(KevKnopfStil(form: .text))
                }
            }
        }
    }
}
#endif

#if os(iOS)
/// Blatt „Mit dem Mac koppeln“ auf dem iPad: Code scannen oder einfügen; ohne Kopplung zeigt die App dahinter das
/// Beispielmodell.
struct PadKopplungsBlatt: View {
    @ObservedObject var kopplung: KopplungsStore
    let aktionen: KopplungsActions?
    let schliessen: () -> Void
    @State private var scannen = false
    @State private var fehler: String?

    private var kannScannen: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    var body: some View {
        VStack(spacing: GA.l) {
            Text("Mit dem Mac koppeln").font(.title2.weight(.semibold)).foregroundStyle(GF.kreide)
            Text("Kev CAD rechnet auf deinem Mac. Öffne dort Kev CAD und wähle im Menü Ablage „iPad koppeln …“. Dann scannst du hier den Code, der dort erscheint.")
                .font(.body).foregroundStyle(GF.asche).multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            if let hinweis = fehler ?? kopplung.meldung {
                Text(hinweis).font(.callout).foregroundStyle(GF.befund).multilineTextAlignment(.center)
            }
            VStack(spacing: GA.m) {
                if kannScannen {
                    Button {
                        scannen = true
                    } label: {
                        Label("Code scannen", systemImage: "qrcode.viewfinder").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
                PasteButton(payloadType: String.self) { texte in
                    Task { @MainActor in uebernehmen(texte.first ?? "") }
                }
                .controlSize(.large)
                Button("Beispiel ansehen", action: schliessen)
                    .controlSize(.large)
            }
            .frame(maxWidth: 320)
        }
        .padding(GA.xl * 1.5)
        .frame(maxWidth: 520)
        .sheet(isPresented: $scannen) {
            QRScanner { text in
                if uebernehmen(text) { scannen = false }
            }
            .ignoresSafeArea()
            .overlay(alignment: .bottom) {
                Text("Halte die Kamera auf den Code am Mac.")
                    .font(.callout).foregroundStyle(.white).padding(GA.m)
                    .background(Capsule().fill(.black.opacity(0.55))).padding(.bottom, 40)
            }
        }
        .onChange(of: kopplung.verbunden) { _, verbunden in if verbunden { schliessen() } }
    }

    /// Text aus dem Scanner oder der Zwischenablage übernehmen; true, wenn es ein Code von Kev CAD war.
    @discardableResult
    private func uebernehmen(_ text: String) -> Bool {
        guard let aktionen else {
            fehler = "Koppeln geht in diesem Modus nicht."
            return false
        }
        if aktionen.koppeln(text: text) {
            fehler = nil
            return true
        }
        fehler = "Das ist kein Code von Kev CAD. Am Mac gibt es ihn unter Ablage › iPad koppeln …"
        return false
    }
}

/// Kamera mit QR-Erkennung (VisionKit). Meldet jeden erkannten Code einmal.
private struct QRScanner: UIViewControllerRepresentable {
    let gefunden: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced,
                                           isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        try? vc.startScanning()
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {}

    func makeCoordinator() -> Koordinator { Koordinator(gefunden: gefunden) }

    final class Koordinator: NSObject, DataScannerViewControllerDelegate {
        let gefunden: (String) -> Void
        private var gesehen = Set<String>()

        init(gefunden: @escaping (String) -> Void) { self.gefunden = gefunden }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem],
                         allItems: [RecognizedItem]) {
            for item in items {
                guard case .barcode(let code) = item, let text = code.payloadStringValue,
                    gesehen.insert(text).inserted
                else { continue }
                gefunden(text)
            }
        }
    }
}

/// Kleine Anzeige oben in der Mitte: mit welchem Mac das iPad verbunden ist; ein Tipp öffnet die Kopplung.
struct PadKopplungsChip: View {
    @ObservedObject var kopplung: KopplungsStore
    let tippen: () -> Void

    var body: some View {
        Button(action: tippen) {
            HStack(spacing: 6) {
                Circle().fill(punktFarbe).frame(width: 7, height: 7)
                Text(text).font(GS.klein).foregroundStyle(GF.asche)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 2)
            .background(Capsule().fill(GF.mitte.opacity(0.6)))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(text)
    }

    private var text: String {
        guard let mac = kopplung.macName else { return "Beispielmodell · Mit dem Mac koppeln" }
        return kopplung.verbunden ? "Verbunden mit \(mac)" : "Verbinde mit \(mac) …"
    }

    private var punktFarbe: Color {
        guard kopplung.macName != nil else { return GF.rauch }
        return kopplung.verbunden ? Color.green : GF.agent
    }
}
#endif
