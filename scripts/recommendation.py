#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推荐股票模块
- 自动选股扫描 + 评分
- 目标价/止损价计算
- 有效期管理
- 推荐池文件 recommendation.csv
"""

import csv, json, time, sys, io
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RECOMMEND_FILE = DATA_DIR / "recommendation.csv"
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"

TRADE_LOG_FILE  = DATA_DIR / "trade_log.csv"

# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────

def nv(v):
    return v is not None and str(v) not in ('', 'nan', 'None', '-')

def now_str():
    return datetime.now().strftime('%Y-%m-%d')

def days_between(date_str, days):
    d = datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=days)
    return d.strftime('%Y-%m-%d')

# ─────────────────────────────────────────────
# 推荐类型 & 有效期
# ─────────────────────────────────────────────

STOCK_TYPES = {
    '超跌反弹': 30,
    '价值投资': 90,
    '周期复苏': 60,
    '技术突破': 30,
}

def determine_type(fin_data, daily_closes, rsi, recent_pct):
    """
    推荐类型判断 + 基础过滤
    增加基本面过滤，排除高风险股票
    """
    # 基础过滤：排除亏损股和高负债
    ann = (fin_data.get('annual') or {}) if fin_data else {}
    roe = ann.get('roe') or 0
    ni_yoy = ann.get('ni_yoy') or 0
    gross = ann.get('gross') or 0
    debt_ratio = ann.get('debt', 0) or 0  # 资产负债率
    
    # 过滤条件
    if roe < 0:
        return None  # 亏损股排除
    if debt_ratio > 90:
        return None  # 高负债排除
    if ni_yoy < -50:
        return None  # 净利润暴跌排除
    
    # 确定类型
    if roe > 15 and ni_yoy > 10:
        return '价值投资'
    if rsi and rsi < 30:
        return '超跌反弹'
    if recent_pct and recent_pct < -15:
        return '超跌反弹'
    if rsi and rsi < 40:
        return '超跌反弹'
    return '技术突破'

def calc_target_stop(entry_price, stock_type):
    if stock_type == '超跌反弹':
        target = entry_price * 1.20; stop = entry_price * 0.92
    elif stock_type == '价值投资':
        target = entry_price * 1.25; stop = entry_price * 0.85
    elif stock_type == '周期复苏':
        target = entry_price * 1.30; stop = entry_price * 0.85
    else:
        target = entry_price * 1.15; stop = entry_price * 0.92
    risk = round((target - entry_price) / entry_price * 100, 1)
    rr = abs(round((target - entry_price) / (entry_price - stop), 1)) if entry_price != stop else 0
    return round(target, 2), round(stop, 2), risk, rr

# ─────────────────────────────────────────────
# 持仓股 & 已清仓股
# ─────────────────────────────────────────────

def get_watched_codes():
    codes = set()
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, encoding='utf-8') as f:
            for line in f:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 1 and parts[0].isdigit() and len(parts[0]) == 6:
                    codes.add(parts[0])
    if TRADE_LOG_FILE.exists():
        text = TRADE_LOG_FILE.read_text(encoding='utf-8-sig')
        if text.strip():
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                code = row.get('代码', '').strip()
                if code.isdigit() and len(code) == 6:
                    codes.add(code)
    return codes

# ─────────────────────────────────────────────
# 推荐文件读写
# ─────────────────────────────────────────────

FIELDNAMES = [
    'code', 'name', 'added_date', 'type', 'entry_price',
    'target_price', 'stop_loss', 'risk_pct', 'risk_ratio',
    'reason', 'score', 'status', 'source', 'expires_date', 'notes'
]

def load_recommendations():
    recs = []
    if not RECOMMEND_FILE.exists():
        return recs
    text = RECOMMEND_FILE.read_text(encoding='utf-8-sig')
    if not text.strip():
        return recs
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        recs.append(dict(row))
    return recs

def save_recommendations(recs):
    with open(RECOMMEND_FILE, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in recs:
            if r.get('code'):
                writer.writerow(r)

def add_recommendation(code, name, entry_price, reason, score,
                       target_price, stop_loss, risk_pct, risk_ratio,
                       stock_type, source='scan', notes=''):
    recs = load_recommendations()
    today = now_str()
    expires = days_between(today, STOCK_TYPES.get(stock_type, 60))
    if any(r.get('code') == code and r.get('status') != '已拒绝' for r in recs):
        return False
    rec = {
        'code': code, 'name': name, 'added_date': today, 'type': stock_type,
        'entry_price': str(entry_price), 'target_price': str(target_price),
        'stop_loss': str(stop_loss), 'risk_pct': str(risk_pct),
        'risk_ratio': str(risk_ratio), 'reason': reason,
        'score': str(score), 'status': '待确认', 'source': source,
        'expires_date': expires, 'notes': notes,
    }
    recs.append(rec)
    save_recommendations(recs)
    return True

def update_status(code, new_status):
    recs = load_recommendations()
    for r in recs:
        if r.get('code') == code:
            r['status'] = new_status
    save_recommendations(recs)

def expire_old():
    today = now_str()
    recs = load_recommendations()
    changed = False
    for r in recs:
        if r.get('status') == '已入关注' and r.get('expires_date', '') < today:
            r['status'] = '已过期'
            changed = True
    if changed:
        save_recommendations(recs)

# ─────────────────────────────────────────────
# 自动选股扫描入口
# ─────────────────────────────────────────────

def run_auto_scan(portfolio_list, top_n=5):
    """自动全市场扫描推荐股（价值投资版）- 增强筛选"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from full_market_scan import run_value_scan
    
    print("🔍 开始价值投资风格扫描（增强筛选版）...")
    
    # 获取大盘状态
    import urllib.request
    idx_url = "https://qt.gtimg.cn/q=sh000001"
    try:
        req = urllib.request.Request(idx_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode('gb2312', errors='ignore')
            pct = 0.0
            if '=' in raw:
                parts = raw.split('~')
                pct = float(parts[32]) if parts[32] not in ['', '-'] else 0.0
    except:
        pct = 0.0
    
    # 根据大盘状态选择策略
    if pct > 1.0:
        market_mode = "bull"
        print("🐂 牛市模式：追强势股")
    elif pct < -1.0:
        market_mode = "bear"
        print("🐻 熊市模式：买超跌股")
    else:
        market_mode = "震荡"
        print("➡️ 震荡市模式：均衡配置")
    
    # 全市场扫描
    top = run_value_scan(top_n=30)  # 增加候选数量
    if not top:
        print("⚠️ 全市场无满足条件的候选股")
        return []
    
    # 二次筛选过滤
    filtered = []
    for c in top[:30]:
        # 排除已有持仓
        if c['code'] in portfolio_list:
            continue
        
        # 价值投资过滤
        roe = c.get('roe', 0)
        pe = c.get('pe', 0)
        pb = c.get('pb', 0)
        
        # 熊市：更严格的基本面要求
        if market_mode == "bear":
            if roe < 10:
                continue  # 熊市要求更高ROE
            if pe > 15:
                continue  # 熊市要求更低PE
        
        # 牛市：可以放宽基本面
        elif market_mode == "bull":
            if roe < 5:
                continue  # 至少要盈利
        
        # 共同过滤：排除高估值
        if pe < 0 or pe > 50:
            continue  # 排除亏损股和高估值
        if pb > 10:
            continue  # 排除高市净率
        
        filtered.append(c)
        
        if len(filtered) >= top_n:
            break
    
    if not filtered:
        print("⚠️ 筛选后无可用候选股")
        return []
    
    # 转换为推荐格式
    new_added = []
    for c in filtered[:top_n]:
        from recommendation import calc_target_stop
        stock_type = '价值投资' if c.get('roe', 0) > 15 else '超跌反弹'
        
        # 调整止盈止损（根据市场状态）
        entry = c['price']
        if market_mode == "bull":
            # 牛市更激进
            target = entry * 1.30
            stop = entry * 0.90
        elif market_mode == "bear":
            # 熊市保守
            target = entry * 1.15
            stop = entry * 0.93
        else:
            target = entry * 1.20
            stop = entry * 0.92
        
        risk_pct = round((target - entry) / entry * 100, 1)
        rr = abs(round((target - entry) / (entry - stop), 1)) if entry != stop else 0
        
        sig_str = ' '.join(c['signals'][:2])
        
        ok = add_recommendation(
            code=c['code'], name=c['name'], entry_price=entry,
            reason=f"({stock_type}){sig_str}",
            score=c['score'], target_price=round(target, 2), stop_loss=round(stop, 2),
            risk_pct=risk_pct, risk_ratio=rr,
            stock_type=stock_type, source='auto_scan',
            notes=f"ROE={c.get('roe',0):.1f}% PE={c.get('pe',0):.0f} PB={c.get('pb',0):.1f} [{market_mode}]")
        if ok:
            new_added.append(c)
    
    print(f"✅ 增强筛选完成，新增 {len(new_added)} 只推荐（模式：{market_mode}）")
    return new_added

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推荐股票模块
- 自动选股扫描 + 评分
- 目标价/止损价计算
- 有效期管理
- 推荐池文件 recommendation.csv
"""

import csv, json, time, sys, io
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RECOMMEND_FILE = DATA_DIR / "recommendation.csv"
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"

TRADE_LOG_FILE  = DATA_DIR / "trade_log.csv"

# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────

def nv(v):
    return v is not None and str(v) not in ('', 'nan', 'None', '-')

def now_str():
    return datetime.now().strftime('%Y-%m-%d')

def days_between(date_str, days):
    d = datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=days)
    return d.strftime('%Y-%m-%d')

# ─────────────────────────────────────────────
# 推荐类型 & 有效期
# ─────────────────────────────────────────────

STOCK_TYPES = {
    '超跌反弹': 30,
    '价值投资': 90,
    '周期复苏': 60,
    '技术突破': 30,
}

def determine_type(fin_data, daily_closes, rsi, recent_pct):
    """
    推荐类型判断 + 基础过滤
    增加基本面过滤，排除高风险股票
    """
    # 基础过滤：排除亏损股和高负债
    ann = (fin_data.get('annual') or {}) if fin_data else {}
    roe = ann.get('roe') or 0
    ni_yoy = ann.get('ni_yoy') or 0
    gross = ann.get('gross') or 0
    debt_ratio = ann.get('debt', 0) or 0  # 资产负债率
    
    # 过滤条件
    if roe < 0:
        return None  # 亏损股排除
    if debt_ratio > 90:
        return None  # 高负债排除
    if ni_yoy < -50:
        return None  # 净利润暴跌排除
    
    # 确定类型
    if roe > 15 and ni_yoy > 10:
        return '价值投资'
    if rsi and rsi < 30:
        return '超跌反弹'
    if recent_pct and recent_pct < -15:
        return '超跌反弹'
    if rsi and rsi < 40:
        return '超跌反弹'
    return '技术突破'

def calc_target_stop(entry_price, stock_type):
    if stock_type == '超跌反弹':
        target = entry_price * 1.20; stop = entry_price * 0.92
    elif stock_type == '价值投资':
        target = entry_price * 1.25; stop = entry_price * 0.85
    elif stock_type == '周期复苏':
        target = entry_price * 1.30; stop = entry_price * 0.85
    else:
        target = entry_price * 1.15; stop = entry_price * 0.92
    risk = round((target - entry_price) / entry_price * 100, 1)
    rr = abs(round((target - entry_price) / (entry_price - stop), 1)) if entry_price != stop else 0
    return round(target, 2), round(stop, 2), risk, rr

# ─────────────────────────────────────────────
# 持仓股 & 已清仓股
# ─────────────────────────────────────────────

def get_watched_codes():
    codes = set()
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, encoding='utf-8') as f:
            for line in f:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 1 and parts[0].isdigit() and len(parts[0]) == 6:
                    codes.add(parts[0])
    if TRADE_LOG_FILE.exists():
        text = TRADE_LOG_FILE.read_text(encoding='utf-8-sig')
        if text.strip():
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                code = row.get('代码', '').strip()
                if code.isdigit() and len(code) == 6:
                    codes.add(code)
    return codes

# ─────────────────────────────────────────────
# 推荐文件读写
# ─────────────────────────────────────────────

FIELDNAMES = [
    'code', 'name', 'added_date', 'type', 'entry_price',
    'target_price', 'stop_loss', 'risk_pct', 'risk_ratio',
    'reason', 'score', 'status', 'source', 'expires_date', 'notes'
]

def load_recommendations():
    recs = []
    if not RECOMMEND_FILE.exists():
        return recs
    text = RECOMMEND_FILE.read_text(encoding='utf-8-sig')
    if not text.strip():
        return recs
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        recs.append(dict(row))
    return recs

def save_recommendations(recs):
    with open(RECOMMEND_FILE, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in recs:
            if r.get('code'):
                writer.writerow(r)

def add_recommendation(code, name, entry_price, reason, score,
                       target_price, stop_loss, risk_pct, risk_ratio,
                       stock_type, source='scan', notes=''):
    recs = load_recommendations()
    today = now_str()
    expires = days_between(today, STOCK_TYPES.get(stock_type, 60))
    if any(r.get('code') == code and r.get('status') != '已拒绝' for r in recs):
        return False
    rec = {
        'code': code, 'name': name, 'added_date': today, 'type': stock_type,
        'entry_price': str(entry_price), 'target_price': str(target_price),
        'stop_loss': str(stop_loss), 'risk_pct': str(risk_pct),
        'risk_ratio': str(risk_ratio), 'reason': reason,
        'score': str(score), 'status': '待确认', 'source': source,
        'expires_date': expires, 'notes': notes,
    }
    recs.append(rec)
    save_recommendations(recs)
    return True

def update_status(code, new_status):
    recs = load_recommendations()
    for r in recs:
        if r.get('code') == code:
            r['status'] = new_status
    save_recommendations(recs)

def expire_old():
    today = now_str()
    recs = load_recommendations()
    changed = False
    for r in recs:
        if r.get('status') == '已入关注' and r.get('expires_date', '') < today:
            r['status'] = '已过期'
            changed = True
    if changed:
        save_recommendations(recs)

# ─────────────────────────────────────────────
# 自动选股扫描入口
# ─────────────────────────────────────────────

def run_auto_scan(portfolio_list, top_n=5):
    """自动全市场扫描推荐股（价值投资版）"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from full_market_scan import run_value_scan
    
    print("🔍 开始价值投资风格扫描...")
    
    # 全市场扫描
    top = run_value_scan(top_n=20)
    if not top:
        print("⚠️ 全市场无满足条件的候选股")
        return []
    
    # 转换为推荐格式
    new_added = []
    for c in top[:top_n]:
        from recommendation import calc_target_stop
        stock_type = '价值投资' if c.get('roe', 0) > 15 else '超跌反弹'
        target, stop, risk_pct, rr = calc_target_stop(c['price'], stock_type)
        sig_str = ' '.join(c['signals'][:2])
        
        ok = add_recommendation(
            code=c['code'], name=c['name'], entry_price=c['price'],
            reason=f"({stock_type}){sig_str}",
            score=c['score'], target_price=target, stop_loss=stop,
            risk_pct=risk_pct, risk_ratio=rr,
            stock_type=stock_type, source='auto_scan',
            notes=f"ROE={c.get('roe',0):.1f}% PE={c.get('pe',0):.0f} PB={c.get('pb',0):.1f}")
        if ok:
            new_added.append(c)
    
    print(f"✅ 价值投资扫描完成，新增 {len(new_added)} 只推荐")
    return new_added

# ─────────────────────────────────────────────
# 核心评分函数
# ─────────────────────────────────────────────

def score_stock_full(code, name, rt_data, fin_data, flow_data, daily_closes):
    tech = fin_s = flow_s = 0
    signals = []; reasons = []

    if len(daily_closes) >= 14:
        closes = daily_closes
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0)); losses.append(max(-d, 0))
        if len(gains) >= 14:
            ag = sum(gains[-14:]) / 14; al = sum(losses[-14:]) / 14
            rsi = 100 - (100 / (1 + ag/al)) if al > 0 else 100
            if rsi < 30: tech += 15; signals.append(f'RSI{rsi:.0f}超卖')
            elif rsi < 40: tech += 10; signals.append(f'RSI{rsi:.0f}偏低')
            elif rsi > 75: tech -= 5; signals.append(f'RSI{rsi:.0f}超买')
        if len(closes) >= 20:
            w = closes[-20:]; sma = sum(w)/20
            std = (sum((x-sma)**2 for x in w)/20)**0.5
            upper = sma+2*std; lower = sma-2*std
            price = closes[-1]
            if price < lower: tech += 10; signals.append('跌破布林下轨(超卖)')
            elif price > upper: tech += 5; signals.append('突破布林上轨')
            ma5 = sum(closes[-5:])/5; ma20 = sum(closes[-20:])/20
            if ma5 > ma20*1.02: tech += 8; signals.append('日线多头排列')
            elif ma5 < ma20*0.98: tech += 3; signals.append('日线空头(低吸机会)')
        if len(closes) >= 20:
            recent_chg = (closes[-1]-closes[-20])/closes[-20]*100
            if recent_chg < -15: tech += 10; signals.append(f'近期跌幅{recent_chg:.0f}%(超跌)')
            elif recent_chg < -8: tech += 5; signals.append(f'近期回调{recent_chg:.0f}%')
    else:
        rsi = None

    if len(daily_closes) >= 26:
        if len(daily_closes) >= 5:
            rw = sum(daily_closes[-5:])/5
            ow = sum(daily_closes[-20:-5])/15 if len(daily_closes) >= 20 else sum(daily_closes[:-5])/max(len(daily_closes)-5,1)
            if rw > ow: tech += 8; signals.append('周线趋势向上')

    tech = max(0, min(40, tech))

    ann = (fin_data.get('annual') or {}) if fin_data else {}
    roe = ann.get('roe') or 0; gross = ann.get('gross') or 0
    rev_yoy = ann.get('rev_yoy') or 0; ni_yoy = ann.get('ni_yoy') or 0
    if roe > 20: fin_s += 15; reasons.append(f'ROE{roe:.0f}%')
    elif roe > 15: fin_s += 10; reasons.append(f'ROE{roe:.0f}%')
    elif roe > 10: fin_s += 5
    if rev_yoy > 20: fin_s += 8; reasons.append(f'营收增{rev_yoy:.0f}%')
    elif rev_yoy > 5: fin_s += 4
    if ni_yoy > 20: fin_s += 8; reasons.append(f'净利增{ni_yoy:.0f}%')
    elif ni_yoy > 0: fin_s += 4
    if gross > 30: fin_s += 4; reasons.append(f'毛利率{gross:.0f}%')
    fin_s = max(0, min(35, fin_s))

    ddx5 = flow_data.get('ddx5', 0) or 0
    main_yi = flow_data.get('main_in_yi', 0) or 0
    if ddx5 > 0.3: flow_s += 12; signals.append(f'DDX5+{ddx5:.2f}(机构买入)')
    elif ddx5 > 0: flow_s += 5
    if main_yi > 1: flow_s += 8
    elif main_yi > 0: flow_s += 4
    flow_s = max(0, min(25, flow_s))

    total = tech + fin_s + flow_s
    recent_pct = (daily_closes[-1]-daily_closes[-20])/daily_closes[-20]*100 if len(daily_closes) >= 20 else None
    stype = determine_type(fin_data, daily_closes, rsi if 'rsi' in dir() else None, recent_pct)
    reason_str = '、'.join(reasons[:3]) if reasons else (signals[0] if signals else '综合评分高')

    return total, signals, stype, reason_str, tech, fin_s, flow_s

# ─────────────────────────────────────────────
# 推荐报告生成
# ─────────────────────────────────────────────

def generate_recommendation_report():
    """生成推荐模块 Markdown 内容"""
    # 新逻辑：只显示有效的推荐（status='有效' 或 top20_date 不为空）
    recs = load_recommendations()
    active = [r for r in recs if r.get('status') == '有效' and r.get('top20_date')]
    expired = [r for r in recs if r.get('status') == '失效']

    lines = []
    if not active and not expired:
        lines.append("## 七·推荐关注\n")
        lines.append("*暂无推荐（无有效推荐股票）*")
        return '\n'.join(lines)

    if active:
        lines.append("## 七·推荐关注（Top20 持续有效）\n")
        lines.append("| 股票 | 代码 | 现价 | 类型 | 推荐理由 | 目标价 | 止损价 | 风险收益 | 评分 | Top20日期 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in active:
            top20_date = r.get('top20_date', '')
            target = float(r.get('target_price') or 0)
            stop = float(r.get('stop_loss') or 0)
            entry = float(r.get('entry_price') or 0)
            rr = r.get('risk_ratio', '-')
            score = r.get('score', '')
            lines.append(f"| {r['name']} | {r['code']} | ¥{entry:.2f} | {r.get('type', '价值投资')} | "
                        f"{r.get('reason','')} | ¥{target:.2f} | ¥{stop:.2f} | 1:{rr} | **{score}** | {top20_date} |")

    if expired:
        lines.append(f"\n**⏰ 已失效（{len(expired)}只）：**")
        lines.append("| 股票 | 代码 | 状态 | 离榜天数 |")
        lines.append("|---|---|---|")
        for r in expired:
            valid_days = r.get('valid_days', '0')
            lines.append(f"| {r['name']} | {r['code']} | {r.get('status')} | {valid_days}天 |")

    if expired:
        lines.append(f"\n**⏰ 已过期（{len(expired)}只）：**")
        lines.append("| 股票 | 类型 | 过期日期 |")
        lines.append("|---|---|---|")
        for r in expired:
            lines.append(f"| {r['name']}({r['code']}) | {r['type']} | {r.get('expires_date','')} |")

    return '\n'.join(lines)
