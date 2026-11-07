import KevCADCore
import SwiftUI
import UniformTypeIdentifiers

/// Blatt „Projekte“ auf dem iPad (I-7): „Öffnen …“ in der Kopfleiste und der Startübersicht sowie der Knopf „Projekte“ in
/// der Statusleiste zeigen es. Hält den gewählten Ordner (Lesezeichen, `PadOrdner`) und verbindet die Liste mit der Sitzung.
/// Wählt Kevin in der Dateien-App einen Projektordner statt eines Ordners mit Projekten, öffnet er ihn gleich.
struct ProjekteBlatt: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    @State private var ordner = PadOrdner.ordner()

    var body: some View {
        ProjektListeAnsicht(
            ordner: ordner, verbunden: AppInfo.isDemoMode || model.kopplung.verbunden,
            oeffnen: { e in
                session.padBlatt = nil
                session.openProject(at: e.url)
            },
            neu: { session.neuesProjektFragen = true },
            ordnerGewaehlt: { url in
                // Der Dialog gibt den Zugriff frei; das Lesezeichen hält ihn über Neustarts
                _ = url.startAccessingSecurityScopedResource()
                if ProjectLocator.isProject(url) {
                    session.padBlatt = nil
                    session.openProject(at: url)
                    return
                }
                try? PadOrdner.merken(url)
                ordner = PadOrdner.ordner() ?? url
            })
    }
}

/// Projekte aus dem gewählten Ordner (PLAN-IPAD.md, I-7). Zeigt auch ohne Mac, was es gibt: Name, letzte Änderung, ob
/// model.py schon auf dem Gerät liegt und ob iCloud Konfliktkopien angelegt hat. Geöffnet und angelegt wird über den Mac,
/// der das Modell rechnet. Gemeinsame Oberfläche; eingehängt auf dem iPad (`ProjekteBlatt`), am Mac öffnet der Dateidialog.
struct ProjektListeAnsicht: View {
    /// Gewählter Ordner; nil, solange keiner gewählt ist.
    let ordner: URL?
    /// Mac verbunden (sonst kann nichts geöffnet werden).
    let verbunden: Bool
    let oeffnen: (ProjektEintrag) -> Void
    let neu: () -> Void
    let ordnerGewaehlt: (URL) -> Void

    @State private var eintraege: [ProjektEintrag] = []
    @State private var laedt = false
    @State private var waehlen = false
    @State private var fehler: String?

    var body: some View {
        VStack(alignment: .leading, spacing: GA.l) {
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
            Text("Wähle einmal den Ordner „Kev CAD“ in iCloud Drive. Kev CAD merkt sich die Wahl und zeigt dir hier deine Projekte, auch wenn der Mac gerade nicht verbunden ist. Ein einzelnes Projekt kannst du auch direkt wählen.")
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
            if !Projektablage.inICloud(ordner) {
                Text("Dieser Ordner liegt nicht in iCloud Drive. Dein Mac sieht ihn nicht und kann die Projekte darin nicht öffnen.")
                    .font(.callout).foregroundStyle(GF.befund).fixedSize(horizontal: false, vertical: true)
            } else if !verbunden {
                Text("Öffnen und Anlegen gehen, sobald dein Mac verbunden ist. Er rechnet das Modell.")
                    .font(.callout).foregroundStyle(GF.rauch)
            }
            HStack {
                Button("Neues Projekt", action: neu).disabled(!verbunden)
                Spacer()
                Button("Anderen Ordner wählen") { waehlen = true }
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
