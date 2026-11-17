"""社区页：注册 / 登录 / 看帖 / 发帖 / 点赞.

密码走后端 PBKDF2 存储，这里只保存 token；UID 按后端规则着色：
black（管理员认定）· gold（靓号）· normal（普通）
"""
from __future__ import annotations

import pygame

from .. import theme

BADGE_TEXT = {"black": "认证", "gold": "靓号", "normal": ""}
BADGE_COLOR = {
    "black": (18, 18, 20),
    "gold": (212, 168, 74),
    "normal": theme.TEXT_MUTED,
}
BADGE_BORDER = {
    "black": (212, 168, 74),
    "gold": (166, 128, 46),
    "normal": theme.BORDER_SOFT,
}


def draw_badge(surface, font, badge: str, pos, text: str = "") -> pygame.Rect:
    """画一个 UID 徽标：普通为灰描边，金色为金边，黑色为深底金边."""
    label = text or BADGE_TEXT.get(badge, "")
    if not label:
        return pygame.Rect(pos[0], pos[1], 0, 0)
    size = font.size(label)
    rect = pygame.Rect(pos[0], pos[1], size[0] + 14, 20)
    color = (240, 240, 240) if badge == "black" else (24, 26, 30)
    theme.rounded_rect(surface, rect, BADGE_COLOR.get(badge, theme.TEXT_MUTED), radius=10,
                       border=BADGE_BORDER.get(badge, theme.BORDER_SOFT))
    theme.draw_text(surface, font, label, rect.center, color, align="center")
    return rect


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
        head = pygame.Rect(rect.x, rect.y, rect.width, 172)
        inner = ui.card(head, "社区", "发帖、看帖、点赞；UID 前的徽标代表身份")
        small = ui.fonts.get(11)
        name_font = ui.fonts.get(15, bold=True)
        theme.draw_text(surface, name_font, client.user.get("username", ""), (inner.x, inner.y + 2), theme.TEXT)
        name_w = name_font.size(client.user.get("username", ""))[0]
        badge_rect = draw_badge(surface, small, client.badge, (inner.x + name_w + 10, inner.y + 4))
        uid_x = badge_rect.right + 8 if badge_rect.width else inner.x + name_w + 10
        theme.draw_text(surface, small, f"UID {client.uid}", (uid_x, inner.y + 5), theme.TEXT_MUTED)

        if ui.button("comm_out", pygame.Rect(inner.right - 84, inner.y, 84, 26), "退出登录",
                     kind="ghost", font_size=12):
            client.logout()
            self.posts = []
            self.loaded = False
            self.hint = "已退出登录"
        if ui.button("comm_reload", pygame.Rect(inner.right - 176, inner.y, 84, 26),
                     "刷新中…" if self.busy == "refresh" else "刷新帖子",
                     kind="default", enabled=not self.busy, font_size=12):
            self.app.community_refresh()

        # 发帖区：标题一行 + 正文一行，避免和下面的列表卡片打架
        y = inner.y + 30
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
            theme.draw_text(surface, small, "发帖后所有人可见；UID 徽标金色=靓号，黑色=认证",
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
            badge = str(author.get("badge", "normal"))
            bar = {"gold": (212, 168, 74), "black": (232, 232, 238)}.get(badge, theme.BORDER_SOFT)
            pygame.draw.rect(surface, bar,
                             pygame.Rect(row.x + 2, row.y + 12, 3, row.height - 24), border_radius=2)
            title_font = ui.fonts.get(14, bold=True)
            theme.draw_text(surface, title_font, theme.ellipsize(title_font, str(post.get("title", "")), row.width - 280),
                            (row.x + 14, row.y + 8), theme.TEXT)
            meta = f"{author.get('username', '?')} · UID {author.get('uid', '?')} · 赞 {post.get('likes', 0)} · 评论 {post.get('comments', 0)}"
            theme.draw_text(surface, ui.fonts.get(11), theme.ellipsize(ui.fonts.get(11), meta, row.width - 280),
                            (row.x + 14, row.y + 30), theme.TEXT_MUTED)
            if badge in ("black", "gold"):
                draw_badge(surface, ui.fonts.get(10), badge, (row.right - 176, row.y + 8))
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
