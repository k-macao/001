#!/usr/bin/env python3
"""
财经概念映射与利好利空概率模型
集成到内地财经热点榜（【沸腾花蛤】栏目）

功能：
- 概念映射：将新闻标题映射到A股概念板块（新能源、芯片、军工等50+概念）
- 情感分析：利好/利空三级分类，支持否定词和转折词修正
- 概率模型：计算利好概率、利空概率、概念相关性分数

用法：
    from output.finance_analysis import analyze_finance_item, FinanceConceptAnalyzer, FinanceSentimentAnalyzer
    
    result = analyze_finance_item("国务院发布新能源汽车产业发展规划")
    print(result)
"""

import jieba
from typing import Dict, List, Tuple, Optional
from collections import Counter
import re
import math


# ============================================================================
# 概念映射引擎
# ============================================================================

class FinanceConceptAnalyzer:
    """
    财经概念映射分析器
    将新闻标题映射到A股概念板块，支持模糊匹配和层级概念
    """

    def __init__(self):
        # 概念层级结构：大类 -> 子类 -> 关键词
        self.concept_hierarchy = self._build_hierarchy()
        # 概念敏感度权重（0-1，数值越高越敏感）
        self.concept_sensitivity = self._build_sensitivity()
        # 初始化jieba分词
        self._init_jieba()

    def _init_jieba(self):
        """添加财经专有词汇到jieba分词"""
        finance_words = [
            # 宏观经济
            "GDP", "CPI", "PPI", "通胀", "通缩", "经济增长", "工业增加值",
            "社会消费品零售总额", "固定资产投资", "出口", "进口", "外汇储备", "人民币汇率",
            # 货币政策
            "降准", "降息", "加息", "LPR", "MLF", "SLF", "逆回购", "正回购",
            "存款准备金率", "公开市场操作", "流动性", "资金面", "M2", "社会融资规模",
            # 热门概念
            "新能源", "光伏", "风电", "储能", "锂电", "氢能", "新能源汽车", "充电桩",
            "芯片", "半导体", "集成电路", "EDA", "封测", "AI", "大模型", "算力",
            "GPU", "机器人", "数字经济", "大数据", "云计算", "区块链", "Web3",
            "CXO", "创新药", "疫苗", "医疗器械", "基因编辑", "军工", "国防",
            # 市场情绪
            "北向资金", "南向资金", "融资余额", "两融", "IPO", "再融资", "定增",
            "减持", "增持", "回购", "分红", "股权激励", "机构调研",
            # 公司事件
            "业绩预告", "业绩快报", "年报", "季报", "中报", "重组", "并购",
            "股权变动", "高管变动", "停牌", "复牌", "退市", "ST", "*ST"
        ]
        for word in finance_words:
            jieba.add_word(word, freq=1000)

    def _build_hierarchy(self) -> Dict[str, Dict[str, List[str]]]:
        """构建概念分层体系"""
        return {
            "宏观经济": {
                "通胀概念": ["CPI", "PPI", "通胀", "物价上涨", "输入型通胀"],
                "增长概念": ["GDP", "经济增长", "工业增加值", "投资增长"],
                "外贸概念": ["出口", "进口", "贸易顺差", "外贸", "对外贸易"],
                "汇率概念": ["人民币汇率", "汇率改革", "离岸人民币", "在岸人民币"]
            },
            "货币政策": {
                "宽松货币": ["降准", "降息", "LPR下调", "MLF下调", "逆回购", "投放流动性", "宽松"],
                "紧缩货币": ["加息", "LPR上调", "MLF上调", "正回购", "回笼流动性", "紧缩"],
                "流动性指标": ["M2", "社会融资规模", "新增信贷", "资金面", "流动性"]
            },
            "财政政策": {
                "刺激政策": ["减税", "降费", "财政赤字扩大", "专项债", "基建投资", "积极财政"],
                "紧缩政策": ["紧缩财政", "财政赤字缩小", "减少支出"]
            },
            "产业政策": {
                "新兴产业": ["新能源", "人工智能", "生物医药", "芯片", "数字经济", "5G", "6G", "元宇宙"],
                "传统产业": ["地产", "汽车", "钢铁", "煤炭", "石化", "纺织"]
            },
            "热门概念": {
                "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "氢能", "新能源汽车", "充电桩"],
                "芯片半导体": ["芯片", "半导体", "集成电路", "EDA", "封测", "存储芯片", "模拟芯片"],
                "人工智能": ["AI", "人工智能", "大模型", "算力", "GPU", "AI芯片", "机器人"],
                "数字经济": ["数字经济", "大数据", "云计算", "区块链", "Web3", "数字化转型"],
                "生物医药": ["生物医药", "CXO", "创新药", "疫苗", "医疗器械", "基因编辑", "细胞治疗"],
                "军工": ["军工", "国防", "武器装备", "军民融合", "航空航天", "船舶", "电子信息"],
                "消费": ["消费", "零售", "电商", "新消费", "奢侈品", "免税", "直播带货"],
                "地产链": ["地产", "房地产", "房企", "保交楼", "地产融资", "房贷", "按揭"],
                "金融": ["金融", "银行", "券商", "保险", "信托", "金融科技", "数字人民币"],
                "汽车": ["汽车", "新能源汽车", "智能网联", "自动驾驶", "汽车芯片", "动力电池"],
                "资源": ["资源", "煤炭", "石油", "天然气", "有色金属", "稀土", "锂矿"],
                "通信": ["通信", "5G", "6G", "光通信", "卫星通信", "物联网"],
                "计算机": ["计算机", "软件", "信息安全", "数据中心", "工业软件"],
                "电子": ["电子", "消费电子", "半导体", "被动元件", "印刷电路板"],
                "机械": ["机械", "装备制造", "工程机械", "机器人", "自动化"],
                "化工": ["化工", "石化", "新材料", "特种化学品", "化工新材料"],
                "建筑": ["建筑", "基建", "装饰", "建材", "水泥", "玻璃"],
                "传媒": ["传媒", "文化", "游戏", "影视", "出版", "广告"],
                "农业": ["农业", "种业", "畜牧", "水产", "农机", "化肥"],
                "环保": ["环保", "节能", "减排", "碳中和", "碳达峰", "固废处理"],
                "公用事业": ["公用事业", "电力", "燃气", "供水", "供暖", "环卫"],
                "交通运输": ["交通运输", "物流", "航空", "铁路", "公路", "港口", "航运"]
            },
            "市场情绪": {
                "资金流向": ["北向资金", "南向资金", "外资流入", "外资流出", "融资买入", "融资偿还"],
                "融资融券": ["两融", "融资余额", "融券余额"],
                "股本变动": ["新股发行", "IPO", "再融资", "定增", "配股", "可转债"],
                "持股变动": ["减持", "增持", "回购", "股权激励"]
            },
            "监管政策": {
                "反垄断": ["反垄断", "反不正当竞争", "垄断调查"],
                "数据安全": ["数据安全", "网络安全", "个人信息保护"],
                "金融监管": ["金融监管", "影子银行", "P2P", "金融乱象"],
                "行业监管": ["行业整顿", "专项整治", "清理整顿"]
            },
            "公司事件": {
                "财报相关": ["业绩预告", "业绩快报", "年报", "季报", "中报", "净利润", "营业收入"],
                "资本运作": ["重组", "并购", "收购", "出售资产", "资产注入"],
                "股权事件": ["股权变动", "股权转让", "定向增发", "股份回购"],
                "人事变动": ["高管变动", "董事长", "总经理", "财务总监", "独立董事"],
                "交易异常": ["停牌", "复牌", "退市风险", "ST", "*ST", "退市"]
            }
        }

    def _build_sensitivity(self) -> Dict[str, float]:
        """构建概念敏感度权重"""
        return {
            # 高敏感度概念
            "新能源": 0.95, "芯片半导体": 0.92, "人工智能": 0.90, "军工": 0.88,
            "生物医药": 0.85, "数字经济": 0.85,
            # 中等敏感度
            "金融": 0.80, "地产链": 0.75, "汽车": 0.70, "消费": 0.65,
            "资源": 0.70, "通信": 0.60, "计算机": 0.65, "电子": 0.60,
            # 低敏感度
            "机械": 0.55, "化工": 0.55, "建筑": 0.50, "传媒": 0.50,
            "农业": 0.45, "环保": 0.50, "公用事业": 0.40, "交通运输": 0.45
        }

    def extract_concepts(self, text: str) -> Dict[str, float]:
        """
        提取新闻中的概念及相关性分数
        
        Args:
            text: 新闻标题或内容
            
        Returns:
            Dict[str, float]: 概念 -> 相关性分数 (0-1)
        """
        words = jieba.lcut(text)
        words = [w.lower() for w in words if len(w) > 1]
        
        # 概念命中计数
        concept_hits = Counter()
        
        # 遍历概念层级
        for category, sub_categories in self.concept_hierarchy.items():
            for sub_category, keywords in sub_categories.items():
                for keyword in keywords:
                    if keyword in words:
                        # 命中子类别和父类别
                        concept_hits[sub_category] += 1
                        concept_hits[category] += 0.5  # 父类别权重稍低
        
        # 计算相关性分数
        concept_scores = {}
        total_hits = sum(concept_hits.values()) if concept_hits else 1
        
        for concept, count in concept_hits.items():
            base_score = count / total_hits
            sensitivity = self.concept_sensitivity.get(concept, 0.5)
            weighted_score = base_score * sensitivity
            concept_scores[concept] = round(weighted_score, 4)
        
        # 归一化
        if concept_scores:
            max_score = max(concept_scores.values())
            if max_score > 0:
                for concept in concept_scores:
                    concept_scores[concept] = round(concept_scores[concept] / max_score, 4)
        
        return concept_scores

    def get_concept_details(self, text: str) -> Dict:
        """
        获取概念详细信息，包括层级结构
        
        Returns:
            Dict: {
                "concepts": {概念: 分数},
                "categories": {大类: [子类]},
                "top_concepts": [{概念, 分数}]
            }
        """
        concepts = self.extract_concepts(text)
        
        # 按分类聚合
        categories = {}
        for concept, score in concepts.items():
            for category, sub_cats in self.concept_hierarchy.items():
                if concept in sub_cats or concept == category:
                    if category not in categories:
                        categories[category] = []
                    categories[category].append({"concept": concept, "score": score})
        
        # 排序
        sorted_concepts = sorted(concepts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "concepts": concepts,
            "categories": categories,
            "top_concepts": [{"concept": c, "score": s} for c, s in sorted_concepts]
        }


# ============================================================================
# 情感分析器
# ============================================================================

class FinanceSentimentAnalyzer:
    """
    财经情感分析器
    分析新闻的利好/利空情绪，支持否定词和转折词修正
    """

    def __init__(self):
        # 正面情感词汇（按强度分级）
        self.positive_words = {
            "强烈利好": ["重大利好", "政策红利", "超预期", "超预期增长", "大幅增长", 
                          "爆发式增长", "历史新高", "创纪录", "突破性进展", "里程碑", 
                          "划时代", "颠覆性", "全面放开", "完全放开", "大规模", 
                          "大力支持", "强力支持", "政策利好", "利好消息", "大涨", "暴涨", 
                          "飙升", "一字涨停", "涨停", "资金流入", "北向资金净流入"],
            "利好": ["利好", "积极", "正面", "向好", "改善", "回升", "回暖", "复苏", 
                      "恢复", "增长", "上升", "上涨", "扩张", "扩大", "提升", "改善", 
                      "优化", "支持", "鼓励", "扶持", "补贴", "减税", "降费", "优惠", 
                      "宽松", "放开", "放宽", "简化", "取消限制", "准入放开", "市场化改革",
                      "创新", "突破", "进展", "成果", "成功", "达成", "签署", "合作",
                      "看好", "看多", "推荐", "买入", "增持", "加仓", "流入", "净买入",
                      "降准", "降息", "释放", "刺激", "利好因素", "积极因素", "向上修正"],
            "弱利好": ["稳定", "平稳", "温和", "小幅增长", "略有改善", "符合预期", "如期而至"]
        }
        
        # 负面情感词汇（按强度分级）
        self.negative_words = {
            "强烈利空": ["重大利空", "政策打击", "超预期下滑", "大幅下滑", "断崖式下跌",
                          "历史新低", "创新低", "崩盘", "暴跌", "暴雷", "爆仓", "退市",
                          "全面收紧", "完全禁止", "大规模撤出", "强力打击", "严厉整顿",
                          "跌停", "一字跌停", "暴跌", "股市震荡", "资金流出"],
            "利空": ["利空", "消极", "负面", "向下", "恶化", "下滑", "下降", "下跌",
                      "收缩", "缩小", "回落", "减少", "低迷", "衰退", "打击", "严厉打击", "限制",
                      "收紧", "监管", "整顿", "整治", "查处", "处罚", "禁止", "叫停",
                      "暂停", "终止", "取消", "撤销", "紧缩", "从严", "悲观", "看空",
                      "看跌", "卖出", "减持", "减仓", "流出", "净卖出", "加息", "上调",
                      "收紧流动性", "抽紧银根", "负面影响", "利空因素", "向下修正",
                      "不及预期", "低于预期", "危机", "流动性危机", "暴雷", "爆雷"],
            "弱利空": ["放缓", "趋缓", "小幅下滑", "略有回落", "低于预期", "不及预期"]
        }
        
        # 中性词汇
        self.neutral_words = {
            "中性": ["预期", "计划", "部署", "安排", "会议", "讨论", "研究", "调研",
                     "观察", "关注", "跟踪", "分析", "评估", "测算", "预测", "展望",
                     "维持", "保持", "继续", "延续", "正常", "常态", "稳步", "有序"]
        }
        
        # 否定词和转折词
        self.negation_words = ["不", "非", "没有", "未", "无", "否", "拒绝", "反对", "避免", "禁止"]
        self.transition_words = ["但", "但是", "然而", "不过", "只是", "尽管", "虽然", "却"]
        
        # 情感强度权重
        self.sentiment_weights = {
            "强烈利好": 1.5, "利好": 1.0, "弱利好": 0.5,
            "强烈利空": -1.5, "利空": -1.0, "弱利空": -0.5
        }

    def calculate_sentiment(self, text: str) -> Tuple[float, Dict]:
        """
        计算情感得分
        
        Args:
            text: 新闻文本
            
        Returns:
            Tuple[float, Dict]:
                - float: 综合情感得分 (-1到1, 正数利好, 负数利空)
                - Dict: 详细的情感分析结果
        """
        words = jieba.lcut(text)
        words = [w.lower() for w in words if len(w) > 1]
        
        # 统计情感词汇
        positive_counts = {"强烈利好": 0, "利好": 0, "弱利好": 0}
        negative_counts = {"强烈利空": 0, "利空": 0, "弱利空": 0}
        
        # 检测否定词和转折词位置
        negation_positions = [i for i, w in enumerate(words) if w in self.negation_words]
        transition_positions = [i for i, w in enumerate(words) if w in self.transition_words]
        
        for word in words:
            for level, keywords in self.positive_words.items():
                if word in keywords:
                    positive_counts[level] += 1
            for level, keywords in self.negative_words.items():
                if word in keywords:
                    negative_counts[level] += 1
        
        # 计算基础得分
        base_score = sum(
            count * self.sentiment_weights[level] 
            for level, count in positive_counts.items()
        ) + sum(
            count * self.sentiment_weights[level] 
            for level, count in negative_counts.items()
        )
        
        # 否定词修正 (反转后续词汇的极性)
        negation_score = 0
        for pos in negation_positions:
            for i in range(1, min(4, len(words) - pos)):
                word = words[pos + i]
                for level, keywords in self.positive_words.items():
                    if word in keywords:
                        negation_score -= self.sentiment_weights[level] * 0.8
                for level, keywords in self.negative_words.items():
                    if word in keywords:
                        negation_score += self.sentiment_weights[level] * 0.8
        
        # 转折词修正 (转折后的情感权重增加)
        transition_score = 0
        for pos in transition_positions:
            for i in range(1, min(4, len(words) - pos)):
                word = words[pos + i]
                for level, keywords in self.positive_words.items():
                    if word in keywords:
                        transition_score += self.sentiment_weights[level] * 0.5
                for level, keywords in self.negative_words.items():
                    if word in keywords:
                        transition_score += self.sentiment_weights[level] * 0.5
        
        total_score = base_score + negation_score + transition_score
        
        # 归一化到 -1 到 1
        if total_score > 0:
            normalized = min(total_score / (total_score + 2), 0.99)
        elif total_score < 0:
            normalized = max(total_score / (abs(total_score) + 2), -0.99)
        else:
            normalized = 0
        
        analysis = {
            "positive_counts": positive_counts,
            "negative_counts": negative_counts,
            "base_score": round(base_score, 4),
            "negation_score": round(negation_score, 4),
            "transition_score": round(transition_score, 4),
            "total_score": round(total_score, 4),
            "normalized_score": round(normalized, 4)
        }
        
        return normalized, analysis

    def classify_sentiment(self, score: float) -> str:
        """根据得分分类情感"""
        if score >= 0.5:
            return "强烈利好"
        elif score >= 0.2:
            return "利好"
        elif score >= 0.05:
            return "弱利好"
        elif score <= -0.5:
            return "强烈利空"
        elif score <= -0.2:
            return "利空"
        elif score <= -0.05:
            return "弱利空"
        else:
            return "中性"

    def analyze(self, text: str) -> Tuple[float, str, float, float, Dict]:
        """
        完整分析情感
        
        Returns:
            Tuple[float, str, float, float, Dict]:
                - 情感得分
                - 情感分类
                - 利好概率 (%)
                - 利空概率 (%)
                - 详细分析
        """
        score, analysis = self.calculate_sentiment(text)
        sentiment_class = self.classify_sentiment(score)
        
        # 计算概率
        if score > 0:
            pos_prob = round(min(score * 100 + 50, 95), 2)
            neg_prob = round(100 - pos_prob, 2)
        elif score < 0:
            neg_prob = round(min(abs(score) * 100 + 50, 95), 2)
            pos_prob = round(100 - neg_prob, 2)
        else:
            pos_prob = 50.0
            neg_prob = 50.0
        
        return score, sentiment_class, pos_prob, neg_prob, analysis


# ============================================================================
# 单例实例（便于直接使用）
# ============================================================================

concept_analyzer = FinanceConceptAnalyzer()
sentiment_analyzer = FinanceSentimentAnalyzer()


# ============================================================================
# 对外接口函数
# ============================================================================

def analyze_finance_item(title: str, content: str = "") -> Dict:
    """
    分析单条财经新闻
    
    Args:
        title: 新闻标题
        content: 新闻内容（可选）
        
    Returns:
        Dict: {
            "concepts": {概念: 相关性分数},
            "concept_probabilities": {概念: 概率分数},
            "top_concepts": [{概念, 分数}],
            "sentiment_score": 情感得分,
            "sentiment_class": 情感分类,
            "positive_probability": 利好概率,
            "negative_probability": 利空概率,
            "analysis": 详细分析数据
        }
    """
    text = title + " " + (content[:500] if content else "")
    
    # 概念提取
    concepts = concept_analyzer.extract_concepts(text)
    concept_details = concept_analyzer.get_concept_details(text)
    
    # 情感分析
    score, sentiment_class, pos_prob, neg_prob, sentiment_analysis = sentiment_analyzer.analyze(text)
    
    # 计算概念概率 (概念分数 * 情感得分)
    concept_probabilities = {c: round(s * score, 4) for c, s in concepts.items()}
    
    # 主要概念排序
    sorted_concepts = sorted(
        concept_probabilities.items(), 
        key=lambda x: abs(x[1]), 
        reverse=True
    )[:5]
    
    return {
        "concepts": concepts,
        "concept_details": concept_details,
        "concept_probabilities": concept_probabilities,
        "top_concepts": [{"concept": c, "probability": p} for c, p in sorted_concepts],
        "sentiment_score": round(score, 4),
        "sentiment_class": sentiment_class,
        "positive_probability": pos_prob,
        "negative_probability": neg_prob,
        "analysis": {
            "sentiment": sentiment_analysis,
            "text_length": len(text)
        }
    }


def batch_analyze_finance_items(items: List[Dict]) -> List[Dict]:
    """
    批量分析财经新闻
    
    Args:
        items: 新闻列表，每个新闻包含 title 和可选的 content
        
    Returns:
        List[Dict]: 分析结果列表
    """
    return [analyze_finance_item(item.get("title", ""), item.get("content", "")) for item in items]


# ============================================================================
# 集成到 pipeline.py 的辅助函数
# ============================================================================

def integrate_finance_analysis_to_hotlist(mainland_data: Dict) -> Dict:
    """
    为内地财经热点榜数据添加财经分析
    
    Args:
        mainland_data: 原始的内地财经媒体数据
        
    Returns:
        Dict: 添加了 finance_analysis 字段的数据
    """
    if not isinstance(mainland_data, dict):
        return mainland_data
    
    headlines = mainland_data.get("headlines", [])
    if not headlines:
        return mainland_data
    
    # 为每个 headline 添加财经分析
    for headline in headlines:
        if isinstance(headline, dict) and "title" in headline:
            if "finance_analysis" not in headline:
                headline["finance_analysis"] = analyze_finance_item(
                    headline.get("title", ""), 
                    headline.get("content", "")
                )
    
    # 计算整体统计
    all_concepts = Counter()
    sentiment_scores = []
    
    for headline in headlines:
        fa = headline.get("finance_analysis", {})
        for concept, score in fa.get("concepts", {}).items():
            all_concepts[concept] += score
        if fa.get("sentiment_score") is not None:
            sentiment_scores.append(fa["sentiment_score"])
    
    # 整体情感统计
    avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
    
    if avg_sentiment > 0:
        overall_pos_prob = round(min(abs(avg_sentiment) * 100, 95), 2)
        overall_neg_prob = round(100 - overall_pos_prob, 2)
    elif avg_sentiment < 0:
        overall_neg_prob = round(min(abs(avg_sentiment) * 100, 95), 2)
        overall_pos_prob = round(100 - overall_neg_prob, 2)
    else:
        overall_pos_prob = 50.0
        overall_neg_prob = 50.0
    
    # 整体概念统计
    top_overall_concepts = sorted(
        all_concepts.items(), 
        key=lambda x: x[1], 
        reverse=True
    )[:5]
    
    mainland_data["finance_analysis_summary"] = {
        "overall_sentiment_score": round(avg_sentiment, 4),
        "overall_sentiment_class": sentiment_analyzer.classify_sentiment(avg_sentiment),
        "overall_positive_probability": overall_pos_prob,
        "overall_negative_probability": overall_neg_prob,
        "top_concepts": [{"concept": c, "score": round(s, 4)} for c, s in top_overall_concepts]
    }
    
    return mainland_data


# ============================================================================
# 测试函数
# ============================================================================

def test_analyzer():
    """测试分析器"""
    test_cases = [
        "国务院发布新能源汽车产业发展规划，目标2030年渗透率达40%",
        "证监会严厉打击内幕交易，多家上市公司被立案调查",
        "降准落地！释放长期资金约5000亿元",
        "美联储加息75个基点，全球股市震荡",
        "芯片法案通过，国内半导体概念股集体大涨",
        "地产销售数据不及预期，多家房企面临流动性危机",
        "北向资金连续10日净流入，A股市场信心回升"
    ]
    
    print("=== 财经概念映射与情感分析测试 ===\n")
    
    for i, text in enumerate(test_cases, 1):
        result = analyze_finance_item(text)
        print(f"{i}. {text}")
        print(f"   概念: {', '.join([c['concept'] for c in result['top_concepts']])}")
        print(f"   情感: {result['sentiment_class']} (得分: {result['sentiment_score']:.4f})")
        print(f"   利好概率: {result['positive_probability']}% | 利空概率: {result['negative_probability']}%")
        print()


if __name__ == "__main__":
    test_analyzer()
