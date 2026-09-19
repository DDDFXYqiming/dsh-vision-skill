# 开发与自检

## 自检命令

```bash
npm run check                              # 语法检查与 no-API 自检
python -m unittest discover -s tests -v    # 纯函数与降级链测试
python scripts/vision.py --check --no-api  # provider 链、PIL 与 tesseract 自检
```

改完代码先跑这三条离线自检。

## 验证粘贴链路

直接粘贴由客户端和 web 宿主协作完成，验证时需要重启 web 宿主，并在浏览器里强制刷新页面。

## pi-ai 兼容补丁

补丁作用于 profile 内的厂商包 `dsh-llm-pi-ai`，脚本从 `USERPROFILE` 推导目标路径，profile 不在默认位置时先改脚本里的路径。DSH 升级或重装覆盖 `node_modules` 后需要重放，重放后重启宿主：

```powershell
powershell -File scripts\reapply-pi-ai-vision-patch.ps1
```

还原旧附件行为：

```powershell
python scripts\restore_pi_ai_vision_patch.py
```
