#if os(macOS)
import AppKit
#else
import UIKit
#endif
import KevCADCore
import SwiftUI

// Grundbausteine (2): Zeile der Gliederung und Eigenschaftsfeld mit „vorher“-Wert.

/// Eine Zeile der Gliederung: Gruppe (mit Pfeil und Anzahl) oder Objekt. Klick wählt (mit ⇧ oder ⌘ dazu),
/// Doppelklick benennt um. Ein Punkt rechts zeigt einen Befund (Koralle) oder eine Markierung durch Kevin (Lichtblau).
struct GliederungsZeile: View {
    let titel: String
    var anzahl: Int?
    var ebene = 0
    var gruppe = false
    var offen = false
    var gewaehlt = false
    var markiert = false
    var befund = false
    var ausgeblendet = false
    /// Das Umbenennen läuft gerade in dieser Zeile.
    var bearbeiten = false
    var aufklappen: () -> Void = {}
    /// `true`: zur Auswahl hinzunehmen bzw. wegnehmen (⇧ oder ⌘ gedrückt).
    var waehlen: (Bool) -> Void = { _ in }
    var umbenennenBeginnen: () -> Void = {}
    /// Neuer Name; nil heißt abgebrochen.
    var umbenennen: (String?) -> Void = { _ in }

    @State private var hover = false
    @State private var entwurf = ""
    @FocusState private var feldFokus: Bool

    private var kind: Bool { ebene > 0 }

    var body: some View {
        HStack(spacing: GA.s) {
            if gruppe {
                Button(action: aufklappen) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 8.5, weight: .bold))
                        .foregroundStyle(GF.rauch)
                        .rotationEffect(.degrees(offen ? 90 : 0))
                        .frame(width: 10, height: 16)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHidden(true)
            } else if !kind {
                Color.clear.frame(width: 10, height: 1)
            }
            name
            Spacer(minLength: GA.xs)
            if let anzahl {
                Text(KevFormat.integer(anzahl))
                    .font(GS.zahl)
                    .foregroundStyle(GF.rauch)
            }
            if befund || markiert {
                Circle()
                    .fill(befund ? GF.befund : GF.kevin)
                    .frame(width: 6, height: 6)
                    .shadow(color: markiert && !befund ? GF.kevin : .clear, radius: 4)
            }
        }
        .padding(.leading, CGFloat(max(0, ebene)) * GA.einzug)
        .padding(.horizontal, GA.s)
        .frame(height: kind ? GA.zeileKind : GA.zeile)
        .background(
            RoundedRectangle(cornerRadius: GR.feld, style: .continuous)
                .fill(gewaehlt ? GF.zeileGewaehlt : (hover ? GF.zeileHover : Color.clear)))
        .opacity(ausgeblendet ? 0.45 : 1)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .gesture(TapGesture(count: 2).onEnded { if !bearbeiten { umbenennenBeginnen() } })
        .simultaneousGesture(TapGesture().onEnded {
            guard !bearbeiten else { return }
            waehlen(auswahlErweitern)
        })
        .accessibilityElement(children: bearbeiten ? .contain : .ignore)
        .accessibilityLabel(titel)
        .accessibilityValue(beschreibung)
        .accessibilityAddTraits(gewaehlt ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction { waehlen(false) }
        .accessibilityAction(named: "Umbenennen") { umbenennenBeginnen() }
        .accessibilityAction(named: offen ? "Zuklappen" : "Aufklappen") { if gruppe { aufklappen() } }
    }

    @ViewBuilder
    private var name: some View {
        if bearbeiten {
            TextField("Name", text: $entwurf)
                .textFieldStyle(.plain)
                .font(kind ? GS.zeileKind : GS.zeile)
                .foregroundStyle(GF.kreide)
                .focused($feldFokus)
                .padding(.horizontal, 4)
                .background(RoundedRectangle(cornerRadius: 4, style: .continuous).fill(GF.feldFokus))
                .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).strokeBorder(GF.kevin.opacity(0.6)))
                .onAppear {
                    entwurf = titel
                    DispatchQueue.main.async { feldFokus = true }
                }
                .onSubmit { fertig(entwurf) }
                .beiEsc { umbenennen(nil) }
                .onChange(of: feldFokus) { _, f in if !f && bearbeiten { fertig(entwurf) } }
        } else {
            Text(titel)
                .font(kind ? GS.zeileKind : GS.zeile)
                .fontWeight(kind ? .regular : .medium)
                .foregroundStyle(textFarbe)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    private func fertig(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        umbenennen(t.isEmpty || t == titel ? nil : t)
    }

    private var textFarbe: Color {
        if markiert && !gewaehlt { return GF.kevin }
        if gewaehlt { return GF.kreide }
        return kind ? GF.asche : GF.kreide.opacity(0.88)
    }

    private var beschreibung: String {
        var t: [String] = []
        if gruppe { t.append(offen ? "Gruppe, offen" : "Gruppe, zu") }
        if let anzahl { t.append(KevFormat.count(anzahl, one: "Teil", many: "Teile")) }
        if befund { t.append("mit Befund") }
        if ausgeblendet { t.append("ausgeblendet") }
        return t.joined(separator: ", ")
    }
}

/// Eigenschaftsfeld: Titel links, Wert im Feld, rechts Einheit oder „vorher …“ (in Messing, mit Rand), wenn sich der
/// Wert gerade geändert hat. Mit `aendern` ist der Wert bearbeitbar; Zeilenschalter übernimmt, esc verwirft.
struct EigenschaftsFeld: View {
    let titel: String
    let wert: String
    var einheit: String?
    var vorher: String?
    var hilfe: String?
    var aendern: ((String) -> Void)?

    @State private var text = ""
    @FocusState private var fokus: Bool

    var body: some View {
        HStack(spacing: 10) {
            Text(titel)
                .font(GS.text)
                .foregroundStyle(GF.asche)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(width: GA.feldTitel, alignment: .leading)
            feld
        }
        .help(hilfe ?? "")
        .onAppear { text = wert }
        .onChange(of: wert) { _, neu in if !fokus { text = neu } }
    }

    private var feld: some View {
        HStack(spacing: 6) {
            if let aendern {
                TextField(titel, text: $text)
                    .labelsHidden()
                    .textFieldStyle(.plain)
                    .font(GS.wert)
                    .foregroundStyle(GF.kreide)
                    .focused($fokus)
                    .onSubmit { uebernehmen(aendern) }
                    .beiEsc {
                        text = wert
                        fokus = false
                    }
                    .accessibilityLabel(titel)
                    .accessibilityHint(vorher.map { "vorher \($0)" } ?? "")
            } else {
                Text(wert)
                    .font(GS.wert)
                    .foregroundStyle(GF.kreide)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                    .truncationMode(.middle)
                    .accessibilityLabel(titel)
                    .accessibilityValue(einheit.map { "\(wert) \($0)" } ?? wert)
            }
            Spacer(minLength: GA.xs)
            if let vorher {
                Text("vorher \(vorher)")
                    .font(.system(size: 11.5))
                    .foregroundStyle(GF.agent)
                    .lineLimit(1)
                    .layoutPriority(1)
            } else if let einheit {
                Text(einheit)
                    .font(.system(size: 11.5))
                    .foregroundStyle(GF.rauch)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 9)
        .frame(height: GA.feld)
        .background(
            RoundedRectangle(cornerRadius: GR.feld, style: .continuous).fill(fokus ? GF.feldFokus : GF.feld))
        .overlay {
            if vorher != nil || fokus {
                RoundedRectangle(cornerRadius: GR.feld, style: .continuous)
                    .strokeBorder(fokus ? GF.kevin.opacity(0.6) : GF.agent.opacity(0.55), lineWidth: 1)
            }
        }
    }

    private func uebernehmen(_ aendern: (String) -> Void) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        fokus = false
        guard !t.isEmpty, t != wert else {
            text = wert
            return
        }
        aendern(t)
    }
}

/// Kleines Suchfeld in Spalten und Kacheln. `.searchable` setzt sein Feld in die Fensterleiste, wo im Hauptfenster die
/// Kopfleiste steht; eingebettete Ansichten nehmen deshalb dieses Feld.
struct SuchFeld: View {
    @Binding var text: String
    var prompt = "Teile filtern"

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 11))
                .foregroundStyle(GF.rauch)
            TextField(prompt, text: $text)
                .textFieldStyle(.plain)
                .font(GS.text)
                .foregroundStyle(GF.kreide)
            if !text.isEmpty {
                Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain)
                    .foregroundStyle(GF.rauch)
                    .accessibilityLabel("Suche leeren")
            }
        }
        .padding(.horizontal, 8)
        .frame(height: GA.feld)
        .background(RoundedRectangle(cornerRadius: GR.feld, style: .continuous).fill(GF.feld))
    }
}

/// Überschrift eines Abschnitts in Spalten und Karten („Objekte 84“, „Maße des Modells“).
struct AbschnittTitel: View {
    let titel: String
    var zusatz: String?

    var body: some View {
        HStack {
            Text(titel)
                .font(GS.abschnitt)
                .foregroundStyle(GF.asche)
            Spacer()
            if let zusatz {
                Text(zusatz)
                    .font(GS.zahl)
                    .foregroundStyle(GF.rauch)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}
