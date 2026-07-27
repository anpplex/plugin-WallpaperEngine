package com.motif.wallpaperengine.importscan

import android.content.Context
import android.util.Log
import java.io.BufferedReader
import java.io.File
import java.io.FileOutputStream
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * 简易 HTTP 接收：手机浏览器打开上传页，.mpkg 落到适配目录后可扫库入库。
 */
class WeReceiveServer(
    private val context: Context,
    private val port: Int = 8765,
    private val onFileReceived: (File) -> Unit = {},
) {
    private val running = AtomicBoolean(false)
    private var server: ServerSocket? = null

    fun isRunning(): Boolean = running.get()

    fun localUrls(): List<String> {
        val ips = mutableListOf<String>()
        runCatching {
            NetworkInterface.getNetworkInterfaces()?.toList()?.forEach { ni ->
                if (!ni.isUp || ni.isLoopback) return@forEach
                ni.inetAddresses.toList().forEach { addr ->
                    if (addr is Inet4Address && !addr.isLoopbackAddress) {
                        ips += "http://${addr.hostAddress}:$port/"
                    }
                }
            }
        }
        if (ips.isEmpty()) ips += "http://127.0.0.1:$port/"
        return ips
    }

    fun start() {
        if (!running.compareAndSet(false, true)) return
        WePackageScan.ensureRecommendedDirs(context)
        thread(name = "WeReceiveServer", isDaemon = true) {
            try {
                val ss = ServerSocket(port)
                server = ss
                Log.i(TAG, "listening on $port urls=${localUrls()}")
                while (running.get()) {
                    val client = runCatching { ss.accept() }.getOrNull() ?: break
                    thread(isDaemon = true) { handle(client) }
                }
            } catch (e: Exception) {
                Log.e(TAG, "server error", e)
            } finally {
                running.set(false)
                runCatching { server?.close() }
            }
        }
    }

    fun stop() {
        running.set(false)
        runCatching { server?.close() }
        server = null
    }

    private fun handle(socket: Socket) {
        try {
            socket.soTimeout = 120_000
            val input = socket.getInputStream()
            val reader = BufferedReader(InputStreamReader(input, Charsets.ISO_8859_1))
            val requestLine = reader.readLine() ?: return
            val parts = requestLine.split(" ")
            val method = parts.getOrNull(0) ?: "GET"
            val path = parts.getOrNull(1) ?: "/"

            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
                val idx = line.indexOf(':')
                if (idx > 0) {
                    headers[line.substring(0, idx).trim().lowercase()] =
                        line.substring(idx + 1).trim()
                }
            }

            val out = socket.getOutputStream()
            when {
                method == "GET" && (path == "/" || path.startsWith("/?")) -> {
                    writeResponse(out, 200, "text/html; charset=utf-8", HTML.toByteArray(Charsets.UTF_8))
                }
                method == "POST" && path.startsWith("/upload") -> {
                    val len = headers["content-length"]?.toLongOrNull() ?: 0L
                    val ctype = headers["content-type"] ?: ""
                    val saved = saveUpload(input, len, ctype)
                    if (saved != null) {
                        onFileReceived(saved)
                        val body = "OK saved ${saved.name} (${saved.length()} bytes)\n扫码页可关闭，回车机点「导入文件」入库 WE 库。"
                        writeResponse(out, 200, "text/plain; charset=utf-8", body.toByteArray(Charsets.UTF_8))
                    } else {
                        writeResponse(out, 400, "text/plain; charset=utf-8", "upload failed\n".toByteArray())
                    }
                }
                else -> writeResponse(out, 404, "text/plain", "not found\n".toByteArray())
            }
        } catch (e: Exception) {
            Log.w(TAG, "handle: ${e.message}")
        } finally {
            runCatching { socket.close() }
        }
    }

    private fun saveUpload(input: java.io.InputStream, contentLength: Long, contentType: String): File? {
        val destDir = File(context.getExternalFilesDir(null), WePackageScan.FOLDER_WE_IMPORT).apply { mkdirs() }
        // 也写一份到 Download/motif_live/we（若可写）
        val publicWe = File("/sdcard/Download/motif_live/we").apply { runCatching { mkdirs() } }

        return try {
            if (contentType.contains("multipart/form-data")) {
                val boundary = contentType.substringAfter("boundary=", "").trim()
                if (boundary.isEmpty()) return null
                val max = contentLength.coerceAtMost(200L * 1024 * 1024).toInt()
                val raw = readFully(input, max)
                val text = String(raw, Charsets.ISO_8859_1)
                val nameMatch = Regex("""filename="([^"]+)"""").find(text)
                val fileName = nameMatch?.groupValues?.get(1)?.substringAfterLast('/') ?: "upload.mpkg"
                val headerEnd = text.indexOf("\r\n\r\n")
                if (headerEnd < 0) return null
                val dataStart = headerEnd + 4
                val endMarker = "\r\n--$boundary"
                val dataEnd = text.indexOf(endMarker, dataStart).let { if (it < 0) raw.size else it }
                val fileBytes = raw.copyOfRange(dataStart, dataEnd)
                val dest = File(destDir, sanitize(fileName))
                FileOutputStream(dest).use { it.write(fileBytes) }
                runCatching { File(publicWe, dest.name).writeBytes(fileBytes) }
                dest
            } else {
                val dest = File(destDir, "upload_${System.currentTimeMillis()}.mpkg")
                FileOutputStream(dest).use { out ->
                    var left = contentLength
                    val buf = ByteArray(64 * 1024)
                    while (left > 0) {
                        val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                        if (n <= 0) break
                        out.write(buf, 0, n)
                        left -= n
                    }
                }
                dest
            }
        } catch (e: Exception) {
            Log.e(TAG, "saveUpload", e)
            null
        }
    }

    private fun readFully(input: java.io.InputStream, size: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream(size.coerceAtMost(8 * 1024 * 1024))
        val buf = ByteArray(64 * 1024)
        var left = size
        while (left > 0) {
            val n = input.read(buf, 0, minOf(buf.size, left))
            if (n <= 0) break
            out.write(buf, 0, n)
            left -= n
        }
        return out.toByteArray()
    }

    private fun sanitize(name: String): String {
        val n = name.replace(Regex("[^A-Za-z0-9._\\-\\u4e00-\\u9fff]"), "_")
        return if (n.endsWith(".mpkg", true) || n.endsWith(".bin", true)) n else "$n.mpkg"
    }

    private fun writeResponse(out: OutputStream, code: Int, type: String, body: ByteArray) {
        val status = when (code) {
            200 -> "OK"
            400 -> "Bad Request"
            else -> "Not Found"
        }
        val header = "HTTP/1.1 $code $status\r\n" +
            "Content-Type: $type\r\n" +
            "Content-Length: ${body.size}\r\n" +
            "Connection: close\r\n\r\n"
        out.write(header.toByteArray(Charsets.US_ASCII))
        out.write(body)
        out.flush()
    }

    companion object {
        private const val TAG = "WeReceiveServer"
        private val HTML = """
            <!DOCTYPE html><html><head><meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width,initial-scale=1"/>
            <title>车机 WE 导入</title>
            <style>
              body{font-family:sans-serif;padding:24px;max-width:480px;margin:auto;background:#0b1a33;color:#eee}
              h1{font-size:1.3rem} .btn{display:block;width:100%;padding:16px;margin:12px 0;font-size:1.1rem;
              background:#1565c0;color:#fff;border:0;border-radius:8px}
              input{width:100%;padding:12px;margin:8px 0}
            </style></head><body>
            <h1>Wallpaper Engine · 扫码上传</h1>
            <p>选择 .mpkg（Windows 移动导出包），上传到车机适配目录，再在车机点「导入文件」写入壁纸库。</p>
            <form action="/upload" method="post" enctype="multipart/form-data">
              <input type="file" name="file" accept=".mpkg,application/octet-stream" required/>
              <button class="btn" type="submit">上传到车机</button>
            </form>
            </body></html>
        """.trimIndent()
    }
}
