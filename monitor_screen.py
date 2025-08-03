import cv2
import numpy as np
import pytesseract
import tkinter as tk
from tkinter import ttk, colorchooser
import threading
import time
from PIL import Image, ImageTk, ImageGrab
import re
from dataclasses import dataclass
from typing import List, Tuple, Dict
import difflib

@dataclass
class TextMatch:
    text: str
    note: str
    x: int
    y: int
    width: int
    height: int
    confidence: int
    match_type: str

@dataclass
class OverlayConfig:
    display_duration: float = 3.0  # 顯示時間（秒）
    bg_color: str = "#FFD700"      # 背景顏色
    text_color: str = "#000000"    # 文字顏色
    font_size: int = 9             # 字體大小
    alpha: float = 0.9             # 透明度
    border_width: int = 2          # 邊框寬度

class TimedOverlay:
    """帶有自動消失功能的覆蓋窗口"""
    def __init__(self, match: TextMatch, config: OverlayConfig, screen_width: int, screen_height: int):
        self.overlay = tk.Toplevel()
        self.overlay.wm_overrideredirect(True)
        self.overlay.wm_attributes("-topmost", True)
        self.overlay.wm_attributes("-alpha", config.alpha)
        
        self.overlay.configure(bg=config.bg_color, relief='raised', bd=config.border_width)
        
        # 計算位置（避免超出螢幕）
        x_pos = match.x + match.width + 10
        y_pos = match.y - 5
        
        if x_pos + 250 > screen_width:
            x_pos = match.x - 250
        if y_pos < 0:
            y_pos = match.y + match.height + 5
        if y_pos + 60 > screen_height:
            y_pos = screen_height - 60
            
        self.overlay.geometry(f"+{x_pos}+{y_pos}")
        
        # 創建標籤
        label_text = f"{match.note}\n'{match.text}'\n{match.match_type} ({match.confidence}%)"
        self.label = tk.Label(self.overlay, text=label_text, 
                            bg=config.bg_color, fg=config.text_color, 
                            font=('Arial', config.font_size, 'bold'), 
                            padx=8, pady=5)
        self.label.pack()
        
        # 設置自動消失
        if config.display_duration > 0:
            self.overlay.after(int(config.display_duration * 1000), self.destroy)
    
    def destroy(self):
        try:
            self.overlay.destroy()
        except:
            pass

class FixedScreenTextMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("可自定義提示樣式的螢幕文字監控系統")
        self.root.geometry("800x700")
        
        # 監控配置
        self.target_strings = {}  # {string: note}
        self.monitoring = False
        self.show_debug = False
        self.overlay_windows = []
        self.debug_window = None
        self.detection_count = 0
        self.last_detected_texts = []
        
        # OCR配置
        self.ocr_config = '--oem 3 --psm 6'
        
        # 螢幕尺寸
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # 覆蓋窗口配置
        self.overlay_configs = {
            "完全匹配": OverlayConfig(3.0, "#00FF00", "#000000", 10, 0.9, 2),
            "包含匹配": OverlayConfig(2.5, "#FFD700", "#000000", 9, 0.9, 2),
            "模糊匹配": OverlayConfig(2.0, "#FF6B6B", "#FFFFFF", 9, 0.9, 2)
        }
        
        self.setup_ui()
        
    def setup_ui(self):
        # 創建筆記本控件（標籤頁）
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 主要監控頁面
        main_frame = ttk.Frame(notebook, padding="10")
        notebook.add(main_frame, text="監控設定")
        
        # 樣式設定頁面
        style_frame = ttk.Frame(notebook, padding="10")
        notebook.add(style_frame, text="提示樣式")
        
        self.setup_main_tab(main_frame)
        self.setup_style_tab(style_frame)
        
    def setup_main_tab(self, parent):
        """設置主要監控標籤頁"""
        # 標題
        title_label = ttk.Label(parent, text="螢幕文字監控系統", 
                               font=('Arial', 14, 'bold'))
        title_label.grid(row=0, column=0, columnspan=4, pady=10)
        
        # 匹配模式選擇
        mode_frame = ttk.LabelFrame(parent, text="匹配模式", padding="5")
        mode_frame.grid(row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)
        
        self.match_mode = tk.StringVar(value="fuzzy")
        ttk.Radiobutton(mode_frame, text="模糊匹配 (推薦)", variable=self.match_mode, 
                       value="fuzzy").grid(row=0, column=0, padx=5)
        ttk.Radiobutton(mode_frame, text="包含匹配", variable=self.match_mode, 
                       value="contains").grid(row=0, column=1, padx=5)
        ttk.Radiobutton(mode_frame, text="完全匹配", variable=self.match_mode, 
                       value="exact").grid(row=0, column=2, padx=5)
        
        # 置信度設置
        conf_frame = ttk.LabelFrame(parent, text="置信度設置", padding="5")
        conf_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(conf_frame, text="最低置信度:").grid(row=0, column=0, padx=5)
        self.confidence_threshold = tk.IntVar(value=30)
        confidence_scale = ttk.Scale(conf_frame, from_=0, to=100, 
                                   variable=self.confidence_threshold, 
                                   orient=tk.HORIZONTAL, length=200)
        confidence_scale.grid(row=0, column=1, padx=5)
        
        self.conf_label = ttk.Label(conf_frame, text="30%")
        self.conf_label.grid(row=0, column=2, padx=5)
        confidence_scale.configure(command=self.update_confidence_label)
        
        # 目標字串輸入
        target_frame = ttk.LabelFrame(parent, text="監控目標", padding="5")
        target_frame.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(target_frame, text="監控字串:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.string_entry = ttk.Entry(target_frame, width=20)
        self.string_entry.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(target_frame, text="顯示註解:").grid(row=0, column=2, sticky=tk.W, pady=2)
        self.note_entry = ttk.Entry(target_frame, width=20)
        self.note_entry.grid(row=0, column=3, padx=5, pady=2)
        
        ttk.Button(target_frame, text="添加", command=self.add_target).grid(row=0, column=4, padx=5)
        
        # 按鈕框架
        button_frame = ttk.Frame(parent)
        button_frame.grid(row=4, column=0, columnspan=4, pady=10)
        
        ttk.Button(button_frame, text="即時檢測測試", command=self.test_detection).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_frame, text="開始監控", command=self.start_monitoring).pack(side=tk.LEFT, padx=3)
        ttk.Button(button_frame, text="停止監控", command=self.stop_monitoring).pack(side=tk.LEFT, padx=3)
        
        # 調試選項
        debug_frame = ttk.Frame(parent)
        debug_frame.grid(row=5, column=0, columnspan=4, pady=5)
        
        self.debug_var = tk.BooleanVar()
        ttk.Checkbutton(debug_frame, text="顯示所有檢測到的文字", variable=self.debug_var).pack(side=tk.LEFT, padx=5)
        
        # 監控列表
        ttk.Label(parent, text="監控列表:").grid(row=6, column=0, sticky=tk.W, pady=(10,5))
        
        list_frame = ttk.Frame(parent)
        list_frame.grid(row=7, column=0, columnspan=4, pady=5, sticky=(tk.W, tk.E))
        
        self.target_listbox = tk.Listbox(list_frame, height=6, width=60)
        self.target_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Button(list_frame, text="刪除選中", command=self.remove_target).pack(side=tk.RIGHT, padx=5)
        
        # 狀態和統計
        self.status_label = ttk.Label(parent, text="狀態: 待機中", foreground="blue")
        self.status_label.grid(row=8, column=0, columnspan=4, pady=5)
        
        self.stats_label = ttk.Label(parent, text="檢測次數: 0")
        self.stats_label.grid(row=9, column=0, columnspan=4)
        
        # 檢測結果顯示
        result_frame = ttk.LabelFrame(parent, text="檢測結果", padding="5")
        result_frame.grid(row=10, column=0, columnspan=4, pady=5, sticky=(tk.W, tk.E))
        
        self.result_text = tk.Text(result_frame, height=6, width=70)
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        # 預設範例
        self.add_default_targets()
        
    def setup_style_tab(self, parent):
        """設置樣式配置標籤頁"""
        ttk.Label(parent, text="提示框樣式設定", font=('Arial', 14, 'bold')).pack(pady=10)
        
        # 為每種匹配類型創建設定區域
        for match_type in ["完全匹配", "包含匹配", "模糊匹配"]:
            self.create_style_section(parent, match_type)
            
        # 全域設定
        global_frame = ttk.LabelFrame(parent, text="全域設定", padding="10")
        global_frame.pack(fill=tk.X, pady=10)
        
        # 預覽按鈕
        preview_frame = ttk.Frame(global_frame)
        preview_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(preview_frame, text="預覽完全匹配", 
                  command=lambda: self.preview_overlay("完全匹配")).pack(side=tk.LEFT, padx=5)
        ttk.Button(preview_frame, text="預覽包含匹配", 
                  command=lambda: self.preview_overlay("包含匹配")).pack(side=tk.LEFT, padx=5)
        ttk.Button(preview_frame, text="預覽模糊匹配", 
                  command=lambda: self.preview_overlay("模糊匹配")).pack(side=tk.LEFT, padx=5)
        
        # 重置按鈕
        ttk.Button(global_frame, text="重置為預設值", command=self.reset_styles).pack(pady=10)
        
    def create_style_section(self, parent, match_type):
        """為特定匹配類型創建樣式設定區域"""
        config = self.overlay_configs[match_type]
        
        frame = ttk.LabelFrame(parent, text=f"{match_type} 設定", padding="10")
        frame.pack(fill=tk.X, pady=5)
        
        # 顯示時間設定
        time_frame = ttk.Frame(frame)
        time_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(time_frame, text="顯示時間(秒):").pack(side=tk.LEFT)
        time_var = tk.DoubleVar(value=config.display_duration)
        time_scale = ttk.Scale(time_frame, from_=0.5, to=10.0, variable=time_var, 
                             orient=tk.HORIZONTAL, length=200)
        time_scale.pack(side=tk.LEFT, padx=5)
        
        time_label = ttk.Label(time_frame, text=f"{config.display_duration:.1f}s")
        time_label.pack(side=tk.LEFT, padx=5)
        
        # 更新顯示時間的回調
        def update_time(value):
            config.display_duration = float(value)
            time_label.config(text=f"{float(value):.1f}s")
        
        time_scale.configure(command=update_time)
        
        # 顏色設定
        color_frame = ttk.Frame(frame)
        color_frame.pack(fill=tk.X, pady=2)
        
        # 背景顏色
        bg_color_frame = ttk.Frame(color_frame)
        bg_color_frame.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(bg_color_frame, text="背景顏色:").pack()
        bg_color_btn = tk.Button(bg_color_frame, text="選擇", bg=config.bg_color, 
                                width=8, height=1,
                                command=lambda: self.choose_color(config, 'bg_color', bg_color_btn))
        bg_color_btn.pack(pady=2)
        
        # 文字顏色
        text_color_frame = ttk.Frame(color_frame)
        text_color_frame.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(text_color_frame, text="文字顏色:").pack()
        text_color_btn = tk.Button(text_color_frame, text="選擇", bg=config.text_color, 
                                  width=8, height=1,
                                  command=lambda: self.choose_color(config, 'text_color', text_color_btn))
        text_color_btn.pack(pady=2)
        
        # 其他設定
        other_frame = ttk.Frame(frame)
        other_frame.pack(fill=tk.X, pady=2)
        
        # 字體大小
        font_frame = ttk.Frame(other_frame)
        font_frame.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(font_frame, text="字體大小:").pack()
        font_var = tk.IntVar(value=config.font_size)
        font_spin = ttk.Spinbox(font_frame, from_=8, to=16, textvariable=font_var, width=5)
        font_spin.pack()
        font_var.trace('w', lambda *args: setattr(config, 'font_size', font_var.get()))
        
        # 透明度
        alpha_frame = ttk.Frame(other_frame)
        alpha_frame.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(alpha_frame, text="透明度:").pack()
        alpha_var = tk.DoubleVar(value=config.alpha)
        alpha_scale = ttk.Scale(alpha_frame, from_=0.3, to=1.0, variable=alpha_var, 
                              orient=tk.HORIZONTAL, length=100)
        alpha_scale.pack()
        alpha_var.trace('w', lambda *args: setattr(config, 'alpha', alpha_var.get()))
        
    def choose_color(self, config, color_type, button):
        """選擇顏色"""
        current_color = getattr(config, color_type)
        color = colorchooser.askcolor(color=current_color, title=f"選擇{color_type}顏色")
        if color[1]:  # 如果選擇了顏色
            setattr(config, color_type, color[1])
            button.config(bg=color[1])
            
    def preview_overlay(self, match_type):
        """預覽覆蓋窗口樣式"""
        # 創建假的匹配數據用於預覽
        fake_match = TextMatch(
            text="預覽文字",
            note="🎯 這是預覽",
            x=100, y=100, width=80, height=20,
            confidence=95,
            match_type=match_type
        )
        
        config = self.overlay_configs[match_type]
        overlay = TimedOverlay(fake_match, config, self.screen_width, self.screen_height)
        
    def reset_styles(self):
        """重置所有樣式為預設值"""
        self.overlay_configs = {
            "完全匹配": OverlayConfig(3.0, "#00FF00", "#000000", 10, 0.9, 2),
            "包含匹配": OverlayConfig(2.5, "#FFD700", "#000000", 9, 0.9, 2),
            "模糊匹配": OverlayConfig(2.0, "#FF6B6B", "#FFFFFF", 9, 0.9, 2)
        }
        # 重新載入樣式標籤頁
        self.root.destroy()
        self.__init__()
        
    def add_default_targets(self):
        """添加預設監控目標"""
        defaults = [
            ("YouTube", "🎥 影片平台"),
            ("Windows", "🪟 作業系統"),
            ("Tesseract", "🔍 OCR引擎"),
            ("bash", "💻 命令列"),
            ("monica", "🤖 AI助手"),
            ("translate", "🌐 翻譯"),
            ("installed", "📦 已安裝"),
            ("file", "📁 檔案"),
            ("directory", "📂 目錄")
        ]
        
        for target, note in defaults:
            self.target_strings[target.lower()] = note
            self.target_listbox.insert(tk.END, f"{target} -> {note}")
            
    def update_confidence_label(self, value):
        """更新置信度標籤"""
        self.conf_label.config(text=f"{int(float(value))}%")
        
    def add_target(self):
        target_string = self.string_entry.get().strip()
        note = self.note_entry.get().strip()
        
        if target_string and note:
            self.target_strings[target_string.lower()] = note
            self.target_listbox.insert(tk.END, f"{target_string} -> {note}")
            self.string_entry.delete(0, tk.END)
            self.note_entry.delete(0, tk.END)
            
    def remove_target(self):
        """刪除選中的目標"""
        selection = self.target_listbox.curselection()
        if selection:
            index = selection[0]
            item = self.target_listbox.get(index)
            target = item.split(" -> ")[0].lower()
            
            if target in self.target_strings:
                del self.target_strings[target]
            
            self.target_listbox.delete(index)
            
    def fuzzy_match(self, text, target, threshold=0.6):
        """模糊匹配函數"""
        ratio = difflib.SequenceMatcher(None, text.lower(), target.lower()).ratio()
        return ratio >= threshold
        
    def capture_screen(self):
        """安全的螢幕截圖方法"""
        try:
            screenshot = ImageGrab.grab()
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img
        except Exception as e:
            print(f"截圖錯誤: {e}")
            return None
        
    def find_text_matches(self, img) -> List[TextMatch]:
        """在圖像中尋找目標文字並返回匹配結果"""
        matches = []
        
        if img is None:
            return matches
            
        try:
            data = pytesseract.image_to_data(img, config=self.ocr_config, 
                                           output_type=pytesseract.Output.DICT)
            
            detected_texts = []
            confidence_threshold = self.confidence_threshold.get()
            match_mode = self.match_mode.get()
            
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = int(data['conf'][i])
                
                if text and conf >= confidence_threshold:
                    detected_texts.append((text, conf, i))
                    
                    for target_string, note in self.target_strings.items():
                        match_found = False
                        match_type = ""
                        
                        if match_mode == "exact":
                            match_found = text.lower() == target_string.lower()
                            match_type = "完全匹配"
                        elif match_mode == "contains":
                            match_found = target_string.lower() in text.lower() or text.lower() in target_string.lower()
                            match_type = "包含匹配"
                        elif match_mode == "fuzzy":
                            match_found = self.fuzzy_match(text, target_string, 0.6)
                            match_type = "模糊匹配"
                        
                        if match_found:
                            match = TextMatch(
                                text=text,
                                note=note,
                                x=data['left'][i],
                                y=data['top'][i],
                                width=data['width'][i],
                                height=data['height'][i],
                                confidence=conf,
                                match_type=match_type
                            )
                            matches.append(match)
            
            self.last_detected_texts = detected_texts
            
        except Exception as e:
            print(f"OCR錯誤: {e}")
            
        return matches
        
    def test_detection(self):
        """測試即時檢測功能"""
        self.status_label.config(text="狀態: 執行檢測測試...", foreground="orange")
        threading.Thread(target=self._run_detection_test, daemon=True).start()
        
    def _run_detection_test(self):
        """執行檢測測試的後台任務"""
        try:
            img = self.capture_screen()
            
            if img is None:
                def update_error_ui():
                    self.status_label.config(text="截圖失敗", foreground="red")
                self.root.after(0, update_error_ui)
                return
            
            matches = self.find_text_matches(img)
            
            def update_ui():
                self.show_detection_results(matches)
            
            self.root.after(0, update_ui)
            
        except Exception as e:
            error_message = str(e)
            
            def update_error_ui():
                self.status_label.config(text=f"檢測測試失敗: {error_message}", foreground="red")
            
            self.root.after(0, update_error_ui)
            
    def show_detection_results(self, matches):
        """顯示檢測結果"""
        self.result_text.delete(1.0, tk.END)
        
        result = f"=== 檢測測試結果 ({time.strftime('%H:%M:%S')}) ===\n"
        result += f"匹配模式: {self.match_mode.get()}\n"
        result += f"置信度門檻: {self.confidence_threshold.get()}%\n"
        result += f"找到匹配: {len(matches)} 個\n\n"
        
        if matches:
            result += "🎯 找到的匹配:\n"
            for match in matches:
                result += f"  • '{match.text}' -> {match.note}\n"
                result += f"    位置: ({match.x}, {match.y}) 置信度: {match.confidence}% ({match.match_type})\n\n"
        else:
            result += "⚠️ 未找到匹配的目標文字\n\n"
        
        if self.debug_var.get() and self.last_detected_texts:
            result += f"🔍 所有檢測到的文字 (前20個):\n"
            for text, conf, _ in self.last_detected_texts[:20]:
                result += f"  • '{text}' (置信度: {conf}%)\n"
        
        self.result_text.insert(1.0, result)
        self.status_label.config(text=f"檢測完成: 找到 {len(matches)} 個匹配", foreground="blue")
        
    def create_overlay(self, match: TextMatch) -> TimedOverlay:
        """創建帶有自定義樣式的覆蓋窗口"""
        config = self.overlay_configs[match.match_type]
        return TimedOverlay(match, config, self.screen_width, self.screen_height)
        
    def start_monitoring(self):
        if not self.monitoring and self.target_strings:
            self.monitoring = True
            self.status_label.config(text="狀態: 監控中...", foreground="green")
            self.monitor_thread = threading.Thread(target=self.monitor_screen, daemon=True)
            self.monitor_thread.start()
        elif not self.target_strings:
            self.status_label.config(text="請先添加監控目標", foreground="red")
            
    def stop_monitoring(self):
        self.monitoring = False
        self.status_label.config(text="狀態: 已停止", foreground="red")
        self.clear_overlays()
        
    def clear_overlays(self):
        for window in self.overlay_windows:
            try:
                window.destroy()
            except:
                pass
        self.overlay_windows.clear()
        
    def monitor_screen(self):
        """主要監控循環"""
        while self.monitoring:
            try:
                start_time = time.time()
                
                img = self.capture_screen()
                
                if img is None:
                    time.sleep(1)
                    continue
                
                # 不需要手動清除，TimedOverlay會自動消失
                
                matches = self.find_text_matches(img)
                
                # 創建新的覆蓋窗口
                for match in matches:
                    overlay = self.create_overlay(match)
                    self.overlay_windows.append(overlay)
                
                self.detection_count += 1
                elapsed_time = (time.time() - start_time) * 1000
                
                count = self.detection_count
                elapsed = elapsed_time
                matches_count = len(matches)
                
                def update_stats():
                    self.stats_label.config(
                        text=f"檢測次數: {count} | 本次耗時: {elapsed:.1f}ms | 找到匹配: {matches_count} 個")
                
                self.root.after(0, update_stats)
                
                if matches:
                    match_info = f"[{time.strftime('%H:%M:%S')}] 找到 {len(matches)} 個匹配:\n"
                    for match in matches[:3]:
                        match_info += f"  • {match.text} -> {match.note} ({match.match_type})\n"
                    match_info += "\n"
                    
                    def update_results():
                        self.result_text.insert(tk.END, match_info)
                        self.result_text.see(tk.END)
                    
                    self.root.after(0, update_results)  # 👈 記得調用函數！
    
                # 控制檢測頻率
                sleep_time = max(0.5, 2.0 - (time.time() - start_time))
                time.sleep(sleep_time)
                
            except Exception as e:  # 👈 修正：與 try 對齊
                print(f"監控錯誤: {e}")
                time.sleep(1)
    
    def run(self):
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.root.mainloop()
        finally:
            self.stop_monitoring()

          
    def on_closing(self):
        self.stop_monitoring()
        self.root.destroy()
    
if __name__ == "__main__":
    print("可自定義提示樣式的螢幕文字監控系統")
    print("=" * 60)
    print("🎨 新增功能:")
    print("1. ✅ 可調整提示顯示時間 (0.5-10秒)")
    print("2. ✅ 可自定義背景和文字顏色")
    print("3. ✅ 可調整字體大小 (8-16)")
    print("4. ✅ 可調整透明度 (0.3-1.0)")
    print("5. ✅ 不同匹配類型使用不同樣式")
    print("6. ✅ 即時預覽功能")
    print("7. ✅ 自動消失的提示框")
    print("\n🎯 預設樣式:")
    print("• 完全匹配: 綠色背景, 3秒顯示")
    print("• 包含匹配: 金色背景, 2.5秒顯示")
    print("• 模糊匹配: 紅色背景, 2秒顯示")
    print("\n📝 使用方法:")
    print("1. 在 '監控設定' 標籤頁設置監控目標")
    print("2. 在 '提示樣式' 標籤頁自定義提示外觀")
    print("3. 使用預覽按鈕測試樣式效果")
    print("4. 開始監控享受個性化提示")
    print("=" * 60)
    
    app = FixedScreenTextMonitor()
    app.run()
