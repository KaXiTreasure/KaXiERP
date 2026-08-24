import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CurrentUser,
  Entity,
  createEntity,
  currentUser,
  getDashboard,
  listEntities,
  login,
  logout,
  postAction,
  request,
  updateEntity,
} from "./api";

type Spec = {
  key: string;
  group: string;
  title: string;
  subtitle: string;
  path: string;
  permission: string;
  columns: [string, string][];
};
type Field = {
  name: string;
  label: string;
  type?:
    | "text"
    | "number"
    | "date"
    | "datetime-local"
    | "checkbox"
    | "json"
    | "select";
  required?: boolean;
  options?: [string, string][];
};
type Appearance = {
  appName: string;
  versionName: string;
  theme: string;
  logoUrl: string;
  loginBackground: string;
  backgroundSource: "local" | "bing";
  bingImageTitle: string;
  bingImageCopyright: string;
  bingImageDate: string;
  loginCardOpacity: number;
  loginFooterText: string;
  loginFooterLinks: FooterLink[];
  loginSlogan: string;
  loginSlogan1: string;
  loginSlogan2: string;
  primaryFont: number | null;
  westernFont: number | null;
  fontLibrary: FontChoice[];
};
type FontChoice = {
  id: number;
  family_name: string;
  display_name: string;
  coverage: "combined" | "cjk_only" | "latin_only";
  latin_supported: boolean;
  cjk_glyph_count: number;
  font_url: string;
};
type FooterLink = { label: string; url: string };
type BrandingResponse = {
  app_name: string;
  version_name: string;
  theme: string;
  logo_url: string;
  login_background: string;
  background_source: "local" | "bing";
  bing_image_title: string;
  bing_image_copyright: string;
  bing_image_date: string;
  login_card_opacity: number;
  login_footer_text: string;
  login_footer_links: FooterLink[];
  login_slogan: string;
  login_slogan_1: string;
  login_slogan_2: string;
  primary_font: number | null;
  western_font: number | null;
  font_library: FontChoice[];
};
const toAppearance = (data: BrandingResponse): Appearance => ({
  appName: data.app_name,
  versionName: data.version_name,
  theme: data.theme,
  logoUrl: data.logo_url,
  loginBackground: data.login_background,
  backgroundSource: data.background_source,
  bingImageTitle: data.bing_image_title,
  bingImageCopyright: data.bing_image_copyright,
  bingImageDate: data.bing_image_date,
  loginCardOpacity: data.login_card_opacity,
  loginFooterText: data.login_footer_text,
  loginFooterLinks: data.login_footer_links,
  loginSlogan: data.login_slogan,
  loginSlogan1: data.login_slogan_1,
  loginSlogan2: data.login_slogan_2,
  primaryFont: data.primary_font,
  westernFont: data.western_font,
  fontLibrary: data.font_library,
});
const DEFAULT_APPEARANCE: Appearance = {
  appName: "KAXI ERP",
  versionName: "V1.0",
  theme: "forest",
  logoUrl: "",
  loginBackground: "",
  backgroundSource: "local",
  bingImageTitle: "",
  bingImageCopyright: "",
  bingImageDate: "",
  loginCardOpacity: 92,
  loginFooterText: "V1.0 · 全链路追溯",
  loginFooterLinks: [],
  loginSlogan: "Slogan",
  loginSlogan1: "Slogan1",
  loginSlogan2: "Slogan2",
  primaryFont: null,
  westernFont: null,
  fontLibrary: [],
};
const themes = [
  { key: "forest", name: "松林金", colors: ["#153426", "#d8aa55", "#f1f3ef"] },
  { key: "ocean", name: "深海蓝", colors: ["#123b58", "#42b4d6", "#eef5f8"] },
  { key: "indigo", name: "典雅靛紫", colors: ["#302b63", "#9d8cff", "#f4f1fa"] },
  { key: "coral", name: "暖砂珊瑚", colors: ["#56312d", "#e9876d", "#faf3ee"] },
  { key: "graphite", name: "石墨夜色", colors: ["#20252b", "#73d1b2", "#edf0f2"] },
];
const specs: Spec[] = [
  {
    key: "products",
    group: "主数据",
    title: "商品与 SKU",
    subtitle: "SPU、SKU、状态与追踪属性",
    path: "/api/v1/products/skus/",
    permission: "product.master.manage",
    columns: [
      ["sku_code", "SKU 编码"],
      ["name_zh", "商品名称"],
      ["spu", "SPU"],
      ["status", "状态"],
    ],
  },
  {
    key: "parties",
    group: "主数据",
    title: "客户与供应商",
    subtitle: "统一客商、联系信息与贸易属性",
    path: "/api/v1/master-data/parties/",
    permission: "master.party.manage",
    columns: [
      ["party_code", "客商编码"],
      ["name", "名称"],
      ["party_type", "类型"],
      ["status", "状态"],
    ],
  },
  {
    key: "party-merges",
    group: "主数据",
    title: "主数据查重合并",
    subtitle: "重复候选、双人审批、引用迁移与历史保留",
    path: "/api/v1/master-data/merge-candidates/",
    permission: "mdm.merge.approve",
    columns: [
      ["canonical_party", "保留档案"],
      ["duplicate_party", "重复档案"],
      ["match_score", "匹配度"],
      ["status", "状态"],
    ],
  },
  {
    key: "warehouses",
    group: "主数据",
    title: "仓库与库位",
    subtitle: "仓库、库区、货架和库位",
    path: "/api/v1/warehouses/warehouses/",
    permission: "warehouse.master.manage",
    columns: [
      ["warehouse_code", "仓库编码"],
      ["name", "仓库名称"],
      ["timezone", "时区"],
      ["status", "状态"],
    ],
  },
  {
    key: "price-lists",
    group: "主数据",
    title: "价格体系",
    subtitle: "价格表、代理折扣与特殊价格",
    path: "/api/v1/pricing/price-lists/",
    permission: "pricing.manage",
    columns: [
      ["price_list_no", "价格表编号"],
      ["name", "名称"],
      ["currency", "币种"],
      ["status", "状态"],
    ],
  },
  {
    key: "sales",
    group: "业务",
    title: "销售订单",
    subtitle: "订单、定价、授信与履约",
    path: "/api/v1/sales/orders/",
    permission: "sales.order.view",
    columns: [
      ["order_no", "订单号"],
      ["order_date", "下单时间"],
      ["customer", "客户"],
      ["status", "状态"],
    ],
  },
  {
    key: "aftersales",
    group: "业务",
    title: "销售售后",
    subtitle: "退货、退款、换货与补发",
    path: "/api/v1/aftersales/cases/",
    permission: "sales.aftersales.create",
    columns: [
      ["case_no", "售后单号"],
      ["case_type", "类型"],
      ["customer", "客户"],
      ["status", "状态"],
    ],
  },
  {
    key: "purchasing",
    group: "供应",
    title: "采购订单",
    subtitle: "采购、收货与验收",
    path: "/api/v1/purchasing/orders/",
    permission: "purchase.order.manage",
    columns: [
      ["purchase_order_no", "采购单号"],
      ["supplier", "供应商"],
      ["total", "金额"],
      ["status", "状态"],
    ],
  },
  {
    key: "requisitions",
    group: "供应",
    title: "采购需求",
    subtitle: "需求、询价与定标",
    path: "/api/v1/purchasing/requisitions/",
    permission: "purchase.requisition.manage",
    columns: [
      ["requisition_no", "需求单号"],
      ["required_date", "需求日期"],
      ["source_type", "来源"],
      ["status", "状态"],
    ],
  },
  {
    key: "inventory",
    group: "供应",
    title: "库存中心",
    subtitle: "在手、预留、冻结与可用",
    path: "/api/v1/inventory/balances/",
    permission: "inventory.balance.read",
    columns: [
      ["sku", "SKU"],
      ["warehouse", "仓库"],
      ["on_hand_qty", "在手"],
      ["reserved_qty", "预留"],
    ],
  },
  {
    key: "warehouse-tasks",
    group: "供应",
    title: "仓储现场任务",
    subtitle: "上架、波次拣货、扫码与打包复核",
    path: "/api/v1/warehouses/tasks/",
    permission: "warehouse.task.read",
    columns: [
      ["task_no", "任务号"],
      ["task_type", "任务类型"],
      ["wave_no", "波次"],
      ["status", "状态"],
    ],
  },
  {
    key: "production",
    group: "制造",
    title: "生产订单",
    subtitle: "领料、报工、完工与损耗",
    path: "/api/v1/manufacturing/orders/",
    permission: "manufacturing.order.manage",
    columns: [
      ["production_order_no", "生产单号"],
      ["product_sku", "产品"],
      ["planned_qty", "计划数量"],
      ["status", "状态"],
    ],
  },
  {
    key: "subcontracts",
    group: "制造",
    title: "委外加工",
    subtitle: "委外发料、在外与收回",
    path: "/api/v1/manufacturing/subcontracts/",
    permission: "manufacturing.subcontract.manage",
    columns: [
      ["subcontract_no", "委外单号"],
      ["supplier", "加工商"],
      ["ordered_qty", "数量"],
      ["status", "状态"],
    ],
  },
  {
    key: "prepack",
    group: "制造",
    title: "预包装",
    subtitle: "预包装执行与拆包",
    path: "/api/v1/prepack/orders/",
    permission: "prepack.order.manage",
    columns: [
      ["prepack_order_no", "任务号"],
      ["product_sku", "产品"],
      ["planned_qty", "计划数量"],
      ["status", "状态"],
    ],
  },
  {
    key: "shipments",
    group: "贸易",
    title: "出运批次",
    subtitle: "装箱、单证、交运与跟踪",
    path: "/api/v1/trade/shipments/",
    permission: "trade.shipment.manage",
    columns: [
      ["shipment_no", "出运批次"],
      ["transport_mode", "运输方式"],
      ["destination", "目的地"],
      ["status", "状态"],
    ],
  },
  {
    key: "trade-documents",
    group: "贸易",
    title: "贸易单证",
    subtitle: "PI、商业发票、装箱单和不可变快照",
    path: "/api/v1/trade/documents/",
    permission: "trade.document.generate",
    columns: [
      ["document_no", "单证编号"],
      ["document_type", "类型"],
      ["shipment", "出运批次"],
      ["status", "状态"],
    ],
  },
  {
    key: "customs-declarations",
    group: "贸易",
    title: "报关与退税",
    subtitle: "申报快照、放行及退税状态",
    path: "/api/v1/trade/customs-declarations/",
    permission: "trade.customs.manage",
    columns: [
      ["declaration_no", "报关单号"],
      ["shipment", "出运批次"],
      ["declared_amount", "申报金额"],
      ["status", "状态"],
    ],
  },
  {
    key: "trade-costs",
    group: "贸易",
    title: "国际费用",
    subtitle: "运费、保险、报关、认证与分摊",
    path: "/api/v1/trade/costs/",
    permission: "trade.cost.manage",
    columns: [
      ["shipment", "出运批次"],
      ["cost_type", "费用类型"],
      ["base_amount", "本位币金额"],
      ["status", "状态"],
    ],
  },
  {
    key: "forwarder-settlements",
    group: "贸易",
    title: "货代结算",
    subtitle: "代收、费用、到账与差异核对",
    path: "/api/v1/trade/forwarder-settlements/",
    permission: "trade.forwarder_settlement.manage",
    columns: [
      ["settlement_no", "结算单号"],
      ["forwarder", "货代"],
      ["difference_amount", "差异"],
      ["status", "状态"],
    ],
  },
  {
    key: "overseas-warehouses",
    group: "贸易",
    title: "海外仓",
    subtitle: "国内外共用库存核心的海外仓扩展档案",
    path: "/api/v1/trade/overseas-warehouses/",
    permission: "trade.overseas_warehouse.manage",
    columns: [
      ["warehouse", "仓库"],
      ["country_region", "国家/地区"],
      ["external_warehouse_code", "外部编码"],
      ["is_active", "启用"],
    ],
  },
  {
    key: "journals",
    group: "财务",
    title: "会计凭证",
    subtitle: "审核、过账与冲销",
    path: "/api/v1/finance/journals/",
    permission: "finance.journal.manage",
    columns: [
      ["voucher_no", "凭证号"],
      ["entry_date", "日期"],
      ["description", "摘要"],
      ["status", "状态"],
    ],
  },
  {
    key: "account-ledger",
    group: "财务",
    title: "科目明细账",
    subtitle: "期初、发生额、逐笔余额与往来辅助核算",
    path: "/api/v1/finance/ledgers/",
    permission: "finance.ledger.read",
    columns: [],
  },
  {
    key: "open-items",
    group: "财务",
    title: "应收应付",
    subtitle: "账龄、收付款与核销",
    path: "/api/v1/finance/open-items/",
    permission: "finance.arap.manage",
    columns: [
      ["item_no", "往来单号"],
      ["kind", "类型"],
      ["party", "往来单位"],
      ["status", "状态"],
    ],
  },
  {
    key: "costs",
    group: "财务",
    title: "成本中心",
    subtitle: "移动平均与单件成本",
    path: "/api/v1/finance/cost-balances/",
    permission: "finance.cost.read",
    columns: [
      ["sku", "SKU"],
      ["warehouse", "仓库"],
      ["quantity", "成本数量"],
      ["average_unit_cost_base", "平均单位成本"],
    ],
  },
  {
    key: "expenses",
    group: "财务",
    title: "费用报销",
    subtitle: "申请、审批、入账与支付",
    path: "/api/v1/finance/expense-claims/",
    permission: "expense.claim.manage",
    columns: [
      ["claim_no", "报销单号"],
      ["claimant", "申请人"],
      ["base_amount", "本位币金额"],
      ["status", "状态"],
    ],
  },
  {
    key: "assets",
    group: "财务",
    title: "固定资产",
    subtitle: "卡片、折旧与处置",
    path: "/api/v1/finance/fixed-assets/",
    permission: "asset.manage",
    columns: [
      ["asset_no", "资产编号"],
      ["name", "资产名称"],
      ["original_cost", "原值"],
      ["status", "状态"],
    ],
  },
  {
    key: "payroll",
    group: "财务",
    title: "薪资批次",
    subtitle: "计算、复核、计提与发放",
    path: "/api/v1/finance/payroll-runs/",
    permission: "payroll.manage",
    columns: [
      ["run_no", "批次号"],
      ["period", "期间"],
      ["net_amount", "实发金额"],
      ["status", "状态"],
    ],
  },
  {
    key: "tax",
    group: "财务",
    title: "税务发票",
    subtitle: "进销项、核验与入账",
    path: "/api/v1/finance/tax-invoices/",
    permission: "tax.manage",
    columns: [
      ["invoice_no", "发票号码"],
      ["direction", "方向"],
      ["total_amount", "价税合计"],
      ["status", "状态"],
    ],
  },
  {
    key: "approvals",
    group: "协同",
    title: "我的待办",
    subtitle: "审批、拒绝与转交",
    path: "/api/v1/workflow/tasks/",
    permission: "workflow.task.process",
    columns: [
      ["id", "任务"],
      ["instance", "审批实例"],
      ["due_at", "截止时间"],
      ["status", "状态"],
    ],
  },
  {
    key: "documents",
    group: "协同",
    title: "文件中心",
    subtitle: "版本、关联、分享与保留",
    path: "/api/v1/documents/files/",
    permission: "document.file.read",
    columns: [
      ["file_no", "文件编号"],
      ["title", "标题"],
      ["security_level", "密级"],
      ["status", "状态"],
    ],
  },
  {
    key: "integrations",
    group: "系统",
    title: "集成事件",
    subtitle: "同步、重试与死信",
    path: "/api/v1/integrations/events/",
    permission: "integration.payload.read",
    columns: [
      ["event_type", "事件"],
      ["direction", "方向"],
      ["attempts", "尝试次数"],
      ["status", "状态"],
    ],
  },
  {
    key: "integration-monitor",
    group: "系统",
    title: "集成健康监控",
    subtitle: "成功率、延迟、失败与死信趋势",
    path: "/api/v1/integrations/events/monitor/",
    permission: "integration.monitor.read",
    columns: [],
  },
  {
    key: "data-imports",
    group: "系统",
    title: "数据迁移",
    subtitle: "CSV 暂存、逐行校验与原子提交",
    path: "/api/v1/system/data-imports/",
    permission: "system.data_import.manage",
    columns: [
      ["batch_no", "批次号"],
      ["entity_type", "数据类型"],
      ["total_rows", "总行数"],
      ["status", "状态"],
    ],
  },
  {
    key: "companies",
    group: "系统",
    title: "公司与账套",
    subtitle: "法律主体、本位币、时区与状态",
    path: "/api/v1/master-data/companies/",
    permission: "system.company.manage",
    columns: [
      ["company_code", "公司编码"],
      ["legal_name", "法定名称"],
      ["base_currency", "本位币"],
      ["status", "状态"],
    ],
  },
  {
    key: "dictionary-types",
    group: "系统",
    title: "业务字典",
    subtitle: "公司级枚举、层级选项与扩展参数",
    path: "/api/v1/system/dictionary-types/",
    permission: "system.config.manage",
    columns: [
      ["dictionary_code", "字典编码"],
      ["name", "名称"],
      ["company", "公司"],
      ["is_active", "启用"],
    ],
  },
  {
    key: "number-rules",
    group: "系统",
    title: "编号规则",
    subtitle: "前缀、日期、流水长度与重置周期",
    path: "/api/v1/system/number-rules/",
    permission: "system.config.manage",
    columns: [
      ["rule_code", "规则编码"],
      ["name", "名称"],
      ["reset_period", "重置周期"],
      ["is_active", "启用"],
    ],
  },
  {
    key: "background-jobs",
    group: "系统",
    title: "任务监控",
    subtitle: "队列、执行、重试与死信",
    path: "/api/v1/system/jobs/",
    permission: "system.job.manage",
    columns: [
      ["task_name", "任务"],
      ["queue", "队列"],
      ["attempts", "尝试次数"],
      ["status", "状态"],
    ],
  },
  {
    key: "outbox-events",
    group: "系统",
    title: "事件投递",
    subtitle: "事务 Outbox、失败原因与人工补偿",
    path: "/api/v1/system/outbox-events/",
    permission: "system.job.manage",
    columns: [
      ["event_type", "事件"],
      ["aggregate_type", "聚合类型"],
      ["attempts", "尝试次数"],
      ["status", "状态"],
    ],
  },
  {
    key: "users",
    group: "系统",
    title: "用户管理",
    subtitle: "账号、组织归属、登录失败与锁定状态",
    path: "/api/v1/auth/users/",
    permission: "auth.user.manage",
    columns: [
      ["username", "登录名"],
      ["display_name", "姓名"],
      ["employee_no", "工号"],
      ["status", "状态"],
      ["failed_login_attempts", "密码错误次数"],
      ["locked_reason", "锁定原因"],
    ],
  },
  {
    key: "roles",
    group: "系统",
    title: "角色权限",
    subtitle: "角色与原子权限集合",
    path: "/api/v1/auth/roles/",
    permission: "auth.role.manage",
    columns: [
      ["role_code", "角色编码"],
      ["name", "角色名称"],
      ["company", "公司"],
      ["is_active", "启用"],
    ],
  },
  {
    key: "permission-overrides",
    group: "系统",
    title: "临时授权",
    subtitle: "用户级允许/拒绝、双人审批与撤销",
    path: "/api/v1/auth/overrides/",
    permission: "auth.override.manage",
    columns: [
      ["user", "用户"],
      ["permission", "原子权限"],
      ["effect", "效果"],
      ["approval_status", "审批状态"],
    ],
  },
  {
    key: "audit-events",
    group: "系统",
    title: "审计日志",
    subtitle: "关键操作、对象与变更留痕",
    path: "/api/v1/auth/audit-events/",
    permission: "audit.log.read",
    columns: [
      ["occurred_at", "发生时间"],
      ["actor", "操作人"],
      ["action", "动作"],
      ["object_type", "对象类型"],
    ],
  },
];
const forms: Record<string, Field[]> = {
  sales: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "order_no", label: "订单号", required: true },
    { name: "customer", label: "客户 ID", type: "number", required: true },
    { name: "channel", label: "渠道 ID", type: "number", required: true },
    {
      name: "shipping_address",
      label: "收货地址 ID",
      type: "number",
      required: true,
    },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    {
      name: "order_date",
      label: "订单时间",
      type: "datetime-local",
      required: true,
    },
    {
      name: "lines",
      label: "订单明细（line_no、sku、ordered_qty）",
      type: "json",
      required: true,
    },
  ],
  aftersales: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "case_no", label: "售后单号", required: true },
    {
      name: "case_type",
      label: "售后类型",
      type: "select",
      required: true,
      options: [
        ["return", "退货"],
        ["refund", "退款"],
        ["exchange", "换货"],
        ["reship", "补发"],
        ["discount", "折让"],
        ["claim", "索赔"],
      ],
    },
    {
      name: "sales_order",
      label: "销售订单 ID",
      type: "number",
      required: true,
    },
    { name: "customer", label: "客户 ID", type: "number", required: true },
    { name: "reason_code", label: "原因代码", required: true },
    { name: "reason_detail", label: "原因说明", required: true },
    {
      name: "lines",
      label: "售后明细（sales_order_line、requested_qty）",
      type: "json",
      required: true,
    },
  ],
  purchasing: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "purchase_order_no", label: "采购单号", required: true },
    { name: "supplier", label: "供应商 ID", type: "number", required: true },
    { name: "order_date", label: "订单日期", type: "date", required: true },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    { name: "exchange_rate", label: "汇率", type: "number", required: true },
    { name: "warehouse", label: "收货仓 ID", type: "number", required: true },
    {
      name: "expected_delivery_date",
      label: "预计交期",
      type: "date",
      required: true,
    },
    {
      name: "lines",
      label:
        "采购明细（line_no、sku、ordered_qty、unit_price、tax_rate、expected_delivery_date）",
      type: "json",
      required: true,
    },
  ],
  production: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "production_order_no", label: "生产单号", required: true },
    {
      name: "product_sku",
      label: "成品 SKU ID",
      type: "number",
      required: true,
    },
    { name: "bom", label: "BOM ID", type: "number", required: true },
    { name: "planned_qty", label: "计划数量", type: "number", required: true },
    { name: "warehouse", label: "生产仓 ID", type: "number", required: true },
    {
      name: "planned_start",
      label: "计划开始",
      type: "datetime-local",
      required: true,
    },
    {
      name: "planned_end",
      label: "计划结束",
      type: "datetime-local",
      required: true,
    },
    { name: "source_type", label: "来源类型" },
    { name: "source_id", label: "来源 ID" },
  ],
  prepack: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "prepack_order_no", label: "预包装任务号", required: true },
    { name: "warehouse", label: "仓库 ID", type: "number", required: true },
    {
      name: "product_sku",
      label: "产品 SKU ID",
      type: "number",
      required: true,
    },
    {
      name: "packaging_plan",
      label: "包装方案 ID",
      type: "number",
      required: true,
    },
    { name: "planned_qty", label: "计划数量", type: "number", required: true },
    {
      name: "source_location",
      label: "来源库位 ID",
      type: "number",
      required: true,
    },
    {
      name: "target_location",
      label: "目标库位 ID",
      type: "number",
      required: true,
    },
  ],
  products: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "sku_code", label: "SKU 编码", required: true },
    { name: "spu", label: "SPU ID", type: "number", required: true },
    { name: "name_zh", label: "中文名称", required: true },
    { name: "name_en", label: "英文名称" },
    { name: "base_uom", label: "基本单位 ID", type: "number", required: true },
    { name: "is_serialized", label: "单件追踪", type: "checkbox" },
    { name: "is_limited_edition", label: "限量产品", type: "checkbox" },
    { name: "is_lot_tracked", label: "批次追踪", type: "checkbox" },
    { name: "allow_oversell", label: "允许超卖", type: "checkbox" },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["draft", "草稿"],
        ["active", "启用"],
        ["inactive", "停用"],
        ["discontinued", "终止"],
      ],
    },
  ],
  parties: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "party_no", label: "客商编码", required: true },
    {
      name: "party_type",
      label: "类型",
      type: "select",
      required: true,
      options: [
        ["organization", "组织"],
        ["person", "个人"],
      ],
    },
    { name: "legal_name", label: "法定名称", required: true },
    { name: "display_name", label: "显示名称", required: true },
    { name: "country_region", label: "国家/地区 ID", type: "number" },
    { name: "default_language", label: "默认语言" },
    { name: "default_currency", label: "默认币种 ID", type: "number" },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["draft", "草稿"],
        ["active", "启用"],
        ["suspended", "暂停"],
        ["inactive", "停用"],
      ],
    },
    { name: "risk_level", label: "风险等级" },
  ],
  "party-merges": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "canonical_party", label: "保留客商 ID", type: "number", required: true },
    { name: "duplicate_party", label: "重复客商 ID", type: "number", required: true },
    { name: "match_score", label: "匹配度（0-1）", type: "number", required: true },
    { name: "match_reasons", label: "匹配原因数组", type: "json", required: true },
  ],
  warehouses: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "warehouse_code", label: "仓库编码", required: true },
    { name: "name", label: "仓库名称", required: true },
    { name: "timezone", label: "时区", required: true },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["active", "启用"],
        ["inactive", "停用"],
      ],
    },
  ],
  "warehouse-tasks": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "warehouse", label: "仓库 ID", type: "number", required: true },
    { name: "task_no", label: "任务号", required: true },
    {
      name: "task_type",
      label: "任务类型",
      type: "select",
      required: true,
      options: [
        ["putaway", "上架"],
        ["pick", "拣货"],
        ["pack", "打包复核"],
      ],
    },
    { name: "goods_receipt", label: "收货单 ID（上架）", type: "number" },
    { name: "sales_shipment", label: "发货单 ID（拣货/复核）", type: "number" },
    { name: "wave_no", label: "波次号" },
    { name: "assigned_to", label: "执行人 ID", type: "number" },
    {
      name: "lines",
      label: "任务行（line_no、sku、source_balance/target_location 或 sales_shipment_line、planned_qty）",
      type: "json",
      required: true,
    },
  ],
  "price-lists": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "price_list_no", label: "价格表编号", required: true },
    { name: "name", label: "名称", required: true },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    { name: "channel", label: "渠道 ID", type: "number" },
    { name: "customer_type", label: "客户类型" },
    {
      name: "tax_mode",
      label: "计税模式",
      type: "select",
      required: true,
      options: [
        ["tax_included", "含税"],
        ["tax_excluded", "未税"],
      ],
    },
    {
      name: "valid_from",
      label: "生效时间",
      type: "datetime-local",
      required: true,
    },
    { name: "valid_to", label: "失效时间", type: "datetime-local" },
    { name: "priority", label: "优先级", type: "number" },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["draft", "草稿"],
        ["approved", "已批准"],
        ["active", "启用"],
        ["disabled", "停用"],
      ],
    },
  ],
  expenses: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "claim_no", label: "报销单号", required: true },
    { name: "claimant", label: "申请人 ID", type: "number", required: true },
    { name: "expense_date", label: "费用日期", type: "date", required: true },
    { name: "description", label: "费用说明", required: true },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    { name: "exchange_rate", label: "汇率", type: "number", required: true },
    { name: "amount", label: "原币金额", type: "number", required: true },
    {
      name: "base_amount",
      label: "本位币金额",
      type: "number",
      required: true,
    },
    { name: "cost_center", label: "成本中心" },
    { name: "journal", label: "凭证 ID", type: "number" },
  ],
  assets: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "asset_no", label: "资产编号", required: true },
    { name: "name", label: "资产名称", required: true },
    { name: "category", label: "资产类别", required: true },
    {
      name: "acquisition_date",
      label: "购置日期",
      type: "date",
      required: true,
    },
    {
      name: "in_service_date",
      label: "启用日期",
      type: "date",
      required: true,
    },
    {
      name: "original_cost",
      label: "资产原值",
      type: "number",
      required: true,
    },
    { name: "residual_value", label: "残值", type: "number", required: true },
    {
      name: "useful_life_months",
      label: "使用月数",
      type: "number",
      required: true,
    },
    { name: "location", label: "存放位置" },
    { name: "custodian", label: "保管人 ID", type: "number" },
  ],
  payroll: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "run_no", label: "薪资批次号", required: true },
    { name: "period", label: "会计期间 ID", type: "number", required: true },
    { name: "journal", label: "计提凭证 ID", type: "number" },
    { name: "lines", label: "薪资明细", type: "json", required: true },
  ],
  tax: [
    { name: "company", label: "公司 ID", type: "number", required: true },
    {
      name: "direction",
      label: "进销项",
      type: "select",
      required: true,
      options: [
        ["input", "进项"],
        ["output", "销项"],
      ],
    },
    { name: "invoice_code", label: "发票代码" },
    { name: "invoice_no", label: "发票号码", required: true },
    { name: "party", label: "往来单位 ID", type: "number", required: true },
    { name: "issue_date", label: "开票日期", type: "date", required: true },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    {
      name: "amount_excluding_tax",
      label: "未税金额",
      type: "number",
      required: true,
    },
    { name: "tax_amount", label: "税额", type: "number", required: true },
    { name: "total_amount", label: "价税合计", type: "number", required: true },
    { name: "tax_detail", label: "税额明细", type: "json", required: true },
    { name: "journal", label: "凭证 ID", type: "number" },
  ],
  users: [
    { name: "username", label: "登录名", required: true },
    { name: "password", label: "初始密码（至少 8 位）" },
    { name: "display_name", label: "姓名", required: true },
    { name: "employee_no", label: "工号" },
    { name: "email", label: "邮箱" },
    { name: "company", label: "公司 ID", type: "number" },
    { name: "department", label: "部门 ID", type: "number" },
    { name: "position", label: "岗位 ID", type: "number" },
    { name: "mobile", label: "手机" },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["invited", "待激活"],
        ["active", "正常"],
        ["locked", "锁定"],
        ["disabled", "停用"],
      ],
    },
    { name: "is_active", label: "允许登录", type: "checkbox" },
  ],
  roles: [
    { name: "company", label: "公司 ID（留空为全局）", type: "number" },
    { name: "role_code", label: "角色编码", required: true },
    { name: "name", label: "角色名称", required: true },
    {
      name: "permission_ids",
      label: "原子权限 ID 数组",
      type: "json",
    },
    { name: "is_active", label: "启用", type: "checkbox" },
  ],
  "permission-overrides": [
    { name: "user", label: "用户 ID", type: "number", required: true },
    {
      name: "permission",
      label: "原子权限 ID",
      type: "number",
      required: true,
    },
    {
      name: "effect",
      label: "授权效果",
      type: "select",
      required: true,
      options: [
        ["allow", "允许"],
        ["deny", "拒绝"],
      ],
    },
    { name: "data_scope_type", label: "数据范围类型" },
    { name: "data_scope_value", label: "数据范围值", type: "json" },
    {
      name: "starts_at",
      label: "生效时间",
      type: "datetime-local",
      required: true,
    },
    { name: "expires_at", label: "失效时间", type: "datetime-local" },
    { name: "reason", label: "申请原因", required: true },
  ],
  companies: [
    { name: "company_code", label: "公司编码", required: true },
    { name: "legal_name", label: "法定名称", required: true },
    { name: "display_name", label: "显示名称", required: true },
    { name: "base_currency", label: "本位币 ID", type: "number", required: true },
    { name: "registered_region", label: "注册地区 ID", type: "number" },
    { name: "timezone", label: "时区", required: true },
    {
      name: "status",
      label: "状态",
      type: "select",
      options: [
        ["active", "启用"],
        ["inactive", "停用"],
      ],
    },
  ],
  "dictionary-types": [
    { name: "company", label: "公司 ID（超级管理员可留空）", type: "number" },
    { name: "dictionary_code", label: "字典编码", required: true },
    { name: "name", label: "名称", required: true },
    { name: "description", label: "说明" },
    { name: "is_system", label: "系统字典", type: "checkbox" },
    { name: "is_active", label: "启用", type: "checkbox" },
  ],
  "number-rules": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "rule_code", label: "规则编码", required: true },
    { name: "name", label: "名称", required: true },
    { name: "prefix_template", label: "前缀模板" },
    { name: "date_format", label: "日期格式" },
    { name: "separator", label: "分隔符" },
    { name: "sequence_length", label: "流水长度", type: "number", required: true },
    {
      name: "reset_period",
      label: "重置周期",
      type: "select",
      options: [
        ["never", "不重置"],
        ["year", "每年"],
        ["month", "每月"],
        ["day", "每日"],
      ],
    },
    { name: "starts_from", label: "起始值", type: "number", required: true },
    { name: "is_active", label: "启用", type: "checkbox" },
  ],
  "trade-documents": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "shipment", label: "出运批次 ID", type: "number", required: true },
    { name: "document_type", label: "单证类型", required: true },
    { name: "document_no", label: "单证编号", required: true },
    { name: "language", label: "语言", required: true },
    { name: "template_version", label: "模板版本", required: true },
    { name: "snapshot", label: "单证数据快照", type: "json", required: true },
  ],
  "customs-declarations": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "shipment", label: "出运批次 ID", type: "number", required: true },
    { name: "declaration_no", label: "报关单号" },
    { name: "customs_office", label: "申报海关", required: true },
    { name: "declaration_mode", label: "申报模式", required: true },
    { name: "declaration_date", label: "申报日期", type: "date" },
    { name: "declaration_currency", label: "申报币种 ID", type: "number", required: true },
    { name: "declared_amount", label: "申报金额", type: "number", required: true },
    { name: "item_snapshot", label: "申报明细快照", type: "json", required: true },
    { name: "rebate_status", label: "退税状态" },
    { name: "rebate_reference", label: "退税引用" },
  ],
  "trade-costs": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "shipment", label: "出运批次 ID", type: "number", required: true },
    { name: "cost_type", label: "费用类型", required: true },
    { name: "service_party", label: "服务商 ID", type: "number" },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    { name: "amount", label: "原币金额", type: "number", required: true },
    { name: "exchange_rate", label: "汇率", type: "number", required: true },
    { name: "base_amount", label: "本位币金额", type: "number", required: true },
    { name: "allocation_basis", label: "分摊依据", required: true },
    { name: "allocation_snapshot", label: "分摊快照", type: "json", required: true },
    { name: "external_reference", label: "外部引用" },
  ],
  "forwarder-settlements": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "settlement_no", label: "结算单号", required: true },
    { name: "forwarder", label: "货代 ID", type: "number", required: true },
    { name: "period_start", label: "期间开始", type: "date", required: true },
    { name: "period_end", label: "期间结束", type: "date", required: true },
    { name: "currency", label: "币种 ID", type: "number", required: true },
    { name: "receivable_amount", label: "代收金额", type: "number", required: true },
    { name: "fee_amount", label: "费用金额", type: "number", required: true },
    { name: "received_amount", label: "到账金额", type: "number", required: true },
    { name: "detail_snapshot", label: "结算明细", type: "json", required: true },
  ],
  "overseas-warehouses": [
    { name: "company", label: "公司 ID", type: "number", required: true },
    { name: "warehouse", label: "内部仓库 ID", type: "number", required: true },
    { name: "country_region", label: "国家/地区 ID", type: "number", required: true },
    { name: "operator", label: "运营商 ID", type: "number" },
    { name: "external_warehouse_code", label: "外部仓编码" },
    { name: "customs_mode", label: "海关模式" },
    { name: "is_active", label: "启用", type: "checkbox" },
  ],
};
const createOnly = new Set([
  "sales",
  "aftersales",
  "purchasing",
  "payroll",
  "permission-overrides",
  "party-merges",
]);
const labels: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  approved: "已批准",
  active: "有效",
  pending: "待处理",
  processing: "处理中",
  completed: "已完成",
  cancelled: "已取消",
  posted: "已过账",
  reversed: "已冲销",
  dispatched: "已交运",
  in_transit: "在途",
  receivable: "应收",
  payable: "应付",
  return: "退货",
  refund: "退款",
};
const can = (user: CurrentUser, permission: string) =>
  user.is_superuser || user.permissions.includes(permission);
function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return `${value.length} 项`;
  if (typeof value === "object") return "结构化数据";
  return labels[String(value)] || String(value);
}

function BrandLogo({ appearance, compact = false }: { appearance: Appearance; compact?: boolean }) {
  return appearance.logoUrl ? (
    <span className={`brand-logo-image ${compact ? "compact" : ""}`}>
      <img src={appearance.logoUrl} alt={`${appearance.appName} Logo`} />
    </span>
  ) : (
    <span className={compact ? "logo-fallback compact" : "logo-fallback"}>
      {appearance.appName.trim()[0]?.toUpperCase() || "K"}
    </span>
  );
}

function Login({ onLogin, appearance }: { onLogin: (user: CurrentUser) => void; appearance: Appearance }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [captcha, setCaptcha] = useState("");
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaNonce, setCaptchaNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const refreshCaptcha = () => {
    setCaptcha("");
    setCaptchaNonce((value) => value + 1);
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await login(username, password, captcha));
    } catch (reason) {
      if (reason instanceof ApiError && reason.body.captcha_required) {
        setCaptchaRequired(true);
        refreshCaptcha();
      }
      setError(reason instanceof Error ? reason.message : "登录失败。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main
      className={`login-shell ${appearance.loginBackground ? "custom-background" : ""}`}
      style={appearance.loginBackground ? { backgroundImage: `linear-gradient(145deg, #071811aa, #10251a88), url("${appearance.loginBackground.replaceAll('"', '%22')}")` } : undefined}
    >
      <section
        className="brand-panel"
      >
        {(appearance.loginSlogan || appearance.loginSlogan1) && <h1>{appearance.loginSlogan}{appearance.loginSlogan && appearance.loginSlogan1 && <br />}{appearance.loginSlogan1}</h1>}
        {appearance.loginSlogan2 && <p>{appearance.loginSlogan2}</p>}
      </section>
      <section className="login-panel">
        <form className="login-card" style={{ backgroundColor: `rgba(255, 255, 255, ${appearance.loginCardOpacity / 100})` }} onSubmit={submit}>
          <div className="login-card-logo"><BrandLogo appearance={appearance} /></div>
          <h2>{appearance.appName}</h2>
          <label>
            用户名
            <input
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {captchaRequired && (
            <label>
              图片验证码
              <span className="captcha-row">
                <input
                  autoComplete="off"
                  value={captcha}
                  onChange={(e) => setCaptcha(e.target.value.toUpperCase())}
                  maxLength={5}
                  required
                />
                <button className="captcha-image-button" type="button" onClick={refreshCaptcha} title="点击更换验证码">
                  <img src={`/api/v1/auth/captcha/?v=${captchaNonce}`} alt="图片验证码，点击更换" />
                </button>
              </span>
            </label>
          )}
          {error && <div className="error-message">{error}</div>}
          <button className="login-submit" disabled={busy}>登录</button>
        </form>
      </section>
      {(appearance.loginFooterText || appearance.loginFooterLinks.length > 0) && (
        <footer className="login-footer" tabIndex={0}>
          <div className="login-footer-handle">{appearance.loginFooterText || "更多信息"}</div>
          {appearance.loginFooterLinks.length > 0 && (
            <div className="login-footer-links" role="navigation" aria-label="登录页相关链接">
              {appearance.loginFooterLinks.map((link, index) => (
                <a href={link.url} key={`${link.url}-${index}`} target="_blank" rel="noreferrer">{link.label}</a>
              ))}
            </div>
          )}
        </footer>
      )}
    </main>
  );
}

function Dashboard({ user }: { user: CurrentUser }) {
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  useEffect(() => {
    getDashboard()
      .then(setMetrics)
      .catch(() => undefined);
  }, []);
  const cards: [string, string][] = [
    ["sales_orders", "销售订单"],
    ["open_supply_demands", "供应缺口"],
    ["production_in_progress", "生产进行中"],
    ["shipments_in_transit", "运输途中"],
    ["pending_journals", "待过账凭证"],
    ["open_aftersales", "售后处理中"],
  ];
  return (
    <>
      <div className="hero">
        <div>
          <p className="eyebrow">OPERATIONS OVERVIEW</p>
          <h2>{user.display_name || user.username}，欢迎回来</h2>
          <p>今天需要关注的跨模块业务状态汇总。</p>
        </div>
        <div className="hero-date">
          {new Intl.DateTimeFormat("zh-CN", { dateStyle: "full" }).format(
            new Date(),
          )}
        </div>
      </div>
      <section className="metrics">
        {cards.map(([key, title]) => (
          <article key={key}>
            <span>{title}</span>
            <strong>{metrics[key] ?? "—"}</strong>
            <small>实时业务口径</small>
          </article>
        ))}
      </section>
      <section className="table-card">
        <div className="section-title">
          <div>
            <p className="eyebrow">QUICK ACCESS</p>
            <h2>常用工作入口</h2>
          </div>
        </div>
        <div className="quick-grid">
          {specs
            .filter((item) => can(user, item.permission))
            .slice(0, 8)
            .map((item) => (
              <a key={item.key} href={`#${item.key}`}>
                <strong>{item.title}</strong>
                <span>{item.subtitle}</span>
              </a>
            ))}
        </div>
      </section>
    </>
  );
}

function DataImports() {
  const [rows, setRows] = useState<Entity[]>([]);
  const [entityType, setEntityType] = useState("party");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    listEntities("/api/v1/system/data-imports/")
      .then(setRows)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "读取失败"),
      );
  }, []);
  useEffect(load, [load]);
  async function stage(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await postAction("/api/v1/system/data-imports/stage/", {
        entity_type: entityType,
        filename: file.name,
        csv_content: await file.text(),
      });
      setFile(null);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂存失败");
    } finally {
      setBusy(false);
    }
  }
  async function run(row: Entity, action: "validate" | "commit") {
    setError("");
    try {
      await postAction(`/api/v1/system/data-imports/${row.id}/${action}/`);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "批次处理失败");
    }
  }
  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">SYSTEM</p>
          <h2>数据迁移</h2>
          <p>先暂存和校验，全部有效后才能原子写入业务表。</p>
        </div>
      </section>
      {error && <div className="error-message page-error">{error}</div>}
      <section className="table-card import-card">
        <form className="import-form" onSubmit={stage}>
          <label>
            数据类型
            <select
              value={entityType}
              onChange={(event) => setEntityType(event.target.value)}
            >
              <option value="party">客户与供应商</option>
              <option value="sku">SKU</option>
              <option value="opening_inventory">期初库存</option>
            </select>
          </label>
          <label>
            UTF-8 CSV 文件
            <input
              type="file"
              accept=".csv,text/csv"
              required
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          <button disabled={busy || !file}>
            {busy ? "正在暂存…" : "上传并暂存"}
          </button>
        </form>
        <div className="table-wrap">
          <table>
            <thead><tr><th>批次号</th><th>类型</th><th>有效/无效/总数</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{show(row.batch_no)}</td><td>{show(row.entity_type)}</td>
                  <td>{show(row.valid_rows)} / {show(row.invalid_rows)} / {show(row.total_rows)}</td>
                  <td><span className={`status status-${row.status}`}>{show(row.status)}</span></td>
                  <td>
                    {["staged", "invalid"].includes(String(row.status)) && <button className="text-button" onClick={() => run(row, "validate")}>重新校验</button>}
                    {row.status === "validated" && <button className="text-button positive" onClick={() => run(row, "commit")}>确认提交</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Editor({
  spec,
  fields,
  current,
  user,
  onClose,
  onSaved,
}: {
  spec: Spec;
  fields: Field[];
  current: Entity | null;
  user: CurrentUser;
  onClose: () => void;
  onSaved: () => void;
}) {
  function initialValue(field: Field): unknown {
    const existing = current?.[field.name];
    if (existing !== null && existing !== undefined) {
      if (field.type === "datetime-local" && typeof existing === "string")
        return existing.slice(0, 16);
      if (field.type === "json" && typeof existing !== "string")
        return JSON.stringify(existing, null, 2);
      return existing;
    }
    if (field.name === "company" && user.company_id) return user.company_id;
    if (field.type === "checkbox") return false;
    if (field.type === "json") return "[]";
    return "";
  }
  const initial = Object.fromEntries(
    fields.map((field) => [field.name, initialValue(field)]),
  );
  const [values, setValues] = useState<Record<string, unknown>>(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  function payload() {
    const result: Record<string, unknown> = {};
    for (const field of fields) {
      const value = values[field.name];
      if (value === "" && !field.required) {
        result[field.name] = ["number", "date", "datetime-local"].includes(
          field.type || "",
        )
          ? null
          : "";
        continue;
      }
      if (field.type === "number") result[field.name] = Number(value);
      else if (field.type === "json")
        result[field.name] =
          typeof value === "string" ? JSON.parse(value) : value;
      else result[field.name] = value;
    }
    return result;
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = payload();
      if (current) await updateEntity(spec.path, current.id, body);
      else await createEntity(spec.path, body);
      onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "保存失败，请检查字段。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer editor"
        onClick={(event) => event.stopPropagation()}
      >
        <button className="drawer-close" onClick={onClose}>
          ×
        </button>
        <p className="eyebrow">{current ? "EDIT RECORD" : "CREATE RECORD"}</p>
        <h2>
          {current ? `编辑${spec.title} #${current.id}` : `新增${spec.title}`}
        </h2>
        <form className="record-form" onSubmit={save}>
          {fields.map((field) => (
            <label key={field.name}>
              {field.label}
              {field.type === "checkbox" ? (
                <input
                  type="checkbox"
                  checked={Boolean(values[field.name])}
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.checked })
                  }
                />
              ) : field.type === "select" ? (
                <select
                  required={field.required}
                  value={String(values[field.name] ?? "")}
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.value })
                  }
                >
                  <option value="">请选择</option>
                  {field.options?.map(([value, label]) => (
                    <option value={value} key={value}>
                      {label}
                    </option>
                  ))}
                </select>
              ) : field.type === "json" ? (
                <textarea
                  required={field.required}
                  rows={7}
                  value={
                    typeof values[field.name] === "string"
                      ? String(values[field.name])
                      : JSON.stringify(values[field.name], null, 2)
                  }
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.value })
                  }
                />
              ) : (
                <input
                  type={field.type || "text"}
                  step={field.type === "number" ? "any" : undefined}
                  disabled={field.name === "company" && user.company_id !== null}
                  required={field.required}
                  value={String(values[field.name] ?? "")}
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.value })
                  }
                />
              )}
            </label>
          ))}
          {error && <div className="error-message">{error}</div>}
          <div className="form-actions">
            <button type="button" className="ghost" onClick={onClose}>
              取消
            </button>
            <button disabled={busy}>{busy ? "正在保存…" : "保存"}</button>
          </div>
        </form>
      </aside>
    </div>
  );
}

function Resource({ spec, user }: { spec: Spec; user: CurrentUser }) {
  const [rows, setRows] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Entity | null>(null);
  const [editing, setEditing] = useState<Entity | null | false>(false);
  const editableFields = forms[spec.key];
  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listEntities(spec.path)
      .then(setRows)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "加载失败"),
      )
      .finally(() => setLoading(false));
  }, [spec.path]);
  useEffect(load, [load]);
  const visible = useMemo(
    () =>
      rows.filter((row) =>
        JSON.stringify(row).toLowerCase().includes(query.toLowerCase()),
      ),
    [rows, query],
  );
  async function decide(row: Entity, decision: string) {
    if (
      !window.confirm(
        decision === "approved"
          ? "确认通过此审批任务？"
          : "确认拒绝此审批任务？",
      )
    )
      return;
    try {
      await postAction(`/api/v1/workflow/tasks/${row.id}/decide/`, {
        decision,
        comment: "前端工作台处理",
      });
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "处理失败");
    }
  }
  async function businessAction(
    row: Entity,
    action: string,
    body: Record<string, unknown> = {},
  ) {
    try {
      await postAction(`${spec.path}${row.id}/${action}/`, body);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "业务操作失败");
    }
  }
  async function previewDocument(row: Entity) {
    try {
      const preview = await request<{ preview_url: string }>(
        `${spec.path}${row.id}/preview/`,
      );
      window.open(preview.preview_url, "_blank", "noopener,noreferrer");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "文件预览失败");
    }
  }
  async function detectPartyDuplicates() {
    const companyId = user.company_id ?? Number(window.prompt("请输入需要扫描的公司 ID："));
    if (!companyId) return;
    try {
      await postAction(`${spec.path}detect/`, { company_id: companyId });
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "查重失败");
    }
  }
  function rowActions(row: Entity) {
    if (spec.key === "documents")
      return (
        <>
          <button className="text-button" onClick={() => previewDocument(row)}>预览</button>
          {row.status === "active" && <button className="text-button positive" onClick={() => businessAction(row, "archive")}>归档</button>}
          {["draft", "active", "void", "archived"].includes(String(row.status)) && <button className="text-button danger" onClick={() => businessAction(row, "recycle")}>回收</button>}
          {row.status === "recycled" && <button className="text-button positive" onClick={() => businessAction(row, "restore")}>恢复</button>}
        </>
      );
    if (spec.key === "warehouse-tasks") {
      if (row.status === "draft")
        return <button className="text-button positive" onClick={() => businessAction(row, "release")}>下达任务</button>;
      if (["released", "in_progress"].includes(String(row.status)))
        return (
          <>
            <button
              className="text-button positive"
              onClick={() => {
                const lineId = Number(window.prompt("任务行 ID："));
                const scannedValue = window.prompt("扫描 SKU、条码或单件编号：");
                const quantity = Number(window.prompt("本次数量：", "1"));
                if (lineId && scannedValue && quantity > 0)
                  businessAction(row, "scan", {
                    line_id: lineId,
                    scanned_value: scannedValue,
                    quantity: quantity,
                    idempotency_key: crypto.randomUUID(),
                    occurred_at: new Date().toISOString(),
                  });
              }}
            >
              扫码
            </button>
            <button className="text-button positive" onClick={() => businessAction(row, "complete")}>完成任务</button>
          </>
        );
    }
    if (spec.key === "party-merges" && row.status === "pending")
      return (
        <>
          <button className="text-button positive" onClick={() => businessAction(row, "approve")}>合并</button>
          <button
            className="text-button danger"
            onClick={() => {
              const reason = window.prompt("请输入判定为非重复的原因：");
              if (reason) businessAction(row, "reject", { reason });
            }}
          >
            非重复
          </button>
        </>
      );
    if (spec.key === "trade-documents") {
      if (row.status === "draft")
        return <button className="text-button positive" onClick={() => businessAction(row, "generate")}>生成快照</button>;
      if (row.status === "generated")
        return <button className="text-button positive" onClick={() => businessAction(row, "issue")}>签发</button>;
    }
    const tradeTransitions: Record<string, Record<string, string>> = {
      "customs-declarations": { draft: "submitted", submitted: "cleared", rejected: "draft" },
      "trade-costs": { estimated: "confirmed", confirmed: "settled" },
      "forwarder-settlements": { draft: "confirmed", confirmed: "paid", paid: "reconciled" },
    };
    const tradeTarget = tradeTransitions[spec.key]?.[String(row.status)];
    if (tradeTarget)
      return (
        <button className="text-button positive" onClick={() => businessAction(row, `transition/${tradeTarget}`)}>
          推进状态
        </button>
      );
    if (
      ["background-jobs", "outbox-events"].includes(spec.key) &&
      ["failed", "dead"].includes(String(row.status))
    )
      return (
        <button
          className="text-button positive"
          onClick={() => businessAction(row, "retry")}
        >
          重新排队
        </button>
      );
    if (spec.key === "permission-overrides") {
      if (row.approval_status === "pending")
        return (
          <>
            <button
              className="text-button positive"
              onClick={() => businessAction(row, "approve")}
            >
              批准
            </button>
            <button
              className="text-button danger"
              onClick={() => businessAction(row, "reject")}
            >
              拒绝
            </button>
          </>
        );
      if (row.approval_status === "approved" && !row.revoked_at)
        return (
          <button
            className="text-button danger"
            onClick={() => businessAction(row, "revoke")}
          >
            撤销
          </button>
        );
    }
    if (spec.key === "expenses") {
      const next: Record<string, string> = {
        draft: "submitted",
        submitted: "approved",
        approved: "posted",
        posted: "paid",
      };
      return next[String(row.status)] ? (
        <button
          className="text-button positive"
          onClick={() =>
            businessAction(row, "transition", {
              target: next[String(row.status)],
            })
          }
        >
          推进状态
        </button>
      ) : null;
    }
    if (spec.key === "assets" && row.status === "draft")
      return (
        <button
          className="text-button positive"
          onClick={() => businessAction(row, "activate")}
        >
          启用
        </button>
      );
    if (spec.key === "payroll") {
      if (row.status === "draft")
        return (
          <button
            className="text-button positive"
            onClick={() => businessAction(row, "calculate")}
          >
            计算
          </button>
        );
      const next: Record<string, string> = {
        calculated: "approved",
        approved: "posted",
        posted: "paid",
      };
      return next[String(row.status)] ? (
        <button
          className="text-button positive"
          onClick={() =>
            businessAction(row, "transition", {
              target: next[String(row.status)],
            })
          }
        >
          推进状态
        </button>
      ) : null;
    }
    if (spec.key === "tax") {
      const next: Record<string, string> = {
        draft: "verified",
        verified: "posted",
      };
      return next[String(row.status)] ? (
        <button
          className="text-button positive"
          onClick={() =>
            businessAction(row, "transition", {
              target: next[String(row.status)],
            })
          }
        >
          推进状态
        </button>
      ) : null;
    }
    return null;
  }
  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">{spec.group.toUpperCase()}</p>
          <h2>{spec.title}</h2>
          <p>{spec.subtitle}</p>
        </div>
        <div className="header-actions">
          {spec.key === "party-merges" && (
            <button onClick={detectPartyDuplicates}>扫描重复档案</button>
          )}
          {editableFields && (
            <button onClick={() => setEditing(null)}>新增记录</button>
          )}
          <button className="ghost" onClick={load}>
            刷新数据
          </button>
        </div>
      </section>
      {error && <div className="error-message page-error">{error}</div>}
      <section className="table-card">
        <div className="toolbar">
          <input
            placeholder="搜索当前列表…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span>{visible.length} 条记录</span>
        </div>
        {loading ? (
          <div className="empty">
            <div className="spinner" />
            正在读取业务数据…
          </div>
        ) : visible.length === 0 ? (
          <div className="empty">暂无可查看数据</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {spec.columns.map(([key, label]) => (
                    <th key={key}>{label}</th>
                  ))}
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.id}>
                    {spec.columns.map(([key]) => (
                      <td key={key}>
                        {key === "status" ? (
                          <span className={`status status-${row[key]}`}>
                            {show(row[key])}
                          </span>
                        ) : (
                          show(row[key])
                        )}
                      </td>
                    ))}
                    <td>
                      <button
                        className="text-button"
                        onClick={() => setSelected(row)}
                      >
                        详情
                      </button>
                      {editableFields && !createOnly.has(spec.key) && (
                        <button
                          className="text-button"
                          onClick={() => setEditing(row)}
                        >
                          编辑
                        </button>
                      )}
                      {spec.key === "approvals" && row.status === "pending" && (
                        <>
                          <button
                            className="text-button positive"
                            onClick={() => decide(row, "approved")}
                          >
                            通过
                          </button>
                          <button
                            className="text-button danger"
                            onClick={() => decide(row, "rejected")}
                          >
                            拒绝
                          </button>
                        </>
                      )}
                      {rowActions(row)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {selected && (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <button className="drawer-close" onClick={() => setSelected(null)}>
              ×
            </button>
            <p className="eyebrow">RECORD DETAIL</p>
            <h2>
              {spec.title} #{selected.id}
            </h2>
            <dl>
              {Object.entries(selected)
                .filter(
                  ([key]) => !["id", "created_at", "updated_at"].includes(key),
                )
                .map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>
                      {typeof value === "object" ? (
                        <pre>{JSON.stringify(value, null, 2)}</pre>
                      ) : (
                        show(value)
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
          </aside>
        </div>
      )}
      {editing !== false && editableFields && (
        <Editor
          spec={spec}
          fields={editableFields}
          current={editing}
          user={user}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            load();
          }}
        />
      )}
    </>
  );
}

type LedgerResult = {
  account_code: string;
  account_name: string;
  opening_balance_base: string;
  period_debit_base: string;
  period_credit_base: string;
  closing_balance_base: string;
  rows: Array<Record<string, unknown>>;
};

function AccountLedger() {
  const today = new Date().toISOString().slice(0, 10);
  const [ledgerId, setLedgerId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [startDate, setStartDate] = useState(`${today.slice(0, 8)}01`);
  const [endDate, setEndDate] = useState(today);
  const [result, setResult] = useState<LedgerResult | null>(null);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const query = new URLSearchParams({
      account_id: accountId,
      start_date: startDate,
      end_date: endDate,
    });
    if (partyId) query.set("party_id", partyId);
    try {
      setResult(
        await request<LedgerResult>(
          `/api/v1/finance/ledgers/${ledgerId}/account-ledger/?${query}`,
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "明细账查询失败");
    }
  }
  return (
    <>
      <section className="page-heading"><div><p className="eyebrow">FINANCE</p><h2>科目明细账</h2><p>按账簿、科目、期间和往来单位查询逐笔余额。</p></div></section>
      <section className="table-card">
        <form className="toolbar" onSubmit={submit}>
          <input required type="number" placeholder="账簿 ID" value={ledgerId} onChange={(e) => setLedgerId(e.target.value)} />
          <input required type="number" placeholder="科目 ID" value={accountId} onChange={(e) => setAccountId(e.target.value)} />
          <input type="number" placeholder="往来单位 ID（可选）" value={partyId} onChange={(e) => setPartyId(e.target.value)} />
          <input required type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <input required type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          <button>查询</button>
        </form>
        {error && <div className="error-message page-error">{error}</div>}
        {result && <>
          <div className="toolbar"><strong>{result.account_code} {result.account_name}</strong><span>期初 {result.opening_balance_base} · 本期借 {result.period_debit_base} · 本期贷 {result.period_credit_base} · 期末 {result.closing_balance_base}</span></div>
          <div className="table-wrap"><table><thead><tr><th>日期</th><th>凭证号</th><th>摘要</th><th>往来单位</th><th>借方</th><th>贷方</th><th>余额</th></tr></thead><tbody>
            {result.rows.map((row) => <tr key={String(row.line_id)}><td>{show(row.entry_date)}</td><td>{show(row.voucher_no)}</td><td>{show(row.summary)}</td><td>{show(row.party_name)}</td><td>{show(row.debit_base)}</td><td>{show(row.credit_base)}</td><td>{show(row.running_balance_base)}</td></tr>)}
          </tbody></table></div>
        </>}
      </section>
    </>
  );
}

type MonitorResult = {
  total: number;
  success_rate: number | null;
  average_latency_ms: number | null;
  status_counts: Record<string, number>;
  by_event_type: Record<string, { total: number; succeeded: number; failed: number }>;
};

function IntegrationMonitor() {
  const [hours, setHours] = useState("24");
  const [data, setData] = useState<MonitorResult | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    request<MonitorResult>(`/api/v1/integrations/events/monitor/?hours=${hours}`)
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "监控加载失败"));
  }, [hours]);
  useEffect(load, [load]);
  return <><section className="page-heading"><div><p className="eyebrow">INTEGRATIONS</p><h2>集成健康监控</h2><p>快速定位同步失败、死信与延迟异常。</p></div><div className="header-actions"><input type="number" min="1" max="744" value={hours} onChange={(e) => setHours(e.target.value)} /><button onClick={load}>刷新</button></div></section>
    {error && <div className="error-message page-error">{error}</div>}
    {data && <section className="table-card"><div className="toolbar"><strong>窗口内 {data.total} 个事件</strong><span>成功率 {data.success_rate === null ? "—" : `${(data.success_rate * 100).toFixed(1)}%`} · 平均延迟 {data.average_latency_ms === null ? "—" : `${data.average_latency_ms.toFixed(0)} ms`} · 失败 {data.status_counts.failed || 0} · 死信 {data.status_counts.dead || 0}</span></div><div className="table-wrap"><table><thead><tr><th>事件类型</th><th>总数</th><th>成功</th><th>失败</th></tr></thead><tbody>{Object.entries(data.by_event_type).map(([eventType, row]) => <tr key={eventType}><td>{eventType}</td><td>{row.total}</td><td>{row.succeeded}</td><td>{row.failed}</td></tr>)}</tbody></table></div></section>}
  </>;
}

function PasswordChange({ onClose, forced = false }: { onClose: () => void; forced?: boolean }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await postAction<void>("/api/v1/auth/password/change/", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "密码修改失败。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="drawer-backdrop" onClick={() => { if (!forced) onClose(); }}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        {!forced && <button className="drawer-close" onClick={onClose}>×</button>}
        <p className="eyebrow">ACCOUNT SECURITY</p>
        <h2>{forced ? "首次登录，请修改初始密码" : "修改登录密码"}</h2>
        {forced && <p>初始密码仅用于首次进入系统。新密码至少 8 位，修改完成后才能使用工作台。</p>}
        <form className="editor-form" onSubmit={submit}>
          <label>当前密码<input type="password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
          <label>新密码<input type="password" required minLength={8} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
          <label>确认新密码<input type="password" required minLength={8} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label>
          {error && <div className="error-message">{error}</div>}
          <div className="form-actions">
            {!forced && <button type="button" className="ghost" onClick={onClose}>取消</button>}
            <button disabled={busy}>{busy ? "正在修改…" : "确认修改"}</button>
          </div>
        </form>
      </aside>
    </div>
  );
}

function LoginPortalSettings({ value, onChange, onClose }: { value: Appearance; onChange: (value: Appearance) => void; onClose: () => void }) {
  const [slogan, setSlogan] = useState(value.loginSlogan);
  const [slogan1, setSlogan1] = useState(value.loginSlogan1);
  const [slogan2, setSlogan2] = useState(value.loginSlogan2);
  const [opacity, setOpacity] = useState(value.loginCardOpacity);
  const [footerText, setFooterText] = useState(value.loginFooterText);
  const [footerLinksText, setFooterLinksText] = useState(value.loginFooterLinks.map((link) => `${link.label} | ${link.url}`).join("\n"));
  const [backgroundFile, setBackgroundFile] = useState<File | null>(null);
  const [backgroundSource, setBackgroundSource] = useState<"local" | "bing">(value.backgroundSource);
  const [removeBackground, setRemoveBackground] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    const links: FooterLink[] = [];
    for (const [index, line] of footerLinksText.split("\n").entries()) {
      if (!line.trim()) continue;
      const separator = line.indexOf("|");
      if (separator < 1 || !line.slice(separator + 1).trim()) {
        setError(`底部链接第 ${index + 1} 行格式应为：名称 | 地址`);
        return;
      }
      links.push({ label: line.slice(0, separator).trim(), url: line.slice(separator + 1).trim() });
    }
    setBusy(true);
    setError("");
    try {
      let data = await request<BrandingResponse>("/api/v1/system/branding/", {
        method: "PATCH",
        body: JSON.stringify({ login_slogan: slogan.trim(), login_slogan_1: slogan1.trim(), login_slogan_2: slogan2.trim(), login_card_opacity: opacity, login_footer_text: footerText.trim(), login_footer_links: links, background_source: backgroundSource }),
      });
      if (backgroundSource === "bing") {
        data = await request<BrandingResponse>("/api/v1/system/branding/background/bing/refresh/", { method: "POST" });
      } else if (removeBackground) {
        data = await request<BrandingResponse>("/api/v1/system/branding/assets/background/", { method: "DELETE" });
      } else if (backgroundFile) {
        const body = new FormData();
        body.append("file", backgroundFile);
        data = await request<BrandingResponse>("/api/v1/system/branding/assets/background/", { method: "POST", body });
      }
      onChange(toAppearance(data));
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录门户设置保存失败。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="portal-modal-backdrop" onClick={onClose}>
      <section className="portal-modal" onClick={(event) => event.stopPropagation()}>
        <div className="portal-modal-header"><strong>登录门户设置</strong><button type="button" onClick={onClose}>×</button></div>
        <div className="portal-modal-body">
          <details open>
            <summary>标题和背景</summary>
            <div className="portal-setting-section">
              <label>背景来源<select value={backgroundSource} onChange={(event) => setBackgroundSource(event.target.value as "local" | "bing")}><option value="local">本地上传</option><option value="bing">Bing 每日图片（每天自动更新）</option></select></label>
              <label>Slogan<input maxLength={120} value={slogan} onChange={(event) => setSlogan(event.target.value)} /></label>
              <label>Slogan1<input maxLength={120} value={slogan1} onChange={(event) => setSlogan1(event.target.value)} /></label>
              <label>Slogan2<textarea maxLength={500} value={slogan2} onChange={(event) => setSlogan2(event.target.value)} /></label>
              <div className="portal-background-row">
                {value.loginBackground && !removeBackground ? <div className="portal-background-thumb" style={{ backgroundImage: `url("${value.loginBackground.replaceAll('"', '%22')}")` }} /> : <div className="portal-background-thumb empty">无背景图</div>}
                <label className="file-picker">选择本地图片<input type="file" accept="image/*" onChange={(event) => { setBackgroundFile(event.target.files?.[0] || null); setRemoveBackground(false); setBackgroundSource("local"); }} /></label>
                {value.loginBackground && backgroundSource === "local" && <button type="button" className="ghost" onClick={() => { setRemoveBackground(true); setBackgroundFile(null); }}>移除</button>}
              </div>
              {backgroundSource === "bing" && <small className="bing-background-note">保存时立即拉取 Bing 当日图片，之后每天自动更新并保存到对象存储。{value.bingImageCopyright && ` 当前图片：${value.bingImageTitle || value.bingImageCopyright}${value.bingImageDate ? `（${value.bingImageDate}）` : ""}`}</small>}
            </div>
          </details>
          <details open>
            <summary>登录框</summary>
            <div className="portal-setting-section"><label>透明度：{opacity}%<input type="range" min="55" max="100" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /></label></div>
          </details>
          <details open>
            <summary>信息</summary>
            <div className="portal-setting-section">
              <label>顶部常显文字<input maxLength={300} value={footerText} onChange={(event) => setFooterText(event.target.value)} /></label>
              <label>展开后的链接<textarea value={footerLinksText} onChange={(event) => setFooterLinksText(event.target.value)} placeholder={"显示文字 | https://example.com\n站内页面 | /help"} /><small>每行一个，格式为“显示文字 | 链接地址”。</small></label>
            </div>
          </details>
          {previewing && <div className="portal-preview"><strong>{slogan} {slogan1}</strong><span>{slogan2}</span><i style={{ opacity: opacity / 100 }}>登录框透明度预览</i><small>{footerText}</small></div>}
          {error && <div className="error-message">{error}</div>}
        </div>
        <div className="portal-modal-actions"><button type="button" className="ghost" onClick={() => setPreviewing((shown) => !shown)}>{previewing ? "关闭预览" : "预览"}</button><button type="button" className="ghost" onClick={onClose}>取消</button><button type="button" disabled={busy} onClick={save}>{busy ? "正在保存…" : "保存"}</button></div>
      </section>
    </div>
  );
}

function AppearanceSettings({
  value,
  onChange,
  onClose,
}: {
  value: Appearance;
  onChange: (value: Appearance) => void;
  onClose: () => void;
}) {
  const [appName, setAppName] = useState(value.appName);
  const [versionName, setVersionName] = useState(value.versionName);
  const [theme, setTheme] = useState(value.theme);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [removeLogo, setRemoveLogo] = useState(false);
  const [fontLibrary, setFontLibrary] = useState(value.fontLibrary);
  const [primaryFont, setPrimaryFont] = useState(value.primaryFont ? String(value.primaryFont) : "");
  const [westernFont, setWesternFont] = useState(value.westernFont ? String(value.westernFont) : "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function uploadAsset(kind: "logo", file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<BrandingResponse>(
      `/api/v1/system/branding/assets/${kind}/`,
      { method: "POST", body },
    );
  }
  async function importFonts(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      let data: BrandingResponse | null = null;
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        data = await request<BrandingResponse>("/api/v1/system/branding/fonts/", { method: "POST", body });
      }
      if (data) {
        setFontLibrary(data.font_library);
        onChange(toAppearance(data));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "字体导入失败。");
    } finally {
      setBusy(false);
    }
  }
  async function removeFont(id: number) {
    try {
      const data = await request<BrandingResponse>(`/api/v1/system/branding/fonts/${id}/`, { method: "DELETE" });
      setFontLibrary(data.font_library);
      onChange(toAppearance(data));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "字体删除失败。");
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    const cleanName = appName.trim();
    if (!cleanName) return;
    setBusy(true);
    setError("");
    try {
      let data = await request<BrandingResponse>("/api/v1/system/branding/", {
        method: "PATCH",
        body: JSON.stringify({ app_name: cleanName, version_name: versionName.trim() || "V1.0", theme, primary_font: primaryFont ? Number(primaryFont) : null, western_font: westernFont ? Number(westernFont) : null }),
      });
      if (removeLogo) data = await request<BrandingResponse>("/api/v1/system/branding/assets/logo/", { method: "DELETE" });
      if (logoFile) data = await uploadAsset("logo", logoFile);
      onChange(toAppearance(data));
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "品牌设置保存失败。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer appearance-drawer" onClick={(event) => event.stopPropagation()}>
        <button className="drawer-close" onClick={onClose}>×</button>
        <p className="eyebrow">APPEARANCE & BRAND</p>
        <h2>外观与品牌</h2>
        <p className="settings-note">设置保存在系统中，并对所有登录设备生效。</p>
        <form className="appearance-form" onSubmit={save}>
          <label>
            前端显示名称
            <input required maxLength={40} value={appName} onChange={(event) => setAppName(event.target.value)} />
            <small>用于登录页、侧栏、页眉和浏览器标题。</small>
          </label>
          <label>
            版本名称
            <input required maxLength={30} value={versionName} onChange={(event) => setVersionName(event.target.value)} placeholder="例如 V1.0、2026 夏季版" />
            <small>显示在登录页品牌信息中。</small>
          </label>
          <div className="asset-setting">
            <label className="file-picker">上传品牌 Logo 到对象存储<input type="file" accept="image/*" onChange={(event) => { setLogoFile(event.target.files?.[0] || null); setRemoveLogo(false); }} /></label>
            {logoFile && <small>待上传：{logoFile.name}（{(logoFile.size / 1024 / 1024).toFixed(2)} MB）</small>}
            {value.logoUrl && !removeLogo && <div className="asset-preview logo-preview"><BrandLogo appearance={{ ...value, appName }} /><button type="button" className="text-button danger" onClick={() => { setRemoveLogo(true); setLogoFile(null); }}>解除当前 Logo</button></div>}
          </div>
          {error && <div className="error-message">{error}</div>}
          <fieldset>
            <legend>界面风格</legend>
            <div className="theme-grid">
              {themes.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className={`theme-option ${theme === item.key ? "selected" : ""}`}
                  onClick={() => setTheme(item.key)}
                >
                  <span className="theme-swatches">{item.colors.map((color) => <i key={color} style={{ background: color }} />)}</span>
                  <strong>{item.name}</strong>
                  <small>{theme === item.key ? "已选择" : "点击选择"}</small>
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend>显示字体</legend>
            <div className="font-selectors">
              <label>主字体（中文或中西文）<select value={primaryFont} onChange={(event) => setPrimaryFont(event.target.value)}><option value="">系统默认字体</option>{fontLibrary.filter((font) => font.coverage !== "latin_only").map((font) => <option key={font.id} value={font.id}>{font.display_name} · {font.coverage === "combined" ? "中西文" : "仅中文"}</option>)}</select></label>
              <label>西文字体（可选）<select value={westernFont} onChange={(event) => setWesternFont(event.target.value)}><option value="">跟随主字体</option>{fontLibrary.filter((font) => font.latin_supported).map((font) => <option key={font.id} value={font.id}>{font.display_name}</option>)}</select></label>
            </div>
            <div className="asset-setting font-library">
              <label className="file-picker">导入字体到对象存储<input type="file" multiple accept=".ttf,.otf,.woff,.woff2,font/ttf,font/otf,font/woff,font/woff2" disabled={busy} onChange={(event) => importFonts(event.target.files)} /></label>
              <small>系统自动检测中文和西文字符覆盖，不限制文件大小。</small>
              {fontLibrary.map((font) => <div className="font-row" key={font.id}><span style={{ fontFamily: `"kaxi-font-${font.id}"` }}>{font.display_name}</span><small>{font.coverage === "combined" ? `中西文 · ${font.cjk_glyph_count} 中文字形` : font.coverage === "cjk_only" ? `仅中文 · ${font.cjk_glyph_count} 字形` : "仅西文"}</small><button type="button" className="text-button danger" onClick={() => removeFont(font.id)}>删除</button></div>)}
            </div>
          </fieldset>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => { setAppName(DEFAULT_APPEARANCE.appName); setVersionName(DEFAULT_APPEARANCE.versionName); setTheme(DEFAULT_APPEARANCE.theme); setPrimaryFont(""); setWesternFont(""); setRemoveLogo(true); setLogoFile(null); }}>恢复默认</button>
            <button type="button" className="ghost" onClick={onClose}>取消</button>
            <button disabled={busy}>{busy ? "正在保存…" : "保存设置"}</button>
          </div>
        </form>
      </aside>
    </div>
  );
}

function Workspace({
  user,
  onLogout,
  appearance,
  onAppearanceChange,
}: {
  user: CurrentUser;
  onLogout: () => void;
  appearance: Appearance;
  onAppearanceChange: (value: Appearance) => void;
}) {
  const available = specs.filter((item) => can(user, item.permission));
  const [active, setActive] = useState(
    window.location.hash.slice(1) || "dashboard",
  );
  const [changingPassword, setChangingPassword] = useState(false);
  const [changingAppearance, setChangingAppearance] = useState(false);
  const [changingLoginPortal, setChangingLoginPortal] = useState(false);
  useEffect(() => {
    const handler = () =>
      setActive(window.location.hash.slice(1) || "dashboard");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  const groups = [...new Set(available.map((item) => item.group))];
  const spec = available.find((item) => item.key === active);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="logo">
          <BrandLogo appearance={appearance} compact />
          <strong>{appearance.appName}</strong>
        </div>
        <nav>
          <a
            className={active === "dashboard" ? "active" : ""}
            href="#dashboard"
          >
            运营总览
          </a>
          {groups.map((group) => (
            <div className="nav-group" key={group}>
              <small>{group}</small>
              {available
                .filter((item) => item.group === group)
                .map((item) => (
                  <a
                    className={active === item.key ? "active" : ""}
                    href={`#${item.key}`}
                    key={item.key}
                  >
                    {item.title}
                  </a>
                ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="user-avatar">
            {(user.display_name || user.username)[0]}
          </span>
          <div>
            <strong>{user.display_name || user.username}</strong>
            <small>
              {user.is_superuser ? "超级管理员" : `公司 #${user.company_id}`}
            </small>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div className="page-brand-heading">
            <BrandLogo appearance={appearance} compact />
            <div>
            <p className="eyebrow">{appearance.appName} · 企业运营系统</p>
            <h1>{spec?.title || "运营总览"}</h1>
            </div>
          </div>
          <div className="header-actions">
            <span className="connection-dot">系统在线</span>
            {can(user, "system.config.manage") && (
              <><button className="ghost" onClick={() => setChangingLoginPortal(true)}>登录门户</button><button className="ghost" onClick={() => setChangingAppearance(true)}>外观设置</button></>
            )}
            <button className="ghost" onClick={() => setChangingPassword(true)}>
              修改密码
            </button>
            <button className="ghost" onClick={onLogout}>
              退出
            </button>
          </div>
        </header>
        <main className="content">
          {spec ? (
            spec.key === "data-imports" ? (
              <DataImports />
            ) : spec.key === "account-ledger" ? (
              <AccountLedger />
            ) : spec.key === "integration-monitor" ? (
              <IntegrationMonitor />
            ) : (
              <Resource spec={spec} user={user} />
            )
          ) : (
            <Dashboard user={user} />
          )}
        </main>
      </div>
      {(changingPassword || user.must_change_password) && (
        <PasswordChange
          forced={user.must_change_password}
          onClose={() => {
            if (user.must_change_password) window.location.reload();
            else setChangingPassword(false);
          }}
        />
      )}
      {changingAppearance && <AppearanceSettings value={appearance} onChange={onAppearanceChange} onClose={() => setChangingAppearance(false)} />}
      {changingLoginPortal && <LoginPortalSettings value={appearance} onChange={onAppearanceChange} onClose={() => setChangingLoginPortal(false)} />}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined);
  const [fatal, setFatal] = useState("");
  const [appearance, setAppearance] = useState<Appearance>(DEFAULT_APPEARANCE);
  useEffect(() => {
    document.documentElement.dataset.theme = appearance.theme;
    document.title = appearance.appName;
    const styleId = "kaxi-dynamic-fonts";
    let style = document.getElementById(styleId) as HTMLStyleElement | null;
    if (!style) {
      style = document.createElement("style");
      style.id = styleId;
      document.head.appendChild(style);
    }
    style.textContent = appearance.fontLibrary
      .map((font) => `@font-face{font-family:"kaxi-font-${font.id}";src:url("${font.font_url.replaceAll('"', '%22')}");font-display:swap;}`)
      .join("\n");
    const primary = appearance.primaryFont ? `"kaxi-font-${appearance.primaryFont}"` : '"Microsoft YaHei"';
    const western = appearance.westernFont ? `"kaxi-font-${appearance.westernFont}",` : "";
    document.documentElement.style.setProperty("--app-font", `${western}${primary},system-ui,sans-serif`);
  }, [appearance]);
  useEffect(() => {
    Promise.all([
      currentUser(),
      request<BrandingResponse>("/api/v1/system/branding/"),
    ])
      .then(([current, branding]) => {
        setUser(current);
        setAppearance(toAppearance(branding));
      })
      .catch((error) =>
        setFatal(error instanceof Error ? error.message : "系统连接失败。"),
      );
  }, []);
  if (fatal)
    return (
      <main className="center-message">
        <h1>暂时无法连接系统</h1>
        <p>{fatal}</p>
      </main>
    );
  if (user === undefined)
    return (
      <main className="center-message">
        <div className="spinner" />
        <p>正在连接 {appearance.appName}…</p>
      </main>
    );
  if (!user) return <Login onLogin={setUser} appearance={appearance} />;
  if (user.must_change_password)
    return (
      <main className="app-shell">
        <PasswordChange forced onClose={() => window.location.reload()} />
      </main>
    );
  return (
    <Workspace
      user={user}
      appearance={appearance}
      onAppearanceChange={setAppearance}
      onLogout={async () => {
        await logout();
        setUser(null);
      }}
    />
  );
}
