# 例子 3 · 细长推杆屈曲（专业版，模型文件） / Example 3 · Slender pushrod buckling (Pro, model files)

钢杆 φ20 × 1000 mm（E = 206 GPa），两端铰支：根部转动副，端部转动副连一个沿杆轴滑动的滑块，滑块上加轴向力。杆按大变形梁算（20 个单元）。
Steel rod φ20 × 1000 mm (E = 206 GPa), pinned at both ends: a revolute joint at the root, and at the tip a revolute joint to a slider moving along the rod axis, loaded axially. The rod is a large-deformation beam (20 elements).

## 步骤 / Steps

1. “打开模型文件…”，选 `pushrod-push60.json`（压力 = 0.6 倍欧拉载荷）。分析已经是“先静平衡再线性化”。点“计算”，模态表里第一阶是一阶弯曲频率。
   "Open model file…", pick `pushrod-push60.json` (compression 0.6 × Euler load). The analysis is already "static then linearization". Compute; mode 1 in the table is the first bending frequency.
2. 再打开 `pull40`（拉力 0.4 倍）、`push00`、`push20`、`push40` 各算一次。
   Repeat with `pull40` (tension 0.4 ×), `push00`, `push20`, `push40`.
3. 把一阶频率的平方对轴力画成直线，直线与零频率的交点就是屈曲载荷。
   Plot the square of the first frequency against the axial force; where the line reaches zero frequency is the buckling load.

## 结果 / Results（`results.json`）

| 轴力 Axial force（N，正为压 / + is compression） | 一阶弯曲频率 1st bending frequency（Hz） |
| ---: | ---: |
| −6,387（拉 / tension） | 47.60 |
| 0 | 40.25 |
| 3,194 | 36.02 |
| 6,387 | 31.22 |
| 9,581 | 25.53 |

- 外推的屈曲载荷 16,028 N；欧拉公式 π²EI/L² = 15,968 N，相差 0.38 %。Extrapolated buckling load 16,028 N; Euler's formula 15,968 N; 0.38 % apart.
- 零轴力的频率 40.25 Hz；公式 π/(2L²)·√(EI/ρA) = 40.23 Hz。Frequency at zero load 40.25 Hz; formula 40.23 Hz.

线性模态柔性体的频率不随轴力变，算不出屈曲；要看受压细长件，用大变形梁。报告样张是压力 0.6 倍那一个。
A linear modal flexible body's frequencies do not change with axial force, so it cannot predict buckling; use large-deformation beams for slender parts in compression. The sample report is the 0.6 × case.
