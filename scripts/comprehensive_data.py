#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一数据源：腾讯财经为主（最稳定）+ 东方财富为辅
涵盖：实时行情 / 日K线 / 财务数据 / 资金流向 / 大盘指数
"""

import urllib.request, json, time
from datetime import datetime, timedelta

TX_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://gu.qq.com/',
}
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}

def _get(url, headers, timeout=8):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or 'utf-8'
            return raw.decode(enc, errors='ignore')
    except:
        return None

# ============ 腾讯：实时行情（主数据源） ============
def tx_realtime_full(codes):
    """
    codes: ['sz000001', 'sh600036', ...]
    返回: {code: {name, price, pre_close, pct, chg, high, low, vol, amount, pe, pb, mktcap_yi, ...}}
    """
    if not codes: return {}
    url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
    raw = _get(url, TX_HEADERS)
    result = {}
    if not raw: return {}
    for line in raw.strip().split('\n'):
        if not line.startswith('v_'): continue
        parts = line.split('="')[1].strip('"').split('~')
        if len(parts) < 50: continue
        code_full = line.split('=')[0].replace('v_', '')  # e.g. sz000001
        code = code_full[2:]  # e.g. 000001
        try:
            price = float(parts[3])
            pre = float(parts[4])
            pct = float(parts[32]) if parts[32] else 0.0
            chg_abs = float(parts[31]) if parts[31] else 0.0
            mktcap_yi = float(parts[44]) if parts[44] else 0.0  # 已经是亿元
            result[code] = {
                'name': parts[1],
                'price': price,
                'pre_close': pre,
                'chg': chg_abs,
                'pct': pct,
                'open': float(parts[5]) if parts[5] else price,
                'high': float(parts[33]) if parts[33] else price,
                'low': float(parts[34]) if parts[34] else price,
                'vol': float(parts[6]) if parts[6] else 0.0,        # 成交量（手）
                'amount_yi': float(parts[37]) / 1e4 if parts[37] else 0.0,  # 成交额（万→亿）
                'pe': float(parts[39]) if parts[39] and parts[39] not in ('-','') else 0.0,
                'pb': float(parts[46]) if parts[46] and parts[46] not in ('-','') else 0.0,
                'mktcap_yi': mktcap_yi,
                'float_mktcap_yi': float(parts[45]) if parts[45] else 0.0,
                'high_52w': float(parts[47]) if parts[47] and parts[47] not in ('-','') else 0.0,  # 52周最高
                'low_52w': float(parts[48]) if parts[48] and parts[48] not in ('-','') else 0.0,   # 52周最低
            }
        except: pass
    return result

# ============ 腾讯：日K线 ============
def tx_daily(code, count=60):
    """腾讯日K，code=纯代码如'000001'"""
    symbol = ('sh' + code) if code.startswith(('6','9')) else ('sz' + code)
    url = (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           f'?param={symbol},day,,,{count},qfq')
    raw = _get(url, TX_HEADERS)
    if not raw: return []
    try:
        data = json.loads(raw)
    except: return []
    raw_klines = data.get('data', {}).get(symbol, {}).get('qfqday', [])
    result = []
    for item in raw_klines[-count:]:
        if len(item) >= 6:
            try:
                result.append({
                    'date': item[0], 'open': float(item[1]),
                    'close': float(item[2]), 'high': float(item[3]),
                    'low': float(item[4]), 'volume': float(item[5]),
                })
            except: pass
    return result

# ============ 东方财富：财务数据（2024年报） ============
def em_financial_full(secids):
    """
    secids: ['0.000001', '1.600036', ...]
    返回: {code: {revenue, rev_chg, profit, profit_chg, roe, npl, dbl, rd, rd_pct, gross, net_margin, dividend}}
    """
    result = {}
    for secid in secids:
        code = secid.split('.')[1]
        # 东方财富财务数据接口
        url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
               f"?reportName=RPT_FCI_PERFORMANCE_NEW"
               f"&columns=SECURITY_CODE,REPORT_DATE,OPERATE_INCOME,OPERATE_INCOME_RR,SECURITY_NAME_ABBR,"
               f"PARENT_NETPROFIT,PARENT_NETPROFIT_RR,ROE,TOTAL_ASSETS,LIABILITIES,NON_OP_INCOME,"
               f"DEDUCT_PARENT_NETPROFIT,NETPROFIT_RR,DILUTED_ROE"
               f"&filter=(SECURITY_CODE%3D%22{secid}%22)"
               f"&pageNumber=1&pageSize=4&sortTypes=-1&sortColumns=REPORT_DATE"
               f"&source=DataCenter&client=PC")
        raw = _get(url, EM_HEADERS, timeout=12)
        if not raw: continue
        try:
            d = json.loads(raw)
            items = d.get('result', {}).get('data', [])
            if not items: continue
            latest = items[0]  # 最新一期
            prev = items[1] if len(items) > 1 else None

            def fv(v, dec=2):
                try:
                    f = float(v)
                    return round(f, dec) if abs(f) < 1e12 else None
                except: return None

            result[code] = {
                'revenue': fv(latest.get('OPERATE_INCOME')),  # 营业收入（元）
                'rev_chg': fv(latest.get('OPERATE_INCOME_RR')),  # 营收同比%
                'profit': fv(latest.get('PARENT_NETPROFIT')),  # 归母净利润
                'profit_chg': fv(latest.get('PARENT_NETPROFIT_RR')),  # 净利同比%
                'roe': fv(latest.get('ROE'), 2),  # ROE%
                'diluted_roe': fv(latest.get('DILUTED_ROE'), 2),
                'dbl': fv(latest.get('LIABILITIES')),  # 负债（需除以总资产）
                'net_margin': fv(latest.get('NETPROFIT_RR')),  # 净利率
                'report_date': latest.get('REPORT_DATE', ''),
            }
        except: pass
        time.sleep(0.3)  # 限速
    return result

# ============ 东方财富：资金流向（DDX系列） ============
def em_capital_flow(secids):
    """
    secids: ['0.000001', '1.600036', ...]
    返回: {code: {ddx5, ddx10, main_in_yi, margin_yi, ...}}
    """
    result = {}
    for secid in secids:
        code = secid.split('.')[1]
        # 资金流向
        url = (f"https://push2.eastmoney.com/api/qt/stock/get"
               f"?ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&invt=2&volt=2"
               f"&fields=f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205"
               f"&secid={secid}")
        raw = _get(url, EM_HEADERS, timeout=8)
        if not raw: continue
        try:
            d = json.loads(raw)
            data = d.get('data', {}) if isinstance(d, dict) else {}
            result[code] = {
                'ddx5': round(float(data.get('f62', 0) or 0), 4),
                'ddx10': round(float(data.get('f184', 0) or 0), 4),
                'ddx20': round(float(data.get('f204', 0) or 0), 4),
                'main_in_yi': round(float(data.get('f66', 0) or 0) / 1e4, 2),  # 万→亿
                'main_out_yi': round(float(data.get('f69', 0) or 0) / 1e4, 2),
                'super_in_yi': round(float(data.get('f72', 0) or 0) / 1e4, 2),
                'super_out_yi': round(float(data.get('f75', 0) or 0) / 1e4, 2),
                'margin_yi': round(float(data.get('f84', 0) or 0) / 1e8, 2),  # 融资余额（亿）
            }
        except: pass
        time.sleep(0.3)
    return result

# ============ 统一入口：持仓分析所需全部数据 ============
def fetch_all(portfolio_list):
    """
    portfolio_list: [{'code': '000001', 'name': '平安银行', 'cost': 12.741, 'qty': 1100}, ...]
    返回: {code: {realtime, daily, financial, flow}}
    同时返回大盘指数
    """
    # 纯代码列表
    codes_pure = [p['code'] for p in portfolio_list]
    # 腾讯格式
    codes_tx = [('sh'+c if c.startswith(('6','9')) else 'sz'+c) for c in codes_pure]
    # 东财格式
    secids_em = [('1.'+c if c.startswith(('6','9')) else '0.'+c) for c in codes_pure]

    # 1. 实时行情（腾讯主数据源）
    print(f"  📡 拉取实时行情（腾讯）...")
    rt_data = tx_realtime_full(codes_tx)
    rt_map = {}
    for p in portfolio_list:
        d = rt_data.get(p['code'], {})
        if d:
            # 计算持仓盈亏
            price = d.get('price', 0)
            cost_total = p['cost'] * p['qty']
            mkt_total = price * p['qty']
            pnl = mkt_total - cost_total
            pnl_pct = pnl / cost_total * 100 if cost_total else 0
            d['cost'] = p['cost']
            d['qty'] = p['qty']
            d['cost_total'] = cost_total
            d['mkt_total'] = mkt_total
            d['pnl'] = pnl
            d['pnl_pct'] = pnl_pct
            rt_map[p['code']] = d

    # 2. 日K线（腾讯）
    print(f"  📜 拉取日K线...")
    daily_map = {}
    for p in portfolio_list:
        d = tx_daily(p['code'], count=60)
        if d:
            daily_map[p['code']] = d

    # 3. 财务数据（东方财富，并行）
    print(f"  📋 拉取财务数据（东财）...")
    fin_data = em_financial_full(secids_em)

    # 4. 资金流向（东方财富，并行）
    print(f"  💰 拉取资金流向（东财）...")
    flow_data = em_capital_flow(secids_em)

    # 5. 大盘指数
    print(f"  🌍 拉取大盘指数...")
    idx_codes_tx = ['sh000001', 'sz399001', 'sz399006', 'sh000300']
    idx_rt = tx_realtime_full(idx_codes_tx)
    # 映射
    idx_map = {
        '上证指数': idx_rt.get('000001', {}),
        '深证成指': idx_rt.get('399001', {}),
        '创业板指': idx_rt.get('399006', {}),
        '沪深300': idx_rt.get('000300', {}),
    }

    return rt_map, daily_map, fin_data, flow_data, idx_map

# ============ 技术指标计算 ============
def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return round(100 - (100 / (1 + ag / al)), 1)

def calc_ema(data, period):
    k = 2 / (period + 1)
    ema = [data[0]]
    for v in data[1:]: ema.append(v * k + ema[-1] * (1 - k))
    return ema

def calc_bollinger(closes, period=20, k=2):
    if len(closes) < period: return None
    w = closes[-period:]
    sma = sum(w) / period
    std = (sum((x - sma) ** 2 for x in w) / period) ** 0.5
    return {'mid': round(sma, 3), 'upper': round(sma + k * std, 3), 'lower': round(sma - k * std, 3)}

def calc_pivot(high, low, close):
    pivot = (high + low + close) / 3
    return {
        'pivot': round(pivot, 2),
        'r1': round(2 * pivot - low, 2),
        'r2': round(pivot + (high - low), 2),
        's1': round(2 * pivot - high, 2),
        's2': round(pivot - (high - low), 2),
    }

def daily_to_weekly(daily):
    """日K聚合周K"""
    if not daily: return []
    weeks = {}
    for bar in daily:
        dt = bar.get('date', '')
        try:
            d = datetime.strptime(dt[:10], '%Y-%m-%d')
            ws = (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d')
        except:
            ws = dt[:10]
        if ws not in weeks:
            weeks[ws] = {'open': bar['open'], 'close': bar['close'],
                        'high': bar['high'], 'low': bar['low'], 'volume': bar['volume']}
        else:
            weeks[ws]['high'] = max(weeks[ws]['high'], bar['high'])
            weeks[ws]['low'] = min(weeks[ws]['low'], bar['low'])
            weeks[ws]['close'] = bar['close']
            weeks[ws]['volume'] += bar['volume']
    return [{'date': k, **v} for k, v in sorted(weeks.items())]
