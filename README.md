# XHS Crawler — 小红书内容同步归档工具

一个**个人使用**的小红书创作者内容同步工具。长期追踪选定创作者，自动下载并归档新发布的内容（图片、视频、正文、标签、元数据），即使原帖被删除，归档依然可搜索。

> ⚠️ **这不是大规模爬虫工具。** 设计目标是个人存档，模拟正常用户浏览行为，优先保障账号安全。

## 功能

- **多创作者追踪** — 管理多个创作者，每次同步一个
- **增量同步** — 只下载新笔记，已归档的不重复下载
- **完整归档** — 图片、视频、封面、正文、标签、发布时间、互动数据
- **全文搜索** — SQLite FTS5 引擎，毫秒级搜索 300+ 条笔记
- **统计报告** — 单博主标签画像、发布节奏、爆款分析
- **CDP 模式** — 连接真实 Chrome，反爬抗性最高

## 快速开始

### 1. 安装

```bash
git clone https://github.com/yourname/xhs-crawler.git
cd xhs-crawler
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. 配置

```bash
cp config/config.example.json config/config.json
```

编辑 `config/config.json`，填入你要追踪的创作者：

```json
{
  "creators": [
    {
      "id": "1",
      "name": "创作者昵称",
      "profile_url": "https://www.xiaohongshu.com/user/profile/xxxxx",
      "enabled": true
    }
  ]
}
```

### 3. 启动 Chrome（CDP 模式，推荐）

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=./chrome_profile

# 在打开的 Chrome 中登录 xiaohongshu.com，然后保持窗口开着
```

### 4. 开始同步

```bash
python main.py                    # 同步第一个启用的创作者
python main.py --creator 2        # 同步指定创作者
python main.py --dry-run          # 只看不下载
```

## 命令参考

```bash
# 同步
python main.py [--creator ID] [--dry-run] [--no-cdp]

# 管理
python main.py --add              # 添加创作者
python main.py --remove ID        # 移除创作者（保留归档）
python main.py --list             # 列出所有创作者
python main.py --status           # 数据库概况

# 搜索 & 分析
python main.py --search "关键词"   # 全文搜索
python main.py --report ID        # 单博主统计报告
```

## 归档结构

```
downloads/creator_name/YYYY-MM-DD_noteid_title/
├── metadata.json    # 机器可读：标签、互动数据、发布时间
├── note.txt         # 人类可读：正文内容
├── 01.jpg           # 图片（确定性命名）
├── 02.jpg
└── video.mp4        # 视频（如有）
```

## 项目架构

```
xhs-crawler/
├── main.py              # 入口
├── login_helper.py      # 登录 & 会话管理
├── cdp_helper.py        # Chrome CDP 连接
├── crawler/             # 页面采集
├── downloader/          # 媒体下载
├── database/            # SQLite + FTS5 搜索
├── archive/             # 文件系统归档
├── sync/                # 工作流协调
├── analyzer/            # 统计报告（只读）
└── config/              # 配置模板
```

## 技术栈

Python 3.11+ · Playwright · SQLite + FTS5 · Chrome DevTools Protocol

## 账号安全

- **不自动化登录** — 使用 CDP 连接你日常使用的 Chrome，或扫码登录
- **不自动输入密码**
- **人类行为模拟** — 随机延时、随机滚动步长
- **单创作者每次运行** — 避免多创作者连续请求触发风控

## 开发哲学

本项目 90% 由 [Claude Code](https://claude.ai/code) 辅助完成（vibe coding）。人类负责需求、架构决策和质量把关，AI 负责实现。详见 [DEVLOG.md](DEVLOG.md) 记录了完整的优化演进过程。

## License

MIT
