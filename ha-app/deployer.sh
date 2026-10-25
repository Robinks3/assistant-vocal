#!/usr/bin/env bash
# Déploie l'appli de l'assistant vocal dans le Home Assistant de la maison, alias SSH reseau.ssh_ha de la configuration (dossier /local_apps/jarvis depuis que HA appelle les add-ons « apps », appli locale local_jarvis).
# Copie le code du POC, la configuration de la maison (maison.json et dictionnaire) et les phrases apprises du
# PC comme graines. Aucun secret ici :
# la clé et le jeton se règlent dans les options de l'appli (voir configurer-options.py).
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
POC="$ICI/../poc"
ETAPE="$(mktemp -d)"
# Configuration de la maison : le dossier réel (ASSISTANT_VOCAL_CONFIG ou son ancien nom MAISON_DOSSIER, sinon config/
# à la racine, non suivi, ou l'ancien maison/). Sans lui, on s'arrête : déployer les valeurs fictives de
# config-exemple/ remplacerait les listes de sécurité de la maison.
MAISON="${ASSISTANT_VOCAL_CONFIG:-${MAISON_DOSSIER:-}}"
if [ -z "$MAISON" ]; then
    MAISON="$ICI/../config"
    if [ ! -f "$MAISON/maison.json" ] && [ -f "$ICI/../maison/maison.json" ]; then
        MAISON="$ICI/../maison"
        echo "Configuration lue dans l'ancien dossier maison/, à renommer en config/." >&2
    fi
fi
for f in maison.json commandes.yaml; do
    [ -f "$MAISON/$f" ] || { echo "$MAISON/$f absent : copier config-exemple/ en config/ et l'adapter." >&2; exit 1; }
done
SSH_HA="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["reseau"]["ssh_ha"])' "$MAISON/maison.json")"
cp -r "$ICI/jarvis/." "$ETAPE/"
# Nom affiché de l'appli dans HA : section assistant de maison.json, sinon « Assistant ».
python - "$MAISON/maison.json" "$ETAPE/config.yaml" <<'PY'
import json, re, sys
section = json.load(open(sys.argv[1], encoding="utf-8")).get("assistant")
nom = section.get("nom") if isinstance(section, dict) else None
nom = (nom.strip() if isinstance(nom, str) else "") or "Assistant"
texte = open(sys.argv[2], encoding="utf-8").read()
texte, n = re.subn(r"(?m)^name:.*$", lambda _: "name: " + json.dumps(nom, ensure_ascii=False), texte, count=1)
assert n == 1, "ligne name: absente de config.yaml"
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(texte)
PY
cp "$POC/assistant.py" "$POC/dictionnaire.py" "$POC/serveur_satellite.py" "$POC/securite.py" "$POC/acces.py" "$POC/vad.py" "$POC/vision.py" "$POC/sante.py" "$POC/sante_hist.py" "$POC/meteo_mer.py" "$POC/vent_mesure.py" "$POC/maison.py" "$ETAPE/app/"
mkdir -p "$ETAPE/app/config" && cp "$MAISON/maison.json" "$MAISON/commandes.yaml" "$ETAPE/app/config/"
mkdir -p "$ETAPE/app/modeles" && cp "$POC/modeles/silero_vad.onnx" "$ETAPE/app/modeles/"
[ -f "$POC/commandes_apprises.yaml" ] && cp "$POC/commandes_apprises.yaml" "$ETAPE/app/"
tar -C "$ETAPE" -cf - . | ssh "$SSH_HA" 'rm -rf /local_apps/jarvis && mkdir -p /local_apps/jarvis && tar --no-same-owner -C /local_apps/jarvis -xf - && chown -R root:root /local_apps/jarvis && ls /local_apps/jarvis'
rm -rf "$ETAPE"
