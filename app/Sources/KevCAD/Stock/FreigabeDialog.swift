import AppKit
import KevCADCore
import SwiftUI

// Freigabe direkt im Projektfenster (Strang „Feinschliff 2“): Band „3 Vorschläge warten auf Freigabe“ und der Dialog
// „Vorschläge freigeben“ mit Vorschau der Daten, Link und „Freigeben“ je Eintrag und für alle. Claude öffnet ihn mit
// `freigabe_anfragen`; freigegeben wird nur mit Kevins Klick (wie im Lagerkatalog, CATALOG_SAVE mit status frei).

extension AppModel {
    var freigabeActions: FreigabeActions? { actions as? FreigabeActions }

    /// Ids der offenen Vorschläge (Teile und Materialien), sortiert: Schlüssel für das Wegklicken des Bands.
    var vorschlagSchluessel: String? {
        guard let c = catalog, c.suggestionCount > 0 else { return nil }
        return (c.items.filter(\.vorgeschlagen).map(\.id) + c.materials.filter(\.vorgeschlagen).map(\.id))
            .sorted().joined(separator: "|")
    }
}

/// Band über dem Viewport bzw. dem Bereich, solange Vorschläge von Claude auf Kevins Freigabe warten.
struct FreigabeBand: View {
    @ObservedObject var model: AppModel
    var oeffnen: () -> Void
    var ausblenden: () -> Void

    var body: some View {
        let liste = FreigabeListe.vorschlaege(model.catalog)
        HStack(spacing: 10) {
            Image(systemName: "checkmark.seal")
                .font(.title3)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 1) {
                Text(FreigabeListe.bandText(liste.count))
                    .font(.headline)
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                Text(InventoryBanner.list(liste.map(\.name)) + " · von Claude vorgeschlagen, verbaubar nach deiner Freigabe")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: 12)
            Button("Freigeben …", action: oeffnen)
                .help("Vorschläge ansehen (Daten, Link) und freigeben")
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("freigabe-band-oeffnen")
            Button(action: ausblenden) {
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 18, height: 18)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.borderless)
            .help("Band ausblenden, bis neue Vorschläge kommen")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(.regularMaterial)
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.orange.opacity(0.05)))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Color.orange.opacity(0.4), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.14), radius: 10, y: 3)
        }
        .frame(maxWidth: 820)
    }
}

/// Dialog und Öffnen bei einer Anfrage von Claude; hängt am Projektfenster.
struct FreigabeDialogModifier: ViewModifier {
    @ObservedObject var model: AppModel
    @ObservedObject var state: ProjectWindowState

    func body(content: Content) -> some View {
        content
            .sheet(isPresented: $state.freigabeOffen, onDismiss: { model.freigabeActions?.freigabeSchliessen() }) {
                FreigabeSheet(model: model) { state.freigabeOffen = false }
            }
            .onChange(of: model.freigabe.anfrage?.anfrage) { _, neu in
                if neu != nil { state.freigabeOffen = true }
            }
            .onAppear {
                if model.freigabe.anfrage != nil { state.freigabeOffen = true }
            }
    }
}

/// „Vorschläge freigeben“: angefragte Vorschläge oben, je Eintrag Vorschau, Link und „Freigeben“, unten „Alle …“.
struct FreigabeSheet: View {
    @EnvironmentObject private var session: AppSession
    @ObservedObject var model: AppModel
    var schliessen: () -> Void

    private var anfrage: FreigabeAnfrage? { model.freigabe.anfrage }
    private var liste: [FreigabeVorschlag] {
        FreigabeListe.vorschlaege(model.catalog, angefragt: anfrage?.eintraege.map(\.id) ?? [])
    }

    var body: some View {
        VStack(spacing: 0) {
            kopf
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
            Divider()
            if let fehler = model.freigabe.fehler {
                fehlerBox(fehler)
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
            }
            inhalt
            Divider()
            fuss
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
        }
        .frame(width: 640, height: 560)
        .onAppear {
            if model.catalog == nil { model.catalogActions?.requestCatalog(query: nil, art: nil) }
        }
    }

    private var kopf: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "checkmark.seal.fill")
                .font(.title)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 3) {
                Text("Vorschläge freigeben").font(.title3.weight(.semibold))
                if let a = anfrage {
                    Text("Claude bittet um Freigabe" + (a.grund.map { ": \($0)" } ?? "."))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("Von Claude vorgeschlagen. Verbauen lässt sich ein Eintrag erst nach deiner Freigabe.")
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private func fehlerBox(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Spacer(minLength: 4)
            Button {
                model.freigabeActions?.freigabeFehlerVerwerfen()
            } label: {
                Image(systemName: "xmark").font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderless)
            .help("Meldung ausblenden")
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.red.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(Color.red.opacity(0.35)))
    }

    @ViewBuilder
    private var inhalt: some View {
        if model.catalog == nil {
            VStack(spacing: 8) {
                ProgressView()
                Text("Lagerkatalog wird geladen …").foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if liste.isEmpty {
            VStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill").font(.largeTitle).foregroundStyle(.green)
                Text("Keine Vorschläge offen").font(.headline)
                if !model.freigabe.freigegeben.isEmpty {
                    Text("Freigegeben: " + model.freigabe.freigegeben.map(name).joined(separator: ", "))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if !model.freigabe.freigegeben.isEmpty {
                        Label("Freigegeben: " + model.freigabe.freigegeben.map(name).joined(separator: ", "),
                              systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                    ForEach(liste) { v in
                        FreigabeKarte(model: model, vorschlag: v) {
                            session.showCatalog(focus: v.kind == "material" ? .material(v.id) : .item(v.id))
                        }
                    }
                }
                .padding(20)
            }
        }
    }

    private func name(_ id: String) -> String {
        model.catalog?.item(id)?.name ?? model.catalog?.material(id)?.name
            ?? anfrage?.eintraege.first { $0.id == id }?.name ?? id
    }

    /// Mit Anfrage: die angefragten, sonst alle offenen Vorschläge.
    private var alle: [FreigabeEintrag] {
        let angefragt = liste.filter(\.angefragt)
        return (angefragt.isEmpty ? liste : angefragt).map(\.eintrag)
    }

    private var fuss: some View {
        HStack {
            if model.freigabe.beschaeftigt {
                ProgressView().controlSize(.small)
                Text("Wird freigegeben …").foregroundStyle(.secondary)
            }
            Spacer()
            Button("Schließen", action: schliessen)
                .keyboardShortcut(.cancelAction)
            Button(alle.count == liste.count ? "Alle freigeben (\(alle.count))" : "Angefragte freigeben (\(alle.count))") {
                model.freigabeActions?.freigeben(alle)
            }
            .buttonStyle(.borderedProminent)
            .disabled(alle.isEmpty || model.freigabe.beschaeftigt || model.freigabeActions == nil)
            .accessibilityIdentifier("freigabe-alle")
        }
    }
}

/// Ein Vorschlag: Art, Name, id, Ebene, Daten, Link und „Freigeben“.
private struct FreigabeKarte: View {
    @ObservedObject var model: AppModel
    var vorschlag: FreigabeVorschlag
    var imKatalog: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                ArtTile(art: vorschlag.kind == "material" ? "platte" : vorschlag.art, size: 28,
                        tint: vorschlag.angefragt ? .orange : .accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(vorschlag.name).font(.headline).lineLimit(2)
                        if vorschlag.angefragt { Badge(text: "angefragt", color: .orange) }
                    }
                    Text([vorschlag.artTitel, vorschlag.id, "Ebene " + vorschlag.ebene.title,
                          vorschlag.vorgeschlagenAm.map { "vorgeschlagen am \($0)" }]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                Spacer(minLength: 8)
                if model.freigabe.wartet(vorschlag.id) {
                    ProgressView().controlSize(.small)
                } else {
                    Button("Freigeben") { model.freigabeActions?.freigeben([vorschlag.eintrag]) }
                        .disabled(model.freigabeActions == nil || model.freigabe.beschaeftigt)
                        .accessibilityIdentifier("freigabe-\(vorschlag.id)")
                }
            }
            if !vorschlag.zeilen.isEmpty {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 3) {
                    ForEach(Array(vorschlag.zeilen.enumerated()), id: \.offset) { _, z in
                        GridRow {
                            Text(z.titel).foregroundStyle(.secondary)
                            Text(z.wert).textSelection(.enabled)
                        }
                    }
                }
                .font(.callout)
                .padding(.leading, 38)
            }
            HStack(spacing: 14) {
                if let link = vorschlag.link {
                    Link(destination: link) {
                        Label(link.host?.replacingOccurrences(of: "www.", with: "") ?? link.absoluteString,
                              systemImage: "arrow.up.right.square")
                    }
                    .help(link.absoluteString)
                }
                Button("Im Lagerkatalog bearbeiten …", action: imKatalog)
                    .buttonStyle(.link)
                    .help("Vor dem Freigeben anpassen oder ablehnen")
            }
            .font(.callout)
            .padding(.leading, 38)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.04)))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(vorschlag.angefragt ? Color.orange.opacity(0.45) : Color.primary.opacity(0.08))
        )
    }
}
