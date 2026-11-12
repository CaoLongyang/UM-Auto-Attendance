# 🚀 UM Auto Attendance Manager (马来亚大学全自动签到神器)

👉 **[🌍 Click here for English Version](README.md)**

这是一个为马大学生准备的自动化辅助工具。它可以帮你准时、全自动地在 Spectrum 上完成签到，让你不用再担心因为忙碌或打游戏而错过 Attendance。

### ✨ v2.0 更新了什么
- **自动同步课表**：token 粘一次，点一下 `🔄 自动同步课表`，星期、开始/结束时间、课程名、URL 全部自己填好；并且会按你的分组过滤掉别的 OCC 的考勤活动。
- **签对今天的课**：现在会按日期选中「今天这一行」的 `Submit attendance`，不再点页面上的第一个链接，也不会再把历史 session 的 `Self-recorded` 误当成今天已签。
- **浏览器稳定多了**：整晚复用同一个 Edge 窗口；4 组启动参数自动降级（兼容模式优先）；修掉了 Edge 的 `tab crashed` 和 `cannot create temp dir` 报错。
- **能查了**：每一步都会写进 `logs/`，签到失败会直接告诉你原因。

---

##  选项一：快速开始
如果你不喜欢折腾代码环境，可以直接到 Releases 页面下载。

### 1. 下载
[![Download v2.0](https://img.shields.io/badge/Download-v2.0-blue?style=for-the-badge&logo=github)](https://github.com/CaoLongyang/UM-Auto-Attendance/releases/latest)

> **v2.0 目前是源码版**：Windows 的 `gui.exe` 一键包正在重新打包，会另外补到 Release 里。
> 在那之前请用源码运行：装好 Python 3.10+、`pip install flet selenium`，然后双击 `start.bat`（详见选项二）。

> **提示**：如果点击上方按钮没反应，请前往 [Releases 页面](https://github.com/CaoLongyang/UM-Auto-Attendance/releases/latest) 手动下载。

### 2. 如何使用
1. **解压文件**：下载后，**必须**右键点击压缩包，选择“解压到当前文件夹”。（⚠️千万不要在压缩包里直接双击运行！）
2. **打开软件**：进入解压后的文件夹，双击运行 `start.bat`（源码版）或 `gui.exe`（一键包）。
3. **首次登录授权**：点击界面上的 `🔑 Log In Spectrum` 按钮，在弹出的浏览器里手动登录一次你的马大账号，然后关掉浏览器。*(此时会生成一个 `bot_profile` 文件夹，这是你的记忆卡，千万别删)*
4. **自动同步课表（推荐）**：把 Spectrum 的 token 粘到输入框，点 `🔄 自动同步课表`。程序会读取**所有对你可见**的考勤活动，自动填好星期、开始/结束时间、课程名和网址，不用再抄 URL。之后每次启动它都会在后台自动同步一次（最多 6 小时一次），老师新加的活动会自己冒出来。
5. **一键挂机**：点击 `🚀 启动自动签到`。你可以把软件最小化，到了时间它会自动帮你点击 Present 并保存日志！

> 旧的手动添加仍然保留（`手动添加` 卡片），同步漏掉的课可以自己补。同步出来的课如果删掉，程序会记住，下次同步不会再塞回来。

#### 怎么拿到 **token**？
1. 浏览器里登录 Spectrum。
2. 打开 <https://spectrum.um.edu.my/user/managetoken.php>。
3. 点 **Create token**，服务选 **Moodle mobile web service**，复制生成的 token。
4. 粘进软件一次即可——它会保存在程序目录的 `token.txt`，以后自动读取。

如果你已经在用 `att.py`，直接把它旁边的 `token.txt` 复制到本程序目录就行。

#### 手动添加时怎么找签到的 **URL**？
1. **进入课程**：在 Spectrum 找到对应课程。
2. **点击 Attendance**：点击那个带有“小人”图标的 Attendance 链接。
3. **复制地址**：进入显示日期列表的页面后，直接复制浏览器地址栏网址。

特征：链接必须包含 mod/attendance 字样。
---

## 💻 选项二：我是开发者（代码环境部署教程）
如果你想研究源码，或者想自己在电脑上配置 Python 环境来跑代码，请严格按照以下步骤部署：

### 1. 基础环境准备
- **安装 Python**：请前往 Python 官网下载并安装（推荐 3.10 或 3.11）。⚠️ **关键**：安装界面的第一步务必勾选 `Add Python.exe to PATH`。
- **确认浏览器**：本程序底层依赖 Windows 系统自带的 Microsoft Edge 浏览器。

### 2. 获取源代码
在你的电脑桌面上打开终端（CMD 或 PowerShell），输入：
```bash
git clone https://github.com/CaoLongyang/UM-Auto-Attendance.git
cd UM-Auto-Attendance
```
*(如果没有安装 Git，可以直接在 GitHub 页面点击绿色的 "Code" 按钮 → Download ZIP。)*
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

### 5. 不开界面也能测同步（可选）
把 token 放进 `token.txt`，然后：
```Bash
python spectrum_sync.py          # 打印它整理出来的每周课表
python spectrum_sync.py --json   # 输出 JSON
```
和界面里 `🔄 自动同步课表` 走的是同一套代码，排查问题很方便。

## ⚠️ 避坑必看指南
电脑防睡眠：挂机期间，你的电脑可以息屏，但绝对不能进入“休眠”或“睡眠”模式，否则断网会导致无法签到。

遇到动态密码墙：如果老师临时设置了签到密码，程序会自动暂停并在屏幕正中间弹出红色报警框，提醒你立刻手动干预！

不要乱删文件：软件生成的 config.json、token.txt 和 bot_profile 是你的课表、token 和登录缓存，删除了就需要重新配置。

课表时间是怎么来的：考勤插件会给每一次 session 建一条日历，同步时按「同一个活动 + 同一个星期几 + 同一个开始时间」归并成一条每周课表。只出现过一次的补课/讲座会被忽略（除非它就是这个活动唯一的 session），整个时段都已经上完的也不会再加进来，所以机器人不会在奇怪的时间突然醒过来。

不是你的 OCC 会被自动过滤：老师在 Moodle 里经常不设分组限制，于是 OCC 1、2、4…的考勤活动对你全都 visible。程序会用 `core_group_get_course_user_groups` 拿到你在这门课的组号（比如 GROUP 6），再和活动名里的 OCC 编号比对：名字里只有一个 OCC 且不是你的组就跳过。名字里没写 OCC、或者一次列了多个 OCC（比如「OCC 3, 4, 5, 6, 7」）的会保留，宁可多一条让你自己删。

页面留存：签到完成后，浏览器会一直保持开启直到你手动关闭，方便你随时确认是否真的勾选成功。