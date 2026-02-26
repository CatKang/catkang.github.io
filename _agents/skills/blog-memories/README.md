# CatKang 博客助手 (Blog Memories Skill)

AI Agent Skill，用于检索和阅读 CatKang 技术博客的文章。

博客地址: https://catkang.github.io

## 支持的 AI 编程助手

| 工具 | 安装路径 |
|------|----------|
| **Claude Code** | `~/.claude/skills/` |
| **Kimi Code** | `~/.kimi/skills/` |

## 安装

### Claude Code

```bash
git clone https://github.com/CatKang/catkang.github.io.git

# 安装 skill
cp -r catkang.github.io/_agents/skills/blog-memories \
  ~/.claude/skills/blog-memories

# 或使用符号链接（开发模式）
ln -s $(pwd)/catkang.github.io/_agents/skills/blog-memories \
  ~/.claude/skills/blog-memories
```

### Kimi Code

```bash
git clone https://github.com/CatKang/catkang.github.io.git

# 安装 skill
cp -r catkang.github.io/_agents/skills/blog-memories \
  ~/.kimi/skills/blog-memories
```

## 使用

安装后，在 AI 助手中直接提问：

```
"CatKang 的博客中关于故障恢复的文章有哪些？"

"CatKang 怎么理解数据库事务隔离？"

"CatKang 写的 LevelDB 系列有哪些？"

"CatKang 关于 Raft 的文章"

"CatKang 怎么说数据库跨地域"

"在 CatKang 博客中搜索 B+树"
```

## 更新索引

索引通过 GitHub Actions 自动更新。手动更新：

```bash
python _agents/skills/blog-memories/update_index.py
```

## 数据格式

`index.json` 包含：
- `blog_url`: 博客 URL
- `total`: 文章总数
- `posts`: 文章列表（标题、URL、日期、分类、标签、摘要）
- `categories`: 按分类组织的文章

## 目录结构

```
blog-memories/
├── SKILL.md          # Skill 定义
├── index.json        # 文章索引
├── update_index.py   # 索引更新脚本
└── README.md         # 本文件
```
