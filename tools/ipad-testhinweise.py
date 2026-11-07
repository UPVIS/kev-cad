#!/usr/bin/env python3
"""Testhinweise („Was ist zu testen?“) eines TestFlight-Builds setzen (PLAN-IPAD.md, I-9).

  python3 -I tools/ipad-testhinweise.py <App-ID> <Build-Nummer> <Text>

Ein frisch hochgeladener Build erscheint in App Store Connect erst nach ein, zwei Minuten; das Skript wartet bis zu acht
Minuten auf ihn. Gesetzt wird die Hauptsprache der App; gibt es sie am Build schon, wird der Text ersetzt. Aufrufe über
asc-api (Team-Schlüssel im Schlüsselbund, Regel apple-app-verteilung). Ausgang 0, wenn der Text steht.
"""
import json
import subprocess
import sys
import time

WARTEN_S = 8 * 60


def api(*args):
    r = subprocess.run(["asc-api", *args], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout) if r.stdout.strip() else {}


def build_id(app, nummer):
    ende = time.monotonic() + WARTEN_S
    while True:
        antwort = api("GET", f"/v1/builds?filter%5Bapp%5D={app}&filter%5Bversion%5D={nummer}&limit=1") or {}
        if antwort.get("data"):
            return antwort["data"][0]["id"]
        if time.monotonic() > ende:
            return None
        time.sleep(15)


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    app, nummer, text = sys.argv[1], sys.argv[2], sys.argv[3][:4000]
    sprache = (((api("GET", f"/v1/apps/{app}") or {}).get("data") or {}).get("attributes") or {}).get("primaryLocale")
    build = build_id(app, nummer)
    if not build:
        print(f"==> Testhinweise nicht gesetzt: Build {nummer} erschien nicht in App Store Connect")
        return 1
    sprache = sprache or "de-DE"
    vorhanden = [x for x in (api("GET", f"/v1/builds/{build}/betaBuildLocalizations") or {}).get("data") or []
                 if x["attributes"].get("locale") == sprache]
    if vorhanden:
        lok = vorhanden[0]["id"]
        ok = api("PATCH", f"/v1/betaBuildLocalizations/{lok}", json.dumps(
            {"data": {"type": "betaBuildLocalizations", "id": lok, "attributes": {"whatsNew": text}}}))
    else:
        ok = api("POST", "/v1/betaBuildLocalizations", json.dumps(
            {"data": {"type": "betaBuildLocalizations", "attributes": {"locale": sprache, "whatsNew": text},
                      "relationships": {"build": {"data": {"type": "builds", "id": build}}}}}))
    if ok is None:
        print(f"==> Testhinweise für Build {nummer} ließen sich nicht setzen")
        return 1
    print(f"==> Testhinweise für Build {nummer} gesetzt ({sprache})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
