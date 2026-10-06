# target3 main table (from official summary.json)

| group/run         | success   | throughput (req/s) | cache hit rate | actual prefill tokens | TTFT p50 (s) | TTFT p95 (s) | e2e p95 (s) | backend distribution        |
| ----------------- | --------- | ------------------ | -------------- | --------------------- | ------------ | ------------ | ----------- | --------------------------- |
| A_default/run-1   | 2048/2048 | 5.67               | 0.5380         | 1493888               | 161.5633     | 312.2909     | 315.8830    | 0:512, 1:528, 2:516, 3:492  |
| candidate-1/run-1 | 2048/2048 | 13.04              | 0.5674         | 1398592               | 57.8935      | 113.8253     | 116.9931    | 0:622, 1:627, 2:557, 3:242  |
| candidate-2/run-1 | 2048/2048 | 17.13              | 0.5770         | 1367552               | 33.3153      | 69.8021      | 73.7792     | 0:853, 1:580, 2:414, 3:201  |
| C_affinity/run-1  | 2048/2048 | 4.51               | 0.7337         | 860928                | 50.6881      | 386.7720     | 390.7359    | 0:330, 1:249, 2:284, 3:1185 |
| D_improved/run-1  | 2048/2048 | 15.70              | 0.6084         | 1266304               | 31.0993      | 74.3844      | 78.4011     | 0:854, 1:580, 2:422, 3:192  |

# per-group details

## A_default/run-1
- router: p2c, max_ongoing_requests: 5
- warmup: 64/64
- validation_errors: []
- tpot_s p50/p95: 0.0256 / 0.0271
- dispatch_lag_s p95: 0.0032 | client_queue_s p95: 0.0006
- replica_distribution: 3ebjjekd:492, 9nc5tfc9:528, bhg1k6c5:516, m5jbunrh:512
- node_distribution: 8c10fbd2e49adbb2eb43224a63533e4cd437b2ee720fa422f6e36393:512, 8f8afbeb6b902d4765222d3fa659a26c7d2405e3ed9d5c6a9a525b82:528, daa66e0325d90764b3ed70ad9464bc7deb7d9e9ac25aa225a7a6e729:516, ed8afc05096a925b64c6a3f053c56ed723bb129db5eddacc8392b6d5:492
- phase steady: n=512 ok=512 hit_rate=0.5013 ttft_p95=87.3692 lat_p95=90.7410
- phase burst: n=1024 ok=1024 hit_rate=0.5596 ttft_p95=245.4229 lat_p95=249.2052
- phase recovery: n=512 ok=512 hit_rate=0.5316 ttft_p95=323.2975 lat_p95=327.1358

## candidate-1/run-1
- router: p2c, max_ongoing_requests: 16
- warmup: 64/64
- validation_errors: []
- tpot_s p50/p95: 0.0280 / 0.0302
- dispatch_lag_s p95: 0.0038 | client_queue_s p95: 0.0007
- replica_distribution: 1mf9nczr:627, 9fvcs3mx:242, belf1ree:622, omusfn35:557
- node_distribution: 20fa35dfd24b6f4e2010923362169a5c7d6e7e11c80a89c3c3b85eb1:622, 30576b02804754bab31f399e99272ec40ababf7129ae36f2296af059:627, 9aa912f579892081c8ebd49645d1cee3fd0cd2f409e7d052ca7c5930:557, dcfe6cc1b10c08b9aa7249979f901d1dadb7fcf37466ddb28bb64ae9:242
- phase steady: n=512 ok=512 hit_rate=0.5321 ttft_p95=29.3011 lat_p95=31.7826
- phase burst: n=1024 ok=1024 hit_rate=0.5919 ttft_p95=91.2611 lat_p95=94.7343
- phase recovery: n=512 ok=512 hit_rate=0.5539 ttft_p95=117.2124 lat_p95=121.3319

## candidate-2/run-1
- router: p2c, max_ongoing_requests: 64
- warmup: 64/64
- validation_errors: []
- tpot_s p50/p95: 0.0311 / 0.0355
- dispatch_lag_s p95: 0.0048 | client_queue_s p95: 0.0006
- replica_distribution: 4l5x7hnv:201, 7jkqqdo3:414, qfrg7wvp:853, wmemetep:580
- node_distribution: 022737d9f2126ff33f6d1f1d103eb289e80e9ad845e8fe6d33fd9439:853, 18eeee6de596a492da7b0e6b3154fa1ebb39c9b0953290028f80c31e:580, 4a209101b27c3e5ff8dd430c0394b188af68aaaa47e02d8247e35a6d:414, 9cd0187f53dd9293165e0949e626c9debecc637b83144d3c82382f9e:201
- phase steady: n=512 ok=512 hit_rate=0.5681 ttft_p95=30.6872 lat_p95=35.3087
- phase burst: n=1024 ok=1024 hit_rate=0.5777 ttft_p95=62.0633 lat_p95=66.3690
- phase recovery: n=512 ok=512 hit_rate=0.5848 ttft_p95=79.8277 lat_p95=82.2319

## C_affinity/run-1
- router: consistent_hash, max_ongoing_requests: 64
- warmup: 64/64
- validation_errors: []
- tpot_s p50/p95: 0.0258 / 0.0376
- dispatch_lag_s p95: 0.0056 | client_queue_s p95: 0.0006
- replica_distribution: 4nmcsorz:330, 760xjre5:284, c4n8uaju:249, z1k54v9j:1185
- node_distribution: 5149550f20fdfd86198f20163387de7d90c5960b552fa48e307d8af6:330, 8d6d1a8921b0aaa32e2015e5ad193d365c6d6efa939f8cfed824b261:249, a613048e241169f3e71ea95a8116af843c87dbf98b5ecb7929efbc60:284, e1bf30b102de954817653ad3a447a7ccd67a97f2a8555cbbe71bafa5:1185
- phase steady: n=512 ok=512 hit_rate=0.7262 ttft_p95=207.5138 lat_p95=210.0476
- phase burst: n=1024 ok=1024 hit_rate=0.7515 ttft_p95=375.6020 lat_p95=380.3390
- phase recovery: n=512 ok=512 hit_rate=0.7059 ttft_p95=407.8363 lat_p95=410.3872

## D_improved/run-1
- router: affinity_load_aware, max_ongoing_requests: 64
- warmup: 64/64
- validation_errors: []
- tpot_s p50/p95: 0.0328 / 0.0405
- dispatch_lag_s p95: 0.0087 | client_queue_s p95: 0.0006
- replica_distribution: 7gwqt1xc:192, d3ip7143:422, h7qy78pk:580, ykfd6t4d:854
- node_distribution: 095ed94542dc9bd77ad57c3ae78f5b12c32dede6f47f80dc601afcc1:854, 79d9684c22a7e6881c0362779a7ab84f2b7c79e02d466df0ceb31a4b:580, 912f511e57fbfefd7ae1956a95c8a47c42eabd99ba0a51045fb1740f:422, a8f515aa6a655b17425323266324de2c5c48183e6704efaf8c82721e:192
- phase steady: n=512 ok=512 hit_rate=0.6571 ttft_p95=31.7784 lat_p95=36.3933
- phase burst: n=1024 ok=1024 hit_rate=0.5896 ttft_p95=77.4140 lat_p95=82.1213
- phase recovery: n=512 ok=512 hit_rate=0.5969 ttft_p95=73.7132 lat_p95=77.5814

