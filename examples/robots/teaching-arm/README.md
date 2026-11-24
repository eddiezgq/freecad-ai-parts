# 案例 A：教学用桌面五轴机械臂（ADR-0115 44.3）

`requirement.txt` 是需求原话。一条命令从需求跑到结果（回放 CI 上 Claude 的录制，不调用真实 AI）：

```bash
python -m assist.robot_case examples/robots/teaching-arm --replay tests/recordings/robot_design
```

真实调用 AI 时把 `--replay …` 换成 `--provider claude`（密钥从环境变量读）。支架有限元最费时，整条约一个半小时。

| 文件 | 内容 |
| --- | --- |
| `out/report.md` | **报告**：整机方案、校核结论、仿真数字与需求逐条对照、模型与 BOM、用时、卡在哪里；每个数注明出自哪个结果文件 |
| `out/bom.json`、`out/bom.csv` | BOM：外购件（零件库型号与资料出处）、自制件（图号 TA-01…，质量取三维模型）、M2.5 螺钉（按装配里的孔计数，长度待定）、未列入的 |
| `out/concept-result.json` | AI 摘的条件（带原话引用）、AI 的问题、每轮构型与初筛、采用哪个 |
| `out/build-result.json` | 载荷、选件与并列方案、杆件强度、关节装得下、重复定位精度 |
| `out/cad/cad-result.json` | 三维装配的零件、质量、重心、接口、干涉检查；`assembly.step`（约 4 MB）不入库，上面的命令重新生成 |
| `out/verify-result.json` | 用真实装配体复核多体动力学，与估算对照，选件重新校核 |
| `out/fea-result.json` | 10 个自制支架的有限元：载荷、可信度核查、对屈服与疲劳的安全系数 |
| `out/timing.json` | 各步实测用时与本机配置 |

三维模型：跑完后在问渠 CAD（或 FreeCAD）里用“文件 → 打开”选 `out/cad/assembly.step`。

只重出报告与 BOM（不重算）：`python -m assist.robot_report examples/robots/teaching-arm/out`。
