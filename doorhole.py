#!/usr/bin/env python

# Checks functional requirements with regexes
# Builds functional matrix

import doorstop
from doorstop.core.types import iter_documents, iter_items, Level
import os
import sys
from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWebEngineWidgets import *
import logging
import markdown
from plantuml_markdown import PlantUMLMarkdownExtension
import tempfile
import copy

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
logger = logging.getLogger
log = logger(__name__)


# requirements tree is a global because it's shared by all classes.
# Maybe it should become a singleton.
reqtree = None

class RequirementsDelegate(QStyledItemDelegate):
	def __init__(self, parent=None):
		super(RequirementsDelegate, self).__init__(parent)
		self.doc = QTextDocument(self)
		self.docIndex = None
		self.h = None
		self.w = None
		self.md = markdown.Markdown(extensions=EXTENSIONS)

	def createEditor(self, parent, option, index):
		if index.model()._headerData[index.column()] == 'text':
			edit = QPlainTextEdit(parent)
			fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
			fixed_font.setStyleHint(QFont.TypeWriter)
			edit.setFont(fixed_font)
			return edit
		return super(RequirementsDelegate, self).createEditor(parent, option, index) # editor chosen with the QtEditRole in model.data()

	def setEditorData(self, editor, index):
		if index.model()._headerData[index.column()] == 'text': 
			editor.insertPlainText(index.data())
		if index.model()._headerData[index.column()] == 'level': # would create an empty QLineEdit otherwise
			editor.setText(index.data())
		return super(RequirementsDelegate, self).setEditorData(editor, index)

	def setModelData(self, editor, model, index): # called after closing the editor
		# We need to extract a value. Possible editors: https://doc.qt.io/qtforpython/PySide2/QtWidgets/QItemEditorFactory.html
		
		# There ought to be be a better way.
		editorType = str(type(editor))
		if 'QComboBox' in editorType:
			model.setData(index, editor.currentText())
		elif 'QLineEdit' in editorType:
			model.setData(index, editor.text())
		elif 'QPlainTextEdit' in editorType:
			model.setData(index, editor.toPlainText())
	
	def getDoc(self, option, index): # builds the doc inside self.doc, uses self.index as cache
		if self.docIndex == index: # Doc already done
			return
		
		# a new doc is to be rendered
		self.docIndex = index
		mdl = index.model()
		if mdl._headerData[index.column()] == 'text':
			item = mdl._data[index.row()][len(mdl._headerData)] # DS item cached in last column
			text = item.get('text')
			level = str(item.get('level'))
			header = str(item.get('header'))
			item_path = item.get('path') # doorstop property 'root' from DS item
			item_path = os.path.dirname(os.path.realpath(item_path))
			
			# mimick DS title and header attributes
			lines = [l for l in text.splitlines()]
			heading = ''
			if level.endswith('.0'): # Chapter title
				heading += '#'*level.count('.') + ' ' + level[:-2] + ' '
				if header.strip(): # use header as heading
					heading += header.strip() + '\n\n'
					if (len(lines)): # append text, if any
						lines = [heading] + lines
					else:
						lines = [heading]
				else: # use first line as heading
					if len(lines): # ...if any!
						heading += lines[0] + '\n\n'
						lines = [heading] + lines[1:]
					else:
						lines = [heading]
			else: # Requirement
				if header.strip(): # use header as heading
					heading += '#'*(level.count('.') +1) + ' ' + level + ' ' + header.strip()
					if item.normative:
						heading += ' (' + str(item.uid) + ')'
				else: # use UID as heading
					heading += '#'*(level.count('.') +1) + ' ' + level + ' ' + str(item.uid)
				lines = [heading] + lines
			text = '\n'.join(lines)

			# change work dir to where the reqs are stored, otherwise images will not be rendered
			cwd_bkp = os.getcwd()
			try:
				os.path.dirname(os.path.realpath(__file__))
				os.chdir(item_path) # necessary to solve linked items with relative paths (e.g. images)
				html = self.md.convert(text)
				self.doc.setHtml(html)
			except Exception as e:
				warning = '**An error occurred while displaying the content**\n\n: '+ str(e) + '\n\n'
				text = warning + text
				self.doc.setMarkdown(text)
			os.chdir(cwd_bkp)
			
			# Document should be restricted to column width
			options = QStyleOptionViewItem(option)
			self.doc.setTextWidth(options.rect.width())

	def paint(self, painter, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] == 'text':
			# get rich text document and paint it
			self.getDoc(option, index)
			ctx = QAbstractTextDocumentLayout.PaintContext()
			painter.save()
			painter.translate(option.rect.topLeft());
			painter.setClipRect(option.rect.translated(-option.rect.topLeft()))
			self.doc.documentLayout().draw(painter, ctx)
			painter.restore()
		else:
			super(RequirementsDelegate, self).paint(painter, option, index)

	def sizeHint(self, option, index):
		mdl = index.model()
		if mdl._headerData[index.column()] == 'text':
			# get rich text document and size it
			self.getDoc(option, index)
			#log.debug(mdl._headerData[index.column()] + "\t W: " + str(self.doc.idealWidth()) + " H: " +  str(self.doc.size().height()))
			return QSize(self.doc.idealWidth(), self.doc.size().height())
		else:
			return QSize(0,0)
			#super(RequirementsDelegate, self).sizeHint(option, index)

class RequirementSetModel(QAbstractTableModel):
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
		#  - standard attributes
		#  - extended attributes (within single requirement)
		#  - extended attributes with defaults (declared in document)
		#  - extended attributes that concur to review timestamp (declared in document)
		#
		# Attribute names are the keys of items[x]._data
		# We do a first loop to gather all user-defined attributes
		
		# Standard data (pulled from doorstop.item inspection)
		stdHeaderData = {'path', 'root', 'active', 'normative', 'uid', 'level', 'header', 'text', 'derived', 'ref', 'references', 'reviewed', 'links'}
		
		headerData =  []
		for item in iter_items(self._document):
			headerData += list(item._data.keys())
			headerData = list(set(headerData)) # drop duplicates
		
		# Non-standard data that we will display in more columns:
		userHeaderData = set(headerData) - stdHeaderData
		if userHeaderData:
			log.debug('['+str(self._document)+'] Custom requirements attributes: ' + str(userHeaderData))
		
		# And we have now the column names.
		# We put 'text' always to the last column because it usually is stretched.
		# The 'active' field is always true - inactive requirements are not shown at all. Doorstop doesn't tell us about them.
		self._headerData = ['uid', 'path', 'root', 'normative', 'derived', 'reviewed', 'level', 'header', 'ref', 'references', 'links'] + list(userHeaderData) + ['text']
		
		# Another loop to fill in the table rows
		self._data = []
		for item in iter_items(self._document):
			row = []
			for f in self._headerData:
				row.append(str(item.get(f)))
			row.append(item) # Doorstop item reference cached in the last row
			self._data.append(row)
		log.debug('['+str(self._document)+'] Requirements reloaded')

	# TableView methods that must be implemented
	def rowCount(self, index):
		return len(self._data)
	
	def columnCount(self, index):
		return len(self._headerData)

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid():
			return None
			
		item = self._data[index.row()][len(self._headerData)]
		colName = self._headerData[index.column()]
		
		if role == Qt.DisplayRole: #------------------------------------- Value
			return str(item.get(colName))
		
		if role == Qt.EditRole:
			return item.get(colName)

		if role == Qt.BackgroundRole: #------------------------------------- BG
			if not item.get('normative') or str(item.get('level')).endswith('.0'):
				return QBrush(QColor('lightGray'))
		
		if role == Qt.ForegroundRole: #------------------------------------- FG
			if not item.get('normative') or str(item.get('level')).endswith('.0'):
				return QBrush(QColor('gray'))
			
	def headerData(self, num, orientation, role=Qt.DisplayRole):
	
		if orientation == Qt.Horizontal: # ---------------------- Column header
			if role == Qt.DisplayRole: #--------------------------------- Value
				return self._headerData[num]
			if role == Qt.ForegroundRole: # -------------------------------- FG
				# custom attributes: blue
				if num > 10 and num < len(self._headerData) - 1:
					return QBrush(QColor('blue'))
					
		if orientation == Qt.Vertical: #---------------------------- Row header
			item = self._data[num][len(self._headerData)]
			if role == Qt.DisplayRole: #--------------------------------- Value
				return str(item.get('uid'))
			if role == Qt.ForegroundRole: #--------------------------------- FG
				# wrong items: red (TODO)
				# unreviewed items: orange
				if not item.get('reviewed'): 
					return QBrush(QColor('orange'))
				# non-normative items: gray
				if not item.get('normative') or str(item.get('level')).endswith('.0'): # non-normative items: dark gray
					return QBrush(QColor('gray'))
				# OK items: green
				return QBrush(QColor('darkGreen')) # OK items
			if role == Qt.ToolTipRole: #------------------------------------ TT
				tt = "Reviewed: " + str(item.get('reviewed'))
				return tt
		return QAbstractTableModel.headerData(self, num, orientation, role)
		
	def flags(self, index):
			return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable

	def setData(self, index, text):
		item = self._data[index.row()][len(self._headerData)]
		attr = self._headerData[index.column()]
		
		# Boolean values are passed as "True" or "False" strings, so we need to determine whether the original datatype was boolean.
		if type(item.get(attr)) == bool:
			if text == 'True':
				text = True
			else:
				text = False
		
		# Integer values are passed as strings, so we need to convert back to integer
		if type(item.get(attr)) == int:
			text = int(text)
		
		# Strings are left as they are
		if item.get(attr) != text:
			try:
				attributes = { attr : text }
				item.set_attributes(attributes)
				item.save()
				self._data[index.row()][index.column()] = item.get(attr)
				log.debug('Updated requirement [' + str(item.get('uid')) + '] attribute ['+attr+']')
			except doorstop.DoorstopError:
				log.error('Requirement [' + str(item.get('uid')) + '] file not saved - manual edit required: ' + path)
		self.layoutChanged.emit()
	
	def newReq(self, level=None):
		global reqtree
		if level is not None:
			item = reqtree.add_item(value=str(self._docId), level=level)
			log.debug("["+str(self._docId)+"] Added requirement " + str(item))
			if item.get('level').heading: # make title items non-normative by default
				item.set('normative', False)
			item.set('derived', False) # set 'derived' property to False by default
			self.load() # reload the whole document
			self.layoutChanged.emit()
	
	def delReq(self, row):
		global reqtree
		item = self._data[row][len(self._headerData)]
		reqid = str(item)
		item.delete() # doorstop item deletion
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
		
	def deactivateRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('normative', False)
	
	def activateRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('normative', True)

	def deriveRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('derived', True)
	
	def underiveRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			item = self._data[row][len(self._headerData)]
			item.set('derived', False)

	def deleteRow(self, qidx):
		row = qidx.row()
		if row < len(self._data): # clicked requirement actually exists
			qm = QMessageBox()
			qm.setText(str("This will delete the requirement from disk.\nYou will not be able to recover it unless it's versioned.\n\nAre you absolutely sure?"))
			qm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
			ret = qm.exec()
			if ret == qm.Yes:
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
		self.load()

	def load(self):
		self.loadModel() # fills in the table
		self.loadDelegate() # delegate is necessary to edit the "text" field
		self.loadView() # table view

	def loadModel(self):
		self.model = RequirementSetModel(self._docId)

	def loadDelegate(self):
		self.delegate = RequirementsDelegate()

	def loadView(self):
		# Table
		self.view = QTableView()
		self.view.setModel(self.model)
		self.view.setItemDelegate(self.delegate)
		self.view.setContextMenuPolicy(Qt.CustomContextMenu)
		self.view.customContextMenuRequested.connect(self.onCustomContextMenuRequested)
		
		# Table appearance
		self.view.setMinimumSize(1024, 768)
		self.view.hideColumn(self.model._headerData.index('path'))
		self.view.hideColumn(self.model._headerData.index('root'))
		self.view.hideColumn(self.model._headerData.index('uid'))
		self.view.hideColumn(self.model._headerData.index('ref'))
		self.view.hideColumn(self.model._headerData.index('references'))
		self.view.hideColumn(self.model._headerData.index('links'))
		
		self.view.horizontalHeader().setStretchLastSection(True)
		self.view.setWordWrap(True)
		self.view.resizeColumnsToContents()
		self.view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
		self.view.setSelectionMode(QAbstractItemView.SingleSelection)
		self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
		self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel) # only has effect on the scrollbar dragging
		self.view.verticalScrollBar().setSingleStep(15) # mouse wheel scrolling: restricted to 15px per "click"

		# Buttons
		reloadBtn = QPushButton("Reload")
		reloadBtn.clicked.connect(self.model.load)
		# Placement

		ly = QVBoxLayout()
		lyBtns = QHBoxLayout()
		lyBtns.addWidget(reloadBtn)
		lyBtns.addStretch()
		ly.addLayout(lyBtns)
		ly.addWidget(self.view)
		self.setLayout(ly)

	def onCustomContextMenuRequested(self, pos):
		menu = QMenu()
		idx = self.view.indexAt(pos)
		item = self.model.getItem(idx)
		if item is not None:
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
		deleteReq = QAction('Delete '+str(item)+' from disk')
		deleteReq.triggered.connect(lambda: self.model.deleteRow(idx))
		menu.addAction(deleteReq)

		menu.exec_(self.view.mapToGlobal(pos))

# Main application
class MainWindow(QMainWindow):
	def __init__(self, parent=None):
		super(MainWindow, self).__init__(parent)
		self.setWindowTitle('Doorhole - doorstop requirements editor')

		global reqtree
		reqtree = doorstop.build()

		self.tabs = QTabWidget()
		self.setCentralWidget(self.tabs)

		# One tab for each document
		for document in reqtree:
			# container widget
			container = QTabWidget()

			# widgets
			reqsW = QWidget()
			reqsView = RequirementManager(document.prefix)

			reqsLy = QVBoxLayout()
			reqsLy.addWidget(reqsView)
			reqsW.setLayout(reqsLy)

			container.addTab(reqsW, 'Requirements')

			title = document.parent + ' -> ' + document.prefix if document.parent else document.prefix
			self.tabs.addTab(container, title)

if __name__ == "__main__":
	app = QApplication(sys.argv)
	win = MainWindow()
	win.show()
	sys.exit(app.exec_())
