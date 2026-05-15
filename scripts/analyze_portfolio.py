#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米米持仓精算分析器
数据源：Tushare Pro (持仓) + 腾讯财经 (行情)
"""

import urllib.request
import tushare as ts
import time
from datetime import datetime
import os
from pathlib import Path

# ============ 路径配置（使用相对路径）============
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"

# 确保目录存在（使用 resolve 确保绝对路径）
DATA_DIR.resolve().mkdir(parents=True, exist_ok=True)
REPORT_DIR.resolve().mkdir(parents=True, exist_ok=True)

# ============ Tushare配置 ============
_token = os.environ.get("TUSHARE_TOKEN", "").strip()
_api_url = os.environ.get("TUSHARE_API_URL", "http://121.40.135.59:8010/")

if not _token:
    raise RuntimeError("Missing TUSHARE_TOKEN environment variable")

# 初始化
pro = ts.pro_api(_token)
pro._DataApi__http_url = _api_url

# ============ 持仓配置 ============
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# ============ 读取持仓 ============
def load_portfolio():
    """读取持仓数据"""
    portfolio = []
    
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"⚠️ 持仓文件不存在: {PORTFOLIO_FILE}")
        return portfolio
    
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                portfolio.append({
                    'code': parts[0].strip(),
                    'cost': float(parts[1]),
                    'qty': int(parts[2])
                })
    
    print(f"📂 读取到 {len(portfolio)} 只持仓")
    return portfolio

# ============ 获取实时行情 ============
def get_realtime_prices(codes):
    """从腾讯财经批量获取实时行情"""
    prices = {}
    
    # 构建腾讯代码
    tx_codes = []
    for code in codes:
        if code.startswith('6'):
            tx_codes.append('sh' + code)
        else:
            tx_codes.append('sz' + code)
    
    # 分批获取
    for i in range(0, len(tx_codes), 50):
        batch = tx_codes[i:i+50]
        url = 'https://qt.gtimg.cn/q=' + ','.join(batch)
        
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('gb2312', errors='ignore')
            
            for line in raw.strip().split('\n'):
                if '=' not in line:
                    continue
                parts = line.split('~')
                if len(parts) < 35:
                    continue
                
                code_full = parts[2]
                if not code_full or len(code_full) != 6:
                    continue
                
                price = float(parts[3]) if parts[3] not in ['-', '0', ''] else None
                if not price or price <= 0:
                    continue
                
                change = float(parts[32]) if parts[32] not in ['-', ''] else 0
                
                prices[code_full] = {'price': price, 'change': change}
        
        except Exception as e:
            print(f"  ⚠️ 批次失败: {e}")
        
        time.sleep(0.3)
    
    return prices

# ============ 计算盈亏 ============
def calculate_pnl(portfolio, prices):
    """计算持仓盈亏"""
    results = []
    total_cost = 0
    total_market = 0
    
    for p in portfolio:
        code = p['code']
        cost = p['cost']
        qty = p['qty']
        
        if code in prices:
            price = prices[code]['price']
            change = prices[code]['change']
        else:
            price = 0
            change = 0
        
        cost_value = cost * qty
        market_value = price * qty
        pnl = market_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0
        
        total_cost += cost_value
        total_market += market_value
        
        results.append({
            'code': code,
            'cost': cost,
            'qty': qty,
            'price': price,
            'change': change,
            'cost_value': cost_value,
            'market_value': market_value,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })
    
    total_pnl = total_market - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    
    return results, total_cost, total_market, total_pnl, total_pnl_pct

# ============ 生成分析报告 ============
def generate_analysis(results, total_cost, total_market, total_pnl, total_pnl_pct):
    """生成持仓分析报告"""
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")
    
    # 按盈亏排序
    results_sorted = sorted(results, key=lambda x: x['pnl_pct'], reverse=True)
    
    md = f"# 📊 持仓分析报告\n\n"
    md += f"**日期：** {today}\n"
    md += f"**生成时间：** {now_str}\n"
    md += f"**数据源：** Tushare Pro + 腾讯财经\n\n"
    md += "---\n\n"
    md += f"## 持仓概况\n\n"
    md += f"| 指标 | 数值 |\n"
    md += f"|------|------|\n"
    md += f"| 持仓成本 | ¥{total_cost:,.2f} |\n"
    md += f"| 当前市值 | ¥{total_market:,.2f} |\n"
    md += f"| 浮动盈亏 | ¥{total_pnl:+,.2f} |\n"
    md += f"| 盈亏率 | {total_pnl_pct:+.2f}% |\n\n"
    
    # 涨幅榜
    md += "## 涨幅榜\n\n"
    md += "| 代码 | 成本价 | 现价 | 涨跌% | 盈亏% |\n"
    md += "|------|-------|------|-------|------|\n"
    
    for r in results_sorted[:5]:
        md += f"| {r['code']} | {r['cost']:.2f} | {r['price']:.2f} | {r['change']:+.2f}% | {r['pnl_pct']:+.2f}% |\n"
    
    # 跌幅榜
    md += "\n## 跌幅榜\n\n"
    md += "| 代码 | 成本价 | 现价 | 涨跌% | 盈亏% |\n"
    md += "|------|-------|------|-------|------|\n"
    
    for r in results_sorted[-5:]:
        md += f"| {r['code']} | {r['cost']:.2f} | {r['price']:.2f} | {r['change']:+.2f}% | {r['pnl_pct']:+.2f}% |\n"
    
    # 操作建议
    md += "\n## 操作建议\n\n"
    
    for r in results_sorted:
        code = r['code']
        pnl_pct = r['pnl_pct']
        change = r['change']
        
        if pnl_pct < -15:
            advice = "❌ 触发止损，建议清仓"
        elif pnl_pct < -8:
            advice = "⚠️ 亏损较大，观望"
        elif pnl_pct > 20:
            advice = "✅ 盈利丰富，可考虑部分止盈"
        elif change > 5:
            advice = "📈 上涨中，持有"
        elif change < -5:
            advice = "📉 大跌，观望"
        else:
            advice = "📊 正常波动"
        
        md += f"| {code} | {advice} |\n"
    
    md += "\n---\n*自动生成报告，仅供参考*\n"
    
    # 保存文件
    filename = f"{REPORT_DIR}/持仓分析-{today}.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(md)
    
    print(f"✅ 持仓分析报告已生成：{filename}")
    return filename

# ============ 主程序 ============
def main():
    print("📡 正在获取持仓数据...")
    
    # 读取持仓
    portfolio = load_portfolio()
    if not portfolio:
        print("❌ 无持仓数据")
        return
    
    # 获取实时行情
    codes = [p['code'] for p in portfolio]
    print(f"📡 正在从腾讯财经拉取 {len(codes)} 只股票实时数据...")
    
    prices = get_realtime_prices(codes)
    print(f"✅ 获取到 {len(prices)} 只股票行情")
    
    # 计算盈亏
    results, total_cost, total_market, total_pnl, total_pnl_pct = calculate_pnl(portfolio, prices)
    
    # 生成报告
    generate_analysis(results, total_cost, total_market, total_pnl, total_pnl_pct)
    
    # 打印摘要
    print(f"\n📊 持仓摘要:")
    print(f"  成本: ¥{total_cost:,.2f}")
    print(f"  市值: ¥{total_market:,.2f}")
    print(f"  盈亏: ¥{total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)")

if __name__ == '__main__':
    main()