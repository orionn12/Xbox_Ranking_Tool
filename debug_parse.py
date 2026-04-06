import re
with open('debug_minecraft.html', 'r', encoding='utf-8') as f:
    text = f.read()
    
    # ギャラリー関連
    print("=== Media ===")
    matches = re.findall(r'class="([^"]*Media[^"]*)"', text)
    for m in list(set(matches))[:10]:
        print(m)
        
    print("\n=== Description ===")
    matches = re.findall(r'class="([^"]*(?:[Dd]escription|[Pp]roduct)[^"]*)"', text)
    for m in list(set(matches))[:10]:
        print(m)
