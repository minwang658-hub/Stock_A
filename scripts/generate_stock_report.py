#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关注股票晨报生成脚本
数据源：Tushare Pro (股票列表) + 腾讯财经 (实时行情)
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

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ============ Tushare配置 ============
_token = os.environ.get("TUSHARE_TOKEN", "").strip()
_api_url = os.environ.get("TUSHARE_API_URL", "http://121.40.135.59:8010/")

if not _token:
    raise RuntimeError("Missing TUSHARE_TOKEN environment variable")

# 初始化
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

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# ============ Tushare获取自选股列表 ============
def get_watchlist_from_tushare():
    """从Tushare获取自选股最新行情"""
    stocks = []
    codes = list(STOCKS.keys())
    
    # 腾讯批量获取实时行情
    tx_codes = []
    for code in codes:
        if code.startswith('6'):
            tx_codes.append('sh' + code)
        else:
            tx_codes.append('sz' + code)
    
    # 分批获取(每批50只)
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
                
                try:
                    code_full = parts[2]
                    if not code_full or len(code_full) != 6:
                        continue
                    
                    price = float(parts[3]) if parts[3] not in ['-', '0', ''] else None
                    if not price or price <= 0:
                        continue
                    
                    change = float(parts[32]) if parts[32] not in ['-', ''] else 0
                    
                    stocks.append({
                        'code': code_full,
                        'name': parts[1],
                        'price': price,
                        'change': change,
                    })
                except:
                    continue
        
        except Exception as e:
            print(f"  ⚠️ 批次{i//50 + 1}失败: {e}")
        
        time.sleep(0.3)
    
    return stocks

# ============ 计算支撑压力位 ============
def calculate_levels(price):
    """简单支撑压力位计算"""
    p = price
    # 支撑位: -2%, -4%
    s1 = p * 0.98
    s2 = p * 0.96
    # 压力位: +2%, +4%
    r1 = p * 1.02
    r2 = p * 1.04
    return round(s1, 2), round(s2, 2), round(r1, 2), round(r2, 2)

# ============ 生成报告 ============
def generate_report(stocks):
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")
    
    # 按涨跌幅排序
    stocks_sorted = sorted(stocks, key=lambda x: x.get('change', 0), reverse=True)
    
    # 生成Markdown
    md = f"# 📊 关注股票晨报\n\n"
    md += f"**日期：** {today}\n"
    md += f"**生成时间：** {now_str}\n"
    md += f"**数据源：** Tushare Pro + 腾讯财经\n\n"
    md += "---\n\n"
    md += "## 持仓行情\n\n"
    md += "| 代码 | 名称 | 现价 | 涨跌% | 支撑1 | 支撑2 | 压力1 | 压力2 |\n"
    md += "|------|------|------|-------|-------|-------|-------|\n"
    
    for s in stocks_sorted:
        code = s['code']
        name = s['name']
        price = s['price']
        change = s['change']
        
        s1, s2, r1, r2 = calculate_levels(price)
        
        md += f"| {code} | {name} | {price:.2f} | {change:+.2f}% | {s1} | {s2} | {r1} | {r2} |\n"
    
    # 优质股推荐
    md += "\n## 优质股推荐（Top 5）\n\n"
    md += "| 排名 | 股票 | 现价 | 涨跌% | 操作建议 |\n"
    md += "|------|------|------|-------|----------|\n"
    
    for i, s in enumerate(stocks_sorted[:5], 1):
        change = s['change']
        if change > 2:
            advice = "上涨，持有"
        elif change > 0:
            advice = "上涨，持有"
        elif change < -3:
            advice = "下跌，观望"
        else:
            advice = "震荡，观望"
        
        md += f"| {i} | {s['name']} | {s['price']:.2f} | {change:+.2f}% | {advice} |\n"
    
    md += "\n---\n*自动生成报告，仅供参考*\n"
    
    # 保存文件
    filename = f"{REPORT_DIR}/晨报-{today}.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(md)
    
    print(f"报告已生成: {filename}")
    return filename

# ============ 主程序 ============
def main():
    print("📡 正在从Tushare Pro拉取自选股数据...")
    
    stocks = get_watchlist_from_tushare()
    print(f"✅ 获取到 {len(stocks)} 只股票数据")
    
    if stocks:
        generate_report(stocks)
    else:
        print("❌ 未获取到数据")

if __name__ == '__main__':
    main()