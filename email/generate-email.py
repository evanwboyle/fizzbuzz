import os
import re
import json
import sys
import subprocess
import tempfile
import time
import requests
from datetime import datetime, date
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
SCRIPT_DIR = Path(__file__).resolve().parent

# ── Hard limits ────────────────────────────────────────────────────────
MAX_IMAGES = 20
IMAGE_CONFIRM_THRESHOLD = 10
MAX_REVISIONS = 5
ANALYSIS_MAX_TOKENS = 8_000
WRITING_MAX_TOKENS = 96_000
IMAGE_MAX_TOKENS = 300
TOKEN_WARNING_THRESHOLD = 150_000  # warn if input estimate exceeds this

# ── Color definitions ────────────────────────────────────────────────

PILL_COLORS = {
    "pink":   ("background:#ff3d9a;color:#ffffff;", "#ff3d9a"),
    "blue":   ("background:#1a6bff;color:#ffffff;", "#1a6bff"),
    "lime":   ("background:#c8f135;color:#0e0e14;", "#c8f135"),
    "orange": ("background:#ff6b1a;color:#ffffff;", "#ff6b1a"),
    "yellow": ("background:#ffe916;color:#0e0e14;", "#ffe916"),
    "dark":   ("background:#0e0e14;color:#c8f135;", "#0e0e14"),
}

CAMP_COLORS = {
    "lime":   ("background-color=\"#e6ffb0\"", "border=\"2px solid #c8f135\""),
    "green":  ("background-color=\"#e6ffb0\"", "border=\"2px solid #c8f135\""),
    "pink":   ("background-color=\"#fff0fa\"", "border=\"2px solid #ff3d9a\""),
    "orange": ("background-color=\"#fff3e8\"", "border=\"2px solid #ff6b1a\""),
    "blue":   ("background-color=\"#dff4ff\"", "border=\"2px solid #1a6bff\""),
}

CAPTION_COLORS = {
    "lime":   "background:#c8f135;color:#0e0e14;",
    "blue":   "background:#1a6bff;color:#ffffff;",
    "pink":   "background:#ff3d9a;color:#ffffff;",
}


# ── Shorthand expansion ─────────────────────────────────────────────

def _attr(tag: str, name: str, default: str = "") -> str:
    """Extract an attribute value from a tag string."""
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else default


def expand_shorthand(raw: str) -> str:
    """Convert compact fb- shorthand tags into full MJML markup."""
    out = raw

    # ── fb-zigzag (self-closing) ──
    out = re.sub(
        r'<fb-zigzag\s*/?>',
        '<mj-section padding="0">\n  <mj-column><mj-text padding="0"><div style="height:12px;background:repeating-linear-gradient(135deg,#c8f135 0px,#c8f135 8px,#ff3d9a 8px,#ff3d9a 16px,#1a6bff 16px,#1a6bff 24px,#ff6b1a 24px,#ff6b1a 32px,#ffe916 32px,#ffe916 40px);"></div></mj-text></mj-column>\n</mj-section>',
        out,
    )

    # ── fb-section / fb-title ──
    _NESTED_FB_RE = re.compile(
        r'(<fb-(?:image|quote|stats|camp|weather|potd)\b[\s\S]*?(?:/>|</fb-(?:image|quote|stats|camp|weather|potd)>))',
    )

    def _expand_section(m):
        tag = m.group(1)
        body = m.group(2)
        color = _attr(tag, "color", "pink")
        label = _attr(tag, "label", "Section")
        pill_style = PILL_COLORS.get(color, PILL_COLORS["pink"])[0]

        title_m = re.search(r'<fb-title>(.*?)</fb-title>', body, re.DOTALL)
        title_html = title_m.group(1).strip() if title_m else ""
        body_no_title = re.sub(r'<fb-title>.*?</fb-title>', '', body, flags=re.DOTALL)

        nested_components = _NESTED_FB_RE.findall(body_no_title)
        body_content = _NESTED_FB_RE.sub('', body_no_title).strip()

        section_mjml = (
            f'<mj-section background-color="#fefefe" padding="0 24px">\n'
            f'  <mj-column>\n'
            f'    <mj-text padding="8px 0 0 0" font-family="\'Chivo Mono\', monospace" font-size="9px" font-weight="700" letter-spacing="1px">\n'
            f'      <span style="{pill_style}padding:4px 10px;text-transform:uppercase;">{label}</span>\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="8px 0 16px 0" font-family="\'Archivo Black\', sans-serif" font-size="24px" line-height="1.2" color="#0e0e14">\n'
            f'      {title_html}\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="0 0 12px 0" font-family="\'Open Sans\', Arial, sans-serif" font-size="14px" line-height="1.6" color="#0e0e14">\n'
            f'      {body_content}\n'
            f'    </mj-text>\n'
            f'  </mj-column>\n'
            f'</mj-section>'
        )

        if nested_components:
            section_mjml += '\n' + '\n'.join(nested_components)

        return section_mjml

    out = re.sub(r'<fb-section([^>]*)>(.*?)</fb-section>', _expand_section, out, flags=re.DOTALL)

    # ── fb-camp ──
    def _expand_camp(m):
        tag = m.group(1)
        body = m.group(2).strip()
        name = _attr(tag, "name", "Camp")
        color = _attr(tag, "color", "lime")
        bg, border = CAMP_COLORS.get(color, CAMP_COLORS["lime"])

        return (
            f'<mj-section {bg} padding="0 24px" {border}>\n'
            f'  <mj-column>\n'
            f'    <mj-text padding="16px 16px 0 16px" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700" letter-spacing="1px" text-transform="uppercase" color="#0e0e14">\n'
            f'      {name}\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="8px 16px 16px 16px" font-family="\'Open Sans\', Arial, sans-serif" font-size="14px" line-height="1.6" color="#0e0e14">\n'
            f'      {body}\n'
            f'    </mj-text>\n'
            f'  </mj-column>\n'
            f'</mj-section>'
        )

    out = re.sub(r'<fb-camp([^>]*)>(.*?)</fb-camp>', _expand_camp, out, flags=re.DOTALL)

    # ── fb-stats / fb-stat ──
    def _expand_stats(m):
        body = m.group(1)
        pills = []
        for sm in re.finditer(r'<fb-stat([^>]*)>(.*?)</fb-stat>', body, re.DOTALL):
            color = _attr(sm.group(1), "color", "lime")
            text = sm.group(2).strip()
            style = PILL_COLORS.get(color, PILL_COLORS["lime"])[0]
            pills.append(f'<span style="{style}padding:6px 12px;border-radius:20px;">{text}</span>')

        return (
            '<mj-section background-color="#fefefe" padding="0 24px">\n'
            '  <mj-column>\n'
            '    <mj-text padding="8px 0" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700">\n'
            f'      {"&nbsp;".join(pills)}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-stats>(.*?)</fb-stats>', _expand_stats, out, flags=re.DOTALL)

    # ── fb-quote ──
    def _expand_quote(m):
        tag = m.group(1)
        body = m.group(2).strip()
        attribution = _attr(tag, "attribution", "")
        post_id = _attr(tag, "post", "")

        if post_id:
            quote_html = f'<a href="{{{{POST_LINK_{post_id}}}}}" style="color:inherit;text-decoration:underline;">&ldquo;{body}&rdquo;</a>'
        else:
            quote_html = f'&ldquo;{body}&rdquo;'

        result = (
            '<mj-section background-color="#0e0e14" padding="0 24px" border-left="4px solid #ff3d9a">\n'
            '  <mj-column>\n'
            '    <mj-text padding="24px" font-family="\'Open Sans\', Arial, sans-serif" font-size="16px" font-weight="700" color="#fefefe" line-height="1.5">\n'
            f'      <p>{quote_html}</p>\n'
            '    </mj-text>\n'
        )
        if attribution:
            result += (
                f'    <mj-text padding="0 24px 24px 24px" font-family="\'Chivo Mono\', monospace" font-size="10px" color="#888888">\n'
                f'      {attribution}\n'
                f'    </mj-text>\n'
            )
        result += '  </mj-column>\n</mj-section>'
        return result

    out = re.sub(r'<fb-quote([^>]*)>(.*?)</fb-quote>', _expand_quote, out, flags=re.DOTALL)

    # ── fb-image (self-closing) ──
    # Supports: size="full|half|small" (default "half"), caption is optional
    SIZE_WIDTHS = {"full": "612px", "half": "306px", "small": "200px"}

    def _image_column(tag):
        """Build a single mj-column for one image from its tag attributes."""
        src = _attr(tag, "src")
        if src and not re.search(r'\.(jpe?g|png|gif|webp|svg)(\?|#|$)', src, re.I):
            src += "#.jpg"
        alt = _attr(tag, "alt", "image")
        caption = _attr(tag, "caption", "")
        color = _attr(tag, "color", "lime")
        size = _attr(tag, "size", "half")
        cap_style = CAPTION_COLORS.get(color, CAPTION_COLORS["lime"])
        width = SIZE_WIDTHS.get(size, SIZE_WIDTHS["half"])

        col = f'    <mj-image src="{src}" alt="{alt}" padding="20px 0 0 0" width="{width}" />\n'
        if caption:
            col += (
                f'    <mj-text padding="0" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700" letter-spacing="1px" text-transform="uppercase">\n'
                f'      <div style="{cap_style}padding:8px 12px;">{caption}</div>\n'
                f'    </mj-text>\n'
            )
        return col, size

    def _expand_image(m):
        tag = m.group(1)
        col, size = _image_column(tag)
        result = (
            '<mj-section background-color="#fefefe" padding="0 24px">\n'
            '  <mj-column>\n'
            + col
            + '  </mj-column>\n</mj-section>'
        )
        return result

    out = re.sub(r'<fb-image([\s\S]*?)/\s*>', _expand_image, out)
    out = re.sub(r'<fb-image([^>]*)>(?:\s*</fb-image>)?', _expand_image, out)

    # ── fb-image-pair (two images side by side) ──
    def _expand_image_pair(m):
        inner = m.group(1)
        # Find the two fb-image tags inside
        imgs = re.findall(r'<fb-image([\s\S]*?)/\s*>', inner)
        if len(imgs) < 2:
            imgs += re.findall(r'<fb-image([^>]*)>(?:\s*</fb-image>)?', inner)
        cols = []
        for tag in imgs[:2]:
            col, _ = _image_column(tag)
            cols.append(col)
        if not cols:
            return ''
        result = '<mj-section background-color="#fefefe" padding="0 24px">\n'
        for col in cols:
            result += '  <mj-column>\n' + col + '  </mj-column>\n'
        result += '</mj-section>'
        return result

    out = re.sub(r'<fb-image-pair>([\s\S]*?)</fb-image-pair>', _expand_image_pair, out)

    # ── fb-weather ──
    def _expand_weather(m):
        body = m.group(1).strip()
        return (
            '<mj-section background-color="#dff4ff" padding="0 24px" border="2px solid #1a6bff">\n'
            '  <mj-column>\n'
            '    <mj-text padding="16px" font-family="\'Chivo Mono\', monospace" font-size="11px" font-weight="700" color="#0e0e14">\n'
            f'      {body}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-weather>(.*?)</fb-weather>', _expand_weather, out, flags=re.DOTALL)

    # ── fb-potd ──
    def _expand_potd(m):
        tag = m.group(1)
        body = m.group(2).strip()
        likes = _attr(tag, "likes", "")
        annotation = _attr(tag, "annotation", "")
        post_id = _attr(tag, "post", "")
        footer_text = f"{likes} &mdash; {annotation}" if likes else annotation

        if post_id:
            quote_html = f'<a href="{{{{POST_LINK_{post_id}}}}}" style="color:inherit;text-decoration:underline;">&ldquo;{body}&rdquo;</a>'
        else:
            quote_html = f'&ldquo;{body}&rdquo;'

        return (
            '<mj-section background-color="#ffe916" padding="24px">\n'
            '  <mj-column>\n'
            '    <mj-text padding="0 0 12px 0" font-family="\'Archivo Black\', sans-serif" font-size="19px" line-height="1.4" color="#0e0e14">\n'
            f'      <p>{quote_html}</p>\n'
            '    </mj-text>\n'
            '    <mj-text padding="0" font-family="\'Chivo Mono\', monospace" font-size="10px" color="rgba(14,14,20,0.7)">\n'
            f'      {footer_text}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-potd([^>]*)>(.*?)</fb-potd>', _expand_potd, out, flags=re.DOTALL)

    # ── Inline post links: <a post="ID">text</a> ──
    def _expand_inline_link(m):
        post_id = m.group(1)
        text = m.group(2)
        return f'<a href="{{{{POST_LINK_{post_id}}}}}" style="color:#ff3d9a;text-decoration:underline;">{text}</a>'

    out = re.sub(r'<a\s+post="([^"]+)">(.*?)</a>', _expand_inline_link, out, flags=re.DOTALL)

    return out


# ── Post text matching ────────────────────────────────────────────────

def _clean_for_matching(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    text = re.sub(r'&[a-z]+;', ' ', text)       # strip HTML entities
    text = re.sub(r'<[^>]+>', ' ', text)         # strip tags
    text = re.sub(r'\[RELATIVE TIME:[^\]]*\]', ' ', text)  # strip time annotations
    text = re.sub(r'[^\w\s]', ' ', text.lower()) # lowercase, strip punctuation
    return re.sub(r'\s+', ' ', text).strip()


def _best_post_match(needle: str, post_texts: dict, threshold: float = 0.4) -> str | None:
    """Find the postID whose text best matches `needle`.

    Returns the postID or None if no match exceeds the threshold.
    """
    import difflib
    clean_needle = _clean_for_matching(needle)
    if not clean_needle:
        return None

    best_id = None
    best_ratio = 0.0

    for post_id, post_text in post_texts.items():
        clean_post = _clean_for_matching(post_text)
        if not clean_post:
            continue

        # Fast check: if needle is a substring, strong match
        if clean_needle in clean_post:
            ratio = 0.95
        else:
            ratio = difflib.SequenceMatcher(None, clean_needle, clean_post).ratio()

        if ratio > best_ratio:
            best_ratio = ratio
            best_id = post_id

    if best_ratio >= threshold:
        return best_id
    return None


def match_post_links(sections_raw: str, map_path: Path) -> str:
    """Match quoted text to posts by content similarity and inject post IDs.

    Scans for fb-quote, fb-potd, and <a post> tags. For each, fuzzy-matches
    the quoted text against the post-text-map.json and injects the matched
    postID into the tag's post attribute.
    """
    if not map_path.is_file():
        print(f"WARNING: {map_path} not found. Post links will not be generated.")
        return sections_raw

    post_texts = json.loads(map_path.read_text(encoding="utf-8"))
    matched = 0
    unmatched = 0

    # Match fb-quote bodies
    def _match_quote(m):
        nonlocal matched, unmatched
        attrs = m.group(1)
        body = m.group(2).strip()
        post_id = _best_post_match(body, post_texts)
        if post_id:
            matched += 1
            # Remove any existing post attr, add the matched one
            attrs = re.sub(r'\s*post="[^"]*"', '', attrs)
            return f'<fb-quote{attrs} post="{post_id}">{m.group(2)}</fb-quote>'
        else:
            unmatched += 1
            print(f"  WARNING: No match for quote: \"{body[:80]}...\"")
            return m.group(0)

    result = re.sub(r'<fb-quote([^>]*)>(.*?)</fb-quote>', _match_quote, sections_raw, flags=re.DOTALL)

    # Match fb-potd bodies
    def _match_potd(m):
        nonlocal matched, unmatched
        attrs = m.group(1)
        body = m.group(2).strip()
        post_id = _best_post_match(body, post_texts)
        if post_id:
            matched += 1
            attrs = re.sub(r'\s*post="[^"]*"', '', attrs)
            return f'<fb-potd{attrs} post="{post_id}">{m.group(2)}</fb-potd>'
        else:
            unmatched += 1
            print(f"  WARNING: No match for POTD: \"{body[:80]}...\"")
            return m.group(0)

    result = re.sub(r'<fb-potd([^>]*)>(.*?)</fb-potd>', _match_potd, result, flags=re.DOTALL)

    # Match inline <a post="verbatim snippet">display text</a>
    # The post attribute contains a verbatim snippet for matching;
    # the tag body is the editorial text readers see.
    def _match_inline(m):
        nonlocal matched, unmatched
        hint = m.group(1).strip()
        display_text = m.group(2)
        post_id = _best_post_match(hint, post_texts, threshold=0.3)
        if post_id:
            matched += 1
            return f'<a post="{post_id}">{display_text}</a>'
        else:
            unmatched += 1
            print(f"  WARNING: No match for inline link: \"{hint[:60]}\"")
            # Drop the <a post> wrapper, keep the display text
            return display_text

    result = re.sub(r'<a\s+post="([^"]+)">(.*?)</a>', _match_inline, result, flags=re.DOTALL)

    print(f"[Post matching: {matched} matched, {unmatched} unmatched]")
    return result


# ── Post link resolution ──────────────────────────────────────────────

def resolve_post_links(mjml_source: str) -> str:
    """Replace {{POST_LINK_<postID>}} placeholders with Fizz share URLs."""
    placeholders = set(re.findall(r'\{\{POST_LINK_([^}]+)\}\}', mjml_source))
    if not placeholders:
        return mjml_source

    # Import generate-url.py functions
    from importlib.util import spec_from_file_location, module_from_spec
    gen_url_path = Path(__file__).resolve().parents[1] / "scraping" / "generate-url.py"
    spec = spec_from_file_location("generate_url", gen_url_path)
    gen_url = module_from_spec(spec)
    spec.loader.exec_module(gen_url)

    gen_url.load_env(gen_url.ENV_PATH)
    community = os.environ.get("COMMUNITY", "Yale")

    try:
        token = gen_url.refresh_bearer_token()
    except Exception as e:
        print(f"WARNING: Could not refresh bearer token: {e}. Post links will be removed.")
        return _strip_unresolved_links(mjml_source, placeholders)

    print(f"[Resolving {len(placeholders)} post link(s)...]")

    result = mjml_source
    for post_id in placeholders:
        try:
            share_url = gen_url.create_share_url(token, post_id, community)
            result = result.replace(f"{{{{POST_LINK_{post_id}}}}}", share_url)
            print(f"  {post_id[:12]}... -> {share_url}")
        except Exception as e:
            print(f"  WARNING: Failed to generate URL for {post_id[:12]}...: {e}. Link removed.")
            result = _strip_single_link(result, post_id)

    return result


def _strip_single_link(html: str, post_id: str) -> str:
    """Remove <a> tags with a specific unresolved post link, keeping inner text."""
    placeholder = f"{{{{POST_LINK_{post_id}}}}}"
    pattern = re.compile(
        rf'<a\s+href="{re.escape(placeholder)}"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    return pattern.sub(r'\1', html)


def _strip_unresolved_links(html: str, post_ids: set) -> str:
    """Remove all unresolved post link <a> tags."""
    for pid in post_ids:
        html = _strip_single_link(html, pid)
    return html


# ── Shared helpers (also used by assemble.py) ────────────────────────

def extract_block(raw: str, name: str) -> str | None:
    pattern = rf"<!--{name}-->(.*?)<!--/{name}-->"
    match = re.search(pattern, raw, re.DOTALL)
    return match.group(1).strip() if match else None


def load_editors_note() -> tuple[str, str]:
    """Return (header_mjml, footer_mjml) from editors-note.json, or empty strings."""
    header_mjml = ""
    footer_mjml = ""
    editors_note_path = SCRIPT_DIR / "input" / "editors-note.json"
    if not editors_note_path.is_file():
        return header_mjml, footer_mjml
    try:
        editors_note = json.loads(editors_note_path.read_text(encoding="utf-8"))
        note_date = editors_note.get("date", "")
        today_str = date.today().isoformat()
        if note_date != today_str:
            print(f"[Editor's note: skipped (date {note_date!r} != today {today_str!r})]")
            return header_mjml, footer_mjml
        header_note = editors_note.get("header", "").strip()
        footer_note = editors_note.get("footer", "").strip()
        if header_note:
            header_mjml = (
                '<mj-section background-color="#0e0e14" padding="10px 32px" border-top="2px solid #ff3d9a">'
                '<mj-column>'
                '<mj-text padding="0" font-family="\'Open Sans\', Arial, sans-serif" font-size="12px" font-style="italic" color="#aaaaaa" line-height="1.6">'
                f'<span style="font-family:\'Chivo Mono\',monospace;font-size:9px;font-weight:700;font-style:normal;text-transform:uppercase;letter-spacing:1px;color:#ff3d9a;">NOTES FROM THE EDITOR:</span> {header_note}'
                '</mj-text>'
                '</mj-column>'
                '</mj-section>'
            )
            print("[Editor's note (header): loaded]")
        if footer_note:
            footer_mjml = (
                '<mj-section background-color="#0e0e14" padding="10px 32px 0 32px" border-bottom="2px solid #c8f135">'
                '<mj-column>'
                '<mj-text padding="0" font-family="\'Open Sans\', Arial, sans-serif" font-size="12px" font-style="italic" color="#aaaaaa" line-height="1.6">'
                f'<span style="font-family:\'Chivo Mono\',monospace;font-size:9px;font-weight:700;font-style:normal;text-transform:uppercase;letter-spacing:1px;color:#ff3d9a;">NOTES FROM THE EDITOR:</span> {footer_note}'
                '</mj-text>'
                '</mj-column>'
                '</mj-section>'
            )
            print("[Editor's note (footer): loaded]")
        if not header_note and not footer_note:
            print("[Editor's note: date matches but both header and footer are empty]")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[Editor's note: skipped (parse error: {e})]")
    return header_mjml, footer_mjml


VERSION = "1.0.0"


def build_issue_info() -> str:
    """Build issue info from edition-memory.log line count and today's date."""
    memory_path = SCRIPT_DIR / "input" / "edition-memory.log"
    if memory_path.is_file():
        lines = [l for l in memory_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        issue_num = len(lines)
    else:
        issue_num = 1
    today = date.today()
    date_str = today.strftime("%B %-d, %Y")
    return f"{date_str}<br>No. {issue_num}<br>v{VERSION}"


def compile_mjml(mjml_source: str) -> str:
    """Compile MJML markup to email-safe HTML using npx mjml."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjml", delete=False, encoding="utf-8"
    ) as tmp_in:
        tmp_in.write(mjml_source)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".mjml", ".html")
    try:
        result = subprocess.run(
            ["npx", "mjml", tmp_in_path, "-o", tmp_out_path,
             "--config.minify", "true"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[MJML compiler stderr]: {result.stderr.strip()}")
        html = Path(tmp_out_path).read_text(encoding="utf-8")
        html = re.sub(r'<!--\[if [^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<!--\[if [^\]]*\]><!-->', '', html)
        html = re.sub(r'<!--<!\[endif\]-->', '', html)
        html = re.sub(r'\s+', ' ', html)
        html = re.sub(r'>\s+<', '>\n<', html)
        return html
    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def assemble_html(raw_output: str, mjml_template: str) -> str | None:
    """Substitute AI content blocks into the MJML template and compile to HTML."""
    ticker = extract_block(raw_output, "TICKER")
    sections_raw = extract_block(raw_output, "SECTIONS")
    footer_except = extract_block(raw_output, "FOOTER_EXCEPT")

    if not all([ticker, sections_raw, footer_except]):
        return None

    # Match quoted text to posts by content similarity, inject postIDs
    text_map_path = Path(__file__).resolve().parents[1] / "data" / "post-text-map.json"
    sections_raw = match_post_links(sections_raw, text_map_path)

    # Expand fb-* shorthand to MJML (creates {{POST_LINK_<id>}} placeholders)
    sections = expand_shorthand(sections_raw)

    editors_header, editors_footer = load_editors_note()
    issue_info = build_issue_info()

    mjml_source = mjml_template
    mjml_source = mjml_source.replace("{{ISSUE_INFO}}", issue_info)
    mjml_source = mjml_source.replace("{{TICKER_CONTENT}}", ticker)
    mjml_source = mjml_source.replace("{{SECTIONS}}", sections)
    mjml_source = mjml_source.replace("{{FOOTER_EXCEPT}}", footer_except)
    mjml_source = mjml_source.replace("{{EDITORS_NOTE_HEADER}}", editors_header)
    mjml_source = mjml_source.replace("{{EDITORS_NOTE_FOOTER}}", editors_footer)

    # Resolve post link placeholders to actual Fizz share URLs
    mjml_source = resolve_post_links(mjml_source)

    print("[Compiling MJML to email-safe HTML...]")
    return compile_mjml(mjml_source)


# ── Interactive helpers ───────────────────────────────────────────────

def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _ask(prompt_text: str, default: str = "") -> str:
    """Prompt the user for input. Returns default if not interactive."""
    if not _is_interactive():
        return default
    try:
        return input(prompt_text).strip()
    except EOFError:
        return default


def _ask_yn(prompt_text: str) -> bool:
    """Ask a yes/no question. Returns False if not interactive."""
    answer = _ask(f"{prompt_text} [y/N] ")
    return answer.lower() in ("y", "yes")


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _print_cost_estimate(input_tokens: int, output_tokens: int):
    input_cost = input_tokens * 0.30 / 1_000_000
    output_cost = output_tokens * 1.20 / 1_000_000
    total = input_cost + output_cost
    print(f"  Est. cost: ${total:.4f} (input: ${input_cost:.4f} + output: ${output_cost:.4f})")


# ── Main generation flow ─────────────────────────────────────────────

def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    import pandas as pd
    import anthropic

    load_env_file(ENV_PATH)

    # ── Load API config ──
    base_url = os.getenv("ANTHROPIC_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.minimax.io/anthropic"))
    api_key = os.getenv("ANTHROPIC_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    if not api_key or api_key.startswith("YOUR_"):
        raise RuntimeError(
            "Please set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env or your shell to your MiniMax API key"
        )

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
    )

    # ── Load all inputs ──
    csv_path = str(Path(__file__).resolve().parents[1] / "data" / "crawl-results-new.csv")
    if not os.path.isfile(csv_path):
        raise FileNotFoundError("data/crawl-results-new.csv not found. Run sanitize.py first.")

    df = pd.read_csv(csv_path, comment="#")
    csv_text = df.to_string(index=False)

    slang_path = SCRIPT_DIR / "input" / "slang-glossary.txt"
    slang_glossary = slang_path.read_text(encoding="utf-8").strip() if slang_path.is_file() else "(No slang glossary yet.)"

    memory_path = SCRIPT_DIR / "input" / "edition-memory.log"
    memory_log = memory_path.read_text(encoding="utf-8").strip() if memory_path.is_file() else "(No previous editions yet.)"

    alignment_path = SCRIPT_DIR / "input" / "alignment.json"
    editor_alignment = "(No editor alignment note for this edition.)"
    if alignment_path.is_file():
        try:
            alignment_data = json.loads(alignment_path.read_text(encoding="utf-8"))
            alignment_date = alignment_data.get("date", "")
            today_str = date.today().isoformat()
            alignment_msg = alignment_data.get("message", "").strip()
            if alignment_date == today_str and alignment_msg:
                editor_alignment = alignment_msg
                print(f"[Editor alignment: loaded]")
            elif alignment_date != today_str:
                print(f"[Editor alignment: skipped (date {alignment_date!r} != today {today_str!r})]")
            else:
                print("[Editor alignment: date matches but message is empty]")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[Editor alignment: skipped (parse error: {e})]")

    # ══════════════════════════════════════════════════════════════════
    # STAGE 1: Analysis Pass (with revision loop)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("STAGE 1: Editorial Analysis")
    print("=" * 60)

    analysis_prompt_path = SCRIPT_DIR / "input" / "analysis-prompt.md"
    if not analysis_prompt_path.is_file():
        raise FileNotFoundError(f"Analysis prompt not found: {analysis_prompt_path}")
    analysis_template = analysis_prompt_path.read_text(encoding="utf-8")
    analysis_prompt = analysis_template.replace("[PASTE CSV HERE]", csv_text)
    analysis_prompt = analysis_prompt.replace("[EDITION_MEMORY_LOG]", memory_log)
    analysis_prompt = analysis_prompt.replace("[SLANG_GLOSSARY]", slang_glossary)
    analysis_prompt = analysis_prompt.replace("[EDITOR_ALIGNMENT]", editor_alignment)

    est_input = _estimate_tokens(analysis_prompt)
    print(f"Analysis prompt: {len(analysis_prompt):,} chars (~{est_input:,} tokens) | {len(df)} posts")
    print(f"Max output: {ANALYSIS_MAX_TOKENS:,} tokens")
    _print_cost_estimate(est_input, ANALYSIS_MAX_TOKENS)

    if est_input > TOKEN_WARNING_THRESHOLD:
        print(f"WARNING: Input estimate ({est_input:,}) exceeds {TOKEN_WARNING_THRESHOLD:,} token threshold.")

    # Build conversation for revision loop
    messages = [
        {"role": "user", "content": analysis_prompt},
    ]

    plan = None
    for revision_round in range(MAX_REVISIONS + 1):
        if revision_round == 0:
            print("\nCalling MiniMax for analysis...")
        else:
            print(f"\nRevision round {revision_round}/{MAX_REVISIONS}...")

        try:
            response = client.messages.create(
                model="MiniMax-M2.5",
                max_tokens=ANALYSIS_MAX_TOKENS,
                system="You are a newsletter editor producing a structured editorial plan as JSON. Output ONLY valid JSON, no markdown fencing, no explanation.",
                messages=messages,
            )
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(
                "Authentication failed. Check your MiniMax API key and endpoint."
            ) from exc

        raw_analysis = next(block.text for block in response.content if block.type == "text")
        print(f"  Input tokens: {response.usage.input_tokens:,} | Output tokens: {response.usage.output_tokens:,}")

        # Try to parse JSON
        try:
            # Strip markdown fencing if model wrapped it
            json_text = raw_analysis.strip()
            if json_text.startswith("```"):
                json_text = re.sub(r'^```\w*\n?', '', json_text)
                json_text = re.sub(r'\n?```$', '', json_text)
            plan = json.loads(json_text)
        except json.JSONDecodeError as e:
            print(f"WARNING: Could not parse analysis as JSON: {e}")
            print("Raw output (first 500 chars):")
            print(raw_analysis[:500])
            if not _is_interactive():
                raise
            # Add to conversation and ask for fix
            messages.append({"role": "assistant", "content": raw_analysis})
            messages.append({"role": "user", "content": "That was not valid JSON. Please output only valid JSON with no markdown fencing."})
            continue

        # Display the plan
        sections = plan.get("sections", [])
        images = plan.get("images_to_annotate", [])
        potd = plan.get("potd_candidate", {})
        unknown_slang = plan.get("unknown_slang", [])

        print(f"\n{'─' * 60}")
        print(f"EDITORIAL PLAN ({len(sections)} sections, {len(images)} images)")
        print(f"{'─' * 60}")
        for i, sec in enumerate(sections, 1):
            print(f"  {i}. {sec.get('title', '???')}")
            print(f"     Type: {sec.get('section_type', '???')} | Engagement: {sec.get('engagement_score', '?')}")
            print(f"     Pitch: {sec.get('pitch', '???')}")
            components = sec.get("suggested_components", [])
            if components:
                print(f"     Components: {', '.join(components)}")
            print()

        if potd:
            print(f"  POTD: \"{potd.get('text', '???')[:80]}...\"")
            print(f"     {potd.get('likes', '?')} likes | {potd.get('why', '')}")
            print()

        print(f"  Images to annotate: {len(images)}")
        for img in images[:5]:
            print(f"    - {img.get('url', '???')[:60]}...")
            print(f"      Section: {img.get('section_title', '???')}")
        if len(images) > 5:
            print(f"    ... and {len(images) - 5} more")

        if unknown_slang:
            print(f"\n  Unknown slang flagged: {', '.join(unknown_slang[:10])}")
            if len(unknown_slang) > 10:
                print(f"    ... and {len(unknown_slang) - 10} more")

        print(f"{'─' * 60}")

        # Ask for approval or revision
        if not _is_interactive():
            print("[Non-interactive mode: auto-approving plan]")
            break

        answer = _ask("\nApprove plan? (yes / type revision notes): ", "yes")
        if answer.lower() in ("y", "yes", ""):
            print("[Plan approved]")
            break

        if revision_round >= MAX_REVISIONS:
            print(f"[Max revisions ({MAX_REVISIONS}) reached, using current plan]")
            break

        # Send revision feedback
        messages.append({"role": "assistant", "content": raw_analysis})
        messages.append({"role": "user", "content": f"Please revise the plan based on this feedback: {answer}"})

    if plan is None:
        raise RuntimeError("Failed to get a valid editorial plan after all attempts.")

    # ── Update slang glossary from analysis pass ──
    analysis_slang = plan.get("unknown_slang", [])
    if analysis_slang:
        existing_terms = set()
        if slang_path.is_file():
            for line in slang_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                term = line.split("=")[0].strip().lower()
                if term:
                    existing_terms.add(term)

        new_terms = [t for t in analysis_slang if t.lower() not in existing_terms]
        if new_terms:
            emoji_terms = [t for t in new_terms if any(ord(c) > 0x2600 for c in t)]
            phrase_terms = [t for t in new_terms if '[' in t and t not in emoji_terms]
            word_terms = [t for t in new_terms if t not in emoji_terms and t not in phrase_terms]

            with open(slang_path, "a", encoding="utf-8") as sf:
                if word_terms:
                    sf.write("\n# --- New (needs definitions) ---\n")
                    for term in word_terms:
                        sf.write(f"{term} = ???\n")
                if phrase_terms:
                    sf.write("\n# --- New phrase patterns (needs definitions) ---\n")
                    for term in phrase_terms:
                        sf.write(f"{term} = ???\n")
                if emoji_terms:
                    sf.write("\n# --- New emoji combos (needs definitions) ---\n")
                    for term in emoji_terms:
                        sf.write(f"{term} = ???\n")
            print(f"[New slang added to {slang_path.name}: {', '.join(new_terms)}]")
            print(f"  -> Edit {slang_path.name} now to fill in definitions before the writing pass")

            # Reload glossary so the writing pass gets updated definitions
            slang_glossary = slang_path.read_text(encoding="utf-8").strip()
        else:
            print("[No new unknown slang from analysis.]")
    else:
        print("[No unknown slang flagged by analysis.]")

    # ══════════════════════════════════════════════════════════════════
    # STAGE 2: Image Annotation
    # ══════════════════════════════════════════════════════════════════
    images_to_annotate = plan.get("images_to_annotate", [])
    image_annotations = {}

    if images_to_annotate:
        # Enforce hard cap
        if len(images_to_annotate) > MAX_IMAGES:
            print(f"\nWARNING: Plan requested {len(images_to_annotate)} images, capping to {MAX_IMAGES}.")
            images_to_annotate = images_to_annotate[:MAX_IMAGES]

        print("\n" + "=" * 60)
        print(f"STAGE 2: Image Annotation ({len(images_to_annotate)} images)")
        print("=" * 60)

        # Show image list
        for i, img in enumerate(images_to_annotate, 1):
            url = img.get("url", "")
            section = img.get("section_title", "???")
            post_text = img.get("post_text", "")[:60]
            print(f"  {i:2d}. {url[:70]}")
            print(f"      Section: {section} | Post: \"{post_text}...\"")

        if _is_interactive():
            print(f"\n  [m] Manual — describe each image yourself (opens URL in browser)")
            print(f"  [a] AI — annotate via MiniMax-Text-01 (requires credits)")
            print(f"  [s] Skip — no image annotations")
            choice = _ask("  Choice [m]: ", "m").lower()
        else:
            choice = "s"

        if choice in ("m", "manual", ""):
            # ── Manual annotation ──
            print()
            for i, img in enumerate(images_to_annotate, 1):
                url = img.get("url", "")
                post_text = img.get("post_text", "")
                if not url:
                    continue

                print(f"  [{i}/{len(images_to_annotate)}] {url}")
                print(f"    Post text: \"{post_text[:100]}{'...' if len(post_text) > 100 else ''}\"")

                # Open in browser
                try:
                    subprocess.run(
                        ["open", url] if sys.platform == "darwin" else ["xdg-open", url],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    print(f"    (Could not open browser. Visit the URL above manually.)")

                description = _ask("    Describe this image (or press Enter to skip): ")
                if description:
                    image_annotations[url] = description
                    print(f"    -> Saved")
                else:
                    print(f"    -> Skipped")
                print()

            annotated = sum(1 for v in image_annotations.values() if v)
            print(f"[{annotated}/{len(images_to_annotate)} images annotated manually]")

        elif choice in ("a", "ai"):
            # ── AI annotation via MiniMax-Text-01 ──
            est_per_image = 500
            est_image_cost = len(images_to_annotate) * est_per_image * 1.50 / 1_000_000
            print(f"  Est. cost for {len(images_to_annotate)} images: ~${est_image_cost:.4f}")

            if not _ask_yn(f"Proceed with AI annotation?"):
                print("[Skipping AI annotation]")
            else:
                openai_base = "https://api.minimax.io/v1"
                openai_headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                for i, img in enumerate(images_to_annotate, 1):
                    url = img.get("url", "")
                    post_text = img.get("post_text", "")
                    if not url:
                        continue

                    print(f"  [{i}/{len(images_to_annotate)}] Annotating: {url[:60]}...", end="", flush=True)

                    payload = {
                        "model": "MiniMax-Text-01",
                        "max_tokens": IMAGE_MAX_TOKENS,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Describe the image in 1-2 concise sentences. Focus on what is visually depicted. If it's a poster or flyer, note the event name and any readable details.",
                            },
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": url},
                                    },
                                    {
                                        "type": "text",
                                        "text": f"This image was posted on a college anonymous app alongside this text: \"{post_text[:500]}\"",
                                    },
                                ],
                            },
                        ],
                    }

                    success = False
                    for attempt in range(3):
                        try:
                            resp = requests.post(
                                f"{openai_base}/chat/completions",
                                headers=openai_headers,
                                json=payload,
                                timeout=60,
                            )
                            if resp.status_code == 429:
                                wait = 2 ** (attempt + 1)
                                print(f" rate limited, waiting {wait}s...", end="", flush=True)
                                time.sleep(wait)
                                continue
                            resp.raise_for_status()
                            resp_data = resp.json()
                            raw_content = resp_data["choices"][0]["message"]["content"].strip()
                            description = re.sub(r'<think>[\s\S]*?</think>', '', raw_content).strip()
                            if not description:
                                description = "(model returned only thinking, no description)"
                            image_annotations[url] = description
                            print(f" OK")
                            print(f"    -> {description[:100]}{'...' if len(description) > 100 else ''}")
                            success = True
                            break
                        except Exception as e:
                            if attempt < 2:
                                wait = 2 ** (attempt + 1)
                                print(f" error, retrying in {wait}s...", end="", flush=True)
                                time.sleep(wait)
                            else:
                                print(f" FAILED: {e}")
                                image_annotations[url] = "(annotation failed)"

                    if not success and url not in image_annotations:
                        image_annotations[url] = "(annotation failed)"

                    if i < len(images_to_annotate):
                        time.sleep(2)

                print(f"\n[{len(image_annotations)} images annotated]")

        else:
            print("[Skipping image annotation]")
    else:
        print("\n[No images to annotate]")

    # ══════════════════════════════════════════════════════════════════
    # STAGE 3: Writing Pass
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("STAGE 3: Writing Pass")
    print("=" * 60)

    writing_prompt_path = SCRIPT_DIR / "input" / "prompt.md"
    if not writing_prompt_path.is_file():
        raise FileNotFoundError(f"Writing prompt not found: {writing_prompt_path}")
    writing_template = writing_prompt_path.read_text(encoding="utf-8")

    # Build the plan text for injection
    plan_text = json.dumps(plan, indent=2)

    # Build image annotations text
    if image_annotations:
        annotations_lines = []
        for url, desc in image_annotations.items():
            annotations_lines.append(f"- {url}\n  Description: {desc}")
        annotations_text = "\n".join(annotations_lines)
    else:
        annotations_text = "(No images were annotated.)"

    writing_prompt = writing_template.replace("[EDITORIAL_PLAN]", plan_text)
    writing_prompt = writing_prompt.replace("[IMAGE_ANNOTATIONS]", annotations_text)
    writing_prompt = writing_prompt.replace("[SLANG_GLOSSARY]", slang_glossary)
    writing_prompt = writing_prompt.replace("[EDITOR_ALIGNMENT]", editor_alignment)

    est_writing_input = _estimate_tokens(writing_prompt)
    print(f"Writing prompt: {len(writing_prompt):,} chars (~{est_writing_input:,} tokens)")
    print(f"Max output: {WRITING_MAX_TOKENS:,} tokens")
    _print_cost_estimate(est_writing_input, WRITING_MAX_TOKENS)

    if est_writing_input > TOKEN_WARNING_THRESHOLD:
        print(f"WARNING: Input estimate ({est_writing_input:,}) exceeds {TOKEN_WARNING_THRESHOLD:,} token threshold.")

    # Prepare output file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = str(SCRIPT_DIR / "output" / f"fizz_raw_{timestamp}.html")
    print(f"Output: {output_file}")
    print(f"Streaming...\n")

    try:
        stream = client.messages.stream(
            model="MiniMax-M2.5",
            max_tokens=WRITING_MAX_TOKENS,
            system="You are a witty college newsletter writer. Output ONLY the delimited content blocks as instructed. Use fb-* shorthand tags (fb-section, fb-quote, fb-image, fb-zigzag, fb-stats, fb-camp, fb-potd, fb-weather) for the SECTIONS block — no raw MJML, no raw HTML divs, no full documents.",
            messages=[
                {"role": "user", "content": writing_prompt},
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "Authentication failed. Check your MiniMax API key and endpoint."
        ) from exc

    # Stream with block-aware progress
    BLOCK_NAMES = ["TICKER", "SECTIONS", "FOOTER_EXCEPT", "EDITION_MEMORY", "UNKNOWN_SLANG"]
    raw_chunks = []
    char_count = 0
    last_reported_count = 0
    detected_opens = set()
    detected_closes = set()
    tail_buffer = ""

    with stream as s:
        for text in s.text_stream:
            raw_chunks.append(text)
            char_count += len(text)
            tail_buffer = (tail_buffer + text)[-200:]

            for block in BLOCK_NAMES:
                if block not in detected_opens and f"<!--{block}-->" in tail_buffer:
                    detected_opens.add(block)
                    print(f"  [{block} streaming...]", flush=True)
                if block not in detected_closes and f"<!--/{block}-->" in tail_buffer:
                    detected_closes.add(block)
                    print(f"  [{block} received] ({char_count:,} chars)", flush=True)

            if char_count - last_reported_count >= 5000 and char_count > last_reported_count:
                print(f"  ... {char_count:,} chars", flush=True)
                last_reported_count = char_count

        writing_response = s.get_final_message()

    raw_output = "".join(raw_chunks)

    # ── Save edition memory ──
    edition_memory = extract_block(raw_output, "EDITION_MEMORY")
    if edition_memory:
        memory_line = edition_memory.strip()
        with open(memory_path, "a", encoding="utf-8") as mf:
            mf.write(memory_line + "\n")
        print(f"\n[Edition memory saved to {memory_path.name}]")
    else:
        print("\nWARNING: No EDITION_MEMORY block found in AI output. Memory not updated.")

    # ── Extract and report unknown slang from writing pass ──
    # (Analysis-pass slang was already added to the glossary before Stage 2)
    unknown_slang_block = extract_block(raw_output, "UNKNOWN_SLANG")
    writing_slang = []
    if unknown_slang_block and unknown_slang_block.strip():
        writing_slang = [t.strip() for t in unknown_slang_block.split(",") if t.strip()]

    if writing_slang:
        existing_terms = set()
        if slang_path.is_file():
            for line in slang_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                term = line.split("=")[0].strip().lower()
                if term:
                    existing_terms.add(term)

        new_terms = [t for t in writing_slang if t.lower() not in existing_terms]

        if new_terms:
            emoji_terms = [t for t in new_terms if any(ord(c) > 0x2600 for c in t)]
            phrase_terms = [t for t in new_terms if '[' in t and t not in emoji_terms]
            word_terms = [t for t in new_terms if t not in emoji_terms and t not in phrase_terms]

            with open(slang_path, "a", encoding="utf-8") as sf:
                if word_terms:
                    sf.write("\n# --- New (needs definitions) ---\n")
                    for term in word_terms:
                        sf.write(f"{term} = ???\n")
                if phrase_terms:
                    sf.write("\n# --- New phrase patterns (needs definitions) ---\n")
                    for term in phrase_terms:
                        sf.write(f"{term} = ???\n")
                if emoji_terms:
                    sf.write("\n# --- New emoji combos (needs definitions) ---\n")
                    for term in emoji_terms:
                        sf.write(f"{term} = ???\n")
            print(f"[New slang added to {slang_path.name}: {', '.join(new_terms)}]")
            print(f"  -> Edit {slang_path.name} to fill in definitions for terms marked '???'")
        else:
            print("[No new unknown slang found.]")
    else:
        print("[No unknown slang reported.]")

    # ── Save output ──
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(raw_output)

    print(f"\n{'=' * 60}")
    print(f"GENERATION COMPLETE")
    print(f"{'=' * 60}")
    print(f"AI output chars: {char_count:,}")
    print(f"Writing pass: input {writing_response.usage.input_tokens:,} / output {writing_response.usage.output_tokens:,} tokens")
    print(f"Stop reason: {writing_response.stop_reason}")
    if writing_response.stop_reason == "max_tokens":
        print("WARNING: Output was truncated! The model hit the max_tokens limit.")
        print("The output file is likely incomplete.")
    print(f"Saved to: {output_file}")
    print(f"  -> Run assemble.py to combine with template.")


if __name__ == "__main__":
    main()
