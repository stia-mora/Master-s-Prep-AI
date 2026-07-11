# PDF 批量清洗与 Markdown 转换

这个项目用于把指定目录下的 PDF 批量转换为 Markdown。脚本会先把大 PDF 按页数切成小块，再调用 MinerU 解析，每个 PDF 的处理状态会记录到 JSON 文件里，因此中途失败或中断后可以继续跑。

当前默认流程面向 Windows + Conda 环境，适合处理中文教材、讲义、题册等 PDF，并保留 MinerU 生成的图片资源引用。

## 项目结构

```text
.
├── batch_mineru_pdf_to_md.py   # 主脚本：扫描 PDF、切块、调用 MinerU、合并 Markdown
├── run_mineru_batch.ps1        # Windows PowerShell 启动脚本，默认使用 conda 环境 data_pipeline
├── requirements.txt            # 最小 Python 依赖说明
├── ENVIRONMENT.md              # 环境安装、版本要求和排错说明
├── test data/                  # 默认 PDF 输入目录，可以按子文件夹分类
└── mineru_markdown/            # 默认输出目录
    ├── markdown/               # 最终 Markdown 文件
    ├── assets/                 # Markdown 引用的图片和资源
    ├── state/                  # 断点续跑状态 JSON
    ├── logs/                   # 每次运行日志
    └── work/                   # 临时切块和 MinerU 中间产物，正常完成后会清理
```

## 快速开始

先按 [ENVIRONMENT.md](./ENVIRONMENT.md) 配好环境，然后在项目根目录执行：

```powershell
# 查看将要处理哪些 PDF、如何切块，不真正转换
.\run_mineru_batch.ps1 -DryRun

# 先处理 1 个 PDF 做冒烟测试
.\run_mineru_batch.ps1 -Limit 1

# 处理默认输入目录下的全部 PDF
.\run_mineru_batch.ps1
```

默认输入目录是 `test data/`，默认输出目录是 `mineru_markdown/`。

## 常用命令

处理自定义目录：

```powershell
.\run_mineru_batch.ps1 -InputRoot "D:\pdfs" -OutputRoot "D:\mineru_output"
```

调整每个切块的页数：

```powershell
.\run_mineru_batch.ps1 -ChunkPages 10
```

强制重新生成已经存在的 Markdown：

```powershell
.\run_mineru_batch.ps1 -Force
```

指定解析方式：

```powershell
.\run_mineru_batch.ps1 -Method ocr -Lang ch
```

如果不想使用 PowerShell 包装脚本，也可以在已激活的 Python 环境中直接运行：

```powershell
python .\batch_mineru_pdf_to_md.py --input-root ".\test data" --output-root ".\mineru_markdown" --chunk-pages 20
```

## 参数说明

| PowerShell 参数 | Python 参数 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `-InputRoot` | `--input-root` | `.\test data` | 要扫描的 PDF 根目录，支持子目录 |
| `-OutputRoot` | `--output-root` | `.\mineru_markdown` | 输出根目录 |
| `-ChunkPages` | `--chunk-pages` | `20` | 每个 PDF 切块包含的页数 |
| `-Backend` | `--backend` | `hybrid-auto-engine` | MinerU 后端 |
| `-Method` | `--method` | `auto` | MinerU 解析方式，可选 `auto`、`txt`、`ocr` |
| `-Lang` | `--lang` | `ch` | OCR 语言 |
| `-Force` | `--force` | 关闭 | 重新生成已存在的结果 |
| `-DryRun` | `--dry-run` | 关闭 | 只打印计划，不写输出 |
| `-Limit` | `--limit` | `0` | 限制处理 PDF 数量，`0` 表示不限制 |
| 无 | `--mineru-bin` | 自动查找 | 指定 MinerU 可执行文件路径 |

## 输出说明

最终 Markdown 会写入：

```text
mineru_markdown/markdown/<输入目录中的相对路径>/<PDF 文件名>.md
```

图片和其他资源会写入：

```text
mineru_markdown/assets/<输入目录中的相对路径>/<PDF 文件名>/chunk_0000/...
```

Markdown 中的资源链接已经被改写为相对路径。交付结果时，如果要让图片正常显示，请保留 `mineru_markdown/markdown/` 和 `mineru_markdown/assets/` 的相对位置。

## 断点续跑逻辑

- 如果最终 Markdown 已经存在，默认会跳过该 PDF；如需覆盖旧结果，请使用 `-Force`。
- 如果某个 PDF 转换中途失败，下次运行会读取 `mineru_markdown/state/` 中的状态文件，从未完成的 chunk 继续处理。
- 对于未完成的任务，脚本会根据源 PDF 大小、修改时间、页数和解析参数判断是否复用中间状态；如果这些信息变化，会重新生成该 PDF 的中间状态。
- 使用 `-Force` 会删除该 PDF 的旧结果、中间状态和临时目录后重新处理。

## 运行日志

每次运行都会在 `mineru_markdown/logs/` 下生成一个日志文件，例如：

```text
mineru_markdown/logs/run_20260427_175928.log
```

日志中包含输入输出路径、MinerU 命令、stdout/stderr、失败原因和最终统计。

## 交付给他人时建议包含

建议包含这些文件和目录：

```text
batch_mineru_pdf_to_md.py
run_mineru_batch.ps1
README.md
ENVIRONMENT.md
requirements.txt
test data/              # 如果允许分享原始 PDF
mineru_markdown/markdown/
mineru_markdown/assets/
```

不建议交付这些临时或机器生成目录：

```text
__pycache__/
mineru_markdown/work/
```

如果原始 PDF 或转换结果涉及版权、内部资料或个人信息，请先确认授权范围再分发。

## 常见问题

### 找不到 MinerU

确认已经在目标环境中安装 MinerU，并且能执行：

```powershell
mineru --help
```

如果 MinerU 不在 PATH 中，可以直接运行 Python 脚本并通过 `--mineru-bin` 指定路径。

### PowerShell 不允许执行脚本

可以在当前 PowerShell 窗口临时放开执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

然后重新执行 `run_mineru_batch.ps1`。

### 输出 Markdown 中图片不显示

通常是只复制了 `markdown/`，没有一起复制 `assets/`。请保持 `mineru_markdown/markdown/` 和 `mineru_markdown/assets/` 在同一个输出根目录下。

### 处理很慢或内存压力大

减小 `-ChunkPages`，例如从默认 `20` 调整为 `10` 或 `5`。如果确认 PDF 是扫描版，使用 `-Method ocr` 会更稳定，但通常也更慢。