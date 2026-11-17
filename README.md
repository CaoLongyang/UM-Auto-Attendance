# 🚀 UM Auto Attendance Manager (University of Malaya)

👉 **[🌏 点击这里查看中文版说明书](readme_CN.md)**

This is an automated assistant tool exclusively designed for University of Malaya (UM) students. It helps you complete your attendance sign-in on Spectrum automatically and punctually, ensuring you never miss a check-in while you are busy.

### ✨ What's new in v2.1
- **English / 中文 UI** — one click on the `EN` / `中文` button in the top bar switches the whole interface *and* every log line. Your choice is remembered in `config.json`.
- **Exact-time scheduling** — the engine no longer wakes up every 10 seconds to scan the timetable. It works out the next class time, sleeps until that second, and fires. Nothing runs in between.
- **Sleep handling** — while the engine is on it asks Windows not to idle-sleep. If the machine does sleep anyway (lid closed, manual sleep), it notices within ~30 seconds of waking, signs in right away when the class is still open, and writes a clear log line when a whole slot was slept through.
- **Standalone .exe** — `AutoAttendance.exe` is attached to the release, no Python install needed.

### ✨ What's new in v2.0
- **Automatic timetable sync** — paste your Spectrum token once, click `🔄 自动同步课表`, and the app fills in every class (weekday, start/end time, course name, URL) by itself. It also filters out attendance activities that belong to other OCC groups.
- **Session-accurate sign-in** — the bot now picks *today's* row on the attendance page instead of the first `Submit attendance` link, and no longer mistakes a past "Self-recorded" row for today's sign-in.
- **Much more stable browser** — one reusable Edge window, four launch modes with automatic fallback (compatibility mode first), and a fix for Edge's `tab crashed` / `cannot create temp dir` errors.
- **Diagnosable** — every step is written to `logs/`, so a failed sign-in now tells you exactly why.

---

## Option 1: Quick Start
If you don't want to mess with coding environments, grab the standalone build from the Releases page.

### 1. Download
[![Download v2.1](https://img.shields.io/badge/Download-v2.1-blue?style=for-the-badge&logo=github)](https://github.com/CaoLongyang/UM-Auto-Attendance/releases/latest)

> **v2.1 ships `AutoAttendance.exe`** — download it from the Releases page and run it directly. Nothing else to install.
> (Source users: install Python 3.10+, `pip install flet selenium`, then double-click `start.bat` — details in Option 2.)

>**Note**: If the button above doesn't work, please go to the [Releases Page](https://github.com/CaoLongyang/UM-Auto-Attendance/releases) and download manually.


### 2. How to Use
1. **Extract Files**: After downloading, you **MUST** right-click the zip file and select "Extract to current folder". (⚠️ Do not run the program directly from inside the zip file!)
2. **Launch**: Open the extracted folder and double-click `AutoAttendance.exe` (standalone build) or `start.bat` (from source). The first launch takes a few seconds while the bundle unpacks itself.
3. **Pick your language**: the top bar has a `EN` / `中文` button — one click switches the whole UI and every log line, and the choice is remembered.
4. **First-time Login**: Click the `🔑 Log In Spectrum` button. Log in to your UM account manually in the pop-up browser, then close it. *(A `bot_profile` folder will be created to store your session; do not delete it!)*
5. **Sync Your Timetable (recommended)**: Paste your Spectrum token into the token box and click `🔄 自动同步课表`. The app reads every Attendance activity that is visible to **you** and fills in the weekday, start/end time, course name and URL automatically. From then on it re-syncs itself on startup (at most once every 6 hours), so new classes show up without any typing.
6. **One-click Standby**: Click the blue `🚀 启动自动签到` button. The log immediately tells you when the next sign-in is due; the engine sleeps until that second instead of polling. You can minimize the app.

> Manual adding still works: use the `手动添加` card if you want to override a time or add something the sync cannot see. Anything you delete from the synced list is remembered and will not come back.

#### Where do I get the **token**?
1. Log in to Spectrum in your browser.
2. Open <https://spectrum.um.edu.my/user/managetoken.php>.
3. Click **Create token**, choose **Moodle mobile web service**, then copy the token.
4. Paste it into the app once — it is stored in `token.txt` next to the program and loaded automatically next time.

If you already use `att.py`, simply copy its `token.txt` into this folder.

#### How do I find a **URL** for manual adding?

1. **Open Course**: Go to your course on Spectrum.
2. **Click Attendance**: Click the Attendance activity link.
3. **Copy URL**: Copy the address from your browser (Ensure it contains `mod/attendance`).
---

## 💻 Option 2: For Developers (Environment Setup)
If you want to study the source code or run the Python script natively, follow these deployment steps:

### 1. Prerequisites
- **Python**: Install Python (3.10 or 3.11 recommended). ⚠️ **CRITICAL**: Make sure to check `Add Python.exe to PATH` during installation.
- **Browser**: This program relies on the built-in Microsoft Edge browser on Windows.

### 2. Clone the Repository
Open your terminal (CMD or PowerShell) and run:
```bash
git clone https://github.com/CaoLongyang/UM-Auto-Attendance.git
cd UM-Auto-Attendance
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

### 5. Try the sync from the command line (optional)
Put your token in `token.txt`, then:
```Bash
python spectrum_sync.py          # prints every weekly slot it derived
python spectrum_sync.py --json   # machine-readable output
```
This is the same code path the `🔄 自动同步课表` button uses, handy for debugging.

## ⚠️ Troubleshooting & Must-Read Guide
Sleep: while the engine is running it asks Windows not to idle-sleep, so you can just leave the laptop on — the screen is allowed to turn off. Closing the lid or choosing Sleep manually still suspends the machine (no app can override that system setting). When it wakes up, the engine notices within ~30 seconds, signs in immediately if the class is still open, and writes a clear `⚠️ missed ...` line if the whole slot was slept through.

Password-protected Attendance: If a lecturer sets a temporary password, the bot will pause and show a red warning box to alert you for manual intervention!

Do Not Delete Files: The generated config.json, token.txt and bot_profile are crucial; deleting them will require you to re-configure the app.

Where do the times come from: the sync reads the calendar entries that the Attendance plugin creates for every session, then merges them into a weekly slot (same weekday + same start time). A once-off session (a make-up class, a briefing) is ignored unless it is the only session of that activity, and slots that are already over are dropped — so the bot will not wake up at odd hours.

Wrong-OCC filtering: teachers often forget to restrict attendance activities by group, so every OCC (1, 2, 4, ...) is visible to you. The sync reads your group in each course (`core_group_get_course_user_groups`, e.g. GROUP 6) and skips activities whose name contains a single OCC number that is not yours. Activities with no OCC in the name, or with several OCC numbers listed at once, are kept — better one extra card you can delete than a missed class.

Page Persistence: After signing in, the browser window will stay open until you manually close it, allowing you to verify the result at any time.

💡 Developer: Cao Longyang
