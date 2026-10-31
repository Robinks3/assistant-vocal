#!/usr/bin/env bash
# Installe sur un appareil une version d'essai (canary) de l'appli, par adb, sans rien d'autre.
# Usage : bash android/outils/pousser_canary.sh <appareil adb> [chemin de l'APK]
#
# L'appareil est celui de `adb devices` (numéro de série, ou adresse:port en adb sans fil).
# Sans chemin, l'APK de débogage de la dernière compilation est prise : dossier de compilation de
# Windows (ASSISTANT_VOCAL_BUILD ou ../../assistant-vocal-build, ou celui de -PdossierBuild passé par la variable DOSSIER_BUILD), sinon
# android/app/build/outputs/apk/debug/app-debug.apk.
#
# Aucun secret ici : l'adresse du serveur et le jeton du satellite sont déjà dans l'APK, copiés par
# Gradle au moment de la compilation (voir docs/INSTALLER.md). Ce script ne lit ni poc/.env ni
# local.properties, ne compile rien et ne touche à aucune donnée de l'appli : `install -r` garde les
# réglages. Une version d'essai porte le même identifiant que l'appli installée, elle la remplace donc.
# Pour revenir en arrière, réinstaller l'APK précédente avec `adb install -r -d` (retour de version).
set -euo pipefail
export MSYS_NO_PATHCONV=1

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage : bash android/outils/pousser_canary.sh <appareil adb> [chemin de l'APK]" >&2
    exit 2
fi
APPAREIL="$1"
ICI="$(cd "$(dirname "$0")" && pwd)"
# adb du SDK Android : variable ADB, sinon celui du PATH.
ADB="${ADB:-adb}"
PAQUET="${PAQUET:-$(python android/outils/paquet.py)}"

command -v "$ADB" >/dev/null 2>&1 || { echo "adb introuvable : installer les platform-tools Android ou régler la variable ADB." >&2; exit 1; }

if [ "$#" -eq 2 ]; then
    APK="$2"
else
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) DOSSIER_BUILD="${DOSSIER_BUILD:-${ASSISTANT_VOCAL_BUILD:-../../assistant-vocal-build}}" ;;
        *) DOSSIER_BUILD="${DOSSIER_BUILD:-}" ;;
    esac
    if [ -n "$DOSSIER_BUILD" ]; then
        APK="$DOSSIER_BUILD/SatelliteJarvis-app/outputs/apk/debug/app-debug.apk"
    else
        APK="$ICI/../app/build/outputs/apk/debug/app-debug.apk"
    fi
fi
[ -f "$APK" ] || { echo "APK introuvable : $APK (compiler d'abord avec ./gradlew assembleDebug, ou donner le chemin)." >&2; exit 1; }

# L'appareil doit être connu d'adb et prêt (pas « unauthorized » ni « offline »).
ETAT="$("$ADB" -s "$APPAREIL" get-state 2>/dev/null || true)"
if [ "$ETAT" != "device" ]; then
    echo "Appareil $APPAREIL non prêt (état : ${ETAT:-inconnu}). Vérifier adb devices et l'autorisation de débogage sur le téléphone." >&2
    exit 1
fi

echo "Installation de $APK sur $APPAREIL"
"$ADB" -s "$APPAREIL" install -r "$APK"
echo "Version installée :"
"$ADB" -s "$APPAREIL" shell dumpsys package "$PAQUET" | grep -E "versionName|versionCode" | head -n 2
