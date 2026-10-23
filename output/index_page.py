"""指数限定的全页拼版：保持栏目顺序，不复用个股/港股专属模型的结论。

🔙 2026-10-23 已回滚为**纯港股日报**：本模块默认不再被调用。
`output/pipeline.py:_index_page_enabled()` 只在显式 `OCTOPUS_INDEX_PAGE=1` 时为真，
关闭时既不采集 9 指数（无 `index_checks` 契约），也不分流到本文件，页面回到原港股口径。
代码保留以便一键恢复；回归见 tests/test_index_page.py（默认关闭 + 开启后口径不变）。
"""
from html import escape
from index_crosscheck import SPECS, render as render_crosscheck
from strategy_quant import _kit_table, _kit_kv


def _disclosure(kit, text):
    # 缺数、证据不足与风险边界是实质披露，入门版也不能隐藏。
    return _kit_kv(kit, [("分析边界", escape(text))])

# 保留原栏目角色；改变不适用于指数的产品分类名称，避免虚构债券/CTA/套利收益。
# 2026-10-23「量化分析总览」（QUANT FORECAST）整栏下线，映射同步移除。
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


def _num(value, pct=False):
    return '—' if value is None else f'{value:.2f}' + ('%' if pct else '')


def _table(rows, kit, columns):
    cells = []
    for r in rows:
        usable = r.get('usable', False)
        line = [escape(r['market'] + ' · ' + r['name']),
                escape(r.get('as_of') or r.get('date') or r.get('overseas_date') or r.get('mainland_date') or '暂缺')]
        for key, label in columns:
            value = r.get(key) if usable else None
            line.append(_num(value, key.startswith('ret_') or key in ('vol_20', 'max_dd_60', 'win_20'))
                        if value is None or isinstance(value, (int, float)) else escape(str(value)))
        line.append(escape(r.get('status', '暂缺')))
        cells.append(line)
    return _kit_table(kit, ['指数', '交易日'] + [c[1] for c in columns] + ['状态'], cells)


def relative_rows(rows):
    """只对同市场、同截止日、有完整20日收益的指数排序，不混合隔夜时点。"""
    groups = {}
    for r in rows:
        if r.get('usable') and r.get('ret_20d') is not None:
            groups.setdefault((r['market'], r['as_of']), []).append(r)
    out = []
    for (market, day), group in groups.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda r: r['ret_20d'], reverse=True)
        for rank, r in enumerate(ordered, 1):
            out.append([escape(market), escape(day), str(rank), escape(r['name']),
                        _num(r['ret_20d'], True), _num(r['ret_20d'] - ordered[-1]['ret_20d'])])
    return out


def build_parts(rows, kit, order, *, calendar=None, date_str=None):
    # 即使整个接口断线，也保留全部标的和全部栏目，不静默回退到旧港股页面。
    lookup = {r.get('symbol'): r for r in rows}
    rows = [lookup.get(symbol, dict(market=m, name=n, symbol=symbol,
             date=None, as_of=None, status='暂缺', usable=False))
            for m, n, symbol, _ in SPECS]
    rows.sort(key=lambda r: ('A股', '港股', '美股').index(r['market']))
    checked = [r for r in rows if r.get('usable')]
    backups = [r for r in checked if r.get('is_backup')]
    cover_note = f'（备用源启用 {len(backups)} 个）' if backups else ('（主源供数）' if checked else '')
    sections = []
    scope = ('分析标的仅限A股、港股、美股指数；各市场按当地最近已收盘日观察，不视为同一时刻。'
             '采用单源未复权已收盘日线计算指标（Yahoo主源优先，失败时自动切换备用源，不做多源交叉核验）。'
             '信号为规则状态，不是未来概率、策略净值或交易建议。')
    for key in order:
        if key not in TITLES:
            continue
        note = ''
        if key == 'MARKET REVIEW':
            body = render_crosscheck(rows, kit)
        elif key in FACTOR_LIMITS:
            body = _kit_table(kit, ['市场指数范围', '因子状态', '处理'],
                [[escape(m + '：' + '、'.join(r['name'] for r in rows if r['market'] == m)),
                  '证据不足', '暂停评分与方向归因'] for m in ('A股', '港股', '美股')])
            note = FACTOR_LIMITS[key]
        elif key == 'ECON CALENDAR':
            body = kit.calendar_block(calendar, date_str=date_str) if calendar and calendar.get('status') == 'success' else ''
            if not body:
                body = _disclosure(kit, '暂无可核查事件日程；不补造事件日期或影响概率。')
            note = '日程仅作三地指数的背景窗口；未经指数级事件研究，不判定正负影响。'
        elif key in ('FORECAST', 'SUMMARY'):
            body = _kit_kv(kit, [('分析范围', 'A股 / 港股 / 美股 · ' + str(len(rows)) + '个指数'),
                                 ('数据覆盖', str(len(checked)) + '/' + str(len(rows)) + '个指数最新收盘可用' + cover_note),
                                 ('判断边界', '缺数或过期的指数暂停判断；不同市场不混排；不输出未经回测校准的涨跌概率')])
            body += _table(rows, kit, [('trend', '趋势'), ('momentum_signal', '20日动量')])
            note = scope
        elif key in ('SECTOR ROTATION', 'INDUSTRY ROTATION', 'STRATEGY ARBITRAGE'):
            ranks = relative_rows(rows)
            body = _kit_table(kit, ['市场', '交易日', '排名', '指数', '20日收益', '相对组内末位差(百分点)'], ranks) if ranks else _disclosure(kit, '同市场、同截止日、有效20日收益的指数不足两个，暂停比较。')
            note = ('仅市场内部指数相对强弱；不代表行业轮动持仓、市场中性组合或可执行套利。'
                    '指数成分可能重叠，收益差不等于无风险价差；不生成买卖配对。')
        elif key in ('TREND TRACKING', 'UZI TREND', 'STRATEGY CTA', 'WEEKLY FORECAST'):
            body = _table(rows, kit, [('ma20', 'MA20'), ('ma60', 'MA60'), ('trend', '均线状态'), ('trend_signal', '规则观察')])
            note = ('收盘>MA20>MA60为多头排列，反之为空头排列，其余震荡。样本不足60根不判排列。'
                    '原港股七日预测不外推到其他指数；这里展示当前条件信号，不编造未来逐日点位或概率。')
        elif key == 'STRATEGY BOND':
            body = _table(rows, kit, [('vol_20', '20日年化波动'), ('max_dd_60', '60根收盘最大回撤')])
            note = '防守观察以指数自身风险衡量；不引入国债ETF或债基替代指数。不提供未经回测的仓位比例或止损点。'
        elif key in ('STRATEGY EQUITY', 'STRATEGY READ'):
            body = _table(rows, kit, [('ret_5d', '5日收益'), ('ret_20d', '20日收益'), ('ret_60d', '60日收益'), ('momentum_signal', '动量状态')])
            note = '20日收益>0标正动量，否则标非正动量。基准收益不是选股策略收益；未包含成本、换仓及样本外检验。'
        else:  # 总览两栏使用一致的指数级收益与风险口径
            body = _table(rows, kit, [('ret_1d', '日收益'), ('ret_20d', '20日收益'), ('ret_60d', '60日收益'), ('vol_20', '年化波动'), ('max_dd_60', '最大回撤')])
            note = ('收益需N+1根收盘；波动需20个日收益，样本标准差×√252；回撤需完整60根收盘。'
                    '缺数不外推，不同交易日不组成同一截面。')
        if note:
            body += _disclosure(kit, note)
        sections.append((key, TITLES[key], body, kit.badge('指数量化', 'ai'), ''))
    # 单源直取（备用源待命），不将9只指数冒充9个独立来源，也不打开当天新闻源门禁。
    has_data = any(r.get('as_of') or r.get('date') or r.get('close') is not None
                   or r.get('overseas_date') or r.get('mainland_date') for r in rows)
    return dict(sections=sections, total=1, today_n=0, content_n=int(has_data),
                market={}, poem=None, bagua_html='', beginner_tips_html='')
