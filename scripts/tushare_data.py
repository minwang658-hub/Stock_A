#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare Pro 数据源
Token: 来自环境变量 TUSHARE_TOKEN
API:   来自环境变量 TUSHARE_API_URL（可选）
"""

import time
import os
import pandas as pd
import tushare as ts

_token = os.environ.get("TUSHARE_TOKEN", "").strip()
_api_url = os.environ.get("TUSHARE_API_URL", "http://api.tushare.pro").strip()
_pro = None

def get_pro():
    global _pro
    if _pro is None:
        if not _token:
            raise RuntimeError("Missing TUSHARE_TOKEN environment variable")
        _pro = ts.pro_api(_token)
        _pro._DataApi__http_url = _api_url
    return _pro

TX_TO_TUSHARE = {
    '000001': '000001.SZ', '000651': '000651.SZ', '002415': '002415.SZ',
    '002594': '002594.SZ', '600036': '600036.SH', '600115': '600115.SH',
    '600160': '600160.SH', '600660': '600660.SH', '601398': '601398.SH',
    '603005': '603005.SH', '603019': '603019.SH',
}

def to_ts(code):
    return TX_TO_TUSHARE.get(code, code + '.SH' if code.startswith(('6','9')) else code + '.SZ')

def nv(v):
    try:
        return pd.notna(v) and v is not None and str(v) not in ('', 'nan', 'None')
    except:
        return v is not None and str(v) not in ('', 'nan', 'None')

# ============ 财务数据 ============

def _parse_cn_number(s) -> float | None:
    """解析中文格式数字，如 '1.23亿' -> 1.23e8, '5090.72万' -> 5.09e7"""
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


def _get_financial_akshare(code: str) -> dict:
    """使用 akshare 从同花顺获取财务数据（免费，无需 token）"""
    try:
        import akshare as ak

        # 年报数据
        df_ann = ak.stock_financial_abstract_ths(symbol=code, indicator='按年度')
        # 季报数据
        df_q = ak.stock_financial_abstract_ths(symbol=code, indicator='按报告期')

        annual = None
        if df_ann is not None and not df_ann.empty:
            # 同花顺按年度数据从旧到新排列，取最新（iloc[-1]）
            df_ann_sorted = df_ann.sort_values('报告期', ascending=False) if '报告期' in df_ann.columns else df_ann.iloc[::-1]
            r0 = df_ann_sorted.iloc[0]
            annual = {
                'end_date': str(r0['报告期']),
                'revenue': _parse_cn_number(r0.get('营业总收入')),
                'n_income': _parse_cn_number(r0.get('净利润')),
                'rev_yoy': _parse_cn_number(r0.get('营业总收入同比增长率')),
                'ni_yoy': _parse_cn_number(r0.get('净利润同比增长率')),
                'roe': _parse_cn_number(r0.get('净资产收益率')),
                'gross': _parse_cn_number(r0.get('销售毛利率')),
                'debt': _parse_cn_number(r0.get('资产负债率')),
            }

        quarter = None
        latest_fi = None
        if df_q is not None and not df_q.empty:
            # 按报告期返回从旧到新，取最新（倒数第1条）
            df_q_sorted = df_q.sort_values('报告期', ascending=False) if '报告期' in df_q.columns else df_q
            q0 = df_q_sorted.iloc[0]
            period = str(q0['报告期'])
            # 跳过年报（重复）
            if period.endswith('12-31') or str(period).endswith('1231'):
                if len(df_q_sorted) > 1:
                    q0 = df_q_sorted.iloc[1]
                    period = str(q0['报告期'])
            quarter = {
                'end_date': period,
                'period_label': period,
                'revenue': _parse_cn_number(q0.get('营业总收入')),
                'n_income': _parse_cn_number(q0.get('净利润')),
                'rev_yoy': _parse_cn_number(q0.get('营业总收入同比增长率')),
                'ni_yoy': _parse_cn_number(q0.get('净利润同比增长率')),
                'gross': _parse_cn_number(q0.get('销售毛利率')),
                'roe': _parse_cn_number(q0.get('净资产收益率')),
            }
            latest_fi = {
                'end_date': period,
                'roe': _parse_cn_number(q0.get('净资产收益率')),
                'debt': _parse_cn_number(q0.get('资产负债率')),
                'pb': None,
            }

        return {'annual': annual, 'quarter': quarter, 'latest_fi': latest_fi}
    except Exception as e:
        print(f"    WARNING: akshare financial {code} failed: {e}")
        return {}


def get_financial(codes_list):
    """
    三层财务数据（以 income 表为基准）：
    优先使用 Tushare，失败时自动降级到 akshare（免费，无需 token）
    """
    import re as _re
    result = {}

    for code in codes_list:
        # 先尝试 Tushare
        ts_result = _get_financial_tushare(code)
        if ts_result:
            result[code] = ts_result
        else:
            # 降级到 akshare
            ak_result = _get_financial_akshare(code)
            if ak_result:
                result[code] = ak_result

    return result


def _get_financial_tushare(code: str) -> dict | None:
    """原 Tushare 财务数据逻辑，失败返回 None"""
    import re as _re
    this_year = 2025
    end_dt = "%d1231" % (this_year + 1)
    ts_code = to_ts(code)
    try:
        pro = get_pro()
        try:
            inc = pro.income(
                ts_code=ts_code,
                start_date="%d0101" % (this_year - 5),
                end_date=str(end_dt),
                fields="ts_code,ann_date,end_date,report_type,total_revenue,n_income"
            )
        except Exception:
            inc = None

        try:
            fi = pro.fina_indicator(
                ts_code=ts_code,
                start_date="%d0101" % (this_year - 5),
                fields="ts_code,ann_date,end_date,roe,grossprofit_margin,"
                       "netprofit_margin,debt_to_assets,eps,bps,roe_yoy,"
                       "netprofit_yoy,or_yoy"
            )
        except Exception:
            fi = None
        if fi is None or fi.empty:
            return None
        fi = fi.dropna(subset=["roe"])
        if fi.empty:
            return None
        fi = fi.sort_values("end_date", ascending=False).drop_duplicates(subset=["end_date"])

        if inc is not None and not inc.empty:
            inc = inc.drop_duplicates(subset=["end_date"], keep="first")
            inc = inc.sort_values("end_date", ascending=False)

        inc_ann = None
        if inc is not None and not inc.empty:
            try:
                inc_ann = inc[inc["end_date"].astype(str).str.endswith("1231")]
            except Exception:
                inc_ann = None
        annual = None
        if inc_ann is not None and not inc_ann.empty:
            a0 = inc_ann.iloc[0]
            a1 = inc_ann.iloc[1] if len(inc_ann) >= 2 else None
            annual = {
                "end_date": str(a0["end_date"]),
                "ann_date": str(a0["ann_date"]),
                "revenue": float(a0["total_revenue"]) if nv(a0.get("total_revenue")) else None,
                "n_income": float(a0["n_income"]) if nv(a0.get("n_income")) else None,
            }
            if a1 is not None and nv(a0.get("total_revenue")) and nv(a1.get("total_revenue")):
                rev0, rev1 = float(a0["total_revenue"]), float(a1["total_revenue"])
                if rev1 != 0:
                    annual["rev_yoy"] = round((rev0 - rev1) / rev1 * 100, 2)
            if a1 is not None and nv(a0.get("n_income")) and nv(a1.get("n_income")):
                ni0, ni1 = float(a0["n_income"]), float(a1["n_income"])
                if ni1 != 0:
                    annual["ni_yoy"] = round((ni0 - ni1) / ni1 * 100, 2)
            ann_end = str(a0["end_date"])
            fi_match = fi[fi["end_date"].astype(str) == ann_end]
            if not fi_match.empty:
                fm = fi_match.iloc[0]
                annual.update({
                    "roe":      round(float(fm["roe"]), 2) if nv(fm.get("roe")) else None,
                    "gross":    round(float(fm["grossprofit_margin"]), 2) if nv(fm.get("grossprofit_margin")) else None,
                    "net_margin": round(float(fm["netprofit_margin"]), 2) if nv(fm.get("netprofit_margin")) else None,
                    "debt":     round(float(fm["debt_to_assets"]), 2) if nv(fm.get("debt_to_assets")) else None,
                    "roe_yoy":  round(float(fm["roe_yoy"]), 2) if nv(fm.get("roe_yoy")) else None,
                })

        latest_fi = None
        if not fi.empty:
            r0 = fi.iloc[0]
            latest_fi = {
                "end_date": str(r0["end_date"]),
                "ann_date": str(r0["ann_date"]),
                "roe":      round(float(r0["roe"]), 2) if nv(r0.get("roe")) else None,
                "gross":    round(float(r0["grossprofit_margin"]), 2) if nv(r0.get("grossprofit_margin")) else None,
                "net_margin": round(float(r0["netprofit_margin"]), 2) if nv(r0.get("netprofit_margin")) else None,
                "debt":     round(float(r0["debt_to_assets"]), 2) if nv(r0.get("debt_to_assets")) else None,
                "roe_yoy":  round(float(r0["roe_yoy"]), 2) if nv(r0.get("roe_yoy")) else None,
                "or_yoy":   round(float(r0["or_yoy"]), 2) if nv(r0.get("or_yoy")) else None,
                "ni_yoy":   round(float(r0["netprofit_yoy"]), 2) if nv(r0.get("netprofit_yoy")) else None,
            }

        quarter = None
        if inc is not None and not inc.empty:
            inc_q = inc[~inc["end_date"].astype(str).str.endswith("1231")]
            if not inc_q.empty:
                q0 = inc_q.iloc[0]
                period = str(q0["end_date"])
                quarter = {
                    "end_date": period,
                    "period_label": "Q%d %s" % (int(period[4:6]) // 3, period[:4]),
                    "revenue": float(q0["total_revenue"]) if nv(q0.get("total_revenue")) else None,
                    "n_income": float(q0["n_income"]) if nv(q0.get("n_income")) else None,
                }
                cur_year = int(period[:4])
                prev_year_period = "%d%s" % (cur_year - 1, period[4:])
                q_prev_row = inc_q[inc_q["end_date"].astype(str) == prev_year_period]
                if not q_prev_row.empty:
                    qp = q_prev_row.iloc[0]
                    if nv(q0.get("total_revenue")) and nv(qp.get("total_revenue")) and float(qp["total_revenue"]) != 0:
                        quarter["rev_yoy"] = round((float(q0["total_revenue"]) - float(qp["total_revenue"])) / float(qp["total_revenue"]) * 100, 1)
                    if nv(q0.get("n_income")) and nv(qp.get("n_income")) and float(qp["n_income"]) != 0:
                        quarter["ni_yoy"] = round((float(q0["n_income"]) - float(qp["n_income"])) / float(qp["n_income"]) * 100, 1)
                fi_q = fi[fi["end_date"].astype(str) == period]
                if not fi_q.empty:
                    fq = fi_q.iloc[0]
                    quarter.update({
                        "roe":      round(float(fq["roe"]), 2) if nv(fq.get("roe")) else None,
                        "gross":    round(float(fq["grossprofit_margin"]), 2) if nv(fq.get("grossprofit_margin")) else None,
                        "net_margin": round(float(fq["netprofit_margin"]), 2) if nv(fq.get("netprofit_margin")) else None,
                        "or_yoy":   round(float(fq["or_yoy"]), 2) if nv(fq.get("or_yoy")) else None,
                    })

        return {"annual": annual, "latest_fi": latest_fi, "quarter": quarter}

    except Exception as e:
        print("    WARNING: Tushare financial %s failed: %s" % (code, e))
        return None


def get_capital_flow(codes_list):
    """
    获取资金流向，返回 {code: {ddx5, ddx10, main_in_yi, margin_yi}}
    优先 Tushare，失败时用东方财富历史资金流接口（免费）
    """
    result = {}
    for code in codes_list:
        flow = _get_capital_flow_tushare(code)
        if flow is None:
            flow = _get_capital_flow_eastmoney(code)
        if flow:
            result[code] = flow
    return result


def _get_capital_flow_tushare(code: str) -> dict | None:
    """原 Tushare 资金流逻辑，失败返回 None"""
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime('%Y%m%d')
    start_10d = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d')
    ts_code = to_ts(code)
    try:
        pro = get_pro()
        mf = pro.moneyflow(
            ts_code=ts_code, start_date=start_10d, end_date=end_date,
            fields='ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount'
        )
        if mf is None or mf.empty:
            return None
        mf['main_net'] = (
            mf['buy_lg_amount'].fillna(0) + mf['buy_elg_amount'].fillna(0)
            - mf['sell_lg_amount'].fillna(0) - mf['sell_elg_amount'].fillna(0)
        )
        mf5 = mf.head(5)
        def total_amount(df):
            s = 0.0
            for col in ['buy_sm_amount','sell_sm_amount','buy_md_amount','sell_md_amount',
                        'buy_lg_amount','sell_lg_amount','buy_elg_amount','sell_elg_amount']:
                s += df[col].fillna(0).sum()
            return s
        main_5d = float(mf5['main_net'].sum())
        main_10d = float(mf['main_net'].sum())
        total_5d = total_amount(mf5)
        total_10d = total_amount(mf)
        ddx5 = round(main_5d / total_5d * 100, 3) if total_5d else 0
        ddx10 = round(main_10d / total_10d * 100, 3) if total_10d else 0
        flow = {
            'ddx5': ddx5, 'ddx10': ddx10,
            'main_in_yi': round(main_5d / 10000, 2),
            'main_10d_yi': round(main_10d / 10000, 2),
        }
        try:
            margin = pro.margin_detail(ts_code=ts_code, trade_date=end_date, fields='ts_code,rzye')
            if margin is not None and not margin.empty and nv(margin.iloc[0].get('rzye')):
                flow['margin_yi'] = round(float(margin.iloc[0]['rzye']) / 1e8, 2)
        except Exception:
            pass
        return flow
    except Exception as e:
        print(f"    WARNING: Tushare capital flow {code} failed: {e}")
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
        rows5 = rows[-5:] if len(rows) >= 5 else rows
        rows10 = rows[-10:] if len(rows) >= 10 else rows
        main_5d = sum(rows5)
        main_10d = sum(rows10)
        abs_5d = sum(abs(r) for r in rows5) or 1
        abs_10d = sum(abs(r) for r in rows10) or 1
        return {
            'ddx5': round(main_5d / abs_5d * 100, 3),
            'ddx10': round(main_10d / abs_10d * 100, 3),
            'main_in_yi': round(main_5d / 1e8, 2),
            'main_10d_yi': round(main_10d / 1e8, 2),
        }
    except Exception as e:
        print(f"    WARNING: EastMoney capital flow {code} failed: {e}")
        return None
