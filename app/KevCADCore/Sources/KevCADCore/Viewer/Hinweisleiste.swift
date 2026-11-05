import OCCTSwiftViewport
import SwiftUI

/// Schmale Leiste am unteren Rand des Viewports wie Blenders Statusleiste: zeigt je Zustand, was Maustasten,
/// Trackpad und Sondertasten gerade tun. Inhalt aus Tastenbelegung.swift. Rechts der Maßstab und „?“ für alle Tasten.
/// Steht die Maus nicht über dem Viewport und passiert nichts, tritt sie zurück.
struct Hinweisleiste: View {
    @ObservedObject var eingabe: ViewerEingabe
    @ObservedObject var model: AppModel
    @ObservedObject var viewer: ViewerStore
    @ObservedObject var viewport: ViewportController
    let groesse: CGSize
    let actions: ViewerActions?

    private struct Eintrag: Identifiable {
        var tasten: [String]
        var maus: MausBelegung.Geraet?
        var text: String
        var id: String { tasten.joined() + (maus?.rawValue ?? "") + text }
    }

    var body: some View {
        let alle = eintraege
        HStack(spacing: 14) {
            // Links so viele Einträge wie passen (die wichtigsten zuerst); rechts fest Zustand, Maßstab, Tasten
            ViewThatFits(in: .horizontal) {
                eintragsZeile(alle)
                eintragsZeile(Array(alle.prefix(5)))
                eintragsZeile(Array(alle.prefix(4)))
                eintragsZeile(Array(alle.prefix(3)))
                eintragsZeile(Array(alle.prefix(2)))
                eintragsZeile(Array(alle.prefix(1)))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if let zustand = zustandsText, groesse.width > 560 {
                Text(zustand)
                    .foregroundStyle(ViewerStil.textLeise)
                    .lineLimit(1)
                    .fixedSize()
            }
            if groesse.width > 420 { Massstab(viewport: viewport, hoehe: groesse.height) }
            Button {
                actions?.ausfuehren(.tastenuebersicht)
            } label: {
                HStack(spacing: 4) {
                    TastenKappe(text: "?")
                    if groesse.width > 700 { Text("Tasten").foregroundStyle(ViewerStil.textLeise) }
                }
            }
            .buttonStyle(.plain)
            .help("Alle Tasten (?)")
        }
        .font(ViewerStil.schrift)
        .padding(.horizontal, 10)
        .frame(height: ViewerStil.hoeheLeiste)
        .frame(maxWidth: max(groesse.width - 20, 0))
        .background(RoundedRectangle(cornerRadius: ViewerStil.radiusLeiste).fill(ViewerStil.leisteGrund))
        .overlay(RoundedRectangle(cornerRadius: ViewerStil.radiusLeiste).strokeBorder(ViewerStil.leisteRand))
        .clipped()
        .opacity(eingabe.mausImViewport || eingabe.navigation != nil || model.measureMode ? 1 : 0.45)
        .animation(.easeOut(duration: 0.15), value: eingabe.mausImViewport)
    }

    private func eintragsZeile(_ liste: [Eintrag]) -> some View {
        HStack(spacing: 14) {
            ForEach(liste) { e in
                HStack(spacing: 5) {
                    if let m = e.maus { MausSymbol(geraet: m) }
                    ForEach(e.tasten, id: \.self) { TastenKappe(text: $0) }
                    Text(e.text).foregroundStyle(ViewerStil.text).lineLimit(1).fixedSize()
                }
            }
        }
    }

    /// Rechts: Auswahlmodus, Darstellung, lokale Ansicht.
    private var zustandsText: String? {
        var teile: [String] = []
        teile.append(model.selectionMode == .parts ? "Teile" : "Flächen und Kanten")
        if viewer.shading != .solid { teile.append(viewer.shading.titel) }
        if viewer.lokaleAnsicht { teile.append("Lokale Ansicht") }
        if case .navigation = viewer.aufnahme { teile.append("● Aufnahme") }
        return teile.joined(separator: " · ")
    }

    private var eintraege: [Eintrag] {
        // Während einer Bewegung: was gerade passiert und was die Sondertasten daraus machen
        if let n = eingabe.navigation {
            switch n {
            case .drehen:
                return [Eintrag(tasten: [], maus: .mitte, text: "Drehen um den Punkt unter der Maus"),
                        Eintrag(tasten: ["⇧"], maus: nil, text: "Verschieben"),
                        Eintrag(tasten: ["⌃"], maus: nil, text: "Zoomen")]
            case .verschieben:
                return [Eintrag(tasten: [], maus: .mitte, text: "Verschieben"),
                        Eintrag(tasten: ["Loslassen"], maus: nil, text: "Ende")]
            case .zoomen:
                return [Eintrag(tasten: [], maus: .rad, text: "Zoomen zur Maus")]
            case .rahmen:
                return [Eintrag(tasten: [], maus: .links, text: "Rahmen aufziehen"),
                        Eintrag(tasten: ["⇧"], maus: nil, text: "ergänzt"),
                        Eintrag(tasten: ["⌃"], maus: nil, text: "zieht ab")]
            case .griff:
                return [Eintrag(tasten: [], maus: .links, text: "Griff ziehen"),
                        Eintrag(tasten: ["⌘"], maus: nil, text: "ohne Einrasten")]
            }
        }
        let zustand: MausBelegung.Zustand = model.measureMode ? .messen : .auswahl
        let mods = eingabe.mods.subtracting(.befehl)
        var out: [Eintrag] = []
        for m in Tastenbelegung.maus where m.mods == mods && (m.zustand == .immer || m.zustand == zustand) {
            // Trackpad nur ohne Sondertasten zeigen, sonst wird die Leiste zu lang
            if mods.isEmpty, m.geraet == .zweiFinger || m.geraet == .zusammenziehen { continue }
            if m.geraet == .links, m.ziehen, m.mods == .wahl { continue }
            out.append(Eintrag(tasten: m.mods.isEmpty ? [] : [m.mods.zeichen], maus: m.geraet,
                               text: m.kurz ?? m.wirkung))
        }
        if model.measureMode {
            out.insert(Eintrag(tasten: ["Esc"], maus: nil, text: "Ende"), at: min(2, out.count))
            if eingabe.messZiele == 1 {
                out.insert(Eintrag(tasten: ["↩"], maus: nil, text: "Allein messen"), at: min(1, out.count))
            }
            if let u = eingabe.unterMaus { out.insert(Eintrag(tasten: [], maus: nil, text: u), at: 0) }
        } else if mods.isEmpty {
            out.insert(Eintrag(tasten: ["Z"], maus: nil, text: "Darstellung"), at: min(4, out.count))
            out.insert(Eintrag(tasten: ["^"], maus: nil, text: "Ansicht"), at: min(5, out.count))
        }
        return out
    }
}

/// Kleine Tastenkappe („⇧“, „Esc“, „1“).
struct TastenKappe: View {
    let text: String

    var body: some View {
        Text(text)
            .font(ViewerStil.schriftTaste)
            .foregroundStyle(ViewerStil.text)
            .padding(.horizontal, 5)
            .frame(minWidth: 18, minHeight: 16)
            .background(RoundedRectangle(cornerRadius: ViewerStil.radiusTaste).fill(ViewerStil.tasteGrund))
            .overlay(RoundedRectangle(cornerRadius: ViewerStil.radiusTaste).strokeBorder(ViewerStil.tasteRand))
    }
}

/// Maus mit hervorgehobener Taste (links, Mitte, rechts, Rad) bzw. Trackpad, wie in Blenders Statusleiste.
struct MausSymbol: View {
    let geraet: MausBelegung.Geraet

    var body: some View {
        switch geraet {
        case .zweiFinger, .zusammenziehen:
            Image(systemName: geraet == .zweiFinger ? "hand.draw" : "arrow.up.left.and.arrow.down.right")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(ViewerStil.text)
                .frame(width: 14)
        default:
            Canvas { ctx, size in
                let r = CGRect(x: 1, y: 0.5, width: size.width - 2, height: size.height - 1)
                let koerper = Path(roundedRect: r, cornerRadius: r.width / 2)
                ctx.stroke(koerper, with: .color(ViewerStil.text), lineWidth: 1)
                let teilung = r.minY + r.height * 0.42
                var linie = Path()
                linie.move(to: CGPoint(x: r.minX, y: teilung))
                linie.addLine(to: CGPoint(x: r.maxX, y: teilung))
                linie.move(to: CGPoint(x: r.midX, y: r.minY))
                linie.addLine(to: CGPoint(x: r.midX, y: teilung))
                ctx.stroke(linie, with: .color(ViewerStil.text.opacity(0.6)), lineWidth: 0.8)
                let akzent = ViewerStil.akzent
                switch geraet {
                case .links:
                    ctx.fill(Path(CGRect(x: r.minX + 1, y: r.minY + 1, width: r.width / 2 - 1.5, height: teilung - r.minY - 1.5)),
                             with: .color(akzent))
                case .rechts:
                    ctx.fill(Path(CGRect(x: r.midX + 0.5, y: r.minY + 1, width: r.width / 2 - 1.5, height: teilung - r.minY - 1.5)),
                             with: .color(akzent))
                case .mitte, .rad:
                    ctx.fill(Path(roundedRect: CGRect(x: r.midX - 1.5, y: r.minY + 2, width: 3, height: 5), cornerRadius: 1.5),
                             with: .color(akzent))
                default:
                    break
                }
            }
            .frame(width: 10, height: 15)
        }
    }
}

/// Maßstab: so viele mm entsprechen dem Balken (runde Werte 1, 2, 5 × 10ⁿ).
struct Massstab: View {
    @ObservedObject var viewport: ViewportController
    let hoehe: CGFloat

    var body: some View {
        let c = viewport.cameraState
        let mmJePunkt = c.isOrthographic
            ? Double(c.orthographicScale) / Double(max(hoehe, 1))
            : 2 * Double(c.distance) * tan(Double(c.fieldOfView) * .pi / 360) / Double(max(hoehe, 1))
        let (mm, breite) = Self.runden(mmJePunkt: mmJePunkt, zielBreite: 60)
        HStack(spacing: 5) {
            ZStack(alignment: .bottom) {
                Rectangle().fill(ViewerStil.text).frame(width: breite, height: 1.2)
                HStack {
                    Rectangle().fill(ViewerStil.text).frame(width: 1.2, height: 5)
                    Spacer(minLength: 0)
                    Rectangle().fill(ViewerStil.text).frame(width: 1.2, height: 5)
                }
                .frame(width: breite)
            }
            .frame(height: 6)
            Text(Self.text(mm) + (c.isOrthographic ? "" : " ≈"))
                .foregroundStyle(ViewerStil.textLeise)
                .monospacedDigit()
                .fixedSize()
        }
        .help(c.isOrthographic ? "Maßstab (parallel, exakt)" : "Maßstab in der Ebene des Drehpunkts")
    }

    static func runden(mmJePunkt: Double, zielBreite: Double) -> (Double, CGFloat) {
        guard mmJePunkt.isFinite, mmJePunkt > 0 else { return (0, 0) }
        let roh = mmJePunkt * zielBreite
        let p = pow(10, floor(log10(roh)))
        let wert = [1.0, 2, 5, 10].map { $0 * p }.last { $0 <= roh } ?? p
        return (wert, CGFloat(wert / mmJePunkt))
    }

    static func text(_ mm: Double) -> String {
        if mm >= 1000 { return GermanFormat.number(mm / 1000, decimals: mm >= 10_000 ? 0 : 1) + " m" }
        if mm >= 1 { return GermanFormat.number(mm, decimals: 0) + " mm" }
        return GermanFormat.number(mm, decimals: mm >= 0.1 ? 1 : 2) + " mm"
    }
}
