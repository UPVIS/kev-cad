import KevCADCore
import SwiftUI

// Deutsche Bezeichnungen und Symbole für die Werte aus dem AppModel-Vertrag.

extension DisplayStyle {
    var title: String {
        switch self {
        case .shadedEdges: return "Schattiert mit Kanten"
        case .shaded: return "Schattiert"
        case .wireframe: return "Drahtgitter"
        case .xray: return "Röntgen"
        }
    }

    var symbol: String {
        switch self {
        case .shadedEdges: return "cube.fill"
        case .shaded: return "cube"
        case .wireframe: return "cube.transparent"
        case .xray: return "square.3.layers.3d"
        }
    }
}

extension StandardViewName {
    var title: String {
        switch self {
        case .top: return "Oben"
        case .bottom: return "Unten"
        case .front: return "Vorne"
        case .back: return "Hinten"
        case .left: return "Links"
        case .right: return "Rechts"
        case .iso: return "Isometrisch"
        case .isoFrontLeft: return "Isometrisch vorne links"
        case .isoBackRight: return "Isometrisch hinten rechts"
        case .isoBackLeft: return "Isometrisch hinten links"
        }
    }

    /// Tastenbelegung: 1 bis 7 wie in PLAN-MVP.md Abschnitt 9, die drei weiteren Isometrien auf 8, 9, 0.
    var key: KeyEquivalent {
        switch self {
        case .top: return "1"
        case .front: return "2"
        case .right: return "3"
        case .back: return "4"
        case .left: return "5"
        case .bottom: return "6"
        case .iso: return "7"
        case .isoFrontLeft: return "8"
        case .isoBackRight: return "9"
        case .isoBackLeft: return "0"
        }
    }

    /// Reihenfolge in Menüs, passend zur Tastenbelegung.
    static let menuOrder: [StandardViewName] = [.top, .front, .right, .back, .left, .bottom, .iso]
    static let extraIsoOrder: [StandardViewName] = [.isoFrontLeft, .isoBackRight, .isoBackLeft]
}

extension KernelState {
    var title: String {
        switch self {
        case .stopped: return "Kernel aus"
        case .starting: return "Kernel startet …"
        case .ready: return "Kernel bereit"
        case .busy: return "Kernel rechnet"
        case .failed: return "Kernel-Fehler"
        }
    }

    var color: Color {
        switch self {
        case .stopped: return .secondary
        case .starting: return .yellow
        case .ready: return .green
        case .busy: return .orange
        case .failed: return .red
        }
    }

    var detail: String? {
        if case .failed(let message) = self { return message }
        return nil
    }
}

extension LogLine.Level {
    var title: String {
        switch self {
        case .info: return "Info"
        case .warning: return "Warnung"
        case .error: return "Fehler"
        }
    }

    var symbol: String {
        switch self {
        case .info: return "info.circle"
        case .warning: return "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        }
    }

    var color: Color {
        switch self {
        case .info: return .secondary
        case .warning: return .orange
        case .error: return .red
        }
    }
}

/// Exportformate in Menüs (Schlüssel laut PROTOCOL.md `EXPORT_REQ.formats`).
enum ExportFormat: String, CaseIterable, Identifiable {
    case step, stl, threeMF = "3mf", glb

    var id: String { rawValue }

    var title: String {
        switch self {
        case .step: return "STEP"
        case .stl: return "STL"
        case .threeMF: return "3MF"
        case .glb: return "GLB"
        }
    }

    var detail: String {
        switch self {
        case .step: return "CAD-Austausch, exakt"
        case .stl: return "Netz für den 3D-Druck"
        case .threeMF: return "Netz mit Farben für Bambu Studio"
        case .glb: return "Netz für Web und Vorschau"
        }
    }

    /// Das Standardpaket aus PLAN-MVP.md Abschnitt 1: STEP, STL und 3MF.
    static let standard: [ExportFormat] = [.step, .stl, .threeMF]
}

extension Color {
    /// Teilfarbe aus dem Modell (lineares RGBA 0…1 laut PROTOCOL.md).
    init(part color: SIMD4<Float>) {
        self.init(
            .sRGBLinear, red: Double(color.x), green: Double(color.y), blue: Double(color.z),
            opacity: Double(max(0.15, color.w)))
    }
}
