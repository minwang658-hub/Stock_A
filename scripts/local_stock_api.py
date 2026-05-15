#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地股票分析接口

启动方式:
  python scripts/local_stock_api.py

接口:
  GET /api/health
  GET /api/stock?code=002208
  GET /api/stock?query=合肥城建
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

import sys

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from comprehensive_data import tx_daily, tx_realtime_full, calc_rsi  # noqa: E402
from tushare_data import get_financial, get_capital_flow, get_pro, to_ts  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
import uvicorn  # noqa: E402


NAME_TO_CODE = {
    "合肥城建": "002208",
    "万科A": "000002",
    "万科": "000002",
    "保利发展": "600048",
    "招商蛇口": "001979",
    "上海建工": "600170",
    "城建发展": "600266",
    "安徽建工": "600502",
}

_EVENT_CACHE: dict[str, tuple[float, dict]] = {}
_EVENT_CACHE_TTL_SEC = 60
_NAME_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_NAME_CACHE_TTL_SEC = 600

API_HOST = os.environ.get("MIMI_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("MIMI_API_PORT", "8765"))
API_KEY = os.environ.get("MIMI_API_KEY", "").strip()
ALLOWED_ORIGIN = os.environ.get("MIMI_ALLOWED_ORIGIN", "*").strip() or "*"

app = FastAPI(title="Mimi Stock API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


def _fmt_code(code: str) -> str:
    c = (code or "").strip()
    if c.startswith(("sh", "sz")) and len(c) == 8:
        return c[2:]
    return c


def _load_name_code_map() -> dict[str, str]:
    now = time.time()
    cache = _NAME_CACHE.get("stock_basic")
    if cache and now - cache[0] <= _NAME_CACHE_TTL_SEC:
        return cache[1]

    mapping: dict[str, str] = {}
    try:
        pro = get_pro()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name")
        if df is not None and not df.empty:
            for r in df.to_dict("records"):
                name = str(r.get("name") or "").strip()
                sym = str(r.get("symbol") or "").strip()
                if name and sym and len(sym) == 6 and sym.isdigit():
                    mapping[name] = sym
    except Exception:
        pass

    # 保底映射
    mapping.update(NAME_TO_CODE)
    _NAME_CACHE["stock_basic"] = (now, mapping)
    return mapping


def resolve_code(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    q_code = _fmt_code(q)
    if q_code.isdigit() and len(q_code) == 6:
        return q_code

    if q in NAME_TO_CODE:
        return NAME_TO_CODE[q]

    # 动态名称解析（全市场在市股票）
    name_map = _load_name_code_map()
    if q in name_map:
        return name_map[q]

    # 兼容去空格/全角空格后的名称
    compact = q.replace(" ", "").replace("\u3000", "")
    if compact in name_map:
        return name_map[compact]

    return None


def _ma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            window = values[i + 1 - period : i + 1]
            out.append(round(sum(window) / period, 3))
    return out


def _safe_pct(new_v: float, old_v: float) -> float | None:
    if old_v == 0:
        return None
    return round((new_v - old_v) / old_v * 100, 2)


def _fmt_num(v: float | None, digits: int = 2, suffix: str = "") -> str:
    if v is None:
        return "--"
    return f"{v:.{digits}f}{suffix}"


def _level_from_title(title: str) -> str:
    t = (title or "").lower()
    high_kw = ["异动", "涨停", "停牌", "复牌", "业绩预告", "大额", "回购", "减持", "增持", "监管", "处罚", "重组", "并购"]
    medium_kw = ["股东会", "董事", "监事", "问询", "回复", "政策", "楼市", "地产", "房贷", "公积金"]
    if any(k in t for k in high_kw):
        return "高"
    if any(k in t for k in medium_kw):
        return "中"
    return "低"


def _credibility(source: str, has_url: bool, event_type: str) -> int:
    s = (source or "").lower()
    if event_type == "公司公告":
        return 95 if has_url else 90
    if any(k in s for k in ["xinhua", "cctv", "新华社", "央视", "gov", "人民"]):
        return 88 if has_url else 82
    if any(k in s for k in ["yicai", "stcn", "eastmoney", "cnstock", "sina", "10jqka", "jinrongjie"]):
        return 78 if has_url else 72
    return 68 if has_url else 62


def _credibility_detail(source: str, has_url: bool, event_type: str) -> tuple[int, str]:
    score = _credibility(source, has_url, event_type)
    if event_type == "公司公告":
        reason = "交易所/巨潮公告优先级最高" + ("，且含原文链接" if has_url else "")
        return score, reason

    s = (source or "").lower()
    if any(k in s for k in ["xinhua", "cctv", "新华社", "央视", "gov", "人民"]):
        reason = "主流官方媒体源" + ("，含链接" if has_url else "")
        return score, reason
    if any(k in s for k in ["yicai", "stcn", "eastmoney", "cnstock", "sina", "10jqka", "jinrongjie"]):
        reason = "主流财经媒体源" + ("，含链接" if has_url else "")
        return score, reason
    return score, "普通媒体/聚合源，需交叉验证"


def _fmt_ymd(date_s: str) -> str:
    s = (date_s or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} 00:00:00"
    return s


def _normalize_title(title: str) -> str:
    t = (title or "").strip().lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[，。、“”‘’：:；;,.!?！？\-_/()（）\[\]{}<>《》|]+", "", t)
    t = re.sub(r"\d{2,}", "#", t)
    return t[:40]


def _topic_from_title(title: str, event_type: str) -> str:
    t = (title or "")
    if any(k in t for k in ["异动", "涨停", "跌停", "龙虎榜"]):
        return "股价异动"
    if any(k in t for k in ["业绩", "年报", "季报", "财报", "盈利"]):
        return "业绩财报"
    if any(k in t for k in ["董事", "监事", "高管", "股东会", "问询", "回复"]):
        return "公司治理"
    if any(k in t for k in ["回购", "减持", "增持", "重组", "并购"]):
        return "资本运作"
    if any(k in t for k in ["地产", "楼市", "住建", "房贷", "公积金", "土地", "保障房", "城中村"]):
        return "地产政策"
    return event_type


def _dedup_and_group_events(events: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    dedup: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for e in events:
        title = str(e.get("title") or "")
        source = str(e.get("source") or "")
        day = str(e.get("time") or "")[:10]
        key = (_normalize_title(title), source.lower(), day)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(e)

    groups: dict[str, dict] = {}
    for e in dedup:
        topic = _topic_from_title(str(e.get("title") or ""), str(e.get("event_type") or "事件"))
        g = groups.get(topic)
        if not g:
            groups[topic] = {
                "topic": topic,
                "count": 1,
                "latest_time": str(e.get("time") or "--"),
                "top_impact": str(e.get("impact_level") or "低"),
                "sample_titles": [str(e.get("title") or "--")],
            }
        else:
            g["count"] += 1
            if str(e.get("time") or "") > str(g.get("latest_time") or ""):
                g["latest_time"] = str(e.get("time") or "--")
            if g["top_impact"] != "高" and str(e.get("impact_level") or "") == "高":
                g["top_impact"] = "高"
            if len(g["sample_titles"]) < 2 and str(e.get("title") or "") not in g["sample_titles"]:
                g["sample_titles"].append(str(e.get("title") or "--"))

    group_list = sorted(groups.values(), key=lambda x: (x["count"], x["latest_time"]), reverse=True)
    dedup_stats = {
        "raw_total": len(events),
        "dedup_total": len(dedup),
        "removed": len(events) - len(dedup),
    }
    return dedup, dedup_stats, group_list


def _recent_fact_events(code: str, name: str) -> dict:
    now = time.time()
    cache_key = f"{code}:{name}"
    cache_v = _EVENT_CACHE.get(cache_key)
    if cache_v and now - cache_v[0] <= _EVENT_CACHE_TTL_SEC:
        return cache_v[1]

    events: list[dict] = []
    latest_ann_title = None
    latest_policy_title = None
    try:
        pro = get_pro()
        ts_code = to_ts(code)
        today = datetime.now().strftime("%Y%m%d")
        start_30d = (datetime.now().timestamp() - 30 * 86400)
        start_30d_str = datetime.fromtimestamp(start_30d).strftime("%Y%m%d")

        # 1) 公司公告（事实强）
        try:
            ann_df = pro.anns_d(
                ts_code=ts_code,
                start_date=start_30d_str,
                end_date=today,
                fields="ts_code,name,title,ann_date,url",
            )
            if ann_df is not None and not ann_df.empty:
                ann_rows = ann_df.head(8).to_dict("records")
                for r in ann_rows:
                    title = str(r.get("title") or "").strip()
                    d = _fmt_ymd(str(r.get("ann_date") or ""))
                    url = str(r.get("url") or "").strip()
                    score, score_reason = _credibility_detail("cninfo", bool(url), "公司公告")
                    e = {
                        "event_type": "公司公告",
                        "time": d,
                        "title": title or "--",
                        "source": "巨潮资讯/交易所公告",
                        "url": url or None,
                        "impact_level": _level_from_title(title),
                        "credibility_score": score,
                        "credibility_reason": score_reason,
                        "evidence": "公告标题与公告链接",
                    }
                    events.append(e)
                if ann_rows:
                    latest_ann_title = str(ann_rows[0].get("title") or "").strip() or None
        except Exception:
            pass

        # 2) 政策/宏观新闻（按关键词筛）
        policy_kw = ["地产", "楼市", "住建", "房贷", "公积金", "保障房", "土地", "城中村"]
        try:
            major_df = pro.major_news(
                src="sina",
                start_date=datetime.fromtimestamp(start_30d).strftime("%Y-%m-%d") + " 00:00:00",
                end_date=datetime.now().strftime("%Y-%m-%d") + " 23:59:59",
                fields="pub_time,src,title,content",
            )
            if major_df is not None and not major_df.empty:
                for r in major_df.head(120).to_dict("records"):
                    title = str(r.get("title") or "").strip()
                    content = str(r.get("content") or "")
                    merged = f"{title} {content}"
                    if not any(k in merged for k in policy_kw):
                        continue
                    source = str(r.get("src") or "major_news").strip()
                    score, score_reason = _credibility_detail(source, False, "政策新闻")
                    e = {
                        "event_type": "政策新闻",
                        "time": str(r.get("pub_time") or "").strip() or "--",
                        "title": title or "--",
                        "source": source,
                        "url": None,
                        "impact_level": _level_from_title(title),
                        "credibility_score": score,
                        "credibility_reason": score_reason,
                        "evidence": "政策关键词命中与新闻标题",
                    }
                    events.append(e)
                    if not latest_policy_title:
                        latest_policy_title = title or None
                    if len([x for x in events if x["event_type"] == "政策新闻"]) >= 6:
                        break
        except Exception:
            pass

        # 3) 个股相关新闻（名称/代码筛）
        try:
            news_df = pro.news(
                start_date=datetime.fromtimestamp(start_30d).strftime("%Y-%m-%d") + " 00:00:00",
                end_date=datetime.now().strftime("%Y-%m-%d") + " 23:59:59",
                fields="datetime,src,title,content",
            )
            if news_df is not None and not news_df.empty:
                matcher = [name, code, to_ts(code)]
                count = 0
                for r in news_df.head(200).to_dict("records"):
                    title = str(r.get("title") or "").strip()
                    content = str(r.get("content") or "")
                    merged = f"{title} {content}"
                    if not any(m and m in merged for m in matcher):
                        continue
                    source = str(r.get("src") or "news").strip()
                    score, score_reason = _credibility_detail(source, False, "个股新闻")
                    e = {
                        "event_type": "个股新闻",
                        "time": str(r.get("datetime") or "").strip() or "--",
                        "title": title or "--",
                        "source": source,
                        "url": None,
                        "impact_level": _level_from_title(title),
                        "credibility_score": score,
                        "credibility_reason": score_reason,
                        "evidence": "公司名/代码命中新闻标题或正文",
                    }
                    events.append(e)
                    count += 1
                    if count >= 6:
                        break
        except Exception:
            pass

    except Exception:
        pass

    # 去重+归并后按时间倒序
    dedup_events, dedup_stats, topic_groups = _dedup_and_group_events(events)
    events = sorted(dedup_events, key=lambda x: str(x.get("time") or ""), reverse=True)[:18]

    credibility_rules = [
        {"rule": "公司公告（交易所/巨潮）", "score_range": "90-95", "description": "官方披露，最高优先级"},
        {"rule": "官方媒体（新华社/央视等）", "score_range": "82-88", "description": "权威媒体，可信度较高"},
        {"rule": "主流财经媒体", "score_range": "72-78", "description": "可用但建议交叉验证"},
        {"rule": "普通聚合来源", "score_range": "62-68", "description": "仅作线索，需二次确认"},
    ]

    facts = {
        "events": events,
        "summary": {
            "total": len(events),
            "high_impact": len([e for e in events if e.get("impact_level") == "高"]),
            "avg_credibility": round(sum(int(e.get("credibility_score") or 0) for e in events) / len(events), 1) if events else None,
        },
        "dedup_stats": dedup_stats,
        "topic_groups": topic_groups[:6],
        "credibility_rules": credibility_rules,
        "latest_announcement_title": latest_ann_title,
        "latest_policy_title": latest_policy_title,
    }
    _EVENT_CACHE[cache_key] = (now, facts)
    return facts


def build_stock_payload(code: str) -> dict:
    code = _fmt_code(code)
    sec = ("sh" + code) if code.startswith(("6", "9")) else ("sz" + code)

    rt_map = tx_realtime_full([sec])
    rt = rt_map.get(code, {})
    daily = tx_daily(code, count=120)
    if not daily:
        raise ValueError("无法获取K线数据")

    closes = [d["close"] for d in daily]
    highs = [d["high"] for d in daily]
    lows = [d["low"] for d in daily]
    dates = [d["date"] for d in daily]

    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)

    price = float(rt.get("price", closes[-1]))
    stock_name = rt.get("name", code)
    latest_close = closes[-1]
    rsi14 = calc_rsi(closes, 14) if len(closes) >= 15 else None

    flow_map = get_capital_flow([code])
    flow = flow_map.get(code, {})
    main_in_yi = float(flow.get("main_in_yi") or 0)
    ddx5 = float(flow.get("ddx5") or 0)

    fact_flow = _recent_fact_events(code, stock_name)
    fact_events = fact_flow.get("events", [])
    latest_ann_title = fact_flow.get("latest_announcement_title")
    latest_policy_title = fact_flow.get("latest_policy_title")

    fin = get_financial([code]).get(code, {})
    ann = fin.get("annual", {}) if fin else {}
    qtr = fin.get("quarter", {}) if fin else {}
    latest_fi = fin.get("latest_fi", {}) if fin else {}

    index_codes = ["sh000001", "sz399001", "sz399006", "sh000300"]
    idx_raw = tx_realtime_full(index_codes)
    indices = {
        "上证指数": idx_raw.get("000001", {}),
        "深证成指": idx_raw.get("399001", {}),
        "创业板指": idx_raw.get("399006", {}),
        "沪深300": idx_raw.get("000300", {}),
    }

    # ===== 多角度解读 =====
    idx_avg = 0.0
    idx_count = 0
    for v in indices.values():
        if v and v.get("pct") is not None:
            idx_avg += float(v.get("pct") or 0)
            idx_count += 1
    idx_avg = idx_avg / idx_count if idx_count else 0.0
    relative_strength = round(float(rt.get("pct", 0) or 0) - idx_avg, 2)

    rsi_state = "中性"
    if rsi14 is not None:
        if rsi14 >= 80:
            rsi_state = "极度超买"
        elif rsi14 >= 70:
            rsi_state = "超买"
        elif rsi14 <= 30:
            rsi_state = "超卖"

    rev_yoy = ann.get("rev_yoy")
    ni_yoy = ann.get("ni_yoy")
    roe = latest_fi.get("roe")
    debt = latest_fi.get("debt")

    chg5 = _safe_pct(latest_close, closes[-6]) if len(closes) >= 6 else None
    chg20 = _safe_pct(latest_close, closes[-21]) if len(closes) >= 21 else None

    policy_view = {
        "summary": "地产政策处在边际修复阶段，交易层通常先反映预期，基本面兑现滞后。",
        "data_source": "系统内置政策观察模板（非实时政策数据库）",
        "facts": [
            f"近30天事实事件数 {len(fact_events)} 条（含公告/政策/个股新闻）。",
            f"最近政策类标题：{latest_policy_title or '--'}。",
            f"当日相对强弱（个股-主要指数均值）为 {relative_strength:+.2f}% 。",
            f"当日主力净流入 {main_in_yi:+.2f} 亿，DDX5 为 {ddx5:+.3f}。",
        ],
        "points": [
            "若政策端继续释放稳地产信号，板块估值与情绪存在修复弹性。",
            "当前更偏结构性行情，个股表现分化，资金会集中于交易辨识度高的标的。",
            "一旦政策预期低于市场预期，高位品种容易出现快速回撤。",
        ],
    }

    industry_view = {
        "summary": "行业层面属于修复但非全面反转阶段，交易机会大于趋势机会。",
        "data_source": "tx_realtime_full 指数与个股实时数据",
        "facts": [
            f"上证指数涨跌幅 {_fmt_num(float(indices.get('上证指数', {}).get('pct') or 0), 2, '%')}。",
            f"深证成指涨跌幅 {_fmt_num(float(indices.get('深证成指', {}).get('pct') or 0), 2, '%')}。",
            f"沪深300涨跌幅 {_fmt_num(float(indices.get('沪深300', {}).get('pct') or 0), 2, '%')}。",
            f"标的当日涨跌幅 {_fmt_num(float(rt.get('pct', 0) or 0), 2, '%')}，相对强度 {relative_strength:+.2f}%。",
        ],
        "points": [
            "地产链条内部轮动快，持续性依赖成交与政策共振。",
            f"当前标的相对大盘强度为 {relative_strength:+.2f}% ，属于短线强势股特征。",
            "若板块转弱而个股独强，后续波动通常更大。",
        ],
    }

    fundamental_view = {
        "summary": "营收有增长，但利润与ROE压力仍在，基本面修复质量需持续跟踪。",
        "data_source": "tushare_data.get_financial 年报/季报/财务结构",
        "facts": [
            f"年报营收同比 {_fmt_num(rev_yoy, 2, '%')}。",
            f"年报净利同比 {_fmt_num(ni_yoy, 2, '%')}。",
            f"最新ROE {_fmt_num(roe, 2, '%')}，资产负债率 {_fmt_num(debt, 2, '%')}。",
        ],
        "points": [
            f"年报营收同比 {rev_yoy if rev_yoy is not None else '--'}%，净利同比 {ni_yoy if ni_yoy is not None else '--'}%。",
            f"最新ROE {roe if roe is not None else '--'}%，资产负债率 {debt if debt is not None else '--'}%。",
            "当前交易逻辑更偏情绪与资金驱动，基本面尚不足以单独支撑高估值扩张。",
        ],
    }

    technical_view = {
        "summary": "技术面处于高动量阶段，短线趋势强但过热风险上升。",
        "data_source": "tx_daily K线 + calc_rsi",
        "facts": [
            f"最新价 {_fmt_num(price, 2)}，RSI14 {_fmt_num(rsi14, 1)}（{rsi_state}）。",
            f"近5日涨幅 {_fmt_num(chg5, 2, '%')}，近20日涨幅 {_fmt_num(chg20, 2, '%')}。",
            f"MA5 {_fmt_num(ma5[-1] if ma5 else None, 2)}，MA20 {_fmt_num(ma20[-1] if ma20 else None, 2)}。",
            f"第一压力 {_fmt_num(round(max(highs[-5:]), 2) if len(highs) >= 5 else None, 2)}，第一支撑 {_fmt_num(round(min(lows[-5:]), 2) if len(lows) >= 5 else None, 2)}。",
        ],
        "points": [
            f"RSI14={rsi14 if rsi14 is not None else '--'}（{rsi_state}）。",
            f"近5日涨幅 {chg5 if chg5 is not None else '--'}%，近20日涨幅 {chg20 if chg20 is not None else '--'}%。",
            "关键观察：是否出现放量滞涨、长上影、跌破短期支撑等信号。",
        ],
    }

    sentiment_view = {
        "summary": "舆情热度高时，交易行为更容易情绪化，分歧放大也更快。",
        "data_source": "capital_flow + hot_core_info（无外部新闻正文抓取）",
        "facts": [
            f"主力净流入 {main_in_yi:+.2f} 亿，DDX5 {ddx5:+.3f}。",
            f"短期涨幅：5日 {_fmt_num(chg5, 2, '%')}，20日 {_fmt_num(chg20, 2, '%')}。",
            f"最新公告标题：{latest_ann_title or '--'}。",
        ],
        "points": [
            "热点标签通常集中在连板、龙虎榜、异动公告、龙头属性。",
            "高关注度有利于短线成交活跃，但一致性过强时也可能触发反向波动。",
            "盘中需结合换手与资金结构判断是增量接力还是高位换手。",
        ],
    }

    scenario_view = {
        "summary": "建议用情景化管理仓位，而非单一方向押注。",
        "data_source": "技术位 + 资金流（规则推导）",
        "facts": [
            f"第一压力位 {_fmt_num(round(max(highs[-5:]), 2) if len(highs) >= 5 else None, 2)}。",
            f"第一支撑位 {_fmt_num(round(min(lows[-5:]), 2) if len(lows) >= 5 else None, 2)}。",
            f"主力净流入 {main_in_yi:+.2f} 亿，DDX5 {ddx5:+.3f}。",
        ],
        "bull": "强势延续：放量突破关键压力且主力资金回流，可小步跟随。",
        "base": "震荡分歧：高位宽幅波动，宜控制仓位并做节奏。",
        "bear": "转弱回落：跌破短支撑并伴随主力流出扩大，优先防守。",
    }

    scenario_name = "中性情景"
    scenario_color = "amber"
    scenario_score = 0
    scenario_reasons: list[str] = []
    pressure_1 = round(max(highs[-5:]), 2) if len(highs) >= 5 else None
    support_1 = round(min(lows[-5:]), 2) if len(lows) >= 5 else None

    if relative_strength >= 0:
        scenario_score += 1
        scenario_reasons.append(f"相对大盘强度 {relative_strength:+.2f}% 为正。")
    else:
        scenario_score -= 1
        scenario_reasons.append(f"相对大盘强度 {relative_strength:+.2f}% 为负。")

    if main_in_yi > 0 and ddx5 > 0:
        scenario_score += 2
        scenario_reasons.append(f"主力净流入 {main_in_yi:+.2f} 亿且 DDX5 {ddx5:+.3f} 同向偏多。")
    elif main_in_yi < 0 and ddx5 < 0:
        scenario_score -= 2
        scenario_reasons.append(f"主力净流入 {main_in_yi:+.2f} 亿且 DDX5 {ddx5:+.3f} 同向偏弱。")
    else:
        scenario_reasons.append("资金信号分歧，暂不支持单边判断。")

    if pressure_1 is not None and price >= pressure_1:
        scenario_score += 1
        scenario_reasons.append(f"价格 {price:.2f} 已触及/站上第一压力位 {pressure_1:.2f}。")
    elif support_1 is not None and price < support_1:
        scenario_score -= 2
        scenario_reasons.append(f"价格 {price:.2f} 已跌破第一支撑位 {support_1:.2f}。")
    elif support_1 is not None and pressure_1 is not None:
        scenario_reasons.append(f"价格仍运行在支撑 {support_1:.2f} 与压力 {pressure_1:.2f} 之间。")

    if rsi14 is not None and rsi14 >= 80:
        scenario_score -= 1
        scenario_reasons.append(f"RSI14 {_fmt_num(rsi14, 1)} 偏高，存在过热约束。")

    if scenario_score >= 2:
        scenario_name = "偏强情景"
        scenario_color = "red"
    elif scenario_score <= -2:
        scenario_name = "偏弱情景"
        scenario_color = "green"

    scenario_view["current_state"] = {
        "name": scenario_name,
        "color": scenario_color,
        "score": scenario_score,
        "reasons": scenario_reasons,
        "next_action": scenario_view["bull"] if scenario_name == "偏强情景" else (scenario_view["bear"] if scenario_name == "偏弱情景" else scenario_view["base"]),
    }

    topic_groups = fact_flow.get("topic_groups") or []
    top_topic = topic_groups[0].get("topic") if topic_groups else "暂无主线题材"
    top_topic_count = topic_groups[0].get("count") if topic_groups else 0
    high_impact_cnt = int((fact_flow.get("summary") or {}).get("high_impact") or 0)

    flow_state = "中性"
    if main_in_yi > 0 and ddx5 > 0:
        flow_state = "偏强"
    elif main_in_yi < 0 and ddx5 < 0:
        flow_state = "偏弱"

    risk_level = "中"
    if (rsi14 is not None and rsi14 >= 80) or (chg5 is not None and chg5 >= 15):
        risk_level = "高"
    elif (rsi14 is not None and rsi14 <= 35) and (main_in_yi >= 0):
        risk_level = "低"

    action_bias = "观察为主"
    if flow_state == "偏强" and risk_level != "高" and relative_strength >= 0:
        action_bias = "偏多跟随"
    elif flow_state == "偏弱" or relative_strength < -1.5:
        action_bias = "偏防守"

    short_term_core_info = {
        "theme": {
            "main_topic": top_topic,
            "topic_heat": "高" if top_topic_count >= 3 or high_impact_cnt >= 2 else ("中" if top_topic_count >= 1 else "低"),
            "event_count_30d": int((fact_flow.get("summary") or {}).get("total") or 0),
            "high_impact_count": high_impact_cnt,
        },
        "money_flow": {
            "state": flow_state,
            "main_in_yi": round(main_in_yi, 2),
            "ddx5": round(ddx5, 3),
            "ddx10": float(flow.get("ddx10") or 0),
        },
        "trend": {
            "relative_strength_pct": relative_strength,
            "rsi14": rsi14,
            "chg5_pct": chg5,
            "chg20_pct": chg20,
            "support_1": round(min(lows[-5:]), 2) if len(lows) >= 5 else None,
            "pressure_1": round(max(highs[-5:]), 2) if len(highs) >= 5 else None,
        },
        "risk_level": risk_level,
        "action_bias": action_bias,
        "current_scenario": scenario_view["current_state"],
        "core_points": [
            f"短期主线题材：{top_topic}（近30天事件 {int((fact_flow.get('summary') or {}).get('total') or 0)} 条，高影响 {high_impact_cnt} 条）。",
            f"资金态度：{flow_state}（主力净流入 {main_in_yi:+.2f} 亿，DDX5 {ddx5:+.3f}）。",
            f"强弱对比：相对指数强度 {relative_strength:+.2f}%，RSI14 {_fmt_num(rsi14, 1)}。",
        ],
        "watch_next_1_3d": [
            "是否放量突破第一压力位并站稳。",
            "主力净流入与DDX是否继续同向。",
            "高影响事件是否持续新增，题材热度是否扩散。",
        ],
    }

    payload = {
        "ok": True,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stock": {
            "code": code,
            "name": rt.get("name", code),
            "price": round(price, 2),
            "pct": round(float(rt.get("pct", 0) or 0), 2),
            "high": round(float(rt.get("high", 0) or 0), 2),
            "low": round(float(rt.get("low", 0) or 0), 2),
            "pe": round(float(rt.get("pe", 0) or 0), 2),
            "pb": round(float(rt.get("pb", 0) or 0), 2),
            "mktcap_yi": round(float(rt.get("mktcap_yi", 0) or 0), 2),
            "rsi14": rsi14,
            "chg5": chg5,
            "chg20": chg20,
            "support_1_low": round(min(lows[-5:]), 2) if len(lows) >= 5 else None,
            "support_1_high": round(min(lows[-3:]), 2) if len(lows) >= 3 else None,
            "pressure_1": round(max(highs[-5:]), 2) if len(highs) >= 5 else None,
        },
        "chart": {
            "dates": dates,
            "closes": closes,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
        },
        "financial": fin,
        "capital_flow": {
            "ddx5": ddx5,
            "ddx10": flow.get("ddx10"),
            "main_in_yi": main_in_yi,
            "main_10d_yi": flow.get("main_10d_yi"),
            "margin_yi": flow.get("margin_yi"),
        },
        "indices": indices,
        "policy_notes": [
            "地产行业近期以结构性修复为主，个股弹性大于行业贝塔。",
            "出现股价异动公告或龙虎榜后，短线情绪容易放大。",
            "若政策预期低于交易预期，高位标的回撤通常更快。",
        ],
        "hot_core_info": {
            "event_drivers": [
                "股价异动公告与龙虎榜披露通常会提升个股关注度。",
                "若个股在指数回调时逆势走强，往往会吸引短线资金抱团。",
                "换手率显著提升时，市场对题材与交易逻辑分歧会同步放大。",
            ],
            "capital_interpretation": (
                "主力净流入为正，短线资金更偏进攻" if main_in_yi > 0 else "主力净流入偏负，短线更多是高位换手与博弈"
            ),
            "risk_flags": [
                "高波动阶段，情绪驱动强于基本面驱动时，回撤通常更快。",
                "若放量滞涨或跌破短期支撑，需警惕抱团松动。",
            ],
        },
        "short_term_core_info": short_term_core_info,
        "fact_event_timeline": fact_flow,
        "multi_angle_interpretation": {
            "policy": policy_view,
            "industry": industry_view,
            "fundamental": fundamental_view,
            "technical": technical_view,
            "sentiment": sentiment_view,
            "scenario": scenario_view,
        },
    }
    return payload


def _authorize_request(
    x_api_key: str | None = Header(default=None),
    key: str | None = Query(default=None),
) -> None:
    if not API_KEY:
        return
    header_key = (x_api_key or "").strip()
    query_key = (key or "").strip()
    if header_key == API_KEY or query_key == API_KEY:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "local_stock_api", "host": API_HOST, "port": API_PORT}


@app.get("/api/stock")
def stock(
    code: str | None = Query(default=None),
    query: str | None = Query(default=None),
    _: None = Depends(_authorize_request),
) -> dict:
    resolved_code = None
    if code is not None:
        resolved_code = resolve_code(code)
    elif query is not None:
        resolved_code = resolve_code(query)

    if not resolved_code:
        raise HTTPException(status_code=400, detail="请传 code=6位股票代码 或 query=股票名称")

    try:
        return build_stock_payload(resolved_code)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def main():
    print(f"Mimi Stock API running at http://{API_HOST}:{API_PORT}")
    print("Try: /api/health or /api/stock?code=002208")
    if API_KEY:
        print("API key auth enabled. Send X-API-Key header or ?key=...")
    print(f"CORS allow origin: {ALLOWED_ORIGIN}")
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
