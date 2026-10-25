package assistant.vocal.jarvis

import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Poignée de main WebSocket bornée (0.32.1) : un serveur qui accepte la connexion puis se tait, comme l'appli
 * HA qui redémarre, doit finir en onFailure au lieu de bloquer l'appel pour toujours. Une liaison montée, elle,
 * survit au délai : il ne s'applique qu'à la poignée de main.
 */
class ConfianceWebSocketTest {
    private class Ecouteur : WebSocketListener() {
        val ouvert = CountDownLatch(1)
        val echec = CountDownLatch(1)
        @Volatile var cause: Throwable? = null
        override fun onOpen(webSocket: WebSocket, response: Response) = ouvert.countDown()
        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            cause = t
            echec.countDown()
        }
    }

    private fun serveur(repondre: Boolean): ServerSocket {
        val s = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
        thread(isDaemon = true) {
            val gardees = mutableListOf<Socket>()
            try {
                while (true) {
                    val c = s.accept()
                    gardees.add(c)
                    if (!repondre) continue  // accepte puis se tait
                    val lecteur = c.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                    var cle = ""
                    while (true) {
                        val ligne = lecteur.readLine() ?: break
                        if (ligne.isEmpty()) break
                        if (ligne.startsWith("Sec-WebSocket-Key:", ignoreCase = true)) cle = ligne.substringAfter(':').trim()
                    }
                    val accepte = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
                        .digest((cle + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray(Charsets.ISO_8859_1)))
                    c.getOutputStream().write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n" +
                        "Connection: Upgrade\r\nSec-WebSocket-Accept: $accepte\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
                    c.getOutputStream().flush()
                }
            } catch (_: Exception) {
                gardees.forEach { runCatching { it.close() } }
            }
        }
        return s
    }

    private fun requete(s: ServerSocket) = Request.Builder().url("ws://127.0.0.1:${s.localPort}/").build()

    @Test
    fun unServeurMuetApresAcceptFinitEnEchec() {
        serveur(repondre = false).use { s ->
            val e = Ecouteur()
            val ws = Confiance.clientWebSocket(connexionS = 2, poigneeDeMainMs = 500).newWebSocket(requete(s), e)
            try {
                assertTrue("aucun onFailure : la poignée de main bloque", e.echec.await(5, TimeUnit.SECONDS))
                assertNotNull(e.cause)
                assertFalse(e.ouvert.await(0, TimeUnit.MILLISECONDS))
            } finally {
                ws.cancel()
            }
        }
    }

    @Test
    fun uneLiaisonMonteeSurvitAuDelaiDePoigneeDeMain() {
        serveur(repondre = true).use { s ->
            val e = Ecouteur()
            // 1000 ms laisse à une JVM froide le temps de la poignée de main, l'attente de 2500 ms dépasse l'échéance.
            val ws = Confiance.clientWebSocket(connexionS = 2, poigneeDeMainMs = 1000).newWebSocket(requete(s), e)
            try {
                assertTrue("liaison jamais ouverte", e.ouvert.await(5, TimeUnit.SECONDS))
                assertFalse("liaison coupée par le délai de poignée de main", e.echec.await(2500, TimeUnit.MILLISECONDS))
            } finally {
                ws.cancel()
            }
        }
    }

    @Test
    fun leClientDeBaseBorneLaPoigneeDeMain() {
        val c = Confiance.clientWebSocket()
        assertTrue(c.callTimeoutMillis == Confiance.POIGNEE_DE_MAIN_MS.toInt())
        assertTrue(c.readTimeoutMillis == 0 && c.pingIntervalMillis == 20_000)
    }
}
