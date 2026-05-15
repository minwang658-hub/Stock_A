#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行入口
"""

import sys
import argparse
from pathlib import Path

# 添加scripts目录到路径
SCRIPT_DIR = Path(__file__).parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

def main():
    parser = argparse.ArgumentParser(
        description="mimi_stock - A股智能选股与晨报生成工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # 基础晨报
    subparsers.add_parser("report", help="生成基础晨报")
    
    # 周线增强
    subparsers.add_parser("weekly", help="生成周线增强报告")
    
    # 持仓分析
    subparsers.add_parser("portfolio", help="持仓诊断分析")
    
    # 综合分析
    subparsers.add_parser("comprehensive", help="生成综合分析报告")
    
    # 一键生成全部
    subparsers.add_parser("all", help="生成全部报告")
    
    args = parser.parse_args()
    
    if args.command == "report":
        from generate_stock_report import main
        main()
    elif args.command == "weekly":
        from generate_weekly_enhanced import main
        main()
    elif args.command == "portfolio":
        from analyze_portfolio import main
        main()
    elif args.command == "comprehensive":
        from comprehensive_report import generate_comprehensive_report
        generate_comprehensive_report()
    elif args.command == "all":
        print("🚀 生成全部报告...")
        from generate_stock_report import main as report_main
        from generate_weekly_enhanced import main as weekly_main
        from analyze_portfolio import main as portfolio_main
        from comprehensive_report import generate_comprehensive_report as comprehensive_main
        
        report_main()
        weekly_main()
        portfolio_main()
        comprehensive_main()
        print("✅ 全部完成")
    else:
        parser.print_help()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())