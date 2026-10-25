package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

class DecouverteTest {

    private val pc = "wss://192.0.2.10:8766"

    @Test
    fun hotesSepareLesNomsEtIgnoreLeVide() {
        assertEquals(listOf("pc.local", "ha.local"), Decouverte.hotes(" pc.local, ha.local ,, pc.local"))
        assertEquals(emptyList<String>(), Decouverte.hotes(""))
        assertEquals(emptyList<String>(), Decouverte.hotes("http://x/y, a b"))
    }

    @Test
    fun candidatsMetLAdresseConfigureeEnDernier() {
        val c = Decouverte.candidats(pc, listOf("pc.local"), null)
        assertEquals(listOf("wss://pc.local:8766", pc), c)
    }

    @Test
    fun candidatsMetLaDerniereCibleEnPremierSansDoublon() {
        val c = Decouverte.candidats(pc, listOf("pc.local"), "wss://192.0.2.99:8766/")
        assertEquals(listOf("wss://192.0.2.99:8766", "wss://pc.local:8766", pc), c)
        assertEquals(listOf("wss://pc.local:8766", pc), Decouverte.candidats(pc, listOf("pc.local"), "wss://pc.local:8766"))
    }

    @Test
    fun candidatsIgnoreUneDerniereCibleDUnAutreSchema() {
        val c = Decouverte.candidats(pc, emptyList(), "ws://192.0.2.99:8765")
        assertEquals(listOf(pc), c)
    }

    @Test
    fun candidatsSansAdresseExploitable() {
        assertEquals(emptyList<String>(), Decouverte.candidats("", listOf("pc.local"), null))
    }

    @Test
    fun cibleDeTourneSurLaListe() {
        val l = listOf("a", "b", "c")
        assertEquals("a", Decouverte.cibleDe(l, 0))
        assertEquals("c", Decouverte.cibleDe(l, 2))
        assertEquals("a", Decouverte.cibleDe(l, 3))
        assertNull(Decouverte.cibleDe(emptyList(), 1))
    }

    @Test
    fun jetonRefuseSeDitEtSeReappaire() {
        val inconnu = Decouverte.diagnostic(4001, "jeton invalide", null, null, "x:1")
        assertEquals(Decouverte.Cause.JETON, inconnu.cause)
        assertTrue(inconnu.jetonRefuse)
        assertTrue(Decouverte.diagnostic(4001, "appareil révoqué", null, null, "x:1").texte.contains("révoqué"))
        assertTrue(Decouverte.diagnostic(4001, "jeton absent", null, null, "x:1").texte.contains("absent"))
        assertEquals(Decouverte.Cause.JETON, Decouverte.diagnostic(null, null, 401, null, "x:1").cause)
    }

    @Test
    fun reseauRefuseEtReponseInattendue() {
        val d = Decouverte.diagnostic(4003, "", null, null, "x:1")
        assertEquals(Decouverte.Cause.RESEAU_REFUSE, d.cause)
        assertFalse(d.jetonRefuse)
        assertEquals(Decouverte.Cause.SERVEUR, Decouverte.diagnostic(null, null, 502, null, "x:1").cause)
    }

    @Test
    fun exceptionsReseauEtCertificat() {
        assertEquals(Decouverte.Cause.RESEAU, Decouverte.diagnostic(null, null, null, UnknownHostException("h"), "x:1").cause)
        assertEquals(Decouverte.Cause.RESEAU, Decouverte.diagnostic(null, null, null, SocketTimeoutException(), "x:1").cause)
        assertEquals(Decouverte.Cause.RESEAU, Decouverte.diagnostic(null, null, null, ConnectException(), "x:1").cause)
        assertEquals(Decouverte.Cause.CERTIFICAT, Decouverte.diagnostic(null, null, null, SSLException("tls"), "x:1").cause)
        val enchaine = RuntimeException("enveloppe", Confiance.CleChangee("x:1", "a", "b"))
        assertEquals(Decouverte.Cause.CERTIFICAT, Decouverte.diagnostic(null, null, null, enchaine, "x:1").cause)
    }

    @Test
    fun ceQuiFaitUneAlerteSurLAccueil() {
        val sans = Accueil.panne(true, true, true, true, true, "ok", "")
        assertEquals("", sans)
        val jeton = Accueil.panne(true, true, true, true, true, "ok", "", "Jeton refusé")
        assertTrue(jeton.contains("Appareils"))
        // La clé refusée reste prioritaire sur le jeton.
        assertTrue(Accueil.panne(true, true, true, true, true, "ok", "cle", "Jeton refusé").startsWith("Clé"))
    }
}
