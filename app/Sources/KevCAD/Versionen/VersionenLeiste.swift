import AppKit
import KevCADCore
import SwiftUI

/// Leiste „Versionen“ rechts neben dem Viewport (wie die Versionsgeschichte in Onshape oder Fusion): jede Version mit
/// Vorschaubild, Zeit, wer sie erzeugt hat, Kennzahlen und Meilenstein. Dichte Folgen sind zusammengefasst.
/// Kontextmenü: Wiederherstellen, Vergleichen, Meilenstein, Variante anlegen.
struct VersionenLeiste: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: VersionenStore
    @ObservedObject var zustand: VersionenZustand

    private var actions: VersionenActions? { model.versionenActions }

    var body: some View {
        VStack(spacing: 0) {
            kopf
            Divider()
            if let s = store.stand {
                if !s.verfuegbar {
                    hinweis(symbol: "exclamationmark.triangle", text: s.meldung ?? "Versionen nicht verfügbar")
                } else if s.versionen.isEmpty {
                    hinweis(
                        symbol: "clock.arrow.circlepath",
                        text: "Noch keine Version. Nach dem ersten erfolgreichen Lauf erscheint hier jeder Stand.")
                } else {
                    liste(s)
                }
            } else if actions == nil {
                hinweis(symbol: "clock.arrow.circlepath", text: "Im Demomodus gibt es keine Versionen.")
            } else {
                VStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Versionen werden geladen …").font(.callout).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            fuss
        }
        .frame(width: VersionenZustand.breite)
        .background(Color(nsColor: .controlBackgroundColor))
        .onAppear { if store.stand == nil { actions?.requestVersionen() } }
    }

    // MARK: Kopf und Fuß

    private var kopf: some View {
        HStack(spacing: 8) {
            Image(systemName: "clock.arrow.circlepath").foregroundStyle(.secondary)
            Text("Versionen").font(.headline)
            if let s = store.stand, s.verfuegbar {
                Text("\(s.anzahl)")
                    .font(.caption.monospacedDigit())
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(Color.primary.opacity(0.08)))
            }
            Spacer(minLength: 4)
            Button {
                zustand.meilensteinSetzen()
            } label: {
                Image(systemName: "flag")
            }
            .buttonStyle(.borderless)
            .help("Meilenstein für den aktuellen Stand setzen (⌘S)")
            .disabled(store.stand?.versionen.isEmpty ?? true)
            Button {
                withAnimation(.snappy(duration: 0.2)) { zustand.zeigeLeiste = false }
            } label: {
                Image(systemName: "xmark").font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help("Leiste ausblenden (⌥⌘V)")
        }
        .padding(.horizontal, 12)
        .frame(height: 38)
    }

    @ViewBuilder
    private var fuss: some View {
        if store.arbeitet != nil || store.vergleichLaeuft != nil || store.meldung != nil
            || (store.stand?.ungesichert ?? false)
        {
            Divider()
            VStack(alignment: .leading, spacing: 4) {
                if let a = store.arbeitet {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text(a).font(.caption)
                    }
                }
                if let nr = store.vergleichLaeuft {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("Vergleich mit V\(nr) wird vorbereitet …").font(.caption)
                    }
                }
                if store.stand?.ungesichert ?? false, store.arbeitet == nil {
                    Label("Ungesicherte Änderungen: Version entsteht beim nächsten erfolgreichen Lauf",
                          systemImage: "pencil.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let m = store.meldung, Date().timeIntervalSince(m.zeit) < 20 {
                    Label(m.text, systemImage: m.fehler ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(m.fehler ? Color.red : Color.secondary)
                        .lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    private func hinweis(symbol: String, text: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: symbol).font(.title2).foregroundStyle(.secondary)
            Text(text)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: Liste

    private func liste(_ s: VersionenStand) -> some View {
        let zeilen = s.zeilen(aufgeklappt: zustand.aufgeklappt)
        let ersteGeerbte = s.versionen.first(where: \.geerbt)?.nr
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 4) {
                    ForEach(zeilen) { zeile in
                        switch zeile {
                        case .version(let v, let eingerueckt):
                            if v.nr == ersteGeerbte {
                                geerbtTrenner(s)
                            }
                            VersionZeileView(
                                version: v, eingerueckt: eingerueckt, ausgewaehlt: zustand.auswahl == v.nr,
                                verglichen: store.vergleich?.a.nr == v.nr,
                                aktuelleNr: s.aktuelleVersion?.nr
                            )
                            .id("v\(v.nr)")
                            .onTapGesture(count: 2) { vergleichen(v) }
                            .onTapGesture { zustand.auswahl = v.nr }
                            .contextMenu { kontextmenue(v) }
                        case .gruppe(let g, let mitglieder):
                            GruppenZeileView(
                                gruppe: g, mitglieder: mitglieder, offen: zustand.aufgeklappt.contains(g.id)
                            ) {
                                withAnimation(.snappy(duration: 0.2)) {
                                    if zustand.aufgeklappt.contains(g.id) {
                                        zustand.aufgeklappt.remove(g.id)
                                    } else {
                                        zustand.aufgeklappt.insert(g.id)
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(8)
            }
            .onChange(of: s.aktuelleVersion?.nr) { _, nr in
                if let nr { withAnimation { proxy.scrollTo("v\(nr)", anchor: .top) } }
            }
        }
    }

    private func geerbtTrenner(_ s: VersionenStand) -> some View {
        let quelle = s.varianten.first { !$0.aktuell && $0.id == "haupt" }?.name ?? "Hauptstand"
        return HStack(spacing: 6) {
            Rectangle().fill(Color.secondary.opacity(0.3)).frame(height: 1)
            Text("Abgezweigt aus \(quelle)").font(.caption2).foregroundStyle(.secondary).fixedSize()
            Rectangle().fill(Color.secondary.opacity(0.3)).frame(height: 1)
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private func kontextmenue(_ v: VersionEintrag) -> some View {
        Button {
            actions?.restoreVersion(v.nr)
        } label: {
            Label("V\(v.nr) wiederherstellen", systemImage: "arrow.uturn.backward")
        }
        .disabled(v.aktuell)
        Button {
            vergleichen(v)
        } label: {
            Label("Mit aktuellem Stand vergleichen", systemImage: "square.split.2x1")
        }
        .disabled(v.aktuell)
        if let a = store.vergleich?.a.nr, a != v.nr, !v.aktuell {
            Button("Mit V\(a) vergleichen (ohne Geisterkörper)") {
                actions?.compareVersion(min(a, v.nr), with: max(a, v.nr))
            }
        }
        Divider()
        Button {
            zustand.meilensteinSetzen(v)
        } label: {
            Label(v.meilenstein == nil ? "Meilenstein setzen …" : "Meilenstein bearbeiten …", systemImage: "flag")
        }
        if v.meilenstein != nil {
            Button {
                actions?.removeMilestone(version: v.nr)
            } label: {
                Label("Meilenstein entfernen", systemImage: "flag.slash")
            }
        }
        Divider()
        Button {
            zustand.varianteAnlegen(von: v)
        } label: {
            Label("Variante von V\(v.nr) anlegen …", systemImage: "arrow.triangle.branch")
        }
        Divider()
        Button("Commit \(v.commit.prefix(10)) kopieren") {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString("V\(v.nr) \(v.commit)", forType: .string)
        }
    }

    private func vergleichen(_ v: VersionEintrag) {
        guard !v.aktuell else { return }
        zustand.auswahl = v.nr
        actions?.compareVersion(v.nr, with: nil)
    }
}

// MARK: - Zeilen

/// Eine Version: Vorschaubild, Titel (Meilenstein), Zeit und wer, Kennzahlen, Prüfstand.
struct VersionZeileView: View {
    var version: VersionEintrag
    var eingerueckt: Bool
    var ausgewaehlt: Bool
    var verglichen: Bool
    var aktuelleNr: Int?
    @State private var hover = false

    var body: some View {
        let v = version
        HStack(alignment: .top, spacing: 9) {
            Vorschaubild(url: v.bild, groesse: CGSize(width: 76, height: 48), ausgegraut: v.geerbt)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    if v.meilenstein != nil {
                        Image(systemName: "flag.fill").foregroundStyle(.orange).font(.caption)
                    } else if let sym = VersionenText.quelleSymbol(v) {
                        Image(systemName: sym).foregroundStyle(.secondary).font(.caption)
                    }
                    Text(v.anzeigeTitel)
                        .font(v.meilenstein != nil ? .callout.weight(.semibold) : .callout)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .help([v.anzeigeTitel, v.zusatz].compactMap { $0 }.joined(separator: "\n"))
                    Spacer(minLength: 2)
                    Text("V\(v.nr)")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                if let zusatz = v.zusatz {  // automatischer Titel unter dem Agententitel, „Übernommener Stand“
                    Text(zusatz)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                HStack(spacing: 4) {
                    Image(systemName: VersionenText.werSymbol(v.wer)).font(.caption2)
                        .foregroundStyle(v.wer == .agent ? Color.accentColor : .secondary)
                    Text("\(VersionenText.zeit(v.zeit)) · \(v.werText)")
                        .lineLimit(1)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                HStack(spacing: 5) {
                    Text(VersionenText.kennzahlen(v.kennzahlen))
                        .lineLimit(1)
                        .foregroundStyle(v.kennzahlen == nil ? .tertiary : .secondary)
                    if let f = v.kennzahlen?.fehler, f > 0 {
                        Label("\(f)", systemImage: "exclamationmark.triangle.fill")
                            .labelStyle(.titleAndIcon)
                            .foregroundStyle(.red)
                            .help(v.kennzahlen?.pruefung ?? "Prüfbefunde")
                    } else if v.kennzahlen?.fehler == 0 {
                        Image(systemName: "checkmark.seal")
                            .foregroundStyle(.green.opacity(0.8))
                            .help("Prüfung ohne Fehler")
                    }
                }
                .font(.caption2.monospacedDigit())
                if let notiz = v.meilenstein?.notiz, !notiz.isEmpty, ausgewaehlt || hover {
                    Text(notiz)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 2)
                }
                if ausgewaehlt {
                    details(v)
                }
            }
        }
        .padding(7)
        .padding(.leading, eingerueckt ? 12 : 0)
        .opacity(v.geerbt ? 0.7 : 1)
        .background {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(
                    ausgewaehlt
                        ? Color.accentColor.opacity(0.14)
                        : (hover ? Color.primary.opacity(0.05) : (v.aktuell ? Color.accentColor.opacity(0.06) : .clear)))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(
                    verglichen ? Color.blue.opacity(0.7) : (v.aktuell ? Color.accentColor.opacity(0.55) : .clear),
                    lineWidth: verglichen || v.aktuell ? 1.2 : 0)
        }
        .overlay(alignment: .topLeading) {
            if v.aktuell {
                Text("Aktuell")
                    .font(.system(size: 9, weight: .semibold))
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(Color.accentColor))
                    .foregroundStyle(.white)
                    .offset(x: 10, y: 3)
            }
        }
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .help(hilfe(v))
    }

    @ViewBuilder
    private func details(_ v: VersionEintrag) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            if !v.params.isEmpty {
                Text(v.params.sorted { $0.key < $1.key }.prefix(8).map { "\($0.key) = \(VersionenText.wert($0.value))" }
                    .joined(separator: ", "))
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !v.dateien.isEmpty {
                Text("Dateien: " + v.dateien.prefix(5).joined(separator: ", "))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            if let p = v.kennzahlen?.pruefung, !p.isEmpty {
                Text("Prüfung: \(p)").font(.caption2).foregroundStyle(.secondary).lineLimit(2)
            }
            if let n = v.nachberechnung {
                Text(n).font(.caption2).foregroundStyle(.orange).lineLimit(3)
            }
            if !v.aktuell {
                Text("Doppelklick: mit aktuellem Stand vergleichen · Rechtsklick: Wiederherstellen")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.top, 3)
    }

    private func hilfe(_ v: VersionEintrag) -> String {
        var t = "V\(v.nr) · \(KevFormat.recentDate(v.zeit)) · \(v.werText)"
        if v.meilenstein != nil { t += "\n\(v.titel)" }
        if let aus = v.aus { t += "\nWiederhergestellt aus V\(aus)" }
        return t
    }
}

/// Zusammengefasste Folge: „12 Läufe in 4 Minuten“, aufklappbar.
struct GruppenZeileView: View {
    var gruppe: VersionGruppe
    var mitglieder: [VersionEintrag]
    var offen: Bool
    var umschalten: () -> Void

    var body: some View {
        Button(action: umschalten) {
            HStack(spacing: 9) {
                ZStack {
                    ForEach(Array(mitglieder.prefix(3).enumerated().reversed()), id: \.offset) { i, v in
                        Vorschaubild(url: v.bild, groesse: CGSize(width: 64, height: 40), ausgegraut: false)
                            .offset(x: CGFloat(i) * 4, y: CGFloat(i) * -3)
                    }
                }
                .frame(width: 76, height: 48)
                VStack(alignment: .leading, spacing: 2) {
                    Text(gruppe.text).font(.callout)
                    Text("V\(gruppe.aelteste)–V\(gruppe.neueste)"
                        + (mitglieder.first.map { " · bis \(VersionenText.zeit($0.zeit))" } ?? ""))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 2)
                Image(systemName: offen ? "chevron.down" : "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(7)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.primary.opacity(0.035)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(offen ? "Folge zuklappen" : "Alle \(gruppe.anzahl) Versionen der Folge zeigen")
    }
}

/// Vorschaubild einer Version (oder ein Platzhalter, solange es keins gibt).
struct Vorschaubild: View {
    var url: URL?
    var groesse: CGSize
    var ausgegraut: Bool

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color(nsColor: .windowBackgroundColor))
            if let img = VorschauCache.shared.bild(url) {
                Image(nsImage: img)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: groesse.width, height: groesse.height)
                    .clipped()
                    .saturation(ausgegraut ? 0.2 : 1)
            } else {
                Image(systemName: "cube.transparent")
                    .font(.system(size: 16))
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(width: groesse.width, height: groesse.height)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(.primary.opacity(0.1), lineWidth: 0.5))
    }
}
