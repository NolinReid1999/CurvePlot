import collections
import csv
import io
import itertools
import textwrap
from pathlib import Path

import pandas as pd
from PySide6 import QtGui, QtWidgets

from tailor.csv_options import resolve_delimiter
from tailor.ui_csv_format_dialog import Ui_CsvFormatDialog

DELIMITER_CHOICES = {
    "detect": None,
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "space": " ",
}
NUM_FORMAT_CHOICES = {"1,000.0": (".", ","), "1.000,0": (",", ".")}

FormatParameters = collections.namedtuple(
    "FormatParameters",
    "delimiter decimal thousands header skiprows skipfooter encoding",
    defaults=[",", ".", None, 0, 0, 0, "utf-8-sig"],
)


class CSVFormatDialog(QtWidgets.QDialog):
    def __init__(self, filename, parent):
        """Create the CSV file format selection dialog."""
        super().__init__(parent)

        self.ui = Ui_CsvFormatDialog()
        self.ui.setupUi(self)

        self.filename = Path(filename).expanduser()
        self.setWindowTitle(f"导入预览 — {self.filename.name}")
        self.encoding_box = QtWidgets.QComboBox(self)
        for title, codec in (
            ("UTF-8 / BOM", "utf-8-sig"),
            ("中文 GB18030", "gb18030"),
            ("Latin-1", "latin-1"),
        ):
            self.encoding_box.addItem(title, codec)
        self.ui.formLayout.addRow("文件编码", self.encoding_box)
        self.encoding_box.currentIndexChanged.connect(self.show_preview)

        self.ui.delimiter_box.addItems(DELIMITER_CHOICES.keys())
        self.ui.num_format_box.addItems(NUM_FORMAT_CHOICES.keys())

        # A numeric first record is data, not a column title (common oscilloscope export).
        try:
            with self.filename.open(encoding="utf-8-sig") as stream:
                first = stream.readline(65536).strip()
            delimiter = resolve_delimiter(
                self.filename, FormatParameters(delimiter=None)
            )
            fields = next(csv.reader([first], delimiter=delimiter))
            if fields and all(field.strip() for field in fields):
                for field in fields:
                    float(field)
                self.ui.use_header_box.setChecked(False)
        except (OSError, UnicodeError, ValueError):
            pass

        self.ui.delimiter_box.currentIndexChanged.connect(self.show_preview)
        self.ui.num_format_box.currentIndexChanged.connect(self.show_preview)
        self.ui.use_header_box.stateChanged.connect(self.show_preview)
        self.ui.header_row_box.valueChanged.connect(self.show_preview)
        self.ui.footer_row_box.valueChanged.connect(
            lambda value: self.show_preview(value, scroll_to_end=True)
        )
        self.ui.preview_choice.buttonClicked.connect(self.show_preview)

        self.show_preview()

    def show_preview(self, value=0, scroll_to_end=False):
        """Show a preview of the CSV data."""
        if self.ui.preview_choice.checkedButton() == self.ui.preview_csv_button:
            format = self.get_format_parameters()
            try:
                source = self.filename
                if format.skipfooter:
                    limit = (
                        202 + format.skiprows + (format.header or 0) + format.skipfooter
                    )
                    with self.filename.open(encoding=format.encoding) as stream:
                        lines = list(itertools.islice(stream, limit))
                    if len(lines) < limit:
                        source = io.StringIO("".join(lines[: -format.skipfooter]))
                df = pd.read_csv(
                    source,
                    delimiter=resolve_delimiter(self.filename, format),
                    decimal=format.decimal,
                    thousands=format.thousands,
                    header=format.header,
                    skiprows=format.skiprows,
                    nrows=200,
                    encoding=format.encoding,
                    encoding_errors="strict",
                    engine="c",
                    skipinitialspace=True,
                )
                from tailor.csv_options import convert_import_columns
                numeric = convert_import_columns(df)
                invalid = int((numeric.isna() & df.notna()).sum().sum())
                types = ", ".join(
                    f"{column}: {dtype}" for column, dtype in numeric.dtypes.items()
                )
                # Retain original nonnumeric text in the preview; conversion policy is explicit.
            except (OSError, UnicodeError, ValueError) as exc:
                text = textwrap.dedent(
                    f"""\
                    An error occured while parsing the data file. Most probably
                    the format is different from what was expected. You can
                    change the options in this screen to fix this. If you switch
                    to a *Plain text* preview you will be able to inspect the
                    literal text of the data file. Please check the column
                    delimiter and numeric format. In the case of comments or
                    introductory text at the start of the file you can skip a
                    number of lines.

                    The exception was:

                    {exc!s}
                    """
                )
            else:
                text = (
                    f"预览前 200 行；正式导入应用尾注设置。数值列中的无效单元格：{invalid}（将显示为空值）；纯文字/日期列保留原内容\n类型：{types}\n"
                    + df.to_string(index=False)
                )
        else:
            try:
                with open(self.filename, encoding=self.encoding_box.currentData()) as f:
                    lines = list(itertools.islice(f, 200))
                # Add line numbers
                max_width = len(str(len(lines)))
                numbered = [
                    f"{idx:>{max_width}}: {line}" for idx, line in enumerate(lines, 1)
                ]
                text = "".join(numbered)
            except (OSError, UnicodeError, ValueError) as exc:
                text = textwrap.dedent(
                    f"""\
                    An error occured while showing the literal text of the data
                    file. This should not happen. Please file an issue at:

                    https://github.com/davidfokkema/tailor/issues

                    If possible, include the data file. The exception was:

                    {exc!s}
                    """
                )
        self.ui.preview_box.setPlainText(text)
        if scroll_to_end:
            self.ui.preview_box.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        else:
            self.ui.preview_box.moveCursor(QtGui.QTextCursor.MoveOperation.Start)

    def get_format_parameters(self):
        """Get CSV format parameters

        Returns:
            delimiter, decimal, thousands, header: a tuple of format options.
        """
        delimiter = DELIMITER_CHOICES[self.ui.delimiter_box.currentText()]
        decimal, thousands = NUM_FORMAT_CHOICES[self.ui.num_format_box.currentText()]
        skipfooter = self.ui.footer_row_box.value()
        if self.ui.use_header_box.isChecked():
            header = self.ui.header_row_box.value()
            skiprows = 0
        else:
            header = None
            skiprows = self.ui.header_row_box.value()
        return FormatParameters(
            delimiter=delimiter,
            decimal=decimal,
            thousands=thousands,
            header=header,
            skiprows=skiprows,
            skipfooter=skipfooter,
            encoding=self.encoding_box.currentData(),
        )
