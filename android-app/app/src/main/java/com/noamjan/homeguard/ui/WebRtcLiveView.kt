package com.noamjan.homeguard.ui

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.webkit.JavaScriptReplyProxy
import androidx.webkit.WebMessageCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.google.gson.Gson
import com.noamjan.homeguard.data.StreamSession
import com.noamjan.homeguard.data.normalizeWebSocketUrl
import com.noamjan.homeguard.logging.AppLogger
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

private const val APP_ORIGIN = "https://appassets.androidplatform.net"
private const val LIVE_PAGE = "$APP_ORIGIN/assets/live_view.html"
private const val MAX_SIGNAL_BYTES = 32 * 1024

@Composable
fun WebRtcLiveView(
    session: StreamSession,
    modifier: Modifier = Modifier,
    onStatus: (String) -> Unit,
) {
    val controller = remember(session.launch.sessionId) { SignalingWebViewController(session, onStatus) }
    DisposableEffect(controller) { onDispose { controller.close() } }
    AndroidView(
        factory = { context -> controller.create(context) },
        modifier = modifier,
    )
}

private class SignalingWebViewController(
    private val session: StreamSession,
    private val onStatus: (String) -> Unit,
) {
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
    private var webView: WebView? = null
    private var socket: WebSocket? = null
    private var closed = false

    @SuppressLint("SetJavaScriptEnabled")
    fun create(context: android.content.Context): WebView {
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(context))
            .build()
        val view = WebView(context).also { webView = it }
        view.setBackgroundColor(android.graphics.Color.BLACK)
        view.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = false
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        view.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                request.url.host != "appassets.androidplatform.net"

            override fun onPageFinished(view: WebView, url: String) {
                if (url != LIVE_PAGE || closed) return
                val config = gson.toJson(
                    mapOf(
                        "sessionId" to session.launch.sessionId,
                        "iceServers" to session.launch.iceServers,
                    )
                )
                view.evaluateJavascript("window.homeGuardStart(${JSONObject.quote(config)})", null)
            }
        }

        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            status("This Android WebView is too old for secure Live View")
            return view
        }
        WebViewCompat.addWebMessageListener(
            view,
            "HomeGuardNative",
            setOf(APP_ORIGIN),
            object : WebViewCompat.WebMessageListener {
                override fun onPostMessage(
                    view: WebView,
                    message: WebMessageCompat,
                    sourceOrigin: Uri,
                    isMainFrame: Boolean,
                    replyProxy: JavaScriptReplyProxy,
                ) {
                    if (!isMainFrame || sourceOrigin.toString() != APP_ORIGIN || closed) return
                    handlePageMessage(message.data.orEmpty())
                }
            },
        )
        view.loadUrl(LIVE_PAGE)
        return view
    }

    private fun handlePageMessage(raw: String) {
        if (raw.length > MAX_SIGNAL_BYTES) {
            status("Live View message was rejected")
            return
        }
        runCatching {
            val message = JSONObject(raw)
            when (message.optString("action")) {
                "connect" -> connect()
                "signal" -> sendSignal(message.getString("message"))
                "close" -> close()
                "status" -> status(message.optString("message").take(160))
            }
        }.onFailure { error ->
            AppLogger.w("WebRTC", "Invalid message from bundled Live View page", error = error)
            status("Live View protocol error")
        }
    }

    private fun connect() {
        if (socket != null || closed) return
        val signalingUrl = normalizeWebSocketUrl(session.launch.signalingUrl)
        val request = Request.Builder()
            .url(signalingUrl)
            .header("Authorization", "Bearer ${session.accessToken}")
            .build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                val join = JSONObject()
                    .put("sessionId", session.launch.sessionId)
                    .put("type", "join")
                    .put("requestId", UUID.randomUUID().toString().replace("-", ""))
                    .put("payload", JSONObject()
                        .put("role", "viewer")
                        .put("deviceId", session.viewerDeviceId))
                webSocket.send(join.toString())
                status("Secure signaling connected")
                AppLogger.i("WebRTC", "Viewer joined signaling", mapOf("session_id" to session.launch.sessionId))
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (text.length > MAX_SIGNAL_BYTES) {
                    webSocket.close(1008, "Signal too large")
                    return
                }
                postToPage(JSONObject().put("action", "signal").put("payload", JSONObject(text)).toString())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                socket = null
                postToPage(JSONObject().put("action", "socket_closed").toString())
                AppLogger.i("WebRTC", "Viewer signaling closed", mapOf("session_id" to session.launch.sessionId, "code" to code))
            }

            override fun onFailure(webSocket: WebSocket, error: Throwable, response: Response?) {
                socket = null
                AppLogger.e("WebRTC", "Viewer signaling failed", mapOf("session_id" to session.launch.sessionId, "status" to response?.code), error)
                postToPage(JSONObject().put("action", "socket_error").put("message", "Secure signaling failed").toString())
                status("Secure signaling failed")
            }
        })
    }

    private fun sendSignal(raw: String) {
        if (raw.length > MAX_SIGNAL_BYTES) throw IllegalArgumentException("Signal is too large")
        val message = JSONObject(raw)
        require(message.optString("sessionId") == session.launch.sessionId) { "Wrong stream session" }
        require(message.optString("type") in setOf("answer", "leave", "ping")) { "Unsupported viewer signal" }
        require(message.optString("requestId").length in 8..100) { "Invalid signal request ID" }
        require(socket?.send(message.toString()) == true) { "Signaling connection is unavailable" }
    }

    private fun postToPage(raw: String) {
        val view = webView ?: return
        view.post {
            if (!closed && WebViewFeature.isFeatureSupported(WebViewFeature.POST_WEB_MESSAGE)) {
                WebViewCompat.postWebMessage(view, WebMessageCompat(raw), Uri.parse(APP_ORIGIN))
            }
        }
    }

    private fun status(value: String) {
        if (value.isBlank()) return
        webView?.post { onStatus(value) } ?: onStatus(value)
        AppLogger.d("WebRTC", value.take(160), mapOf("session_id" to session.launch.sessionId))
    }

    fun close() {
        if (closed) return
        closed = true
        socket?.let { webSocket ->
            runCatching {
                webSocket.send(
                    JSONObject()
                        .put("sessionId", session.launch.sessionId)
                        .put("type", "leave")
                        .put("requestId", UUID.randomUUID().toString().replace("-", ""))
                        .toString()
                )
            }
            webSocket.close(1000, "Live View closed")
        }
        socket = null
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
        webView?.post {
            runCatching { WebViewCompat.removeWebMessageListener(webView!!, "HomeGuardNative") }
            webView?.stopLoading()
            webView?.loadUrl("about:blank")
            webView?.destroy()
            webView = null
        }
    }
}
