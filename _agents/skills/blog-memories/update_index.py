#!/usr/bin/env python3
"""
从本地博客文件生成索引
用于博客仓库内嵌 Skill
"""

import json
import re
from pathlib import Path
from datetime import datetime

def parse_frontmatter(content):
    """解析 Markdown frontmatter"""
    if not content.startswith('---'):
        return {}, content
    
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content
    
    fm_text = parts[1].strip()
    body = parts[2].strip()
    
    fm = {}
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('#'):
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip().strip('"\'')
            fm[key] = value
    
    return fm, body

def extract_summary(body, max_length=200):
    """提取摘要"""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', body)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = ' '.join(text.split())
    
    if len(text) > max_length:
        return text[:max_length] + '...'
    return text

def build_index():
    """构建索引"""
    blog_root = Path(__file__).parent.parent.parent.parent  # 回到博客根目录
    posts_dir = blog_root / '_posts'
    
    index = {
        'blog_url': 'https://catkang.github.io',
        'last_updated': datetime.now().isoformat(),
        'total': 0,
        'categories': {},
        'posts': []
    }
    
    for md_file in posts_dir.rglob('*.md'):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            fm, body = parse_frontmatter(content)
            if not fm.get('title'):
                continue
            
            # 从文件名提取日期
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', md_file.name)
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""
            
            # 构建 URL
            slug = md_file.stem.replace(f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}-", "") if date_match else md_file.stem
            url = f"https://catkang.github.io/{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}/{slug}.html" if date_match else ""
            
            post_info = {
                'title': fm.get('title', ''),
                'url': url,
                'date': date_str,
                'category': fm.get('category', '未分类'),
                'tags': [t.strip() for t in fm.get('tags', '').strip('[]').split(',') if t.strip()],
                'summary': extract_summary(body)
            }
            
            index['posts'].append(post_info)
            index['total'] += 1
            
            # 分类
            cat = post_info['category']
            if cat not in index['categories']:
                index['categories'][cat] = []
            index['categories'][cat].append(post_info)
            
        except Exception as e:
            print(f"Error: {md_file} - {e}")
    
    # 排序
    index['posts'].sort(key=lambda x: x['date'], reverse=True)
    
    return index

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='index.json')
    args = parser.parse_args()
    
    print("📝 生成博客索引...")
    index = build_index()
    
    output_path = Path(__file__).parent / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 索引已保存: {output_path}")
    print(f"📊 总计: {index['total']} 篇文章")
    print(f"📂 分类: {list(index['categories'].keys())}")

if __name__ == '__main__':
    main()
