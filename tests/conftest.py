import os

os.environ.setdefault("MASTER_PASSWORD", "test-pw")
os.environ.setdefault("REPO_BACKEND", "memory")
os.environ["ANTHROPIC_API_KEY"] = ""      # 測試不呼叫真的 AI
os.environ["SMTP_PASSWORD"] = ""          # 測試不寄真信
