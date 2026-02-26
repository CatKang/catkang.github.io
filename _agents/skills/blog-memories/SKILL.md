---
name: blog-memories
description: CatKang博客助手 - 帮助用户检索和阅读CatKang技术博客(https://catkang.github.io)中的文章。当用户提到"CatKang的博客"、"CatKang的文章"、"CatKang怎么说"、"CatKang写的"、"CatKang关于"等关键词时触发。也当用户询问关于数据库、存储引擎、分布式系统、LevelDB、InnoDB、故障恢复、事务隔离、并发控制、一致性协议、Raft、Paxos等技术话题，且需要参考CatKang博客内容时触发。支持按主题、时间、关键词搜索文章，并展示配图。
---

# CatKang 博客助手

帮助用户检索和阅读 CatKang 技术博客中的文章。博客包含 41 篇技术文章，主要涵盖：
- **数据库**：故障恢复、事务隔离、并发控制、NewSQL、B+树、跨地域等
- **存储**：Zeppelin、Haystack、Pika、Redis Cluster等
- **一致性**：Raft、Paxos、ZooKeeper、Chubby等
- **源码解析**：LevelDB、InnoDB等

## 关键信息

- **博客网址**: https://catkang.github.io
- **RSS Feed**: https://catkang.github.io/feed.xml
- **作者**: CatKang (Kang Wang)
- **文章总数**: 41篇
- **索引文件**: `index.json`
- **更新脚本**: `update_index.py`

## 触发场景

用户可能会这样提问：

- "CatKang 的博客中关于故障恢复的文章"
- "CatKang 怎么理解数据库事务隔离"
- "CatKang 写的 LevelDB 系列"
- "CatKang 关于 Raft 的文章"
- "在 CatKang 博客中搜索 B+树"
- "CatKang 怎么说数据库跨地域"

## 核心能力

### 1. 文章检索

使用预构建的索引文件快速搜索：

```python
import json

# 加载索引
with open('index.json', 'r') as f:
    index = json.load(f)

# 搜索文章（按标题、分类、标签、摘要匹配）
results = [p for p in index['posts'] if '关键词' in p['title']]
```

### 2. 获取文章完整内容

直接从网站获取单篇文章：
```bash
curl -sL "https://catkang.github.io/2019/01/16/crash-recovery.html"
```

或使用 FetchURL 工具：
```
FetchURL: https://catkang.github.io/2019/01/16/crash-recovery.html
```

### 3. 配图路径

文章配图位于 `http://catkang.github.io/assets/img/` 目录下：
- 文章 URL: `https://catkang.github.io/2019/01/16/crash-recovery.html`
- 配图目录: `http://catkang.github.io/assets/img/crash_recovery/`

## 检索流程

当用户询问 CatKang 博客相关内容时：

1. **理解意图**：确认用户想检索的主题、时间范围或关键词
2. **加载索引**：读取 `index.json`
3. **搜索匹配**：根据关键词匹配文章（标题权重最高）
4. **获取内容**：如果需要详细信息，使用 FetchURL 获取完整文章内容
5. **展示配图**：提及相关配图的位置
6. **总结要点**：提炼文章核心观点和关键信息

## 常见检索场景

**按主题检索**：
- "CatKang 的博客中关于故障恢复的文章" → 返回7篇相关文章
- "CatKang 写的 LevelDB 系列" → 返回4篇LevelDB系列
- "CatKang 关于 Raft 的文章" → 返回2篇Raft相关

**按技术关键词**：
- "CatKang 怎么理解 MVCC"
- "CatKang 对数据库跨地域的看法"
- "CatKang 博客中的 B+树文章"

**探索性查询**：
- "CatKang 最早写的文章"
- "CatKang 2020年写的文章"
- "CatKang 博客中有哪些存储相关的"

## 文章分类概览

| 分类 | 数量 | 代表文章 |
|------|------|----------|
| 数据库 | 8篇 | 故障恢复、事务隔离、并发控制、NewSQL、B+树、跨地域等 |
| 庖丁解InnoDB | 5篇 | REDO/Undo Log、B+Tree、Buffer Pool、锁机制 |
| 庖丁解LevelDB | 4篇 | 概览、数据存储、版本控制、Iterator |
| 存储 | 9篇 | Zeppelin、Haystack、Pika、Redis Cluster、CloudJump等 |
| 一致性 | 6篇 | Raft、Paxos、ZooKeeper、Chubby等 |

## 注意事项

1. **索引更新**：`index.json` 是预构建的，博客更新后需要重新生成
2. **更新方法**：运行 `update_index.py`
3. **文章URL格式**：`https://catkang.github.io/YYYY/MM/DD/slug.html`
4. **配图URL格式**：`http://catkang.github.io/assets/img/{topic}/image.png`
5. **网络依赖**：获取新文章或完整内容需要网络连接

## 使用示例

**示例1：用户问"CatKang 的博客中关于 WAL 的文章"**
```
1. 加载索引
2. 搜索关键词 "WAL" 或 "Write Ahead Log"
3. 找到《数据库故障恢复机制的前世今生》
4. 如果需要，使用 FetchURL 获取完整内容
5. 总结文章要点，提及配图位置
```

**示例2：用户问"CatKang 怎么理解 LevelDB"**
```
1. 加载索引，查看 "庖丁解LevelDB" 分类
2. 列出4篇文章：
   - 庖丁解LevelDB之概览 (2017-01-07)
   - 庖丁解LevelDB之数据存储 (2017-01-17)
   - 庖丁解LevelDB之版本控制 (2017-02-03)
   - 庖丁解LevelDB之Iterator (2017-02-12)
3. 简要介绍每篇的核心内容
```

**示例3：用户问"CatKang 最早写的文章是什么"**
```
1. 加载索引，按日期排序
2. 找到最早的文章（2015年关于Ceilometer的文章）
3. 读取并总结内容
```
