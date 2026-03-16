import flet as ft
import json
import os
import datetime
import time
import threading 
# 【修改】：把刚写的 manual_login 也拿进来
from sign_in import start_sign_in, manual_login 

def main(page: ft.Page):
    # 1. Basic window configuration
    page.title = "UM Auto Attendance Manager"
    page.theme_mode = ft.ThemeMode.DARK 
    page.window_width = 540  
    page.window_height = 850 
    page.padding = 30
    page.scroll = "adaptive"

    course_list = ft.Column(spacing=10)
    my_schedule = []
    bot_running = False 

    # Console log view configuration
    log_view = ft.ListView(expand=True, spacing=5, height=150, auto_scroll=True)
    log_container = ft.Container(
        content=log_view, border=ft.border.all(1, "grey"),
        border_radius=5, padding=10, visible=False, bgcolor="#1e1e1e" 
    )

    # Helper function to append logs to the UI console
    def write_log(message):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        log_view.controls.append(ft.Text(f"[{t}] {message}", size=12, color="green"))
        page.update()

    # --- [Background Engine: The monitoring thread] ---
    def bot_thread():
        write_log("🤖 Auto Engine Started. Monitoring time...")
        signed_history = []
        
        while bot_running: 
            now = datetime.datetime.now()
            today_weekday = now.weekday()
            current_time_str = now.strftime("%H:%M")
            today_date_str = now.strftime("%Y-%m-%d")

            for course in my_schedule:
                if course["day"] == today_weekday:
                    start_num = int(course["start"].replace(":", ""))
                    end_num = int(course["end"].replace(":", ""))
                    curr_num = int(current_time_str.replace(":", ""))
                    
                    if start_num <= curr_num <= end_num:
                        course_id = f"{today_date_str}_{course['name']}"
                        
                        if course_id not in signed_history:
                            write_log(f"👉 Target found! Time is {current_time_str}.")
                            write_log(f"🚀 Launching browser for {course['name']}...")
                            
                            try:
                                is_success = start_sign_in(course["url"])
                                
                                if is_success:
                                    signed_history.append(course_id)
                                    write_log(f"✅ SUCCESS: {course['name']} sign-in verified!")
                                else:
                                    write_log(f"⚠️ FAILED: {course['name']} unconfirmed. Retrying later...")

                            except Exception as e:
                                write_log(f"❌ Error: {e}")
            
            time.sleep(10) 

    # Template function to generate course UI cards
    def create_course_card(course_data):
        day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun",
                   "0": "Mon", "1": "Tue", "2": "Wed", "3": "Thu", "4": "Fri", "5": "Sat", "6": "Sun"}
        display_day = day_map.get(course_data["day"], "")

        def delete_this_card(e):
            course_list.controls.remove(card) 
            my_schedule.remove(course_data)
            page.update() 

        card = ft.Card(
            content=ft.Container(
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN, 
                    controls=[
                        ft.Column([
                            ft.Text(f"📚 {course_data['name']}", size=18, weight="bold"),
                            ft.Text(f"⏰ {display_day} | {course_data['start']} - {course_data['end']}", color="grey"),
                            ft.Text(f"🔗 {course_data['url']}", size=12, color="blue"),
                        ]),
                        ft.ElevatedButton("❌ Delete", color="red", on_click=delete_this_card)
                    ]
                ),
                padding=15,
            ),
            elevation=5 
        )
        return card

    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                for item in saved_data:
                    my_schedule.append(item)
                    course_list.controls.append(create_course_card(item))
        except Exception as e:
            pass

    def toggle_theme(e):
        if page.theme_mode == ft.ThemeMode.DARK:
            page.theme_mode = ft.ThemeMode.LIGHT
            theme_btn.text = "🌙 Dark Mode" 
        else:
            page.theme_mode = ft.ThemeMode.DARK
            theme_btn.text = "☀️ Light Mode" 
        page.update()

    theme_btn = ft.ElevatedButton("☀️ Light Mode", on_click=toggle_theme)
    page.appbar = ft.AppBar(title=ft.Text("Auto Attendance"), center_title=False, actions=[theme_btn])

    def add_course(e):
        if not day_input.value or not start_time.value or not end_time.value or not name_input.value:
            page.snack_bar = ft.SnackBar(ft.Text("Please fill in all required fields!"), bgcolor="red")
            page.snack_bar.open = True
            page.update()
            return
        
        course_data = {
            "day": int(day_input.value), "start": start_time.value,
            "end": end_time.value, "name": name_input.value, "url": url_input.value
        }
        my_schedule.append(course_data)
        course_list.controls.append(create_course_card(course_data))
        
        start_time.value = ""
        end_time.value = ""
        name_input.value = ""
        url_input.value = ""
        page.update()

    # --- [新增]：响应点击登录按钮的动作 ---
    def handle_login_click(e):
        write_log("Opening browser for manual login...")
        # 召唤刚才写好的单纯开网页的工具
        manual_login()

    # Engine toggle logic (Start/Stop background thread)
    def toggle_engine(e):
        nonlocal bot_running
        if not bot_running:
            # --- 【新增核心】：拦截没登录的冒失鬼 ---
            if not os.path.exists("bot_profile"):
                page.snack_bar = ft.SnackBar(ft.Text("⚠️ ERROR: You must 'Log In Spectrum' first before launching!"), bgcolor="red")
                page.snack_bar.open = True
                page.update()
                return # 发现没登录，直接打断施法，下面的代码不执行了
            
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(my_schedule, f, ensure_ascii=False, indent=4)
            
            bot_running = True
            save_btn.text = "⏹️ Stop Engine"
            save_btn.color = "red"
            log_container.visible = True 
            write_log("Config saved. Preparing engine...")
            
            threading.Thread(target=bot_thread, daemon=True).start()
        else:
            bot_running = False
            save_btn.text = "🚀 Save & Launch"
            save_btn.color = "blue"
            write_log("🛑 Engine Stopped.")
        page.update()

    # UI Components definition
    title = ft.Text("Schedule Configuration", size=28, weight="bold")
    subtitle = ft.Text("Add your classes like a to-do list", color="grey")

    day_input = ft.Dropdown(
        label="Day", width=110, filled=True, border_radius=10,
        options=[ft.dropdown.Option(key=str(i), text=d) for i, d in enumerate(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])]
    )
    start_time = ft.TextField(label="Start (14:00)", width=130, filled=True, border_radius=10)
    end_time = ft.TextField(label="End (14:15)", width=130, filled=True, border_radius=10)
    name_input = ft.TextField(label="Course Name (e.g. WIA1005)", expand=True, filled=True, border_radius=10)
    url_input = ft.TextField(label="Attendance URL", expand=True, filled=True, border_radius=10)

    add_btn = ft.ElevatedButton("➕ Add to Schedule", on_click=add_course, width=200, height=45)
    
    # --- [新增]：前台的独立登录按钮 ---
    pre_login_btn = ft.ElevatedButton("🔑 Log In Spectrum", on_click=handle_login_click, color="white", bgcolor="orange", height=50)
    
    save_btn = ft.FilledButton("🚀 Save & Launch", on_click=toggle_engine, height=50)

    # 把按钮横向排在一起
    top_buttons_row = ft.Row([pre_login_btn, save_btn], alignment=ft.MainAxisAlignment.CENTER)

    # Overall UI layout assembly
    page.add(
        title, subtitle,
        ft.Divider(height=10, color="transparent"), 
        top_buttons_row,  # 【修改】：把两个大按钮放在这里   
        log_container, 
        ft.Divider(height=15),
        ft.Text("Add New Course", size=18, weight="bold"),
        ft.Row([day_input, start_time, end_time]),
        ft.Row([name_input]),
        ft.Row([url_input]),
        ft.Row([add_btn], alignment=ft.MainAxisAlignment.END), 
        ft.Divider(height=15),
        ft.Text("My Pending Classes", size=20, weight="bold"),
        course_list
    )

ft.app(target=main)