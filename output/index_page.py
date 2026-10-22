"""指数限定的全页拼版：保持栏目顺序，不复用个股/港股专属模型的结论。"""
from html import escape
from index_crosscheck import SPECS, render as render_crosscheck
from strategy_quant import _kit_table, _kit_kv


def _disclosure(kit, text):
    # 缺数、证据不足与风险边界是实质披露，入门版也不能隐藏。
    return (
        '<div style="margin:6px 0;padding:6px 9px;background:#F7F7F9;'
        'border-left:3px solid #8E8E93;font-size:12px;line-height:1.6;color:#333">'
        f'<b style="color:#111">分析边界</b>：{escape(text)}</div>'
    )


# 保留原栏目角色；改变不适用于指数的产品分类名称，避免虚构债券/CTA/套利收益。
TITLES = {
    'FORECAST': '今日预判 · 三地指数',
    'MARKET REVIEW': '【及时秋刀鱼】三地指数行情复盘',
    'ECON CALENDAR': '时间节点 · 三地指数事件窗口',
    'POLICY SHOCK': '【深海肥蓝鲸】三地指数政策因子',
    'FED TREND': '美联储因子 · 三地指数',
    'GEO TREND': '地缘因子 · 三地指数',
    'RETAIL SENTIMENT': '散户情绪因子 · 三地指数',
    'TREND TRACKING': '【深海大鲨鱼】三地指数趋势跟踪',
    'MAINLAND HOTLIST': '【沸腾花蛤】三地指数热点因子',
    'MEDIA RISK': '【警戒爆炸豚】三地指数媒体风险',
    'NEWS SENTIMENT': '【亮亮灯光鱿鱼】三地指数新闻情绪',
    'QUANT FORECAST': '【蜉蝣天地水母】三地指数量化总览',
    'LIQUIDITY FLOW': '资金流动性 · 三地指数',
    'WEEKLY FORECAST': '每日趋势量化推演 · 三地指数',
    'STRATEGY READ': '策略研判 · 三地指数',
    'UZI TREND': '【游资剑鱼】三地指数技术信号',
    'SECTOR ROTATION': '【滚滚翻车鱼】三地指数相对强弱',
    'INDUSTRY ROTATION': '【巡游旗鱼】三地指数轮动观察',
    'STRATEGY OVERVIEW': '【策略总览】三地指数量化策略全景',
    'STRATEGY EQUITY': '【权益多头】三地指数动量观察',
    'STRATEGY BOND': '【防守观察】三地指数风险控制',
    'STRATEGY CTA': '【趋势策略】三地指数均线信号',
    'STRATEGY ARBITRAGE': '【相对价值】三地指数收益差观察',
    'SUMMARY': '总结 · 三地指数',
}

FACTOR_LIMITS = {
    'POLICY SHOCK': '缺少按指数覆盖范围归因、带发布时间的政策证据；不将A股政策分直接套用于港股或美股。',
    'FED TREND': '缺少事件时间、利率预期变化与指数响应窗口的统一样本；不生成三地涨跌概率。',
    'GEO TREND': '缺少可核查事件及指数暴露权重；不将泛化地缘标题转换为指数风险分。',
    'RETAIL SENTIMENT': '缺少按指数归因的境内外社区样本及基线；个股帖子不等于指数情绪。',
    'MAINLAND HOTLIST': '缺少三地指数层面的热点覆盖率与发布时间核验；个股热度不直接汇总为指数因子。',
    'MEDIA RISK': '缺少指数成分权重与事件归因；证据不足不代表没有风险。',
    'NEWS SENTIMENT': '缺少按指数归因的新闻样本及来源去重；不复用港股个股情绪或虚构美股因子。',
    'LIQUIDITY FLOW': '指数本身没有可直接相加的资金净流入；缺少一致口径的成分成交、ETF申赎或衍生品数据。不将南向资金替代三地流动性。',
}

_CARD_OPEN = (
    '<table width="100%" cellpadding="0" cellspacing="0" '
    'style="width:100%;table-layout:fixed;border-collapse:collapse;margin:8px 0;'
    'background:#fff;border:1px solid #E5E5E8;font-size:13px">'
)


def _num(value, pct=False):
    return '—' if value is None else f'{value:.2f}' + ('%' if pct else '')


def _card_list(entries):
    rows_html = []
    for idx, (title, pairs) in enumerate(entries):
        border = '' if idx == len(entries) - 1 else 'border-bottom:1px solid #EDEDEF;'
        kvs = ' ｜ '.join(f'{escape(str(label))} {escape(str(value))}' for label, value in pairs)
        rows_html.append(
            f'<div style="padding:5px 0;{border}color:#222">'
            f'<b style="color:#111">{escape(title)}</b><br>{kvs}</div>'
        )
    return (
        '<div style="margin:6px 0;padding:4px 10px;background:#fff;border:1px solid #E5E5E8;'
        f'border-radius:8px;font-size:12px;line-height:1.62;color:#222">{"".join(rows_html)}</div>'
    )


def _table(rows, kit, columns):
    """窄屏微信友好的逐指数紧凑卡片；控制体积以确保全主题不超 PushPlus 分条上限。"""
    entries = []
    for r in rows:
        usable = r.get('usable', False)
        day = r.get('as_of') or r.get('overseas_date') or r.get('mainland_date') or '暂缺'
        title = f"{r['market']} · {r['name']}（{day} · {r.get('status', '双源缺失')}）"
        values = []
        for key, label in columns:
            value = r.get(key) if usable else None
            shown = (
                _num(value, key.startswith('ret_') or key in ('vol_20', 'max_dd_60', 'win_20'))
                if value is None or isinstance(value, (int, float))
                else str(value)
            )
            values.append((label, shown))
        entries.append((title, values))
    return _card_list(entries)


def relative_rows(rows):
    """仅在同一市场、同一交易日、至少两只通过核验的指数间比较20日收益。"""
    groups = {}
    for r in rows:
        if r.get('usable') and r.get('ret_20d') is not None and r.get('as_of'):
            groups.setdefault((r['market'], r['as_of']), []).append(r)
    out = []
    for (market, day), items in groups.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda x: x['ret_20d'], reverse=True)
        for rank, item in enumerate(ordered, 1):
            spread = item['ret_20d'] - ordered[-1]['ret_20d']
            out.append([escape(market), escape(day), str(rank), escape(item['name']),
                        f"{item['ret_20d']:.2f}", f"{spread:.2f}"])
    return out


def _normalize(rows):
    by_symbol = {r.get('symbol'): r for r in (rows or [])}
    order = {'A股': 0, '港股': 1, '美股': 2}
    full = [by_symbol.get(s) or dict(market=m, name=n, symbol=s, secid=c,
            status='双源缺失', usable=False) for m, n, s, c in SPECS]
    return sorted(full, key=lambda r: order.get(r['market'], 9))


def build_parts(rows, kit, order, *, calendar=None, date_str=None):
    rows = _normalize(rows)
    passed = [r for r in rows if r.get('usable')]
    hist_sources = {r.get('history_source') or 'Yahoo' for r in passed}
    hist_note = (
        '仅最新收盘经境内外核验，历史指标取已核验未复权指数日线（Yahoo 优先，缺序列时取境内未复权日K）；历史未逐日双源核验。'
        if any(not str(s).startswith('Yahoo') for s in hist_sources)
        else '仅最新收盘经境内外核验，历史指标取Yahoo未复权日线；历史未逐日双源核验。'
    )
    scope = (
        '分析标的仅限A股、港股、美股指数；各市场按当地最近已收盘日观察，不视为同一时刻。'
        + hist_note
        + '信号为规则状态，不是未来概率、策略净值或交易建议。'
    )
    summary_head = _kit_kv(kit, [
        ('分析范围', 'A股 / 港股 / 美股 · 9个指数'),
        ('数据覆盖', f'{len(passed)}/9个最新收盘通过双源核验'),
        ('判断边界', '未通过核验的指数暂停判断；不同市场不混排；不输出未经回测校准的涨跌概率'),
    ])
    sections = []
    for key in order:
        note = None
        if key == 'MARKET REVIEW':
            body = render_crosscheck(rows, kit)
        elif key in FACTOR_LIMITS:
            body = _card_list([
                (m, [
                    ('指数范围', '、'.join(r['name'] for r in rows if r['market'] == m)),
                    ('状态', '证据不足 · 暂停评分与方向归因'),
                ])
                for m in ('A股', '港股', '美股')
            ])
            note = FACTOR_LIMITS[key]
        elif key == 'ECON CALENDAR':
            body = kit.calendar_block(calendar, date_str=date_str) if calendar and calendar.get('status') == 'success' else ''
            note = '日程仅作三地指数的背景窗口；未经指数级事件研究，不判定正负影响。'
        elif key in ('FORECAST', 'SUMMARY'):
            body = summary_head + _table(rows, kit, [('trend', '趋势'), ('ret_20d', '20日动量')])
            note = scope
        elif key in ('SECTOR ROTATION', 'INDUSTRY ROTATION', 'STRATEGY ARBITRAGE'):
            ranks = relative_rows(rows)
            body = (
                _card_list([
                    (
                        f'{row[0]} · {row[3]}',
                        [
                            ('交易日', row[1]),
                            ('组内排名', row[2]),
                            ('20日收益', row[4] + '%'),
                            ('较组内末位差', row[5] + '个百分点'),
                        ],
                    )
                    for row in ranks
                ])
                if ranks
                else _disclosure(kit, '同市场、同截止日、有效20日收益的指数不足两个，暂停比较。')
            )
            note = (
                '仅市场内部指数相对强弱；不代表行业轮动持仓、市场中性组合或可执行套利。'
                '指数成分可能重叠，收益差不等于无风险价差；不生成买卖配对。'
            )
        elif key in ('TREND TRACKING', 'UZI TREND', 'STRATEGY CTA', 'WEEKLY FORECAST'):
            body = _table(rows, kit, [('ma20', 'MA20'), ('ma60', 'MA60'), ('trend', '均线状态'), ('trend_signal', '规则观察')])
            note = (
                '收盘>MA20>MA60为多头排列，反之为空头排列，其余震荡。样本不足60根不判排列。'
                '原港股七日预测不外推到其他指数；这里展示当前条件信号，不编造未来逐日点位或概率。'
            )
        elif key == 'STRATEGY BOND':
            body = _table(rows, kit, [('vol_20', '20日年化波动'), ('max_dd_60', '60根收盘最大回撤')])
            note = '防守观察以指数自身风险衡量；不引入国债ETF或债基替代指数。不提供未经回测的仓位比例或止损点。'
        elif key in ('STRATEGY EQUITY', 'STRATEGY READ'):
            body = _table(rows, kit, [('ret_5d', '5日收益'), ('ret_20d', '20日收益'), ('ret_60d', '60日收益'), ('momentum_signal', '动量状态')])
            note = '20日收益>0标正动量，否则标非正动量。基准收益不是选股策略收益；未包含成本、换仓及样本外检验。'
        else:  # 总览两栏使用一致的指数级收益与风险口径
            body = _table(rows, kit, [('ret_1d', '日收益'), ('ret_20d', '20日收益'), ('ret_60d', '60日收益'), ('vol_20', '年化波动'), ('max_dd_60', '最大回撤')])
            note = (
                '收益需N+1根收盘；波动需20个日收益，样本标准差×√252；回撤需完整60根收盘。'
                '缺数不外推，不同交易日不组成同一截面。'
            )
        if note:
            body += _disclosure(kit, note)
        sections.append((key, TITLES[key], body, kit.badge('指数量化', 'ai'), ''))
    # 两个供应商不冒充18个独立来源；仅当通过双源核验且确实命中报告当日收盘时计入 today_n，
    # 隔日快照与未核验单源保持 today_n=0，绝不虚开 --push-only 门禁。
    today_iso = (
        f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
        if date_str and len(str(date_str)) == 8 and str(date_str).isdigit()
        else None
    )
    source_present = [any(r.get(k + '_date') for r in rows) for k in ('overseas', 'mainland')]
    today_n = sum(
        1 for k in ('overseas', 'mainland')
        if today_iso and any(r.get('usable') and r.get(k + '_date') == today_iso for r in rows)
    )
    return dict(sections=sections, total=2, today_n=today_n, content_n=sum(source_present),
                market={}, poem=None, bagua_html='', beginner_tips_html='')
