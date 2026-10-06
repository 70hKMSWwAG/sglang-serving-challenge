# HW3：Ray Serve 路由对比与改进（第三次挑战）

四副本 SGLang + Ray Serve 路由对照实验（A / B1 / B2 / C / D）。两个版本在
不同硬件上各自独立完成，互不覆盖：

| 目录 | 环境 | 内容 |
|---|---|---|
| [`ray-serve-4gpu/`](ray-serve-4gpu/) | 4 × RTX 4090D（AutoDL 北京 B2 区） | **交付版**（符合任务书「每人四张 GPU」）：`ray_cluster.py` 显式建簇、`course_workload/` 官方负载校验、report.pdf、作业感受与 AI 使用说明 PDF、README 内含目标三主表 |
| [`ray-serve-1gpu/`](ray-serve-1gpu/) | 1 × RTX 4090D（SeetaCloud 容器） | 交叉验证版（原独立仓库 HW3-0102603133，subtree 合并且保留全部提交历史）：全套部署/运行脚本（`setup_env.sh` → `download_model.sh` → `launch_sglang.sh` → `run_round.sh` → `run_all_rounds.sh`）、逐轮结果（run-1 层级）、`router_fallbacks.jsonl` 逐请求路由日志、6 页含主表的 report.pdf |

仓库根目录的 `HW3-0102603133.zip` 由 `ray-serve-4gpu/` 打包而来（解压后仅含同名根目录），
重新打包：`python scripts/build_deliverable_zips.py`。

tools/ 说明（仅 1gpu 版）：

- `tools/report/`：`build_report.py` 直接从 `summary.json` / `requests.csv`
  读取数据生成 `report.html`（报告数字与原始结果不会漂移），含模板与 AI 披露页源码；
- `tools/remote-relay/`：实验期间使用的远程联调脚本（GitHub 仓库命令下行 + ntfy 上行），
  与实验结论无关，留作过程记录。
