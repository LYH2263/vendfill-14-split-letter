# VendFill 售货机补货

按货道容量、库存与在途量计算缺口，生成不超缺口、非负的补货单；一次生成按货道编号首字母拆成多本分册（一字母一张单），并对账到整机总数。

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

> 表结构有变更（新增分册表）：沿用旧数据卷启动前请先 `docker compose down -v` 重建。

## 使用说明

1. 在「点位」「货道」查看售货机布局与库存；点货道编号可改名（历史分册归属不改口）。
2. 在「销量」了解近期出货。
3. 打开「补货单」按缺口生成建议补货量：按货道编号首字母分组，每个有待补货道的字母各落一张分册，单上只含本组货道；某字母无待补货道则不建空单。
4. 在「汇总」按点位对账：字母台账（补量为 0 的字母也保留键）、各分册合计，且 Σ分册 = Σ字母 = 整机总补件数，对不齐即整批作废；拆单落库为单事务，任一环节失败全部回滚。
5. 历史分册为生成时快照，之后改货道编号不影响其归属。

## 开发与测试

```bash
docker compose exec api pytest -q
```
