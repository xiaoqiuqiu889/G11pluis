#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re

DQ = '"'
files = [
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/anchors.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/1985_meeting.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/1989_farewell.yaml',
    'D:/G1-ai-native/content/case_02_moscow_no_fairy_tale/scenes/2008_reunion.yaml',
]
for f in files:
    with open(f, 'r', encoding='utf-8') as fp:
        lines = fp.readlines()
    for i, line in enumerate(lines, 1):
        n = line.count(DQ)
        if n >= 4:
            print(f'{f}:{i}  ({n} dquotes): {line.rstrip()[:120]}')
