#!/usr/bin/env python3
"""
Sofa catalog price extractor.
Reads module prices per fabric/leather category from a PDF price list
and turns them into selling prices using your own formula.

USAGE
-----
  python extract_prices.py <pdf_path> "<query>"

QUERY FORMAT
------------
  ProductName, [CategoryCodes], ModuleCode1, ModuleCode2, ...

  Examples:
    Product, B C D V T M N, ABC2000, ABC3000
    Product, ABC2000, ABC3000           <- defaults to all categories
    Product, B M N, AB1CD2000

  Category codes: B  C  D  V  T  Extra  M  N

PRICING FORMULAS
----------------
  List Price       = base_price * MULTIPLIER * DISCOUNT
  Compare At Price = base_price * MULTIPLIER
  (set MULTIPLIER and DISCOUNT in the CONFIG section below)
"""

import re
import sys
import math
import pdfplumber

# ===========================================================================
# CONFIG
# ===========================================================================

# ADD YOUR FORMULA HERE
# MULTIPLIER: everything applied to the catalog price, e.g. exchange rate * markup * VAT
# DISCOUNT:   applied on top for the list price, e.g. 0.8 = 20% off (1.0 = no discount)
MULTIPLIER = 1.0
DISCOUNT   = 1.0

# ===========================================================================
# Category label mapping
# ===========================================================================

CATEGORY_LABELS = {
    "TC":    "Tessuto Cliente",
    "B":     "Categoria B",
    "C":     "Categoria C",
    "D":     "Categoria D",
    "V":     "Categoria V",
    "T":     "Categoria T",
    "Extra": "Categoria Extra",
    "M":     "Pelle M",
    "N":     "Pelle N",
}
ALL_DEFAULT_CATEGORIES = ["B", "C", "D", "V", "T", "Extra", "M", "N"]

ROW_LABEL_TOKENS = [
    ("TC",    ["Tessuto", "Cliente"]),
    ("Extra", ["Categoria", "Extra"]),
    ("B",     ["Categoria", "B"]),
    ("C",     ["Categoria", "C"]),
    ("D",     ["Categoria", "D"]),
    ("V",     ["Categoria", "V"]),
    ("T",     ["Categoria", "T"]),
    ("M",     ["Pelle", "M"]),
    ("N",     ["Pelle", "N"]),
]

PRICE_RE = re.compile(r"^\d{1,3}(?:[.,]\d{3})*[.,]\d{2}$")
MODULE_RE = re.compile(r"^[A-Z][A-Z0-9]{4,}$")  # 5+ chars

# Dimension unit prefixes to reject (centimetri, metri, kg, etc.)
_DIMENSION_PREFIXES = {"CM", "MT", "KG", "M", "MT"}

def is_module_code(text):
    """
    Distinguishes real module codes from Italian words / dimension strings.

    Rules:
      - Must match MODULE_RE (5+ uppercase alphanumeric, starts with letter)
      - Must contain at least 3 digits (rules out DIVANO2, SOFA3ER)
      - Letter prefix (before first digit) must be 1–5 chars
        (rules out POSTIDIVANO3 with 11-char prefix)
      - Letter prefix must not be a dimension unit like CM, KG, MT
        (rules out CM114151CM)
      - Trailing suffix (after last digit) must be 0–2 chars
        (rules out SOFA3ER with 2-char suffix — wait, ER=2... but digit_count<3 catches it)

    Passes:  AB1CD2000, ABCD2000, AB2000, B2000, AB1CD0001S, ABCL2000S
    Fails:   DIVANO2, SOFA3ER, CM114151CM, POSTIDIVANO3
    """
    if not MODULE_RE.match(text):
        return False
    digit_count = sum(1 for c in text if c.isdigit())
    if digit_count < 3:
        return False
    first_digit_pos = next(i for i, c in enumerate(text) if c.isdigit())
    prefix = text[:first_digit_pos]
    if not prefix or len(prefix) > 5:
        return False
    if prefix in _DIMENSION_PREFIXES:
        return False
    last_digit_pos = max(i for i, c in enumerate(text) if c.isdigit())
    trailing = text[last_digit_pos + 1:]
    return len(trailing) <= 2


# ===========================================================================
# Query parsing
# ===========================================================================

def parse_query(raw):
    parts = [p.strip() for p in raw.split(",")]
    # Take only the first word of the product name
    # handles headers like "Product - schienale EASY | Product - ..."
    product_name = parts[0].strip().split()[0]
    categories, modules = [], []
    for part in parts[1:]:
        tokens = part.split()
        categories.extend([t for t in tokens if t in CATEGORY_LABELS])
        modules.extend([t for t in tokens if t not in CATEGORY_LABELS])
    if not categories:
        categories = ALL_DEFAULT_CATEGORIES
    return product_name, categories, modules

# ===========================================================================
# PDF helpers
# ===========================================================================

def clean_token(text):
    """Strip bracket decorators like (<-) and (->) from module codes."""
    return re.sub(r"[\(\)\-<>]", "", text).strip()


def group_words_by_line(words, y_tol=2.0):
    lines = {}
    for w in words:
        key = round(w["top"] / y_tol) * y_tol
        lines.setdefault(key, []).append(w)
    for key in lines:
        lines[key].sort(key=lambda w: w["x0"])
    return lines


def parse_price_str(text):
    text = text.replace("€", "").strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None

# ===========================================================================
# Page-level extraction
# ===========================================================================

def find_code_position(words, module_code):
    """
    Find a module code on the page. Handles:
      - Standalone:       ABCD2000
      - Bracket-wrapped:  (<-)ABCL2000S - ABCL2000D(->)
      - Cod.-prefixed:    Cod. D2000  (some catalogs)

    For Cod.-prefixed codes, returns Cod.'s x0 as the column anchor
    so it aligns with category label rows below.
    """
    code_upper = module_code.upper()
    lines = group_words_by_line(words)

    for top_y, line_words in sorted(lines.items()):
        for i, w in enumerate(line_words):
            # Direct / bracket-wrapped single token
            if clean_token(w["text"]).upper() == code_upper:
                return (w["x0"], w["top"], w["x1"], w["bottom"])

            # Multi-token bracket-wrapped (e.g. split across words)
            for length in range(2, 5):
                if i + length > len(line_words):
                    break
                chunk = line_words[i:i + length]
                joined = clean_token("".join(w2["text"] for w2 in chunk)).upper()
                if joined == code_upper:
                    return (chunk[0]["x0"], chunk[0]["top"],
                            chunk[-1]["x1"], chunk[-1]["bottom"])

            # Cod.-prefixed
            # Handles "Cod. D2000" and "Cod. (<-) XY3000S - XY3000D (->)"
            # Both XY3000S and XY3000D share the same price table under one Cod.
            if w["text"] == "Cod.":
                for offset in range(1, 8):
                    if i + offset >= len(line_words):
                        break
                    candidate = line_words[i + offset]
                    # Stop at the next column's Cod. token
                    if candidate["text"] == "Cod.":
                        break
                    cleaned = clean_token(candidate["text"]).upper()
                    if not cleaned:
                        continue  # pure bracket token, skip
                    if cleaned == code_upper:
                        # Use Cod.'s x0 — aligns with label rows below
                        return (w["x0"], w["top"], candidate["x1"], candidate["bottom"])
                    # Keep scanning — target might be the S or D variant further along

    return None


def find_all_code_positions(words):
    """
    Discover ALL module codes on the page with their positions.
    Used to determine the bottom boundary of each module's price table.
    Returns list of (code_text, x0, top, x1, bottom).
    """
    results = []
    seen = set()
    lines = group_words_by_line(words)

    for top_y, line_words in sorted(lines.items()):
        for i, w in enumerate(line_words):
            # Cod.-prefixed
            # Handles:
            #   "Cod. D2000"                        -> one code
            #   "Cod. (<-) XY3000S - XY3000D (->)" -> two codes, same price table
            # We collect ALL real code tokens until the next Cod. token,
            # all anchored to this Cod.'s x0 (column position).
            if w["text"] == "Cod.":
                for offset in range(1, 8):
                    if i + offset >= len(line_words):
                        break
                    candidate = line_words[i + offset]
                    # Stop if we've reached the next column's Cod. token
                    if candidate["text"] == "Cod.":
                        break
                    code = clean_token(candidate["text"]).upper()
                    if not code:
                        continue  # pure bracket token like (<-) (->) -, skip
                    if is_module_code(code) and code not in seen:
                        seen.add(code)
                        # Use Cod.'s x0 as column anchor
                        results.append((code, w["x0"], w["top"], candidate["x1"], candidate["bottom"]))
                    # Keep going to catch second variant in same bracket group
                continue

            # Standalone / bracket-wrapped (1–4 token combos)
            for length in range(1, 5):
                if i + length > len(line_words):
                    break
                chunk = line_words[i:i + length]
                joined = clean_token("".join(w2["text"] for w2 in chunk)).upper()
                if (is_module_code(joined)
                        and joined not in seen):
                    seen.add(joined)
                    results.append((joined,
                                    chunk[0]["x0"], chunk[0]["top"],
                                    chunk[-1]["x1"], chunk[-1]["bottom"]))
                    break

    return results


def find_next_code_y_in_column(all_codes, target_code, target_x0, target_top, page_height):
    col_tol = 65
    best_y = page_height
    for code, x0, top, x1, bottom in all_codes:
        if code == target_code.upper():
            continue
        if abs(x0 - target_x0) > col_tol:
            continue
        if top <= target_top + 3:
            continue
        if top < best_y:
            best_y = top
    return best_y


def find_label_rows(words, label_tokens, col_x0, col_top, col_bottom, col_x_right):
    X_TOL = 60
    results = []
    lines = group_words_by_line(words)
    for top_y, line_words in sorted(lines.items()):
        if top_y < col_top - 5:
            continue
        if top_y > col_bottom + 5:
            break
        n = len(label_tokens)
        for i in range(len(line_words) - n + 1):
            chunk = line_words[i:i + n]
            if all(chunk[j]["text"].lower() == label_tokens[j].lower() for j in range(n)):
                lx0 = chunk[0]["x0"]
                if lx0 < col_x0 - X_TOL:
                    continue
                if lx0 > col_x_right:
                    continue
                results.append((chunk[0]["top"], chunk[-1]["bottom"], chunk[-1]["x1"]))
    return results


def find_price_on_line(words, label_top, label_x1, col_x_right, y_tol=3.0):
    candidates = []
    for w in words:
        if abs(w["top"] - label_top) > y_tol:
            continue
        if w["x0"] <= label_x1:
            continue
        if PRICE_RE.match(w["text"]):
            candidates.append(w)
    if not candidates:
        return None
    candidates.sort(key=lambda w: w["x0"])
    return parse_price_str(candidates[0]["text"])


def extract_prices_from_page(page, module_code):
    """
    Given an already-opened pdfplumber page and a module code,
    extract the price dict {category_code: base_price} or {}.
    """
    words = page.extract_words(x_tolerance=5, y_tolerance=3)

    pos = find_code_position(words, module_code)
    if pos is None:
        return {}

    code_x0, code_top, code_x1, code_bottom = pos
    all_codes = find_all_code_positions(words)
    next_y = find_next_code_y_in_column(
        all_codes, module_code, code_x0, code_top, page.height)

    col_x_right = code_x0 + 170
    prices = {}
    for cat_code, label_tokens in ROW_LABEL_TOKENS:
        label_rows = find_label_rows(
            words, label_tokens,
            col_x0=code_x0, col_top=code_top,
            col_bottom=next_y, col_x_right=col_x_right)
        for (lbl_top, lbl_bottom, lbl_x1) in label_rows:
            price = find_price_on_line(words, lbl_top, lbl_x1, col_x_right)
            if price is not None and cat_code not in prices:
                prices[cat_code] = price
                break

    return prices

# ===========================================================================
# Main extraction — opens PDF ONCE, scans pages once, serves all modules
# ===========================================================================

def extract_all_modules(pdf_path, module_codes):
    """
    Open the PDF a single time and extract prices for all requested modules.
    Returns dict: {module_code: {category_code: base_price}}

    Strategy:
      1. Scan each page's flat text to build a quick index: {code -> page_number}
      2. For each module, go directly to its page and run the coordinate extraction.
    """
    code_upper_set = {c.upper() for c in module_codes}

    # Step 1: build index — one pass through the whole PDF
    code_to_page = {}  # {CODE_UPPER: page_index_0based}
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if len(code_to_page) == len(code_upper_set):
                break  # found all codes, stop early
            words = page.extract_words(x_tolerance=5, y_tolerance=3)
            page_text = " ".join(clean_token(w["text"]).upper() for w in words)
            for code in code_upper_set:
                if code not in code_to_page and code in page_text:
                    code_to_page[code] = page_idx

    # Step 2: extract prices — open PDF once more, jump to each relevant page
    results = {}
    unique_pages = sorted(set(code_to_page.values()))

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx in unique_pages:
            page = pdf.pages[page_idx]
            # Extract all modules that live on this page
            for code in module_codes:
                if code.upper() in code_to_page and code_to_page[code.upper()] == page_idx:
                    prices = extract_prices_from_page(page, code)
                    results[code] = prices

    return results

# ===========================================================================
# Price calculation
# ===========================================================================

def to_99(value):
    """Ceil to the current whole number and append .99.
    e.g. 523.81 → 523.99,  524.01 → 524.99"""
    return math.ceil(value - 0.99) + 0.99


def calculate_prices(base_price):
    list_price       = to_99(base_price * MULTIPLIER * DISCOUNT)
    compare_at_price = to_99(base_price * MULTIPLIER)
    return list_price, compare_at_price

# ===========================================================================
# Main
# ===========================================================================

def run(pdf_path, query):
    product_name, categories, modules = parse_query(query)

    print(f"\nProduct   : {product_name}")
    print(f"Modules   : {', '.join(modules)}")
    print(f"Categories: {', '.join(categories)}")
    print("-" * 62)

    if not modules:
        print("ERROR: No module codes provided in query.")
        sys.exit(1)

    # Extract all modules in one PDF pass
    all_prices = extract_all_modules(pdf_path, modules)

    totals = {cat: 0.0 for cat in categories}
    found_any = False

    for module in modules:
        prices = all_prices.get(module, {})

        if not prices:
            print(f"\n  Module: {module}  -- no prices found in PDF")
            continue

        found_any = True
        print(f"\n  Module: {module}")
        for cat in categories:
            base = prices.get(cat)
            label = CATEGORY_LABELS.get(cat, cat)
            if base is None:
                print(f"    {label:<20} {'N/A':>10}")
                continue
            list_price, compare_at = calculate_prices(base)
            totals[cat] += base
            print(f"    {label:<20}  EUR {base:>8.2f}  →  "
                  f"List: {list_price:>9.2f}  |  Compare: {compare_at:>9.2f}")

    if found_any and len(modules) > 1:
        print("\n" + "=" * 62)
        print(f"  TOTAL ({' + '.join(modules)})")
        print("=" * 62)
        for cat in categories:
            label = CATEGORY_LABELS.get(cat, cat)
            base = totals[cat]
            list_price, compare_at = calculate_prices(base)
            print(f"    {label:<20}  EUR {base:>8.2f}  →  "
                  f"List: {list_price:>9.2f}  |  Compare: {compare_at:>9.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])