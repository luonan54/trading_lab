from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.models import TechnicalFeatures

PRODUCT_NAME = "Local Stock Lab"
ET = ZoneInfo("America/New_York")
MARKET_HEADERS = "<th>Price</th><th>Today %</th><th>15m %</th><th>Today Open</th>"


def render_market_price(value: float | None) -> str:
    if value is None:
        return "<span class='muted' title='Unavailable for this snapshot'>—</span>"
    return f"${value:,.2f}"


def render_market_change(value: float | None) -> str:
    if value is None:
        return "<span class='muted' title='Unavailable for this snapshot'>—</span>"
    css_class = "delta-positive" if value >= 0 else "delta-negative"
    direction = "▲" if value >= 0 else "▼"
    return f"<span class='{css_class}'>{direction} {abs(value):.2f}%</span>"


def render_market_cells(features: TechnicalFeatures) -> str:
    values = (
        ("price", render_market_price(features.current_price)),
        ("today", render_market_change(features.today_return_pct)),
        ("15m", render_market_change(features.return_15m_pct)),
        ("open", render_market_price(features.session_open)),
    )
    return "".join(
        f"<td class='market-cell' data-market-field='{name}' "
        f"title='Latest equity snapshot; not a live quote'>{value}</td>"
        for name, value in values
    )


def format_timestamp_et(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ET).strftime("%Y-%m-%d %I:%M %p ET")


def shared_page_styles() -> str:
    return (
        ".market-cell{white-space:nowrap;font-variant-numeric:tabular-nums}"
        ".market-cell .delta-positive{color:#087443}.market-cell .delta-negative{color:#ba2525}"
        ":root{--li-blue:#0A66C2;--li-blue-dark:#004182;--li-blue-bright:#378FE9;"
        "--li-blue-soft:#70B5F9;--li-blue-pale:#E8F3FF;--navy:#0B1F35;"
        "--navy-soft:#173A5E;--shell-text:#10243D;--shell-muted:#60738A;"
        "--shell-border:rgba(80,113,148,.18);--glass:rgba(255,255,255,.82);"
        "--surface-shadow:0 16px 34px rgba(33,75,112,.08),inset 0 1px 0 #fff;"
        "--apple-font:-apple-system,BlinkMacSystemFont,'SF Pro Display','SF Pro Text',"
        "'Helvetica Neue',Arial,sans-serif;--apple-mono:'SFMono-Regular',SFMono-Regular,"
        "ui-monospace,Menlo,monospace;--glass-panel:rgba(255,255,255,.58);"
        "--glass-panel-strong:rgba(255,255,255,.74);"
        "--glass-edge:rgba(255,255,255,.72);"
        "--glass-shadow:0 24px 70px rgba(23,46,72,.14),"
        "inset 0 1px 0 rgba(255,255,255,.82)}"
        "html{min-width:320px;min-height:100%}body{min-width:320px;min-height:100vh;"
        "background:radial-gradient(circle at 18% 12%,rgba(218,237,255,.64),"
        "transparent 25rem),radial-gradient(circle at 88% 88%,rgba(10,102,194,.28),"
        "transparent 32rem),linear-gradient(145deg,#b8c2cf 0%,#9facbd 100%);"
        "color:var(--shell-text)}.app-viewport{min-height:100vh;padding:22px}"
        "main.app-shell{width:min(1540px,100%);max-width:1540px;min-height:"
        "calc(100vh - 44px);margin:0 auto;padding:0;overflow:hidden;position:relative;"
        "border:1px solid rgba(255,255,255,.7);border-radius:36px;background:"
        "radial-gradient(circle at 88% 4%,rgba(112,181,249,.24),transparent 31rem),"
        "linear-gradient(135deg,rgba(246,251,255,.97),rgba(224,239,253,.94));"
        "box-shadow:0 30px 70px rgba(10,35,64,.24),inset 0 1px 0 rgba(255,255,255,.94)}"
        "main.app-shell::before{content:'';width:520px;height:520px;position:absolute;"
        "top:-330px;left:34%;border:1px solid rgba(55,143,233,.16);border-radius:50%;"
        "box-shadow:0 0 0 70px rgba(55,143,233,.03),0 0 0 140px rgba(55,143,233,.02);"
        "pointer-events:none}.page-shell{width:min(1400px,calc(100% - 48px));margin:0 auto;"
        "padding:24px 0 30px;position:relative;z-index:1}.page-hero{min-height:205px;"
        "overflow:visible;position:relative;margin:0 0 42px;padding:34px 38px 27px;"
        "border:1px solid rgba(255,255,255,.88);border-radius:25px;color:var(--shell-text);"
        "background:radial-gradient(circle at 89% 12%,rgba(55,143,233,.31),"
        "transparent 22rem),linear-gradient(112deg,rgba(255,255,255,.9),"
        "rgba(219,238,255,.68));box-shadow:0 18px 45px rgba(33,75,112,.1),"
        "inset 0 1px 0 #fff}.page-hero::after{content:'';width:270px;height:270px;"
        "position:absolute;right:-80px;bottom:-190px;border:1px solid rgba(10,102,194,.18);"
        "border-radius:50%;box-shadow:0 0 0 42px rgba(10,102,194,.03),"
        "0 0 0 84px rgba(10,102,194,.02);pointer-events:none}.page-hero-top{display:flex;"
        "align-items:flex-start;justify-content:space-between;gap:30px;position:relative;"
        "z-index:1}.page-hero .eyebrow{display:flex;align-items:center;gap:10px;"
        "color:var(--li-blue-dark);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
        "font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}"
        ".page-hero h1{margin:12px 0 0;color:var(--navy);font-size:clamp(36px,5vw,58px);"
        "font-weight:500;letter-spacing:-.055em;line-height:1}.page-hero p{max-width:800px;"
        "margin:13px 0 0;color:#566D84;font-size:14px;line-height:1.65}.page-hero "
        ".hero-meta,.page-hero .header-meta{text-align:right}.page-hero .feed-badge,"
        ".page-hero .refresh-badge,.page-hero .update-badge{display:inline-block;"
        "border:1px solid #C9DBEA;border-radius:999px;color:var(--li-blue-dark);"
        "background:rgba(255,255,255,.78);box-shadow:inset 0 1px 0 #fff}"
        ".page-hero .feed-dot{background:var(--li-blue-bright);box-shadow:"
        "0 0 8px rgba(55,143,233,.72)}.page-hero .refresh-badge small{color:#71869B}"
        ".primary-nav{width:fit-content;max-width:100%;display:flex;align-items:center;"
        "justify-content:center;flex-wrap:wrap;gap:3px;margin:26px auto -47px;padding:5px;"
        "position:relative;z-index:4;border:1px solid rgba(255,255,255,.8);"
        "border-radius:999px;background:rgba(255,255,255,.78);box-shadow:"
        "0 8px 24px rgba(32,73,111,.1),inset 0 1px 0 #fff;backdrop-filter:blur(18px)}"
        ".primary-nav a,.primary-nav button{height:37px;display:flex;align-items:center;"
        "padding:0 14px;border:0;border-radius:999px;color:#51677F;background:transparent;"
        "font-size:11px;font-weight:750;text-decoration:none;transition:color .16s,"
        "background .16s,transform .16s}.primary-nav a:hover,.primary-nav button:hover{"
        "color:var(--li-blue-dark);background:rgba(232,243,255,.9);transform:translateY(-1px)}"
        ".primary-nav a[aria-current='page']{color:#fff;background:linear-gradient(135deg,"
        "var(--li-blue-dark),var(--li-blue));box-shadow:0 8px 18px rgba(10,102,194,.24)}"
        ".card,.section,.kpi-card,.summary,.proposal{border:1px solid "
        "rgba(255,255,255,.9);border-radius:20px;background:var(--glass);box-shadow:"
        "var(--surface-shadow);backdrop-filter:blur(16px)}.card,.section,.proposal{"
        "margin:15px 0;padding:22px}.kpi-grid,.summary-grid{gap:15px}.kpi-card,.summary{"
        "padding:18px 20px}.kpi-value,.summary strong{color:var(--li-blue-dark)}"
        ".card h2,.section h2,.proposal h3{color:var(--navy);letter-spacing:-.025em}"
        ".control-plane{overflow:hidden;position:relative;border-color:rgba(112,181,249,.2);"
        "color:#fff;background:radial-gradient(circle at 100% 0%,rgba(55,143,233,.32),"
        "transparent 16rem),linear-gradient(155deg,#102F50,#071828 72%);"
        "box-shadow:0 22px 40px rgba(5,24,43,.24)}.control-plane::before{content:'';"
        "position:absolute;inset:0;opacity:.22;background-image:linear-gradient("
        "rgba(112,181,249,.13) 1px,transparent 1px),linear-gradient(90deg,"
        "rgba(112,181,249,.13) 1px,transparent 1px);background-size:32px 32px;"
        "mask-image:linear-gradient(to bottom,black,transparent 74%);pointer-events:none}"
        ".control-plane>*{position:relative;z-index:1}.control-plane h2,"
        ".control-plane h3,.control-plane strong{color:#fff}.control-plane p,"
        ".control-plane .muted,.control-plane .scan-copy,.control-plane label,"
        ".control-plane label small{color:rgba(220,235,247,.76)}.control-plane .eyebrow{"
        "color:#8BC8F5}.control-plane .result{border:1px solid rgba(112,181,249,.18);"
        "background:rgba(255,255,255,.06)}.control-plane input,.control-plane select{"
        "color:var(--navy);background:#fff}.control-plane button{box-shadow:"
        "0 8px 18px rgba(10,102,194,.3)}.scan-toolbar.control-plane{padding:18px 20px;"
        "border-radius:18px}.architecture-panel .architecture li{color:#315B7F;"
        "border:1px solid rgba(112,181,249,.28);background:rgba(232,243,255,.94)}"
        ".view-nav{width:fit-content;max-width:100%;"
        "padding:5px;border:1px solid rgba(255,255,255,.86);border-radius:999px;"
        "background:rgba(255,255,255,.62);box-shadow:inset 0 1px 0 #fff;"
        "backdrop-filter:blur(16px)}.view-nav a{border:0;border-radius:999px;"
        "background:transparent}.view-nav a.active{background:linear-gradient(135deg,"
        "var(--li-blue-dark),var(--li-blue));box-shadow:0 7px 16px rgba(10,102,194,.2)}"
        ".app-shell input,.app-shell select{border-color:#C9DBEA;border-radius:11px;"
        "outline:none}.app-shell input:focus,.app-shell select:focus{border-color:"
        "var(--li-blue-bright);box-shadow:0 0 0 3px rgba(55,143,233,.12)}"
        ".app-shell button:not(.ticker-copy):not(.glossary-close):not(.glossary-open):not(.readiness-light){"
        "border-radius:999px;padding-left:16px;padding-right:16px}.table-wrap{"
        "overflow-x:auto;border:1px solid rgba(108,139,169,.13);border-radius:15px;"
        "background:rgba(255,255,255,.62)}.table-wrap table{background:transparent}"
        ".table-wrap th{color:#60758A;background:rgba(241,247,252,.82);font-family:"
        "ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px;letter-spacing:.06em;"
        "text-transform:uppercase}.table-wrap td{border-bottom-color:rgba(96,115,138,.12)}"
        ".table-wrap tbody tr:hover{background:rgba(232,243,255,.58)}.notice{border-radius:"
        "14px}.warning{border-radius:14px}.footer,.footer-note{color:#6D8196!important;"
        "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px!important;"
        "letter-spacing:.06em;text-transform:uppercase}.glossary-dialog{border-radius:22px;"
        "color:var(--shell-text);background:#F7FBFF}.glossary-head{background:"
        "linear-gradient(112deg,#fff,var(--li-blue-pale))}.glossary-dialog input[type='search']{"
        "border-color:#C9DBEA;border-radius:999px}.ticker-copy-status{border-radius:999px;"
        "background:var(--navy)}"
        "body{font-family:var(--apple-font);font-feature-settings:'kern' 1,'tnum' 1;"
        "-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}"
        "body::before{content:'';position:fixed;inset:-18%;z-index:-2;pointer-events:none;"
        "background:radial-gradient(circle at 18% 18%,rgba(255,255,255,.74),transparent 24%),"
        "radial-gradient(circle at 82% 20%,rgba(104,178,244,.38),transparent 28%),"
        "radial-gradient(circle at 72% 84%,rgba(0,65,130,.25),transparent 31%),"
        "linear-gradient(145deg,#dce5ee,#9dafc0);filter:blur(18px)}"
        ".app-viewport{position:relative;isolation:isolate}"
        "main.app-shell{border-color:var(--glass-edge);background:"
        "linear-gradient(145deg,rgba(248,252,255,.78),rgba(219,235,248,.64));"
        "box-shadow:0 34px 100px rgba(14,36,61,.27),"
        "inset 0 1px 0 rgba(255,255,255,.92);"
        "-webkit-backdrop-filter:blur(34px) saturate(150%);"
        "backdrop-filter:blur(34px) saturate(150%)}"
        ".page-hero{border-color:rgba(255,255,255,.8);background:"
        "radial-gradient(circle at 88% 8%,rgba(95,175,245,.32),transparent 22rem),"
        "linear-gradient(118deg,rgba(255,255,255,.72),rgba(222,239,253,.5));"
        "box-shadow:var(--glass-shadow);-webkit-backdrop-filter:blur(26px) saturate(155%);"
        "backdrop-filter:blur(26px) saturate(155%)}"
        ".page-hero h1{font-family:var(--apple-font);font-weight:600;letter-spacing:-.048em}"
        ".page-hero .eyebrow,.table-wrap th,.footer,.footer-note{"
        "font-family:var(--apple-mono)}"
        ".primary-nav,.view-nav{border-color:rgba(255,255,255,.78);"
        "background:rgba(245,249,252,.48);box-shadow:0 16px 38px rgba(28,59,89,.12),"
        "inset 0 1px 0 rgba(255,255,255,.9);"
        "-webkit-backdrop-filter:blur(24px) saturate(180%);"
        "backdrop-filter:blur(24px) saturate(180%)}"
        ".primary-nav a,.primary-nav button,.app-shell button,.app-shell input,"
        ".app-shell select{font-family:var(--apple-font)}"
        ".card,.section,.kpi-card,.summary,.proposal,.notice,.warning{"
        "border-color:var(--glass-edge);background:var(--glass-panel);"
        "box-shadow:var(--glass-shadow);-webkit-backdrop-filter:blur(22px) saturate(155%);"
        "backdrop-filter:blur(22px) saturate(155%)}"
        ".kpi-card,.summary{background:var(--glass-panel-strong)}"
        ".control-plane{border-color:rgba(187,222,250,.24);background:"
        "radial-gradient(circle at 96% 0%,rgba(79,165,239,.34),transparent 18rem),"
        "linear-gradient(145deg,rgba(11,35,59,.94),rgba(20,57,91,.84));"
        "-webkit-backdrop-filter:blur(24px) saturate(145%);"
        "backdrop-filter:blur(24px) saturate(145%)}"
        ".table-wrap{border-color:rgba(255,255,255,.7);background:rgba(255,255,255,.46);"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.86);"
        "-webkit-backdrop-filter:blur(18px) saturate(140%);"
        "backdrop-filter:blur(18px) saturate(140%)}"
        ".table-wrap th{background:rgba(239,246,252,.68)}"
        ".glossary-dialog{border:1px solid rgba(255,255,255,.78);"
        "background:rgba(247,251,255,.8);box-shadow:0 32px 100px rgba(8,28,48,.34);"
        "-webkit-backdrop-filter:blur(30px) saturate(165%);"
        "backdrop-filter:blur(30px) saturate(165%)}"
        ".glossary-dialog::backdrop{background:rgba(19,35,52,.32);"
        "-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}"
        ":root{--li-blue:#7C5CE5;--li-blue-dark:#6546C9;--li-blue-bright:#9C7AF2;"
        "--li-blue-soft:#C6B8FF;--li-blue-pale:#F2EEFF;--navy:#49386F;"
        "--navy-soft:#6C5A8F;--shell-text:#554A6D;--shell-muted:#817794;"
        "--shell-border:rgba(124,92,229,.18);--blue:#7C5CE5;--blue-dark:#6546C9;"
        "--dark:#6546C9;--bg:#F2EFF8;--surface:rgba(255,255,255,.76);"
        "--border:#DED6EF;--muted:#817794;--text:#554A6D;--secondary:#706783}"
        "body{color:var(--shell-text);background:radial-gradient(circle at 16% 12%,"
        "rgba(247,243,255,.88),transparent 25rem),radial-gradient(circle at 88% 88%,"
        "rgba(124,92,229,.23),transparent 32rem),linear-gradient(145deg,#DDD7E8,#BEB6D0)}"
        "body::before{background:radial-gradient(circle at 18% 18%,rgba(255,255,255,.82),"
        "transparent 24%),radial-gradient(circle at 82% 20%,rgba(184,160,255,.44),"
        "transparent 28%),radial-gradient(circle at 72% 84%,rgba(113,79,205,.24),"
        "transparent 31%),linear-gradient(145deg,#EBE7F3,#C7BFD5)}"
        "main.app-shell{background:linear-gradient(145deg,rgba(253,251,255,.82),"
        "rgba(235,229,247,.7));box-shadow:0 34px 100px rgba(55,42,82,.22),"
        "inset 0 1px 0 rgba(255,255,255,.92)}"
        ".page-hero{background:radial-gradient(circle at 88% 8%,"
        "rgba(178,151,250,.38),transparent 22rem),linear-gradient(118deg,"
        "rgba(255,255,255,.76),rgba(239,233,252,.58))}"
        ".page-hero p{color:#74698A}.page-hero .feed-badge,.page-hero .refresh-badge,"
        ".page-hero .update-badge{border-color:rgba(152,126,216,.3);"
        "color:var(--li-blue-dark);background:rgba(255,255,255,.62)}"
        ".primary-nav,.view-nav{background:rgba(250,247,255,.54);"
        "box-shadow:0 16px 38px rgba(72,53,105,.12),inset 0 1px 0 rgba(255,255,255,.9)}"
        ".primary-nav a,.primary-nav button{color:#776B8B}"
        ".primary-nav a:hover,.primary-nav button:hover{color:var(--li-blue-dark);"
        "background:rgba(241,235,255,.92)}"
        ".primary-nav a[aria-current='page'],.view-nav a.active{background:"
        "linear-gradient(135deg,var(--li-blue-dark),var(--li-blue));"
        "box-shadow:0 8px 20px rgba(101,70,201,.25)}"
        ".control-plane{border-color:rgba(232,225,255,.3);background:"
        "radial-gradient(circle at 96% 0%,rgba(205,190,255,.38),transparent 18rem),"
        "linear-gradient(145deg,rgba(135,105,218,.96),rgba(105,74,204,.9));"
        "box-shadow:0 22px 44px rgba(91,64,157,.25)}"
        ".control-plane::before{background-image:linear-gradient(rgba(232,225,255,.13) 1px,"
        "transparent 1px),linear-gradient(90deg,rgba(232,225,255,.13) 1px,"
        "transparent 1px)}.control-plane .eyebrow{color:#E7E0FF}"
        ".control-plane .result{border-color:rgba(235,228,255,.25)}"
        ".app-shell input,.app-shell select{border-color:#D8CFEA;color:#5D5272;"
        "background:rgba(255,255,255,.82)}.app-shell input:focus,.app-shell select:focus{"
        "border-color:var(--li-blue-bright);box-shadow:0 0 0 3px rgba(124,92,229,.13)}"
        ".table-wrap{background:rgba(255,255,255,.5)}"
        ".table-wrap th{color:#827693;background:rgba(247,243,252,.74)}"
        ".table-wrap td{color:#6B617C}.table-wrap tbody tr:hover{"
        "background:rgba(242,237,255,.72)}tr.current{background:rgba(242,237,255,.74)}"
        ".result{background:rgba(82,62,126,.9);color:#F8F5FF}"
        ".notice{background:rgba(246,242,255,.74);border-left-color:var(--li-blue);"
        "color:#675B7C}.architecture-panel .architecture li,.architecture li,"
        ".principles article,.two-col article,.feature-card,.technical,.advanced{"
        "border-color:rgba(124,92,229,.16);background:rgba(251,249,255,.6);color:#675B7C}"
        ".card h2,.section h2,.proposal h3,.feature-card h3,.principles h3,"
        ".two-col h3{color:var(--navy)}.metric span,.muted,.source-note{color:#817794}"
        ".glossary-dialog{color:var(--shell-text);background:rgba(251,249,255,.84);"
        "box-shadow:0 32px 100px rgba(58,43,91,.3)}"
        ".glossary-head{background:linear-gradient(112deg,rgba(255,255,255,.88),"
        "rgba(241,235,255,.82))}.glossary-term dt{color:var(--li-blue-dark)}"
        ".glossary-term dd{color:#6B617C}.ticker-copy:hover,.ticker-copy:focus-visible{"
        "color:var(--li-blue);outline-color:var(--li-blue)}"
        ".footer,.footer-note{color:#8A809B!important}"
        "@media(max-width:800px){.app-viewport{padding:0}"
        "main.app-shell{min-height:100vh;border-radius:0}.page-shell{width:min(100% - 20px,"
        "1400px);padding-top:10px}.page-hero{min-height:0;margin-bottom:36px;padding:28px 22px}"
        ".page-hero-top{display:block}.page-hero .hero-meta,.page-hero .header-meta{"
        "margin-top:16px;text-align:left}.page-hero h1{font-size:36px}.primary-nav{"
        "width:100%;justify-content:flex-start;flex-wrap:nowrap;overflow-x:auto;"
        "scrollbar-width:none}.primary-nav::-webkit-scrollbar{display:none}.card,.section,"
        ".proposal{padding:18px;border-radius:18px}.view-nav{width:100%;overflow-x:auto;"
        "flex-wrap:nowrap}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{"
        "animation-duration:.01ms!important;animation-iteration-count:1!important;"
        "scroll-behavior:auto!important}}"
    )

GLOSSARY_TERMS = (
    (
        "Technical State",
        "共有 6 个值：NORMAL（无特殊信号）、DIP_WATCH（回撤观察）、"
        "SELLING_EXHAUSTION（卖压衰减）、RIGHT_SIDE_REPAIR（右侧修复）、"
        "CALL_CANDIDATE（修复及确认条件齐全）、BREAKDOWN（支撑与结构破坏）。"
        "状态由已完成行情和固定规则计算，不是交易指令。",
    ),
    (
        "Next Step / 下一步",
        "当前页面策略视角下建议执行的分析工作流，不是交易指令。共有 5 种提示语气："
        "neutral（继续观察）、watch（重点留意）、wait（等待条件）、review（人工复核）、"
        "caution（风险优先）。同一 Technical State 在 All、Leader Long Call、Long-Term、"
        "High-Risk Growth、Short-Term 这 5 个页面中可显示不同下一步；Long-Term 和"
        "High-Risk 页面始终以手工 Long-Term Action 与风险上限为主。Dashboard 的"
        " Next Step 筛选值只来自当前策略页面，切换页面后会随语境变化。",
    ),
    (
        "Move Lane / 下一步动作分类",
        "把现有 Next Step、手工 Long-Term Action、Call Readiness 和 Options 资格压缩为"
        "一眼可扫的关注路线。它只安排复核顺序，不执行、不覆盖手工计划，也不产生新评分"
        "或资格规则。",
    ),
    (
        "OPTIONS_SETUP / 期权准备",
        "现有 Leader 工作流已支持合约预筛或合格方案复核；只表示 Review options setup "
        "或 Run options pre-screen，不表示立即执行。",
    ),
    (
        "LONG_TERM_PLAN / 长期计划",
        "已确认手工 ADD 计划与修复结构同时存在，可复核下一次分阶段增加；不是自动改变"
        "仓位。",
    ),
    (
        "THESIS_REVIEW / 逻辑复核",
        "手工计划要求逻辑复核，或尚未定义计划；先完成确认计划再看技术时点。",
    ),
    (
        "RISK_CAUTION / 风险优先",
        "结构破坏、PAUSE_ADD 或高风险上限需要优先复核；不会自动改变 HOLD 或其他手工"
        "计划。",
    ),
    (
        "WAIT_MONITOR / 等待观察",
        "当前没有更高优先级的复核路线；继续使用 Next Step 和 Next Trigger 观察条件。",
    ),
    (
        "Next Trigger / 下一触发条件",
        "行情还需要发生什么才支持下一次状态判断，和 Next Step 的“现在做什么工作流”"
        "不同。包括入场计划与 RSI 动量复核，以及等待有效回撤或突破形态、Higher Low + Reclaim、确认"
        "Higher Low、突破阻力并两根完成 K 线站稳、维持修复结构、收复支撑 + Higher "
        "Low、突破近期摆动高点、受控回踩支撑、满足 Options Scanner 资格、建立修复"
        "背景、局部 Acceptance 或 Reclaim、基准确认、Leader 工作流许可。若没有"
        "可靠价位会明确显示 No reliable level，不会编造数值。",
    ),
    (
        "Call Readiness",
        "共有 4 个值：NOT_READY（关键前提尚未形成）、DEVELOPING（已有部分修复证据）、"
        "NEAR_QUALIFICATION（修复背景与 higher low 已有，仍缺完成 K 线或基准确认）、"
        "QUALIFIED（所有必需条件 PASS 且没有 blocker）。它与 Technical State 分开："
        "RIGHT_SIDE_REPAIR 可以同时是 NEAR_QUALIFICATION；Tech Setup Score 再高也不会"
        "单独升级 readiness。首次结构突破不需要旧修复状态；QUALIFIED 还要求 RSI 达标、"
        "最新完整行情、日线趋势、结构止损、真实阻力目标、延伸限制与最低 R。"
        "不适合新入场不代表应卖出现有持仓。",
    ),
    (
        "Equity Entry Plan / 标的入场计划",
        "E 是最新完整 15 分钟收盘价，不是可成交报价；S 是确认时的结构失效价加波动缓冲，"
        "T 是此前已确认的最近日线阻力。R=(T-E)/(E-S)，默认要求至少 2R，"
        "另检查日线 ATR 延伸和 15 分钟噪声。缺目标、旧记录、过期行情不视为可入场。"
        "这些是可调且未回测的研究规则；股票 R 不等于期权 R、胜率或保证收益。",
    ),
    (
        "Tech Setup Score",
        "0–10 分的标的技术形态评分：越高表示当前形态越符合已配置的结构、"
        "动量和基准条件。0 不是“必跌”，10 也不是“必涨”；它与期权质量和"
        "仓位大小分开。内部旧字段名 ceg_tech_score 仅为兼容保留。",
    ),
    (
        "Today %",
        "连续数值，可正、可负或暂无数据。最新已完成 15 分钟收盘价相对上一"
        "常规交易日收盘价的百分比变化；正数表示高于昨收，负数表示低于昨收。",
    ),
    (
        "15m %",
        "连续数值，可正、可负或暂无数据。最新两个已完成 15 分钟收盘价之间"
        "的百分比变化，用来观察最近一根完整 K 线的方向。",
    ),
    (
        "Today Open",
        "价格或暂无数据。当天第一根已完成常规交易时段 15 分钟 K 线的开盘价；"
        "通常要到美东时间 09:45 后才可用。",
    ),
    (
        "VWAP",
        "成交量加权平均价。现价在 VWAP 上方表示高于当日成交重心，在下方表示"
        "低于成交重心；它是参考线，不保证支撑或阻力。",
    ),
    (
        "EMA9/20",
        "9 与 20 周期指数移动平均线。EMA9 更敏感；EMA9 高于 EMA20 通常表示"
        "短期结构较强，低于 EMA20 通常表示较弱，但仍需结合价格结构。",
    ),
    (
        "RSI",
        "0–100 的 14 周期相对强弱指标。约 30 以下表示近期跌势较极端，约 70 "
        "以上表示近期涨势较极端；RSI 单独出现绝不会产生 CALL_CANDIDATE。",
    ),
    (
        "MACD",
        "包含 MACD 线、Signal 信号线和 Histogram 柱值。MACD 上穿 Signal 或"
        "柱值转正表示动量改善；下穿或转负表示动量走弱，不单独决定状态。",
    ),
    (
        "ATR",
        "大于等于 0 的 14 周期平均真实波幅，单位与股价相同。数值越大表示近期"
        "日内波动尺度越大；它不表示涨跌方向。",
    ),
    (
        "Higher Low",
        "布尔值：Yes 表示近期低点高于前一个可比低点，结构可能改善；No 表示"
        "未确认 higher low，不等于一定出现 lower low。",
    ),
    (
        "Lower Low",
        "布尔值：Yes 表示近期低点低于前一个可比低点，结构转弱；No 表示未确认"
        " lower low，不等于一定出现 higher low。",
    ),
    (
        "Support",
        "分为 Local Support（从最后两根确认 K 线之前的已完成 15 分钟 pivot/swing "
        "结构确定）与 Major Swing Support（配置窗口内日线低点，默认 20 日）。局部位"
        "用于战术 Reclaim，主级别用于较大周期结构；都不保证未来有效。",
    ),
    (
        "Resistance",
        "分为 Local Resistance（从最后两根确认 K 线之前的已完成 15 分钟 pivot/swing "
        "结构确定）与 Major Swing Resistance（配置窗口内日线高点，默认 20 日）。"
        "局部位驱动两根完成 K 线 Acceptance；主级别只显示较大周期突破背景。",
    ),
    (
        "Acceptance",
        "布尔确认：Yes 表示连续两根已完成 15 分钟 K 线都维持在指定参考位之上"
        "或之下；No 表示两根确认尚未成立。",
    ),
    (
        "Benchmark Confirmation",
        "布尔值：Yes 表示该股票配置的 QQQ/SOXX 等基准满足确认规则；No 表示"
        "基准未确认或数据不足。它是条件检查，不是市场预测。",
    ),
    (
        "NORMAL",
        "普通/中性：当前没有触发回撤观察、卖压衰减、右侧修复、完整候选或结构"
        "破坏。它不是“安全”或“应该持有”的意思。",
    ),
    (
        "DIP_WATCH",
        "回撤观察：价格从近期高点回落达到配置阈值，但仍未确认止跌和右侧修复。"
        "重点是继续观察 support、低点结构和后续完整 K 线。",
    ),
    (
        "SELLING_EXHAUSTION",
        "卖压衰减：RSI 较低且最近完整 15 分钟价格开始稳定，表示连续抛售的力度"
        "可能正在减弱。它只说明“跌速可能放缓”，不等于已经见底、反转或可以买入；"
        "仍需 higher low、均线/VWAP 修复和两根完整 K 线确认。",
    ),
    (
        "RIGHT_SIDE_REPAIR",
        "右侧修复：回撤之后价格不再只向下，开始形成 higher low、回到短期均线或"
        "关键位附近并改善结构；但完整确认条件尚未全部满足。",
    ),
    (
        "CALL_CANDIDATE",
        "条件齐全候选：必须有先前修复背景、higher low、连续两根完整 K 线确认、"
        "基准确认，并属于配置的 leader 组。仅表示规则条件满足，不是期权建议。",
    ),
    (
        "BREAKDOWN",
        "结构破坏：价格跌破带缓冲的近期 support，同时日线确认 lower low。它是"
        "短期技术状态，不等于长期组合中的卖出或处置指令。",
    ),
    (
        "Ticker Group",
        "共有 5 个配置组：leader_long_call（可进入期权资格检查）、long_term_core"
        "（长期核心）、long_term_growth（长期成长）、high_risk_growth（高风险"
        "成长）、short_term_watch（短期观察）。同一 ticker 可属于多个组。",
    ),
    (
        "Long-Term Action",
        "共有 4 个手工配置值：ADD（允许按既定长期计划增加）、HOLD（保持）、"
        "PAUSE_ADD（暂停增加）、THESIS_REVIEW（复核长期逻辑）。它不会由短期"
        " Technical State 或 Next Step 自动改变，也不是订单。Dashboard 可用它筛选"
        "当前页面已有的行；即使该列在当前策略页面不显示，筛选语义也保持独立不变。",
    ),
    (
        "DTE",
        "距离到期的日历天数。本期权扫描只保留 60–120 DTE；75–100 DTE 是评分"
        "最高的偏好区间，区间内仍会按接近程度平滑打分。",
    ),
    (
        "Delta",
        "通常为 -1 到 1；本项目扫描 call，偏好 0.55–0.70，可接受范围 0.45–0.75。"
        "越接近偏好区间得分越高；缺失不会臆造，并会明显降低置信度。",
    ),
    (
        "Delta Range Status",
        "共有 4 个值：PREFERRED（0.55–0.70 偏好区间）、ACCEPTABLE（0.45–0.75 "
        "可接受但不在偏好区间）、MISSING（数据缺失）、OUTSIDE（范围外）。",
    ),
    (
        "IV",
        "大于等于 0 的隐含波动率，页面以百分比显示。它反映期权价格隐含的波动"
        "假设，不是未来实际波动或涨跌概率。",
    ),
    (
        "Chain-Relative IV",
        "0–100% 的同次抓取期权链内相对位置：例如 80% 表示该合约 IV 高于本次链中"
        "约 80% 的可比较合约。它不是历史 IV 百分位，也没有通用绝对阈值。",
    ),
    (
        "Open Interest/OI",
        "非负整数或暂无数据，表示未平仓合约数量。越高通常表示参与度更好；缺失"
        "不会按 0 处理，并会降低评分置信度。",
    ),
    (
        "Volume",
        "非负整数或暂无数据，表示当日合约成交量。它是流动性辅助信息；缺失不按"
        " 0 处理。",
    ),
    (
        "Bid / Ask",
        "Bid 是当前买方报价，Ask 是当前卖方报价；都为非负价格或暂无数据。Basic "
        "indicative feed 可能修改并延迟最多 15 分钟，应谨慎解释。",
    ),
    (
        "Spread",
        "Ask - Bid，以及相对中间价的百分比。百分比越小通常流动性越好；本项目的"
        "流动性评分中 spread 权重最高，其次是 OI、Volume。",
    ),
    (
        "Moneyness",
        "call 的行权价相对现价位置。共有 4 个状态：ATM_OR_ITM（平值或价内）、"
        "ACCEPTABLE_OTM（可接受的轻度价外）、TOO_FAR_OTM（过度价外）、INVALID"
        "（价格数据无效）。评分偏好平值/轻度价内，远价外不会入选。",
    ),
    (
        "Intrinsic/Extrinsic Value",
        "call 内在价值 = max(现价 - 行权价, 0)；外在价值 = 期权价格 - 内在价值。"
        "两者为非负价格或暂无数据。",
    ),
    (
        "Options Score",
        "0–10 分，由 5 个各 0–2 分组件相加：Delta Fit、DTE Fit、Liquidity、"
        "Chain-Relative IV Quality、Moneyness。越高表示越符合配置，不代表收益概率。",
    ),
    (
        "Combined Score",
        "0–10 分，固定公式为 70% Tech Setup Score + 30% Options Score。用于稳定"
        "排序，不是交易建议。",
    ),
    (
        "Score Confidence",
        "0–100% 的数据完整性/可信度。缺少 Delta 或 OI 扣分较多，缺少 IV 或 Volume "
        "扣分中等；它不是成功概率。",
    ),
    (
        "Candidate Status",
        "共有 2 个值：TOP_CANDIDATE（当前配置下排名第一）和 ACCEPTABLE（通过筛选"
        "且适配度可接受）。两者都不是建议或订单。",
    ),
    (
        "TOP_CANDIDATE",
        "Candidate Status 的排名第一值，表示在当前数据与配置下综合适配度最高。"
        "它不是收益预测、交易建议或执行指令。",
    ),
    (
        "Options Eligibility",
        "共有 4 个当前值及 1 个旧兼容值：NOT_ELIGIBLE（不可扫描）、RESEARCH_ELIGIBLE"
        "（高质量 RIGHT_SIDE_REPAIR，可做 Contract Pre-Screen）、EXECUTION_QUALIFIED"
        "（仅 CALL_CANDIDATE + QUALIFIED readiness + 零必需 blocker）、MANUAL_OVERRIDE"
        "（仅人工研究覆盖），以及旧数据可能出现的 ELIGIBLE。只有 "
        "EXECUTION_QUALIFIED 会进入 Current Qualified Setups；这里的 execution 表示"
        "规则资格层级，不会下单或准备订单。",
    ),
    (
        "Options Scan Status",
        "共有 5 个值：NOT_ELIGIBLE（股票条件不符合）、MANUAL_OVERRIDE（人工覆盖了"
        "股票状态/分数门槛）、OPTIONS_DATA_UNAVAILABLE（数据源不可用）、"
        "NO_SUITABLE_CONTRACT（链已取回但无合约通过）、CANDIDATES_FOUND（找到合约）。",
    ),
    (
        "Options Feed",
        "共有 2 个配置值：indicative（Basic 账户默认，修改后的报价/成交并延迟最多 "
        "15 分钟）和 opra（需要相应订阅的 consolidated feed）。系统不会静默切换。",
    ),
    (
        "Options Data Quality Flags",
        "共 23 个可能标记：MISSING_QUOTE、MISSING_QUOTE_TIMESTAMP、MISSING_GREEKS、"
        "MISSING_IV、MISSING_OPEN_INTEREST、MISSING_VOLUME（字段缺失）；STALE_QUOTE"
        "（报价过旧）；CROSSED_MARKET（Bid 高于 Ask）；ZERO_BID；INVALID_BID、"
        "INVALID_ASK、INVALID_UNDERLYING_PRICE、INVALID_STRIKE、INVALID_DTE、"
        "INVALID_IV、INVALID_OPEN_INTEREST、INVALID_VOLUME（数值无效）；WIDE_SPREAD"
        "（价差过宽）；HIGH_RELATIVE_IV（相对当前链偏高）；"
        "INSUFFICIENT_RELATIVE_IV_SAMPLE"
        "（链内 IV 样本不足）；NEAR_TERM_EARNINGS_RISK、EARNINGS_WITHIN_CONTRACT_LIFE"
        "（财报事件风险）；EARNINGS_DATA_UNAVAILABLE（财报数据不可用）。标记会降低"
        "置信度、发出警告或使合约被过滤，不会用假数据补齐。",
    ),
    (
        "Manual Override",
        "布尔值：Off 使用正常股票状态和 Tech Setup Score 资格门槛；On 只绕过这两个"
        "门槛。它不会绕过 ticker enabled、leader_long_call 组、期权筛选或数据质量"
        "规则，并会在结果中明确标记。",
    ),
    (
        "Portfolio Role",
        "共有 7 个确认角色：CORE（核心）、CORE_GROWTH（核心成长）、GROWTH（成长）、"
        "HIGH_RISK_GROWTH（高风险成长）、TACTICAL（战术仓位）、CYCLICAL（周期）、"
        "HEDGE（对冲）。它与短期 Technical State 分开。",
    ),
    (
        "Risk Tier",
        "共有 5 级：LOW、MEDIUM、MEDIUM_HIGH、HIGH、VERY_HIGH。级别越高表示分类中"
        "的风险越高；它不会自动决定仓位大小。",
    ),
    (
        "Classification Evidence Scores",
        "页面有 6 个可填写的 0–10 分字段：Business Quality、Financial Stability、"
        "Revenue Visibility（越高越强）；Volatility Regime（越高越稳定/低波动）；"
        "Customer Concentration（越高越分散/低集中）；Event Dependence（越高越不"
        "依赖单一事件）。留空表示 UNAVAILABLE，不会按 0 分处理。",
    ),
    (
        "Evidence Data Quality",
        "共有 3 个值：AVAILABLE（完整可用，权重 1.0）、PARTIAL（部分可用，权重 "
        "0.5）、UNAVAILABLE（不可用，不计入评分且不当作 0）。",
    ),
    (
        "Evidence Confidence",
        "0–100%，表示分类证据来源和质量的可信程度，不是角色判断正确概率。",
    ),
    (
        "Data Completeness",
        "0–100%，表示配置要求的证据轴中有多少实际可用。空白证据为 UNAVAILABLE，"
        "不会用 0 分补齐。",
    ),
    (
        "Hysteresis",
        "滞后确认规则：当前配置要求同一候选角色连续 2 个合格 review cycle，避免"
        "单次波动立即改写已确认分类。",
    ),
    (
        "Confirmed/Suggested Profile",
        "Confirmed 是数据库中的当前权威分类；Suggested 是规则计算出的待审核快照。"
        "Suggested 不会自动覆盖 Confirmed。",
    ),
    (
        "Review Mode",
        "共有 3 个值：WEEKLY（周期复核）、EVENT（事件触发复核）、MANUAL（用户手动"
        "复核）。模式记录复核来源，不改变人工确认要求。",
    ),
    (
        "Evaluation Status",
        "共有 8 个值：INSUFFICIENT_EVIDENCE（证据不足）、NO_CHANGE（无需变化）、"
        "DISALLOWED_TRANSITION（角色跨级不允许）、AWAITING_CONFIRMATION（等待下一"
        "一致周期）、PROPOSAL_CREATED（已建提议）、DUPLICATE_PENDING（已有同类待办）、"
        "COOLDOWN_BLOCKED（冷却期阻止）、SNOOZE_BLOCKED（延期期间阻止）。",
    ),
    (
        "Proposal Type",
        "模型共有 8 个值：ROLE_CHANGE、GROUP_ADD、GROUP_REMOVE、RISK_TIER_CHANGE、"
        "STRATEGY_TAG_ADD、STRATEGY_TAG_REMOVE、BENCHMARK_TAG_CHANGE、"
        "COMPANY_QUALITY_CHANGE。当前自动分类流程只创建 ROLE_CHANGE；其他值为"
        "兼容和后续扩展保留。",
    ),
    (
        "Proposal Status",
        "共有 6 个值：PENDING（待处理）、ACCEPTED（已接受）、REJECTED（保持当前）、"
        "SNOOZED（延期）、EXPIRED（过期）、SUPERSEDED（被更新提议取代）。",
    ),
    (
        "Proposal",
        "确定性分类规则生成的变更草案。当前自动流程只提出相邻 Portfolio Role "
        "变化；必须由用户明确接受才会更新 Confirmed Profile。",
    ),
    (
        "Snooze",
        "将 PENDING 提议延后到指定日期；既不是接受，也不是拒绝，且不会产生新的"
        " Confirmed Profile 版本。",
    ),
)


def render_primary_nav(active: str) -> str:
    links = (
        ("dashboard", "/", "Dashboard"),
        ("options", "/options", "Options"),
        ("classification", "/classification", "Classification"),
        ("features", "/features", "Features"),
    )
    anchors = "".join(
        f"<a href='{href}'{' aria-current=\"page\"' if key == active else ''}>"
        f"{escape(label)}</a>"
        for key, href, label in links
    )
    return (
        "<nav class='primary-nav' aria-label='Primary navigation'>"
        f"{anchors}<button class='glossary-open' type='button' "
        "data-glossary-open aria-haspopup='dialog'>Glossary / 术语</button></nav>"
    )


def render_glossary() -> str:
    rows = "".join(
        "<article class='glossary-term' data-glossary-term>"
        f"<dt>{escape(term)}</dt><dd>{escape(description)}</dd></article>"
        for term, description in GLOSSARY_TERMS
    )
    return (
        "<dialog class='glossary-dialog' data-glossary-dialog "
        "aria-labelledby='glossary-title'>"
        "<div class='glossary-head'><div><h2 id='glossary-title'>"
        "Glossary / 术语</h2><p>Values, ranges, and practical Chinese explanations.</p>"
        "</div><button type='button' class='glossary-close' data-glossary-close "
        "aria-label='Close glossary'>×</button></div>"
        "<label class='glossary-search-label' for='glossary-search'>"
        "Filter terms / 搜索术语</label>"
        "<input id='glossary-search' data-glossary-search type='search' "
        "placeholder='RSI, Delta, 状态…' autocomplete='off'>"
        f"<dl class='glossary-list'>{rows}</dl>"
        "<p class='glossary-empty' data-glossary-empty hidden>No matching term / 无匹配术语</p>"
        "</dialog><p class='ticker-copy-status' data-ticker-copy-status "
        "role='status' aria-live='polite'></p>"
    )


def render_ticker_copy(ticker: str, *, css_class: str = "") -> str:
    symbol = ticker.strip().upper()
    escaped_symbol = escape(symbol)
    classes = "ticker-copy"
    if css_class:
        classes += f" {escape(css_class, quote=True)}"
    return (
        f"<button type='button' class='{classes}' "
        f"data-copy-ticker='{escape(symbol, quote=True)}' "
        f"aria-label='Copy {escape(symbol, quote=True)} ticker' "
        f"title='Copy {escape(symbol, quote=True)}'>{escaped_symbol}</button>"
    )


def glossary_styles() -> str:
    return (
        ".primary-nav{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin-top:20px}"
        ".primary-nav a,.primary-nav button{appearance:none;border:1px solid transparent;"
        "border-radius:7px;background:transparent;color:rgba(255,255,255,.84);padding:7px 11px;"
        "font:inherit;font-size:12px;font-weight:700;text-decoration:none;cursor:pointer}"
        ".primary-nav a:hover,.primary-nav button:hover{background:rgba(255,255,255,.13)}"
        ".primary-nav a[aria-current='page']{background:#fff;color:#004182}"
        ".glossary-dialog{width:min(760px,calc(100vw - 28px));max-height:82vh;border:0;"
        "border-radius:12px;padding:0;box-shadow:0 18px 60px #0005;color:#222}"
        ".glossary-dialog::backdrop{background:rgba(0,0,0,.48)}.glossary-head{display:flex;"
        "justify-content:space-between;gap:20px;padding:20px 22px 12px;border-bottom:1px solid #e5e5e5}"
        ".glossary-head h2{margin:0;font-size:22px}.glossary-head p{margin:4px 0 0;color:#666}"
        ".glossary-close{appearance:none;border:0;background:transparent;color:#555;font-size:28px;"
        "line-height:1;cursor:pointer}.glossary-search-label{display:block;margin:16px 22px 5px;"
        "font-size:12px;font-weight:700}.glossary-dialog input[type='search']{display:block;"
        "width:calc(100% - 44px);margin:0 22px 12px;padding:9px 11px;border:1px solid #aaa;"
        "border-radius:7px;font:inherit}.glossary-list{margin:0;padding:0 22px 22px;overflow:auto}"
        ".glossary-term{display:grid;grid-template-columns:minmax(150px,210px) 1fr;gap:16px;"
        "padding:11px 0;border-bottom:1px solid #eee}.glossary-term dt{font-weight:800;color:#0A66C2}"
        ".glossary-term dd{margin:0;color:#444}"
        ".glossary-term.is-filtered-out,.glossary-term[hidden]{display:none!important}"
        ".glossary-empty{padding:4px 22px 22px;color:#666}"
        ".ticker-copy{appearance:none;border:0;border-bottom:1px dashed currentColor;"
        "border-radius:0;background:transparent;color:inherit;padding:0;font:inherit;"
        "font-weight:800;line-height:inherit;cursor:copy}.ticker-copy:hover,.ticker-copy:focus-visible{"
        "color:#0A66C2;background:transparent;outline:2px solid #0A66C2;outline-offset:3px}"
        ".ticker-copy[data-copied='true']{color:#057642}.ticker-copy-status{position:fixed;"
        "right:18px;bottom:18px;z-index:1000;margin:0;padding:9px 13px;border-radius:7px;"
        "background:#172033;color:#fff;box-shadow:0 4px 18px #0004;opacity:0;"
        "transform:translateY(8px);pointer-events:none;transition:opacity .15s,transform .15s}"
        ".ticker-copy-status[data-visible='true']{opacity:1;transform:translateY(0)}"
        "@media(max-width:620px){.glossary-term{grid-template-columns:1fr;gap:3px}}"
    )


def glossary_script() -> str:
    return (
        "(()=>{const copyStatus=document.querySelector('[data-ticker-copy-status]');"
        "let copyStatusTimer=null;"
        "function showCopyStatus(message){if(!copyStatus)return;copyStatus.textContent=message;"
        "copyStatus.dataset.visible='true';if(copyStatusTimer)window.clearTimeout(copyStatusTimer);"
        "copyStatusTimer=window.setTimeout(()=>{delete copyStatus.dataset.visible;},1800);}"
        "function fallbackCopy(text){const area=document.createElement('textarea');"
        "area.value=text;area.setAttribute('readonly','');area.style.position='fixed';"
        "area.style.opacity='0';document.body.appendChild(area);area.select();"
        "const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('copy failed');}"
        "document.addEventListener('click',async event=>{"
        "const button=event.target.closest('[data-copy-ticker]');if(!button)return;"
        "const ticker=button.dataset.copyTicker;if(!ticker)return;"
        "try{if(navigator.clipboard&&navigator.clipboard.writeText){"
        "await navigator.clipboard.writeText(ticker);}else{fallbackCopy(ticker);}"
        "document.querySelectorAll('[data-copy-ticker][data-copied=\"true\"]').forEach("
        "item=>{if(item!==button)delete item.dataset.copied;});"
        "button.dataset.copied='true';button.title=`Copied ${ticker}`;"
        "showCopyStatus(`Copied ${ticker} to clipboard`);"
        "window.setTimeout(()=>{delete button.dataset.copied;button.title=`Copy ${ticker}`;},1600);"
        "}catch(error){showCopyStatus(`Could not copy ${ticker}`);}});"
        "const dialog=document.querySelector('[data-glossary-dialog]');"
        "if(!dialog)return;const search=dialog.querySelector('[data-glossary-search]');"
        "const terms=[...dialog.querySelectorAll('[data-glossary-term]')];"
        "const empty=dialog.querySelector('[data-glossary-empty]');let trigger=null;"
        "document.querySelectorAll('[data-glossary-open]').forEach(button=>"
        "button.addEventListener('click',()=>{trigger=button;dialog.showModal();search.focus();}));"
        "dialog.querySelector('[data-glossary-close]').addEventListener('click',()=>dialog.close());"
        "dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});"
        "dialog.addEventListener('close',()=>{search.value='';terms.forEach(term=>{"
        "term.hidden=false;term.classList.remove('is-filtered-out');});"
        "empty.hidden=true;if(trigger)trigger.focus();});"
        "function filterTerms(){const query=search.value.trim().toLocaleLowerCase();"
        "let visible=0;terms.forEach(term=>{const matches=!query||"
        "term.textContent.toLocaleLowerCase().includes(query);term.hidden=!matches;"
        "term.classList.toggle('is-filtered-out',!matches);if(matches)visible+=1;});"
        "empty.hidden=visible!==0;}"
        "search.addEventListener('input',filterTerms);"
        "search.addEventListener('search',filterTerms);})();"
    )
