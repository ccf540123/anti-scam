#!/usr/bin/env python3
"""第一階段完整流程入口：爬蟲 → 雙來源比對 → 只 append temp 進 Review。"""

from scripts.ptt_stage1_pipeline import main

if __name__ == "__main__":
    main()
