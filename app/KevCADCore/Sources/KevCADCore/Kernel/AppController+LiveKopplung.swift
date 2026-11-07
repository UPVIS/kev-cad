import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

// I-6 Live-Kopplung (PLAN-IPAD.md, Abschnitt 5; PROTOCOL.md, „I-6 Live-Kopplung“). Gleicher Code auf Mac und iPad:
// - Gemeinsame Ansicht: Ein Takt (60 je Sekunde, solange ein anderes Gerät mitschaut) vergleicht Kamera, Sicht,
//   Auswahl, Darstellung, Schnitt und Explosion mit dem zuletzt geteilten Stand und schickt, was Kevin hier geändert
//   hat. Was von einem anderen Gerät kommt, übernimmt die App (Kamera weich, Rest sofort) und schickt es nicht zurück.
// - Führung: Fasst Kevin hier an (EingabeBeobachter.swift), trägt die nächste ANSICHT `griff`; der Kernel gibt dann
//   diesem Gerät die Führung. Seine Hand geht vor: Während er hier bedient, folgt die App keinem anderen Gerät.
// - AKTIV (I-2): höchstens einmal je Sekunde, solange Kevin hier bedient und ein anderes Gerät verbunden ist.
// - Sprechen: Striche, Zeiger und Text der eigenen Sitzung gehen live an die anderen Geräte (20 je Sekunde), Striche
//   der anderen erscheinen hier im Modell.

/// Zustand der Live-Kopplung je App.
@MainActor
final class LiveKopplung {
    /// Zuletzt geteilter oder übernommener Stand: Vergleich für die nächste ANSICHT.
    var basis = AnsichtStand()
    var letzteEingabe: CFTimeInterval = -10
    /// Die nächste ANSICHT trägt `griff` (Kevin hat hier eben angefasst).
    var griffOffen = false
    var aktivGesendet: CFTimeInterval = -10
    /// Bis dahin übernimmt die App einen fremden Stand (keine eigene ANSICHT).
    var folgtBis: CFTimeInterval = 0
    var takt: Timer?
    var tick = 0
    /// Verzögerung vom Senden am anderen Gerät bis hier (ms), die letzten 60.
    var latenzen: [Double] = []
    // Sprechen live: was schon draußen ist
    var liveSitzung: String?
    var liveStriche: [Int: Int] = [:]
    var liveZeiger: [Double]?
    var liveText: String?
    var liveGesendet: CFTimeInterval = 0
    /// Striche, Zeiger und Text der anderen Geräte (nach Verbindungsnummer).
    var fremd: [Int: FremdesSprechen] = [:]
    /// Schmales Fenster: diese Kachel zeigt das Gerät groß, obwohl geteilt keine groß ist (geteilt bleibt nil).
    var flaecheAnpassung: KachelArt?

    /// Solange gilt eine Eingabe als „Kevin bedient hier“ (Sekunden).
    static let bedientFenster: CFTimeInterval = 0.35
    /// Ab so langer Pause beginnt ein neuer Griff.
    static let griffPause: CFTimeInterval = 0.5
}

/// Was ein anderes Gerät beim Sprechen gerade zeigt.
struct FremdesSprechen {
    var sitzung: String
    var striche: [Int: [SIMD3<Float>]] = [:]
    var zeiger: SIMD3<Float>?
    var text: String?
}

extension AppController {
    // MARK: Verbindung

    /// Verbindung steht (nach HELLO_APP): Ansicht melden, Eingaben beobachten.
    func kopplungVerbindungSteht() {
        let k = liveKopplung
        k.basis = AnsichtStand()
        k.griffOffen = false
        k.fremd = [:]
        send(AnsichtModusMessage(modus: model.kopplung.modus))
        if viewport.onEingabe == nil {
            viewport.onEingabe = { [weak self] in self?.lokaleEingabe() }
        }
    }

    func kopplungVerbindungWeg() {
        model.kopplung.liveGeraete = []
        liveKopplung.fremd = [:]
        liveKopplung.liveSitzung = nil
        kopplungTaktPruefen()
        refreshOverlay()
    }

    public func ansichtModus(_ modus: AnsichtModus) {
        guard modus != model.kopplung.modus else { return }
        model.kopplung.modus = modus
        UserDefaults.standard.set(modus.rawValue, forKey: KopplungsStore.modusSchluessel)
        liveKopplung.basis = AnsichtStand()  // beim Wechsel in die Gemeinsame Ansicht kommt der Stand des Führenden
        liveKopplung.griffOffen = false
        if connected { send(AnsichtModusMessage(modus: modus)) }
        log(.info, modus == .gemeinsam ? "Gemeinsame Ansicht" : "Eigene Ansicht")
        kopplungTaktPruefen()
    }

    func handleKopplung(_ k: KopplungNachricht) {
        switch k {
        case .geraete(let g):
            let vorher = model.kopplung.liveGeraete
            model.kopplung.liveGeraete = g.geraete
            // Geräte, die gegangen sind, nehmen ihre Striche mit
            let da = Set(g.geraete.map(\.nr))
            if liveKopplung.fremd.keys.contains(where: { !da.contains($0) }) {
                liveKopplung.fremd = liveKopplung.fremd.filter { da.contains($0.key) }
                refreshOverlay()
            }
            if vorher.map(\.nr) != g.geraete.map(\.nr) { liveKopplung.liveStriche = [:] }  // neu dazu: alles neu schicken
            kopplungTaktPruefen()
        case .ansicht(let a):
            ansichtUebernehmen(a)
        case .sprechenLive(let m):
            fremdesSprechen(m)
        }
    }

    // MARK: Eingabe

    /// Kevin bedient den Viewer dieses Geräts (jedes Ereignis): Folgen endet, Griff und AKTIV.
    func lokaleEingabe() {
        let k = liveKopplung
        let jetzt = CACurrentMediaTime()
        if jetzt - k.letzteEingabe > LiveKopplung.griffPause { k.griffOffen = true }
        k.letzteEingabe = jetzt
        k.folgtBis = 0
        viewport.folgenAbbrechen()
        if connected, model.kopplung.liveGeraete.count != 1, jetzt - k.aktivGesendet >= 1 {
            k.aktivGesendet = jetzt
            send(AktivMessage())
        }
    }

    private var kevinBedientHier: Bool {
        CACurrentMediaTime() - liveKopplung.letzteEingabe < LiveKopplung.bedientFenster
    }

    // MARK: Takt

    /// Takt an, solange es etwas zu teilen gibt: ein anderes Gerät in der Gemeinsamen Ansicht oder eine Sprachsitzung.
    func kopplungTaktPruefen() {
        let k = liveKopplung
        let faehig = live.kernelFaehigkeiten.contains(LiveFaehigkeit.ansicht)
        let noetig = connected && faehig && !model.kopplung.andere.isEmpty
        if noetig, k.takt == nil {
            let t = Timer(timeInterval: 1 / KopplungGrenzen.ansichtJeS, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.kopplungTakt() }
            }
            RunLoop.main.add(t, forMode: .common)  // auch während Maustaste oder Finger unten sind
            k.takt = t
        } else if !noetig, let t = k.takt {
            t.invalidate()
            k.takt = nil
        }
    }

    private func kopplungTakt() {
        let k = liveKopplung
        k.tick += 1
        if k.tick % 3 == 0 { sprechenLiveTakt() }  // 20 je Sekunde
        guard model.kopplung.teiltMitAnderen else { return }
        let jetzt = CACurrentMediaTime()
        let alles = k.griffOffen || k.tick % 6 == 0 || !k.basis.vollstaendig
        let stand = ansichtJetzt(alles: alles)
        if !kevinBedientHier && (viewport.folgtGerade || jetzt < k.folgtBis) {
            k.basis.uebernehmen(stand)  // Nachziehen ist keine Bedienung: nichts zurückschicken
            return
        }
        let neu = Self.unterschied(stand, zu: k.basis)
        guard !neu.leer else { return }
        let fuehrt = model.kopplung.fuehrtSelbst
        // Wer die Führung übernimmt, schickt alles; ebenso, solange noch nichts geteilt ist
        let voll = (k.griffOffen && !fuehrt) || !k.basis.vollstaendig
        let zuSenden = voll ? ansichtJetzt(alles: true) : neu
        send(AnsichtMessage(t: Date().timeIntervalSince1970, griff: k.griffOffen, voll: voll, stand: zuSenden))
        k.basis.uebernehmen(zuSenden)
        k.griffOffen = false
    }

    // MARK: Stand

    /// Stand der Ansicht hier; ohne `alles` nur die Kamera (die übrigen Teile alle 0,1 s).
    func ansichtJetzt(alles: Bool) -> AnsichtStand {
        func r(_ x: Float, _ n: Double = 1000) -> Double { (Double(x) * n).rounded() / n }
        var s = AnsichtStand()
        s.kamera = Self.kameraTeil(viewport.kameraZiel)
        guard alles else { return s }
        s.sicht = .init(verborgen: scene.order.filter { !scene.isVisible($0) }, isoliert: scene.isolated)
        s.auswahl = .init(run: scene.selection.isEmpty ? nil : scene.latestRun, refs: scene.selection.map(\.string))
        s.darstellung = lageDarstellung
        s.schnitt = .some(scene.section.map { .init(normale: [$0.normal.x, $0.normal.y, $0.normal.z].map { r($0, 1e6) },
                                                     abstand: r($0.distance)) })
        s.explosion = r(scene.explodeFactor)
        s.flaeche = flaecheJetzt()
        return s
    }

    /// Leisten und Kacheln zum Teilen. Eine Anpassung an ein schmales Fenster (große Kachel) bleibt hier: geteilt wird,
    /// was das führende Gerät gezeigt hat, bis Kevin hier selbst etwas ändert.
    func flaecheJetzt() -> AnsichtStand.Flaeche {
        let z = model.oberflaeche.zustand
        var gross = z.gross
        if let a = liveKopplung.flaecheAnpassung {
            if z.gross == a { gross = nil } else { liveKopplung.flaecheAnpassung = nil }
        }
        return .init(kacheln: z.kacheln.map(\.rawValue), gross: gross?.rawValue, aktiv: z.aktiv?.rawValue,
                     leisteLinks: z.leisteLinks, leisteRechts: z.leisteRechts, zeitleiste: z.zeitleiste,
                     zweiteAnsicht: z.zweiteAnsicht, blatt: z.blatt)
    }

    /// Ist das Fenster zu schmal für Kacheln nebeneinander?
    var fensterSchmal: Bool {
        let b = model.kopplung.fensterBreite
        return b > 0 && b < KopplungGrenzen.kachelnNebeneinanderAb
    }

    /// Leisten und Kacheln eines anderen Geräts übernehmen. Ausnahme: In einem schmalen Fenster (unter 640 pt) werden
    /// Kacheln nebeneinander zur großen Kachel (die aktive, sonst die letzte). Leisten blendet die Oberfläche unter 760 pt
    /// ohnehin aus (`Arbeitsgeometrie`), ihr Zustand geht trotzdem mit.
    func flaecheUebernehmen(_ f: AnsichtStand.Flaeche) {
        let kacheln = f.kacheln.compactMap(KachelArt.init(rawValue:))
        guard !kacheln.isEmpty else { return }
        var gross = f.gross.flatMap(KachelArt.init(rawValue:))
        let aktiv = f.aktiv.flatMap(KachelArt.init(rawValue:))
        liveKopplung.flaecheAnpassung = nil
        if fensterSchmal, gross == nil, kacheln.contains(where: { $0 != .modell }) {
            let lokal = aktiv.flatMap { kacheln.contains($0) ? $0 : nil } ?? kacheln.last ?? .modell
            liveKopplung.flaecheAnpassung = lokal
            gross = lokal
        }
        let o = model.oberflaeche
        if o.uebersicht { oberflaeche(.uebersicht(false)) }
        if o.kacheln != kacheln { oberflaeche(.kachelnOrdnen(kacheln)) }
        if o.gross != gross { oberflaeche(.kachelGross(gross)) }
        if o.aktiv != aktiv, aktiv.map(kacheln.contains) ?? true { oberflaeche(.kachelAktiv(aktiv)) }
        if o.leisteLinks != f.leisteLinks { oberflaeche(.leisteLinks(f.leisteLinks)) }
        if o.leisteRechts != f.leisteRechts { oberflaeche(.leisteRechts(f.leisteRechts)) }
        if o.zeitleiste != f.zeitleiste { oberflaeche(.zeitleiste(f.zeitleiste)) }
        if o.zweiteAnsicht != f.zweiteAnsicht, standardAnsichten.contains(f.zweiteAnsicht) {
            oberflaeche(.zweiteAnsicht(f.zweiteAnsicht))
        }
        if let b = f.blatt, o.blatt != b { oberflaeche(.blatt(b)) }
    }

    /// Kamera als Teil einer ANSICHT, gerundet (so vergleicht die App ohne Rauschen).
    static func kameraTeil(_ c: CameraState) -> AnsichtStand.Kamera {
        func r(_ x: Float, _ n: Double = 1000) -> Double { (Double(x) * n).rounded() / n }
        let q = simd_normalize(c.rotation).vector
        return .init(
            drehung: [q.x, q.y, q.z, q.w].map { r($0, 1e6) }, ziel: [c.pivot.x, c.pivot.y, c.pivot.z].map { r($0) },
            abstand: r(c.distance), projektion: c.isOrthographic ? "orthographic" : "perspective", fov: r(c.fieldOfView),
            orthoHoehe: r(max(c.orthographicScale, 0.001)))
    }

    /// Teile von `neu`, die anders sind als in `alt`.
    static func unterschied(_ neu: AnsichtStand, zu alt: AnsichtStand) -> AnsichtStand {
        var d = AnsichtStand()
        if let k = neu.kamera, k != alt.kamera { d.kamera = k }
        if let s = neu.sicht, s != alt.sicht { d.sicht = s }
        if let a = neu.auswahl, a != alt.auswahl { d.auswahl = a }
        if let x = neu.darstellung, x != alt.darstellung { d.darstellung = x }
        if let x = neu.schnitt, alt.schnitt.map({ $0 != x }) ?? true { d.schnitt = .some(x) }
        if let x = neu.explosion, x != alt.explosion { d.explosion = x }
        if let f = neu.flaeche, f != alt.flaeche { d.flaeche = f }
        return d
    }

    static func kameraState(_ k: AnsichtStand.Kamera, wie alt: CameraState) -> CameraState? {
        guard k.drehung.count == 4, k.ziel.count == 3, k.abstand > 0 else { return nil }
        var c = alt
        c.rotation = simd_normalize(simd_quatf(ix: Float(k.drehung[0]), iy: Float(k.drehung[1]), iz: Float(k.drehung[2]),
                                               r: Float(k.drehung[3])))
        c.pivot = SIMD3(Float(k.ziel[0]), Float(k.ziel[1]), Float(k.ziel[2]))
        c.distance = Float(k.abstand)
        c.fieldOfView = Float(k.fov)
        c.orthographicScale = Float(k.orthoHoehe)
        c.isOrthographic = k.projektion == "orthographic"
        c.panOffset = .zero
        return c
    }

    // MARK: Übernehmen

    /// ANSICHT eines anderen Geräts: folgen, außer Kevin bedient gerade hier oder dieses Gerät hat die Eigene Ansicht.
    func ansichtUebernehmen(_ a: AnsichtMessage) {
        guard model.kopplung.modus == .gemeinsam, !kevinBedientHier else { return }
        let k = liveKopplung
        if a.t > 0 {
            let ms = (Date().timeIntervalSince1970 - a.t) * 1000
            if ms > -5000 && ms < 60000 {
                k.latenzen.append(ms)
                if k.latenzen.count > 60 { k.latenzen.removeFirst(k.latenzen.count - 60) }
            }
        }
        k.folgtBis = CACurrentMediaTime() + 0.25
        var s = a.stand
        if let kam = s.kamera, let ziel = Self.kameraState(kam, wie: viewport.camera) {
            viewport.folge(zu: ziel, sofort: a.voll)
            s.kamera = Self.kameraTeil(ziel)  // Basis so, wie diese App die Kamera selbst rundet
        }
        var teileGeaendert = false
        if let sicht = s.sicht {
            if let iso = sicht.isoliert {
                if scene.isolated != iso { scene.isolate(iso.filter { scene.record($0) != nil }); teileGeaendert = true }
            } else {
                if scene.isolated != nil { scene.showAll(); teileGeaendert = true }
                let soll = Set(sicht.verborgen)
                let zeigen = scene.order.filter { !scene.isVisible($0) && !soll.contains($0) }
                let weg = scene.order.filter { scene.isVisible($0) && soll.contains($0) }
                if !zeigen.isEmpty { scene.setVisible(zeigen, true); teileGeaendert = true }
                if !weg.isEmpty { scene.setVisible(weg, false); teileGeaendert = true }
            }
        }
        if let f = s.flaeche { flaecheUebernehmen(f) }
        if let d = s.darstellung, d != lageDarstellung {
            if let modus = ShadingModus.allCases.first(where: { $0.protokollName == d }), Self.displayStyle(protocolName: d) == nil {
                setShading(modus)
            } else if let style = Self.displayStyle(protocolName: d) {
                darstellungUebernehmen(style)
            }
        }
        if let schnitt = s.schnitt {
            let ebene = schnitt.flatMap { $0.normale.count == 3 ? $0 : nil }
            if let e = ebene {
                applySection(enabled: true, normal: -SIMD3(Float(e.normale[0]), Float(e.normale[1]), Float(e.normale[2])),
                             offset: Float(e.abstand))
            } else if scene.section != nil {
                applySection(enabled: false, normal: nil, offset: 0)
            }
        }
        if let x = s.explosion, abs(Double(scene.explodeFactor) - x) > 1e-4 { applyExplode(x) }
        if let auswahl = s.auswahl, auswahl.refs != scene.selection.map(\.string) {
            measurePending = []
            applySelection(auswahl.refs.compactMap(ElementRef.init), notifyKernel: false)  // der Führende hat es gemeldet
        }
        if teileGeaendert {
            updateParts()
            refreshOverlay()
        }
        k.basis.uebernehmen(s)
        if a.voll { k.basis = s }
    }

    /// Median der Verzögerung (ms) vom Senden am anderen Gerät bis hier; nil ohne Messung.
    var kopplungLatenzMs: Double? {
        let l = liveKopplung.latenzen.sorted()
        return l.isEmpty ? nil : l[l.count / 2]
    }

    // MARK: Sprechen live

    /// Striche, Zeiger und Text der eigenen Sprachsitzung an die anderen Geräte (aus dem Takt, 20 je Sekunde).
    private func sprechenLiveTakt() {
        let k = liveKopplung
        guard live.kernelFaehigkeiten.contains(LiveFaehigkeit.ansicht) else { return }
        guard let s = sprache.sitzung else {
            if let alt = k.liveSitzung {  // Sitzung vorbei: die anderen nehmen die Striche weg
                send(SprechenLiveMessage(sitzung: alt, ende: true))
                k.liveSitzung = nil
                k.liveStriche = [:]
                k.liveZeiger = nil
                k.liveText = nil
            }
            return
        }
        if k.liveSitzung != s.id {
            k.liveSitzung = s.id
            k.liveStriche = [:]
            k.liveZeiger = nil
            k.liveText = nil
        }
        var striche: [SprechenLiveMessage.Strich] = []
        func punkte(_ p: [FeedbackPaket.StrichPunkt]) -> [[Double]] {
            Array(p.compactMap { $0.welt.count == 3 ? $0.welt : nil }.suffix(KopplungGrenzen.punkteMax))
        }
        for st in s.striche where k.liveStriche[st.nr] != -1 {
            striche.append(.init(nr: st.nr, punkte: punkte(st.punkte), fertig: true))
            k.liveStriche[st.nr] = -1  // fertig geschickt
        }
        if let offen = s.offenerStrich, offen.punkte.count != k.liveStriche[offen.nr], offen.punkte.count >= 2 {
            striche.append(.init(nr: offen.nr, punkte: punkte(offen.punkte), fertig: false))
            k.liveStriche[offen.nr] = offen.punkte.count
        }
        let zeiger = s.mausweg.last?.punkt
        let text = model.sprache.text.map { String($0.prefix(KopplungGrenzen.textMax)) }
        let zeigerNeu = zeiger != k.liveZeiger
        let textNeu = text != k.liveText
        guard !striche.isEmpty || zeigerNeu || textNeu else { return }
        k.liveZeiger = zeiger
        k.liveText = text
        let erster = striche.first
        send(SprechenLiveMessage(sitzung: s.id, strich: erster, zeiger: zeigerNeu ? .some(zeiger) : nil,
                                 text: textNeu ? (text ?? "") : nil))
        for rest in striche.dropFirst() { send(SprechenLiveMessage(sitzung: s.id, strich: rest)) }
    }

    /// SPRECHEN_LIVE eines anderen Geräts: Striche und Zeiger im Modell zeigen, bei `ende` wegnehmen.
    func fremdesSprechen(_ m: SprechenLiveMessage) {
        let von = m.von ?? -1
        if m.ende {
            if liveKopplung.fremd.removeValue(forKey: von) != nil { refreshOverlay() }
            return
        }
        var f = liveKopplung.fremd[von].flatMap { $0.sitzung == m.sitzung ? $0 : nil } ?? FremdesSprechen(sitzung: m.sitzung)
        func p(_ v: [Double]) -> SIMD3<Float>? { v.count == 3 ? SIMD3(Float(v[0]), Float(v[1]), Float(v[2])) : nil }
        if let st = m.strich { f.striche[st.nr] = st.punkte.compactMap(p) }
        if let z = m.zeiger { f.zeiger = z.flatMap(p) }
        if let t = m.text { f.text = t.isEmpty ? nil : t }
        liveKopplung.fremd[von] = f
        refreshOverlay()
    }

    /// Striche und Zeiger der anderen Geräte im Viewer (in der Strichfarbe, etwas blasser als die eigenen).
    func fremdesSprechenOverlay() -> [OverlayPrimitive] {
        var items: [OverlayPrimitive] = []
        let farbe = ViewerStil.strich * SIMD4(1, 1, 1, 0.75)
        for f in liveKopplung.fremd.values {
            for nr in f.striche.keys.sorted() {
                if let pkte = f.striche[nr], pkte.count >= 2 { items.append(.polyline(points: pkte, color: farbe, width: 3)) }
            }
            if let z = f.zeiger { items.append(.dot(point: z, color: farbe, radius: 5)) }
        }
        return items
    }

    // MARK: Testbefehl (Kettentest)

    /// `VIEW_CMD test_kopplung` (nur Testvarianten und Debug-Bauten): Das Gerät der Art `art` bedient eine
    /// Standardansicht wie Kevin oder wechselt die Ansicht und meldet seinen Stand als JSON. Geräte anderer Art
    /// antworten nicht (es zählt die erste Antwort). nil = nicht antworten.
    func testKopplung(_ v: ViewCommandMessage) -> (Bool, String?)? {
        // `art` steht in jeder Fassung fest: Swift prüft auch Code hinter einem frühen return, und im Release-Bau fürs
        // iPad fehlte es (TestFlight-Build 5 scheiterte daran, der Debug-Bau im Simulator nicht)
        #if os(macOS)
        let (erlaubt, art, grund) = (AppInfo.isTestVariant, "mac", "nur in Testvarianten")
        #elseif DEBUG
        let (erlaubt, art, grund) = (true, "ipad", "")
        #else
        let (erlaubt, art, grund) = (false, "ipad", "nur in Testbauten")
        #endif
        guard erlaubt else { return (false, grund) }
        guard v.args["art"]?.stringValue == art else { return nil }
        if let m = v.args["modus"]?.stringValue.flatMap(AnsichtModus.init(rawValue:)) { ansichtModus(m) }
        if let name = v.args["ansicht"]?.stringValue {
            guard let sv = ViewportCoordinator.standardView(protocolName: name) else { return (false, "Unbekannte Ansicht") }
            lokaleEingabe()
            viewport.setCamera(viewport.camera)  // wie ein Griff: Folgen endet
            viewport.apply(rotation: sv.rotation, orthographic: nil, fitTo: scene.visibleBounds(), animated: true)
        }
        let c = viewport.camera
        let stand: [String: JSONValue] = [
            "modus": .string(model.kopplung.modus.rawValue), "fuehrt": .bool(model.kopplung.fuehrtSelbst),
            "geraete": .number(Double(model.kopplung.liveGeraete.count)),
            "ansicht": ViewportCoordinator.nearestStandardName(c).map(JSONValue.string) ?? .null,
            "kamera": .array([c.rotation.vector.x, c.rotation.vector.y, c.rotation.vector.z, c.rotation.vector.w]
                .map { .number((Double($0) * 1e4).rounded() / 1e4) }),
            "latenz_ms": kopplungLatenzMs.map { .number(($0 * 10).rounded() / 10) } ?? .null,
            "messungen": .number(Double(liveKopplung.latenzen.count)),
        ]
        let text = (try? JSONEncoder().encode(JSONValue.object(stand))).flatMap { String(data: $0, encoding: .utf8) }
        return (true, text)
    }
}
