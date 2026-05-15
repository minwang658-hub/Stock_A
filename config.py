#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# 数据目录
DATA_DIR = BASE_DIR / "data"

# 报告输出目录（支持环境变量覆盖）
REPORT_DIR = Path(os.environ.get("MIMI_REPORT_DIR", BASE_DIR / "reports"))

# 持仓数据
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"
TRADE_LOG_FILE = DATA_DIR / "trade_log.csv"
SNAPSHOT_FILE = DATA_DIR / "daily_portfolio.json"

# Tushare 配置
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "pRdHdexpjHTcBXXdnzaUSfqpXtRvryjjJXpAlwYpEHtzktTksDeYnybzFCeXumwI")
TUSHARE_API_URL = os.environ.get("TUSHARE_API_URL", "http://121.40.135.59:8010/")

# 确保目录存在
def init_dirs():
    """初始化必要的目录"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 自选股列表
DEFAULT_WATCHLIST = {
    '600519': '贵州茅台',
    '300750': '宁德时代',
    '002594': '比亚迪',
    '600036': '招商银行',
    '603005': '晶方科技',
    '600115': '中国东航',
    '600660': '福耀玻璃',
    '000630': '铜陵有色',
    '002415': '海康威视',
    '000651': '格力电器',
    '603019': '中科曙光',
    '000001': '平安银行',
    '601318': '中国平安',
    '000858': '五粮液'
}