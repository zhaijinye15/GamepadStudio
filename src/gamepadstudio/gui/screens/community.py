"""社区页：注册 / 登录 / 看帖 / 发帖 / 点赞 / 个性化.

UID 徽标代表身份（black=认证，gold=靓号）；称号 / 配色 / 签名由用户自己改：
称号跟在徽标后面，配色决定头像圆牌和称号的颜色，签名放在顶部卡片里。
"""
from __future__ import annotations

import pygame

from .. import theme

BADGE_TEXT = {"black": "认证", "gold": "靓号", "normal": ""}
GOLD = (212, 168, 74)
GOLD_DARK = (166, 128, 46)
INK = (24, 26, 30)

# 与服务端 PALETTE 一一对应（顺序一致，改一边必须同步另一边）
ACCENTS = (
    "",         # 默认灰
    "#D4A84A",  # 金
    "#4A9EE0",  # 蓝
    "#43C08A",  # 绿
    "#E0685E",  # 红
    "#A66BD4",  # 紫
    "#E08CB4",  # 粉
    "#E0A33C",  # 橙
    "#5FB7C7",  # 青
)


def _rgb(hex_color: str, fallback):
    """#RRGGBB → (r,g,b)；解析不了就用 fallback."""
    try:
        text = str(hex_color or "").strip().lstrip("#")
        if len(text) == 6:
            return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        pass
    return fallback


def _lum(color) -> float:
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


def person_color(data) -> tuple:
    """这个人的主题色：没设过就用灰色."""
    return _rgb(str(data.get("color", "") or ""), theme.TEXT_DIM)


def draw_badge(surface, font, badge: str, pos, text: str = "") -> pygame.Rect:
    """身份徽标：认证＝金底深字（深色界面上最显眼），靓号＝金边金字，普通＝不画."""
    badge = str(badge or "normal")
    if badge not in ("black", "gold"):
        return pygame.Rect(pos[0], pos[1], 0, 0)
    label = text or BADGE_TEXT.get(badge, "")
    if not label:
        return pygame.Rect(pos[0], pos[1], 0, 0)
    size = font.size(label)
    rect = pygame.Rect(pos[0], pos[1], size[0] + 16, 19)
    if badge == "black":
        theme.rounded_rect(surface, rect, GOLD, radius=9)
        theme.draw_text(surface, font, label, rect.center, INK, align="center")
    else:
        theme.rounded_rect(surface, rect, theme.PANEL, radius=9, border=GOLD_DARK)
        theme.draw_text(surface, font, label, rect.center, GOLD, align="center")
    return rect


def draw_avatar(surface, font, name: str, color, center, radius: int = 13) -> None:
    """昵称首字的彩色圆牌，配色不同一眼能认出来."""
    fill = color if color else theme.PANEL_ALT
    pygame.draw.circle(surface, fill, center, radius)
    pygame.draw.circle(surface, theme.lerp_color(fill, (255, 255, 255), 0.25), center, radius, 1)
    char = (str(name or "?").strip()[:1] or "?").upper()
    theme.draw_text(surface, font, char, center, INK if _lum(fill) > 140 else theme.TEXT, align="center")


class CommunityScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.username = ""
        self.password = ""
        self.base = ""
        self.title = ""
        self.content = ""
        self.error = ""
        self.hint = ""
        self.posts = []
        self.loaded = False
        self.busy = ""
        # 个性化编辑区
        self.p_title = ""
        self.p_bio = ""
        self.p_color = ""
        self._profile_uid = 0

    def handle_event(self, event) -> None:
        """键盘输入由 UI 层统一收口，这里不额外处理（与其它页面保持一致）."""
        return

    # ------------------------------------------------------------------ 绘制
    def draw(self, ui, rect: pygame.Rect) -> None:
        client = self.app.community
        if not self.base:
            self.base = client.base
        if client.logged_in:
            self._draw_logged_in(ui, rect, client)
        else:
            self._draw_login(ui, rect, client)

    def _sync_profile(self, client) -> None:
        """换账号时把个性化编辑区拉回服务端值，避免显示上一个号的内容."""
        if self._profile_uid != client.uid:
            self._profile_uid = client.uid
            self.p_title = client.title
            self.p_bio = client.bio
            self.p_color = client.color

    # ---------------------------------------------------------------- 登录前
    def _draw_login(self, ui, rect, client) -> None:
        surface = ui.surface
        card_h = min(300, max(240, rect.height // 2 + 40))
        card = pygame.Rect(rect.x, rect.y, rect.width, card_h)
        inner = ui.card(card, "社区", "注册一个账号，UID 就是你在社区里的编号；靓号自动标金")

        width = min(360, inner.width - 12)
        x = inner.x
        y = inner.y + 4
        self.base = ui.text_input("comm_base", pygame.Rect(x, y, width, 30),
                                  self.base, "服务器地址", max_len=64)
        y += 40
        self.username = ui.text_input("comm_user", pygame.Rect(x, y, width, 30),
                                      self.username, "用户名（2–20 字符）", max_len=20)
        y += 40
        self.password = ui.text_input("comm_pass", pygame.Rect(x, y, width, 30),
                                      self.password, "密码（至少 6 位）", max_len=32)
        y += 44

        busy = self.busy
        if ui.button("comm_login", pygame.Rect(x, y, 110, 32),
                     "登录中…" if busy == "login" else "登录",
                     kind="primary", enabled=not busy, font_size=13):
            self._submit(False)
        if ui.button("comm_reg", pygame.Rect(x + 120, y, 110, 32),
                     "注册中…" if busy == "reg" else "注册新账号",
                     kind="default", enabled=not busy, font_size=13):
            self._submit(True)
        if ui.button("comm_apply", pygame.Rect(x + 240, y, 92, 32),
                     "用此地址", kind="ghost", enabled=not busy, font_size=12):
            client.base = self.base.strip() or client.base
            client._save()
            self.hint = f"服务器已切到 {client.base}"

        y += 40
        if self.error:
            theme.draw_text(surface, ui.fonts.get(12), self.error, (x, y), (232, 110, 110))
        elif self.hint:
            theme.draw_text(surface, ui.fonts.get(12), self.hint, (x, y), theme.TEXT_MUTED)
        else:
            theme.draw_text(surface, ui.fonts.get(12),
                            "没有账号就先点「注册新账号」，用户名不能重名（密码框是明文显示）",
                            (x, y), theme.TEXT_MUTED)

    # ---------------------------------------------------------------- 登录后
    def _draw_logged_in(self, ui, rect, client) -> None:
        surface = ui.surface
        self._sync_profile(client)
        head = pygame.Rect(rect.x, rect.y, rect.width, min(272, max(248, rect.height - 180)))
        inner = ui.card(head, "社区", "徽标＝身份；称号、配色、签名都能自己改，发帖后所有人可见")
        small = ui.fonts.get(11)
        name_font = ui.fonts.get(15, bold=True)
        tint = person_color(client.user)

        # 第一行：头像 + 昵称 + 身份徽标 + 称号 + UID
        y0 = inner.y + 2
        draw_avatar(surface, name_font, client.user.get("username", ""), tint, (inner.x + 13, y0 + 11), 13)
        name_x = inner.x + 32
        username = str(client.user.get("username", ""))
        theme.draw_text(surface, name_font, username, (name_x, y0), theme.TEXT)
        x = name_x + name_font.size(username)[0] + 8
        badge_rect = draw_badge(surface, small, client.badge, (x, y0 + 5))
        if badge_rect.width:
            x = badge_rect.right + 8
        if client.title:
            title_font = ui.fonts.get(12, bold=True)
            theme.draw_text(surface, title_font, client.title, (x, y0 + 4), tint)
            x += title_font.size(client.title)[0] + 8
        label = f"UID {client.uid}"
        if badge_rect.width or client.title:
            label = f"· {label}"
        theme.draw_text(surface, small, label, (x, y0 + 5), theme.TEXT_MUTED)

        if ui.button("comm_out", pygame.Rect(inner.right - 84, inner.y, 84, 26), "退出登录",
                     kind="ghost", font_size=12):
            client.logout()
            self.posts = []
            self.loaded = False
            self._profile_uid = 0
            self.hint = "已退出登录"
        if ui.button("comm_reload", pygame.Rect(inner.right - 176, inner.y, 84, 26),
                     "刷新中…" if self.busy == "refresh" else "刷新帖子",
                     kind="default", enabled=not self.busy, font_size=12):
            self.app.community_refresh()

        # 第二行：称号 + 配色色板 + 保存
        y = inner.y + 32
        self.p_title = ui.text_input("comm_p_title", pygame.Rect(inner.x, y, 150, 28),
                                     self.p_title, "称号（最多 8 字）", max_len=8)
        swatch_x = inner.x + 166
        swatch_y = y + 14
        for index, accent in enumerate(ACCENTS):
            box = pygame.Rect(swatch_x + index * 26 - 9, swatch_y - 9, 18, 18)
            if ui.hit_test(f"comm_color_{index}", box):
                self.p_color = accent
            chosen = (self.p_color or "") == accent
            fill = _rgb(accent, theme.PANEL_ALT) if accent else theme.PANEL_ALT
            pygame.draw.circle(surface, fill, box.center, 9)
            pygame.draw.circle(surface, theme.ACCENT if chosen else theme.BORDER_SOFT,
                               box.center, 9, 2 if chosen else 1)
        if ui.button("comm_save_profile", pygame.Rect(inner.right - 96, y, 92, 28),
                     "保存中…" if self.busy == "profile" else "保存",
                     kind="default", enabled=not self.busy, font_size=12):
            self.app.community_save_profile(self.p_title, self.p_bio, self.p_color)

        # 第三行：签名
        y += 34
        self.p_bio = ui.text_input("comm_p_bio", pygame.Rect(inner.x, y, inner.width, 28),
                                   self.p_bio, "签名（最多 40 字，给自己一句话）", max_len=40)

        # 第四行：发帖标题 + 发布
        y += 34
        title_w = inner.width - 112
        self.title = ui.text_input("comm_title", pygame.Rect(inner.x, y, title_w, 28),
                                   self.title, "帖子标题", max_len=40)
        if ui.button("comm_post", pygame.Rect(inner.x + title_w + 16, y, 96, 28),
                     "发布中…" if self.busy == "post" else "发布",
                     kind="primary", enabled=not self.busy, font_size=12):
            self.app.community_post(self.title, self.content)
        y += 34
        self.content = ui.text_input("comm_content", pygame.Rect(inner.x, y, inner.width, 28),
                                     self.content, "说点什么…（正文）", max_len=120)
        y += 32
        if self.error:
            theme.draw_text(surface, small, self.error, (inner.x, y), (232, 110, 110))
        elif self.hint:
            theme.draw_text(surface, small, self.hint, (inner.x, y), theme.TEXT_MUTED)
        else:
            theme.draw_text(surface, small, "金底「认证」＝管理员，金边「靓号」＝好编号；头像和称号跟着你选的配色走",
                            (inner.x, y), theme.TEXT_MUTED)

        # 列表
        body = pygame.Rect(rect.x, head.bottom + 12, rect.width,
                           max(120, rect.bottom - head.bottom - 12))
        inner2 = ui.card(body, "最新帖子", "按时间倒序；点「赞」给自己喜欢的帖子 +1")
        viewport = pygame.Rect(inner2.x, inner2.y + 4, inner2.width, max(80, inner2.height - 12))
        if not self.loaded and not self.busy:
            self.app.community_refresh()
        if not self.posts:
            hint = "正在加载…" if self.busy else "还没有帖子，发第一条吧"
            theme.draw_text(surface, ui.fonts.get(13), hint, viewport.center, theme.TEXT_MUTED, align="center")
            return

        row_h = 62
        offset = ui.scroll("comm_list", viewport, len(self.posts) * row_h, row_h)
        surface.set_clip(viewport)
        for index, post in enumerate(self.posts):
            y = viewport.y + index * row_h - offset
            if y > viewport.bottom or y + row_h < viewport.y:
                continue
            row = pygame.Rect(viewport.x, y, viewport.width, row_h - 8)
            if row.collidepoint(ui.mouse):
                theme.rounded_rect(surface, row, (22, 27, 35), radius=9)
            author = post.get("author") or {}
            tint_row = person_color(author)
            bar = GOLD if str(author.get("badge", "")) in ("gold", "black") else theme.BORDER_SOFT
            pygame.draw.rect(surface, bar,
                             pygame.Rect(row.x + 2, row.y + 12, 3, row.height - 24), border_radius=2)

            draw_avatar(surface, ui.fonts.get(11, bold=True), str(author.get("username", "?")),
                        tint_row, (row.x + 20, row.y + 18), 10)
            title_font = ui.fonts.get(14, bold=True)
            theme.draw_text(surface, title_font,
                            theme.ellipsize(title_font, str(post.get("title", "")), row.width - 300),
                            (row.x + 36, row.y + 6), theme.TEXT)

            meta_font = ui.fonts.get(11)
            author_name = str(author.get("username", "?"))
            x = row.x + 36
            theme.draw_text(surface, meta_font, author_name, (x, row.y + 28),
                            theme.lerp_color(tint_row, theme.TEXT, 0.25))
            x += meta_font.size(author_name)[0] + 8
            badge_rect = draw_badge(surface, ui.fonts.get(10), str(author.get("badge", "normal")),
                                    (x, row.y + 28))
            if badge_rect.width:
                x = badge_rect.right + 8
            title_text = str(author.get("title", "") or "")
            if title_text:
                author_font = ui.fonts.get(11, bold=True)
                theme.draw_text(surface, author_font, title_text, (x, row.y + 28), tint_row)
                x += author_font.size(title_text)[0] + 8
            tail = f"UID {author.get('uid', '?')} · 赞 {post.get('likes', 0)} · 评论 {post.get('comments', 0)}"
            if x > row.x + 36 + meta_font.size(author_name)[0] + 8:
                tail = f"· {tail}"
            theme.draw_text(surface, meta_font,
                            theme.ellipsize(meta_font, tail, max(60, row.right - x - 96)),
                            (x, row.y + 28), theme.TEXT_MUTED)

            if ui.button(f"comm_like_{post.get('id')}", pygame.Rect(row.right - 84, row.y + 10, 70, 26),
                         "赞", kind="default", font_size=12, enabled=not self.busy):
                self.app.community_like(int(post.get("id", 0)))
        surface.set_clip(None)

    # ------------------------------------------------------------------ 动作
    def _submit(self, register: bool) -> None:
        client = self.app.community
        if self.base.strip():
            client.base = self.base.strip()
        self.error = ""
        self.hint = ""
        username, password = self.username.strip(), self.password
        if not username or not password:
            self.error = "用户名和密码都要填"
            return
        if len(password) < 6:
            self.error = "密码至少 6 位"
            return
        self.app.community_auth(username, password, register)
