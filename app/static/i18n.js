'use strict';
// UI translation. English is the source language; every string that reaches the screen passes through tr().
// Exact matches come from ZH; strings with numbers, dates or server-generated text go through ZH_PATTERNS.
// Tickers, amounts and terminal mnemonics (PORT, PERF, NVDA <GO>) are intentionally left as-is.

const LANGS = { en: 'EN', zh: '中文' };
let LANG = (() => {
  const q = new URLSearchParams(location.search).get('lang');
  if (q && LANGS[q]) { try { localStorage.setItem('lang', q); } catch {} return q; }
  try { const saved = localStorage.getItem('lang'); if (saved && LANGS[saved]) return saved; } catch {}
  return /^zh/i.test(navigator.language || '') ? 'zh' : 'en';
})();

const ZH = {
  // screens & navigation
  'PORTFOLIO': '投资组合', 'PERFORMANCE': '业绩表现', 'REALIZED P&L': '已实现盈亏', 'TRADES': '交易', 'ALLOCATION': '资产配置',
  'RULES': '规则', 'EVENTS': '事件', 'INCOME': '收益', 'DECISION AUDIT': '决策审计', 'WHAT-IF': '情景模拟', 'DATA & FETCH': '数据与抓取', 'IMPORT': '导入', 'HELP': '帮助',
  'NAV ': '净值 ', 'DAY ': '当日 ', 'GAIN ': '收益 ', 'PX ': '行情 ', 'EXPORT ': '导出 ', 'USDCAD ': '美元/加元 ',
  'REBUILD': '重建', 'REFRESH': '刷新', 'FETCH': '抓取', 'OFFLINE': '离线', 'server not reachable': '无法连接服务器',
  'FETCH · UP TO DATE': '抓取 · 已是最新', 'FETCH · NO DATA': '抓取 · 无数据', 'FETCH · NEED HOLDINGS': '抓取 · 需要持仓报告', 'REBUILDING…': '重建中…', 'NEVER FETCHED': '从未抓取',
  ' · RATE LIMITED': ' · 已限流', 'Command or ticker…': '命令或代码…', 'LOADING…': '加载中…', 'LOADING STATUS…': '加载状态…',
  'NO DATA · IMPORT YOUR EXPORTS': '无数据 · 请导入导出文件', 'NO DATA YET — IMPORT YOUR EXPORTS': '尚无数据 — 请导入导出文件',
  'Fetching due market data…': '正在抓取到期行情…', 'Rebuilding…': '正在重建…', 'Imported · rebuilding…': '已导入 · 正在重建…',
  'Imported · fetching prices for new symbols…': '已导入 · 正在抓取新代码的价格…', 'Choose .csv files': '请选择 .csv 文件',
  'No valid files in upload': '上传中没有有效文件', 'Open DATA screen': '打开数据页',
  'VIM': 'VIM', 'EXIT VIM': '退出 VIM', 'Enable Vim keyboard navigation': '启用 Vim 键盘导航', 'Exit Vim mode (:q)': '退出 Vim 模式（:q）',
  'GUEST · EPHEMERAL': '访客 · 临时', 'END SESSION': '结束会话', 'Uploaded portfolio data is erased when this guest container stops; only public market data persists.': '访客容器停止后，上传的投资组合数据将被清除；仅保留公开市场数据。',
  'One browser owns this guest workspace. END SESSION erases its portfolio data; only public market data persists.': '此访客工作区仅由一个浏览器会话占用。结束会话会清除投资组合数据；仅保留公开市场数据。',
  'End this guest session and permanently erase all uploaded portfolio data? Public market prices will remain cached.': '结束访客会话并永久清除所有上传的投资组合数据？公开市场价格缓存将保留。',
  'VIM MODE · h/j/k/l controls · Enter activates · gg/G edges · i/: command': 'VIM 模式 · h/j/k/l 移动控件 · Enter 激活 · gg/G 到顶/底 · i/: 输入命令', 'VIM MODE OFF': 'VIM 模式已关闭',
  'Enable Vim keys: h/j/k/l move between panel controls · Enter/Space activate · gg/G top/bottom · Ctrl-d/Ctrl-u half-page · b back · i/: command': '启用 Vim 按键：h/j/k/l 在面板控件间移动 · Enter/空格激活 · gg/G 到顶/底 · Ctrl-d/Ctrl-u 半页 · b 返回 · i/: 输入命令',
  'Exit Vim mode': '退出 Vim 模式',
  'Recompute from exports and cached prices, no network (REBUILD <GO>)': '用导出文件和缓存价格重新计算，不联网（REBUILD <GO>）',
  'Fetch due market data, then rebuild (FETCH <GO>)': '抓取到期行情后重建（FETCH <GO>）',

  // common terms
  'ACCOUNT': '账户', 'ACCOUNTS': '账户', 'Account': '账户', 'SYMBOL': '代码', 'TICKER': '代码', 'HOLDING': '持仓', 'HOLDINGS': '持仓',
  'QTY': '数量', 'AVG COST': '平均成本', 'LAST': '最新价', 'DAY': '当日', 'VALUE': '市值', 'VALUE CAD': '市值（加元）', 'WT': '权重', 'WEIGHT': '权重',
  'UNREAL': '浮动盈亏', 'UNREAL %': '浮动盈亏 %', 'UNREALIZED': '未实现盈亏', 'REALIZED': '已实现', 'REALIZED (CAD)': '已实现（加元）',
  'GAIN': '收益', 'GAIN %': '收益率', 'DEPOSITED': '已存入', 'NET DEPOSITED': '净存入', 'BUCKET': '类别', 'CORE': '核心', 'STOCKS': '个股',
  'SPECULATIVE': '投机', 'CASH': '现金', 'OPTION': '期权', 'OPTIONS': '期权', 'CRYPTO': '加密货币', 'Crypto': '加密货币', 'Non-registered': '非注册账户',
  'NON-REGISTERED': '非注册账户', 'ALL': '全部', 'BUY': '买入', 'SELL': '卖出', 'BUYS': '买入', 'SELLS': '卖出', 'SIDE': '方向', 'Side': '方向',
  'DATE': '日期', 'PRICE': '价格', 'AMOUNT': '金额', 'NOW': '现在', 'HINDSIGHT': '事后对比', 'FLAG': '标记', 'AVG↓': '摊低',
  'FIRST': '首次', 'OPEN': '持有中', 'TOTAL': '合计', 'YES': '是', 'OK': '正常', 'FAILED': '失败', 'IDLE': '空闲', 'NONE': '不计入',
  'ACTUAL': '实际', 'FROZEN': '冻结', 'SIMULATED': '模拟', 'SIM': '模拟', 'YOU': '你', 'DEPOSITED ': '已存入 ', 'TODAY': '今天',
  '1M': '1个月', '3M': '3个月', '6M': '6个月', '1Y': '1年', '1W': '1周', 'YTD': '年初至今', 'TO DATE': '至今', 'RETURN': '收益率',
  'Symbol filter': '代码筛选', 'SYMBOL ': '代码 ', 'not yet': '尚未到期', 'Freeze date': '冻结日期', 'USD CASH': '美元现金', 'CAD CASH': '加元现金',

  // PORT
  'TOTAL VALUE (CAD)': '总市值（加元）', 'DAY CHANGE': '当日变动', 'Yahoo last two closes': 'Yahoo 最近两个收盘价', 'all accounts, all time': '全部账户，全部时间',
  'TOTAL GAIN': '总收益', 'avg-cost, all time': '平均成本法，全部时间', 'open positions': '当前持仓', 'click a row for its history': '点击行查看历史',

  'INVESTED': '已投资', 'ALL MONEY': '全部资金', 'INVESTED (NO CASH)': '已投资（不含现金）', 'CAPITAL DEPLOYED': '投入资金',
  'INVESTED MONEY (TIME-WEIGHTED)': '已投资资金（时间加权）', 'CASH ETF': '现金ETF',
  'value change minus capital deployed': '市值变化减去投入资金',
  'deposits after the freeze buy CCAD, the cash ETF you actually park money in': '冻结后的存款买入 CCAD（你实际用来存放现金的现金 ETF）',
  'Cash and cash ETFs (CCAD, TCSH, CBIL) are excluded from both sides: the benchmark receives money only when you bought a risk asset, and dividends leave the sleeve as they do in reality. This compares your picks with XEQT on equal terms.': '双方均剔除现金及现金 ETF（CCAD、TCSH、CBIL）：只有在你真正买入风险资产时基准才获得资金，股息也像现实中一样流出。这样才能公平比较你的选股与 XEQT。',
  'Benchmark lines replay every deposit and withdrawal into that ETF on the same day (dividends reinvested) — including money you parked in cash ETFs, which is why they can lead. Switch to INVESTED for a like-for-like comparison.': '基准线假设每笔存取款当天买卖该 ETF（股息再投资）——包括你存放在现金 ETF 中的资金，因此基准可能领先。切换到"已投资"可进行同口径比较。',

  // PERF
  'YOUR GAIN IN RANGE': '区间内你的收益', 'value change minus deposits': '市值变化减去存入', 'YOUR RETURN': '你的收益率',
  'time-weighted, flows removed': '时间加权，已剔除资金进出', 'you vs it: ': '你 vs 它：', 'PORTFOLIO (TIME-WEIGHTED)': '投资组合（时间加权）',
  'Benchmark lines replay every deposit and withdrawal into that ETF on the same day (dividends reinvested).': '基准线假设每笔存取款在当天买卖该 ETF（股息再投资）。',
  'Returns rebased to 0% at the range start. Early months are noisy because balances were small.': '收益率以区间起点为 0%。早期余额较小，波动较大。',
  'Account value in CAD, including cash.': '账户市值（加元），含现金。',

  'rate: ': '收益率：', 'worth ': '折合 ', ' in range': '（区间内）', 'you vs it: ': '你 vs 它：',
  'GAIN': '盈亏', 'YOUR GAIN': '你的盈亏', 'INVESTED GAIN': '已投资盈亏',
  'Cumulative money made or lost since the start of the range, deposits removed: 0 means break even. Benchmark lines get the same money on the same days.': '区间内累计盈亏（已剔除存入资金）：0 表示持平。基准线在相同日期获得相同资金。',
  'GAIN': '盈亏', 'YOUR GAIN': '你的盈亏', 'INVESTED GAIN': '已投资盈亏',
  'Money made or lost since the range start, deposits removed: 0 is break even. Hover shows the time-weighted rate beside each amount; benchmark lines receive the same money on the same days.': '区间内累计盈亏（已剔除存入资金）：0 表示持平。悬停可查看对应的时间加权收益率；基准线在相同日期获得相同资金。',
  'GAIN': '盈亏', 'YOUR GAIN': '你的盈亏', 'INVESTED GAIN': '已投资盈亏',
  'Money made or lost since the range start, deposits removed: 0 is break even. Hover shows the time-weighted rate beside each amount.': '区间内累计盈亏（已剔除存入资金）：0 表示持平。悬停可查看对应的时间加权收益率。',
  'Time-weighted returns rebased to 0% at the range start; hover shows what each rate is worth in CAD.': '时间加权收益率以区间起点为 0%；悬停可查看该收益率折合多少加元。',
  'Benchmark lines replay every deposit and withdrawal into that ETF on the same day (dividends reinvested).': '基准线假设每笔存取款当天买卖该 ETF（股息再投资）。',
  'Cash and cash ETFs (CCAD, TCSH, CBIL) are excluded from both sides: the benchmark receives money only when you bought a risk asset, and dividends leave the sleeve as they do in reality.': '双方均剔除现金及现金 ETF（CCAD、TCSH、CBIL）：只有在你买入风险资产时基准才获得资金，股息也像现实中一样流出。',
  'ALL MONEY includes what you parked in cash ETFs, which is why a benchmark can lead. Switch to INVESTED for a like-for-like comparison.': '"全部资金"包含你存放在现金 ETF 中的资金，因此基准可能领先。切换到"已投资"可进行同口径比较。',
  'BALANCE CHANGE': '余额变化', 'MONEY ADDED': '新增资金', 'INVESTMENT GAIN': '投资收益',
  'money added + investment gain': '新增资金 + 投资收益', 'deposits and transfers in range': '区间内的存入与转入',
  'balance change minus money added': '余额变化减去新增资金', 'value change minus money added': '市值变化减去新增资金',

  // AUD
  'PORTFOLIO TWR': '组合时间加权收益率', 'daily, cash flows removed': '按日计算，已剔除资金进出',
  'CAD total return over the same period': '同期加元总收益率', 'EXCESS VS BENCHMARK': '相对基准超额收益',
  'portfolio TWR minus benchmark return': '组合时间加权收益率减去基准收益率',
  'TOP 1 / POSITIVE P&L': '前1 / 正收益', 'TOP 3 / POSITIVE P&L': '前3 / 正收益', 'campaign concentration': '持仓周期集中度',
  'DAILY COVERAGE': '日线覆盖率', 'HOW TO READ THIS AUDIT': '如何阅读本审计', 'definitions used throughout this screen': '本页所用术语定义',
  'CAMPAIGN': '持仓周期', 'One continuous position in one account: it starts when shares move from zero to positive and ends when they return to zero. Transactions inside it are related, not independent bets.': '同一账户中的一段连续持仓：股数从零变为正数时开始，回到零时结束。其中的交易彼此相关，并非独立下注。',
  'ABOVE / BELOW COST': '高于 / 低于成本', 'The previous completed daily close is compared with average cost immediately before the decision. This avoids using a close that occurred after the trade.': '用决策前最近一个已完成的日收盘价与当时平均成本比较，避免使用交易发生后的收盘价。',
  'EXCESS RETURN': '超额收益', 'EXIT SCORE': '卖出评分', 'For a sale the sign is reversed: benchmark return minus the sold security return. Positive means selling added relative value; negative means holding would have done better.': '卖出采用反向符号：基准收益减去已卖证券收益。正值表示卖出创造了相对价值；负值表示继续持有会更好。',
  'ACCUMULATED FACTOR': '累计因子', 'Starts at 1.000× and multiplies relative wealth when each score matures: security divided by benchmark for buys, and benchmark divided by security for sells.': '从 1.000× 开始，每个评分到期时乘以相对财富因子：买入为证券除以基准，卖出为基准除以证券。',
  '10–90% BAND': '10–90% 区间', 'Campaigns are resampled as blocks. This is a concentration-sensitivity range, not a statistical confidence interval and not a probability of skill.': '以完整持仓周期为区块进行重采样。这是集中度敏感性区间，不是统计置信区间，也不是能力概率。',
  'CUMULATIVE DECISION INDEX': '累计决策指数', '100 = starting level · compounds fixed-horizon excess returns by decision class': '100 = 起始值 · 按决策类别复合累计固定周期超额收益',
  'No priced decisions yet.': '尚无可定价的决策。',
  'Daily close-to-close CAD excess return; pre-trade state uses the previous completed close; exits use benchmark minus security. When a horizon elapses, the accumulated series multiplies a positive relative-wealth factor: security/benchmark for buys, benchmark/security for sells. The indices are descriptive, not evidence of independent bets.': '按日收盘到收盘计算加元超额收益；交易前状态采用上一个已完成收盘价；卖出采用基准减证券收益。观察周期结束时，累计序列乘以始终为正的相对财富因子：买入为证券/基准，卖出为基准/证券。指数仅作描述，不代表每笔交易是独立下注。',
  'DAILY EVIDENCE REPLAY': '每日证据回放', 'First day': '第一天', 'Previous day': '前一天', 'Next day': '后一天', 'Latest day': '最新一天',
  '▶ PLAY': '▶ 播放', 'Ⅱ PAUSE': 'Ⅱ 暂停', 'Score horizon': '评分周期', 'Replay speed': '回放速度', 'SLOW': '慢速', 'NORMAL': '正常', 'FAST': '快速',
  'Replay day': '回放日期', 'Arrow keys or Vim h/l move one day · Shift moves five': '方向键或 Vim h/l 移动一天 · Shift 移动五天',
  'FOCUSED SLIDER: ←/→ OR VIM h/l = 1 DAY · SHIFT = 5 · HOME/END = EDGES': '滑块聚焦时：←/→ 或 Vim h/l = 1 天 · Shift = 5 天 · Home/End = 两端',
  'EVIDENCE AS OF': '证据截至', 'TODAY': '当日', 'NO SCORE MATURED': '无评分到期',
  'DECISIONS MADE': '当日决策', 'on this trading day': '此交易日', 'CLASS': '类别', 'NOTIONAL': '名义金额', 'SCORE DATE': '评分日期', 'PENDING': '待观察',
  'No equity decision was made on this day.': '此日没有股票决策。', 'EVIDENCE MATURED': '到期证据', 'DECISION DATE': '决策日期', 'EXCESS SCORE': '超额评分', 'RELATIVE FACTOR': '相对因子',
  'No fixed-horizon score matured on this day; accumulated factors carry forward.': '此日没有固定周期评分到期；累计因子沿用前一日。',
  'RELATIVE FACTOR PATH · LOG SCALE': '相对因子路径 · 对数尺度', '1.000× is neutral · evidence posts only after the selected horizon has elapsed': '1.000× 为中性 · 仅在所选观察周期结束后计入证据',
  'WHAT THIS DAY MEANS': '这一天意味着什么', 'DECISION MADE': '做出决策',
  'A transaction was classified from the portfolio state immediately before it. Its future score is still unknown.': '根据交易发生前一刻的组合状态对该交易分类；未来评分此时仍未知。',
  'The selected observation window has fully elapsed. Only now does its score enter the accumulated factor.': '所选观察周期已经完整结束；评分到此刻才计入累计因子。',
  'The decision exists, but its selected horizon has not finished. Pending is not a gain, loss, or missing-data verdict.': '该决策已经发生，但所选周期尚未结束。待观察不代表盈利、亏损或缺少数据。',
  'The position moved from zero to positive. This starts a new campaign and measures the initial entry.': '持仓从零变为正数，开启新的持仓周期，并衡量首次建仓。',
  'More shares were bought while the previous completed close was below the pre-trade average cost.': '在上一个已完成收盘价低于交易前平均成本时继续买入。',
  'More shares were bought while the previous completed close was at or above the pre-trade average cost.': '在上一个已完成收盘价等于或高于交易前平均成本时继续买入。',
  'Part of the position was sold below average cost, while some shares remained.': '在低于平均成本时卖出部分仓位，并保留部分股份。',
  'Part of the position was sold at or above average cost, while some shares remained.': '在等于或高于平均成本时卖出部分仓位，并保留部分股份。',
  'The remaining position was sold below average cost, ending the campaign.': '在低于平均成本时卖出剩余仓位，结束该持仓周期。',
  'The remaining position was sold at or above average cost, ending the campaign.': '在等于或高于平均成本时卖出剩余仓位，结束该持仓周期。',
  'NO COMPLETE WINDOW': '无完整观察周期', 'SECURITY RETURN': '证券收益', 'BENCHMARK RETURN': '基准收益',
  'For an exit, a positive score means the benchmark beat the sold security afterward, so selling added relative value. A negative score means holding would have done better.': '对于卖出，正评分表示之后基准跑赢已卖证券，因此卖出创造了相对价值；负评分表示继续持有会更好。',
  'For an entry, a positive score means the security beat the benchmark after the purchase. A negative score means the benchmark did better.': '对于买入，正评分表示买入后证券跑赢基准；负评分表示基准表现更好。',
  'NO NEW EVIDENCE TODAY': '今日无新证据',
  'DECISION EVIDENCE': '决策证据', 'average CAD excess return at fixed trading-day horizons · n = priced decisions': '固定交易日周期的平均加元超额收益 · n = 可定价决策数',
  'DECISION CLASS': '决策类别', 'CAMPAIGNS': '持仓周期数',
  'ALL DECISIONS': '全部决策', 'INITIAL ENTRY': '首次建仓', 'ADD BELOW COST': '低于成本加仓', 'ADD ABOVE COST': '高于成本加仓',
  'PARTIAL EXIT BELOW COST': '低于成本部分卖出', 'PARTIAL EXIT ABOVE COST': '高于成本部分卖出',
  'FULL EXIT BELOW COST': '低于成本全部卖出', 'FULL EXIT ABOVE COST': '高于成本全部卖出', 'FULL EXIT': '全部卖出',
  'SHORT-HORIZON EXIT': '短期卖出', 'TOP-3 CONCENTRATION': '前三集中度', 'TOP-5 CONCENTRATION': '前五集中度',
  'The 10–90% bands resample whole campaigns, preserving dependence between transactions in the same position. Wide bands mean the result depends heavily on which campaigns occurred.': '10–90% 区间以完整持仓周期重采样，保留同一持仓内交易的相关性。区间越宽，说明结果越依赖于具体出现过的持仓周期。',
  'CONCENTRATION STRESS TEST': '集中度压力测试', 'remove the highest-P&L campaigns and replay the remaining ledger': '移除盈亏最高的持仓周期并重放其余账本',
  'SCENARIO': '情景', 'VS BENCH': '对比基准', 'END VALUE': '期末市值', 'TRADES OUT': '移除交易',
  'AVERAGING-DOWN ROBUSTNESS': '低于成本加仓稳健性', '20D EST. RELATIVE EFFECT': '20日估算相对效果', '60D EST. RELATIVE EFFECT': '60日估算相对效果',
  'trade notional × 20D excess return': '交易名义金额 × 20日超额收益', 'trade notional × 60D excess return': '交易名义金额 × 60日超额收益',
  'MEDIAN CAMPAIGN P&L': '持仓周期盈亏中位数', 'campaigns containing an add below cost': '包含低于成本加仓的持仓周期',
  'NO ADD BELOW COST': '未低于成本加仓', 'median of other campaigns': '其他持仓周期的中位数', '20D EFFECT': '20日效果', '60D EFFECT': '60日效果',
  'CAMPAIGN P&L': '持仓周期盈亏', 'START': '开始', 'END': '结束', 'DECISIONS': '决策数', 'P&L CAD': '盈亏（加元）',
  'SCOPE & LIMITATIONS': '范围与限制', 'frozen hypotheses · explicit exclusions': '冻结假设 · 明确排除项', 'PRE-REGISTERED V1 QUESTIONS': 'V1 预先登记问题',
  'Daily bars are canonical; hourly data is optional and currently not used.': '日线是标准时间尺度；小时数据为可选项，目前未使用。',
  'Accumulated factors are frequency-weighted across decisions. They are diagnostic evidence paths, not portfolio returns.': '累计因子按决策频次加权，是诊断性的证据路径，并非组合收益率。',
  'The relative-effect dollars are exposure-weighted approximations, not a separately tradable portfolio return.': '相对效果金额是按敞口加权的近似值，并非可单独交易的组合收益。',
  'Shapley attribution, weekly-block bootstrap, and feasible timing randomization are not estimated in V1.': 'V1 尚未估算 Shapley 归因、周区块自助法及可行交易时点随机化。',
  'This audit reports what happened in this history. It never labels the result as proof of an edge.': '本审计只报告这段历史中发生的结果，不会把它称为投资优势的证明。',
  'time-weighted, money in and out removed': '时间加权，已剔除资金进出',
  'net buys of risk assets in range': '区间内风险资产净买入', 'deposits minus withdrawals in range': '区间内存入减取出',
  'portfolio value change': '组合市值变化', 'invested value change': '已投资市值变化',

  // PNL
  'BEST 12': '最佳 12 个', 'WORST 12': '最差 12 个', 'realized, CAD': '已实现，加元', 'BY BUCKET': '按类别', 'BY HOLDING TIME': '按持有时间',
  'days since position opened': '自建仓起的天数', 'HELD': '持有', 'AVG / SELL': '每笔卖出平均', 'WIN %': '胜率', 'ALL POSITIONS': '全部持仓',

  // TRD
  'TRADE BLOTTER': '交易流水', 'native currency · hindsight uses latest close, split-adjusted': '原币种 · 事后对比使用最新收盘价（已复权拆股）',
  'SELLS VS HOLDING (CAD)': '卖出 vs 继续持有（加元）', 'positive = you sold above today’s price': '正数 = 卖出价高于今天价格',
  'BUYS SINCE (CAD)': '买入至今（加元）', 'gain from buy price to today': '从买入价到今天的收益', 'AVERAGING-DOWN BUYS': '摊低成本买入',
  'stock/spec buys >2% below avg cost': '个股/投机买入价低于平均成本 2% 以上',

  // ALOC
  'CASH & CASH ETFS': '现金及现金 ETF', 'INVESTED': '已投资', 'INVESTED MIX VS TARGET': '投资结构 vs 目标',
  'bar = now · white tick = target · $ = amount over (+) or under (−) target': '条形 = 当前 · 白线 = 目标 · $ = 高于（+）或低于（−）目标的金额',
  'BY ACCOUNT': '按账户',

  'CORE CONTRIBUTIONS': '核心定投', 'CORE BUYS / MONTH': '每月核心买入', 'RUN RATE': '年化投入', 'INVESTED IN CORE': '核心累计投入',
  'MONTHS WITHOUT A BUY': '未买入的月份', 'gaps break the habit': '中断会破坏习惯', 'bought every month': '每月都有买入',
  'last 6 months · 3M ': '近 6 个月 · 近 3 个月 ', ' vs previous 3M': ' 对比前 3 个月', 'per month · ': '每月 · ', ' vs prev 3M': ' 对比前 3 个月',
  'last 6 months × 12': '近 6 个月 × 12', 'TRACKS': '跟踪', 'NET INVESTED': '净投入', 'NET SHARES': '净份额',
  'NET COST/SHARE': '每份净成本', 'HELD NOW': '当前持有', 'LAST 6 MO': '近 6 个月', 'TICKER': '代码',
  'net buys per month (buys minus sells), equivalent tickers grouped: VOO+VFV, QQQ+XQQ, XEQT': '每月净买入（买入减卖出），等价标的已合并：VOO+VFV、QQQ+XQQ、XEQT',
  'CORE ETF PURCHASE EVERY MONTH': '每月买入核心 ETF', 'S&P 500': '标普 500', 'NASDAQ 100': '纳斯达克 100', 'ALL-WORLD': '全球市场',

  // RULE
  'CHECKS': '检查项', 'edit thresholds in pipeline/config.json': '在 pipeline/config.json 中修改阈值', '✓ PASS': '✓ 通过', '✕ FAIL': '✕ 未通过',
  'All positions within limit': '所有持仓均在限额内', 'Clean': '无', 'None below threshold': '没有低于阈值的持仓',

  // EVT
  'EVENT': '事件', 'IN': '距今', 'holdings only · ETF ex-dividend dates are projected from past payments': '仅限持仓 · ETF 除息日按历史派息推算',
  'EARNINGS': '财报', 'EX-DIVIDEND': '除息日', 'DIVIDEND PAY': '派息日', 'EX-DIVIDEND (PROJECTED)': '除息日（推算）',

  // INC
  'DIVIDENDS': '股息', 'all time, CAD': '全部时间，加元', 'INTEREST + BONUS': '利息 + 奖励', 'WITHHOLDING TAX': '预扣税',
  'US non-resident tax': '美国非居民税', 'FEES': '费用', 'subscription': '订阅费', 'NET, LAST 12 MO': '近 12 个月净额',
  'NET INCOME BY MONTH': '每月净收益', 'income minus tax and fees, CAD': '收益减去税费，加元', 'DETAIL': '明细', 'MONTH': '月份',
  'DIVIDEND': '股息', 'INTEREST': '利息', 'TAX': '税', 'FEE': '费用', 'NET': '净额',

  // SIM common
  'WHAT-IF MODE': '模拟模式', 'FREEZE': '冻结', 'REMOVE TRADES': '移除交易',
  'stop all trading after a trade or day and let the portfolio ride': '在某笔交易或某天之后停止所有交易，让组合自然运行',
  'remove specific past trades and replay history': '移除指定的历史交易并重放历史',

  // SIM remove
  'TRADES REMOVED': '移除的交易', 'ACTUAL VALUE': '实际市值', 'replayed from your trades': '根据你的交易重放', 'SIMULATED VALUE': '模拟市值',
  'RUNNING…': '计算中…', 'freed cash stays idle': '释放的现金闲置', 'DIFFERENCE': '差额', 'REALIZED P&L ': '已实现盈亏 ',
  'remove past trades and replay history · removed buys shrink later sells of those shares · the freed cash goes to →': '移除历史交易并重放 · 移除买入会相应减少之后卖出的股数 · 释放的现金用于 →',
  'ADD PRESET:': '添加预设：', 'AVG↓ BUYS': '摊低买入', 'CLEAR ALL': '全部清除', 'ACTUAL VS SIMULATED': '实际 vs 模拟',
  'PICK TRADES': '选择交易', 'OUT': '移除', 'WHAT CHANGES TODAY': '今天的变化', 'select trades to run': '选择交易后运行',
  'POSITION': '持仓', 'ACTUAL QTY': '实际数量', 'SIM QTY': '模拟数量', 'VALUE Δ CAD': '市值差（加元）',
  'Tick trades on the left, or use a preset.': '在左侧勾选交易，或使用预设。', 'SHRUNK BECAUSE SHARES WERE REMOVED': '因股份被移除而减少的卖出',
  '−ALL': '−全部',
  'Approximation: other trades are kept exactly as they happened, so the simulation ignores that you might have acted differently with the extra cash or shares. Options without price history are carried at cost.': '近似说明：其他交易保持原样，模拟不考虑你可能会用多出的现金或股份做出不同决定。没有价格历史的期权按成本计。',

  // SIM freeze
  'FREEZE POINT': '冻结点', 'choose a day, or pick a trade below': '选择日期，或在下方选择一笔交易', 'TRADE ✕': '交易 ✕',
  'MONEY ADDED AFTER:': '之后存入的资金：', 'deposits after the freeze arrive and sit as cash': '冻结后的存款到账后保持现金',
  'deposits after the freeze buy XEQT the same day': '冻结后的存款当天买入 XEQT', 'deposits after the freeze buy VOO the same day': '冻结后的存款当天买入 VOO',
  'deposits after the freeze are ignored: compare returns only': '忽略冻结后的存款：只比较收益率', 'SIMULATING…': '模拟中…',
  'FROZEN ON': '冻结日期', 'VALUE AT FREEZE': '冻结时市值', 'same starting line for both paths': '两条路径起点相同', 'VALUE TODAY': '今日市值',
  'actual vs frozen': '实际 vs 冻结', 'actual (frozen excludes new money)': '实际（冻结不含新增资金）', 'FROZEN − ACTUAL, $': '冻结 − 实际，$',
  'gain since freeze, deposits removed': '冻结以来收益，已扣除存入', 'RETURN SINCE FREEZE': '冻结以来收益率', 'actual vs frozen · ': '实际 vs 冻结 · ',
  'Doing nothing would have been better since then.': '从那时起什么都不做会更好。', 'Your trading after this point added value.': '此后你的交易创造了价值。',
  'About even.': '大致持平。', 'SHORT VS LONG TERM': '短期 vs 长期', 'frozen minus actual, time-weighted return': '冻结减实际，时间加权收益率',
  'HORIZONS': '期限', 'HORIZON': '期限', 'ENDS': '截止', 'F − A': '冻结 − 实际', 'F − A $': '冻结 − 实际 $',
  'SINCE THE FREEZE': '冻结以来', 'time-weighted return from the freeze day (XEQT for reference)': '自冻结日起的时间加权收益率（XEQT 作参考）',
  'portfolio value, CAD': '组合市值，加元', 'value, CAD · frozen line excludes money added later': '市值，加元 · 冻结线不含之后新增资金',
  'HINDSIGHT MAP': '事后对比图', 'freeze on each date (weekly) · above 0 = doing nothing from that date would have beaten what you did · click to freeze there': '在每个日期冻结（每周）· 高于 0 = 从该日起什么都不做会跑赢你的实际操作 · 点击在该处冻结',
  'FREEZING WON · 1M': '冻结胜出 · 1个月', 'FREEZING WON · 3M': '冻结胜出 · 3个月', 'FREEZING WON · TO DATE': '冻结胜出 · 至今', 'of freeze dates': '占全部冻结日期',
  'MEDIAN · 3M': '中位数 · 3个月', 'frozen − actual': '冻结 − 实际', 'NEXT 1 MONTH': '之后 1 个月', 'NEXT 3 MONTHS': '之后 3 个月', 'CLICK TO FREEZE HERE': '点击在此冻结',
  'Deposits are ignored so every point compares pure returns. Starts once the portfolio passed $5,000; smaller balances swing too much to compare.': '忽略存款，每个点只比较纯收益率。组合超过 $5,000 后开始计算；余额太小时波动过大，不便比较。',
  'HOLDINGS AT FREEZE': '冻结时持仓', 'left untouched; returns include dividends': '保持不动；收益含股息', 'THEN': '当时', 'YOU HOLD NOW': '你现在持有',
  'FREEZE AFTER A TRADE': '在某笔交易后冻结', 'click a trade to stop right after it': '点击交易，在其之后立即停止',
  'Frozen portfolio: the same shares held untouched with dividends reinvested, cash left as cash (USD still moves with the exchange rate), open options closed at cost, subscription fees still charged, no trades, conversions or transfers.': '冻结组合：持有相同股份不动，股息再投资；现金保持现金（美元仍随汇率变动）；未平仓期权按成本平仓；仍收取订阅费；无交易、换汇或转账。',

  // DATA
  'DUE NOW': '当前待抓取', 'everything is current': '全部已是最新', 'LAST FETCH': '上次抓取', 'REQUESTS TODAY': '今日请求数', '429s, LAST 7D': '近 7 天 429 次数',
  'no throttling seen': '未发生限流', 'slow down: raise REQUEST_GAP': '请放慢：调大 REQUEST_GAP', 'JOB': '任务', 'FETCH HISTORY': '抓取记录',
  'FETCH DUE': '抓取待更新', 'FORCE FULL…': '强制全量…', 'STARTED': '开始时间', 'REQUESTS': '请求数', 'SECONDS': '秒', 'PRICES UPD': '价格更新',
  'SKIPPED': '跳过', 'UPDATED': '已更新', 'CAL CACHED': '日历缓存', 'FX': '汇率', 'ISSUES': '问题', 'forced': '强制', 'REQUEST BUDGET': '请求预算',
  'how fetching stays cheap': '如何控制抓取成本', 'SOURCE': '数据源', 'COST': '成本', 'PACING': '节奏', 'SKIPS': '跳过规则', 'CALENDARS': '日历',
  'BUTTON': '按钮', 'TYPICAL': '典型用量', 'TICKERS': '代码', 'TIER': '层级', 'HELD ': '持有 ', 'BENCHMARK': '基准', 'CLOSED': '已清仓',
  'LAST BAR': '最新K线', 'CHECKED': '检查时间', 'DUE': '待抓取',
  'Yahoo Finance (unofficial, via yfinance) for prices + calendars; Bank of Canada Valet for USD/CAD. Both free, no API key.': '价格和日历来自 Yahoo Finance（非官方，通过 yfinance）；美元/加元汇率来自加拿大银行 Valet。均免费，无需 API 密钥。',
  '$0. The real constraint is Yahoo throttling: it publishes no limit and answers bursts with HTTP 429.': '$0。真正的限制是 Yahoo 限流：它不公布限额，请求过密时返回 HTTP 429。',

  'HOW TO EXPORT FROM WEALTHSIMPLE': '如何从 Wealthsimple 导出', 'activities CSV in four steps · upload it above': '四步导出交易记录 CSV · 然后在上方上传',
  'Open Activity and start the export': '打开 Activity 并开始导出', 'Choose the period': '选择时间范围', 'Pick the accounts and download': '选择账户并下载',
  'Upload the downloaded CSV': '上传已下载的 CSV',
  'In the Wealthsimple desktop web app, select the clock icon in the left sidebar to open **Activity**.': '在 Wealthsimple 电脑网页版中，点击左侧边栏的时钟图标打开 **Activity**（活动）。',
  'On the Activity page, select **Download activities** above the transaction list.': '在 Activity 页面中，点击交易列表上方的 **Download activities**（下载活动）。',
  'Set **Select period** to **Custom period**.': '将 **Select period**（选择期间）设为 **Custom period**（自定义期间）。',
  '**Start date**: a date before your first trade — 2000-01-01 is a safe catch-all. Full history is what lets the app compute cost basis; a partial range still imports and merges.': '**Start date**（开始日期）：早于你第一笔交易的日期——2000-01-01 最保险。完整历史才能算出成本基础；部分区间也可导入并合并。',
  'Leave **End date** as today, then **Next**.': '**End date**（结束日期）保持今天，然后点 **Next**（下一步）。',
  'Tick **All accounts** so every account lands in one file (TFSA, FHSA, RRSP, Non-registered, Crypto).': '勾选 **All accounts**（全部账户），让所有账户导出到一个文件（TFSA、FHSA、RRSP、非注册、加密货币）。',
  'Expand **Closed / Archived** if you once held accounts that are now closed — their trades still affect your history.': '如果曾有已关闭的账户，请展开 **Closed / Archived**（已关闭/归档）——这些交易仍会影响历史。',
  'Select **Download CSV** and wait for the download to finish.': '点击 **Download CSV**，并等待下载完成。',
  'Open your browser downloads and find the newest **activities-export-YYYY-MM-DD.csv** file.': '打开浏览器下载列表，找到最新的 **activities-export-YYYY-MM-DD.csv** 文件。',
  'Drag that file into **DROP CSV EXPORTS HERE** above. If you also have a **holdings-report-YYYY-MM-DD.csv**, upload both together so the app can check current positions against the activity ledger.': '将该文件拖入上方的 **DROP CSV EXPORTS HERE**。如果还有 **holdings-report-YYYY-MM-DD.csv**，请一并上传，以便应用根据交易账本核对当前持仓。',
  'Exports overlap safely: inside the range an export covers it is treated as the truth, so a row the broker later corrects (a settled trade, an added FX rate) replaces the old version instead of doubling up. Rows outside that range are untouched, so a monthly full-history export is the simplest routine.': '导出区间重叠没问题：在导出覆盖的范围内以其为准，券商后续更正的记录（交易结算、补充汇率）会替换旧版本而不会重复计入；范围之外的记录保持不变，因此每月导出一次完整历史是最省心的做法。',

  // IMP
  'ACTIVITY ROWS': '交易记录行数', 'nothing imported yet': '尚未导入', 'HOLDINGS AS OF': '持仓截至', 'latest holdings report': '最新持仓报告',
  'UPLOADS ARCHIVED': '已归档上传', 'originals kept, never modified': '保留原始文件，从不修改', 'IMPORT EXPORTS': '导入导出文件',
  'ACTIVITY-DERIVED HOLDINGS': '根据交易记录推算持仓', 'portfolio panes use transactions plus latest Yahoo prices': '投资组合面板使用交易记录及 Yahoo 最新价格',
  'Estimated mode: open quantities, cash and cost basis are reconstructed from the activity ledger. A holdings report is optional and can later verify the snapshot.': '估算模式：根据完整交易流水重建当前数量、现金及成本基础。持仓报告为可选项，之后可用于核对快照。',
  'Wealthsimple activities export and holdings report, the same CSV formats as before': 'Wealthsimple 交易记录导出和持仓报告，与之前相同的 CSV 格式',
  'DROP CSV EXPORTS HERE': '将 CSV 导出文件拖到这里', 'CHECKING FILES…': '正在检查文件…',
  'or click to choose · activities export and/or holdings report · up to 10 files': '或点击选择 · 交易记录导出和/或持仓报告 · 最多 10 个文件',
  'Overlapping date ranges are fine: rows you already have are skipped.': '日期范围重叠没关系：已有的记录会被跳过。',
  'NEW ACTIVITY ROWS': '新增交易记录', 'HISTORY AFTER': '导入后历史', 'unchanged': '不变', 'NEW SYMBOLS': '新代码', 'prices will be fetched': '将抓取价格',
  'RECONCILIATION': '核对', '✓ MATCHES': '✓ 一致', 'activities vs holdings quantities': '交易记录数量 vs 持仓数量', 'FILES': '文件', 'STATUS': '状态',
  'FILE': '文件', 'TYPE': '类型', 'ROWS': '行数', 'COVERS': '范围', 'NOTES': '备注', '✓ OK': '✓ 正常', '✕ REJECTED': '✕ 已拒绝',
  'ACTIVITIES': '交易记录', 'UNKNOWN': '未知',
  'usually means the two exports were taken on different days; import both from the same day to clear': '通常是两个文件导出日期不同；导入同一天的两个文件即可消除',
  'COMMIT': '提交', 'COMMIT & REBUILD': '提交并重建', 'NOTHING NEW · COMMIT ANYWAY': '没有新内容 · 仍然提交', 'CANCEL': '取消',
  ' Replace holdings even though the file is older': ' 即使文件较旧也替换持仓', 'LAST IMPORT': '上次导入', 'OTHER WAYS IN': '其他导入方式',
  'INBOX': '收件箱', 'CLI': '命令行',
  'Copy CSVs into exports/inbox/ on the server (scp, Syncthing…). They are imported within 5 minutes or on REBUILD; rejected files move to inbox/rejected/.': '将 CSV 复制到服务器的 exports/inbox/（scp、Syncthing…）。5 分钟内或重建时导入；被拒绝的文件移到 inbox/rejected/。',
  'Not a Wealthsimple activities export or holdings report (header does not match)': '不是 Wealthsimple 交易记录导出或持仓报告（表头不匹配）',
  'None of these account IDs match your existing data. Different person?': '这些账户 ID 与现有数据都不匹配。是别人的账户吗？',
  'No "As of" date found; treated as newest': '未找到 "As of" 日期；视为最新', 'File is not UTF-8 or Windows-1252 text': '文件不是 UTF-8 或 Windows-1252 文本',

  'OPTION POSITIONS': '期权持仓', 'CONTRACTS': '合约数', 'PREMIUM PAID': '已付权利金', 'BREAK-EVEN': '盈亏平衡价',
  'UNDERLYING NOW': '标的现价', 'DAYS TO EXPIRY': '距到期', 'EXPIRED': '已到期', 'at expiry': '到期时',
  'in the money ': '实值 ', 'out of the money ': '虚值 ', 'if it expired today: ': '若今天到期：',
  'no underlying price': '无标的价格', 'CONTRACT': '合约', 'STRIKE': '行权价', 'EXPIRY': '到期日', 'PREMIUM': '权利金',
  'IF EXPIRED TODAY': '若今天到期', 'underlying needs ': '标的需变动 ',
  'Contracts have no price history to chart, so the position is held at cost. The curve is the payoff at expiry: intrinsic value minus the premium paid, ignoring any time value left.': '合约没有可绘制的价格历史，因此按成本计价。曲线为到期收益：内在价值减去已付权利金，不计剩余时间价值。',

  // symbol screen
  'CHANGE IN RANGE': '区间涨跌', 'HELD NOW': '当前持有', 'unreal ': '浮动 ',

  // help
  'Focus the command line': '聚焦命令行', 'Back to previous screen': '返回上一页', 'Download only market data that is due, then rebuild': '只下载到期的行情数据，然后重建',
  'Recompute from exports and cached prices (no network)': '用导出文件和缓存价格重新计算（不联网）', 'Fetch history, request budget, per-ticker freshness': '抓取记录、请求预算、各代码的数据新鲜度',
  'Upload new Wealthsimple CSV exports (preview before commit)': '上传新的 Wealthsimple CSV 导出文件（提交前预览）',
  'Open a symbol: price history with your buys ▲ and sells ▼': '打开代码：价格走势及你的买入 ▲ 和卖出 ▼',
  'Use the Yahoo ticker to disambiguate (T = AT&T, T.TO = Telus)': '用 Yahoo 代码区分同名代码（T = AT&T，T.TO = Telus）',
  '/  or start typing': '/  或直接输入', 'NEW EXPORTS': '新导出文件',
  'Drop them into WS/, then REBUILD (or FETCH if prices are due). Thresholds and buckets: pipeline/config.json': '放入 WS/ 后重建（如价格待更新则抓取）。阈值和类别：pipeline/config.json',
  'DATA <GO>  or  0': 'DATA <GO>  或  0', 'Language': '语言', 'Language: English / 中文': '语言：English / 中文',
};

const ZH_PATTERNS = [
  // decision audit
  [/^([A-Z0-9.]+) RETURN$/, '$1 收益率'],
  [/^Security return in CAD minus ([A-Z0-9.]+) return over the same fixed horizon\. Positive means the decision beat the benchmark\.$/, '证券的加元收益减去同期 $1 收益。正值表示该决策跑赢基准。'],
  [/^(\d+)D AVG EXCESS$/, '$1日平均超额'], [/^(\d+)D 10–90% BAND$/, '$1日 10–90% 区间'],
  [/^(\d+) campaigns$/, '$1 个持仓周期'], [/^(\d+)\/(\d+) equity decisions$/, '$1/$2 个股票决策'],
  [/^(\d+) decisions in (\d+) campaigns$/, '$1 个决策，分布于 $2 个持仓周期'],
  [/^(\d+)-trading-day score · slide (\d+) of (\d+) · no look-ahead$/, '$1 个交易日评分 · 第 $2/$3 页 · 无前视偏差'],
  [/^(\d+) SCORES MATURED$/, '$1 个评分到期'], [/^(\d+) NEW DECISIONS$/, '$1 个新决策'], [/^(\d+) PENDING$/, '$1 个待观察'],
  [/^(\d+) on this trading day$/, '此交易日 $1 个'], [/^(\d+) fixed-horizon scores posted today$/, '今日计入 $1 个固定周期评分'],
  [/^The (\d+)-trading-day window from (\d{4}-\d{2}-\d{2}) is complete\. This score is posted today, not on the decision date\.$/, '从 $2 开始的 $1 个交易日观察周期已结束。评分在今天计入，而不是决策当天。'],
  [/^No decision was made and no (\d+)-trading-day score matured\. The accumulated factors carry forward unchanged; (\d+) earlier decisions remain pending\.$/, '今天没有新决策，也没有 $1 个交易日评分到期。累计因子保持不变；此前仍有 $2 个决策待观察。'],
  [/^WITHOUT TOP (\d+)$/, '移除前 $1'],
  [/^(\d+) total · options included in P&L but excluded from timing tests$/, '共 $1 个 · 期权计入盈亏，但不纳入择时测试'],
  [/^Options remain in actual P&L \((\d+) campaigns, (.+)\) but are excluded from equity timing tests without contract history\.$/, '期权仍计入实际盈亏（$1 个持仓周期，$2），但在缺少合约历史价格时不纳入股票择时测试。'],

  // relative time & counts
  [/^(\d+)D AGO$/, '$1天前'], [/^(\d+)H AGO$/, '$1小时前'], [/^(\d+)MIN AGO$/, '$1分钟前'], [/^(\d+)D$/, '$1天'],
  [/^(\d+)M AGO$/, '$1个月前'], [/^(\d+)Y AGO$/, '$1年前'],
  [/^([\d,]+) lines · click a row to open the symbol$/, '$1 行 · 点击行打开代码'],
  [/^(\d+)\/(\d+) PASS$/, '$1/$2 通过'], [/^(\d+) waiting in inbox$/, '$1 个文件在收件箱等待'],
  [/^([\d,]+) REQ$/, '$1 次请求'], [/^(\d+) · (\d+) due$/, '$1 · $2 个待抓取'], [/^(\d+) lines differ$/, '$1 行不同'],
  [/^(\d+) later sells\/transfers shrunk$/, '$1 笔之后的卖出/转出被减少'], [/^(\d+) buys · (\d+) sells \(priced\)$/, '$1 笔买入 · $2 笔卖出（有价格）'],
  [/^(\d+) buys · (\d+) sells$/, '$1 笔买入 · $2 笔卖出'], [/^(\d+) buys · (\d+) sells · (.+)$/, '$1 笔买入 · $2 笔卖出 · $3'],
  [/^(\d+) runs$/, '$1 次运行'], [/^(\d+) req · ([\d.]+)s$/, '$1 次请求 · $2秒'], [/^([\d,]+) duplicates skipped$/, '跳过 $1 条重复'],
  [/^([\d,]+) later trades skipped$/, '跳过之后的 $1 笔交易'], [/^(\d+) with realized P&L$/, '$1 个有已实现盈亏'],
  [/^(\d+) errors$/, '$1 个错误'], [/^([\d,]+) shown · click a row or tick OUT$/, '显示 $1 条 · 点击行或勾选移除'],
  [/^(\d+) trades$/, '$1 笔交易'], [/^(\d+) ISSUES$/, '$1 个问题'], [/^([\d.]+%) of total$/, '占总额 $1'],
  [/^target ([\d.]+%) of invested$/, '目标：投资额的 $1'], [/^now ([\d.]+%) · target ([\d.]+%)$/, '当前 $1 · 目标 $2'],
  [/^cooldown (\d+)s$/, '冷却 $1秒'], [/^current (.+)$/, '当前 $1'], [/^as of (.+)$/, '截至 $1'], [/^preview (\w+)$/, '预览 $1'],
  [/^open options closed at cost (.+)$/, '未平仓期权按成本平仓 $1'], [/^freed cash buys (.+)$/, '释放的现金买入 $1'],
  [/^\+ALL (\d+)$/, '+全部 $1'], [/^\+ (.+)$/, m => '+ ' + tr(m.slice(2))],
  [/^LAST FETCH (.+) · (\d+) REQ · ([\d.]+)s$/, (m, a, b, c) => `上次抓取 ${tr(a)} · ${b} 次请求 · ${c}秒`],
  [/^ · (\d+) ERR$/, ' · $1 个错误'], [/^FETCH · (\d+) DUE$/, '抓取 · $1 个待更新'], [/^FETCH (\d+)s$/, '抓取 $1秒'],
  [/^FETCHING (\d+)\/(.+)$/, '抓取中 $1/$2'], [/^FETCHING… (\d+)s$/, '抓取中… $1秒'],
  [/^Preview ready: \+(\d+) rows$/, '预览就绪：新增 $1 行'], [/^REALIZED (\d{4})$/, '$1 年已实现'],
  [/^([A-Z]+) INSTEAD$/, '改买 $1'], [/^ALL DEPOSITS IN (.+)$/, '全部存款买入 $1'], [/^SAME MONEY IN (.+)$/, '同样资金买入 $1'], [/^(.+) WITH THE SAME MONEY$/, '$1（相同资金）'], [/^(.+) WITH THE SAME MONEY$/, '$1（相同资金）'], [/^(.+) WITH THE SAME MONEY$/, '$1（相同资金）'], [/^(.+) TOTAL RETURN \(CAD\)$/, '$1 总收益率（加元）'],
  [/^([A-Z0-9.\-]+) <EQUITY>$/, '$1 <股票>'], [/^SIMULATE WITHOUT (.+) →$/, '模拟去掉 $1 →'], [/^Remove (BUY|SELL) (.+)$/, (m, s, r) => `移除 ${tr(s)} ${r}`],
  [/^(.+): also (.+)$/, '$1：另有 $2'], [/^UNKNOWN: (.+) — type HELP$/, '未知命令：$1 — 输入 HELP'],
  [/^NO PRICE HISTORY FOR (.+)$/, '$1 没有价格历史'], [/^NO PRICE DATA FOR (.+)$/, '没有 $1 的价格数据：'], [/^LOADING (.+)…$/, '正在加载 $1…'],
  [/^COULD NOT LOAD DATA \((.+)\)$/, '无法加载数据（$1）'],
  [/^(FETCH|REBUILD|IMPORT) OK · (.+)$/, (m, k, rest) => `${tr(k)} 成功 · ${rest}`], [/^(FETCH|REBUILD|IMPORT) FAILED · (.*)$/, (m, k, rest) => `${tr(k)} 失败 · ${rest}`],
  [/^IMPORT FAILED · (.*)$/, '导入失败 · $1'], [/^COMMIT FAILED · (.*)$/, '提交失败 · $1'], [/^SIMULATION FAILED: (.*)$/, '模拟失败：$1'],
  [/^(\w+)…$/, (m, w) => ZH[w] ? ZH[w] + '中…' : m],
  [/^~([\d.]+)s · (\d+) prices · (\d+) calendars( · FX)?$/, (m, a, b, c, fx) => `约${a}秒 · ${b} 个价格 · ${c} 个日历${fx ? ' · 汇率' : ''}`],
  [/^gross (.+) · tax\/fees (.+)$/, '总额 $1 · 税费 $2'], [/^to (\S+) · actual (.+) · frozen (.+) · (.+)$/, '至 $1 · 实际 $2 · 冻结 $3 · $4'],
  [/^Archived: (.+)$/, '已归档：$1'],
  [/^\+([\d,]+) activity rows · ([\d,]+) duplicates skipped · holdings (updated|unchanged) · (.+)$/,
    (m, a, d, h, j) => `新增 ${a} 条交易记录 · 跳过 ${d} 条重复 · 持仓${h === 'updated' ? '已更新' : '不变'} · ${j === 'no rebuild' ? '未重建' : j.replace(' started', ' 已开始')}`],
  [/^split-adjusted close( \(USD; CAD-booked trades converted\))? · ▲ your buys · ▼ your sells$/, (m, u) => `拆股调整后收盘价${u ? '（美元；加元记账的交易已换算）' : ''} · ▲ 你的买入 · ▼ 你的卖出`],

  // rules (server)
  [/^SINGLE STOCK ≤ (.+) OF TOTAL$/, '单一股票 ≤ 总资产的 $1'], [/^SPECULATIVE ≤ (.+) OF INVESTED$/, '投机仓位 ≤ 投资额的 $1'],
  [/^NO LEVERAGED\/THEMATIC ETFS IN TFSA$/, 'TFSA 不持有杠杆/主题 ETF'], [/^REVIEW POSITIONS ≤ (.+)$/, '复查亏损 ≤ $1 的持仓'],
  [/^NO AVERAGING DOWN \(LAST (\d+)D\)$/, '不摊低成本（近 $1 天）'], [/^TFSA TRADES ≤ (\d+)\/MONTH$/, 'TFSA 每月交易 ≤ $1 笔'],
  [/^(\d+) over limit$/, '$1 个超限'], [/^Now (.+)$/, '当前 $1'], [/^(\d+) held$/, '持有 $1 个'], [/^(\d+) need a decision$/, '$1 个需要决定'],
  [/^(\d+) buys below average cost$/, '$1 笔低于平均成本的买入'], [/^(\d{4}-\d{2}): (\d+) trades$/, '$1：$2 笔交易'],
  [/^last 6 months: (\d)\/6 with a purchase$/, '近 6 个月：$1/6 个月有买入'], [/^(\d+) months tracked$/, '已跟踪 $1 个月'],

  // import (server)
  [/^Older than current holdings \((.+)\); will be skipped unless forced$/, '早于当前持仓（$1）；除非强制，否则跳过'],
  [/^line (\d+): unfamiliar activity_type '(.+)' \(kept\)$/, "第 $1 行：未知的 activity_type '$2'（已保留）"],
  [/^line (\d+): (.+)$/, '第 $1 行：$2'],
  [/^(.+): activities give (.+), holdings say (.+)$/, '$1：交易记录为 $2，持仓报告为 $3'], [/^(.+): activities give (.+), not in holdings$/, '$1：交易记录为 $2，持仓报告中没有'],

  // freeze labels (server)
  [/^frozen at the end of (.+)$/, '冻结于 $1 收盘'], [/^end of (.+)$/, '$1 收盘'],
  [/^frozen after (\S+ \S+) (.+) (BUY|SELL) (.+)$/, (m, when, acct, side, sym) => `冻结于 ${when} ${tr(acct)} ${tr(side)} ${sym} 之后`],
  [/^after (\S+ \S+) (.+) (BUY|SELL) (.+)$/, (m, when, acct, side, sym) => `${when} ${tr(acct)} ${tr(side)} ${sym} 之后`],

  // data screen prose with numbers
  [/^([\d.]+)s between requests, sequential \(never parallel\), so a burst is at most ~2–3 requests\/second\. On a 429: pause (\d+)s and retry once; a second 429 stops the run and keeps cached data\.$/,
    '请求间隔 $1 秒，顺序执行（从不并行），突发最多约每秒 2–3 次。遇到 429：暂停 $2 秒并重试一次；第二次 429 则停止并保留缓存数据。'],
  [/^A ticker is only requested when a newer daily close should exist than its last check\. Held \+ benchmarks: every session \((\d+)\)\. Closed positions \((\d+)\): weekly, staggered by weekday\. Delisted: weekly re-check\.$/,
    '只有在应有比上次检查更新的收盘价时才请求该代码。持仓 + 基准：每个交易日（$1 个）。已清仓（$2 个）：每周一次，按工作日错开。已退市：每周复查。'],
  [/^Stocks: once per (\d+)h\. ETFs have none, remembered for 30 days \(ETF ex-dividend dates are projected locally\)\.$/,
    '个股：每 $1 小时一次。ETF 没有日历，记住 30 天（ETF 除息日在本地推算）。'],
  [/^(\d+)s cooldown after each fetch; only one job at a time\. REBUILD never touches the network\.$/, '每次抓取后冷却 $1 秒；同一时间只运行一个任务。重建从不联网。'],
  [/^~30–40 requests per trading day \(~15 held\/benchmark, ~16 staggered closed, 1 FX, a few calendars\), ~2 on weekends \(crypto\)\. Full forced re-download: ~(\d+) requests, ~45s\.$/,
    '每个交易日约 30–40 次请求（约 15 个持仓/基准、约 16 个错开的已清仓、1 次汇率、少量日历），周末约 2 次（加密货币）。强制全量重新下载：约 $1 次请求，约 45 秒。'],
  [/^Force a full re-download of every ticker\?\nThat is about (\d+) requests to Yahoo\.$/, '强制重新下载所有代码？\n这将向 Yahoo 发送约 $1 次请求。'],
  [/^(.+) · Portfolio Terminal$/, (m, t) => `${tr(t)} · 投资终端`],
  [/^USDCAD (.+)$/, '美元/加元 $1'],
  [/^(Crypto|Non-registered) ([^·]+)$/, (m, a, rest) => `${ZH[a]} ${rest}`],
  [/^(\d{4}-\d{2}-\d{2}) (Crypto|Non-registered) (.+)$/, (m, d, a, rest) => `${d} ${ZH[a]} ${rest}`],
];

function tr(text) {
  if (LANG === 'en' || text == null) return text;
  const str = String(text);
  if (!/[A-Za-z]/.test(str)) return str;
  if (Object.prototype.hasOwnProperty.call(ZH, str)) return ZH[str];
  for (const [re, rep] of ZH_PATTERNS) {
    if (re.test(str)) return str.replace(re, rep);
  }
  if (str.includes(' · ')) {  // composite labels: translate each part
    const parts = str.split(' · '), done = parts.map(tr);
    if (done.some((p, i) => p !== parts[i])) return done.join(' · ');
  }
  return str;
}

function setLang(lang) {
  if (!LANGS[lang]) return;
  LANG = lang;
  try { localStorage.setItem('lang', lang); } catch {}
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
}
document.documentElement.lang = LANG === 'zh' ? 'zh-CN' : 'en';
