# 环境要求

本文档说明运行本项目所需的系统、Python 环境、依赖安装方式和常见排错方法。

## 推荐环境

| 项目 | 推荐值 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 | 当前启动脚本是 PowerShell 脚本 |
| Shell | PowerShell 5.1 或更高 | 需要能运行 `.ps1` 文件 |
| Python | 3.10 | 当前已验证环境为 Python 3.10.20 |
| 环境管理 | Conda / Miniconda / Anaconda | `run_mineru_batch.ps1` 默认调用 conda 环境 `data_pipeline` |
| MinerU | 3.1.0 | 当前已验证版本 |
| pypdf | 6.10.2 | 用于读取页数和拆分 PDF |
| 编码 | UTF-8 | 项目包含中文路径和中文文件名 |

## 硬件与磁盘

- CPU 可以运行，但 OCR 和大 PDF 解析会比较慢。
- 如果 MinerU 后端使用 GPU，建议提前确认 CUDA、显卡驱动和 MinerU 相关模型可用。
- 输出目录会包含 Markdown、图片资源、日志和临时切块。建议预留至少为原始 PDF 总大小 2 倍以上的可用磁盘空间。
- 处理超大 PDF 或扫描版 PDF 时，可以减小 `-ChunkPages` 来降低单次解析压力。

## 创建环境

推荐创建名为 `data_pipeline` 的 conda 环境，因为 `run_mineru_batch.ps1` 默认使用这个环境名。

```powershell
conda create -n data_pipeline python=3.10 -y
conda activate data_pipeline
python -m pip install -U pip
python -m pip install -r requirements.txt
```

如果没有使用 `requirements.txt`，也可以手动安装：

```powershell
python -m pip install mineru==3.1.0 pypdf==6.10.2
```

## 验证安装

在已激活的 `data_pipeline` 环境中执行：

```powershell
python -V
python -m pip show mineru pypdf
mineru --help
```

建议再做一次 dry run，确认脚本能读取输入目录：

```powershell
python .\batch_mineru_pdf_to_md.py --input-root ".\test data" --output-root ".\mineru_markdown" --dry-run
```

或者使用 PowerShell 包装脚本：

```powershell
.\run_mineru_batch.ps1 -DryRun
```

## 环境名不是 data_pipeline 时

有两种处理方式。

方式一：直接激活自己的环境后运行 Python 主脚本：

```powershell
conda activate your_env_name
python .\batch_mineru_pdf_to_md.py --input-root ".\test data" --output-root ".\mineru_markdown"
```

方式二：修改 `run_mineru_batch.ps1` 中的环境名，把下面这段里的 `data_pipeline` 改成你的环境名：

```powershell
"run", "--no-capture-output", "-n", "data_pipeline",
```

## UTF-8 设置

`run_mineru_batch.ps1` 已经设置了以下环境变量，通常不需要手动处理：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

如果直接运行 Python 脚本且遇到中文路径乱码，可以在当前 PowerShell 窗口手动设置同样的变量。

## 首次运行注意事项

- MinerU 首次运行时可能需要下载或初始化模型文件，请确保机器有网络，或提前准备好 MinerU 所需的本地模型缓存。
- 大批量处理前，建议先用 `-Limit 1` 测试一份 PDF。
- 如果处理过程中中断，重新运行同一命令即可利用 `mineru_markdown/state/` 继续处理。

## 常见排错

### `mineru` 不是内部或外部命令

说明 MinerU 没有安装到当前环境，或当前环境没有激活。请执行：

```powershell
conda activate data_pipeline
python -m pip show mineru
mineru --help
```

### PowerShell 禁止运行脚本

临时允许当前窗口运行脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### `conda run` 在某些受限环境中报权限错误

可以绕过 `run_mineru_batch.ps1`，手动激活环境后直接运行 Python：

```powershell
conda activate data_pipeline
python .\batch_mineru_pdf_to_md.py --input-root ".\test data" --output-root ".\mineru_markdown"
```

### 中文文件名或路径异常

确认终端和 Python 都使用 UTF-8，并尽量在 PowerShell 中运行。项目脚本会设置 UTF-8 编码，并以 `utf-8` 读取和写入文本文件。

### 转换失败但没有继续处理

查看最新日志：

```powershell
Get-ChildItem .\mineru_markdown\logs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

如果某个 PDF 的状态损坏，可以对该 PDF 使用 `-Force` 重新生成，或清理对应的 `state` 文件后重跑。