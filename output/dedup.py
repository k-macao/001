#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔍 内容去重合并模块 · 70% 相似度阈值

目标：
- 检测各栏目内容的重复度，相似度 ≥70% 时合并
- 避免同一新闻在多个栏目重复展示，提升阅读体验
- 保留最完整、最新的版本，合并来源信息

设计：
- 使用多种相似度算法：Jaccard、SequenceMatcher、关键词重叠
- 对标题、正文、摘要分别计算相似度
- 相似度 ≥70% 时视为重复，执行合并策略
- 合并时保留最新时间、最多来源、完整链接
"""

import re
import math
from difflib import SequenceMatcher
from typing import List, Dict, Tuple, Set
from collections import Counter


def _normalize_text(text: str) -> str:
    """标准化文本：去空格、转小写、去标点"""
    if not text:
        return ""
    # 去 HTML 标签
    text = re.sub(r"<[^>]+>", " ", text)
    # 去特殊符号，保留中文、英文、数字
    text = re.sub(r"[^\w\u4e00-\u9fff]", " ", text)
    # 合并空格，转小写
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _tokenize(text: str) -> Set[str]:
    """分词：按空格和字符分割，支持中文"""
    norm = _normalize_text(text)
    if not norm:
        return set()
    
    tokens = set()
    # 英文按空格分词
    for word in norm.split():
        if len(word) >= 2:
            tokens.add(word)
        # 中文按字符 2-gram
        if any('\u4e00' <= c <= '\u9fff' for c in word):
            # 中文 2-gram
            for i in range(len(word) - 1):
                tokens.add(word[i:i+2])
    
    return tokens


def jaccard_similarity(text1: str, text2: str) -> float:
    """Jaccard 相似度：交集/并集"""
    tokens1 = _tokenize(text1)
    tokens2 = _tokenize(text2)
    
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    
    return intersection / union if union > 0 else 0.0


def sequence_similarity(text1: str, text2: str) -> float:
    """SequenceMatcher 相似度"""
    norm1 = _normalize_text(text1)
    norm2 = _normalize_text(text2)
    
    if not norm1 and not norm2:
        return 1.0
    if not norm1 or not norm2:
        return 0.0
    
    return SequenceMatcher(None, norm1, norm2).ratio()


def keyword_overlap(text1: str, text2: str) -> float:
    """关键词重叠度：基于重要词汇"""
    # 提取关键词（长度 ≥2 的词）
    tokens1 = _tokenize(text1)
    tokens2 = _tokenize(text2)
    
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    
    # 计算重叠
    overlap = len(tokens1 & tokens2)
    min_len = min(len(tokens1), len(tokens2))
    
    return overlap / min_len if min_len > 0 else 0.0


def combined_similarity(text1: str, text2: str, weights=(0.4, 0.4, 0.2)) -> float:
    """
    综合相似度：加权平均
    
    weights: (jaccard, sequence, keyword) 的权重
    """
    if not text1 or not text2:
        return 0.0
    
    # 快速检查：完全相同
    if text1.strip() == text2.strip():
        return 1.0
    
    # 快速检查：一个包含另一个且长度接近
    norm1 = _normalize_text(text1)
    norm2 = _normalize_text(text2)
    if norm1 in norm2 or norm2 in norm1:
        len_ratio = min(len(norm1), len(norm2)) / max(len(norm1), len(norm2))
        if len_ratio > 0.8:
            return 0.9
    
    jaccard = jaccard_similarity(text1, text2)
    seq = sequence_similarity(text1, text2)
    keyword = keyword_overlap(text1, text2)
    
    return weights[0] * jaccard + weights[1] * seq + weights[2] * keyword


def is_duplicate(text1: str, text2: str, threshold: float = 0.7) -> bool:
    """判断是否重复（相似度 ≥ 阈值）"""
    return combined_similarity(text1, text2) >= threshold


def find_duplicates(items: List[Dict], threshold: float = 0.7, key: str = "title") -> List[List[int]]:
    """
    在列表中查找重复项
    
    参数:
        items: 字典列表
        threshold: 相似度阈值
        key: 用于比较的键
    
    返回:
        重复组列表，每组是索引列表，如 [[0, 2], [1, 3, 5]]
    """
    if not items:
        return []
    
    n = len(items)
    visited = [False] * n
    groups = []
    
    for i in range(n):
        if visited[i]:
            continue
        
        group = [i]
        visited[i] = True
        
        for j in range(i + 1, n):
            if visited[j]:
                continue
            
            text1 = str(items[i].get(key, ""))
            text2 = str(items[j].get(key, ""))
            
            if is_duplicate(text1, text2, threshold):
                group.append(j)
                visited[j] = True
        
        if len(group) > 1:
            groups.append(group)
    
    return groups


def merge_similar_items(items: List[Dict], threshold: float = 0.7, key: str = "title") -> Tuple[List[Dict], int]:
    """
    合并相似项
    
    策略：
    - 每组重复项保留最新的、来源最多的、内容最完整的
    - 合并来源信息和链接
    - 记录合并数量
    
    返回:
        (去重后列表, 合并数量)
    """
    if not items:
        return items, 0
    
    groups = find_duplicates(items, threshold, key)
    
    if not groups:
        return items, 0
    
    # 标记要删除的索引
    to_remove = set()
    merged_count = 0
    
    for group in groups:
        # 组内按质量排序：时间最新 > 内容最长 > 来源最多
        def quality_score(idx):
            item = items[idx]
            score = 0
            # 时间：有发布时间的加分
            if item.get("published_cst") and item["published_cst"] != "—":
                score += 10
            if item.get("is_today"):
                score += 5
            # 内容长度
            score += len(str(item.get(key, ""))) / 100
            # 有链接的加分
            if item.get("url"):
                score += 3
            # 有来源的加分
            if item.get("source"):
                score += 1
            return score
        
        sorted_group = sorted(group, key=quality_score, reverse=True)
        keeper = sorted_group[0]
        duplicates = sorted_group[1:]
        
        # 合并来源信息到 keeper
        keeper_item = items[keeper]
        all_sources = set()
        all_urls = []
        
        for idx in group:
            item = items[idx]
            if item.get("source"):
                all_sources.add(item["source"])
            if item.get("url") and item["url"] not in all_urls:
                all_urls.append(item["url"])
        
        # 更新 keeper 的来源信息
        if all_sources:
            original_source = keeper_item.get("source", "")
            merged_sources = "、".join(sorted(all_sources))
            if original_source and original_source not in merged_sources:
                merged_sources = f"{original_source} + {merged_sources}"
            keeper_item["_merged_sources"] = merged_sources
            keeper_item["_duplicate_count"] = len(group) - 1
        
        if all_urls and len(all_urls) > 1:
            keeper_item["_merged_urls"] = all_urls
        
        # 标记重复项为删除
        for idx in duplicates:
            to_remove.add(idx)
        
        merged_count += len(duplicates)
    
    # 生成去重后列表
    deduped = [item for idx, item in enumerate(items) if idx not in to_remove]
    
    return deduped, merged_count


def dedup_across_sections(data: Dict, threshold: float = 0.7) -> Dict:
    """
    跨栏目去重
    
    检查所有新闻类栏目的标题，跨栏目合并相似内容
    
    返回:
    {
        "total_before": 去重前总数,
        "total_after": 去重后总数,
        "merged": 合并数,
        "details": {栏目: 合并数},
        "data": 去重后数据
    }
    """
    # 需要去重的栏目
    news_sections = [
        "全球头条",
        "东财快讯",
        "港股名家频道",
        "美联储趋势",
        "地缘政治趋势",
        "港股新闻源头",
        "全网新闻源头（36家）",
        "内地财经媒体源头",       # 2026-10-12：18 家内地财经媒体（headlines 列表）
        "内地财经媒体（18家）",
    ]
    
    # 收集所有标题
    all_items = []
    section_map = {}  # 索引 -> (栏目, 原索引)
    
    for section in news_sections:
        src = data.get(section, {})
        if not isinstance(src, dict):
            continue
        
        # 不同栏目数据结构不同
        if section == "港股名家频道":
            for ch in src.get("channels", []):
                for video in ch.get("videos", []):
                    idx = len(all_items)
                    all_items.append({
                        "title": video.get("title", ""),
                        "source": ch.get("name", ""),
                        "url": video.get("url", ""),
                        "section": section,
                        "_original": video,
                        "_channel": ch,
                    })
                    section_map[idx] = (section, len(all_items) - 1)
        else:
            headlines = src.get("headlines", []) or src.get("items", [])
            for item in headlines:
                if not isinstance(item, dict):
                    continue
                idx = len(all_items)
                all_items.append({
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                    "section": section,
                    "_original": item,
                })
                section_map[idx] = (section, len(all_items) - 1)
    
    total_before = len(all_items)
    
    if total_before < 2:
        return {
            "total_before": total_before,
            "total_after": total_before,
            "merged": 0,
            "details": {},
            "data": data,
        }
    
    # 跨栏目去重
    deduped, merged = merge_similar_items(all_items, threshold, key="title")
    
    # 如果没有合并，直接返回
    if merged == 0:
        return {
            "total_before": total_before,
            "total_after": total_before,
            "merged": 0,
            "details": {},
            "data": data,
        }
    
    # 重建数据：需要把去重后的结果写回各栏目
    # 简化：只在总结中记录合并数，不实际修改各栏目（避免复杂的数据结构重建）
    # 实际去重在渲染层处理，这里只做检测和统计
    
    # 统计各栏目合并情况
    details = {}
    # 通过比较去重前后的 section 分布来统计
    before_sections = Counter(item["section"] for item in all_items)
    after_sections = Counter(item["section"] for item in deduped)
    
    for section in news_sections:
        before = before_sections.get(section, 0)
        after = after_sections.get(section, 0)
        if before > after:
            details[section] = before - after
    
    return {
        "total_before": total_before,
        "total_after": len(deduped),
        "merged": merged,
        "details": details,
        "data": data,  # 暂不修改原数据，合并在渲染层处理
        "deduped_items": deduped,
    }


def get_dedup_summary(dedup_result: Dict) -> str:
    """获取去重总结文本"""
    if dedup_result["merged"] == 0:
        return "未发现重复内容（相似度阈值 70%）"
    
    lines = [
        f"去重合并：{dedup_result['total_before']} 条 → {dedup_result['total_after']} 条（合并 {dedup_result['merged']} 条重复）"
    ]
    
    if dedup_result["details"]:
        detail_str = "、".join(f"{sec} {cnt} 条" for sec, cnt in dedup_result["details"].items())
        lines.append(f"各栏目合并：{detail_str}")
    
    return "；".join(lines)
