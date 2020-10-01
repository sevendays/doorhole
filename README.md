# doorhole

A graphical requirements editor for doorstop: https://github.com/doorstop-dev/doorstop

This tool is designed to view and edit doorstop requirements, as fast as possible.

## Why?

Because all the tools lack something:

- doorstop GUI is slow
- editing requirements using Calc or Excel is cumbersome
- you don't see PlantUML graphs (but you love them)

## Features

- fast!
- open all requirement sets at once with tabs
- display requirements in a table-like interface
- edit and actually see plantUML graphs!
- Create, view, edit, delete requirements

## Un-features

This tool is not performing a whole doorstop verification, because it would be rather slow (like doorstop GUI).
Use `doorstop` for that, and add your own checks there.

## Usage

1. Download this script and place it inside your git folder (you should already have a doorstop requirement tree).
2. Open the terminal and launch the script with `python doorhole.py`.

It will launch `doorstop` internally, and after a while the editor window will appear.

If you're missing some dependencies, install them with `pip`.

## Dependencies

- python 3.6+
- doorstop
- pyside2
- markdown
- plantuml locally installed (or just edit line #26 of the script to use plantuml.com).
