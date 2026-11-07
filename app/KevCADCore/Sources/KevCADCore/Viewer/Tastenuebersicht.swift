import SwiftUI

/// Alle Tasten und Mausbelegungen des Viewers, nach Gruppen, durchsuchbar (? öffnet und schließt, Esc schließt).
/// Inhalt aus Tastenbelegung.swift.
struct Tastenuebersicht: View {
    @ObservedObject var viewer: ViewerStore
    @State private var suche = ""
    @FocusState private var suchFokus: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text("Tasten")
                    .font(ViewerStil.schriftTitel)
                    .foregroundStyle(ViewerStil.text)
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundStyle(ViewerStil.textLeise)
                    TextField("Suchen", text: $suche)
                        .textFieldStyle(.plain)
                        .foregroundStyle(ViewerStil.text)
                        .focused($suchFokus)
                }
                .padding(.horizontal, 8)
                .frame(height: 24)
                .background(RoundedRectangle(cornerRadius: 6).fill(ViewerStil.tasteGrund))
                .frame(maxWidth: 240)
                Spacer()
                Button {
                    viewer.tastenuebersicht = false
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(ViewerStil.textLeise)
                        .frame(width: 22, height: 22)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Schließen (Esc)")
            }
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 270), spacing: 22, alignment: .top)],
                          alignment: .leading, spacing: 16) {
                    ForEach(gruppen, id: \.0) { titel, zeilen in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(titel)
                                .font(ViewerStil.schriftFett)
                                .foregroundStyle(ViewerStil.textLeise)
                            ForEach(zeilen, id: \.id) { z in
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    HStack(spacing: 3) {
                                        if let m = z.maus { MausSymbol(geraet: m) }
                                        ForEach(z.tasten, id: \.self) { TastenKappe(text: $0) }
                                    }
                                    .frame(minWidth: 54, alignment: .leading)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(z.titel).foregroundStyle(ViewerStil.text)
                                        if let e = z.erklaerung {
                                            Text(e).foregroundStyle(ViewerStil.textLeise).font(.system(size: 10.5))
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(.vertical, 2)
            }
            if gruppen.isEmpty {
                Text("Keine Taste passt zu „\(suche)“.")
                    .foregroundStyle(ViewerStil.textLeise)
            }
            Text("Ziffern der oberen Reihe wirken wie der Ziffernblock, solange der Viewport den Fokus hat.")
                .font(.system(size: 10.5))
                .foregroundStyle(ViewerStil.textLeise)
        }
        .font(ViewerStil.schrift)
        .padding(16)
        .frame(maxWidth: 720, maxHeight: 520)
        .background(RoundedRectangle(cornerRadius: ViewerStil.radiusKarte).fill(ViewerStil.leisteGrund.opacity(0.98)))
        .overlay(RoundedRectangle(cornerRadius: ViewerStil.radiusKarte).strokeBorder(ViewerStil.leisteRand))
        .shadow(color: .black.opacity(0.35), radius: 18, y: 6)
        .beiEsc { viewer.tastenuebersicht = false }
    }

    private struct Zeile {
        var id: String
        var tasten: [String]
        var maus: MausBelegung.Geraet?
        var titel: String
        var erklaerung: String?
    }

    private var gruppen: [(String, [Zeile])] {
        let q = suche.trimmingCharacters(in: .whitespaces).lowercased()
        func passt(_ texte: [String]) -> Bool { q.isEmpty || texte.contains { $0.lowercased().contains(q) } }
        var out: [(String, [Zeile])] = []
        #if os(iOS)
        // iPad: Finger und Stift zuerst (Tastenbelegung.gesten), dann Maus und Trackpad für Magic Keyboard und Maus
        let gesten = Tastenbelegung.gesten.filter { passt([$0.wirkung, $0.eingabe]) }.map { g in
            Zeile(id: "geste-" + g.id, tasten: [g.geste.rawValue], maus: nil, titel: g.wirkung,
                  erklaerung: g.eingabe + (g.zustand == .messen ? " · im Messmodus"
                                           : g.zustand == .sprechen ? " · beim Sprechen" : ""))
        }
        if !gesten.isEmpty { out.append(("Finger und Stift", gesten)) }
        #endif
        // Maus und Trackpad zuerst
        let maus = Tastenbelegung.maus.filter { passt([$0.wirkung, $0.eingabe]) }.map { m in
            Zeile(id: m.id, tasten: m.mods.isEmpty ? [] : [m.mods.zeichen], maus: m.geraet, titel: m.wirkung,
                  erklaerung: m.eingabe + (m.zustand == .messen ? " · im Messmodus"
                                           : m.zustand == .sprechen ? " · beim Sprechen" : ""))
        }
        if !maus.isEmpty { out.append(("Maus und Trackpad", maus)) }
        for g in BelegungsGruppe.allCases {
            let zeilen = Tastenbelegung.alle.filter { $0.gruppe == g }
                .filter { b in passt([b.titel, b.erklaerung ?? ""] + b.tasten.map(\.anzeige)) }
                .map { b in Zeile(id: b.befehl.rawValue, tasten: b.tasten.map(\.anzeige), maus: nil, titel: b.titel,
                                  erklaerung: b.erklaerung) }
            if !zeilen.isEmpty { out.append((g.rawValue, zeilen)) }
        }
        return out
    }
}
