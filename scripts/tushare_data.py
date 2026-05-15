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
_api_url = os.environ.get("TUSHARE_API_URL", "http://121.40.135.59:8010/").strip()
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
def get_financial(codes_list):
    """
    三层财务数据（以 income 表为基准）：
    1. income 年报基准：income 表最新年报（含同比）
    2. 最新财务指标：fina_indicator 最新一期（与年报期间对齐）
    3. 最新季报累计：income + fina_indicator 最新季度数据

    返回 {code: {annual{...}, latest_fi{...}, quarter{...}}}
    """
    import re as _re
    pro = get_pro()
    result = {}

    this_year = 2025  # 当前已知最新年报年份（截至 Q3 财报季）
    # 动态往后取，覆盖次年 1-4 月补发的年报
    end_dt = "%d1231" % (this_year + 1)

    for code in codes_list:
        ts_code = to_ts(code)
        try:
            # ── income 表：取近 5 年年报 + 近 3 年季报 ──
            try:
                inc = pro.income(
                    ts_code=ts_code,
                    start_date="%d0101" % (this_year - 5),
                    end_date=str(end_dt),
                    fields="ts_code,ann_date,end_date,report_type,total_revenue,n_income"
                )
            except Exception as e:
                inc = None

            # ── fina_indicator 表：取近 5 年 ──
            try:
                fi = pro.fina_indicator(
                    ts_code=ts_code,
                    start_date="%d0101" % (this_year - 5),
                    fields="ts_code,ann_date,end_date,roe,grossprofit_margin,"
                           "netprofit_margin,debt_to_assets,eps,bps,roe_yoy,"
                           "netprofit_yoy,or_yoy"
                )
            except Exception as e:
                fi = None
            if fi is None or fi.empty:
                continue
            fi = fi.dropna(subset=["roe"])
            fi = fi.sort_values("end_date", ascending=False).drop_duplicates(subset=["end_date"])

            if inc is not None and not inc.empty:
                inc = inc.drop_duplicates(subset=["end_date"], keep="first")
                inc = inc.sort_values("end_date", ascending=False)

            # ── Layer 1: income 年报基准 ──
            inc_ann = None
            if inc is not None and not inc.empty:
                try:
                    inc_ann = inc[inc["end_date"].astype(str).str.endswith("1231")]
                except:
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
                # 同比（income 表直接计算）
                if a1 is not None and nv(a0.get("total_revenue")) and nv(a1.get("total_revenue")):
                    rev0, rev1 = float(a0["total_revenue"]), float(a1["total_revenue"])
                    if rev1 != 0:
                        annual["rev_yoy"] = round((rev0 - rev1) / rev1 * 100, 2)
                if a1 is not None and nv(a0.get("n_income")) and nv(a1.get("n_income")):
                    ni0, ni1 = float(a0["n_income"]), float(a1["n_income"])
                    if ni1 != 0:
                        annual["ni_yoy"] = round((ni0 - ni1) / ni1 * 100, 2)

                # 与年报期间对齐的 fina_indicator
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

            # ── Layer 2: fina_indicator 最新一期 ──
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

            # ── Layer 3: 最新季报累计 ──
            quarter = None
            if inc is not None and not inc.empty:
                # 取非 1231 的最新季报
                inc_q = inc[~inc["end_date"].astype(str).str.endswith("1231")]
                if not inc_q.empty:
                    q0 = inc_q.iloc[0]
                    q1 = inc_q.iloc[1] if len(inc_q) >= 2 else None
                    period = str(q0["end_date"])
                    quarter = {
                        "end_date": period,
                        "period_label": "Q%d %s" % (int(period[4:6]) // 3, period[:4]),
                        "revenue": float(q0["total_revenue"]) if nv(q0.get("total_revenue")) else None,
                        "n_income": float(q0["n_income"]) if nv(q0.get("n_income")) else None,
                    }
                    # 季报同比（与去年同期同季度比，如 Q3 2025 vs Q3 2024）
                    # 按月份匹配，而非简单取下一行
                    # 上年同期：保持8位格式 YYYYMMDD
                    cur_year = int(period[:4])
                    prev_year_period = "%d%s" % (cur_year - 1, period[4:])  # "20250930" → "20240930"
                    q_prev_row = inc_q[inc_q["end_date"].astype(str) == prev_year_period]
                    if not q_prev_row.empty:
                        qp = q_prev_row.iloc[0]
                        if nv(q0.get("total_revenue")) and nv(qp.get("total_revenue")) and float(qp["total_revenue"]) != 0:
                            quarter["rev_yoy"] = round((float(q0["total_revenue"]) - float(qp["total_revenue"])) / float(qp["total_revenue"]) * 100, 1)
                        if nv(q0.get("n_income")) and nv(qp.get("n_income")) and float(qp["n_income"]) != 0:
                            quarter["ni_yoy"] = round((float(q0["n_income"]) - float(qp["n_income"])) / float(qp["n_income"]) * 100, 1)
                    # 对应期间 fina_indicator
                    fi_q = fi[fi["end_date"].astype(str) == period]
                    if not fi_q.empty:
                        fq = fi_q.iloc[0]
                        quarter.update({
                            "roe":      round(float(fq["roe"]), 2) if nv(fq.get("roe")) else None,
                            "gross":    round(float(fq["grossprofit_margin"]), 2) if nv(fq.get("grossprofit_margin")) else None,
                            "net_margin": round(float(fq["netprofit_margin"]), 2) if nv(fq.get("netprofit_margin")) else None,
                            "or_yoy":   round(float(fq["or_yoy"]), 2) if nv(fq.get("or_yoy")) else None,
                        })

            result[code] = {"annual": annual, "latest_fi": latest_fi, "quarter": quarter}

        except Exception as e:
            print("    WARNING: Tushare financial %s failed: %s" % (code, e))
        time.sleep(0.5)
    return result



def get_capital_flow(codes_list):
    """
    获取资金流向，返回 {code: {ddx5, ddx10, main_in_yi, margin_yi}}
    """
    pro = get_pro()
    result = {}
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime('%Y%m%d')
    start_5d = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')
    start_10d = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d')

    for code in codes_list:
        ts_code = to_ts(code)
        try:
            mf = pro.moneyflow(
                ts_code=ts_code,
                start_date=start_10d,
                end_date=end_date,
                fields='ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount'
            )

            if mf is None or mf.empty:
                continue

            # 主力 = 大单 + 超大单
            mf['main_net'] = (
                mf['buy_lg_amount'].fillna(0) + mf['buy_elg_amount'].fillna(0)
                - mf['sell_lg_amount'].fillna(0) - mf['sell_elg_amount'].fillna(0)
            )

            mf5 = mf.head(5)
            mf10 = mf

            main_5d = float(mf5['main_net'].sum()) if not mf5.empty else 0
            main_10d = float(mf10['main_net'].sum()) if not mf10.empty else 0

            def total_amount(df):
                s = 0.0
                for col in ['buy_sm_amount','sell_sm_amount','buy_md_amount','sell_md_amount',
                            'buy_lg_amount','sell_lg_amount','buy_elg_amount','sell_elg_amount']:
                    s += df[col].fillna(0).sum()
                return s

            total_5d = total_amount(mf5)
            total_10d = total_amount(mf10)

            ddx5 = round(main_5d / total_5d * 100, 3) if total_5d else 0
            ddx10 = round(main_10d / total_10d * 100, 3) if total_10d else 0

            result[code] = {
                'ddx5': ddx5,
                'ddx10': ddx10,
                'main_in_yi': round(main_5d / 10000, 2),
                'main_10d_yi': round(main_10d / 10000, 2),
            }

        except Exception as e:
            print(f"    ⚠️ Tushare资金流 {code} 失败: {e}")

        # 融资融券
        try:
            margin = pro.margin_detail(
                ts_code=ts_code,
                trade_date=end_date,
                fields='ts_code,trade_date,rzye,rqye'
            )
            if margin is not None and not margin.empty and nv(margin.iloc[0].get('rzye')):
                result[code]['margin_yi'] = round(float(margin.iloc[0]['rzye']) / 100000000, 2)
        except:
            pass

        time.sleep(0.3)

    return result
