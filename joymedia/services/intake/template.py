"""The downloadable storyboard template.

The storyboard sheet has the same layout as the clients' own sheets (the brief in A1:B10, the scene table from row 13
with the same eight columns), so a sheet written for us and one written for the client are the same thing. Labels and
the required/optional split come from planning.workbook's field schema, so the template always matches what the reader
understands: required cells are shaded amber, every label has a note saying what to write, and a guide sheet explains
it. The notes and shading are ignored by the reader, so the sheet can be uploaded exactly as filled.
"""

from __future__ import annotations

import io

import frappe
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from joymedia.services.planning.workbook import (
	BRAND_FIELDS,
	FIELDS,
	REFERENCE_COLUMNS,
	REFERENCE_TYPE_LABELS,
	SCENE_COLUMNS,
)

REQUIRED_FILL = PatternFill("solid", fgColor="FFE9A8")
OPTIONAL_FILL = PatternFill("solid", fgColor="EDEDED")
HEADER_FILL = PatternFill("solid", fgColor="2F5D50")
SHEET_TITLES = {
	"guide": {"vi": "Hướng dẫn", "en": "Guide"},
	"sheet": {"vi": "Kịch bản mẫu", "en": "Storyboard"},
	"references": {"vi": "Tham chiếu", "en": "References"},
	"brand": {"vi": "Thương hiệu", "en": "Brand"},
}
EDGE = Side(style="thin", color="BDBDBD")
BORDER = Border(left=EDGE, right=EDGE, top=EDGE, bottom=EDGE)
WRAP = Alignment(wrap_text=True, vertical="top")

TEXT = {
	"vi": {
		"title": "Cách điền",
		"steps": (
			"1. Trang 'Kịch bản mẫu': ô vàng bắt buộc, ô xám tuỳ chọn. Rê chuột lên nhãn để xem gợi ý.",
			"2. Bảng cảnh (từ dòng 13): mỗi cảnh cần Tên cảnh + Hành động. Bỏ trống cả bảng: AI tự viết cảnh.",
			"3. Trang 'Tham chiếu': mỗi ảnh hoặc bối cảnh một dòng, có Tên và tệp sẽ tải lên.",
			"4. Cột Nhân vật / Sản phẩm / Bối cảnh của cảnh: chọn tên từ trang Tham chiếu.",
			"5. Trang 'Thương hiệu': tuỳ chọn.",
			"6. Tải bảng lên ở bước 1, các tệp ảnh/PDF ở bước 2.",
		),
		"brief": "Thông tin chung của video",
		"scenes": "Các cột của bảng cảnh",
		"field": "Nội dung",
		"need": "Bắt buộc?",
		"what": "Điền gì",
		"example": "Ví dụ",
		"yes": "Bắt buộc",
		"no": "Tuỳ chọn",
		"hint": "Ghi chú",
	},
	"en": {
		"title": "How to fill it in",
		"steps": (
			"1. 'Storyboard' sheet: amber cells are required, grey optional. Hover a label for a hint.",
			"2. Scene table (from row 13): each scene needs a Scene name + Action. Leave it empty: the AI writes the scenes.",
			"3. 'References' sheet: one row per picture or place, with a Name and the file you will upload.",
			"4. A scene's Characters / Products / Place columns: pick names from the References sheet.",
			"5. 'Brand' sheet: optional.",
			"6. Upload the sheet in step 1, the picture/PDF files in step 2.",
		),
		"brief": "The film's general brief",
		"scenes": "Scene table columns",
		"field": "Field",
		"need": "Required?",
		"what": "What to write",
		"example": "Example",
		"yes": "Required",
		"no": "Optional",
		"hint": "Note",
	},
}


def build_template(lang: str = "vi") -> bytes:
	"""The template workbook as .xlsx bytes."""
	lang = "en" if lang == "en" else "vi"
	copy = TEXT[lang]
	book = Workbook()
	guide = book.active
	guide.title = SHEET_TITLES["guide"][lang]
	_fill_guide(guide, lang, copy)
	_fill_sheet(book.create_sheet(SHEET_TITLES["sheet"][lang]), lang, copy)
	_fill_references(book.create_sheet(SHEET_TITLES["references"][lang]), lang)
	_fill_brand(book.create_sheet(SHEET_TITLES["brand"][lang]), lang)
	buffer = io.BytesIO()
	book.save(buffer)
	return buffer.getvalue()


def _fill_guide(sheet, lang, copy):
	# Column A stays empty: the reader takes labels from column A, so the guide can never be mistaken for a storyboard.
	sheet.column_dimensions["A"].width = 3
	for column, width in zip("BCDE", (28, 14, 60, 44), strict=False):
		sheet.column_dimensions[column].width = width
	sheet["B1"] = copy["title"]
	sheet["B1"].font = Font(bold=True, size=15)
	row = 3
	for step in copy["steps"]:
		sheet.cell(row, 2, step).alignment = Alignment(wrap_text=False, vertical="top")
		row += 1
	row += 1
	sections = (
		(copy["brief"], FIELDS),
		(copy["scenes"], SCENE_COLUMNS),
		(SHEET_TITLES["references"][lang], REFERENCE_COLUMNS),
		(SHEET_TITLES["brand"][lang], BRAND_FIELDS),
	)
	for heading, schema in sections:
		sheet.cell(row, 2, heading).font = Font(bold=True, size=12)
		row += 1
		for column, title in enumerate((copy["field"], copy["need"], copy["what"], copy["example"]), start=2):
			cell = sheet.cell(row, column, title)
			cell.font = Font(bold=True, color="FFFFFF")
			cell.fill = HEADER_FILL
			cell.border = BORDER
		row += 1
		for key, spec in schema.items():
			if key in NOT_ASKED:
				continue
			required = spec.get("required", False)
			values = (
				spec["label"][lang],
				copy["yes"] if required else copy["no"],
				spec["hint"][lang],
				spec.get("example", {}).get(lang, ""),
			)
			for column, value in enumerate(values, start=2):
				cell = sheet.cell(row, column, value)
				cell.alignment = WRAP
				cell.border = BORDER
				cell.fill = REQUIRED_FILL if required else OPTIONAL_FILL
			row += 1
		row += 1


# The layout of the clients' own storyboard sheets: the brief in A1:B10 (USPs on three rows), two empty rows, then the
# scene table from row 13 with these eight columns, as an Excel table named "Storyboard".
BRIEF_ROWS = (
	("product_name", 1),
	("objective", 2),
	("usp", 3),
	("duration", 6),
	("format", 7),
	("tone_mood", 8),
	("characters", 9),
)
# Fields the reader still accepts from older sheets but the template no longer asks for (pictures are uploaded instead).
NOT_ASKED = {"asset_requirements"}
HEADER_ROW = 13
COLUMN_WIDTHS = {
	"A": 12.5,
	"B": 12.2,
	"C": 28.1,
	"D": 36.0,
	"E": 22.1,
	"F": 19.8,
	"G": 22.1,
	"H": 27.8,
	"I": 20.0,
	"J": 20.0,
	"K": 16.0,
	"L": 30.0,
}
SCENE_HEADERS = {
	"vi": {
		"beat_name": "Phân cảnh",
		"timing": "Thời lượng",
		"visual_camera": "Hình ảnh & Góc máy (Visual / Camera)",
		"action": "Hành động & Diễn xuất (Action)",
		"voice_over": "Lời thoại / Voice-over (VO)",
		"audio_cues": "Âm thanh (SFX & BGM)",
		"on_screen_text": "Chữ hiển thị (On-screen Text)",
		"illustration_reference": "Minh hoạ khung hình",
		"cast": "Nhân vật trong cảnh",
		"products": "Sản phẩm trong cảnh",
		"place": "Bối cảnh",
		"continuity": "Logic / Liên tục",
	},
	"en": {
		"beat_name": "Scene",
		"timing": "Timing",
		"visual_camera": "Visual / Camera",
		"action": "Action",
		"voice_over": "Voice-over (VO)",
		"audio_cues": "Sound (SFX & BGM)",
		"on_screen_text": "On-screen Text",
		"illustration_reference": "Frame illustration",
		"cast": "Characters in the scene",
		"products": "Products in the scene",
		"place": "Place",
		"continuity": "Logic / Continuity",
	},
}
FONT = "Arial"


def _fill_sheet(sheet, lang, copy):
	"""The storyboard sheet, in the same layout as the clients' own sheets, with an example to overwrite."""
	from openpyxl.worksheet.datavalidation import DataValidation
	from openpyxl.worksheet.table import Table, TableStyleInfo

	for column, width in COLUMN_WIDTHS.items():
		sheet.column_dimensions[column].width = width
	for key, row in BRIEF_ROWS:
		spec = FIELDS[key]
		label = sheet.cell(row, 1, spec["label"][lang])
		label.font = Font(name=FONT, bold=True)
		label.alignment = Alignment(vertical="center")
		label.comment = Comment(
			f"{copy['yes'] if spec['required'] else copy['no']}. {spec['hint'][lang]}", "JoyMedia"
		)
		if spec["required"]:
			label.fill = REQUIRED_FILL
		lines = str(spec["example"][lang]).split("\n")
		if key == "usp":
			for offset, line in enumerate(lines[:3]):  # one USP per row, B3:B5
				sheet.cell(row + offset, 2, line).font = Font(name=FONT)
		else:
			value = sheet.cell(row, 2, "\n".join(lines))
			value.font = Font(name=FONT)
			value.alignment = Alignment(vertical="center", wrap_text=key == "characters")
	for column, (key, spec) in enumerate(SCENE_COLUMNS.items(), start=1):
		cell = sheet.cell(HEADER_ROW, column, SCENE_HEADERS[lang].get(key, spec["label"][lang]))
		if cell.column_letter not in COLUMN_WIDTHS:
			sheet.column_dimensions[cell.column_letter].width = 24
		cell.font = Font(name=FONT, bold=True)
		cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
		cell.comment = Comment(
			f"{copy['yes'] if spec['required'] else copy['no']}. {spec['hint'][lang]}", "JoyMedia"
		)
		if spec["required"]:
			cell.fill = REQUIRED_FILL
	sheet.row_dimensions[HEADER_ROW].height = 22.5
	row = HEADER_ROW
	for number in range(3):
		row += 1
		for column, key in enumerate(SCENE_COLUMNS, start=1):
			cell = sheet.cell(row, column, _scene_example(key, number, lang))
			cell.font = Font(name=FONT, bold=key == "beat_name")
			cell.alignment = Alignment(vertical="center", wrap_text=True)
	last = sheet.cell(HEADER_ROW, len(SCENE_COLUMNS)).column_letter
	table = Table(displayName="Storyboard", ref=f"A{HEADER_ROW}:{last}{row}")
	table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True, showFirstColumn=True)
	sheet.add_table(table)
	# The scene's cast, products and place are picked from the References sheet's names. Several names are typed with
	# commas, so a typed value is accepted (no error box); the list is a help.
	names = f"'{SHEET_TITLES['references'][lang]}'!$A$2:$A${REFERENCE_ROWS + 1}"
	keys = list(SCENE_COLUMNS)
	for key in ("cast", "products", "place", "opening_reference", "ending_reference"):
		letter = sheet.cell(HEADER_ROW, keys.index(key) + 1).column_letter
		choice = DataValidation(type="list", formula1=f"={names}", allow_blank=True, showErrorMessage=False)
		choice.add(f"{letter}{HEADER_ROW + 1}:{letter}{HEADER_ROW + 60}")
		sheet.add_data_validation(choice)


REFERENCE_ROWS = 40


def _fill_references(sheet, lang):
	"""One row per picture or place, by name; scenes refer to these names."""
	from openpyxl.worksheet.datavalidation import DataValidation

	for column, (_key, spec) in enumerate(REFERENCE_COLUMNS.items(), start=1):
		cell = sheet.cell(1, column, spec["label"][lang])
		cell.font = Font(name=FONT, bold=True)
		cell.alignment = Alignment(vertical="center", wrap_text=True)
		cell.comment = Comment(spec["hint"][lang], "JoyMedia")
		if spec["required"]:
			cell.fill = REQUIRED_FILL
		sheet.column_dimensions[cell.column_letter].width = spec["width"]
	for row, values in enumerate(REFERENCE_EXAMPLES[lang], start=2):
		for column, value in enumerate(values, start=1):
			cell = sheet.cell(row, column, value)
			cell.font = Font(name=FONT, bold=column == 1)
			cell.alignment = Alignment(vertical="top", wrap_text=True)
	types = DataValidation(
		type="list",
		formula1='"' + ",".join(label[lang] for label in REFERENCE_TYPE_LABELS.values()) + '"',
		allow_blank=True,
	)
	types.add(f"B2:B{REFERENCE_ROWS + 1}")
	sheet.add_data_validation(types)
	preservation_column = sheet.cell(1, list(REFERENCE_COLUMNS).index("preservation_mode") + 1).column_letter
	modes = DataValidation(type="list", formula1='"source_pixels,reference_guided"', allow_blank=True)
	modes.add(f"{preservation_column}2:{preservation_column}{REFERENCE_ROWS + 1}")
	sheet.add_data_validation(modes)
	sheet.freeze_panes = "B2"


REFERENCE_EXAMPLES = {
	"vi": (
		(
			"Bé Mai",
			"Nhân vật",
			"be_mai.png",
			"Bé gái 6 tuổi, tóc buộc hai bên, áo vàng",
			"con",
			"",
			"Giữ đúng gương mặt và áo vàng",
		),
		("Mẹ Lan", "Nhân vật", "me_lan.png", "Phụ nữ 30 tuổi, tóc ngang vai", "mẹ", "", ""),
		(
			"Sunny 500ml",
			"Sản phẩm",
			"sunny_500ml.png",
			"Chai nước rửa chén Sunny hương chanh 500ml, nhãn vàng",
			"",
			"",
			"Đúng chai 500ml, không vẽ lại nhãn",
		),
		("Logo Sunny", "Logo", "catalogue.pdf trang 2", "", "", "", "Chỉ chèn ở cảnh cuối"),
		(
			"Bếp nhà",
			"Bối cảnh",
			"",
			"Bếp gia đình nhỏ, sáng sủa, tủ gỗ, cửa sổ có nắng",
			"",
			"",
			"Một căn bếp cho mọi cảnh",
		),
		("Chai dầu ăn", "Đạo cụ", "", "Chai nhựa trong, nắp đỏ", "", "", ""),
	),
	"en": (
		(
			"Mai",
			"Character",
			"mai.png",
			"A 6-year-old girl, pigtails, yellow T-shirt",
			"child",
			"",
			"Same face and yellow T-shirt",
		),
		("Lan", "Character", "lan.png", "A woman of 30, shoulder-length hair", "mother", "", ""),
		(
			"Sunny 500 ml",
			"Product",
			"sunny_500ml.png",
			"Sunny lemon dish soap, 500 ml bottle, yellow label",
			"",
			"",
			"The 500 ml bottle; never redraw the label",
		),
		("Sunny logo", "Logo", "catalogue.pdf page 2", "", "", "", "Only in the last scene"),
		(
			"Home kitchen",
			"Place",
			"",
			"A small bright family kitchen, wooden cabinets, a sunny window",
			"",
			"",
			"One kitchen for every scene",
		),
		("Oil bottle", "Prop", "", "A clear plastic bottle with a red cap", "", "", ""),
	),
}


def _fill_brand(sheet, lang):
	"""What the film must say and must not say: labels in column A, values in B (more rows below for lists)."""
	sheet.column_dimensions["A"].width = 28
	sheet.column_dimensions["B"].width = 90
	row = 1
	for spec in BRAND_FIELDS.values():
		label = sheet.cell(row, 1, spec["label"][lang])
		label.font = Font(name=FONT, bold=True)
		label.alignment = Alignment(vertical="top")
		label.comment = Comment(spec["hint"][lang], "JoyMedia")
		lines = spec["example"][lang].split("\n")
		for offset, line in enumerate(lines):
			cell = sheet.cell(row + offset, 2, line)
			cell.font = Font(name=FONT)
			cell.alignment = Alignment(vertical="top", wrap_text=True)
		row += len(lines)


def _scene_example(key, number, lang):
	"""A believable example row (a hook, a selling point, an outro) for each scene column."""
	if key == "beat_name":
		return ("Hook", "USP 1", "Outro")[number]
	if key == "timing":
		return ("0:00 - 0:05", "0:05 - 0:20", "0:20 - 0:30")[number]
	examples = {
		"vi": {
			"visual_camera": (
				"Cận cảnh bồn rửa bếp, ánh nắng sáng",
				"Trung cảnh, bàn bếp gọn gàng",
				"Chính diện, sản phẩm ở giữa khung hình",
			),
			"action": (
				"Bé Mai làm đổ chai dầu ăn ra bếp, hoảng hốt tìm khăn",
				"Mẹ Lan nhỏ một giọt nước rửa chén, dầu mỡ tan ngay",
				"Mai và Mẹ Lan cầm sản phẩm, cười tươi với camera",
			),
			"voice_over": ('"Dầu mỡ cứng đầu?"', '"Chỉ một giọt là sạch!"', '"Sunny, bếp sạch mỗi ngày!"'),
			"audio_cues": ("SFX: tiếng chai đổ", "SFX: tiếng nước chảy", ""),
			"on_screen_text": ("", "SẠCH DẦU MỠ CHỈ 1 GIỌT", "MUA NGAY"),
			"illustration_reference": ("", "", ""),
			"cast": ("Bé Mai", "Mẹ Lan", "Bé Mai, Mẹ Lan"),
			"products": ("", "Sunny 500ml", "Sunny 500ml"),
			"place": ("Bếp nhà", "Bếp nhà", "Bếp nhà"),
			"continuity": (
				"Chai không vỡ; dầu chỉ đổ một vệt nhỏ",
				"Dầu tan dần, không biến mất tức thì",
				"Sản phẩm ở giữa, nhãn quay ra trước",
			),
		},
		"en": {
			"visual_camera": (
				"Close-up of a kitchen sink in morning sun",
				"Medium shot, a tidy counter",
				"Front view, the product centred",
			),
			"action": (
				"Mai knocks over the oil bottle on the counter and panics, reaching for a cloth",
				"Lan adds one drop of dish soap and the grease melts away",
				"Mai and Lan hold the product and smile at the camera",
			),
			"voice_over": (
				'"Stubborn grease?"',
				'"One drop and it\'s clean!"',
				'"Sunny, a clean kitchen every day!"',
			),
			"audio_cues": ("SFX: a bottle tipping", "SFX: running water", ""),
			"on_screen_text": ("", "GREASE GONE IN ONE DROP", "BUY NOW"),
			"illustration_reference": ("", "", ""),
			"cast": ("Mai", "Lan", "Mai, Lan"),
			"products": ("", "Sunny 500 ml", "Sunny 500 ml"),
			"place": ("Home kitchen", "Home kitchen", "Home kitchen"),
			"continuity": (
				"The bottle does not break; only a small spill",
				"The grease clears gradually, not instantly",
				"Product centred, label facing front",
			),
		},
	}
	return examples[lang].get(key, ("", "", ""))[number]


@frappe.whitelist()
def download_storyboard_template(lang="vi"):
	"""Download the storyboard template (.xlsx) in Vietnamese ('vi') or English ('en')."""
	lang = "en" if lang == "en" else "vi"
	frappe.response["filename"] = f"joymedia-storyboard-template-{lang}.xlsx"
	frappe.response["filecontent"] = build_template(lang)
	frappe.response["type"] = "download"
