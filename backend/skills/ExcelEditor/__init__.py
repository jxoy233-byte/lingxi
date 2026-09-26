"""Excel 文档编辑 skill —— 基于 openpyxl。

零外部 CLI 依赖，openpyxl 是沙盒已有依赖。
内容精确性优先：数字格式、日期、公式、CSV 互转。

LLM 调用方式（沙盒 code() 内）:
    from skills.ExcelEditor import ExcelDoc, ExcelDocError

    doc = ExcelDoc.create("/work/sales.xlsx", sheet_name="Q3")
    doc.write_table("A1", [["日期","产品","金额"], ...], header=True)
    doc.add_formula("D5", "=SUM(D2:D4)")
    doc.save()

    doc = ExcelDoc.from_csv("/work/data.csv", header=True)
    doc.save()

    doc.to_csv("/work/report.csv")
"""
import csv
import datetime
import sys
from pathlib import Path
from typing import Any, List, Optional, Union

from skills._shared._skill_help import _HelpMeta, auto_attach_help_module


# 中文字号映射（与 WordEditor 一致）
_CHINESE_FONT_SIZES = {
    "初号": 42, "小初": 36, "一号": 26, "小一": 24,
    "二号": 22, "小二": 18, "三号": 16, "小三": 15,
    "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
    "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
}
_UNIT_TO_PT = {"pt": 1.0, "px": 0.75, "cm": 28.3464567,
               "mm": 2.83464567, "in": 72.0}


def to_pt(value) -> Optional[float]:
    """字号 → pt。支持中文字号 / "12pt" / "0.5cm" / 纯数字。详细 help("to_pt")。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s in _CHINESE_FONT_SIZES:
        return _CHINESE_FONT_SIZES[s]
    for unit, factor in sorted(_UNIT_TO_PT.items(), key=lambda x: -len(x[0])):
        if s.endswith(unit):
            try:
                return float(s[:-len(unit)].strip()) * factor
            except ValueError:
                break
    try:
        return float(s)
    except ValueError:
        raise ExcelDocError(f"无法解析字号: {value!r}")


def to_rgb(value):
    """颜色 → (r, g, b)。支持 hex/named/rgb() 字符串/3 元组。详细 help("to_rgb")。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(int(v) for v in value)
    s = str(value).strip()
    if s.startswith("#"):
        s = s[1:]
    if s.startswith("rgb(") and s.endswith(")"):
        try:
            nums = [int(n.strip()) for n in s[4:-1].split(",")]
            if len(nums) == 3:
                return tuple(nums)
        except ValueError:
            pass
    named = {
        "black": (0, 0, 0), "white": (255, 255, 255),
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
        "gray": (128, 128, 128), "grey": (128, 128, 128),
        "yellow": (255, 255, 0), "orange": (255, 165, 0),
    }
    if s.lower() in named:
        return named[s.lower()]
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    raise ExcelDocError(f"无法解析颜色: {value!r}")


def hex_color(rgb):
    """RGB tuple → 6 位 hex 字符串（无 # 前缀）。"""
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


# 字重后缀（与 WordEditor 一致）
_FONT_WEIGHT_MAP = {
    "thin": " Thin", "hairline": " Thin",
    "light": " Light", "regular": "", "normal": "",
    "medium": " Medium", "semibold": " SemiBold", "demibold": " SemiBold",
    "bold": "", "extrabold": " ExtraBold",
    "heavy": " Black", "black": " Black", "extrablack": " ExtraBlack",
}


# 异常
class ExcelDocError(Exception):
    """Excel 文档操作的统一异常。"""
    pass


# 列字母 ↔ 列号转换
def _excel_letters(col: int) -> str:
    """1 → 'A', 26 → 'Z', 27 → 'AA'."""
    result = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        result = chr(65 + rem) + result
    return result


def _excel_to_col(letters: str) -> int:
    """'A' → 1, 'Z' → 26, 'AA' → 27."""
    n = 0
    for c in letters:
        n = n * 26 + (ord(c.upper()) - 64)
    return n


def _parse_cell_ref(ref: str) -> tuple:
    """'A1' → (col=1, row=1); 'AB12' → (28, 12)."""
    import re
    m = re.match(r"^([A-Z]+)(\d+)$", ref.strip().upper())
    if not m:
        raise ExcelDocError(f"无效的单元格引用: {ref!r}（格式: 'A1' / 'BC23'）")
    return _excel_to_col(m.group(1)), int(m.group(2))


# 核心类
class ExcelDoc(metaclass=_HelpMeta):
    """Excel 文档（.xlsx）封装，基于 openpyxl。

    内容精确性优先：数字格式 / 日期 / 公式 / CSV 互转 quote-aware + BOM。
    """

    def __init__(self, wb, *, path: Optional[str] = None):
        """内部构造；外部请用 create() / open() / from_csv()。"""
        self._wb = wb
        self._active = wb.active
        self._path = path

    @classmethod
    def create(cls, path: Optional[str] = None,
               sheet_name: str = "Sheet1") -> "ExcelDoc":
        """创建空白 xlsx。

        Args: path 文件保存路径（None 时 save() 必须显式传）；sheet_name 第一个工作表名（默认 "Sheet1"）。
        Returns: ExcelDoc 实例。详细 help("create")。
        """
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.title = sheet_name
        return cls(wb, path=path)

    @classmethod
    def open(cls, path: str) -> "ExcelDoc":
        """打开已有 xlsx。

        Args: path xlsx 文件路径。
        Returns: ExcelDoc 实例。
        Raises: 文件不存在抛 ExcelDocError。
        """
        from openpyxl import load_workbook
        path = str(Path(path))
        if not Path(path).exists():
            raise ExcelDocError(f"文件不存在: {path}")
        wb = load_workbook(path, data_only=False)
        return cls(wb, path=path)

    def save(self, path: Optional[str] = None):
        """落盘到 path 或 create/open 时指定的路径。详细 help("save")。"""
        out = path or self._path
        if not out:
            raise ExcelDocError("save() 需要 path，或在 create/open/from_csv 时指定 path")
        self._wb.save(out)
        self._path = out

    @classmethod
    def from_csv(cls, csv_path: str, xlsx_path: Optional[str] = None,
                 sheet_name: str = "Sheet1",
                 header: bool = True,
                 delimiter: str = ",",
                 encoding: str = "utf-8-sig") -> "ExcelDoc":
        """从 CSV 创建 xlsx 并自动落盘。

        Args: csv_path CSV 输入路径；xlsx_path xlsx 输出路径（None = CSV 同名 .xlsx）；sheet_name 工作表名（默认 "Sheet1"）；header 第一行是否为表头（默认 True）；delimiter 字段分隔符（默认 ","，TSV 用 "\\t"）；encoding 文件编码（默认 utf-8-sig 自动处理 BOM，中文乱码换 "gbk"）。
        Returns: 已落盘的 ExcelDoc 实例。
        Raises: CSV 文件不存在 / 编码错误 / 解析失败抛 ExcelDocError。
        """
        from openpyxl import Workbook
        csv_path = str(Path(csv_path))
        if not Path(csv_path).exists():
            raise ExcelDocError(f"CSV 文件不存在: {csv_path}")
        if xlsx_path is None:
            xlsx_path = str(Path(csv_path).with_suffix(".xlsx"))

        rows = []
        try:
            with open(csv_path, "r", encoding=encoding, newline="") as f:
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
        except UnicodeDecodeError as e:
            raise ExcelDocError(
                f"CSV 编码错误（{encoding}）: {e}\n"
                f"试试 encoding='gbk'（Excel 中文导出常见）或 'utf-8'"
            )
        except csv.Error as e:
            raise ExcelDocError(f"CSV 解析失败: {e}\n文件可能错位 quote 或字段数不一致")

        doc = cls.create(xlsx_path, sheet_name=sheet_name)
        if not rows:
            doc.save(xlsx_path)
            return doc
        doc.write_table("A1", rows, header=header)
        if header and rows:
            for c_idx, header_name in enumerate(rows[0]):
                col_letter = _excel_letters(c_idx + 1)
                width = max(10, min(40, len(str(header_name)) * 2 + 4))
                doc.set_column_width(col_letter, width)
        doc.save(xlsx_path)
        return doc

    def to_csv(self, path: str, sheet_name: str = None,
               delimiter: str = ",", encoding: str = "utf-8-sig") -> None:
        """当前 sheet 导出为 CSV。详细 help("to_csv")。

        Args: path 输出路径；sheet_name 导出哪个 sheet（None = 当前活动）；delimiter 字段分隔符（默认 ","）；encoding 文件编码（默认 utf-8-sig 带 BOM，Excel 中文不乱码）。
        """
        if sheet_name:
            self.select_sheet(sheet_name)
        rows = self.read_table()
        with open(path, "w", encoding=encoding, newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            for row in rows:
                writer.writerow(["" if v is None else v for v in row])

    # ---- Sheet 管理 ----

    def add_sheet(self, name: str) -> "ExcelDoc":
        """加新工作表（自动切换为新 sheet）。"""
        if name in self._wb.sheetnames:
            raise ExcelDocError(
                f"sheet 已存在: {name!r}\n"
                f"现有: {', '.join(self._wb.sheetnames)}"
            )
        self._active = self._wb.create_sheet(title=name)
        return self

    def select_sheet(self, name: str) -> "ExcelDoc":
        """切换到指定 sheet。"""
        if name not in self._wb.sheetnames:
            raise ExcelDocError(
                f"sheet 不存在: {name!r}\n"
                f"现有: {', '.join(self._wb.sheetnames)}"
            )
        self._active = self._wb[name]
        return self

    def sheets(self) -> list:
        """列出所有 sheet 名。"""
        return self._wb.sheetnames

    def delete_sheet(self, name: str) -> "ExcelDoc":
        """删除指定 sheet（不可恢复）。"""
        if name not in self._wb.sheetnames:
            raise ExcelDocError(
                f"sheet 不存在: {name!r}\n"
                f"现有: {', '.join(self._wb.sheetnames)}"
            )
        del self._wb[name]
        if self._active.title == name:
            self._active = self._wb[self._wb.sheetnames[0]] if self._wb.sheetnames else None
        return self

    def rename_sheet(self, old_name: str, new_name: str) -> "ExcelDoc":
        """重命名 sheet。"""
        if old_name not in self._wb.sheetnames:
            raise ExcelDocError(
                f"sheet 不存在: {old_name!r}\n"
                f"现有: {', '.join(self._wb.sheetnames)}"
            )
        if new_name in self._wb.sheetnames:
            raise ExcelDocError(f"目标 sheet 名已存在: {new_name!r}")
        self._wb[old_name].title = new_name
        return self

    def freeze_cells(self, cell_ref: str) -> None:
        """冻结到指定单元格（如 'A2' 冻结首行 / 'B1' 冻结首列 / 'B2' 都冻结）。"""
        self._active.freeze_panes = cell_ref

    def autofilter(self, range_ref: str) -> None:
        """启用自动筛选（如 'A1:D100'）。"""
        self._active.auto_filter.ref = range_ref

    # ---- 数据写入 ----

    def write_table(self, start_cell: str, data: list, *,
                    header: bool = False,
                    header_fill: str = None,
                    header_color: str = "FFFFFF",
                    number_formats: dict = None,
                    date_format: str = "yyyy-mm-dd",
                    date_columns: list = None) -> int:
        """从 start_cell 开始批量写二维数据。

        Args: start_cell 起始单元格；data 二维列表；header True 时第一行加粗+背景；header_fill 表头背景色；number_formats 列号 → 数字格式字符串；date_columns 哪些列按日期格式化。
        Returns: 写入行数。详细 help("write_table")。
        """
        from openpyxl.styles import Font, PatternFill, Alignment

        if not data:
            return 0
        start_col, start_row = _parse_cell_ref(start_cell)
        date_columns = date_columns or []
        number_formats = number_formats or {}

        rows_written = 0
        for r_offset, row_data in enumerate(data):
            for c_offset, value in enumerate(row_data):
                col = start_col + c_offset
                row = start_row + r_offset
                cell = self._active.cell(row=row, column=col)
                cell.value = value

                is_header = header and r_offset == 0
                custom_fmt = number_formats.get(str(c_offset))

                if is_header:
                    cell.font = Font(
                        bold=True,
                        color=hex_color(to_rgb(header_color)) if header_color else None,
                    )
                    if header_fill:
                        h = hex_color(to_rgb(header_fill))
                        cell.fill = PatternFill(
                            start_color="FF" + h, end_color="FF" + h,
                            fill_type="solid",
                        )
                    cell.alignment = Alignment(horizontal="center")
                else:
                    if c_offset in date_columns or custom_fmt == "date":
                        cell.number_format = date_format
                    elif custom_fmt:
                        cell.number_format = custom_fmt
                    elif isinstance(value, (datetime.datetime, datetime.date)):
                        cell.number_format = date_format
                    elif isinstance(value, float) and custom_fmt is None:
                        cell.number_format = "#,##0.00"

            rows_written += 1
        return rows_written

    def set_cell(self, cell_ref: str, value, *,
                 number_format: str = None,
                 bold: bool = None, italic: bool = None,
                 font: str = None, font_size=None,
                 font_weight: str = None,
                 color: str = None, fill: str = None,
                 alignment: str = None) -> None:
        """设置单格的值和格式（数字设 number_format="0.00" 避免科学计数）。详细 help("set_cell")。"""
        from openpyxl.styles import Font, PatternFill, Alignment

        col, row = _parse_cell_ref(cell_ref)
        cell = self._active.cell(row=row, column=col)
        cell.value = value

        font_name = font if font else None
        weight_suffix = _FONT_WEIGHT_MAP.get(font_weight.lower().replace("-", "").replace(" ", "")) if font_weight else None
        if font_name and weight_suffix:
            if not any(s in font_name for s in (" Thin"," Light"," Medium"," SemiBold"," ExtraBold"," Black"," ExtraBlack")):
                font_name = font_name + weight_suffix

        if any(x is not None for x in (bold, italic, font, font_size, font_weight, color)):
            cell.font = Font(
                name=font_name,
                size=to_pt(font_size) if font_size else None,
                bold=bold or False,
                italic=italic or False,
                color="FF" + hex_color(to_rgb(color)) if color else None,
            )
        if fill:
            h = hex_color(to_rgb(fill))
            cell.fill = PatternFill(start_color="FF" + h, end_color="FF" + h, fill_type="solid")
        if alignment:
            cell.alignment = Alignment(horizontal=alignment)
        if number_format:
            cell.number_format = number_format
        elif isinstance(value, (datetime.datetime, datetime.date)):
            cell.number_format = "yyyy-mm-dd"

    def add_formula(self, cell_ref: str, formula: str) -> None:
        """写公式（自动补 = 前缀）。openpyxl 不计算，Excel/WPS 打开后才算。"""
        col, row = _parse_cell_ref(cell_ref)
        cell = self._active.cell(row=row, column=col)
        cell.value = formula if formula.startswith("=") else f"={formula}"

    # ---- 数据读取 ----

    def get_cell(self, cell_ref: str):
        """读单格值。公式返回公式字符串；计算后值需 data_only=True 重打开。"""
        col, row = _parse_cell_ref(cell_ref)
        return self._active.cell(row=row, column=col).value

    def read_table(self, start_cell: str = "A1", end_cell: str = None) -> list:
        """读表格为二维数组。详细 help("read_table")。"""
        start_col, start_row = _parse_cell_ref(start_cell)
        if end_cell:
            end_col, end_row = _parse_cell_ref(end_cell)
        else:
            end_row = self._active.max_row
            end_col = self._active.max_column

        rows = []
        for row in range(start_row, end_row + 1):
            row_data = []
            for col in range(start_col, end_col + 1):
                row_data.append(self._active.cell(row=row, column=col).value)
            rows.append(row_data)
        return rows

    def get_table_as_dicts(self, start_cell: str = "A1") -> list:
        """读表格为 list[dict]（第一行作字段名）。"""
        rows = self.read_table(start_cell)
        if not rows:
            return []
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        result = []
        for row in rows[1:]:
            record = {}
            for i, h in enumerate(headers):
                record[h] = row[i] if i < len(row) else None
            result.append(record)
        return result

    # ---- 行列 / 样式 ----

    def set_column_width(self, col: str, width: float) -> None:
        """col: 'A' / 'B'。width: 字符宽度（openpyxl 默认单位）。"""
        self._active.column_dimensions[col.upper()].width = width

    def set_row_height(self, row: int, height: float) -> None:
        """设置指定行高度。"""
        self._active.row_dimensions[row].height = height

    def insert_row(self, row_idx: int) -> None:
        """在 row_idx 处插入空行（**公式不自动 shift**，复杂公式手动重写）。"""
        self._active.insert_rows(row_idx)

    def delete_row(self, row_idx: int) -> None:
        """删除 row_idx 行（**公式不自动 shift**）。"""
        self._active.delete_rows(row_idx)

    def merge_cells(self, range_ref: str) -> None:
        """合并单元格。range_ref: 'A1:D5'。"""
        self._active.merge_cells(range_ref)

    def used_range(self) -> tuple:
        """返回 (start_cell, end_cell)，如 ('A1', 'D10')。"""
        return (
            "A1",
            f"{_excel_letters(self._active.max_column)}{self._active.max_row}",
        )


# 公共辅助函数
def path_to_work(sandbox_path: str) -> str:
    """沙盒 /work/xxx → 主进程 cached/{sid}/xxx。"""
    p = Path(sandbox_path)
    if p.is_absolute() and str(p).startswith("/work/"):
        return str(p.relative_to("/work"))
    return sandbox_path


def version_info() -> dict:
    """返回底层库版本信息（用于诊断）。"""
    out = {}
    try:
        import openpyxl
        out["openpyxl"] = openpyxl.__version__
    except ImportError:
        out["openpyxl"] = "NOT INSTALLED"
    return out


# help() / doc() —— AI 按需查函数详细用法
def doc(name=None):
    """查询本 skill 的函数 / 类 docstring。详细 help("doc")。

    用法:
        from skills.ExcelEditor import help
        help()                       # 全部函数 / 类签名
        help("ExcelDoc")             # ExcelDoc 类详情 + 方法列表
        help("ExcelDoc.from_csv")    # 单个方法详细用法
    """
    import sys
    from skills._shared._skill_help import skill_help
    return skill_help(sys.modules[__name__], name)


def help(name=None):
    """doc() 别名。"""
    return doc(name)


# 自动给所有函数挂 .help 属性（ExcelDoc.add_paragraph.help 直接拿）
auto_attach_help_module(sys.modules[__name__])