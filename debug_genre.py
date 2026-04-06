import asyncio
from scraper import XboxScraper

async def test_urls():
    scraper = XboxScraper()
    urls = [
        "https://www.xbox.com/ja-JP/games/store/minecraft/9MVXMVT8ZKWC/0010", # Minecraft
        "https://www.xbox.com/ja-JP/games/store/grand-theft-auto-v-premium-edition/C49L9H5LMG8W", # GTA V
        "https://www.xbox.com/ja-JP/games/store/2077/BX3M8L83BBRW", # Cyberpunk 2077
        "https://www.xbox.com/ja-JP/games/store/palworld/9N9E3CQWBDRN", # Palworld
    ]
    
    for url in urls:
        print(f"\nTesting: {url}")
        res = await scraper.fetch_details(url)
        print(f"Result Genre: {res['genre']}")
        print(f"Result Images: {len(res['screenshots'])}")

if __name__ == "__main__":
    asyncio.run(test_urls())
