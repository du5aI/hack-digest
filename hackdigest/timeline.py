"""Картинка-таймлайн ближайших хакатонов (PNG для отправки в Telegram)."""
import io
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from hackdigest.digest import MONTHS_FULL, MONTHS_SHORT, SOURCE_NAMES  # noqa: E402
from hackdigest.models import Hackathon  # noqa: E402
from hackdigest.text import strip_emoji  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e6e5e1"
BAR = "#2a78d6"  # даты проведения
DEADLINE = "#eb6834"  # дедлайн регистрации
TODAY = "#8a8984"

MAX_ROWS = 28
WINDOW_DAYS = 56
TITLE_LEN = 40


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def render_timeline(items: list[Hackathon], new_uids: set[str], now: datetime, window_days: int = WINDOW_DAYS) -> bytes | None:
    """Возвращает PNG или None, если рисовать нечего (нет событий с датами в окне)."""
    left = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    right = left + timedelta(days=window_days)
    def visible(h: Hackathon) -> bool:
        if h.start:
            return h.start < right and (h.end or h.start) >= left
        return h.reg_deadline is not None and now <= h.reg_deadline < right

    rows = [h for h in items if h.source != "telegram" and visible(h)]
    # сначала то, что скоро; уже идущие длинные конкурсы — в конец
    rows.sort(key=lambda h: (bool(h.start) and h.start.date() < now.date(), h.key_date))
    rows = rows[:MAX_ROWS]
    if not rows:
        return None

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    height = 1.5 + 0.34 * len(rows)
    fig, ax = plt.subplots(figsize=(11, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x0, x1 = mdates.date2num(left), mdates.date2num(right)
    for i, h in enumerate(rows):
        if h.start is None:  # известен только дедлайн регистрации — рисуем лишь его
            ax.plot(mdates.date2num(h.reg_deadline), i, marker="D", markersize=6.5,
                    color=DEADLINE, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3)
            continue
        start = max(mdates.date2num(h.start), x0)
        end = min(mdates.date2num(h.end or h.start + timedelta(hours=23)), x1)
        width = max(end - start, 0.6)  # однодневные события тоже должны быть видны
        ax.add_patch(FancyBboxPatch(
            (start, i - 0.26), width, 0.52,
            boxstyle="round,pad=0,rounding_size=0.18", mutation_aspect=1 / 6,
            facecolor=BAR, edgecolor=SURFACE, linewidth=1.5,
        ))
        if h.reg_deadline and h.reg_deadline >= now and mdates.date2num(h.reg_deadline) <= x1:
            ax.plot(mdates.date2num(h.reg_deadline), i, marker="D", markersize=6.5,
                    color=DEADLINE, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3)

    labels = [_short(strip_emoji(h.title), TITLE_LEN) for h in rows]
    ax.set_yticks(range(len(rows)), labels)
    for tick, h in zip(ax.get_yticklabels(), rows):
        tick.set_color(TEXT)
        if h.uid in new_uids:
            tick.set_fontweight("bold")
    # источник — мелким серым текстом справа от строки
    for i, h in enumerate(rows):
        ax.annotate(SOURCE_NAMES.get(h.source, h.source), xy=(1, i), xycoords=("axes fraction", "data"),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=7.5, color=TEXT_MUTED)

    ax.set_xlim(x0, x1)
    ax.set_ylim(len(rows) - 0.5, -0.7)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: (lambda d: f"{d.day} {MONTHS_SHORT[d.month - 1]}")(mdates.num2date(x))))
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", colors=TEXT_MUTED, length=0, labelsize=8)
    ax.tick_params(axis="y", length=0, pad=8)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    today = mdates.date2num(now)
    ax.axvline(today, color=TODAY, linewidth=1, linestyle=(0, (3, 3)), zorder=1)
    ax.annotate("сегодня", xy=(today, len(rows) - 0.5), xytext=(3, 3), textcoords="offset points",
                fontsize=7.5, color=TEXT_MUTED)

    fig.text(0.012, 1 - 0.32 / height, "Ближайшие хакатоны", fontsize=13, fontweight="bold", color=TEXT)
    fig.text(0.012, 1 - 0.58 / height,
             f"на {now.day} {MONTHS_FULL[now.month - 1]} {now.year}, жирным — новые с прошлого дайджеста",
             fontsize=8.5, color=TEXT_MUTED)
    # легенда: что означают полоса и ромб
    lx = 0.62
    fig.patches.append(FancyBboxPatch((lx, 1 - 0.5 / height), 0.022, 0.12 / height, transform=fig.transFigure,
                                      boxstyle="round,pad=0,rounding_size=0.004", facecolor=BAR, edgecolor="none"))
    fig.text(lx + 0.028, 1 - 0.47 / height, "даты проведения", fontsize=8.5, color=TEXT_MUTED, va="center")
    fig.lines.append(plt.Line2D([lx + 0.17], [1 - 0.44 / height], transform=fig.transFigure, marker="D",
                                markersize=6.5, color=DEADLINE, linestyle="none"))
    fig.text(lx + 0.18, 1 - 0.47 / height, "конец регистрации", fontsize=8.5, color=TEXT_MUTED, va="center")

    fig.subplots_adjust(left=0.36, right=0.89, top=1 - 1.0 / height, bottom=0.25 / height)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()
