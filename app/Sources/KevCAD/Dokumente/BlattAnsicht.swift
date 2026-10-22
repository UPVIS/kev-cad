import AppKit
import KevCADCore
import SwiftUI

/// Ein Zeichnungsblatt im Bereich Dokumente: Leinwand (Zoom, Verschieben, Bearbeiten), Statuszeile, Laden und Fehler.
struct BlattAnsicht: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: DokumenteStore
    @ObservedObject var zustand: DokumenteZustand
    let blattID: String

    private var zeichnung: Zeichnung? { store.zeichnung(blattID) }
    /// Zeitpunkt der zuletzt ausgeblendeten Meldung.
    @State private var verborgen: Date?

    /// Neueste Meldung aus Kern (Kernel lehnt ab) und Oberfläche (PDF gesichert …), bis sie ausgeblendet ist.
    private var aktuelleMeldung: DokumenteMeldung? {
        let m = [store.meldung, zustand.meldung].compactMap { $0 }.max { $0.zeit < $1.zeit }
        guard let m, m.zeit != verborgen, Date().timeIntervalSince(m.zeit) < 12 else { return nil }
        return m
    }

    var body: some View {
        ZStack {
            BlattLeinwandView(zeichnung: zeichnung, zustand: zustand, model: model,
                              angefordert: zustand.gewaehltUm?.blatt == blattID ? zustand.gewaehltUm?.zeit : nil)
            if zeichnung == nil {
                ladeZustand
            }
        }
        .overlay(alignment: .bottom) {
            BlattStatuszeile(store: store, anzeige: zustand.anzeige, zustand: zustand, blattID: blattID)
        }
        .overlay(alignment: .top) {
            if let m = aktuelleMeldung {
                BlattMeldung(meldung: m)
                    .padding(.top, 10)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .id(m.zeit)
                    .task(id: m.zeit) {
                        try? await Task.sleep(for: .seconds(m.fehler ? 9 : 4))
                        verborgen = m.zeit
                    }
            }
        }
        .animation(.snappy(duration: 0.2), value: aktuelleMeldung)
        .onAppear { laden() }
        .onChange(of: blattID) { _, _ in laden() }
        .onChange(of: model.kernelState) { _, s in if s == .ready, zeichnung == nil { laden() } }
        .confirmationDialog(
            "Ansicht löschen?", isPresented: Binding(get: { zustand.ansichtLoeschen != nil },
                                                    set: { if !$0 { zustand.ansichtLoeschen = nil } }),
            titleVisibility: .visible
        ) {
            Button("Ansicht löschen", role: .destructive) {
                if let id = zustand.ansichtLoeschen {
                    zustand.bearbeiter.ausfuehren([.ansichtLoeschen(id: id)], blatt: blattID)
                    zustand.element = nil
                }
                zustand.ansichtLoeschen = nil
            }
        } message: {
            Text("Die Maße dieser Ansicht fallen mit weg. Rückgängig geht das nur über die Versionen.")
        }
    }

    private func laden() {
        guard model.kernelState == .ready || model.kernelState == .busy else { return }
        if zeichnung == nil || store.istVeraltet(blattID), !store.laedt.contains(blattID) {
            model.dokumenteActions?.zeichnungAnfordern(blattID)
        }
    }

    @ViewBuilder
    private var ladeZustand: some View {
        if let f = store.fehler[blattID] {
            ContentUnavailableView {
                Label("Blatt nicht gerechnet", systemImage: "exclamationmark.triangle")
            } description: {
                Text(f).textSelection(.enabled)
            } actions: {
                Button("Erneut versuchen") { model.dokumenteActions?.zeichnungAnfordern(blattID) }
            }
        } else {
            VStack(spacing: 12) {
                ProgressView().controlSize(.large)
                Text("Blatt wird gerechnet …").foregroundStyle(.secondary)
            }
        }
    }
}

/// Statuszeile unter dem Blatt, zwei schwebende Kapseln: links Format, Maßstab, verwaiste Maße und der Hinweis des
/// Werkzeugs; rechts Zeigerlage in mm und Zoom.
private struct BlattStatuszeile: View {
    @ObservedObject var store: DokumenteStore
    @ObservedObject var anzeige: BlattAnzeige
    @ObservedObject var zustand: DokumenteZustand
    let blattID: String

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            if store.zeichnung(blattID) != nil || anzeige.hinweis != nil {
            HStack(spacing: 12) {
                if let z = store.zeichnung(blattID) {
                    Text(z.formatText)
                    Text("Maßstab \(z.blatt.massstab)")
                    if !z.verwaisteMasse.isEmpty {
                        Label("\(z.verwaisteMasse.count) verwaist", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                            .help("Maße, deren Bezug nach einer Modelländerung nicht mehr gefunden wurde (rot)")
                    }
                }
                if let b = store.bearbeitung[blattID] {
                    HStack(spacing: 5) {
                        ProgressView().controlSize(.mini)
                        Text("\(b) …")
                    }
                } else if store.laedt.contains(blattID), store.zeichnung(blattID) != nil {
                    HStack(spacing: 5) {
                        ProgressView().controlSize(.mini)
                        Text("wird aktualisiert …")
                    }
                } else if let h = anzeige.hinweis {
                    Text(h).foregroundStyle(.primary).lineLimit(1)
                }
            }
            .modifier(Kapsel())
            }
            Spacer(minLength: 8)
            HStack(spacing: 10) {
                if let p = anzeige.zeiger {
                    Text("x \(KevFormat.number(Double(p.x), digits: 1))   y \(KevFormat.number(Double(p.y), digits: 1))")
                        .monospacedDigit()
                        .frame(minWidth: 118, alignment: .trailing)
                        .help("Lage des Zeigers auf dem Blatt in mm (Ursprung links unten)")
                }
                Menu("\(anzeige.zoomProzent) %") {
                    Button("Blatt einpassen") { zustand.ausfuehren(.einpassen) }
                    Button("Originalgröße (1:1)") { zustand.ausfuehren(.originalgroesse) }
                    Divider()
                    Button("Vergrößern") { zustand.ausfuehren(.vergroessern) }
                    Button("Verkleinern") { zustand.ausfuehren(.verkleinern) }
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("Zoom (100 % = Papiergröße auf dem Bildschirm)")
            }
            .modifier(Kapsel())
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .padding(.bottom, 10)
    }
}

/// Schwebende Kapsel der Statuszeile.
private struct Kapsel: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .background(.regularMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(.separator.opacity(0.5), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.08), radius: 4, y: 1)
    }
}

/// Fehler oder Bestätigung oben über dem Blatt.
private struct BlattMeldung: View {
    let meldung: DokumenteMeldung

    var body: some View {
        Label(meldung.text, systemImage: meldung.fehler ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
            .font(.callout)
            .foregroundStyle(meldung.fehler ? Color.red : Color.secondary)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(.regularMaterial, in: Capsule())
            .overlay(Capsule().strokeBorder(.separator.opacity(0.6), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.12), radius: 8, y: 2)
            .frame(maxWidth: 640)
    }
}

/// Brücke zur AppKit-Leinwand.
struct BlattLeinwandView: NSViewRepresentable {
    let zeichnung: Zeichnung?
    @ObservedObject var zustand: DokumenteZustand
    let model: AppModel
    let angefordert: Date?

    func makeNSView(context: Context) -> BlattLeinwand {
        let v = BlattLeinwand(frame: .zero)
        v.zustand = zustand
        v.model = model
        return v
    }

    func updateNSView(_ v: BlattLeinwand, context: Context) {
        v.zustand = zustand
        v.setze(zeichnung, angefordertSeit: angefordert)
        v.werkzeug = zustand.werkzeug
        v.element = zustand.element
        if let b = zustand.befehl, b.id != v.letzterBefehl {
            v.letzterBefehl = b.id
            DispatchQueue.main.async { v.fuehreAus(b.art) }
        }
    }
}
