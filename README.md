# doorhole

A graphical requirements editor for doorstop: https://github.com/doorstop-dev/doorstop

This tool is designed to view and edit doorstop requirements, as fast as possible.

![immagine](https://user-images.githubusercontent.com/301673/104736138-cdf86c00-5742-11eb-9a24-89f2f3f04da1.png)


## Installation

1. Install the required dependencies (Python 3.5+ required by doorstop):

```
pip install doorstop
pip install PySide6
pip install plantuml-markdown
```

2. Download the `doorhole.py` script inside a directory listed in your PATH system variable for easier access
3. Make it executable


## Usage

1. Open a terminal inside your git folder (you should already have a doorstop requirement tree).
2. Launch the script with `./doorhole.py`.

It will launch `doorstop` internally, load all requirements, and after a while the editor window will appear.


## Why?

Because all the tools lack something:

- doorstop GUI is slow while editing
- editing requirements using Calc or Excel is cumbersome
- you don't see PlantUML graphs (but you love them)

## Features

- faster than doorstop-gui
- open all requirement sets at once with tabs
- display requirements in a table-like interface
- edit and actually see plantUML graphs!
- create, view, edit, delete requirements

## Un-features

This tool is not performing a whole doorstop verification, because it would be rather slow (like doorstop GUI).
Use `doorstop` for that, and add your own checks there.

## PlantUML rendering

The script uses by default the PlantUML online renderer at http://www.plantuml.com/plantuml.

If you experience issues with the above online renderer, you can:

- use another web renderer (Docker image: https://hub.docker.com/r/plantuml/plantuml-server), or
- install a local renderer

If you want to change the PlantUML web renderer, update line #24 of the `doorhole.py` accordingly.

If you want to install PlantUML locally, read on!

### Local PlantUML installation (Windows)

1. Download and install Java
2. Download `plantuml.jar` from https://plantuml.com/download inside a directory listed in your PATH system variable for easier access.
3. Next to the `plantuml.jar` file, create the `plantuml.bat` file with the following content:

```
@echo off
set mypath=%~dp0
setlocal
java -jar %mypath%\plantuml.jar -charset UTF-8 %*
```

Done!

## (Lack of) Math equations

The sad news is that this tool cannot render MathJax expressions right now. It's a Javascript loaded in the published HTML.
