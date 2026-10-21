"""Geometrie zu Katalogeinträgen (KATALOG.md, „Kameras und Objektive“, Feld ``geometrie``).

Ein Eintrag verweist mit ``"geometrie": {"modul": "kevcad.geometrie.kamerasystem", "funktion": "sony_fx6"}`` (oder
``{"datei": "geometrie/x.py", "funktion": "…"}`` relativ zur Katalogdatei) auf eine Funktion

    def sony_fx6(eintrag: dict) -> Shape | dict[str, Shape]

in lokalen Koordinaten des Eintrags: Ursprung Sensormitte (Kamera), Bajonett-Auflage (Objektiv) bzw. laut Feld
``ursprung`` (Zubehör); +x Blickrichtung bzw. nach vorn, +y links, +z oben, mm. Ein dict ergibt Unterteile
(Schlüssel = Teilname), Farben über ``shape.color``. Bezugspunkte stehen im Katalogeintrag, nicht hier.
"""
