#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源：腾讯财经（优先）+ Tushare备用 + 东方财富（备用）
优先使用最稳定的接口
"""

import urllib.request, json, time
from datetime import datetime

# ============ Tushare配置 ============
try:
    import tushare as ts
    _token = 'pRdHdexpjHTcBXXdnzaUSfqpXtRvryjjJXpAlwYpEHtzktTksDeYnybzFCeXumwI'
    _api_url = 'http://121.40.135.59:8010/'
    ts.set_token(_token)
    _pro = ts.pro_api(_token)
    _pro._DataApi__http_url = _api_url
    _tushare_ok = True
except:
    _tushare_ok = False

TX_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://gu.qq.com/',
}
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}

_tx_ok = None  # 腾讯接口状态

# ============ 工具 ============
def _get(url, headers, timeout=8):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            enc = r.headers.get_content_charset() or 'utf-8'
            return r.read().decode(enc, errors='ignore')
    except:
        return None

# ============ 腾讯财经：实时行情 ============
def tx_realtime(codes):
    """
    腾讯财经实时行情
    codes: ['600036', '002594'] 或 ['sh600036', 'sz002594']
    """
    if not codes:
        return {}
    
    # 构建腾讯格式
    tx_codes = []
    for c in codes:
        c = str(c).strip()
        if c.startswith(('sh', 'sz')):
            tx_codes.append(c)
        elif c.startswith('6'):
            tx_codes.append('sh' + c)
        else:
            tx_codes.append('sz' + c)
    
    # 分批获取
    result = {}
    for i in range(0, len(tx_codes), 50):
        batch = tx_codes[i:i+50]
        url = 'https://qt.gtimg.cn/q=' + ','.join(batch)
        
        raw = _get(url, TX_HEADERS, timeout=10)
        if not raw:
            continue
        
        for line in raw.strip().split('\n'):
            if '=' not in line:
                continue
            parts = line.split('~')
            if len(parts) < 35:
                continue
            
            try:
                code = parts[2]
                if not code or len(code) != 6:
                    continue
                
                price = float(parts[3]) if parts[3] not in ['-', '0', ''] else 0
                if price <= 0:
                    continue
                
                change = float(parts[32]) if parts[32] not in ['-', ''] else 0
                pre_close = float(parts[33]) if parts[33] not in ['-', ''] else price
                
                result[code] = {
                    'price': round(price, 2),
                    'pre_close': round(pre_close, 2),
                    'change': round(change, 2),
                    'pct_change': round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0,
                    'high': round(float(parts[4]), 2) if parts[4] not in ['-', ''] else price,
                    'low': round(float(parts[5]), 2) if parts[5] not in ['-', ''] else price,
                    'volume': float(parts[37]) * 100 if parts[37] else 0,  # 手转成股
                }
            except:
                continue
        
        time.sleep(0.2)
    
    return result

# ============ 腾讯财经：K线 ============
def tx_kline(code, count=30):
    """
    腾讯财经日K线
    code: '600036' 或 'sh600036'
    """
    if code.startswith('6'):
        tx_code = 'sh' + code
    else:
        tx_code = 'sz' + code
    
    url = f'https://web.ifzq.gtimg.cn/appstock/get/fqklinevar={tx_code}&_var=kline_day&param={code},day,{count},qfq'
    
    raw = _get(url, TX_HEADERS, timeout=10)
    if not raw:
        return []
    
    try:
        data = json.loads(raw)
        klines = data.get('data', {}).get(tx_code, {}).get('day', [])
        
        result = []
        for k in klines:
            if len(k) >= 2:
                result.append({
                    'date': str(k[0]),
                    'open': float(k[1]),
                    'high': float(k[2]) if len(k) > 2 else 0,
                    'low': float(k[3]) if len(k) > 3 else 0,
                    'close': float(k[4]) if len(k) > 4 else 0,
                    'volume': float(k[5]) if len(k) > 5 else 0,
                })
        return result
    except:
        return []

# ============ Tushare：股票列表 ============
def ts_stock_list():
    """Tushare获取全市场股票列表"""
    if not _tushare_ok:
        return []
    
    try:
        df = _pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry')
        df = df[df['ts_code'].str.endswith(('.SH', '.SZ'))]
        
        return [{'code': str(row['ts_code'])[:6], 'name': row['name'], 'industry': row.get('industry', '')} 
               for _, row in df.iterrows()]
    except:
        return []

# ============ Tushare：财务数据 ============
def ts_financial(codes):
    """Tushare财务指标"""
    if not _tushare_ok or not codes:
        return {}
    
    # 转换格式
    ts_codes = []
    for c in codes:
        if c.startswith('6'):
            ts_codes.append(c + '.SH')
        else:
            ts_codes.append(c + '.SZ')
    
    result = {}
    for i in range(0, len(ts_codes), 100):
        batch = ts_codes[i:i+100]
        try:
            df = _pro.fina_indicator(
                ts_code=','.join(batch),
                fields='ts_code,end_date,roe,grossprofit_margin,netprofit_margin,debt_to_assets'
            )
            if df is not None and not df.empty:
                df = df.sort_values('end_date', ascending=False)
                df = df.drop_duplicates(subset=['ts_code'], keep='first')
                
                for _, row in df.iterrows():
                    code = row['ts_code'][:6]
                    result[code] = {
                        'roe': row['roe'],
                        'grossprofit_margin': row['grossprofit_margin'],
                        'netprofit_margin': row['netprofit_margin'],
                        'debt_to_assets': row['debt_to_assets'],
                    }
        except:
            pass
        time.sleep(0.5)
    
    return result

# ============ 统一入口 ============
def get_realtime(codes):
    """统一获取实时行情 - 优先腾讯，失败则降级"""
    result = tx_realtime(codes)
    
    if not result and _tushare_ok:
        # 降级到tushare
        pass
    
    return result

def get_kline(code, count=30):
    """获取K线数据"""
    return tx_kline(code, count)

def get_stock_list():
    """获取股票列表"""
    return ts_stock_list()

def get_financial(codes):
    """获取财务数据"""
    return ts_financial(codes)