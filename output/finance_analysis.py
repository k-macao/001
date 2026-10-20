#!/usr/bin/env python3
"""
【沸腾花蛤】情绪热点因子量化分析（原「内地财经热点榜」，2026-10-19 更名）的本地标题分析
（jieba + 财经词表 + 情绪词典 + 风险词表）。

在不请求外部大模型、也不读取新闻正文的前提下，对标题做分词、停用词过滤和词汇统计；
主题词频按「提及该词的标题数」及「涉及媒体数」统计，不把重复出现次数包装成热度或概率。
2026-10-19 起新增三块本地「AI 分析」（全部规则合成、确定性、可复现）：
  ① 情绪总览：标题级情绪词典折叠成 偏多 / 中性 / 偏空 计数与净情绪分；
  ② 热点聚合：同一份标题词汇把跨媒体同题（≥2 条）聚成热点簇，附情绪与风险标注；
  ③ 预警风险点：风险词表命中的标题按类别聚合，给出传播度等级（高 / 中 / 关注）。
情绪分数与风险等级都是启发式词典结果，不是经校准的涨跌概率，也不构成投资建议。
另保留概念映射与标题情绪词典接口供兼容使用。

用法：
    from output.finance_analysis import analyze_finance_item, summarize_hotlist_vocabulary
    from output.finance_analysis import (aggregate_hotlist_sentiment,
                                         aggregate_hotlist_hotspots, analyze_hotlist_risks)

    item = analyze_finance_item("国务院发布新能源汽车产业发展规划")
    print(item["vocabulary_terms"])
"""

import jieba
from typing import Dict, List, Tuple, Optional
from collections import Counter
import datetime
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
            "股权变动", "高管变动", "停牌", "复牌", "退市", "ST", "*ST",
            # 词频分析专用词（避免「大额存单」「存储芯片」等关键短语被切碎）
            "A股", "H股", "港股", "沪指", "创业板指", "科创板", "北交所", "沪深300",
            "人工智能", "生成式人工智能", "大模型", "算力", "数据中心", "光模块", "存储芯片",
            "具身智能", "人形机器人", "固态电池", "动力电池", "新能源汽车", "消费电子",
            "金融街论坛", "大额存单", "存款利率", "北向资金", "南向资金", "社融",
            "以旧换新", "创新药", "大宗商品", "净流入", "净流出", "同比增长", "环比增长",
            "ETF", "CPO", "PCB", "GPU", "CPU", "GDP", "CPI", "PPI", "PMI", "LPR", "MLF", "M2"
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
# 标题词汇分析（本地 jieba 分词，不调用外部大模型）
# ============================================================================

# 新闻标题里的通用报道词 / 虚词。词频按标题级去重，停用词只影响词汇榜，
# 不会删改原始标题，也不会影响热点主题榜的条数。
FINANCE_VOCABULARY_STOPWORDS = frozenset((
    "今日", "昨日", "明日", "近日", "日前", "本周", "今年", "去年", "年内", "目前", "当前",
    "今日早盘", "今日午间", "今日下午", "早盘", "午盘", "午后", "盘中", "收盘后", "开盘后",
    "公司", "企业", "上市公司", "多家公司", "多家企业", "市场", "行业", "领域", "机构", "人士",
    "记者", "消息", "新闻", "财经", "报道", "相关", "表示", "指出", "称", "据悉", "获悉",
    "发布", "宣布", "公布", "显示", "披露", "公告", "回应", "提到", "介绍", "表示称",
    "预计", "有望", "将于", "或将", "正在", "已经", "目前已", "进一步", "持续", "继续", "再次",
    "首次", "首个", "首批", "多个", "多家", "部分", "其中", "同时", "此外", "此前", "之后",
    "方面", "情况", "变化", "相关人士", "有关", "我国", "国内", "全国", "全球", "中国", "目前来看",
    "三大", "集体", "指跌超", "指涨超", "频频", "并作", "出席", "演讲", "透露", "认为", "提出",
    "今日起", "正式", "创新", "推动", "加快", "加大", "实现", "成为", "进入", "带动", "影响",
    "同比", "环比", "同比增长", "环比增长", "增长", "下降", "上升", "上涨", "下跌", "大幅",
    "亿元", "万亿元", "人民币", "万亿", "亿元人民币", "亿美元", "美元", "个百分点", "个基点", "个交易日",
    "主席", "频频", "披露", "供给", "需求", "紧张", "旺盛", "格局", "没有", "重回", "逆势",
    "上调", "年期", "成本", "容量", "三大指数", "板块", "支持", "科技", "融资",
))

# 同频时优先保留高信息量的财经词；其余词按首次出现次序稳定排序。
FINANCE_VOCABULARY_PRIORITY = (
    "AI", "大模型", "算力", "半导体", "芯片", "存储芯片", "A股", "港股", "创业板指",
    "证监会", "央行", "监管", "政策", "降准", "降息", "LPR", "GDP", "CPI", "PPI", "PMI",
    "新能源", "新能源汽车", "电池", "固态电池", "光伏", "储能", "机器人", "数据中心",
    "ETF", "CPO", "PCB", "GPU", "CPU", "北向资金", "南向资金", "沪指", "科创板",
    "大额存单", "存款利率", "银行", "券商", "基金", "保险", "房地产", "创新药", "黄金", "原油",
    "业绩", "净利润", "订单", "回购", "增持", "减持", "并购", "重组", "涨停", "跌停",
)
_FINANCE_VOCABULARY_PRIORITY_RANK = {term: i for i, term in enumerate(FINANCE_VOCABULARY_PRIORITY)}


def _normalize_vocabulary_token(token: str) -> str:
    """清理分词结果；全 ASCII 词汇统一大写，便于 AI / ETF 等跨标题合并。"""
    token = str(token or "").strip()
    token = re.sub(r"^[^\w]+|[^\w]+$", "", token, flags=re.UNICODE)
    if token.isascii():
        token = token.upper()
    return token


def extract_finance_vocabulary(text: str) -> List[str]:
    """从标题 / 文本抽取可读词汇，返回去重后的 token（保留首次出现顺序）。

    采用 jieba 的本地词典分词，再过滤数字、标点、单字和常见报道套话。
    这是一份可复现的候选词清单，不做无监督「语义」推断；外部模型不可用也不影响结果。
    """
    text = str(text or "").strip()
    if not text:
        return []

    result, seen = [], set()
    for raw in jieba.lcut(text, HMM=False):
        token = _normalize_vocabulary_token(raw)
        if len(token) < 2 or token in FINANCE_VOCABULARY_STOPWORDS:
            continue
        if token.isdigit() or not re.search(r"[\u3400-\u9fff]", token):
            # ASCII acronym / ticker-like terms can be meaningful (AI, ETF, GDP).
            if not re.fullmatch(r"[A-Z]{2,}[0-9]*", token):
                continue
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def summarize_hotlist_vocabulary(headlines: List[Dict], top_n: int = 8) -> Dict:
    """汇总内地热点榜的标题词汇。

    每个词在一条标题中至多计一次；`title_count` 是提及该词的标题数，
    `media_count` 是这些标题涉及的不同媒体数，绝不是词频概率或市场预测。
    """
    headlines = headlines if isinstance(headlines, (list, tuple)) else []
    title_counts = Counter()
    media_by_term = {}
    first_seen = {}
    analyzed_titles = 0

    for headline in headlines:
        if not isinstance(headline, dict):
            continue
        title = str(headline.get("title") or "").strip()
        if not title:
            continue
        analyzed_titles += 1
        # 不信任历史 / 外部注入的缓存词条：按标题重新分词，确保词汇摘要绝不读取正文。
        terms = extract_finance_vocabulary(title)
        unique_terms = list(dict.fromkeys(str(term).strip() for term in terms if str(term).strip()))
        source = str(headline.get("source") or "").strip()
        for term in unique_terms:
            if term not in first_seen:
                first_seen[term] = len(first_seen)
            title_counts[term] += 1
            media_by_term.setdefault(term, set())
            if source:
                media_by_term[term].add(source)

    try:
        limit = max(0, int(top_n))
    except (TypeError, ValueError):
        limit = 8
    sorted_terms = sorted(
        title_counts.items(),
        key=lambda pair: (-pair[1],
                          _FINANCE_VOCABULARY_PRIORITY_RANK.get(pair[0], len(FINANCE_VOCABULARY_PRIORITY)),
                          first_seen.get(pair[0], 0)),
    )
    top_terms = [
        {"term": term, "title_count": count,
         "media_count": len(media_by_term.get(term) or ())}
        for term, count in sorted_terms[:limit]
    ]
    return {
        "enabled": True,
        "has_data": bool(title_counts),
        "method": "jieba 本地分词 + 财经停用词表",
        "counting_unit": "标题级去重",
        "total_titles": analyzed_titles,
        "unique_terms": len(title_counts),
        "top_terms": top_terms,
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
# 情绪热点因子（2026-10-19 升级）：情绪总览 + 热点聚合 + 预警风险点
#   与词汇分析同一口径：只读标题、本地 jieba 分词与固定词表命中、不调用外部大模型；
#   同一批标题两次跑出同一份结果。情绪分是词典启发式分数、风险等级是传播度等级，
#   都不是经校准的涨跌概率，也不构成投资建议。
# ============================================================================

# 情绪极性折叠：词典七档标签 → 偏多 / 中性 / 偏空 三档（阈值与 classify_sentiment 对齐）。
_MOOD_POSITIVE_CLASSES = frozenset(("强烈利好", "利好", "弱利好"))
_MOOD_NEGATIVE_CLASSES = frozenset(("强烈利空", "利空", "弱利空"))
MOOD_POSITIVE = "偏多"
MOOD_NEUTRAL = "中性"
MOOD_NEGATIVE = "偏空"
# 净情绪分 → 定调阈值（与弱利好 / 弱利空档位 ±0.05 对齐，避免自造第二套阈值）。
_MOOD_AVG_THRESHOLD = 0.05

# 风险词表：类别 → 关键词。匹配口径与热点主题词表一致——中文按子串命中；
# 目前全部为中文词（短 ASCII 词如 ST 容易误命中 STOXX / FIRST 之类，宁缺毋滥不收）。
FINANCE_RISK_LEXICON = (
    ("监管与合规风险", ("立案", "调查", "处罚", "罚款", "违规", "违法", "警示函", "监管函",
                     "问询", "整改", "整治", "约谈", "叫停", "暂停", "终止", "撤销", "查处",
                     "谴责", "禁入", "内幕交易", "市场操纵")),
    ("市场波动风险", ("大跌", "暴跌", "跌停", "跳水", "下挫", "重挫", "跌超", "低开", "收跌",
                   "下探", "回调", "腰斩", "蒸发", "闪崩")),
    ("信用与财务风险", ("违约", "暴雷", "爆雷", "预亏", "亏损", "债务", "逾期", "破产", "清算",
                     "退市", "风险警示", "减值", "资不抵债", "流动性危机", "不及预期",
                     "低于预期", "重整")),
    ("资金流向风险", ("减持", "抛售", "净流出", "撤离", "赎回", "做空", "套现", "清仓", "出逃")),
    ("外部冲击风险", ("关税", "制裁", "封锁", "禁运", "管制", "实体清单", "黑名单", "冲突",
                   "战争", "加息", "断供", "短缺")),
)
_RISK_CATEGORY_ORDER = {name: i for i, (name, _) in enumerate(FINANCE_RISK_LEXICON)}
RISK_LEVEL_HIGH = "高"
RISK_LEVEL_MID = "中"
RISK_LEVEL_WATCH = "关注"
_RISK_LEVEL_ORDER = {RISK_LEVEL_HIGH: 0, RISK_LEVEL_MID: 1, RISK_LEVEL_WATCH: 2}
# 等级只描述「传播度」（几条标题 / 几家媒体在说），不预测风险发生的概率。
RISK_LEVEL_RULE = "高 = 同类 ≥3 条且 ≥2 家媒体；中 = ≥2 条或 ≥2 家媒体；关注 = 单条命中"


def match_risk_keywords(title: str) -> List[Tuple[str, str]]:
    """标题的风险词表命中：[(风险类别, 关键词)]，按词表顺序返回；未命中为空列表。

    中文按子串命中（与热点主题词表同口径）；确定性——同一标题永远得到同一份命中。
    """
    text = str(title or "")
    hits = []
    for category, keywords in FINANCE_RISK_LEXICON:
        for kw in keywords:
            if kw in text:
                hits.append((category, kw))
    return hits


def title_mood(title: str) -> Dict:
    """标题级词典情绪：{"score": float, "label": 偏多/中性/偏空}。

    只调用本地情绪词典（jieba 分词 + 正负词表），不读正文、不调外部模型；
    分数是启发式词典分，不是校准概率。
    """
    score, _analysis = sentiment_analyzer.calculate_sentiment(str(title or ""))
    sentiment_class = sentiment_analyzer.classify_sentiment(score)
    if sentiment_class in _MOOD_POSITIVE_CLASSES:
        label = MOOD_POSITIVE
    elif sentiment_class in _MOOD_NEGATIVE_CLASSES:
        label = MOOD_NEGATIVE
    else:
        label = MOOD_NEUTRAL
    return {"score": round(score, 4), "label": label}


def aggregate_titles_mood(titles: List[str]) -> Dict:
    """标题列表 → 情绪折叠计数与净情绪分（确定性；空列表时 avg_score / label 为 None）。"""
    titles = [str(t or "").strip() for t in (titles or [])]
    titles = [t for t in titles if t]
    pos = neu = neg = 0
    scores = []
    for t in titles:
        mood = title_mood(t)
        scores.append(mood["score"])
        if mood["label"] == MOOD_POSITIVE:
            pos += 1
        elif mood["label"] == MOOD_NEGATIVE:
            neg += 1
        else:
            neu += 1
    avg = round(sum(scores) / len(scores), 3) if scores else None
    if avg is None:
        label = None
    elif avg >= _MOOD_AVG_THRESHOLD:
        label = MOOD_POSITIVE
    elif avg <= -_MOOD_AVG_THRESHOLD:
        label = MOOD_NEGATIVE
    else:
        label = MOOD_NEUTRAL
    return {"pos_n": pos, "neu_n": neu, "neg_n": neg, "avg_score": avg, "label": label}


def aggregate_hotlist_sentiment(headlines: List[Dict]) -> Dict:
    """情绪总览（栏目因子行）：偏多 / 中性 / 偏空 条数 + 净情绪分 + 定调。

    只读标题；样本不足时如实只报样本量，不硬造定调。
    """
    titles = [str((h or {}).get("title") or "").strip() for h in headlines if isinstance(h, dict)]
    titles = [t for t in titles if t]
    mix = aggregate_titles_mood(titles)
    return {
        "has_data": bool(titles),
        "method": "本地情绪词典（jieba 分词 · 标题级）",
        "counting_unit": "标题级",
        "total_titles": len(titles),
        **mix,
        "note": "词典启发式情绪分，非校准概率，不构成投资建议",
    }


def aggregate_hotlist_hotspots(headlines: List[Dict], top_n: int = 8) -> Dict:
    """热点聚合：把标题级词汇当聚合键，跨媒体同题（≥2 条）的标题聚成热点簇。

    与 summarize_hotlist_vocabulary 用同一份分词、同一套排序
    （-标题数 → 财经优先词表 → 首见次序），因此词汇口径与旧「AI词汇分析」完全一致；
    每个簇再附：涉及媒体、情绪折叠（偏多/中性/偏空 + 净分 + 定调）、命中的风险类别。
    `aggregated=True` 表示 ≥2 条标题同题（真正的「聚合」热点）；单条命中的词照常列出，
    与旧词汇榜不丢信息。同一条标题可命中多个热点簇（按词聚合，不是划分），计数行如实说明。
    """
    headlines = headlines if isinstance(headlines, (list, tuple)) else []
    try:
        limit = max(0, int(top_n))
    except (TypeError, ValueError):
        limit = 8
    clusters = {}          # term -> 聚合状态
    first_seen = {}        # term -> 首见次序（稳定排序用）
    analyzed_titles = 0

    for headline in headlines:
        if not isinstance(headline, dict):
            continue
        title = str(headline.get("title") or "").strip()
        if not title:
            continue
        analyzed_titles += 1
        # 与词汇摘要同口径：不信任缓存词条，按标题重新分词，绝不读取正文。
        terms = extract_finance_vocabulary(title)
        mood = title_mood(title)
        risk_categories = list(dict.fromkeys(cat for cat, _kw in match_risk_keywords(title)))
        source = str(headline.get("source") or "").strip()
        for term in dict.fromkeys(str(t).strip() for t in terms if str(t).strip()):
            if term not in clusters:
                first_seen[term] = len(first_seen)
                clusters[term] = {"term": term, "title_count": 0, "media": set(),
                                  "pos_n": 0, "neu_n": 0, "neg_n": 0, "scores": [],
                                  "risk_categories": [], "members": []}
            c = clusters[term]
            c["title_count"] += 1                 # 标题级去重：同一标题同一词只计一次
            if source:
                c["media"].add(source)
            if mood["label"] == MOOD_POSITIVE:
                c["pos_n"] += 1
            elif mood["label"] == MOOD_NEGATIVE:
                c["neg_n"] += 1
            else:
                c["neu_n"] += 1
            c["scores"].append(mood["score"])
            for cat in risk_categories:
                if cat not in c["risk_categories"]:
                    c["risk_categories"].append(cat)
            c["members"].append(headline)

    ordered = sorted(
        clusters.values(),
        key=lambda c: (-c["title_count"],
                       _FINANCE_VOCABULARY_PRIORITY_RANK.get(c["term"], len(FINANCE_VOCABULARY_PRIORITY)),
                       first_seen.get(c["term"], 0)),
    )
    top = []
    for c in ordered[:limit]:
        avg = round(sum(c["scores"]) / len(c["scores"]), 3) if c["scores"] else None
        if avg is None:
            label = None
        elif avg >= _MOOD_AVG_THRESHOLD:
            label = MOOD_POSITIVE
        elif avg <= -_MOOD_AVG_THRESHOLD:
            label = MOOD_NEGATIVE
        else:
            label = MOOD_NEUTRAL
        members = sorted(c["members"], key=lambda h: str(h.get("published_cst") or ""), reverse=True)
        top.append({
            "term": c["term"],
            "title_count": c["title_count"],
            "media_count": len(c["media"]),
            "media": sorted(c["media"]),
            "pos_n": c["pos_n"], "neu_n": c["neu_n"], "neg_n": c["neg_n"],
            "avg_score": avg, "label": label,
            "risk_categories": c["risk_categories"],
            "aggregated": c["title_count"] >= 2,
            "samples": [{"title": str(m.get("title") or ""), "source": str(m.get("source") or ""),
                         "url": str(m.get("url") or ""),
                         "published_cst": str(m.get("published_cst") or "")}
                        for m in members[:2]],
        })
    return {
        "enabled": True,
        "has_data": bool(clusters),
        "method": "jieba 本地分词 + 财经停用词表 + 情绪/风险词表",
        "counting_unit": "标题级去重",
        "total_titles": analyzed_titles,
        "aggregated_n": sum(1 for c in clusters.values() if c["title_count"] >= 2),
        "clusters": top,
        "note": "按词聚合，同一条标题可进多个热点簇；情绪与风险为词典启发式，非校准概率",
    }


def analyze_hotlist_risks(headlines: List[Dict], top_n: int = 5) -> Dict:
    """预警风险点：风险词表命中的标题按类别聚合，附传播度等级（高 / 中 / 关注）。

    口径：标题级计数——同一标题在同类别里命中多个词只算 1 条；同一标题可命中多个类别。
    等级只看传播度（见 RISK_LEVEL_RULE），不是发生概率；每类附最多 2 条最新证据标题。
    没有任何命中时 has_data=False（渲染层如实报「未命中」，不硬造风险）。
    """
    headlines = headlines if isinstance(headlines, (list, tuple)) else []
    try:
        limit = max(0, int(top_n))
    except (TypeError, ValueError):
        limit = 5
    by_category = {}       # category -> 聚合状态
    total_titles = 0
    hit_n = 0

    for headline in headlines:
        if not isinstance(headline, dict):
            continue
        title = str(headline.get("title") or "").strip()
        if not title:
            continue
        total_titles += 1
        hits = match_risk_keywords(title)
        if not hits:
            continue
        hit_n += 1
        for category, kw in hits:
            entry = by_category.setdefault(
                category, {"titles": [], "keyword_counts": {}, "media": set()})
            if not any(t is headline for t in entry["titles"]):
                entry["titles"].append(headline)          # 标题级：同类别一条只计一次
            entry["keyword_counts"][kw] = entry["keyword_counts"].get(kw, 0) + 1
            source = str(headline.get("source") or "").strip()
            if source:
                entry["media"].add(source)

    points = []
    for category, entry in by_category.items():
        count = len(entry["titles"])
        media_n = len(entry["media"])
        if count >= 3 and media_n >= 2:
            level = RISK_LEVEL_HIGH
        elif count >= 2 or media_n >= 2:
            level = RISK_LEVEL_MID
        else:
            level = RISK_LEVEL_WATCH
        # 关键词按命中次数降序、同频按词表次序——确定性排序，不用 dict 迭代序。
        kw_order = {kw: i for i, (_c, kw) in enumerate(
            (pair for pair in _iter_lexicon_pairs() if pair[0] == category))}
        keywords = [kw for kw, _n in sorted(entry["keyword_counts"].items(),
                                            key=lambda kv: (-kv[1], kw_order.get(kv[0], 0)))]
        samples = sorted(entry["titles"],
                         key=lambda h: str(h.get("published_cst") or ""), reverse=True)[:2]
        points.append({
            "category": category,
            "level": level,
            "count": count,
            "media_n": media_n,
            "media": sorted(entry["media"]),
            "keywords": keywords,
            "samples": [{
                "title": str(s.get("title") or ""),
                "source": str(s.get("source") or ""),
                "url": str(s.get("url") or ""),
                "published_cst": str(s.get("published_cst") or ""),
                "matched": list(dict.fromkeys(kw for cat2, kw in match_risk_keywords(
                    s.get("title")) if cat2 == category)),
            } for s in samples],
        })
    points.sort(key=lambda p: (_RISK_LEVEL_ORDER.get(p["level"], 9), -p["count"],
                               -p["media_n"], _RISK_CATEGORY_ORDER.get(p["category"], 99)))
    return {
        "enabled": True,
        "has_data": hit_n > 0,
        "method": "本地风险词表（标题级命中）",
        "counting_unit": "标题级",
        "total_titles": total_titles,
        "hit_n": hit_n,
        "level_rule": RISK_LEVEL_RULE,
        "points": points[:limit],
        "points_total": len(points),
        "note": "等级是传播度等级，不是发生概率；不构成投资建议",
    }


def _iter_lexicon_pairs():
    """按词表顺序展开 (类别, 关键词)，供确定性排序使用。"""
    for category, keywords in FINANCE_RISK_LEXICON:
        for kw in keywords:
            yield category, kw


# ============================================================================
# 预警趋势与今日风险态势（2026-10-20 新增：「平时也有功能」的每日风险分析）
# ============================================================================
# 口径：与「⚠ 预警风险点」同一份本地风险词表、同一套标题级命中与传播度等级规则，
# 对存档语料（news_history.json「内地财经媒体」段）按自然日重算近 RISK_TREND_DAYS 日
# 画像，与基准日（今日之前最近一个有存档的日子）对比出五种确定性状态：
#   新增 / 升级 / 持续 / 降级 / 解除。
# 状态只描述「词表命中的日间变化」，不是事件演化事实，也不是发生概率；
# 今日存档样本过少时如实提示「对比仅作提示」，无基准日时渲染层整行不出（不硬造变化）。

RISK_TREND_DAYS = 7          # 近几个自然日（含今日）重算逐日风险画像
RISK_TREND_MIN_SAMPLE = 5    # 今日存档切片少于该条数 → 低样本，对比仅作提示
RISK_STATUS_NEW = "新增"
RISK_STATUS_UP = "升级"
RISK_STATUS_ONGOING = "持续"
RISK_STATUS_DOWN = "降级"
RISK_STATUS_CLEARED = "解除"
_RISK_STATUS_ORDER = {RISK_STATUS_NEW: 0, RISK_STATUS_UP: 1, RISK_STATUS_ONGOING: 2,
                      RISK_STATUS_DOWN: 3, RISK_STATUS_CLEARED: 4}
_RISK_LEVEL_RANK = {RISK_LEVEL_WATCH: 1, RISK_LEVEL_MID: 2, RISK_LEVEL_HIGH: 3}
RISK_TREND_METHOD = (f"近 {RISK_TREND_DAYS} 日按日重算"
                     "（同一份风险词表 · 标题级 · 存档日期口径）")


def daily_risk_profile(items) -> Dict:
    """一个自然日的标题切片 → 逐日风险画像（与预警风险点同一份词表和等级规则）。

    返回 {total_titles, hit_n, hit_rate, categories: {类别: {level, count, media_n}}}。
    categories 保全量类别（不做 top_n 截断），只供按日对比，不供渲染证据行。
    """
    report = analyze_hotlist_risks(items, top_n=len(FINANCE_RISK_LEXICON))
    categories = {}
    for p in report.get("points") or []:
        if isinstance(p, dict):
            categories[str(p.get("category") or "")] = {
                "level": str(p.get("level") or ""),
                "count": int(p.get("count") or 0),
                "media_n": int(p.get("media_n") or 0),
            }
    total = int(report.get("total_titles") or 0)
    hit = int(report.get("hit_n") or 0)
    return {
        "total_titles": total,
        "hit_n": hit,
        "hit_rate": round(hit / total * 100, 1) if total else 0.0,
        "categories": categories,
    }


def analyze_risk_trend(items_by_day, today, days=RISK_TREND_DAYS) -> Dict:
    """逐日预警趋势：今日日切片对比基准日 → 新增 / 升级 / 持续 / 降级 / 解除。

    items_by_day: {"YYYY-MM-DD": [item, ...]}（item 只认 title / source 字段）；
    today: "YYYY-MM-DD" 报告日。只对窗口 [today-days+1, today] 内有存档的自然日
    算画像；基准日 = 今日之前最近一个有存档的日子。没有基准日或今日无切片 →
    has_history=False（渲染层不出趋势行，不硬造变化）。
    今日存档 < RISK_TREND_MIN_SAMPLE 条 → low_sample=True（对比仅作提示）。
    """
    items_by_day = items_by_day if isinstance(items_by_day, dict) else {}
    today = str(today or "")
    try:
        today_d = datetime.date.fromisoformat(today)
    except ValueError:
        today_d = None
    day_rows = []
    if today_d is not None:
        for offset in range(max(1, int(days)) - 1, -1, -1):
            key = (today_d - datetime.timedelta(days=offset)).isoformat()
            slice_items = items_by_day.get(key)
            if not isinstance(slice_items, (list, tuple)) or not slice_items:
                continue
            prof = daily_risk_profile(slice_items)
            prof["date"] = key
            day_rows.append(prof)
    today_prof = next((p for p in day_rows if p.get("date") == today), None)
    baseline = next((p for p in reversed(day_rows) if str(p.get("date") or "") < today), None)
    has_history = bool(today_prof) and bool(baseline)

    changes = []
    if has_history:
        t_cats = today_prof.get("categories") or {}
        b_cats = baseline.get("categories") or {}
        known = sorted(set(t_cats) | set(b_cats),
                       key=lambda c: _RISK_CATEGORY_ORDER.get(c, 99))   # 词表序，确定性
        for cat in known:
            t, b = t_cats.get(cat), b_cats.get(cat)
            if t and not b:
                changes.append({"category": cat, "status": RISK_STATUS_NEW,
                                "level": t["level"], "baseline_level": None,
                                "count": t["count"], "media_n": t["media_n"]})
            elif t and b:
                rt = _RISK_LEVEL_RANK.get(t["level"], 0)
                rb = _RISK_LEVEL_RANK.get(b["level"], 0)
                status = (RISK_STATUS_UP if rt > rb else
                          RISK_STATUS_DOWN if rt < rb else RISK_STATUS_ONGOING)
                changes.append({"category": cat, "status": status,
                                "level": t["level"], "baseline_level": b["level"],
                                "count": t["count"], "media_n": t["media_n"]})
            elif b and not t:
                changes.append({"category": cat, "status": RISK_STATUS_CLEARED,
                                "level": None, "baseline_level": b["level"],
                                "count": b["count"], "media_n": b["media_n"]})
        changes.sort(key=lambda c: (
            _RISK_STATUS_ORDER.get(c["status"], 9),
            -_RISK_LEVEL_RANK.get(c.get("level") or c.get("baseline_level") or "", 0),
            _RISK_CATEGORY_ORDER.get(c["category"], 99)))

    counts = {s: sum(1 for c in changes if c["status"] == s) for s in _RISK_STATUS_ORDER}
    today_n = int((today_prof or {}).get("total_titles") or 0)
    low_sample = has_history and today_n < RISK_TREND_MIN_SAMPLE
    # 两套同义异文的归纳，渲染层按行分配（态势行用 phrase、提鲜结论用 brief、
    # 趋势行自己列逐类明细），避免同一栏里两个单元格逐字重复同一句长文
    # （栏内重复审计口径：≥14 字且 ≥8 个汉字的片段同栏出现两次即告警）。
    # 低样本提示由各渲染行自行追加措辞，这里不拼进 phrase/brief。
    if not has_history:
        trend_phrase = trend_brief = ""
    elif not changes:
        trend_phrase = "较最近存档日无类别变化"
        trend_brief = "按日对比无类别变化"
    else:
        order = (RISK_STATUS_NEW, RISK_STATUS_UP, RISK_STATUS_ONGOING,
                 RISK_STATUS_DOWN, RISK_STATUS_CLEARED)
        trend_phrase = "较最近存档日 " + "、".join(
            f"{s} {counts[s]} 类" for s in order if counts[s])
        trend_brief = "按日对比 " + "、".join(
            f"{s} {counts[s]}" for s in order if counts[s])

    return {
        "enabled": True,
        "has_history": has_history,
        "method": RISK_TREND_METHOD,
        "window_days": max(1, int(days)),
        "today": today,
        "baseline_date": (baseline or {}).get("date"),
        "days": day_rows,
        "today_n": today_n,
        "low_sample": low_sample,
        "changes": changes,
        "new_n": counts[RISK_STATUS_NEW],
        "upgraded_n": counts[RISK_STATUS_UP],
        "ongoing_n": counts[RISK_STATUS_ONGOING],
        "downgraded_n": counts[RISK_STATUS_DOWN],
        "cleared_n": counts[RISK_STATUS_CLEARED],
        "trend_phrase": trend_phrase,
        "trend_brief": trend_brief,
        "note": "状态是词表命中的日间对比，不是事件演化事实，也不是发生概率；不构成投资建议",
    }


def risk_posture(risk_report, sentiment_agg=None, trend=None) -> Dict:
    """今日风险态势：无命中 / 低等级的平时日子也给出一行确定性分析结论。

    只组合三个同源结果里已有的数字——窗口内预警风险点（risk_report）、情绪总览
    （sentiment_agg）、逐日预警趋势（trend）；不新增取数，不造方向或概率。
    verdict 是态势定调（AI 研判 / 提鲜 / 渲染共用同一句）；text 是全量版渲染句，
    plain_text 是入门版压缩句。
    """
    risk = risk_report if isinstance(risk_report, dict) else {}
    points = [p for p in (risk.get("points") or []) if isinstance(p, dict)]
    total_titles = int(risk.get("total_titles") or 0)
    agg = sentiment_agg if isinstance(sentiment_agg, dict) else {}
    trend = trend if isinstance(trend, dict) else {}
    mood = str(agg.get("label") or "") if agg.get("has_data") else ""
    levels = [str(p.get("level") or "") for p in points]

    if not points:
        calm = True
        verdict = "无预警命中，留意报道" if mood == "偏空" else "无预警命中，保持观察"
    elif RISK_LEVEL_HIGH in levels:
        calm = False
        verdict = "有【高】级预警，优先核证据"
    elif RISK_LEVEL_MID in levels:
        calm = False
        verdict = "有【中】级预警，关注传播面"
    else:
        calm = False
        verdict = "仅关注级命中，保持观察"

    if trend.get("has_history"):
        trend_phrase = str(trend.get("trend_phrase") or "")
    else:
        trend_phrase = "历史存档不足，暂不按日对比"

    # 「未命中风险词表」的披露与「等级是传播度」的注记由栏内「预警风险点」头行负责；
    # 态势行只讲情绪面定调 + 趋势对比。verdict 控制在 13 字内，与「🦑 AI帮你提鲜」
    # 结论里引用的同一句话构成 <14 字的公共片段，不触发栏内重复审计
    # （口径：≥14 字且 ≥8 个汉字的片段同栏出现两次即告警）。
    mood_part = f"情绪面{mood}，" if mood else ""
    text = f"{mood_part}{verdict} · {trend_phrase}"
    plain_text = f"{mood_part}{verdict}"
    return {
        "has_data": bool(total_titles or points),
        "calm": calm,
        "verdict": verdict,
        "trend_phrase": trend_phrase,
        "text": text,
        "plain_text": plain_text,
        "mood_label": mood,
        "note": "词表启发式的态势归纳，不是校准概率；不构成投资建议",
    }


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
        Dict: 词汇项（`vocabulary_terms`）+ 概念映射 + 兼容用的启发式标题情绪评分。
        `positive_probability` / `negative_probability` 是旧接口派生值，并非校准概率，
        不应用作涨跌概率或投资判断。
    """
    title = str(title or "")
    content = str(content or "")
    text = title + " " + content[:500]
    # 热点榜词汇统计严格只读标题；正文只保留给旧的概念 / 情绪兼容接口使用。
    vocabulary_terms = extract_finance_vocabulary(title)
    
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
        "vocabulary_terms": vocabulary_terms,
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
    """为热点榜标题附加本地词汇分析，并写入可复现的词汇汇总。"""
    if not isinstance(mainland_data, dict):
        return mainland_data

    headlines = mainland_data.get("headlines", [])
    if not isinstance(headlines, list):
        return mainland_data

    for headline in headlines:
        if isinstance(headline, dict) and "title" in headline:
            if not isinstance(headline.get("finance_analysis"), dict):
                headline["finance_analysis"] = analyze_finance_item(
                    headline.get("title", ""), headline.get("content", "")
                )

    mainland_data["finance_analysis_summary"] = summarize_hotlist_vocabulary(headlines)
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
        print(f"   词汇: {', '.join(result['vocabulary_terms'][:8]) or '无有效词条'}")
        print(f"   规则情绪标签: {result['sentiment_class']} (词典得分: {result['sentiment_score']:.4f}，非校准概率)")
        print()


if __name__ == "__main__":
    test_analyzer()
