# LLM 录制响应

测试与 CI 只回放这里的录制，不联网（ADR-0021）。文件名是请求内容（模型、提示词版本、提示文本、工具定义）的 sha256；提示词或字段清单改动后旧录制自动失效。

录制只能由持有 API 密钥的人在本地生成：

```bash
pip install -e ".[dev,llm]"
# 密钥放在仓库根目录的 .env（不入 git）：ANTHROPIC_API_KEY=...
python -m ingest.synthetic --out data/synthetic --variants 2
python -m ingest.llm_extract data/synthetic/<规格书>.pdf --category reducer --doc src-test-fixture --record
```

录制文件里没有密钥，只有请求哈希、模型名、提示词版本和响应内容，可以提交。真实厂商规格书的录制含有规格书内容，须在该来源取得授权后才能提交。
