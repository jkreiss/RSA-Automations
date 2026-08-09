import pandas as pd


REQUIRED_COLUMNS = [
    'Tags',
    'Cost Per Item',
    'Variant Price',
    'Variant Compare At Price',
    'Variant Sku',
    'Title',
    'Type',
    'Variant Inventory Qty'
]

class CSVLoadError(Exception):
    pass

def load_csv(filename):
    # Load
    try:
        df = pd.read_csv(filename)
    except FileNotFoundError:
        raise CSVLoadError(f"File {filename} not found")

    # CHeck cols
    df.columns = [str(col).title() for col in df.columns]
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise CSVLoadError(f"Missing required columns {missing_cols}")

    # Clean and normalize
    df['Cost Per Item'] = pd.to_numeric(df['Cost Per Item'], errors='coerce')
    df['Variant Price'] = pd.to_numeric(df['Variant Price'], errors='coerce')
    df['Variant Compare At Price'] = pd.to_numeric(df['Variant Compare At Price'], errors='coerce')
    df['Variant Inventory Qty'] = pd.to_numeric(df['Variant Inventory Qty'], errors='coerce')
    df.dropna(subset=['Cost Per Item', 'Variant Price', 'Variant Inventory Qty'], inplace=True)  # drop if not available
    df['Tags'] = df['Tags'].astype(str)
    df['Variant Sku'] = df['Variant Sku'].astype(str)

    return df.reset_index(drop=True)
