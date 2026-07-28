# 跨平台 pkg2mpkg 第一阶段设计

- 日期：2026-07-28
- 状态：待用户书面审阅
- 目标平台：macOS、Windows、Linux
- 目标客户端：未修改的官方 Wallpaper Engine Android 2.8.8

## 1. 背景与证据边界

本项目从 Windows Wallpaper Engine 2.8.26 的安装目录重新分析 exportMobilePkg，并实现独立的跨平台 pkg2mpkg。Windows 行为研究只使用以下目录：

~~~
/Users/anpple/Codex/WallpaperEngine/research/Wallpaper Engine.2.8.26
~~~

仓库中已有的 pkg2mpkg 工具、分析文档和历史实现均不作为格式或算法依据。它们可以继续存在，但新实现不得导入其代码，也不得用其结论替代对 Windows 2.8.26 的验证。

Android 兼容性以连接车机上的官方应用为黑盒验收基准：

- 包名：io.wallpaperengine.weclient
- 版本：2.8.8（versionCode 4354）
- Android：12（API 31）
- 显示器：1920 × 1080
- 官方动态壁纸服务：WEWallpaperService

当前确认的直接证据包括：

- Windows UI 只把 Scene 和 Video 交给移动导出；Web、Application 被过滤。
- exportMobilePkg 接收壁纸数组、属性、标题、mpkgversionoverride 和导出设置。
- Windows 动态预设使用 compression 与 reduction；预渲染预设使用视频尺寸、FPS、裁切和对齐。
- Windows 转码阶段依次包含打开 PKG、解包、复制文件、生成缩略图、复制 project.json、转换纹理或视频、重新打包。
- Windows 2.8.26 二进制包含 PKGM0020、scene.pkg、wallpaper.mp4 和 mp4_h264。
- 官方 Android APK 可读取 PKGM0018 和 PKGM0020。
- 官方 Android 内置 Dino Run 的 project.json 明确为 type: scene；其 JavaScript 是 Scene 脚本，不是 Web 内容。

## 2. 第一阶段目标

第一阶段交付一个 Rust 核心库、命令行工具和 egui 桌面 GUI，并允许使用隔离的辅助程序完成专有资源转换及 Scene 预渲染。

第一阶段的成功标准是 Android 行为一致，而不是 Windows 输出逐字节一致。生成的 MPKG 必须能被未修改的官方 Android 应用导入、展示、预览、应用，并在应用或壁纸服务重启后恢复。

### 2.1 支持范围

#### Scene

- High Quality 动态导出。
- Balanced 动态导出。
- 自定义 compression 和 reduction。
- High Performance 预渲染为 H.264 Video MPKG。
- 保留动态 Scene 的脚本、触摸交互、音频响应、用户属性和场景资源。
- 预渲染模式只保证录制后的画面与音频；时钟、触摸和实时状态等动态行为不会继续运行。

#### Video

- 将官方 Video 项目和受支持的本地 MP4/WebM 输入规范化为 H.264 MP4。
- 生成包含 wallpaper.mp4 的 Video MPKG。
- 保留合理的循环、画面方向和音频行为。

#### 分辨率

- 官方 1080p、4K UHD 和 Original 预设。
- 手动指定目标分辨率 WIDTH × HEIGHT。
- 通过 ADB 自动读取目标设备显示尺寸和旋转方向。
- 车机自动模式保留实际横屏方向，不强制套用官方手机竖屏归一化规则。

### 2.2 明确排除

以下类型在输入分析阶段立即拒绝：

- Web
- Application

CLI、Rust API 和 GUI 必须返回同一个 UnsupportedWallpaperType 错误。第一阶段不得将这两种类型静默录屏、伪装成 Scene 或自动改成 Video。未来若增加 Web/Application 预渲染，应作为独立功能重新设计。

### 2.3 非目标

- 第一阶段不要求与 Windows 2.8.26 的 MPKG 逐字节相同。
- 不实现 WebView、CEF 或 Application 运行时。
- 不实现 Steam 登录、Workshop 下载、作者协议确认或联网传输协议。
- 不修改、注入或重新签名官方 Android APK。
- 不把官方 Wallpaper Engine 可执行文件或 DLL 提交到本仓库。

## 3. 方案选择

评估过 3 种实现方式：

1. 纯 Rust 原生实现所有容器、纹理、Scene 渲染和视频编码。长期可移植性最好，但完整 Scene 渲染器的范围远大于 pkg2mpkg，无法作为第一阶段前置条件。
2. 完全调用 Windows exportMobilePkg。短期最接近官方输出，但只是套壳，无法建立可复用 Rust 库，也无法逐步替换专有行为。
3. Rust 主导的混合架构。Rust 实现输入分析、预设决策、MPKG、验证和公共 API；FFmpeg 与 Scene/资源辅助后端只承担明确的转换任务。

选择方案 3。生产流程不得调用 Windows exportMobilePkg 直接生成最终 MPKG。Windows 2.8.26 仅作为差分基准，以及在专有 Scene 渲染尚未原生化时由用户提供的运行时来源。

## 4. 工作区与模块边界

新代码位于独立 Rust workspace，避免与现有 Android 工程耦合。

### 4.1 pkg2mpkg-core

职责：

- 定位并解析输入项目。
- 识别 Scene、Video、Web 和 Application。
- 表示 project.json、导出属性和 MPKG 文件表。
- 生成不可变的 ExportPlan。
- 调度转换、打包、验证和进度事件。
- 提供稳定的 Rust 公共 API。

core 不直接依赖 egui、ADB 或具体进程实现。

### 4.2 pkg2mpkg-codecs

职责：

- 图片探测、缩放、裁切和编码。
- Wallpaper Engine 纹理资源的转换适配。
- FFmpeg/ffprobe 调用。
- H.264/AAC 输出规范化。
- SceneCaptureBackend 和 ResourceTranscodeBackend 的进程适配。

所有外部程序均使用参数数组启动，不经过 shell 字符串拼接。

### 4.3 pkg2mpkg-device

职责：

- 发现 ADB 设备。
- 读取物理分辨率、覆盖分辨率、密度、旋转方向和当前用户。
- 查询官方 WE 包版本。
- 选择目标兼容性配置。
- 执行可选的只读检查和显式启用的导入/应用验收。

### 4.4 pkg2mpkg-cli

提供以下命令：

~~~
pkg2mpkg inspect <input>
pkg2mpkg export <input> --output <file.mpkg> [options]
pkg2mpkg verify <file.mpkg> [--device <serial>]
pkg2mpkg device list
pkg2mpkg device inspect [--serial <serial>]
~~~

export 支持多个输入。每个输出独立原子提交；批处理中一个项目失败不会破坏其他已完成输出，但最终进程状态为失败并给出逐项结果。

### 4.5 pkg2mpkg-gui

GUI 使用 egui，并直接调用 core：

1. 选择一个或多个输入。
2. 显示类型、标题、原始尺寸和风险。
3. 选择动态或预渲染质量。
4. 选择设备自动、官方预设或手动分辨率。
5. 显示 ExportPlan 摘要。
6. 导出并展示分阶段进度。
7. 可选执行 MPKG 或设备验证。

GUI 不复制类型判断、预设矩阵或输出命名逻辑。

### 4.6 pkg2mpkg-fixtures

保存可公开提交的小型合成样本、预期结构摘要和哈希。受版权限制的 Windows/Android 原始包只通过本地 fixture manifest 引用，不提交内容本身。

## 5. 领域模型与公共接口

核心类型：

~~~
WallpaperKind = Scene | Video | Web | Application

ExportMode =
  SceneDynamic
  | ScenePreRenderedVideo
  | Video

DynamicSettings {
  compression,
  reduction
}

VideoSettings {
  resolution,
  fps,
  crop_mode,
  alignment_x,
  alignment_y,
  audio_policy
}

ExportPlan {
  source,
  kind,
  mode,
  compatibility,
  properties,
  transformations,
  output,
  estimated_size,
  helper_requirements
}
~~~

ExportPlan 可序列化为 JSON。inspect 与 export --dry-run 必须能输出它，GUI 也使用同一对象展示实际行为。

公共库以显式 Context 接收取消令牌、进度回调、临时目录策略和后端集合。库不得自行退出进程、弹出窗口或读取全局 GUI 状态。

## 6. 输入解析

SourceResolver 接受：

- 包含 project.json 的项目目录。
- project.json 文件路径。
- 能定位同级或父级 project.json 的 .pkg 文件。
- 直接 MP4/WebM 文件；此时由 CLI 参数或文件名建立最小 Video 项目元数据。

解析顺序：

1. 规范化绝对路径，但不修改输入。
2. 确定项目根目录和入口文件。
3. 读取 project.json 并保留未知字段。
4. 从 type 与 file 联合判断类型；type 大小写不敏感并归一化为核心枚举。
5. 验证所有引用均留在项目根目录或受支持的容器内。
6. Web/Application 返回 UnsupportedWallpaperType。
7. 生成 SourceProject。

类型缺失时只允许以下无歧义推断：

- HTML 入口判定为 Web。
- EXE 入口判定为 Application。
- 受支持的视频扩展名和 MIME 判定为 Video。
- 只有经 Scene 入口结构验证的 JSON 才判定为 Scene。

其他情况返回 InvalidProjectType，不能默认当作 Scene，也不能通过删除 type 字段绕过 Web/Application 拒绝规则。

## 7. Windows 2.8.26 预设行为

动态模式保留 Windows UI 的配置值：

| 预设 | 内容类别 | compression | reduction |
|---|---|---|---|
| High Quality | Pixel art | high_quality | high_quality |
| High Quality | Normal | high_performance | high_quality |
| High Quality | UHD | high_performance | reduction_x2 |
| Balanced | Pixel art | high_performance | high_quality |
| Balanced | Normal | high_performance | reduction_x2 |
| Balanced | UHD | high_performance | reduction_x4 |

高级模式允许直接选择：

- compression：high_quality、high_performance。
- reduction：high_quality、reduction_x2、reduction_x4。

High Performance 使用预渲染视频，默认值：

- 分辨率：1080p。
- FPS：30。
- 裁切：cropphone。
- 对齐：50。

官方导出文件模式不提供设备 Auto 选项；本工具额外提供手动分辨率和 ADB Auto。

CLI 的 Scene 导出必须显式给出 high、balanced、performance 或 custom；没有显式值时只生成 dry-run，不开始转换。GUI 可以记住上次选择，但导出按钮附近始终显示当前模式。Video 输入自动选择 VideoPipeline；未提供视频变换参数时保留源尺寸和受支持的源 FPS，仅在编解码器不兼容时规范化。提供分辨率、FPS、裁切或 performance 时执行完整视频转换。

导出前清理 Windows UI 中不会传给移动端的当前属性：

- alignment
- alignmentx
- alignmenty
- alignmentz
- alignmentposition
- alignmentfliph
- pluginledextensionsenableleds
- wec_e
- wec_brs
- wec_con
- wec_sat
- wec_hue
- rate

清理只作用于待导出的属性覆盖，不盲目删除场景文件中的同名普通字段。

## 8. 分辨率、裁切与方向

ResolutionSpec 支持：

- Preset1080p
- Preset4K
- Original
- Exact(width, height)
- AdbAuto(serial)

H.264 Android 兼容输出使用 8-bit YUV 4:2:0，因此 Exact 的宽高必须为正偶数。奇数尺寸返回 InvalidTargetResolution，并建议相邻的两个偶数值；程序不得静默改变用户明确指定的尺寸。

ADB Auto 的计算顺序：

1. 读取 wm size 的 override；无 override 时使用 physical。
2. 读取当前 display rotation。
3. 得到设备实际逻辑方向。
4. 对车机保留横屏；不执行 min(width, height) × max(width, height) 的手机竖屏归一化。
5. 将最终尺寸记录到 ExportPlan，保证后续设备状态变化不会改变正在运行的任务。

裁切模式：

- Cover：填满指定的目标画布，超出部分裁切，对应 cropphone。选择该模式时 Exact 的宽高就是最终视频宽高。
- KeepAspect：不裁切、不拉伸、不主动加黑边，对应 disabled。1080p、4K 或 Exact 被解释为最大边界，程序在边界内计算保持源比例的最终偶数宽高；Original 保留源像素尺寸。最终尺寸必须在 ExportPlan 中明确显示。
- ContainPad 不在第一阶段提供，避免把 Windows 的「Keep original aspect ratio」错误实现成带黑边的视频。
- Stretch 不在第一阶段提供。

alignment_x 和 alignment_y 取值为 0 到 100。50 表示居中；只有存在对应方向的溢出时才生效。Windows 兼容输入中的 videoalignment 在进入核心模型时完成方向映射，避免 UI 与转换器重复反转。

动态 Scene 的目标分辨率不改变场景画布；它只参与纹理预设建议和设备验收。Exact/ADB Auto 的强制像素尺寸用于预渲染 Scene 和 Video 输出。

## 9. Scene 动态导出

SceneDynamicPipeline：

1. 打开并验证 scene.pkg 或项目资源集合。
2. 解包到任务专属临时目录。
3. 复制 project.json、Scene 入口和被引用资源。
4. 根据属性覆盖建立移动项目清单。
5. 按 compression/reduction 转换纹理及其元数据。
6. 生成 Android 可读取的预览图。
7. 写入 PKGM0020。
8. 重新读取输出并执行结构、引用和类型验证。

脚本、粒子、材质、模型、声音和 Scene 层级默认保留。任何无法转换但又被引用的资源必须使任务失败，不能悄悄遗漏。

Dino Run 是动态 Scene 的首要综合样本，因为它同时覆盖：

- Scene JavaScript。
- 动态创建图层。
- 用户属性。
- localStorage。
- 触摸/游标接口。
- 音效。
- 多纹理和多背景配置。

第一阶段要求 Android 侧行为一致，不要求纹理压缩后的字节与 Windows 相同；但尺寸、Alpha、色彩空间和引用关系必须一致。

## 10. Video 与 Scene 预渲染

### 10.1 VideoPipeline

输出 wallpaper.mp4 必须满足：

- H.264/AVC。
- 8-bit YUV 4:2:0。
- 恒定输出尺寸。
- 30 或 60 FPS，或兼容模式下保留受支持的源 FPS。
- 有音频时规范化为 Android 支持的 AAC-LC；无音频时不创建空音轨。
- 元数据旋转烘焙到像素，输出旋转标记归零。

即使源文件已经是 H.264，也只有在 Windows 差分样本证明可直接复制，且无需尺寸、裁切、FPS、旋转或音频转换时才允许 passthrough。否则统一转码。

### 10.2 ScenePreRenderedPipeline

1. 用选定用户属性启动 SceneCaptureBackend。
2. 以固定时间步长渲染帧，避免依赖机器实时速度。
3. 捕获 Scene 音频或按策略关闭音频。
4. 按 crop/alignment 映射到目标画布。
5. 交给 VideoPipeline 编码 wallpaper.mp4。
6. 生成 type: video 的移动 project.json。
7. 打包并验证 MPKG。

Windows UI 不暴露预渲染时长。兼容后端必须通过 Windows 2.8.26 差分样本确定其循环/时长策略。在该策略通过至少 3 个不同 Scene 样本验证前，High Performance 模式标记为实验性，不能宣称第一阶段完成。CLI 可提供显式 --duration 作为研究和扩展选项，但默认值必须来自已验证的兼容策略。

预渲染后不承诺保留触摸、时钟、音频响应、网络状态或其他运行时交互；GUI 必须在导出前显示这一差异。

## 11. 辅助程序与跨平台策略

### 11.1 FFmpeg

- 为每个平台提供固定版本的 ffmpeg/ffprobe，或允许显式指定系统版本。
- 启动时记录版本和二进制 SHA-256。
- 许可证及构建配置随发行包提供。
- 所有编码参数由 ExportPlan 生成，GUI 不直接拼接参数。

### 11.2 Scene/资源后端

定义两个可替换接口：

- ResourceTranscodeBackend：解码、缩放并重新编码专有纹理资源。
- SceneCaptureBackend：加载 Scene、应用属性、按固定时间步长输出帧和音频。

辅助进程通过版本化 JSON Lines 协议通信：

~~~
hello
capabilities
start
progress
warning
result
cancel
~~~

协议必须包含后端版本、目标平台、GPU 后端、支持的资源格式和运行时版本。能力不满足 ExportPlan 时在写输出前失败。

第一阶段允许用户通过 --we-runtime 指向合法持有的 Windows 2.8.26 目录。Windows 可原生启动兼容后端；macOS/Linux 可通过隔离的 Wine 兼容层启动。该路径只承担资源转换或帧渲染，最终 project.json 和 MPKG 始终由 Rust 生成。

发行包不得重新分发官方 WE 二进制。未来原生 Scene/纹理后端可在不改变 core、CLI 或 GUI 的情况下替换兼容后端。

## 12. MPKG 读写

Reader：

- 接受 PKGM0018 与 PKGM0020。
- 使用流式读取，验证所有整数运算和范围。
- 拒绝重复路径、绝对路径、父目录逃逸、NUL、越界区间和重叠区间。
- 支持只读取目录和指定文件，不要求一次加载整个包。

Writer：

- 第一阶段默认输出 PKGM0020。
- 文件顺序由显式 Windows2826OrderingPolicy 决定，不依赖 HashMap 迭代顺序。
- JSON 编码、换行、路径分隔符和预览图格式保持确定性。
- 偏移和长度写入前检查溢出。
- 输出达到或超过 4 GiB 时返回 PackageTooLarge。
- 写入 .partial，完成 fsync 和自验证后再原子重命名。

Writer API 保留 ContainerVersion 和 OrderingPolicy 参数，为后续逐字节阶段切换策略，不污染业务层。

## 13. 错误、取消与诊断

错误对象包含：

- 稳定错误码。
- 当前阶段。
- 输入和输出路径。
- 人类可读说明。
- 底层原因链。
- 可执行的处理建议。

主要 CLI 退出码：

| 退出码 | 类别 |
|---|---|
| 0 | 成功 |
| 2 | 参数或配置错误 |
| 3 | Web/Application 等不支持类型 |
| 4 | 项目、PKG 或 MPKG 无效 |
| 5 | 辅助程序缺失或版本不兼容 |
| 6 | 纹理、视频或 Scene 转换失败 |
| 7 | 输出 I/O、空间或 4 GiB 限制 |
| 8 | 输出自验证失败 |
| 9 | ADB 或设备验证失败 |
| 130 | 用户取消 |

CLI 提供 --json-errors。GUI 使用同一错误码映射本地化提示。

取消必须沿 Context 传播到 Rust 任务和子进程。子进程先接收协议 cancel，超时后终止当前子进程；不得杀死不属于本任务的系统进程。

默认失败时保留诊断 manifest 和日志，但删除不完整输出。--keep-temp 显式保留转换目录，日志中必须移除配对密钥等敏感数据。

## 14. 安全与数据完整性

- 输入始终只读。
- 每次导出使用独立、权限受限的临时目录。
- 解包执行路径穿越、符号链接逃逸、重复路径和大小上限检查。
- 外部程序不接受拼接后的 shell 命令。
- 对帧数、纹理尺寸、文件数量、单文件大小和总解包大小设置可配置上限。
- 后端二进制按版本和 SHA-256 校验。
- ADB 导入和应用是显式操作；普通 verify 不改变当前壁纸。
- 不记录设备配对密钥或用户内容正文。

## 15. 测试策略

### 15.1 单元测试

- PKGM0018/0020 合法和畸形容器。
- 文件表偏移、溢出、重复路径和路径逃逸。
- 类型识别及 Web/Application 负例。
- High Quality/Balanced 预设矩阵。
- 属性清理列表。
- 1080p、4K、Exact 和 ADB Auto。
- Cover/KeepAspect、横竖屏、alignment_x/y。
- H.264 偶数尺寸约束。
- 原子输出和取消。

### 15.2 Windows 差分测试

为同一输入生成 Windows 2.8.26 官方输出和本工具输出，至少覆盖：

- 普通 Scene：High Quality、Balanced。
- Pixel art Scene：High Quality、Balanced。
- UHD Scene：High Quality、Balanced。
- Scene：High Performance、1080p/4K、30/60 FPS、Cover/KeepAspect。
- H.264 MP4 Video。
- Web 与 Application 拒绝。

第一阶段比较：

- 容器版本及文件清单。
- project.json 的语义字段。
- 资源引用闭包。
- 解码后纹理尺寸、像素和 Alpha。
- wallpaper.mp4 的尺寸、FPS、时长、画面方向、音轨和可解码性。

逐字节哈希只记录，不作为第一阶段门禁。

### 15.3 Android 端到端测试

在未修改官方 WE 上验证：

1. MPKG 可导入且没有 Import failed。
2. 标题、预览和类型正确。
3. 可进入预览并应用为 WEWallpaperService。
4. Scene 脚本持续运行。
5. 用户属性生效。
6. 触摸、声音、音频响应及其他声明能力按样本工作。
7. Video 循环、裁切、方向和音频正确。
8. 应用进程或壁纸服务重启后仍可恢复。
9. 1920 × 1080 车机 Auto 输出没有被误转为竖屏。

设备导入/应用测试必须显式启用，并记录测试前状态。能够安全恢复时自动恢复；无法读取官方应用内部选择时，测试报告明确提示人工恢复。

### 15.4 跨平台测试

- macOS arm64。
- Windows x86-64。
- Linux x86-64。
- 同一 ExportPlan 在不同平台的 MPKG 结构和 JSON 必须确定性一致。
- 视频编码允许平台实现产生不同码流，但解码语义必须满足相同验收指标。

## 16. 完成定义

第一阶段只有在以下条件全部满足后才算完成：

- Rust 库、CLI 和 egui GUI 均可发布。
- Scene 动态 High Quality/Balanced 在 3 个桌面平台可导出。
- Scene High Performance 可稳定预渲染为 Video MPKG。
- Video 可规范化并打包。
- 手动 Exact 与 ADB Auto 分辨率工作。
- Web/Application 在所有入口一致拒绝。
- 输出通过内部 verify。
- 车机上的未修改官方 WE 2.8.8 通过 Android 端到端矩阵。
- 无输入文件被修改，无失败输出冒充成功文件。
- 依赖、辅助后端和限制有完整文档。

后续逐字节阶段将在不改变公共导出模型的前提下，锁定 Windows 文件排序、JSON 空白、纹理编码器版本、视频编码参数及所有二进制元数据。
