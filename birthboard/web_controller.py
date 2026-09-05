from playwright.sync_api import sync_playwright
import ddddocr
import time
import re
from dataclasses import dataclass, field
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path
import sys
from typing import Any
from time import perf_counter
import logging

from birthboard.config import shihannet

logger = logging.getLogger(__name__)

def _step_result(ok, retryable=False, pending=None, result=None, error=None):
    return {
        "ok": ok,
        "retryable": retryable,
        "pending": pending or [],
        "result": result,
        "error": error,
    }

def _solve_captcha(page, ocr, max_retry=6):
    code = None
    retry = 0
    while retry < max_retry:
        try:
            captcha_img = page.locator("img#safecode")
            img_bytes = captcha_img.screenshot(timeout=3000)
            raw_code = ocr.classification(img_bytes)
            code = re.sub(r"\D", "", raw_code)
            print(f"识别原始: {raw_code} -> 纯数字: {code}")
            if len(code) == 4:
                return code
            print(f"验证码长度不对，刷新重试 {retry + 1}/{max_retry}")
        except Exception:
            print(f"验证码加载失败 {retry + 1}/{max_retry}")

        page.locator("img#safecode").click()
        page.wait_for_timeout(1000)
        retry += 1

    raise RuntimeError("验证码重试失败")


def _is_network_goto_error(error):
    message = str(error).lower()
    network_markers = [
        "net::err_connection_timed_out",
        "net::err_connection_refused",
        "net::err_connection_reset",
        "net::err_name_not_resolved",
        "page.goto",
    ]
    return any(marker in message for marker in network_markers)


def open_and_login(playwright, url, username, password, max_login_retry=5):
    """打开浏览器并登录，遇到异常自动重试。"""
    ocr = ddddocr.DdddOcr(show_ad=False)

    for attempt in range(1, max_login_retry + 1):
        browser = None
        try:
            print(f"\n===== 开始登录（第 {attempt}/{max_login_retry} 次）=====")
            browser = playwright.chromium.launch(
                headless=shihannet.headless,
                slow_mo=shihannet.slow_mo_ms,
            )
            page = browser.new_page()
            try:
                page.goto(url)
            except Exception as error:
                if _is_network_goto_error(error):
                    raise ConnectionError('投放屏站点暂时不可达') from error
                raise

            page.wait_for_timeout(1000)

            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)

            code = _solve_captcha(page, ocr)
            page.locator("input#randCode").fill(code)
            page.wait_for_timeout(500)
            page.get_by_role("button", name="登录").first.click()
            page.wait_for_timeout(2000)

            # 验证码错误弹窗：按文本检测，不再依赖动态 id。
            error_popup = page.locator("div.x-shadow").filter(
                has_text="验证码错误"
            ).first
            if error_popup.is_visible(timeout=1500):
                raise RuntimeError("验证码错误弹窗")

            print("登录成功")
            # 登录成功后点击左侧树节点的展开箭头（原 #ext-gen1105 为动态 id），
            # 改为定位左侧树中可见的展开图标。
            tree_elbow = page.locator(
                "span.x-tree-elbow-img"
            ).first
            try:
                tree_elbow.click(timeout=3000)
            except Exception:
                pass
            return browser, page
        except Exception as error:
            print(f"登录失败: {error}")
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if attempt < max_login_retry:
                retry_seconds = (
                    shihannet.network_retry_seconds
                    if isinstance(error, ConnectionError)
                    else 2
                )
                if retry_seconds > 0:
                    time.sleep(retry_seconds)

    raise RuntimeError("登录重试次数已耗尽")


def _open_media_management(page, name):
    """点击左侧树中的“多媒体素材管理”或“播出单管理”。

    这两个是“多媒体管理”父节点下的叶子节点，父节点折叠时它们不渲染。
    先查找目标文本，找不到时双击父节点“多媒体管理”展开后重试，
    最多尝试 5 次；仍失败则返回 False 并终止。
    """
    parent = page.locator("span.x-tree-node-text").filter(
        has_text=re.compile(r"^多媒体管理$")
    )

    for attempt in range(1, 6):
        menu = page.locator("span.x-tree-node-text").filter(
            has_text=re.compile(rf"^{re.escape(name)}$")
        )
        if menu.count() > 0:
            try:
                menu.first.click(timeout=2000)
                return True
            except Exception:
                # 单击失败，尝试双击目标节点。
                try:
                    menu.first.dblclick(timeout=2000)
                    return True
                except Exception as exc:
                    print(f"点击左侧菜单“{name}”失败: {exc}")

        # 未找到或点击失败：双击父节点“多媒体管理”展开，再重试。
        if parent.count() > 0:
            try:
                parent.first.dblclick(timeout=2000)
            except Exception as exc:
                print(f"展开父节点“多媒体管理”失败: {exc}")
        else:
            print("未找到父节点“多媒体管理”")
        page.wait_for_timeout(500)
        print(f"打开左侧菜单“{name}”第 {attempt}/5 次尝试")

    print(f"打开左侧菜单“{name}”失败，已终止")
    return False


def _frame_by_acl_id(page, acl_id):
    iframe = page.locator(f"iframe[id='{acl_id}-tab']").first
    if iframe.count() == 0:
        return None
    try:
        iframe.wait_for(state="visible", timeout=3000)
    except Exception:
        return None
    return iframe.content_frame


def _find_visible_frame(page, checker, timeout_ms=12000, interval_ms=250):
    """从当前页面可见 iframe 中查找满足条件的 frame。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if page.is_closed():
            break

        iframes = page.locator("iframe")
        count = iframes.count()
        for i in range(count):
            iframe = iframes.nth(i)
            try:
                if not iframe.is_visible(timeout=200):
                    continue
            except Exception:
                continue

            frame = iframe.content_frame
            if frame is None:
                continue

            try:
                if checker(frame):
                    return frame
            except Exception:
                continue

        page.wait_for_timeout(interval_ms)

    raise RuntimeError("未找到匹配的可见 iframe")


def _get_media_frame(page, timeout_ms=12000):
    fixed_frame = _frame_by_acl_id(page, "22")
    if fixed_frame is not None:
        return fixed_frame

    def _checker(frame):
        # 按标题“多媒体素材管理”判断素材管理 iframe。
        header = frame.locator("span.x-header-text").filter(
            has_text=re.compile(r"^多媒体素材管理$")
        )
        if header.count() > 0:
            return header.first.is_visible(timeout=250)
        # 兜底：按“上传”按钮判断。
        return frame.get_by_role("button", name="上传").first.is_visible(timeout=250)

    return _find_visible_frame(page, _checker, timeout_ms=timeout_ms)


def _get_playlist_frame(page, playlist_name=None, timeout_ms=12000):
    fixed_frame = _frame_by_acl_id(page, "42")
    if fixed_frame is not None:
        if not playlist_name:
            return fixed_frame
        try:
            if fixed_frame.get_by_text(playlist_name, exact=True).first.is_visible(timeout=1000):
                return fixed_frame
        except Exception:
            pass

    def _checker(frame):
        # 按标题“播出单管理”判断播出单管理 iframe。
        header = frame.locator("span.x-header-text").filter(
            has_text=re.compile(r"^播出单管理$")
        )
        if header.count() > 0:
            return header.first.is_visible(timeout=250)
        # 兜底：按“修改”按钮 + 播出单名判断。
        if not frame.get_by_role("button", name="修改").first.is_visible(timeout=250):
            return False
        if playlist_name:
            return frame.get_by_text(playlist_name, exact=True).first.is_visible(timeout=250)
        return True
    return _find_visible_frame(page, _checker, timeout_ms=timeout_ms)


def _get_picker_frame(play_frame, page, timeout_ms=12000, debug=False):
    """在播出单 frame 的子 iframe 中找到素材选择窗口。"""
    def _dbg(msg):
        if debug:
            print(f"[_get_picker_frame][debug] {msg}")

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if page.is_closed():
            break

        windows = play_frame.locator("div.x-window").filter(has_text=re.compile(r"添加元素"))
        win_count = windows.count()
        _dbg(f"添加元素窗口数量: {win_count}")
        for wi in range(win_count - 1, -1, -1):
            add_window = windows.nth(wi)
            try:
                if not add_window.is_visible(timeout=150):
                    continue
            except Exception:
                continue

            popup_iframes = add_window.locator("iframe")
            popup_count = popup_iframes.count()
            _dbg(f"可见窗口#{wi + 1} iframe数量: {popup_count}")
            for pi in range(popup_count - 1, -1, -1):
                popup_iframe = popup_iframes.nth(pi)
                try:
                    if not popup_iframe.is_visible(timeout=150):
                        continue
                except Exception:
                    continue

                child = popup_iframe.content_frame
                if child is None:
                    continue

                try:
                    if child.get_by_text("Birth", exact=True).first.is_visible(timeout=200):
                        _dbg(f"命中Birth文本iframe: window#{wi + 1}, iframe#{pi + 1}")
                        return child
                except Exception:
                    continue

        iframes = play_frame.locator("iframe")
        count = iframes.count()
        _dbg(f"play_frame下iframe总数: {count}")
        for i in range(count - 1, -1, -1):
            iframe = iframes.nth(i)
            try:
                if not iframe.is_visible(timeout=150):
                    continue
            except Exception:
                continue

            child = iframe.content_frame
            if child is None:
                continue

            try:
                if child.get_by_text("Birth", exact=True).first.is_visible(timeout=200):
                    _dbg(f"回退命中Birth iframe序号: {i + 1}")
                    return child
            except Exception:
                pass

            try:
                if child.get_by_role("button", name="添加").first.is_visible(timeout=200):
                    _dbg(f"回退命中添加按钮 iframe序号: {i + 1}")
                    return child
            except Exception:
                continue

        page.wait_for_timeout(250)

    raise RuntimeError("未找到素材选择窗口 iframe")


def _close_picker_window(play_frame, page):
    windows = play_frame.locator("div.x-window").filter(has_text=re.compile(r"添加元素"))
    win_count = windows.count()
    for wi in range(win_count - 1, -1, -1):
        add_window = windows.nth(wi)
        try:
            if not add_window.is_visible(timeout=150):
                continue
        except Exception:
            continue

        if _safe_click(add_window.locator(".x-tool-close").first, "添加元素窗口关闭.x-tool-close", page, timeout=2500):
            try:
                add_window.wait_for(state="hidden", timeout=1500)
            except Exception:
                pass
            return True

    return _safe_click(play_frame.locator(".x-tool-close").first, "窗口关闭.x-tool-close", page, timeout=2500)


def _click_optional_confirm(page, scope, max_clicks=2):
    for _ in range(max_clicks):
        clicked = False
        for current in (scope, page):
            btn = current.get_by_role("button", name="确定").first
            try:
                if btn.is_visible(timeout=700):
                    btn.click(timeout=1500)
                    page.wait_for_timeout(250)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            break


def _safe_click(locator, desc, page, timeout=4000):
    if page.is_closed():
        print(f"页面已关闭，跳过: {desc}")
        return False
    try:
        locator.click(timeout=timeout)
        return True
    except Exception as e:
        print(f"点击失败[{desc}]: {e}")
        return False


def _safe_click_force(locator, desc, page, timeout=3000):
    """强制点击（force=True），绕过元素可见性/稳定性与遮罩层遮挡检查。"""
    if page.is_closed():
        print(f"页面已关闭，跳过: {desc}")
        return False
    try:
        locator.click(timeout=timeout, force=True)
        return True
    except Exception as e:
        print(f"强制点击失败[{desc}]: {e}")
        return False


def _close_visible_popup(scope, page, timeout=3000):
    if page.is_closed():
        return False

    windows = scope.locator("div.x-window")
    window_count = windows.count()
    for i in range(window_count - 1, -1, -1):
        window = windows.nth(i)
        try:
            if not window.is_visible(timeout=200):
                continue
        except Exception:
            continue

        close_candidates = [
            (window.locator(".x-tool-close").first, "弹窗关闭按钮.x-tool-close"),
            (window.locator("[id$='-toolEl']").first, "弹窗关闭按钮[id$='-toolEl']"),
            (window.get_by_role("button", name=re.compile(r"^(关闭|取消|Close)$")).first, "弹窗关闭按钮(角色)"),
        ]
        for locator, desc in close_candidates:
            if _safe_click(locator, desc, page, timeout=timeout):
                try:
                    window.wait_for(state="hidden", timeout=1500)
                except Exception:
                    pass
                return True

    return False


def close_playlist(page):
    """关闭播出单编辑窗口并保存。"""
    play_frame = _get_playlist_frame(page)
    if play_frame is None:
        print("未定位到播出单区域frame")
        return _step_result(False, retryable=True, error="未定位到播出单区域frame")

    close_candidates = [
        # 优先用稳定的 class 定位关闭按钮，动态 id 兜底。
        (play_frame.locator(".x-tool-close").first, "播出单窗口关闭.x-tool-close"),
        (play_frame.locator("[id$='-toolEl']").first, "播出单窗口关闭[id$='-toolEl']"),
    ]
    closed = False
    for locator, desc in close_candidates:
        if _safe_click(locator, desc, page, timeout=2500):
            closed = True
            break

    if not closed:
        print("未找到播出单窗口关闭按钮")
        return _step_result(False, retryable=True, error="未找到播出单窗口关闭按钮")

    _safe_click(play_frame.get_by_role("button", name="保存").first, "播出单保存", page, timeout=3000)
    _click_optional_confirm(page, play_frame, max_clicks=2)
    return _step_result(True, result=True)


def _open_media_category(frame, category_name="Birth"):
    """在素材分类树中选中目录，优先使用稳定 recordid。"""
    stable_row = frame.locator("tr.x-grid-row").filter(
        has=frame.locator("span.x-tree-node-text", has_text=re.compile(rf"^{re.escape(category_name)}$"))
    ).first
    if stable_row.count() > 0:
        row_cell = stable_row.locator("td[role='gridcell']").first
        try:
            row_cell.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        try:
            row_cell.click(timeout=3000)
            return True
        except Exception:
            pass

        try:
            stable_row.click(timeout=2000, force=True)
            return True
        except Exception:
            pass

        node_text = stable_row.locator("span.x-tree-node-text").first
        node_text.click(timeout=2000, force=True)
        return True

    target = frame.get_by_text(category_name, exact=True).first
    try:
        target.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    try:
        target.click(timeout=3000)
        return True
    except Exception:
        target.click(timeout=2000, force=True)
        return True


def upload_material(page, image_path):
    print("开始上传素材...")
    """上传素材，image_path 为本地图片路径。"""
    if not _open_media_management(page, "多媒体素材管理"):
        return _step_result(False, retryable=True, error="未打开多媒体素材管理")
    media_frame = _get_media_frame(page)

    _open_media_category(media_frame, "Birth")
    # 上传按钮：按文本“上传”定位，不再依赖动态 id。
    _safe_click(media_frame.get_by_role("button", name="上传").first, "上传按钮(角色)", page, timeout=2500)

    file_input = media_frame.locator("input[type='file']").first
    file_input.wait_for(state="attached", timeout=5000)
    file_input.set_input_files(image_path)

    # 上传确认按钮：取最后一个“上传”按钮（通常是当前上传弹窗的确认）。
    _safe_click(media_frame.get_by_role("button", name="上传").last, "上传确认按钮(角色)", page, timeout=2500)

    _safe_click(media_frame.locator(".x-tool-close").first, "上传弹窗关闭按钮", page, timeout=1500)
    _close_visible_popup(media_frame, page)
    print(f"素材上传完成: {image_path}")
    return _step_result(True, result=image_path)

def delete_material(page, image_name):
    print("开始删除素材...")
    if not _open_media_management(page, "多媒体素材管理"):
        return _step_result(False, retryable=True, error="未打开多媒体素材管理")
    frame = _get_media_frame(page)
    _open_media_category(frame, "Birth")
    _close_visible_popup(frame, page)
    selected_rows = set()
    has_selected = False

    names = [image_name] if isinstance(image_name, str) else image_name

    def _name_cell_text(row_locator):
        selectors = [
            "td.x-grid-cell-gridcolumn-1214 div.x-grid-cell-inner",
            "xpath=.//td[@role='gridcell'][3]//div[contains(@class,'x-grid-cell-inner')]",
            "xpath=.//td[contains(@class,'x-grid-cell-gridcolumn')][1]//div[contains(@class,'x-grid-cell-inner')]",
        ]
        for sel in selectors:
            cell = row_locator.locator(sel).first
            try:
                if cell.count() == 0:
                    continue
                text = cell.inner_text(timeout=1000)
                text = text.replace("\xa0", " ").strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _match_name_cell(cell_text, filename):
        text_l = cell_text.strip().lower()
        filename_l = filename.lower()
        stem_l = re.sub(r"\.[^.]+$", "", filename_l)

        if text_l == filename_l:
            return True

        if stem_l and text_l.startswith(stem_l + "_"):
            return True

        return False

    not_matched=[]

    for name in names:
        if not name:
            continue

        filename = re.split(r"[\\/]", str(name))[-1]
        if not filename:
            continue

        matched = False
        rows = frame.locator("tr.x-grid-row")
        row_count = rows.count()

        for i in range(row_count):
            row_locator = rows.nth(i)
            try:
                if not row_locator.is_visible():
                    continue
            except Exception:
                continue

            row_key = row_locator.get_attribute("data-recordid")
            if not row_key:
                row_key = row_locator.get_attribute("id")
            if not row_key:
                row_key = row_locator.inner_text(timeout=1000).strip()

            if not row_key or row_key in selected_rows:
                continue

            name_text = _name_cell_text(row_locator)
            if not name_text or not _match_name_cell(name_text, filename):
                continue

            if has_selected:
                row_locator.click(modifiers=["ControlOrMeta"])
            else:
                row_locator.click()
                has_selected = True
            selected_rows.add(row_key)
            matched = True

        if not matched:
            print(f"未找到可删除素材: {filename}")
            not_matched.append(name)

    if len(not_matched) > 0:
        print("有未匹配到素材：" + ", ".join(not_matched))
        if len(not_matched) == len(names):
            return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")

    # 删除按钮：按文本“删除”定位，不再依赖动态 id。
    _safe_click(frame.get_by_role("button", name="删除").first, "删除按钮(角色)", page, timeout=2500)
    frame.get_by_role("button", name="是").click()
    frame.get_by_role("button", name="确定").click()
    print(f"素材删除完成: {image_name}")
    if len(not_matched) > 0:
        return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")
    return _step_result(True, result=image_name)

# def build_playlist(page, image_name, date):
#     """建立播放单，image_name 为素材名称，date 为业务日期字符串。"""
#     page.get_by_text("播出单管理").click()
#     play_frame = page.locator('[id="42-tab"]').content_frame

#     playlist_name = f"birthboard_{date}"
#     play_frame.get_by_role("button", name="添加").click()
#     play_frame.get_by_role("textbox", name="播出单名称:").fill(playlist_name)
#     play_frame.get_by_role("textbox", name="播出单名称:").press("Tab")
#     play_frame.get_by_role("textbox", name="播出单描述:").fill(f"自动创建_{date}")
#     play_frame.get_by_role("textbox", name="播出单描述:").press("Tab")
#     play_frame.get_by_role("textbox", name="任务类型:").click()
#     play_frame.get_by_role("option", name="插播任务").click()
#     play_frame.get_by_role("button", name="下一步").click()
#     play_frame.get_by_text("元培学院").click()
#     play_frame.locator("#gridcolumn-1277-textEl").click()
#     play_frame.get_by_role("button", name="下一步").click()
#     play_frame.get_by_role("button", name="添加").click()
#     play_frame.get_by_role("img", name="横-全屏-1920*").click()
#     play_frame.locator("#button-1312").click()
#     play_frame.get_by_role("button", name="确定").click()
#     play_frame.locator("#tool-1316-toolEl").click()
#     play_frame.locator("#region_1").click(button="right")
#     play_frame.get_by_role("link", name="添加元素").click()
#     page.wait_for_timeout(3000)

#     picker_frame = play_frame.locator("iframe").content_frame
#     picker_frame.locator("img").nth(3).click()
#     picker_frame.locator("#ext-gen1202 > .x-grid-cell-inner > .x-tree-elbow-img.x-tree-elbow-plus").click()
#     picker_frame.get_by_text("新目录-2", exact=True).click()
#     picker_frame.get_by_text(image_name, exact=True).click()
#     picker_frame.get_by_role("button", name="添加").click()
#     picker_frame.get_by_role("button", name="确定").click()
#     print(f"播放单已创建，已加入素材: {image_name}")


# def close_playlist(page):
#     """关闭图片选择窗口并保存播放单。"""
#     play_frame = page.locator('[id="42-tab"]').content_frame
#     play_frame.locator("#tool-1328-toolEl").click()
#     play_frame.get_by_role("button", name="保存").click()
#     play_frame.get_by_role("button", name="确定").click()
#     play_frame.get_by_role("button", name="确定").click()
#     print("图片窗口已关闭并保存播放单")

def update_playlist(page, image_name, playlist_name="0-1点生日三联", debug=False):
    print("开始向播出单导入素材...")
    """上传素材，image_path 为本地图片路径。"""
    if not _open_media_management(page, "播出单管理"):
        return _step_result(False, retryable=True, error="未打开播出单管理")
    play_frame = _get_playlist_frame(page, playlist_name=playlist_name)
    _close_visible_popup(play_frame, page)
    play_frame.get_by_text(playlist_name, exact=True).first.click(timeout=3000)
    play_frame.get_by_role("button", name="修改").first.click(timeout=3000)
    # 右键点击播出单编排区域弹出菜单。
    # region_1 是叠加在模板上的半透明编排层，右键落在它上面才能弹出菜单；
    # 背景图 backgroundImage 在其下层，右键无效，故仅作兜底。
    template_panel = play_frame.locator("div.x-panel").filter(
        has_text="模版区域"
    ).first
    right_click_targets = [
        template_panel.locator("#region_1").first,
        template_panel.locator("#backgroundImage").first,
        template_panel.locator("#TemplateRegionID").first,
    ]
    for target in right_click_targets:
        try:
            target.click(button="right", timeout=3000)
            break
        except Exception:
            continue
    page.wait_for_timeout(500)
    play_frame.get_by_role("link", name="添加元素").first.click(timeout=3000)

    picker_frame = _get_picker_frame(play_frame, page, debug=debug)
    _open_media_category(picker_frame, "Birth")
    selected_rows = set()

    def _row_key_from_match(match_locator):
        row = match_locator.locator("xpath=ancestor::*[contains(@class,'x-grid-row')][1]")
        if row.count() == 0:
            return None, None
        row_id = row.first.get_attribute("data-recordid")
        if not row_id:
            row_id = row.first.get_attribute("id")
        if not row_id:
            row_id = row.first.inner_text(timeout=1000).strip()
        return row_id, row.first

    def _name_cell_text(row_locator):
        selectors = [
            "td.x-grid-cell-gridcolumn-1214 div.x-grid-cell-inner",
            "xpath=.//td[@role='gridcell'][3]//div[contains(@class,'x-grid-cell-inner')]",
            "xpath=.//td[contains(@class,'x-grid-cell-gridcolumn')][1]//div[contains(@class,'x-grid-cell-inner')]",
        ]
        for sel in selectors:
            cell = row_locator.locator(sel).first
            try:
                if cell.count() == 0:
                    continue
                text = cell.inner_text(timeout=1000)
                text = text.replace("\xa0", " ").strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _match_name_cell(cell_text, filename):
        text_l = cell_text.strip().lower()
        filename_l = filename.lower()
        stem_l = re.sub(r"\.[^.]+$", "", filename_l)

        if text_l == filename_l:
            return True

        if stem_l and text_l.startswith(stem_l + "_"):
            return True

        return False

    # 兼容传入单个字符串或列表
    names = [image_name] if isinstance(image_name, str) else image_name

    not_matched = []

    for name in names:
        if not name:
            continue

        # 允许传入完整路径，统一提取文件名
        filename = re.split(r"[\\/]", str(name))[-1]
        if not filename:
            continue

        # 先做精确匹配，保持与手写单条定位一致
        exact_target = picker_frame.get_by_text(filename, exact=True)
        if exact_target.count() > 0:
            row_key, row_locator = _row_key_from_match(exact_target.first)
            if row_key and row_key not in selected_rows:
                row_locator.dblclick()
                selected_rows.add(row_key)
            continue

        rows = picker_frame.locator("tr.x-grid-row")
        row_count = rows.count()
        matched = False

        for i in range(row_count):
            row_locator = rows.nth(i)
            try:
                if not row_locator.is_visible():
                    continue
            except Exception:
                continue

            row_key = row_locator.get_attribute("data-recordid")
            if not row_key:
                row_key = row_locator.get_attribute("id")
            if not row_key:
                row_key = row_locator.inner_text(timeout=1000).strip()

            if not row_key or row_key in selected_rows:
                continue

            name_text = _name_cell_text(row_locator)
            if not name_text or not _match_name_cell(name_text, filename):
                continue

            row_locator.dblclick()
            selected_rows.add(row_key)
            matched = True

        if not matched:
            print(f"未找到可添加素材: {filename}")
            not_matched.append(filename)

    if len(not_matched) > 0:
        print("有未匹配到素材：" + ", ".join(not_matched))
        if len(not_matched) == len(names):
            return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")

    _close_picker_window(play_frame, page)

    # 将新加入的素材切换效果统一设置为“上进”。
    # 参考 delete_playlist 的选行方式：在播出单 frame 中按名称列匹配并选中。
    try:
        added_filenames = [
            re.split(r"[\\/]", str(n))[-1]
            for n in names
            if n and re.split(r"[\\/]", str(n))[-1] not in not_matched
        ]

        def _row_key(row_locator):
            row_id = row_locator.get_attribute("data-recordid")
            if not row_id:
                row_id = row_locator.get_attribute("id")
            if not row_id:
                row_id = row_locator.inner_text(timeout=1000).strip()
            return row_id

        def _name_cell_text(row_locator):
            selectors = [
                "td.x-grid-cell-gridcolumn-1214 div.x-grid-cell-inner",
                "xpath=.//td[@role='gridcell'][3]//div[contains(@class,'x-grid-cell-inner')]",
                "xpath=.//td[contains(@class,'x-grid-cell-gridcolumn')][1]//div[contains(@class,'x-grid-cell-inner')]",
            ]
            for sel in selectors:
                cell = row_locator.locator(sel).first
                try:
                    if cell.count() == 0:
                        continue
                    text = cell.inner_text(timeout=1000)
                    text = text.replace("\xa0", " ").strip()
                    if text:
                        return text
                except Exception:
                    continue
            return ""

        def _match_name_cell(cell_text, filename):
            text_l = cell_text.strip().lower()
            filename_l = filename.lower()
            stem_l = re.sub(r"\.[^.]+$", "", filename_l)
            if text_l == filename_l:
                return True
            if stem_l and text_l.startswith(stem_l + "_"):
                return True
            return False

        def _is_row_selected(row_locator):
            try:
                cls = row_locator.get_attribute("class") or ""
                return "x-grid-row-selected" in cls
            except Exception:
                return False

        def _click_and_ensure_selected(row_locator, use_ctrl):
            if use_ctrl:
                row_locator.click(modifiers=["ControlOrMeta"])
            else:
                row_locator.click()
            page.wait_for_timeout(120)
            if _is_row_selected(row_locator):
                return True
            checker = row_locator.locator(
                "td.x-grid-cell-row-checker .x-grid-row-checker"
            ).first
            try:
                if checker.count() > 0:
                    if use_ctrl:
                        checker.click(modifiers=["ControlOrMeta"])
                    else:
                        checker.click()
                    page.wait_for_timeout(120)
                    return _is_row_selected(row_locator)
            except Exception:
                return _is_row_selected(row_locator)
            return _is_row_selected(row_locator)

        selected_rows = set()
        has_selected = False
        rows = play_frame.locator("tr.x-grid-row")
        row_count = rows.count()

        for filename in added_filenames:
            matched = False
            for i in range(row_count):
                row_locator = rows.nth(i)
                try:
                    if not row_locator.is_visible():
                        continue
                except Exception:
                    continue

                row_key = _row_key(row_locator)
                if not row_key or row_key in selected_rows:
                    continue

                try:
                    name_text = _name_cell_text(row_locator)
                except Exception:
                    continue

                if not name_text or not _match_name_cell(name_text, filename):
                    continue

                use_ctrl = has_selected
                selected_ok = _click_and_ensure_selected(row_locator, use_ctrl)
                if not has_selected and selected_ok:
                    has_selected = True
                if not selected_ok:
                    continue

                selected_rows.add(row_key)
                matched = True

            if not matched:
                print(f"设置切换效果未找到素材: {filename}")

        if selected_rows:
            # 先点击“图片特效”文本框，再点击“切换效果”按钮。
            _safe_click(
                play_frame.get_by_role("button", name="切换效果").first,
                "切换效果按钮",
                page,
                timeout=3000,
            )
            _safe_click(
                play_frame.get_by_role("textbox", name="图片特效:").first,
                "图片特效文本框",
                page,
                timeout=3000,
            )
            # 选中“上进”选项。
            _safe_click(
                play_frame.get_by_role("option", name="上进", exact=True).first,
                "切换效果-上进",
                page,
                timeout=3000,
            )
            # 点击“设置图片特效”弹窗内的“保存”按钮。
            # 该按钮是 <a role="button"> 元素，id 每次会话都会变化。
            # 页面上可能残留多个同名弹窗，且被遮罩(mask)遮挡；
            # 遍历所有同名弹窗，选一个可见的，对其“保存”按钮做 force 点击。
            effect_windows = play_frame.locator("div.x-window").filter(
                has_text="设置图片特效"
            )
            print(
                "[debug] play_frame 中标题含“设置图片特效”的弹窗数:",
                effect_windows.count(),
            )
            ok = False
            window_count = effect_windows.count()
            for idx in range(window_count - 1, -1, -1):
                effect_window = effect_windows.nth(idx)
                try:
                    if not effect_window.is_visible(timeout=1000):
                        continue
                except Exception:
                    continue
                save_btn = effect_window.get_by_text("保存", exact=True).first
                print(
                    f"[debug] 弹窗#{idx} 内文本“保存”的元素数:",
                    save_btn.count(),
                )
                if save_btn.count() == 0:
                    continue
                # 用 force 点击绕过 mask 遮挡，并直接命中该按钮。
                ok = _safe_click_force(
                    save_btn, f"设置图片特效-保存(force#{idx})", page
                )
                if ok:
                    print(f"[debug] 设置图片特效-保存 点击结果: {ok} (弹窗#{idx})")
                    break
            if not ok:
                print("[debug] 设置图片特效-保存 点击结果: False")
            _click_optional_confirm(page, play_frame, max_clicks=2)
    except Exception:
        logger.exception("[birthboard.web_controller] set transition effect failed")

    if not _safe_click(play_frame.get_by_role("button", name="保存").first, "播出单保存", page, timeout=3000):
        return
    _click_optional_confirm(page, play_frame, max_clicks=2)

    print(f"播出单导入完成: {image_name}")
    if len(not_matched) > 0:
        return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")
    return _step_result(True, result=image_name)


def delete_playlist(page, image_name, playlist_name="0-1点生日三联", debug=False):
    print("开始从播出单删除素材...")
    """删除播出单中的素材，image_name 可为字符串或列表。"""
    if not _open_media_management(page, "播出单管理"):
        return _step_result(False, retryable=True, error="未打开播出单管理")

    play_frame = _get_playlist_frame(page, playlist_name=playlist_name)
    _close_visible_popup(play_frame, page)
    play_frame.get_by_text(playlist_name, exact=True).first.click(timeout=3000)
    play_frame.get_by_role("button", name="修改").first.click(timeout=3000)

    # page.wait_for_timeout(1500)
    names = [image_name] if isinstance(image_name, str) else image_name
    selected_rows = set()
    has_selected = False

    def _dbg(msg):
        if debug:
            print(f"[delete_playlist][debug] {msg}")

    def _row_key(row_locator):
        row_id = row_locator.get_attribute("data-recordid")
        if not row_id:
            row_id = row_locator.get_attribute("id")
        if not row_id:
            row_id = row_locator.inner_text(timeout=1000).strip()
        return row_id

    def _name_cell_text(row_locator):
        # 列ID会在不同流程后动态变化，优先按旧class取，失败后回退到第3列(名称列)。
        selectors = [
            "td.x-grid-cell-gridcolumn-1214 div.x-grid-cell-inner",
            "xpath=.//td[@role='gridcell'][3]//div[contains(@class,'x-grid-cell-inner')]",
            "xpath=.//td[contains(@class,'x-grid-cell-gridcolumn')][1]//div[contains(@class,'x-grid-cell-inner')]",
        ]
        for sel in selectors:
            cell = row_locator.locator(sel).first
            try:
                if cell.count() == 0:
                    continue
                text = cell.inner_text(timeout=1000)
                text = text.replace("\xa0", " ").strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _match_name_cell(cell_text, filename):
        text_l = cell_text.strip().lower()
        filename_l = filename.lower()
        stem_l = re.sub(r"\.[^.]+$", "", filename_l)

        # 完整文件名直接命中
        if text_l == filename_l:
            _dbg(f"命中(完整文件名): row='{cell_text}' target='{filename}'")
            return True

        # 兼容上传后追加流水号: stem_xxxxx.ext
        if stem_l and text_l.startswith(stem_l + "_"):
            _dbg(f"命中(stem_前缀): row='{cell_text}' target='{filename}'")
            return True

        return False

    def _is_row_selected(row_locator):
        try:
            cls = row_locator.get_attribute("class") or ""
            return "x-grid-row-selected" in cls
        except Exception:
            return False

    def _selected_row_count():
        try:
            return play_frame.locator("tr.x-grid-row.x-grid-row-selected").count()
        except Exception:
            return -1

    def _click_and_ensure_selected(row_locator, use_ctrl):
        """某些场景首击只聚焦不选中，这里做一次补点兜底。"""
        if use_ctrl:
            row_locator.click(modifiers=["ControlOrMeta"])
        else:
            row_locator.click()

        page.wait_for_timeout(120)
        if _is_row_selected(row_locator):
            return True

        checker = row_locator.locator("td.x-grid-cell-row-checker .x-grid-row-checker").first
        try:
            if checker.count() > 0:
                if use_ctrl:
                    checker.click(modifiers=["ControlOrMeta"])
                else:
                    checker.click()
                page.wait_for_timeout(120)
                return _is_row_selected(row_locator)
        except Exception:
            return _is_row_selected(row_locator)

        return _is_row_selected(row_locator)

    rows = play_frame.locator("tr.x-grid-row")
    row_count = rows.count()
    _dbg(f"当前可见行数: {row_count}")
    _dbg(f"输入素材数量: {len(names)}")

    not_matched = []

    for name in names:
        if not name:
            _dbg("跳过空素材名")
            continue

        filename = re.split(r"[\\/]", str(name))[-1]
        if not filename:
            _dbg(f"无法解析文件名: {name}")
            continue

        _dbg(f"开始匹配素材: {filename}")

        matched = False
        for i in range(row_count):
            row_locator = rows.nth(i)
            try:
                if not row_locator.is_visible():
                    continue
            except Exception:
                continue

            row_key = _row_key(row_locator)
            if not row_key or row_key in selected_rows:
                continue

            try:
                name_text = _name_cell_text(row_locator)
            except Exception:
                continue

            if debug and i < 12:
                _dbg(f"行{i + 1} 名称列: {name_text}")

            if not name_text or not _match_name_cell(name_text, filename):
                continue

            before_selected = _is_row_selected(row_locator)
            before_total = _selected_row_count()
            _dbg(
                f"点击前: row={i + 1}, key={row_key}, selected={before_selected}, total_selected={before_total}"
            )

            use_ctrl = has_selected
            selected_ok = _click_and_ensure_selected(row_locator, use_ctrl)
            if not has_selected and selected_ok:
                has_selected = True

            after_selected = _is_row_selected(row_locator)
            after_total = _selected_row_count()
            _dbg(
                f"点击后: row={i + 1}, key={row_key}, selected={after_selected}, total_selected={after_total}"
            )

            if not selected_ok:
                _dbg(f"点击未生效，跳过该行: row={i + 1}, key={row_key}")
                continue

            selected_rows.add(row_key)
            matched = True
            _dbg(f"已选中行: key={row_key}, text={name_text}")

        if not matched:
            print(f"未找到播出单素材: {filename}")
            _dbg(f"素材未命中: {filename}")
            not_matched.append(filename)

    if len(not_matched) > 0:
        print("有未匹配到的删除素材："+", ".join(not_matched))
        if len(not_matched) == len(names):
            page.locator("[id=\"42-tab\"]").content_frame.get_by_role("button", name="返回").click()
            return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")
   
    print(f"已选中播出单素材行数: {len(selected_rows)}")

    if page.is_closed():
        print("页面已关闭，终止删除流程")
        return _step_result(False, retryable=False, error="页面已关闭")

    def _click_delete_button():
        # 只按文本“删除”定位按钮，避免依赖动态 id(#button-xxxx)。
        candidates = [
            (play_frame.get_by_role("button", name="删除").first, "删除按钮(播出单frame)"),
            (play_frame.locator("span.x-btn-inner").filter(has_text=re.compile(r"^删除$", re.IGNORECASE)).first, "删除按钮(span.x-btn-inner)"),
            (page.get_by_role("button", name="删除").first, "删除按钮(页面)"),
        ]
        for locator, desc in candidates:
            if _safe_click(locator, desc, page, timeout=500):
                return True
        return False

    if not _click_delete_button():
        return _step_result(False, retryable=True, error="未找到删除按钮")
    _safe_click(play_frame.get_by_role("button", name="是"), "删除确认", page)
    if not _safe_click(play_frame.get_by_role("button", name="保存"), "保存按钮", page):
        return _step_result(False, retryable=True, error="保存按钮点击失败")
    _click_optional_confirm(page, play_frame, max_clicks=2)
    print(f"播出单素材删除完成: {image_name}")
    if len(not_matched) > 0:
        return _step_result(False, retryable=True, pending=not_matched, result=not_matched, error="有未匹配到素材")
    return _step_result(True, result=image_name)

def update_list(page, up_image_name=None, del_image_name=None):
    up_image_name = up_image_name or []
    del_image_name = del_image_name or []
    if up_image_name:
        if del_image_name:
            print("同时指定了上传和删除素材，优先执行删除后再上传")
            upload_material(page, up_image_name)

            temp = update_playlist(page, up_image_name, "生日三联")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = update_playlist(page, temp, "生日三联")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功添加到播出单，未删除原有素材: {', '.join(temp)}")
            close_playlist(page)

            temp = delete_playlist(page, del_image_name, "生日三联")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_playlist(page, temp, "生日三联")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从播出单删除，可能仍在播出单中: {', '.join(temp)}")
            
            temp = update_playlist(page, up_image_name, "1号横屏")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = update_playlist(page, temp, "1号横屏")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功添加到播出单，未删除原有素材: {', '.join(temp)}")
            close_playlist(page)
            
            temp = delete_playlist(page, del_image_name, "1号横屏")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_playlist(page, temp, "1号横屏")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从播出单删除，可能仍在播出单中: {', '.join(temp)}")
            
            temp = delete_material(page, del_image_name)
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_material(page, temp)
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从素材库删除，可能仍在素材库中: {', '.join(temp)}")

        else:
            print("仅指定了上传素材，执行上传和播出单更新")
            upload_material(page, up_image_name)
            temp = update_playlist(page, up_image_name, "生日三联")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = update_playlist(page, temp, "生日三联")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功添加到播出单，未删除原有素材: {', '.join(temp)}")
            close_playlist(page)

            temp = update_playlist(page, up_image_name, "1号横屏")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = update_playlist(page, temp, "1号横屏")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功添加到播出单，未删除原有素材: {', '.join(temp)}")
            close_playlist(page)
            

    else:
        if del_image_name:
            print("仅指定了删除素材，执行删除和播出单更新")
           

            temp = delete_playlist(page, del_image_name, "生日三联")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_playlist(page, temp, "生日三联")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从播出单删除，可能仍在播出单中: {', '.join(temp)}")
            
            temp = delete_playlist(page, del_image_name, "1号横屏")
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_playlist(page, temp, "1号横屏")
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从播出单删除，可能仍在播出单中: {', '.join(temp)}")
            
            temp = delete_material(page, del_image_name)
            # temn = 1
            # while len(temp) > 0 and temn < 3:
            #     temp = delete_material(page, temp)
            #     temn += 1
            if len(temp) > 0:
                print(f"部分素材未成功从素材库删除，可能仍在素材库中: {', '.join(temp)}")
        else:
            print("未指定上传或删除素材，跳过更新")
            return False
    return True

@dataclass
class StepOutcome:
    label: str
    ok: bool
    retryable: bool = False
    result: Any = None
    pending: list[str] = field(default_factory=list)
    error: str | None = None


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _format_seconds(seconds):
    return f"{seconds:.2f}s"


def _restart_browser(playwright, browser, url, username, password):
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    return open_and_login(
        playwright=playwright,
        url=url,
        username=username,
        password=password,
    )


def _normalize_step_result(label, result):
    if isinstance(result, dict) and "ok" in result:
        return StepOutcome(
            label=label,
            ok=bool(result.get("ok")),
            retryable=bool(result.get("retryable", False)),
            result=result.get("result"),
            pending=list(result.get("pending") or []),
            error=result.get("error"),
        )

    if result is True or result is None:
        return StepOutcome(label=label, ok=True, result=result)

    if result == []:
        return StepOutcome(label=label, ok=True, result=result)

    if isinstance(result, list) and result and all(isinstance(item, str) for item in result):
        return StepOutcome(label=label, ok=False, retryable=True, result=result, pending=result)

    return StepOutcome(label=label, ok=False, retryable=False, result=result, error=f"unexpected return value: {result!r}")


def _step_failed(label, error):
    return StepOutcome(label=label, ok=False, retryable=True, error=str(error))


def _run_step_with_restart(playwright, browser, page, url, username, password, label, func, args, max_retries=3):
    attempt = 1
    current_args = args

    while attempt <= max_retries:
        step_start = perf_counter()
        try:
            print(f"开始步骤: {label}（第 {attempt}/{max_retries} 次）")
            result = func(page, *current_args)
        except Exception as e:
            outcome = _step_failed(label, e)
            elapsed = perf_counter() - step_start
            print(f"步骤失败[{label}]，耗时 {_format_seconds(elapsed)}: {outcome.error}")
            if attempt >= max_retries:
                return browser, page, outcome
            browser, page = _restart_browser(playwright, browser, url, username, password)
            attempt += 1
            continue

        outcome = _normalize_step_result(label, result)
        if outcome.ok:
            elapsed = perf_counter() - step_start
            print(f"步骤成功[{label}]，耗时 {_format_seconds(elapsed)}")
            return browser, page, outcome

        if outcome.retryable and outcome.pending:
            elapsed = perf_counter() - step_start
            print(f"步骤未完全完成[{label}]，耗时 {_format_seconds(elapsed)}，剩余: {', '.join(outcome.pending)}")
            current_args = (outcome.pending,) + current_args[1:]
        else:
            elapsed = perf_counter() - step_start
            print(f"步骤未达到预期效果[{label}]，耗时 {_format_seconds(elapsed)}，返回值: {outcome.result}")

        if attempt >= max_retries:
            return browser, page, outcome

        browser, page = _restart_browser(playwright, browser, url, username, password)
        attempt += 1

    return browser, page, StepOutcome(label=label, ok=False, retryable=False, error=f"步骤[{label}]重试次数已耗尽")


def _run_update_cycle(playwright, browser, page, url, username, password, up_image_name, del_image_name):
    deletion_step_count = 0
    if up_image_name:
        if del_image_name:
            print("同时指定了上传和删除素材，优先执行删除后再上传")
            workflow = [
                ("从播单删除-生日三联", delete_playlist, (del_image_name, "生日三联")),
                ("从播单删除-1号横屏", delete_playlist, (del_image_name, "1号横屏")),
                ("删除素材库", delete_material, (del_image_name,)),
                ("上传素材", upload_material, (up_image_name,)),
                ("更新播单-生日三联", update_playlist, (up_image_name, "生日三联")),
                ("更新播单-1号横屏", update_playlist, (up_image_name, "1号横屏")),
            ]
            deletion_step_count = 3
        else:
            print("仅指定了上传素材，执行上传和播单更新")
            workflow = [
                ("上传素材", upload_material, (up_image_name,)),
                ("更新播单-生日三联", update_playlist, (up_image_name, "生日三联")),
                # ("关闭播单-生日三联", close_playlist, ()),
                ("更新播单-1号横屏", update_playlist, (up_image_name, "1号横屏")),
                # ("关闭播单-1号横屏", close_playlist, ()),
            ]
    else:
        if del_image_name:
            print("仅指定了删除素材，执行删除和播出单更新")
            workflow = [
                ("从播单删除-生日三联", delete_playlist, (del_image_name, "生日三联")),
                ("从播单删除-1号横屏", delete_playlist, (del_image_name, "1号横屏")),
                ("删除素材库", delete_material, (del_image_name,)),
            ]
            deletion_step_count = len(workflow)
        else:
            print("未指定上传或删除素材，跳过更新")
            return browser, page, StepOutcome(
                label="update_cycle",
                ok=True,
                result=True,
            )

    deletion_failures = []
    for step_index, (label, func, args) in enumerate(workflow):
        if deletion_failures and step_index == deletion_step_count:
            # Mixed cycle barrier: incomplete removals block new uploads.
            break
        browser, page, outcome = _run_step_with_restart(
            playwright=playwright,
            browser=browser,
            page=page,
            url=url,
            username=username,
            password=password,
            label=label,
            func=func,
            args=args,
        )
        if not outcome.ok:
            print(f"步骤[{label}]最终失败: {outcome.error or outcome.result}")
            if step_index < deletion_step_count:
                # Takedown targets are independent. Continue so a failure on
                # one playlist cannot leave the same content active on the
                # other display. The caller still receives failure and keeps
                # the durable retry marker.
                deletion_failures.append(outcome)
                continue
            return browser, page, outcome

    if deletion_failures:
        pending = []
        errors = []
        for failure in deletion_failures:
            pending.extend(failure.pending)
            errors.append(
                f"{failure.label}: {failure.error or failure.result}"
            )
        return browser, page, StepOutcome(
            label="update_cycle",
            ok=False,
            retryable=True,
            pending=list(dict.fromkeys(pending)),
            error="; ".join(errors),
        )

    return browser, page, StepOutcome(label="update_cycle", ok=True, result=True)


def main():
    # 按需修改这些参数
    url = shihannet.url
    username = shihannet.username
    password = shihannet.password

    up_image_path = ["E:\\desktop\\Birth\\2026041701null.png", "E:\\desktop\\Birth\\1.png", "E:\\desktop\\Birth\\2026041705uewit.png"]
    # ,"E:\\desktop\\Birth\\2026041701null.png", "E:\\desktop\\Birth\\1.png"
    del_image_path = ["E:\\desktop\\Birth\\2026041702hahaha.png", "E:\\desktop\\Birth\\2026041703huaitfh.png", "E:\\desktop\\Birth\\2026041704ewiuat.png", ]
    image_name = "2_17677841565904.png"
    date = "20260417"
    log_path = Path(__file__).with_name("try_functions_output.txt")
    n=0
    with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
        tee = _Tee(sys.stdout, log_file)
        err_tee = _Tee(sys.stderr, log_file)
        with redirect_stdout(tee), redirect_stderr(err_tee):
            print(f"日志文件: {log_path}")
            print(f"日志开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            while True:
                round_start = perf_counter()
                n+=1
                print(f"============================第{n}轮测试开始============================")
                try:
                    with sync_playwright() as p:
                        browser = None
                        page = None
                        try:
                            browser, page = open_and_login(
                                playwright=p,
                                url=url,
                                username=username,
                                password=password,
                            )

                            browser, page, outcome = _run_update_cycle(
                                playwright=p,
                                browser=browser,
                                page=page,
                                url=url,
                                username=username,
                                password=password,
                                up_image_name=up_image_path,
                                del_image_name=del_image_path,
                            )
                            if not outcome.ok:
                                print(f"第一轮更新失败: {outcome.error or outcome.result}")
                                continue

                            browser, page, outcome = _run_update_cycle(
                                playwright=p,
                                browser=browser,
                                page=page,
                                url=url,
                                username=username,
                                password=password,
                                up_image_name=del_image_path,
                                del_image_name=up_image_path,
                            )
                            if not outcome.ok:
                                print(f"第二轮更新失败: {outcome.error or outcome.result}")
                                continue
                        finally:
                            if browser is not None:
                                try:
                                    browser.close()
                                except Exception:
                                    pass
                finally:
                    round_elapsed = perf_counter() - round_start
                    print(f"============================第{n}轮测试结束，耗时 {_format_seconds(round_elapsed)}============================")



def run():
    url = "http://192.168.8.2/admin/index/logon/"
    username = "admin"
    password = "2964f3db1822AC"

    import os as _os
    from django.conf import settings as _settings
    media_dir = _os.path.join(_settings.MEDIA_ROOT, 'birthboard_images')
    files = [
        f for f in _os.listdir(media_dir)
        if _os.path.isfile(_os.path.join(media_dir, f))
        and not f.startswith('._')
    ]
    up_image_path = [
        _os.path.join(media_dir, f) for f in files[:2]
    ] if len(files) >= 2 else []
    del_image_path = [
        _os.path.join(media_dir, f) for f in files[2:4]
    ] if len(files) >= 4 else []

    print(f"up_image_path={up_image_path}")
    print(f"del_image_path={del_image_path}")

    with sync_playwright() as p:
        browser, page = open_and_login(p, url, username, password)
        try:
            _run_update_cycle(
                playwright=p,
                browser=browser,
                page=page,
                url=url,
                username=username,
                password=password,
                up_image_name=[],
                del_image_name=del_image_path,
            )
        finally:
            browser.close()


if __name__ == "__main__":
    run()
