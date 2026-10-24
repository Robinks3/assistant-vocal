"""Sonde les applis Wyoming de HA par `ssh <alias de HA> nc` : liste des modèles, synthèse française."""
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maison
from wyoming.event import async_read_event, async_write_event
from wyoming.info import Describe, Info
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.audio import AudioChunk, AudioStop
sys.stdout.reconfigure(encoding="utf-8")

async def canal(hote, port):
    return await asyncio.create_subprocess_exec("ssh", "-o", "ConnectTimeout=10", maison.reseau("ssh_ha"), "nc", hote, str(port),
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)

async def decrire(hote, port):
    p = await canal(hote, port)
    await async_write_event(Describe().event(), p.stdin)
    info = Info.from_event(await asyncio.wait_for(async_read_event(p.stdout), 30)); p.kill()
    return info

async def main():
    oww = await decrire("core-openwakeword", 10400)
    for w in oww.wake:
        print("openWakeWord :", [m.name for m in w.models])
    pip = await decrire("core-piper", 10200)
    for t in pip.tts:
        fr = [v.name for v in t.voices if v.name.startswith("fr_FR")]
        print(f"Piper : {len(t.voices)} voix, dont françaises : {fr[:8]}")
    p = await canal("core-piper", 10200)
    t0 = time.perf_counter()
    await async_write_event(Synthesize(text="La lampe de la télé est allumée.", voice=SynthesizeVoice(name="fr_FR-siwis-medium")).event(), p.stdin)
    octets, premier = 0, None
    while True:
        ev = await asyncio.wait_for(async_read_event(p.stdout), 120)
        if ev is None: break
        if AudioChunk.is_type(ev.type):
            premier = premier or time.perf_counter() - t0; octets += len(AudioChunk.from_event(ev).audio)
        if AudioStop.is_type(ev.type): break
    p.kill()
    print(f"Synthèse française : premier son {premier:.2f} s, total {time.perf_counter() - t0:.2f} s, {octets} octets")

asyncio.run(main())
