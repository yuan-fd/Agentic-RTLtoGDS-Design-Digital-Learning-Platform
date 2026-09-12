# 完整 Ibex ORFS baseline 证据

时间：2026-09-12 18:05（Asia/Shanghai）  
入口：服务器固定 `/share/home/yuanwenjie/OpenROAD-flow-scripts/flow`  
设计：`sky130hd/ibex`，顶层 `ibex_core`  

## 执行

```bash
make DESIGN_CONFIG=./designs/sky130hd/ibex/config.mk finish
```

命令实际完成了 ORFS 的综合、floorplan、placement、CTS、global/detailed routing、fill、GDS merge 和 final report。`6_report` 日志显示总耗时 1459 秒，峰值内存 7697 MB；最终 GDS 已生成。

## 产物

| 产物 | SHA-256 |
| --- | --- |
| `results/sky130hd/ibex/base/6_final.gds` | `013c422d8699db6251df4172a0c8425696bd5905ade1d68fc40a7a822a548248` |
| `logs/sky130hd/ibex/base/6_report.log` | `18dcb49f5562d1d6a44b13512e69cd469653a2ed8c936f7ccec860eeb5e312db` |
| `reports/sky130hd/ibex/base/synth_stat.txt` | `475d9516d28ea34d1ae2e0d183b72dbf00a334d6533ac41b8da03f7db02aae07` |

## 观察到的结果

- 综合报告记录顶层 `ibex_core` 面积 `129664.358400`；
- floorplan 阶段曾记录 WNS `-17.28`、TNS `-16039.15`；
- placement 阶段记录 WNS `-0.08`、TNS `-4.66`；
- CTS 阶段记录 WNS `-0.01`、TNS `-0.01`；
- 该证据证明完整 Ibex 的 ORFS baseline 真实跑到 GDS，不代表它已经满足时序签核；负裕量必须在 Dashboard 中明确显示。

## 边界

这是服务器原生 ORFS baseline 证据。它还没有被包装成一次新的平台 Runtime 教学任务，因此不能把它当成平台 API 的 fresh teaching session；下一步需要把同一固定参考设计接入 Runtime，并保留相同产物指针。
