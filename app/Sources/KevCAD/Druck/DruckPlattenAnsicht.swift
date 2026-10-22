import KevCADCore
import SwiftUI

/// Draufsicht einer Druckplatte im Maßstab (vorn unten, wie in Bambu Studio): Raster, Sperrzone vorn links, Teile als
/// Umriss in der Farbe ihres Materials. Klick wählt das Teil im 3D-Bereich, Doppelklick passt es ein; was dort
/// ausgewählt ist, leuchtet hier auf, der Rest tritt zurück.
struct DruckPlattenBild: View {
    var platte: DruckPlatte
    var vorschau: Druckvorschau
    var farben: [String: Color]
    /// Ausgewählte Teile (Namen aus show()).
    var ausgewaehlt: Set<String>
    /// Gruppe im Detail (ihre Teile werden betont, auch ohne Auswahl im 3D).
    var gruppe: String?
    var nummern: [String: Int]
    var hover: String?
    var klick: (DruckPlattenTeil?, Int) -> Void
    var schwebt: (DruckPlattenTeil?) -> Void
    @Environment(\.colorScheme) private var schema

    var body: some View {
        GeometryReader { geo in
            let geom = DruckPlattenGeometrie(bett: vorschau.bett, in: CGRect(origin: .zero, size: geo.size), rand: 1)
            Canvas { ctx, _ in zeichne(&ctx, geom) }
                .contentShape(Rectangle())
                .gesture(SpatialTapGesture(count: 2).onEnded { e in klick(geom.treffer(platte.teile, bei: e.location), 2) })
                .simultaneousGesture(SpatialTapGesture(count: 1).onEnded { e in
                    klick(geom.treffer(platte.teile, bei: e.location), 1)
                })
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let p): schwebt(geom.treffer(platte.teile, bei: p))
                    case .ended: schwebt(nil)
                    }
                }
                .overlay(alignment: .topLeading) { tooltip(geom) }
        }
        .aspectRatio(CGFloat(vorschau.bett.breite / vorschau.bett.tiefe), contentMode: .fit)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Platte \(platte.nr), \(platte.teile.count) Teile")
    }

    private var hell: Bool { schema == .light }

    private func zeichne(_ ctx: inout GraphicsContext, _ g: DruckPlattenGeometrie) {
        let r = g.platte
        let ecke = max(3, r.width * 0.018)
        let plattenPfad = Path(roundedRect: r, cornerRadius: ecke, style: .continuous)
        // Platte: gedämpftes Grau mit leichtem Verlauf (PEI-Platte)
        let oben = hell ? Color(white: 0.925) : Color(white: 0.235)
        let unten = hell ? Color(white: 0.885) : Color(white: 0.195)
        ctx.fill(plattenPfad, with: .linearGradient(Gradient(colors: [oben, unten]), startPoint: CGPoint(x: r.midX, y: r.minY),
                                                     endPoint: CGPoint(x: r.midX, y: r.maxY)))
        // Raster: alle 10 mm fein, alle 50 mm deutlicher
        var fein = Path(), grob = Path()
        for x in g.gitter(schritt: 10).x {
            let a = g.punkt(SIMD2(x, 0)), b = g.punkt(SIMD2(x, vorschau.bett.tiefe))
            if Int(x.rounded()) % 50 == 0 { grob.move(to: a); grob.addLine(to: b) } else { fein.move(to: a); fein.addLine(to: b) }
        }
        for y in g.gitter(schritt: 10).y {
            let a = g.punkt(SIMD2(0, y)), b = g.punkt(SIMD2(vorschau.bett.breite, y))
            if Int(y.rounded()) % 50 == 0 { grob.move(to: a); grob.addLine(to: b) } else { fein.move(to: a); fein.addLine(to: b) }
        }
        let linie = hell ? Color.black : Color.white
        if r.width > 160 { ctx.stroke(fein, with: .color(linie.opacity(0.045)), lineWidth: 0.5) }
        ctx.stroke(grob, with: .color(linie.opacity(0.09)), lineWidth: 0.7)
        // Sperrzone vorn links: schraffiert
        for z in g.sperrzonen {
            let zp = Path(z)
            ctx.fill(zp, with: .color(Color.red.opacity(hell ? 0.10 : 0.16)))
            var schraffur = Path()
            var s = z.minX - z.height
            let schritt = max(2.5, g.massstab * 2.2)
            while s < z.maxX {
                schraffur.move(to: CGPoint(x: s, y: z.maxY))
                schraffur.addLine(to: CGPoint(x: s + z.height, y: z.minY))
                s += schritt
            }
            var c2 = ctx
            c2.clip(to: zp)
            c2.stroke(schraffur, with: .color(Color.red.opacity(0.45)), lineWidth: 0.6)
            ctx.stroke(zp, with: .color(Color.red.opacity(0.5)), lineWidth: 0.6)
        }
        // Teile
        let betont: (DruckPlattenTeil) -> Bool = { t in
            ausgewaehlt.contains(t.name) || (ausgewaehlt.isEmpty && gruppe != nil && t.gruppe == gruppe)
        }
        let jemandBetont = platte.teile.contains(where: betont)
        for t in platte.teile {
            let farbe = DruckFarben.platte(platte, standard: farben[vorschau.gruppe(t.gruppe ?? "")?.material
                ?? platte.material.first?.material ?? ""] ?? DruckFarben.palette[0])
            let pfad = Path(g.pfad(t.plattenUmriss))
            let an = betont(t)
            let schwach = jemandBetont && !an
            let ueber = hover == t.name
            ctx.fill(pfad, with: .color(farbe.opacity(schwach ? 0.24 : an ? 0.95 : ueber ? 0.86 : 0.74)))
            if t.ersatz {
                ctx.stroke(pfad, with: .color(farbe.opacity(schwach ? 0.4 : 1)),
                           style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
            } else {
                ctx.stroke(pfad, with: .color(farbe.opacity(schwach ? 0.45 : 1)), lineWidth: 0.9)
            }
            if an {
                ctx.stroke(pfad, with: .color(Color.accentColor), lineWidth: 2)
            }
        }
        // Nummern der Gruppen in den Umrissen
        if r.width > 120 {
            for t in platte.teile {
                guard let gid = t.gruppe ?? vorschau.gruppe(vonTeil: t.name)?.gruppe, let nr = nummern[gid] else { continue }
                let box = g.pfad(t.plattenUmriss).boundingBox
                guard box.width > 13, box.height > 11 else { continue }
                let groesse = min(12, max(8, min(box.width, box.height) * 0.38))
                let text = Text("\(nr)").font(.system(size: groesse, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                var schatten = ctx
                schatten.addFilter(.shadow(color: .black.opacity(0.35), radius: 1, x: 0, y: 0.5))
                schatten.draw(text, at: g.punkt(t.mitte))
            }
        }
        // Rand und „vorn“
        ctx.stroke(plattenPfad, with: .color(linie.opacity(hell ? 0.22 : 0.3)), lineWidth: 0.8)
    }

    @ViewBuilder
    private func tooltip(_ g: DruckPlattenGeometrie) -> some View {
        if let name = hover, let t = platte.teile.first(where: { $0.name == name }) {
            let p = g.punkt(t.mitte)
            let gr = vorschau.gruppe(vonTeil: name)
            VStack(alignment: .leading, spacing: 1) {
                Text(name.split(separator: "/").last.map(String.init) ?? name).font(.caption.weight(.semibold))
                if let gr {
                    Text([DruckFormat.gramm(gr.grammJe), DruckFormat.zeit(gr.zeitJeS), t.ersatz ? "Ersatzstück" : nil]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            .shadow(color: .black.opacity(0.15), radius: 3, y: 1)
            .fixedSize()
            .offset(x: min(max(4, p.x + 10), g.platte.maxX - 110), y: max(4, p.y - 40))
            .allowsHitTesting(false)
            .transition(.opacity)
        }
    }
}

/// Plattenbereich: eine Platte mit Blättern oder alle nebeneinander, darunter je Platte Zeit, Filament und Belegung.
struct DruckPlattenBereich: View {
    @ObservedObject var model: AppModel
    @ObservedObject var ui = DruckUI.shared
    var vorschau: Druckvorschau
    var farben: [String: Color]
    var nummern: [String: Int]

    var body: some View {
        VStack(spacing: 8) {
            kopf
            if vorschau.platten.isEmpty {
                ContentUnavailableView("Keine Platte", systemImage: "square.dashed",
                                       description: Text("Nichts angeordnet."))
            } else if ui.nebeneinander {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180, maximum: 320), spacing: 14, alignment: .top)],
                          alignment: .leading, spacing: 16) {
                    ForEach(vorschau.platten) { p in
                        karte(p, legende: false)
                    }
                }
            } else if let p = vorschau.platte(ui.platte) ?? vorschau.platten.first {
                karte(p, legende: true)
                    .id(p.nr)
                    .transition(.asymmetric(insertion: .opacity.combined(with: .scale(scale: 0.98)), removal: .opacity))
            }
        }
    }

    private var kopf: some View {
        HStack(spacing: 6) {
            Text("Platten").font(.headline)
            if vorschau.platten.count > 1 && !ui.nebeneinander {
                Text("\(min(ui.platte, vorschau.platten.count)) von \(vorschau.platten.count)")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            if vorschau.platten.count > 1 {
                if !ui.nebeneinander {
                    Button { blaettern(-1) } label: { Image(systemName: "chevron.left") }
                        .disabled(index == 0)
                        .help("Vorige Platte")
                    Button { blaettern(1) } label: { Image(systemName: "chevron.right") }
                        .disabled(index >= vorschau.platten.count - 1)
                        .help("Nächste Platte")
                }
                Toggle(isOn: Binding(get: { ui.nebeneinander },
                                     set: { an in withAnimation(.snappy(duration: 0.25)) { ui.nebeneinander = an } })) {
                    Image(systemName: "rectangle.split.3x1")
                }
                .toggleStyle(.button)
                .help("Alle Platten nebeneinander")
            }
        }
        .buttonStyle(.borderless)
        .controlSize(.small)
    }

    private var index: Int { vorschau.platten.firstIndex { $0.nr == ui.platte } ?? 0 }

    private func blaettern(_ d: Int) {
        let i = min(max(0, index + d), vorschau.platten.count - 1)
        ui.zeigePlatte(vorschau.platten[i].nr)
    }

    private func karte(_ p: DruckPlatte, legende: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            DruckPlattenBild(
                platte: p, vorschau: vorschau, farben: farben, ausgewaehlt: Set(model.selectedPartIDs), gruppe: ui.auswahl,
                nummern: nummern, hover: ui.hover,
                klick: { t, anzahl in
                    if let t {
                        ui.waehleTeil(t.name, vorschau: vorschau, model: model, einpassen: anzahl == 2)
                    } else if anzahl == 1 {
                        ui.auswahl = nil
                        model.druckActions?.druckTeileWaehlen([], einpassen: false)
                    }
                },
                schwebt: { t in if ui.hover != t?.name { ui.hover = t?.name } })
            .animation(.smooth(duration: 0.2), value: ui.hover)
            plattenZeile(p, kompakt: !legende)
            if legende { teileLegende(p) }
        }
    }

    /// Was auf der Platte liegt: Nummer, Anzahl, Name; Klick wählt die Gruppe.
    private func teileLegende(_ p: DruckPlatte) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(p.gruppen, id: \.gruppe) { eintrag in
                let g = vorschau.gruppe(eintrag.gruppe)
                Button {
                    if let g { ui.waehle(g, vorschau: vorschau, model: model) }
                } label: {
                    HStack(spacing: 6) {
                        Text(nummern[eintrag.gruppe].map(String.init) ?? "–")
                            .font(.system(size: 9, weight: .bold, design: .rounded))
                            .foregroundStyle(.white)
                            .frame(width: 15, height: 15)
                            .background(Circle().fill(farben[g?.material ?? ""] ?? DruckFarben.palette[0]))
                        Text("\(eintrag.anzahl) × \(g?.kurzname ?? DruckFormat.teilname(eintrag.gruppe))")
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        if let g { DruckAmpelPunkt(ampel: g.ampel, groesse: 6) }
                    }
                    .padding(.vertical, 2)
                    .padding(.horizontal, 4)
                    .background(RoundedRectangle(cornerRadius: 5, style: .continuous)
                        .fill(ui.auswahl == eintrag.gruppe ? Color.accentColor.opacity(0.14) : .clear))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .font(.callout)
        .padding(.top, 4)
    }

    /// Zeile unter der Platte; `kompakt` (nebeneinander): nur Zeit, Teile, Gewicht und Belegung.
    private func plattenZeile(_ p: DruckPlatte, kompakt: Bool) -> some View {
        let anteil = DruckPlattenGeometrie.auslastung(p, bett: vorschau.bett)
        let material = p.material.map { m in vorschau.summe.material.first { $0.material == m.material }?.name ?? m.material.uppercased() }
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text("Platte \(p.nr)").fontWeight(.semibold)
                if let m = p.material.first {
                    Circle().fill(DruckFarben.platte(p, standard: farben[m.material] ?? .gray)).frame(width: 7, height: 7)
                        .overlay(Circle().strokeBorder(Color.secondary.opacity(0.4), lineWidth: 0.5))
                }
                Text(material.joined(separator: ", ") + (p.farbe.map { " \($0)" } ?? "")).foregroundStyle(.secondary)
                    .help(p.farbe.map { "Farbe der Platte: \($0) (P1P ohne AMS: eine Farbe je Platte)" } ?? "")
                Spacer(minLength: 4)
                Text(DruckFormat.zeit(p.zeitS)).monospacedDigit().contentTransition(.numericText())
            }
            .font(.callout)
            HStack(spacing: 6) {
                Text(KevFormat.count(p.teile.count, one: "Teil", many: "Teile"))
                Text("·")
                Text(DruckFormat.gramm(p.gramm)).contentTransition(.numericText())
                if let k = p.kosten, !kompakt { Text("·"); Text(DruckFormat.euro(k)) }
                Spacer(minLength: 4)
                if !kompakt {
                    Gauge(value: anteil) { EmptyView() }
                        .gaugeStyle(.accessoryLinearCapacity)
                        .tint(Color.kevAkzent)
                        .frame(width: 46)
                        .controlSize(.mini)
                }
                Text(kompakt ? DruckFormat.prozent(anteil) : "\(DruckFormat.prozent(anteil)) belegt")
                    .help("\(DruckFormat.prozent(anteil)) der Platte belegt")
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
            .lineLimit(1)
            // Strang „Rest Druck“: Knopf „Gedruckt“ je Platte (bucht ihr Filament von den Spulen ab) bzw. der Stand
            GedrucktPlattenKnopf(model: model, platte: p, kompakt: kompakt)
            if !kompakt && (p.vomSlicerAngeordnet || p.hoeheMM != nil) {
                HStack(spacing: 6) {
                    if p.vomSlicerAngeordnet {
                        Label("von Bambu Studio angeordnet", systemImage: "checkmark.seal")
                    } else {
                        Label("schnell angeordnet", systemImage: "square.grid.3x3")
                    }
                    if let h = p.hoeheMM { Text("· höchstens \(KevFormat.compact(h, maxDigits: 1)) mm hoch") }
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .lineLimit(1)
            }
        }
    }
}
