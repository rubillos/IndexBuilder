#!python3

from bs4 import BeautifulSoup, NavigableString, Tag
import re
from dateutil.parser import parse
from enum import Enum
import subprocess, sys, os, shutil
import requests
import argparse
from PIL import Image
import cv2
import platform
import copy
from rich.console import Console
from rich.progress import Progress, BarColumn, TimeElapsedColumn, Task
from rich.text import Text
from rich.theme import Theme
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
import webbrowser
import traceback

srcFolder = "/Users/randy/Sites/PortlandAve/"
indexFileName = "siteindex.txt"

crMatch = r'\s*\n+\s*'
tabMatch = r'\s*\t+\s*'

copyright_parts = [
	r'(©|\(c\)) *(\d{4})? *(RickAndRandy\.com)?',
	r'-\d{4} RickAndRandy\.com'
]

copyrightMatch = r'|'.join(copyright_parts)

paths_to_skip_parts = [
	r'\/rubber\/',
	r'\/meta\/both\/',
	r'\/meta\/randy\/',
	r'\/meta\/rick.*\/'
]

pathsToSkip = r'|'.join(paths_to_skip_parts)

strings_to_remove_parts = [
	r'Please use Safari or Chrome\.',
	r'Your browser does not support this movie\.',
	r'Click on a thumbnail below for a larger size image\.',
	r'(?:P|p)age \d+ of \d+ *',
	r'(?:P|p)age \d+ *',
	r'^ *(?:Back|Index|Previous|Next|Movie) *$',
	r'(?:Previous\s)?(?:\d+\s){2,}(?:\s?Next)?',
	r'(?:Previous )(?:.+ • ){2,}.+(?: Next)',
	r'(?:Previous )(?:\w+ ){2,}(?:Next)',
	r'(?:Previous )?(?:\w+ • ){2,}\w+(?: Next)?',
	r'Back © RickAndRandy.com',
	r'.*Switch to full .* version.*',
	r'Back to .* Index',
	r'^Back to .{1,15}$',
	r'Back Description ?',
	r' - RickAndRandy.com ?$',
	r'(?:B|b)ack to RickAndRandy.com',
	r' Next(?: Page)? ?$',
	r'^- ',
	r' $'
]

stringsToRemove = r'|'.join(strings_to_remove_parts)

theme = Theme({
			"progress.percentage": "white",
			"progress.remaining": "green",
			"progress.elapsed": "cyan",
			"bar.complete": "green",
			"bar.finished": "green",
			"bar.pulse": "green",
			"repr.ellipsis": "white",
			"repr.number": "white",
			"repr.path": "white",
			"repr.filename": "white"
			})

progressDesc = "[progress.description]{task.description}"
progressPercent = "[progress.percentage]{task.percentage:>3.0f}% "
progressPercentCount = "[progress.percentage]{task.percentage:>3.0f}% ({task.fields[count]})"
progressPercentMedia = "[progress.percentage]{task.percentage:>3.0f}% (copied:{task.fields[count]}, reused:{task.fields[reuse]})"

console = Console(theme=theme)

def extract_visible_text_from_html(file_path):
	"""
	Extracts user-visible text and the page name from an HTML file at the specified path.

	Args:
		file_path (str): The path to the HTML file.

	Returns:
		tuple: A tuple containing the page name (str) and the extracted visible text (str).
	"""
	try:
		with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
			html_content = file.read()

		soup = BeautifulSoup(html_content, 'html.parser')

		page_name = soup.title.string.strip() if soup.title and soup.title.string else "Untitled"

		for element in soup(['script', 'style', 'head', 'title', 'meta']):
			element.decompose()

		visible_text = soup.get_text(separator=' ', strip=True)

		visible_text = visible_text.replace(page_name + " ", "")
		visible_text = visible_text.replace(page_name, "")
		visible_text = re.sub(crMatch, ' ', visible_text)
		visible_text = re.sub(tabMatch, ' ', visible_text)
		visible_text = re.sub(stringsToRemove, '', visible_text)
		visible_text = re.sub(copyrightMatch, '', visible_text)
		visible_text = re.sub(r'\s+', ' ', visible_text)

		while True:
			startLen = len(visible_text)
			visible_text = re.sub(stringsToRemove, '', visible_text)
			visible_text = re.sub(r'\s+', ' ', visible_text)
			if len(visible_text) == startLen:
				break

		if visible_text == " ":
			visible_text = ""

		page_name = page_name.replace("\n", " ").replace("\r", "").replace(" • ", " ")
		page_name = re.sub(tabMatch, ' ', page_name)
		page_name = re.sub(" •$", "", page_name)

		return page_name, visible_text

	except Exception as e:
		print(f"Error extracting text from {file_path}: {e}")
		return "Error", ""

def scan_folder_for_index_files(start_folder, date_string):
	"""
	Recursively scans a folder for files named 'index*.html', extracts their page name and text,
	and returns an array of tuples containing the relative file path, page name, and page text.

	Args:
		start_folder (str): The folder to start scanning from.

	Returns:
		list: A list of tuples, where each tuple contains:
			  - relative file path (str)
			  - page name (str)
			  - page text (str)
	"""
	result = []

	try:
		# Walk through the directory tree
		for root, _, files in os.walk(start_folder):
			for file in files:
				if re.match(r'index.*\.htm', file, re.IGNORECASE):
					full_path = os.path.join(root, file)
					relative_path = os.path.relpath(full_path, srcFolder)
					page_name, page_text = extract_visible_text_from_html(full_path)
					
					if date_string:
						page_name = f"{page_name} <i>({date_string})</i>"
					if page_text != "":
						result.append((relative_path, page_name, page_text))
	except Exception as e:
		print(f"Error scanning folder {start_folder}: {e}")

	return result

def read_links_file(file_path):
	"""
	Reads the file 'links.txt' and splits its content into an array of lines.

	Args:
		file_path (str): The path to the 'links.txt' file.

	Returns:
		list: A list of lines from the file.
	"""
	try:
		with open(file_path, 'r', encoding='utf-8') as file:
			lines = file.read().splitlines()
		return lines
	except Exception as e:
		print(f"Error reading file {file_path}: {e}")
		return []

def find_index_files():
	link_list = read_links_file(os.path.join(srcFolder, "links.txt"))
	index_data = []
	with Progress(progressDesc, BarColumn(), progressPercent, console=console) as progress:
		task = progress.add_task("Build site index...", total=len(link_list))
		for link in link_list:
			link_parts = link.split("\t")
			if len(link_parts) >= 6:
				relative_path = link_parts[5]
				if not "http" in relative_path:
					if not "/" in relative_path:
						if "L" in link_parts[3]:
							relative_path = "Local/" + relative_path
						else:
							relative_path = "travel/" + relative_path
					if ".htm" in relative_path:
						relative_path = os.path.dirname(relative_path)

					year = link_parts[0].strip()
					month = link_parts[1].strip()
					day = link_parts[2].strip().zfill(2)

					if month.isdigit():
						month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(month) - 1]

					if year and month:
						date_string = f"{year}-{month}-{day}" if day else f"{year}-{month}"
					else:
						date_string = ""

					search_path = os.path.join(srcFolder, relative_path)
					if os.path.exists(search_path):
						link_data = scan_folder_for_index_files(search_path, date_string)
						index_data.extend(link_data)
			progress.update(task, advance=1)
	return index_data

if __name__ == "__main__":
	start_folder = srcFolder  # Use the defined srcFolder as the starting point
	index_files_data = find_index_files()
	pathCount = 0
	titleCount = 0
	textCount = 0
	for relative_path, page_name, page_text in index_files_data:
		pathCount += len(relative_path)
		titleCount += len(page_name)
		textCount += len(page_text)
		# print(f"File: {relative_path}, Page Name: {page_name}, Text: {page_text[:100]}...")  # Print first 100 chars of text

	print(f"Number of pages: {len(index_files_data)}")
	print(f"Total path length: {pathCount}")
	print(f"Total title length: {titleCount}")
	print(f"Total text count: {textCount}")

	with open(os.path.join(srcFolder, indexFileName), 'w', encoding='utf-8') as index_file:
		for relative_path, page_name, page_text in index_files_data:
			index_file.write(f"{relative_path}\t{page_name}\t{page_text}\n")
