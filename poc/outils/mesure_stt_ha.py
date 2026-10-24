"""Mesure la transcription des applis vocales de HA (Wyoming) sur des phrases synthétisées.

Usage : python poc/outils/mesure_stt_ha.py <ip interne:port> "phrase 1" "phrase 2"
(172.30.33.2:10300 Whisper, 172.30.33.3:10300 Speech-to-Phrase)
Le SSH de HA interdit les tunnels : le dialogue Wyoming passe par `ssh <alias de HA> nc <ip> <port>`,
une connexion SSH par phrase. Le temps mesuré part de la fin de l'envoi de l'audio."""
import asyncio, sys, time, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maison
from piper import PiperVoice
from wyoming.event import async_read_event, async_write_event
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioStart, AudioChunk, AudioStop
from wyoming.info import Describe, Info
sys.stdout.reconfigure(encoding="utf-8")
ICI = Path(__file__).resolve().parents[1]
voix = PiperVoice.load(str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))

def pcm(texte):
    x = np.frombuffer(b"".join(c.audio_int16_bytes for c in voix.synthesize(texte)), np.int16).astype(np.float32)
    n = int(len(x) * 16000 / voix.config.sample_rate)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16).tobytes()

class Canal:
    """Wyoming par les entrées et sorties d'un `ssh <alias de HA> nc`."""
    def __init__(self, cible):
        self.ip, self.port = cible.split(":")
    async def __aenter__(self):
        self.proc = await asyncio.create_subprocess_exec("ssh", "-o", "ConnectTimeout=10", maison.reseau("ssh_ha"),
                                                         "nc", self.ip, self.port,
                                                         stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        return self
    async def ecrire(self, ev):
        await async_write_event(ev, self.proc.stdin)
    async def lire(self):
        return await async_read_event(self.proc.stdout)
    async def __aexit__(self, *a):
        self.proc.kill()
        await self.proc.wait()

async def main(cible, phrases):
    async with Canal(cible) as c:
        await c.ecrire(Describe().event())
        info = Info.from_event(await asyncio.wait_for(c.lire(), 30))
        for a in info.asr:
            print(f"service : {a.name} {a.version or ''}, modèles : {[m.name for m in a.models][:3]}")
    for p in phrases:
        audio = pcm(p)
        async with Canal(cible) as c:
            await c.ecrire(Transcribe(language="fr").event())
            await c.ecrire(AudioStart(rate=16000, width=2, channels=1).event())
            for i in range(0, len(audio), 3200):
                await c.ecrire(AudioChunk(rate=16000, width=2, channels=1, audio=audio[i:i + 3200]).event())
            await c.ecrire(AudioStop().event())
            t_fin_envoi = time.perf_counter()
            while True:
                ev = await asyncio.wait_for(c.lire(), 240)
                if ev is None:
                    tr = "(connexion fermée)"
                    break
                if Transcript.is_type(ev.type):
                    tr = Transcript.from_event(ev).text
                    break
            print(f"{time.perf_counter() - t_fin_envoi:6.2f} s après la fin de la phrase ({len(audio)/32000:.1f} s d'audio) : "
                  f"« {p} » -> « {tr} »")

asyncio.run(main(sys.argv[1], sys.argv[2:]))
