from bs4 import BeautifulSoup

def html_to_plain_text(html: str) -> str:
    """Convert HTML to clean plain text, preserving links and lists."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Replace links with: text (url)
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        a.replace_with(f"{text} ({href})" if href else text)

    # Convert list items to '- item'
    for li in soup.find_all("li"):
        li.insert_before("- ")
        li.insert_after("\n")

    # Replace <br> and <p> with newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_after("\n")

    text = soup.get_text()
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
