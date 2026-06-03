#!/usr/bin/env python3
"""
将 HTML 中的外部图片本地化
用法: python3 tools/localize_images.py <html在项目内的相对文件路径>

接收一个 HTML 文件路径作为命令行参数
在同级目录创建 {html名}_image 文件夹，冲突时交互确认
提取所有非本地的 <img> 链接，用随机无后缀文件名重命名
映射关系写入 image_mapping.json
下载图片并保存到本地对应路径
不改变原 HTML 的结构下修改图片链接，将外部链接替换为本地相对路径

"""

import sys
import json
import shutil
import uuid
import re
from pathlib import Path

try:
    import requests
except ImportError:
    print("请先安装依赖: pip install requests")
    sys.exit(1)


def confirm_delete(folder: Path) -> bool:
    """询问用户是否删除已存在的文件夹。"""
    answer = input(f"文件夹 '{folder}' 已存在，是否删除并重建？(yes/y 确认): ").strip().lower()
    if answer in ("y", "yes"):
        shutil.rmtree(folder)
        return True
    print("已取消操作。")
    return False


def is_external_url(src: str) -> bool:
    """判断 src 是否为外部链接（非本地图片）。"""
    if not src:
        return False
    if src.startswith("http://") or src.startswith("https://"):
        return True
    if src.startswith("data:"):
        return False
    return False


def extract_src(tag: str):
    """从 <img ...> 标签字符串中提取 src 属性值（带引号）与包围引号类型，用于后续替换。"""
    # 匹配 src='...' 或 src="..." 或 src=...（无引号）
    m = re.search(r"""\bsrc\s*=\s*(['"])(.*?)\1""", tag, re.IGNORECASE)
    if m:
        return m.group(2), m.group(1)   # src 值, 引号类型
    m = re.search(r"""\bsrc\s*=\s*([^\s>]+)""", tag, re.IGNORECASE)
    if m:
        return m.group(1), ''  # 无引号
    return None, None


def replace_src_in_tag(tag: str, new_src: str):
    """返回替换 src 属性后的标签字符串，保留原引号风格。"""
    # 先尝试带引号的替换
    m = re.search(r"""(\bsrc\s*=\s*['"])(.*?)(['"])""", tag, re.IGNORECASE)
    if m:
        # m.group(1): src=' 或 src=" ; m.group(3): 对应的结束引号
        return tag[:m.start(2)] + new_src + tag[m.end(2):]
    # 再尝试无引号
    m = re.search(r"""(\bsrc\s*=\s*)([^\s>]+)""", tag, re.IGNORECASE)
    if m:
        return tag[:m.start(2)] + new_src + tag[m.end(2):]
    return tag  # 没有 src，原样返回


def main():
    if len(sys.argv) != 2:
        print("用法: python tools/localize_images.py <html在项目内的相对文件路径>")
        sys.exit(1)

    html_path = Path(sys.argv[1]).resolve()
    if not html_path.is_file():
        print(f"错误: 文件不存在 - {html_path}")
        sys.exit(1)

    html_dir = html_path.parent
    html_stem = html_path.stem
    image_dir = html_dir / f"{html_stem}_image"

    # 1. 创建图片文件夹，冲突时交互确认
    if image_dir.exists():
        if not confirm_delete(image_dir):
            sys.exit(1)
    image_dir.mkdir(parents=True, exist_ok=True)

    # 2. 读取原始 HTML 文本
    with open(html_path, "r", encoding="utf-8") as f:
        original_html = f.read()

    # 3. 正则匹配所有 <img ...> 标签，提取需要替换的外部图片
    img_pattern = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    mapping = []            # [[原链接, 相对路径], ...]
    # 用于记录每个外部图片对应的随机文件名（同一链接只生成一次）
    url_to_local = {}       # 原链接 -> 相对路径

    for tag_match in img_pattern.finditer(original_html):
        tag = tag_match.group(0)
        src_val, quote = extract_src(tag)
        if not src_val or not is_external_url(src_val):
            continue

        if src_val not in url_to_local:
            random_name = uuid.uuid4().hex
            local_rel = f"{html_stem}_image/{random_name}"
            url_to_local[src_val] = local_rel
            mapping.append([src_val, local_rel])

    if not mapping:
        print("未发现需要本地化的外部图片，无需操作。")
        try:
            image_dir.rmdir()
        except OSError:
            pass
        return

    # 4. 保存映射 JSON
    json_path = image_dir / "image_mapping.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"图片映射已保存至: {json_path}")

    # 5. 下载图片
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    for src, local_rel in mapping:
        dest_abs = html_dir / local_rel
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        print(f"下载: {src} -> {dest_abs}")
        try:
            resp = session.get(src, timeout=30)
            resp.raise_for_status()
            with open(dest_abs, "wb") as img_file:
                img_file.write(resp.content)
        except Exception as e:
            print(f"  下载失败: {e}")

    # 6. 替换 HTML 中的 src 属性（只修改<img>标签内，不改变其他部分）
    def replacer(match):
        tag = match.group(0)
        src_val, _ = extract_src(tag)
        if src_val and src_val in url_to_local:
            return replace_src_in_tag(tag, url_to_local[src_val])
        return tag  # 不替换

    new_html = img_pattern.sub(replacer, original_html)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"HTML 文件已更新: {html_path}")


if __name__ == "__main__":
    main()