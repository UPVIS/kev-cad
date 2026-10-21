import KevCADCore
import SwiftUI

/// Meilenstein setzen oder bearbeiten: Titel und Notiz.
struct MeilensteinDialog: View {
    var daten: MeilensteinDialogDaten
    var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var titel = ""
    @State private var notiz = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "flag.fill").foregroundStyle(.orange)
                Text(daten.bearbeiten ? "Meilenstein bearbeiten" : "Meilenstein setzen").font(.headline)
            }
            Text(daten.aktuell ? "Benennt den aktuellen Stand. Ungesicherte Änderungen werden vorher eine Version."
                 : "Benennt V\(daten.version ?? 0).")
                .font(.callout)
                .foregroundStyle(.secondary)
            TextField("Titel, z. B. „Prototyp für den Testdruck“", text: $titel)
                .textFieldStyle(.roundedBorder)
            VStack(alignment: .leading, spacing: 4) {
                Text("Notiz").font(.caption).foregroundStyle(.secondary)
                TextEditor(text: $notiz)
                    .font(.body)
                    .frame(height: 84)
                    .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(.primary.opacity(0.15)))
            }
            HStack {
                Spacer()
                Button("Abbrechen") { dismiss() }.keyboardShortcut(.cancelAction)
                Button(daten.bearbeiten ? "Sichern" : "Meilenstein setzen") {
                    model.versionenActions?.setMilestone(
                        version: daten.aktuell ? nil : daten.version, titel: titel.trimmingCharacters(in: .whitespaces),
                        notiz: notiz.trimmingCharacters(in: .whitespacesAndNewlines))
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(titel.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 420)
        .onAppear {
            titel = daten.titel
            notiz = daten.notiz
        }
    }
}

/// Neue Variante von einer Version (oder dem aktuellen Stand) anlegen.
struct VarianteDialog: View {
    var daten: VarianteDialogDaten
    var model: AppModel
    @ObservedObject var store: VersionenStore
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""

    private var vergeben: Bool {
        let n = name.trimmingCharacters(in: .whitespaces).lowercased()
        return store.stand?.varianten.contains { $0.name.lowercased() == n } ?? false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "arrow.triangle.branch").foregroundStyle(.purple)
                Text("Variante anlegen").font(.headline)
            }
            Text(
                "Eine Variante probiert eine Idee aus, ohne den Hauptstand anzufassen. Sie startet bei "
                    + (daten.von.map { "V\($0)" } ?? "dem aktuellen Stand")
                    + " und hat eine eigene Versionsleiste; ungesicherte Änderungen werden vorher eine Version."
            )
            .font(.callout)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            TextField("Name, z. B. „Leichtbau“", text: $name)
                .textFieldStyle(.roundedBorder)
            if vergeben {
                Text("Diesen Namen gibt es schon.").font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Abbrechen") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Anlegen und wechseln") {
                    model.versionenActions?.createVariant(name: name.trimmingCharacters(in: .whitespaces), from: daten.von)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || vergeben)
            }
        }
        .padding(20)
        .frame(width: 420)
    }
}

/// Variante umbenennen.
struct VarianteUmbenennenDialog: View {
    var variante: VersionVariante
    var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Variante „\(variante.name)“ umbenennen").font(.headline)
            TextField("Neuer Name", text: $name).textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("Abbrechen") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Umbenennen") {
                    model.versionenActions?.renameVariant(variante.id, to: name.trimmingCharacters(in: .whitespaces))
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 380)
        .onAppear { name = variante.name }
    }
}

/// Variantenmenü in der Titelleiste: aktuelle Variante, Wechsel mit einem Klick, neue Variante.
struct VariantenMenu: View {
    @ObservedObject var model: AppModel
    @ObservedObject var store: VersionenStore
    @ObservedObject var zustand: VersionenZustand

    var body: some View {
        let s = store.stand
        let aktuell = s?.aktuelleVariante
        Menu {
            Section("Varianten") {
                ForEach(s?.varianten ?? []) { v in
                    Button {
                        if !v.aktuell { model.versionenActions?.switchVariant(v.id) }
                    } label: {
                        if v.aktuell {
                            Label("\(v.name) (\(v.versionen))", systemImage: "checkmark")
                        } else {
                            Text("\(v.name) (\(v.versionen))")
                        }
                    }
                }
            }
            Divider()
            Button("Neue Variante vom aktuellen Stand …") { zustand.varianteAnlegen() }
                .disabled(s?.versionen.isEmpty ?? true)
            if let a = aktuell, a.id != "haupt" {
                Button("„\(a.name)“ umbenennen …") { zustand.umbenennenDialog = a }
            }
        } label: {
            Label(aktuell?.name ?? "Hauptstand", systemImage: "arrow.triangle.branch")
                .labelStyle(.titleAndIcon)
        }
        .disabled(!(s?.verfuegbar ?? false))
        .help("Varianten: Ideen ausprobieren, ohne den Hauptstand anzufassen. Wechsel sichert vorher alles.")
    }
}
