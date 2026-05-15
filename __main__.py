#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
支持直接运行: python -m mimi_stock 或 python __main__.py
"""

import sys
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from cli import main

if __name__ == "__main__":
    main()