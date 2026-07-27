package com.motif.wallpaperengine

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.motif.wallpaperengine.importscan.WeLibrarySync
import com.motif.wallpaperengine.importscan.WeMpkgDelivery
import com.motif.wallpaperengine.importscan.WePackageScan
import com.motif.wallpaperengine.importscan.WeReceiveServer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * 车机 WE 添加入口：
 * - 扫码导入：HTTP 上传到适配目录
 * - 导入文件：扫描适配目录 → 点选/全部 **入库官方 WE 壁纸库**（files/downloads）
 */
class MainActivity : ComponentActivity() {
    private var receiveServer: WeReceiveServer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WePackageScan.ensureRecommendedDirs(this)

        val initialMode = intent?.getStringExtra("we_mode") // qr | scan | null

        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize(), color = Color.White) {
                    WeAddScreen(
                        initialMode = initialMode,
                        onRequestStorage = { ensureStorageAccess() },
                        onImportOne = { c ->
                            val o = WeLibrarySync.importOne(this, c, openPreview = true, forceRestartWe = true)
                            Toast.makeText(this, o.message, Toast.LENGTH_SHORT).show()
                            o.ok
                        },
                        onImportAll = { list, onProgress ->
                            WeLibrarySync.importAll(this, list, onProgress)
                        },
                        onOpenLibrary = { WeLibrarySync.openWeLibrary(this) },
                        onStartReceive = { onFile ->
                            if (receiveServer?.isRunning() != true) {
                                receiveServer = WeReceiveServer(this) { f ->
                                    runOnUiThread {
                                        Toast.makeText(this, "已接收 ${f.name}", Toast.LENGTH_SHORT).show()
                                        onFile(f)
                                    }
                                }.also { it.start() }
                            }
                            receiveServer!!.localUrls()
                        },
                        onStopReceive = {
                            receiveServer?.stop()
                            receiveServer = null
                        },
                        isImported = { name, bytes ->
                            WeLibrarySync.isMarkedImported(this, name, bytes)
                        },
                    )
                }
            }
        }

        handleImportExtras(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleImportExtras(intent)
    }

    private fun handleImportExtras(intent: Intent?) {
        when {
            intent?.getBooleanExtra("import_test", false) == true -> {
                window.decorView.post {
                    val r = WeMpkgDelivery.deliverAsset(this, "we_packs/1994794519_DVA.mpkg")
                    Toast.makeText(this, r.message, Toast.LENGTH_SHORT).show()
                }
            }
            !intent?.getStringExtra("import_path").isNullOrBlank() -> {
                val rel = intent.getStringExtra("import_path")!!
                window.decorView.post {
                    val base = getExternalFilesDir(null) ?: filesDir
                    val file = File(base, rel)
                    val c = WePackageScan.Candidate(
                        file = file,
                        label = file.name,
                        bytes = file.length(),
                        bucket = "app",
                        sourceHint = "adb",
                    )
                    val o = WeLibrarySync.importOne(this, c, forceRestartWe = true)
                    Toast.makeText(this, o.message, Toast.LENGTH_LONG).show()
                }
            }
            !intent?.getStringExtra("import_asset").isNullOrBlank() -> {
                val asset = intent.getStringExtra("import_asset")!!
                window.decorView.post {
                    val r = WeMpkgDelivery.deliverAsset(this, asset)
                    Toast.makeText(this, r.message, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    override fun onDestroy() {
        receiveServer?.stop()
        super.onDestroy()
    }

    private fun ensureStorageAccess() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (!Environment.isExternalStorageManager()) {
                runCatching {
                    startActivity(
                        Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                            data = android.net.Uri.parse("package:$packageName")
                        },
                    )
                }
            }
        }
        val need = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE)
            != PackageManager.PERMISSION_GRANTED
        ) {
            need += Manifest.permission.READ_EXTERNAL_STORAGE
        }
        if (need.isNotEmpty()) requestPermissions(need.toTypedArray(), 1001)
    }
}

private val WeBlue = Color(0xFF1565C0)
private val WeBlueDark = Color(0xFF0D47A1)
private val WeBarGray = Color(0xFF9E9E9E)

@Composable
private fun WeAddScreen(
    initialMode: String?,
    onRequestStorage: () -> Unit,
    onImportOne: (WePackageScan.Candidate) -> Boolean,
    onImportAll: suspend (List<WePackageScan.Candidate>, (Int, Int, String) -> Unit) -> Pair<Int, Int>,
    onOpenLibrary: () -> Unit,
    onStartReceive: ((File) -> Unit) -> List<String>,
    onStopReceive: () -> Unit,
    isImported: (String, Long) -> Boolean,
) {
    var screen by remember {
        mutableStateOf(
            when (initialMode) {
                "qr" -> "qr"
                "scan" -> "scan"
                else -> "home"
            },
        )
    }
    var status by remember { mutableStateOf("适配目录扫描后入库官方 WE 壁纸库（files/downloads）") }
    var candidates by remember { mutableStateOf<List<WePackageScan.Candidate>>(emptyList()) }
    var scanning by remember { mutableStateOf(false) }
    var importing by remember { mutableStateOf(false) }
    var qrUrls by remember { mutableStateOf<List<String>>(emptyList()) }
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current

    fun doScan() {
        scanning = true
        status = "正在扫描适配目录…"
        scope.launch {
            val list = withContext(Dispatchers.IO) {
                WePackageScan.ensureRecommendedDirs(context)
                WePackageScan.scanAll(context)
            }
            candidates = list
            scanning = false
            status = if (list.isEmpty()) {
                "未找到 .mpkg。请先扫码上传或拷到 Download/motif_live/we/"
            } else {
                "发现 ${list.size} 个包 · 点选入库，或全部写入 WE 壁纸库"
            }
        }
    }

    LaunchedEffect(screen) {
        if (screen == "scan") {
            onRequestStorage()
            doScan()
        }
        if (screen == "qr") {
            qrUrls = onStartReceive { doScan() }
            status = "扫码/浏览器打开下方地址上传 .mpkg"
        }
    }

    DisposableEffect(Unit) {
        onDispose { onStopReceive() }
    }

    Column(Modifier.fillMaxSize()) {
        // 顶栏仿官方 WE
        Box(
            Modifier
                .fillMaxWidth()
                .background(WeBlue)
                .padding(horizontal = 24.dp, vertical = 20.dp),
        ) {
            Column {
                Text("Wallpaper Engine", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Medium)
                Text("壁纸引擎 · 车机添加", color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp)
            }
        }
        Box(
            Modifier
                .fillMaxWidth()
                .background(WeBarGray)
                .padding(vertical = 10.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(status, color = Color.White, fontSize = 14.sp, textAlign = TextAlign.Center)
        }

        when (screen) {
            "home" -> HomeAddButtons(
                onQr = { screen = "qr" },
                onScan = { screen = "scan" },
                onOpenLibrary = onOpenLibrary,
            )
            "qr" -> QrPanel(
                urls = qrUrls,
                onBack = {
                    onStopReceive()
                    screen = "home"
                },
                onGoScan = { screen = "scan" },
            )
            "scan" -> ScanPanel(
                candidates = candidates,
                scanning = scanning,
                importing = importing,
                isImported = isImported,
                onRefresh = { doScan() },
                onBack = { screen = "home" },
                onImportOne = { c ->
                    importing = true
                    status = "正在入库 ${c.file.name} → WE 壁纸库…"
                    val ok = onImportOne(c)
                    importing = false
                    status = if (ok) "已入库: ${c.file.name}（打开官方 WE 壁纸页可见）" else "入库失败"
                },
                onImportAll = {
                    if (candidates.isEmpty()) return@ScanPanel
                    importing = true
                    scope.launch {
                        val (ok, fail) = onImportAll(candidates) { cur, total, name ->
                            status = "入库中 $cur/$total · $name"
                        }
                        importing = false
                        status = "完成：成功 $ok · 失败 $fail · 已写入 WE 壁纸库"
                        doScan()
                    }
                },
                onOpenLibrary = onOpenLibrary,
            )
        }
    }
}

@Composable
private fun HomeAddButtons(
    onQr: () -> Unit,
    onScan: () -> Unit,
    onOpenLibrary: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        BigWeButton(text = "扫码导入", onClick = onQr)
        Text(
            "手机扫码上传 .mpkg 到车机，无需连接 Windows 电脑。",
            Modifier
                .widthIn(max = 360.dp)
                .padding(bottom = 24.dp),
            color = Color.Gray,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
            minLines = 2,
        )
        // 文案保持官方「导入文件」
        BigWeButton(text = "导入文件", onClick = onScan)
        Text(
            "选择存储在移动设备上的视频、GIF 或导出的壁纸，将其用作动态壁纸。",
            Modifier
                .widthIn(max = 360.dp)
                .padding(bottom = 16.dp),
            color = Color.Gray,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
            minLines = 2,
        )
        Text(
            "实际：扫描车机适配目录，入库官方 WE 壁纸库 downloads/",
            color = Color(0xFF666666),
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.widthIn(max = 400.dp),
        )
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = onOpenLibrary) {
            Text("打开官方 WE 壁纸库", color = WeBlue)
        }
    }
}

@Composable
private fun BigWeButton(text: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier
            .widthIn(min = 300.dp)
            .height(100.dp),
        shape = RoundedCornerShape(4.dp),
        colors = ButtonDefaults.buttonColors(containerColor = WeBlue, contentColor = Color.White),
    ) {
        Text(text, fontSize = 20.sp)
    }
}

@Composable
private fun QrPanel(
    urls: List<String>,
    onBack: () -> Unit,
    onGoScan: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("扫码导入", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = WeBlueDark)
        Spacer(Modifier.height(12.dp))
        Text(
            "手机与车机同一网络，浏览器打开：",
            color = Color.Gray,
            fontSize = 14.sp,
        )
        Spacer(Modifier.height(16.dp))
        urls.forEach { url ->
            Text(
                url,
                fontSize = 20.sp,
                fontWeight = FontWeight.Medium,
                color = WeBlue,
                modifier = Modifier.padding(vertical = 6.dp),
            )
        }
        Spacer(Modifier.height(12.dp))
        Text(
            "上传完成后点下方「导入文件」扫描并写入 WE 壁纸库。",
            color = Color.DarkGray,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onGoScan, colors = ButtonDefaults.buttonColors(containerColor = WeBlue)) {
                Text("导入文件（扫描入库）")
            }
            TextButton(onClick = onBack) { Text("返回") }
        }
    }
}

@Composable
private fun ScanPanel(
    candidates: List<WePackageScan.Candidate>,
    scanning: Boolean,
    importing: Boolean,
    isImported: (String, Long) -> Boolean,
    onRefresh: () -> Unit,
    onBack: () -> Unit,
    onImportOne: (WePackageScan.Candidate) -> Unit,
    onImportAll: () -> Unit,
    onOpenLibrary: () -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("导入文件", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = WeBlueDark)
            TextButton(onClick = onBack) { Text("返回") }
        }
        Text(
            "适配目录 → 入库官方 WE 壁纸库（downloads/）",
            color = Color.Gray,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = onRefresh,
                enabled = !scanning && !importing,
                colors = ButtonDefaults.buttonColors(containerColor = WeBlue),
            ) { Text(if (scanning) "扫描中…" else "重新扫描") }
            Button(
                onClick = onImportAll,
                enabled = !scanning && !importing && candidates.isNotEmpty(),
                colors = ButtonDefaults.buttonColors(containerColor = WeBlueDark),
            ) { Text(if (importing) "入库中…" else "全部入库 WE") }
            TextButton(onClick = onOpenLibrary) { Text("打开壁纸库") }
        }
        Spacer(Modifier.height(12.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(candidates, key = { it.file.absolutePath }) { c ->
                val imported = isImported(c.file.name, c.bytes)
                Column(
                    Modifier
                        .fillMaxWidth()
                        .background(
                            if (imported) Color(0xFFE8F5E9) else Color(0xFFF5F5F5),
                            RoundedCornerShape(8.dp),
                        )
                        .clickable(enabled = !importing) { onImportOne(c) }
                        .padding(12.dp),
                ) {
                    Text(c.file.name, fontWeight = FontWeight.Medium)
                    Text(
                        "${c.label} · ${if (imported) "已标记入库" else "点选入库 WE"}",
                        fontSize = 12.sp,
                        color = Color.Gray,
                    )
                    Text(c.file.parent ?: "", fontSize = 11.sp, color = Color.Gray, maxLines = 1)
                }
            }
        }
    }
}
