# OCCTSwiftViewport · lokale Kopie für Kev CAD

Herkunft: https://github.com/SecondMouseAU/OCCTSwiftViewport, Commit `d9984ad46a9195f8eb91897e6cd4cf2a4e553bd0`
(„fix: native drag/magnify/rotate on macOS 27“, durch AP0 geprüft, siehe PLAN-MVP.md Abschnitt 12). Lizenz: LGPL-2.1
mit OCCT-Ausnahme (`LICENSE`, `OCCT_LGPL_EXCEPTION.md`). Übernommen sind nur `Sources/` und die Lizenztexte; das
Manifest baut nur die Bibliothek.

Warum eine Kopie (Viewer V2, 05.11.2026): Die Darstellungsarten von Kev CAD brauchen Schalter zur Laufzeit und eine
Umgebungsverdeckung, die im Millimeter-Maßstab wirkt. Das Original liest Silhouetten, Hintergrund und Kantenlinien aus
einer unveränderlichen Konfiguration, und seine SSAO prüft nur „Nachbar näher an der Kamera“: Bei CAD-Maßen (Radius
0,8 Welt-Einheiten) traf sie praktisch nichts, mit größerem Radius hätte sie jede geneigte Ebene gleichmäßig abgedunkelt.

Jede Änderung ist im Code mit „Kev CAD“ markiert. Die öffentliche Schnittstelle wächst nur (alles Bisherige bleibt).

| Datei | Änderung |
|---|---|
| `Configuration/ViewportConfiguration.swift`, `Views/MetalViewportView.swift` | neu `backgroundFollowsAppearance` (Vorgabe true wie bisher): false hält im Dunkelmodus den konfigurierten Hintergrund statt Dunkelgrau |
| `Views/ViewportController.swift` | `configuration` ist `@Published public var` statt `public let` (Silhouetten, Hintergrund, Kantenlinien zur Laufzeit) |
| `Display/LightingConfiguration.swift` | neu `kevAORadiusPixels` (Umgebungsverdeckung ohne Neigungsfehler, Radius in Bildpunkten, 0 = alte SSAO) und `kevCavityIntensity` (Kantenbetonung) |
| `Renderer/ViewportRenderer.swift` | `SSAOParamsSwift` um vier Werte am Ende ergänzt und befüllt; der Nachbearbeitungsdurchgang läuft auch nur für die Kantenbetonung; ohne `enableSSAO` keine Verdunklung mehr (das Original gab die Stärke immer mit, sobald Silhouetten an waren) |
| `Renderer/ViewportRendererHeadless.swift` | `renderHeadless` und `renderHeadlessBGRA` öffentlich (Bildschirmfoto und Video mit genau dem Bild des Viewports) |
| `Renderer/ViewportRenderer.swift` (Bildzeiten) | `onFrameTiming`: je angezeigtem Bild CPU-Zeit auf dem Hauptfaden, GPU-Zeit und Anzeigezeitpunkt (Selbsttest `KEVCAD_SELFTEST=viewer`); ohne Abnehmer keine Kosten |
| `Renderer/OffscreenRenderer.swift`, `Renderer/ShadowMapManager.swift`, `Renderer/MeasurementCompositor.swift` | nicht mehr `@MainActor` (V2-7): Die zweite Ansicht rechnet ihr Bild auf einer eigenen Warteschlange, `render` wartet sonst auf dem Hauptfaden auf die GPU. Eine Instanz gehört einem Faden |
| `Renderer/Shaders.metal` | `SSAOParams` passend ergänzt; neue Verdeckung und Kantenbetonung aus der Krümmung der Tiefe (Abweichung der Mitte von der Ebene durch zwei gegenüberliegende Nachbarn: perspektivisch harmonisches Mittel, parallel arithmetisch), Tiefe auch für Parallelprojektion richtig linearisiert; die alte SSAO und die Tiefen-Unschärfemaske bleiben für `kevAORadiusPixels = 0` |

Aktualisieren auf einen neueren Stand des Originals: Quellen neu kopieren, die Stellen mit „Kev CAD“ übertragen, mit
`tools/fern.sh testbau` und dem Selbsttest `KEVCAD_SELFTEST=viewer` prüfen.
