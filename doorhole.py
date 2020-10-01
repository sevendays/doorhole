#!/usr/bin/env python

# Checks functional requirements with regexes
# Builds functional matrix

import doorstop
from doorstop.core.types import iter_documents, iter_items
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
import pandas as pd

EXTENSIONS = (
    'markdown.extensions.extra',
    'markdown.extensions.sane_lists',
    'mdx_outline',
    'mdx_math',
    PlantUMLMarkdownExtension(
        server='',#'http://www.plantuml.com/plantuml',
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
		#self.plantumlService = plantuml.PlantUML()
		self.h = None
		self.w = None

	def createEditor(self, parent, option, index):
		if index.column() == 8: #'text'
			edit = QPlainTextEdit(parent)
			fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
			fixed_font.setStyleHint(QFont.TypeWriter)
			edit.setFont(fixed_font)
			return edit
		return QStyledItemDelegate.createEditor(self, parent, option, index)

	def setEditorData(self, editor, index):
		if index.column() == 8: #'text'
			editor.insertPlainText(index.data())

	def setModelData(self, editor, model, index):
		if index.column() == 8: #'text'
			model.setData(index, editor.toPlainText())

	def paint(self, painter, option, index):
		if index.column() == 8: #'text'
			text = index.model().data(index) #default role is display
			palette = QApplication.palette()

			active = index.model()._data[index.row()][2]
			normative = index.model()._data[index.row()][3]
			uid = index.model()._data[index.row()][4]
			asil = index.model()._data[index.row()][5]
			level = index.model()._data[index.row()][6]
			header = index.model()._data[index.row()][7]

			if level.endswith('.0'): # first line will be bold
				lines = [l for l in text.splitlines()]
				heading = '#'*level.count('.') + ' ' + level[:-2]
				if header.strip():
					heading += ' ' + header.strip() + '\n\n'
					lines = [heading] + lines
				else:
					heading += ' ' + lines[0].replace('**','') + '\n\n'
					lines[0] = heading
				text = '\n'.join(lines)

			#self.doc.setMarkdown(text) // will not render images
			try:
				html = markdown.markdown(text, extensions=EXTENSIONS)
				self.doc.setHtml(html)
			except:
				warning = '!! **An error occurred while displaying the content**\n\n'
				text = warning + text
				self.doc.setMarkdown(text) # will not render images
			size = super(RequirementsDelegate, self).sizeHint(option, index);
			#log.debug('-------------oh: ' + str(size.height()))
			#log.debug('-------------ow: ' + str(size.width()))
			if size.width() < 400:
				size.setWidth(400)
			self.doc.setTextWidth(size.width())
			self.w = self.doc.textWidth()
			self.h = self.doc.size().height()
			#log.debug('-------------dh: ' + str(self.doc.size().height()))
			#log.debug('-------------dw: ' + str(self.doc.size().width()))
			ctx = QAbstractTextDocumentLayout.PaintContext()
			painter.save()
			painter.translate(option.rect.topLeft());
			painter.setClipRect(option.rect.translated(-option.rect.topLeft()))
			self.doc.documentLayout().draw(painter, ctx)
			painter.restore()
		else:
			super(RequirementsDelegate, self).paint(painter, option, index)

	def sizeHint(self, option, index):
		size = super(RequirementsDelegate, self).sizeHint(option, index)
		if self.h:
			size.setHeight(self.h + 2)
		return size

class RequirementSetModel(QAbstractTableModel):
	def __init__(self, docId=None, parent=None):
		super(RequirementSetModel, self).__init__(parent)
		self._docId = docId
		self.load()

	@Slot()
	def load(self):
		global reqtree
		self._document = reqtree.find_document(self._docId)
		self._headerData = ['path', 'root', 'active', 'normative', 'uid', 'asil', 'level', 'header', 'text']
		self._data = []
		for item in iter_items(self._document):
			row = []
			for f in self._headerData:
				row.append(str(item.get(f)))
			#log.debug("Item: "+str(item))
			row.append(item) # Doorstop item reference put in the last row
			self._data.append(row)
		log.debug('['+str(self._document)+'] Requirements reloaded')

	def rowCount(self, index):
		return len(self._data)
	def columnCount(self, index):
		return len(self._headerData)

	def pos(self, h):
		return self._headerData.index(h)

	def data(self, index, role=Qt.DisplayRole):
		if not index.isValid():
			return QVariant()
		if role == Qt.DisplayRole or role == Qt.EditRole: #--------------- Value
			if index.column() == self.pos('asil'):
				if self._data[index.row()][index.column()] == 'None':
					return 'QM'
			return self._data[index.row()][index.column()]

		if role == Qt.BackgroundColorRole: #--------------------------------- BG
				pos = self.pos('level')
				if self._data[index.row()][pos].endswith('.0'):
						return QBrush(QColor('#a0a0a0'))
		if role == Qt.ForegroundRole: #-------------------------------------- FG
				pos = self.pos('level')
				if self._data[index.row()][pos].endswith('.0'):
						return QBrush(QColor('#505050'))

	def headerData(self, col, orientation, role=Qt.DisplayRole):
		if role == Qt.DisplayRole and orientation == Qt.Horizontal:
			return self._headerData[col]
		return QAbstractTableModel.headerData(self, col, orientation, role)
	def flags(self, index):
		if self._headerData[index.column()] in ['level','asil','text']:
			return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
		else:
			return Qt.ItemIsEnabled | Qt.ItemIsSelectable
	def sort(self, col, order):
		self.emit(SIGNAL("layoutAboutToBeChanged()"))
		self._data = sorted(self._data, key=operator.itemgetter(col))
		if order == Qt.DescendingOrder:
			self._data.reverse()
		self.emit(SIGNAL("layoutChanged()"))

	def setData(self, index, text): # called after closing the editor
		path = self._data[index.row()][0] # requirement file path
		try:
			# item reference is at last position
			self._data[index.row()][len(self._headerData)].text = text
			self._data[index.row()][len(self._headerData)].save()
			self._data[index.row()][self.pos('text')] = self._data[index.row()][len(self._headerData)].get('text') # the last column is the doorstop item
			log.debug('Edited requirement at ' + path)
		except doorstop.DoorstopError:
			log.error("Requirement not saved - manual edit required. " + path)

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
		self.loadModel()
		self.loadDelegate()
		self.loadView()

	def loadModel(self):
		self.model = RequirementSetModel(self._docId)

	def loadDelegate(self):
		self.delegate = RequirementsDelegate()

	def loadView(self):
		# Table
		self.view = QTableView()
		self.view.setModel(self.model)
		self.view.setItemDelegate(self.delegate)
		# Table appearance
		self.view.setMinimumSize(1024, 768)
		self.view.hideColumn(self.model.pos('path'))
		self.view.hideColumn(self.model.pos('root'))
		#self.view.setSelectionMode(QAbstractItemView.SingleSelection)
		#self.view.viewport().setAcceptDrops(True)
		#self.view.setDropIndicatorShown(True)
		#self.view.setDragEnabled(True)
		self.view.horizontalHeader().setStretchLastSection(True)
		self.view.resizeColumnsToContents()
		self.view.resizeRowsToContents()
		self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);
		# Buttons
		reloadBtn = QPushButton("Reload")
		reloadBtn.clicked.connect(self.model.load)
		newReqBtn = QPushButton("Add")
		newReqBtn.clicked.connect(self.new)
		delReqBtn = QPushButton("Remove")
		delReqBtn.clicked.connect(self.delete)
		# Placement
		ly = QVBoxLayout()
		lyBtns = QHBoxLayout()
		lyBtns.addWidget(reloadBtn)
		lyBtns.addWidget(newReqBtn)
		lyBtns.addWidget(delReqBtn)
		lyBtns.addStretch()
		ly.addLayout(lyBtns)
		ly.addWidget(self.view)
		self.setLayout(ly)

	@Slot()
	def new(self):
		global reqtree
		item = reqtree.add_item(str(self._docId))
		log.debug("["+str(self._docId)+"] Added requirement " + str(item))
		# to update the view, a signal needs to be sent
		self.model.load()
		self.model.emit(SIGNAL("layoutChanged()"))

	@Slot()
	def delete(self):
		index_list = []
		for model_index in self.view.selectionModel().selectedRows():
			index = QPersistentModelIndex(model_index)
			index_list.append(index)
		global reqtree
		for index in index_list:
			doorstop_item = index.model()._data[index.row()][len(index.model()._headerData)]
			index.model().removeRow(index.row())
			doorstop_requirement = index.model()._data[index.row()][4]
			doorstop_item.delete() # doorstop item deletion
			log.debug("Deleted row:  " + str(index.row()))
			log.debug("["+str(self._docId)+"] Deleted requirement " + str(doorstop_requirement))
		self.model.load()
		self.model.emit(SIGNAL("layoutChanged()"))

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
