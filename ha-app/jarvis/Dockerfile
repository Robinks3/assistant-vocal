# Appli Home Assistant « Assistant vocal local » : serveur des satellites vocaux, profil ha (aucun modèle local,
# s'appuie sur les applis openWakeWord, Speech-to-Phrase et Piper de HA, et sur Claude).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY app/ /app/
CMD ["python3", "/app/demarrage.py"]
