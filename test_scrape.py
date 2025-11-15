import requests
from bs4 import BeautifulSoup

url = 'https://www.myjourneyfm.com/recently-played/'
response = requests.get(url)
soup = BeautifulSoup(response.content, 'html.parser')

# Try to find song elements
print("Song items:")
song_items = soup.find_all('div', class_='song-item')
for item in song_items:
    print(item.prettify())

print("\nScripts with 'song' or 'played':")
scripts = soup.find_all('script')
for script in scripts:
    if script.string and ('song' in script.string.lower() or 'played' in script.string.lower()):
        print(script.string[:2000])

print("\nAll links:")
for a in soup.find_all('a'):
    if 'recently' in a.get('href', '').lower():
        print(a)