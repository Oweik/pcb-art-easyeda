---
name: pcb-art-easyeda
description: 制作和精修 PCB 艺术画、双面板画或挂件，将分层黑白 PNG 导入嘉立创EDA专业版，生成铜、阻焊开窗、丝印和矩形板框，导出原生工程与独立回读验证的 Gerber 草稿。不用于普通功能电路设计。
license: MIT
metadata:
  version: "0.2.1"
---

# PCB 艺术画与嘉立创EDA

根据参考图与用户确认的构图确定制造分层，再把已分层的 PNG 写入嘉立创EDA原生 PCB 图元。保留用户指定工艺、角色细节、字体与认可版本。没有指定工艺时，可以提出双层沉金、单色阻焊与白丝印方案。

## 根据任务读取参考

- 制定图层与材料方案时读 [设计与材料](references/design.md)。
- 局部图案精修时读 [精修与视觉验收](references/refinement.md)。
- 文件交付与生产核查时读 [制造核查](references/fabrication.md)，区分其中的目标流程与本适配器已实现能力。
- 准备连接编辑器、制作 manifest 或导入 PNG 时读 [接入方法与输入格式](references/integration.md)。

## 能力与执行方式

脚本为本技能目录内的 `scripts/pcb_art.py`，运行时从相邻的 `runtime.js` 加载 EDA 代码。使用脚本绝对路径，所有生成文件写入当前用户任务的输出目录，不写回技能库。

```powershell
python "<skill-dir>/scripts/pcb_art.py" status
python "<skill-dir>/scripts/pcb_art.py" preview "<work-dir>/manifest.json" "<work-dir>/preview-v1"
python "<skill-dir>/scripts/pcb_art.py" import-images "<work-dir>/manifest.json" --receipt "<work-dir>/import-receipt.json"
python "<skill-dir>/scripts/pcb_art.py" export-native "<work-dir>/board-v1.epro2"
python "<skill-dir>/scripts/pcb_art.py" export-gerber "<work-dir>/manifest.json" "<work-dir>/gerber-v1"
```

完整工作流需要 Python 3.12+；处理图片需要 Pillow。Gerber 草稿导出还需要 gerbonara，其当前验证版本要求 Python 3.12+。使用可用的 `easyeda-api` 技能启动桥接和检查 API；使用时读取该技能的连接流程。本技能不附带桥接服务。网关扩展入口：https://jlc-ext.com/item/oshwhub/run-api-gateway 。仅安装本技能不等于扩展已连接。

导入前查看 `status`。仅对用户为此任务打开的专用空白 PCB 执行导入。多窗口时使用 `--window` 明确指定目标，不切换或覆盖无关工程。脚本固定文档 UUID，验证空白状态，每层创建一个包含多块轮廓的原生 Image 图元，回读图层、位置与制造几何。不要将图片作为彩色 Object 图元导入来替代制造层。

导入失败时检查 receipt。Image 后端保留已创建图元与记录，不自动回滚或重试；超时/断连可能发生在写入成功但未拿到 ID 之后，先核查现场，不要删除已有图元来绕过空白检查。`import` 是兼容的小图 Fill 后端，限制 2000 个矩形，只有当前批会尝试回滚。不要混淆两个后端的恢复方式。

## 制造图层语义

黑白输入中黑色为选中几何，白色为空；六层同画布、不透明、纯二值。`mask_open` 是阻焊开窗：有铜且开窗才会露出所选表面处理。丝印不得覆盖开窗。背面输入必须是正常观看方向，最终制造几何镜像一次；不要预先镜像。Image 后端依赖客户端底层图像自动反射，使用右侧锚点补偿；Fill 与 Gerber 后端则显式镜像。不同后端不能照搬镜像代码。

不要把整张彩色原图直接交给转换器。先根据脸部、头发、服装、文字等语义完成分区，再给用户看图层组合效果。覆铜与无铜阻焊的明暗差仅是材料示意，需要实物确认；EDA 默认图层色也不是成品配色。

## 验证和交付边界

现有适配器支持六层黑白 PNG、矩形板框、原生图元回读、原生 `.epro2` 导出和本地确定性 Gerber 草稿导出。Gerber 使用独立解析器回读六层像素与闭合板框，再核对 ZIP 内容。它不是客户端原生 Gerber 导出结果，也不是厂家 CAM 审核。

尚不支持自动语义分层、异形板框和 NPTH 挂孔；这些需求应另行实现、测试并明确报告状态。对彩色原图，需要先做针对该作品的语义分区与视觉精修，不把历史作品的阈值、角色坐标或尺寸写成通用规则。

输入检查包括同画布、二值极性、开窗下铜覆盖、丝印与开窗不交叠。未检查最小线宽、阻焊桥、铜外扩裕量、板边间距，高分辨率图的矩形数量与性能也未充分验证。不要将原生 API 回读称为独立 DRC、厂家 CAM 或实物验收。

完成时报告实际写入的目标和图层、回读结果、输出绝对路径及尚未完成的验证。原生写入后可用 `easyeda-api` 的截图 API 检查编辑器视觉；截图仅为空网格时，先核查图层可见性与焦点。导入脚本会尝试显示正面图层并缩放到板框。

本技能不会主动保存云端工程、上传、下单或付款；按用户本次授权范围执行这些操作。

## 来源

设计、精修和制造参考来自 [soranatsu/PCB_ART](https://github.com/soranatsu/PCB_ART)，以 MIT 许可保留于本技能，见 `LICENSE`。嘉立创EDA适配脚本为本地接入实现，不依赖原作者的本机目录。
