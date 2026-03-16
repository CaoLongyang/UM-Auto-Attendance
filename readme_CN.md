# 🚀 UM Auto Attendance Manager (马来亚大学全自动签到神器)

👉 **[🌍 Click here for English Version](README_EN.md)**

这是一个为马大学生准备的自动化辅助工具。它可以帮你准时、全自动地在 Spectrum 上完成签到，让你不用再担心因为忙碌或打游戏而错过 Attendance。

---

##  选项一：我是普通小白（懒人免安装版）
如果你不喜欢折腾代码环境，只想直接双击运行软件，请看这里：

### 1. 专门的下载位置
👉 **[点击这里下载最新版 EXE 压缩包]** *(注：以后这里会放你的 Release 链接)*
或者，你也可以在当前页面的右侧，找到 **"Releases"** 标签下载 `Auto_Attendance.zip`。

### 2. 如何使用
1. **解压文件**：下载后，**必须**右键点击压缩包，选择“解压到当前文件夹”。（⚠️千万不要在压缩包里直接双击运行！）
2. **打开软件**：进入解压后的文件夹，双击运行 `gui.exe`。
3. **首次登录授权**：点击界面上的 `🔑 Log In Spectrum` 按钮，在弹出的浏览器里手动登录一次你的马大账号，然后关掉浏览器。*(此时会生成一个 `bot_profile` 文件夹，这是你的记忆卡，千万别删)*
4. **添加课表**：填入你的上课时间、课程名和具体的 Spectrum 签到网址，点击 `➕ Add to Schedule`。
5. **一键挂机**：点击最下方的 `🚀 Save & Launch`。你可以把软件最小化，到了时间它会自动帮你点击 Present 并保存日志！

---

## 💻 选项二：我是开发者（代码环境部署教程）
如果你想研究源码，或者想自己在电脑上配置 Python 环境来跑代码，请严格按照以下步骤部署：

### 1. 基础环境准备
- **安装 Python**：请前往 Python 官网下载并安装（推荐 3.10 或 3.11）。⚠️ **关键**：安装界面的第一步务必勾选 `Add Python.exe to PATH`。
- **确认浏览器**：本程序底层依赖 Windows 系统自带的 Microsoft Edge 浏览器。

### 2. 获取源代码
在你的电脑桌面上打开终端（CMD 或 PowerShell），输入：
```bash
git clone [https://github.com/CaoLongyang/Auto_Attendance.git](https://github.com/CaoLongyang/Auto_Attendance.git)
cd Auto_Attendance
```
*(如果没有安装 Git，可以直接在 GitHub 页面点击绿色的 "Code" 按)
### 3. 安装依赖包 (部署环境)
请在终端里依次输入以下命令来安装必须的工具包：

```Bash
python -m pip install --upgrade pip
python -m pip install flet selenium
```
### 4. 运行代码
环境部署完成后，直接在终端里输入以下命令启动界面：

```Bash
python gui.py
```

## ⚠️ 避坑必看指南
电脑防睡眠：挂机期间，你的电脑可以息屏，但绝对不能进入“休眠”或“睡眠”模式，否则断网会导致无法签到。

遇到动态密码墙：如果老师临时设置了签到密码，程序会自动暂停并在屏幕正中间弹出红色报警框，提醒你立刻手动干预！

不要乱删文件：软件生成的 config.json 和 bot_profile 是你的课表和登录缓存，删除了就需要重新配置。