# 问渠CAM 验证手册

验证手册逐题列出数控编程标准题的参考值和本软件的计算值，做法见 ADR-0104 第 6 节（沿用 ADR-0096 第 4 步的有限元验证手册机制）。

- 题目清单：`assist/cam_verification_cases.json`。每题对应 `tests/test_cam_benchmarks.py` 里的一个标准题测试。C1 共 17 题，分 5 类：
  加工时间与切削功率；机床运动学；碰撞判断、材料去除与几何；必须报出的错误；后处理。
- 数字的来路：标准题测试除了断言，还用 `tests/verification.record` 记下计算值、参考值和容差（设了 `FAP_VERIFICATION_OUT` 才记）。
  手册里的数字都是这样记下来的，不另算、不手填。
- 生成：`python -m assist.cam_verification --out <目录>`。命令会跑全部标准题（约 20 秒），生成中英两版 Word 和 PDF，外加 `verification.json`。
- 漏题检查：测试 `tests/test_cam_verification.py` 核对清单与 `tests/test_cam_*.py` 里记了对照数的测试一一对应。
- 还没有的：合作厂实机空走与首件试切的检测记录（C1 合作厂验收后加）；NAS 979、ISO 10791-7 S 形试件（C3）。

## 当前版本

第 1 版（2026-11-19）：用提交 `bacc73e` 加本次改动生成，NumPy 2.5.3。17 题全部通过，24 项对照全部在容差内。
文件：`问渠CAM验证手册.pdf`、`WenQuest-CAM-Verification-Manual.pdf`、`verification.json`。
