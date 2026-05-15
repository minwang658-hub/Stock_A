"""
portfolio_daily.py — 持仓快照 & 交易重放

设计原则（你只需要维护 portfolio.csv 和 trade_log.csv）：

┌──────────────────────────────────────────────────────────────┐
│  portfolio.csv        你的初始建仓成本（你维护）                │
│  trade_log.csv       你的交易记录（你录入）                  │
│                     系统自动填写"已实现盈亏"列                │
├──────────────────────────────────────────────────────────────┤
│  daily_portfolio.json 系统生成的每日快照（自动追加）           │
└──────────────────────────────────────────────────────────────┘

你只需要做两件事：
  1. portfolio.csv → 每次买入/卖出后手动更新持仓数量和成本价
  2. trade_log.csv → 每次交易后追加一行（"已实现盈亏"留空，系统填写）

已实现收益计算逻辑：
  卖出时 → (卖出价 - portfolio.csv 中的成本价) × 数量
  系统自动填入 trade_log.csv 的"已实现盈亏"列，下次不再重复计算
"""

import csv as _csv
import json as _json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent  # = mimi_stock/
DATA_DIR = BASE_DIR / "data"
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"
TRADE_LOG_FILE  = DATA_DIR / "trade_log.csv"
SNAPSHOT_FILE  = DATA_DIR / "daily_portfolio.json"
MARKER_FILE    = DATA_DIR / ".last_trade_date"  # 记录最后处理到哪一笔交易


# ═══════════════════════════════════════════════════════════════
# 读取文件
# ═══════════════════════════════════════════════════════════════

def load_portfolio():
    """读取 portfolio.csv，返回 [{code, cost, qty}]"""
    holdings = []
    if not PORTFOLIO_FILE.exists():
        return holdings
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    holdings.append({"code": parts[0], "cost": float(parts[1]), "qty": int(parts[2])})
                except:
                    pass
    return holdings


def load_trades():
    """
    读取 trade_log.csv，返回 [{date, action, code, name, price, qty, note}]
    使用纯文本逐行解析，兼容 BOM、空格等所有格式问题
    """
    import csv as __csv
    trades = []
    if not TRADE_LOG_FILE.exists():
        return trades

    # 先读取全部文本
    with open(TRADE_LOG_FILE, encoding="utf-8-sig") as f:
        text = f.read()

    if not text.strip():
        return trades

    # 用 csv.reader 解析（更简单）
    reader = __csv.reader(text.splitlines())
    header = next(reader)
    # 标准化表头字段名
    # 格式：日期,操作,代码,名称,成交价,数量(股),已实现盈亏(元),备注
    # 列索引：    0     1     2     3     4       5          6           7
    col_idx = {}
    for i, h in enumerate(header):
        h_clean = h.strip().lstrip(chr(0xFEFF)).strip()
        col_idx[h_clean] = i

    for row in reader:
        if len(row) < 3:
            continue
        # 通过列索引安全获取
        def getcol(row, *keys):
            for k in keys:
                if k in col_idx and col_idx[k] < len(row):
                    v = row[col_idx[k]].strip()
                    if v:
                        return v
            return ""
        
        date   = getcol(row, "日期")
        action = getcol(row, "操作")
        code   = getcol(row, "代码")
        name   = getcol(row, "名称")
        price  = getcol(row, "成交价")
        qty    = getcol(row, "数量(股)")
        pnl_str = getcol(row, "已实现盈亏(元)")
        note   = getcol(row, "备注")
        
        if not date or not action or not code:
            continue
        try:
            pnl = float(pnl_str) if pnl_str and pnl_str not in ('', '-') else None
        except:
            pnl = None
        try:
            trades.append({
                "date": date, "action": action, "code": code, "name": name,
                "price": float(price) if price else 0,
                "qty": int(qty) if qty else 0,
                "note": note,
                "pnl": pnl,
            })
        except:
            pass
    return sorted(trades, key=lambda x: x["date"])


# ═══════════════════════════════════════════════════════════════
# 核心：重放交易 → 计算已实现收益
# ═══════════════════════════════════════════════════════════════

def replay_trades(portfolio_holdings, trades):
    """
    从 portfolio_holdings（初始成本）出发，按时间顺序重放全部 trades，
    返回 (current_holdings, total_realized_pnl, processed_trades)

    - 卖出/止损/清仓/止盈：计算已实现收益 (卖出价 - 成本) × 数量
    - 买入：更新成本价（加权平均）
    """
    holdings = {h["code"]: {"cost": h["cost"], "qty": h["qty"]} for h in portfolio_holdings}
    total_realized = 0.0

    for t in trades:
        code, action, price, qty = t["code"], t["action"], t["price"], t["qty"]

        if action in ("卖出", "止损", "清仓", "止盈"):
            if code not in holdings or holdings[code]["qty"] <= 0:
                t["pnl"] = 0.0
                continue
            h = holdings[code]
            sell_qty = min(qty, h["qty"])
            pnl = (price - h["cost"]) * sell_qty
            h["qty"] -= sell_qty
            total_realized += pnl
            t["pnl"] = round(pnl, 2)

        elif action == "买入":
            if code in holdings:
                h = holdings[code]
                total_cost = h["cost"] * h["qty"] + price * qty
                total_qty  = h["qty"] + qty
                holdings[code] = {"cost": total_cost / total_qty, "qty": total_qty}
            else:
                holdings[code] = {"cost": price, "qty": qty}
            t["pnl"] = 0.0

        elif action == "分红":
            total_realized += qty  # qty 在这里是分红金额
            t["pnl"] = qty

    current = [{"code": c, "cost": h["cost"], "qty": h["qty"]}
               for c, h in holdings.items() if h["qty"] > 0]

    return current, round(total_realized, 2), trades


# ═══════════════════════════════════════════════════════════════
# 写回 trade_log.csv（自动填入"已实现盈亏"列）
# ═══════════════════════════════════════════════════════════════

def write_back_pnl(trades_with_pnl):
    """
    把每笔交易的已实现收益写回 trade_log.csv 的"已实现盈亏(元)"列。
    文件只写一次，不重复追加。
    """
    if not trades_with_pnl:
        return

    # 建立 (日期, 代码) → pnl 的映射
    pnl_map = {(t["date"], t["code"]): t["pnl"] for t in trades_with_pnl}

    # 一次性读取全部内容
    with open(TRADE_LOG_FILE, encoding="utf-8-sig") as f:
        raw = f.read()

    if not raw.strip():
        return

    lines = raw.splitlines()
    raw_header = lines[0].lstrip("\ufeff")  # 去除 BOM 残留
    # 建立 干净名→原始名 的映射
    raw_fields = [h.strip() for h in raw_header.split(",")]
    FIELDNAMES = [h.strip().lstrip("\ufeff") for h in raw_fields]

    output = [raw_header]
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        # 解析这一行
        parts = [p.strip() for p in line.split(",")]
        row = dict(zip(FIELDNAMES, parts + [""] * (len(FIELDNAMES) - len(parts))))
        key = (row.get("日期", ""), row.get("代码", ""))
        if key in pnl_map and not row.get("已实现盈亏(元)"):
            row["已实现盈亏(元)"] = str(pnl_map[key])
        output.append(",".join(row.get(f, "") for f in FIELDNAMES))

    with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output) + "\n")


# ═══════════════════════════════════════════════════════════════
# 每日快照
# ═══════════════════════════════════════════════════════════════

def _recompute_cumulative(trades, current_holdings):
    """
    从零重新计算累计已确认收益，不依赖快照链。
    逻辑：
    1. 当前持仓里有成本 → 用当前持仓成本
    2. 已卖完的股票 → 从快照历史里找历史成本
    3. 仍找不到 → 用 trade_log 里的预填 pnl
    """
    # 用当前持仓构建成本映射
    cost_map = {h["code"]: h["cost"] for h in current_holdings}
    # 从快照历史恢复已卖完股票的历史成本
    closed_costs = {}
    if SNAPSHOT_FILE.exists():
        try:
            for snap in _json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8")):
                for s in snap.get("stocks", []):
                    code, qty, cost = s["code"], s["qty"], s["cost"]
                    if qty > 0 and code not in cost_map and code not in closed_costs:
                        closed_costs[code] = cost
        except:
            pass
    # 对每笔卖出交易重新算 pnl
    total = 0.0
    for t in trades:
        if t.get("action") in ("卖出", "止损", "清仓", "止盈"):
            code, price, qty = t["code"], t["price"], t["qty"]
            if t.get("pnl") not in (None, 0, ""):
                total += t["pnl"]
            elif code in cost_map:
                total += (price - cost_map[code]) * qty
            elif code in closed_costs:
                total += (price - closed_costs[code]) * qty
    return round(total, 2)


def take_snapshot(holdings, day_realized, market_values, date_str):
    """
    追加当日持仓快照到 daily_portfolio.json。
    holdings: 重放后的当前持仓（含成本）
    day_realized: 预留参数（现由调用方传0，累计已由 run_daily_snapshot 算好）
    market_values: {code: 今日市值}
    """
    # 累计已确认收益：直接用传入值（run_daily_snapshot 已从 trade_log 正确算出）
    # 不再从快照链累加，避免误差传播
    cumulative = day_realized

    total_cost = sum(h["cost"] * h["qty"] for h in holdings)
    total_mkt  = sum(market_values.get(h["code"], h["cost"]) * h["qty"] for h in holdings)
    floating   = total_mkt - total_cost
    total_pnl  = floating + cumulative

    snap = {
        "date": date_str,
        "stocks": [
            {
                "code": h["code"],
                "qty": h["qty"],
                "cost": h["cost"],
                "cost_total": round(h["cost"] * h["qty"], 2),
                "market_value": round(market_values.get(h["code"], h["cost"]) * h["qty"], 2),
                "floating_pnl": round(market_values.get(h["code"], h["cost"]) * h["qty"] - h["cost"] * h["qty"], 2),
            }
            for h in holdings
        ],
        "total_cost": round(total_cost, 2),
        "total_market_value": round(total_mkt, 2),
        "floating_pnl": round(floating, 2),
        "day_realized": round(day_realized, 2),
        "cumulative_realized": round(cumulative, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
    }

    snaps = []
    if SNAPSHOT_FILE.exists():
        try:
            snaps = _json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except:
            snaps = []
    snaps.append(snap)
    SNAPSHOT_FILE.write_text(_json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8")

    return snap


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def _write_portfolio(current_holdings):
    """
    把重放后的当前持仓写回 portfolio.csv。
    保留原文件的注释头部，只更新数据行。
    """
    if not PORTFOLIO_FILE.exists():
        # 文件不存在，直接创建
        lines = ["# 持仓成本数据（格式：代码,成本价,持仓数量）",
                 "# ——由用户手动维护，每次买入/卖出后更新——"]
        for h in sorted(current_holdings, key=lambda x: x["code"]):
            lines.append(f"{h['code']}, {h['cost']:.3f}, {h['qty']}")
        PORTFOLIO_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"    📝 portfolio.csv 已创建（{len(current_holdings)}只持仓）")
        return

    # 保留原文件注释头部
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        orig_lines = f.readlines()

    data_lines = []
    for line in orig_lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            data_lines.append(stripped)
        elif not stripped or stripped.startswith("代码,"):
            continue  # 跳过空行和旧表头
        else:
            data_lines.append(stripped)

    # 用重放后的持仓覆盖（按 code 匹配）
    cost_qty_map = {h["code"]: (h["cost"], h["qty"]) for h in current_holdings}
    kept = 0
    new_lines = []
    for line in data_lines:
        if line.startswith("#"):
            new_lines.append(line)
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 1 and parts[0] in cost_qty_map:
            cost, qty = cost_qty_map.pop(parts[0])
            if qty > 0:  # 只保留仍有持仓的股票
                new_lines.append(f"{parts[0]}, {cost:.3f}, {qty}")
                kept += 1
        # else: 原文件中已无持仓的股票 → 跳过，不写入

    # 新增的股票（在 portfolio.csv 中原来没有的）
    for code, (cost, qty) in cost_qty_map.items():
        if qty > 0:
            new_lines.append(f"{code}, {cost:.3f}, {qty}")

    PORTFOLIO_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"    📝 portfolio.csv 已同步（{kept + len(cost_qty_map)}只持仓）")


def run_daily_snapshot(market_values, date_str=None):
    """
    由 comprehensive_report.py 调用。
    流程：读取文件 → 幂等检查 → 重放交易 → 写回trade_log → 拍照快照

    market_values: {code: 当日市值}
    date_str: "YYYY-MM-DD"
    """
    today = date_str or datetime.now().strftime("%Y-%m-%d")
    print("  📸 持仓快照...")

    # 1. 读取用户维护的初始持仓
    portfolio = load_portfolio()
    if not portfolio:
        print("    ⚠️ portfolio.csv 为空，跳过")
        return None

    # 2. 读取交易记录
    trades = load_trades()
    if not trades:
        print("    📋 无交易记录，直接拍照")
        prev_cumulative = 0.0
        if SNAPSHOT_FILE.exists():
            try:
                snaps = _json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
                for snap in reversed(snaps):
                    cr = snap.get("cumulative_realized", 0.0)
                    if cr and cr != 0.0:
                        prev_cumulative = cr
                        break
            except:
                pass
        snap = take_snapshot(portfolio, prev_cumulative, market_values, today)
        print_summary(snap)
        return snap

    # 3. 幂等检查：只处理 last_trade_date 之后的新交易
    last_synced = None
    if MARKER_FILE.exists():
        last_synced = MARKER_FILE.read_text().strip() or None

    new_trades = [t for t in trades if last_synced is None or t["date"] > last_synced]

    # ===== 重要修复：无论是否有新交易，都需要重放获取当前真实持仓 =====
    # 原因：portfolio.csv 可能已手动更新（如3月31日买入100股后），
    #      需要重放 trade_log 计算当前真实持仓，再拍照
    
    if not new_trades:
        print(f"    📋 无新增交易（last={last_synced}），但仍执行重放获取最新持仓")

    # 4. 先用原始 trade_log 数据算累计已确认收益（replay 会改 pnl 值）
    cumulative_realized = 0.0
    for t in trades:
        if t.get("action") in ("卖出", "止损", "清仓", "止盈", "分红"):
            pre = t.get("pnl")
            if pre is not None and pre != 0:
                cumulative_realized += pre
    cumulative_realized = round(cumulative_realized, 2)

    # 5. 重放全部历史交易（用 portfolio.csv 作为初始成本基准）
    current_holdings, total_realized, processed = replay_trades(portfolio, trades)

    # 5. 把已实现收益写回 trade_log.csv
    write_back_pnl(processed)

    # 6. 更新 marker（防止下次重复处理）
    # 注意：只要执行了重放就更新 marker，避免重复计算
    last_date = max(t["date"] for t in trades) if trades else (last_synced or today)
    MARKER_FILE.write_text(last_date, encoding="utf-8")
    print(f"    ✅ 已实现收益 ¥{total_realized:+.2f} 已写入 trade_log.csv（last={last_date}）")

    # 7. 【重要】不再自动写回 portfolio.csv
    # portfolio.csv 应保持为初始建仓，不随交易更新
    # 只有用户手动维护初始建仓成本

    # 8. 拍照快照（累计已确认收益已正确算出）
    snap = take_snapshot(current_holdings, cumulative_realized, market_values, today)
    print_summary(snap)
    return snap


def print_summary(snap):
    fp  = snap["floating_pnl"]
    cr  = snap["cumulative_realized"]
    tp  = snap["total_pnl"]
    pct = snap["total_pnl_pct"]
    sign = lambda v: "+" if v >= 0 else ""
    print(f"    💰 浮动: {sign(fp)}{fp:,.0f} | 已确认: {sign(cr)}{cr:,.0f} | 总收益: {sign(tp)}{tp:,.0f} ({pct:+.1f}%)")
