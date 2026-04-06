import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageOps
import asyncio
import threading
import requests
from io import BytesIO
import webbrowser
import pywinstyles
import re
from scraper import XboxScraper

# デザイン定数 (究極のホログラム・ネオン)
NEON_CYAN = "#00f2ff"
DARK_CYAN = "#004b50"
NEON_PINK = "#ff00ff"
DARK_BLUE = "#050a14"
PANEL_BG = "#0b1e2e" # 深海のような紺色
HEADER_BG = "#162b3a"

class XboxRankingApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # ウィンドウ基本設定
        self.title("Xbox Holographic Ranking Terminal v5")
        self.geometry("1400x900")
        self.state("zoomed") # 起動時に最大化
        
        # アクリル効果と透過度の設定
        try:
            pywinstyles.apply_style(self, "acrylic")
        except:
            print("pywinstyles error: ignored")
        self.attributes("-alpha", 0.94)
        ctk.set_appearance_mode("dark")
        
        self.scraper = XboxScraper()
        self.ranking_data = []
        self.current_item_index = -1
        self.photo_references = []
        self.row_widgets = []
        self.current_details = None
        self.current_img_index = 0
        self.media_items = []
        self.is_fetching_details = False
        
        # 背景レイヤーの作成 (グリッド・走査線描画用)
        self.bg_canvas = tk.Canvas(self, bg=DARK_BLUE, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        # 背景画像の読み込み
        try:
            self.bg_img_raw = Image.open("bg.png").resize((1400, 950), Image.Resampling.LANCZOS)
            self.bg_img = ImageTk.PhotoImage(self.bg_img_raw)
            self.bg_canvas.create_image(0, 0, image=self.bg_img, anchor="nw", tags="bg_img")
        except: pass

        self.after(100, self._draw_hologram_bg)
        
        self._setup_ui()
        
        # ショートカットキーの有効化
        self.bind_all("<F5>", lambda e: self.load_ranking())
        self.bind_all("<Control-w>", lambda e: self.destroy())
        self.bind_all("<Control-W>", lambda e: self.destroy())
        
    def _draw_hologram_bg(self):
        """背景にSF的なグリッドと走査線を描画"""
        w = self.winfo_width()
        h = self.winfo_height()
        self.bg_canvas.delete("bg")
        
        # グリッド描画 (50px間隔)
        grid_color = "#0a1a2a"
        for x in range(0, w, 50):
            self.bg_canvas.create_line(x, 0, x, h, fill=grid_color, tags="bg")
        for y in range(0, h, 50):
            self.bg_canvas.create_line(0, y, w, y, fill=grid_color, tags="bg")
            
        # 走査線 (非常に薄い横線)
        for y in range(0, h, 4):
            self.bg_canvas.create_line(0, y, w, y, fill="#08101a", width=1, tags="bg")

    def _setup_ui(self):
        # メインコンテナ (背景Canvasの上に配置)
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.place(relx=0.05, rely=0.05, relwidth=0.9, relheight=0.9)
        
        self.main_container.grid_columnconfigure(0, weight=3)
        self.main_container.grid_columnconfigure(1, weight=2)
        self.main_container.grid_rowconfigure(0, weight=1) # メインが全高を優先的に使用
        self.main_container.grid_rowconfigure(1, weight=0) # ログは拡張せず最小限の高さに
        
        # --- 左側パネル: ランキング ---
        self.left_panel = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        
        # タイトルヘッダー (SF調)
        self.app_title = ctk.CTkLabel(
            self.left_panel, text="XBOX 売れ筋ランキング", 
            font=("Segoe UI", 24, "bold"), text_color=NEON_CYAN, anchor="w"
        )
        self.app_title.pack(fill=tk.X, pady=(0, 20))
        
        self.control_bar = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.control_bar.pack(fill=tk.X, pady=(0, 15))
        
        self.refresh_btn = ctk.CTkButton(
            self.control_bar, text="一覧取得 [F5]", font=("Segoe UI", 12, "bold"),
            fg_color="transparent", border_color=NEON_CYAN, border_width=2,
            text_color=NEON_CYAN, hover_color="#003b45", corner_radius=0,
            command=self.load_ranking
        )
        self.refresh_btn.pack(side=tk.LEFT)
        
        self.status_label = ctk.CTkLabel(self.control_bar, text="準備完了", font=("Consolas", 11), text_color="#7ba8b5")
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # リストヘッダー (下の項目とpadxを5で同期し、列を完全に合わせる)
        self.list_header = ctk.CTkFrame(self.left_panel, fg_color=HEADER_BG, height=35, corner_radius=0, border_width=1, border_color=DARK_CYAN)
        self.list_header.pack(fill=tk.X, pady=(0, 5), padx=5)
        self.list_header.pack_propagate(False)
        
        # 1. 順位 (左端 35)
        ctk.CTkLabel(self.list_header, text="順位", width=35, font=("Meiryo", 10, "bold"), text_color=NEON_CYAN).pack(side=tk.LEFT, padx=(5, 1))
        # 4. GP空きスペース (右端 26)
        ctk.CTkFrame(self.list_header, fg_color="transparent", width=26, height=35).pack(side=tk.RIGHT, padx=(0, 2))
        # 3. 価格 (幅84pxの中央に寄せる)
        ctk.CTkLabel(self.list_header, text="価格", width=84, font=("Meiryo", 10, "bold"), anchor="center").pack(side=tk.RIGHT, padx=0)
        # 2. タイトル (残りのスペース)
        ctk.CTkLabel(self.list_header, text="タイトル", font=("Meiryo", 10, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 1))
        
        # スクロールエリア
        self.list_scroll = ctk.CTkScrollableFrame(self.left_panel, fg_color="transparent", corner_radius=0)
        self.list_scroll.pack(fill=tk.BOTH, expand=True)

        # --- 右側パネル: 詳細 (ホログラムカード) ---
        self.right_panel = ctk.CTkFrame(
            self.main_container, fg_color=PANEL_BG, corner_radius=0, 
            border_width=2, border_color=NEON_CYAN
        )
        # 詳細パネルが右側全高を占有するように rowspan=2 を設定
        self.right_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        
        # 装飾: コーナーマーカー (Canvasで描画)
        self.detail_header = ctk.CTkFrame(self.right_panel, fg_color=HEADER_BG, height=60, corner_radius=0)
        self.detail_header.pack(fill=tk.X)
        self.detail_header.pack_propagate(False)
        self.detail_header_label = ctk.CTkLabel(
            self.detail_header, text="データを選択してください", 
            font=("Meiryo", 18, "bold"), text_color=NEON_CYAN
        )
        self.detail_header_label.pack(pady=15, padx=20, anchor="w")
        
        # --- ギャラリー (固定表示) ---
        self.media_module = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.media_module.pack(fill=tk.X, padx=20, pady=(20, 0))
        
        # ギャラリー本体 (フレーム枠を削除)
        self.proj_frame = ctk.CTkFrame(self.media_module, fg_color="transparent", width=320, height=200)
        self.proj_frame.pack(side=tk.LEFT)
        self.proj_frame.pack_propagate(False)
        
        # 画像ラベル (インジケーターを内包する)
        self.image_label = ctk.CTkLabel(self.proj_frame, text="", fg_color="#000000", width=316, height=196)
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # --- レーティング・モジュール (右側の余白に配置) ---
        self.rating_frame = ctk.CTkFrame(self.media_module, fg_color="#0d1f2d", border_width=1, border_color=DARK_CYAN, width=155)
        self.rating_frame.pack(side=tk.LEFT, padx=(15, 0), fill=tk.Y)
        self.rating_frame.pack_propagate(False)
        
        self.avg_score_label = ctk.CTkLabel(self.rating_frame, text="--", font=("Segoe UI", 32, "bold"), text_color="#ffffff")
        self.avg_score_label.pack(side=tk.TOP, pady=0)
        
        self.total_reviews_label = ctk.CTkLabel(self.rating_frame, text="合計 --", font=("Meiryo", 10, "bold"), text_color=NEON_CYAN)
        self.total_reviews_label.pack(side=tk.TOP, pady=0)
        
        # 星別バーのコンテナ (密着表示のためpady=0)
        self.stars_container = ctk.CTkFrame(self.rating_frame, fg_color="transparent")
        self.stars_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=0)
        
        self.star_bars = {}
        for s in ["5", "4", "3", "2", "1"]:
            row = ctk.CTkFrame(self.stars_container, fg_color="transparent", height=24)
            row.pack(fill=tk.X, pady=0)
            row.pack_propagate(False) # 高さを24pxに厳密に固定
            
            ctk.CTkLabel(row, text=f"{s} ★", font=("Meiryo", 11, "bold"), width=34).pack(side=tk.LEFT)
            
            bar = ctk.CTkProgressBar(row, height=12, fg_color="#1a334a", progress_color=NEON_CYAN)
            bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 5))
            bar.set(0)
            
            pct = ctk.CTkLabel(row, text="0%", font=("Consolas", 11, "bold"), width=38)
            pct.pack(side=tk.LEFT)
            self.star_bars[s] = (bar, pct)

        # クリックイベントのバインド (評価エリア全体)
        for w in [self.rating_frame, self.avg_score_label, self.total_reviews_label, self.stars_container]:
            w.bind("<Button-1>", lambda e: self.open_reviews_in_chrome())
            w.configure(cursor="hand2")
        
        # --- スクロール可能な詳細エリア (ギャラリーの下) ---
        self.scroll_detail = ctk.CTkScrollableFrame(self.right_panel, fg_color="transparent", corner_radius=0)
        self.scroll_detail.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 詳細説明（上部に移動）
        self.desc_header = ctk.CTkLabel(self.scroll_detail, text="詳細説明", font=("Meiryo", 12, "bold"), text_color=NEON_CYAN)
        self.desc_header.pack(anchor="w", pady=(10, 5), padx=10)
        
        self.desc_box = ctk.CTkTextbox(self.scroll_detail, fg_color="#081420", border_width=1, border_color=DARK_CYAN, font=("Meiryo", 11), height=400)
        self.desc_box.pack(fill=tk.X, padx=10)
        self.desc_box.configure(state="disabled")

        # 日本語対応状況（詳細説明の下に移動）
        self.lang_header = ctk.CTkLabel(self.scroll_detail, text="日本語対応状況", font=("Meiryo", 12, "bold"), text_color=NEON_CYAN)
        self.lang_header.pack(anchor="w", pady=(20, 5), padx=10)

        self.lang_matrix_frame = ctk.CTkFrame(self.scroll_detail, fg_color="transparent")
        self.lang_matrix_frame.pack(fill=tk.X, pady=(0, 5), padx=10)
        
        self.lang_nodes = {}
        for i, (key, label) in enumerate([("ui", "インターフェース"), ("audio", "音声"), ("subtitles", "字幕")]):
            node = ctk.CTkFrame(self.lang_matrix_frame, fg_color="#081420", border_width=1, border_color=DARK_CYAN, width=110, height=50)
            node.pack(side=tk.LEFT, padx=(0, 10))
            node.pack_propagate(False)
            ctk.CTkLabel(node, text=label, font=("Meiryo", 9, "bold"), text_color=DARK_CYAN).pack(pady=(5, 0))
            status = ctk.CTkLabel(node, text="--", font=("Meiryo", 11, "bold"), text_color="#ffffff")
            status.pack()
            self.lang_nodes[key] = status

        self.play_anywhere_label = ctk.CTkLabel(self.scroll_detail, text="XBOX PLAY ANYWHERE: --", font=("Consolas", 13, "bold"), text_color=NEON_CYAN, anchor="w")
        self.play_anywhere_label.pack(fill=tk.X, pady=(15, 0), padx=10)
        
        # (アクションボタン削除)

        # --- 下部: ターミナルログ ---
        self.log_frame = ctk.CTkFrame(self.main_container, fg_color="#030810", border_width=1, border_color=DARK_CYAN, height=100)
        self.log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 20))
        self.log_frame.grid_propagate(False)
        
        self.log_title = ctk.CTkLabel(self.log_frame, text=" SYSTEM ANALYSIS LOG:", font=("Consolas", 10, "bold"), text_color=DARK_CYAN)
        self.log_title.pack(anchor="w", padx=10, pady=2)
        
        self.log_box = ctk.CTkTextbox(self.log_frame, fg_color="transparent", font=("Consolas", 9), height=70, text_color=NEON_CYAN)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.log_box.insert(tk.END, "> SYSTEM INITIALIZED...\n> WAITING FOR DATA FEED...\n")
        self.log_box.configure(state="disabled")

        # --- 最終解: CustomTkinterの真のキャンバス設定を上書き ---
        def _apply_ultra_increment():
            for scroll_frame in [self.list_scroll, self.scroll_detail]:
                # CustomTkinterの内部キャンバス名は _parent_canvas が正解
                if hasattr(scroll_frame, "_parent_canvas"):
                    # CTk標準は yscrollincrement=1。これを15倍に設定することで、
                    # ホイール1目盛りで20pxから 300px の移動へ劇的倍増させる。
                    scroll_frame._parent_canvas.configure(yscrollincrement=15)
            self.log("SCROLL ENGINE: FIXED & ENHANCED (15X)")

        self.after(500, _apply_ultra_increment)
        self._scroll_reinforce = lambda w, t: None # 不要

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert(tk.END, f"> {text}\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")

    def load_ranking(self):
        self.refresh_btn.configure(state="disabled")
        self.status_label.configure(text="データ取得中...")
        self.log("ATTEMPTING TO ESTABLISH CONNECTION TO XBOX LIVE REPOSITORY...")
        for widget in self.list_scroll.winfo_children(): widget.destroy()
        
        def run():
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(self.scraper.fetch_ranking(limit=350))
                if data:
                    self.after(0, lambda: self.display_ranking(data))
                else:
                    self.log("WARNING: No data returned. Retry.")
                    self.after(0, lambda: self.status_label.configure(text="データ取得失敗 - 再試行してください"))
            except Exception as e:
                err_text = str(e)
                self.log(f"CRITICAL ERROR: {err_text}")
                self.after(0, lambda: self.status_label.configure(text="接続エラー - 再試行してください"))
            finally:
                loop.close()
                self.after(0, lambda: self.refresh_btn.configure(state="normal"))
        threading.Thread(target=run, daemon=True).start()

    def display_ranking(self, data):
        self.ranking_data = data
        self.row_widgets = []
        
        for i, item in enumerate(data):
            # カード型 (高さを24に固定、はみ出し厳禁)
            row = ctk.CTkFrame(self.list_scroll, fg_color="#0c1822", corner_radius=0, border_width=1, border_color="#1a3a4a", height=24)
            row.pack(fill=tk.X, pady=1, padx=5)
            row.pack_propagate(False)
            
            # 1. 順位ビット (左端固定: 幅35)
            r_box = ctk.CTkFrame(row, fg_color=DARK_CYAN, width=35, height=20, corner_radius=0)
            r_box.pack(side=tk.LEFT, padx=(5, 1))
            r_box.pack_propagate(False)
            ctk.CTkLabel(r_box, text=f"{item['rank']:02d}", font=("Consolas", 10, "bold"), text_color=NEON_CYAN, height=12).pack(expand=True)

            # --- 右詰め要素の配置 (限界まで絞る) ---
            
            # 4. GP列 (26pxまで圧縮)
            gp_container = ctk.CTkFrame(row, fg_color="transparent", width=26, height=24)
            gp_container.pack(side=tk.RIGHT, padx=(0, 2))
            gp_container.pack_propagate(False)
            if item["is_game_pass"]:
                ctk.CTkLabel(gp_container, text="GP+", font=("Arial", 8, "bold"), text_color="#10f010", height=20, anchor="e").pack(fill=tk.BOTH)

            # 3. 価格列 (84pxに圧縮 / ￥99,999 が2つ並ぶ最小幅)
            perf_frame = ctk.CTkFrame(row, fg_color="transparent", width=84, height=24)
            perf_frame.pack(side=tk.RIGHT, padx=0)
            perf_frame.pack_propagate(False)
            
            if item["is_sale"]:
                sale_p_lbl = ctk.CTkLabel(perf_frame, text=item["price"], font=("Segoe UI", 10, "bold"), text_color=NEON_PINK, height=20)
                sale_p_lbl.pack(side=tk.RIGHT)
                
                orig_price = item.get("original_price", "")
                if orig_price:
                    lbl_orig = ctk.CTkLabel(perf_frame, text=orig_price, font=("Segoe UI", 8), text_color="#ffffff", height=20)
                    lbl_orig.pack(side=tk.RIGHT, padx=(0, 1))
                    line_strike = ctk.CTkFrame(lbl_orig, fg_color=NEON_PINK, height=2)
                    line_strike.place(relx=0.5, rely=0.5, relwidth=1.0, anchor="center")
            else:
                p_color = NEON_CYAN if item["price"] == "無料" else "#ffffff"
                ctk.CTkLabel(perf_frame, text=item["price"], font=("Segoe UI", 10, "bold"), text_color=p_color, height=20).pack(side=tk.RIGHT)

            # 2. タイトル (残りのスペースを1px単位までタイトに使用)
            lbl_title = ctk.CTkLabel(row, text=item["title"], font=("Meiryo", 11, "bold"), anchor="w", height=20)
            lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 1))
            
            # クリックイベント & 高速スクロールのバインド (全パーツへ適用)
            for w in [row, lbl_title, r_box, perf_frame]:
                w.bind("<Button-1>", lambda e, idx=i: self.on_row_click(idx))
            
            # 再帰的にこのアイテムの全パーツへ高速スクロールを伝播
            self._scroll_reinforce(row, self.list_scroll)
            
            self.row_widgets.append(row)

        self.refresh_btn.configure(state="normal")
        self.status_label.configure(text=f"{len(data)}件のデータを取得")

    def _clear_details_ui(self):
        """詳細パネルの表示項目をリセット"""
        self.detail_header_label.configure(text="データ読込中...")
        self.desc_box.configure(state="normal")
        self.desc_box.delete("1.0", tk.END)
        self.desc_box.insert(tk.END, "データ取得中...")
        self.desc_box.configure(state="disabled")
        
        # 評価のリセット
        self.avg_score_label.configure(text="--")
        self.total_reviews_label.configure(text="合計 --")
        for bar, pct in self.star_bars.values():
            bar.set(0)
            pct.configure(text="0%")
            
        # 対応言語のリセット
        for status in self.lang_nodes.values():
            status.configure(text="--", text_color="#505050")
            
        # Play Anywhereリセット
        self.play_anywhere_label.configure(text="XBOX PLAY ANYWHERE: --", text_color="#505050")
        
        # ギャラリーのリセット
        self.image_label.configure(image=None)
        self.media_items = []

    def on_row_click(self, index):
        if self.is_fetching_details:
            return

        self.is_fetching_details = True
        self.config(cursor="watch")
        
        for idx, row in enumerate(self.row_widgets):
            is_selected = (idx == index)
            row.configure(border_color=NEON_CYAN if is_selected else "#1a3a4a", fg_color="#1a334a" if is_selected else "#0c1822")

        self.current_item_index = index
        game = self.ranking_data[index]
        self.log(f"ANALYZING NODE: {game['title']}")
        
        # UIクリア
        self._clear_details_ui()
        self.detail_header_label.configure(text=game['title']) # タイトルだけは先に表示

        def run_detail():
            self.log(f"FETCHING DETAILS FOR: {game['title']}...")
            loop = asyncio.new_event_loop()
            try:
                details = loop.run_until_complete(self.scraper.fetch_details(game['url']))
                self.after(0, lambda: self.log(f"DECRYPTION COMPLETE: {game['title']}"))
                self.after(0, lambda: self.display_details(details))
            except Exception as e: 
                self.log(f"FAILED TO FETCH DETAILS: {str(e)}")
                print(e)
                self.after(0, lambda: self.config(cursor=""))
                self.after(0, lambda: setattr(self, "is_fetching_details", False))
            finally: loop.close()
        threading.Thread(target=run_detail, daemon=True).start()

    def draw_dots(self, num_imgs):
        # UIウィジェットとしての描画は行わず、状態更新のみ
        pass

    def _draw_indicators_on_img(self, img, num_imgs):
        if num_imgs <= 1: return img
        
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        spacing = 30 # 少し詰める
        dot_radius = 5 # 小さく
        max_w = 200
        if (num_imgs - 1) * spacing > max_w:
            spacing = max_w // (num_imgs - 1)
        
        total_dots_width = (num_imgs - 1) * spacing
        start_x = (img.size[0] / 2) - (total_dots_width / 2)
        y = img.size[1] - 30
        
        # 背景ライン (透明度を上げ、より細く)
        draw.line([start_x, y, start_x + total_dots_width, y], fill=(0, 242, 255, 30), width=1)
        
        # ◀ 矢印 (ポリゴンで確実に描画)
        tri_l = [(start_x - 35, y), (start_x - 20, y - 8), (start_x - 20, y + 8)]
        draw.polygon(tri_l, fill=NEON_CYAN, outline=NEON_CYAN)
        
        for i in range(num_imgs):
            x = start_x + (i * spacing)
            is_active = i == self.current_img_index
            
            if is_active:
                # 活発なノードの控えめなグロー
                draw.ellipse([x-dot_radius-3, y-dot_radius-3, x+dot_radius+3, y+dot_radius+3], outline=(0, 242, 255, 80), width=1)
                draw.ellipse([x-dot_radius, y-dot_radius, x+dot_radius, y+dot_radius], fill=NEON_CYAN, outline=(255, 255, 255, 180), width=1)
            else:
                draw.ellipse([x-dot_radius, y-dot_radius, x+dot_radius, y+dot_radius], fill=(0, 26, 29, 150), outline=(0, 242, 255, 70), width=1)

        # ▶ 矢印 (ポリゴンで確実に描画)
        tri_r = [(start_x + total_dots_width + 35, y), (start_x + total_dots_width + 20, y - 8), (start_x + total_dots_width + 20, y + 8)]
        draw.polygon(tri_r, fill=NEON_CYAN, outline=NEON_CYAN)
        
        return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    def display_details(self, details):
        self.is_fetching_details = False
        self.config(cursor="")
        self.current_details = details
        self.current_img_index = 0
        self.desc_box.configure(state="normal")
        self.desc_box.delete("1.0", tk.END); self.desc_box.insert(tk.END, details["description"])
        self.desc_box.configure(state="disabled")
        
        self.media_items = []
        video_url = details.get("video_url", "なし")
        video_thumb = details.get("video_thumbnail")
        
        if video_url and video_url != "なし":
            thumb_url = video_thumb
            if not thumb_url:
                # YouTube ID 抽出テスト
                m = re.search(r'(?:v=|be/)([A-Za-z0-9_-]{11})', video_url)
                if m:
                    thumb_url = f"https://img.youtube.com/vi/{m.group(1)}/maxresdefault.jpg"
            
            if thumb_url:
                self.media_items.append({'type': 'video', 'url': thumb_url, 'video_url': video_url})
        
        for s in details.get("screenshots", []):
            self.media_items.append({'type': 'image', 'url': s})
        
        # ローカライゼーション・マトリックスの更新
        langs = details.get("languages", None)  # None=テーブルなし, dict=テーブルあり

        for key, status_lbl in self.lang_nodes.items():
            if langs is None:
                # 「その他」タブに言語テーブルが存在しないゲーム → 「-」
                status_lbl.configure(text="-", text_color="#505050")
            elif langs.get(key, False):
                status_lbl.configure(text="◯", text_color=NEON_CYAN)
            else:
                status_lbl.configure(text="×", text_color=NEON_PINK)
        
        # Play Anywhere とレビュー評価
        pa = "-"
        pa_color = "#505050"
        if "play_anywhere" in details:
            if details["play_anywhere"]:
                pa = "◯"; pa_color = NEON_CYAN
            else:
                pa = "×"; pa_color = NEON_PINK
        self.play_anywhere_label.configure(text=f"XBOX PLAY ANYWHERE: {pa}", text_color=pa_color)
        
        # レビューデータの反映
        ratings = details.get("ratings", {})
        self.avg_score_label.configure(text=ratings.get("average", "--"))
        self.total_reviews_label.configure(text=f"合計レビュー数 {ratings.get('total_count', '--')}")
        
        dist = ratings.get("dist", {})
        for s, (bar, pct_label) in self.star_bars.items():
            val_str = dist.get(s, "0%")
            pct_label.configure(text=val_str)
            try:
                # 0% をパース可能な数値に確実に変換
                clean_val = val_str.replace("%", "").strip()
                if clean_val.isdigit():
                    val_int = int(clean_val)
                    bar.set(val_int / 100.0)
                else:
                    bar.set(0)
            except Exception as e:
                print(f"Rating graph error: {e}")
                bar.set(0)
        
        self.draw_dots(len(self.media_items))
        if self.media_items: self.show_current_image()

    def show_current_image(self):
        if not self.media_items: return
        item = self.media_items[self.current_img_index]
        self.draw_dots(len(self.media_items)) # 全描画してインジケーター更新
        
        is_video = item['type'] == 'video'
        url = item['url']
        
        def load():
            try:
                resp = requests.get(url, timeout=10)
                img = Image.open(BytesIO(resp.content))
                img = ImageOps.fit(img, (316, 196), Image.Resampling.LANCZOS)

                if is_video:
                    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)
                    cx, cy = img.size[0] // 2, img.size[1] // 2
                    r = 30
                    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(0, 0, 0, 160), outline=NEON_CYAN, width=2)
                    tri = [(cx-10, cy-16), (cx-10, cy+16), (cx+20, cy)]
                    draw.polygon(tri, fill=NEON_CYAN)
                    img_rgba = img.convert('RGBA')
                    combined = Image.alpha_composite(img_rgba, overlay)
                    img = combined.convert('RGB')

                # インジケーターを描画 (透明オーバーレイ)
                img = self._draw_indicators_on_img(img, len(self.media_items))

                # CTkImage を使用
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(316, 196))
                self.after(0, lambda: self._apply_img(photo, is_video, item.get('video_url')))
            except Exception as e:
                print(f"IMAGE LOAD ERROR: {e}")
        threading.Thread(target=load, daemon=True).start()

    def _apply_img(self, photo, is_video=False, video_url=None):
        self.photo_references = [photo]
        self.image_label.configure(image=photo)
        self.image_label.unbind('<Button-1>')
        self.image_label.bind('<Button-1>', lambda e: self._on_image_click(e, is_video, video_url))
        self.image_label.configure(cursor='hand2')

    def _on_image_click(self, event, is_video, video_url):
        # 画面スケーリング(125%, 150%等)の影響を排除するため、相対比率(0.0-1.0)を使用
        w = self.image_label.winfo_width()
        h = self.image_label.winfo_height()
        if w < 10 or h < 10: return
        
        # 相対座標 (0.0 〜 1.0)
        rx = event.x / w
        ry = event.y / h
        
        # 画像サイズ (316, 196) 上の仮想座標に投影
        vx = rx * 316
        vy = ry * 196
        
        # 画像中心 (158, 98) を基準としたオフセット
        ox = vx - 158
        oy = vy - 98
        
        # 下部操作エリア
        if oy > 40:
            num = len(self.media_items)
            if num <= 1: return
            
            spacing = 30
            max_w = 200
            if (num - 1) * spacing > max_w: spacing = max_w // (num - 1)
            total_w = (num - 1) * spacing
            start_ox = -(total_w / 2)
            
            # 各要素の中心 ox (描画時と完全同期)
            x_prev = start_ox - 27.5
            x_next = (total_w / 2) + 27.5
            
            dists = []
            dists.append(("prev", abs(ox - x_prev)))
            dists.append(("next", abs(ox - x_next)))
            for i in range(num):
                dot_x = start_ox + (i * spacing)
                dists.append((i, abs(ox - dot_x)))
            
            # 最短距離の要素を選択
            target, min_dist = min(dists, key=lambda x: x[1])
            
            # 許容有効範囲を 30px (仮想空間上) に設定
            if min_dist > 30: return
            
            if target == "prev":
                self.log("NAV: PREVIOUS PAGE CLICKED")
                self.prev_image()
            elif target == "next":
                self.log("NAV: NEXT PAGE CLICKED")
                self.next_image()
            else:
                if target != self.current_img_index:
                    self.log(f"NAV: SELECTED ITEM {target + 1} / {num}")
                    self.goto_image(target)
        
        # 中央付近 (動画再生)
        elif is_video and video_url:
            # 仮想中心からの距離で判定
            if (ox**2 + oy**2)**0.5 < 45:
                self.log("MEDIA: OPENING EXTERNAL STREAM")
                webbrowser.open(video_url)

    def goto_image(self, index):
        self.current_img_index = index
        self.show_current_image()

    def prev_image(self):
        if not self.media_items: return
        self.current_img_index = (self.current_img_index - 1) % len(self.media_items)
        self.show_current_image()

    def next_image(self):
        if not self.media_items: return
        self.current_img_index = (self.current_img_index + 1) % len(self.media_items)
        self.show_current_image()

    def open_reviews_in_chrome(self, url_append="?activetab=pivot:reviewstab"):
        if self.current_item_index < 0: return
        url = self.ranking_data[self.current_item_index]["url"]
        if url_append and url_append not in url:
            url += url_append

        self.log(f"OPENING BROWSER: {url}")

        import threading

        def run_browser():
            import asyncio
            from playwright.async_api import async_playwright

            async def do_navigate():
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=False,
                        args=['--start-maximized']
                    )
                    context = await browser.new_context(
                        no_viewport=True,
                        locale="ja-JP"
                    )
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(2.0)

                        # 「レビュー」タブを探してクリック
                        tab = page.locator('button:has-text("レビュー")').first
                        if await tab.count() > 0:
                            await tab.scroll_into_view_if_needed()
                            await asyncio.sleep(0.3)
                            await tab.click(force=True)
                            await asyncio.sleep(2.5)  # レビュー描画を待つ

                        # レビューセクションまでスクロール
                        await page.evaluate("window.scrollTo(0, 700)")

                    except Exception as e:
                        print(f"Browser nav error: {e}")
                    try:
                        while len(context.pages) > 0:
                            await asyncio.sleep(1.0)
                    except:
                        pass

            asyncio.run(do_navigate())

        threading.Thread(target=run_browser, daemon=True).start()
        self.log("Browser launched.")


if __name__ == "__main__":
    app = XboxRankingApp()
    app.mainloop()
