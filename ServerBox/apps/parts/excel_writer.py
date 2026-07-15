# -*- coding: utf-8 -*-
"""
excel_writer.py — 원본 엑셀을 서식/이미지 보존한 채 수정 ("매칭 실패" 표시).

openpyxl 로 load→save 하면 셀 삽입 이미지가 사라지므로,
xlsx(zip) 내부 XML 을 직접 패치한다. (WebApp lib/xlsx-writer.js 의 파이썬 포팅)
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col_to_idx(letter: str) -> int:
    col = 0
    for ch in letter.upper():
        if "A" <= ch <= "Z":
            col = col * 26 + (ord(ch) - 64)
    return col - 1


def _ref_col_idx(ref: str) -> int:
    m = re.match(r"^([A-Z]+)", ref or "")
    return _col_to_idx(m.group(1)) if m else -1


def _add_red_style(styles_xml: str):
    """styles.xml 에 빨간 fill + cellXf 추가. (수정된 xml, 새 스타일 인덱스) 반환"""
    m = re.search(r'<fills count="(\d+)">', styles_xml)
    fill_count = int(m.group(1))
    styles_xml = styles_xml.replace(m.group(0), f'<fills count="{fill_count + 1}">', 1)
    styles_xml = styles_xml.replace(
        "</fills>",
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFF0000"/>'
        '<bgColor indexed="64"/></patternFill></fill></fills>', 1)

    m = re.search(r'<cellXfs count="(\d+)">', styles_xml)
    xf_count = int(m.group(1))
    styles_xml = styles_xml.replace(m.group(0), f'<cellXfs count="{xf_count + 1}">', 1)
    styles_xml = styles_xml.replace(
        "</cellXfs>",
        f'<xf numFmtId="0" fontId="0" fillId="{fill_count}" borderId="0" xfId="0" applyFill="1"/></cellXfs>', 1)
    return styles_xml, xf_count


def _mark_rows(sheet_xml: bytes, rows, style_idx: int, col_letter: str) -> bytes:
    """시트 XML 의 지정 행/열에 '매칭 실패'(빨간 스타일) 셀 삽입 (열 순서 유지)"""
    ET.register_namespace("", NS_MAIN)
    ET.register_namespace("r", NS_REL)
    root = ET.fromstring(sheet_xml)
    q = lambda t: f"{{{NS_MAIN}}}{t}"
    col_idx = _col_to_idx(col_letter)

    row_map = {r.get("r"): r for r in root.iter(q("row"))}
    for row_num in rows:
        row_el = row_map.get(str(row_num))
        if row_el is None:
            continue
        ref = col_letter.upper() + str(row_num)

        # 기존 동일 셀 제거
        for c in list(row_el):
            if c.tag == q("c") and c.get("r") == ref:
                row_el.remove(c)

        c = ET.Element(q("c"), {"r": ref, "t": "inlineStr", "s": str(style_idx)})
        is_el = ET.SubElement(c, q("is"))
        t_el = ET.SubElement(is_el, q("t"))
        t_el.text = "매칭 실패"

        # 열 순서를 지켜 삽입
        pos = len(list(row_el))
        for i, x in enumerate(list(row_el)):
            if x.tag == q("c") and _ref_col_idx(x.get("r")) > col_idx:
                pos = i
                break
        row_el.insert(pos, c)

    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ET.tostring(root)


def mark_fail_rows(xlsx_bytes: bytes, fail_rows: dict, fail_col: str = "A") -> bytes:
    """
    원본 xlsx 에 매칭 실패 표시를 넣어 새 xlsx 바이트로 반환.
    fail_rows: {시트이름: [행번호, ...]}
    """
    src = zipfile.ZipFile(io.BytesIO(xlsx_bytes))

    # 시트 이름 → 내부 경로
    wb_xml = src.read("xl/workbook.xml").decode("utf-8")
    rels_xml = src.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rid_to_target = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels_xml))
    sheet_paths = {}
    for name, rid in re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wb_xml):
        target = rid_to_target.get(rid, "")
        sheet_paths[name] = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target

    has_fails = any(v for v in fail_rows.values())
    styles_xml = src.read("xl/styles.xml").decode("utf-8")
    style_idx = 0
    if has_fails:
        styles_xml, style_idx = _add_red_style(styles_xml)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/styles.xml" and has_fails:
                data = styles_xml.encode("utf-8")
            else:
                for sheet_name, path in sheet_paths.items():
                    if item.filename == path and fail_rows.get(sheet_name):
                        data = _mark_rows(data, fail_rows[sheet_name], style_idx, fail_col)
                        break
            dst.writestr(item, data)
    return out_buf.getvalue()
