# PCB Art for 嘉立创EDA

[![Tests](https://github.com/Oweik/pcb-art-easyeda/actions/workflows/test.yml/badge.svg)](https://github.com/Oweik/pcb-art-easyeda/actions/workflows/test.yml)

一个面向 Codex 的 PCB 艺术画 Skill：把已经设计好的双面黑白分层图，导入嘉立创EDA专业版，生成可追溯的铜、阻焊开窗、丝印和矩形板框；提供原生工程导出、材料示意预览和独立解析验证的 Gerber 草稿。

**它是制造图层工具，不是一键把任意彩色插画变成生产稿的转换器。** 彩色参考图需要先按五官、头发、服装与背景进行语义分层和视觉精修。

## 能做什么

- 正反面六层：铜、阻焊开窗、白丝印；黑色为选中几何。
- 大图按层写入原生 Image 图元，避免创建几万个独立 Fill。
- 毫米尺寸、统一画布、闭合板框、背面一次镜像。
- 开窗下铜覆盖、丝印与开窗避让、原生位置与几何回读。
- 正常观看方向的双面预览，以及覆铜 / 无铜色差较低时的检查图。
- 嘉立创EDA `.epro2` 文件导出；本地 Gerber 草稿、独立 `gerbonara` 回读与 ZIP 一致性检查。
- 中断记录保留文档 UUID、窗口和已返回的图元 ID；超时不自动重试。

## 安装

克隆到 Codex 技能目录。已有同名目录时先检查并保留本地修改。

```powershell
git clone https://github.com/Oweik/pcb-art-easyeda.git "$env:USERPROFILE/.codex/skills/pcb-art-easyeda"
python -m pip install -r "$env:USERPROFILE/.codex/skills/pcb-art-easyeda/requirements-validation.txt"
```

Linux/macOS 的技能位置通常为 `~/.codex/skills/pcb-art-easyeda`。如设置了 `CODEX_HOME`，使用其 `skills` 子目录。下一条 Codex 消息可调用 `$pcb-art-easyeda`。

依赖 Python 3.10+。Pillow 用于分层处理与预览；Gerber 导出验证需要 gerbonara。Node.js 20+ 仅用于本仓库的运行时测试。SDK 桥接服务使用自己的 Node.js 环境。

## 连接嘉立创EDA

需要另行安装可用的 `easyeda-api` 技能及其桥接服务，并在嘉立创EDA专业版加载 [API 网关扩展](https://jlc-ext.com/item/oshwhub/run-api-gateway)。本仓库不捆绑第三方桥接服务或 SDK。

桥接服务监听 `127.0.0.1:49620–49629`。脚本验证 `easyeda-bridge` 服务标识，单窗口自动使用，多窗口需 `--window` 明确指定。导入前打开一张专用空白 PCB。

## 快速试用

以下命令在仓库根目录执行。生成文件保存在工作目录，勿将自己的图片、工程和日志提交到此仓库。

```powershell
python scripts/pcb_art.py demo outputs/demo
python scripts/pcb_art.py preview outputs/demo/manifest.json outputs/preview-v1
python scripts/pcb_art.py status
python scripts/pcb_art.py import-images outputs/demo/manifest.json --receipt outputs/import-v1.json
python scripts/pcb_art.py export-native outputs/board-v1.epro2
python scripts/pcb_art.py export-gerber outputs/demo/manifest.json outputs/gerber-v1
```

`demo` 使用程序绘制的简单非角色图案，不包含用户素材。`preview`、`demo`、`build` 与 `export-gerber` 只操作本地文件；`import-images` 会修改当前专用空白 PCB；`export-native` 只读取当前 PCB 并保存到指定本地文件。不主动调用云端保存或下单。

通过 Codex 使用：

> `$pcb-art-easyeda 按这两张参考图制作双面板画，紫色阻焊、少量沉金，约 50 × 70 mm。先看构图和材质分层，再导入专用空白 PCB。`

## 输入格式

六张 PNG 使用相同、不透明的纯黑白画布，黑色为选中几何。`mask_open` 代表去掉阻焊的区域；开窗下必须有铜。正反面输入均为正常观看方向，工具负责制造坐标转换。可省略空层。

```json
{
  "width_mm": 70,
  "height_mm": 50,
  "polarity": "black-selected",
  "back_view": "normal",
  "layers": {
    "front_copper": "front_copper.png",
    "front_mask_open": "front_mask_open.png",
    "front_silk": "front_silk.png",
    "back_copper": "back_copper.png",
    "back_mask_open": "back_mask_open.png",
    "back_silk": "back_silk.png"
  }
}
```

路径相对于 manifest。不要对每层按非空包围框分别裁切。更多坐标、后端与故障恢复说明见 [接入参考](references/integration.md)。

兼容的小图 Fill 后端：

```powershell
python scripts/pcb_art.py build outputs/demo/manifest.json outputs/demo/plan.json
python scripts/pcb_art.py import outputs/demo/plan.json --receipt outputs/fill-import-v1.json
```

Fill 后端限制 2000 个矩形；复杂画面使用 `import-images`。请用 `build` 生成 plan，手工修改 plan 会绕过像素级源层检查。

## 已验证与未验证

客户端实测基线：嘉立创EDA专业版 **4.1.71**。双面六层、约 5.9 万个源矩形合并为六个 Image 图元，回读恢复制造网格后六层差异为零；原生 `.epro2` 导出成功。此实测使用的私人素材与成品不在仓库中。

Image 后端依赖该客户端的底层图像自动反射与归一化 SVG 行为。遇到不认识的格式或几何差异会停止，其他客户端版本需要重新验证。

Gerber 草稿由本地源图层确定性生成，使用独立解析器核对六层与板框。**通过文件一致性检查，不等于通过厂家 CAM 或实物打样。** 不自动检查全路径最小线宽、负形缝隙、阻焊桥、对位裕量；网格分辨率不等于加工能力。覆铜与无铜的紫色深浅仅为示意，低色差图用于暴露细节合并风险。

当前支持矩形板框，无钻孔。不支持自动语义分层、异形板框或 NPTH 挂孔。颜色、厚度和 ENIG/OSP 表面处理属于制造订单设置。

导入失败时先检查 receipt 和编辑器现场。Image 后端保留已经创建的图元，不自动重试；Fill 后端仅尝试回滚当前批。超时可能发生在实际写入后、拿到图元 ID 前，不能直接重跑。

## 验证

```powershell
python -m pip install -r requirements-validation.txt
python -m unittest discover -s scripts -p "test_*.py" -v
node scripts/test_runtime.mjs
```

测试覆盖源像素精确保留、输入极性、画布、铜覆盖、镜像、归一化回读、超时记录、Gerber 独立回读、ZIP 内容以及 Fill 回滚和空白工程保护。CI 使用 Python 3.10 / 3.12 / 3.13 与 Node.js 20；CI 不连接真实 EDA。

v0.2.0 发布前，通用命令还在专用空白 PCB 上完成了合成图案实机检查：六层 Image 导入与回读、原生 `.epro2` 导出、四张材料预览及 Gerber 独立回读均通过。检查结束恢复了原文档焦点。

## 来源与许可

设计、精修与制造参考源自 [soranatsu/PCB_ART](https://github.com/soranatsu/PCB_ART)，保留原作者 MIT 许可与署名，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。嘉立创EDA接入代码是本仓库新增实现。本仓库不包含原项目案例角色图片、私人路径或用户原画；素材权利不随代码许可转移。
