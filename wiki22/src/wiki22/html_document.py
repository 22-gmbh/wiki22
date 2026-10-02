"""Extract semantic reading blocks without running HTML or guessing new prose."""
from html.parser import HTMLParser
import re


class ReadingHTML(HTMLParser):
    void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    skip = {'head', 'script', 'style', 'nav', 'footer', 'form', 'button', 'svg', 'template', 'noscript'}
    blocks = {'p', 'div', 'section', 'article', 'main', 'header', 'blockquote', 'ul', 'ol', 'li', 'tr', 'pre', 'dl', 'dt', 'dd', 'figure', 'figcaption'}
    headings = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'summary'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.rows = []
        self.kind = 'p'
        self.scope = (False, False)

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.parts)).strip()
        if text:
            self.rows.append((self.kind, text, *self.scope))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else ('', False, False, False)
        hidden = parent[1] or tag in self.skip or 'hidden' in attrs or attrs.get('aria-hidden') == 'true' or attrs.get('role') in ('navigation', 'contentinfo') or bool(set(attrs.get('class', '').split()) & {'breadcrumb', 'breadcrumbs'})
        main = parent[2] or tag == 'main' or attrs.get('role') == 'main'
        article = parent[3] or tag == 'article'
        if not hidden and tag == 'br' and self.kind == 'h':
            self.parts.append(' ')
        elif not hidden and (tag in self.blocks or tag in self.headings or tag in ('br', 'hr')):
            self.flush()
            self.kind = 'h' if tag in self.headings else 'p'
            self.scope = (main, article)
        if tag not in self.void:
            self.stack.append((tag, hidden, main, article))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag not in self.void:
            index = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == tag), None)
            if index is not None:
                if not self.stack[-1][1] and (tag in self.blocks or tag in self.headings):
                    self.flush()
                    self.kind = 'p'
                elif not self.stack[-1][1] and tag in ('span', 'a', 'small'):
                    # Adjacent labels/links often rely on CSS for their spacing.
                    self.parts.append(' ')
                del self.stack[index:]
        if self.stack:
            self.scope = self.stack[-1][2:]

    def handle_data(self, text):
        if not self.stack or not self.stack[-1][1]:
            if not self.parts and self.stack:
                self.scope = self.stack[-1][2:]
            self.parts.append(text)


def html_sections(raw):
    parser = ReadingHTML()
    parser.feed(raw)
    parser.close()
    parser.flush()
    rows = parser.rows
    # Prefer an explicit reading region, retaining all its sections in order.
    if any(row[2] for row in rows):
        rows = [row for row in rows if row[2]]
    elif any(row[3] for row in rows):
        rows = [row for row in rows if row[3]]
    sections = []
    heading, paragraphs = 'Documento', []
    for kind, text, _, _ in rows:
        if kind == 'h':
            if paragraphs:
                sections.append((heading, '\n\n'.join(paragraphs)))
                paragraphs = []
            elif heading != 'Documento':
                # A heading without a body still carries source content.
                sections.append((heading, heading))
            heading = text
        else:
            paragraphs.append(text)
    if paragraphs:
        sections.append((heading, '\n\n'.join(paragraphs)))
    elif heading != 'Documento':
        sections.append((heading, heading))
    return sections
