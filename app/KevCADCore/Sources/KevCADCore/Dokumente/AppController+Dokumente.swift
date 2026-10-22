import Foundation

/// Zeichnungen (DOKUMENTE.md): Übersicht (DOCS) und Blätter (DRAWING) in den DokumenteStore, Anfragen und Änderungen der
/// Oberfläche an den Kernel (DOCS_REQ, DRAWING_REQ, DRAWING_EDIT mit `von: "kevin"`).
extension AppController: DokumenteActions {
    func handleDokumente(_ m: DokumenteMessage) {
        switch m {
        case .docs(let d, _): applyDocs(d)
        case .drawing(let z, _): applyZeichnung(z)
        }
    }

    /// Neue Übersicht: Blätter mit neuem Stand neu anfordern, sofern sie schon einmal geladen waren (das alte Blatt bleibt
    /// bis zur Antwort stehen, damit nichts flackert). Blätter, die es nicht mehr gibt, fallen weg.
    func applyDocs(_ d: DocsUebersicht) {
        let store = model.dokumente
        store.uebersicht = d
        store.uebersichtLaedt = false
        let ids = Set(d.blaetter.map(\.id))
        for id in store.zeichnungen.keys where !ids.contains(id) { store.zeichnungen[id] = nil }
        for e in d.blaetter {
            if let f = e.fehler { store.fehler[e.id] = f } else { store.fehler[e.id] = nil }
            if store.zeichnungen[e.id] != nil, store.istVeraltet(e.id), !store.laedt.contains(e.id) {
                zeichnungAnfordern(e.id)
            }
        }
    }

    func applyZeichnung(_ z: Zeichnung) {
        let store = model.dokumente
        let id = z.id
        if let t = store.angefordert[id] {
            store.antwortMs[id] = Date().timeIntervalSince(t) * 1000
        }
        store.zeichnungen[id] = z
        store.laedt.remove(id)
        store.fehler[id] = nil
        // Übersicht nachziehen (Format, Maßstab, Zahl der Maße), ohne auf das nächste DOCS zu warten
        if var u = store.uebersicht, let i = u.blaetter.firstIndex(where: { $0.id == id }) {
            u.blaetter[i].titel = z.blatt.titel
            u.blaetter[i].format = z.blatt.format
            u.blaetter[i].ausrichtung = z.blatt.ausrichtung
            u.blaetter[i].massstab = z.blatt.massstab
            u.blaetter[i].masse = z.masse.count
            u.blaetter[i].verwaisteMasse = z.verwaisteMasse.count
            u.blaetter[i].stand = z.stand
            u.blaetter[i].pruefung = z.pruefung.count
            if store.uebersicht != u { store.uebersicht = u }
        }
    }

    /// Projektwechsel: Blätter des alten Projekts verwerfen.
    func resetDokumente() {
        model.dokumente.leeren()
    }

    // MARK: DokumenteActions

    public func dokumenteAnfordern() {
        let store = model.dokumente
        guard !store.uebersichtLaedt else { return }
        store.uebersichtLaedt = true
        request(DocsRequestMessage(id: nextRequestID()), timeout: 300) { [weak self] result in
            guard let self else { return }
            self.model.dokumente.uebersichtLaedt = false
            switch result {
            case .success(.dokumente(.docs(let d, _))):
                self.applyDocs(d)
            case .success(let m):
                self.log(.warning, "Dokumente: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.model.dokumente.meldung = DokumenteMeldung(text: e.message, fehler: true)
                self.log(.error, "Dokumente laden: \(e.message)")
            }
        }
    }

    public func zeichnungAnfordern(_ blatt: String) {
        let store = model.dokumente
        store.laedt.insert(blatt)
        store.angefordert[blatt] = Date()
        request(DrawingRequestMessage(id: nextRequestID(), blatt: blatt), timeout: 180) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.dokumente(.drawing(let z, _))):
                self.applyZeichnung(z)
                let ms = self.model.dokumente.antwortMs[z.id] ?? 0
                self.log(.info, "Blatt \(z.id): \(z.masse.count) Maße, \(z.anzahlPolylinien) Polylinien, "
                    + "\(z.grafik.punkte) Punkte, \(Int(ms)) ms")
            case .success(let m):
                self.model.dokumente.laedt.remove(blatt)
                self.log(.warning, "Blatt \(blatt): unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.model.dokumente.laedt.remove(blatt)
                self.model.dokumente.fehler[blatt] = e.message
                self.log(.error, "Blatt \(blatt): \(e.message)")
            }
        }
    }

    public func zeichnungBearbeiten(_ blatt: String, ops: [ZeichnungsOp],
                                    abschluss: (@MainActor (ZeichnungsBearbeitung) -> Void)?) {
        guard !ops.isEmpty else { return }
        let store = model.dokumente
        let titel = ops.count == 1 ? ops[0].titel : "\(ops.count) Änderungen"
        store.bearbeitung[blatt] = titel
        store.angefordert[blatt] = Date()
        let msg = DrawingEditMessage(id: nextRequestID(), blatt: blatt, ops: ops, von: "kevin")
        request(msg, timeout: 180) { [weak self] result in
            guard let self else { return }
            let store = self.model.dokumente
            store.bearbeitung[blatt] = nil
            let erg: ZeichnungsBearbeitung
            switch result {
            case .success(.ack(let a)):
                erg = ZeichnungsBearbeitung(ok: a.ok, meldung: a.message, ergebnisse: a.ergebnisse)
            case .success(let m):
                erg = ZeichnungsBearbeitung(ok: false, meldung: "Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                erg = ZeichnungsBearbeitung(ok: false, meldung: e.message)
            }
            if let f = erg.fehlerText {
                store.meldung = DokumenteMeldung(text: "\(titel): \(f)", fehler: true)
                self.log(.warning, "Blatt \(blatt), \(titel): \(f)")
            }
            abschluss?(erg)
        }
    }
}
