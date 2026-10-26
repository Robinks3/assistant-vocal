"""Musique demandée à la voix : voie Spotify Connect, confirmation par l'état, journal (22/10/2026)."""
import json

import httpx
import pytest

import assistant as A

GROUPE, SPOTIFY = "media_player.enceintes_maison", "media_player.spotify_sacha"
SALON, CUISINE = "media_player.barre_son_salon_enceintes", "media_player.enceinte_cuisine_enceintes"
MJ = {"nom": "Artiste Fictif", "uri": "spotify--D7ai9Jsy://artist/3fMbdgg4jU18AjLCKBhRSm",
      "titre": "Artiste Fictif", "artistes": [], "type": "artist"}


class Reponse:
    def __init__(self, code=200, corps=None):
        self.status_code, self.corps = code, corps or {}
        self.text = json.dumps(self.corps)

    def json(self):
        return self.corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(str(self.status_code))


class FauxHA:
    """Client httpx de remplacement : des états, et des services qui les font évoluer comme sur l'installation d'origine
    le 22/10/2026 (play_media de Spotify qui fait jouer le groupe en Spotify Connect)."""

    def __init__(self, etats, effets=None):
        self.etats, self.effets, self.appels = etats, effets or {}, []

    def get(self, url, **_):
        e = url.rsplit("/", 1)[1]
        return Reponse(200, self.etats[e]) if e in self.etats else Reponse(404)

    def post(self, url, json=None, **_):
        service = url.split("/api/services/")[1].split("?")[0].replace("/", ".")
        self.appels.append((service, json))
        effet = self.effets.get(service)  # peut changer les états, rendre une réponse ou lever
        return (effet(self.etats, json) if effet else None) or Reponse(200, [])


def etat(state, **attrs):
    return {"state": state, "attributes": attrs}


def ha_avec(client, vraie_attente=False):
    ha = A.HomeAssistant("http://exemple.invalid", "x")
    ha.client = client
    ha.entree_mass = "mass"
    if not vraie_attente:
        ha.attendre = lambda condition, delai, relancer=None: bool(condition())
    return ha


class Horloge:
    """Temps virtuel : sleep() avance l'horloge sans attendre."""

    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += d

    def perf_counter(self):
        return self.t


@pytest.fixture
def horloge(monkeypatch):
    h = Horloge()
    monkeypatch.setattr(A, "time", h)
    return h


def test_uri_spotify():
    assert A.uri_spotify(MJ["uri"]) == "spotify:artist:3fMbdgg4jU18AjLCKBhRSm"
    assert A.uri_spotify("spotify://track/1EFO29WYvunKbc4awNPqD8") == "spotify:track:1EFO29WYvunKbc4awNPqD8"
    assert A.uri_spotify("library://track/1693") is None
    assert A.uri_spotify(None) is None


def test_correspond():
    piste = {"titre": "Billie Jean", "type": "track"}
    assert A.correspond({"media_title": "Billie Jean - Single Version"}, piste)
    assert not A.correspond({"media_title": "Bad"}, {"titre": "Bad Romance", "type": "track"})
    assert not A.correspond({"media_title": "Bad Romance"}, {"titre": "Bad", "type": "track"})
    assert A.correspond({"media_artist": "Akon, Artiste Fictif"}, {"titre": "Artiste Fictif", "type": "artist"})
    assert not A.correspond({"media_artist": "Julien Doré"}, {"titre": "Artiste Fictif", "type": "artist"})
    assert A.correspond({"media_title": "(I Can't Get No) Satisfaction - Mono"},
                        {"titre": "(I Can't Get No) Satisfaction", "type": "track"})
    assert not A.correspond({"media_title": "(Sittin' On) The Dock of the Bay"},
                            {"titre": "(I Can't Get No) Satisfaction", "type": "track"})
    assert A.correspond({"media_album_name": "Thriller (Special Edition)"}, {"titre": "Thriller", "type": "album"})
    assert not A.correspond({"media_album_name": "Thriller 25"}, {"titre": "Thriller", "type": "album"})
    liste = {"titre": "Ma playlist", "type": "playlist", "avant": "Billie Jean"}
    assert A.correspond({"media_playlist": "Ma Playlist"}, dict(liste, avant=None))
    assert A.correspond({"media_title": "Beat It"}, liste)
    assert not A.correspond({"media_title": "Billie Jean"}, liste)
    assert not A.correspond({"media_title": "Beat It"}, {"titre": "Ma playlist", "type": "playlist"})


def lecture_connect(etats, corps):
    etats[GROUPE] = etat("playing", source=A.HomeAssistant.SOURCE_CONNECT, media_artist="Artiste Fictif",
                         media_title="Billie Jean")
    etats[SPOTIFY] = etat("playing", source=A.HomeAssistant.SPOTIFY_APPAREIL, supported_features=444983,
                          source_list=[A.HomeAssistant.SPOTIFY_APPAREIL], media_artist="Artiste Fictif")
    etats[SALON] = etat("playing", media_title=A.HomeAssistant.SOURCE_CONNECT)


def etats_session_connect():
    """Les Enceintes jouent déjà en Spotify Connect (cas du soir du 22/10/2026)."""
    return {GROUPE: etat("playing", source=A.HomeAssistant.SOURCE_CONNECT, media_artist="Daft Punk", media_title="Get Lucky"),
            SPOTIFY: etat("playing", source=A.HomeAssistant.SPOTIFY_APPAREIL, supported_features=444983,
                          source_list=["téléphone de Sacha", A.HomeAssistant.SPOTIFY_APPAREIL]),
            SALON: etat("playing"), CUISINE: etat("playing")}


def test_session_connect_jouee_par_spotify(journal_musique_temporaire):
    client = FauxHA(etats_session_connect(), {"media_player.play_media": lecture_connect})
    ha = ha_avec(client)
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    res = ha.musique("Artiste Fictif", "artist")
    assert res == {"ok": True, "confirme": True, "lance": "Artiste Fictif", "enceinte": GROUPE}
    services = [s for s, _ in client.appels]
    assert "music_assistant.play_media" not in services and "media_player.select_source" not in services
    assert client.appels[-1] == ("media_player.play_media", {"entity_id": SPOTIFY, "media_content_type": "artist",
                                                              "media_content_id": "spotify:artist:3fMbdgg4jU18AjLCKBhRSm"})
    ligne = json.loads(journal_musique_temporaire.read_text(encoding="utf-8").splitlines()[-1])
    assert (ligne["demande"], ligne["voie"], ligne["lecteur"], ligne["resultat"]) == (
        "Artiste Fictif", "spotify connect", SPOTIFY, "confirmé")
    assert "duree_s" in ligne


def test_prise_de_main_avant_lecture():
    etats = etats_session_connect()
    etats[GROUPE] = etat("idle", source="Music Assistant Queue")
    etats[SPOTIFY] = etat("playing", source="téléphone de Sacha", supported_features=444983,
                          source_list=["téléphone de Sacha", A.HomeAssistant.SPOTIFY_APPAREIL])
    bascule = lambda e, c: e.update({GROUPE: etat("playing", source=A.HomeAssistant.SOURCE_CONNECT, media_title="Get Lucky")})
    client = FauxHA(etats, {"media_player.select_source": bascule, "media_player.play_media": lecture_connect})
    ha = ha_avec(client)
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    assert ha.musique("Artiste Fictif", "artist")["confirme"] is True
    assert [s for s, _ in client.appels] == ["media_player.select_source", "media_player.play_media"]


def test_jamais_lance_sans_confirmation(journal_musique_temporaire):
    # Spotify accepte, mais le groupe ne change pas de titre : pas de champ « lance ».
    client = FauxHA(etats_session_connect())
    ha = ha_avec(client)
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    res = ha.musique("Artiste Fictif", "artist")
    assert res["confirme"] is False and "lance" not in res and "attention" in res
    assert json.loads(journal_musique_temporaire.read_text(encoding="utf-8"))["resultat"] == res["attention"]


def test_ma_qui_affiche_playing_sans_son():
    # Repli par MA (une seule enceinte) : le lecteur de MA dit « playing », l'enceinte Enceintes est en pause.
    etats = {SPOTIFY: etat("idle", source_list=[]), "media_player.barre_son_salon": etat("playing", media_title="Billie Jean"),
             SALON: etat("paused", media_title="Billie Jean", media_artist="Artiste Fictif")}
    ha = ha_avec(FauxHA(etats))
    ha.chercher_musique = lambda r, t, a="", fin=None: {"nom": "Billie Jean de Artiste Fictif", "uri": "spotify://track/x",
                                              "titre": "Billie Jean", "artistes": ["Artiste Fictif"], "type": "track"}
    res = ha.musique("Billie Jean", "track", "salon")
    assert res["confirme"] is False and "lance" not in res
    etats[SALON] = etat("playing", media_title="Billie Jean", media_artist="Artiste Fictif")
    assert ha.musique("Billie Jean", "track", "salon")["lance"] == "Billie Jean de Artiste Fictif"


def recherche(horloge, duree, resultats=None):
    """Effet du service de recherche de MA : prend duree secondes, rend resultats (liste de pistes)."""
    def effet(_etats, _corps):
        horloge.sleep(duree)
        return Reponse(200, {"service_response": {"tracks": resultats or []}})
    return effet


def test_recherche_lente_n_est_pas_rien_trouve(horloge):
    client = FauxHA({}, {"music_assistant.search": recherche(horloge, 8.0)})
    ha = ha_avec(client)
    debut = horloge.time()
    assert "Spotify fait patienter" in ha.musique("Thriller Artiste Fictif", "track")["erreur"]
    assert horloge.time() - debut >= 8 + A.HomeAssistant.PAUSE_FREINAGE + 8
    # Première forme lente : la seconde (« titre artiste ») n'est pas tentée, mais un second essai après la pause.
    assert [s for s, _ in client.appels] == ["music_assistant.search"] * 2
    vide_vite = FauxHA({}, {"music_assistant.search": recherche(horloge, 0.5)})
    assert "rien trouvé" in ha_avec(vide_vite).musique("Thriller", "track")["erreur"]


def test_recherche_en_delai_depasse(horloge):
    def delai(_etats, _corps):
        raise httpx.ReadTimeout("lent")
    ha = ha_avec(FauxHA({}, {"music_assistant.search": delai}))
    assert "Spotify fait patienter" in ha.musique("Thriller", "track")["erreur"]


def test_resultat_spotify_prefere_a_la_bibliotheque(horloge):
    pistes = [{"name": "Thriller", "uri": "library://track/12", "artists": [{"name": "Artiste Fictif"}]},
              {"name": "Thriller", "uri": "spotify--D7ai9Jsy://track/3S2R0EVwBSAVMd5UMgKTL0", "artists": []}]
    ha = ha_avec(FauxHA({}, {"music_assistant.search": recherche(horloge, 0.2, pistes)}))
    assert ha.chercher_musique("Thriller", "track")["uri"].startswith("spotify--")


def test_pas_de_repli_par_ma_apres_la_prise_de_main(horloge, journal_musique_temporaire):
    # Le groupe ne passe jamais en Spotify Connect : pas de music_assistant.play_media, qui se battrait
    # pour le compte avec la session Connect, et une réponse dans l'échéance.
    etats = {GROUPE: etat("idle", source="Music Assistant Queue"), SALON: etat("idle"),
             SPOTIFY: etat("paused", source="téléphone de Sacha", supported_features=444983,
                           source_list=["téléphone de Sacha", A.HomeAssistant.SPOTIFY_APPAREIL])}
    client = FauxHA(etats)
    ha = ha_avec(client, vraie_attente=True)
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    debut = horloge.time()
    res = ha.musique("Artiste Fictif", "artist")
    assert res["confirme"] is False and "lance" not in res
    assert [s for s, _ in client.appels] == ["media_player.select_source"]
    assert horloge.time() - debut <= A.HomeAssistant.DELAI_MUSIQUE


def test_delai_sur_play_media_de_spotify(horloge, journal_musique_temporaire):
    # play_media dépasse son délai mais l'ordre est passé : l'état tranche, et la ligne de journal part.
    def lent(etats, corps):
        lecture_connect(etats, corps)
        raise httpx.ReadTimeout("lent")
    ha = ha_avec(FauxHA(etats_session_connect(), {"media_player.play_media": lent}), vraie_attente=True)
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    assert ha.musique("Artiste Fictif", "artist")["confirme"] is True
    assert json.loads(journal_musique_temporaire.read_text(encoding="utf-8"))["resultat"] == "confirmé"


def test_ha_injoignable_toujours_journalise(journal_musique_temporaire):
    def coupe(*_):
        raise httpx.ConnectError("HA redémarre")
    ha = ha_avec(FauxHA({}))
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    ha.lire = coupe
    res = ha.musique("Artiste Fictif", "artist")
    assert res["confirme"] is False and "ConnectError" in res["attention"]
    assert len(journal_musique_temporaire.read_text(encoding="utf-8").splitlines()) == 1


def test_relance_espacee(horloge):
    client = FauxHA({SPOTIFY: etat("idle", supported_features=2048)})
    ha = ha_avec(client, vraie_attente=True)
    assert not ha.attendre(lambda: False, 12.0, relancer=SPOTIFY)
    assert [s for s, _ in client.appels] == ["homeassistant.update_entity"] * 2
    client.appels.clear()
    assert ha.attendre(lambda: True, 12.0, relancer=SPOTIFY) and client.appels == []


def test_garde_fou_musique():
    sans = [{"ok": False, "confirme": False, "attention": "..."}]
    assert A.garde_fou_musique("Artiste Fictif est lancé.", sans) == (
        "J'ai demandé la musique, mais les enceintes ne la jouent pas encore.")
    assert A.garde_fou_musique("C'est parti !", [{"erreur": "x"}]) == "Je n'ai pas réussi à lancer cette musique."
    assert A.garde_fou_musique("La demande est partie, ça peut prendre une minute.", sans).startswith("La demande")
    assert A.garde_fou_musique("Artiste Fictif est lancé.", [{"ok": True, "lance": "Artiste Fictif"}]).endswith("lancé.")
    assert A.garde_fou_musique("C'est lancé.", []) == "C'est lancé."


def test_script_de_musique_confirme_par_les_enceintes(journal_musique_temporaire):
    etats = {GROUPE: etat("idle"), SALON: etat("idle"), CUISINE: etat("idle")}
    ha = ha_avec(FauxHA(etats))
    assert ha.confirmer("script.turn_on", {"entity_id": "script.lancer_musique"}) == [GROUPE]
    etats.update({GROUPE: etat("playing"), SALON: etat("playing")})
    assert ha.confirmer("script.turn_on", {"entity_id": "script.lancer_musique"}) == []
    assert ha.confirmer("script.turn_on", {"entity_id": "script.couper_musique"}) == []
    assert len(journal_musique_temporaire.read_text(encoding="utf-8").splitlines()) == 2


def test_dictionnaire_musique_sans_son(journal_musique_temporaire):
    etats = {GROUPE: etat("playing"), SALON: etat("paused"), CUISINE: etat("idle")}
    assistant = A.Assistant.__new__(A.Assistant)
    assistant.ha = ha_avec(FauxHA(etats))
    with pytest.raises(A.NonConfirme) as e:
        assistant.executer({"service": "script.turn_on", "entity_id": "script.lancer_musique"})
    assert e.value.parole == "J'ai demandé la musique, mais les Enceintes ne jouent pas encore."


THRILLER = [{"name": "Thriller", "uri": "spotify--D7ai9Jsy://track/3S2R0EVwBSAVMd5UMgKTL0",
             "artists": [{"name": "Artiste Fictif"}]}]


def test_freinage_pause_puis_second_essai(horloge):
    reponses = [(8.0, []), (0.3, THRILLER)]  # vide après 8 s, puis trouvé (cache de MA)

    def effet(_etats, _corps):
        duree, pistes = reponses.pop(0)
        horloge.sleep(duree)
        return Reponse(200, {"service_response": {"tracks": pistes}})
    ha = ha_avec(FauxHA({}, {"music_assistant.search": effet}))
    debut = horloge.time()
    trouve = ha.chercher_musique("Thriller", "track", fin=debut + 36)
    assert trouve["uri"].endswith("3S2R0EVwBSAVMd5UMgKTL0") and trouve["patience"] is True
    assert 14 <= horloge.time() - debut <= 15
    assert A.patience(trouve)["note"].startswith("Spotify m'a fait patienter")


def test_cache_des_recherches(horloge):
    client = FauxHA({}, {"music_assistant.search": recherche(horloge, 0.3, THRILLER)})
    ha = ha_avec(client)
    assert ha.chercher_musique("Thriller", "track")["titre"] == "Thriller"
    assert ha.chercher_musique("thriller ", "track")["titre"] == "Thriller"
    assert len(client.appels) == 1
    horloge.sleep(601)
    ha.chercher_musique("Thriller", "track")
    assert len(client.appels) == 2


def test_vide_rapide_en_rafale_reessaye(horloge):
    client = FauxHA({}, {"music_assistant.search": recherche(horloge, 0.3)})
    ha = ha_avec(client)
    for nom in ("a", "b", "c"):
        assert ha.chercher_musique(nom, "artist") is None
    assert len(client.appels) == 3  # vides isolés : pas de second essai
    assert ha.chercher_musique("d", "artist") is None
    assert len(client.appels) == 5  # quatrième en 30 s : freinage probable, un second essai


def test_pas_de_second_essai_hors_echeance(horloge):
    client = FauxHA({}, {"music_assistant.search": recherche(horloge, 8.0)})
    ha = ha_avec(client)
    with pytest.raises(A.RechercheLente):
        ha.chercher_musique("Thriller", "track", fin=horloge.time() + 20)
    assert len(client.appels) == 1


def test_phrase_des_enceintes_manquantes():
    assert A.phrase_manquantes([("cuisine", True)]) == (
        "La musique est lancée, mais l'enceinte cuisine est hors ligne.")
    assert A.phrase_manquantes([("cuisine", False), ("salon", True)]) == (
        "La musique est lancée, mais l'enceinte cuisine ne joue pas et l'enceinte salon est hors ligne.")


def test_absentes_distingue_hors_ligne_et_muette():
    etats = {SALON: etat("playing"), CUISINE: etat("unavailable")}
    ha = ha_avec(FauxHA(etats))
    assert ha.absentes() == [("cuisine", True)]
    etats[CUISINE] = etat("idle")
    assert ha.absentes() == [("cuisine", False)]
    etats[CUISINE] = etat("playing")
    assert ha.absentes() == []


def test_spotify_signale_la_cuisine_hors_ligne(journal_musique_temporaire):
    """25/10/2026 : la cuisine débranchée, la musique partait sur le seul salon sans rien dire."""
    etats = etats_session_connect()
    etats[CUISINE] = etat("unavailable")
    ha = ha_avec(FauxHA(etats, {"media_player.play_media": lambda e, c: (lecture_connect(e, c), e.update(
        {CUISINE: etat("unavailable")}))[1]}))
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    res = ha.musique("Artiste Fictif", "artist")
    assert res["confirme"] and res["lance"] == "Artiste Fictif"
    assert res["remarque"].startswith("La musique est lancée, mais l'enceinte cuisine est hors ligne.")
    ligne = json.loads(journal_musique_temporaire.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["muettes"] == "cuisine"


def test_enceinte_nommee_sans_remarque(journal_musique_temporaire):
    """Une enceinte nommée ne fait pas signaler les autres."""
    etats = {SALON: etat("idle"), CUISINE: etat("unavailable"), "media_player.barre_son_salon": etat("idle")}

    def lancer(e, c):
        e[SALON] = etat("playing", media_artist="Artiste Fictif", media_title="Billie Jean")

    ha = ha_avec(FauxHA(etats, {"music_assistant.play_media": lancer}))
    ha.chercher_musique = lambda r, t, a="", fin=None: MJ
    res = ha.musique("Artiste Fictif", "artist", enceinte="salon")
    assert res["confirme"] and "remarque" not in res


def test_script_de_musique_signale_la_cuisine(journal_musique_temporaire):
    etats = {GROUPE: etat("playing"), SALON: etat("playing"), CUISINE: etat("unavailable")}
    assistant = A.Assistant.__new__(A.Assistant)
    assistant.ha = ha_avec(FauxHA(etats))
    remarque = assistant.executer({"service": "script.turn_on", "entity_id": "script.lancer_musique"})
    assert remarque == "La musique est lancée, mais l'enceinte cuisine est hors ligne."
    assert "cuisine" in assistant.ha.service("script", "turn_on", "script.lancer_musique")["note"]
    ligne = json.loads(journal_musique_temporaire.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["muettes"] == "cuisine"
    etats[CUISINE] = etat("playing")
    assert assistant.executer({"service": "script.turn_on", "entity_id": "script.lancer_musique"}) is None


def test_outil_musique_sur_toutes_par_defaut():
    outil = next(o["function"] for o in A.OUTILS if o["function"]["name"] == "jouer_musique")
    assert "sauf si une enceinte précise est nommée" in outil["parameters"]["properties"]["enceinte"]["description"]


def test_transfert_ne_signale_rien(journal_musique_temporaire):
    """Seul le script de lancement vise tout le groupe : un transfert peut viser une seule enceinte."""
    etats = {GROUPE: etat("playing"), SALON: etat("playing"), CUISINE: etat("idle")}
    ha = ha_avec(FauxHA(etats))
    assert ha.confirmer("script.turn_on", {"entity_id": "script.deplacer_musique"}) == []
    assert ha.manquantes == []


def test_synonyme_cite_une_seule_fois(monkeypatch):
    enceintes = dict(A.HomeAssistant.ENCEINTES_MUSIQUE, sejour=A.HomeAssistant.ENCEINTES_MUSIQUE["cuisine"])
    monkeypatch.setattr(A.HomeAssistant, "ENCEINTES_MUSIQUE", enceintes)
    ha = ha_avec(FauxHA({SALON: etat("playing"), CUISINE: etat("unavailable")}))
    assert ha.absentes() == [("cuisine", True)]
