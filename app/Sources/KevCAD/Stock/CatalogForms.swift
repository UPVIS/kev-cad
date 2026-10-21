import AppKit
import KevCADCore
import SwiftUI

/// Auftrag für das Formular: neuer Eintrag, Bearbeiten oder Kopie (z. B. eines mitgelieferten Eintrags).
struct CatalogFormRequest: Identifiable {
    enum Mode {
        case new, edit, copy
    }

    enum Draft {
        case item(CatalogItemDraft)
        case material(CatalogMaterialDraft)
    }

    let id = UUID()
    var mode: Mode
    var draft: Draft
    var ebene: CatalogLevel
}

/// Blatt mit dem passenden Formular.
struct CatalogFormSheet: View {
    @ObservedObject var model: AppModel
    let request: CatalogFormRequest
    var onSaved: (CatalogFocus) -> Void

    var body: some View {
        switch request.draft {
        case .item(let draft):
            ItemForm(model: model, mode: request.mode, draft: draft, ebene: request.ebene, onSaved: onSaved)
        case .material(let draft):
            MaterialForm(model: model, mode: request.mode, draft: draft, ebene: request.ebene, onSaved: onSaved)
        }
    }
}

// MARK: - Lagerteil

private struct ItemForm: View {
    @ObservedObject var model: AppModel
    let mode: CatalogFormRequest.Mode
    @State var draft: CatalogItemDraft
    @State var ebene: CatalogLevel
    var onSaved: (CatalogFocus) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var nameEdited = false
    @State private var idEdited = false
    @State private var showIssues = false
    @State private var submitted = false
    @State private var kernelError: String?
    private let originalID: String

    init(
        model: AppModel, mode: CatalogFormRequest.Mode, draft: CatalogItemDraft, ebene: CatalogLevel,
        onSaved: @escaping (CatalogFocus) -> Void
    ) {
        self.model = model
        self.mode = mode
        _draft = State(initialValue: draft)
        _ebene = State(initialValue: ebene)
        self.onSaved = onSaved
        originalID = draft.id
        // Neue Einträge bekommen Name und ID vorgeschlagen, bis jemand sie selbst ändert
        _nameEdited = State(initialValue: mode != .new || !draft.name.isEmpty)
        _idEdited = State(initialValue: mode != .new || !draft.id.isEmpty)
    }

    private var catalog: Catalog? { model.catalog }
    private var materials: [CatalogMaterial] { catalog?.materials ?? [] }
    private var material: CatalogMaterial? { catalog?.material(draft.material) }
    private var issues: [CatalogIssue] { draft.validate(materials: Set(materials.map(\.id))) }

    private var title: String {
        switch mode {
        case .new: return "Neues Lagerteil"
        case .edit: return "Lagerteil bearbeiten"
        case .copy: return "Lagerteil kopieren"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            FormTitle(title: title, symbol: CatalogSchema.art(draft.art).symbol, subtitle: subtitle)
            Form {
                artSection
                measureSection
                nameSection
                materialSection
                priceSection
                levelSection
            }
            .formStyle(.grouped)
            FormFooter(
                issues: showIssues ? issues : [], kernelError: kernelError, saving: submitted,
                cancel: { dismiss() }, save: save)
        }
        .frame(width: 580, height: 680)
        .onChange(of: draft.masse) { suggest() }
        .onChange(of: draft.material) { suggest() }
        .onChange(of: draft.art) { _, art in artChanged(art) }
        .onChange(of: model.catalogActivity) { _, activity in finish(activity) }
        .onAppear { suggest() }
    }

    private var subtitle: String {
        switch mode {
        case .new: return "Wird als JSON im \(ebene == .projekt ? "Projektkatalog" : "eigenen Katalog") gespeichert."
        case .edit: return "\(ebene.title) · \(originalID)"
        case .copy: return "Kopie von \(originalID)"
        }
    }

    // MARK: Abschnitte

    private var artSection: some View {
        Section {
            Picker("Art", selection: $draft.art) {
                ForEach(CatalogSchema.arten) { art in
                    Label(art.title, systemImage: art.symbol).tag(art.id)
                }
                if !CatalogSchema.art(draft.art).isKnown {
                    Text(CatalogSchema.art(draft.art).title).tag(draft.art)
                }
            }
            .disabled(mode == .edit)
        } footer: {
            let art = CatalogSchema.art(draft.art)
            Text(art.profile.isEmpty ? "" : "Querschnitt: \(art.profile)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var measureSection: some View {
        Section("Maße") {
            ForEach(draft.schema.fields) { field in
                FieldRow(
                    label: field.label, text: masseBinding(field.key), unit: field.unit,
                    prompt: field.required ? "Pflicht" : "optional", suggestions: field.suggestions, hint: field.hint,
                    issue: issue("masse.\(field.key)"), numeric: field.kind == .number,
                    width: field.kind == .number ? 120 : 190)
            }
            if draft.schema.fields.isEmpty {
                Text("Für diese Art kennt die App keine Maßfelder; die Maße bleiben wie im Eintrag.")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var nameSection: some View {
        Section("Bezeichnung") {
            FieldRow(
                label: "Name", text: Binding(get: { draft.name }, set: { draft.name = $0; nameEdited = true }),
                prompt: "z. B. Vierkantrohr 40 × 40 × 3", issue: issue("name"), width: 300)
            if mode == .edit {
                LabeledContent("ID") { Text(draft.id).font(.body.monospaced()).textSelection(.enabled) }
            } else {
                FieldRow(
                    label: "ID", text: Binding(get: { draft.id }, set: { draft.id = $0; idEdited = true }),
                    prompt: "kleinbuchstaben-mit-bindestrich", issue: issue("id") ?? idNote, monospaced: true,
                    width: 300, issueIsNote: issue("id") == nil)
            }
            FieldRow(label: "Norm", text: $draft.norm, prompt: "optional, z. B. DIN EN 10219", width: 300)
        }
    }

    private var materialSection: some View {
        Section("Werkstoff und Lieferform") {
            Picker("Material", selection: $draft.material) {
                Text("Bitte wählen").tag("")
                ForEach(materialGroups, id: \.self) { group in
                    Section(group) {
                        ForEach(materials.filter { $0.gruppe == group }) { m in
                            Text(m.name).tag(m.id)
                        }
                    }
                }
                if !draft.material.isEmpty && material == nil {
                    Text(draft.material).tag(draft.material)
                }
            }
            if let issue = issue("material") { IssueText(text: issue) }
            switch draft.schema.supply {
            case .bar:
                FieldRow(label: "Gewicht je Meter", text: $draft.kgJeM, unit: "kg/m", prompt: "optional",
                         hint: weightHint, issue: issue("kg_je_m"), numeric: true)
                FieldRow(label: "Stangenlänge", text: $draft.stangenlaenge, unit: "mm", prompt: "z. B. 6000",
                         issue: issue("stangenlaenge"), numeric: true)
            case .sheet:
                LabeledContent("Standardformat") {
                    HStack(spacing: 6) {
                        NumberInput(text: $draft.formatB, prompt: "Breite")
                        Text("×").foregroundStyle(.secondary)
                        NumberInput(text: $draft.formatH, prompt: "Höhe")
                        Text("mm").foregroundStyle(.secondary)
                    }
                }
                if let issue = issue("platte") { IssueText(text: issue) }
            case .piece:
                LabeledContent("Länge") { Text("beim Verbauen, z. B. verbauen(laenge=60)").foregroundStyle(.secondary) }
            }
        }
    }

    private var priceSection: some View {
        Section {
            LabeledContent("Preis") {
                HStack(spacing: 6) {
                    NumberInput(text: $draft.preis, prompt: "optional", width: 90)
                    Picker("Einheit", selection: $draft.preisEinheit) {
                        ForEach(CatalogSchema.PriceUnit.allCases) { Text($0.title).tag($0) }
                    }
                    .labelsHidden()
                    .fixedSize()
                }
            }
            if let issue = issue("preis") { IssueText(text: issue) }
            if !draft.preis.trimmingCharacters(in: .whitespaces).isEmpty {
                FieldRow(label: "Quelle", text: $draft.preisQuelle, prompt: "z. B. Angebot Stahlhandel",
                         issue: issue("preis_quelle"), width: 240)
                FieldRow(label: "Stand", text: $draft.preisStand, prompt: CatalogSchema.currentMonth(),
                         issue: issue("preis_stand"), width: 100)
            }
            FieldRow(label: "Suchbegriffe", text: $draft.tags, prompt: "kommagetrennt, z. B. geländer, rund", width: 300)
        } header: {
            Text("Preis und Suche")
        } footer: {
            Text("Preise sind Richtwerte netto; die Stückliste rechnet damit Materialkosten.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var levelSection: some View {
        LevelSection(model: model, ebene: $ebene, fixed: mode == .edit)
    }

    // MARK: Hilfen

    private var materialGroups: [String] {
        var seen = Set<String>()
        return materials.map(\.gruppe).filter { seen.insert($0).inserted }
    }

    private var weightHint: String {
        if let m = material, m.dichte > 0 { return "leer: aus Querschnitt × \(KevFormat.compact(m.dichte)) g/cm³" }
        return "leer: aus Querschnitt × Dichte"
    }

    private func masseBinding(_ key: String) -> Binding<String> {
        Binding(get: { draft.masse[key] ?? "" }, set: { draft.masse[key] = $0 })
    }

    private func issue(_ field: String) -> String? {
        guard showIssues else { return nil }
        return issues.first { $0.field == field }?.message
    }

    /// Hinweis, wenn die ID schon im Katalog steht.
    private var idNote: String? {
        let id = draft.id.trimmingCharacters(in: .whitespaces)
        guard !id.isEmpty, let existing = catalog?.item(id) else { return nil }
        if existing.ebene == .mitgeliefert {
            return "Gleiche ID wie ein mitgelieferter Eintrag: deine Fassung ersetzt ihn. Für ein zusätzliches Teil "
                + "eine neue ID vergeben."
        }
        return existing.ebene == ebene ? "Ersetzt „\(existing.name)“ (\(existing.ebene.title))." : nil
    }

    private func suggest() {
        if !nameEdited { draft.name = draft.suggestedName(materialName: material?.name, materialGroup: material?.gruppe) }
        if !idEdited { draft.id = draft.suggestedID() }
    }

    private func artChanged(_ art: String) {
        let schema = CatalogSchema.art(art)
        if draft.preis.trimmingCharacters(in: .whitespaces).isEmpty || mode == .new {
            draft.preisEinheit = schema.priceUnit
        }
        if schema.supply == .bar && draft.stangenlaenge.isEmpty { draft.stangenlaenge = "6000" }
        let keys = Set(schema.fields.map(\.key))
        draft.masse = draft.masse.filter { keys.contains($0.key) }
        suggest()
    }

    private func save() {
        kernelError = nil
        guard issues.isEmpty else {
            withAnimation(.snappy(duration: 0.2)) { showIssues = true }
            return
        }
        guard let actions = model.catalogActions else {
            kernelError = "Speichern geht gerade nicht (keine Verbindung zum Kernel)."
            return
        }
        submitted = true
        actions.saveCatalogEntry(kind: "teil", json: draft.json(), ebene: ebene)
    }

    private func finish(_ activity: CatalogActivity) {
        guard submitted else { return }
        switch activity {
        case .saved(let id, _):
            submitted = false
            onSaved(.item(id))
            dismiss()
        case .failed(let text):
            submitted = false
            kernelError = text
        default:
            break
        }
    }
}

// MARK: - Material

private struct MaterialForm: View {
    @ObservedObject var model: AppModel
    let mode: CatalogFormRequest.Mode
    @State var draft: CatalogMaterialDraft
    @State var ebene: CatalogLevel
    var onSaved: (CatalogFocus) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var idEdited = false
    @State private var showIssues = false
    @State private var submitted = false
    @State private var kernelError: String?
    private let originalID: String

    init(
        model: AppModel, mode: CatalogFormRequest.Mode, draft: CatalogMaterialDraft, ebene: CatalogLevel,
        onSaved: @escaping (CatalogFocus) -> Void
    ) {
        self.model = model
        self.mode = mode
        _draft = State(initialValue: draft)
        _ebene = State(initialValue: ebene)
        self.onSaved = onSaved
        originalID = draft.id
        _idEdited = State(initialValue: mode != .new || !draft.id.isEmpty)
    }

    private var issues: [CatalogIssue] { draft.validate() }

    private var title: String {
        switch mode {
        case .new: return "Neues Material"
        case .edit: return "Material bearbeiten"
        case .copy: return "Material kopieren"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            FormTitle(title: title, symbol: "paintpalette", subtitle: mode == .new
                ? "Für material= in model.py und für Lagerteile." : "\(ebene.title) · \(originalID)")
            Form {
                Section("Bezeichnung") {
                    FieldRow(label: "Name", text: $draft.name, prompt: "z. B. Eiche massiv", issue: issue("name"),
                             width: 260)
                    if mode == .edit {
                        LabeledContent("ID") { Text(draft.id).font(.body.monospaced()).textSelection(.enabled) }
                    } else {
                        FieldRow(
                            label: "ID", text: Binding(get: { draft.id }, set: { draft.id = $0; idEdited = true }),
                            prompt: "kleinbuchstaben-mit-bindestrich", issue: issue("id") ?? idNote, monospaced: true,
                            width: 260, issueIsNote: issue("id") == nil)
                    }
                    FieldRow(label: "Gruppe", text: $draft.gruppe, prompt: "z. B. Stahl",
                             suggestions: CatalogSchema.materialGroups, issue: issue("gruppe"), width: 200)
                }
                Section("Eigenschaften") {
                    FieldRow(label: "Dichte", text: $draft.dichte, unit: "g/cm³", prompt: "Pflicht", issue: issue("dichte"),
                             numeric: true)
                    LabeledContent("Farbe") {
                        HStack(spacing: 8) {
                            ColorPicker("Farbe", selection: colorBinding, supportsOpacity: false)
                                .labelsHidden()
                            TextField("Farbe", text: $draft.farbe, prompt: Text("#8A9099"))
                                .labelsHidden()
                                .font(.body.monospaced())
                                .frame(width: 96)
                        }
                    }
                    if let issue = issue("farbe") { IssueText(text: issue) }
                    FieldRow(label: "Metallisch", text: $draft.metallisch, unit: "0 … 1", prompt: "optional",
                             issue: issue("metallisch"), numeric: true)
                    FieldRow(label: "Rauheit", text: $draft.rauheit, unit: "0 … 1", prompt: "optional",
                             issue: issue("rauheit"), numeric: true)
                    Toggle(isOn: $draft.druckbar) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Für 3D-Druck")
                            Text("Filament: Teile daraus gelten als 3D-Druckteile (Inventar-Regel)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                Section {
                    FieldRow(label: draft.druckbar ? "Filamentpreis" : "Preis je kg", text: $draft.preisJeKg,
                             unit: "€/kg", prompt: "optional", issue: issue("preis_je_kg"), numeric: true)
                    if !draft.preisJeKg.trimmingCharacters(in: .whitespaces).isEmpty {
                        FieldRow(label: "Quelle", text: $draft.preisQuelle, prompt: "z. B. Angebot Holzhandel",
                                 issue: issue("preis_quelle"), width: 240)
                        FieldRow(label: "Stand", text: $draft.preisStand, prompt: CatalogSchema.currentMonth(),
                                 issue: issue("preis_stand"), width: 100)
                    }
                    FieldRow(label: "Weitere Namen", text: $draft.aliase, prompt: "kommagetrennt, z. B. eiche, oak",
                             width: 260)
                } header: {
                    Text("Preis und Namen")
                } footer: {
                    Text(draft.druckbar
                        ? "Mit dem Filamentpreis rechnet die Stückliste die Kosten der 3D-Druckteile."
                        : "Der Preis je kg gilt für frei modellierte Teile aus diesem Material.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                LevelSection(model: model, ebene: $ebene, fixed: mode == .edit)
            }
            .formStyle(.grouped)
            FormFooter(
                issues: showIssues ? issues : [], kernelError: kernelError, saving: submitted,
                cancel: { dismiss() }, save: save)
        }
        .frame(width: 540, height: 660)
        .onChange(of: draft.name) { _, name in
            if !idEdited { draft.id = CatalogSchema.slug(name) }
        }
        .onChange(of: model.catalogActivity) { _, activity in
            guard submitted else { return }
            switch activity {
            case .saved(let id, _):
                submitted = false
                onSaved(.material(id))
                dismiss()
            case .failed(let text):
                submitted = false
                kernelError = text
            default:
                break
            }
        }
    }

    private var colorBinding: Binding<Color> {
        Binding(
            get: { Color(hex: draft.farbe) ?? .gray },
            set: { draft.farbe = $0.hexString })
    }

    private func issue(_ field: String) -> String? {
        guard showIssues else { return nil }
        return issues.first { $0.field == field }?.message
    }

    private var idNote: String? {
        let id = draft.id.trimmingCharacters(in: .whitespaces)
        guard !id.isEmpty, let existing = model.catalog?.material(id) else { return nil }
        if existing.ebene == .mitgeliefert { return "Gleiche ID wie ein mitgeliefertes Material: deine Fassung ersetzt es." }
        return existing.ebene == ebene ? "Ersetzt „\(existing.name)“ (\(existing.ebene.title))." : nil
    }

    private func save() {
        kernelError = nil
        guard issues.isEmpty else {
            withAnimation(.snappy(duration: 0.2)) { showIssues = true }
            return
        }
        guard let actions = model.catalogActions else {
            kernelError = "Speichern geht gerade nicht (keine Verbindung zum Kernel)."
            return
        }
        submitted = true
        actions.saveCatalogEntry(kind: "material", json: draft.json(), ebene: ebene)
    }
}

// MARK: - Bausteine

private struct FormTitle: View {
    var title: String
    var symbol: String
    var subtitle: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(.tint)
                .frame(width: 38, height: 38)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(.tint.opacity(0.12)))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.title3.weight(.semibold))
                Text(subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
        .padding(.bottom, 6)
    }
}

/// Speichern in: eigener Katalog oder Projekt.
private struct LevelSection: View {
    @ObservedObject var model: AppModel
    @Binding var ebene: CatalogLevel
    var fixed: Bool

    var body: some View {
        Section {
            if fixed {
                LabeledContent("Speichern in") { Text(ebene.title) }
            } else {
                Picker("Speichern in", selection: $ebene) {
                    Text("Eigener Katalog").tag(CatalogLevel.eigen)
                    Text(model.project.map { "Projekt „\($0.name)“" } ?? "Projekt").tag(CatalogLevel.projekt)
                }
                .pickerStyle(.segmented)
                .onAppear { if ebene == .projekt && model.project == nil { ebene = .eigen } }
            }
        } footer: {
            Text(ebene.detail + (ebene == .projekt && model.project == nil ? " Kein Projekt offen." : ""))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

/// Zeile mit Bezeichnung, Eingabe, Einheit, Vorschlägen und Fehlertext.
private struct FieldRow: View {
    var label: String
    @Binding var text: String
    var unit: String? = nil
    var prompt: String = ""
    var suggestions: [String] = []
    var hint: String? = nil
    var issue: String? = nil
    var numeric = false
    var monospaced = false
    var width: CGFloat = 120
    /// `issue` ist nur ein Hinweis (grau), kein Fehler.
    var issueIsNote = false

    var body: some View {
        VStack(alignment: .trailing, spacing: 3) {
            LabeledContent {
                HStack(spacing: 6) {
                    TextField(label, text: $text, prompt: Text(prompt))
                        .labelsHidden()
                        .multilineTextAlignment(numeric ? .trailing : .leading)
                        .font(monospaced ? .body.monospaced() : .body)
                        .frame(width: width)
                    if !suggestions.isEmpty {
                        Menu {
                            ForEach(suggestions, id: \.self) { s in Button(s) { text = s } }
                        } label: {
                            Image(systemName: "chevron.down")
                        }
                        .menuStyle(.borderlessButton)
                        .menuIndicator(.hidden)
                        .fixedSize()
                        .help("Vorschläge")
                    }
                    if let unit {
                        Text(unit)
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 34, alignment: .leading)
                    }
                }
            } label: {
                VStack(alignment: .leading, spacing: 1) {
                    Text(label)
                    if let hint {
                        Text(hint).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            if let issue {
                if issueIsNote {
                    Text(issue)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .multilineTextAlignment(.trailing)
                } else {
                    IssueText(text: issue)
                }
            }
        }
    }
}

private struct NumberInput: View {
    @Binding var text: String
    var prompt: String
    var width: CGFloat = 70

    var body: some View {
        TextField(prompt, text: $text, prompt: Text(prompt))
            .labelsHidden()
            .multilineTextAlignment(.trailing)
            .frame(width: width)
    }
}

private struct IssueText: View {
    var text: String

    var body: some View {
        Label(text, systemImage: "exclamationmark.circle.fill")
            .font(.caption)
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .trailing)
    }
}

private struct FormFooter: View {
    var issues: [CatalogIssue]
    var kernelError: String?
    var saving: Bool
    var cancel: () -> Void
    var save: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            if saving {
                ProgressView().controlSize(.small)
                Text("Wird gespeichert …").foregroundStyle(.secondary)
            } else if let kernelError {
                Label(kernelError, systemImage: "xmark.octagon.fill")
                    .foregroundStyle(.red)
                    .lineLimit(2)
                    .textSelection(.enabled)
            } else if !issues.isEmpty {
                Label(
                    issues.count == 1 ? issues[0].message : "\(issues.count) Angaben fehlen oder stimmen nicht",
                    systemImage: "exclamationmark.triangle.fill"
                )
                .foregroundStyle(.orange)
                .lineLimit(1)
            }
            Spacer(minLength: 8)
            Button("Abbrechen", action: cancel)
                .keyboardShortcut(.cancelAction)
            Button("Sichern", action: save)
                .keyboardShortcut(.defaultAction)
                .disabled(saving)
        }
        .font(.callout)
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .overlay(alignment: .top) { Divider() }
    }
}
