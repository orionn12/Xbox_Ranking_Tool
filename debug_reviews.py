import asyncio
from playwright.async_api import async_playwright
import re

async def debug_reviews(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Opening: {url}")
        await page.goto(url, wait_until="networkidle")
        
        # ページ全体のHTMLを保存して後で確認できるようにする
        content = await page.content()
        with open("debug_page_ratings.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        ratings_info = {"average": "0.0", "total_count": "0", "dist": {}}
        
        # 現在のセレクターを試す
        avg_loc = page.locator('[class*="AverageRating-module__rating"]').first
        cnt_loc = page.locator('[class*="AverageRating-module__reviewCount"]').first
        
        print(f"Current Avg Selector Count: {await avg_loc.count()}")
        if await avg_loc.count() > 0:
            print(f"Avg Text: {await avg_loc.inner_text()}")
            
        # 画面上の「評価」というテキストを持つ要素を探す
        try:
            # 「4.5 / 5」のようなテキストを探す
            rating_text = await page.evaluate('''() => {
                const el = document.querySelector('[class*="AverageRating"]');
                return el ? el.innerText : "Not found";
            }''')
            print(f"JS Eval Rating: {rating_text}")
        except: pass

        # スクリーンショットを撮って視覚的に確認
        await page.screenshot(path="debug_ratings.png")
        await browser.close()

if __name__ == "__main__":
    # フォートナイトのページでテスト
    asyncio.run(debug_reviews("https://www.xbox.com/ja-JP/games/store/fortnite/BT9FZP7X0F6V"))
