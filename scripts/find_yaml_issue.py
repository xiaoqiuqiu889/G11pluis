#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐行调试 YAML 解析"""
import yaml
import sys

f = 'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/anchors.yaml'
with open(f, 'r', encoding='utf-8') as fp:
    content = fp.read()

# 切到 line 347 之前
lines = content.split(chr(10))
sub_content = chr(10).join(lines[:346])  # 包含前 346 行
try:
    data = yaml.safe_load(sub_content)
    print(f'Lines 1-346 OK')
except yaml.YAMLError as e:
    print(f'Lines 1-346 FAIL: {e.problem_mark.line+1} col {e.problem_mark.column+1}: {e.problem}')

# 切到 line 348 之前
sub_content2 = chr(10).join(lines[:347])
try:
    data = yaml.safe_load(sub_content2)
    print(f'Lines 1-347 OK')
except yaml.YAMLError as e:
    print(f'Lines 1-347 FAIL: {e.problem_mark.line+1} col {e.problem_mark.column+1}: {e.problem}')

# 切到 line 350 之前
sub_content3 = chr(10).join(lines[:350])
try:
    data = yaml.safe_load(sub_content3)
    print(f'Lines 1-350 OK')
except yaml.YAMLError as e:
    print(f'Lines 1-350 FAIL: {e.problem_mark.line+1} col {e.problem_mark.column+1}: {e.problem}')
