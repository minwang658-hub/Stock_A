#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周线增强版晨报生成器
数据源：Tushare Pro + 腾讯财经
功能：MACD背离检测 + 布林带突破信号 + 周K线分析
"""

import urllib.request
import tushare as ts
import time
from datetime import datetime, timedelta
import os
from pathlib import Path

# ============ 路径配置（使用相对路径）============
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============ Tushare配置 ============
_token = os.environ.get("TUSHARE_TOKEN", "").strip()
_api_url = os.environ.get("TUSHARE_API_URL", "http://121.40.135.59:8010/")

if not _token:
    raise RuntimeError("Missing TUSHARE_TOKEN environment variable")

pro = ts.pro_api(_token)
pro._DataApi__http_url = _api_url

# ============ 自选股池 ============
STOCKS = {
    '600519': '贵州茅台', '300750': '宁德时代', '002594': '比亚迪',
    '600036': '招商银行', '603005': '晶方科技', '600115': '中国东航',
    '600660': '福耀玻璃', '000630': '铜陵有色', '002415': '海康威视',
    '000651': '格力电器', '603019': '中科曙光', '000001': '平安银行',
    '601318': '中国平安', '000858': '五粮液'
}

HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ============ 获取K线数据 ============
def get_klines(code, count=30):
    """从腾讯获取日K线"""
    if code.startswith('6'):
        tx_code = 'sh' + code
    else:
        tx_code = 'sz' + code
    
    url = f'https://web.ifzq.gtimg.cn/appstock/get/fqklinevar={tx_code}&_var=kline_day&param={code},day,{count},qfq'
    
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='ignore')
        
        data = eval(raw)
        klines = data['data'][tx_code]['day']
        
        result = []
        for k in klines:
            result.append({
                'date': k[0],
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
            })
        return result
    except:
        return []

# ============ 计算MACD ============
def calc_macd(closes):
    """计算MACD"""
    if len(closes) < 26:
        return None, None, None
    
    # EMA12, EMA26
    ema12 = closes[:]
    ema26 = closes[:]
    for i in range(1, len(closes)):
        ema12[i] = ema12[i-1] * 11/13 + closes[i] * 2/13
        ema26[i] = ema26[i-1] * 25/27 + closes[i] * 2/27
    
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    
    # DEA (MACD信号线)
    dea = dif[:]
    for i in range(1, len(dif)):
        dea[i] = dea[i-1] * 8/10 + dif[i] * 2/10
    
    # MACD柱状图
    macd = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    
    return dif, dea, macd

# ============ MACD背离检测 ============
def check_macd_divergence(klines):
    """检测MACD背离"""
    if len(klines) < 60:
        return None
    
    closes = [k['close'] for k in klines]
    dif, dea, macd = calc_macd(closes)
    
    if not dif:
        return None
    
    # 检查底背离：价格创新低，MACD没有创新低
    recent_low = min(closes[-20:])
    macd_low = min(macd[-20:])
    
    # 60天前
    old_low = min(closes[-60:-40]) if len(closes) > 40 else min(closes[:20])
    old_macd_low = min(macd[-60:-40]) if len(macd) > 40 else min(macd[:20])
    
    # 底背离
    if recent_low < old_low * 1.05 and macd_low > old_macd_low:
        return "MACD底背离✅"
    # 顶背离
    elif max(closes[-20:]) > max(closes[-60:-40]) and max(macd[-20:]) < max(macd[-60:-40]):
        return "MACD顶背离⚠���"
    # 金叉
    elif dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
        return "MACD金叉✅"
    # 死叉
    elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
        return "MACD死叉⚠️"
    
    return None

# ============ 布林带 ============
def check_bollinger(klines):
    """检测布林带"""
    if len(klines) < 20:
        return None
    
    closes = [k['close'] for k in klines[-20:]]
    ma20 = sum(closes) / 20
    
    # 标准差
    std = (sum((c - ma20) ** 2 for c in closes) / 20) ** 0.5
    
    upper = ma20 + 2 * std
    lower = ma20 - 2 * std
    
    current_price = closes[-1]
    
    if current_price > upper:
        return "布林上轨突破🚀超买"
    elif current_price < lower:
        return "布林下轨突破📉超卖"
    elif current_price > ma20:
        return "布林中轨上方运行"
    else:
        return "布林中轨下方运行"

# ============ 均线多头 ============
def check_ma_alignment(klines):
    """均线多头排列"""
    if len(klines) < 60:
        return None
    
    ma5 = sum(k['close'] for k in klines[-5:]) / 5
    ma20 = sum(k['close'] for k in klines[-20:]) / 20
    ma60 = sum(k['close'] for k in klines[-60:]) / 60
    
    if ma5 > ma20 > ma60:
        return "均线多头排列✅"
    elif ma5 < ma20 < ma60:
        return "均线空头排列⚠️"
    
    return None

# ============ 主程序 ============
def main():
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")
    
    print(f"📡 正在获取周线数据...")
    
    report = f"# 📈 关注股票晨报（周线增强版）\n\n"
    report += f"**日期：** {today}\n"
    report += f"**生成时间：** {now_str}\n"
    report += f"**数据源：** Tushare Pro + 腾讯财经\n\n"
    report += "---\n\n"
    report += "## 【周线核心信号】\n\n"
    
    signals_found = 0
    
    for code, name in STOCKS.items():
        print(f"  分析 {code} {name}...")
        
        # 获取K线
        klines = get_klines(code, count=60)
        if not klines:
            continue
        
        signals = []
        
        # MACD
        macd_signal = check_macd_divergence(klines)
        if macd_signal:
            signals.append(macd_signal)
        
        # 布林
        bb_signal = check_bollinger(klines)
        if bb_signal:
            signals.append(bb_signal)
        
        # 均线
        ma_signal = check_ma_alignment(klines)
        if ma_signal:
            signals.append(ma_signal)
        
        # 周涨跌幅
        week_change = (klines[-1]['close'] - klines[-5]['close']) / klines[-5]['close'] * 100
        
        if signals:
            signals_found += 1
            report += f"- `{code} {name}`：\n"
            report += f"  周收：{klines[-1]['close']:.2f} | 周涨跌：{week_change:+.2f}%\n"
            report += f"  💡 信号：{' | '.join(signals)}\n\n"
        else:
            report += f"- `{code} {name}`：\n"
            report += f"  周收：{klines[-1]['close']:.2f} | 周涨跌：{week_change:+.2f}%\n"
            report += f"  📊 信号：无明显信号\n\n"
        
        time.sleep(0.3)
    
    if signals_found == 0:
        report += "\n*📊 本周期无明显技术信号*\n"
    
    report += "\n---\n*自动生成报告，仅供参考*\n"
    
    # 保存
    filename = f"{REPORT_DIR}/晨报-{today}-周线版.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n✅ 周线版已生成：{filename}")
    print(f"📊 发现 {signals_found} 只股票有明显信号")

if __name__ == '__main__':
    main()