# 《新超级幸运狐》汉化项目

## 游戏信息
- 原名：New Super Lucky's Tale
- 中文名：新超级幸运狐（本项目暂译）
- 开发及发行：Playful Corp.
- 发行平台：Steam，2020 年 8 月 21 日发行。当前本机 Build ID 为 `10670184`。
- 引擎：本机资源头为 Unity 2017.4.36f1，使用 Mono 托管程序和 UnityFS AssetBundle。
- 原语言：英语（界面、语音和字幕）。另有法语、意大利语、德语、两种西班牙语、日语和巴西葡萄牙语界面及字幕。
- 年龄分级：ESRB E，含轻度卡通暴力。[Steam 商店](https://store.steampowered.com/app/1038300/New_Super_Luckys_Tale/?l=schinese)

## 游戏简介
小狐狸 Lucky 通过一本能通往不同世界的魔法书展开冒险，靠跳跃、钻地和甩尾闯过平台关卡，寻找被巫师 Jinx 及其猫族夺走的书页。[Steam 商店](https://store.steampowered.com/app/1038300/New_Super_Luckys_Tale/)

## 汉化目标
- 范围：菜单、界面、教程、剧情对白、字幕及游戏内图片文字。
- 目标语言：简体中文
- 图片文字翻译：启用

## 图片文字流程
- 选择记录：`localization_project.json`；未决定时可先提取常规文本，不能默认启用图片步骤。
- 启用时：常规解包 → `game-image-extract` → `game-translate`（常规/图片数据集独立）→ `game-image-repack` → 引擎回填。

## 技术栈
| 环节 | 工具 | 版本 |
|------|------|------|
| 提取 | UnityPy / dnSpy Console | UnityPy 1.25.4 |
| 翻译 | 共用汉化流程 / API | 正文配置 r3，冻结术语 r2 |
| 回填 | UnityPy / TextMesh Pro 静态字库 / 图片 staged patch | UnityPy 1.25.4 |

## 文本提取
- 主语言表位于 `nslt_Data/resources.assets` 的 I2 LanguageSource 组件，PathID `1841`。定位依据是托管程序集的 `LocalizationManager.GlobalSources` 和组件脚本引用。
- 从 2,341 个键中导出 2,191 条美国英语玩家文本。单列 CSV 按字段保存，mapping 绑定资源路径、对象、数组位置和原文哈希，context 保存章节及资源上下文。
- 保留字体标识、样式定义、独立富文本控制项、二进制编码台词、空行与其他语言原值。提取入口为 `python scripts/i2_table.py extract`，依赖工作区 UnityPy 1.25.4。

## 图片文字提取
- 通过 `scripts/export_textures.py` 从游戏基础资源和 Windows AssetBundle 导出 3,742 张贴图，像素去重后为 3,094 张。导出错误为 0。名称明确表示非色彩图及单边小于 20 像素的贴图分别排除 155、75 张。
- 全量执行 GPU PP-OCRv6 medium。按策略选择 520 张交本地 Qwen3-VL 8B Instruct Q4_K_M，其中 518 张产出模型结论。默认端口占用后用独立回环端口续跑，沿用了已保存的扫描与分流。17 张候选经实际看图确认，导出 19 条不同原文和 27 个位置。另有 468 张尚需视觉裁决，包含模型分歧或仅有候选信号的图片。
- [图片译文](new-super-luckys-tale_images_text_translated.csv)和 [Unity 来源映射](new-super-luckys-tale_images_text.mapping.json)保存在项目根。图片术语、润色和 19 条全文独立审校在 `TranslateFiles/image-text/` 内完成。

## 翻译
- 共用流程 API 路线按工作区配置优先级执行，本轮请求使用 Codex CLI 的 gpt-6-luna。术语独立审校、定向标准档修复、试译、正文、草稿校验、独立润色和全文语义审校均已完成。
- 冻结表包含 95 条角色、75 条术语、0 条禁翻项，见 `TranslateFiles/glossary/r2/freeze_3977527e/built/glossary_reviewed.json`。
- I2 对话样式、替换标记、分页与可见方括号转义按游戏语法保护。正式验证覆盖全部 2,191 条，见 `TranslateFiles/reports/final_validation.json`。

## 回填

- 本机测试版适配 Steam Build 10670184。用 `scripts/i2_table.py` 按资源键回填美国英语槽位，再用 `scripts/tmp_fallback.py` 为旧版 TextMesh Pro 配置中文后备字库。全量读回已验证 2,191 条译文，中文字符覆盖检查通过，实际新增 1,394 个字形。
- 图片经过清字与成图两轮视觉检查。已回填 10 张不同图片和 29 处 Texture2D 实例，包含主标题、六个章节标题、福克辛顿解锁插图、施工牌及爆破拟声。主标题保留原绘狐尾，纸纹插图使用局部清字和纹理修补。保留每个资源的尺寸、Mip 层数和引用对象，读回像素哈希通过。
- 已用 `scripts/install_local.py` 同步 5 个文件到本机 Steam 安装。安装目标和原件备份均已核验，备份在 `Build/original-backup-10670184/`，本地载荷在 `Build/test-payload-v1/`，文件清单见 `ImageText/installed_payload_v1.json`。
- 从 Steam 正常启动，语言选择英语（美国）。已在本机 Steam 版确认中文主标题、菜单、开场字幕、天空城堡关卡提示和 NPC 对话。

## 对外发布

- [v1.0 下载与安装说明](https://github.com/zfyu222/new-super-luckys-tale/releases/tag/v1.0)。补丁为 `新超级幸运狐_子非鱼汉化1.0.zip`，适用 Steam Windows Build `10670184`，沿用游戏原有启动入口。
- ZIP 的 SHA-256 为 `f41b54164cd9bd2a54c7240fb440f3e2c11afa626a166786d9f8e9dad99cc265`。五份 VCDIFF 差分重建两个 Unity 资源文件和三个 AssetBundle，安装后字节与实机测试版本一致。[发布清单](Release/PATCH_MANIFEST.json) [测试载荷](ImageText/installed_payload_v1.json)
- 隔离回放覆盖带中文和空格的路径、首次安装、重复安装、模拟旧版升级、卸载，以及错误版本和损坏补丁的拒绝处理。[回放脚本](scripts/verify_release_delta.py)
- [发布封面](Dispatch/Artwork/title.png)根据 Steam 官方主视觉制作。[素材来源](Dispatch/Artwork/source.json)

## 开发与复核

将本仓库放在 [StaticHanHua](https://github.com/zfyu222/StaticHanHua) 工作区的 `Projects/new-super-luckys-tale/` 下。Windows 工程使用 Python 3.12 和 UnityPy 1.25.4。中文后备字库构建使用工作区的 Noto Sans SC，以及 Pillow、NumPy、fontTools、OpenCV 和 UnityPy 的 TypeTree 生成依赖。

在本仓库根目录执行下列命令。将 `<原版目录>` 替换为资源未改动的 Steam Build 10670184 安装目录。提取会用[提交的资源映射](new-super-luckys-tale_text.mapping.json)核对本机原文，回填会根据[正式校验报告](TranslateFiles/reports/final_validation.json)和[正文译文](new-super-luckys-tale_text_translated.csv)校验全部 2,191 条记录。

```powershell
python scripts/i2_table.py extract --game "<原版目录>"
python scripts/i2_table.py rebuild --game "<原版目录>" --destination Build/text
python scripts/tmp_fallback.py --game "<原版目录>" --translated new-super-luckys-tale_text_translated.csv --resources Build/text/nslt_Data/resources.assets --destination Build/font
```

用[贴图导出脚本](scripts/export_textures.py)导出原画，以工作区 `Tools/image_text/staged_patch.py` 生成经视觉审批的图片载荷，通过[贴图回填脚本](scripts/import_textures.py)将其合入文字与字库回填结果。逐图清字、绘制素材和中间图层保存在本地工程。复核发布版时，可直接使用已发布的 ZIP 和本机原版资源。

```powershell
python scripts/verify_release_delta.py --zip "<下载的 ZIP>" --exe "<原版目录>/nslt.exe" --originals "<原版目录>"
```

[差分构建脚本](scripts/build_release_delta.py)使用[发布配置](Dispatch/release_config.json)、[实机测试载荷清单](ImageText/installed_payload_v1.json)、原版与已验收的回填文件，以及 [Xdelta 3.2.2](https://github.com/jmacd/xdelta/releases/tag/v3.2.2) 官方 Windows ZIP 和许可证。用脚本的 `--help` 查看各输入路径。构建时逐文件解码比对测试载荷，再打包。

## 已知问题

- 部分复合预览牌、书封、街机纹理及未逐图确认的资源仍可能显示英文。试制中存在旧字重影或底图损伤的图未进入本机载荷。
- 当前版本以美国英语槽位显示中文。切换其他语言时，通用贴图中的中文仍可能可见。

## 版本记录
- 2026-11-26 - 初始化汉化项目工作区。
- 2026-11-26 - 安装并验证正文与图片汉化测试版 local-v1。
- 2026-11-26 - 发布简体中文补丁 v1.0。
