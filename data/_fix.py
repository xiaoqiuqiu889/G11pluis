import re
with open('D:/G1-ai-native/tests/operations/test_w10_smoke.py', encoding='utf-8') as f:
    src = f.read()
# Remove all (temp_db) param
src = re.sub(r'\(temp_db\)', '()', src)
# Also remove the temp_db fixture (8 lines approx)
lines = src.split('\n')
out = []
i = 0
while i < len(lines):
    if 'def temp_db' in lines[i]:
        # Skip until blank line
        i += 1
        while i < len(lines) and lines[i].strip():
            i += 1
        continue
    out.append(lines[i])
    i += 1
with open('D:/G1-ai-native/tests/operations/test_w10_smoke.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('rewrote')
