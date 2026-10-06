# envs：环境级辅助资产

不属于单个作业、但支撑某个完成环境的公共资产：

| 目录 | 内容 |
|---|---|
| [`wsl/`](wsl/) | 环境①（真机 WSL2）一键复现脚本：`01_setup_env.sh` → `02_start_server.sh` → `04_benchmark.py` → `05_patch_cpu_isa.sh` 等，见其内 README |
| [`evidence/`](evidence/) | 环境①运行证据：日志、GPU 探测、截图，见 `evidence/README.md` |
| [`report/`](report/) | 环境①报告的 HTML 源码（6 份交付 PDF 的生成源） |
| [`tools/wsl/`](tools/wsl/) | 环境①辅助脚本（截图合成、操作手册 PDF 生成、批量抓取） |
| [`tools/sandbox/`](tools/sandbox/) | 环境②（云沙箱）流程图生成与 HW2 打包脚本 |
| [`reference/`](reference/) | 任务书原文截图（HW2 第 1–2 页） |
| [`sandbox-index.md`](sandbox-index.md) | 环境②存档的入口说明（原 sandbox-run/README.md） |

各作业目录内的 `env-sandbox/`、`env-wsl/`、`env-cloud/` 子目录是该环境下
该作业的完整产物；本目录只放跨作业共享或环境级的部分。
