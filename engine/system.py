"""系统装载与连接图（ADR-0025）。

组件由调用方给出（golden fixtures、知识库或候选求解器），引擎本身不读数据库。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


class SystemError_(ValueError):
    """系统本身不合法（实例重复、引用不存在的组件或端口、端口重复连接）。"""


@dataclass(frozen=True)
class PortRef:
    instance: str
    port: str

    def __str__(self) -> str:
        return f"{self.instance}.{self.port}"

    @classmethod
    def parse(cls, ref: str) -> PortRef:
        inst, _, port = ref.partition(".")
        return cls(inst, port)


@dataclass
class System:
    id: str
    requirement: dict
    instances: dict[str, dict]  # 实例名 → 组件
    connections: list[tuple[PortRef, PortRef]]
    _ports: dict[PortRef, dict] = field(default_factory=dict, repr=False)

    def port(self, ref: PortRef) -> dict:
        return self._ports[ref]

    def spec(self, ref: PortRef, name: str) -> dict | None:
        return self._ports[ref]["spec"].get(name)

    def of_category(self, category: str) -> list[str]:
        return [name for name, c in self.instances.items() if c["category"] == category]

    def one(self, category: str) -> str | None:
        """该品类的唯一实例名；没有或多于一个时返回 None（多于一个由链路模板负责，V1 校验按唯一实例处理）。"""
        found = self.of_category(category)
        return found[0] if len(found) == 1 else None

    def partner(self, ref: PortRef) -> PortRef | None:
        for a, b in self.connections:
            if a == ref:
                return b
            if b == ref:
                return a
        return None

    def connected(self, start: PortRef, goal: PortRef, port_types: set[str]) -> bool:
        """start 与 goal 之间是否有一条连接路径，中间只经过转接件（ADR-0020）。

        转接件视为直通：从它的一个端口进入，可以从它另一个同类端口（同在 port_types 中）出去。
        """
        seen = {start}
        frontier = [start]
        while frontier:
            ref = frontier.pop()
            if ref == goal:
                return True
            nxt = []
            other = self.partner(ref)
            if other is not None:
                nxt.append(other)
            comp = self.instances[ref.instance]
            if comp["category"] == "adapter" and ref != start:
                nxt += [PortRef(ref.instance, p["id"]) for p in comp["ports"]
                        if p["id"] != ref.port and p["type"] in port_types]
            for n in nxt:
                if n not in seen:
                    seen.add(n)
                    frontier.append(n)
        return False


def load_system(system: Mapping, resolve: Callable[[str], dict | None]) -> System:
    """由系统对象（schema/system.schema.json）与组件解析函数装载系统。"""
    instances: dict[str, dict] = {}
    for c in system["components"]:
        name = c["instance"]
        if name in instances:
            raise SystemError_(f"实例名重复：{name}")
        comp = resolve(c["component"])
        if comp is None:
            raise SystemError_(f"找不到组件 {c['component']}")
        instances[name] = comp
    ports = {PortRef(n, p["id"]): p for n, comp in instances.items() for p in comp["ports"]}
    conns = []
    used: set[PortRef] = set()
    for c in system["connections"]:
        a, b = PortRef.parse(c["a"]), PortRef.parse(c["b"])
        for r in (a, b):
            if r not in ports:
                raise SystemError_(f"端口不存在：{r}")
            if r in used:
                raise SystemError_(f"端口重复连接：{r}")
            used.add(r)
        conns.append((a, b))
    return System(system["id"], dict(system["requirement"]), instances, conns, ports)
