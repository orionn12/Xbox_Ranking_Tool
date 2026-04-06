import asyncio
import re
from playwright.async_api import async_playwright

async def debug_run(url):
    print(f"Starting debug for: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="ja-JP")
        page = await context.new_page()
        
        await page.goto(url, wait_until="domcontentloaded")
        
        # Auto scroll to bottom
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    let distance = 300;
                    let timer = setInterval(() => {
                        let scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight - window.innerHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 200);
                });
            }
        """)
        await asyncio.sleep(2.0)
        
        try:
            tab_btn = page.locator('button:has-text("レビュー"), [id*="review-tab"], [aria-label*="レビュー"]').first
            print(f"Found review tab: {await tab_btn.count()}")
            if await tab_btn.count() > 0:
                await tab_btn.click()
                print("Clicked review tab")
                await asyncio.sleep(2.0)
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1.0)
        except Exception as e:
            print("Tab click error:", e)
        
        await page.screenshot(path="debug_after_scroll_bottom.png")
        content = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        ratings_info = {"average": "0.0", "total_count": "0"}
        
        m_avg = re.search(r'"ratingValue":\s*"([\d.]+)"', content)
        if m_avg: ratings_info["average"] = m_avg.group(1)
        m_cnt = re.search(r'"ratingCount":\s*"(\d+)"', content)
        if m_cnt: ratings_info["total_count"] = m_cnt.group(1)
        
        print("JSON-LD extraction:", ratings_info)
        
        if ratings_info["average"] == "0.0":
            body_text = await page.inner_text("body")
            p_avg = re.search(r'(\d\.\d)\s*/\s*5|(\d\.\d)つ星', body_text)
            if p_avg: ratings_info["average"] = p_avg.group(1) or p_avg.group(2)
            p_cnt = re.search(r'\((\d[\d,.]*[KkMm]?)\)\s*評価|(\d[\d,.]*[KkMm]?)\s*個の評価|合計(\d[\d,.]+[a-zA-Z]*)\s+', body_text)
            if p_cnt: ratings_info["total_count"] = p_cnt.group(1) or p_cnt.group(2) or p_cnt.group(3)
            print("Regex extraction:", ratings_info)
            
        await browser.close()
        print("Debug done.")

if __name__ == "__main__":
    asyncio.run(debug_run("https://www.xbox.com/ja-JP/games/store/minecraft/9MVXMVT8ZKWC/0010"))
