from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options 
import time
import ctypes 
import os 

# --- 【武器 1：全自动打卡引擎】 ---
def start_sign_in(target_url):
    edge_options = Options()
    profile_path = os.path.join(os.getcwd(), "bot_profile")
    edge_options.add_argument(f"user-data-dir={profile_path}")
    edge_options.add_experimental_option("detach", True)
    
    driver = webdriver.Edge(options=edge_options)
    
    try:
        # 1. Login to Spectrum
        driver.get("https://spectrum.um.edu.my")
        time.sleep(3)
        print("[*] Automatically clicking 'Log in'...")
        driver.find_element(By.LINK_TEXT, "Log in").click()

        # 2. Monitor login status
        print("[*] Checking login status... Waiting for redirection...")
        for _ in range(60):
            if "login" not in driver.current_url.lower():
                print("[+] Login success detected!")
                break
            time.sleep(1)

        # 3. Force navigate to the specific course attendance page
        print(f"[*] Navigating to specific classroom: {target_url}")
        driver.get(target_url)
        time.sleep(5) 

        # --- [Core: The 3-Step Sign-in Combo] ---
        print("[*] Searching and clicking 'Submit attendance'...")
        driver.find_element(By.LINK_TEXT, "Submit attendance").click()
        time.sleep(3)

        print("[*] Attempting to select 'Present'...")
        present_option = driver.find_element(By.XPATH, "//span[contains(text(), 'Present')]")
        present_option.click()
        time.sleep(1)

        print("[*] Clicking save to complete sign-in!")
        driver.find_element(By.ID, "id_submitbutton").click()

        print("[*] Sign-in actions executed.")

        # --- [Verification Logic] ---
        print("[*] Waiting for page to refresh, verifying sign-in result...")
        time.sleep(3) 
        
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        
        if "you must enter the session password" in page_text or "password required" in page_text:
            print("🚨 Critical Block: Password wall encountered!")
            error_message = "⚠️ Alert: Password required for attendance!\n\nThe lecturer has set a dynamic password for this session.\nPlease manually open your browser and enter the password immediately to avoid being marked absent!"
            ctypes.windll.user32.MessageBoxW(0, error_message, "UM Auto Attendance - Manual Intervention Required", 0 | 16)
            return False 

        elif "your attendance in this session has been recorded" in page_text or "self-recorded" in page_text:
            print("🎉 System Confirmed: Success banner detected. Attendance is 100% recorded!")
            return True 
            
        else:
            print("⚠️ Warning: Button clicked, but no success banner appeared. Preparing for the next retry...")
            return False

    except Exception as e:
        print(f"[-] Unable to execute sign-in actions:\n{e}")
        return False
        
    finally:
        print("[*] Task finished. Browser will stay open for your review.")


# --- 【武器 2：手动提前登录工具】 ---
def manual_login():
    edge_options = Options()
    profile_path = os.path.join(os.getcwd(), "bot_profile")
    edge_options.add_argument(f"user-data-dir={profile_path}")
    
    # 保持浏览器常亮，留出足够的时间让你慢慢输密码
    edge_options.add_experimental_option("detach", True)
    
    try:
        print("[*] Opening browser for manual pre-login...")
        driver = webdriver.Edge(options=edge_options)
        driver.get("https://spectrum.um.edu.my")
        print("[*] Please log in manually on the popped-up browser. You can close it once logged in.")
    except Exception as e:
        print(f"[-] Error opening browser for manual login:\n{e}")