import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type Language = "zh-CN" | "en";

const STORAGE_KEY = "kaxi-language";
const LanguageContext = createContext<Language>("zh-CN");

// Longest phrases must come first. This vocabulary intentionally covers the
// complete ERP shell and its current modules while leaving user-entered data
// (company names, slogans, document content, and so on) untouched.
const TERMS: Array<[string, string]> = [
  ["登录门户设置", "Login portal settings"], ["外观与品牌设置", "Appearance and branding"],
  ["主数据查重合并", "Master data deduplication"], ["集成健康监控", "Integration health monitor"],
  ["登录页背景图片", "Login background image"], ["登录页背景", "Login background"],
  ["登录框透明度", "Login panel opacity"], ["页脚链接", "Footer links"],
  ["页脚信息", "Footer information"], ["欢迎信息", "Welcome message"],
  ["欢迎标题", "Welcome title"], ["标题和背景", "Title and background"],
  ["选择本地图片", "Choose local image"], ["必应每日图片", "Bing daily image"],
  ["立即更新必应背景", "Refresh Bing background now"], ["刷新必应背景", "Refresh Bing background"],
  ["上传自定义字体", "Upload custom font"], ["导入字体", "Import font"],
  ["企业资源管理系统", "Enterprise resource planning system"],
  ["连续密码错误", "Consecutive password failures"], ["账号已锁定", "Account locked"],
  ["管理员才能启用", "Only an administrator can reactivate it"],
  ["没有权限执行此操作", "You do not have permission to perform this action"],
  ["请求失败，请稍后重试", "Request failed. Please try again later"],
  ["密码至少需要 8 位", "Password must contain at least 8 characters"],
  ["两次输入的密码不一致", "The passwords do not match"],
  ["修改初始密码", "Change initial password"], ["修改密码", "Change password"],
  ["当前密码", "Current password"], ["确认新密码", "Confirm new password"], ["新密码", "New password"],
  ["商品与 SKU", "Products and SKUs"], ["客户与供应商", "Customers and suppliers"],
  ["仓库与库位", "Warehouses and locations"], ["价格体系", "Pricing"],
  ["销售订单", "Sales orders"], ["销售售后", "Sales after-sales"],
  ["采购订单", "Purchase orders"], ["采购需求", "Purchase requisitions"],
  ["库存中心", "Inventory center"], ["仓储现场任务", "Warehouse operations"],
  ["生产订单", "Production orders"], ["委外加工", "Subcontracting"], ["预包装", "Prepacking"],
  ["出运批次", "Shipments"], ["贸易单证", "Trade documents"], ["报关与退税", "Customs and tax rebates"],
  ["国际费用", "International costs"], ["货代结算", "Forwarder settlement"], ["海外仓", "Overseas warehouses"],
  ["会计凭证", "Accounting vouchers"], ["科目明细账", "Account ledger"], ["应收应付", "Receivables and payables"],
  ["成本中心", "Cost center"], ["费用报销", "Expense claims"], ["固定资产", "Fixed assets"],
  ["薪资批次", "Payroll runs"], ["税务发票", "Tax invoices"], ["我的待办", "My tasks"],
  ["文件中心", "File center"], ["集成事件", "Integration events"], ["数据迁移", "Data migration"],
  ["公司与账套", "Companies and ledgers"], ["业务字典", "Business dictionaries"],
  ["用户与权限", "Users and permissions"], ["角色与权限", "Roles and permissions"],
  ["审计日志", "Audit log"], ["系统设置", "System settings"], ["登录门户", "Login portal"],
  ["SPU、SKU、状态与追踪属性", "SPU, SKU, status, and traceability attributes"],
  ["统一客商、联系信息与贸易属性", "Unified parties, contacts, and trade attributes"],
  ["重复候选、双人审批、引用迁移与历史保留", "Duplicate candidates, dual approval, reference migration, and history"],
  ["仓库、库区、货架和库位", "Warehouses, zones, shelves, and locations"],
  ["价格表、代理折扣与特殊价格", "Price lists, agent discounts, and special prices"],
  ["订单、定价、授信与履约", "Orders, pricing, credit, and fulfillment"],
  ["退货、退款、换货与补发", "Returns, refunds, exchanges, and reshipments"],
  ["采购、收货与验收", "Purchasing, receiving, and acceptance"],
  ["需求、询价与定标", "Demand, RFQ, and award"],
  ["在手、预留、冻结与可用", "On hand, reserved, frozen, and available"],
  ["上架、波次拣货、扫码与打包复核", "Putaway, wave picking, scanning, and packing review"],
  ["领料、报工、完工与损耗", "Material issue, reporting, completion, and loss"],
  ["委外发料、在外与收回", "Subcontract issue, work in process, and receipt"],
  ["预包装执行与拆包", "Prepacking execution and unpacking"],
  ["装箱、单证、交运与跟踪", "Packing, documentation, dispatch, and tracking"],
  ["PI、商业发票、装箱单和不可变快照", "PI, commercial invoices, packing lists, and immutable snapshots"],
  ["申报快照、放行及退税状态", "Declaration snapshots, release, and tax rebate status"],
  ["运费、保险、报关、认证与分摊", "Freight, insurance, customs, certification, and allocation"],
  ["代收、费用、到账与差异核对", "Collections, charges, receipts, and variance reconciliation"],
  ["国内外共用库存核心的海外仓扩展档案", "Overseas warehouse profiles sharing the inventory core"],
  ["审核、过账与冲销", "Review, posting, and reversal"],
  ["期初、发生额、逐笔余额与往来辅助核算", "Opening balances, activity, running balances, and subledgers"],
  ["账龄、收付款与核销", "Aging, receipts, payments, and settlement"],
  ["移动平均与单件成本", "Moving average and unit cost"],
  ["申请、审批、入账与支付", "Application, approval, posting, and payment"],
  ["卡片、折旧与处置", "Asset cards, depreciation, and disposal"],
  ["计算、复核、计提与发放", "Calculation, review, accrual, and payment"],
  ["进销项、核验与入账", "Input/output tax, verification, and posting"],
  ["审批、拒绝与转交", "Approve, reject, and transfer"],
  ["版本、关联、分享与保留", "Versions, links, sharing, and retention"],
  ["同步、重试与死信", "Synchronization, retry, and dead letters"],
  ["成功率、延迟、失败与死信趋势", "Success rate, latency, failures, and dead-letter trends"],
  ["CSV 暂存、逐行校验与原子提交", "CSV staging, row validation, and atomic commit"],
  ["法律主体、本位币、时区与状态", "Legal entities, base currency, time zone, and status"],
  ["公司级枚举、层级选项与扩展参数", "Company enums, hierarchical options, and extended parameters"],
  ["账号、组织归属与启停", "Accounts, organization membership, and activation"],
  ["最小权限、职责分离与授权", "Least privilege, segregation of duties, and authorization"],
  ["操作人、对象、结果与来源", "Actor, object, result, and source"],
  ["全链路追溯", "End-to-end traceability"], ["默认拒绝权限", "Deny by default"],
  ["松林金", "Pine Gold"], ["深海蓝", "Deep Ocean"], ["典雅靛紫", "Elegant Indigo"],
  ["暖砂珊瑚", "Warm Coral"], ["石墨夜色", "Graphite Night"],
  ["主数据", "Master data"], ["业务", "Business"], ["供应", "Supply"], ["制造", "Manufacturing"],
  ["贸易", "Trade"], ["财务", "Finance"], ["协同", "Collaboration"], ["系统", "System"],
  ["控制台", "Dashboard"], ["工作台", "Workspace"], ["退出登录", "Sign out"], ["退出", "Sign out"],
  ["搜索模块", "Search modules"], ["搜索", "Search"], ["设置", "Settings"], ["外观设置", "Appearance"],
  ["用户名", "Username"], ["密码", "Password"], ["验证码", "Verification code"],
  ["看不清，换一张", "Refresh image"], ["登录", "Sign in"], ["正在登录", "Signing in"],
  ["保存", "Save"], ["取消", "Cancel"], ["关闭", "Close"], ["重置", "Reset"], ["预览", "Preview"],
  ["刷新", "Refresh"], ["新增", "New"], ["编辑", "Edit"], ["删除", "Delete"], ["详情", "Details"],
  ["提交", "Submit"], ["确认", "Confirm"], ["返回", "Back"], ["上传", "Upload"], ["下载", "Download"],
  ["启用", "Enable"], ["停用", "Disable"], ["解锁", "Unlock"], ["重试", "Retry"],
  ["上一页", "Previous"], ["下一页", "Next"], ["第一页", "First"], ["最后一页", "Last"],
  ["加载中", "Loading"], ["暂无数据", "No data"], ["无数据", "No data"], ["共", "Total"], ["条", "items"],
  ["名称", "Name"], ["编码", "Code"], ["编号", "Number"], ["类型", "Type"], ["状态", "Status"],
  ["日期", "Date"], ["时间", "Time"], ["金额", "Amount"], ["数量", "Quantity"], ["单位", "Unit"],
  ["币种", "Currency"], ["备注", "Notes"], ["摘要", "Description"], ["标题", "Title"],
  ["客户", "Customer"], ["供应商", "Supplier"], ["仓库", "Warehouse"], ["产品", "Product"],
  ["公司", "Company"], ["用户", "User"], ["角色", "Role"], ["权限", "Permission"],
  ["创建人", "Created by"], ["创建时间", "Created at"], ["更新时间", "Updated at"],
  ["开始时间", "Start time"], ["结束时间", "End time"], ["截止时间", "Due at"],
  ["成功", "Success"], ["失败", "Failed"], ["待处理", "Pending"], ["已完成", "Completed"],
  ["已取消", "Cancelled"], ["已启用", "Enabled"], ["已停用", "Disabled"], ["是否启用", "Enabled"],
  ["是", "Yes"], ["否", "No"], ["全部", "All"], ["请选择", "Select"], ["必填", "Required"],
  ["背景", "Background"], ["图片", "Image"], ["标识", "Logo"], ["字体", "Font"], ["主题", "Theme"],
  ["颜色", "Color"], ["透明度", "Opacity"], ["填充", "Fill"], ["居中", "Center"],
  ["信息", "Information"], ["链接", "Link"], ["显示文字", "Display text"], ["版本名称", "Version name"],
  ["应用名称", "Application name"], ["前端名称", "Frontend name"], ["品牌 Logo", "Brand logo"],
  ["默认", "Default"], ["自定义", "Custom"], ["本地上传", "Local upload"], ["自动更新", "Automatic update"],
  ["操作", "Actions"], ["创建", "Create"], ["更新", "Update"], ["查看", "View"], ["筛选", "Filter"],
  ["清除", "Clear"], ["确定", "OK"], ["错误", "Error"], ["警告", "Warning"], ["提示", "Notice"],
  ["平均延迟", "Average latency"], ["死信", "Dead letters"], ["窗口内", "In window"], ["个事件", "events"],
  ["成功率", "Success rate"], ["快速定位同步失败、死信与延迟异常", "Quickly locate sync failures, dead letters, and latency anomalies"],
  ["中西文", "CJK and Latin"], ["仅中文", "CJK only"], ["中文字形", "CJK glyphs"], ["字形", "glyphs"],
  ["对象存储", "object storage"], ["上传品牌", "Upload brand"], ["保存时立即拉取", "Fetch on save"],
  ["当日图片", "daily image"], ["之后每天", "then daily"], ["当前图片", "Current image"],
  ["导入字体到", "Import font to"], ["上传并暂存", "Upload and stage"],
  ["上架", "Putaway"], ["下单时间", "Order time"], ["不重置", "Do not reset"],
  ["两次输入的", "The two entered"], ["不一致", "do not match"], ["个人", "Personal"],
  ["中文名称", "Chinese name"], ["英文名称", "English name"], ["临时授权", "Temporary authorization"],
  ["事件投递", "Event delivery"], ["事件", "Event"], ["事务", "Transaction"], ["失败原因", "failure reason"],
  ["人工补偿", "manual compensation"], ["代收金额", "Collected amount"], ["价格表编号", "Price list number"],
  ["价税合计", "Tax-inclusive total"], ["任务监控", "Task monitor"], ["任务类型", "Task type"],
  ["任务行", "Task line"], ["任务号", "Task number"], ["任务", "Task"], ["优先级", "Priority"],
  ["会计期间", "Accounting period"], ["使用月数", "Useful life in months"], ["例如", "For example"],
  ["夏季版", "Summer edition"], ["供应缺口", "Supply shortage"], ["保存失败，请检查字段", "Save failed. Check the fields"],
  ["保留客商", "Retained party"], ["保留档案", "Retained record"], ["保管人", "Custodian"],
  ["修改登录密码", "Change login password"], ["允许登录", "Allow login"], ["允许超卖", "Allow overselling"],
  ["允许", "Allow"], ["留空为全局", "Leave blank for global"], ["超级管理员可留空", "Super administrators may leave blank"],
  ["关键操作、对象与变更留痕", "Key actions, objects, and change history"], ["内部仓库", "Internal warehouse"],
  ["凭证号", "Voucher number"], ["凭证", "Voucher"], ["分摊依据", "Allocation basis"],
  ["分摊快照", "Allocation snapshot"], ["分隔符", "Delimiter"], ["初始密码", "Initial password"],
  ["至少", "at least"], ["位", "characters"], ["到账金额", "Received amount"],
  ["前端工作台处理", "Handled in the frontend workspace"], ["前缀、日期、流水长度与重置周期", "Prefix, date, sequence length, and reset cycle"],
  ["前缀模板", "Prefix template"], ["加工商", "Processor"], ["加载失败", "Failed to load"], ["动作", "Action"],
  ["包装方案", "Packing plan"], ["匹配原因数组", "Match reason array"], ["匹配度", "Match score"],
  ["单件追踪", "Item traceability"], ["单证数据快照", "Document data snapshot"], ["单证类型", "Document type"],
  ["单证编号", "Document number"], ["原值", "Original value"], ["原因代码", "Reason code"],
  ["原因说明", "Reason description"], ["原子权限", "Atomic permission"], ["原币金额", "Original-currency amount"],
  ["发生时间", "Occurred at"], ["发票代码", "Invoice code"], ["发票号码", "Invoice number"],
  ["发货单", "Delivery order"], ["拣货/复核", "Picking/review"], ["含税", "Tax included"],
  ["品牌设置保存失败", "Failed to save branding settings"], ["售后处理中", "After-sales processing"],
  ["售后明细", "After-sales lines"], ["售后类型", "After-sales type"], ["售后单号", "After-sales number"],
  ["商品名称", "Product name"], ["国家/地区", "Country/region"], ["图片验证码，点击更换", "Image verification code; click to refresh"],
  ["在手", "On hand"], ["在途", "In transit"], ["基本单位", "Base unit"], ["处理中", "Processing"],
  ["处理失败", "Processing failed"], ["外部仓编码", "External warehouse code"], ["外部引用", "External reference"],
  ["外部编码", "External code"], ["失效时间", "Expires at"], ["姓名", "Full name"], ["委外单号", "Subcontract number"],
  ["字体导入失败", "Font import failed"], ["字典编码", "Dictionary code"], ["存放位置", "Storage location"],
  ["实发金额", "Net amount"], ["审批实例", "Approval instance"], ["审批状态", "Approval status"],
  ["客商编码", "Party code"], ["密码修改失败", "Password change failed"], ["密码错误次数", "Password failure count"],
  ["密级", "Security level"], ["对象类型", "Object type"], ["尝试次数", "Attempts"], ["岗位", "Position"],
  ["工号", "Employee number"], ["差异", "Difference"], ["已交运", "Dispatched"], ["已冲销", "Reversed"],
  ["已批准", "Approved"], ["已确认", "Confirmed"], ["已过账", "Posted"], ["已选择", "Selected"],
  ["平均单位成本", "Average unit cost"], ["应付", "Payable"], ["应收", "Receivable"],
  ["开票日期", "Invoice date"], ["往来单位", "Counterparty"], ["可选", "optional"], ["往来单号", "Transaction number"],
  ["待激活", "Pending activation"], ["待过账凭证", "Vouchers pending posting"], ["总行数", "Total rows"],
  ["成品", "Finished product"], ["成本数量", "Cost quantity"], ["手机", "Mobile"], ["打包复核", "Packing review"],
  ["执行人", "Executor"], ["扫描", "Scan"], ["条码", "barcode"], ["或单件编号", "or item number"],
  ["批次处理失败", "Batch processing failed"], ["批次追踪", "Batch traceability"], ["批次号", "Batch number"],
  ["折让", "Allowance"], ["报关单号", "Customs declaration number"], ["报销单号", "Expense claim number"],
  ["拒绝", "Reject"], ["拣货", "Pick"], ["换货", "Exchange"], ["授权效果", "Authorization effect"],
  ["搜索当前列表", "Search current list"], ["操作人", "Operator"], ["收货仓", "Receiving warehouse"],
  ["收货单", "Receipt"], ["收货地址", "Receiving address"], ["效果", "Effect"], ["数据类型", "Data type"],
  ["数据范围值", "Data scope value"], ["数据范围类型", "Data scope type"], ["文件编号", "File number"],
  ["文件预览失败", "File preview failed"], ["方向", "Direction"], ["日期格式", "Date format"], ["时区", "Time zone"],
  ["明细账查询失败", "Ledger query failed"], ["显示名称", "Display name"], ["站内页面", "Internal page"],
  ["暂停", "Paused"], ["暂存失败", "Staging failed"], ["更多信息", "More information"], ["有效", "Valid"],
  ["服务商", "Service provider"], ["期间开始", "Period start"], ["期间结束", "Period end"], ["期间", "Period"],
  ["未税金额", "Amount before tax"], ["未税", "Before tax"], ["本位币金额", "Base-currency amount"],
  ["本位币", "Base currency"], ["本次数量", "Current quantity"], ["来源库位", "Source location"],
  ["来源类型", "Source type"], ["来源", "Source"], ["查重失败", "Duplicate check failed"],
  ["模板版本", "Template version"], ["正在保存", "Saving"], ["正在修改", "Updating"], ["正在暂存", "Staging"],
  ["正常", "Normal"], ["残值", "Residual value"], ["每年", "Yearly"], ["每日", "Daily"], ["每月", "Monthly"],
  ["汇率", "Exchange rate"], ["法定名称", "Legal name"], ["波次号", "Wave number"], ["波次", "Wave"],
  ["注册地区", "Registered region"], ["流水长度", "Sequence length"], ["海关模式", "Customs mode"],
  ["渠道", "Channel"], ["点击更换验证码", "Click to refresh the verification code"], ["点击选择", "Click to select"],
  ["生产仓", "Production warehouse"], ["生产单号", "Production order number"], ["生产进行中", "Production in progress"],
  ["生效时间", "Effective at"], ["用户管理", "User management"],
  ["用户级允许/拒绝、双人审批与撤销", "User-level allow/deny, dual approval, and revocation"],
  ["申报币种", "Declaration currency"], ["申报日期", "Declaration date"], ["申报明细快照", "Declaration detail snapshot"],
  ["申报模式", "Declaration mode"], ["申报海关", "Declared customs office"], ["申报金额", "Declared amount"],
  ["申请人", "Applicant"], ["申请原因", "Application reason"], ["登录名", "Login name"],
  ["登录页相关链接", "Login-page links"], ["监控加载失败", "Failed to load monitoring data"],
  ["目标库位", "Target location"], ["目的地", "Destination"], ["确认修改", "Confirm changes"],
  ["确认拒绝此审批任务", "Reject this approval task"], ["确认通过此审批任务", "Approve this approval task"],
  ["科目", "Account"], ["税额明细", "Tax details"], ["税额", "Tax amount"], ["系统字典", "System dictionary"],
  ["系统连接失败", "System connection failed"], ["索赔", "Claim"], ["组织", "Organization"], ["终止", "Terminate"],
  ["结构化数据", "Structured data"], ["结算明细", "Settlement lines"], ["结算单号", "Settlement number"],
  ["编号规则", "Numbering rules"], ["聚合类型", "Aggregation type"], ["草稿", "Draft"],
  ["薪资批次号", "Payroll run number"], ["薪资明细", "Payroll lines"], ["补发", "Reship"],
  ["规则编码", "Rule code"], ["角色与原子权限集合", "Role and atomic permission set"],
  ["计划开始", "Planned start"], ["计划数量", "Planned quantity"], ["计划结束", "Planned end"],
  ["计提凭证", "Accrual voucher"], ["计税模式", "Tax calculation mode"], ["订单明细", "Order lines"],
  ["订单日期", "Order date"], ["订单时间", "Order time"], ["订单号", "Order number"], ["语言", "Language"],
  ["说明", "Description"], ["请输入判定为非重复的原因", "Enter the reason this is not a duplicate"],
  ["请输入需要扫描的公司", "Enter the company to scan"], ["读取失败", "Failed to read"],
  ["账号、组织归属、登录失败与锁定状态", "Accounts, organization membership, login failures, and lock status"],
  ["账簿", "Ledger"], ["货代", "Freight forwarder"], ["购置日期", "Acquisition date"],
  ["费用日期", "Expense date"], ["费用类型", "Expense type"], ["费用说明", "Expense description"],
  ["费用金额", "Expense amount"], ["资产原值", "Original asset cost"], ["资产名称", "Asset name"],
  ["资产类别", "Asset category"], ["资产编号", "Asset number"], ["起始值", "Starting value"],
  ["超级管理员", "Super administrator"], ["运营商", "Carrier"], ["运营总览", "Operations overview"],
  ["运输方式", "Transport mode"], ["运输途中", "In transit"], ["进销项", "Input/output tax"],
  ["进项", "Input tax"], ["销项", "Output tax"], ["退款", "Refund"], ["退税引用", "Tax rebate reference"],
  ["退税状态", "Tax rebate status"], ["退货", "Return"], ["邮箱", "Email"], ["部门", "Department"],
  ["采购明细", "Purchase lines"], ["采购单号", "Purchase order number"], ["重复客商", "Duplicate party"],
  ["重复档案", "Duplicate record"], ["重置周期", "Reset cycle"], ["锁定原因", "Lock reason"], ["锁定", "Locked"],
  ["队列、执行、重试与死信", "Queues, execution, retries, and dead letters"], ["队列", "Queue"],
  ["限量产品", "Limited product"], ["需求单号", "Requisition number"], ["需求日期", "Required date"],
  ["预包装任务号", "Prepacking task number"], ["预留", "Reserved"], ["预计交期", "Expected delivery"],
  ["风险等级", "Risk level"], ["首次登录，请修改初始密码", "First login: change the initial password"],
  ["默认语言", "Default language"],
  ["上传品牌 Logo 到对象存储", "Upload brand logo to object storage"],
  ["保存时立即拉取 Bing 当日图片，之后每天自动更新并保存到对象存储", "Fetch today's Bing image on save, then update it daily and store it in object storage"],
  ["事务 Outbox、失败原因与人工补偿", "Transactional outbox, failure reasons, and manual compensation"],
  ["任务行（line_no、sku、source_balance/target_location 或 sales_shipment_line、planned_qty）", "Task lines (line_no, sku, source_balance/target_location, or sales_shipment_line and planned_qty)"],
  ["原子权限 ID 数组", "Atomic permission ID array"],
];

const sortedTerms = [...TERMS].sort((a, b) => b[0].length - a[0].length);
const originalText = new WeakMap<Text, string>();
const originalAttributes = new WeakMap<Element, Map<string, string>>();

function translate(value: string): string {
  if (!/[\u3400-\u9fff]/.test(value)) return value;
  let result = value;
  for (const [zh, en] of sortedTerms) result = result.split(zh).join(en);
  return result
    .replace(/，/g, ", ").replace(/。/g, ".").replace(/：/g, ": ")
    .replace(/；/g, "; ").replace(/（/g, " (").replace(/）/g, ")")
    .replace(/\s+,/g, ",").replace(/\s{2,}/g, " ");
}

function translateTree(root: ParentNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const textNode = node as Text;
    if (textNode.parentElement?.closest("[data-no-translate]") || !textNode.nodeValue?.trim()) continue;
    if (!originalText.has(textNode)) originalText.set(textNode, textNode.nodeValue);
    textNode.nodeValue = translate(originalText.get(textNode) ?? textNode.nodeValue);
  }
  const elements = root instanceof Element ? [root, ...root.querySelectorAll("*")] : [...root.querySelectorAll("*")];
  for (const element of elements) {
    if (element.closest("[data-no-translate]")) continue;
    let originals = originalAttributes.get(element);
    if (!originals) { originals = new Map(); originalAttributes.set(element, originals); }
    for (const name of ["placeholder", "title", "aria-label", "alt"]) {
      const current = element.getAttribute(name);
      if (!current) continue;
      if (!originals.has(name)) originals.set(name, current);
      element.setAttribute(name, translate(originals.get(name) ?? current));
    }
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language] = useState<Language>(() => localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh-CN");
  useEffect(() => {
    document.documentElement.lang = language;
    if (language !== "en") return;
    const root = document.getElementById("root");
    if (!root) return;
    translateTree(root);
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const added of mutation.addedNodes) {
          if (added.nodeType === Node.TEXT_NODE && added.parentElement) translateTree(added.parentElement);
          else if (added instanceof Element) translateTree(added);
        }
      }
    });
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [language]);
  return <LanguageContext.Provider value={language}>{children}<LanguageSwitch /></LanguageContext.Provider>;
}

export function useLanguage() { return useContext(LanguageContext); }

function LanguageSwitch() {
  const language = useLanguage();
  const choose = (next: Language) => {
    if (next === language) return;
    localStorage.setItem(STORAGE_KEY, next);
    window.location.reload();
  };
  return (
    <label className="language-switch" data-no-translate>
      <select
        aria-label="Language"
        value={language}
        onChange={(event) => choose(event.target.value as Language)}
      >
        <option value="zh-CN">简体中文</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}
