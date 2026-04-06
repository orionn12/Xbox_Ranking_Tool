import json
from pathlib import Path

def print_keys(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            print(f"{prefix}{k}")
            if isinstance(v, dict):
                print_keys(v, prefix + "  ")

def search_json(d, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            search_json(v, path + f"['{k}']")
    elif isinstance(d, list):
        for i, item in enumerate(d):
            search_json(item, path + f"[{i}]")
    else:
        v_str = str(d).lower()
        if "desc" in v_str or "play" in v_str or "anywhere" in v_str or "lang" in v_str or "japan" in v_str or "ja-jp" in v_str:
            # We don't print everything, it might be too much.
            if len(str(d)) < 100:
                print(f"Found: {path} = {d}")

with open('debug_api_9NBLGGH2JHXJ.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

p = data.get('Products', [{}])[0]
print("--- Product Keys ---")
print_keys(p)

print("\n--- Value Search ---")
search_json(p)
