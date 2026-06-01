#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据源（akshare）
替代原 Tushare Pro 数据源，使用 akshare 免费接口。
保持与原模块相同的公开 API：get_financial / get_capital_flow / to_ts
"""

import time
import os
import pandas as pd

# ── akshare 懒加载，避免启动时报错 ──────────────────────────────────────────
_ak = None

def _get_ak():
    global _ak
    if _ak is None:
        import akshare as ak
        _ak = ak
    return _ak


def to_ts(code: str) -> str:
    """将纯6位代码转换为 Tushare 格式（兼容旧调用方）"""
    return code + '.SH' if code.startswith(('6', '9')) else code + '.SZ'


# ── get_pro 保留为空壳，避免旧代码 import 报错 ──────────────────────────────
def get_pro():
    raise RuntimeError(
        "Tushare 已被移除，请改用 akshare 接口。"
        "如需股票基础信息，请调用 akshare.stock_info_a_code_name()。"
    )

def nv(v):
    try:
        return pd.notna(v) and v is not None and str(v) not in ('', 'nan', 'None')
    except Exception:
        return v is not None and str(v) not in ('', 'nan', 'None')


# ============ 财务数据 ============

def _parse_cn_number(s) -> float | None:
    """解析中文格式数字，如 '1.23亿' -> 1.23e8, '5090.72万' -> 5.09e7, '12.3%' -> 12.3"""
    if s is None or str(s).strip() in ('', '--', 'False', 'nan', 'None'):
        return None
    s = str(s).strip()
    try:
        if '亿' in s:
            return float(s.replace('亿', '')) * 1e8
        elif '万' in s:
            return float(s.replace('万', '')) * 1e4
        elif '%' in s:
            return float(s.replace('%', ''))
        else:
            return float(s)
    except Exception:
        return None


def get_financial(codes_list: list) -> dict:
    """
    使用 akshare 从同花顺获取财务数据（免费，无需 token）。
    返回 {code: {annual, quarter, latest_fi}}，结构与原 Tushare 版本兼容。
    """
    result = {}
    ak = _get_ak()
    for code in codes_list:
        try:
            # 年报数据
            df_ann = ak.stock_financial_abstract_ths(symbol=code, indicator='按年度')
            # 季报数据
            df_q = ak.stock_financial_abstract_ths(symbol=code, indicator='按报告期')

            annual = None
            if df_ann is not None and not df_ann.empty:
                df_ann_sorted = (
                    df_ann.sort_values('报告期', ascending=False)
                    if '报告期' in df_ann.columns
                    else df_ann.iloc[::-1]
                )
                r0 = df_ann_sorted.iloc[0]
                annual = {
                    'end_date': str(r0['报告期']),
                    'revenue':  _parse_cn_number(r0.get('营业总收入')),
                    'n_income': _parse_cn_number(r0.get('净利润')),
                    'rev_yoy':  _parse_cn_number(r0.get('营业总收入同比增长率')),
                    'ni_yoy':   _parse_cn_number(r0.get('净利润同比增长率')),
                    'roe':      _parse_cn_number(r0.get('净资产收益率')),
                    'gross':    _parse_cn_number(r0.get('销售毛利率')),
                    'debt':     _parse_cn_number(r0.get('资产负债率')),
                }

            quarter = None
            latest_fi = None
            if df_q is not None and not df_q.empty:
                df_q_sorted = (
                    df_q.sort_values('报告期', ascending=False)
                    if '报告期' in df_q.columns
                    else df_q
                )
                q0 = df_q_sorted.iloc[0]
                period = str(q0['报告期'])
                # 跳过年报（避免与 annual 重复）
                if period.endswith('12-31') or period.endswith('1231'):
                    if len(df_q_sorted) > 1:
                        q0 = df_q_sorted.iloc[1]
                        period = str(q0['报告期'])
                quarter = {
                    'end_date':     period,
                    'period_label': period,
                    'revenue':  _parse_cn_number(q0.get('营业总收入')),
                    'n_income': _parse_cn_number(q0.get('净利润')),
                    'rev_yoy':  _parse_cn_number(q0.get('营业总收入同比增长率')),
                    'ni_yoy':   _parse_cn_number(q0.get('净利润同比增长率')),
                    'gross':    _parse_cn_number(q0.get('销售毛利率')),
                    'roe':      _parse_cn_number(q0.get('净资产收益率')),
                }
                latest_fi = {
                    'end_date': period,
                    'roe':  _parse_cn_number(q0.get('净资产收益率')),
                    'debt': _parse_cn_number(q0.get('资产负债率')),
                    'pb':   None,
                }

            if annual or quarter:
                result[code] = {
                    'annual':    annual,
                    'quarter':   quarter,
                    'latest_fi': latest_fi,
                }
        except Exception as e:
            print(f"    WARNING: akshare financial {code} failed: {e}")

    return result


def get_capital_flow(codes_list: list) -> dict:
    """
    获取资金流向，返回 {code: {ddx5, ddx10, main_in_yi, margin_yi}}。
    优先使用 akshare 同花顺资金流，失败时降级到东方财富免费接口。
    """
    result = {}
    for code in codes_list:
        flow = _get_capital_flow_akshare(code)
        if flow is None:
            flow = _get_capital_flow_eastmoney(code)
        if flow:
            result[code] = flow
    return result


def _get_capital_flow_akshare(code: str) -> dict | None:
    """akshare 同花顺资金流向（免费）"""
    try:
        ak = _get_ak()
        # stock_individual_fund_flow 返回近期资金流数据
        df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith(('6', '9')) else "sz")
        if df is None or df.empty:
            return None
        # 取最近10行
        df = df.tail(10).reset_index(drop=True)
        # 列名示例：日期, 主力净流入-净额, 主力净流入-净占比, ...
        main_col = next((c for c in df.columns if '主力净流入' in c and '净额' in c), None)
        if main_col is None:
            return None
        vals = df[main_col].apply(lambda x: _parse_cn_number(x) or 0.0).tolist()
        vals5  = vals[-5:]  if len(vals) >= 5  else vals
        vals10 = vals[-10:] if len(vals) >= 10 else vals
        main_5d  = sum(vals5)
        main_10d = sum(vals10)
        abs_5d   = sum(abs(v) for v in vals5)  or 1
        abs_10d  = sum(abs(v) for v in vals10) or 1
        return {
            'ddx5':        round(main_5d  / abs_5d  * 100, 3),
            'ddx10':       round(main_10d / abs_10d * 100, 3),
            'main_in_yi':  round(main_5d  / 1e8, 2),
            'main_10d_yi': round(main_10d / 1e8, 2),
        }
    except Exception as e:
        print(f"    WARNING: akshare capital flow {code} failed: {e}")
        return None


def _get_capital_flow_eastmoney(code: str) -> dict | None:
    """东方财富历史资金流向接口（免费，无需 token）"""
    import urllib.request as _urlreq
    import json as _j
    try:
        mkt = '1' if code.startswith(('6', '9')) else '0'
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
            f"?klt=101&secid={mkt}.{code}"
            f"&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56"
        )
        req = _urlreq.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _urlreq.urlopen(req, timeout=8) as resp:
            data = _j.loads(resp.read().decode('utf-8'))
        klines = data.get('data', {}).get('klines') or []
        if not klines:
            return None
        rows = []
        for line in klines:
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    rows.append(float(parts[1]))
                except Exception:
                    pass
        if not rows:
            return None
        rows5  = rows[-5:]  if len(rows) >= 5  else rows
        rows10 = rows[-10:] if len(rows) >= 10 else rows
        main_5d  = sum(rows5)
        main_10d = sum(rows10)
        abs_5d   = sum(abs(r) for r in rows5)  or 1
        abs_10d  = sum(abs(r) for r in rows10) or 1
        return {
            'ddx5':        round(main_5d  / abs_5d  * 100, 3),
            'ddx10':       round(main_10d / abs_10d * 100, 3),
            'main_in_yi':  round(main_5d  / 1e8, 2),
            'main_10d_yi': round(main_10d / 1e8, 2),
        }
    except Exception as e:
        print(f"    WARNING: EastMoney capital flow {code} failed: {e}")
        return None
