# 本地桥接与 PNG 输入

## 连接

通过已安装的 `easyeda-api` 技能启动本地桥接服务，嘉立创EDA专业版加载 API 网关扩展。连接入口为本机 49620–49629 端口，脚本验证 `/health` 的服务标识为 `easyeda-bridge`，然后枚举窗口。单个窗口自动使用，多窗口通过 `--window` 指定。`status` 是只读检查，不新建工程或清空图元。

## Manifest

PNG 文件名相对于 manifest 所在目录。可以省略空层。统一画布、不透明、只有纯黑与纯白；不要对每张图按非空边界单独裁切。黑色代表几何，白色为空。

```json
{
  "width_mm": 30,
  "height_mm": 40,
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

复杂画面使用 `import-images manifest.json --receipt receipt-v1.json`，直接验证源分层并按层写入 Image 图元。兼容的小图流程可以用 `build` 生成 plan，然后 `import`，但 Fill 后端限制 2000 个矩形。不要手工修改 plan 绕过像素级铜覆盖和丝印交叠检查。输出的 `pixel_mm` 记录网格量化尺度；实际边界由该分辨率决定。

## 实现约定

- 各层连续像素段合并为不重叠矩形，精确保留选中像素，不隐式去噪或阈值化。Image 后端把一层矩形合并到一个复合图像图元，Fill 后端逐矩形写入。高分辨率仍可能生成大量内部轮廓，不能保证任意大图性能。
- 原图坐标从左上向右、向下；EDA 数据单位为 mil，y 取负。Fill 与本地 Gerber 背面按板宽变换 `x'=width-x-w`。Image 后端保留源图正常观看方向，使用负的局部 y 及右侧锚点 `x=boardWidth-sourceLeft`，由客户端的底层图像自动反射实现一次镜像。若提前镜像会变成两次。
- API 执行环境未导出枚举时，使用经本地 API 文档核对的具名兼容映射：铜 1/2、丝印 3/4、阻焊 5/6、板框 11。这里不是锡膏层。
- 轮廓显式重复起点；矩形板框用闭合 Polyline。2026-10-16 实测基线为嘉立创EDA专业版 4.1.71，未显式闭合的填充或使用 Line 创建板框会失败。
- Image 后端先检查空白状态并创建板框，再逐层写入、持久化返回的 ID、独立请求回读。检查图层、位置、尺寸、旋转与镜像；原始源数组一致时比较几何及位置，否则解析归一化 SVG 恢复到输入网格。该客户端的 SVG 使用 10 mil 坐标跨度；对未知格式或几何差异停止。
- Image 后端失败后保留现场和 receipt，`pending` 表示尚未完成的步骤。超时不意味着未写入；不能自动清空或重试。Fill 后端每批最多 12 个填充，仅尝试回滚当前批，并保留先前成功批。两种恢复方式不可混淆。
- 不调用云端保存。测试板仍在当前编辑器现场，后续保存按用户要求处理。

## 验证与样例

技能包附带 Python 转换测试与 Node.js 运行时测试。可在任意工作目录执行，测试不连接 EDA：

```powershell
python -m unittest discover -s "<skill-dir>/scripts" -p "test_*.py" -v
node "<skill-dir>/scripts/test_runtime.mjs"
python "<skill-dir>/scripts/pcb_art.py" demo "<work-dir>/demo"
```

`demo` 仅生成六张 PNG、manifest 与 plan，不写入 EDA。只有显式 `import` 才会修改专用空白 PCB。

初次接入实测：30 × 40 mm、双面六层、14 个填充加闭合板框，原生图层及几何回读通过，并捕获实际 EDA 画面。该结果不能代替新作品的视觉检查或制造文件验证。

后续 Image 后端实测：70 × 50 mm、六层约 5.9 万个矩形，合并为六个 Image 图元；六层原生几何回读恢复网格后零差异。原生文件成功导出。这些历史检查不自动代表当前版本或新作品已通过。

## 导出与预览

- `preview manifest.json preview-v1`：从同一铜、开窗与丝印的布尔关系生成正常观看的两面示意图及低色差版本，输出目录中同名图已存在时停止。不会生成新的画面元素。
- `export-native board-v1.epro2`：读取当前 PCB 并导出本地原生文件，核查 ZIP 结构；不主动保存云端工程。导出体积超过 50 MB 时建议手工导出，避免桥接传输过大。
- `export-gerber manifest.json gerber-v1`：创建新目录，按源像素生成六层与闭合矩形板框，使用独立 gerbonara 解析器回读源网格和板框连续性，再核对 ZIP 内容。空层仍输出合法的空 Gerber。不生成钻孔，因为本工具尚未实现孔。

Gerber 草稿来自本地确定性导出器，不是 EDA 原生 Gerber 导出。默认不自动调用客户端 Gerber 导出，避免长时间操作的超时状态不明。独立解析验证依赖 `requirements-validation.txt`，不以自写解析器冒充独立验证。最小线宽、负形缝隙、阻焊桥及厂家 CAM 仍待验证。
