"""Vision déportée sur le PC : calcul du regard et réponses du serveur sans moteur ou sans image."""
import vision as VI


def test_regard_de_face_et_de_profil():
    de_face = [[100, 100], [140, 100], [120, 125], [105, 145], [135, 145]]
    profil = [[100, 100], [140, 100], [138, 125], [120, 145], [145, 145]]
    assert VI.regard(de_face)[0] is True
    assert VI.regard(profil)[0] is False


def test_sans_moteur():
    assert "erreur" in VI.traiter_message(None, {"id": 3, "jpeg": "AAAA"})


def test_image_absente_ou_illisible():
    class Faux:
        def analyser(self, jpeg):
            raise ValueError("image illisible")
    assert "erreur" in VI.traiter_message(Faux(), {"id": 1})
    rep = VI.traiter_message(Faux(), {"id": 2, "jpeg": "AAAA"})
    assert rep["id"] == 2 and "illisible" in rep["erreur"]
