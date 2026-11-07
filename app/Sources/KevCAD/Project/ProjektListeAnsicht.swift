import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

/// Projekte aus dem iCloud-Ordner (PLAN-IPAD.md, I-7, Prototyp hinter dem Schalter „Projekte aus iCloud“). Zeigt auch ohne
/// Mac, was es gibt: Name, letzte Änderung, ob model.py schon auf dem Gerät liegt und ob iCloud Konfliktkopien angelegt hat.
/// Geöffnet wird über den Mac, der das Modell rechnet. Gemeinsame Oberfläche; heute nur auf dem iPad eingehängt (am Mac
/// legt der Schalter `projektablage.json` neue Projekte in der iCloud an, geöffnet wird dort über „Öffnen …“).
struct ProjektListeAnsicht: View {
    /// Gewählter Ordner; nil, solange keiner gewählt ist.
    let ordner: URL?
    /// Mac verbunden (sonst kann nichts geöffnet werden).
    let verbunden: Bool
    let oeffnen: (ProjektEintrag) -> Void
    let ordnerGewaehlt: (URL) -> Void
    let schliessen: () -> Void

    @State private var eintraege: [ProjektEintrag] = []
    @State private var laedt = false
    @State private var waehlen = false
    @State private var fehler: String?

    var body: some View {
        VStack(alignment: .leading, spacing: GA.l) {
            HStack {
                Text("Projekte in iCloud").font(.title2.weight(.semibold)).foregroundStyle(GF.kreide)
                Spacer()
                Button("Fertig", action: schliessen)
            }
            if let ordner {
                liste(ordner)
            } else {
                ohneOrdner
            }
            if let fehler {
                Text(fehler).font(.callout).foregroundStyle(GF.befund)
            }
        }
        .padding(GA.xl)
        .fileImporter(isPresented: $waehlen, allowedContentTypes: [.folder]) { ergebnis in
            switch ergebnis {
            case .success(let url):
                fehler = nil
                ordnerGewaehlt(url)
            case .failure(let e):
                fehler = "Der Ordner ließ sich nicht öffnen: \(e.localizedDescription)"
            }
        }
        .task(id: ordner) { await laden() }
    }

    private var ohneOrdner: some View {
        VStack(alignment: .leading, spacing: GA.m) {
            Text("Wähle einmal den Ordner „Kev CAD“ in iCloud Drive. Kev CAD merkt sich die Wahl und zeigt dir hier deine Projekte, auch wenn der Mac gerade nicht verbunden ist.")
                .font(.body).foregroundStyle(GF.asche).fixedSize(horizontal: false, vertical: true)
            Button {
                waehlen = true
            } label: {
                Label("Ordner wählen", systemImage: "folder")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    private func liste(_ ordner: URL) -> some View {
        VStack(alignment: .leading, spacing: GA.m) {
            if eintraege.isEmpty {
                Text(laedt ? "Projekte werden gelesen …" : "In „\(ordner.lastPathComponent)“ liegt noch kein Projekt.")
                    .font(.body).foregroundStyle(GF.asche)
            } else {
                List(eintraege) { e in
                    Button { oeffnen(e) } label: { zeile(e) }
                        .disabled(!verbunden)
                        .listRowBackground(GF.mitte.opacity(0.5))
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .refreshable { await laden() }
            }
            if !verbunden {
                Text("Öffnen geht, sobald dein Mac verbunden ist. Er rechnet das Modell.")
                    .font(.callout).foregroundStyle(GF.rauch)
            }
            HStack {
                Button("Anderen Ordner wählen") { waehlen = true }
                Spacer()
                Button("Aktualisieren") { Task { await laden() } }
            }
            .font(.callout)
        }
    }

    private func zeile(_ e: ProjektEintrag) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(e.name).font(.headline).foregroundStyle(GF.kreide)
            HStack(spacing: GA.s) {
                if let d = e.geaendert {
                    Text("geändert \(d.formatted(.relative(presentation: .named)))")
                }
                if !e.geladen {
                    Label("noch in der iCloud", systemImage: "icloud.and.arrow.down")
                }
            }
            .font(.caption).foregroundStyle(GF.asche)
            if !e.konflikte.isEmpty {
                Text("iCloud hat eine Konfliktkopie angelegt: \(e.konflikte.joined(separator: ", ")). Am Mac prüfen, welche Fassung bleibt.")
                    .font(.caption).foregroundStyle(GF.befund)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }

    private func laden() async {
        guard let ordner else { return }
        laedt = true
        let liste = await Task.detached(priority: .userInitiated) { ProjektListe.lesen(ordner) }.value
        eintraege = liste
        laedt = false
    }
}
