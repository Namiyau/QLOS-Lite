# QLOS-Lite

简体中文 | [English](README.en.md) | [日本語](README.ja.md)

QLOS-Lite 是 QQ / NapCat / OneBot 到 Hermes 的安全接入层。它负责 QQ 消息接收、身份和群规则、附件元数据、队列、审计、风险拦截，并可把消息交给 Hermi Gateway 统一处理。

## 配合关系

```text
QQ -> NapCat/OneBot -> QLOS-Lite :8766 -> Hermi Gateway :8789 -> Hermes Gateway :8642
```

Hermi 是可选的：不接 Hermi 时，QLOS-Lite 也可以直接调用 Hermes Gateway；接入 Hermi 后，建议统一由 Hermi 负责会话、权限和额度。

## 本地运行

1. 安装 Python 3.11+、外部 NapCatQQ 和 Hermes Agent/Gateway。
2. 复制 `secrets.local.env.example` 为 `secrets.local.env`。
3. 复制 `roles.example.json` 为 `roles.json`，填入自己的 QQ/群规则。
4. 安装外部 NapCatQQ，并设置 `NAPCAT_ROOT`，或启动脚本传入 `-NapCatDir`。
5. 运行：

```powershell
python -m qlos_lite.onebot_server
```

NapCatQQ、Hermes Agent 和 Hermi 的启动由外部脚本或 `Hermi-Stack-Launcher` 负责。NapCatQQ 的二进制、登录状态和 QQ 数据没有放进公开版。

诊断脚本默认从 `NAPCAT_LOG_DIR` 读取 NapCat 日志；不设置时只使用一个不存在的公开占位路径，不会假装仓库内带有 NapCat。

## 测试

```powershell
python -m pytest -q
```

重点测试包括 Hermi 客户端、Hermes runs 客户端、OneBot 路由、附件、队列、审批桥、身份和风险策略。

## 公开版边界

公开版不包含 NapCat、`state/`、`logs/`、QQ 媒体、真实角色配置和任何密钥。它只包含 QLOS Python 核心、测试、公开插件、技能说明和诊断脚本。
