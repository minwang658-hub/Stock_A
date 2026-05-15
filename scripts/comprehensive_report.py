#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股持仓综合分析报告 - 六大模块标准版
持仓情况 / 市场行情 / 财务基本面 / 资金动向 / 盘手综合判断 / 操作建议
数据源：腾讯财经（实时行情）+ Tushare（财务）+ 东方财富（资金流）
"""

import sys, os, json
from datetime import datetime
from pathlib import Path

# ============ 路径配置（使用相对路径）============
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
REPORT_DIR = BASE_DIR / "reports"
DATA_DIR = BASE_DIR / "data"

REPORT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
from comprehensive_data import (
    fetch_all, tx_realtime_full, tx_daily, calc_rsi, calc_ema,
    calc_bollinger, calc_pivot, daily_to_weekly
)
from portfolio_daily import run_daily_snapshot
from tushare_data import get_financial, get_capital_flow
from recommendation import generate_recommendation_report, run_auto_scan, load_recommendations

NAME_MAP = {
    '000001': '平安银行', '000651': '格力电器', '002415': '海康威视',
    '002594': '比亚迪', '600036': '招商银行', '600115': '东方航空',
    '600160': '中化国际', '600660': '福耀玻璃', '601398': '工商银行',
    '603005': '晶方科技', '603019': '中科曙光',
}
SECTOR_MAP = {
    '000651': '家电', '002594': '汽车', '002415': '电子/AI监控',
    '600036': '银行', '601398': '银行', '000001': '银行',
    '600115': '航空', '600160': '化工', '600660': '汽车零部件',
    '603005': '半导体封测', '603019': '服务器/AI算力',
}

# ============ 数据校验模块 ============
class ValidationReport:
    """校验报告生成器 - 追踪数据准确性和模块加载状态"""
    def __init__(self):
        self.warnings = []      # 警告（不影响运行）
        self.errors = []        # 错误（可能影响结果）
        self.module_status = {} # 模块加载状态
        self.data_anomalies = [] # 数据异常

    def add_warning(self, msg, severity="⚠️"):
        self.warnings.append(f"{severity} {msg}")
        print(f"  {severity} {msg}")

    def add_error(self, msg, severity="❌"):
        self.errors.append(f"{severity} {msg}")
        print(f"  {severity} {msg}")

    def add_module_ok(self, module_name, details=""):
        self.module_status[module_name] = "✅ 正常"
        if details:
            self.module_status[module_name] += f" ({details})"

    def add_module_fail(self, module_name, error):
        self.module_status[module_name] = f"❌ 失败: {error}"
        self.add_error(f"模块 {module_name} 加载失败: {error}")

    def add_anomaly(self, stock_code, field, expected, actual, severity="⚠️"):
        msg = f"{severity} {stock_code} {field}异常: 期望{expected}, 实际{actual}"
        self.data_anomalies.append(msg)
        self.add_warning(msg, severity)

    def is_critical_error(self):
        """关键错误：数据严重不准确，不应生成报告"""
        return len([e for e in self.errors if "关键" in e]) > 0

    def get_summary(self):
        """生成校验摘要"""
        lines = []
        lines.append("\n" + "="*50)
        lines.append("📋 **数据校验报告**")
        lines.append("="*50)

        # 模块状态
        if self.module_status:
            lines.append("\n**模块状态：**")
            for name, status in self.module_status.items():
                lines.append(f"- {name}: {status}")

        # 数据异常
        if self.data_anomalies:
            lines.append(f"\n**数据异常 ({len(self.data_anomalies)} 项)：**")
            for a in self.data_anomalies[:10]:  # 最多显示10项
                lines.append(f"- {a}")
            if len(self.data_anomalies) > 10:
                lines.append(f"- ... 还有 {len(self.data_anomalies)-10} 项")

        # 警告
        if self.warnings:
            lines.append(f"\n**⚠️ 警告 ({len(self.warnings)} 项)：**")
            for w in self.warnings[:5]:
                lines.append(f"- {w}")
            if len(self.warnings) > 5:
                lines.append(f"- ... 还有 {len(self.warnings)-5} 项")

        # 错误
        if self.errors:
            lines.append(f"\n**❌ 错误 ({len(self.errors)} 项)：**")
            for e in self.errors:
                lines.append(f"- {e}")

        lines.append("\n" + "="*50)
        return "\n".join(lines)


def validate_snapshot(snapshot, today):
    """校验快照数据有效性"""
    vr = ValidationReport()

    if not snapshot:
        vr.add_error("快照数据为空", severity="❌")
        return vr

    snap_date = snapshot.get('date', '')
    if snap_date != today:
        vr.add_error(f"快照日期过期: {snap_date}, 今天: {today}", severity="❌")
    else:
        vr.add_module_ok(f"快照日期", f"✓ {snap_date}")

    stocks = snapshot.get('stocks', [])
    if not stocks:
        vr.add_error("快照无持仓数据", severity="❌")
        return vr

    vr.add_module_ok(f"持仓数据", f"{len(stocks)} 只股票")

    # 检查每只股票的数据准确性
    for s in stocks:
        code = s.get('code', 'Unknown')
        qty = s.get('qty', 0)
        cost = s.get('cost', 0)
        cost_total = s.get('cost_total', 0)
        market_value = s.get('market_value', 0)
        floating_pnl = s.get('floating_pnl', 0)

        # 数量校验
        if qty <= 0:
            vr.add_anomaly(code, "持仓数量", ">0", qty)
        elif qty % 100 != 0:
            vr.add_anomaly(code, "持仓数量", "100的整数倍", qty, "⚠️ A股最小单位")

        # 成本校验
        if cost <= 0:
            vr.add_anomaly(code, "成本价", ">0", cost, "⚠️")

        # 市值校验
        if market_value <= 0:
            vr.add_anomaly(code, "市值", ">0", market_value, "⚠️")

        # 计算一致性校验
        expected_cost_total = round(cost * qty, 2)
        if abs(cost_total - expected_cost_total) > 0.01:
            vr.add_anomaly(code, "成本总额", f"{expected_cost_total}", cost_total, "⚠️ 计算不一致")

        # 盈亏合理性校验（涨跌幅超过20%视为异常）
        if cost > 0:
            price = market_value / qty if qty > 0 else 0
            pct_change = (price - cost) / cost * 100
            if abs(pct_change) > 50:
                vr.add_anomaly(code, "盈亏比例", "<±50%", f"{pct_change:.1f}%", "⚠️ 涨跌幅过大")

    # 汇总校验
    total_cost = snapshot.get('total_cost', 0)
    total_mkt = snapshot.get('total_market_value', 0)
    if total_cost <= 0:
        vr.add_error("总成本为0或负数，数据异常", severity="❌")
    if total_mkt <= 0:
        vr.add_error("总市值为0或负数，数据异常", severity="❌")

    return vr


def validate_realtime_data(rt_map, portfolio):
    """校验实时行情数据"""
    vr = ValidationReport()

    missing_data = []
    stale_data = []
    zero_price = []

    for p in portfolio:
        code = p['code']
        rt = rt_map.get(code, {})

        if not rt:
            missing_data.append(code)
            continue

        price = rt.get('price', 0)
        pct = rt.get('pct', 0)

        if price <= 0:
            zero_price.append(code)
            vr.add_anomaly(code, "现价", ">0", price, "⚠️")

    if missing_data:
        vr.add_error(f"缺少 {len(missing_data)} 只股票行情数据: {', '.join(missing_data)}")
    else:
        vr.add_module_ok("行情数据", f"{len(rt_map)} 只")

    if zero_price:
        vr.add_warning(f"部分股票价格异常: {', '.join(zero_price)}")

    return vr


def validate_financial_data(fin_data, portfolio):
    """校验财务数据完整性"""
    vr = ValidationReport()

    if not fin_data:
        vr.add_warning("财务数据为空，可能影响评分准确性")
        return vr

    # 检查关键字段
    has_pe = sum(1 for d in fin_data.values() if d.get('pe') is not None)
    has_pb = sum(1 for d in fin_data.values() if d.get('pb') is not None)
    has_roe = sum(1 for d in fin_data.values() if d.get('roe') is not None)

    vr.add_module_ok("财务数据", f"PE:{has_pe} PB:{has_pb} ROE:{has_roe}")

    if has_pe < len(portfolio) * 0.5:
        vr.add_warning(f"PE数据覆盖率仅 {has_pe}/{len(portfolio)}，财务评分可能偏低")

    return vr


# ============ 评分体系 ============
def tech_score(pct, daily):
    """技术面评分（0-100）- 使用周线RSI确保稳定性"""
    if not daily or len(daily) < 15:
        return {'score': 50, 'level': '⚪数据不足', 'signals': [], 'rsi': None, 'rsi_weekly': None, 'rsi_daily': None}
    
    closes = [d['close'] for d in daily]
    score = 50
    signals = []
    
    # === 周线RSI（主用，更稳定）===
    rsi_weekly = None
    rsi_daily = None
    
    try:
        weekly = daily_to_weekly(daily)
        if len(weekly) >= 15:
            w_closes = [d['close'] for d in weekly]
            rsi_weekly = calc_rsi(w_closes)
    except Exception:
        pass  # 如果周线转换失败，使用日线
        if rsi_weekly:
            signals.append(f'RSI(周)={rsi_weekly}')
            if rsi_weekly < 30:
                score += 10
                signals.append('RSI周超卖✅')
            elif rsi_weekly > 75:
                score -= 6
                signals.append('RSI周超买⚠️')
            elif rsi_weekly > 65:
                score += 4
                signals.append('RSI周强势')
            elif rsi_weekly < 45:
                score -= 3
    
    # === 日线RSI（辅助参考）===
    rsi_daily = calc_rsi(closes)
    
    # === 均线排列（MA5 vs MA20）===
    if len(closes) >= 20:
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        if ma5 > ma20 * 1.02:
            score += 8
            signals.append('日线多头排列✅')
        elif ma5 < ma20 * 0.98:
            score -= 6
            signals.append('日线空头排列⚠️')
    
    # === 今日涨跌 ===
    if pct > 5:
        score += 10
        signals.append(f'今日强势+{pct:.1f}%')
    elif pct > 2:
        score += 5
        signals.append(f'今日上涨+{pct:.1f}%')
    elif pct > 0:
        score += 1
    elif pct < -5:
        score -= 10
        signals.append(f'今日大跌{pct:.1f}%')
    elif pct < -2:
        score -= 5
        signals.append(f'今日下跌{pct:.1f}%')
    
    # === 5日动量 ===
    if len(closes) >= 5:
        recent_chg = (closes[-1] - closes[-5]) / closes[-5] * 100
        if recent_chg > 10:
            score += 6
            signals.append(f'5日涨幅+{recent_chg:.1f}%🚀')
        elif recent_chg < -10:
            score -= 6
            signals.append(f'5日跌幅{recent_chg:.1f}%📉')
    
    # === 评分收敛 ===
    score = max(0, min(100, score))
    if score >= 70:
        level = '🟢强势'
    elif score >= 55:
        level = '🟡偏强'
    elif score >= 40:
        level = '🟠中性'
    else:
        level = '🔴偏弱'
    
    return {
        'score': score,
        'level': level,
        'signals': signals,
        'rsi': rsi_weekly,
        'rsi_weekly': rsi_weekly,
        'rsi_daily': rsi_daily
    }


def fin_score(fin):
    """
    财务面评分（0-100）
    以 annual（income 年报基准）为评分数据源
    增加数据来源标签显示
    """
    score = 50
    signals = []
    if not fin:
        return {'score': 50, 'level': '⚪无数据', 'signals': [], 'data_year': '', 'is_stale': False}
    
    ann = fin.get('annual', {})
    # 获取数据年份标签
    data_year = ann.get('end_date', '')[:4] if ann.get('end_date') else ''
    
    roe = ann.get('roe', 0) or 0
    gross_margin = ann.get('gross', 0) or 0
    rev_chg = ann.get('rev_yoy', 0) or 0
    profit_chg = ann.get('ni_yoy', 0) or 0

    # 检查数据是否过期（用2024年或更早数据）
    is_stale = data_year in ['2023', '2024'] if data_year else False
    if is_stale:
        signals.append(f'⚠️数据为{data_year}年')
    
    # ROE评分
    if roe > 15:
        score += 15
        signals.append(f'ROE={roe:.1f}%✅')
    elif roe > 10:
        score += 8
        signals.append(f'ROE={roe:.1f}%良好')
    elif roe > 5:
        score += 2
    elif roe > 0:
        pass
    else:
        score -= 10
        signals.append(f'ROE={roe:.1f}%🔴亏损')

    # 毛利率评分
    if gross_margin > 30:
        score += 6
        signals.append(f'毛利率={gross_margin:.1f}%✅')
    elif gross_margin > 15:
        score += 3

    # 净利润增速评分
    if profit_chg > 20:
        score += 12
        signals.append(f'净利+{profit_chg:.1f}%✅')
    elif profit_chg > 5:
        score += 6
        signals.append(f'净利+{profit_chg:.1f}%')
    elif profit_chg > 0:
        score += 3
    elif profit_chg < -20:
        score -= 12
        signals.append(f'净利{profit_chg:.1f}%⚠️')
    elif profit_chg < 0:
        score -= 6
        signals.append(f'净利{profit_chg:.1f}%')

    # 营收增速评分
    if rev_chg > 10:
        score += 8
        signals.append(f'营收+{rev_chg:.1f}%✅')
    elif rev_chg > 0:
        score += 3
    elif rev_chg < -10:
        score -= 8
        signals.append(f'营收{rev_chg:.1f}%⚠️')
    elif rev_chg < 0:
        score -= 4
    
    # 如果数据过期，降低评分置信度
    if is_stale:
        score -= 5

    score = max(0, min(100, score))
    if score >= 70:
        level = '🟢优秀'
    elif score >= 55:
        level = '🟡良好'
    elif score >= 40:
        level = '🟠一般'
    else:
        level = '🔴较差'
    
    return {
        'score': score,
        'level': level,
        'signals': signals,
        'data_year': data_year,
        'is_stale': is_stale
    }


def flow_score(flow):
    """
    资金面评分（0-100）
    增加数据源状态检测和数据缺失时的降级处理
    """
    # 数据缺失时降级处理
    if not flow:
        return {'score': 50, 'level': '⚪资金流数据缺失', 'signals': ['⚠️数据源不稳定'], 'data_status': 'missing'}
    
    ddx5 = flow.get('ddx5', 0) or 0
    ddx10 = flow.get('ddx10', 0) or 0
    main_in_yi = flow.get('main_in_yi', 0) or 0
    
    # 检查数据有效性（DDX为0可能是数据缺失）
    data_valid = (ddx5 != 0 or ddx10 != 0 or main_in_yi != 0)
    signals = []
    
    if not data_valid:
        signals.append('⚠️资金流数据不稳定')
    
    score = 50

    # 5日DDX
    if ddx5 > 0.3:
        score += 15
        signals.append(f'5日DDX={ddx5:+.2f}✅机构大幅流入')
    elif ddx5 > 0.1:
        score += 10
        signals.append(f'5日DDX={ddx5:+.2f}✅')
    elif ddx5 < -0.5:
        score -= 15
        signals.append(f'5日DDX={ddx5:+.2f}⚠️机构大幅流出')
    elif ddx5 < -0.2:
        score -= 10
        signals.append(f'5日DDX={ddx5:+.2f}⚠️')
    elif ddx5 < 0:
        score -= 4

    # 10日DDX
    if ddx10 > 0.3:
        score += 12
        signals.append(f'10日DDX={ddx10:+.2f}✅')
    elif ddx10 > 0.1:
        score += 8
        signals.append(f'10日DDX={ddx10:+.2f}✅')
    elif ddx10 < -0.5:
        score -= 12
        signals.append(f'10日DDX={ddx10:+.2f}⚠️机构持续流出')
    elif ddx10 < -0.2:
        score -= 8
        signals.append(f'10日DDX={ddx10:+.2f}⚠️')
    elif ddx10 < 0:
        score -= 4

    # 主力净流入
    if main_in_yi > 5:
        score += 8
        signals.append(f'主力净流入{main_in_yi:.1f}亿✅')
    elif main_in_yi > 1:
        score += 5
        signals.append(f'主力净流入{main_in_yi:.1f}亿')
    elif main_in_yi < -5:
        score -= 8
        signals.append(f'主力净流出{abs(main_in_yi):.1f}亿⚠️')
    elif main_in_yi < -1:
        score -= 5
    
    # 数据不稳定时降低置信度
    if not data_valid:
        score = max(30, score - 10)  # 最低不低于30分

    score = max(0, min(100, score))
    if score >= 68:
        level = '🟢偏多'
    elif score >= 52:
        level = '🟡中性'
    elif score >= 38:
        level = '🟠偏空'
    else:
        level = '🔴看空'
    
    return {
        'score': score,
        'level': level,
        'signals': signals,
        'data_status': 'valid' if data_valid else 'unstable'
    }


def combined(tech, fin, flow, pnl_pct=0):
    """综合评分：技术40% + 财务25% + 资金20% + 持仓15%"""
    t = tech.get('score', 50) * 0.40
    f = fin.get('score', 50) * 0.25
    c = flow.get('score', 50) * 0.20
    # 持仓分：盈利越好分越高
    pl = min(100, max(0, 50 + pnl_pct * 2)) * 0.15
    total = round(t + f + c + pl)
    if total >= 75: label = '🟢强力买入'
    elif total >= 62: label = '🟡建议持有'
    elif total >= 50: label = '🟠谨慎持有'
    else: label = '🔴建议减仓'
    return {'score': total, 'label': label}

# ============ 读取快照（优先） ============
def load_latest_snapshot():
    """
    从 daily_portfolio.json 读取最新快照
    - 必须存在
    - 必须是今天（当天日期）
    否则报错提醒用户
    """
    global DATA_DIR
    SNAPSHOT_FILE = DATA_DIR / "daily_portfolio.json"
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not os.path.exists(SNAPSHOT_FILE):
        print("""
❌ 错误：daily_portfolio.json 不存在

   请先运行 portfolio_daily.py 生成快照：
   cd mimi_stock/scripts
   python3 portfolio_daily.py
""")
        return None
    
    try:
        with open(SNAPSHOT_FILE, encoding='utf-8') as f:
            snaps = json.load(f)
        if not snaps:
            print("❌ 错误：daily_portfolio.json 为空")
            return None
        
        # 取最新快照
        latest = snaps[-1]
        snap_date = latest.get('date', '')
        
        if snap_date != today:
            print(f"""
❌ 错误：快照已过期（最后快照：{snap_date}，今天：{today}）

   请先运行 portfolio_daily.py 更新快照：
   cd mimi_stock/scripts
   python3 portfolio_daily.py
""")
            return None
        
        return latest
    except Exception as e:
        print(f"❌ 错误：读取快照失败 - {e}")
        return None


# ============ 主程序 ============
def generate_comprehensive_report():
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")
    
    # ===== 新增：从快照读取持仓 =====
    snapshot = load_latest_snapshot()
    if not snapshot:
        print("  ⚠️ 快照不存在或为空，使用portfolio.csv直接分析")
        # 回退到直接读取portfolio.csv
        from portfolio_daily import load_portfolio
        portfolio = load_portfolio()
        if not portfolio:
            print("  ❌ 无持仓数据")
            return None
        # 获取实时行情
        codes = [p['code'] for p in portfolio]
        print(f"  📡 正在从腾讯财经拉取 {len(codes)} 只股票实时数据...")
        from comprehensive_data import tx_realtime_full
        tx_codes = []
        for code in codes:
            if code.startswith('6'):
                tx_codes.append('sh' + code)
            else:
                tx_codes.append('sz' + code)
        rt_data = tx_realtime_full(tx_codes)
        
        # 构建模拟快照数据
        total_cost = sum(p['cost'] * p['qty'] for p in portfolio)
        total_mkt = 0
        holdings = []
        for p in portfolio:
            code = p['code']
            price = rt_data.get(code, {}).get('price', p['cost'])
            mkt_val = price * p['qty']
            total_mkt += mkt_val
            holdings.append({
                'code': code,
                'name': NAME_MAP.get(code, code),
                'cost': p['cost'],
                'qty': p['qty'],
                'price': price,
                'market_value': mkt_val,
                'pnl': mkt_val - (p['cost'] * p['qty']),
                'pnl_pct': (price - p['cost']) / p['cost'] * 100 if p['cost'] > 0 else 0
            })
        
        snapshot = {
            'date': today,
            'total_cost': total_cost,
            'total_market_value': total_mkt,
            'floating_pnl': total_mkt - total_cost,
            'cumulative_realized': 0,
            'stocks': holdings
        }

    # ============ 数据校验：快照 ============
    print(f"\n🔍 校验快照数据...")
    vr_snapshot = validate_snapshot(snapshot, today)
    if vr_snapshot.is_critical_error():
        print(f"  ❌ 快照数据严重错误，报告生成终止")
        return None

    # 从快照提取持仓数据
    portfolio = []
    for s in snapshot.get('stocks', []):
        code = s.get('code', '')
        if code:
            portfolio.append({
                'code': code,
                'name': NAME_MAP.get(code, code),
                'cost': s.get('cost', 0),
                'qty': s.get('qty', 0),
            })

    if not portfolio:
        print("❌ 持仓为空"); return None

    # 拉取实时行情（腾讯财经）
    print(f"\n📡 开始拉取 {len(portfolio)} 只股票实时行情...")
    rt_map, daily_map, _, flow_em, idx_map = fetch_all(portfolio)  # fin/flow 改用 Tushare

    # ============ 数据校验：实时行情 ============
    vr_rt = validate_realtime_data(rt_map, portfolio)

    # 使用 Tushare 获取财务数据（替代东财，更稳定）
    print(f"  📋 拉取财务数据（Tushare）...")
    fin_data_ts = {}
    try:
        codes_list = [p['code'] for p in portfolio]
        fin_data_ts = get_financial(codes_list)
        print(f"    Tushare 财务: {len(fin_data_ts)} 只有效")
    except Exception as e:
        print(f"    ⚠️ Tushare 财务失败: {e}, 使用东财数据")
        fin_data_ts = {}

    # ============ 数据校验：财务数据 ============
    vr_fin = validate_financial_data(fin_data_ts, portfolio)

    # 使用 Tushare 获取资金流向
    print(f"  💰 拉取资金流向（Tushare）...")
    flow_data_ts = {}
    try:
        flow_data_ts = get_capital_flow(codes_list)
        print(f"    Tushare 资金流: {len(flow_data_ts)} 只有效")
    except Exception as e:
        print(f"    ⚠️ Tushare 资金流失败: {e}, 使用东财数据")
        flow_data_ts = {}

    # 合并：只使用 Tushare 三层数据（东财已废弃）
    fin_data = {}
    for code in [p['code'] for p in portfolio]:
        fin_data[code] = fin_data_ts.get(code, {})

    flow_data = {}
    for code in [p['code'] for p in portfolio]:
        ts_d = flow_data_ts.get(code, {})
        # flow only from Tushare
        if ts_d.get('ddx5') is not None or ts_d.get('main_in_yi') is not None:
            flow_data[code] = ts_d
        else:
            flow_data[code] = {}

    # 大盘分析
    sz = idx_map['上证指数'].get('pct', 0)
    cy = idx_map['创业板指'].get('pct', 0)
    hs300 = idx_map['沪深300'].get('pct', 0)
    if sz > 1 or cy > 1.5: mkt_cond = '🟢大盘强势'; mkt_adj = 5
    elif sz > 0 or cy > 0: mkt_cond = '🟡大盘震荡偏强'; mkt_adj = 2
    elif sz < -1 or cy < -1.5: mkt_cond = '🔴大盘弱势'; mkt_adj = -5
    elif sz < 0 or cy < 0: mkt_cond = '🟠大盘震荡偏弱'; mkt_adj = -2
    else: mkt_cond = '⚪大盘震荡'; mkt_adj = 0

    # 逐股分析
    results = []
    for p in portfolio:
        code, name, cost, qty = p['code'], p['name'], p['cost'], p['qty']
        rt = rt_map.get(code, {})
        daily = daily_map.get(code, [])
        fin = fin_data.get(code, {})
        flow = flow_data.get(code, {})
        
        if not rt:
            print(f"  ⚠️ {name}({code}): 无实时数据"); continue

        price = rt.get('price', 0)
        pct = rt.get('pct', 0)
        closes = [d['close'] for d in daily]
        
        ts = tech_score(pct, daily)
        fs = fin_score(fin)
        fls = flow_score(flow)
        cb = combined(ts, fs, fls, rt.get('pnl_pct', 0))
        
        # 布林带
        bb = calc_bollinger(closes) if len(closes) >= 20 else None
        # 枢轴点
        pivots = calc_pivot(rt.get('high', price), rt.get('low', price), price)
        # 周线
        weekly = daily_to_weekly(daily)
        
        results.append({
            'code': code, 'name': name,
            'rt': rt, 'daily': daily, 'fin': fin, 'flow': flow,
            'tech': ts, 'fin_score': fs, 'flow_score': fls,
            'combined': cb, 'bb': bb, 'pivots': pivots, 'weekly': weekly,
        })
        
        # 信号打印
        sig_str = ' | '.join(ts['signals'][:3])
        print(f"  ✅ {name}({code}): ¥{price:.2f} {pct:+.2f}% "
              f"技{ts['score']} 财{fs['score']} 资{fls['score']} 综合{cb['score']} "
              f"→ {cb['label']}")

    if not results:
        print("❌ 无有效数据"); return None

    # 排序
    results.sort(key=lambda x: x['combined']['score'], reverse=True)

    # ============ 生成报告 ============
    total_cost = sum(r['rt']['cost_total'] for r in results)
    total_mkt = sum(r['rt']['mkt_total'] for r in results)
    total_pnl = total_mkt - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0

    lines = []
    lines.append(f"# 📊 **A股持仓综合分析报告**\n")
    lines.append(f"**📅 {today} {now_str}** | 数据源：腾讯财经（实时行情）+ Tushare（财务）+ 东方财富（资金流）\n")

    # =================== 模块一：持仓情况 ===================
    lines.append("---\n## 一、持仓情况总览\n")
    # 表头
    lines.append("| 股票 | 代码 | 现价 | 今日涨跌 | 持仓股数 | 成本价 | 总成本 | 市值 | 盈亏额 | 盈亏% | 财务年 | 信号 |")
    lines.append("|------|------|------|---------|---------|--------|--------|------|--------|-------|------|")
    for r in results:
        rt = r['rt']
        pnl = rt.get('pnl', 0)
        pnl_pct = rt.get('pnl_pct', 0)
        sig = "🟢盈利" if pnl_pct > 0 else "🔴亏损"
        lines.append(f"| {r['name']} | {r['code']} | ¥{rt['price']:.2f} | "
                    f"{rt['pct']:+.2f}% | {rt['qty']}股 | ¥{rt['cost']:.3f} | "
                    f"¥{rt['cost_total']:,.0f} | ¥{rt['mkt_total']:,.0f} | "
                    f"{'+¥' if pnl>=0 else '¥'}{pnl:,.0f} | "
                    f"{'+' if pnl_pct>=0 else ''}{pnl_pct:.1f}% | {sig} |")

    lines.append(f"\n**💼 账户总览：**")
    lines.append(f"- 总成本：¥{total_cost:,.0f}")
    lines.append(f"- 总市值：¥{total_mkt:,.0f}")
    lines.append(f"- **总体盈亏：{'+' if total_pnl>=0 else ''}¥{total_pnl:,.0f}（{'+' if total_pnl_pct>=0 else ''}{total_pnl_pct:.1f}%）**")
    gainers = [r for r in results if r['rt']['pnl'] > 0]
    losers = [r for r in results if r['rt']['pnl'] <= 0]
    lines.append(f"- 🟢 盈利股：{len(gainers)}只 | 🔴 亏损股：{len(losers)}只")

    # =================== 模块一·扩展：收益分析 ===================
    # 构造市值字典（供快照模块用）
    mkt_vals = {}
    for p in portfolio:
        code, qty = p['code'], p['qty']
        rt = rt_map.get(code, {})
        mkt_vals[code] = rt.get('price', p['cost'])

    # 拍摄今日快照 + 分析收益
    snap, analysis, err = None, None, None
    try:
        snap = run_daily_snapshot(mkt_vals, today)
        if snap:
            analysis = {
                'total_pnl':       snap['total_pnl'],
                'total_return_pct': snap['total_pnl'] / max(snap['total_cost'], 1) * 100,
                'unrealized_pnl':  snap['floating_pnl'],
                'realized_pnl':    snap['cumulative_realized'],
                'annual_return_pct': 0,
                'max_drawdown_pct': 0,
                'sharpe_ratio':    0,
                'win_rate':        0,
                'days':            1,
                'total_cost':      snap['total_cost'],
                'total_mkt':       snap['total_market_value'],
                'holdings':        [
                    {'code': s['code'], 'cost_total': s['cost_total'],
                     'mkt': s['market_value'], 'pnl': s['floating_pnl'],
                     'pnl_pct': s['floating_pnl'] / max(snap['total_cost'], 1) * 100}
                    for s in snap['stocks']
                ],
                'unrealized_pct':  snap['floating_pnl'] / max(snap['total_cost'], 1) * 100,
            }
            err = None
        else:
            err = "portfolio.csv 为空"
    except Exception as e:
        snap, analysis, err = None, None, str(e)

    if analysis and not err:
        lines.append("\n---\n## 一·扩展：收益分析\n")

        # 核心指标卡
        total_pnl_a = analysis['total_pnl']
        total_return_pct = analysis['total_return_pct']
        unreal_pnl = analysis['unrealized_pnl']
        real_pnl = analysis['realized_pnl']
        annual_ret = analysis['annual_return_pct']
        mdd = analysis['max_drawdown_pct']
        sharpe = analysis['sharpe_ratio']
        win_rate = analysis['win_rate']
        days = analysis['days']
        total_cost_a = analysis['total_cost']
        total_mkt_a = analysis['total_mkt']

        pnl_sign = '+' if total_pnl_a >= 0 else '-'
        ret_sign = '+' if total_return_pct >= 0 else ''
        annual_sign = '+' if annual_ret >= 0 else ''

        # 评分（收益率角度）
        if total_return_pct > 10: ret_grade = '🟢优秀'
        elif total_return_pct > 0: ret_grade = '🟡盈利'
        elif total_return_pct > -10: ret_grade = '🟠一般'
        else: ret_grade = '🔴较差'

        lines.append(f"| 指标 | 数值 | 评价 |")
        lines.append(f"|------|------|------|")
        lines.append(f"| 💰 总收益(浮动+已确认) | {pnl_sign}¥{abs(total_pnl_a):,.0f}（{'+' if total_return_pct>=0 else ''}{total_return_pct:.1f}%）| {ret_grade} |")
        lines.append(f"| 📊 总成本 → 当前市值 | ¥{total_cost_a:,.0f} → ¥{total_mkt_a:,.0f} | — |")
        unreal_sign = '+' if unreal_pnl >= 0 else '-'
        lines.append(f"| 💹 浮动收益 | {unreal_sign}¥{abs(unreal_pnl):,.0f}（{'+' if unreal_pnl>=0 else ''}{analysis['unrealized_pct']:.1f}%）| — |")
        lines.append(f"| ✅ 已确认收益 | {'+' if real_pnl>=0 else ''}¥{abs(real_pnl):,.0f} | {'有实际卖出' if real_pnl != 0 else '暂无卖出记录'} |")
        if days < 7:
            lines.append(f"| 📐 年化收益率 | {annual_sign}{abs(annual_ret):.0f}% | ⚠️数据不足7天，参考性低 |")
        else:
            lines.append(f"| 📐 年化收益率 | {annual_sign}{annual_ret:.1f}% | {'优秀' if annual_ret > 15 else ('良好' if annual_ret > 5 else ('偏差' if annual_ret > 0 else '亏损'))} |")
        if days < 7:
            lines.append(f"| 📉 最大回撤 | -{mdd:.1f}% | ⚠️数据不足7天，参考性低 |")
        else:
            lines.append(f"| 📉 最大回撤 | -{mdd:.1f}% | {'小回撤' if mdd < 5 else ('中等' if mdd < 15 else '大幅回撤')} |")
        lines.append(f"| ⚡ 夏普比率 | {sharpe:.2f} | {'优秀' if sharpe > 1 else ('良好' if sharpe > 0.5 else ('一般' if sharpe > 0 else '较差'))} |")
        lines.append(f"| 🎯 胜率 | {win_rate:.0f}% | {'高' if win_rate > 50 else '低'} |")
        lines.append(f"| 📅 记录天数 | {days}天 | — |")

        # 盈亏排名
        holdings_sorted = sorted(analysis['holdings'], key=lambda x: x['pnl_pct'], reverse=True)
        lines.append(f"\n**📋 持仓盈亏排名（从大到小）：**")
        lines.append(f"| 排名 | 股票 | 持仓成本 | 当前市值 | 浮动盈亏 | 收益率 |")
        lines.append(f"|------|------|---------|---------|---------|--------|")
        for rank, h in enumerate(holdings_sorted, 1):
            pnl_sign_h = '+' if h['pnl'] >= 0 else ''
            pct_sign = '+' if h['pnl_pct'] >= 0 else ''
            emoji = '🟢' if h['pnl'] > 0 else '🔴'
            lines.append(f"| {emoji} {rank} | {h['code']} | ¥{h['cost_total']:,.0f} | ¥{h['mkt']:,.0f} | {pnl_sign_h}¥{abs(h['pnl']):,.0f} | {pct_sign}{h['pnl_pct']:.1f}% |")

        # 月度收益
        monthly = analysis.get('monthly_returns', [])
        if len(monthly) > 1:
            lines.append(f"\n**📅 月度收益：**")
            lines.append(f"| 月份 | 月涨跌幅 | 期初市值 | 期末市值 |")
            lines.append(f"|------|---------|---------|---------|")
            for m in monthly:
                sign = '+' if m['return_pct'] >= 0 else ''
                lines.append(f"| {m['month']} | {sign}{m['return_pct']:.1f}% | ¥{m['start_mkt']:,.0f} | ¥{m['end_mkt']:,.0f} |")

        # 收益诊断
        lines.append(f"\n**💡 收益诊断：**")
        if analysis['unrealized_pct'] < -15:
            lines.append(f"- 🔴 浮动亏损超过-15%，注意止损纪律")
        if analysis['realized_pnl'] > 0:
            lines.append(f"- ✅ 已实现收益 ¥{analysis['realized_pnl']:,.0f}，恭喜有实际盈利")
        if mdd < 3 and days > 7:
            lines.append(f"- 🟢 最大回撤仅-{mdd:.1f}%，风控良好")
        if sharpe > 1 and days > 30:
            lines.append(f"- ⚡ 夏普比率{sharpe:.2f}，风险调整后收益优秀")
        if win_rate < 30 and len(analysis['holdings']) > 5:
            lines.append(f"- ⚠️ 胜率{win_rate:.0f}%偏低，建议减少持仓集中度")
        if not monthly or len(monthly) <= 1:
            lines.append(f"- ⏳ 每日快照记录刚开始，建议坚持每日运行以积累数据")

        lines.append(f"\n> 📝 **每日快照说明**：每日运行综合报告时自动记录当日市值，用于追踪收益率曲线和最大回撤。运行越久，数据越准确。")
    else:
        lines.append(f"\n---\n## 一·扩展：收益分析\n")
        lines.append(f"⚠️ 收益数据暂缺（{err or '请运行综合报告生成快照'}）")

    # =================== 模块二：市场行情 ===================
    lines.append("\n---\n## 二、市场行情\n")

    # === 周线压力位 / 支撑位分析 ===
    lines.append("**📅 周线关键价位分析：**\n")
    lines.append("| 股票 | 现价 | 压力位1 | 压力位2 | 支撑位1 | RSI(周) | 趋势 |")
    lines.append("|------|------|---------|---------|---------|--------|------|")

    weekly_sorted = sorted(results, key=lambda x: x['combined']['score'], reverse=True)
    for r in weekly_sorted:
        price = r['rt']['price']
        daily = r['daily']
        weekly = daily_to_weekly(daily) if daily else []
        closes = [d['close'] for d in daily] if daily else []
        tech = r['tech']

        # 周线数据
        if len(weekly) >= 5:
            w_closes = [d['close'] for d in weekly[-5:]]
            w_high = max(d['high'] for d in weekly[-5:])
            w_low = min(d['low'] for d in weekly[-5:])
            w_close = w_closes[-1]
            pivots = calc_pivot(w_high, w_low, w_close)
            rsi_w = calc_rsi(w_closes) if len(w_closes) >= 15 else None
        elif len(daily) >= 20:
            # 用日线模拟周线（前20日高低）
            recent = daily[-20:]
            w_high = max(d['high'] for d in recent)
            w_low = min(d['low'] for d in recent)
            w_close = recent[-1]['close']
            pivots = calc_pivot(w_high, w_low, w_close)
            rsi_w = calc_rsi(closes[-20:]) if len(closes) >= 20 else None
        else:
            pivots = {'r1': None, 'r2': None, 's1': None, 's2': None}
            rsi_w = None

        # 趋势判断
        if rsi_w and rsi_w > 65: trend = "📈强势"
        elif rsi_w and rsi_w < 35: trend = "📉弱势"
        elif rsi_w and rsi_w > 50: trend = "🟡偏强"
        elif rsi_w and rsi_w < 50: trend = "🟠偏弱"
        else: trend = "⚪中性"

        r1 = f"¥{pivots['r1']:.2f}" if pivots.get('r1') else "—"
        r2 = f"¥{pivots['r2']:.2f}" if pivots.get('r2') else "—"
        s1 = f"¥{pivots['s1']:.2f}" if pivots.get('s1') else "—"
        s2 = f"¥{pivots['s2']:.2f}" if pivots.get('s2') else "—"
        rsi_str = f"{rsi_w:.0f}" if rsi_w else "—"

        # 信号
        sig = ""
        if price > pivots.get('r1', 0) > 0: sig = "🔥突破"
        elif price < pivots.get('s1', 0) > 0: sig = "⚠️跌破"

        lines.append(f"| {r['name']}({r['code']}) | ¥{price:.2f} | {r1} | {r2} | {s1} | {s2} | {rsi_str} | {trend}{sig} |")

    lines.append("")
    lines.append("**🌍 今日大盘：**")
    for name, idx in [('上证指数', '上证指数'), ('深证成指', '深证成指'),
                      ('创业板指', '创业板指'), ('沪深300', '沪深300')]:
        d = idx_map.get(name, {})
        if d:
            lines.append(f"- {name}: ¥{d.get('price', 0):.2f}（{d.get('pct', 0):+.2f}%）")
    lines.append(f"\n**市场状态：** {mkt_cond}（大盘调整分：{mkt_adj:+d}）")

    lines.append("\n**📈 个股行情明细：**")
    lines.append("| 股票 | 现价 | 今高 | 今低 | PE | PB | 市值(亿) | 52周相对位置 | 技术分 | 技术信号 |")
    lines.append("|------|------|------|------|----|----|---------|-------------|--------|---------|")
    for r in results:
        rt = r['rt']
        closes = [d['close'] for d in r['daily']]
        # 52周高低（从今日价和涨跌幅推算）
        pre = rt.get('pre_close', rt['price'])
        pct_52w = rt.get('high_52w', 0) or 0
        # 52周高 = pre / (1-pct/100) 如果 pct_52w > 0
        high52 = low52 = "—"
        if pct_52w > 0:
            high52 = round(pre * (1 + pct_52w/100 * 1.5), 2)
        elif pct_52w < 0:
            low52 = round(pre * (1 + pct_52w/100 * 0.5), 2)
        sig_short = ' | '.join(r['tech']['signals'][:2])
        pe_v = f"{rt.get('pe', 0):.1f}" if rt.get('pe', 0) > 0 else "亏损"
        mkt = f"{rt.get('mktcap_yi', 0):.0f}" if rt.get('mktcap_yi', 0) > 0 else "—"
        lines.append(f"| {r['name']}({r['code']}) | ¥{rt['price']:.2f} | "
                    f"¥{rt.get('high', 0):.2f} | ¥{rt.get('low', 0):.2f} | "
                    f"{pe_v} | {rt.get('pb', 0):.2f} | {mkt} | "
                    f"高¥{high52} | {r['tech']['score']} | {sig_short} |")

    # 布林带
    bb_results = [r for r in results if r['bb']]
    if bb_results:
        lines.append("\n**🎯 布林带位置：**")
        lines.append("| 股票 | 现价 | 下轨 | 中轨 | 上轨 | 当前位置 |")
        lines.append("|------|------|------|------|------|---------|")
        for r in bb_results:
            bb = r['bb']
            p = r['rt']['price']
            if p > bb['upper']: pos = '🔥突破上轨（强势）'
            elif p < bb['lower']: pos = '📉跌破下轨（超卖）'
            elif p > bb['mid']: pos = '✅中轨上方（偏强）'
            else: pos = '⚠️中轨下方（偏弱）'
            lines.append(f"| {r['name']} | ¥{p:.2f} | ¥{bb['lower']:.2f} | ¥{bb['mid']:.2f} | ¥{bb['upper']:.2f} | {pos} |")

    # =================== 模块三：财务基本面 ===================
    lines.append("\n---\n## 三、财务基本面\n")
    fin_sorted = sorted(results, key=lambda x: x['fin_score']['score'], reverse=True)

    def fY(v): return ("\u00a5%.0f亿" % (v/1e8)) if (v and v > 0) else "—"
    def fP(v): return ("%+.1f%%" % v) if (v and v != 0) else "—"
    def fR(v): return ("%.1f%%" % v) if (v and v > 0) else "—"

    # ── 第一层：income 年报基准 ──
    lines.append("**【一】income 年报基准**（以 income 表最新年报为营收/净利润基准，ROE/毛利率来自同期 fina_indicator）\n")
    lines.append("| 股票 | 报告期 | 营业收入 | 营收同比 | 净利润 | 净利同比 | ROE | 毛利率 | 净利率 | 财务分 |")
    lines.append("|------|--------|---------|---------|---------|---------|------|--------|--------|--------|")
    for r in fin_sorted:
        fin = r['fin']
        fs = r['fin_score']
        ann = fin.get('annual', {})
        end_date = ann.get('end_date', '')
        ann_label = (end_date[:4] + "年报") if end_date else "—"
        rev = ann.get('revenue', 0) or 0
        ni = ann.get('n_income', 0) or 0
        lines.append("| %s(%s) | %s | %s | %s | %s | %s | %s | %s | %s | **%d** |" % (
            r['name'], r['code'], ann_label,
            fY(rev), fP(ann.get('rev_yoy', 0) or 0),
            fY(ni), fP(ann.get('ni_yoy', 0) or 0),
            fR(ann.get('roe', 0) or 0),
            fP(ann.get('gross', 0) or 0),
            fP(ann.get('net_margin', 0) or 0),
            fs['score']))

    # ── 第二层：最新 fina_indicator ──
    lines.append("\n**【二】最新 fina_indicator**（fina_indicator 最新一期，可能为预估或已出正式年报）\n")
    lines.append("| 股票 | 报告期 | ROE | ROE同比 | 毛利率 | 净利率 | 资产负债率 | 营收同比 | 净利同比 |")
    lines.append("|------|--------|-----|---------|---------|---------|-----------|---------|---------|")
    for r in fin_sorted:
        fin = r['fin']
        lf = fin.get('latest_fi', {})
        end_date = lf.get('end_date', '')
        fi_label = (end_date[:4] + ("年报" if end_date.endswith("1231") else "季报")) if end_date else "—"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r['name'], fi_label,
            fR(lf.get('roe', 0) or 0),
            fP(lf.get('roe_yoy', 0) or 0),
            fP(lf.get('gross', 0) or 0),
            fP(lf.get('net_margin', 0) or 0),
            fP(lf.get('debt', 0) or 0),
            fP(lf.get('or_yoy', 0) or 0),
            fP(lf.get('ni_yoy', 0) or 0)))

    # ── 第三层：最新季报累计 ──
    lines.append("\n**【三】最新季报累计**（income + fina_indicator 最新季度，与去年同期季报比较）\n")
    lines.append("| 股票 | 季报期间 | 季报营收 | 营收同比(季) | 季报净利 | 净利同比(季) | ROE(季) | 毛利率(季) |")
    lines.append("|------|---------|---------|------------|---------|------------|---------|-----------|")
    for r in fin_sorted:
        fin = r['fin']
        q = fin.get('quarter', {})
        if not q:
            lines.append("| %s | — | — | — | — | — | — | — |" % r['name'])
            continue
        pl = q.get('period_label', q.get('end_date', '—'))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r['name'], pl,
            fY(q.get('revenue', 0) or 0),
            fP(q.get('rev_yoy', 0) or 0),
            fY(q.get('n_income', 0) or 0),
            fP(q.get('ni_yoy', 0) or 0),
            fR(q.get('roe', 0) or 0),
            fP(q.get('gross', 0) or 0)))

    lines.append("\n**📋 财务详细：**")
    for r in fin_sorted:
        fin = r['fin']
        fs = r['fin_score']
        ann = fin.get('annual', {})
        lf = fin.get('latest_fi', {})
        q = fin.get('quarter', {})
        sigs = fs['signals'] or []
        # 补充资产负债率
        debt = ann.get('debt', 0) or lf.get('debt', 0) or 0
        if debt:
            sigs.append(f'资产负债率={debt:.0f}%')
        # 标注财务期间
        ann_end = ann.get('end_date', '')
        fi_end = lf.get('end_date', '')
        if ann_end and fi_end and ann_end != fi_end:
            sigs.append(f'⚠️年报FY{ann_end[:4]}，FI最新{fi_end[:4]}')
        elif ann_end:
            sigs.append(f'财务期=FY{ann_end[:4]}')
        lines.append(f"- **{r['name']}** [{fs['score']}分 {fs['level']}]: " + ' | '.join(sigs))

    # =================== 模块四：资金动向 ===================
    lines.append("\n---\n## 四、资金动向\n")
    lines.append("| 股票 | 5日DDX | 10日DDX | 5日主力净流入(亿) | 融资余额(亿) | 资金评分 | 资金信号 |")
    lines.append("|------|---------|---------|---------------|-------------|--------|---------|")
    flow_sorted = sorted(results, key=lambda x: x['flow_score']['score'], reverse=True)
    for r in flow_sorted:
        fl = r['flow']
        fls = r['flow_score']
        ddx5 = fl.get('ddx5', 0) or 0
        ddx10 = fl.get('ddx10', 0) or 0
        main_in = fl.get('main_in_yi', 0) or 0
        margin = fl.get('margin_yi', 0) or 0
        ddx5_str = f"{ddx5:+.2f}"
        ddx10_str = f"{ddx10:+.2f}"
        main_str = f"{main_in:+.2f}" if main_in != 0 else "—"
        margin_str = f"{margin:.1f}" if margin > 0 else "—"
        sig_short = fls['signals'][0] if fls['signals'] else '—'
        lines.append(f"| {r['name']}({r['code']}) | {ddx5_str} | {ddx10_str} | {main_str} | {margin_str} | "
                    f"**{fls['score']}** | {fls['level']} |")

    lines.append("\n**💡 资金解读：**")
    pos_flow = [r for r in flow_sorted if (r['flow'].get('ddx5', 0) or 0) > 0.1]
    neg_flow = [r for r in flow_sorted if (r['flow'].get('ddx5', 0) or 0) < -0.2]
    if pos_flow: lines.append(f"✅ 资金流入（DDX>+0.1）：{', '.join(r['name'] for r in pos_flow)}")
    if neg_flow: lines.append(f"⚠️ 资金流出（DDX<-0.2）：{', '.join(r['name'] for r in neg_flow)}")
    if not pos_flow and not neg_flow: lines.append("中性：资金无明显方向")

    # =================== 模块五：盘手综合判断 ===================
    lines.append("\n---\n## 五、盘手综合判断\n")
    lines.append("**综合评分体系：** 技术面(40%) + 财务面(25%) + 资金面(20%) + 持仓盈亏(15%)\n")
    lines.append("| 股票 | 综合分 | 评级 | 技术分 | 财务分 | 资金分 | 主要判断依据 |")
    lines.append("|------|--------|------|--------|--------|--------|-------------|")
    for r in results:
        cb = r['combined']
        tech = r['tech']
        fin_s = r['fin_score']
        flow_s = r['flow_score']
        pnl_pct = r['rt'].get('pnl_pct', 0)
        # 主要判断依据
        reasons = []
        if tech['score'] >= 65: reasons.append(f"技术强势({tech['score']})")
        elif tech['score'] < 45: reasons.append(f"技术偏弱({tech['score']})")
        if fin_s['score'] >= 65: reasons.append(f"基本面优({fin_s['score']})")
        elif fin_s['score'] < 45: reasons.append(f"基本面弱({fin_s['score']})")
        if flow_s['score'] >= 60: reasons.append(f"资金流入")
        elif flow_s['score'] < 40: reasons.append(f"资金流出")
        if pnl_pct > 10: reasons.append(f"持仓盈利{pnl_pct:.0f}%")
        elif pnl_pct < -10: reasons.append(f"持仓亏损{pnl_pct:.0f}%")
        reason_str = ' / '.join(reasons[:2]) if reasons else '—'
        lines.append(f"| {r['name']}({r['code']}) | **{cb['score']}** | {cb['label']} | "
                    f"{tech['score']} | {fin_s['score']} | {flow_s['score']} | {reason_str} |")

    lines.append("\n**📝 盘手深度解读：**\n")
    for r in results:
        rt = r['rt']
        cb = r['combined']
        tech = r['tech']
        fin_s = r['fin_score']
        flow_s = r['flow_score']
        pnl_pct = rt.get('pnl_pct', 0)
        price = rt['price']
        
        # 生成个股简评
        comments = []
        if cb['score'] >= 70:
            comments.append("综合评分优秀，多维度共振，偏多")
        elif cb['score'] >= 60:
            comments.append("综合评分良好，基本面和技术面支撑，持仓合理")
        elif cb['score'] >= 50:
            if flow_s['score'] < 45: comments.append("资金面偏弱，需关注短期走势")
            if pnl_pct < -10: comments.append("持仓亏损较大，注意止损")
            if not comments: comments.append("综合评分中性，震荡格局，观望为主")
        else:
            comments.append("综合评分偏弱，多项指标走弱，建议减仓观察")
        if tech['rsi'] and tech['rsi'] < 35: comments.append(f"RSI={tech['rsi']}超卖，可能有反弹")
        if tech['rsi'] and tech['rsi'] > 75: comments.append(f"RSI={tech['rsi']}超买，注意回调风险")
        
        comment = '；'.join(comments)
        sig = "🟢" if cb['score'] >= 70 else ("🟡" if cb['score'] >= 55 else "🔴")
        lines.append(f"- **{sig} {r['name']}({r['code']})** ¥{price:.2f} {rt['pct']:+.2f}%：{comment}")

    # =================== 模块六：操作建议 ===================
    lines.append("\n---\n## 六、操作建议\n")
    lines.append("**🚨 止损止盈三维判断（价格 + 技术 + 资金）**\n")
    
    stop_list = [r for r in results if r['rt'].get('pnl_pct', 0) < -13]
    caution_list = [r for r in results if -13 <= r['rt'].get('pnl_pct', 0) <= -8]
    hold_list = [r for r in results if r['rt'].get('pnl_pct', 0) > -8]
    
    if stop_list:
        lines.append("**🔴 建议止损（亏损超过-13%，基本面/资金面偏弱）：**")
        for r in stop_list:
            pnl_pct = r['rt']['pnl_pct']
            price = r['rt']['price']
            stop_price = round(price * (1 + (pnl_pct + 15) / 100 / 0.85), 2)  # 模拟回到-15%的价格
            lines.append(f"- **{r['name']}({r['code']})** 亏损{pnl_pct:.1f}% | "
                        f"现价¥{price:.2f} | 止损参考¥{stop_price:.2f}（若反弹至成本价附近） | "
                        f"综合评分{r['combined']['score']}({r['combined']['label']})")

    if caution_list:
        lines.append("\n**🟡 关注（亏损-8%~-13%，观察是否企稳）：**")
        for r in caution_list:
            pnl_pct = r['rt']['pnl_pct']
            lines.append(f"- **{r['name']}({r['code']})** 亏损{pnl_pct:.1f}% | "
                        f"现价¥{r['rt']['price']:.2f} | "
                        f"技术{r['tech']['level']} | 资金{r['flow_score']['level']} | "
                        f"综合{r['combined']['label']} → 持有观察，跌破-15%止损")

    if hold_list:
        lines.append("\n**✅ 可持有（浮亏可控或盈利）：**")
        for r in hold_list:
            pnl_pct = r['rt']['pnl_pct']
            price = r['rt']['price']
            if pnl_pct > 0:
                # 止盈建议
                take_profit_price = round(price * 1.15, 2)  # 涨15%后考虑止盈
                lines.append(f"- **{r['name']}({r['code']})** 盈利{pnl_pct:.1f}% | "
                            f"现价¥{price:.2f} | 建议持有，涨至¥{take_profit_price:.2f}附近考虑分批止盈")
            else:
                lines.append(f"- **{r['name']}({r['code']})** 亏损{pnl_pct:.1f}% | "
                            f"现价¥{price:.2f} | "
                            f"综合{r['combined']['label']} → 持有，耐心等待修复")

    # 综合建议
    lines.append("\n**💡 综合仓位建议：**")
    pos_cnt = len([r for r in results if r['combined']['score'] >= 60])
    neg_cnt = len([r for r in results if r['combined']['score'] < 50])
    if pos_cnt >= len(results) * 0.6 and mkt_adj >= 0:
        lines.append(f"🟢 大盘{mkt_cond}，{pos_cnt}只股票综合评分≥60，持仓偏多头，可维持或适度加仓")
    elif neg_cnt >= len(results) * 0.5 or mkt_adj <= -3:
        lines.append(f"🔴 大盘{mkt_cond}，{neg_cnt}只股票综合评分<50，建议减仓防守，等待企稳")
    else:
        lines.append(f"🟡 大盘{mkt_cond}，持仓分化，精选个股操作，整体标配观望")

    # =================== 模块七：推荐关注 ===================
    try:
        rec_lines = generate_recommendation_report()
        lines.append("\n---\n")
        lines.append(rec_lines)
        vr_snapshot.add_module_ok("推荐关注模块", "正常" if "暂无推荐" not in rec_lines else "无数据")
    except Exception as e:
        import traceback
        lines.append(f"\n---\n## 七·推荐关注\n*推荐模块加载失败: {e}*\n```\n{traceback.format_exc()}\n```")
        vr_snapshot.add_module_fail("推荐关注模块", str(e))

    # =================== 模块八：V3推荐股票 ===================
    try:
        from recommendation_v3 import run_v3_scan, save_v3_recommendations, generate_v3_report
        # 先运行V3扫描并保存
        v3_results = run_v3_scan(top_n=20)
        save_v3_recommendations(v3_results)
        v3_lines = generate_v3_report()
        lines.append("\n---\n")
        lines.append(v3_lines)
        vr_snapshot.add_module_ok("V3推荐模块", f"生成 {len(v3_results) if v3_results else 0} 条推荐")
    except Exception as e:
        import traceback
        lines.append(f"\n---\n## 八·推荐股票（V3）\n*V3推荐模块加载失败: {e}*\n```\n{traceback.format_exc()}\n```")
        vr_snapshot.add_module_fail("V3推荐模块", str(e))

    # =================== 附录：评分说明 ===================
    lines.append("\n---\n## 附录：评分体系说明\n")
    lines.append("| 维度 | 权重 | 数据来源 | 关键指标 |")
    lines.append("|------|------|---------|---------|")
    lines.append("| 技术面 | 40% | 腾讯财经日K | 涨跌、RSI、均线、布林带 |")
    lines.append("| 财务面 | 25% | Tushare年报 | PE、PB、ROE、毛利率、净利率、营收增速、净利增速 |")
    lines.append("| 资金面 | 20% | 东方财富资金流 | 5日/10日DDX、主力净流入、融资余额 |")
    lines.append("| 持仓盈亏 | 15% | 成本价vs现价 | 盈亏比例影响综合分 |")
    lines.append("| 大盘调整 | ±5 | 腾讯财经指数 | 上证+创业板+沪深300平均涨跌 |")

    lines.append(f"\n---\n*数据来源：腾讯财经（实时行情/日K）+ Tushare（财务年报）+ 东方财富（资金流）| "
                f"报告生成：{now_str} | 仅供参考，不构成投资建议*")

    # ============ 添加校验报告 ============
    # 合并所有校验报告
    all_vr = ValidationReport()
    if 'vr_snapshot' in dir():
        for name, status in vr_snapshot.module_status.items():
            all_vr.module_status[name] = status
        all_vr.warnings.extend(vr_snapshot.warnings)
        all_vr.errors.extend(vr_snapshot.errors)
        all_vr.data_anomalies.extend(vr_snapshot.data_anomalies)
    if 'vr_rt' in dir():
        for name, status in vr_rt.module_status.items():
            all_vr.module_status[name] = status
        all_vr.warnings.extend(vr_rt.warnings)
        all_vr.errors.extend(vr_rt.errors)
        all_vr.data_anomalies.extend(vr_rt.data_anomalies)
    if 'vr_fin' in dir():
        for name, status in vr_fin.module_status.items():
            all_vr.module_status[name] = status
        all_vr.warnings.extend(vr_fin.warnings)
        all_vr.errors.extend(vr_fin.errors)
        all_vr.data_anomalies.extend(vr_fin.data_anomalies)

    # 添加校验摘要到报告
    lines.append(all_vr.get_summary())

    report = '\n'.join(lines)

    # 保存报告
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"综合分析-{today}.md")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)

    # 打印校验摘要到控制台
    print(all_vr.get_summary())
    print(f"\n✅ 综合报告已生成: {path}")
    return path

if __name__ == "__main__":
    generate_comprehensive_report()