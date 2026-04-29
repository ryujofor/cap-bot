# cap-bot - QQ 图片生成机器人

## 功能

在 QQ 群里 **@机器人** 后输入图片描述，自动生成图片。

**使用示例**: `@我 一只在月光下的白猫，中国水墨画风格`

## 项目结构

```
D:\bot\
├── cap-bot/              # NoneBot 插件（图片生成）
│   ├── src/plugins/image_gen/
│   └── gen_image.py      # 图片生成接口
├── lagrange/             # Lagrange.OneBot（QQ 协议端）
│   └── Lagrange.OneBot/
├── start-all.bat         # 一键启动两个服务
├── start-nonebot.bat     # 单独启动 NoneBot
└── start-lagrange.bat    # 单独启动 Lagrange
```

## 快速启动

双击 `D:\bot\start-all.bat` 即可一键启动。

会打开两个窗口：
- **NoneBot** - 图片生成插件，监听 `http://127.0.0.1:8081`
- **Lagrange.OneBot** - QQ 协议端，连接 QQ 服务器

关闭任意窗口即停止对应服务。

## 注意事项

- 首次登录可能需要手机 QQ 扫码验证
- 图片生成需要 10-30 秒，请耐心等待
- API 调用次数有限额，请勿频繁使用
