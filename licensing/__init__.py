"""商业授权（ADR-0066 第 5 项）：Ed25519 签名的授权文件，离线校验。

- 只决定“闭源功能能不能用”；公开功能（工作台、选型校验、公开零件库）不看授权，到期也照常可用
- 校验是纯函数：不联网、不读时钟（日期由调用方传入）
- 公钥写在 keys.py；私钥只在签发人的环境变量 FAP_LICENSE_PRIVATE_KEY 里，不进任何仓库
"""

from licensing.license import (  # noqa: F401
    LicenseError,
    Verdict,
    canonical,
    sign,
    verify,
)
