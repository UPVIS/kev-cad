import KevCADCore
import SwiftUI

/// Formular „Neues Projekt“: Name, Vorlage, Zielordner (ohne Namenskollision) → `actions.newProject`.
struct NewProjectSheet: View {
    @EnvironmentObject private var session: AppSession
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var template: ProjectTemplate = .example
    @FocusState private var nameFocused: Bool

    private var folder: URL { session.proposedFolder(for: name) }
    private var renamed: Bool { folder.lastPathComponent != ProjectLocator.sanitizedName(name) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Neues Projekt")
                    .font(.title2.weight(.semibold))
                Text("Ein Projekt ist ein Ordner mit model.py. Claude oder du schreibst darin das Modell.")
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 24)
            .padding(.top, 22)
            .padding(.bottom, 4)

            Form {
                Section {
                    TextField("Name", text: $name, prompt: Text("z. B. Wandhalter"))
                        .focused($nameFocused)
                        .onSubmit(create)
                    LabeledContent("Ordner") {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(KevFormat.abbreviatedPath(folder.path))
                                .lineLimit(1)
                                .truncationMode(.head)
                                .foregroundStyle(.secondary)
                            if renamed {
                                Text("„\(ProjectLocator.sanitizedName(name))“ gibt es schon")
                                    .font(.caption)
                                    .foregroundStyle(.orange)
                            }
                        }
                    }
                }
                Section("Vorlage") {
                    Picker("Vorlage", selection: $template) {
                        ForEach(ProjectTemplate.allCases) { template in
                            VStack(alignment: .leading, spacing: 1) {
                                Text(template.title)
                                Text(template.detail)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .tag(template)
                        }
                    }
                    .pickerStyle(.radioGroup)
                    .labelsHidden()
                }
            }
            .formStyle(.grouped)
            .scrollDisabled(true)

            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Anlegen", action: create)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 20)
        }
        .frame(width: 500, height: 400)
        .onAppear { nameFocused = true }
    }

    private func create() {
        session.createProject(named: name, template: template)
        dismiss()
    }
}
