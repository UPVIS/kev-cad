import KevCADCore
import SwiftUI

/// Was die Druckerleiste gerade offen hat (für den Selbsttest steuerbar).
@MainActor
final class DruckerUI: ObservableObject {
    static let shared = DruckerUI()
    @Published var einstellungenOffen = false
}

/// Druckerleiste (Phase 8, DRUCKVORSCHAU.md „Drucken (Phase 8)“): eine Zeile über der Druckvorschau mit dem Zustand des
/// P1P (nur lesend bei Weg A), Fortschritt, Schicht, Restzeit, Temperaturen, Fehlern, dem laufenden Auftrag von Kev CAD
/// und dem Knopf „Drucken …“. Pause, Fortsetzen und Abbruch erscheinen nur, wenn der Kernel das Steuern freigibt
/// (Weg B mit nachgewiesenem Developer Mode).
struct DruckerLeiste: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var drucker: DruckerStore
    @ObservedObject private var druck: DruckStore
    @ObservedObject private var ui = DruckerUI.shared
    @State private var fehlerOffen = false
    @State private var abbrechenFragen = false

    init(model: AppModel) {
        self.model = model
        _drucker = ObservedObject(wrappedValue: model.drucker)
        _druck = ObservedObject(wrappedValue: model.druck)
    }

    private var status: DruckerStatus { drucker.status ?? DruckerStatus() }

    var body: some View {
        HStack(spacing: 12) {
            kennung
            Divider().frame(height: 22)
            mitte
            Spacer(minLength: 8)
            fehlerKnopf
            steuerKnoepfe
            druckenKnopf
            Button {
                ui.einstellungenOffen = true
            } label: {
                Image(systemName: "gearshape")
            }
            .buttonStyle(.borderless)
            .help("Drucker-Einstellungen: IP, Seriennummer, Zugangscode, Weg, Status lesen")
            .disabled(model.druckerActions == nil)
        }
        .padding(.horizontal, 14)
        .frame(height: 40)
        .background(Color.kevAkzent.opacity(0.06))
        .overlay(alignment: .bottom) { Divider() }
        // Dialog „Drucken …“ und Einstellungen hängen am Projektfenster (DruckerDialoge), damit auch eine Frage des
        // Agenten erscheint, wenn die Druckvorschau gerade nicht zu sehen ist.
        .confirmationDialog("Druck wirklich abbrechen?", isPresented: $abbrechenFragen) {
            Button("Druck abbrechen", role: .destructive) { model.druckerActions?.druckerSteuern(.abbrechen) }
        } message: {
            Text("Der Drucker bricht den laufenden Druck ab; das lässt sich nicht fortsetzen.")
        }
    }

    // MARK: Teile

    private var kennung: some View {
        HStack(spacing: 7) {
            Image(systemName: "printer.dotmatrix")
                .foregroundStyle(punktFarbe)
                .help(status.verbindung.titel)
            VStack(alignment: .leading, spacing: 0) {
                Text(status.drucker?.name ?? drucker.aktiver?.name ?? "Drucker")
                    .font(.callout.weight(.semibold))
                Text(unterzeile)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .fixedSize()
    }

    private var unterzeile: String {
        if !status.konfiguriert && drucker.aktiver == nil { return "nicht eingerichtet" }
        var t: [String] = []
        if let d = status.drucker, d.modus != "unbekannt" { t.append(d.modusTitel) }
        t.append(status.weg == .a ? "Weg A" : "Weg B")
        t.append(status.verbindung.titel)
        return t.joined(separator: " · ")
    }

    private var punktFarbe: Color {
        switch status.verbindung {
        case .verbunden: return .green
        case .verbindet, .getrennt: return .orange
        case .fehler: return .red
        case .aus: return .secondary
        }
    }

    @ViewBuilder
    private var mitte: some View {
        if let a = status.auftrag, a.zustand.laeuft || (a.zustand == .fehler && drucker.dialog == nil) {
            HStack(spacing: 6) {
                if a.zustand.laeuft { ProgressView().controlSize(.small) }
                if a.zustand == .fehler { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red) }
                Text(a.meldung ?? a.zustand.titel).font(.callout).lineLimit(1)
            }
        } else if let d = status.druck, status.verbindung == .verbunden {
            druckZeile(d)
        } else {
            Text(hinweis).font(.callout).foregroundStyle(.secondary).lineLimit(1)
                .help(status.meldung ?? "")
        }
    }

    private var hinweis: String {
        if !status.konfiguriert && drucker.aktiver == nil {
            return "Kein Drucker eingestellt – „Drucken …“ öffnet die Platten trotzdem in Bambu Studio."
        }
        if let a = status.auftrag, a.zustand == .geoeffnet {
            return "Zuletzt in Bambu Studio geöffnet: dort „Platte drucken“ und „Senden“."
        }
        return status.meldung ?? status.verbindung.titel
    }

    private func druckZeile(_ d: DruckLauf) -> some View {
        HStack(spacing: 12) {
            Text(d.zustand.titel.prefix(1).uppercased() + d.zustand.titel.dropFirst())
                .font(.callout.weight(.medium))
            if d.zustand.aktiv, let f = d.fortschritt {
                ProgressView(value: f).frame(width: 120)
                Text("\(Int((f * 100).rounded())) %").font(.callout.monospacedDigit())
            }
            ViewThatFits(in: .horizontal) {
                details(d, temperaturen: true)
                details(d, temperaturen: false)
                EmptyView()
            }
        }
        .help(d.aufgabe.map { "Druckauftrag: \($0)" } ?? "")
    }

    private func details(_ d: DruckLauf, temperaturen: Bool) -> some View {
        HStack(spacing: 12) {
            if let s = d.schicht, let n = d.schichten, n > 0 {
                Text("Schicht \(s)/\(n)").monospacedDigit()
            }
            if d.zustand.aktiv, let r = d.restzeitS {
                Text("noch \(DruckFormat.zeit(r))").monospacedDigit()
            }
            if let stufe = d.stufe, stufe != "druckt" { Text(stufe).foregroundStyle(.secondary) }
            if temperaturen, let t = status.temperaturen {
                Text("Düse \(grad(t.duese, t.dueseZiel))  Bett \(grad(t.bett, t.bettZiel))")
                    .monospacedDigit().foregroundStyle(.secondary)
            }
        }
        .font(.callout)
        .lineLimit(1)
    }

    private func grad(_ ist: Double?, _ soll: Double?) -> String {
        guard let ist else { return "–" }
        let i = Int(ist.rounded())
        if let soll, soll > 0 { return "\(i)/\(Int(soll.rounded())) °C" }
        return "\(i) °C"
    }

    @ViewBuilder
    private var fehlerKnopf: some View {
        let fehler = status.fehler
        if !fehler.isEmpty || drucker.fehler != nil {
            Button {
                fehlerOffen.toggle()
            } label: {
                Label("\(fehler.count + (drucker.fehler == nil ? 0 : 1))", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(fehler.contains(where: \.istFehler) ? Color.red : Color.orange)
            }
            .buttonStyle(.borderless)
            .help("Meldungen des Druckers")
            .popover(isPresented: $fehlerOffen) {
                VStack(alignment: .leading, spacing: 8) {
                    if let f = drucker.fehler { Text(f).foregroundStyle(.red) }
                    ForEach(fehler) { f in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(f.code).font(.caption.monospaced()).foregroundStyle(f.istFehler ? Color.red : Color.orange)
                            Text(f.text).font(.callout).textSelection(.enabled)
                        }
                    }
                }
                .padding(12)
                .frame(width: 360, alignment: .leading)
            }
        }
    }

    @ViewBuilder
    private var steuerKnoepfe: some View {
        if status.steuern, let d = status.druck {
            HStack(spacing: 4) {
                if d.zustand == .druckt {
                    Button { model.druckerActions?.druckerSteuern(.pause) } label: { Image(systemName: "pause.fill") }
                        .help("Druck pausieren")
                }
                if d.zustand == .pausiert {
                    Button { model.druckerActions?.druckerSteuern(.fortsetzen) } label: { Image(systemName: "play.fill") }
                        .help("Druck fortsetzen")
                }
                if d.zustand.aktiv {
                    Button { abbrechenFragen = true } label: { Image(systemName: "stop.fill") }
                        .help("Druck abbrechen …")
                }
            }
            .controlSize(.small)
        }
    }

    private var druckenKnopf: some View {
        Button {
            model.druckerActions?.druckDialogOeffnen(platten: [])
        } label: {
            Label("Drucken …", systemImage: "printer.fill")
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.small)
        .disabled(model.druckerActions == nil || model.project == nil || drucker.dialog != nil
            || !status.wegA.moeglich && !status.wegB.moeglich)
        .help(status.wegA.moeglich
            ? "Platten fertig slicen und in Bambu Studio öffnen; dort „Platte drucken“ und „Senden“"
            : (status.wegA.grund ?? "Bambu Studio fehlt"))
    }
}
