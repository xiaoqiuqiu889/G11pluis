# Demo 01：第一案第一场可运行演示

## 交付边界

Demo 01 只验收第一案 `case_01_revolution_street` 的第一场
`photo_lab_2008`。它不是“所有页面都能打开”的展示，而是以下真实链路：

`浏览器操作 → Vite 客户端 → FastAPI → SQLite 世界状态 → 客户端回显`

客户端必须以 `VITE_USE_MOCK=false` 启动；服务端为了保证现场稳定，显式使用
`G1N_USE_MOCK=1` 的确定性 LLM provider。也就是说，交互和状态都走真实后端，
只有模型文本生成使用本地 mock，不需要 API Key。

## 一键启动

1. 确保 8000、5173 端口没有残留的开发服务。
2. 双击仓库根目录的 `Demo-01.cmd`。
3. 首次启动会补齐缺失依赖，随后打开：
   `http://localhost:5173/scene/photo_lab_2008`。
4. 演示结束后，关闭标题为 `G1N-Demo01-Backend` 和
   `G1N-Demo01-Frontend` 的两个窗口。

只做环境预检、不启动服务：

```cmd
Demo-01.cmd --check
```

自动化验收时禁止自动打开浏览器：

```cmd
set DEMO_NO_BROWSER=1
Demo-01.cmd
```

启动器的安全约束：不会强杀占用端口的进程；8000 仅在健康响应明确返回
`service=g1n-server` 时复用；5173 不复用，因为已运行的 Vite 实例是否由
`VITE_USE_MOCK=false` 编译无法从外部可靠判断。

## 现场演示脚本

1. 页面直接进入“德黑兰，2008 / 地下照相馆”。
2. 完成一次调查动作，确认 NPC 回应出现，界面不显示静默降级或 404。
3. 对照片执行一次有对象、有证据的结构化行为。
4. 观察服务端返回的新快照/因果种子在客户端显式回显。
5. 到达本场合法结束状态，并进入下一场或看到明确的场景结束交互。

## Demo 通过标准

- `GET http://127.0.0.1:8000/health` 返回 `status=ok`、
  `service=g1n-server`。
- `GET /v1/scenes/photo_lab_2008` 返回 `sceneId=photo_lab_2008`。
- 浏览器直达路由返回 200，并渲染 React 根节点。
- 页面创建真实服务端 run，并成功进入 `photo_lab_2008`。
- 至少一个玩家动作命中 `/v1/runs/:runId/actions`，且没有客户端伪造的
  “服务端失败后自动成功”回退。
- 至少一个动作改变服务端快照中的 artifact、belief 或 causal seed。
- 客户端展示的 runId、场景状态与服务端快照一致。
- 场景可以通过玩家可见操作结束，不存在“必须先结束才能看到结束按钮”的循环。

## 故障定位

- 后端未就绪：查看 `G1N-Demo01-Backend` 窗口，并访问 `/health`。
