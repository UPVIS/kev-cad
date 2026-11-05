import Foundation

/// Wörter, die Kevin beim Konstruieren oft sagt. Apples Erkennung bekommt sie als Kontext (`AnalysisContext`), dazu die
/// Namen der Teile; Wortlauts Vertrag kennt keine Wortliste. Vorbild `Fachwoerter` in Sichtung.
enum Fachwoerter {
    static let konstruktion = [
        "Bohrung", "Fase", "Verrundung", "Nut", "Steg", "Lasche", "Flansch", "Gewinde", "Gewindeeinsatz", "Sterngriff",
        "Mutter", "Schraube", "Scheibe", "Rohr", "Vierkantrohr", "Profil", "Nutprofil", "Winkel", "Halter", "Rahmen",
        "Griff", "Laufrolle", "Druckteil", "Überhang", "Wandstärke", "Stückliste", "Zuschnitt", "Baugruppe", "Isolieren",
        "Schnitt", "Explosion", "Millimeter", "Zentimeter", "Kante", "Fläche", "Rundung", "PETG", "PLA",
    ]

    /// Höchstens so viele Einträge (Apple nennt keine Grenze; mehr verlangsamt die Erkennung womöglich).
    static let hoechstens = 120

    /// Fachwörter und die Namen der Teile, ohne Doppel und ohne Nummern am Ende („Rolle 3“ wird „Rolle“).
    static func kontext(teile: [String]) -> [String] {
        var liste = konstruktion
        for name in teile {
            let letzter = name.split(separator: "/").last.map(String.init) ?? name
            liste.append(letzter.trimmingCharacters(in: .decimalDigits.union(.whitespaces)))
        }
        var gesehen = Set<String>()
        var aus: [String] = []
        for wort in liste where wort.count >= 2 && wort.count <= 60 && gesehen.insert(wort.lowercased()).inserted {
            aus.append(wort)
            if aus.count >= hoechstens { break }
        }
        return aus
    }
}
