#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把所有 yaml 文件中的 `\"` 内嵌双引号问题转为单引号包裹"""
import re

files = [
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/anchors.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/characters/ilya_berman.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/characters/natasha_roschina.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/characters/sasha_kuzmin.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/characters/lisa_hoffmann.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/1985_meeting.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/1989_farewell.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/2008_reunion.yaml',
]

DQ = '"'
for f in files:
    with open(f, 'r', encoding='utf-8') as fp:
        content = fp.read()
    lines = content.split(chr(10))
    fixed = 0
    for i, line in enumerate(lines):
        # 检测 "key: \"...\"...\"...\"" 模式（同一行 ≥4 个双引号）
        if line.count(DQ) >= 4 and not line.lstrip().startswith('#'):
            # 简单策略：把这一行用 single-quote 包裹，找到 : 之后的 value 部分
            m = re.match(r'^(\s*[A-Za-z_][A-Za-z0-9_-]*\s*:\s*)(.+)$', line)
            if m:
                prefix = m.group(1)
                rest = m.group(2)
                # 如果 rest 已经被单引号包裹，跳过
                if rest.startswith("'") and rest.endswith("'"):
                    continue
                # 把 rest 中的 " 替换为 ' (或者直接单引号包裹)
                # 简单做法：用单引号包裹整个 rest
                # 但要先检查 rest 里没有单引号（如果有，需要更复杂的处理）
                if "'" not in rest:
                    lines[i] = prefix + "'" + rest + "'"
                    fixed += 1
    if fixed > 0:
        new_content = chr(10).join(lines)
        with open(f, 'w', encoding='utf-8') as fp:
            fp.write(new_content)
        print(f'Fixed {fixed} lines in {f.split(chr(92))[-1]}')
    else:
        print(f'No fixes needed in {f.split(chr(92))[-1]}')
