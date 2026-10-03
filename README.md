# VendFill 售货机补货

按货道容量、库存与在途量计算缺口，生成不超缺口、非负的补货单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4800 |
| API | http://localhost:9800 |
| API 文档 | http://localhost:9800/docs |
| Postgres | localhost:5449 |

健康检查：`GET http://localhost:9800/api/health`

## 使用说明

1. 在「点位」「货道」查看售货机布局与库存。
2. 在「销量」了解近期出货。
3. 打开「补货小票」生成整机补货单：按货道编号首字母（立柱字母）拆单，每个有待补货道的字母落一册小票，单上只含该组货道；某字母无待补时不建空单，但页面仍显示该字母补量为 0。
4. 各分册补量之和必须等于整机总补件数（页面对账栏实时校验，对不齐即废）。
5. 「历史批次」下拉可回看任意批次：分册内容为生成时快照，事后修改货道编号不会改变历史归属。
6. 在「满仓」「汇总」查看满仓货道与按字母分册的对账汇总。

拆单（非法编号、串组、对账不平）或落库任一环节失败时，整机批次与所有分册整批回滚，不会留下半套分册。

## 开发与测试

```bash
docker compose exec api pytest -q
```
