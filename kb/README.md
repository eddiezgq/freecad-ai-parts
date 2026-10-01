# kb：组件知识库（L2）

存储设计见 [ADR-0018](../docs/adr/0018-kb-storage.md)。

| 模块 | 作用 |
| --- | --- |
| `db.py` | 连接（`DATABASE_URL`）与迁移（`migrations/*.sql`，可重复运行） |
| `validation.py` | 用 `schema/` 校验数据 |
| `sources.py` | 读取 `data/sources.yaml`，判断来源文档能否入库 |
| `store.py` | 导入（schema 校验 → 虚构组件拦截 → 来源许可 → 端口 id 唯一 → 变更留痕）、读取、列出、导出快照 |

```python
from kb.db import connect, migrate
from kb.sources import SourceRegistry
from kb.store import import_component, get_component, export_snapshot

conn = connect()            # 读 DATABASE_URL
migrate(conn)
import_component(conn, component, registry=SourceRegistry.load(), changed_by="eddie")
```
