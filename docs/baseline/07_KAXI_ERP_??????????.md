# KAXI ERP 全系统产品与开发清单

> 存放位置：`docs/baseline/`

> 文档状态：现行合并基线 V0.3
> 整理日期：2026-08-22
> 文档职责：登记页面、API、权限入口、后台任务和开发包，不替代完成性审计
> 最近复核：2026-08-24
> 规则：本文件是产品与开发清单的唯一现行合并基线；正式已确认决策优先于待确认建议，合并前来源仅通过 Git 历史追溯。

---

## 第1编｜KAXI_ERP_V1.0_全系统开发清单_V0.1

> 状态：开发目录基线草案  
> 目标：建立全系统功能入口和稳定编号；详细字段、请求响应及界面交互在对应模块设计中展开。  
> 关联：《V1.0需求追踪矩阵》《核心业务状态机》《数据库实体关系模型》《角色与权限矩阵》

### 1. 统一约定

#### 1.1 编号与路径

- 页面编号：`模块-P序号`，编号在全系统范围内唯一。
- API 基础路径：`/api/v1/{module}/...`。
- 权限编码：`module.resource.action`，原子权限不得依赖页面名称。
- 后台任务：`module.task_name`，必须定义幂等键、重试、死信、人工补偿和监控指标。

#### 1.2 API 基线

- 列表接口统一支持分页、排序、结构化筛选和授权范围过滤。
- 写接口携带 `Idempotency-Key`；修改接口携带 `version_no` 进行乐观锁校验。
- 状态变化使用命令端点，如 `/confirm`、`/approve`、`/cancel`，不得通过通用 PATCH 任意修改状态。
- 批量导入分为上传、校验、确认、结果下载四步。
- 导出为异步任务，权限、字段脱敏和数据范围与页面/API一致。
- 删除默认为逻辑停用；有历史交易的主数据不能物理删除。

### 2. 基础平台与权限 `SYS`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| SYS-P01 | 工作台 | 待办、告警、任务、快捷入口 | `system.dashboard.read` |
| SYS-P02 | 公司与账套 | 公司、账簿、本位币、有效期配置 | `system.company.manage` |
| SYS-P03 | 组织架构 | 部门、岗位、人员及上下级 | `auth.organization.manage` |
| SYS-P04 | 用户管理 | 账号、状态、登录方式、数据范围 | `auth.user.manage` |
| SYS-P05 | 角色权限 | 角色、原子权限和默认范围 | `auth.role.manage` |
| SYS-P06 | 用户单独授权 | 追加、限制、临时授权和最终权限预览 | `auth.override.manage` |
| SYS-P07 | 审批流程 | 流程版本、条件、节点、代理和升级 | `workflow.definition.manage` |
| SYS-P08 | 我的待办 | 审批、退回、转交、加签 | `workflow.task.process` |
| SYS-P09 | 通知中心 | 站内信、通知偏好和已读状态 | `notification.read` |
| SYS-P10 | 审计日志 | 操作、权限、登录和数据导出审计 | `audit.log.read` |
| SYS-P11 | 任务监控 | 定时任务、队列、失败和补偿 | `system.job.manage` |
| SYS-P12 | 系统参数 | 字典、编号、时区、精度及开关 | `system.config.manage` |

主要 API：`/system/companies`、`/auth/organizations`、`/auth/users`、`/auth/roles`、`/auth/user-overrides`、`/workflows/definitions`、`/workflows/tasks`、`/audit/events`、`/system/jobs`、`/system/configurations`。

### 3. 客商与基础主数据 `MDM`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| MDM-P01 | 客户档案 | 客户、联系人、地址、开票和贸易资料 | `mdm.customer.manage` |
| MDM-P02 | 代理档案 | 等级、归属、授信关联和状态 | `mdm.agent.manage` |
| MDM-P03 | 供应商档案 | 分类、联系人、结算和资质 | `mdm.supplier.manage` |
| MDM-P04 | 物流/货代档案 | 服务范围、账户和接口标识 | `mdm.logistics_party.manage` |
| MDM-P05 | 地区与国家 | 国家、地区、地址规则 | `mdm.geography.manage` |
| MDM-P06 | 币种与汇率类型 | 币种、精度、汇率来源类型 | `mdm.currency.manage` |
| MDM-P07 | 计量单位 | 单位、换算和精度 | `mdm.uom.manage` |
| MDM-P08 | 主数据查重合并 | 重复候选、合并及历史引用 | `mdm.merge.approve` |

主要 API：`/mdm/customers`、`/mdm/agents`、`/mdm/suppliers`、`/mdm/logistics-parties`、`/mdm/geographies`、`/mdm/currencies`、`/mdm/uoms`、`/mdm/merge-candidates`。

### 4. 商品与价格 `PRD/PRC`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| PRD-P01 | 商品工作台 | SPU/SKU状态、完整度及异常 | `product.dashboard.read` |
| PRD-P02 | SPU档案 | 分类、品牌、系列、中英文资料 | `product.spu.manage` |
| PRD-P03 | SKU档案 | 属性组合、材质、单位、成本方式 | `product.sku.manage` |
| PRD-P04 | 属性与模板 | 属性、可选值、模板和组合规则 | `product.attribute.manage` |
| PRD-P05 | 材质档案 | 材质、成分、贵金属参数 | `product.material.manage` |
| PRD-P06 | 条码与标签 | 多条码、二维码和标签模板 | `product.barcode.manage` |
| PRD-P07 | 单件编号规则 | 号段、限量、跳号和重生产关联 | `product.serial_rule.manage` |
| PRD-P08 | 包装方案 | 产品与包装物料标准组合 | `product.packaging_plan.manage` |
| PRD-P09 | 商品导入 | 校验、预览、确认和错误报告 | `product.import.execute` |
| PRC-P01 | 价格表 | 渠道、币种、有效期和含税模式 | `pricing.price_list.manage` |
| PRC-P02 | 代理等级折扣 | 等级、SKU折扣和最低折扣 | `pricing.agent_discount.manage` |
| PRC-P03 | 特殊定价 | 客户/SKU特价及审批 | `pricing.special_price.manage` |
| PRC-P04 | 价格试算 | 展示命中规则、优先级和毛利 | `pricing.simulate` |

主要 API：`/products/spus`、`/products/skus`、`/products/attributes`、`/products/materials`、`/products/barcodes`、`/products/serial-rules`、`/products/packaging-plans`、`/pricing/price-lists`、`/pricing/rules`、`/pricing/simulations`。

### 5. 销售、代理与售后 `SAL`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| SAL-P01 | 订单工作台 | 平台、代理、私域订单统一视图 | `sales.order.read` |
| SAL-P02 | 销售订单 | 创建、导入、确认、变更和取消 | `sales.order.manage` |
| SAL-P03 | 订单审核 | 价格、授信、库存和异常确认 | `sales.order.approve` |
| SAL-P04 | 库存承诺 | 多仓建议、预留、释放和拆单 | `sales.reservation.manage` |
| SAL-P05 | 预售/穿透订单 | 需求、补货、生产建议和交期 | `sales.penetration.manage` |
| SAL-P06 | 指定编号 | 搜索、锁定、收费和释放 | `sales.serial.assign` |
| SAL-P07 | 履约跟踪 | 拣货、发货、签收和异常 | `sales.fulfillment.read` |
| SAL-P08 | 售后单 | 退货、退款、换货、补发和折让 | `sales.aftersales.manage` |
| SAL-P09 | 客户对账 | 订单、发货、应收、收款对照 | `sales.statement.read` |

主要 API：`/sales/orders`、`/sales/orders/{id}/confirm`、`/sales/order-changes`、`/sales/reservations`、`/sales/penetration-demands`、`/sales/serial-assignments`、`/sales/fulfillments`、`/sales/after-sales`。

### 6. 仓库与库存 `INV/WMS`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| INV-P01 | 库存总览 | 现存、可售、预留、在途、冻结和成本 | `inventory.balance.read` |
| INV-P02 | 仓库库位 | 动态仓库、区域、库位和容量 | `warehouse.location.manage` |
| INV-P03 | 库存流水 | 来源单据、数量、状态和金额穿透 | `inventory.transaction.read` |
| INV-P04 | 批次/单件库存 | 批号、编号、质量和成本 | `inventory.trace.read` |
| WMS-P01 | 收货工作台 | 预约、到货、收货和待验收 | `warehouse.receipt.process` |
| WMS-P02 | 上架任务 | 上架建议、扫码和确认 | `warehouse.putaway.process` |
| WMS-P03 | 拣货任务 | 波次、拣货、缺货和复核 | `warehouse.pick.process` |
| WMS-P04 | 打包发货 | 包装、称重、面单和交接 | `warehouse.ship.process` |
| INV-P05 | 调拨 | 申请、出库、在途、收货和差异 | `inventory.transfer.manage` |
| INV-P06 | 盘点 | 计划、冻结、扫码、差异和审批 | `inventory.count.manage` |
| INV-P07 | 库存调整 | 盘盈亏、状态转换和受控更正 | `inventory.adjust.approve` |
| INV-P08 | 异常库存 | 质检、返工、报废、责任和恢复 | `inventory.exception.manage` |

主要 API：`/inventory/balances`、`/inventory/transactions`、`/warehouses`、`/warehouse-locations`、`/warehouse/tasks`、`/inventory/transfers`、`/inventory/counts`、`/inventory/adjustments`、`/inventory/exceptions`。

### 7. 采购与供应商协同 `PUR`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| PUR-P01 | 采购需求 | 补货、生产及人工需求归集 | `purchase.requisition.manage` |
| PUR-P02 | 询价比价 | 供应商报价、含税/币种比较 | `purchase.rfq.manage` |
| PUR-P03 | 采购订单 | 创建、审批、变更、交期和关闭 | `purchase.order.manage` |
| PUR-P04 | 到货与验收 | 数量、质量、差异及处置 | `purchase.receipt.inspect` |
| PUR-P05 | 采购退货 | 退货、物流和应付冲销关联 | `purchase.return.manage` |
| PUR-P06 | 供应商绩效 | 交付、质量、价格和异常 | `purchase.supplier_performance.read` |

主要 API：`/purchasing/requisitions`、`/purchasing/rfqs`、`/purchasing/orders`、`/purchasing/receipts`、`/purchasing/inspections`、`/purchasing/returns`、`/purchasing/supplier-performance`。

### 8. 生产、BOM与预包装 `MFG/PACK`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| MFG-P01 | BOM | 多版本、替代料、生效及审批 | `manufacturing.bom.manage` |
| MFG-P02 | 工艺路线 | 工序、工作中心和标准工时 | `manufacturing.routing.manage` |
| MFG-P03 | 生产建议 | 缺口、季节、活动及人工调整 | `manufacturing.suggestion.manage` |
| MFG-P04 | 生产订单 | 下达、领料、报工、完工和关闭 | `manufacturing.order.manage` |
| MFG-P05 | 领退补料 | 理论/实际用料及差异 | `manufacturing.material_issue` |
| MFG-P06 | 质检与NG | 合格、返工、报废和重生产 | `manufacturing.quality.process` |
| MFG-P07 | 委外加工 | 发料、在外、收回和费用 | `manufacturing.subcontract.manage` |
| MFG-P08 | 成本差异 | 材料、人工、制造费用和损耗 | `manufacturing.cost.read` |
| PACK-P01 | 预包装建议 | 闲时建议和人工创建 | `prepack.suggestion.manage` |
| PACK-P02 | 预包装任务 | 领料、包装、标签和完工 | `prepack.order.process` |
| PACK-P03 | 拆包 | 可退材料、损耗和库存恢复 | `prepack.breakdown.process` |

主要 API：`/manufacturing/boms`、`/manufacturing/routings`、`/manufacturing/suggestions`、`/manufacturing/orders`、`/manufacturing/material-movements`、`/manufacturing/quality`、`/manufacturing/subcontracts`、`/prepack/orders`、`/prepack/breakdowns`。

### 9. 内销、外贸、物流与单证 `TRD`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| TRD-P01 | 贸易合同 | 内外贸类型、币种、条款和履约义务 | `trade.contract.manage` |
| TRD-P02 | 外贸订单扩展 | Incoterms、目的国、报关和收款条件 | `trade.order.manage` |
| TRD-P03 | 装箱 | 箱号、SKU、编号、重量和体积 | `trade.packing.process` |
| TRD-P04 | 出运批次 | 分批/合并出运、承运及节点 | `trade.shipment.manage` |
| TRD-P05 | 单证中心 | PI、CI、PL及其他模板和快照 | `trade.document.generate` |
| TRD-P06 | 报关与退税台账 | 申报、报关资料和退税状态 | `trade.customs.manage` |
| TRD-P07 | 国际费用 | 运费、保险、报关、认证和分摊 | `trade.cost.manage` |
| TRD-P08 | 货代结算 | 代收、费用、扣款和到账核对 | `trade.forwarder_settlement.manage` |
| TRD-P09 | 运输跟踪 | 国内、国际、签收、异常和索赔 | `trade.tracking.read` |
| TRD-P10 | 海外仓 | 入仓、在途、出库和盘点 | `trade.overseas_warehouse.manage` |

主要 API：`/trade/contracts`、`/trade/orders`、`/trade/packing-lists`、`/trade/shipments`、`/trade/documents`、`/trade/customs`、`/trade/costs`、`/trade/forwarder-settlements`、`/trade/tracking`、`/trade/overseas-warehouses`。

### 10. 文件管理中心 `DOC`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| DOC-P01 | 文件库 | 分类、标签、搜索、预览和关联 | `document.file.read` |
| DOC-P02 | 文件上传 | 分片、哈希、病毒检测和元数据 | `document.file.upload` |
| DOC-P03 | 版本管理 | 新版本、对比、恢复和锁定 | `document.version.manage` |
| DOC-P04 | 业务附件 | 订单、SKU、合同、凭证双向关联 | `document.link.manage` |
| DOC-P05 | 外部分享 | 密码、期限、次数、水印和撤销 | `document.share.manage` |
| DOC-P06 | 文件审批 | L4查看、下载、分享和删除审批 | `document.sensitive.approve` |
| DOC-P07 | 归档销毁 | 保留策略、法律冻结及销毁清单 | `document.retention.manage` |
| DOC-P08 | 文件审计 | 查看、下载、分享和变更记录 | `document.audit.read` |

主要 API：`/documents/files`、`/documents/uploads`、`/documents/files/{id}/versions`、`/documents/links`、`/documents/shares`、`/documents/retention-policies`、`/documents/disposal-batches`、`/documents/audit-events`。

### 11. 财务与资金 `FIN`

财务外围页面与接口详见《财务外围页面、接口、权限与任务清单》。全局还包括：

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| FIN-P01 | 财务工作台 | 待过账、差异、资金和月结 | `finance.dashboard.read` |
| FIN-P02 | 会计政策 | 准则、纳税人、账簿和有效期 | `finance.policy.manage` |
| FIN-P03 | 会计科目 | 模板、科目、辅助核算和映射 | `finance.account.manage` |
| FIN-P04 | 会计事件 | 来源、规则、失败和重试 | `finance.event.manage` |
| FIN-P05 | 凭证 | 自动/手工、审核、过账及冲销 | `finance.journal.manage` |
| FIN-P06 | 总账与明细账 | 科目、辅助、多币种和穿透 | `finance.ledger.read` |
| FIN-P07 | 应收与收款 | 应收、账龄、收款及核销 | `finance.ar.manage` |
| FIN-P08 | 应付与付款 | 应付、三单匹配、支付及核销 | `finance.ap.manage` |
| FIN-P09 | 资金与银行 | 账户、流水、余额和对账 | `finance.treasury.manage` |
| FIN-P10 | 存货与生产成本 | 成本记录、差异和跌价 | `finance.cost.manage` |
| FIN-P11 | 费用报销 | 借款、报销、政策和分摊 | `expense.claim.manage` |
| FIN-P12 | 固定资产 | 卡片、折旧、盘点和处置 | `asset.manage` |
| FIN-P13 | 薪资 | 计算、复核、计提和发放 | `payroll.manage` |
| FIN-P14 | 税务发票 | 税码、进销项、台账和底稿 | `tax.manage` |
| FIN-P15 | 月结 | 检查、试算、关账和反结账 | `finance.period_close.manage` |
| FIN-P16 | 财务报表 | 三大报表、余额和附表 | `finance.statement.read` |

主要 API：`/finance/policies`、`/finance/accounts`、`/finance/events`、`/finance/journals`、`/finance/ledger`、`/finance/ar`、`/finance/ap`、`/finance/treasury`、`/finance/costs`、`/finance/period-close`、`/finance/statements`。

### 12. 外部接口中心 `INT`

| 页面ID | 页面 | 主要能力 | 核心权限 |
|---|---|---|---|
| INT-P01 | 连接器管理 | 平台、物流、银行、税票和货代连接 | `integration.connector.manage` |
| INT-P02 | 外部商品映射 | 平台商品/SKU与内部SKU映射 | `integration.product_mapping.manage` |
| INT-P03 | 同步任务 | 增量同步、游标、频率和状态 | `integration.sync.manage` |
| INT-P04 | 原始消息 | 请求、响应、回调和签名校验 | `integration.payload.read` |
| INT-P05 | 异常队列 | 错误分类、重试、忽略和补偿 | `integration.error.resolve` |
| INT-P06 | Webhook管理 | 订阅、密钥、重放和日志 | `integration.webhook.manage` |
| INT-P07 | 接口监控 | 成功率、延迟、限流和告警 | `integration.monitor.read` |

主要 API：`/integrations/connectors`、`/integrations/mappings`、`/integrations/sync-jobs`、`/integrations/payloads`、`/integrations/errors`、`/integrations/webhooks`。所有外部写入先落原始负载和幂等记录，再调用领域命令。

### 13. 报表与经营分析 `ANA`

| 页面ID | 页面 | 数据源 | 核心权限 |
|---|---|---|---|
| ANA-P01 | 经营驾驶舱 | ClickHouse/受控汇总 | `analytics.dashboard.read` |
| ANA-P02 | 销售分析 | 订单、收入、渠道、国家、SKU | `analytics.sales.read` |
| ANA-P03 | 库存分析 | 周转、库龄、缺货、滞销和异常 | `analytics.inventory.read` |
| ANA-P04 | 采购分析 | 价格、交期、质量和供应商 | `analytics.purchase.read` |
| ANA-P05 | 生产分析 | 产量、效率、损耗和差异 | `analytics.manufacturing.read` |
| ANA-P06 | 客户代理分析 | 复购、授信、账龄和利润 | `analytics.customer.read` |
| ANA-P07 | 外贸分析 | 国家、币种、费用和出运 | `analytics.trade.read` |
| ANA-P08 | 财务分析 | 利润、现金、成本和预算 | `analytics.finance.read` |
| ANA-P09 | 报表中心 | 模板、订阅、导出和快照 | `analytics.report.manage` |

经营报表允许使用 ClickHouse；正式余额、凭证、库存可用量和审批判断必须回到 PostgreSQL 交易事实。

### 14. 全系统后台任务目录

| 领域 | 任务 |
|---|---|
| 系统权限 | 临时权限回收、离职账号冻结、审批超时升级、通知投递 |
| 主数据 | 重复候选扫描、资料完整度检查、外部编码校验 |
| 商品价格 | 价格生效/失效、条码冲突扫描、商品索引刷新 |
| 销售 | 平台订单同步、订单超时、预留释放、授信重算、售后状态同步 |
| 库存仓库 | 库存汇总重建、预留一致性检查、在途超时、盘点差异汇总 |
| 采购 | 交期提醒、收货未验收、三单匹配、暂估计提/冲回 |
| 生产包装 | 需求计算、生产建议、成本归集、超耗检查、预包装建议 |
| 外贸物流 | 运踪同步、节点提醒、单证生成、费用分摊、货代对账 |
| 文件 | 病毒检测、预览/OCR、哈希校验、分享过期、保留与销毁候选 |
| 财务 | 过账、汇率导入、重估、折旧、薪资、税账、月结和子账对账 |
| 接口 | Outbox投递、回调验签、限流重试、死信补偿、凭据过期提醒 |
| 分析 | CDC同步、指标聚合、报表快照、订阅发送和源端对账 |
| 运维 | 数据库备份、对象存储校验、恢复演练、日志归档和容量告警 |

### 15. 跨模块事务与事件

| 场景 | 强一致事务内 | 事务后事件/任务 |
|---|---|---|
| 订单确认 | 订单状态、价格快照、授信占用、库存预留 | 通知仓库、分析同步、平台确认 |
| 销售出库 | 履约明细、库存流水、编号状态、成本记录 | 会计事件、物流回传、报表同步 |
| 采购验收 | 验收结果、库存流水、质检状态 | 暂估事件、供应商绩效更新 |
| 生产完工 | 投入产出、库存、编号、实际成本 | 差异分析和凭证生成 |
| 预包装/拆包 | 产品状态与包装物料库存 | 标签、成本事件和建议刷新 |
| 收付款核销 | 资金可用额、核销明细、子账余额 | 汇兑事件、对账及通知 |
| 文件版本 | 元数据、当前版本指针、关联 | 预览、OCR、病毒检测和索引 |

跨模块异步事件统一经事务 Outbox 发出；消费者必须幂等。任何异步失败不得造成库存、资金或凭证事实被静默丢失。

### 16. 开发包与建议顺序

开发仍以完整 V1.0 一次上线为目标，以下仅是工程依赖顺序：

1. `foundation`：公司、组织、权限、工作流、审计、文件、字典、任务框架。
2. `master-data`：客商、商品、仓库、价格和迁移框架。
3. `order-inventory`：销售、授信、预留、库存、仓库履约和售后。
4. `supply-production`：采购、质检、BOM、生产、预包装及成本。
5. `trade-integration`：外贸、物流、单证、平台与外部接口。
6. `finance`：总账、收付、资产、费用、薪资、税票和月结。
7. `analytics-go-live`：ClickHouse、报表、全量迁移、压测、安全和上线演练。

各开发包通过对应内部验收门后进入集成主线，但不得独立替代最终 V1.0 总体验收。

### 17. 下一层详细设计产物

- 页面字段与交互规格：输入、显示、筛选、批量操作、状态按钮和错误提示。
- OpenAPI：请求响应模型、错误码、幂等、权限和示例。
- 物理数据模型：字段、索引、约束、分区门槛和迁移顺序。
- 权限注册表：权限码、风险等级、默认角色、审批和数据范围。
- 任务注册表：调度、队列、超时、重试、死信、补偿和告警。
- 测试用例：需求ID、前置数据、步骤、预期结果、凭证/流水及审计证据。

---

## 第2编｜KAXI_ERP_V1.0_后台任务注册表_V0.1

> 技术基线：Celery 执行，Redis 作为队列/缓存基础设施；PostgreSQL保存任务业务状态和幂等记录。  
> 原则：任务可以重试，业务影响只能发生一次。

### 1. 队列划分

| 队列 | 用途 | 特性 |
|---|---|---|
| `critical` | 库存补偿、财务过账、权限回收 | 高优先级、短任务、严格告警 |
| `integration` | 平台、物流、银行、税票接口 | 外部限流、指数退避 |
| `documents` | 病毒检测、预览、OCR、哈希 | CPU/IO隔离，文件大小限制 |
| `finance` | 成本、重估、折旧、薪资、月结 | 单公司/期间互斥锁 |
| `analytics` | CDC后处理、指标、报表 | 可延迟，不阻塞交易 |
| `maintenance` | 对账、归档、通知、清理 | 低优先级、错峰运行 |

### 2. 任务公共字段

`task_name`、`task_version`、`idempotency_key`、`company_id`、`source_type/id`、`status`、`priority`、`queue`、`attempts/max_attempts`、`scheduled_at`、`started_at`、`heartbeat_at`、`finished_at`、`next_retry_at`、`error_code`、`error_summary`、`trace_id`、`result_reference`。

任务载荷不存密码、令牌、完整银行/身份信息；大结果保存到文件中心并引用文件ID。

### 3. 权限、工作流与系统任务

| 任务名 | 触发 | 幂等键/互斥 | 失败策略 |
|---|---|---|---|
| `auth.expire_user_overrides` | 每分钟 | 时间窗 | 读取时先判过期；任务失败立即告警 |
| `auth.freeze_departed_users` | 人员离职事件+每日 | 用户+离职版本 | 重试并生成未转交清单 |
| `workflow.escalate_overdue_tasks` | 每15分钟 | 待办+升级级次 | 重试；不自动代替审批 |
| `notification.dispatch` | 事件驱动 | 通知ID+渠道 | 分渠道重试，永久失败保留 |
| `system.export_dataset` | 用户申请 | 导出申请ID | 权限快照复核；超时分片 |
| `audit.verify_chain` | 每日 | 公司+日期 | 发现断链立即安全告警 |

### 4. 商品、价格与主数据

| 任务名 | 触发 | 关键规则 |
|---|---|---|
| `mdm.scan_duplicate_parties` | 每日/导入后 | 只生成候选，不自动合并 |
| `product.validate_catalog_completeness` | 资料变更后 | 按渠道/国家模板检查 |
| `product.refresh_search_index` | Outbox | PostgreSQL搜索索引幂等更新 |
| `pricing.activate_versions` | 每分钟 | 仅激活已批准、到生效时间版本 |
| `pricing.expire_versions` | 每分钟 | 不改写订单价格快照 |
| `product.validate_barcode_uniqueness` | 导入确认前 | 冲突阻断正式导入 |

### 5. 销售、授信、库存和仓库

| 任务名 | 触发 | 幂等/补偿 |
|---|---|---|
| `sales.expire_draft_orders` | 定时 | 按渠道策略，先通知后关闭 |
| `inventory.release_expired_reservations` | 每分钟 | 预留ID+版本；事务内释放库存与授信 |
| `credit.rebuild_exposure` | 每日/异常后 | 从订单占用和应收重建，差异报警 |
| `inventory.rebuild_balance_check` | 每日 | 从流水核对余额，不自动覆盖差异 |
| `inventory.detect_negative_or_overreserved` | 高频 | 异常立即冻结相关维度并告警 |
| `wms.release_abandoned_task_locks` | 每5分钟 | 租约超时；保留作业记录 |
| `inventory.flag_overdue_transfers` | 每日 | 调拨在途超时生成待办 |
| `sales.refresh_penetration_demands` | 订单/库存事件 | 需求ID+版本，不增加物理库存 |

### 6. 采购、生产与包装

| 任务名 | 触发 | 关键规则 |
|---|---|---|
| `purchase.remind_due_orders` | 每日 | 供应商/采购负责人通知 |
| `purchase.flag_uninspected_receipts` | 每小时 | 超时收货进入异常队列 |
| `finance.run_three_way_match` | 收货/发票事件 | 匹配批次唯一，超差人工处理 |
| `finance.accrue_uninvoiced_receipts` | 月结 | 公司+期间+收货行唯一 |
| `manufacturing.calculate_suggestions` | 每日/人工 | 保存输入快照，输出需人工确认 |
| `manufacturing.collect_actual_costs` | 完工/月结 | 生产单+成本版本唯一 |
| `manufacturing.detect_overconsumption` | 领料后 | 超阈值预警/阻断按政策 |
| `prepack.calculate_idle_suggestions` | 每日 | 只生成建议，不自动消耗库存 |

### 7. 外贸、文件与接口

| 任务名 | 触发 | 关键规则 |
|---|---|---|
| `trade.sync_tracking` | 定时 | 运单+外部事件ID去重 |
| `trade.generate_documents` | 审批/状态事件 | 模板版本+业务快照固定 |
| `trade.allocate_shipment_costs` | 费用确认 | 分摊批次可重算，过账后走更正 |
| `document.scan_malware` | 上传完成 | 通过前文件不可业务发布 |
| `document.generate_preview` | 安全扫描通过 | 失败不影响原件保存 |
| `document.run_ocr` | 按分类启用 | OCR为建议，修订留痕 |
| `document.expire_shares` | 每分钟 | 访问时也同步校验失效 |
| `document.verify_object_hash` | 周期抽检 | 丢失/篡改立即告警 |
| `document.prepare_retention_candidates` | 每日 | 法律冻结优先，不自动永久删除 |
| `integration.pull_orders` | 平台游标定时 | 账号+对象+外部ID幂等 |
| `integration.push_fulfillment` | Outbox | 平台订单+履约版本唯一 |
| `integration.process_webhook` | 回调 | 先验签落原文，再处理 |
| `integration.retry_dead_letters` | 人工批准 | 新补偿记录引用原失败消息 |

### 8. 财务任务

| 任务名 | 触发 | 互斥与失败策略 |
|---|---|---|
| `finance.post_accounting_events` | 事件驱动 | 会计事件幂等；失败进入复核队列 |
| `finance.import_exchange_rates` | 每日/人工 | 来源+币种+日期+类型唯一 |
| `finance.run_fx_revaluation` | 月结 | 公司+账簿+期间+版本互斥 |
| `finance.calculate_inventory_cost` | 入出库/月结 | SKU成本维度顺序锁，禁止并发重算 |
| `finance.assess_inventory_impairment` | 月结 | 只生成评估草稿，审批后过账 |
| `finance.refresh_ar_ap_aging` | 每日 | 快照可重建，失败阻断月结 |
| `finance.suggest_cash_allocations` | 流水后 | 仅建议，不自动越权核销 |
| `asset.calculate_depreciation` | 月结/人工 | 折旧试算可重跑，过账批次唯一 |
| `payroll.calculate_run` | 人工 | 输入和规则版本快照；逐员工错误 |
| `tax.verify_invoices` | 定时/人工 | 外部不可用时排队告警 |
| `tax.build_return_workpaper` | 月结 | 从税务明细重建，不覆盖已确认版本 |
| `finance.run_subledger_reconciliation` | 每日/月结 | 差异输出文件；重大差异阻断关账 |
| `finance.run_period_close_checks` | 人工/月结 | 任务图按依赖顺序，全部留证 |

### 9. 分析与运维

| 任务名 | 触发 | 关键规则 |
|---|---|---|
| `event.publish_outbox` | 高频 | `SKIP LOCKED`领取；至少一次投递+消费幂等 |
| `analytics.consume_cdc` | 持续 | 保存LSN/水位，不反写交易表 |
| `analytics.reconcile_source` | 每日 | 行数、金额和关键维度核对 |
| `analytics.refresh_aggregates` | 小时/每日 | 迟到事件支持重算窗口 |
| `database.verify_backup` | 每日 | 验证备份可读、WAL连续 |
| `database.restore_rehearsal` | 定期 | 隔离环境恢复并形成报告 |
| `storage.capacity_monitor` | 每5分钟 | 数据库/对象/队列阈值告警 |

### 10. 重试和死信标准

- 数据库瞬态错误：短间隔指数退避，最多5次。
- 外部限流/不可用：尊重 `Retry-After`，指数退避并加随机抖动。
- 业务校验错误：不自动重试，直接进入人工处理。
- 权限或审批缺失：不重试执行，创建待办。
- 达到上限进入死信，保存错误类别、载荷摘要、原任务、尝试记录和建议动作。
- 人工补偿不修改原任务为成功，而是创建引用原任务的新补偿执行。

### 11. 监控指标

每任务至少监控：排队数量、最老等待时间、吞吐、成功率、重试率、P95耗时、死信数、租约超时数和业务水位。财务过账、权限回收、库存异常、接口回传和CDC延迟设独立告警。

### 12. 任务验收

1. 重复投递不会重复扣库存、占授信、核销资金或生成凭证。
2. Worker崩溃后租约任务可恢复且不丢失。
3. 外部接口长期不可用时不阻塞内部交易，恢复后可按序补偿。
4. 每个死信可定位来源、责任模块和人工动作。
5. 任务跨版本发布兼容，旧消息不会被新代码错误解释。

