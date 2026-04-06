"""フォートナイトの説明文セクションのHTML構造を調査"""
import asyncio
from playwright.async_api import async_playwright

async def debug_desc():
    url = "https://www.xbox.com/ja-JP/games/store/a/BT5P2X999VH2"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP", viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=90000)
        print("Page loaded.")

        # モーダルをJS削除
        await page.evaluate("""
            () => {
                const portals = document.querySelectorAll('reach-portal');
                portals.forEach(p => p.remove());
                const overlays = document.querySelectorAll('[data-reach-dialog-overlay],[class*="modalOverlay"],[class*="AgeGating"]');
                overlays.forEach(o => o.remove());
            }
        """)
        await asyncio.sleep(0.5)

        # 「続きを表示」ボタンがあればクリック
        try:
            btn = page.locator('button:has-text("続きを表示"), button:has-text("詳細を表示"), button:has-text("さらに表示")').first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.5)
                print("Expanded description.")
        except: pass

        # ページのh2、h3タグを全部表示
        print("\n--- h2/h3 headings ---")
        for sel in ['h1', 'h2', 'h3']:
            els = page.locator(sel)
            count = await els.count()
            for i in range(min(count, 5)):
                txt = (await els.nth(i).inner_text()).strip()[:60]
                cls = await els.nth(i).get_attribute("class") or ""
                print(f"  <{sel}> '{txt}' class='{cls[:50]}'")

        # 説明文っぽいdivを探す
        print("\n--- description candidates ---")
        for sel in [
            'div[class*="Description"]',
            'div[class*="description"]',
            'div[class*="ProductDescription"]',
            'div[class*="ExpandableText"]',
            'div[class*="expandable"]',
            'section[class*="description"]',
            '[id*="description"]',
            '[id*="Description"]',
            'div[class*="gameInfo"]',
        ]:
            els = page.locator(sel)
            count = await els.count()
            if count > 0:
                for i in range(min(count, 2)):
                    txt = (await els.nth(i).inner_text()).strip()
                    cls = await els.nth(i).get_attribute("class") or ""
                    if len(txt) > 30:
                        print(f"  [{sel}] class='{cls[:60]}'")
                        print(f"  text: '{txt[:200]}'")
                        print()

        # 説明文を単純に長いテキストブロックで探す
        print("\n--- Long text divs (>100 chars) ---")
        all_divs = page.locator('div, p, section')
        count = await all_divs.count()
        found = []
        for i in range(min(count, 200)):
            try:
                el = all_divs.nth(i)
                children = await el.locator('*').count()
                if children < 5:  # 子要素が少ない = テキストのみの可能性
                    txt = (await el.inner_text()).strip()
                    if 100 < len(txt) < 2000 and txt not in found:
                        cls = await el.get_attribute("class") or ""
                        tag = await el.evaluate("el => el.tagName")
                        print(f"  <{tag}> class='{cls[:60]}'")
                        print(f"  text: '{txt[:150]}'")
                        print()
                        found.append(txt)
                        if len(found) >= 5:
                            break
            except: pass

        await browser.close()

if __name__ == '__main__':
    asyncio.run(debug_desc())
