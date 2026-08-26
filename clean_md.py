import pymupdf4llm
import re

def clean_markdown(md_text):
    # Remove repetitive page headers/footers
    md_text = re.sub(r'Quest1\nFinal Approach\n\d+\n', '', md_text)
    md_text = re.sub(r'Quest1\nFinal Approach\n', '', md_text)
    
    # Remove Table of Contents (everything before "1 Current Approach")
    # Actually, let's just let pymupdf4llm do its best, then we can clean up the TOC.
    return md_text

if __name__ == "__main__":
    md_text = pymupdf4llm.to_markdown("Approach.pdf")
    cleaned = clean_markdown(md_text)
    
    # Strip TOC by finding the first actual section if possible
    # We can just write it directly.
    with open("Approach.md", "w", encoding="utf-8") as f:
        f.write(cleaned)
