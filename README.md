# CatKang's Blog

技术博客，主要涵盖数据库、分布式系统、存储引擎等主题。

**在线访问**: https://catkang.github.io

---

## 📝 关于博客

### 内容方向

本博客专注于分布式系统和数据库内核技术，包括：

- **数据库理论**：事务、并发控制、故障恢复、存储引擎
- **分布式系统**：一致性协议、分布式事务、数据复制
- **源码解析**：LevelDB、InnoDB、Zeppelin 等开源项目
- **工程实践**：云原生数据库、NewSQL、性能优化

### 文章分类

- **[数据库](https://catkang.github.io/categories.html#数据库)**：故障恢复、事务隔离、并发控制、NewSQL、B+树、跨地域等
- **[源码解析 - InnoDB](https://catkang.github.io/categories.html#庖丁解InnoDB)**：REDO LOG、Undo LOG、B+Tree、Buffer Pool、锁机制
- **[源码解析 - LevelDB](https://catkang.github.io/categories.html#庖丁解LevelDB)**：概览、数据存储、版本控制、Iterator
- **[存储系统](https://catkang.github.io/categories.html#存储)**：Zeppelin、Haystack、Pika、Redis Cluster、CloudJump 等
- **[一致性协议](https://catkang.github.io/categories.html#一致性)**：Raft、Paxos、ZooKeeper、Chubby 等

### 写作风格

- 深入原理，从设计目标出发解释实现细节
- 结合源码，理论与实践并重
- 配图丰富，一图胜千言
- 系列文章，由浅入深系统讲解

### 订阅更新

- RSS Feed: https://catkang.github.io/feed.xml
- GitHub: 关注 [CatKang](https://github.com/CatKang) 获取更新通知

---

## 🤖 CatKang 博客助手 (AI Agent Skill)

本博客提供 AI Agent Skill，支持通过 AI 编程助手（Claude Code、Kimi Code 等）快速检索和问答博客内容。

**[→ 查看 Skill 详细文档](_agents/skills/blog-memories/README.md)**

### 支持的 AI 编程助手

| 工具 | 状态 |
|------|------|
| **Claude Code** | ✅ 已支持 |
| **Kimi Code** | ✅ 已支持 |

### 快速体验

安装后，在 AI 助手中直接提问：

```
"CatKang 的博客中关于故障恢复的文章有哪些？"

"CatKang 怎么理解数据库事务隔离？"

"CatKang 写的 LevelDB 系列有哪些？"

"CatKang 关于 Raft 的文章"
```

安装方法：

```bash
git clone https://github.com/CatKang/catkang.github.io.git
cp -r catkang.github.io/_agents/skills/blog-memories \
  ~/.claude/skills/blog-memories
```

[![Update Skill Index](https://github.com/CatKang/catkang.github.io/actions/workflows/update-skill.yml/badge.svg)](https://github.com/CatKang/catkang.github.io/actions)

---

## 👤 关于作者

- **Name**: Kang Wang (CatKang)
- **Email**: beijingwangkang@hotmail.com
- **GitHub**: [@CatKang](https://github.com/CatKang)
- **Focus**: 数据库内核、分布式系统

欢迎通过 [Issues](https://github.com/CatKang/catkang.github.io/issues) 或邮件交流技术问题。

---

## 📄 License

[MIT License](LICENSE.txt)

转载请注明出处。
