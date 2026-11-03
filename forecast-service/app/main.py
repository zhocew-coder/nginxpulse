"""预测服务主入口。

启动：USE_MOCK=true python -m app.main
"""
import uvicorn

from app.api.main import app
from app.core.config import settings


if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
