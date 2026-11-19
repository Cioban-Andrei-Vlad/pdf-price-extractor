# 📄 PDF Price Extractor

A Python command-line tool that reads furniture catalog price lists from PDF and works out selling prices. Give it a product, a few module codes and the fabric/leather categories you want, and it finds each module's price table in the PDF, reads the price for every category and applies your own pricing formula.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![pdfplumber](https://img.shields.io/badge/pdfplumber-FF6F00?style=for-the-badge&logo=adobeacrobatreader&logoColor=white)

---

## ✨ Features

### 🔍 Smart Module Detection
- Finds module codes in different catalog layouts: standalone (`ABCD2000`), bracket-wrapped (`(<-)ABCL2000S - ABCL2000D(->)`) and `Cod.`-prefixed (`Cod. D2000`)
- Tells real module codes apart from dimension strings and regular words
- Works out where each module's price table ends by finding the next code in the same column

### 💶 Price Extraction
- Reads the price for each category row (Categoria B, C, D, V, T, Extra, Pelle M, N, Tessuto Cliente)
- Handles European number formats like `1.318,00`
- Scans the PDF once to index which page each module is on, then only reads those pages

### 🧮 Configurable Pricing
- Calculates a **List Price** and a **Compare At Price** with your own formula
- Rounds prices to `.99`
- Adds up totals when you ask for several modules at once

---

## 📋 Prerequisites

- **Python 3.10+**

```bash
pip install -r requirements.txt
```

---

## ⚙️ Setting Your Formula

Open `extract_prices.py` and set the two values in the `CONFIG` section:

```python
# ADD YOUR FORMULA HERE
MULTIPLIER = 1.0   # everything applied to the catalog price, e.g. exchange rate * markup * VAT
DISCOUNT   = 1.0   # applied on top for the list price, e.g. 0.8 = 20% off
```

```
List Price       = base_price * MULTIPLIER * DISCOUNT
Compare At Price = base_price * MULTIPLIER
```

Both are rounded to `.99`. To change the formula itself, edit `calculate_prices()`.

---

## 🚀 Usage

```bash
python extract_prices.py <pdf_path> "<query>"
```

### Query format

```
ProductName, [CategoryCodes], ModuleCode1, ModuleCode2, ...
```

| Example | Meaning |
|---|---|
| `Product, B C D, ABC2000, ABC3000` | Two modules, categories B, C and D |
| `Product, ABC2000, ABC3000` | No categories given, so all of them are used |
| `Product, B M N, AB1CD2000` | One module, fabric B and leathers M and N |

Category codes: `B` `C` `D` `V` `T` `Extra` `M` `N` `TC`

### Example output

```
  Module: D2000
    Categoria B           EUR  1318.00  →  List:   1318.99  |  Compare:   1318.99
    Categoria C           EUR  1440.00  →  List:   1440.99  |  Compare:   1440.99
```

> 💡 On Windows, if you get a `UnicodeEncodeError` in the terminal, run `set PYTHONIOENCODING=utf-8` first. PyCharm's console works without it.

---

## 🛠️ Adapting to Another Catalog

Everything catalog-specific is at the top of `extract_prices.py`:
- `CATEGORY_LABELS` / `ROW_LABEL_TOKENS`: the category row names printed in the PDF
- `MODULE_RE` and `is_module_code()`: what a module code looks like
- `col_x_right` in `extract_prices_from_page()`: how wide a price column is

---

## 👤 Author

**Andrei-Vlad Cioban**
