import KevCADCore
import SwiftUI

/// Karte unten links im Viewport, solange ein Vergleich läuft oder gezeigt wird: was sich geändert hat, Legende der
/// Farben im Viewer, Details und Beenden.
struct VergleichKarte: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: VersionenStore
    @ObservedObject var zustand: VersionenZustand

    var body: some View {
        if let v = store.vergleich {
            karte(v)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if let nr = store.vergleichLaeuft {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("V\(nr) wird zum Vergleich vorbereitet …").font(.callout)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(.regularMaterial))
            .shadow(color: .black.opacity(0.14), radius: 8, y: 2)
            .transition(.opacity)
        }
    }

    private func karte(_ v: VersionVergleich) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "square.split.2x1").foregroundStyle(.blue)
                Text("Vergleich \(v.a.kurz) → \(v.b.kurz)").font(.headline)
                Spacer(minLength: 10)
                Button("Details") { zustand.zeigeVergleichDetail = true }
                    .controlSize(.small)
                    .help("Parameter, Stückliste, Prüfung und Code-Unterschied")
                Button {
                    model.versionenActions?.endCompare()
                } label: {
                    Image(systemName: "xmark").font(.caption.weight(.semibold))
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .help("Vergleich beenden")
            }
            Text(v.gleich ? "Keine Unterschiede" : v.zusammenfassung)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if v.aktuell, !v.gleich {
                HStack(spacing: 12) {
                    if !v.teileGeaendert.isEmpty { Legende(farbe: .orange, text: "geändert (\(v.teileGeaendert.count))") }
                    if !v.teileNeu.isEmpty { Legende(farbe: .green, text: "neu (\(v.teileNeu.count))") }
                    if v.geometrie.contains(where: { $0.art == "alt" }) { Legende(farbe: .blue, text: "vorher", hohl: true) }
                    if !v.teileWeg.isEmpty { Legende(farbe: .red, text: "entfernt (\(v.teileWeg.count))", hohl: true) }
                }
                .font(.caption)
            } else if !v.aktuell {
                Text("Zwei ältere Versionen: Unterschiede ohne Geisterkörper").font(.caption).foregroundStyle(.tertiary)
            }
            ForEach(v.hinweise, id: \.self) { h in
                Label(h, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(maxWidth: 440, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.blue.opacity(0.35), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
        }
    }
}

private struct Legende: View {
    var farbe: Color
    var text: String
    var hohl = false

    var body: some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 3)
                .fill(farbe.opacity(hohl ? 0.35 : 0.9))
                .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(farbe, lineWidth: hohl ? 1 : 0))
                .frame(width: 12, height: 12)
            Text(text)
        }
    }
}

// MARK: - Details

/// Blatt mit allen Unterschieden: Übersicht (Kennzahlen, Parameter, Prüfung), Teile, Stückliste, Code.
struct VergleichDetail: View {
    @ObservedObject var store: VersionenStore
    @Environment(\.dismiss) private var dismiss
    @State private var reiter = 0

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                if let v = store.vergleich {
                    Text("Vergleich \(v.a.kurz) → \(v.b.kurz)").font(.title3.weight(.semibold))
                    Text(v.a.titel).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Picker("", selection: $reiter) {
                    Text("Übersicht").tag(0)
                    Text("Teile").tag(1)
                    Text("Stückliste").tag(2)
                    Text("Code").tag(3)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 340)
            }
            .padding(14)
            Divider()
            if let v = store.vergleich {
                switch reiter {
                case 0: uebersicht(v)
                case 1: teile(v)
                case 2: stueckliste(v)
                default: CodeDiffView(dateien: v.codeDateien, diff: v.diff, gekuerzt: v.diffGekuerzt)
                }
            } else {
                Text("Kein Vergleich").foregroundStyle(.secondary).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Divider()
            HStack {
                Spacer()
                Button("Schließen") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            .padding(12)
        }
        .frame(minWidth: 760, idealWidth: 860, minHeight: 520, idealHeight: 640)
    }

    // MARK: Übersicht

    private func uebersicht(_ v: VersionVergleich) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 6) {
                    GridRow {
                        Text("").gridColumnAlignment(.leading)
                        Text(v.a.kurz).font(.headline)
                        Text(v.b.kurz).font(.headline)
                    }
                    Divider().gridCellUnsizedAxes(.horizontal)
                    zeile("Teile", v.kennzahlenAlt.map { String($0.teile) }, v.kennzahlenNeu.map { String($0.teile) })
                    zeile("Masse", v.kennzahlenAlt?.masseKg.map(KevFormat.kg), v.kennzahlenNeu?.masseKg.map(KevFormat.kg))
                    zeile("Kosten", v.kennzahlenAlt?.kosten.map(KevFormat.euro), v.kennzahlenNeu?.kosten.map(KevFormat.euro))
                    zeile("Prüfung", v.pruefungAlt, v.pruefungNeu)
                }
                if !v.params.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Parameter").font(.headline)
                        ForEach(v.params) { p in
                            HStack(spacing: 8) {
                                Text(p.name).font(.body.monospaced())
                                Spacer(minLength: 8)
                                Text(VersionenText.wert(p.alt)).foregroundStyle(.secondary).monospacedDigit()
                                Image(systemName: "arrow.right").foregroundStyle(.tertiary)
                                Text(VersionenText.wert(p.neu)).monospacedDigit()
                                    .foregroundStyle(p.art == "weg" ? Color.red : (p.art == "neu" ? Color.green : .primary))
                            }
                        }
                    }
                    .frame(maxWidth: 420)
                }
                if v.gleich {
                    Label("Keine Unterschiede", systemImage: "equal.circle").foregroundStyle(.secondary)
                }
                ForEach(v.hinweise, id: \.self) { Label($0, systemImage: "info.circle").foregroundStyle(.secondary) }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func zeile(_ name: String, _ a: String?, _ b: String?) -> some View {
        GridRow {
            Text(name).foregroundStyle(.secondary)
            Text(a ?? "–").monospacedDigit()
            Text(b ?? "–").monospacedDigit().fontWeight(a != b ? .semibold : .regular)
        }
    }

    // MARK: Teile

    private func teile(_ v: VersionVergleich) -> some View {
        List {
            if !v.teileGeaendert.isEmpty {
                Section("Geändert (\(v.teileGeaendert.count))") {
                    ForEach(v.teileGeaendert) { t in
                        HStack {
                            Circle().fill(Color.orange).frame(width: 8, height: 8)
                            Text(t.name)
                            Spacer()
                            Text(t.arten.map(Self.artText).joined(separator: ", ")).foregroundStyle(.secondary)
                            if let dv = t.dvolumen, dv != 0 {
                                Text((dv > 0 ? "+" : "") + KevFormat.volume(mm3: dv)).foregroundStyle(.secondary)
                                    .monospacedDigit()
                            }
                        }
                    }
                }
            }
            if !v.teileNeu.isEmpty {
                Section("Neu (\(v.teileNeu.count))") {
                    ForEach(v.teileNeu, id: \.self) { n in
                        HStack { Circle().fill(Color.green).frame(width: 8, height: 8); Text(n) }
                    }
                }
            }
            if !v.teileWeg.isEmpty {
                Section("Entfernt (\(v.teileWeg.count))") {
                    ForEach(v.teileWeg, id: \.self) { n in
                        HStack { Circle().fill(Color.red).frame(width: 8, height: 8); Text(n).strikethrough() }
                    }
                }
            }
            Section("Unverändert") { Text(KevFormat.count(v.teileGleich, one: "Teil", many: "Teile")) }
        }
    }

    static func artText(_ a: String) -> String {
        ["form": "Form", "lage": "Lage", "farbe": "Farbe", "material": "Material", "lagerteil": "Lagerteil"][a] ?? a
    }

    // MARK: Stückliste

    private func stueckliste(_ v: VersionVergleich) -> some View {
        List {
            if v.stuecklisteNeu.isEmpty && v.stuecklisteWeg.isEmpty && v.stuecklisteGeaendert.isEmpty {
                Text("Stückliste unverändert").foregroundStyle(.secondary)
            }
            if !v.stuecklisteGeaendert.isEmpty {
                Section("Geändert") {
                    ForEach(Array(v.stuecklisteGeaendert.enumerated()), id: \.offset) { _, z in
                        HStack {
                            Text(z.benennung)
                            Spacer()
                            if let alt = z.altMasseText, alt != z.masseText {
                                Text("\(alt) → \(z.masseText ?? "")").foregroundStyle(.secondary)
                            } else {
                                Text(z.masseText ?? "").foregroundStyle(.secondary)
                            }
                            Text("\(z.altAnzahl ?? 0) → \(z.neuAnzahl ?? 0) Stk.").monospacedDigit()
                        }
                    }
                }
            }
            if !v.stuecklisteNeu.isEmpty {
                Section("Neu") {
                    ForEach(Array(v.stuecklisteNeu.enumerated()), id: \.offset) { _, z in
                        HStack {
                            Text("\(z.anzahl ?? 0) ×").monospacedDigit().foregroundStyle(.green)
                            Text(z.benennung)
                            Spacer()
                            Text(z.masseText ?? "").foregroundStyle(.secondary)
                        }
                    }
                }
            }
            if !v.stuecklisteWeg.isEmpty {
                Section("Entfallen") {
                    ForEach(Array(v.stuecklisteWeg.enumerated()), id: \.offset) { _, z in
                        HStack {
                            Text("\(z.anzahl ?? 0) ×").monospacedDigit().foregroundStyle(.red)
                            Text(z.benennung).strikethrough()
                            Spacer()
                            Text(z.masseText ?? "").foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }
}

/// Code-Unterschied: Dateiliste und farbiger Unified Diff.
struct CodeDiffView: View {
    var dateien: [CodeDatei]
    var diff: String
    var gekuerzt: Bool

    var body: some View {
        if dateien.isEmpty {
            Text("Keine Unterschiede in den Projektdateien").foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 14) {
                    ForEach(dateien) { d in
                        HStack(spacing: 4) {
                            Text(d.status).font(.caption.monospaced().weight(.bold))
                                .foregroundStyle(d.status == "A" ? .green : (d.status == "D" ? .red : .orange))
                            Text(d.pfad).font(.callout.monospaced())
                            if d.binaer {
                                Text("binär").font(.caption).foregroundStyle(.secondary)
                            } else {
                                Text("+\(d.plus ?? 0)").font(.caption.monospacedDigit()).foregroundStyle(.green)
                                Text("−\(d.minus ?? 0)").font(.caption.monospacedDigit()).foregroundStyle(.red)
                            }
                        }
                    }
                }
                .padding(10)
                Divider()
                ScrollView([.vertical, .horizontal]) {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(diff.split(separator: "\n", omittingEmptySubsequences: false).enumerated()),
                                id: \.offset) { _, zeile in
                            DiffZeile(text: String(zeile))
                        }
                        if gekuerzt {
                            Text("… gekürzt").foregroundStyle(.secondary).padding(8)
                        }
                    }
                    .padding(.vertical, 6)
                }
                .background(Color(nsColor: .textBackgroundColor))
            }
        }
    }
}

private struct DiffZeile: View {
    var text: String

    var body: some View {
        let kopf = text.hasPrefix("diff ") || text.hasPrefix("index ") || text.hasPrefix("+++") || text.hasPrefix("---")
        let farbe: Color =
            kopf ? .secondary : text.hasPrefix("+") ? .green : text.hasPrefix("-") ? .red : text.hasPrefix("@@") ? .blue : .primary
        Text(text.isEmpty ? " " : text)
            .font(.system(size: 11.5, design: .monospaced))
            .foregroundStyle(farbe)
            .fontWeight(kopf ? .semibold : .regular)
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                kopf ? Color.clear
                    : text.hasPrefix("+") ? Color.green.opacity(0.08) : text.hasPrefix("-") ? Color.red.opacity(0.08) : .clear)
            .textSelection(.enabled)
    }
}
