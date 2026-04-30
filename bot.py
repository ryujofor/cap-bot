import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
from fastapi import FastAPI
from nonebot import get_app
import asyncio


nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
app: FastAPI = get_app()

async def list_routes():
    print("=== 当前注册的路由 ===")
    for route in app.routes:
        print(f"路径: {route.path}, 方法: {route.methods}")
    print("===================")

# 在启动后打印路由
@app.on_event("startup")
async def startup_event():
    await asyncio.sleep(1)  # 等待其他插件加载
    await list_routes()

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
