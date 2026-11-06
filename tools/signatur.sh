# Signatur der App, gemeinsam für build.sh und tools/fern.sh (wird eingebunden, nicht aufgerufen).
#
# Auf Kevins MacBook mit seinem Team: Wortlauts Sprachdienst nimmt nur solche Programme an, und die Rechte fürs Mikrofon
# bleiben über Updates erhalten. Auf dem Mac mini und auf fremden Rechnern fehlt die Identität, dort bleibt es ad hoc.
# Vom Mini geholte Apps signiert deshalb das MacBook nach dem Holen neu. KEVCAD_SIGNATUR=- erzwingt ad hoc.
KEVCAD_TEAM=2GX7UC98J6

kevcad_identitaet() {
  if [ -n "${KEVCAD_SIGNATUR:-}" ]; then echo "$KEVCAD_SIGNATUR"; return; fi
  local id
  id=$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n "s/.*\"\(Developer ID Application: .*($KEVCAD_TEAM)\)\".*/\1/p" | head -1)
  echo "${id:--}"
}

kevcad_signieren() {
  codesign --force --deep --sign "$(kevcad_identitaet)" --timestamp=none "$1" >/dev/null 2>&1
}
