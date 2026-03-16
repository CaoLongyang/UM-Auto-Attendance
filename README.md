# 🚀 UM Auto Attendance Manager (University of Malaya)

👉 **[🌏 点击这里查看中文版说明书](README_CN.md)**

This is an automated assistant tool exclusively designed for University of Malaya (UM) students. It helps you complete your attendance sign-in on Spectrum automatically and punctually, ensuring you never miss a check-in while you are busy.

---

## Option 1: For General Users (Standalone No-install Version)
If you don't want to mess with coding environments and just want to run the software directly, follow these steps:

### 1. Dedicated Download Location
### 1. Download the App
[![Download v1.0](https://img.shields.io/badge/Download-Attendance_v1.0-blue?style=for-the-badge&logo=github)](https://github.com/CaoLongyang/Auto_Attendance/releases/latest/download/attendance.zip)

**Note**: If the button above doesn't work, please go to the [Releases Page](https://github.com/CaoLongyang/UM-Auto-Attendance/releases) and download manually.
Alternatively, find the `Auto_Attendance.zip` under the **"Releases"** section on the right side of this page.

### 2. How to Use
1. **Extract Files**: After downloading, you **MUST** right-click the zip file and select "Extract to current folder". (⚠️ Do not run the program directly from inside the zip file!)
2. **Launch**: Open the extracted folder and double-click `gui.exe`.
3. **First-time Login**: Click the `🔑 Log In Spectrum` button. Log in to your UM account manually in the pop-up browser, then close it. *(A `bot_profile` folder will be created to store your session; do not delete it!)*
4. **Add Schedule**: Enter your class day, start/end time, course name, and the specific Spectrum attendance URL, then click `➕ Add to Schedule`.
5. 
6. **One-click Standby**: Click the blue `🚀 Save & Launch` button. You can minimize the app; it will automatically click "Present" and save logs when the time comes!

---

## 💻 Option 2: For Developers (Environment Setup)
If you want to study the source code or run the Python script natively, follow these deployment steps:

### 1. Prerequisites
- **Python**: Install Python (3.10 or 3.11 recommended). ⚠️ **CRITICAL**: Make sure to check `Add Python.exe to PATH` during installation.
- **Browser**: This program relies on the built-in Microsoft Edge browser on Windows.

### 2. Clone the Repository
Open your terminal (CMD or PowerShell) and run:
```bash
git clone [https://github.com/CaoLongyang/Auto_Attendance.git](https://github.com/CaoLongyang/Auto_Attendance.git)
cd Auto_Attendance
```
### 3. Install Dependencies
```Bash
python -m pip install --upgrade pip
python -m pip install flet selenium
```
### 4. Run the Application
```Bash
python gui.py
```

## ⚠️ Troubleshooting & Must-Read Guide
Prevent Computer Sleep: Your screen can turn off, but your PC must not enter "Sleep" or "Hibernate" mode, otherwise the network disconnection will cause sign-in failure.

Password-protected Attendance: If a lecturer sets a temporary password, the bot will pause and show a red warning box to alert you for manual intervention!

Do Not Delete Files: The generated config.json and bot_profile are crucial; deleting them will require you to re-configure the app.

💡 Developer: Cao Longyang
