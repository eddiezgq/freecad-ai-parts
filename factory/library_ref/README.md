# library_ref

问渠零件库（wenquest 仓库 `library/`，提交 8710ae0c）中被数字工厂测试用来互核的几份文件（ADR-0058）：

- `vendor/menagerie.yaml`：MuJoCo Menagerie 机器人模型的固定提交
- `catalog/C/*/entry.yaml`：机构的参数缺省值（与 `digital/cae/mech_mjcf.py` 核对）
- `generators/c_mech.py`：机构运动学公式（与动力学模型逐点互核）

只供测试核对，不是本仓库的零件库（本仓库的零件库在 `data/library/` 与企业库）。
