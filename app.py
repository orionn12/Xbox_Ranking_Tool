import asyncio
import re
import threading
import webbrowser

import requests
import pywinstyles
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageOps
from io import BytesIO

from scraper import XboxScraper

# =====================================================================
# デザイン定数
# =====================================================================
NEON_CYAN = "#00f2ff"
DARK_CYAN  = "#004b50"
NEON_PINK  = "#ff00ff"
DARK_BLUE  = "#050a14"
PANEL_BG   = "#0b1e2e"
HEADER_BG  = "#162b3a"


class XboxRankingApp(ctk.CTk):
    """Xbox ホログラフィック・ランキング・ターミナル"""

    def __init__(self):
        super().__init__()

        # ウィンドウ設定
        self.title("Xbox Holographic Ranking Terminal")
        self.geometry("1400x900")
        self.state("zoomed")

        try:
            pywinstyles.apply_style(self, "acrylic")
        except Exception:
            pass
        self.attributes("-alpha", 0.94)
        ctk.set_appearance_mode("dark")

        # 状態変数
        self.scraper            = XboxScraper()
        self.ranking_data:  list = []
        self.row_widgets:   list = []
        self.photo_references:  list = []
        self.media_items:   list = []
        self.current_details    = None
        self.current_item_index = -1
        self.current_img_index  = 0
        self.is_fetching_details = False

        # 背景キャンバス
        self.bg_canvas = tk.Canvas(self, bg=DARK_BLUE, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)

        try:
            self.bg_img_raw = Image.open("bg.png").resize((1400, 950), Image.Resampling.LANCZOS)
            self.bg_img = ImageTk.PhotoImage(self.bg_img_raw)
            self.bg_canvas.create_image(0, 0, image=self.bg_img, anchor="nw", tags="bg_img")
        except Exception:
            pass

        self.after(100, self._draw_hologram_bg)
        self._setup_ui()

        # キーボードショートカット
        self.bind_all("<F5>",        lambda e: self.load_ranking())
        self.bind_all("<Control-w>", lambda e: self.destroy())
        self.bind_all("<Control-W>", lambda e: self.destroy())

    # =========================================================
    # 背景描画
    # =========================================================

    def _draw_hologram_bg(self):
        """SF的なグリッドと走査線を背景に描画する"""
        w = self.winfo_width()
        h = self.winfo_height()
        self.bg_canvas.delete("bg")

        grid_color = "#0a1a2a"
        for x in range(0, w, 50):
            self.bg_canvas.create_line(x, 0, x, h, fill=grid_color, tags="bg")
        for y in range(0, h, 50):
            self.bg_canvas.create_line(0, y, w, y, fill=grid_color, tags="bg")
        for y in range(0, h, 4):
            self.bg_canvas.create_line(0, y, w, y, fill="#08101a", width=1, tags="bg")

    # =========================================================
    # UI 構築
    # =========================================================

    def _setup_ui(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.place(relx=0.05, rely=0.05, relwidth=0.9, relheight=0.9)
        self.main_container.grid_columnconfigure(0, weight=3)
        self.main_container.grid_columnconfigure(1, weight=2)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=0)

        self._build_left_panel()
        self._build_right_panel()
        self._build_log_panel()

        # スクロール速度の強化（15倍）
        self.after(500, self._apply_scroll_boost)

    def _build_left_panel(self):
        """左パネル: ランキングリスト"""
        self.left_panel = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))

        ctk.CTkLabel(
            self.left_panel, text="XBOX 売れ筋ランキング",
            font=("Segoe UI", 24, "bold"), text_color=NEON_CYAN, anchor="w"
        ).pack(fill=tk.X, pady=(0, 20))

        # コントロールバー
        ctrl = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        ctrl.pack(fill=tk.X, pady=(0, 15))

        self.refresh_btn = ctk.CTkButton(
            ctrl, text="一覧取得 [F5]", font=("Segoe UI", 12, "bold"),
            fg_color="transparent", border_color=NEON_CYAN, border_width=2,
            text_color=NEON_CYAN, hover_color="#003b45", corner_radius=0,
            command=self.load_ranking
        )
        self.refresh_btn.pack(side=tk.LEFT)

        self.status_label = ctk.CTkLabel(
            ctrl, text="準備完了", font=("Consolas", 11), text_color="#7ba8b5"
        )
        self.status_label.pack(side=tk.LEFT, padx=20)

        # リストヘッダー
        header = ctk.CTkFrame(
            self.left_panel, fg_color=HEADER_BG, height=35,
            corner_radius=0, border_width=1, border_color=DARK_CYAN
        )
        header.pack(fill=tk.X, pady=(0, 5), padx=5)
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="順位", width=35, font=("Meiryo", 10, "bold"), text_color=NEON_CYAN).pack(side=tk.LEFT, padx=(5, 1))
        ctk.CTkFrame(header, fg_color="transparent", width=26, height=35).pack(side=tk.RIGHT, padx=(0, 2))
        ctk.CTkLabel(header, text="価格", width=84, font=("Meiryo", 10, "bold"), anchor="center").pack(side=tk.RIGHT)
        ctk.CTkLabel(header, text="タイトル", font=("Meiryo", 10, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 1))

        # スクロールエリア
        self.list_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color="transparent", corner_radius=0)
        self.list_scroll.pack(fill=tk.BOTH, expand=True)

    def _build_right_panel(self):
        """右パネル: ゲーム詳細"""
        self.right_panel = ctk.CTkFrame(
            self.main_container, fg_color=PANEL_BG,
            corner_radius=0, border_width=2, border_color=NEON_CYAN
        )
        self.right_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")

        # ヘッダー
        self.detail_header = ctk.CTkFrame(self.right_panel, fg_color=HEADER_BG, height=60, corner_radius=0)
        self.detail_header.pack(fill=tk.X)
        self.detail_header.pack_propagate(False)
        self.detail_header_label = ctk.CTkLabel(
            self.detail_header, text="データを選択してください",
            font=("Meiryo", 18, "bold"), text_color=NEON_CYAN
        )
        self.detail_header_label.pack(pady=15, padx=20, anchor="w")

        # ---- ギャラリー ----
        media_module = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        media_module.pack(fill=tk.X, padx=20, pady=(20, 0))

        self.proj_frame = ctk.CTkFrame(media_module, fg_color="transparent", width=320, height=200)
        self.proj_frame.pack(side=tk.LEFT)
        self.proj_frame.pack_propagate(False)

        self.image_label = ctk.CTkLabel(self.proj_frame, text="", fg_color="#000000", width=316, height=196)
        self.image_label.pack(fill=tk.BOTH, expand=True)

        # ---- 評価パネル ----
        self.rating_frame = ctk.CTkFrame(
            media_module, fg_color="#0d1f2d",
            border_width=1, border_color=DARK_CYAN, width=155
        )
        self.rating_frame.pack(side=tk.LEFT, padx=(15, 0), fill=tk.Y)
        self.rating_frame.pack_propagate(False)

        self.avg_score_label = ctk.CTkLabel(
            self.rating_frame, text="--", font=("Segoe UI", 32, "bold"), text_color="#ffffff"
        )
        self.avg_score_label.pack(side=tk.TOP, pady=0)

        self.total_reviews_label = ctk.CTkLabel(
            self.rating_frame, text="合計 --", font=("Meiryo", 10, "bold"), text_color=NEON_CYAN
        )
        self.total_reviews_label.pack(side=tk.TOP, pady=0)

        self.stars_container = ctk.CTkFrame(self.rating_frame, fg_color="transparent")
        self.stars_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=0)

        self.star_bars = {}
        for s in ["5", "4", "3", "2", "1"]:
            row = ctk.CTkFrame(self.stars_container, fg_color="transparent", height=24)
            row.pack(fill=tk.X, pady=0)
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=f"{s} ★", font=("Meiryo", 11, "bold"), width=34).pack(side=tk.LEFT)
            bar = ctk.CTkProgressBar(row, height=12, fg_color="#1a334a", progress_color=NEON_CYAN)
            bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 5))
            bar.set(0)
            pct = ctk.CTkLabel(row, text="0%", font=("Consolas", 11, "bold"), width=38)
            pct.pack(side=tk.LEFT)
            self.star_bars[s] = (bar, pct)

        # 評価エリアクリックでレビューページを開く
        for w in [self.rating_frame, self.avg_score_label, self.total_reviews_label, self.stars_container]:
            w.bind("<Button-1>", lambda e: self.open_reviews_in_browser())
            w.configure(cursor="hand2")

        # ---- スクロール可能な詳細エリア ----
        self.scroll_detail = ctk.CTkScrollableFrame(self.right_panel, fg_color="transparent", corner_radius=0)
        self.scroll_detail.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            self.scroll_detail, text="詳細説明",
            font=("Meiryo", 12, "bold"), text_color=NEON_CYAN
        ).pack(anchor="w", pady=(10, 5), padx=10)

        self.desc_box = ctk.CTkTextbox(
            self.scroll_detail, fg_color="#081420",
            border_width=1, border_color=DARK_CYAN, font=("Meiryo", 11), height=400
        )
        self.desc_box.pack(fill=tk.X, padx=10)
        self.desc_box.configure(state="disabled")

        ctk.CTkLabel(
            self.scroll_detail, text="日本語対応状況",
            font=("Meiryo", 12, "bold"), text_color=NEON_CYAN
        ).pack(anchor="w", pady=(20, 5), padx=10)

        lang_frame = ctk.CTkFrame(self.scroll_detail, fg_color="transparent")
        lang_frame.pack(fill=tk.X, pady=(0, 5), padx=10)

        self.lang_nodes = {}
        for key, label in [("ui", "インターフェース"), ("audio", "音声"), ("subtitles", "字幕")]:
            node = ctk.CTkFrame(lang_frame, fg_color="#081420", border_width=1, border_color=DARK_CYAN, width=110, height=50)
            node.pack(side=tk.LEFT, padx=(0, 10))
            node.pack_propagate(False)
            ctk.CTkLabel(node, text=label, font=("Meiryo", 9, "bold"), text_color=DARK_CYAN).pack(pady=(5, 0))
            status = ctk.CTkLabel(node, text="--", font=("Meiryo", 11, "bold"), text_color="#ffffff")
            status.pack()
            self.lang_nodes[key] = status

        self.play_anywhere_label = ctk.CTkLabel(
            self.scroll_detail, text="XBOX PLAY ANYWHERE: --",
            font=("Consolas", 13, "bold"), text_color=NEON_CYAN, anchor="w"
        )
        self.play_anywhere_label.pack(fill=tk.X, pady=(15, 0), padx=10)

    def _build_log_panel(self):
        """下部ターミナルログ"""
        self.log_frame = ctk.CTkFrame(
            self.main_container, fg_color="#030810",
            border_width=1, border_color=DARK_CYAN, height=100
        )
        self.log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 20))
        self.log_frame.grid_propagate(False)

        ctk.CTkLabel(
            self.log_frame, text=" SYSTEM ANALYSIS LOG:",
            font=("Consolas", 10, "bold"), text_color=DARK_CYAN
        ).pack(anchor="w", padx=10, pady=2)

        self.log_box = ctk.CTkTextbox(
            self.log_frame, fg_color="transparent",
            font=("Consolas", 9), height=70, text_color=NEON_CYAN
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.log_box.insert(tk.END, "> SYSTEM INITIALIZED...\n> WAITING FOR DATA FEED...\n")
        self.log_box.configure(state="disabled")

    def _apply_scroll_boost(self):
        """スクロール速度を 15 倍に設定する"""
        for scroll_frame in [self.list_scroll, self.scroll_detail]:
            if hasattr(scroll_frame, "_parent_canvas"):
                scroll_frame._parent_canvas.configure(yscrollincrement=15)
        self.log("SCROLL ENGINE: ENHANCED (15X)")

    # =========================================================
    # ログ出力
    # =========================================================

    def log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, f"> {text}\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")

    # =========================================================
    # ランキング取得・表示
    # =========================================================

    def load_ranking(self):
        self.refresh_btn.configure(state="disabled")
        self.status_label.configure(text="データ取得中...")
        self.log("CONNECTING TO XBOX LIVE REPOSITORY...")
        for w in self.list_scroll.winfo_children():
            w.destroy()

        def run():
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(self.scraper.fetch_ranking(limit=350))
                if data:
                    self.after(0, lambda: self.display_ranking(data))
                else:
                    self.log("WARNING: No data returned.")
                    self.after(0, lambda: self.status_label.configure(text="データ取得失敗 - 再試行してください"))
            except Exception as e:
                self.log(f"CRITICAL ERROR: {e}")
                self.after(0, lambda: self.status_label.configure(text="接続エラー - 再試行してください"))
            finally:
                loop.close()
                self.after(0, lambda: self.refresh_btn.configure(state="normal"))

        threading.Thread(target=run, daemon=True).start()

    def display_ranking(self, data: list):
        self.ranking_data = data
        self.row_widgets = []

        for i, item in enumerate(data):
            row = ctk.CTkFrame(
                self.list_scroll, fg_color="#0c1822",
                corner_radius=0, border_width=1, border_color="#1a3a4a", height=24
            )
            row.pack(fill=tk.X, pady=1, padx=5)
            row.pack_propagate(False)

            # 順位
            r_box = ctk.CTkFrame(row, fg_color=DARK_CYAN, width=35, height=20, corner_radius=0)
            r_box.pack(side=tk.LEFT, padx=(5, 1))
            r_box.pack_propagate(False)
            ctk.CTkLabel(r_box, text=f"{item['rank']:02d}", font=("Consolas", 10, "bold"), text_color=NEON_CYAN, height=12).pack(expand=True)

            # Game Pass バッジ
            gp_container = ctk.CTkFrame(row, fg_color="transparent", width=26, height=24)
            gp_container.pack(side=tk.RIGHT, padx=(0, 2))
            gp_container.pack_propagate(False)
            if item["is_game_pass"]:
                ctk.CTkLabel(gp_container, text="GP+", font=("Arial", 8, "bold"), text_color="#10f010", height=20, anchor="e").pack(fill=tk.BOTH)

            # 価格
            perf_frame = ctk.CTkFrame(row, fg_color="transparent", width=84, height=24)
            perf_frame.pack(side=tk.RIGHT)
            perf_frame.pack_propagate(False)

            if item["is_sale"]:
                sale_lbl = ctk.CTkLabel(perf_frame, text=item["price"], font=("Segoe UI", 10, "bold"), text_color=NEON_PINK, height=20)
                sale_lbl.pack(side=tk.RIGHT)
                orig = item.get("original_price", "")
                if orig:
                    orig_lbl = ctk.CTkLabel(perf_frame, text=orig, font=("Segoe UI", 8), text_color="#ffffff", height=20)
                    orig_lbl.pack(side=tk.RIGHT, padx=(0, 1))
                    ctk.CTkFrame(orig_lbl, fg_color=NEON_PINK, height=2).place(relx=0.5, rely=0.5, relwidth=1.0, anchor="center")
            else:
                p_color = NEON_CYAN if item["price"] == "無料" else "#ffffff"
                ctk.CTkLabel(perf_frame, text=item["price"], font=("Segoe UI", 10, "bold"), text_color=p_color, height=20).pack(side=tk.RIGHT)

            # タイトル
            lbl = ctk.CTkLabel(row, text=item["title"], font=("Meiryo", 11, "bold"), anchor="w", height=20)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 1))

            for w in [row, lbl, r_box, perf_frame]:
                w.bind("<Button-1>", lambda e, idx=i: self.on_row_click(idx))

            self.row_widgets.append(row)

        self.refresh_btn.configure(state="normal")
        self.status_label.configure(text=f"{len(data)} 件のデータを取得")

    # =========================================================
    # 詳細パネルの制御
    # =========================================================

    def _clear_details_ui(self):
        """詳細パネルをリセットする"""
        self.detail_header_label.configure(text="データ読込中...")
        self.desc_box.configure(state="normal")
        self.desc_box.delete("1.0", tk.END)
        self.desc_box.insert(tk.END, "データ取得中...")
        self.desc_box.configure(state="disabled")

        self.avg_score_label.configure(text="--")
        self.total_reviews_label.configure(text="合計 --")
        for bar, pct in self.star_bars.values():
            bar.set(0)
            pct.configure(text="0%")

        for status in self.lang_nodes.values():
            status.configure(text="--", text_color="#505050")

        self.play_anywhere_label.configure(text="XBOX PLAY ANYWHERE: --", text_color="#505050")
        self.image_label.configure(image=None)
        self.media_items = []

    def on_row_click(self, index: int):
        if self.is_fetching_details:
            return

        self.is_fetching_details = True
        self.config(cursor="watch")

        for idx, row in enumerate(self.row_widgets):
            row.configure(
                border_color=NEON_CYAN if idx == index else "#1a3a4a",
                fg_color="#1a334a" if idx == index else "#0c1822"
            )

        self.current_item_index = index
        game = self.ranking_data[index]
        self.log(f"ANALYZING: {game['title']}")
        self._clear_details_ui()
        self.detail_header_label.configure(text=game["title"])

        def run_detail():
            loop = asyncio.new_event_loop()
            try:
                details = loop.run_until_complete(self.scraper.fetch_details(game["url"]))
                self.after(0, lambda: self.log(f"DECRYPTION COMPLETE: {game['title']}"))
                self.after(0, lambda: self.display_details(details))
            except Exception as e:
                self.log(f"FETCH ERROR: {e}")
                self.after(0, lambda: self.config(cursor=""))
                self.after(0, lambda: setattr(self, "is_fetching_details", False))
            finally:
                loop.close()

        threading.Thread(target=run_detail, daemon=True).start()

    def display_details(self, details: dict):
        self.is_fetching_details = False
        self.config(cursor="")
        self.current_details = details
        self.current_img_index = 0

        # 説明文
        self.desc_box.configure(state="normal")
        self.desc_box.delete("1.0", tk.END)
        self.desc_box.insert(tk.END, details["description"])
        self.desc_box.configure(state="disabled")

        # メディアリスト構築
        self.media_items = []
        video_url = details.get("video_url", "なし")
        video_thumb = details.get("video_thumbnail")

        if video_url and video_url != "なし":
            if not video_thumb:
                m = re.search(r'(?:v=|be/)([A-Za-z0-9_-]{11})', video_url)
                if m:
                    video_thumb = f"https://img.youtube.com/vi/{m.group(1)}/maxresdefault.jpg"
            if video_thumb:
                self.media_items.append({"type": "video", "url": video_thumb, "video_url": video_url})

        for s in details.get("screenshots", []):
            self.media_items.append({"type": "image", "url": s})

        # 日本語サポート
        langs = details.get("languages")
        for key, status_lbl in self.lang_nodes.items():
            if langs is None:
                status_lbl.configure(text="-", text_color="#505050")
            elif langs.get(key, False):
                status_lbl.configure(text="◯", text_color=NEON_CYAN)
            else:
                status_lbl.configure(text="×", text_color=NEON_PINK)

        # Play Anywhere
        pa_val, pa_color = "-", "#505050"
        if "play_anywhere" in details:
            if details["play_anywhere"]:
                pa_val, pa_color = "◯", NEON_CYAN
            else:
                pa_val, pa_color = "×", NEON_PINK
        self.play_anywhere_label.configure(text=f"XBOX PLAY ANYWHERE: {pa_val}", text_color=pa_color)

        # 評価
        ratings = details.get("ratings", {})
        self.avg_score_label.configure(text=ratings.get("average", "--"))
        self.total_reviews_label.configure(text=f"合計レビュー数 {ratings.get('total_count', '--')}")
        dist = ratings.get("dist", {})
        for s, (bar, pct_label) in self.star_bars.items():
            val_str = dist.get(s, "0%")
            pct_label.configure(text=val_str)
            clean = val_str.replace("%", "").strip()
            bar.set(int(clean) / 100.0 if clean.isdigit() else 0)

        if self.media_items:
            self.show_current_image()

    # =========================================================
    # 画像ギャラリー
    # =========================================================

    def _draw_indicators_on_img(self, img: Image.Image, num_imgs: int) -> Image.Image:
        """ギャラリーナビゲーターをオーバーレイ描画する"""
        if num_imgs <= 1:
            return img

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        spacing = min(30, 200 // max(num_imgs - 1, 1))
        dot_r = 5
        total_w = (num_imgs - 1) * spacing
        start_x = img.size[0] / 2 - total_w / 2
        y = img.size[1] - 30

        draw.line([start_x, y, start_x + total_w, y], fill=(0, 242, 255, 30), width=1)

        # ◀ / ▶ 矢印
        draw.polygon([(start_x - 35, y), (start_x - 20, y - 8), (start_x - 20, y + 8)], fill=NEON_CYAN)
        draw.polygon([(start_x + total_w + 35, y), (start_x + total_w + 20, y - 8), (start_x + total_w + 20, y + 8)], fill=NEON_CYAN)

        for i in range(num_imgs):
            x = start_x + i * spacing
            if i == self.current_img_index:
                draw.ellipse([x - dot_r - 3, y - dot_r - 3, x + dot_r + 3, y + dot_r + 3], outline=(0, 242, 255, 80), width=1)
                draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=NEON_CYAN, outline=(255, 255, 255, 180), width=1)
            else:
                draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=(0, 26, 29, 150), outline=(0, 242, 255, 70), width=1)

        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    def show_current_image(self):
        if not self.media_items:
            return
        item = self.media_items[self.current_img_index]
        is_video = item["type"] == "video"
        url = item["url"]

        def load():
            try:
                resp = requests.get(url, timeout=10)
                img = Image.open(BytesIO(resp.content))
                img = ImageOps.fit(img, (316, 196), Image.Resampling.LANCZOS)

                if is_video:
                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    d = ImageDraw.Draw(overlay)
                    cx, cy = img.size[0] // 2, img.size[1] // 2
                    r = 30
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 160), outline=NEON_CYAN, width=2)
                    d.polygon([(cx - 10, cy - 16), (cx - 10, cy + 16), (cx + 20, cy)], fill=NEON_CYAN)
                    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

                img = self._draw_indicators_on_img(img, len(self.media_items))
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(316, 196))
                self.after(0, lambda: self._apply_img(photo, is_video, item.get("video_url")))
            except Exception as e:
                print(f"Image load error: {e}")

        threading.Thread(target=load, daemon=True).start()

    def _apply_img(self, photo, is_video: bool = False, video_url: str | None = None):
        self.photo_references = [photo]
        self.image_label.configure(image=photo)
        self.image_label.unbind("<Button-1>")
        self.image_label.bind("<Button-1>", lambda e: self._on_image_click(e, is_video, video_url))
        self.image_label.configure(cursor="hand2")

    def _on_image_click(self, event, is_video: bool, video_url: str | None):
        """画像クリックでナビゲーションまたは動画再生"""
        w = self.image_label.winfo_width()
        h = self.image_label.winfo_height()
        if w < 10 or h < 10:
            return

        # 仮想座標（316×196）へ変換
        vx = (event.x / w) * 316
        vy = (event.y / h) * 196
        ox = vx - 158
        oy = vy - 98

        if oy > 40:
            num = len(self.media_items)
            if num <= 1:
                return
            spacing = min(30, 200 // max(num - 1, 1))
            total_w = (num - 1) * spacing
            start_ox = -(total_w / 2)

            candidates = [
                ("prev", abs(ox - (start_ox - 27.5))),
                ("next", abs(ox - (total_w / 2 + 27.5))),
            ] + [(i, abs(ox - (start_ox + i * spacing))) for i in range(num)]

            target, min_dist = min(candidates, key=lambda x: x[1])
            if min_dist > 30:
                return

            if target == "prev":
                self.prev_image()
            elif target == "next":
                self.next_image()
            elif target != self.current_img_index:
                self.goto_image(target)

        elif is_video and video_url and (ox ** 2 + oy ** 2) ** 0.5 < 45:
            self.log("MEDIA: OPENING EXTERNAL STREAM")
            webbrowser.open(video_url)

    def goto_image(self, index: int):
        self.current_img_index = index
        self.show_current_image()

    def prev_image(self):
        if self.media_items:
            self.current_img_index = (self.current_img_index - 1) % len(self.media_items)
            self.show_current_image()

    def next_image(self):
        if self.media_items:
            self.current_img_index = (self.current_img_index + 1) % len(self.media_items)
            self.show_current_image()

    # =========================================================
    # レビューページを Playwright で開く
    # =========================================================

    def open_reviews_in_browser(self):
        if self.current_item_index < 0:
            return
        url = self.ranking_data[self.current_item_index]["url"]
        if "?activetab" not in url:
            url += "?activetab=pivot:reviewstab"
        self.log(f"OPENING BROWSER: {url}")

        def run_browser():
            import asyncio
            from playwright.async_api import async_playwright

            async def navigate():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                    context = await browser.new_context(no_viewport=True, locale="ja-JP")
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(2.0)
                        tab = page.locator('button:has-text("レビュー")').first
                        if await tab.count() > 0:
                            await tab.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            await tab.click(force=True)
                            await asyncio.sleep(2.5)
                        await page.evaluate("window.scrollTo(0, 700)")
                        while len(context.pages) > 0:
                            await asyncio.sleep(1.0)
                    except Exception as e:
                        print(f"Browser nav error: {e}")

            asyncio.run(navigate())

        threading.Thread(target=run_browser, daemon=True).start()
        self.log("Browser launched.")


if __name__ == "__main__":
    app = XboxRankingApp()
    app.mainloop()
