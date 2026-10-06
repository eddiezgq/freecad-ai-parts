# -*- coding: utf-8 -*-
"""把问渠实验台的 ST 程序改写成 OpenPLC 运行时能编译的完整程序（第 18 轮第 8 步，OpenPLC 兼容性检查）。

问渠实验台里，设备的 I/O 名字（B_Part、Y_Clamp……）由实验的 I/O 表提供，程序直接用；OpenPLC（MatIEC 编译器）
要求程序自己声明带地址的变量，并有 CONFIGURATION / RESOURCE / TASK。这里：
1. 去掉注释（MatIEC 对注释里的非 ASCII 字符不总是友好）；
2. 在 PROGRAM 的开头插入 I/O 声明。地址改到 OpenPLC 从站设备的映射区：%IXb.i → %IX(100+b).i，%QXb.i → %QX(100+b).i，
   模拟量输入按顺序映射到 %IW100、%IW101……（OpenPLC 作为 Modbus 主站轮询“虚拟设备”这台从站，见 openplc/plant_server.mjs）；
3. 末尾加上 CONFIGURATION：一个 10 ms 的周期任务运行 PROGRAM。
"""
import re

OFFSET = 100


def strip_comments(st):
    out, i, n = [], 0, len(st)
    while i < n:
        if st.startswith("(*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if st.startswith("(*", i):
                    depth, i = depth + 1, i + 2
                elif st.startswith("*)", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif st.startswith("//", i):
            j = st.find("\n", i)
            i = n if j < 0 else j
        elif st[i] == "'":
            j = st.find("'", i + 1)
            j = n - 1 if j < 0 else j
            out.append(st[i:j + 1])
            i = j + 1
        else:
            out.append(st[i])
            i += 1
    return "".join(out)


def split_decls(src):
    """“a, b, c : R_TRIG;” → 每个变量一行。MatIEC 遇到一行声明三个以上功能块实例会崩溃（段错误），拆开就好。"""
    def one(m):
        body = re.sub(r"^(\s*)([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*:(?!=)\s*([^;]+);",
                      lambda d: "".join("{}{} : {};".format(d.group(1) if i == 0 else "\n" + d.group(1), n.strip(), d.group(3).strip())
                                        for i, n in enumerate(d.group(2).split(","))), m.group(2), flags=re.M)
        return m.group(1) + body + m.group(3)
    return re.sub(r"(\bVAR(?:_\w+)?\b[^\n]*\n)([\s\S]*?)(\bEND_VAR\b)", one, src)


def mapping(io):
    """I/O 表 → [(名字, OpenPLC 地址, 类型, 从站里的序号, 种类)]；种类 di / coil / ir"""
    out, ir = [], 0
    for x in io:
        m = re.match(r"%([IQ])([XW])(\d+)(?:\.(\d+))?$", x["addr"])
        if not m:
            raise ValueError("不支持的地址 " + x["addr"])
        area, size, a, b = m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or 0)
        if size == "X":
            addr = "%{}X{}.{}".format(area, OFFSET + a, b)
            out.append((x["name"], addr, "BOOL", a * 8 + b, "di" if area == "I" else "coil"))
        elif area == "I":
            out.append((x["name"], "%IW{}".format(OFFSET + ir), x.get("type") or "INT", ir, "ir"))
            ir += 1
        else:
            raise ValueError("暂不支持模拟量输出 " + x["addr"])
    return out


def to_openplc(st, io, cycle_ms=10):
    src = split_decls(strip_comments(st))
    m = re.search(r"\bPROGRAM\s+(\w+)", src, re.I)
    if not m:
        raise ValueError("程序里没有 PROGRAM")
    name = m.group(1)
    decl = "\n  VAR\n" + "".join("    {} AT {} : {};\n".format(n, a, t) for n, a, t, _, _ in mapping(io)) + "  END_VAR\n"
    src = src[:m.end()] + decl + src[m.end():]
    src = re.sub(r"[^\x00-\x7f]", " ", src)        # 只剩字符串里可能有的非 ASCII 字符：换成空格
    src += ("\n\nCONFIGURATION Config0\n  RESOURCE Res0 ON PLC\n"
            "    TASK MainTask(INTERVAL := T#{}ms, PRIORITY := 0);\n"
            "    PROGRAM Inst0 WITH MainTask : {};\n  END_RESOURCE\nEND_CONFIGURATION\n").format(cycle_ms, name)
    return src
