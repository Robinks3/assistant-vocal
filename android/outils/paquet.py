"""Affiche l'identifiant installé de l'appli (appareils.android.application_id de la configuration), pour les scripts adb."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "poc"))
import maison  # noqa: E402

print(((maison.CONFIG.get("appareils") or {}).get("android") or {}).get("application_id") or "assistant.vocal.jarvis")
