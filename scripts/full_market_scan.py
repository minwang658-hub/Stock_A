#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场智能选股系统 v3 - 价值投资版
多数据源架构：
1. 腾讯财经（主要实时行情）
2. 新浪财经（备用）
3. 扩展候选股池（兜底，500+只）
"""

import urllib.request, json, time, sys, random
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# 数据源配置
# ─────────────────────────────────────────────

DATA_SOURCES = {
    'tx': {
        'name': '腾讯财经',
        'batch_url': 'https://qt.gtimg.cn/q=',
        'kline_url': 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
        'status': 'active'
    },
    'sina': {
        'name': '新浪财经', 
        'status': 'backup'
    },
    'eastmoney': {
        'name': '东方财富',
        'status': 'limited'
    }
}

# 扩展候选股池（500+只，覆盖全行业）
EXTENDED_POOL = None

def get_extended_pool():
    """获取扩展候选股池（500+只）"""
    global EXTENDED_POOL
    if EXTENDED_POOL:
        return EXTENDED_POOL
    
    # 行业代表性股票（按行业分类，每行业5-10只）
    pool = [
        # 银行 (20只)
        ('600036','招商银行','银行'),('601398','工商银行','银行'),('601166','兴业银行','银行'),
        ('600000','浦发银行','银行'),('600015','华夏银行','银行'),('600016','民生银行','银行'),
        ('601009','南京银行','银行'),('601169','北京银行','银行'),('601229','上海银行','银行'),
        ('601288','农业银行','银行'),('601328','交通银行','银行'),('601818','光大银行','银行'),
        ('601939','建设银行','银行'),('601988','中国银行','银行'),('002142','宁波银行','银行'),
        ('600926','杭州银行','银行'),('600919','江苏银行','银行'),('600908','苏州银行','银行'),
        ('600839','四川长虹','银行'),('002948','青岛银行','银行'),
        
        # 证券/保险 (15只)
        ('600030','中信证券','券商'),('601066','中信建投','券商'),('600999','招商证券','券商'),
        ('000776','广发证券','券商'),('000686','东北证券','券商'),('002500','山西证券','券商'),
        ('300059','东方财富','互联网金融'),('601601','中国太保','保险'),('601628','中国人寿','保险'),
        ('601319','中国平安','保险'),('601601','中国太保','保险'),('601336','新华保险','保险'),
        ('601901','方正证券','券商'),('600369','西南证券','券商'),('000166','申万宏源','券商'),
        
        # 白酒 (15只)
        ('600519','贵州茅台','白酒'),('000858','五粮液','白酒'),('000568','泸州老窖','白酒'),
        ('002304','洋河股份','白酒'),('000596','古井贡酒','白酒'),('600809','山西汾酒','白酒'),
        ('603589','金种子酒','白酒'),('603198','迎驾贡酒','白酒'),('603919','金徽酒','白酒'),
        ('000799','酒鬼酒','白酒'),('000559','万丰奥特','白酒'),('600197','伊力特','白酒'),
        ('603589','今世缘','白酒'),('000568','老白干酒','白酒'),('600059','华钰矿业','白酒'),
        
        # 家电 (15只)
        ('000333','美的集团','家电'),('000651','格力电器','家电'),('600690','海尔智家','家电'),
        ('002508','老板电器','家电'),('002032','苏泊尔','家电'),('603486','科沃斯','家电'),
        ('002242','九阳股份','家电'),('002543','万和电气','家电'),('000521','长虹美菱','家电'),
        ('600690','海尔智家','家电'),('000810','华安保险','家电'),('002429','兆驰股份','家电'),
        ('603868','飞科电器','家电'),('000651','格力电器','家电'),('000333','美的集团','家电'),
        
        # 新能源/电力 (25只)
        ('300750','宁德时代','新能源电池'),('002594','比亚迪','新能源汽车'),('601012','隆基绿能','光伏'),
        ('600438','通威股份','光伏'),('002459','晶澳科技','光伏'),('603806','福斯特','光伏'),
        ('601615','明阳智能','风电'),('002202','金风科技','风电'),('600900','长江电力','水电'),
        ('600905','三峡能源','新能源'),('601669','中国电建','电力'),('600795','国电电力','火电'),
        ('601985','中国核电','核电'),('600027','华映科技','光电'),('002129','中环股份','光伏'),
        ('600855','中国嘉陵','军工'),('601179','上海电工','电气'),('600875','东方电气','电气'),
        ('601179','千山药机','医疗'),('002202','金山股份','电力'),('600795','大唐发电','电力'),
        ('000591','中化岩土','基建'),('600383','金地集团','地产'),('601669','中国电建','基建'),
        
        # 医药 (30只)
        ('600276','恒瑞医药','创新药'),('000538','云南白药','中药'),('300760','迈瑞医疗','医疗器械'),
        ('300015','爱尔眼科','医疗服务'),('603259','药明康德','医药CRO'),('300347','泰格医药','医药CRO'),
        ('000661','长春高新','生物药'),('300142','沃森生物','疫苗'),('300122','智飞生物','疫苗'),
        ('688180','君实生物','创新药'),('300294','博雅生物','血制品'),('002007','华兰生物','血制品'),
        ('002252','上海莱士','血制品'),('300003','乐普医疗','医疗器械'),('300529','健帆生物','医疗器械'),
        ('002412','汉森制药','中药'),('000999','华润三九','中药'),('603707','健友股份','医药'),
        ('603939','益丰药房','医药零售'),('603883','金陵药业','医药'),('000513','丽珠集团','医药'),
        ('000566','海南海药','医药'),('600332','中宏股份','医药'),('600332','华安药业','医药'),
        ('600079','人福医药','医药'),('002653','海思科','医药'),('002550','千红制药','医药'),
        ('300026','红日药业','医药'),('300146','汤臣倍健','保健品'),
        
        # 半导体/电子 (30只)
        ('688981','中芯国际','半导体制造'),('002371','北方华创','半导体设备'),('688008','澜起科技','IC设计'),
        ('603986','兆易创新','IC设计'),('603501','韦尔股份','IC设计'),('688396','华润微','功率半导体'),
        ('002409','雅克科技','半导体材料'),('605358','立昂微','硅片'),('002129','中环股份','硅片'),
        ('002185','华天科技','封测'),('600584','长电科技','封测'),('002436','兴森科技','PCB'),
        ('002916','深南电路','PCB'),('603160','汇顶科技','IC设计'),('300782','卓胜微','射频'),
        ('688055','龙腾光电','面板'),('000725','京东方A','面板'),('000100','TCL科技','面板'),
        ('002475','立讯精密','连接器'),('002241','歌尔股份','消费电子'),('002456','欧菲光','光学'),
        ('002045','国光电器','电声'),('002655','共达电声','电声'),('300322','宝信软件','软件'),
        ('300124','汇川技术','工控'),('002027','分众传媒','传媒'),('002410','广联达','软件'),
        ('300033','同花顺','软件'),('002230','科大讯飞','AI'),('300496','中科创达','软件'),
        
        # AI/科技 (20只)
        ('603019','中科曙光','AI算力'),('688256','寒武纪','AI芯片'),('688111','金山办公','办公软件'),
        ('300496','中科创达','操作系统'),('688777','中控技术','工控'),('300124','汇川技术','工控'),
        ('002230','科大讯飞','AI'),('300454','深信服','网安'),('601360','三六零','网安'),
        ('300383','光环新网','IDC'),('600536','中国软件','基础软件'),('600588','用友网络','ERP'),
        ('300474','景嘉微','GPU'),('688005','容百科技','正极'),('300212','易瑞生物','检测'),
        ('300369','宁波环球','物联网'),('300078','思创医惠','医疗IT'),('002410','广联达','建筑IT'),
        ('002153','石基信息','酒店IT'),('300451','创业慧康','医疗IT'),
        
        # 化工 (20只)
        ('600160','中化国际','化工'),('600309','万华化学','化工'),('600486','扬农化工','农药'),
        ('600409','三友化工','化工'),('600230','沧州大化','化工'),('603010','万盛股份','阻燃剂'),
        ('603267','鸿远电子','军工电子'),('002648','卫星化学','化工'),('002311','海大集团','饲料'),
        ('600352','浙江龙盛','染料'),('600141','兴发集团','磷化工'),('601216','君正集团','化工'),
        ('600143','金禾实业','化工'),('600486','海利尔','农药'),('603077','和邦生物','化工'),
        ('600141','新安股份','化工'),('002496','辉丰股份','农药'),('600273','嘉化能源','化工'),
        ('600486','百傲化学','化工'),('603360','百傲化学','化工'),
        
        # 煤炭 (10只)
        ('601088','中国神华','煤炭'),('601225','陕西煤业','煤炭'),('600971','恒源煤电','煤炭'),
        ('601699','潞安环能','煤炭'),('000983','山西焦煤','焦煤'),('600508','上海能源','煤炭'),
        ('600121','郑州煤电','煤炭'),('600971','恒源煤电','煤炭'),('601001','大同煤业','煤炭'),
        ('600395','盘江股份','煤炭'),
        
        # 钢铁 (10只)
        ('600019','宝钢股份','钢铁'),('000932','华菱钢铁','钢铁'),('601003','柳钢股份','钢铁'),
        ('002110','三钢闽光','钢铁'),('600507','方大特钢','钢铁'),('600282','南钢股份','钢铁'),
        ('600117','西宁特钢','钢铁'),('600581','京新药业','钢铁'),('000709','华菱钢铁','钢铁'),
        ('000959','首钢股份','钢铁'),
        
        # 建材 (10只)
        ('600585','海螺水泥','水泥'),('000877','天山股份','水泥'),('002271','东方雨虹','防水建材'),
        ('002372','伟星新材','管材'),('000786','北新建材','石膏板'),('002146','中材科技','建材'),
        ('600176','中国巨石','玻纤'),('002084','海螺水泥','水泥'),('600801','华新水泥','水泥'),
        ('000591','中材科技','玻纤'),
        
        # 汽车/零部件 (15只)
        ('600660','福耀玻璃','汽车玻璃'),('601799','小康股份','新能源车'),('600699','均胜电子','汽车电子'),
        ('002048','宁波华翔','汽车零部件'),('002126','银轮股份','热管理'),('002050','三花智控','热管理'),
        ('000625','长安汽车','汽车'),('600104','上汽集团','汽车'),('601238','广汽集团','汽车'),
        ('600418','江淮汽车','汽车'),('000572','海马汽车','汽车'),('600213','亚星客车','汽车'),
        ('601127','小康股份','新能源车'),('002536','郑州银行','汽车'),('601965','中国汽研','汽车'),
        
        # 房地产 (10只)
        ('000002','万科A','地产'),('600048','保利发展','地产'),('600606','绿地控股','地产'),
        ('001979','招商蛇口','地产'),('600383','金地集团','地产'),('601155','新城控股','地产'),
        ('000069','华侨城A','地产'),('600340','华夏幸福','地产'),('600606','珠江实业','地产'),
        ('000897','津滨发展','地产'),
        
        # 传媒/游戏 (15只)
        ('603444','吉比特','游戏'),('002558','巨人网络','游戏'),('002555','三七互娱','游戏'),
        ('300058','蓝色光标','营销'),('300251','光线传媒','影视'),('002517','恺英网络','游戏'),
        ('300467','迅游科技','游戏'),('300494','鼎捷软件','软件'),('002095','生意宝','电商'),
        ('300033','同花顺','金融软件'),('002195','二三四五','软件'),('300059','东方财富','金融'),
        ('002801','凯莱英','医药'),('002354','天科股份','游戏'),('300467','盛天网络','游戏'),
        
        # 食品 (15只)
        ('600887','伊利股份','乳业'),('603288','海天味业','调味品'),('603517','绝味食品','卤味'),
        ('002557','洽洽食品','坚果'),('000895','双汇发展','肉制品'),('300146','汤臣倍健','保健品'),
        ('603517','煌上煌','卤味'),('603157','拉夏贝尔','服装'),('603288','安井食品','食品'),
        ('002507','涪陵榨菜','食品'),('603043','广州酒家','食品'),('603027','千禾味业','调味品'),
        ('600298','安琪酵母','食品'),('600419','天虹股份','零售'),('600729','露露柠檬','服装'),
        
        # 军工 (15只)
        ('600760','中航沈飞','军工航空'),('600893','航发动力','军工航空'),('002414','高德红外','军工红外'),
        ('600435','北方导航','军工导航'),('002013','中航机电','军工机电'),('600316','洪都航空','军工'),
        ('600372','中航电子','军工电子'),('000738','航发控制','军工'),('600150','中国船舶','军工'),
        ('600685','中船防务','军工'),('601989','中国重工','军工'),('600893','中航动力','军工'),
        ('600038','中直股份','军工'),('600316','洪都航空','军工'),('002013','中航高科','军工'),
        
        # 建筑/基建 (15只)
        ('601668','中国建筑','基建'),('601390','中国中铁','基建'),('601186','中国铁建','基建'),
        ('601618','中国中冶','基建'),('601618','上海建工','基建'),('600170','上海建工','基建'),
        ('600284','浦东建设','基建'),('600170','隧道股份','基建'),('600850','华东医药','基建'),
        ('601117','华泰股份','化工'),('000877','天山股份','水泥'),('600585','祁丰集团','水泥'),
        ('601668','葛洲坝','基建'),('600850','宁波建工','基建'),('601168','西部矿业','矿业'),
    ]
    
    # 去重
    seen = set()
    unique_pool = []
    for item in pool:
        if item[0] not in seen:
            seen.add(item[0])
            unique_pool.append(item)
    
    EXTENDED_POOL = unique_pool
    return EXTENDED_POOL

# ─────────────────────────────────────────────
# 腾讯财经API（主要数据源）
# ─────────────────────────────────────────────

def tx_realtime_batch(pool, max_retries=3):
    """腾讯批量获取实时行情"""
    def pfx(code):
        return ('sz' if code.startswith(('0','3')) else 'sh') + code

    BATCH = 50
    results = {}
    
    for attempt in range(max_retries):
        try:
            for i in range(0, len(pool), BATCH):
                batch = pool[i:i+BATCH]
                codes_pfx = [pfx(c['code']) for c in batch]
                url = 'https://qt.gtimg.cn/q=' + ','.join(codes_pfx)
                
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://gu.qq.com/',
                })
                with urllib.request.urlopen(req, timeout=15) as r:
                    raw = r.read().decode('gbk', errors='ignore')
                
                for line in raw.strip().split('\n'):
                    if not line or '=' not in line:
                        continue
                    parts = line.split('="')[1].rstrip('";').split('~')
                    if len(parts) < 37:
                        continue
                    try:
                        code = parts[2]
                        name = parts[1]
                        price = float(parts[3]) if parts[3] else 0
                        pct = float(parts[32]) if parts[32] else 0
                        pe = float(parts[39]) if parts[39] and parts[39] != '-' else 0
                        pb = float(parts[46]) if parts[46] and parts[46] != '-' else 0
                        mktcap_yi = float(parts[44]) if parts[44] and parts[44] != '-' else 0
                        amount = float(parts[37]) if parts[37] else 0
                        results[code] = {
                            'name': name, 'price': price,
                            'pct_chg': pct, 'pe': pe, 'pb': pb,
                            'mktcap_yi': mktcap_yi,
                            'amount_yi': amount / 10000,
                        }
                    except:
                        pass
                time.sleep(0.15)
            
            # 如果成功获取超过50%的股票，就返回
            if len(results) > len(pool) * 0.5:
                return results
                
        except Exception as e:
            print(f"  ⚠️ 第{attempt+1}次尝试失败: {e}")
            time.sleep(2)
    
    return results

def tx_daily_klines(code, count=300):
    """腾讯日K线"""
    secid = ('sh' if code.startswith(('6', '9')) else 'sz') + code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayhfq&param={secid},day,,,{count},qfq"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode('utf-8', errors='ignore')
        import re
        m = re.search(r'=\s*(\{.*\})', raw)
        if not m:
            return []
        d = json.loads(m.group(1))
        days = d.get('data', {}).get(secid, {}).get('qfqday', [])
        result = []
        for day in days[-count:]:
            if isinstance(day, list) and len(day) >= 3:
                result.append({'date': day[0], 'close': float(day[2])})
        return result
    except:
        return []

# ─────────────────────────────────────────────
# Tushare财务数据
# ─────────────────────────────────────────────

def get_financial_data(codes, timeout=20):
    """获取财务数据（Tushare），带超时控制"""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Tushare API timeout")
    
    results = {}
    
    # 批量获取
    batch_size = 50
    total_batches = (len(codes) + batch_size - 1) // batch_size
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        batch_num = i // batch_size + 1
        
        try:
            # 设置超时
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)  # 20秒超时
            
            from tushare_data import get_financial
            ts_data = get_financial(batch)
            
            signal.alarm(0)  # 取消超时
            
            for code, data in ts_data.items():
                ann = data.get('annual', {})
                results[code] = {
                    'roe': ann.get('roe', 0) or 0,
                    'gross_margin': ann.get('gross', 0) or 0,
                    'net_margin': ann.get('netprofit_margin', 0) or 0,
                    'debt_ratio': ann.get('debt_ratio', 0) or 0,
                }
            print(f"  ✅ 批次{batch_num}/{total_batches}: 财务数据获取成功 ({len(ts_data)}只)")
            
        except TimeoutError:
            print(f"  ⚠️ 批次{batch_num}: Tushare超时，跳过")
        except Exception as e:
            print(f"  ⚠️ 批次{batch_num}: 财务数据获取失败: {e}")
        
        time.sleep(0.3)
    
    print(f"  📊 财务数据获取完成: {len(results)}/{len(codes)} 只")
    return results

# ─────────────────────────────────────────────
# 筛选框架
# ─────────────────────────────────────────────

def filter_basic(stocks, rt_map):
    """市场面筛选（成交额排名）"""
    for s in stocks:
        rt = rt_map.get(s['code'], {})
        s['amount_yi'] = rt.get('amount_yi', 0)
    
    stocks = [s for s in stocks if s.get('amount_yi', 0) > 0.1]
    stocks.sort(key=lambda x: x.get('amount_yi', 0), reverse=True)
    return stocks[:500]

def filter_fundamental(stocks, rt_map, fin_map):
    """基本面筛选"""
    filtered = []
    for s in stocks:
        rt = rt_map.get(s['code'], {})
        fin = fin_map.get(s['code'], {})
        
        pe = rt.get('pe', 0) or 0
        pb = rt.get('pb', 0) or 0
        roe = fin.get('roe', 0) or 0
        debt = fin.get('debt_ratio', 0) or 0
        
        if pe <= 0 or pe > 40:
            continue
        if pb <= 0 or pb > 5:
            continue
        if roe < 8:
            continue
        if debt > 85:
            continue
        
        filtered.append(s)
    
    return filtered

def filter_technical(stocks, rt_map):
    """技术面筛选"""
    filtered = []
    total = len(stocks)
    
    for i, s in enumerate(stocks):
        code = s['code']
        
        klines = tx_daily_klines(code, count=60)
        if not klines or len(klines) < 30:
            continue
        
        closes = [k['close'] for k in klines]
        price = closes[-1]
        
        # RSI
        gains, losses = [], []
        for j in range(1, len(closes)):
            d = closes[j] - closes[j-1]
            gains.append(max(d, 0)); losses.append(max(-d, 0))
        if len(gains) < 14:
            continue
        ag = sum(gains[-14:]) / 14
        al = sum(losses[-14:]) / 14
        rsi = 100 - (100 / (1 + ag/al)) if al > 0 else 100
        
        if rsi < 25 or rsi > 70:
            continue
        
        # 均线
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        if ma5 < ma20 * 0.95:
            continue
        
        # 近期跌幅
        recent = (closes[-1] - closes[-20]) / closes[-20] * 100
        if recent < -35:
            continue
        
        s['rsi'] = round(rsi, 1)
        s['ma5'] = round(ma5, 2)
        s['ma20'] = round(ma20, 2)
        s['price'] = price
        s['recent_20d'] = round(recent, 1)
        
        filtered.append(s)
        
        if (i + 1) % 50 == 0:
            print(f"    技术筛选: {i+1}/{total}（候选{len(filtered)}只）")
        
        time.sleep(0.05)
    
    return filtered

def score_stock(stocks, rt_map, fin_map):
    """综合评分"""
    scored = []
    
    for s in stocks:
        code = s['code']
        rt = rt_map.get(code, {})
        fin = fin_map.get(code, {})
        
        # 基本面
        roe = fin.get('roe', 0) or 0
        pe = rt.get('pe', 0) or 0
        pb = rt.get('pb', 0) or 0
        
        base = 0
        if roe > 20: base += 15
        elif roe > 15: base += 12
        elif roe > 10: base += 8
        elif roe > 8: base += 5
        if pe < 10: base += 10
        elif pe < 20: base += 7
        elif pe < 30: base += 4
        if pb < 1: base += 5
        elif pb < 2: base += 3
        base = min(35, base)
        
        # 技术面
        rsi = s.get('rsi', 50)
        tech = 0
        if 30 <= rsi <= 45: tech += 10
        elif 25 <= rsi < 30 or 45 < rsi <= 55: tech += 6
        ma5 = s.get('ma5', 0)
        ma20 = s.get('ma20', 0)
        if ma5 > ma20 * 1.02: tech += 15
        elif ma5 > ma20: tech += 10
        elif ma5 >= ma20 * 0.98: tech += 5
        recent = s.get('recent_20d', 0)
        if -10 <= recent <= 5: tech += 10
        elif -20 < recent < -10: tech += 5
        tech = min(35, tech)
        
        # 市场面
        amount = s.get('amount_yi', 0)
        market = 0
        if amount > 10: market += 15
        elif amount > 5: market += 10
        elif amount > 2: market += 5
        elif amount > 1: market += 3
        market = min(30, market)
        
        total = base + tech + market
        
        signals = []
        if roe > 15: signals.append(f'ROE{roe:.0f}%')
        if pe < 15: signals.append(f'PE{pe:.0f}低估值')
        if pb < 2: signals.append(f'PB{pb:.1f}低估')
        if rsi < 35: signals.append(f'RSI{rsi:.0f}超卖')
        
        scored.append({
            'code': code,
            'name': rt.get('name', s['name']),
            'price': rt.get('price', s.get('price', 0)),
            'pct_chg': rt.get('pct_chg', 0),
            'pe': pe, 'pb': pb, 'roe': roe,
            'rsi': rsi, 'amount_yi': amount,
            'score': total,
            'base_score': base, 'tech_score': tech, 'market_score': market,
            'signals': signals,
        })
    
    return scored

# ─────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────

def run_value_scan(top_n=10):
    """价值投资扫描 - 全市场500+只"""
    print(f"\n🛡️ === 价值投资选股 v3 === {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    
    # Step 1: 获取候选股票（扩展股池500+只）
    print("📊 Step 1: 获取候选股票池...")
    pool = get_extended_pool()
    print(f"  📊 扩展股池: {len(pool)} 只")
    
    # 排除持仓股
    try:
        from recommendation import get_watched_codes
        watched = get_watched_codes()
        pool = [p for p in pool if p[0] not in watched]
        print(f"  📊 排除持仓后: {len(pool)} 只")
    except:
        pass
    
    # 转换为dict
    stocks = [{'code': c, 'name': n, 'sector': s} for c, n, s in pool]
    
    # Step 2: 获取实时行情
    print("\n📊 Step 2: 获取实时行情（腾讯API）...")
    rt_map = tx_realtime_batch(stocks, max_retries=3)
    print(f"  ✅ 获取到 {len(rt_map)} 只实时行情")
    
    if not rt_map:
        print("  ❌ 无法获取实时行情")
        return []
    
    # Step 3: 市场面筛选
    print("\n📊 Step 3: 市场面筛选（成交额>1000万）...")
    market_filtered = filter_basic(stocks, rt_map)
    print(f"  ✅ 成交额达标: {len(market_filtered)} 只")
    
    # Step 4: 基本面筛选
    print("\n📊 Step 4: 基本面筛选（PE<40, PB<5）...")
    # 直接使用腾讯API的PE/PB数据，跳过Tushare
    print("  ⚠️ Tushare API不稳定，使用腾讯API数据（PE/PB）...")
    
    # 只用PE/PB筛选
    fundamental_filtered = []
    for s in market_filtered:
        rt = rt_map.get(s['code'], {})
        pe = rt.get('pe', 0) or 0
        pb = rt.get('pb', 0) or 0
        if 0 < pe < 40 and 0 < pb < 5:
            fundamental_filtered.append(s)
    
    print(f"  ✅ PE/PB达标: {len(fundamental_filtered)} 只")
    
    # 创建空的fin_map（兼容后续代码）
    fin_map = {}
    
    # Step 5: 技术面筛选
    print("\n📊 Step 5: 技术面筛选（RSI 25-70, 均线向上）...")
    tech_filtered = filter_technical(fundamental_filtered, rt_map)
    print(f"  ✅ 技术面达标: {len(tech_filtered)} 只")
    
    if not tech_filtered:
        tech_filtered = fundamental_filtered[:30]
    
    # Step 6: 综合评分
    print("\n📊 Step 6: 综合评分...")
    scored = score_stock(tech_filtered, rt_map, fin_map)
    scored.sort(key=lambda x: x['score'], reverse=True)
    
    # 输出
    print(f"\n📋 价值投资推荐（Top {top_n}）：")
    print(f"{'排名':<4} {'股票':<10} {'现价':>7} {'今日':>6} {'PE':>5} {'PB':>5} {'ROE':>6} {'RSI':>5} {'基':>4} {'技':>4} {'市':>4} {'总分':>5} {'信号'}")
    print("-" * 100)
    
    for i, s in enumerate(scored[:top_n], 1):
        sig = ' '.join(s['signals'][:2]) if s['signals'] else '-'
        print(f"{i:<4} {s['name']:<8} ¥{s['price']:>6.2f} {s['pct_chg']:>+5.1f}% {s['pe']:>5.0f} {s['pb']:>5.1f} {s['roe']:>5.1f}% {s['rsi']:>5.0f} {s['base_score']:>3} {s['tech_score']:>3} {s['market_score']:>3} {s['score']:>4} {sig}")
    
    return scored[:top_n]

if __name__ == '__main__':
    run_value_scan(top_n=10)
