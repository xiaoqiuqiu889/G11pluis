import re
path = 'D:/G1-ai-native/server/analytics_warehouse.py'
src = open(path, 'r', encoding='utf-8').read()
# Replace the int(window.total_seconds() // 60)m pattern
count_before = src.count('int(window.total_seconds() // 60)}m')
new = re.sub(r'window=f"\{int\(window\.total_seconds\(\) // 60\)\}m"', 'window=_humanize_window(window)', src)
count_after = new.count('int(window.total_seconds() // 60)}m')
open(path, 'w', encoding='utf-8').write(new)
print(f'replaced {count_before - count_after} occurrences; {count_after} remaining')
