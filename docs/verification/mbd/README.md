# 问渠多体动力学验证手册

验证手册逐题列出多体动力学标准题的参考值和本软件的计算值，做法见 ADR-0102 第 3 步（沿用 ADR-0096 第 4 步的有限元验证手册机制）。

- 题目清单：`assist/mbd_verification_cases.json`。每题对应一个标准题测试，共 44 题，分 6 类：刚体机构；力元、摩擦、接触与间隙；
  控制与联合仿真；线性化与模态；柔性体与大变形梁；隐式积分与参数研究。
- 数字的来路：标准题测试除了断言，还用 `tests/verification.record` 记下计算值、参考值和容差（设了 `FAP_VERIFICATION_OUT` 才记）。
  手册里的数字都是这样记下来的，不另算、不手填。
- 生成：`python -m assist.mbd_verification --out <目录>`。命令会跑全部标准题（约 4 分钟），生成中英两版 Word 和 PDF，外加 `verification.json`。
  有题没通过或没运行时，手册照样生成，但结论里会写明，命令以非 0 退出。
- 不在自动测试里的题：旋转梁升速（Kane 1987）单次几分钟，由 `scripts/mbd_spinup_check.py` 验证，结果写在手册“说明”里（出自 ADR-0101 补充二）。
- 发版：每次发版都从干净的提交重新生成。手册页眉和“运行环境”表写明代码版本（git 提交号）、数值库版本、柔性体缩减用的 CalculiX 与 Gmsh 版本。
- 漏题检查：测试 `tests/test_mbd_verification.py` 核对清单与 `tests/test_mbd_*.py` 一一对应。新写的标准题只要记了对照数却没进清单，测试就不通过。

## 当前版本

第 1 版（2026-11-18）：用提交 `5ab4491` 生成，NumPy 2.5.3、SciPy 1.17.1、CalculiX 2.21、Gmsh 4.15.2。44 题全部通过，74 项对照全部在容差内。文件：`问渠多体动力学验证手册.pdf`、`WenQuest-MBD-Verification-Manual.pdf`、`verification.json`。
