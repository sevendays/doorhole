#!/usr/bin/env python

# Checks functional requirements with regexes
# Builds functional matrix

import doorstop
from doorstop.core.types import iter_items, Level
import os
import sys
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import logging
import markdown
from plantuml_markdown import PlantUMLMarkdownExtension
import tempfile

EXTENSIONS = (
	'markdown.extensions.extra',
	'markdown.extensions.sane_lists',
	PlantUMLMarkdownExtension(
		server='http://www.plantuml.com/plantuml',
		cachedir=tempfile.gettempdir(),
		format='svg',
		classes='class1,class2',
		title='UML',
		alt='UML Diagram',
	),
)

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logging.getLogger('doorstop').setLevel(logging.WARNING)
logging.getLogger('MARKDOWN').setLevel(logging.WARNING)
log = logging.getLogger(__name__)


# requirements tree is a global because it's shared by all classes.
# Maybe it should become a singleton.
reqtree = None

def build_child_links_index():
	"""Scan the entire requirements tree and build a mapping from a UID (str)
	to the list of UIDs (str) of items that declare it as a parent link."""
	global reqtree
	index = {}
	for document in reqtree:
		for item in iter_items(document):
			child_uid = str(item.uid).strip()
			for link in (item.links or []):
				parent_uid = str(link).strip()
				index.setdefault(parent_uid, []).append(child_uid)
	return index

class LinksDelegate(QStyledItemDelegate):
	"""Custom delegate for rendering clickable links in the 'links' column."""

	LINK_COLUMN_NAMES = ('links', 'childlinks')

	def __init__(self, parent=None):
		super(LinksDelegate, self).__init__(parent)
		self.doc = QTextDocument(self)
		self._currentCacheKey = None

	def getDoc(self, option, index, linksList):
		width = option.rect.width()
		cache_key = (index.row(), tuple(linksList), width)
		if self._currentCacheKey == cache_key:
			return
		self._currentCacheKey = cache_key
		html = '<html><body style="margin: 4px;">'
		for uid in linksList:
			if uid:
				html += f'<a href="link:{uid}" style="color: blue; text-decoration: underline;">{uid}</a><br/>'
		html += '</body></html>'
		self.doc.setHtml(html)
		self.doc.setTextWidth(width)
	def paint(self, painter, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] in self.LINK_COLUMN_NAMES:
			links_data = mdl._data[index.row()][index.column()]
			linksList = self.parseLinks(links_data)
			self.getDoc(option, index, linksList)
			ctx = QAbstractTextDocumentLayout.PaintContext()
			painter.save()
			painter.translate(option.rect.topLeft())
			painter.setClipRect(option.rect.translated(-option.rect.topLeft()))
			self.doc.documentLayout().draw(painter, ctx)
			painter.restore()
		else:
			super(LinksDelegate, self).paint(painter, option, index)

	def sizeHint(self, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] in self.LINK_COLUMN_NAMES:
			links_data = mdl._data[index.row()][index.column()]
			linksList = self.parseLinks(links_data)
			self.getDoc(option, index, linksList)
			return QSize(self.doc.idealWidth(), self.doc.size().height())
		return super(LinksDelegate, self).sizeHint(option, index)

	def parseLinks(self, links_data):
		"""Parse links data into a list of UIDs.
		Doorstop links format: UID(<uid>
		stamp=<stamp>)
		Example: UID(SysR-002
		stamp=mcidGMWQFubYs9jDkGkCaoHchg3-41N0HMTToh_AiBl=)
		Multiple links are separated by newlines or commas.
		"""
		if not links_data or links_data == 'None' or links_data == '[]':
			return []

		if 'UID(' not in links_data:
			# Simple format: comma-separated UIDs (e.g. calculated child links)
			raw = links_data.strip('[]').replace("'", '')
			uids = [u.strip().rstrip(',') for u in raw.replace('\n', ',').split(',')]
			return [u for u in uids if u]

		# Remove list brackets if present
		links_data = links_data.strip('[]').replace("'", '')
		uids = []
		# Find all occurrences of "UID(" and extract the UID
		idx = 0
		while True:
			pos = links_data.find('UID(', idx)
			if pos == -1:
				break
			# Find the closing parenthesis
			end_pos = links_data.find(')', pos)
			if end_pos == -1:
				break
			# Extract content between "UID(" and ")"
			content = links_data[pos+4:end_pos]
			# Extract UID (everything before " stamp=" or newline)
			stamp_pos = content.find(' stamp=')
			newline_pos = content.find('\n')
			if stamp_pos != -1:
				uid = content[:stamp_pos].strip().rstrip(',')
			elif newline_pos != -1:
				uid = content[:newline_pos].strip().rstrip(',')
			else:
				uid = content.strip().rstrip(',')
			if uid and uid not in uids:
				uids.append(uid)
			idx = end_pos + 1
		return uids

	def getLinkAtPos(self, pos):
		"""Get the link URL at the given position, if any."""
		anchor = self.doc.documentLayout().anchorAt(pos)
		if anchor.startswith('link:'):
			return anchor[5:]  # Remove 'link:' prefix
		return None

class RequirementsDelegate(QStyledItemDelegate):
	# Constants
	MIN_TEXT_WIDTH = 200  # Minimum width for the text column
	INDENT_PER_LEVEL = 20  # Pixels per level of indentation
	_DOCUMENT_CSS = """
		table {
			border-collapse: collapse;
			margin: 6px 0;
		}
		th, td {
			border: 1px solid #999999;
			padding: 4px 8px;
		}
		th {
			background-color: #e8e8e8;
			font-weight: bold;
		}
	"""

	# Instance Variables
	indentTextByLevel = False  # Option to enable/disable indentation
	def __init__(self, parent=None):
		super(RequirementsDelegate, self).__init__(parent)
		self.doc = QTextDocument(self)
		self.doc.setDefaultStyleSheet(self._DOCUMENT_CSS)
		self.md = markdown.Markdown(extensions=EXTENSIONS)
		self._htmlCache = {}    # key: (uid, text_hash, width) -> html string
		self._currentCacheKey = None

	def _computeIndent(self, item, option):
		if not self.indentTextByLevel:
			return 0, option.rect.width()
		level_str = str(item.get('level'))
		try:
			level_depth = level_str.count('.')
			if level_str.endswith(".0"):
				level_depth -= 1
		except Exception:
			level_depth = 0
		indent = self.INDENT_PER_LEVEL * level_depth
		available_width = option.rect.width() - indent
		if available_width < self.MIN_TEXT_WIDTH:
			indent = max(0, option.rect.width() - self.MIN_TEXT_WIDTH)
			available_width = self.MIN_TEXT_WIDTH
		return indent, available_width

	def createEditor(self, parent, option, index):
		mdl = index.model()
		colName = mdl._headerData[index.column()]

		if colName == 'text':
			edit = QPlainTextEdit(parent)
			fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
			fixed_font.setStyleHint(QFont.TypeWriter)
			edit.setFont(fixed_font)
			edit.setStyleSheet("""
				QPlainTextEdit {
					color: black;
					background: white;
				}
			""")
			return edit

		item = mdl._data[index.row()][len(mdl._headerData)]
		value = item.get(colName)

		# Generic check instead of hardcoded column names: automatically
		# captures ALL boolean attributes (normative, derived, reviewed, potentially
		# future custom attributes), not just a fixed list.
		if isinstance(value, bool):
			edit = QComboBox(parent)
			edit.addItems(['True', 'False'])
			return edit

		if colName == 'level':
			# Level objects are not recognized by Qt's standard editor factory
			# (no registered editor for this Python type), therefore
			# explicitly force a simple QLineEdit.
			return QLineEdit(parent)

		return super(RequirementsDelegate, self).createEditor(parent, option, index)

	def updateEditorGeometry(self, editor, option, index):
		"""Ensure editor fills the cell properly to cover underlying text."""
		# Ensure combo boxes fill the entire cell rectangle
		if isinstance(editor, QComboBox):
			editor.setGeometry(option.rect)
		else:
			super(RequirementsDelegate, self).updateEditorGeometry(editor, option, index)

	def setEditorData(self, editor, index):
		colName = index.model()._headerData[index.column()]
		if colName == 'text':
			editor.insertPlainText(index.data())
		elif colName == 'level': # would create an empty QLineEdit otherwise
			editor.setText(index.data())
		elif isinstance(editor, QComboBox):
			# Set the current value for boolean combo boxes
			value = index.model().data(index, Qt.EditRole)
			if isinstance(value, bool):
				editor.setCurrentText('True' if value else 'False')
			else:
				editor.setCurrentText(str(value))
			return
		return super(RequirementsDelegate, self).setEditorData(editor, index)

	def setModelData(self, editor, model, index): # called after closing the editor
		# We need to extract a value. Possible editors: https://doc.qt.io/qtforpython/PySide2/QtWidgets/QItemEditorFactory.html

		if isinstance(editor, QComboBox):
			model.setData(index, editor.currentText())
		elif isinstance(editor, QPlainTextEdit):
			model.setData(index, editor.toPlainText())
		elif isinstance(editor, QLineEdit):
			model.setData(index, editor.text())
	def getDoc(self, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] != 'text':
			return
		item = mdl._data[index.row()][len(mdl._headerData)]
		width = option.rect.width()
		cache_key = (str(item.uid), hash(item.get('text')), width)

		if self._currentCacheKey == cache_key:
			return

		item_path = item.get('path')
		item_path = os.path.dirname(os.path.realpath(item_path))

		item_path = item.get('path')
		item_path = os.path.dirname(os.path.realpath(item_path))

		if cache_key in self._htmlCache:
			cached = self._htmlCache[cache_key]
		else:
			text = item.get('text')
			level = str(item.get('level'))
			header = str(item.get('header'))

			lines = [l for l in text.splitlines()]
			heading = ''
			if level.endswith('.0'):
				heading += '#'*level.count('.') + ' ' + level[:-2] + ' '
				if header.strip():
					heading += header.strip() + '\n\n'
					lines = [heading] + lines if len(lines) else [heading]
				else:
					if len(lines):
						heading += lines[0] + '\n\n'
						lines = [heading] + lines[1:]
					else:
						lines = [heading]
			else:
				if header.strip():
					heading += '#'*(level.count('.') +1) + ' ' + level + ' ' + header.strip()
					if item.get('normative'):
						heading += ' (' + str(item.uid) + ')'
				else:
					heading += '#'*(level.count('.') +1) + ' ' + level + ' ' + str(item.uid)
				lines = [heading] + lines
				text = '\n'.join(lines)

			cwd_bkp = os.getcwd()
			try:
				os.chdir(item_path)  # remains necessary because of PlantUML extension (cache dir etc.)
				html = self.md.convert(text)
				cached = ('html', html)
			except Exception as e:
				warning = '**An error occurred while displaying the content**\n\n: ' + str(e) + '\n\n'
				text = warning + text
				cached = ('md', text)
			finally:
				os.chdir(cwd_bkp)

			self._htmlCache[cache_key] = cached

		self._currentCacheKey = cache_key

		# IMPORTANT: Set base URL so that relative image paths are ALWAYS resolved
		# correctly - regardless of CWD, timing, cache hit/miss, or lazy loading by Qt.
		self.doc.setBaseUrl(QUrl.fromLocalFile(item_path + os.sep))

		kind, content = cached
		if kind == 'html':
			self.doc.setHtml(content)
		else:
			self.doc.setMarkdown(content)
		self.doc.setTextWidth(width)
	def paint(self, painter, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] == 'text':
			# get rich text document and paint it
			self.getDoc(option, index)
			# Calculate indentation based on level
			indent = 0
			available_width = option.rect.width()
			if self.indentTextByLevel:
				item = mdl._data[index.row()][len(mdl._headerData)]
				indent, available_width = self._computeIndent(item, option)
			ctx = QAbstractTextDocumentLayout.PaintContext()
			painter.save()
			painter.translate(option.rect.topLeft() + QPoint(indent, 0))
			painter.setClipRect(option.rect.translated(-option.rect.topLeft() - QPoint(indent, 0)))
			self.doc.setTextWidth(available_width)
			self.doc.documentLayout().draw(painter, ctx)
			painter.restore()
		else:
			super(RequirementsDelegate, self).paint(painter, option, index)

	def sizeHint(self, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] == 'text':
			self.getDoc(option, index)
			indent = 0
			available_width = option.rect.width()
			if self.indentTextByLevel:
				item = mdl._data[index.row()][len(mdl._headerData)]
				indent, available_width = self._computeIndent(item, option)
			self.doc.setTextWidth(available_width)
			return QSize(self.doc.idealWidth() + indent, self.doc.size().height())
		else:
			return QSize(0,0)
			#super(RequirementsDelegate, self).sizeHint(option, index)

class RequirementSetModel(QAbstractTableModel):
	# Standard columns that always appear at the front (fixed definition instead of magic numbers)
	_STANDARD_LEADING = ['uid', 'path', 'root', 'normative', 'derived', 'reviewed',
							'level', 'header', 'ref', 'references', 'links', 'childlinks']
	_READONLY_COLUMNS = {'links', 'childlinks', 'uid', 'path', 'root', 'ref', 'references'}
	_DISPLAY_NAMES = {
		'links': 'Parent Links',
		'childlinks': 'Child Links',
	}

	def __init__(self, docId=None, parent=None):
		super(RequirementSetModel, self).__init__(parent)
		self._docId = docId
		self.load()

	@Slot()
	def load(self):
		global reqtree
		self._document = reqtree.find_document(self._docId)

		# Requirements attributes
		# -----------------------
		#
		# Requirements attributes will be the column names in the table view.
		#
		# There are:
		#- standard attributes
		#- extended attributes (within single requirement)
		#- extended attributes with defaults (declared in document)
		#- extended attributes that concur to review timestamp (declared in document)
		#
		# Attribute names are the keys of items[x].data (doorstop 3.x public API)
		# We do a first loop to gather all user-defined attributes
		stdHeaderData = {'path', 'root', 'active', 'normative', 'uid', 'level',
							'header', 'text', 'derived', 'ref', 'references', 'reviewed', 'links'}

		headerSet = set()
		for item in iter_items(self._document):
			headerSet.update(item.data.keys())
		userHeaderData = headerSet - stdHeaderData
		if userHeaderData:
			log.debug('['+str(self._document)+'] Custom requirements attributes: ' + str(userHeaderData))

		self._headerData = self._STANDARD_LEADING + list(userHeaderData) + ['text']

		# Child links must be calculated once across the ENTIRE tree,
		# as children may also reside in other documents.
		childLinksIndex = build_child_links_index()

		self._data = []
		for item in iter_items(self._document):
			item_uid = str(item.uid).strip()
			row = []
			for f in self._headerData:
				if f == 'childlinks':
					row.append(','.join(childLinksIndex.get(item_uid, [])))
				else:
					row.append(str(item.get(f)))
			row.append(item)
			self._data.append(row)
		log.debug('['+str(self._document)+'] Requirements reloaded')
	# TableView methods that must be implemented
	def rowCount(self, index=QModelIndex()):
		return len(self._data)

	def columnCount(self, index=QModelIndex()):
		return len(self._headerData)

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid():
			return None

		item = self._data[index.row()][len(self._headerData)]
		colName = self._headerData[index.column()]

		if role == Qt.DisplayRole:
			if colName == 'childlinks':
				return self._data[index.row()][index.column()]
			return str(item.get(colName))

		if role == Qt.EditRole:
			if colName == 'childlinks':
				return self._data[index.row()][index.column()]
			return item.get(colName)

		if role == Qt.BackgroundRole:
			if not item.get('normative') or str(item.get('level')).endswith('.0'):
				# Use AlternateBase color from palette (adapts to light/dark mode)
				palette = QApplication.palette()
				return QBrush(palette.color(QPalette.AlternateBase))

		if role == Qt.ForegroundRole:
			if not item.get('normative') or str(item.get('level')).endswith('.0'):
				# Use disabled text color from palette (adapts to theme)
				palette = QApplication.palette()
				return QBrush(palette.color(QPalette.Disabled, QPalette.Text))

		if colName == 'links' and role == Qt.UserRole:
			return item.get(colName)
	def headerData(self, num, orientation, role=Qt.DisplayRole):
		if orientation == Qt.Horizontal:
			if role == Qt.DisplayRole:
				key = self._headerData[num]
				return self._DISPLAY_NAMES.get(key, key)
			if role == Qt.ForegroundRole:
				leading = len(self._STANDARD_LEADING)
				if leading <= num < len(self._headerData) - 1:
					return QBrush(QColor('blue'))

		if orientation == Qt.Vertical:
			item = self._data[num][len(self._headerData)]
			if role == Qt.DisplayRole:
				return str(item.get('uid'))
			if role == Qt.ForegroundRole:
				if not item.get('reviewed'):
					return QBrush(QColor('orange'))
				# non-normative items: use disabled text color from palette
				if not item.get('normative') or str(item.get('level')).endswith('.0'):
					palette = QApplication.palette()
					return QBrush(palette.color(QPalette.Disabled, QPalette.Text))
				# OK items: green
				return QBrush(QColor('darkGreen')) # OK items
			if role == Qt.ToolTipRole: #------------------------------------ TT
				tt = "Reviewed: " + str(item.get('reviewed')) + "\nDouble-click to copy requirement UID"
				return tt
		return QAbstractTableModel.headerData(self, num, orientation, role)

	def flags(self, index):
		colName = self._headerData[index.column()]
		base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
		if colName not in self._READONLY_COLUMNS:
			base |= Qt.ItemIsEditable
		return base

	def setData(self, index, text, role=Qt.EditRole):
		item = self._data[index.row()][len(self._headerData)]
		attr = self._headerData[index.column()]

		if type(item.get(attr)) == bool:
			text = (text == 'True')
		if type(item.get(attr)) == int:
			text = int(text)

		try:
			changed = str(item.get(attr)) != str(text)
		except Exception:
			changed = True

		if changed:
			try:
				item.set_attributes({attr: text})
				item.save()
				self._data[index.row()][index.column()] = item.get(attr)
				log.debug('Updated requirement [' + str(item.get('uid')) + '] attribute ['+attr+']')
				self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
			except doorstop.DoorstopError as e:
				log.error('Requirement [' + str(item.get('uid')) + '] file not saved - manual edit required: ' + str(e))
				self.layoutChanged.emit()
				return False
		self.layoutChanged.emit()
		return True

	def newReq(self, level=None):
		global reqtree
		if level is not None:
			item = reqtree.add_item(value=str(self._docId), level=level)
			log.debug("["+str(self._docId)+"] Added requirement " + str(item))
			# New items are created with auto=False; set() won't save until we save explicitly
			if item.get('level').heading: # make title items non-normative by default
				item.set('normative', False)
			item.set('derived', False) # set 'derived' property to False by default
			item.save()
			item.auto = True  # so future edits auto-save
			self.load()  # reload the whole document
			self.layoutChanged.emit()

	def delReq(self, row):
		global reqtree
		item = self._data[row][len(self._headerData)]
		reqid = str(item)
		# doorstop 3.x: delete() removes from document and deletes file
		item.delete()
		log.debug("["+str(self._docId)+"] Deleted requirement " + reqid)
		self.load() # reload the whole document
		self.layoutChanged.emit()

	def insertRowBefore(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			new_level = Level(item.get('level')) # just use the level of the clicked req
			self.newReq(new_level)

	def insertRowAfter(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			new_level = self._getSubsequentLevel(item.get('level'))
			self.newReq(new_level)

	def _getSubsequentLevel(self, level):
		new_level = Level(level) # create a new object, the '=' operator does a reference
		if new_level.heading:
			parts = str(new_level).split('.') # adding +1 to level doesn't work as expected when the level is a heading
			parts[-1] = 1 # x.x.x.0 --> x.x.x.1
			new_level = Level(parts)
		else:
			new_level += 1
		return new_level

	def _saveRowAndNotify(self, row):
		"""Emit dataChanged for a row so the view updates (e.g. row header color)."""
		if 0 <= row < len(self._data):
			top_left = self.index(row, 0)
			bot_right = self.index(row, len(self._headerData) - 1)
			self.dataChanged.emit(top_left, bot_right, [Qt.DisplayRole, Qt.BackgroundRole, Qt.ForegroundRole])

	def deactivateRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('normative', False)
			item.save()
			self._saveRowAndNotify(row)

	def activateRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('normative', True)
			item.save()
			self._saveRowAndNotify(row)

	def deriveRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('derived', True)
			item.save()
			self._saveRowAndNotify(row)

	def underiveRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('derived', False)
			item.save()
			self._saveRowAndNotify(row)

	def deleteRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			qm = QMessageBox()
			qm.setText(str("This will delete the requirement from disk.\nYou will not be able to recover it unless it's versioned.\n\nAre you absolutely sure?"))
			qm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
			ret = qm.exec()
			if ret == QMessageBox.Yes:
				self.delReq(row)

	def getItem(self, qidx):
		row = qidx.row()
		if row < len(self._data):
			return self._data[row][len(self._headerData)]
		else:
			return None

class RequirementManager(QWidget):
	'''
	Requirement document viewer with editor.
	The display format is a table.
	The model uses doorstop as source.

	Allows:
		- view requirement
		- edit requirement
		- add requirement
		- delete requirement
		- reload requirements

	Uses:
		- doorstop as backend
		- table view
	'''

	def __init__(self, docId=None, parent=None):
		super(RequirementManager, self).__init__(parent)
		self._docId = docId
		self._currentAnchorUid = None
		self._geometryInitialized = False
		self.load()

	def showEvent(self, event):
		super().showEvent(event)
		if not self._geometryInitialized:
			self._geometryInitialized = True
			# Now the widget is guaranteed to have real geometry
			self.view.resizeColumnsToContents()
			self.view.resizeRowsToContents()
	def load(self):
		self.loadModel() # fills in the table
		self.loadDelegate() # delegate is necessary to edit the "text" field
		self.loadView() # table view

	def loadModel(self):
		self.model = RequirementSetModel(self._docId)

	def loadDelegate(self):
		self.delegate = RequirementsDelegate()
		self.linksDelegate = LinksDelegate()

	def loadView(self):
		# Table
		self.view = QTableView()
		self.view.setModel(self.model)
		self.view.selectionModel().currentChanged.connect(self._onCurrentChanged)
		self.view.setItemDelegate(self.delegate)
		# Set custom delegate for links column
		linksCol = self.model._headerData.index('links')
		childLinksCol = self.model._headerData.index('childlinks')
		self.view.setItemDelegateForColumn(linksCol, self.linksDelegate)
		self.view.setItemDelegateForColumn(childLinksCol, self.linksDelegate)
		# Connect link click handler
		self.view.clicked.connect(self.onLinkClicked)
		self.view.setContextMenuPolicy(Qt.CustomContextMenu)
		self.view.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

		# Table appearance
		self.view.hideColumn(self.model._headerData.index('path'))
		self.view.hideColumn(self.model._headerData.index('root'))
		self.view.hideColumn(self.model._headerData.index('uid'))
		self.view.hideColumn(self.model._headerData.index('ref'))
		self.view.hideColumn(self.model._headerData.index('references'))

		self.view.horizontalHeader().setStretchLastSection(True)
		self.view.setWordWrap(True)
		self.view.resizeColumnsToContents()
		# Set wider default widths for level and header columns
		try:
			levelCol = self.model._headerData.index('level')
			headerCol = self.model._headerData.index('header')
			self.view.setColumnWidth(levelCol, 100)  # Fits ~9 characters for level numbers like "1.2.3"
			self.view.setColumnWidth(headerCol, 170)  # Fits ~16 characters for header text
		except ValueError:
			# Columns might not exist, ignore
			pass
		self.view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
		self.view.verticalHeader().sectionDoubleClicked.connect(self.onRowHeaderDoubleClicked)
		self.view.setSelectionMode(QAbstractItemView.SingleSelection)
		self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
		self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel) # only has effect on the scrollbar dragging
		self.view.verticalScrollBar().setSingleStep(15) # mouse wheel scrolling: restricted to 15px per "click"

		# Indentation toggle
		self.indentToggle = QCheckBox("Indent text column by level")
		self.indentToggle.setChecked(self.delegate.indentTextByLevel)
		self.indentToggle.setToolTip("Toggle indentation of the text column based on requirement level.")
		self.indentToggle.stateChanged.connect(self.onIndentToggleChanged)

		# Buttons
		reloadBtn = QPushButton("Reload")
		reloadBtn.clicked.connect(self.onReloadClicked)
		addBtn = QPushButton("Add")
		addBtn.clicked.connect(self.onAddClicked)
		addBtn.setToolTip("Add a new requirement after the selected item, or at the end if none selected")
		removeBtn = QPushButton("Remove")
		removeBtn.clicked.connect(self.onDeleteClicked)
		removeBtn.setToolTip("Remove the selected requirement")
		# Store button references for enabling/disabling
		self.deleteBtn = removeBtn
		# Connect selection changes to enable/disable remove button
		self.view.selectionModel().selectionChanged.connect(self.onSelectionChanged)
		self.onSelectionChanged()  # Initial state

		# Spacer
		spacer = QSpacerItem(10, 30)

		# Placement
		ly = QVBoxLayout()
		lyBtns = QHBoxLayout()
		lyBtns.addWidget(reloadBtn)
		lyBtns.addWidget(addBtn)
		lyBtns.addWidget(removeBtn)
		lyBtns.addSpacerItem(spacer)
		lyBtns.addWidget(self.indentToggle)
		lyBtns.addStretch()
		ly.addLayout(lyBtns)
		ly.addWidget(self.view)
		self.setLayout(ly)

	def onIndentToggleChanged(self, state):
		self.delegate.indentTextByLevel = bool(state)
		self.view.viewport().update()

	def onAddClicked(self):
		"""Handle Add button click - adds a new requirement after the selected item, or at the end."""
		idx = self.view.currentIndex()
		if idx.isValid() and idx.row() < len(self.model._data):
			# Add after selected item
			self.model.insertRowAfter(idx)
		else:
			# No selection or invalid - add at the end
			# Find the last item's level and add after it
			if len(self.model._data) > 0:
				last_row = len(self.model._data) - 1
				last_idx = self.model.index(last_row, 0)
				self.model.insertRowAfter(last_idx)
			else:
				# Empty document - create first requirement at level 1
				self.model.newReq(Level([1]))
	def onDeleteClicked(self):
		"""Handle Delete button click - deletes the selected requirement."""
		idx = self.view.currentIndex()
		if idx.isValid():
			self.model.deleteRow(idx)
	def onSelectionChanged(self):
		"""Enable/disable delete button based on selection."""
		idx = self.view.currentIndex()
		self.deleteBtn.setEnabled(idx.isValid() and idx.row() < len(self.model._data))
	def onRowHeaderDoubleClicked(self, logicalIndex):
		"""Handle double-click on row header to copy requirement UID to clipboard."""
		if 0 <= logicalIndex < len(self.model._data):
			item = self.model._data[logicalIndex][len(self.model._headerData)]
			uid = str(item.get('uid'))
			# Copy to clipboard
			clipboard = QApplication.clipboard()
			clipboard.setText(uid)
			# Show brief feedback message
			QMessageBox.information(self, "Copied",
				f"Requirement UID copied to clipboard:\n{uid}")

	def _buildCreateChildMenu(self, parentMenu, idx, docPrefix):
		"""Recursively populate parentMenu with the document hierarchy
		rooted at the children of docPrefix, so only actual descendant
		documents can be picked as a target for a linked child."""
		global reqtree
		childDocuments = sorted(
			(d for d in reqtree if d.parent == docPrefix),
			key=lambda d: d.prefix
		)
		for childDoc in childDocuments:
			grandChildren = [d for d in reqtree if d.parent == childDoc.prefix]
			if grandChildren:
				subMenu = parentMenu.addMenu(childDoc.prefix)
				createHereAction = QAction(f'Create in {childDoc.prefix}', subMenu)
				createHereAction.triggered.connect(
					lambda checked=False, target_prefix=childDoc.prefix: self.onCreateLinkedChild(idx, target_prefix)
				)
				subMenu.addAction(createHereAction)
				subMenu.addSeparator()
				self._buildCreateChildMenu(subMenu, idx, childDoc.prefix)
			else:
				docAction = QAction(childDoc.prefix, parentMenu)
				docAction.triggered.connect(
					lambda checked=False, target_prefix=childDoc.prefix: self.onCreateLinkedChild(idx, target_prefix)
				)
				parentMenu.addAction(docAction)

	def onCustomContextMenuRequested(self, pos):
		global reqtree
		idx = self.view.indexAt(pos)
		item = self.model.getItem(idx)
		if item is None:
			return

		menu = QMenu()
		addReqBefore = QAction('Add new requirement before '+str(item))
		addReqBefore.triggered.connect(lambda: self.model.insertRowBefore(idx))
		menu.addAction(addReqBefore)

		addReqAfter = QAction('Add new requirement after '+str(item))
		addReqAfter.triggered.connect(lambda: self.model.insertRowAfter(idx))
		menu.addAction(addReqAfter)
		menu.addSeparator()

		if item.get('level').heading == False:
			if item.get('normative'):
				deactivateReq = QAction('Make '+str(item)+' not normative')
				deactivateReq.triggered.connect(lambda: self.model.deactivateRow(idx))
				deactivateReq.setToolTip("Changes the 'normative' attribute to False.\nNon-normative requirements are informative or are not valid on this specific project.")
				menu.addAction(deactivateReq)
			else:
				activateReq = QAction('Make '+str(item)+' normative')
				activateReq.triggered.connect(lambda: self.model.activateRow(idx))
				activateReq.setToolTip("Changes the 'normative' attribute to True.\nNormative requirements must be implemented.")
				menu.addAction(activateReq)

		if item.get('normative'):
			if item.get('derived'):
				setNotDerived = QAction('Make '+str(item)+' not derived')
				setNotDerived.setToolTip("Changes the 'derived' attribute to False.\nNot derived requirements must have a parent requirement unless they're the top-level requirements.")
				setNotDerived.triggered.connect(lambda: self.model.underiveRow(idx))
				menu.addAction(setNotDerived)
			else:
				setDerived = QAction('Make '+str(item)+' derived')
				setDerived.setToolTip("Changes the 'derived' attribute to True.\nDerived requirements don't need to have a parent requirement even if they're not top-level requirements.")
				setDerived.triggered.connect(lambda: self.model.deriveRow(idx))
				menu.addAction(setDerived)

		menu.addSeparator()
		childDocuments = [d for d in reqtree if d.parent == self._docId]
		if childDocuments:
			createChildMenu = menu.addMenu('Create linked child in')
			self._buildCreateChildMenu(createChildMenu, idx, self._docId)

		menu.addSeparator()
		deleteReq = QAction('Delete '+str(item)+' from disk')
		deleteReq.triggered.connect(lambda: self.model.deleteRow(idx))
		menu.addAction(deleteReq)

		menu.exec(self.view.mapToGlobal(pos))

	def onCreateLinkedChild(self, qidx, target_prefix):
		"""Create a new item in the target document, reusing the parent's
		number (with a letter suffix if that number is already taken in the
		target document) and copying the parent's level. Links the new item
		to the parent."""
		global reqtree

		parent_item = self.model.getItem(qidx)
		if parent_item is None:
			return

		target_document = reqtree.find_document(target_prefix)
		if target_document is None:
			QMessageBox.critical(self, "Error", f"Document '{target_prefix}' not found.")
			return

		source_document = self.model._document
		parent_prefix = str(source_document.prefix)
		parent_sep = getattr(source_document, 'sep', '')
		parent_uid_str = str(parent_item.uid)

		prefix_and_sep = parent_prefix + parent_sep
		if parent_uid_str.startswith(prefix_and_sep):
			number_part = parent_uid_str[len(prefix_and_sep):]
		else:
			number_part = parent_uid_str[len(parent_prefix):]

		parent_level = Level(parent_item.get('level'))

		new_item = None
		suffix_index = 0
		while new_item is None:
			suffix = '' if suffix_index == 0 else chr(ord('a') + suffix_index - 1)
			candidate_name = number_part + suffix
			try:
				new_item = target_document.add_item(
					level=parent_level,
					name=candidate_name,
					reorder=False,
				)
			except doorstop.DoorstopError:
				suffix_index += 1
				if suffix_index > 26:
					QMessageBox.critical(self, "Error",
						"Could not find a free UID after 26 suffix attempts.")
					return

		if parent_level.heading:
			new_item.set('normative', False)
		new_item.set('derived', False)
		new_item.link(str(parent_item.uid))
		new_item.save()

		log.debug(f"Created linked child '{new_item.uid}' in '{target_prefix}', "
				f"linked to parent '{parent_item.uid}'")

		main_window = self.parent()
		while main_window and not isinstance(main_window, MainWindow):
			main_window = main_window.parent()
		if not main_window:
			return

		target_req_manager = None
		source_req_manager = None
		for req_manager in main_window._requirementManagers:
			if req_manager._docId == target_prefix:
				target_req_manager = req_manager
			if req_manager._docId == self._docId:
				source_req_manager = req_manager

		for req_manager in (target_req_manager, source_req_manager):
			if req_manager is None:
				continue
			req_manager.model.beginResetModel()
			req_manager.model.load()
			req_manager.model.endResetModel()
			req_manager.delegate._htmlCache.clear()
			req_manager.delegate._currentCacheKey = None

		if target_req_manager is None:
			return

		# Activate the outer tab containing the target document
		for i in range(main_window.tabs.count()):
			tab_widget = main_window.tabs.widget(i)
			if tab_widget.findChild(RequirementManager) is target_req_manager:
				main_window.tabs.setCurrentIndex(i)
				break

		# Find the row of the newly created item
		new_uid = str(new_item.uid).strip()
		target_model = target_req_manager.model
		row = 0
		for r in range(target_model.rowCount(QModelIndex())):
			row_item = target_model._data[r][len(target_model._headerData)]
			if str(row_item.uid).strip() == new_uid:
				row = r
				break

		text_col = target_model._headerData.index('text')
		target_req_manager._scrollToRow(target_model, target_req_manager.view, row, edit_column=text_col)

	def onLinkClicked(self, index):
		colName = self.model._headerData[index.column()]
		if colName not in ('links', 'childlinks'):
			return
		pos = self.view.viewport().mapFromGlobal(QCursor.pos())
		linkPos = self.view.visualRect(index).topLeft()
		relativePos = pos - linkPos
		delegate = self.view.itemDelegateForColumn(index.column())
		if delegate and hasattr(delegate, 'getLinkAtPos'):
			uid = delegate.getLinkAtPos(relativePos)
			if uid:
				self.navigateToRequirement(uid)

	def onReloadClicked(self):
		main_window = self.parent()
		while main_window and not isinstance(main_window, MainWindow):
			main_window = main_window.parent()
		if main_window:
			main_window.reloadAll()

	def navigateToRequirement(self, uid):
		"""Navigate to the tab and row containing the given UID."""
		global reqtree
		uid = uid.strip().rstrip(',')
		main_window = self.parent()
		while main_window and not isinstance(main_window, MainWindow):
			main_window = main_window.parent()
		if not main_window:
			QMessageBox.critical(self, "Error", "Could not find main window.")
			return

		for document in reqtree:
			for item in iter_items(document):
				if str(item.uid).strip() != uid:
					continue
				for i in range(main_window.tabs.count()):
					tab_widget = main_window.tabs.widget(i)
					req_manager = tab_widget.findChild(RequirementManager)
					if not req_manager or req_manager._docId != document.prefix:
						continue
					model = req_manager.model
					view = req_manager.view
					for row in range(model.rowCount(QModelIndex())):
						row_item = model._data[row][len(model._headerData)]
						if str(row_item.uid).strip() != uid:
							continue
						log.debug(f"Navigating to {uid}: tab {i}, row {row}")
						main_window.tabs.setCurrentIndex(i)
						self._scrollToRow(model, view, row)
						return
		log.error(f"UID '{uid}' not found in requirements tree")
		QMessageBox.information(self, "Link Not Found",
							 f"Requirement '{uid}' was not found in the requirements tree.")

	def _firstVisibleColumn(self, view, model):
		for c in range(model.columnCount(QModelIndex())):
			if not view.isColumnHidden(c):
				return c
		return 0

	def _doScroll(self):
		if not hasattr(self, '_scrollRow'):
			return
		row = self._scrollRow
		model = self._scrollModel
		view = self._scrollView
		edit_column = getattr(self, '_scrollEditColumn', None)

		col = self._firstVisibleColumn(view, model)
		idx = model.index(row, col)
		rect = view.visualRect(idx)

		if (not rect.isValid() or rect.height() == 0) and self._scrollAttempts < 20:
			self._scrollAttempts += 1
			QTimer.singleShot(10, self._doScroll)
			return

		del self._scrollRow, self._scrollModel, self._scrollView, self._scrollAttempts

		view.scrollTo(idx, QAbstractItemView.PositionAtCenter)
		view.setCurrentIndex(idx)
		view.selectRow(row)
		if view.isVisible():
			view.setFocus()
		log.debug(f"Scrolled to row {row}")

		if edit_column is not None:
			edit_idx = model.index(row, edit_column)
			view.edit(edit_idx)

	def _captureAnchorUid(self):
		"""Returns the last known anchor UID. Only falls back to the top visible row
		on the very first call (if nothing has been selected yet)."""
		if self._currentAnchorUid is not None:
			return self._currentAnchorUid

		if self.model.rowCount(QModelIndex()) == 0:
			return None
		idx = self.view.indexAt(self.view.viewport().rect().topLeft())
		if not idx.isValid():
			return None
		item = self.model.getItem(idx)
		return str(item.uid).strip() if item is not None else None

	def _restoreAnchorUid(self, uid):
		"""Scrolls to the row with the given UID, or to the beginning if it is no longer present."""
		row = 0
		if uid is not None:
			for r in range(self.model.rowCount(QModelIndex())):
				row_item = self.model._data[r][len(self.model._headerData)]
				if str(row_item.uid).strip() == uid:
					row = r
					break
		self._scrollToRow(self.model, self.view, row)

	def _scrollToRow(self, model, view, row, edit_column=None):
		if row is None or row < 0:
			row = 0
		self._scrollRow = row
		self._scrollModel = model
		self._scrollView = view
		self._scrollAttempts = 0
		self._scrollEditColumn = edit_column
		QTimer.singleShot(0, self._doScroll)

	def _onCurrentChanged(self, current, previous):
		"""Tracks the anchor UID continuously. Ignores invalid indices
		(e.g. those caused by beginResetModel/endResetModel), so the
		last known good anchor survives a reset."""
		item = self.model.getItem(current)
		if item is not None:
			self._currentAnchorUid = str(item.uid).strip()
		# Deliberately do NOT overwrite when current is invalid (due to reset)

# Main application
class MainWindow(QMainWindow):
	def __init__(self, parent=None):
		super(MainWindow, self).__init__(parent)
		self.setWindowTitle('Doorhole - doorstop requirements editor')

		global reqtree
		reqtree = doorstop.build()

		self.tabs = QTabWidget()
		self.setCentralWidget(self.tabs)

		self._requirementManagers = []

		for document in reqtree:
			container = QTabWidget()
			reqsW = QWidget()
			reqsView = RequirementManager(document.prefix)
			self._requirementManagers.append(reqsView)

			reqsLy = QVBoxLayout()
			reqsLy.addWidget(reqsView)
			reqsW.setLayout(reqsLy)
			container.addTab(reqsW, 'Requirements')

			title = document.parent + ' -> ' + document.prefix if document.parent else document.prefix
			self.tabs.addTab(container, title)

	def reloadAll(self):
		"""Rebuild the entire requirements tree from disk and refresh every
		open tab, preserving each tab's scroll position if the anchor
		requirement still exists there."""
		global reqtree

		anchors = {}
		for req_manager in self._requirementManagers:
			anchors[req_manager] = req_manager._captureAnchorUid()

		log.info("Rebuilding requirements tree from disk...")
		reqtree = doorstop.build()

		for req_manager in self._requirementManagers:
			req_manager.model.beginResetModel()
			req_manager.model.load()
			req_manager.model.endResetModel()

			req_manager.delegate._htmlCache.clear()
			req_manager.delegate._currentCacheKey = None

			# Only resize if the tab has already had real geometry.
			# For tabs that have never been shown, showEvent() will handle this correctly later.
			if req_manager._geometryInitialized:
				req_manager.view.resizeColumnsToContents()
				req_manager.view.resizeRowsToContents()

			req_manager._restoreAnchorUid(anchors[req_manager])

		log.info("Reload complete.")

def start_app():
	app = QApplication(sys.argv)
	win = MainWindow()
	win.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	start_app()