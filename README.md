# UM-Auto-Attendance
An automated attendance tracker for University of Malaya (UM) Spectrum. Features a user-friendly GUI, auto-login, and background scheduling to ensure you never miss a sign-in.

# 🚀 UM Auto Attendance Manager (马来亚大学全自动签到神器)

An automation tool exclusively designed for University of Malaya (UM) students. It helps you automatically and punctually complete your attendance sign-ins on Spectrum.
这是一个为马大学生准备的自动化辅助工具。它可以帮你准时、全自动地在 Spectrum 上完成签到，让你不用再担心因为忙碌而错过 Attendance。

---

## 📥 选项一：普通小白（懒人免安装版）/ Option 1: No Coding Required
如果你不想折腾代码环境，只想直接双击运行软件，请看这里 (For general users who just want to run the app):

### 1. 下载位置 / Download
👉 **[点击这里下载最新版 EXE 压缩包 / Click Here to Download]** *(注意：请在右侧 Releases 页面下载最新的 Auto_Attendance.zip)*

### 2. 如何使用 / How to Use
1. **解压文件 (Unzip)**：下载后，**必须**右键点击压缩包，选择“解压到当前文件夹”。（⚠️千万不要在压缩包里直接双击运行！）
2. **打开软件 (Launch)**：进入解压后的文件夹，找到 `gui.exe`，双击打开。
3. **首次登录授权 (First-time Login)**：点击界面上的 `🔑 Log In Spectrum` 按钮，在弹出的浏览器里手动登录一次你的马大账号，然后关掉浏览器。*(此时会生成一个 `bot_profile` 文件夹，这是你的记忆卡，千万别删！)*
4. **添加课表 (Add Schedule)**：填入你的上课时间、课程名和具体的 Spectrum 签到网址，点击 `➕ Add to Schedule`。
5. **一键挂机 (Auto-Pilot)**：点击最下方的 `🚀 Save & Launch`。你可以把软件最小化，到了时间它会自动帮你点击 Present 并保存！

---

## 💻 选项二：开发者（代码环境部署教程）/ Option 2: For Developers
如果你想研究源码，或者想自己在电脑上跑代码，请严格按照以下步骤部署 (Deployment steps for source code):

### 1. 基础环境准备 / Prerequisites
- **安装 Python**：请前往 Python 官网下载并安装 Python（推荐 3.10 或 3.11）。⚠️ **关键步骤**：安装时务必勾选 `Add Python.exe to PATH`。
- **确认浏览器**：本程序底层依赖 Windows 系统自带的 Microsoft Edge 浏览器。

### 2. 获取源代码 / Clone the Repository
在你的电脑桌面上打开终端（CMD 或 PowerShell），输入以下命令：
`git clone https://github.com/你的GitHub名字/Auto_Attendance.git`
`cd Auto_Attendance`

### 3. 安装依赖包 / Install Dependencies
请在终端里依次输入以下命令来安装必须的工具：
`python -m pip install --upgrade pip`
`python -m pip install flet selenium`

### 4. 运行代码 / Run
环境部署完成后，直接输入以下命令启动程序：
`python gui.py`

### 5. （进阶）自己打包 / Build the EXE
请使用 Flet 官方打包命令：
`python -m flet pack gui.py`

---

## ⚠️ 避坑必看指南 / Troubleshooting
1. **电脑防睡眠**：挂机期间，电脑可以息屏，但**绝对不能**进入“休眠/Sleep”模式，否则网络断开会无法签到。
2. **遇到动态密码墙**：如果老师设置了随机密码，程序会自动暂停并弹出红色报警框，提醒你立刻手动输入密码！
3. **不要乱删文件**：软件运行后生成的 `config.json` 和 `bot_profile` 是你的课表和登录缓存，删除了就需要重新配置。

💡 **Developer**: Cao Longyang
