# 微信朋友圈采集与搜索工具

一个仅适用于 Windows 的本地工具，用于从当前微信账号本来就能查看的好友朋友圈页面中读取内容，并保存到本机 SQLite 数据库以便搜索和导出。

项目通过 Windows UI Automation、窗口截图和 OCR 工作，不接入微信协议、不注入微信进程，也不会把采集数据上传到服务器。

## 重要提醒

- 微信用户协议可能限制自动化操作。使用本项目所产生的账号限制或其他风险由使用者自行承担。
- 只能处理你有权查看并有权保存的内容；请尊重他人隐私，不要传播或公开采集结果。
- 遇到“操作频繁”或安全验证时请立即停止，不要尝试绕过限制。
- `data/moments.db` 会包含好友名称和朋友圈正文，切勿提交到 GitHub 或发送给无关人员。

## 下载 EXE（推荐）

在 GitHub 项目的 **Releases** 页面下载 `wxmoments-v1.0.0-windows-x64.zip`，把压缩包完整解压后，双击 `wxmoments.exe`。不需要安装 Python，也没有需要保持开启的黑色命令行窗口。

请不要只把 EXE 单独复制出来：同目录的 `_internal` 文件夹是运行所需组件。程序数据保存在解压目录内的 `data/moments.db`，升级时请先备份 `data` 文件夹。

Windows SmartScreen 或部分杀毒软件可能对未经数字签名的 PyInstaller 程序给出提示。请只从本项目 Releases 下载，并用同名 `.sha256` 文件核对校验值；有疑虑时可按下文从源码运行或自行构建。

## 从源码运行

- Windows 10/11，64 位
- Python 3.10–3.13，64 位（仅源码运行需要）
- 已登录的电脑版微信

### 安装

双击 `setup.bat`，脚本会创建 `.venv` 虚拟环境并安装 `requirements.txt` 中的依赖。

也可以手动执行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### 使用

> 源码版运行期间不要关闭 `run.bat` 打开的黑色窗口，可以将它最小化。EXE 版没有这个窗口。
> 无论使用哪个版本，微信里的朋友圈窗口都需要保持打开，**不要最小化**。

1. 在电脑版微信中打开目标好友的资料页。
2. 进入该好友的朋友圈相册，并保持窗口不要最小化。
3. 双击 `run.bat`。
4. 在程序中输入好友备注名称并开始采集。
5. 可随时停止，已保存的内容不会丢失。

退出时，请先点“停止”并等待采集结束，再关闭工具的图形界面；程序正常退出后，命令行窗口会自动关闭。

如果识别不到窗口，可以执行：

```powershell
.venv\Scripts\python -m wm.probe
```

## 数据与隐私

所有数据默认保存在本机 `data/moments.db`，错误信息保存在 `data/crash.log`。`data/` 已加入 `.gitignore`。更多说明见 [PRIVACY.md](PRIVACY.md)。

## 项目结构

```text
wm/
  collector.py   采集、OCR 和内容切分
  db.py          SQLite 存储、查询和导出
  gui.py         图形界面
  probe.py       微信窗口与 OCR 检测工具
  windows.py     Windows 窗口定位、截图和滚动
requirements.txt
setup.bat
run.bat
build.bat
```

## 构建发布包

先运行 `setup.bat`，再双击 `build.bat`。脚本会生成 `dist/wxmoments-v1.0.0-windows-x64.zip` 和对应的 `.sha256` 校验文件。将这两个文件上传到 GitHub Releases；源码分支中不要提交 `dist/`。

## 已知限制

- 仅支持 Windows。
- 微信升级后窗口结构可能变化，需要相应更新识别逻辑。
- OCR 可能出现错字，搜索结果应回到原微信页面核对。
- 本项目不提供规避验证、限流或访问控制的功能。

## 许可证

项目源码使用 [MIT License](LICENSE)。通过 pip 安装的第三方组件分别适用它们自己的许可证。
