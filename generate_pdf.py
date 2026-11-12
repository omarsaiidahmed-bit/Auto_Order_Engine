# -*- coding: utf-8 -*-
"""Build the Arabic/English Auto Order V2 management report and SOP PDF.

The document is intentionally self-contained: it only reads the bundled fonts
and logo, then writes ``AutoOrder_SOP_and_Comparison.pdf`` next to this file.
It does not import or modify anything in ``core/``.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, XPos, YPos
from fpdf.fonts import FontFace

# ---------------------------------------------------------------------------
# Paths and page geometry
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "fonts"
LOGO = ROOT / "company_logo.png"
OUTPUT = ROOT / "AutoOrder_SOP_and_Comparison.pdf"

PAGE_W = 210.0
PAGE_H = 297.0
M = 17.0
CW = PAGE_W - 2 * M  # 176 mm

# ---------------------------------------------------------------------------
# Soft blue / grey palette
# ---------------------------------------------------------------------------
NAVY = (22, 48, 73)
BLUE = (43, 108, 158)
STEEL = (78, 112, 142)
SKY = (143, 183, 214)
PALE = (234, 243, 249)
PALE_2 = (246, 249, 252)
MIST = (249, 251, 253)
LINE = (215, 225, 234)
TEXT = (36, 50, 65)
MUTED = (101, 118, 134)
WHITE = (255, 255, 255)
PAIN = (166, 86, 86)
PAIN_BG = (251, 242, 242)
GOOD = (38, 120, 103)
GOOD_BG = (237, 247, 243)
AMBER = (173, 132, 54)
AMBER_BG = (252, 247, 235)

PINK = (247, 220, 233)
PINK_DARK = (185, 104, 145)
YELLOW = (251, 241, 201)
YELLOW_DARK = (172, 137, 43)
GREY = (230, 235, 240)
GREY_DARK = (104, 117, 130)
BLUE_LIGHT = (218, 234, 246)
BLUE_DARK = (44, 111, 160)


class ReportPDF(FPDF):
    """A4 report with RTL Arabic typography and soft editorial styling."""

    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_margins(M, 24, M)
        self.set_auto_page_break(True, margin=20)
        self.set_top_margin(24)
        self.set_compression(True)

        self.rtl = True
        self.body = "Body"
        self.serif = "Serif"
        self.add_font(self.body, "", str(FONTS / "Tajawal-Regular.ttf"))
        self.add_font(self.body, "B", str(FONTS / "Tajawal-Bold.ttf"))
        self.add_font(self.serif, "", str(FONTS / "Amiri-Regular.ttf"))
        self.add_font(self.serif, "B", str(FONTS / "Amiri-Bold.ttf"))

        # Arabic shaping is handled by fpdf2's HarfBuzz integration.
        self._auto_text()
        self.set_draw_color(*LINE)
        self.set_text_color(*TEXT)
        self.set_fill_color(*WHITE)
        self.set_line_width(0.3)
        self.alias_nb_pages()

        self._suppress_header = False
        self.section_label = "تقرير الإدارة"

        self.set_title("تقرير تقييم نظام الأوتو أوردر (Auto Order V2) ودليل التشغيل")
        self.set_author("إدارة العمليات / تطوير الأنظمة")
        self.set_subject("مقارنة بين النظام اليدوي الحالي ونظام Auto Order V2 مع دليل تشغيل")
        self.set_keywords("Auto Order V2, SOP, ROP, Safety Stock, Pharmacy, Operations")
        self.set_creator("Auto Order V2 report generator")

    # ------------------------------------------------------------------
    # Text direction helpers
    # ------------------------------------------------------------------
    def _auto_text(self) -> None:
        self.set_text_shaping(True, features={"rlig": False})

    def _rtl_text(self) -> None:
        self.set_text_shaping(True, features={"rlig": False}, direction="rtl")

    def _ltr_text(self) -> None:
        self.set_text_shaping(True, features={"rlig": False}, direction="ltr")

    # ------------------------------------------------------------------
    # Page furniture
    # ------------------------------------------------------------------
    def header(self) -> None:
        if self.page_no() == 1 or self._suppress_header:
            return

        self.set_fill_color(*PALE)
        self.rect(0, 0, PAGE_W, 18, "F")
        self.image(str(LOGO), M, 4.3, 9.2)

        self._ltr_text()
        self.set_font(self.body, "B", 6.4)
        self.set_text_color(*STEEL)
        self.set_xy(30, 6.2)
        self.cell(80, 4, "AUTO ORDER V2  ·  EXECUTIVE REPORT & SOP", align="L")

        self._rtl_text()
        self.set_font(self.body, "", 6.8)
        self.set_text_color(*MUTED)
        self.set_xy(95, 6.2)
        self.cell(98, 4, self.section_label, align="R")

        self.set_draw_color(*LINE)
        self.set_line_width(0.3)
        self.line(M, 18, PAGE_W - M, 18)
        self.set_y(24)

    def footer(self) -> None:
        if self.page_no() == 1:
            return

        self.set_draw_color(*LINE)
        self.set_line_width(0.25)
        self.line(M, 281, PAGE_W - M, 281)

        self._ltr_text()
        self.set_font(self.body, "", 6.5)
        self.set_text_color(*MUTED)
        self.set_xy(M, 284)
        self.cell(65, 4, "AUTO ORDER V2.0  ·  INTERNAL", align="L")

        self._rtl_text()
        self.set_xy(90, 284)
        self.cell(103, 4, "وثيقة إدارية — إدارة العمليات", align="R")

        self.set_fill_color(*PALE)
        self.rect(96, 282.2, 18, 7, "F", round_corners=True, corner_radius=3.5)
        self._ltr_text()
        self.set_font(self.body, "B", 6.8)
        self.set_text_color(*BLUE)
        self.set_xy(96, 283.2)
        self.cell(18, 4.5, f"{self.page_no()} / {{nb}}", align="C")

    # ------------------------------------------------------------------
    # Measuring and simple typography
    # ------------------------------------------------------------------
    def measure(
        self,
        text: str,
        width: float,
        size: float = 9.5,
        leading: float = 5.0,
        *,
        bold: bool = False,
        font: str | None = None,
        align: str = "R",
    ) -> float:
        self.set_font(font or self.body, "B" if bold else "", size)
        if align == "L":
            self._ltr_text()
        else:
            self._rtl_text()
        lines = self.multi_cell(
            width,
            leading,
            text,
            align=align,
            dry_run=True,
            output="LINES",
        )
        return max(1, len(lines)) * leading

    def ensure_space(self, needed: float) -> None:
        if self.get_y() + needed > PAGE_H - 24:
            self.add_page()

    def p(
        self,
        text: str,
        *,
        size: float = 10.0,
        leading: float = 5.5,
        color: tuple[int, int, int] = TEXT,
        bold: bool = False,
        after: float = 1.6,
        align: str = "R",
        font: str | None = None,
    ) -> None:
        if align == "L":
            self._ltr_text()
        else:
            self._rtl_text()
        self.set_font(font or self.body, "B" if bold else "", size)
        self.set_text_color(*color)
        self.multi_cell(
            0,
            leading,
            text,
            align=align,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        if after:
            self.ln(after)

    def lead(self, text: str, *, align: str = "R") -> None:
        self.p(text, size=10.7, leading=5.8, color=TEXT, after=2.0, align=align)

    def h2(self, text: str, en: str | None = None) -> None:
        self._rtl_text()
        self.set_font(self.body, "B", 13.0)
        ar_h = self.measure(text, CW - 6, 13.0, 7.0, bold=True)
        total = ar_h + (4.0 if en else 0.0) + 2.0
        self.ensure_space(total + 3.0)
        y = self.get_y()

        self.set_fill_color(*BLUE)
        self.rect(PAGE_W - M - 2.4, y + 1.0, 2.4, max(5.0, ar_h - 1.2), "F")

        self.set_font(self.body, "B", 13.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, y)
        self.multi_cell(
            CW - 6,
            7.0,
            text,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        if en:
            self.set_font(self.body, "", 6.8)
            self.set_text_color(*MUTED)
            self._ltr_text()
            self.set_xy(M, self.get_y() + 0.4)
            self.cell(CW - 6, 4, en.upper(), align="L")
            self.ln(4.2)
        else:
            self.ln(1.8)

    def bullets(self, items: list[str], *, size: float = 9.8, rtl: bool = True) -> None:
        for item in items:
            if rtl:
                self._rtl_text()
            else:
                self._ltr_text()
            h = self.measure(
                item,
                CW - (8 if rtl else 8),
                size,
                5.2,
                align="R" if rtl else "L",
            )
            self.ensure_space(h + 2.0)
            y = self.get_y()
            if rtl:
                self.set_fill_color(*BLUE)
                self.ellipse(PAGE_W - M - 2.1, y + 1.9, 1.5, 1.5, "F")
                self.set_xy(M + 2, y)
                self.multi_cell(
                    CW - 7,
                    5.2,
                    item,
                    align="R",
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
            else:
                self.set_fill_color(*BLUE)
                self.ellipse(M, y + 1.9, 1.5, 1.5, "F")
                self.set_xy(M + 4, y)
                self.multi_cell(
                    CW - 7,
                    5.2,
                    item,
                    align="L",
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
            self.ln(1.0)
        self.ln(1.2)

    def numbered(self, items: list[str], *, size: float = 9.7) -> None:
        for index, item in enumerate(items, 1):
            self._rtl_text()
            h = self.measure(item, CW - 12, size, 5.2)
            self.ensure_space(max(9.0, h + 2.0))
            y = self.get_y()
            self.set_fill_color(*PALE)
            self.ellipse(PAGE_W - M - 6.2, y, 6.2, 6.2, "F")
            self.set_font(self.body, "B", 6.6)
            self.set_text_color(*BLUE)
            self.set_xy(PAGE_W - M - 6.2, y + 0.8)
            self.cell(6.2, 4.3, str(index), align="C")

            self.set_font(self.body, "", size)
            self.set_text_color(*TEXT)
            self.set_xy(M + 2, y)
            self.multi_cell(
                CW - 11,
                5.2,
                item,
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.ln(1.0)
        self.ln(1.2)

    # ------------------------------------------------------------------
    # Reusable cards and callouts
    # ------------------------------------------------------------------
    def callout(
        self,
        title: str,
        text: str,
        *,
        tone: str = "blue",
        size: float = 9.2,
        rtl: bool = True,
    ) -> None:
        if tone == "pain":
            fill, accent = PAIN_BG, PAIN
        elif tone == "good":
            fill, accent = GOOD_BG, GOOD
        elif tone == "amber":
            fill, accent = AMBER_BG, AMBER
        else:
            fill, accent = PALE, BLUE

        align = "R" if rtl else "L"
        if rtl:
            self._rtl_text()
        else:
            self._ltr_text()
        tw = CW - 12
        th = self.measure(text, tw, size, 5.0, align=align)
        h = 10.0 + th + 4.0
        self.ensure_space(h + 3.0)
        y = self.get_y()

        self.set_fill_color(*fill)
        self.rect(M, y, CW, h, "F", round_corners=True, corner_radius=2.5)
        self.set_fill_color(*accent)
        bar_x = PAGE_W - M - 2.5 if rtl else M
        self.rect(bar_x, y + 3, 2.5, h - 6, "F")

        self.set_font(self.body, "B", 9.2)
        self.set_text_color(*accent)
        self.set_xy(M + 5, y + 3.0)
        self.cell(CW - 10, 4.6, title, align=align)

        self.set_font(self.body, "", size)
        self.set_text_color(*TEXT)
        self.set_xy(M + 5, y + 9.0)
        self.multi_cell(
            tw,
            5.0,
            text,
            align=align,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_y(y + h + 3.0)

    def stat_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        value: str,
        label: str,
        note: str = "",
        *,
        accent: tuple[int, int, int] = BLUE,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*accent)
        self.rect(x, y, w, 2.2, "F")

        self._rtl_text()
        self.set_font(self.body, "B", 18.0)
        self.set_text_color(*accent)
        self.set_xy(x + 4, y + 5.2)
        self.cell(w - 8, 8, value, align="R")

        self.set_font(self.body, "B", 8.2)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 14.0)
        self.multi_cell(
            w - 8,
            4.2,
            label,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        if note:
            self.set_font(self.body, "", 6.8)
            self.set_text_color(*MUTED)
            self.set_xy(x + 4, y + h - 7.5)
            self.multi_cell(
                w - 8,
                3.5,
                note,
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    def stat_row(self, items: list[tuple[str, str, str]], *, h: float = 29.0) -> None:
        count = len(items)
        gap = 3.0
        w = (CW - gap * (count - 1)) / count
        self.ensure_space(h + 3.0)
        y = self.get_y()
        for index, (value, label, note) in enumerate(items):
            x = PAGE_W - M - w - index * (w + gap)
            self.stat_card(x, y, w, h, value, label, note)
        self.set_y(y + h + 4.0)

    def card_height(
        self,
        title: str,
        en: str,
        body: str,
        w: float,
        *,
        title_size: float = 10.2,
        body_size: float = 8.7,
    ) -> float:
        title_h = self.measure(title, w - 21, title_size, 5.2, bold=True)
        en_h = 3.8 if en else 0.0
        body_h = self.measure(body, w - 10, body_size, 4.7)
        return max(29.0, 6.0 + title_h + en_h + 2.0 + body_h + 5.0)

    def info_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        en: str,
        body: str,
        *,
        accent: tuple[int, int, int] = BLUE,
        icon: str = "01",
        title_size: float = 10.2,
        body_size: float = 8.7,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.4)
        self.set_fill_color(*accent)
        self.rect(x + w - 2.5, y + 3, 2.5, h - 6, "F")

        self.set_fill_color(*PALE)
        self.ellipse(x + w - 12.5, y + 6.0, 8.0, 8.0, "F")
        self.set_font(self.body, "B", 6.2)
        self.set_text_color(*accent)
        self.set_xy(x + w - 12.5, y + 7.8)
        self.cell(8.0, 4.0, icon, align="C")

        self._rtl_text()
        self.set_font(self.body, "B", title_size)
        self.set_text_color(*NAVY)
        self.set_xy(x + 5, y + 5.0)
        self.multi_cell(
            w - 20,
            5.2,
            title,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        if en:
            self.set_font(self.body, "", 6.4)
            self.set_text_color(*MUTED)
            self._ltr_text()
            self.set_xy(x + 5, self.get_y() + 0.2)
            self.multi_cell(
                w - 20,
                3.6,
                en.upper(),
                align="L",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

        self._rtl_text()
        self.set_font(self.body, "", body_size)
        self.set_text_color(*TEXT)
        self.set_xy(x + 5, self.get_y() + 1.6)
        self.multi_cell(
            w - 10,
            4.7,
            body,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def card_row(
        self,
        cards: list[tuple[str, str, str, str]],
        *,
        accent: tuple[int, int, int] = BLUE,
    ) -> None:
        """Draw two equal cards: (title, en, body, icon)."""
        gap = 4.0
        w = (CW - gap) / 2
        heights = [
            self.card_height(title, en, body, w) for title, en, body, _ in cards
        ]
        h = max(heights)
        self.ensure_space(h + 4.0)
        y = self.get_y()
        for index, (title, en, body, icon) in enumerate(cards):
            x = PAGE_W - M - w - index * (w + gap)
            self.info_card(x, y, w, h, title, en, body, accent=accent, icon=icon)
        self.set_y(y + h + 4.0)

    def toggle(
        self,
        x: float,
        y: float,
        *,
        on: bool = False,
        label: str | None = None,
    ) -> None:
        track_w, track_h = 17.0, 7.0
        self.set_fill_color(*(BLUE if on else (217, 226, 235)))
        self.rect(x, y, track_w, track_h, "F", round_corners=True, corner_radius=3.5)
        knob_x = x + track_w - 5.8 if on else x + 1.4
        self.set_fill_color(*WHITE)
        self.ellipse(knob_x, y + 1.0, 5.0, 5.0, "F")
        if label:
            self.set_font(self.body, "B", 5.8)
            self.set_text_color(*(BLUE if on else MUTED))
            self.set_xy(x - 2, y + 7.4)
            self.cell(track_w + 4, 3.2, label, align="C")

    def button_card(
        self,
        title: str,
        en: str,
        body: str,
        *,
        on: bool | None = None,
        toggle_label: str | None = None,
        slider: float | None = None,
        cta: str | None = None,
        accent: tuple[int, int, int] = BLUE,
        options: list[tuple[str, str, bool]] | None = None,
    ) -> None:
        self._rtl_text()
        has_toggle = on is not None
        content_x = M + (32.0 if has_toggle else 5.0)
        content_w = CW - (70.0 if has_toggle else 44.0)
        title_h = self.measure(title, content_w, 11.0, 5.6, bold=True)
        body_h = self.measure(body, CW - 12, 8.9, 4.8)
        extra = 0.0
        if options:
            extra += 22.0
        if slider is not None:
            extra += 13.0
        if cta:
            extra += 17.0
        h = 8.0 + title_h + 4.2 + body_h + extra + 6.0

        self.ensure_space(h + 4.0)
        y = self.get_y()
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(M, y, CW, h, "DF", round_corners=True, corner_radius=2.5)
        self.set_fill_color(*accent)
        self.rect(PAGE_W - M - 2.5, y + 3, 2.5, h - 6, "F")

        self.set_font(self.body, "B", 11.0)
        self.set_text_color(*NAVY)
        self.set_xy(content_x, y + 5.0)
        self.multi_cell(
            content_w,
            5.6,
            title,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 6.6)
        self.set_text_color(*MUTED)
        self._ltr_text()
        self.set_xy(content_x, self.get_y() + 0.2)
        self.multi_cell(
            content_w,
            3.8,
            en.upper(),
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        if on is not None:
            self.toggle(
                M + 7,
                y + 7.0,
                on=on,
                label=toggle_label or ("ON" if on else "OFF"),
            )

        self._rtl_text()
        self.set_font(self.body, "", 8.9)
        self.set_text_color(*TEXT)
        self.set_xy(M + 5, self.get_y() + 2.0)
        self.multi_cell(
            CW - 10,
            4.8,
            body,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        if options:
            option_w = (CW - 20) / 2
            oy = self.get_y() + 2.5
            for index, (name, desc, selected) in enumerate(options):
                ox = PAGE_W - M - 7 - option_w - index * (option_w + 5)
                self.option_box(ox, oy, option_w, 17.0, name, desc, selected)
            self.set_y(oy + 19.0)

        if slider is not None:
            sy = self.get_y() + 5.0
            line_x1, line_x2 = M + 12, PAGE_W - M - 12
            self.set_draw_color(*LINE)
            self.set_line_width(1.2)
            self.line(line_x1, sy, line_x2, sy)
            frac = max(0.0, min(1.0, (slider - 7.0) / 23.0))
            knob_x = line_x1 + frac * (line_x2 - line_x1)
            self.set_fill_color(*BLUE)
            self.ellipse(knob_x - 2.5, sy - 2.5, 5.0, 5.0, "F")
            self.set_font(self.body, "", 6.0)
            self.set_text_color(*MUTED)
            self.set_xy(line_x1 - 2, sy + 3.2)
            self.cell(10, 3, "7", align="L")
            self.set_xy(line_x2 - 8, sy + 3.2)
            self.cell(10, 3, "30", align="R")
            self.set_font(self.body, "B", 8.2)
            self.set_text_color(*BLUE)
            self.set_xy(PAGE_W - M - 28, sy - 6.2)
            self.cell(20, 4, f"{slider:.0f} يوم", align="R")
            self.set_y(sy + 7.0)

        if cta:
            by = self.get_y() + 2.0
            bw = 64.0
            bx = M + (CW - bw) / 2
            self.set_fill_color(*BLUE)
            self.rect(bx, by, bw, 10.0, "F", round_corners=True, corner_radius=2.0)
            self.set_font(self.body, "B", 9.0)
            self.set_text_color(*WHITE)
            self.set_xy(bx, by + 2.6)
            self.cell(bw, 5, cta, align="C")
            self.set_y(by + 12.0)

        self.set_y(y + h + 4.0)

    def option_box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        desc: str,
        selected: bool,
    ) -> None:
        self.set_fill_color(*(PALE if selected else WHITE))
        self.set_draw_color(*(BLUE if selected else LINE))
        self.set_line_width(0.45 if selected else 0.3)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.0)

        cx, cy = x + w - 6.0, y + 5.0
        self.set_draw_color(*(BLUE if selected else LINE))
        self.set_line_width(0.4)
        self.ellipse(cx - 2.2, cy - 2.2, 4.4, 4.4, "D")
        if selected:
            self.set_fill_color(*BLUE)
            self.ellipse(cx - 1.2, cy - 1.2, 2.4, 2.4, "F")

        self._rtl_text()
        self.set_font(self.body, "B", 8.4)
        self.set_text_color(*(NAVY if selected else TEXT))
        self.set_xy(x + 3, y + 2.4)
        self.cell(w - 12, 4.2, title, align="R")

        self.set_font(self.body, "", 6.6)
        self.set_text_color(*MUTED)
        self.set_xy(x + 3, y + 7.0)
        self.multi_cell(
            w - 12,
            3.5,
            desc,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    # ------------------------------------------------------------------
    # Tables and legends
    # ------------------------------------------------------------------
    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        widths: list[float],
        *,
        font_size: float = 8.3,
        leading: float = 4.4,
        rtl: bool | None = None,
        header_fill: tuple[int, int, int] = NAVY,
        row_fill: tuple[int, int, int] = PALE_2,
        min_row_height: float = 8.0,
        padding: float = 1.7,
    ) -> None:
        if not rows:
            return
        use_rtl = self.rtl if rtl is None else rtl
        if use_rtl:
            headers = list(reversed(headers))
            rows = [list(reversed(row)) for row in rows]
            widths = list(reversed(widths))

        self.ensure_space(28.0)
        self.set_font(self.body, "", font_size)
        with super().table(
            col_widths=tuple(widths),
            text_align="RIGHT" if use_rtl else "LEFT",
            headings_style=FontFace(
                emphasis="BOLD",
                color=WHITE,
                fill_color=header_fill,
            ),
            line_height=leading,
            padding=padding,
            repeat_headings=1,
            borders_layout=TableBordersLayout.NONE,
            min_row_height=min_row_height,
        ) as table:
            head = table.row()
            for value in headers:
                head.cell(str(value))
            for index, row in enumerate(rows):
                fill = row_fill if index % 2 == 0 else WHITE
                line = table.row(style=FontFace(fill_color=fill))
                for value in row:
                    line.cell("" if value is None else str(value))
        self.ln(2.5)

    def legend_pill(
        self,
        x: float,
        y: float,
        label: str,
        color: tuple[int, int, int],
        *,
        w: float = 39.0,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, 7.2, "DF", round_corners=True, corner_radius=3.0)
        self.set_fill_color(*color)
        self.ellipse(x + w - 5.2, y + 2.1, 3.0, 3.0, "F")
        self.set_font(self.body, "", 6.8)
        self.set_text_color(*TEXT)
        self.set_xy(x + 2, y + 1.2)
        self.cell(w - 9, 4.5, label, align="R")

    def color_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        note: str,
        fill: tuple[int, int, int],
        accent: tuple[int, int, int],
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*fill)
        self.rect(x + w - 12, y + 4, 8, 8, "F", round_corners=True, corner_radius=1.5)
        self.set_fill_color(*accent)
        self.rect(x + w - 12, y + 4, 8, 1.5, "F", round_corners=True, corner_radius=0.7)

        self._rtl_text()
        self.set_font(self.body, "B", 8.8)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 3.5)
        self.cell(w - 18, 4.5, title, align="R")

        self.set_font(self.body, "", 6.8)
        self.set_text_color(*MUTED)
        self.set_xy(x + 4, y + 9.0)
        self.multi_cell(
            w - 18,
            3.6,
            note,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    # ------------------------------------------------------------------
    # Cover and section openings
    # ------------------------------------------------------------------
    def cover(self) -> None:
        self.add_page()
        self.set_fill_color(248, 250, 252)
        self.rect(0, 0, PAGE_W, PAGE_H, "F")
        self.set_fill_color(*NAVY)
        self.rect(PAGE_W - 10, 0, 10, PAGE_H, "F")
        self.set_fill_color(*PALE)
        self.rect(0, 0, PAGE_W - 10, 8, "F")

        self.image(str(LOGO), M, 18, 24)
        self._ltr_text()
        self.set_font(self.body, "B", 9.0)
        self.set_text_color(*NAVY)
        self.set_xy(45, 21)
        self.cell(0, 5, "AUTO ORDER V2", align="L")
        self.set_font(self.body, "", 6.5)
        self.set_text_color(*MUTED)
        self.set_xy(45, 27)
        self.cell(0, 4, "PHARMACY SUPPLY CHAIN  ·  OPERATIONS", align="L")

        self._ltr_text()
        self.set_font(self.body, "B", 7.3)
        self.set_text_color(*BLUE)
        self.set_xy(M, 53)
        self.cell(0, 5, "EXECUTIVE REPORT  ·  STANDARD OPERATING PROCEDURE", align="L")

        self._rtl_text()
        self.set_font(self.body, "B", 22.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, 60)
        self.multi_cell(
            176,
            10.6,
            "تقرير تقييم نظام الأوتو أوردر\n(Auto Order V2)\nودليل التشغيل",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 11.4)
        self.set_text_color(*STEEL)
        self.set_xy(M, self.get_y() + 3.0)
        self.multi_cell(
            176,
            6.2,
            "مقارنة بين النظام اليدوي الحالي والنظام الآلي الجديد",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 9.0)
        self.set_text_color(*MUTED)
        self.set_xy(M, self.get_y() + 1.5)
        self.multi_cell(
            176,
            5.0,
            "من التقدير اليدوي إلى قرار شرائي علمي، قابل للقياس والتدقيق.",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_draw_color(*LINE)
        self.set_line_width(0.4)
        self.line(M, 124, PAGE_W - M, 124)

        meta = [
            ("التاريخ", "3 نوفمبر 2026", "DATE"),
            ("الإعداد", "إدارة العمليات / تطوير الأنظمة", "PREPARED BY"),
            ("الإصدار", "Auto Order V2.0", "VERSION"),
            ("النطاق", "51 فرعاً · 10 ملفات · 20 عموداً", "SCOPE"),
        ]
        card_w, card_h, gap = 85.0, 21.0, 6.0
        positions = [
            (PAGE_W - M - card_w, 134.0),
            (M, 134.0),
            (PAGE_W - M - card_w, 160.0),
            (M, 160.0),
        ]
        for (label, value, en), (x, y) in zip(meta, positions):
            self.meta_card(x, y, card_w, card_h, label, value, en)

        self.set_fill_color(*PALE)
        self.rect(M, 197, CW, 34, "F", round_corners=True, corner_radius=3.0)
        self.set_fill_color(*BLUE)
        self.rect(PAGE_W - M - 2.5, 201, 2.5, 26, "F")
        self._rtl_text()
        self.set_font(self.serif, "B", 13.0)
        self.set_text_color(*NAVY)
        self.set_xy(M + 7, 203)
        self.multi_cell(
            CW - 14,
            6.2,
            "«القرار الجيد يبدأ ببيانات نظيفة، وينتهي بطلب قابل للتدقيق.»",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_font(self.body, "", 7.6)
        self.set_text_color(*MUTED)
        self.set_xy(M + 7, 218)
        self.cell(CW - 14, 4, "مبدأ تشغيل Auto Order V2", align="R")

        self.set_y(252)
        self.set_font(self.body, "", 7.0)
        self.set_text_color(*MUTED)
        self._rtl_text()
        self.cell(0, 4, "وثيقة داخلية — للاستخدام الإداري", align="C")
        self.set_y(258)
        self.cell(0, 4, "Auto Order V2.0  ·  Operations & Systems Development", align="C")

    def meta_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        value: str,
        en: str,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*BLUE)
        self.rect(x + w - 2.5, y + 3.0, 2.5, h - 6.0, "F")

        self._rtl_text()
        self.set_font(self.body, "B", 6.6)
        self.set_text_color(*MUTED)
        self.set_xy(x + 4, y + 3.0)
        self.cell(w - 9, 4, label, align="R")

        self.set_font(self.body, "B", 8.8)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 8.0)
        self.multi_cell(
            w - 9,
            4.6,
            value,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 5.8)
        self.set_text_color(*MUTED)
        self._ltr_text()
        self.set_xy(x + 4, y + h - 5.2)
        self.cell(w - 9, 3, en, align="L")

    def section_cover(
        self,
        number: str,
        kicker: str,
        title: str,
        lead: str,
        *,
        accent: tuple[int, int, int] = BLUE,
    ) -> None:
        self._suppress_header = True
        self.add_page()
        self._suppress_header = False
        self.section_label = title

        self.set_fill_color(*PALE)
        self.rect(0, 0, PAGE_W, 80, "F")
        self.set_fill_color(*accent)
        self.rect(PAGE_W - 7, 0, 7, 80, "F")

        self._ltr_text()
        self.set_font(self.body, "B", 51.0)
        self.set_text_color(*SKY)
        self.set_xy(M, 12)
        self.cell(50, 22, number, align="L")

        self.set_font(self.body, "B", 7.1)
        self.set_text_color(*accent)
        self.set_xy(70, 17)
        self.cell(123, 5, kicker.upper(), align="R")

        self._rtl_text()
        self.set_font(self.body, "B", 22.5)
        self.set_text_color(*NAVY)
        self.set_xy(70, 27)
        self.multi_cell(
            123,
            10.4,
            title,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 10.0)
        self.set_text_color(*TEXT)
        self.set_xy(70, self.get_y() + 4.0)
        self.multi_cell(
            123,
            5.5,
            lead,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_draw_color(*LINE)
        self.set_line_width(0.4)
        self.line(M, 86, PAGE_W - M, 86)
        self.set_y(94)

    # ------------------------------------------------------------------
    # Specialized content blocks
    # ------------------------------------------------------------------
    def flow_strip(self, items: list[tuple[str, str, str]]) -> None:
        count = len(items)
        gap = 3.2
        w = (CW - gap * (count - 1)) / count
        h = 19.0
        self.ensure_space(h + 4.0)
        y = self.get_y()
        for index, (num, title, en) in enumerate(items):
            x = PAGE_W - M - w - index * (w + gap)
            self.set_fill_color(*PALE)
            self.set_draw_color(*LINE)
            self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.0)
            self._ltr_text()
            self.set_font(self.body, "B", 7.0)
            self.set_text_color(*BLUE)
            self.set_xy(x + 3, y + 2.2)
            self.cell(w - 6, 4, num, align="L")
            self._rtl_text()
            self.set_font(self.body, "B", 8.0)
            self.set_text_color(*NAVY)
            self.set_xy(x + 3, y + 7.0)
            self.cell(w - 6, 4, title, align="R")
            self.set_font(self.body, "", 5.8)
            self.set_text_color(*MUTED)
            self._ltr_text()
            self.set_xy(x + 3, y + 12.0)
            self.cell(w - 6, 3.2, en, align="L")
        self.set_y(y + h + 4.0)

    def formula_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        formula: str,
        note: str,
    ) -> None:
        self.set_fill_color(*PALE_2)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*BLUE)
        self.rect(x + w - 2.2, y + 3, 2.2, h - 6, "F")

        self._rtl_text()
        self.set_font(self.body, "B", 8.4)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 2.4)
        self.cell(w - 8, 4.0, title, align="R")

        self._ltr_text()
        self.set_font(self.body, "B", 6.9)
        self.set_text_color(*BLUE)
        self.set_xy(x + 4, y + 7.0)
        self.cell(w - 8, 3.6, formula, align="L")

        self._rtl_text()
        self.set_font(self.body, "", 6.3)
        self.set_text_color(*MUTED)
        self.set_xy(x + 4, y + 12.2)
        self.multi_cell(
            w - 8,
            3.4,
            note,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def formula_grid(self, formulas: list[tuple[str, str, str]]) -> None:
        gap_x, gap_y = 4.0, 2.5
        w = (CW - gap_x) / 2
        h = 24.0
        rows = (len(formulas) + 1) // 2
        self.ensure_space(rows * h + (rows - 1) * gap_y + 2.0)
        start_y = self.get_y()
        for index, (title, formula, note) in enumerate(formulas):
            row, col = divmod(index, 2)
            x = PAGE_W - M - w - col * (w + gap_x)
            y = start_y + row * (h + gap_y)
            self.formula_card(x, y, w, h, title, formula, note)
        self.set_y(start_y + rows * h + (rows - 1) * gap_y + 4.0)

    def upload_header(self) -> None:
        self.ensure_space(20)
        y = self.get_y()
        self.set_fill_color(*PALE)
        self.rect(M, y, CW, 16, "F", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*BLUE)
        self.ellipse(PAGE_W - M - 13, y + 3.5, 9, 9, "F")
        self.set_font(self.body, "B", 7.0)
        self.set_text_color(*WHITE)
        self.set_xy(PAGE_W - M - 13, y + 5.7)
        self.cell(9, 4, "10", align="C")
        self._rtl_text()
        self.set_font(self.body, "B", 9.0)
        self.set_text_color(*NAVY)
        self.set_xy(M + 5, y + 3.0)
        self.cell(CW - 25, 4.5, "منطقة رفع الملفات — 3 ملفات إلزامية + 7 اختيارية", align="R")
        self.set_font(self.body, "", 7.0)
        self.set_text_color(*MUTED)
        self.set_xy(M + 5, y + 9.0)
        self.cell(CW - 25, 3.8, "النظام يتعرّف على نوع الملف من الأعمدة، وليس من اسم الملف.", align="R")
        self.set_y(y + 20.0)

    def file_box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        num: str,
        title: str,
        en: str,
        required: bool,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.0)
        self.set_fill_color(*(PALE if required else MIST))
        self.ellipse(x + w - 9.5, y + 3.5, 6.0, 6.0, "F")
        self.set_font(self.body, "B", 5.7)
        self.set_text_color(*(BLUE if required else MUTED))
        self.set_xy(x + w - 9.5, y + 5.0)
        self.cell(6.0, 3.2, num, align="C")

        self._rtl_text()
        self.set_font(self.body, "B", 7.7)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 3.0)
        self.multi_cell(
            w - 15,
            3.8,
            title,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        self.set_font(self.body, "", 5.6)
        self.set_text_color(*MUTED)
        self._ltr_text()
        self.set_xy(x + 4, y + h - 8.4)
        self.cell(w - 18, 3, en, align="L")

        self._rtl_text()
        self.set_font(self.body, "B", 5.4)
        self.set_text_color(*(BLUE if required else MUTED))
        self.set_xy(x + 4, y + h - 4.7)
        self.cell(w - 8, 2.8, "إلزامي" if required else "اختياري", align="R")

    def upload_grid(self) -> None:
        files = [
            ("01", "ملف الأصناف الأساسي", "MASTER CATALOGUE", True),
            ("02", "تقرير النواقص", "SHORTAGES", True),
            ("03", "رصيد الفرع", "BRANCH STOCK", True),
            ("04", "رصيد المخزن المركزي", "WAREHOUSE STOCK", False),
            ("05", "مبيعات الفرع الحديثة", "RECENT SALES", False),
            ("06", "تحت التوريد", "PENDING PURCHASES", False),
            ("07", "التحويلات", "TRANSFERS", False),
            ("08", "لوحة المبيعات التاريخية", "HISTORICAL SALES", False),
            ("09", "أصناف متعددة الكروت", "MULTI-PRICE ITEMS", False),
            ("10", "قائمة Pushing", "PUSHING LIST", False),
        ]
        gap_x, gap_y = 4.0, 2.4
        w = (CW - gap_x) / 2
        h = 18.4
        self.ensure_space(5 * h + 4 * gap_y + 2)
        start_y = self.get_y()
        for index, (num, title, en, required) in enumerate(files):
            row, col = divmod(index, 2)
            x = PAGE_W - M - w - col * (w + gap_x)
            y = start_y + row * (h + gap_y)
            self.file_box(x, y, w, h, num, title, en, required)
        self.set_y(start_y + 5 * h + 4 * gap_y + 4.0)

    def color_legend(self) -> None:
        items = [
            ("تحميل من المخزن", "الكمية المغطاة من المخزن المركزي", PINK, PINK_DARK),
            ("Pushing", "أصناف قائمة الدفع / الأولوية", BLUE_LIGHT, BLUE_DARK),
            ("تحويلات", "حركة تحويل بين الفروع", YELLOW, YELLOW_DARK),
            ("تعدد الكروت", "الصنف له أكثر من كارت أو سعر", GREY, GREY_DARK),
        ]
        gap_x, gap_y = 4.0, 2.8
        w = (CW - gap_x) / 2
        h = 18.0
        self.ensure_space(2 * h + gap_y + 2)
        start_y = self.get_y()
        for index, (title, note, fill, accent) in enumerate(items):
            row, col = divmod(index, 2)
            x = PAGE_W - M - w - col * (w + gap_x)
            y = start_y + row * (h + gap_y)
            self.color_card(x, y, w, h, title, note, fill, accent)
        self.set_y(start_y + 2 * h + gap_y + 4.0)

    def phase_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        num: str,
        title: str,
        body: str,
    ) -> None:
        self.set_fill_color(*WHITE)
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.2)
        self.set_fill_color(*PALE)
        self.ellipse(x + w - 13, y + 4, 8.5, 8.5, "F")
        self.set_font(self.body, "B", 6.4)
        self.set_text_color(*BLUE)
        self.set_xy(x + w - 13, y + 5.8)
        self.cell(8.5, 4, num, align="C")
        self._rtl_text()
        self.set_font(self.body, "B", 8.4)
        self.set_text_color(*NAVY)
        self.set_xy(x + 4, y + 14)
        self.multi_cell(
            w - 8,
            4.3,
            title,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_font(self.body, "", 7.1)
        self.set_text_color(*TEXT)
        self.set_xy(x + 4, self.get_y() + 1.0)
        self.multi_cell(
            w - 8,
            3.8,
            body,
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    # ------------------------------------------------------------------
    # Document content
    # ------------------------------------------------------------------
    def build(self) -> None:
        self.cover()
        self.executive_summary()
        self.section_one()
        self.section_two()
        self.section_three()
        self.section_four()
        self.section_five()
        self.english_snapshot()

    def executive_summary(self) -> None:
        self.section_label = "الملخص التنفيذي"
        self.add_page()
        self._ltr_text()
        self.set_font(self.body, "B", 7.0)
        self.set_text_color(*BLUE)
        self.set_xy(M, 26)
        self.cell(0, 4, "EXECUTIVE SUMMARY  ·  AT A GLANCE", align="L")

        self._rtl_text()
        self.set_font(self.body, "B", 22.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, 34)
        self.multi_cell(
            CW,
            10.0,
            "ملخص تنفيذي: لماذا نغيّر طريقة عمل الأوتو أوردر؟",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_font(self.body, "", 10.0)
        self.set_text_color(*TEXT)
        self.set_xy(M, self.get_y() + 3)
        self.multi_cell(
            CW,
            5.6,
            "النظام الحالي يستهلك وقتاً كبيراً في تجميع 10 تقارير ودمجها يدوياً، ثم يترك القرار النهائي للتقدير الشخصي. "
            "Auto Order V2 يحوّل هذه الرحلة إلى مسار واحد: رفع الملفات، تطبيق معادلات علمية، مراجعة القيود، ثم إخراج طلبية موثقة بـ 20 عموداً.",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(5)

        self.stat_row(
            [
                ("10", "ملفات في مكان واحد", "بدلاً من 10 تقارير متفرقة"),
                ("0", "VLOOKUP أو SUMIFS", "دمج آلي وتنظيف موحد للأكواد"),
                ("20", "عموداً في المخرج", "رؤية مالية وتشغيلية كاملة"),
                ("ثوانٍ", "لتوليد الطلبية", "بدلاً من ساعات أو أيام"),
            ],
            h=31.0,
        )

        self.h2("ما الذي يقدمه V2 للإدارة؟", "THE MANAGEMENT CASE")
        self.bullets(
            [
                "قرار شرائي موحّد لكل فرع، مبني على ROP وTarget Level وSafety Stock بدلاً من التقدير الشخصي.",
                "شفافية مالية فورية: كل سطر يحمل السعر، القيمة المالية للطلب، وتاريخ الوصول المتوقع.",
                "حماية رأس المال من المخزون الميت عبر استبعاد الرواكد وتوثيق سبب الاستبعاد.",
                "قابلية تدقيق كاملة: معادلة نهائية واضحة، وفحص Fail-Fast قبل export، وأثر واضح لكل Toggle.",
            ]
        )

        self.h2("محتويات التقرير", "REPORT MAP")
        contents = [
            ("01", "تحليل الوضع الحالي", "رحلة الطلبية اليدوية، نقاط الهدر، وحلقة الخطأ."),
            ("02", "نظام V2 الجديد", "المعادلات، محرك القرار، والضوابط."),
            ("03", "جدول المقارنة الشامل", "12 بنداً بين اليدوي وV2."),
            ("04", "دليل التشغيل", "كل زر، كل Toggle، وكل عمود من الـ 20."),
            ("05", "القيمة المضافة", "العائد التشغيلي والمالي وخطة الانتقال."),
        ]
        for num, title, desc in contents:
            self.ensure_space(12)
            y = self.get_y()
            self.set_fill_color(*PALE)
            self.ellipse(PAGE_W - M - 9, y + 1.5, 7.5, 7.5, "F")
            self._ltr_text()
            self.set_font(self.body, "B", 6.6)
            self.set_text_color(*BLUE)
            self.set_xy(PAGE_W - M - 9, y + 3.0)
            self.cell(7.5, 3.6, num, align="C")
            self._rtl_text()
            self.set_font(self.body, "B", 9.0)
            self.set_text_color(*NAVY)
            self.set_xy(M + 5, y + 1.0)
            self.cell(CW - 20, 4.2, title, align="R")
            self.set_font(self.body, "", 7.2)
            self.set_text_color(*MUTED)
            self.set_xy(M + 5, y + 5.3)
            self.multi_cell(
                CW - 20,
                3.6,
                desc,
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.ln(2.0)

        self.callout(
            "الرسالة الأساسية",
            "V2 لا يسرّع العمل فقط؛ بل يغيّر طبيعة القرار من «تقدير شخصي» إلى «سياسة قابلة للتكرار والتدقيق».",
            tone="blue",
        )

    def section_one(self) -> None:
        self.section_cover(
            "01",
            "AS-IS PROCESS  ·  THE MANUAL NIGHTMARE",
            "تحليل الوضع الحالي: رحلة الطلبية اليدوية",
            "قبل الحديث عن الحل، يجب تسمية المشكلة بدقة: 10 تقارير، دمج يدوي، معادلات غير موثقة، وقرارات تعتمد على الخبرة الشخصية.",
            accent=PAIN,
        )

        self.h2("رحلة الطلبية اليوم — خطوة بخطوة", "THE CURRENT WORKFLOW")
        self.p(
            "كل خطوة تبدو بسيطة بمفردها، لكن تراكمها هو ما يخلق التأخير والأخطاء. هذه هي الرحلة كما تحدث فعلياً:",
            size=9.7,
        )

        steps = [
            (
                "01",
                "استخراج البيانات",
                "DATA EXTRACTION",
                "سحب يدوي لـ 10 تقارير من PharmaFly: النواقص، كل الأصناف، رصيد الفرع، رصيد المخزن، مبيعات الشهر، مبيعات آخر 3 شهور، التحويلات، تحت التوريد، Pushing List، والأصناف متعددة الكروت.",
                PAIN,
            ),
            (
                "02",
                "الدمج والمعادلات",
                "MERGING",
                "استخدام VLOOKUP لربط الأكواد وSUMIFS لتجميع الأرصدة. أخطاء بشرية مستمرة، وتضارب في الأكواد (.0)، وملفات لا تتحدث بنفس المنطق.",
                PAIN,
            ),
            (
                "03",
                "المعادلات الخاطئة",
                "FLAWED MATH",
                "إضافة التحويلات الصادرة على المبيعات — خطأ رياضياً يرهق المخزن — وحساب Demand بناءً على تقدير بشري بدلاً من متوسط علمي.",
                PAIN,
            ),
            (
                "04",
                "القرارات الشخصية",
                "HUMAN JUDGMENT",
                "توزيع التجميل، اختيار البدائل، وتحديد الرواكد يتم بناءً على «خبرة مسؤول الأوتو أوردر»، وليس على معادلة قابلة للتكرار.",
                PAIN,
            ),
            (
                "05",
                "النتيجة",
                "THE RESULT",
                "أخطاء بشرية، ساعات طويلة من العمل، مخزون ميت، ونقص في أصناف حيوية. الإدارة تطلب تفسيراً، لكن لا يوجد أثر موثق لكل قرار.",
                PAIN,
            ),
        ]

        for num, title, en, body, accent in steps:
            self.ensure_space(31)
            y = self.get_y()
            h = 27.0
            self.set_fill_color(*WHITE)
            self.set_draw_color(*LINE)
            self.rect(M, y, CW, h, "DF", round_corners=True, corner_radius=2.3)
            self.set_fill_color(*PAIN_BG)
            self.ellipse(PAGE_W - M - 12, y + 4.0, 8.0, 8.0, "F")
            self._ltr_text()
            self.set_font(self.body, "B", 6.3)
            self.set_text_color(*accent)
            self.set_xy(PAGE_W - M - 12, y + 5.8)
            self.cell(8.0, 4.0, num, align="C")

            self._rtl_text()
            self.set_font(self.body, "B", 10.0)
            self.set_text_color(*NAVY)
            self.set_xy(M + 5, y + 3.5)
            self.cell(80, 4.5, title, align="R")
            self.set_font(self.body, "", 6.2)
            self.set_text_color(*MUTED)
            self._ltr_text()
            self.set_xy(M + 5, y + 8.0)
            self.cell(80, 3.2, en, align="L")

            self._rtl_text()
            self.set_font(self.body, "", 8.1)
            self.set_text_color(*TEXT)
            self.set_xy(M + 5, y + 12.0)
            self.multi_cell(
                CW - 25,
                4.4,
                body,
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.set_y(y + h + 3.2)

        self.callout(
            "خمس خطوات = خمس نقاط فشل",
            "كل خطوة في الرحلة اليدوية تعتمد على الخطوة التي قبلها. خطأ واحد في كود أو تحويل أو شهر ينتقل إلى النتيجة النهائية دون أن يوقفه النظام.",
            tone="pain",
        )

        self.h2("أين يتسرب الوقت والمال؟", "WHERE VALUE LEAKS")
        self.stat_row(
            [
                ("10", "تقارير منفصلة", "استخراج ومراجعة يدوية"),
                ("3+", "ساعات إلى أيام", "حسب حجم الفرع والملفات"),
                ("16", "عموداً فقط", "لا قيمة مالية ولا تاريخ وصول"),
                ("N/A", "قرار غير موثق", "يعتمد على الخبرة الشخصية"),
            ],
            h=28.0,
        )
        self.callout(
            "حلقة الخطأ",
            "بيانات يدوية ← أرقام متضاربة ← قرار غير دقيق ← مخزون ميت أو نقص ← مزيد من العمل اليدوي لتصحيح الأثر. كل دورة تغذي التي تليها.",
            tone="pain",
        )

        self.h2("مخاطر مباشرة على الشركة", "OPERATIONAL RISKS")
        self.card_row(
            [
                (
                    "مخزون ميت",
                    "Dead stock",
                    "شراء كميات لا تتحرك بسبب تقدير مبالغ فيه أو عدم مراجعة الرواكد، فيتجمد رأس المال في المخزن.",
                    "01",
                ),
                (
                    "نقص أصناف حيوية",
                    "Stock-out",
                    "خطأ في قراءة النواقص أو التحويلات قد يترك صنفاً حيوياً بلا طلب، فتظهر شكاوى الفروع.",
                    "02",
                ),
            ],
            accent=PAIN,
        )
        self.card_row(
            [
                (
                    "وقت غير قابل للقياس",
                    "Unmeasured effort",
                    "ساعات التجميع والمراجعة لا تظهر في أي مؤشر، ولا يمكن تحسينها أو مقارنتها بين الفروع.",
                    "03",
                ),
                (
                    "غياب أثر التدقيق",
                    "No audit trail",
                    "لا يوجد سجل يشرح لماذا طُلب صنف أو استُبعد آخر؛ الإدارة ترى النتيجة ولا ترى السبب.",
                    "04",
                ),
            ],
            accent=PAIN,
        )
        self.callout(
            "السؤال الذي يجب أن يطرحه الاجتماع",
            "كم فرعاً يكرر نفس الخطأ اليوم؟ وكم ساعة تُنفق في تصحيح أثر قرار لم يُوثّق أصلاً؟",
            tone="pain",
        )
        self.callout(
            "الخلاصة",
            "المشكلة ليست في مجهود الفريق؛ المشكلة في نظام يطلب من الفريق أن يعمل كآلة. V2 يعيد للفريق دوره في المراجعة والقرار، لا في النسخ واللصق.",
            tone="blue",
        )

    def section_two(self) -> None:
        self.section_cover(
            "02",
            "TO-BE PROCESS  ·  THE SCIENTIFIC ENGINE",
            "نظام V2: من 10 ملفات إلى طلبية واحدة",
            "V2 لا يضيف طبقة أخرى من العمل اليدوي؛ بل يستبدل رحلة التجميع والقرار بمحرك واحد قابل للضبط والتدقيق.",
            accent=BLUE,
        )

        self.h2("المسار الجديد في 6 خطوات", "THE V2 FLOW")
        self.flow_strip(
            [
                ("01", "رفع الملفات", "UPLOAD"),
                ("02", "تنظيف ودمج", "CLEAN & MERGE"),
                ("03", "حساب الطلب", "CALCULATE"),
                ("04", "تطبيق القيود", "RULES"),
                ("05", "مراجعة", "REVIEW"),
                ("06", "Excel", "EXPORT"),
            ]
        )
        self.p(
            "كل خطوة لها مدخل واضح ومخرج واضح. لا VLOOKUP يدوي، ولا معادلات مبعثرة في ملفات منفصلة، ولا قرارات غير موثقة.",
            size=9.7,
        )

        self.h2("المعادلات التي تحكم القرار", "THE MATH")
        formulas = [
            ("Daily Demand", "Daily Demand = Average / 30", "المتوسط الشهري يُحوّل إلى طلب يومي. لا قسمة على Lead Time."),
            ("Safety Stock", "Safety Stock = Z x Sigma_daily x sqrt(LT)", "مخزون أمان علمي يحمي من تقلب الطلب أثناء التوريد."),
            ("ROP", "ROP = Daily Demand x LT + Safety Stock", "نقطة إعادة الطلب: لا نطلب إلا إذا نزل المخزون الفعلي تحتها."),
            ("Target Level", "Target = Daily Demand x (LT + Coverage Days)", "الكمية المستهدفة تغطي التوريد وفترة التغطية المختارة."),
            ("Final Order", "Final = Calculated Order - Warehouse Covered", "المخزن المركزي يخصم من الطلب قبل الإخراج."),
            ("Substitutes", "Substitute = max(0, Calculated - Warehouse)", "طلب العجز فقط عند نقص المخزن، لا طلب الصنف الأساسي مرتين."),
        ]
        self.formula_grid(formulas)
        self.callout(
            "مبدأ التطبيق",
            "كل معادلة تُطبق على مستوى الصنف والفرع، وليس على إجمالي الطلبية. هذا ما يمنع أن يخفي صنف سريع الحركة خطأً في صنف راكد.",
            tone="blue",
        )

        self.add_page()
        self.section_label = "نظام V2: من 10 ملفات إلى طلبية واحدة"
        self.h2("محرك القرار في 4 خطوات", "THE DECISION ENGINE")
        self.numbered(
            [
                "تنظيف وتوحيد الأكواد، ثم دمج الملفات آلياً بواسطة Pandas مع تحديد دور كل ملف من أعمدته.",
                "حساب Daily Demand ثم Safety Stock وROP وTarget Level لكل صنف وفرع.",
                "تطبيق القواعد: التحويلات (Toggle)، الرواكد، التجميل، Pushing، والبدائل — كل قاعدة معزولة وقابلة للتفسير.",
                "خصم تغطية المخزن، ثم فحص Fail-Fast: هل النهائي = المحسوب - المخزن + البدائل؟ قبل أي export.",
            ]
        )
        self.callout(
            "Fail-Fast بدلاً من التصحيح اليدوي",
            "إذا اختلف الرقم النهائي عن معادلة التدقيق، يظهر تحذير واضح قبل التصدير. هذا يمنع خروج طلبية «تبدو صحيحة» لكنها غير قابلة للتفسير.",
            tone="good",
        )

        self.h2("مثال رقمي مبسط", "A WORKED EXAMPLE")
        self.callout(
            "كيف تتحول المعادلة إلى قرار؟",
            "متوسط مبيعات 24 وحدة شهرياً = 0.8 يومياً. مع LT = 3 أيام وSafety Stock = 3.4، يصبح ROP = 5.8. "
            "إذا كان Effective Stock = 10 فلا يوجد طلب. وإذا نزل إلى 4، يبدأ الطلب من Target Level بعد إضافة أيام التغطية. "
            "هذه الأرقام توضيحية فقط، لكن المنطق نفسه هو ما يطبقه V2 على كل صنف.",
            tone="blue",
        )

        self.h2("قواعد القرار في جدول واحد", "THE RULE TABLE")
        self.table(
            ["الحالة", "القاعدة", "النتيجة"],
            [
                ["Effective Stock > ROP", "Required = 0", "لا يوجد طلب"],
                ["Effective Stock <= ROP", "Required = ceil(Target - Effective Stock)", "طلب للوصول إلى الهدف"],
                ["Warehouse < Calculated", "Substitute = shortfall only", "طلب بديل للعجز فقط"],
                ["Pushing / Cosmetics", "Force only when its toggle is ON", "طلب إجباري عند التفعيل"],
                ["Stagnant / no sales", "Exclude and document the reason", "راكد - لا يحتاج طلب"],
            ],
            [48.0, 76.0, 52.0],
            font_size=7.5,
            leading=4.0,
            min_row_height=7.4,
            padding=1.5,
        )
        self.callout(
            "ماذا يعني ذلك للفريق؟",
            "لم يعد على الفريق أن يقرر «هل نطلب؟» من الصفر. القاعدة تحدد الحالة، والمعادلة تحدد الكمية، والتوثيق يشرح السبب. دور الفريق ينتقل إلى مراجعة الاستثناءات وجودة البيانات.",
            tone="blue",
        )

    def section_three(self) -> None:
        self.section_cover(
            "03",
            "SIDE-BY-SIDE  ·  THE COMPARISON",
            "جدول المقارنة الشامل: اليدوي مقابل V2",
            "اثنا عشر بنداً تلخص الفرق بين طريقة تعتمد على المجهود البشري، ونظام يعتمد على بيانات نظيفة وسياسة حسابية موثقة.",
            accent=BLUE,
        )

        self.h2("المقارنة التفصيلية", "DETAILED COMPARISON")
        self.p(
            "الجدول التالي هو جوهر رسالة الاجتماع: أين تختفي الساعات، وأين تنشأ الأخطاء، وأين تتحسن جودة القرار.",
            size=9.4,
        )

        legend_y = self.get_y()
        self.set_fill_color(*PAIN)
        self.ellipse(PAGE_W - M - 4, legend_y + 1.8, 2.6, 2.6, "F")
        self.set_font(self.body, "", 7.0)
        self.set_text_color(*TEXT)
        self.set_xy(PAGE_W - M - 46, legend_y)
        self.cell(40, 4.2, "النظام اليدوي", align="R")
        self.set_fill_color(*BLUE)
        self.ellipse(PAGE_W - M - 73, legend_y + 1.8, 2.6, 2.6, "F")
        self.set_xy(PAGE_W - M - 115, legend_y)
        self.cell(40, 4.2, "نظام V2", align="R")
        self.ln(7.0)

        rows = [
            ["استخراج البيانات", "10 تقارير يدوية من PharmaFly", "رفع ذكي لـ 10 ملفات بضغطة واحدة"],
            ["دمج البيانات", "VLOOKUP وSUMIFS وأخطاء الأكواد (.0)", "Pandas Merge آلي وتنظيف موحد"],
            ["المعادلات", "تقدير شخصي غير موثق", "ROP وTarget Level وSafety Stock علمي"],
            ["حساب الـ Demand", "مبيعات متضاربة وتقدير بشري", "Daily Demand = Average / 30"],
            ["التحويلات", "تُضاف على المبيعات وتفسد الحساب", "معزولة ومربوطة بـ Toggle"],
            ["الشهور التاريخية", "كتابة يدوية للشهور", "سحب ديناميكي للشهور الأربعة"],
            ["البدائل", "اختيار شخصي للبديل", "طلب العجز فقط آلياً"],
            ["الرواكد", "تبقى في الشيت وتشتكي منها الإدارة", "استبعاد آلي وتوثيق «راكد»"],
            ["توزيع التجميل", "تقدير شخصي", "Force Push ذكي ومربوط بـ Toggle"],
            ["الأخطاء البشرية", "عالية جداً", "شبه معدومة مع Fail-Fast"],
            ["الوقت المستغرق", "ساعات أو أيام", "ثوانٍ معدودة"],
            ["الأعمدة المخرجة", "16 عموداً", "20 عموداً مع القيمة المالية وتاريخ الوصول"],
        ]
        headers = ["وجه المقارنة", "النظام اليدوي الحالي", "نظام V2 الجديد"]
        widths = [37.0, 65.0, 74.0]
        self.table(
            headers,
            rows,
            widths,
            font_size=8.0,
            leading=4.2,
            min_row_height=8.0,
            padding=1.6,
        )

        self.callout(
            "الخلاصة التنفيذية",
            "V2 لا يستبدل «خبرة» الفريق؛ بل يحوّلها إلى سياسة واضحة: البيانات موحدة، المعادلة واحدة، والاستثناء موثق. الخبرة تنتقل من التخمين إلى ضبط القواعد.",
            tone="blue",
        )

    def section_four(self) -> None:
        self.section_cover(
            "04",
            "STANDARD OPERATING PROCEDURE  ·  BUTTON BY BUTTON",
            "دليل التشغيل: كل زر وكل مخرج",
            "هذا القسم هو المرجع العملي للفريق: ماذا يفعل كل زر، ومتى يُستخدم، وما أثره على الطلبية والمخرج النهائي.",
            accent=BLUE,
        )

        self.h2("خريطة الواجهة", "SCREEN MAP")
        self.flow_strip(
            [
                ("01", "شاشة الإدخال", "INPUT"),
                ("02", "لوحة الإعدادات", "SETTINGS"),
                ("03", "توليد الطلبية", "GENERATE"),
                ("04", "المخرجات", "OUTPUT"),
            ]
        )
        self.p(
            "الواجهة مقسمة إلى أربع مناطق. املأ الإدخال أولاً، راجع الإعدادات، اضغط توليد الطلبية، ثم راجع المعاينة ونزّل Excel.",
            size=9.5,
        )

        self.h2("شاشة الإدخال: سياق الطلبية", "ORDER CONTEXT")
        self.card_row(
            [
                (
                    "التاريخ",
                    "Order Date",
                    "اختيار يوم عمل الطلبية. يؤثر مباشرة على حساب Lead Time، وعلى الأشهر الديناميكية التي تُسحب للمبيعات.",
                    "01",
                ),
                (
                    "الفرع",
                    "Branch",
                    "اختيار الفرع المراد عمل الأوتو أوردر له. كل فرع له رصيده، تحويلاته، ومبيعاته المستقلة.",
                    "02",
                ),
            ]
        )

        self.callout(
            "قاعدة الرفع",
            "ثلاثة ملفات إلزامية فقط: الماستر، النواقص، ورصيد الفرع. الباقي اختياري ويحسّن الدقة. لا ترفع ملفاً باسم مختلف لمجرد أن الاسم «يبدو» صحيحاً؛ النظام يقرأ الأعمدة.",
            tone="blue",
        )
        self.h2("الإدخال مقابل الإعدادات", "INPUT VS. SETTINGS")
        self.card_row(
            [
                (
                    "الإدخال",
                    "Input",
                    "يجيب على سؤالين: لمن الطلبية؟ ومتى؟ التاريخ والفرع والملفات هي سياق التشغيل.",
                    "01",
                ),
                (
                    "الإعدادات",
                    "Settings",
                    "تجيب على سؤال: كيف نحسب؟ طريقة الحساب، أيام التغطية، وToggles القرار.",
                    "02",
                ),
            ]
        )
        self.add_page()
        self.section_label = "دليل التشغيل: كل زر وكل مخرج"
        self.h2("منطقة رفع الملفات", "FILE UPLOAD AREA")
        self.upload_header()
        self.upload_grid()
        self.p(
            "الملفات الثلاثة الأولى إلزامية. الملفات السبعة الأخرى اختيارية: كل ملف إضافي يحسّن الدقة، لكنه لا يمنع توليد الطلبية.",
            size=8.2,
            color=MUTED,
        )
        self.callout(
            "بعد الرفع",
            "يتم التعرف على دور كل ملف من أعمدته، ثم تنظيف الأكواد ودمج البيانات. إذا رفعت ملفاً اختيارياً خاطئاً، يستطيع النظام تجاهله بدلاً من إفساد الدمج.",
            tone="good",
        )
        self.h2("ترتيب الرفع الموصى به", "RECOMMENDED UPLOAD ORDER")
        self.numbered(
            [
                "ابدأ بالماستر ثم النواقص ورصيد الفرع؛ هذه الملفات الثلاثة تكفي لتشغيل الطلبية.",
                "أضف رصيد المخزن والمبيعات الحديثة وتحت التوريد لتحسين دقة التغطية والطلب.",
                "أضف التحويلات ولوحة المبيعات والأصناف متعددة الكروت وPushing عند توفرها.",
            ]
        )
        self.h2("أخطاء شائعة عند الرفع", "COMMON UPLOAD MISTAKES")
        self.numbered(
            [
                "رفع ملف فرع آخر بالخطأ: النظام يقرأ الفرع من الملف، لكن رصيد الفرع الصحيح هو الأساس.",
                "استخدام ماستر قديم أو ناقص الأعمدة: هذا أخطر من عدم رفع ملف اختياري.",
                "رفع ملف اختياري بصيغة مختلفة دون التأكد من الأعمدة؛ النظام قد يتجاهله، لكن الأفضل التحقق أولاً.",
            ]
        )

        self.add_page()
        self.section_label = "دليل التشغيل: كل زر وكل مخرج"
        self.h2("لوحة الإعدادات: طريقة الحساب", "SETTINGS SIDEBAR")
        self.p(
            "الإعدادات لا تُغيّر الملفات؛ بل تُغيّر سياسة القرار. راجعها قبل كل تشغيل، ثم اضغط حفظ الإعدادات.",
            size=9.4,
        )
        self.button_card(
            "طريقة الحساب",
            "Order Method",
            "تحدد متى يتحول المخزون إلى طلبية. ROP لا يطلب إلا عند النزول تحت الحد، بينما Target Level يطلب للوصول إلى الهدف دائماً.",
            options=[
                ("ROP", "لا يطلب إلا إذا نزل المخزون الفعلي تحت ROP.", True),
                ("Target Level", "يطلب دائماً للوصول إلى الكمية المستهدفة.", False),
            ],
            accent=BLUE,
        )
        self.button_card(
            "أيام التغطية",
            "Coverage Days",
            "عدد الأيام التي نريد تغطيتها بعد وصول الطلبية. القيمة الافتراضية 21 يوماً، وتُستخدم داخل معادلة Target Level.",
            slider=21.0,
            accent=BLUE,
        )
        self.h2("مفاتيح إضافية", "ADDITIONAL SWITCHES")
        self.card_row(
            [
                (
                    "تجاهل الأصناف اللي ملهاش معدل بيع",
                    "Ignore items with no sales rate",
                    "عند التفعيل، تُستبعد الأصناف التي لا تملك معدل بيع موثوقاً من حساب الطلب العادي.",
                    "03",
                ),
                (
                    "تخصيص المخزون من المخزن",
                    "Deduct central warehouse stock",
                    "عند التفعيل، يُخصم المخزن المركزي من الطلب النهائي. عند الإيقاف، لا يُخصم.",
                    "04",
                ),
            ]
        )
        self.card_row(
            [
                (
                    "تفعيل البدائل",
                    "Enable substitutes",
                    "عند التفعيل، يُطلب العجز فقط إذا كان المخزن أقل من الطلب المحسوب. لا يُطلب الصنف الأساسي والبديل معاً.",
                    "05",
                ),
                (
                    "تقريب للعبوات الكاملة",
                    "Round to whole packs",
                    "عند التفعيل، تُقرّب الكمية النهائية إلى عبوات كاملة حسب إعداد الصنف.",
                    "06",
                ),
            ]
        )
        self.h2("الافتراضيات الحالية", "CURRENT DEFAULTS")
        self.stat_row(
            [
                ("1.65", "معامل Z", "مخزون أمان"),
                ("21", "أيام التغطية", "Target Level"),
                ("OFF", "التحويلات", "Net Transfers = 0"),
                ("OFF", "Overrides", "لا إجبار بدون مبيعات"),
            ],
            h=26.0,
        )

        self.add_page()
        self.section_label = "دليل التشغيل: كل زر وكل مخرج"
        self.h2("مفاتيح التشغيل والقرار", "TOGGLES & OVERRIDES")
        self.p(
            "كل Toggle معزول عن الآخر. عند إيقافه لا يؤثر على الحساب، وعند تفعيله يظهر أثره بوضوح في سبب الطلب والمعاينة.",
            size=9.4,
        )
        self.button_card(
            "تضمين التحويلات (Include Transfers)",
            "Include Transfers",
            "مفتاح تشغيل/إيقاف. عند التفعيل: Net Transfers = Transfers IN - Transfers OUT، ويُضاف الصافي إلى Effective Stock. عند الإيقاف: Net Transfers = 0.",
            on=False,
            toggle_label="OFF",
            accent=BLUE,
        )
        self.button_card(
            "Force Push للتجميل",
            "Force Cosmetics",
            "مفتاح تشغيل/إيقاف. عند التفعيل، يتم توزيع التجميل حتى لو لم تكن له مبيعات. عند الإيقاف، لا يتم إجبار أي صنف تجميل بدون معدل بيع.",
            on=False,
            toggle_label="OFF",
            accent=BLUE,
        )
        self.button_card(
            "Pushing List Override",
            "Pushing List",
            "مفتاح تشغيل/إيقاف. عند التفعيل، يتم إجبار طلب الأصناف الموجودة في قائمة Pushing. عند الإيقاف، تبقى القائمة مرجعاً فقط ولا تفرض طلباً.",
            on=False,
            toggle_label="OFF",
            accent=BLUE,
        )

        self.h2("الزر النهائي: توليد الطلبية", "GENERATE ORDER")
        self.p(
            "بعد رفع الملفات ومراجعة الإعدادات، اضغط الزر الأزرق. تبدأ الرحلة الآلية، ولا تحتاج إلى أي معادلة يدوية بعدها.",
            size=9.6,
        )
        self.button_card(
            "توليد الطلبية",
            "Generate Order",
            "الزر النهائي الذي يقوم بكل الحسابات: دمج الملفات، حساب Daily Demand وROP وTarget، تطبيق القواعد، ثم توليد ملف Excel جاهز للمراجعة والتنزيل.",
            cta="توليد الطلبية",
            accent=BLUE,
        )
        self.numbered(
            [
                "قراءة الملفات والتعرّف على دور كل ملف من الأعمدة.",
                "تنظيف الأكواد ودمج البيانات في إطار واحد.",
                "حساب الطلب لكل صنف وفرع حسب طريقة الحساب المختارة.",
                "تطبيق التحويلات والرواكد والتجميل وPushing والبدائل حسب الإعدادات.",
                "خصم المخزن، ثم فحص Fail-Fast، ثم تجهيز المعاينة والتصدير.",
            ]
        )

        self.add_page()
        self.section_label = "دليل التشغيل: كل زر وكل مخرج"
        self.h2("المخرجات: الأعمدة الـ 20", "THE 20-COLUMN CONTRACT")
        self.p(
            "ملف Excel النهائي يحمل 20 عموداً. أعمدة المبيعات ديناميكية: تتغير أسماؤها حسب تاريخ الطلب، لكن عددها يبقى أربعة.",
            size=8.9,
        )
        output_rows = [
            ["1", "التصنيف", "فئة الصنف أو عائلته."],
            ["2", "الكود", "كود الصنف الموحد بعد التنظيف."],
            ["3", "الاسم", "اسم الصنف كما يظهر في الماستر."],
            ["4", "المطلوب", "الكمية النهائية بعد خصم المخزن والبدائل."],
            ["5", "السعر", "سعر الوحدة."],
            ["6", "القيمة المالية للطلب", "المطلوب × السعر."],
            ["7", "الموجود في الفرع", "رصيد الفرع الفعلي."],
            ["8", "الموجود في المخزن", "رصيد المخزن المركزي المتاح."],
            ["9", "التحويلات", "صافي التحويلات عند تفعيل الخيار."],
            ["10", "مبيعات الشهر 1", "ديناميكي حسب تاريخ الطلب."],
            ["11", "مبيعات الشهر 2", "ديناميكي حسب تاريخ الطلب."],
            ["12", "مبيعات الشهر 3", "ديناميكي حسب تاريخ الطلب."],
            ["13", "مبيعات الشهر 4", "ديناميكي حسب تاريخ الطلب."],
            ["14", "المتوسط", "متوسط المبيعات الشهرية."],
            ["15", "ROP", "نقطة إعادة الطلب."],
            ["16", "Lead_Time", "زمن التوريد بالأيام."],
            ["17", "تاريخ الوصول المتوقع", "تاريخ وصول الطلبية."],
            ["18", "تغطية المخزون (أيام)", "كم يوماً يغطيها المخزون."],
            ["19", "سبب الطلب", "ROP / Target / Pushing / تجميل / بديل / راكد."],
            ["20", "ملاحظات", "ملاحظات التشغيل والاستبعاد."],
        ]
        self.table(
            ["#", "العمود", "ماذا يعني؟"],
            output_rows,
            [9.0, 48.0, 119.0],
            font_size=7.4,
            leading=3.9,
            min_row_height=6.3,
            padding=1.2,
        )
        self.callout(
            "ملاحظة على الأعمدة الديناميكية",
            "أعمدة المبيعات الأربعة تحمل أسماء الأشهر الفعلية حسب تاريخ الطلب، وليس أسماء ثابتة. عدد الأعمدة يبقى 20، لكن العناوين تتغير مع الدورة.",
            tone="blue",
        )
        self.h2("لماذا 20 عموداً؟", "WHY 20 COLUMNS")
        self.card_row(
            [
                (
                    "قيمة مالية واضحة",
                    "Financial value",
                    "المطلوب × السعر يعطي الإدارة تكلفة الطلبية قبل الاعتماد، لا مجرد كمية.",
                    "01",
                ),
                (
                    "تاريخ وصول وتغطية",
                    "Arrival & coverage",
                    "تاريخ الوصول المتوقع وتغطية المخزون يجعلان التخطيط الزمني جزءاً من القرار.",
                    "02",
                ),
            ]
        )
        self.add_page()
        self.section_label = "دليل التشغيل: كل زر وكل مخرج"
        self.h2("نظام الألوان في المعاينة وExcel", "COLOUR SYSTEM")
        self.p(
            "الألوان ليست زينة؛ بل طبقة تواصل سريعة. كل لون يخبر المراجع من أين جاءت الكمية أو لماذا ظهر السطر.",
            size=9.4,
        )
        self.color_legend()
        self.callout(
            "قاعدة الاستخدام",
            "وردي = تحميل من المخزن، أزرق = Pushing، أصفر = تحويلات، رمادي = تعدد الكروت. اللون لا يغيّر الرقم؛ لكنه يشرح مصدره.",
            tone="blue",
        )

        self.h2("قبل التنزيل: قائمة مراجعة سريعة", "PRE-EXPORT CHECKLIST")
        checklist = [
            "الفرع والتاريخ صحيحان، والملفات الثلاثة الإلزامية مرفوعة.",
            "طريقة الحساب وأيام التغطية مطابقتان لسياسة التشغيل.",
            "حالة Toggles واضحة: التحويلات، التجميل، Pushing، والبدائل.",
            "لا توجد ملاحظات Fail-Fast غير مفسرة.",
            "المعاينة تعرض الألوان والأسباب المتوقعة، والقيمة المالية منطقية.",
        ]
        self.numbered(checklist)
        self.callout(
            "التنزيل الآمن",
            "نزّل الملف باسم يحتوي الفرع والتاريخ، واحفظه في مجلد الأوتو أوردر الرسمي. لا تعدّل الأرقام يدوياً بعد التصدير؛ أي تعديل يجب أن يعود إلى الإعدادات أو الملفات المصدر.",
            tone="amber",
        )
        self.h2("بعد التنزيل", "AFTER EXPORT")
        self.numbered(
            [
                "راجع المعاينة وملف Excel، وتأكد من الألوان وسبب الطلب لكل سطر.",
                "اعتمد الطلبية حسب صلاحية الفرع، واحفظ نسخة في المجلد الرسمي.",
                "إذا احتجت تعديلاً، عدّل الإعدادات أو الملف المصدر ثم أعد التوليد؛ لا تعدّل الأرقام يدوياً.",
            ]
        )

    def section_five(self) -> None:
        self.section_cover(
            "05",
            "VALUE PROPOSITION  ·  THE BUSINESS CASE",
            "القيمة المضافة للشركة",
            "التحول من التقدير إلى العلم لا يوفّر وقتاً فقط؛ بل يحمي رأس المال، يقلل المخزون الميت، ويعطي الإدارة رؤية مالية فورية.",
            accent=GOOD,
        )

        self.h2("أربع قيم مباشرة", "FOUR BUSINESS OUTCOMES")
        self.card_row(
            [
                (
                    "من «التقدير» إلى «العلم»",
                    "From judgment to science",
                    "ROP وSafety Stock وTarget Level تحمي الشركة من الإغراق أو النقص، وتجعل القرار قابلاً للتكرار.",
                    "01",
                ),
                (
                    "الشفافية المالية",
                    "Financial transparency",
                    "عمود القيمة المالية للطلب يعطي الإدارة رؤية فورية لتكلفة الطلبية قبل اعتمادها.",
                    "02",
                ),
            ],
            accent=GOOD,
        )
        self.card_row(
            [
                (
                    "منع الهدر",
                    "Prevent dead stock",
                    "استبعاد الرواكد آلياً وتوثيق «راكد - لا يحتاج طلب» يحافظ على رأس المال ويقلل المخزون الميت.",
                    "03",
                ),
                (
                    "توفير الوقت",
                    "Time saved",
                    "تقليص وقت الأوتو أوردر من ساعات إلى ثوانٍ، مما يتيح للفريق التركيز على مهام استراتيجية.",
                    "04",
                ),
            ],
            accent=GOOD,
        )

        self.h2("الأثر على مؤشرات التشغيل", "OPERATING IMPACT")
        self.stat_row(
            [
                ("10", "ملفاً", "مصدر واحد موحد"),
                ("1", "سياسة", "لكل فرع ودورة"),
                ("20", "عموداً", "رؤية كاملة"),
                ("0", "VLOOKUP", "لا دمج يدوي"),
            ],
            h=27.0,
        )

        self.h2("خطة انتقال مقترحة", "SUGGESTED ROLLOUT")
        phases = [
            ("01", "تشغيل ظل", "أسبوع واحد", "شغّل V2 بالتوازي مع الطريقة الحالية، وقارن النتائج دون اعتمادها بعد."),
            ("02", "اعتماد", "أسبوعان", "اعتمد المخرج الرسمي، وثبّت الإعدادات، ودرّب الفريق على قائمة المراجعة."),
            ("03", "توسع", "الشهر التالي", "طبّق على بقية الفروع، وراجع مؤشرات الوقت والمخزون الميت شهرياً."),
        ]
        gap = 4.0
        w = (CW - gap * 2) / 3
        h = 36.0
        self.ensure_space(h + 4)
        y = self.get_y()
        for index, (num, title, when, body) in enumerate(phases):
            x = PAGE_W - M - w - index * (w + gap)
            self.phase_card(x, y, w, h, num, title, body)
            self.set_font(self.body, "B", 6.4)
            self.set_text_color(*BLUE)
            self.set_xy(x + 4, y + h - 7.0)
            self.cell(w - 8, 3.2, when, align="R")
        self.set_y(y + h + 4.0)

        self.callout(
            "الخلاصة النهائية",
            "Auto Order V2 ليس مجرد أداة أسرع؛ إنه طبقة حوكمة تشغيلية: بيانات نظيفة، معادلة واحدة، استثناءات موثقة، ومخرج مالي قابل للمراجعة.",
            tone="good",
        )

        self.p(
            "التوصية: البدء بتشغيل ظل على فرع واحد، ثم اعتماد النتائج بعد مقارنة أسبوعين. النجاح لا يُقاس بعدد الملفات المرفوعة، بل بجودة القرار الذي يخرج منها.",
            size=9.4,
            bold=False,
        )

        self.h2("مؤشرات نجاح بعد 30 يوماً", "SUCCESS METRICS")
        self.stat_row(
            [
                ("أقل", "وقت الأوتو أوردر", "من ساعات إلى دقائق"),
                ("أقل", "المخزون الميت", "استبعاد الرواكد آلياً"),
                ("أعلى", "دقة الطلب", "معادلة موحدة لكل فرع"),
                ("100%", "أثر التدقيق", "سبب موثق لكل سطر"),
            ],
            h=27.0,
        )

        self.h2("ما نحتاجه من الإدارة", "MANAGEMENT DECISIONS")
        self.numbered(
            [
                "اعتماد سياسة الحساب: ROP أو Target Level، وقيمة Z، وأيام التغطية الرسمية.",
                "تحديد فرع تجريبي لمدة أسبوعين، ومقارنة نتائجه بالطريقة اليدوية الحالية.",
                "مراجعة شهرية لمؤشرات الوقت والمخزون الميت ودقة الطلب، مع توثيق أي استثناء.",
            ]
        )
        self.callout(
            "القرار المطلوب",
            "الموافقة على تشغيل ظل لمدة أسبوعين، ثم اعتماد V2 كمسار رسمي إذا تحققت مؤشرات الدقة والوقت. البدء بفرع واحد يقلل المخاطرة ويصنع قصة نجاح قابلة للتوسع.",
            tone="good",
        )

        self.h2("مسرد سريع للمصطلحات", "GLOSSARY")
        self.table(
            ["المصطلح", "المعنى"],
            [
                ["ROP", "نقطة إعادة الطلب: الحد الذي لا يُطلب الصنف تحته."],
                ["Safety Stock", "مخزون الأمان الذي يحمي من تقلب الطلب أثناء التوريد."],
                ["Lead Time", "زمن التوريد بالأيام من الطلب حتى الوصول."],
                ["Effective Stock", "المخزون الفعلي بعد إضافة المعلّق وصافي التحويلات."],
                ["Target Level", "الكمية المستهدفة بعد التوريد وأيام التغطية."],
                ["Coverage Days", "عدد الأيام التي نريد تغطيتها بعد وصول الطلبية."],
            ],
            [42.0, 134.0],
            font_size=7.8,
            leading=4.0,
            min_row_height=7.2,
            padding=1.4,
        )

    def english_snapshot(self) -> None:
        self.section_label = "ENGLISH SNAPSHOT"
        self.add_page()
        self._ltr_text()
        self.set_font(self.body, "B", 7.0)
        self.set_text_color(*BLUE)
        self.set_xy(M, 27)
        self.cell(0, 4, "APPENDIX  ·  ONE-PAGE EXECUTIVE SNAPSHOT", align="L")

        self.set_font(self.body, "B", 21.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, 36)
        self.multi_cell(
            CW,
            9.5,
            "Auto Order V2: from manual estimation to an auditable order",
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_font(self.body, "", 9.6)
        self.set_text_color(*TEXT)
        self.set_xy(M, self.get_y() + 3)
        self.multi_cell(
            CW,
            5.2,
            "The current process asks the team to extract ten reports, merge them with VLOOKUP/SUMIFS, "
            "and then rely on personal judgement for demand, substitutes, cosmetics and stagnant items. "
            "V2 replaces that chain with one repeatable pipeline and a transparent twenty-one-column output.",
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.ln(5)

        self.set_font(self.body, "B", 11.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, self.get_y())
        self.cell(CW, 6, "What changes", align="L")
        self.ln(7)
        self.bullets(
            [
                "Ten PharmaFly files are uploaded in one place; the system detects each role from its columns, not its file name.",
                "Codes are cleaned and merged automatically, removing VLOOKUP, SUMIFS and the recurring '.0' code conflicts.",
                "Demand is calculated as Average / 30, then ROP, Safety Stock and Target Level are applied consistently.",
                "Transfers, warehouse deduction, cosmetics, pushing and substitutes are explicit toggles with a documented effect.",
                "The export carries 21 columns, including financial value, expected arrival, stock coverage and order reason.",
            ],
            size=9.4,
            rtl=False,
        )

        self.set_font(self.body, "B", 11.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, self.get_y())
        self.cell(CW, 6, "Manual vs. V2", align="L")
        self.ln(7)
        self.table(
            ["Dimension", "Current manual process", "Auto Order V2"],
            [
                ["Data collection", "Ten separate reports", "One smart upload area"],
                ["Merging", "VLOOKUP / SUMIFS / code conflicts", "Automated Pandas merge and cleaning"],
                ["Demand", "Personal estimate", "Average / 30, documented"],
                ["Math", "Unclear or inconsistent", "ROP, Target Level and Safety Stock"],
                ["Transfers", "Added to sales, distorting demand", "Isolated behind a toggle"],
                ["Stagnant items", "Remain in the sheet", "Filtered and documented"],
                ["Output", "16 columns", "21 columns with financial value"],
                ["Speed", "Hours or days", "Seconds"],
            ],
            [35.0, 65.0, 76.0],
            font_size=7.7,
            leading=4.0,
            rtl=False,
            min_row_height=7.2,
            padding=1.4,
        )

        self.callout(
            "Bottom line",
            "V2 is not only faster. It turns replenishment into a governed operating policy: clean data, one formula, documented exceptions, and a financially readable output.",
            tone="good",
            rtl=False,
        )

        self.set_font(self.body, "B", 11.0)
        self.set_text_color(*NAVY)
        self.set_xy(M, self.get_y())
        self.cell(CW, 6, "What management gets", align="L")
        self.ln(7)
        self.bullets(
            [
                "A repeatable policy that any branch can run without rebuilding the same ten reports.",
                "A financially readable order: quantity, unit price, order value, arrival date and stock coverage.",
                "A documented decision trail: every forced or excluded item has a visible reason.",
            ],
            size=9.0,
            rtl=False,
        )

        self.set_font(self.body, "", 7.2)
        self.set_text_color(*MUTED)
        self.set_xy(M, self.get_y() + 1)
        self.cell(
            CW,
            4,
            "Prepared for management review  ·  3 November 2026  ·  Auto Order V2.0",
            align="L",
        )


def main() -> None:
    pdf = ReportPDF()
    pdf.build()
    pdf.output(str(OUTPUT))
    print(f"Generated: {OUTPUT}")
    print(f"Pages: {pdf.page_no()}")
    print(f"Size: {OUTPUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
