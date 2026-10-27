"""Demandes du client web (S-W3) : ce qu'un navigateur associé a le droit d'envoyer, en quelle quantité, et le fait
que rien ne passe ailleurs que par la chaîne des autres demandes. Le rôle et la personne viennent de la session, jamais
du message. L'essai effectif est celui du serveur OU celui du message."""
import asyncio
import base64
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import appairage_web as AW
import demande_web as D
import maison
import serveur_satellite as S
import serveur_web as W
from test_contexte_requete import ENTITE, faux_assistant, faux_ha
from test_serveur_web_appairage import (  # noqa: F401  (fixtures réutilisées)
    appairer_direct, arreter, entetes, envoyer, fermeture, horloge, journal, lancer, ouvrir_ws, recevoir,
    recevoir_reponse, service, statut_de)

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def quotas_par_defaut(monkeypatch):
    """Les tests ne lisent pas la configuration de la maison : les valeurs par défaut du module, sauf mention."""
    monkeypatch.setattr(maison, "CLIENT_WEB", {})


def regler_quotas(monkeypatch, **sections):
    monkeypatch.setattr(maison, "CLIENT_WEB", {"quotas": sections})


def pcm(secondes=1.0):
    return base64.b64encode(bytes(int(2 * D.TAUX * secondes))).decode("ascii")


# ---------------------------------------------------------------------------------------------------------------
# Le module des demandes : quotas, validations
# ---------------------------------------------------------------------------------------------------------------

def test_quotas_par_defaut_decroissent_avec_le_role():
    for genre in D.GENRES:
        valeurs = [D.quota(genre, r) for r in ("administrateur", "habitant", "invite")]
        assert valeurs == sorted(valeurs, reverse=True) and valeurs[2] > 0, (genre, valeurs)
        assert valeurs[2] <= 5, "l'invité reste faiblement doté"


def test_un_role_inconnu_ou_un_genre_inconnu_n_a_aucun_droit():
    assert D.quota("demande_texte", "partage") == 0
    assert D.quota("demande_texte", "") == 0
    assert D.quota("demande_texte", None) == 0
    assert D.quota("demande_inconnue", "administrateur") == 0


def test_les_quotas_se_lisent_dans_la_configuration(monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 1, "habitant": 7}, voix={"invite": 0})
    assert D.quota("demande_texte", "invite") == 1
    assert D.quota("demande_texte", "habitant") == 7
    assert D.quota("demande_texte", "administrateur") == D.QUOTAS_DEFAUT["demande_texte"]["administrateur"]
    assert D.quota("demande_voix", "invite") == 0
    monkeypatch.setattr(maison, "CLIENT_WEB", {"quotas": "pas un objet"})
    assert D.quota("demande_texte", "invite") == D.QUOTAS_DEFAUT["demande_texte"]["invite"]


def test_zero_retire_le_droit(monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 0})
    with pytest.raises(D.RefusDemande) as e:
        D.Quotas().compter("web:a", "invite", "demande_texte")
    assert e.value.cause == "droit"


def test_quota_depasse_donne_le_delai_avant_la_prochaine_place(monkeypatch, horloge):
    regler_quotas(monkeypatch, texte={"invite": 2})
    q = D.Quotas(horloge)
    q.compter("web:a", "invite", "demande_texte")
    horloge.t += 100
    q.compter("web:a", "invite", "demande_texte")
    with pytest.raises(D.RefusDemande) as e:
        q.compter("web:a", "invite", "demande_texte")
    assert e.value.cause == "quota"
    # La première demande sort de la fenêtre 500 secondes plus tard (fenêtre de 600 s, 100 s déjà écoulées).
    assert 495 <= e.value.attente_s <= 502
    horloge.t += e.value.attente_s
    q.compter("web:a", "invite", "demande_texte")  # une place s'est libérée


def test_quota_par_appareil_et_par_genre(monkeypatch, horloge):
    regler_quotas(monkeypatch, texte={"invite": 1}, voix={"invite": 1})
    q = D.Quotas(horloge)
    q.compter("web:a", "invite", "demande_texte")
    q.compter("web:b", "invite", "demande_texte")  # un autre appareil
    q.compter("web:a", "invite", "demande_voix")   # un autre genre
    with pytest.raises(D.RefusDemande):
        q.compter("web:a", "invite", "demande_texte")


def test_la_fenetre_est_reglable(monkeypatch, horloge):
    monkeypatch.setattr(maison, "CLIENT_WEB", {"quotas": {"fenetre_s": 60, "texte": {"invite": 1}}})
    q = D.Quotas(horloge)
    q.compter("web:a", "invite", "demande_texte")
    with pytest.raises(D.RefusDemande) as e:
        q.compter("web:a", "invite", "demande_texte")
    assert e.value.attente_s <= 61
    horloge.t += 61
    q.compter("web:a", "invite", "demande_texte")


def test_oublier_et_purger(monkeypatch, horloge):
    regler_quotas(monkeypatch, texte={"invite": 1})
    q = D.Quotas(horloge)
    q.compter("web:a", "invite", "demande_texte")
    q.compter("web:b", "invite", "demande_texte")
    q.oublier("web:a")
    q.compter("web:a", "invite", "demande_texte")  # compteur remis à zéro
    horloge.t += D.fenetre_s() + 1
    q.purger()
    assert not q._vus


@pytest.mark.parametrize("brut,attendu", [
    ("allume la cuisine", "allume la cuisine"),
    ("  allume   la\tcuisine \n", "allume la cuisine"),
    ("x" * D.TEXTE_MAX, "x" * D.TEXTE_MAX),
])
def test_texte_valide(brut, attendu):
    assert D.texte_valide(brut) == attendu


@pytest.mark.parametrize("brut", ["", "   ", None, 12, ["a"], {"t": "a"}, "x" * (D.TEXTE_MAX + 1), "bon\x00jour",
                                  "bon\x1bjour", "bon\x7fjour"])
def test_texte_refuse(brut):
    with pytest.raises(D.RefusDemande) as e:
        D.texte_valide(brut)
    assert e.value.cause == "texte"


def test_pcm_valide_decode_les_octets():
    octets = D.pcm_valide(pcm(1.0))
    assert isinstance(octets, bytes) and len(octets) == 2 * D.TAUX
    assert len(D.pcm_valide(pcm(20.0))) == D.PCM_MAX_OCTETS


CAS_PCM_REFUSES = {
    "absent": None, "vide": "", "entier": 12, "octets": b"AAAA", "liste": ["AAAA"],
    "hors alphabet": "pas du base64 !!",
    "octets impairs": base64.b64encode(bytes(D.PCM_MIN_OCTETS + 1)).decode("ascii"),
    "moins de 0,2 s": base64.b64encode(bytes(D.PCM_MIN_OCTETS - 2)).decode("ascii"),
    "plus de 20 s": base64.b64encode(bytes(D.PCM_MAX_OCTETS + 2)).decode("ascii"),
    "texte trop long": "A" * (D.BASE64_MAX + 4),
    "base64 tronque": pcm(1.0)[:-1],
}


@pytest.mark.parametrize("brut", list(CAS_PCM_REFUSES.values()), ids=list(CAS_PCM_REFUSES))
def test_pcm_refuse(brut):
    with pytest.raises(D.RefusDemande) as e:
        D.pcm_valide(brut)
    assert e.value.cause == "audio"


def test_essai_du_message_vaut_vrai_sauf_faux_explicite():
    assert D.essai_du_message({}) is True
    assert D.essai_du_message({"essai": True}) is True
    assert D.essai_du_message({"essai": False}) is False
    for bizarre in ("non", 0, None, [], "false"):
        assert D.essai_du_message({"essai": bizarre}) is True, bizarre


def test_les_causes_sont_une_liste_fermee():
    with pytest.raises(AssertionError):
        D.RefusDemande("n'importe quoi")
    assert {"droit", "quota", "texte", "audio", "occupe", "indisponible", "transcription"} == set(D.CAUSES)


# ---------------------------------------------------------------------------------------------------------------
# Sur la connexion du client web
# ---------------------------------------------------------------------------------------------------------------

def brancher(service, bloque=None, reponse=None):
    """Un demandeur factice qui range les demandes reçues. bloque : un asyncio.Event à lever pour qu'il réponde."""
    vus = []

    async def demandeur(demande):
        vus.append(demande)
        if bloque is not None:
            await bloque.wait()
        res = {"id": "0123456789ab", "texte": demande.texte, "reponse": "C'est fait.", "actions": [],
               "cerveau": "Claude Haiku", "ms": 12, "essai": demande.essai, "erreur": False}
        res.update(reponse or {})
        return res
    service.demandeur = demandeur
    return vus


def scenario_ws(service, jeton, corps):
    """Ouvre une connexion /ws avec ce cookie, lance corps(ws) et renvoie son résultat."""
    async def lance():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws", jeton)
            try:
                return await corps(ws)
            finally:
                await ws.close()
        finally:
            await arreter(serveur)
    return asyncio.run(lance())


async def demander(ws, texte="allume la cuisine", **plus):
    await envoyer(ws, {"type": "demande_texte", "texte": texte, **plus})
    return await recevoir_reponse(ws)


def test_une_demande_ecrite_est_traitee_et_la_reponse_revient_au_navigateur(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher(service)

    async def corps(ws):
        return await demander(ws, "  allume   la cuisine ", essai=False)
    rep = scenario_ws(service, jeton, corps)
    assert rep["type"] == "reponse" and rep["genre"] == "demande_texte"
    assert rep["texte"] == "allume la cuisine" and rep["reponse"] == "C'est fait." and rep["id"] == "0123456789ab"
    assert len(vus) == 1 and vus[0].texte == "allume la cuisine" and vus[0].pcm is None


def test_la_personne_du_message_est_ignoree_le_role_et_l_appareil_viennent_de_la_session(service):
    appareil, _, jeton = appairer_direct(service, "habitant")
    vus = brancher(service)

    async def corps(ws):
        return await demander(ws, personne=maison.CLE_PROPRIETAIRE, role="administrateur", appareil="appareil:tab1",
                              identite="web:autre", habitant=maison.CLE_PROPRIETAIRE)
    assert scenario_ws(service, jeton, corps)["type"] == "reponse"
    d = vus[0]
    assert d.personne is None and d.role == "habitant" and d.appareil == "web:" + appareil["id"]


def test_seul_le_proprietaire_porte_une_personne_et_c_est_celle_de_la_session(service):
    appareil, _, jeton = appairer_direct(service, "administrateur")
    vus = brancher(service)

    async def corps(ws):
        return await demander(ws, personne="un-voisin")
    assert scenario_ws(service, jeton, corps)["type"] == "reponse"
    d = vus[0]
    assert d.role == "administrateur" and d.personne == acces.cle_habitant(maison.CLE_PROPRIETAIRE)
    assert d.personne != "un-voisin"


def test_l_invite_ne_porte_aucune_personne(service):
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher(service)

    async def corps(ws):
        return await demander(ws, personne=maison.CLE_PROPRIETAIRE)
    assert scenario_ws(service, jeton, corps)["type"] == "reponse"
    assert vus[0].personne is None and vus[0].role == "invite"


def test_l_essai_est_vrai_sauf_si_le_message_dit_faux(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher(service)

    async def corps(ws):
        await demander(ws)                    # absent
        await demander(ws, essai="non")       # illisible
        await demander(ws, essai=True)
        await demander(ws, essai=False)
    scenario_ws(service, jeton, corps)
    assert [d.essai for d in vus] == [True, True, True, False]


def test_un_role_sans_droit_est_refuse_avant_tout_traitement(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 0})
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher(service)

    async def corps(ws):
        return await demander(ws)
    rep = scenario_ws(service, jeton, corps)
    assert rep == {"type": "erreur", "cause": "droit", "genre": "demande_texte"}
    assert vus == []


def test_quota_depasse_refus_motive_avec_le_delai(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 2})
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher(service)

    async def corps(ws):
        return [await demander(ws, f"demande {i}") for i in range(3)]
    reps = scenario_ws(service, jeton, corps)
    assert [r["type"] for r in reps] == ["reponse", "reponse", "erreur"]
    assert reps[2]["cause"] == "quota" and reps[2]["genre"] == "demande_texte" and reps[2]["attente_s"] > 0
    assert len(vus) == 2


def test_le_quota_d_un_appareil_ne_ferme_pas_la_porte_a_un_autre(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 1})
    _, _, jeton_a = appairer_direct(service, "invite", "Invité A", conn=1)
    _, _, jeton_b = appairer_direct(service, "invite", "Invité B", conn=2)
    brancher(service)

    async def corps(ws):
        return [(await demander(ws, "une"))["type"], (await demander(ws, "deux"))["type"]]
    assert scenario_ws(service, jeton_a, corps) == ["reponse", "erreur"]
    assert scenario_ws(service, jeton_b, corps) == ["reponse", "erreur"]


def test_un_texte_refuse_ne_consomme_pas_de_place(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 1})
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher(service)

    async def corps(ws):
        refus = [await demander(ws, t) for t in ("", "   ", "x" * 401, "a\x00b")]
        refus.append(await demandes_mal_formees(ws))
        return refus + [await demander(ws, "une vraie demande")]
    reps = scenario_ws(service, jeton, corps)
    assert all(r["type"] == "erreur" and r["cause"] == "texte" for r in reps[:-1]), reps
    assert reps[-1]["type"] == "reponse" and len(vus) == 1


async def demandes_mal_formees(ws):
    await envoyer(ws, {"type": "demande_texte", "texte": ["pas", "une", "chaîne"]})
    return await recevoir_reponse(ws)


def test_une_deuxieme_demande_pendant_la_premiere_est_refusee(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = []

    async def corps(ws):
        bloque = asyncio.Event()  # créé dans la boucle du scénario
        brancher_depuis(service, bloque, vus)
        await envoyer(ws, {"type": "demande_texte", "texte": "première"})
        await asyncio.sleep(0.2)
        await envoyer(ws, {"type": "demande_texte", "texte": "deuxième"})
        refus = await recevoir_reponse(ws)
        bloque.set()
        return refus, await recevoir_reponse(ws)
    refus, reponse = scenario_ws(service, jeton, corps)
    assert refus == {"type": "erreur", "cause": "occupe", "genre": "demande_texte"}
    assert reponse["type"] == "reponse" and reponse["texte"] == "première"
    assert [d.texte for d in vus] == ["première"]


def brancher_depuis(service, bloque, vus):
    async def demandeur(demande):
        vus.append(demande)
        await bloque.wait()
        return {"id": "0123456789ab", "texte": demande.texte, "reponse": "ok", "actions": [], "cerveau": "x",
                "ms": 1, "essai": True, "erreur": False}
    service.demandeur = demandeur


def test_sans_demandeur_branche_la_demande_est_indisponible(service):
    _, _, jeton = appairer_direct(service, "administrateur")
    assert service.demandeur is None

    async def corps(ws):
        return await demander(ws)
    assert scenario_ws(service, jeton, corps) == {"type": "erreur", "cause": "indisponible",
                                                  "genre": "demande_texte"}


def test_une_panne_du_demandeur_ne_montre_jamais_son_texte(service, capsys):
    _, _, jeton = appairer_direct(service, "habitant")

    async def casse(demande):
        raise RuntimeError("clé secrète sk-123 dans le message")
    service.demandeur = casse

    async def corps(ws):
        rep = await demander(ws)
        return rep, await demander(ws, "et ensuite")  # le drapeau « en cours » est retombé
    (rep, suite) = scenario_ws(service, jeton, corps)
    assert rep == {"type": "erreur", "cause": "indisponible", "genre": "demande_texte"}
    assert suite["cause"] == "indisponible"
    sortie = capsys.readouterr().out
    assert "RuntimeError" in sortie and "sk-123" not in sortie


def test_un_refus_du_demandeur_arrive_en_erreur_motivee(service):
    _, _, jeton = appairer_direct(service, "habitant")

    async def refuse(demande):
        raise D.RefusDemande("transcription")
    service.demandeur = refuse

    async def corps(ws):
        return await demander(ws)
    assert scenario_ws(service, jeton, corps)["cause"] == "transcription"


def brancher_voix(service):
    """Un demandeur factice pour les deux genres : il rend le texte « transcrit » d'une demande parlée."""
    vus = []

    async def demandeur(demande):
        vus.append(demande)
        texte = demande.texte if demande.texte is not None else "texte transcrit"
        return {"id": "0123456789ab", "texte": texte, "reponse": "ok", "actions": [], "cerveau": "x", "ms": 1,
                "essai": demande.essai, "erreur": False, "saisie": "voix" if demande.pcm else "texte"}
    service.demandeur = demandeur
    return vus


async def parler_ws(ws, brut=None, **plus):
    await envoyer(ws, {"type": "demande_voix", "pcm": pcm(1.0) if brut is None else brut, **plus})
    return await recevoir_reponse(ws)


def test_une_demande_vocale_arrive_au_demandeur_avec_la_session_et_l_enregistrement(service):
    appareil, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        return await parler_ws(ws, personne=maison.CLE_PROPRIETAIRE, role="administrateur", essai=False)
    rep = scenario_ws(service, jeton, corps)
    assert rep["type"] == "reponse" and rep["genre"] == "demande_voix" and rep["saisie"] == "voix"
    d = vus[0]
    assert d.genre == "demande_voix" and d.texte is None and len(d.pcm) == 2 * D.TAUX
    assert d.personne is None and d.role == "habitant" and d.appareil == "web:" + appareil["id"]
    assert d.essai is False


def test_une_demande_vocale_sans_essai_precise_reste_en_essai(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        return await parler_ws(ws)
    scenario_ws(service, jeton, corps)
    assert vus[0].essai is True


def test_un_enregistrement_de_vingt_secondes_passe_malgre_sa_taille(service):
    """Environ 853 Ko en base64 : bien au-dessus des 64 Ko des autres messages, sous la limite du protocole."""
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)
    gros = pcm(20.0)
    assert len(gros) > W.TAILLE_MESSAGE

    async def corps(ws):
        return await parler_ws(ws, gros)
    assert scenario_ws(service, jeton, corps)["type"] == "reponse"
    assert len(vus[0].pcm) == D.PCM_MAX_OCTETS


CAS_PCM_TEXTES = {nom: v for nom, v in CAS_PCM_REFUSES.items() if isinstance(v, str)}  # ce que JSON sait porter


@pytest.mark.parametrize("brut", list(CAS_PCM_TEXTES.values()), ids=list(CAS_PCM_TEXTES))
def test_un_enregistrement_mal_forme_ou_trop_long_est_refuse_sans_consommer_de_place(service, monkeypatch, brut):
    regler_quotas(monkeypatch, voix={"invite": 1})
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher_voix(service)

    async def corps(ws):
        refus = await parler_ws(ws, brut)
        return refus, await parler_ws(ws)  # la place n'a pas été prise par le refus
    refus, suite = scenario_ws(service, jeton, corps)
    assert refus == {"type": "erreur", "cause": "audio", "genre": "demande_voix"}
    assert suite["type"] == "reponse" and len(vus) == 1


def test_un_enregistrement_absent_ou_d_un_autre_type_est_refuse(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        reps = []
        for plus in ({}, {"pcm": None}, {"pcm": 12}, {"pcm": [1, 2]}, {"pcm": {"a": 1}}):
            await envoyer(ws, {"type": "demande_voix", **plus})
            reps.append(await recevoir_reponse(ws))
        return reps
    reps = scenario_ws(service, jeton, corps)
    assert [r["cause"] for r in reps] == ["audio"] * 5 and vus == []


def test_un_enregistrement_trop_long_pour_le_protocole_ferme_la_connexion(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        await envoyer(ws, {"type": "demande_voix", "pcm": "A" * (W.TAILLE_MESSAGE_VOIX + 10)})
        return await fermeture(ws)
    assert scenario_ws(service, jeton, corps) == 1009
    assert vus == []


def test_seule_la_demande_vocale_a_le_droit_d_etre_grosse(service):
    """Les autres messages, de tout rôle, sont bornés à 64 Ko : la connexion se ferme sur un message plus gros."""
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        await envoyer(ws, {"type": "demande_texte", "texte": "a", "remplissage": "x" * W.TAILLE_MESSAGE})
        return await fermeture(ws)
    assert scenario_ws(service, jeton, corps) == 1009
    assert vus == []


def test_un_message_de_64_ko_pile_ou_moins_passe_encore(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = brancher_voix(service)

    async def corps(ws):
        return await demander(ws, "bonjour", remplissage="x" * (W.TAILLE_MESSAGE - 200))
    assert scenario_ws(service, jeton, corps)["type"] == "reponse" and len(vus) == 1


def test_le_navigateur_non_associe_ne_peut_pas_envoyer_de_gros_messages(service):
    brancher_voix(service)

    async def lance():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(ws, {"type": "code", "code": "x" * (W.TAILLE_MESSAGE + 10)})
            return await fermeture(ws)
        finally:
            await arreter(serveur)
    assert asyncio.run(lance()) == 1009


def test_le_quota_de_voix_est_separe_de_celui_du_texte_et_motive(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 1}, voix={"invite": 1})
    _, _, jeton = appairer_direct(service, "invite")
    brancher_voix(service)

    async def corps(ws):
        return [await demander(ws), await parler_ws(ws), await parler_ws(ws), await demander(ws)]
    reps = scenario_ws(service, jeton, corps)
    assert [r["type"] for r in reps] == ["reponse", "reponse", "erreur", "erreur"]
    assert reps[2]["cause"] == "quota" and reps[2]["genre"] == "demande_voix" and reps[2]["attente_s"] > 0
    assert reps[3]["genre"] == "demande_texte"


def test_un_role_sans_droit_de_voix_est_refuse_avant_toute_lecture_de_l_enregistrement(service, monkeypatch):
    regler_quotas(monkeypatch, voix={"invite": 0})
    _, _, jeton = appairer_direct(service, "invite")
    vus = brancher_voix(service)

    async def corps(ws):
        return await parler_ws(ws, "pas du base64 du tout")
    assert scenario_ws(service, jeton, corps) == {"type": "erreur", "cause": "droit", "genre": "demande_voix"}
    assert vus == []


def test_la_voix_et_le_texte_se_partagent_le_drapeau_en_cours(service):
    _, _, jeton = appairer_direct(service, "habitant")
    vus = []

    async def corps(ws):
        bloque = asyncio.Event()
        brancher_depuis(service, bloque, vus)
        await parler_ws_sans_attente(ws)
        await asyncio.sleep(0.2)
        await envoyer(ws, {"type": "demande_texte", "texte": "pendant"})
        refus = await recevoir_reponse(ws)
        bloque.set()
        await recevoir_reponse(ws)
        return refus
    assert scenario_ws(service, jeton, corps)["cause"] == "occupe"


async def parler_ws_sans_attente(ws):
    await envoyer(ws, {"type": "demande_voix", "pcm": pcm(1.0)})


def test_la_connexion_reste_lisible_pendant_une_demande_longue(service):
    """La demande est lancée à part : un « moi » reçoit sa réponse avant celle de la demande."""
    _, _, jeton = appairer_direct(service, "habitant")
    vus = []

    async def corps(ws):
        bloque = asyncio.Event()
        brancher_depuis(service, bloque, vus)
        await envoyer(ws, {"type": "demande_texte", "texte": "lente"})
        await asyncio.sleep(0.2)
        await envoyer(ws, {"type": "moi"})
        premiere = await recevoir_reponse(ws)
        bloque.set()
        return premiere, await recevoir_reponse(ws)
    premiere, seconde = scenario_ws(service, jeton, corps)
    assert premiere["type"] == "moi" and seconde["type"] == "reponse"


def test_les_deux_genres_sont_listes_pour_tous_les_roles_et_ferment_aux_autres_voies():
    assert set(D.GENRES) <= W.MESSAGES_TOUT_ROLE
    assert D.GENRES == ("demande_texte", "demande_voix")


def test_un_navigateur_pas_encore_associe_ne_peut_rien_demander(service):
    vus = brancher(service)

    async def lance():
        serveur, port = await lancer(service)
        try:
            ws = await ouvrir_ws(port, "/ws/appairage")
            await envoyer(ws, {"type": "demande_texte", "texte": "ouvre tout"})
            return await fermeture(ws)
        finally:
            await arreter(serveur)
    assert asyncio.run(lance()) == 1000
    assert vus == []


def test_sans_session_la_connexion_de_demande_est_refusee(service):
    brancher(service)

    async def lance():
        serveur, port = await lancer(service)
        try:
            with pytest.raises(Exception) as e:
                await ouvrir_ws(port, "/ws")
            return str(e.value)
        finally:
            await arreter(serveur)
    assert "401" in asyncio.run(lance())


def test_retirer_un_appareil_coupe_sa_connexion_et_remet_ses_compteurs_a_zero(service, monkeypatch):
    regler_quotas(monkeypatch, texte={"invite": 1})
    appareil, _, jeton = appairer_direct(service, "invite")
    brancher(service)
    identite = AW.identite_de(appareil["id"])

    async def corps(ws):
        assert (await demander(ws))["type"] == "reponse"
        assert (await demander(ws))["cause"] == "quota"
        service.retirer_acces(identite)
        return await fermeture(ws)
    assert scenario_ws(service, jeton, corps) == W.FERMETURE_REVOQUE
    assert not [c for c in service.quotas._vus if c[0] == identite]


def test_les_satellites_n_acceptent_pas_les_demandes_du_client_web():
    """Seule la connexion web a ces messages : le répartiteur des satellites ne les connaît pas."""
    source = inspect.getsource(S)
    assert not re.search(r"type[\"']?\)?\s*(==|in)\s*[^\n]*demande_(texte|voix)", source)
    assert source.replace("demande_texte", "").count("demande_voix") == 0


# ---------------------------------------------------------------------------------------------------------------
# Le moteur : même chaîne que les autres demandes, jamais une voie à côté du point de contrôle
# ---------------------------------------------------------------------------------------------------------------

class Cerveau:
    """Un cerveau qui essaie d'agir : l'éclairage permis, puis une serrure, puis un appel qui vise tout un étage."""

    def __init__(self, ha):
        self.ha = ha
        self.vu = None
        self.resultats = []

    def repondre(self, texte):
        r = A.requete_en_cours()
        self.vu = (r.essai, r.personne, r.appareil, r.role, r.canal)
        self.resultats = [
            self.ha.service("light", "turn_on", ENTITE),
            self.ha.service("lock", "unlock", None, {"entity_id": "lock.porte"}),
            self.ha.service("light", "turn_on", ENTITE, {"floor_id": "rdc"}),
            self.ha.service("light", "turn_on", None, {"entity_id": ENTITE, "device_id": "abc"}),
        ]
        return "Voilà.", ["light.turn_on ['light.salon_plafond']"]


def moteur_de_test(monkeypatch, essai_serveur=False):
    ha = faux_ha()
    a = faux_assistant(ha)
    a.cerveau, a.apprendre, a.routines_avant = Cerveau(ha), (lambda *x: None), (lambda t: None)
    monkeypatch.setattr(A, "journaliser", lambda *x, **k: None)
    monkeypatch.setattr(S, "lire_journal", lambda n: [])
    monkeypatch.setattr(S.R, "registre", lambda: SimpleNamespace(version=1))
    moteur = object.__new__(S.Moteur)
    moteur.assistant, moteur.essai, moteur.cerveau_actif = a, essai_serveur, "claude"
    moteur.noms = lambda c: c
    moteur.service_web = None
    moteur.stt, moteur.stt_actif = None, "pc"
    return moteur, ha, a.cerveau


def repondre(moteur, **champs):
    base = dict(genre="demande_texte", texte="allume le salon", pcm=None, essai=True, appareil="web:ab12",
                personne=None, role="habitant")
    base.update(champs)

    async def lance():
        moteur.verrou, moteur.verrou_stt = asyncio.Lock(), asyncio.Lock()
        return await moteur.repondre_web(D.Demande(**{k: base[k] for k in ("genre", "texte", "pcm", "essai",
                                                                            "appareil", "personne", "role")}))
    return asyncio.run(lance())


def test_le_moteur_passe_la_session_au_contexte_de_la_requete(monkeypatch):
    moteur, ha, cerveau = moteur_de_test(monkeypatch)
    res = repondre(moteur, personne="camille", role="administrateur", essai=True)
    assert cerveau.vu == (True, "camille", "web:ab12", "administrateur", "web")
    assert res["reponse"] == "Voilà." and res["essai"] is True and res["erreur"] is False
    assert res["texte"] == "allume le salon" and re.fullmatch(r"[0-9a-f]{12}", res["id"])


def test_serveur_en_essai_le_message_ne_rend_pas_la_demande_reelle(monkeypatch):
    moteur, ha, _ = moteur_de_test(monkeypatch, essai_serveur=True)
    res = repondre(moteur, essai=False)
    assert res["essai"] is True
    assert ha.client.posts == []


def test_serveur_reel_message_en_essai_n_agit_pas(monkeypatch):
    moteur, ha, _ = moteur_de_test(monkeypatch, essai_serveur=False)
    res = repondre(moteur, essai=True)
    assert res["essai"] is True and ha.client.posts == []


def test_serveur_reel_message_reel_agit_mais_seulement_par_le_point_de_controle(monkeypatch):
    moteur, ha, cerveau = moteur_de_test(monkeypatch)
    res = repondre(moteur, essai=False)
    assert res["essai"] is False
    # Un seul ordre part vers Home Assistant : l'éclairage permis.
    assert [url for url, _ in ha.client.posts] == ["http://ha/api/services/light/turn_on"]
    ok, serrure, etage, appareil = cerveau.resultats
    assert ok == {"ok": True}
    assert "erreur" in serrure and "interdit" in serrure["erreur"]
    assert "erreur" in etage and "erreur" in appareil


class MoteurStt:
    """Un moteur de transcription du PC : rend le texte voulu et note le signal reçu."""

    def __init__(self, texte="allume le salon", panne=False):
        self.texte, self.panne, self.signaux = texte, panne, []

    def transcrire(self, signal):
        self.signaux.append(signal)
        if self.panne:
            raise RuntimeError("clé secrète sk-456 dans la panne")
        return self.texte


def interdire_les_moteurs_en_ligne(monkeypatch):
    def jamais(*a, **k):
        raise AssertionError("la voix d'un navigateur a quitté la maison")
    monkeypatch.setattr(S, "transcrire_api", jamais)
    monkeypatch.setattr(S, "stt_api_configuree", lambda: True)


def parler(moteur, octets=None, **champs):
    octets = bytes(2 * D.TAUX) if octets is None else octets  # une seconde de silence
    return repondre(moteur, genre="demande_voix", texte=None, pcm=octets, **champs)


def test_une_demande_vocale_est_transcrite_par_le_moteur_du_pc_puis_suit_la_meme_chaine(monkeypatch):
    interdire_les_moteurs_en_ligne(monkeypatch)
    moteur, ha, cerveau = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt("allume le salon")
    res = parler(moteur, essai=False, role="administrateur", personne="camille")
    assert res["texte"] == "allume le salon" and res["saisie"] == "voix" and res["essai"] is False
    assert cerveau.vu == (False, "camille", "web:ab12", "administrateur", "web")
    # La voix passe par le même point de contrôle : un seul ordre part, l'éclairage permis.
    assert [url for url, _ in ha.client.posts] == ["http://ha/api/services/light/turn_on"]
    assert "interdit" in cerveau.resultats[1]["erreur"]
    assert len(moteur.stt.signaux) == 1 and moteur.stt.signaux[0].dtype.name == "float32"
    assert len(moteur.stt.signaux[0]) == D.TAUX


def test_le_pcm_est_lu_en_16_bits_petit_boutiste_et_ramene_entre_moins_un_et_un(monkeypatch):
    import numpy as np
    moteur, _, _ = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt()
    octets = np.array([0, 16384, -32768, 32767] * (D.PCM_MIN_OCTETS // 8), dtype="<i2").tobytes()
    parler(moteur, octets)
    signal = moteur.stt.signaux[0]
    assert signal[:4].tolist() == [0.0, 0.5, -1.0, 32767 / 32768]


def test_une_demande_vocale_sans_moteur_du_pc_passe_par_whisper_de_home_assistant(monkeypatch):
    interdire_les_moteurs_en_ligne(monkeypatch)
    moteur, _, _ = moteur_de_test(monkeypatch)
    moteur.stt = None
    appels = []
    monkeypatch.setattr(S, "transcrire_ha", lambda cible, signal: appels.append((cible, len(signal))) or "ouvre le volet")
    res = parler(moteur)
    assert res["texte"] == "ouvre le volet"
    assert appels == [(S.SERVICES_STT_HA["ha_whisper"][0], D.TAUX)]


def test_le_moteur_choisi_pour_les_satellites_ne_change_pas_la_voie_du_navigateur(monkeypatch):
    """Même si le serveur transcrit en ligne pour les satellites, la voix d'un navigateur reste dans la maison."""
    interdire_les_moteurs_en_ligne(monkeypatch)
    moteur, _, _ = moteur_de_test(monkeypatch)
    moteur.stt, moteur.stt_actif = MoteurStt(), "api"
    assert parler(moteur)["texte"] == "allume le salon"


def test_une_transcription_en_echec_est_une_cause_motivee_sans_fuite(monkeypatch, capsys):
    moteur, ha, _ = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt(panne=True)
    with pytest.raises(D.RefusDemande) as e:
        parler(moteur)
    assert e.value.cause == "transcription" and ha.client.posts == []
    sortie = capsys.readouterr().out
    assert "RuntimeError" in sortie and "sk-456" not in sortie


@pytest.mark.parametrize("texte", ["", "   ", "\n\t", None])
def test_une_transcription_vide_ne_part_pas_dans_la_chaine(monkeypatch, texte):
    moteur, ha, cerveau = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt(texte)
    with pytest.raises(D.RefusDemande) as e:
        parler(moteur)
    assert e.value.cause == "transcription" and cerveau.vu is None and ha.client.posts == []


def test_une_transcription_trop_longue_est_coupee_comme_un_texte_ecrit(monkeypatch):
    moteur, _, _ = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt("mot " * 400)
    assert len(parler(moteur)["texte"]) <= D.TEXTE_MAX


def test_texte_transcrit_nettoie_les_espaces_et_les_caracteres_de_controle():
    assert D.texte_transcrit("  allume \n la\tcuisine\x00 ") == "allume la cuisine"
    assert len(D.texte_transcrit("a " * 500)) <= D.TEXTE_MAX
    for vide in ("", " \n ", "\x00\x01", 12, None):
        with pytest.raises(D.RefusDemande) as e:
            D.texte_transcrit(vide)
        assert e.value.cause == "transcription"


def test_une_demande_vocale_ecrit_au_journal_seulement_le_texte(monkeypatch):
    """Le son n'est ni gardé ni passé au journal : la chaîne ordinaire n'en voit que la transcription."""
    interdire_les_moteurs_en_ligne(monkeypatch)
    moteur, _, cerveau = moteur_de_test(monkeypatch)
    moteur.stt = MoteurStt("allume le salon")
    vus = []
    monkeypatch.setattr(A, "journaliser", lambda *x, **k: vus.append(x))
    parler(moteur, bytes([1, 0]) * D.TAUX)
    assert vus and all(isinstance(v, (str, float, int, list)) for x in vus for v in x)
    assert not any(isinstance(v, (bytes, bytearray)) for x in vus for v in x)


def test_la_reponse_du_moteur_est_du_json_pur(monkeypatch):
    moteur, _, _ = moteur_de_test(monkeypatch)
    json.dumps(repondre(moteur))


# ---------------------------------------------------------------------------------------------------------------
# Aucune voie ne contourne le contrôle : lecture du code des deux modules des demandes
# ---------------------------------------------------------------------------------------------------------------

def sans_commentaires(source):
    """Le code seul : ni commentaires ni docstrings, qui peuvent citer ce qu'ils interdisent."""
    import ast
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        corps = getattr(noeud, "body", None)
        if isinstance(corps, list) and corps and isinstance(corps[0], ast.Expr) \
                and isinstance(getattr(corps[0], "value", None), ast.Constant) \
                and isinstance(corps[0].value.value, str):
            corps[0].value.value = ""
    return ast.unparse(arbre)


@pytest.mark.parametrize("nom", ["demande_web.py", "serveur_web.py"])
def test_ni_le_module_des_demandes_ni_le_serveur_web_n_appellent_home_assistant(nom):
    source = sans_commentaires((RACINE / nom).read_text(encoding="utf-8"))
    for motif in (r"\.service\(", r"/api/services", r"client\.post", r"requests\.", r"httpx", r"urllib\.request",
                  r"ha\.", r"controler_service", r"securite\."):
        assert not re.search(motif, source), (nom, motif)


def test_repondre_web_n_appelle_que_llm_texte_et_aucun_service():
    import textwrap
    source = sans_commentaires(textwrap.dedent(inspect.getsource(S.Moteur.repondre_web)))
    assert "self.llm_texte" in source
    for motif in (r"\.service\(", r"/api/services", r"client\.post", r"transcrire_api", r"\.ha\b"):
        assert not re.search(motif, source), motif


@pytest.mark.parametrize("fonction", ["transcrire_locale", "transcrire_web"])
def test_la_transcription_des_demandes_du_navigateur_n_a_aucune_voie_en_ligne(fonction):
    import textwrap
    source = sans_commentaires(textwrap.dedent(inspect.getsource(getattr(S.Moteur, fonction))))
    for motif in (r"transcrire_api", r"stt_api_configuree", r"self\.transcrire\(", r"stt_actif", r"requests\.",
                  r"httpx", r"urllib", r"anthropic", r"STT_API"):
        assert not re.search(motif, source, re.I), (fonction, motif)
    assert ("ha_whisper" in source) == (fonction == "transcrire_locale")


def test_aucun_moteur_en_ligne_dans_le_module_des_demandes():
    source = sans_commentaires((RACINE / "demande_web.py").read_text(encoding="utf-8"))
    assert "transcrire_api" not in source and "anthropic" not in source.lower()


# ---------------------------------------------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------------------------------------------

def test_pages_demander_exigent_une_session_et_s_ouvrent_a_tous_les_roles(service):
    rep = service.traiter("127.0.0.1", "/demander", entetes())
    assert statut_de(rep) == 303 and rep[1]["Location"] == "/appairage"
    assert statut_de(service.traiter("127.0.0.1", "/demander.js", entetes())) == 401
    for conn, role in enumerate(("administrateur", "habitant", "invite"), start=1):
        _, _, jeton = appairer_direct(service, role, f"Appareil {role}", conn=conn)
        page = service.traiter("127.0.0.1", "/demander", entetes(jeton))
        assert statut_de(page) == 200, role
        html = page[2].decode("utf-8")
        assert "{{" not in html and "0.11.0" in html and maison.NOM_ASSISTANT in html, role
        assert statut_de(service.traiter("127.0.0.1", "/demander.js", entetes(jeton))) == 200, role


def test_la_page_demander_n_a_ni_script_ni_style_en_ligne():
    html = (RACINE / "web" / "demander.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "style=" not in html and "<style" not in html
    assert not re.search(r"\son[a-z]+=", html), "aucun gestionnaire d'événement en ligne"
    js = (RACINE / "web" / "demander.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js and "eval(" not in js


def test_le_client_enregistre_en_16_khz_mono_pour_20_secondes_au_plus_et_ne_pose_pas_de_style_en_ligne():
    """Le micro : même format et mêmes bornes que le serveur (demande_web), CSP stricte respectée (CSSOM, pas
    d'attribut style), micro libéré à l'arrêt, à l'annulation et quand la page se cache."""
    js = (RACINE / "web" / "demander.js").read_text(encoding="utf-8")
    html = (RACINE / "web" / "demander.html").read_text(encoding="utf-8")
    assert f"TAUX = {D.TAUX};" in js and f"DUREE_MAX_S = {D.DUREE_MAX_S};" in js
    assert "getUserMedia" in js and '"demande_voix"' in js and "setInt16(i * 2, pcm[i], true)" in js
    assert 'setAttribute("style"' not in js and ".cssText" not in js and "style.setProperty" in js
    assert "getTracks().forEach" in js and "pagehide" in js and "visibilitychange" in js
    assert 'id="bouton-micro"' in html and 'id="orbe-ecoute"' in html and 'id="annuler-ecoute"' in html
    assert "hidden" in re.search(r'<button id="bouton-micro"[^>]*>', html).group(0), "caché tant que le script ne l'a pas validé"
    assert "microphone=(self)" in W.ENTETES_SECURITE["Permissions-Policy"]


def test_le_client_web_ne_parle_qu_a_son_serveur():
    for nom in ("demander.js", "demander.html"):
        texte = (RACINE / "web" / nom).read_text(encoding="utf-8")
        assert not re.search(r"https?://", texte), nom
    js = (RACINE / "web" / "demander.js").read_text(encoding="utf-8")
    assert "/api/services" not in js and "/ha/" not in js


def test_l_accueil_connecte_propose_demander(service):
    _, _, jeton = appairer_direct(service, "habitant")
    rep = service.traiter("127.0.0.1", "/", entetes(jeton))
    corps = rep[2].decode("utf-8")
    assert statut_de(rep) == 200 and 'id="onglet-micro"' in corps and 'href="/ecouter"' in corps
