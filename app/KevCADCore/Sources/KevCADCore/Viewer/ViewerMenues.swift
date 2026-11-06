import SwiftUI

/// Kreismenü an der Maus wie Blenders Pie-Menüs: ^ für Ansichten, Z für die Darstellung. Ein Klick wählt, ein Klick
/// daneben oder Esc schließt; die Tasten der Einträge wirken weiter.
struct ViewerMenueOverlay: View {
    @ObservedObject var viewer: ViewerStore
    let groesse: CGSize
    let actions: ViewerActions?
    let orthographisch: Bool

    var body: some View {
        if let menue = viewer.menue {
            ZStack {
                // Klick daneben schließt
                Color.black.opacity(0.001)
                    .contentShape(Rectangle())
                    .onTapGesture { viewer.menue = nil }
                Torte(eintraege: eintraege(menue), zusatz: zusatz(menue),
                      titel: menue == .ansicht ? "Ansicht" : "Darstellung") { [viewer] in viewer.menue = nil }
                    .position(mitte)
            }
            .frame(width: groesse.width, height: groesse.height)
            .transition(.opacity.combined(with: .scale(scale: 0.96)))
            .beiEsc { viewer.menue = nil }
        }
    }

    /// Mittelpunkt so, dass das Menü im Viewport bleibt.
    private var mitte: CGPoint {
        let rx: CGFloat = 190, ry: CGFloat = 150
        return CGPoint(x: min(max(viewer.menuePunkt.x, rx), max(rx, groesse.width - rx)),
                       y: min(max(viewer.menuePunkt.y, ry), max(ry, groesse.height - ry - 40)))
    }

    private func befehl(_ b: ViewerBefehl, _ symbol: String, aktiv: Bool = false, titel: String? = nil) -> TortenEintrag {
        let bel = Tastenbelegung.belegung(b)
        return TortenEintrag(titel: titel ?? bel?.titel ?? b.rawValue, symbol: symbol,
                             taste: bel?.tasten.first?.anzeige, aktiv: aktiv) { [actions] in actions?.ausfuehren(b) }
    }

    private func modus(_ m: ShadingModus) -> TortenEintrag {
        TortenEintrag(titel: m.titel, symbol: m.symbol, taste: m == .roentgen ? "⌥Z" : nil, aktiv: viewer.shading == m) {
            [actions] in actions?.setShading(m)
        }
    }

    /// Acht Plätze: W, O, S, N, NW, NO, SW, SO (wie Blender).
    private func eintraege(_ m: ViewerMenue) -> [TortenEintrag?] {
        switch m {
        case .ansicht:
            return [befehl(.links, "arrow.left.to.line"), befehl(.rechts, "arrow.right.to.line"),
                    befehl(.unten, "arrow.down.to.line"), befehl(.oben, "arrow.up.to.line"),
                    befehl(.vorne, "square"), befehl(.hinten, "square.dashed"),
                    befehl(.allesEinrahmen, "arrow.up.left.and.arrow.down.right"),
                    befehl(.auswahlEinrahmen, "scope")]
        case .darstellung:
            return [modus(.drahtgitter), modus(.solid), modus(.material), modus(.technisch), modus(.roentgen),
                    nil, nil, nil]
        }
    }

    private func zusatz(_ m: ViewerMenue) -> [TortenEintrag] {
        switch m {
        case .ansicht:
            return [befehl(.projektion, orthographisch ? "perspective" : "square.grid.3x3", aktiv: orthographisch,
                           titel: orthographisch ? "Perspektive" : "Parallel"),
                    befehl(.gegenseite, "arrow.triangle.2.circlepath"),
                    befehl(.kameraBlick, "camera", titel: "Kamera")]
        case .darstellung:
            return ShadingOption.allCases.map { o in
                TortenEintrag(titel: o.kurz, symbol: o.wert(viewer.optionen) ? "checkmark.circle.fill" : "circle",
                              taste: nil, aktiv: o.wert(viewer.optionen), schliesst: false) { [actions, viewer] in
                    actions?.setShadingOption(o, !o.wert(viewer.optionen))
                }
            }
        }
    }
}

struct TortenEintrag {
    var titel: String
    var symbol: String
    var taste: String?
    var aktiv = false
    var schliesst = true
    var aktion: () -> Void
}

private struct Torte: View {
    let eintraege: [TortenEintrag?]
    let zusatz: [TortenEintrag]
    let titel: String
    let schliessen: () -> Void

    /// Richtungen der acht Plätze (W, O, S, N, NW, NO, SW, SO), y nach unten.
    private static let richtungen: [CGPoint] = [
        CGPoint(x: -1, y: 0), CGPoint(x: 1, y: 0), CGPoint(x: 0, y: 1), CGPoint(x: 0, y: -1),
        CGPoint(x: -0.72, y: -0.72), CGPoint(x: 0.72, y: -0.72), CGPoint(x: -0.72, y: 0.72), CGPoint(x: 0.72, y: 0.72),
    ]

    var body: some View {
        ZStack {
            Circle()
                .fill(ViewerStil.leisteGrund)
                .frame(width: 34, height: 34)
                .overlay(Circle().strokeBorder(ViewerStil.leisteRand))
                .overlay(Circle().fill(ViewerStil.akzent).frame(width: 6, height: 6))
            ForEach(Array(eintraege.enumerated()), id: \.offset) { i, e in
                if let e {
                    TortenKnopf(eintrag: e, schliessen: schliessen)
                        .offset(x: Self.richtungen[i].x * 125, y: Self.richtungen[i].y * 92)
                }
            }
            VStack(spacing: 6) {
                Text(titel)
                    .font(ViewerStil.schriftFett)
                    .foregroundStyle(ViewerStil.textLeise)
                HStack(spacing: 6) {
                    ForEach(Array(zusatz.enumerated()), id: \.offset) { _, e in
                        TortenKnopf(eintrag: e, schliessen: schliessen)
                    }
                }
            }
            .offset(y: 150)
        }
        .frame(width: 380, height: 300)
        .font(ViewerStil.schrift)
    }
}

private struct TortenKnopf: View {
    let eintrag: TortenEintrag
    let schliessen: () -> Void
    @State private var ueber = false

    var body: some View {
        Button {
            eintrag.aktion()
            if eintrag.schliesst { schliessen() }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: eintrag.symbol)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(eintrag.aktiv ? ViewerStil.akzent : ViewerStil.text)
                    .frame(width: 14)
                Text(eintrag.titel)
                    .foregroundStyle(ViewerStil.text)
                    .lineLimit(1)
                    .fixedSize()
                if let t = eintrag.taste { TastenKappe(text: t) }
            }
            .padding(.horizontal, 10)
            .frame(height: 26)
            .background(Capsule().fill(ueber ? ViewerStil.akzent.opacity(0.35) : ViewerStil.leisteGrund))
            .overlay(Capsule().strokeBorder(eintrag.aktiv ? ViewerStil.akzent.opacity(0.8) : ViewerStil.leisteRand))
        }
        .buttonStyle(.plain)
        .onHover { ueber = $0 }
    }
}
