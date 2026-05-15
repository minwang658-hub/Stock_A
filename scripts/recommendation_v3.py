#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推荐股票模块 V3 - 量化因子评分体系
基于Barra/CNE5因子模型：
- 价值因子 25% (PE/PB/股息率)
- 成长因子 25% (营收增速/净利增速/毛利率变化)
- 质量因子 25% (ROE/毛利率/资产负债率)
- 动量因子 15% (20日涨幅/RSI)
- 行业分散 10% (每行业最多2只)
"""

import csv, json, time, sys
from pathlib import Path
from datetime import datetime, timedelta
import urllib.request

# ─────────────────────────────────────────────
# 路径配置
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RECOMMEND_V3_FILE = DATA_DIR / "recommendation_v3.csv"

# 行业配置
INDUSTRIES = [
    '银行', '券商', '保险', '白酒', '家电', 
    '医药', '科技', '新能源', '化工', '基建',
    '交通运输', '房地产', '钢铁', '电力', '汽车', '传媒'
]

# 行业龙头（确保覆盖）
INDUSTRY_LEADERS = {
    '银行': ['600036', '601398', '601939', '601166', '600000'],
    '券商': ['600030', '600837', '601066', '600999', '601788'],
    '保险': ['601318', '601628', '601601', '601336'],
    '白酒': ['600519', '000858', '000596', '000568', '603198'],
    '家电': ['000651', '000333', '000810', '002032', '002508'],
    '医药': ['600276', '000538', '300015', '300003', '603259'],
    '科技': ['000063', '002410', '300033', '600570', '002415'],
    '新能源': ['300750', '002594', '600438', '002311', '002202'],
    '化工': ['600309', '600160', '600486', '002601', '600352'],
    '基建': ['601668', '601390', '601669', '600585', '601618'],
    '交通运输': ['600115', '600029', '601111', '600009', '601006'],
    '房地产': ['000002', '600048', '600340', '000069', '601155'],
    '钢铁': ['600019', '000709', '000717', '600808'],
    '电力': ['600900', '600795', '600011', '600027'],
    '汽车': ['600104', '601238', '000625', '002594'],
    '传媒': ['601888', '002027', '300133'],
}

# 行业PB阈值
SECTOR_PB = {
    '银行': 2.0, '券商': 2.5, '保险': 2.5, '基建': 3.0, '电力': 3.0,
    '钢铁': 3.5, '制造业': 4.0, '房地产': 4.5, '交通运输': 5.0, '化工': 5.0,
    '家电': 5.5, '消费': 6.0, '医药': 6.0, '白酒': 8.0, '科技': 8.0,
    '新能源': 8.0, '汽车': 8.0, '传媒': 8.0,
}

# ─────────────────────────────────────────────
# 数据源：腾讯财经实时行情
# ─────────────────────────────────────────────

def tx_realtime(codes):
    """腾讯财经实时行情"""
    if not codes:
        return {}
    
    tx_codes = []
    for c in codes:
        if c.startswith(('0', '3')):
            tx_codes.append(f'sz{c}')
        else:
            tx_codes.append(f'sh{c}')
    
    url = 'https://qt.gtimg.cn/q=' + ','.join(tx_codes)
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gb2312', errors='ignore')
        
        result = {}
        for line in raw.split('\n'):
            if '=' not in line:
                continue
            parts = line.split('=')
            if len(parts) < 2:
                continue
            
            key = parts[0].strip()
            if '~' not in parts[1]:
                continue
            
            code = key.split('_')[-1] if '_' in key else ''
            if not code:
                continue
            
            try:
                data = parts[1].strip('"').split('~')
                name = data[1] if len(data) > 1 else ''
                price = float(data[3]) if data[3] else 0
                pct = float(data[32]) if len(data) > 32 and data[32] else 0
                amount_raw = float(data[7]) if len(data) > 7 and data[7] else 0
                amount_yi = amount_raw / 10000  # 万元转亿元
                pe = float(data[39]) if len(data) > 39 and data[39] and data[39] != '-' else 0
                pb = float(data[46]) if len(data) > 46 and data[46] and data[46] != '-' else 0
                high52w = float(data[48]) if len(data) > 48 and data[48] else 0
                low52w = float(data[49]) if len(data) > 49 and data[49] else 0
                
                # 简化RSI
                rsi = 50
                
                # 计算20日涨幅（简化：用当日涨跌幅代替）
                pct_20d = pct * 20  # 简化估算
                
                result[code] = {
                    'name': name,
                    'price': price,
                    'pct_chg': pct,
                    'pct_20d': pct_20d,
                    'amount': amount_yi,
                    'pe': pe,
                    'pb': pb,
                    'high52w': high52w,
                    'low52w': low52w,
                    'rsi': rsi,
                }
            except:
                continue
        
        return result
    except Exception as e:
        print(f"  ⚠️ 腾讯API错误: {e}")
        return {}


# ─────────────────────────────────────────────
# 量化因子评分体系
# ─────────────────────────────────────────────

def score_value(rt, sector='其他'):
    """价值因子 (25分)"""
    score = 0
    pe = rt.get('pe', 0) or 0
    pb = rt.get('pb', 0) or 0
    
    # PE 评分 (10分)
    if 0 < pe < 10:
        score += 10
    elif 0 < pe < 15:
        score += 7
    elif 0 < pe < 25:
        score += 4
    elif 0 < pe < 40:
        score += 2
    
    # PB 评分 (10分) - 按行业调整
    pb_threshold = SECTOR_PB.get(sector, 6.0)
    if pb > 0 and pb < pb_threshold * 0.5:
        score += 10
    elif pb > 0 and pb < pb_threshold * 0.8:
        score += 7
    elif pb > 0 and pb < pb_threshold:
        score += 4
    
    # 股息率简化 (5分) - 银行/保险通常有股息
    if sector in ['银行', '保险', '电力']:
        if pb < 1.5:
            score += 3  # 高股息蓝筹
        elif pb < 2:
            score += 1
    
    return min(25, score)


def score_growth(rt, fin_data=None):
    """成长因子 (25分)"""
    score = 0
    
    if fin_data:
        # 营收增速 (10分)
        rev_yoy = fin_data.get('revenue_yoy', 0) or 0
        if rev_yoy > 20:
            score += 10
        elif rev_yoy > 10:
            score += 7
        elif rev_yoy > 0:
            score += 4
        
        # 净利润增速 (10分)
        ni_yoy = fin_data.get('ni_yoy', 0) or 0
        if ni_yoy > 20:
            score += 10
        elif ni_yoy > 10:
            score += 7
        elif ni_yoy > 0:
            score += 4
        
        # 毛利率变化 (5分)
        gross = fin_data.get('gross', 0) or 0
        if gross > 40:
            score += 5
        elif gross > 30:
            score += 3
    else:
        # 无财务数据时，用涨跌幅模拟
        pct = rt.get('pct_chg', 0) or 0
        if pct > 5:
            score += 10
        elif pct > 0:
            score += 5
    
    return min(25, score)


def score_quality(rt, fin_data=None):
    """质量因子 (25分)"""
    score = 0
    
    if fin_data:
        # ROE (10分)
        roe = fin_data.get('roe', 0) or 0
        if roe > 20:
            score += 10
        elif roe > 15:
            score += 7
        elif roe > 10:
            score += 4
        
        # 毛利率 (8分)
        gross = fin_data.get('gross', 0) or 0
        if gross > 40:
            score += 8
        elif gross > 30:
            score += 5
        elif gross > 20:
            score += 2
        
        # 资产负债率 (7分) - 越低越好
        debt = fin_data.get('debt_ratio', 0) or 0
        if debt < 50:
            score += 7
        elif debt < 70:
            score += 4
    else:
        # 无财务数据时，用PB模拟质量
        pb = rt.get('pb', 0) or 0
        if pb < 1:
            score += 10
        elif pb < 2:
            score += 6
        elif pb < 3:
            score += 3
    
    return min(25, score)


def score_momentum(rt):
    """动量因子 (15分)"""
    score = 0
    pct = rt.get('pct_chg', 0) or 0
    pct_20d = rt.get('pct_20d', 0) or pct * 20
    rsi = rt.get('rsi', 50) or 50
    
    # 20日涨幅 (8分)
    if pct_20d > 15:
        score += 8
    elif pct_20d > 10:
        score += 6
    elif pct_20d > 5:
        score += 4
    elif pct_20d > 0:
        score += 2
    
    # RSI (7分)
    if rsi < 30:
        score += 7  # 超卖反弹
    elif rsi < 40:
        score += 4
    elif rsi > 75:
        score -= 3  # 超买风险
    
    return max(0, min(15, score))


def calculate_target_stop(price, stock_type='价值投资'):
    """计算目标价和止损价"""
    if stock_type == '价值投资':
        target = price * 1.25
        stop = price * 0.85
    elif stock_type == '成长股':
        target = price * 1.40
        stop = price * 0.88
    elif stock_type == '周期复苏':
        target = price * 1.30
        stop = price * 0.85
    elif stock_type == '超跌反弹':
        target = price * 1.20
        stop = price * 0.92
    else:
        target = price * 1.15
        stop = price * 0.92
    
    rr = (target - price) / (price - stop) if price > stop else 0
    return round(target, 2), round(stop, 2), round(rr, 1)


# ─────────────────────────────────────────────
# V3 扫描主函数
# ─────────────────────────────────────────────

def run_v3_scan(top_n=20):
    """V3 量化因子扫描"""
    print(f"\n🛡️ === 价值投资V3（量化因子版）=== {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Step 1: 构建候选池（行业龙头 + 行业分散）
    print("\n📊 Step 1: 构建候选股票池...")
    candidate_codes = []
    for industry, leaders in INDUSTRY_LEADERS.items():
        candidate_codes.extend(leaders[:5])  # 每行业取5只龙头
    
    # 去重
    candidate_codes = list(dict.fromkeys(candidate_codes))
    print(f"  📊 候选股池: {len(candidate_codes)} 只")
    
    # Step 2: 获取实时行情
    print("\n📊 Step 2: 获取实时行情...")
    rt_map = tx_realtime(candidate_codes)
    print(f"  ✅ 获取到 {len(rt_map)} 只行情")
    
    if not rt_map:
        print("  ❌ 无法获取行情")
        return []
    
    # Step 3: 因子评分
    print("\n📊 Step 3: 量化因子评分...")
    results = []
    
    for code in candidate_codes:
        # 找行情数据
        matched_key = None
        for key in rt_map:
            if key.endswith(code):
                matched_key = key
                break
        
        if not matched_key:
            continue
        
        rt = rt_map[matched_key]
        price = rt.get('price', 0) or 0
        pe = rt.get('pe', 0) or 0
        pb = rt.get('pb', 0) or 0
        amount = rt.get('amount', 0) or 0
        
        # 找行业
        sector = '其他'
        for ind, leaders in INDUSTRY_LEADERS.items():
            if code in leaders:
                sector = ind
                break
        
        # 基础过滤
        if price <= 0:
            continue
        if pe < 0 or pe > 50:
            continue
        pb_threshold = SECTOR_PB.get(sector, 6.0)
        if pb <= 0 or pb > pb_threshold:
            continue
        if amount < 0.1:
            continue
        
        # 因子评分
        value_score = score_value(rt, sector)
        growth_score = score_growth(rt)  # 简化版
        quality_score = score_quality(rt)  # 简化版
        momentum_score = score_momentum(rt)
        total_score = value_score + growth_score + quality_score + momentum_score
        
        # 确定类型
        if pe > 0 and pe < 15 and pb < pb_threshold * 0.6:
            stock_type = '价值投资'
        elif pe > 15 and pe < 35:
            stock_type = '成长股'
        elif rt.get('pct_chg', 0) or 0 < -5:
            stock_type = '超跌反弹'
        else:
            stock_type = '技术突破'
        
        # 计算目标/止损
        target, stop, rr = calculate_target_stop(price, stock_type)
        
        results.append({
            'code': code,
            'name': rt.get('name', code),
            'sector': sector,
            'price': price,
            'pct_chg': rt.get('pct_chg', 0) or 0,
            'pe': pe,
            'pb': pb,
            'value_score': value_score,
            'growth_score': growth_score,
            'quality_score': quality_score,
            'momentum_score': momentum_score,
            'total_score': total_score,
            'type': stock_type,
            'target_price': target,
            'stop_loss': stop,
            'risk_ratio': rr,
            'top20_date': datetime.now().strftime('%Y-%m-%d'),
            'status': '有效',
        })
    
    # Step 4: 行业分散（每行业最多2只）
    print("\n📊 Step 4: 行业分散筛选...")
    
    # 按行业分组
    sector_groups = {}
    for r in results:
        s = r['sector']
        if s not in sector_groups:
            sector_groups[s] = []
        sector_groups[s].append(r)
    
    # 每行业取Top 2
    final_results = []
    for sector in INDUSTRIES:
        if sector in sector_groups:
            # 按得分排序，取前2
            sector_groups[sector].sort(key=lambda x: x['total_score'], reverse=True)
            final_results.extend(sector_groups[sector][:2])
    
    # 按总分排序
    final_results.sort(key=lambda x: x['total_score'], reverse=True)
    
    # 行业分布统计
    result_sectors = {}
    for r in final_results[:top_n]:
        s = r['sector']
        result_sectors[s] = result_sectors.get(s, 0) + 1
    
    print(f"\n📊 推荐行业分布: {result_sectors}")
    
    # 输出
    print(f"\n📋 V3推荐股票（Top {top_n}）：")
    print(f"{'排名':<4} {'股票':<10} {'行业':<6} {'现价':>7} {'今日':>6} {'价值':>4} {'成长':>4} {'质量':>4} {'动量':>4} {'总分':>5} {'类型'}")
    print("-" * 95)
    
    for i, r in enumerate(final_results[:top_n], 1):
        print(f"{i:<4} {r['name']:<8} {r['sector']:<4} ¥{r['price']:>6.2f} {r['pct_chg']:>+5.1f}% {r['value_score']:>3} {r['growth_score']:>3} {r['quality_score']:>3} {r['momentum_score']:>3} {r['total_score']:>4} {r['type']}")
    
    return final_results[:top_n]


def save_v3_recommendations(results):
    """保存V3推荐到CSV"""
    if not results:
        with open(RECOMMEND_V3_FILE, 'w', encoding='utf-8') as f:
            f.write('')
        return
    
    fieldnames = ['code','name','sector','price','pct_chg','pe','pb','value_score','growth_score','quality_score','momentum_score','total_score','type','target_price','stop_loss','risk_ratio','top20_date','status']
    
    with open(RECOMMEND_V3_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k, '') for k in fieldnames}
            writer.writerow(row)
    
    print(f"  ✅ V3推荐已保存: {RECOMMEND_V3_FILE}")


def load_v3_recommendations():
    """加载V3推荐"""
    if not RECOMMEND_V3_FILE.exists():
        return []
    
    results = []
    with open(RECOMMEND_V3_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(row)
    return results


def generate_v3_report():
    """生成V3推荐模块 Markdown 内容"""
    results = load_v3_recommendations()
    
    if not results:
        return "## 八·推荐股票（V3）\n\n*暂无推荐*"
    
    lines = ["## 八·推荐股票（V3）\n"]
    lines.append("| 股票 | 代码 | 行业 | 现价 | 涨跌 | 价值 | 成长 | 质量 | 动量 | 总分 | 类型 | 目标价 | 止损价 | 风险收益 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    
    for r in results:
        lines.append(f"| {r['name']} | {r['code']} | {r['sector']} | ¥{r['price']} | {r['pct_chg']}% | {r['value_score']} | {r['growth_score']} | {r['quality_score']} | {r['momentum_score']} | **{r['total_score']}** | {r['type']} | ¥{r['target_price']} | ¥{r['stop_loss']} | 1:{r['risk_ratio']} |")
    
    return '\n'.join(lines)


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

if __name__ == '__main__':
    results = run_v3_scan(top_n=20)
    save_v3_recommendations(results)
    print(f"\n✅ V3扫描完成，共推荐 {len(results)} 只股票")