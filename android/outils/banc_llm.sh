#!/usr/bin/env bash
# Banc du LLM sur l'appareil, sans écran ni action (lecture seule des appareils dans HA).
# Usage : bash android/outils/banc_llm.sh <appareil adb> <fichier .litertlm> "phrase 1|phrase 2" [n phrases attendues]
# Installe l'APK compilée, lance RecepteurBanc et affiche les décisions (logcat JarvisLlm).
set -u
export MSYS_NO_PATHCONV=1
# adb du SDK Android : variable ADB, sinon celui du PATH.
ADB="${ADB:-adb}"
T="$1"; MODELE="$2"; PHRASES="$3"; N="${4:-$(echo "$PHRASES" | tr '|' '\n' | wc -l)}"
timeout 120 "$ADB" -s "$T" install -r "${ASSISTANT_VOCAL_BUILD:-../../assistant-vocal-build}/SatelliteJarvis-app/outputs/apk/debug/app-debug.apk" | tail -1
timeout 10 "$ADB" -s "$T" logcat -c
timeout 20 "$ADB" -s "$T" shell "am broadcast -n ${PAQUET:-$(python android/outils/paquet.py)}/assistant.vocal.jarvis.RecepteurBanc --es test_llm '$PHRASES' --es modele $MODELE ${EXTRA:-}" | tail -1
for i in $(seq 1 200); do
  n=$(timeout 10 "$ADB" -s "$T" logcat -d -s JarvisLlm:* | grep -c "   brut\|impossible\|aucun modèle")
  [ "$n" -ge "$N" ] && break
  sleep 3
done
timeout 10 "$ADB" -s "$T" logcat -d -s JarvisLlm:* AndroidRuntime:E | cut -c33-
