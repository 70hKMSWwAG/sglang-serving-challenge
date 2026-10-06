# HW2：前缀缓存测量与请求流程分析（第二次挑战）

三个独立完成的环境版本并存，结论一致。**最终交付以 [`env-wsl/`](env-wsl/) 为准**
（真机 WSL2，run-1/run-2 换序复测，目录层级与任务书规定一致）。

| 目录 | 环境 | 定位 |
|---|---|---|
| [`env-wsl/`](env-wsl/) | ① 真机 WSL2（12 vCPU / 15 GiB），SGLang 源码构建 + AVX2 补丁 | **最终交付**：report.pdf 8 页、run-1/run-2 逐请求结果、src 全套脚本 |
| [`env-sandbox/`](env-sandbox/) | ② 云沙箱（4 核 / 8 GB 无 GPU），pip 安装 CPU 引擎 | 复跑存档（3 轮重复） |
| [`env-cloud/`](env-cloud/) | ③ 云主机（2 vCPU / 7.4 GB 无 GPU），pip + vllm ops | 存档（1 轮） |

三版实验输入长度不同（① 2112 tok / ② 1024 tok / ③ 512 tok），绝对数值不可互比；
组内对照结论一致：共享前缀组命中率大幅更高、实际 Prefill token 大幅更少、
TTFT 显著下降、TPOT 基本不变。

> `env-wsl/results/target1/*/run-N/` 中除任务书要求的逐请求结果外，
> 还补录了当时实测产生的 `server_log_slice.log` 与 `version_info.log`
> （此前散落在本地未入库，2026-10 整理仓库时归位）。
