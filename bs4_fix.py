from bs4 import BeautifulSoup
with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")
with open("chauffeur/templates/config_fixed.html", "w", encoding="utf-8") as f:
    f.write(soup.prettify())
