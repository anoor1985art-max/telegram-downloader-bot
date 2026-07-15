import requests
import re
from bs4 import BeautifulSoup

url = "https://www.instagram.com/p/DalZoF3NutQ/embed/captioned/"
h = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}).text

soup = BeautifulSoup(h, 'html.parser')
for img in soup.find_all('img'):
    src = img.get('src', '')
    if src:
        print("IMG_TAG:", src[:140])

# Also let's check for any background-image or JSON data
for script in soup.find_all('script'):
    if script.string and 'EmbeddedMedia' in script.string:
        print("SCRIPT:", script.string[:200])
