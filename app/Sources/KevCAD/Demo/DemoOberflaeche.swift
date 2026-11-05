import KevCADCore

// V2-3: Aktionen der Oberfläche im Demomodus, genau wie im App-Kern (nur der Zustand in AppModel.oberflaeche).
extension DemoActions: OberflaechenActions {
    func oberflaeche(_ befehl: Oberflaechenbefehl) {
        model.oberflaeche.ausfuehren(befehl)
    }
}
