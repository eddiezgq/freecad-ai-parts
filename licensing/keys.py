"""授权签名的公钥（ADR-0066）。键是公钥编号（授权文件的 key_id），值是 32 字节原始公钥的 base64。

正式公钥由项目负责人生成（python -m licensing.issue keygen），只把公钥加到这里；私钥自己保管。
还没有正式公钥时这里为空：任何授权都校验不通过，闭源功能不开放，公开功能不受影响。
"""

PUBLIC_KEYS: dict[str, str] = {}
