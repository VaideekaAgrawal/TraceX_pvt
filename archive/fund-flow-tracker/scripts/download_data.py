"""
Download the IBM AML (Anti-Money Laundering) dataset from Kaggle.

Prerequisites:
    pip install kaggle
    Set KAGGLE_USERNAME and KAGGLE_KEY environment variables,
    or place kaggle.json in ~/.kaggle/

Dataset: IBM Transactions for Anti Money Laundering (AML)
License: CDLA Sharing 1.0
URL: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml
"""
import os
import sys
import zipfile

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DATASET = "ealtman2019/ibm-transactions-for-anti-money-laundering-aml"
TARGET_FILE = "HI-Small_Trans.csv"


def download_kaggle():
    """Download via Kaggle API."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        print("ERROR: kaggle package not installed. Run: pip install kaggle")
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    api = KaggleApi()
    api.authenticate()

    print(f"Downloading dataset: {DATASET}")
    print(f"Target directory: {DATA_DIR}")
    api.dataset_download_files(DATASET, path=DATA_DIR, unzip=True)

    target = os.path.join(DATA_DIR, TARGET_FILE)
    if os.path.exists(target):
        size_mb = os.path.getsize(target) / (1024 * 1024)
        print(f"\n✓ Downloaded: {TARGET_FILE} ({size_mb:.1f} MB)")
    else:
        # Some Kaggle datasets have nested directories
        for root, dirs, files in os.walk(DATA_DIR):
            for f in files:
                if f == TARGET_FILE:
                    src = os.path.join(root, f)
                    os.rename(src, target)
                    size_mb = os.path.getsize(target) / (1024 * 1024)
                    print(f"\n✓ Found and moved: {TARGET_FILE} ({size_mb:.1f} MB)")
                    return

        print(f"\n⚠ Downloaded files but {TARGET_FILE} not found.")
        print("Files in data directory:")
        for f in os.listdir(DATA_DIR):
            print(f"  {f}")


def main():
    target = os.path.join(DATA_DIR, TARGET_FILE)
    if os.path.exists(target):
        size_mb = os.path.getsize(target) / (1024 * 1024)
        print(f"Dataset already exists: {target} ({size_mb:.1f} MB)")
        print("Delete it and re-run to re-download.")
        return

    print("=" * 60)
    print("TraceX — IBM AML Dataset Downloader")
    print("=" * 60)
    print(f"\nDataset: {DATASET}")
    print(f"File: {TARGET_FILE} (~150 MB)")
    print(f"Records: ~5 million transactions, 5,100 labelled laundering")
    print(f"License: CDLA Sharing 1.0\n")

    download_kaggle()

    print("\n" + "=" * 60)
    print("Setup complete! Run the app with:")
    print("  streamlit run app_v3.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
