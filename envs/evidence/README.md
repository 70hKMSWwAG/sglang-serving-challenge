# evidence - WSL 版运行证据（环境 ①）

本目录为 `wsl/` 一键脚本在 WSL2 真机（12 vCPU / 15 GiB）上的真实运行产物，供批改时核验。

## 文件说明

| 文件 | 作用 |
|---|---|
| `00_env_report.log` | 环境自检（torch / sgl_kernel / sglang 导入检查） |
| `01_setup.log` | `wsl/01_setup_env.sh` 编译与安装日志 |
| `02_start.log` | `wsl/02_start_server.sh` Ray + SGLang 启动日志 |
| `04_benchmark.log` | `wsl/04_benchmark.py` Mooncake workload 压测日志 |
| `05_patch.log` | `wsl/05_patch_cpu_isa.sh` AVX-512 补丁日志 |
| `10_gpu_probe.txt` / `11_gpu_probe_sudo.txt` | GPU 探测结果（确认无可用 GPU，走 CPU 后端） |
| `sglang_server.log` | SGLang 服务端完整日志（含 RadixCache 初始化、Prefill #cached-token 证据） |
| `benchmark_results.json` / `.csv` | 压测逐请求汇总（TTFT / latency / tokens） |
| `shot1.png` / `shot1.txt` / `shot1_raw.txt` | 截图1：`GET /v1/models` + 单次推理（`tools/make_shot.py` 渲染） |
| `shot2a.png` / `shot2a.txt` | 截图2a：Poisson 到达压测逐请求记录 |
| `shot2b.png` / `shot2b.txt` | 截图2b：压测汇总统计 |
| `shot3.png` / `shot3.txt` | 附录：服务端 `#cached-token > 0` 前缀复用证据 |

截图 PNG 由 `tools/make_shot.py` 从对应的 `.txt` 终端文本渲染；HTML 版见 `report/src/操作保存.html`。
